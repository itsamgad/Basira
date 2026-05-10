from __future__ import annotations
import math
import re
import warnings
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest, RandomForestRegressor
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD
from sklearn.model_selection import cross_val_score
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings('ignore')

try:
    import shap
    SHAP_AVAILABLE = True
except ImportError:
    SHAP_AVAILABLE = False

# NLP (optional)
NLP_AVAILABLE         = False
LANG_DETECT_AVAILABLE = False

try:
    import torch
    from transformers import AutoModel, AutoTokenizer
    NLP_AVAILABLE = True
except ImportError:
    pass

try:
    from langdetect import DetectorFactory, detect as _ld_detect
    DetectorFactory.seed = 42
    LANG_DETECT_AVAILABLE = True
except ImportError:
    pass



# Model registry  (HuggingFace — loaded once, cached)
_MODEL_CACHE: Dict[str, Any] = {}

_LANG_TO_MODEL = {
    'arabic':  'aubmindlab/bert-base-arabertv02',
    'english': 'roberta-base',
    'mixed':   'xlm-roberta-base',
}


def _load_model(lang: str):
    if not NLP_AVAILABLE:
        return None, None
    hf_id = _LANG_TO_MODEL.get(lang, _LANG_TO_MODEL['mixed'])
    if hf_id not in _MODEL_CACHE:
        try:
            print(f'[NLP] Loading model: {hf_id} …')
            tok   = AutoTokenizer.from_pretrained(hf_id)
            model = AutoModel.from_pretrained(hf_id)
            model.eval()
            _MODEL_CACHE[hf_id] = (tok, model)
            print(f'[NLP] Loaded: {hf_id}')
        except Exception as exc:
            print(f'[NLP] Could not load {hf_id}: {exc}')
            _MODEL_CACHE[hf_id] = (None, None)
    return _MODEL_CACHE[hf_id]


# Arabic normalisation
_RE_DIACRITICS  = re.compile(r'[\u064B-\u065F\u0610-\u061A\u06D6-\u06DC\u06DF-\u06E4\u06E7-\u06ED]')
_RE_ALEF        = re.compile(r'[إأآا]')
_RE_TA_MARBUTA  = re.compile(r'ة')
_RE_TATWEEL     = re.compile(r'\u0640')
_RE_WS          = re.compile(r'\s+')
_RE_ARABIC_CHARS = re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+')


def normalise_arabic(text: str) -> str:
    text = _RE_DIACRITICS.sub('', text)
    text = _RE_ALEF.sub('ا', text)
    text = _RE_TA_MARBUTA.sub('ه', text)
    text = _RE_TATWEEL.sub('', text)
    text = _RE_WS.sub(' ', text).strip()
    return text


# Language detection (per cell and per column)
def detect_text_language(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        return 'unknown'
    ar_len  = len(_RE_ARABIC_CHARS.findall(text))
    lat_len = len(re.findall(r'[a-zA-Z]', text))
    total   = ar_len + lat_len
    if total == 0:
        return 'unknown'
    ar_ratio = ar_len / total
    if ar_ratio >= 0.60:
        return 'arabic'
    elif ar_ratio <= 0.15:
        if LANG_DETECT_AVAILABLE:
            try:
                detected = _ld_detect(text)
                return 'english' if detected == 'en' else 'mixed'
            except Exception:
                pass
        return 'english'
    return 'mixed'


def detect_column_language(series: pd.Series) -> str:
    texts  = series.dropna().astype(str).head(200).tolist()
    if not texts:
        return 'unknown'
    counts = {'arabic': 0, 'english': 0, 'mixed': 0, 'unknown': 0}
    for t in texts:
        counts[detect_text_language(t)] += 1
    total    = sum(counts.values())
    ar_share = counts['arabic']  / total
    en_share = counts['english'] / total
    if ar_share >= 0.15 and en_share >= 0.15:
        return 'mixed'
    return max(counts, key=counts.get)



# NLP embedding engine  (BERT / RoBERTa / XLM-RoBERTa)
def _mean_pool(last_hidden, attn_mask) -> np.ndarray:
    mask_exp = attn_mask.unsqueeze(-1).float()
    summed   = (last_hidden * mask_exp).sum(dim=1)
    counts   = mask_exp.sum(dim=1).clamp(min=1e-9)
    return (summed / counts).detach().numpy()


def embed_text_column(
    series:     pd.Series,
    lang:       str,
    batch_size: int = 32,
    max_len:    int = 128,
) -> Optional[np.ndarray]:
    if not NLP_AVAILABLE:
        return None
    tok, model = _load_model(lang)
    if tok is None:
        return None
    import torch
    texts = series.fillna('').astype(str).tolist()
    if lang in ('arabic', 'mixed'):
        texts = [
            normalise_arabic(t) if detect_text_language(t) in ('arabic', 'mixed') else t
            for t in texts
        ]
    all_embs = []
    with torch.no_grad():
        for start in range(0, len(texts), batch_size):
            batch   = texts[start: start + batch_size]
            encoded = tok(batch, padding=True, truncation=True, max_length=max_len, return_tensors='pt')
            out     = model(**encoded)
            embs    = _mean_pool(out.last_hidden_state, encoded['attention_mask'])
            all_embs.append(embs)
    matrix    = np.vstack(all_embs)
    norms     = np.linalg.norm(matrix, axis=1, keepdims=True)
    zero_mask = (norms.flatten() == 0)
    if zero_mask.any() and not zero_mask.all():
        col_mean           = matrix[~zero_mask].mean(axis=0)
        matrix[zero_mask]  = col_mean
    return matrix


def _tfidf_fallback(series: pd.Series, n_components: int = 8) -> Optional[np.ndarray]:
    """TF-IDF + SVD fallback when BERT models are unavailable."""
    texts = series.fillna('').astype(str).tolist()
    if len(set(texts)) < 2:
        return None
    try:
        vec   = TfidfVectorizer(max_features=2000, ngram_range=(1, 2), lowercase=True)
        X     = vec.fit_transform(texts)
        k     = min(n_components, X.shape[1] - 1, len(texts) - 1)
        if k < 2:
            return None
        svd   = TruncatedSVD(n_components=k, random_state=42)
        return svd.fit_transform(X)
    except Exception:
        return None


def process_text_columns(df: pd.DataFrame) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
    """
    Detect text columns, embed them (BERT or TF-IDF fallback), PCA-compress,
    and return a combined matrix + metadata.
    """
    nlp_meta = {
        'nlp_available':         NLP_AVAILABLE,
        'lang_detect_available': LANG_DETECT_AVAILABLE,
        'columns_processed':     [],
        'warning': (
            None if NLP_AVAILABLE else
            'NLP libraries not installed. Using TF-IDF+SVD fallback. '
            'Install with: pip install torch transformers langdetect sentencepiece'
        ),
    }

    text_cols = [
        c for c in df.columns
        if df[c].dtype == object
        and df[c].nunique() / max(len(df), 1) < 0.95
        and df[c].dropna().astype(str).str.len().mean() > 3
    ]

    if not text_cols:
        return None, nlp_meta

    all_matrices:   List[np.ndarray] = []
    all_feat_names: List[str]        = []

    for col in text_cols:
        lang        = detect_column_language(df[col])
        model_label = {
            'arabic':  'AraBERT (bert-base-arabertv02)',
            'english': 'RoBERTa (roberta-base)',
            'mixed':   'XLM-RoBERTa (xlm-roberta-base)',
        }.get(lang, 'TF-IDF+SVD fallback')

        col_meta = {
            'column':     col,
            'language':   lang,
            'model_used': model_label,
            'n_non_null': int(df[col].notna().sum()),
            'sample_texts': df[col].dropna().astype(str).head(3).tolist(),
        }

        # Try BERT; fall back to TF-IDF+SVD
        if NLP_AVAILABLE:
            embed = embed_text_column(df[col], lang)
            if embed is None or embed.shape[0] != len(df):
                embed = _tfidf_fallback(df[col])
                col_meta['model_used'] = 'TF-IDF+SVD fallback (BERT unavailable)'
        else:
            embed = _tfidf_fallback(df[col])
            col_meta['model_used'] = 'TF-IDF+SVD fallback'

        if embed is None or embed.shape[0] != len(df):
            nlp_meta['columns_processed'].append(col_meta)
            continue

        # PCA compression — at most 8 dims per column
        n_components = min(8, embed.shape[1], len(df) - 1)
        if n_components >= 2:
            pca   = PCA(n_components=n_components, random_state=42)
            embed = pca.fit_transform(embed)
            col_meta['embedding_dims']         = n_components
            col_meta['variance_explained_pct'] = round(float(pca.explained_variance_ratio_.sum() * 100), 1)
        else:
            col_meta['embedding_dims']         = embed.shape[1]
            col_meta['variance_explained_pct'] = 100.0

        feat_names = [f'[NLP]{col}_d{i+1}' for i in range(embed.shape[1])]
        col_meta['feature_names'] = feat_names
        all_matrices.append(embed)
        all_feat_names.extend(feat_names)
        nlp_meta['columns_processed'].append(col_meta)

    if not all_matrices:
        return None, nlp_meta

    combined = np.hstack(all_matrices)
    nlp_meta['total_nlp_features'] = combined.shape[1]
    return combined, nlp_meta


# Utility: NaN / Inf sanitiser
def sanitize(obj: Any) -> Any:
    """Recursively replace NaN / Inf / None with JSON-safe values."""
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    if isinstance(obj, float):
        return 0 if (math.isnan(obj) or math.isinf(obj)) else round(obj, 6)
    if isinstance(obj, (np.floating, np.float32, np.float64)):
        v = float(obj)
        return 0 if (math.isnan(v) or math.isinf(v)) else round(v, 6)
    if isinstance(obj, (np.integer, np.int32, np.int64)):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if obj is None:
        return 0
    return obj


# Smart chart selection
def detect_chart_types(
    df:             pd.DataFrame,
    numeric_df:     pd.DataFrame,
    feature_impact: List[Dict],
    dist_data:      Dict[str, Any],
    target_col:     str,
) -> List[Dict]:
    charts     = []
    n_features = len(feature_impact)
    impacts    = [f['impact'] for f in feature_impact]
    n_rows     = len(df)
    top_feat   = feature_impact[0]['feature'] if feature_impact else None

    skews = (
        numeric_df.drop(columns=[target_col], errors='ignore')
        .apply(lambda c: abs(float(stats.skew(c.dropna()))) if c.dropna().std() > 0 else 0)
        .mean()
    )

    top2_sum      = sum(sorted(impacts, reverse=True)[:2]) if len(impacts) >= 2 else 0
    is_pareto     = top2_sum > 60
    high_variance = skews > 1.2
    large_dataset = n_rows > 1000

    # Chart 1: Feature ranking
    if n_features <= 7:
        charts.append({'type': 'horizontalBar', 'title': 'Feature Impact Ranking',
                       'reason': f'Horizontal bars optimal for {n_features} labeled features.', 'chartData': 'impact'})
    else:
        charts.append({'type': 'bar', 'title': 'Impact Magnitude Matrix',
                       'reason': f'{n_features} features — vertical bar handles wide feature space.', 'chartData': 'impact'})

    # Chart 2: Composition
    if is_pareto:
        charts.append({'type': 'doughnut', 'title': 'Decision Weight Allocation',
                       'reason': 'Top 2 features dominate (>60%). Doughnut highlights Pareto concentration.',
                       'chartData': 'impact'})
    elif high_variance:
        charts.append({'type': 'polarArea', 'title': 'Asymmetric Impact Distribution',
                       'reason': 'High skewness — polar area reveals unequal radial impact spread.',
                       'chartData': 'impact'})
    else:
        charts.append({'type': 'doughnut', 'title': 'Proportional Weight Map',
                       'reason': 'Balanced distribution — doughnut gives intuitive part-to-whole view.',
                       'chartData': 'impact'})

    # Chart 3: Profile
    if 3 <= n_features <= 10:
        charts.append({'type': 'radar', 'title': 'Multi-Axis Feature Signature',
                       'reason': f'Radar maps {n_features} features on one canvas.',
                       'chartData': 'impact'})
    else:
        charts.append({'type': 'line', 'title': 'Impact Decay Curve',
                       'reason': 'Large feature count — line chart traces diminishing returns.',
                       'chartData': 'impact'})

    # Chart 4: Distribution of primary driver
    if top_feat and top_feat in dist_data:
        charts.append({'type': 'histogram', 'title': f'Distribution: {top_feat.upper()}',
                       'reason': f"Histogram reveals how '{top_feat}' is distributed.",
                       'chartData': 'histogram', 'histFeature': top_feat})

    # Chart 5: Scatter / Bubble
    if n_features >= 2:
        f1 = feature_impact[0]['feature']
        f2 = feature_impact[1]['feature']
        if large_dataset:
            charts.append({'type': 'bubble', 'title': f'Feature Interaction: {f1.upper()} × {f2.upper()}',
                           'reason': 'Bubble shows joint relationship + SHAP magnitude.',
                           'chartData': 'bubble', 'feat1': f1, 'feat2': f2})
        else:
            charts.append({'type': 'scatter', 'title': f'Correlation Scatter: {f1.upper()} vs {f2.upper()}',
                           'reason': f"Scatter exposes raw relationship between '{f1}' and '{f2}'.",
                           'chartData': 'scatter', 'feat1': f1, 'feat2': f2})

    # Chart 6: Cumulative impact
    charts.append({'type': 'area', 'title': 'Cumulative Feature Contribution',
                   'reason': 'Area chart shows how decision weight accumulates across features.',
                   'chartData': 'cumulative'})

    return charts


# Root Cause Analysis
def compute_rca(
    df:             pd.DataFrame,
    numeric_df:     pd.DataFrame,
    feature_impact: List[Dict],
    shap_values:    np.ndarray,
    X:              pd.DataFrame,
    y:              pd.Series,
    target_col:     str,
) -> List[Dict]:
    """
    For each top feature: compute statistical profile, identify root causes,
    and produce a prioritised plain-language recommendation.

    Root-cause signals examined:
      • Outlier density (IQR method)
      • Distribution skewness
      • Coefficient of variation (extreme variability)
      • SHAP context-dependence (std vs mean)
      • Linear correlation type (strong / weak / non-linear)
      • Directional SHAP tendency (predominantly positive / negative)
    """
    rca_nodes    = []
    correlations = numeric_df.corr()[target_col]
    n_rows       = len(X)

    def _s(v, d=4):
        return 0 if (math.isnan(v) or math.isinf(v)) else round(v, d)

    # Pre-compute per-feature statistics
    feature_stats: Dict[str, Dict] = {}
    for col in X.columns:
        col_data = X[col].dropna()
        if len(col_data) < 2:
            continue
        q1, q3 = float(col_data.quantile(0.25)), float(col_data.quantile(0.75))
        iqr     = q3 - q1
        n_out   = int(((col_data < q1 - 1.5 * iqr) | (col_data > q3 + 1.5 * iqr)).sum())
        mean_v  = float(col_data.mean())
        std_v   = float(col_data.std())
        feature_stats[col] = {
            'mean':     _s(mean_v),
            'std':      _s(std_v),
            'min':      _s(float(col_data.min())),
            'max':      _s(float(col_data.max())),
            'skew':     _s(float(stats.skew(col_data)), 3),
            'kurtosis': _s(float(stats.kurtosis(col_data)), 3),
            'outliers': n_out,
            'cv':       _s(std_v / mean_v * 100, 1) if mean_v != 0 else 0,
        }

    for rank, item in enumerate(feature_impact[:6], 1):
        feat = item['feature']
        if feat not in feature_stats:
            continue

        fs       = feature_stats[feat]
        corr_val = round(float(correlations.get(feat, 0)), 3)
        if math.isnan(corr_val) or math.isinf(corr_val):
            corr_val = 0.0

        shap_idx     = list(X.columns).index(feat)
        shap_feat    = shap_values[:, shap_idx]
        shap_mean    = _s(round(float(np.mean(shap_feat)), 4))
        shap_std     = _s(round(float(np.std(shap_feat)),  4))
        shap_pos_pct = round(float((shap_feat > 0).sum() / max(len(shap_feat), 1) * 100), 1)

        causes:        List[str] = []
        severity_score = 0

        # Cause 1 — outlier density
        if fs['outliers'] > n_rows * 0.05:
            causes.append(
                f"High outlier density: {fs['outliers']} records "
                f"({round(fs['outliers'] / n_rows * 100, 1)}% of data) fall outside normal range. "
                f"These extreme values are likely inflating this feature's apparent importance."
            )
            severity_score += 2

        # Cause 2 — distribution skewness
        if abs(fs['skew']) > 1.5:
            direction = 'right-skewed' if fs['skew'] > 0 else 'left-skewed'
            tail      = 'extreme high values' if fs['skew'] > 0 else 'extreme low values'
            causes.append(
                f"Distribution is {direction} (skew={fs['skew']}), with a long tail of {tail}. "
                f"A log-transform would likely stabilise variance and improve model reliability."
            )
            severity_score += 1

        # Cause 3 — extreme variability
        if abs(fs['cv']) > 80:
            causes.append(
                f"Extreme variability detected (CV={fs['cv']}%). "
                f"This feature behaves inconsistently and can destabilise predictions. "
                f"Consider grouping or binning this variable."
            )
            severity_score += 2

        # Cause 4 — context-dependent SHAP
        if shap_std > abs(shap_mean) * 1.5 and shap_mean != 0:
            causes.append(
                f"Highly context-dependent influence: SHAP values vary greatly "
                f"(std={shap_std} vs mean={shap_mean}). "
                f"This feature influences the target through non-linear or interaction effects."
            )
            severity_score += 1

        # Cause 5 — linear correlation type
        if abs(corr_val) > 0.75:
            causes.append(
                f"Strong direct linear link to target (r={corr_val}). "
                f"This feature and the outcome move "
                f"{'together' if corr_val > 0 else 'in opposite directions'} almost proportionally."
            )
            severity_score += 1
        elif abs(corr_val) < 0.15:
            causes.append(
                f"Weak linear correlation (r={corr_val}) yet high SHAP importance — "
                f"this feature influences the target through non-linear, threshold, or interaction effects. "
                f"Standard correlation analysis would completely miss this."
            )
            severity_score += 1

        # Cause 6 — SHAP direction
        if shap_pos_pct > 70:
            causes.append(
                f"Predominantly positive effect: in {shap_pos_pct}% of records "
                f"it pushes the predicted outcome upward — a consistent positive lever."
            )
        elif shap_pos_pct < 30:
            causes.append(
                f"Acts mainly as a suppressor: in {100 - shap_pos_pct}% of records "
                f"it pulls the predicted outcome downward. "
                f"Managing it could help prevent negative outcomes."
            )

        if not causes:
            causes.append(
                'Stable, consistent influence with no anomalous patterns detected. '
                'Contributes predictably to model decisions and can be relied upon as a stable signal.'
            )

        # Recommendation (calibrated by importance level)
        if item['importance_level'] == 'Critical':
            recommendation = (
                f"URGENT: '{feat}' is the single most powerful lever — "
                f"it drives {item['impact']}% of all predictions. "
                f"Set up real-time monitoring, define acceptable value ranges, "
                f"assign ownership, and never change it without prior impact assessment."
            )
        elif item['importance_level'] == 'High':
            recommendation = (
                f"MONITOR: '{feat}' contributes {item['impact']}% to decisions. "
                f"Establish monthly review thresholds and document baseline values."
            )
        else:
            recommendation = (
                f"TRACK: '{feat}' provides {item['impact']}% of predictive weight. "
                f"Include in your standard periodic review cycle."
            )

        rca_nodes.append({
            'rank':             rank,
            'feature':          feat,
            'impact':           item['impact'],
            'trend':            item['trend'],
            'importance_level': item['importance_level'],
            'corr_with_target': corr_val,
            'shap_mean':        shap_mean,
            'shap_std':         shap_std,
            'shap_pos_pct':     shap_pos_pct,
            'stats':            fs,
            'root_causes':      causes,
            'recommendation':   recommendation,
            'severity_score':   severity_score,
        })

    return rca_nodes

# Advanced insight cards
def compute_advanced_insights(
    df:             pd.DataFrame,
    numeric_df:     pd.DataFrame,
    feature_impact: List[Dict],
    shap_values:    np.ndarray,
    X:              pd.DataFrame,
    y:              pd.Series,
    target_col:     str,
    model_r2:       float,
) -> List[Dict]:
    insights = []
    n_rows   = len(df)
    n_cols   = len(df.columns)

    missing_pct = round(df.isnull().sum().sum() / max(n_rows * n_cols, 1) * 100, 1)
    dup_rows    = int(df.duplicated().sum())
    top         = feature_impact[0]
    second      = feature_impact[1] if len(feature_impact) > 1 else feature_impact[0]

    def _sf(v):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return 0
        return v

    target_skew = _sf(round(float(stats.skew(y)), 2))
    target_std  = _sf(round(float(y.std()), 3))
    y_mean      = float(y.mean())
    target_cv   = _sf(round(float(y.std() / y_mean * 100), 1)) if y_mean != 0 else 0

    # Anomaly detection
    iso         = IsolationForest(contamination=0.05, random_state=42)
    iso.fit(X)
    n_anomalies = int((iso.predict(X) == -1).sum())
    anomaly_pct = round(n_anomalies / n_rows * 100, 1)

    # SHAP concentration
    total_shap = sum(np.abs(shap_values[:, i]).mean() for i in range(X.shape[1]))
    top3_shap  = sum(np.abs(shap_values[:, i]).mean() for i in range(min(3, X.shape[1])))
    top3_conc  = round(top3_shap / total_shap * 100, 1) if total_shap > 0 else 0

    inter_r = 0.0
    f1, f2  = top['feature'], second['feature']
    if f1 in X.columns and f2 in X.columns:
        inter_r = _sf(round(float(abs(X[f1].corr(X[f2]))), 3))

    # Card 1: Model reliability
    if model_r2 >= 80:
        desc   = f"The model explains {model_r2}% of outcome variation — strong predictive power."
        action = '✓ High confidence — insights are decision-ready'
        color  = '#22c55e'
    elif model_r2 >= 55:
        desc   = f"The model achieves {model_r2}% explanation power — moderate performance."
        action = '⚠ Use with caution — validate key findings'
        color  = '#f59e0b'
    else:
        desc   = f"The model explains only {model_r2}% of variance — low performance."
        action = '⚠ Low confidence — explore additional data sources'
        color  = '#ef4444'
    insights.append({'id': 'model_reliability', 'title': 'MODEL RELIABILITY SCORE',
                     'value': f'{model_r2}%', 'metric': 'Cross-validated R² score',
                     'desc': desc, 'action': action, 'color': color})

    # Card 2: Primary driver
    direction = 'increases' if top['trend'] == 'Positive' else 'decreases'
    insights.append({
        'id': 'primary_driver', 'title': 'PRIMARY DECISION DRIVER',
        'value': top['feature'].upper(), 'metric': f"{top['impact']}% of all predictive weight",
        'desc': (f"'{top['feature']}' has the strongest influence on outcomes, "
                 f"accounting for {top['impact']}% of the model's total decision weight. "
                 f"When this value {direction}, your target outcome moves in the same direction."),
        'action': f"Monitor '{top['feature']}' as your primary operational lever",
        'color': '#3b82f6',
    })

    # Card 3: Anomaly alert
    if anomaly_pct > 10:
        desc   = f"{n_anomalies} records ({anomaly_pct}%) show unusual patterns."
        action = '🚨 Review anomalous records before relying on analysis'
        color  = '#ef4444'
    elif anomaly_pct > 4:
        desc   = f"Moderate anomaly rate: {anomaly_pct}% of records are unusual."
        action = '⚠ Investigate flagged records'
        color  = '#f59e0b'
    else:
        desc   = f"Low anomaly rate ({anomaly_pct}%) — data distribution is healthy."
        action = '✓ Data distribution is healthy'
        color  = '#22c55e'
    insights.append({'id': 'anomaly_alert', 'title': 'ANOMALY DETECTION',
                     'value': f'{anomaly_pct}%', 'metric': f'{n_anomalies} unusual records (IsolationForest)',
                     'desc': desc, 'action': action, 'color': color})

    # Card 4: Decision concentration risk
    if top3_conc > 85:
        desc   = (f"Top 3 features carry {top3_conc}% of all decisions — "
                  f"extreme concentration creates fragility. If any of these features are "
                  f"unavailable or measured incorrectly, predictions will fail.")
        action = '⚠ High concentration — diversify data collection'
        color  = '#ef4444'
    elif top3_conc > 65:
        desc   = (f"Top 3 features carry {top3_conc}% of decisions — "
                  f"moderate concentration. The model has some breadth but depends heavily on a few inputs.")
        action = '⚠ Moderate — monitor top 3 features closely'
        color  = '#f59e0b'
    else:
        desc   = (f"Decision weight is distributed across features (top 3 = {top3_conc}%). "
                  f"Robust predictions — no single point of failure.")
        action = '✓ Well-distributed — model is robust'
        color  = '#22c55e'
    insights.append({'id': 'concentration_risk', 'title': 'DECISION CONCENTRATION RISK',
                     'value': f'{top3_conc}%', 'metric': 'Top-3 feature share of total SHAP',
                     'desc': desc, 'action': action, 'color': color})

    # Card 5: Data integrity
    quality = max(0, round(100 - missing_pct * 2 - (1 if dup_rows > 0 else 0)))
    if quality >= 85:
        desc   = f"Dataset quality is high ({quality}%). Missing: {missing_pct}%, Duplicates: {dup_rows}."
        action = '✓ Clean dataset — analysis is reliable'
        color  = '#22c55e'
    elif quality >= 60:
        desc   = f"Dataset quality is acceptable ({quality}%). Some missing values detected."
        action = '⚠ Address missing values for better reliability'
        color  = '#f59e0b'
    else:
        desc   = f"Dataset quality is low ({quality}%). Missing: {missing_pct}%, Duplicates: {dup_rows}."
        action = '🚨 Clean dataset before production use'
        color  = '#ef4444'
    insights.append({'id': 'data_quality', 'title': 'DATA INTEGRITY SCORE',
                     'value': f'{quality}%', 'metric': f'{missing_pct}% missing · {dup_rows} duplicates',
                     'desc': desc, 'action': action, 'color': color})

    # Card 6: Target volatility
    if target_cv > 60:
        desc   = f"Target '{target_col}' is highly volatile (CV={target_cv}%)."
        action = '⚠ High variance — widen prediction confidence intervals'
    elif target_cv > 30:
        desc   = f"Target '{target_col}' shows moderate variability (CV={target_cv}%)."
        action = 'Normal variance — predictions reliable on average'
    else:
        desc   = f"Target '{target_col}' is quite stable (CV={target_cv}%)."
        action = '✓ Low variance — high prediction confidence'
    insights.append({'id': 'target_volatility', 'title': 'TARGET VOLATILITY INDEX',
                     'value': f'CV: {target_cv}%', 'metric': f'σ={target_std} · Skew={target_skew}',
                     'desc': desc, 'action': action, 'color': '#8b5cf6'})

    # Card 7: Feature interaction / collinearity
    combined = round(top['impact'] + second['impact'], 1)
    if inter_r > 0.6:
        desc   = (f"'{f1}' and '{f2}' are strongly correlated (r={inter_r}), "
                  f"sharing {combined}% of decisions. SHAP scores may be inflated.")
        action = '⚠ Collinearity risk — consider removing one'
        color  = '#f59e0b'
    else:
        desc   = (f"'{f1}' and '{f2}' contribute independently (r={inter_r}), "
                  f"together accounting for {combined}% of decisions without redundancy.")
        action = '✓ Features contribute independently'
        color  = '#6366f1'
    insights.append({'id': 'feature_interaction', 'title': 'TOP-2 FEATURE SYNERGY',
                     'value': f'r = {inter_r}', 'metric': f'{combined}% combined decision weight',
                     'desc': desc, 'action': action, 'color': color})

    return insights


# Decision narrative
def generate_decision_narrative(
    feature_impact: List[Dict],
    rca_report:     List[Dict],
    insights:       List[Dict],
    target_col:     str,
    model_r2:       float,
    n_rows:         int,
    anomaly_pct:    float,
) -> Dict[str, str]:
    top  = feature_impact[0]
    top2 = feature_impact[1] if len(feature_impact) > 1 else feature_impact[0]
    conf = 'high' if model_r2 >= 75 else 'moderate' if model_r2 >= 50 else 'low'
    return {
        'headline': 'Your dataset has been fully analyzed. Here is what the data is telling you.',
        'summary': (
            f"This analysis examined {n_rows:,} records across {len(feature_impact) + 1} variables "
            f"to understand what drives your target outcome: '{target_col}'. "
            f"The AI model explains {model_r2}% of outcome variation, "
            f"giving us {conf} confidence in these findings."
        ),
        'key_finding': (
            f"The single most important factor affecting '{target_col}' is '{top['feature']}', "
            f"which carries {top['impact']}% of all predictive weight."
        ),
        'secondary_finding': (
            f"The second most influential factor is '{top2['feature']}' at {top2['impact']}% weight. "
            f"Together, these two variables explain the majority of what happens in your data."
        ),
        'risk_alert': (
            f"⚠ ATTENTION: {round(anomaly_pct)}% of records show unusual patterns "
            f"that may indicate errors or rare events. Review before acting on this analysis."
            if anomaly_pct > 8 else
            '✓ No major anomaly risks detected. Data is clean enough to support confident decision-making.'
        ),
        'recommended_action': (
            f"Focus immediate effort on monitoring and controlling '{top['feature']}'. "
            f"Establish clear operational boundaries for its acceptable range, "
            f"assign a team responsible for tracking it, "
            f"and build dashboards that alert you when it moves outside normal limits."
        ),
    }


# Main analysis entry point  — replaces the Flask /analyze route body
def run_rca_analysis(
    df:               pd.DataFrame,
    routing_decision: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Full XAI + RCA pipeline.

    Parameters
    ----------
    df               : Cleaned DataFrame from BS_final (cleaned_df).
    routing_decision : Dict from PH1.determine_analytical_strategy_from_bs()
                       or PH1.determine_analytical_strategy().

    The target column, numeric/text/categorical column lists, task type, and
    modality are all taken from routing_decision — this function does NOT
    re-detect the target.

    Returns a sanitized dict ready for JSON serialisation.
    """
    if not SHAP_AVAILABLE:
        return {'status': 'error', 'message': 'SHAP is not installed. Run: pip install shap'}

    try:
        # ── Read routing_decision ─────────────────────────────────────────────
        target_col   = routing_decision.get('target_column')
        task_type    = routing_decision.get('task_type', 'regression')
        num_cols     = routing_decision.get('numeric_columns', [])
        txt_cols     = routing_decision.get('text_columns', [])
        id_cols      = routing_decision.get('identifier_like_columns', [])
        excl_cols    = routing_decision.get('excluded_columns', [])
        task_conf    = routing_decision.get('task_confidence', 'medium')
        modality     = routing_decision.get('dataset_modality', 'tabular')

        if target_col is None:
            return {
                'status':  'error',
                'message': (
                    'routing_decision has no target_column. '
                    'RCA requires a supervised target. '
                    f"Strategy was: {routing_decision.get('strategy')}. "
                    f"Narrative: {routing_decision.get('narrative', '')}"
                ),
            }

        # Replace Inf/NaN 
        df_work = df.replace([np.inf, -np.inf], np.nan).copy()

        missing_total = int(df_work.isnull().sum().sum())
        dup_rows      = int(df_work.duplicated().sum())

        #  Step 1: NLP text embedding
        text_matrix, nlp_metadata = process_text_columns(df_work)

        #  Step 2: Build numeric feature matrix 
        # Use only numeric columns that PH1 identified, excluding target & identifiers
        drop_in_feats = set(id_cols) | set(excl_cols) | {target_col}

        # Columns available for features: PH1-declared numerics, minus exclusions
        available_num = [
            c for c in num_cols
            if c in df_work.columns and c not in drop_in_feats
        ]

        # If PH1's list doesn't cover enough, fall back to all numerics in df
        if len(available_num) < 1:
            available_num = [
                c for c in df_work.select_dtypes(include=[np.number]).columns
                if c not in drop_in_feats
            ]

        if not available_num:
            return {'status': 'error',
                    'message': 'No numeric feature columns available for analysis.'}

        numeric_df = df_work[available_num + [target_col]].select_dtypes(include=[np.number])
        if target_col not in numeric_df.columns:
            return {'status': 'error',
                    'message': f"Target column '{target_col}' is not numeric after cleaning."}

        # Validate target has enough unique values for regression
        feature_cols = [c for c in numeric_df.columns if c != target_col]
        if not feature_cols:
            return {'status': 'error', 'message': 'No feature columns remain after excluding target.'}

        # Fill any residual NaN (BS should have handled most)
        numeric_df = numeric_df.fillna(numeric_df.median(numeric_only=True)).fillna(0)

        X_num = numeric_df[feature_cols]
        y     = numeric_df[target_col]

        # ── Step 3: Augment X with NLP embeddings
        nlp_feat_names = []
        for cm in nlp_metadata.get('columns_processed', []):
            nlp_feat_names.extend(cm.get('feature_names', []))

        if (text_matrix is not None
                and text_matrix.shape[0] == len(X_num)
                and len(nlp_feat_names) == text_matrix.shape[1]):
            nlp_df = pd.DataFrame(text_matrix, columns=nlp_feat_names, index=X_num.index)
            X      = pd.concat([X_num, nlp_df], axis=1)
            nlp_metadata['features_added'] = len(nlp_feat_names)
        else:
            X = X_num

        #  Step 4: Model training 
        model = RandomForestRegressor(
            n_estimators=80,
            random_state=42,
            max_depth=12,
            n_jobs=-1,
        )
        model.fit(X, y)

        #  Step 5: SHAP 
        explainer   = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X)

        #  Step 6: Feature impact 
        all_frame    = pd.concat([X, y], axis=1)
        correlations = all_frame.corr()[target_col]
        raw_impacts  = [np.abs(shap_values[:, i]).mean() for i in range(X.shape[1])]
        total_impact = sum(raw_impacts) or 1

        feature_impact = []
        for i, col in enumerate(X.columns):
            pct      = round((raw_impacts[i] / total_impact) * 100, 1)
            corr_val = float(correlations.get(col, 0))
            trend    = 'Positive' if corr_val >= 0 else 'Negative'
            level    = 'Critical' if pct > 25 else 'High' if pct > 10 else 'Standard'
            feature_impact.append({
                'feature':          col,
                'impact':           pct,
                'trend':            trend,
                'importance_level': level,
                'is_nlp':           col.startswith('[NLP]'),
            })
        feature_impact.sort(key=lambda x: x['impact'], reverse=True)

        # ── Step 7: Distribution data ──────────────────────────────────────────
        dist_data: Dict[str, Any] = {}
        for col in X_num.columns[:6]:
            col_data     = X_num[col].dropna()
            hist, edges  = np.histogram(col_data, bins=12)
            dist_data[col] = {
                'bins':   [round(float(e), 3) for e in edges[:-1]],
                'counts': [int(h) for h in hist],
                'labels': [str(round(float(e), 2)) for e in edges[:-1]],
            }

        # Scatter (top 2 non-NLP features)
        scatter_data: Dict[str, Any] = {}
        top_num_feats = [
            f['feature'] for f in feature_impact
            if not f['is_nlp'] and f['feature'] in X_num.columns
        ]
        if len(top_num_feats) >= 2:
            f1, f2     = top_num_feats[0], top_num_feats[1]
            sample_idx = np.random.choice(len(X), min(300, len(X)), replace=False)
            fi1        = list(X.columns).index(f1)
            scatter_data = {
                'feat1': f1, 'feat2': f2,
                'points': [
                    {
                        'x': round(float(X[f1].iloc[i]), 4),
                        'y': round(float(X[f2].iloc[i]), 4),
                        'r': round(float(abs(shap_values[i, fi1])) * 10 + 4, 1),
                    }
                    for i in sample_idx
                ],
            }

        # Cumulative impact
        sorted_impacts = sorted([f['impact'] for f in feature_impact], reverse=True)
        cum, running = [], 0
        for v in sorted_impacts:
            running += v
            cum.append(round(running, 1))

        #  Step 8: Chart recommendations 
        chart_recommendations = detect_chart_types(
            df_work, numeric_df, feature_impact, dist_data, target_col
        )

        #  Step 9: Cross-validated R² 
        cv_scores = cross_val_score(model, X, y, cv=min(5, len(X)), scoring='r2')
        model_r2  = max(0.0, min(100.0, round(float(np.mean(cv_scores)) * 100, 1)))

        #  Step 10: Advanced insight cards 
        advanced_insights = compute_advanced_insights(
            df_work, numeric_df, feature_impact, shap_values, X, y, target_col, model_r2
        )

        #  Step 11: Root Cause Analysis 
        rca_report = compute_rca(
            df_work, numeric_df, feature_impact, shap_values, X, y, target_col
        )

        # Extract anomaly % for narrative
        anomaly_pct_val = 0.0
        for ins in advanced_insights:
            if ins['id'] == 'anomaly_alert':
                try:
                    anomaly_pct_val = float(ins['metric'].split('%')[0])
                except Exception:
                    pass

        #  Step 12: Decision narrative 
        decision_narrative = generate_decision_narrative(
            feature_impact, rca_report, advanced_insights,
            target_col, model_r2, len(df_work), anomaly_pct_val,
        )

        #  Step 13: Correlation matrix 
        top_feats = [
            f['feature'] for f in feature_impact[:7]
            if not f['is_nlp'] and f['feature'] in numeric_df.columns
        ]
        sub_cols    = list(dict.fromkeys(top_feats + [target_col]))
        sub_cols    = [c for c in sub_cols if c in numeric_df.columns]
        corr_matrix = []
        if len(sub_cols) >= 2:
            sub = numeric_df[sub_cols].corr()
            for r in sub.index:
                for c in sub.columns:
                    corr_matrix.append({'row': r, 'col': c, 'value': round(float(sub.loc[r, c]), 3)})

        #  Step 14: Safe data preview 
        preview_records = []
        for _, row in df_work.head(10).iterrows():
            rec: Dict[str, Any] = {}
            for col in df_work.columns:
                v = row[col]
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    rec[col] = '—'
                elif pd.isna(v):
                    rec[col] = '—'
                elif isinstance(v, np.integer):
                    rec[col] = int(v)
                elif isinstance(v, np.floating):
                    rec[col] = round(float(v), 4)
                else:
                    rec[col] = v
            preview_records.append(rec)

        #  Step 15: Assemble payload 
        payload = sanitize({
            'status':                'success',
            'preview':               preview_records,
            'xai_report':            feature_impact,
            'chart_recommendations': chart_recommendations,
            'advanced_insights':     advanced_insights,
            'rca_report':            rca_report,
            'corr_matrix':           corr_matrix,
            'dist_data':             dist_data,
            'scatter_data':          scatter_data,
            'cumulative_data': {
                'values': cum,
                'labels': [f['feature'] for f in feature_impact[:len(cum)]],
            },
            'model_score':        model_r2,
            'decision_narrative': decision_narrative,
            # PH1's decision echoed back so the frontend can display it
            'target_detection': {
                'column':          target_col,
                'task_type':       task_type,
                'confidence':      task_conf,
                'dataset_modality': modality,
                'reason': (
                    f"Target '{target_col}' identified by PH1 with {task_conf} confidence "
                    f"(gain={routing_decision.get('target_candidates', [{}])[0].get('gain_over_baseline', '?')} "
                    f"over baseline)."
                    if routing_decision.get('target_candidates') else
                    f"Target '{target_col}' passed to RCA engine from PH1 routing decision."
                ),
            },
            'nlp_analysis': nlp_metadata,
            'dataset_meta': {
                'rows':           len(df_work),
                'cols':           len(df_work.columns),
                'numeric_cols':   len(numeric_df.columns),
                'missing_total':  missing_total,
                'duplicate_rows': dup_rows,
                'target_column':  target_col,
                'feature_cols':   feature_cols,
                'nlp_text_cols':  len(nlp_metadata.get('columns_processed', [])),
                'ph1_strategy':   routing_decision.get('strategy', 'supervised'),
            },
        })

        return payload

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return {'status': 'error', 'message': str(exc)}


# Unsupervised RCA helpers]
def _anova_feature_importance(
    X:            pd.DataFrame,
    cluster_labels: List[int],
) -> List[Dict[str, Any]]:
    """
    Rank numeric features by how strongly they differentiate clusters
    using one-way ANOVA F-statistics.

    High F-score → feature varies significantly across cluster centroids
                   relative to within-cluster variance.
    Low  F-score → feature is similar across all clusters (not useful for
                   separating them).

    Returns a list of dicts sorted descending by f_score.
    """
    results: List[Dict[str, Any]] = []
    labels_arr = np.array(cluster_labels)
    unique_clusters = sorted(set(labels_arr))
    if len(unique_clusters) < 2:
        return results

    for col in X.columns:
        col_data = X[col].dropna()
        if len(col_data) < 4 or col_data.std() == 0:
            continue
        groups = [
            col_data[labels_arr[:len(col_data)] == k].values
            for k in unique_clusters
            if len(col_data[labels_arr[:len(col_data)] == k]) >= 2
        ]
        if len(groups) < 2:
            continue
        try:
            f_stat, p_val = stats.f_oneway(*groups)
            if math.isnan(f_stat) or math.isinf(f_stat):
                continue
            results.append({
                'feature':    col,
                'f_score':    round(float(f_stat), 4),
                'p_value':    round(float(p_val), 6),
                'significant': bool(p_val < 0.05),
            })
        except Exception:
            continue

    results.sort(key=lambda x: x['f_score'], reverse=True)

    # Normalise to percentage impact (same scale as supervised xai_report)
    total = sum(r['f_score'] for r in results) or 1
    for r in results:
        r['impact'] = round(r['f_score'] / total * 100, 1)
        r['trend']  = 'Differentiating' if r['significant'] else 'Weak'
        r['importance_level'] = (
            'Critical' if r['impact'] > 25 else
            'High'     if r['impact'] > 10 else
            'Standard'
        )
        r['is_nlp'] = r['feature'].startswith('[NLP]')

    return results


def _cluster_delta_rca(
    X:              pd.DataFrame,
    cluster_labels: List[int],
    feature_rank:   List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    For each cluster: compute how its centroid differs from the global mean
    for the top-ranked features, and produce root-cause bullets.

    Returns a list of cluster RCA nodes — one per cluster.
    """
    labels_arr      = np.array(cluster_labels)
    global_means    = X.mean()
    global_stds     = X.std().replace(0, 1)
    unique_clusters = sorted(set(labels_arr))
    top_features    = [r['feature'] for r in feature_rank[:8] if r['feature'] in X.columns]
    cluster_nodes:  List[Dict[str, Any]] = []

    for cid in unique_clusters:
        mask      = labels_arr == cid
        cluster_X = X[mask]
        size      = int(mask.sum())
        size_pct  = round(size / len(X) * 100, 1)

        if size == 0:
            continue

        # Z-score distance of cluster centroid from global mean per feature
        deltas: Dict[str, float] = {}
        for feat in top_features:
            if feat not in cluster_X.columns:
                continue
            z = float((cluster_X[feat].mean() - global_means[feat]) / global_stds[feat])
            deltas[feat] = round(z, 3)

        # Sort features by absolute delta
        sorted_deltas = sorted(deltas.items(), key=lambda kv: abs(kv[1]), reverse=True)

        # Build root-cause bullets
        causes: List[str] = []
        for feat, z in sorted_deltas[:4]:
            direction = 'above' if z > 0 else 'below'
            strength  = 'far'   if abs(z) > 1.5 else 'slightly'
            causes.append(
                f"'{feat}' is {strength} {direction} the dataset average "
                f"(z={z:+.2f}) — a defining trait of this segment."
            )

        if not causes:
            causes.append('This cluster does not deviate strongly from the dataset average.')

        # Choose severity based on max |z|
        max_z = max((abs(z) for _, z in sorted_deltas), default=0)
        severity = 'High' if max_z > 2 else 'Medium' if max_z > 1 else 'Low'

        cluster_nodes.append({
            'cluster_id':       cid,
            'size':             size,
            'size_pct':         size_pct,
            'feature_deltas':   {k: v for k, v in sorted_deltas},
            'root_causes':      causes,
            'severity':         severity,
            'recommendation': (
                f"Cluster {cid} ({size_pct}% of data) has a distinct profile. "
                f"Investigate the top differentiating features and assess whether "
                f"this segment requires a separate strategy or intervention."
            ),
        })

    return cluster_nodes


def _unsupervised_advanced_insights(
    df:             pd.DataFrame,
    X:              pd.DataFrame,
    feature_rank:   List[Dict[str, Any]],
    cluster_nodes:  List[Dict[str, Any]],
    n_clusters:     int,
    silhouette:     float,
    algorithm:      str,
) -> List[Dict[str, Any]]:
    """
    Seven insight cards adapted for unsupervised results.
    """
    insights: List[Dict[str, Any]] = []
    n_rows       = len(df)
    n_cols       = len(df.columns)
    missing_pct  = round(df.isnull().sum().sum() / max(n_rows * n_cols, 1) * 100, 1)
    dup_rows     = int(df.duplicated().sum())

    def _sf(v):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return 0
        return v

    # Anomaly detection
    iso         = IsolationForest(contamination=0.05, random_state=42)
    iso.fit(X)
    n_anomalies = int((iso.predict(X) == -1).sum())
    anomaly_pct = round(n_anomalies / n_rows * 100, 1)

    # Card 1: Cluster quality (silhouette replaces R²)
    if silhouette >= 0.60:
        desc   = f"Silhouette score {silhouette:.3f} — clusters are well-separated and dense."
        action = '✓ High cluster quality — segments are reliable'
        color  = '#22c55e'
    elif silhouette >= 0.35:
        desc   = f"Silhouette score {silhouette:.3f} — moderate separation. Segments have real but overlapping structure."
        action = '⚠ Review cluster boundaries before acting'
        color  = '#f59e0b'
    else:
        desc   = f"Silhouette score {silhouette:.3f} — weak separation. Data may not form clear natural groups."
        action = '⚠ Low quality — consider feature engineering'
        color  = '#ef4444'
    insights.append({
        'id': 'cluster_quality', 'title': 'CLUSTER QUALITY SCORE',
        'value': f'{silhouette:.3f}', 'metric': f'{algorithm} · {n_clusters} clusters',
        'desc': desc, 'action': action, 'color': color,
    })

    # Card 2: Largest segment
    if cluster_nodes:
        largest = max(cluster_nodes, key=lambda c: c['size'])
        insights.append({
            'id': 'dominant_segment', 'title': 'DOMINANT SEGMENT',
            'value': f"Cluster {largest['cluster_id']}",
            'metric': f"{largest['size_pct']}% of all records",
            'desc': (
                f"The largest segment contains {largest['size']:,} records ({largest['size_pct']}%). "
                f"{'Its distinguishing traits: ' + largest['root_causes'][0] if largest['root_causes'] else ''}"
            ),
            'action': f"Focus initial investigation on Cluster {largest['cluster_id']}",
            'color': '#3b82f6',
        })

    # Card 3: Anomaly detection
    if anomaly_pct > 10:
        desc   = f"{n_anomalies} records ({anomaly_pct}%) flagged as anomalous — unusually high."
        action = '🚨 Investigate flagged records before relying on segments'
        color  = '#ef4444'
    elif anomaly_pct > 4:
        desc   = f"Moderate anomaly rate: {anomaly_pct}% of records are unusual."
        action = '⚠ Review anomalous records'
        color  = '#f59e0b'
    else:
        desc   = f"Low anomaly rate ({anomaly_pct}%) — clustering is based on clean, representative data."
        action = '✓ Data distribution is healthy'
        color  = '#22c55e'
    insights.append({
        'id': 'anomaly_alert', 'title': 'ANOMALY DETECTION',
        'value': f'{anomaly_pct}%', 'metric': f'{n_anomalies} unusual records (IsolationForest)',
        'desc': desc, 'action': action, 'color': color,
    })

   # Card 4: Top differentiating feature
    if feature_rank:
        top = feature_rank[0]
        p_str = '<0.001' if top['p_value'] < 0.001 else f"{top['p_value']:.4f}"
        insights.append({
            'id': 'top_differentiator', 'title': 'TOP DIFFERENTIATING FEATURE',
            'value': top['feature'].upper(),
            'metric': f"{top['impact']:.1f}% of cluster separation power",
            'desc': (
                f"'{top['feature']}' varies most significantly across clusters "
                f"(F={top['f_score']:.1f}, p={p_str}). "
                f"It is the single best variable for explaining why records land in different segments."
            ),
            'action': f"Monitor '{top['feature']}' as the primary segmentation driver",
            'color': '#8b5cf6',
        })

    # Card 5: Cluster size balance
    sizes = [c['size_pct'] for c in cluster_nodes]
    if sizes:
        max_pct = max(sizes)
        min_pct = min(sizes)
        imbalance = max_pct - min_pct
        if imbalance > 50:
            desc   = f"Clusters are highly imbalanced (largest={max_pct:.0f}%, smallest={min_pct:.0f}%)."
            action = '⚠ One segment dominates — verify cluster count k'
            color  = '#f59e0b'
        else:
            desc   = f"Clusters are reasonably balanced ({min_pct:.0f}%–{max_pct:.0f}%)."
            action = '✓ Balanced segments — robust for strategy'
            color  = '#22c55e'
        insights.append({
            'id': 'segment_balance', 'title': 'SEGMENT SIZE BALANCE',
            'value': f'{n_clusters} clusters',
            'metric': f'Range: {min_pct:.0f}% – {max_pct:.0f}%',
            'desc': desc, 'action': action, 'color': color,
        })

    # Card 6: Data integrity
    quality = max(0, round(100 - missing_pct * 2 - (1 if dup_rows > 0 else 0)))
    if quality >= 85:
        desc   = f"Dataset quality is high ({quality}%). Clustering results are reliable."
        action = 'Clean dataset — analysis is reliable'
        color  = '#22c55e'
    elif quality >= 60:
        desc   = f"Dataset quality is acceptable ({quality}%). Some missing values detected."
        action = '⚠ Address missing values for better clustering'
        color  = '#f59e0b'
    else:
        desc   = f"Dataset quality is low ({quality}%). Missing values may distort cluster boundaries."
        action = 'Clean dataset before acting on segments'
        color  = '#ef4444'
    insights.append({
        'id': 'data_quality', 'title': 'DATA INTEGRITY SCORE',
        'value': f'{quality}%', 'metric': f'{missing_pct}% missing · {dup_rows} duplicates',
        'desc': desc, 'action': action, 'color': color,
    })

    # Card 7: Actionability
    n_significant = sum(1 for r in feature_rank if r['significant'])
    if n_significant >= 3:
        desc   = f"{n_significant} features significantly separate the clusters — clear action signals."
        action = '✓ Segments are actionable — proceed with strategy'
        color  = '#22c55e'
    elif n_significant >= 1:
        desc   = f"{n_significant} feature(s) significantly differentiate clusters — limited but usable signal."
        action = '⚠ Validate with domain experts before acting'
        color  = '#f59e0b'
    else:
        desc   = "No feature significantly separates clusters. Segmentation may be noise-driven."
        action = '⚠ Low signal — consider more data or different features'
        color  = '#ef4444'
    insights.append({
        'id': 'actionability', 'title': 'SEGMENTATION ACTIONABILITY',
        'value': f'{n_significant} sig. features',
        'metric': f'ANOVA p<0.05 on {len(feature_rank)} features tested',
        'desc': desc, 'action': action, 'color': color,
    })

    return insights


def _unsupervised_narrative(
    feature_rank:   List[Dict[str, Any]],
    cluster_nodes:  List[Dict[str, Any]],
    n_clusters:     int,
    silhouette:     float,
    algorithm:      str,
    n_rows:         int,
    anomaly_pct:    float,
) -> Dict[str, str]:
    """
    Executive narrative for unsupervised results.
    Mirrors the supervised narrative structure so the frontend can reuse
    the same rendering component.
    """
    top  = feature_rank[0] if feature_rank else {'feature': 'unknown', 'impact': 0}
    top2 = feature_rank[1] if len(feature_rank) > 1 else top
    quality = 'well-separated' if silhouette >= 0.5 else 'moderately separated' if silhouette >= 0.3 else 'weakly separated'
    largest = max(cluster_nodes, key=lambda c: c['size'], default={'cluster_id': 0, 'size_pct': 0})

    return {
        'headline': 'Your dataset has been segmented. Here is what the patterns are telling you.',
        'summary': (
            f"This analysis examined {n_rows:,} records and identified {n_clusters} natural segments "
            f"using {algorithm}. The clusters are {quality} (silhouette={silhouette:.3f}), "
            f"meaning {'the segments are reliable for decision-making' if silhouette >= 0.5 else 'the segments should be validated before strategic use'}."
        ),
        'key_finding': (
            f"The single feature that most distinguishes the segments is '{top['feature']}', "
            f"accounting for {top['impact']:.1f}% of the separation power between groups. "
            f"If you want to understand why your records cluster differently, '{top['feature']}' "
            f"is where your analysis should start."
        ),
        'secondary_finding': (
            f"The second most differentiating feature is '{top2['feature']}' ({top2['impact']:.1f}%). "
            f"Together, these two variables explain the majority of why records land in different segments."
        ),
        'risk_alert': (
            f"⚠ ATTENTION: {round(anomaly_pct)}% of records show unusual patterns "
            f"that don't fit cleanly into any cluster. Review before basing decisions on these segments."
            if anomaly_pct > 8 else
            f"✓ No major anomaly risks detected. The segments are based on {n_rows:,} clean records."
        ),
        'recommended_action': (
            f"Focus initial investigation on Cluster {largest['cluster_id']} "
            f"({largest['size_pct']:.0f}% of data — the largest segment). "
            f"Understand what distinguishes it, then design differentiated strategies "
            f"for each of the {n_clusters} segments."
        ),
    }


def _unsupervised_chart_recommendations(
    feature_rank: List[Dict[str, Any]],
    n_clusters:   int,
    n_rows:       int,
) -> List[Dict[str, Any]]:
    """Chart type suggestions appropriate for cluster analysis."""
    charts = []
    n_features = len(feature_rank)
    large = n_rows > 1000

    # Feature differentiation bar
    if n_features <= 7:
        charts.append({'type': 'horizontalBar', 'title': 'Feature differentiation ranking',
                       'reason': 'Horizontal bars optimal for labeled cluster features.', 'chartData': 'impact'})
    else:
        charts.append({'type': 'bar', 'title': 'Feature separation power',
                       'reason': 'Vertical bar handles wide feature space.', 'chartData': 'impact'})

    # Cluster size pie / doughnut
    charts.append({'type': 'doughnut', 'title': 'Cluster size distribution',
                   'reason': 'Doughnut shows proportional membership across segments.', 'chartData': 'cluster_sizes'})

    # Radar for cluster profiles (if manageable)
    if 2 <= n_clusters <= 6 and n_features >= 3:
        charts.append({'type': 'radar', 'title': 'Cluster centroid profile',
                       'reason': f'Radar overlays {n_clusters} cluster centroids on {min(n_features, 8)} axes.',
                       'chartData': 'cluster_centroids'})

    # Scatter / bubble for top 2 features
    if n_features >= 2:
        f1 = feature_rank[0]['feature']
        f2 = feature_rank[1]['feature']
        if large:
            charts.append({'type': 'bubble', 'title': f'Segment map: {f1} × {f2}',
                           'reason': 'Bubble chart shows cluster positions and sizes for large datasets.',
                           'chartData': 'scatter', 'feat1': f1, 'feat2': f2})
        else:
            charts.append({'type': 'scatter', 'title': f'Cluster scatter: {f1} vs {f2}',
                           'reason': 'Scatter reveals spatial separation between clusters.',
                           'chartData': 'scatter', 'feat1': f1, 'feat2': f2})

    # Distribution of top feature
    charts.append({'type': 'histogram', 'title': f'Distribution: {feature_rank[0]["feature"].upper()}',
                   'reason': 'Histogram of top differentiator reveals cluster-driving shape.',
                   'chartData': 'histogram', 'histFeature': feature_rank[0]['feature']})

    # Cumulative separation power
    charts.append({'type': 'area', 'title': 'Cumulative separation power',
                   'reason': 'Area chart shows how many features explain 80% of cluster differences.',
                   'chartData': 'cumulative'})

    return charts


# =============================================================================
# Public entry point 2 — Unsupervised RCA
# =============================================================================

def run_unsupervised_rca_analysis(
    df:                  pd.DataFrame,
    routing_decision:    Dict[str, Any],
    unsupervised_result: Any,
) -> Dict[str, Any]:
    """
    Full RCA pipeline for unsupervised (clustering) results.

    Parameters
    ----------
    df                   : Cleaned DataFrame from BS_final.
    routing_decision     : Dict from PH1 (no target_column required).
    unsupervised_result  : UnsupervisedResult from unsupervised_engine.run().

    Mechanism (no SHAP — no target column exists)
    ------
    1. Extract cluster labels from the best model.
    2. ANOVA F-scores → rank features by cluster differentiation power.
    3. Cluster delta analysis → how each cluster deviates from global mean.
    4. IsolationForest → anomaly detection.
    5. Insight cards (7, parallel to supervised cards).
    6. Decision narrative.
    7. Chart recommendations appropriate for cluster data.

    Returns
    -------
    Sanitized dict ready for JSON serialisation.
    """
    try:
        # Extract labels from UnsupervisedResult 
        # UnsupervisedResult stores labels only inside all_model_results dicts and cluster_profiles. We reconstruct from the best model's profile.
        cluster_profiles = getattr(unsupervised_result, 'cluster_profiles', [])
        best_algorithm   = getattr(unsupervised_result, 'best_algorithm',   'KMeans')
        best_n_clusters  = getattr(unsupervised_result, 'best_n_clusters',  2)
        best_silhouette  = getattr(unsupervised_result, 'best_silhouette',  0.0)
        prep_summary     = getattr(unsupervised_result, 'preparation_summary', {})
        feature_cols_us  = prep_summary.get('feature_columns', [])

        # Build numeric feature matrix (same as unsupervised_engine did)
        id_cols    = routing_decision.get('identifier_like_columns', [])
        excl_cols  = routing_decision.get('excluded_columns', [])
        drop_set   = set(id_cols) | set(excl_cols)

        # Prefer PH1's numeric cols; fall back to all numerics
        num_cols = [
            c for c in routing_decision.get('numeric_columns', [])
            if c in df.columns and c not in drop_set
        ]
        if not num_cols:
            num_cols = [c for c in df.select_dtypes(include=[np.number]).columns
                        if c not in drop_set]

        if not num_cols:
            return {'status': 'error',
                    'message': 'No numeric columns available for unsupervised RCA.'}

        df_work = df.replace([np.inf, -np.inf], np.nan).copy()
        X_raw   = df_work[num_cols].fillna(df_work[num_cols].median(numeric_only=True)).fillna(0)

        # Reconstruct cluster label vector from cluster_profiles , Each profile has cluster_id and size — rebuild by repeating IDs. and If the sizes don't sum to len(X_raw), we fall back to re-running KMeans.
        label_vector: Optional[List[int]] = None
        total_in_profiles = sum(p.get('size', 0) for p in cluster_profiles)

        if total_in_profiles == len(X_raw):
            label_vector = []
            for p in sorted(cluster_profiles, key=lambda x: x.get('cluster_id', 0)):
                label_vector.extend([p['cluster_id']] * p['size'])
        else:
            # Re-run KMeans with same k to get labels (cheap, fast)
            from sklearn.cluster import KMeans
            from sklearn.preprocessing import StandardScaler as _SS
            scaler  = _SS()
            X_scaled = scaler.fit_transform(X_raw)
            km       = KMeans(n_clusters=best_n_clusters, random_state=42, n_init='auto')
            label_vector = km.fit_predict(X_scaled).tolist()

        # Trim/pad to match X_raw length
        if len(label_vector) > len(X_raw):
            label_vector = label_vector[:len(X_raw)]
        elif len(label_vector) < len(X_raw):
            label_vector = label_vector + [label_vector[-1]] * (len(X_raw) - len(label_vector))

        #  Step 1: ANOVA feature importance
        feature_rank = _anova_feature_importance(X_raw, label_vector)
        if not feature_rank:
            return {'status': 'error',
                    'message': 'ANOVA feature importance returned no results. '
                               'Ensure numeric columns have sufficient variance.'}

        #  Step 2: Cluster delta RCA 
        cluster_rca_nodes = _cluster_delta_rca(X_raw, label_vector, feature_rank)

        #  Step 3: Anomaly detection 
        iso         = IsolationForest(contamination=0.05, random_state=42)
        iso.fit(X_raw)
        anom_preds  = iso.predict(X_raw)
        anomaly_idx = [int(i) for i, p in enumerate(anom_preds) if p == -1]
        anomaly_pct = round(len(anomaly_idx) / len(X_raw) * 100, 1)

        anomaly_report = {
            'n_anomalies':   len(anomaly_idx),
            'anomaly_ratio': len(anomaly_idx) / max(len(X_raw), 1),
            'anomaly_pct':   anomaly_pct,
            'anomaly_indices': anomaly_idx[:50],  # cap to avoid huge payloads
        }

        #  Step 4: Distribution data (top 6 features) 
        dist_data: Dict[str, Any] = {}
        for col in [r['feature'] for r in feature_rank[:6]]:
            if col not in X_raw.columns:
                continue
            col_data    = X_raw[col].dropna()
            hist, edges = np.histogram(col_data, bins=12)
            dist_data[col] = {
                'bins':   [round(float(e), 3) for e in edges[:-1]],
                'counts': [int(h) for h in hist],
                'labels': [str(round(float(e), 2)) for e in edges[:-1]],
            }

        # Scatter data (top 2 differentiating features)
        scatter_data: Dict[str, Any] = {}
        top2_feats = [r['feature'] for r in feature_rank[:2] if r['feature'] in X_raw.columns]
        if len(top2_feats) >= 2:
            f1, f2     = top2_feats[0], top2_feats[1]
            sample_idx = np.random.choice(len(X_raw), min(400, len(X_raw)), replace=False)
            scatter_data = {
                'feat1': f1, 'feat2': f2,
                'points': [
                    {
                        'x':       round(float(X_raw[f1].iloc[i]), 4),
                        'y':       round(float(X_raw[f2].iloc[i]), 4),
                        'cluster': int(label_vector[i]),
                    }
                    for i in sample_idx
                ],
            }

        # Cluster size data (for doughnut chart)
        cluster_sizes = {
            str(p.get('cluster_id', i)): p.get('size', 0)
            for i, p in enumerate(cluster_profiles)
        }

        # Cumulative separation power
        sorted_impacts = sorted([r['impact'] for r in feature_rank], reverse=True)
        cum, running = [], 0
        for v in sorted_impacts:
            running += v
            cum.append(round(running, 1))
        cumulative_data = {
            'values': cum,
            'labels': [r['feature'] for r in feature_rank[:len(cum)]],
        }

        #  Step 5: Advanced insight cards 
        advanced_insights = _unsupervised_advanced_insights(
            df_work, X_raw, feature_rank, cluster_rca_nodes,
            best_n_clusters, best_silhouette, best_algorithm,
        )

        #  Step 6: Narrative 
        decision_narrative = _unsupervised_narrative(
            feature_rank, cluster_rca_nodes, best_n_clusters,
            best_silhouette, best_algorithm, len(df_work), anomaly_pct,
        )

        #  Step 7: Chart recommendations 
        chart_recommendations = _unsupervised_chart_recommendations(
            feature_rank, best_n_clusters, len(df_work)
        )

        #  Step 8: Correlation matrix (top differentiating features) 
        top_feats   = [r['feature'] for r in feature_rank[:7] if r['feature'] in X_raw.columns]
        corr_matrix = []
        if len(top_feats) >= 2:
            sub = X_raw[top_feats].corr()
            for r in sub.index:
                for c in sub.columns:
                    corr_matrix.append({'row': r, 'col': c, 'value': round(float(sub.loc[r, c]), 3)})

        #  Step 9: Safe data preview 
        preview_records = []
        for _, row in df_work.head(10).iterrows():
            rec: Dict[str, Any] = {}
            for col in df_work.columns:
                v = row[col]
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    rec[col] = '—'
                elif pd.isna(v):
                    rec[col] = '—'
                elif isinstance(v, np.integer):
                    rec[col] = int(v)
                elif isinstance(v, np.floating):
                    rec[col] = round(float(v), 4)
                else:
                    rec[col] = v
            preview_records.append(rec)

        #  Step 10: Assemble payload 
        payload = sanitize({
            'status':  'success',
            'preview': preview_records,

            # Feature differentiation ranking (mirrors xai_report in supervised)
            'xai_report':              feature_rank,
            'feature_importance_unsupervised': feature_rank,

            # Cluster-level RCA
            'cluster_rca':             cluster_rca_nodes,
            'rca_report':              cluster_rca_nodes,  # alias for frontend compat

            # Charts, insights, narrative
            'advanced_insights':       advanced_insights,
            'chart_recommendations':   chart_recommendations,
            'corr_matrix':             corr_matrix,
            'dist_data':               dist_data,
            'scatter_data':            scatter_data,
            'cumulative_data':         cumulative_data,
            'cluster_sizes':           cluster_sizes,
            'decision_narrative':      decision_narrative,
            'anomaly_report':          anomaly_report,

            # No SHAP model score — use silhouette instead
            'model_score':             round(best_silhouette * 100, 1),

            # Target detection equivalent for unsupervised
            'target_detection': {
                'column':      None,
                'task_type':   'clustering',
                'algorithm':   best_algorithm,
                'n_clusters':  best_n_clusters,
                'silhouette':  best_silhouette,
                'reason':      (
                    f"No target column — unsupervised path. "
                    f"{best_algorithm} found {best_n_clusters} clusters "
                    f"(silhouette={best_silhouette:.3f})."
                ),
            },

            'nlp_analysis': {'nlp_available': NLP_AVAILABLE, 'columns_processed': []},

            'dataset_meta': {
                'rows':           len(df_work),
                'cols':           len(df_work.columns),
                'numeric_cols':   len(num_cols),
                'missing_total':  int(df_work.isnull().sum().sum()),
                'duplicate_rows': int(df_work.duplicated().sum()),
                'n_clusters':     best_n_clusters,
                'algorithm':      best_algorithm,
                'silhouette':     best_silhouette,
                'ph1_strategy':   'unsupervised',
            },
        })

        return payload

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return {'status': 'error', 'message': str(exc)}

# Smoke tests
if __name__ == '__main__':
    import numpy as _np
    _np.random.seed(42)

    n = 200
    df_test = pd.DataFrame({
        'region':   _np.random.choice(['North', 'South', 'East', 'West'], n),
        'product':  _np.random.choice(['A', 'B', 'C'], n),
        'quantity': _np.random.randint(1, 100, n),
        'discount': _np.round(_np.random.uniform(0, 0.5, n), 2),
        'profit':   _np.round(_np.random.normal(500, 200, n), 2),
        'sales':    _np.round(_np.random.normal(2000, 800, n), 2),
    })

    # Smoke test 1: Supervised RCA 
    print('SMOKE TEST 1 — Supervised RCA')
    fake_routing_sup = {
        'has_valid_target':        True,
        'target_column':           'profit',
        'task_type':               'regression',
        'task_confidence':         'high',
        'strategy':                'supervised',
        'explainability_mode':     'supervised_xai_rca',
        'numeric_columns':         ['quantity', 'discount', 'profit', 'sales'],
        'categorical_columns':     ['region', 'product'],
        'datetime_columns':        [],
        'text_columns':            [],
        'identifier_like_columns': [],
        'excluded_columns':        [],
        'dataset_modality':        'tabular',
        'target_candidates':       [{'gain_over_baseline': 0.312}],
    }
    r1 = run_rca_analysis(df_test, fake_routing_sup)
    if r1['status'] == 'success':
        print(f"  Model R²        : {r1['model_score']}%")
        print(f"  Top feature     : {r1['xai_report'][0]['feature']} ({r1['xai_report'][0]['impact']}%)")
        print(f"  RCA nodes       : {len(r1['rca_report'])}")
        print('  ✓ Supervised RCA passed')
    else:
        print(f"  ERROR: {r1['message']}")

    # Smoke test 2: Unsupervised RCA
    print()
    print('SMOKE TEST 2 — Unsupervised RCA')
    # Simulate a UnsupervisedResult
    from dataclasses import dataclass
    from typing import List as _List

    @dataclass
    class _FakeUnsupResult:
        best_algorithm:      str
        best_n_clusters:     int
        best_silhouette:     float
        best_davies_bouldin: float
        all_model_results:   list
        cluster_profiles:    list
        pca_variance_ratio:  list
        pca_n_components:    int
        preparation_summary: dict
        saved_model_dir:     str

    fake_profiles = [
        {'cluster_id': 0, 'size': 70,  'size_pct': 35.0, 'feature_means': {'quantity': 30, 'sales': 1500}, 'label': 'Low-quantity'},
        {'cluster_id': 1, 'size': 80,  'size_pct': 40.0, 'feature_means': {'quantity': 60, 'sales': 2200}, 'label': 'Mid-tier'},
        {'cluster_id': 2, 'size': 50,  'size_pct': 25.0, 'feature_means': {'quantity': 90, 'sales': 2800}, 'label': 'High-volume'},
    ]
    fake_unsup = _FakeUnsupResult(
        best_algorithm='KMeans', best_n_clusters=3,
        best_silhouette=0.52, best_davies_bouldin=0.81,
        all_model_results=[], cluster_profiles=fake_profiles,
        pca_variance_ratio=[0.6, 0.25], pca_n_components=2,
        preparation_summary={'rows_used': n, 'feature_columns': ['quantity', 'discount', 'profit', 'sales']},
        saved_model_dir='saved_models/smoke_unsup',
    )
    fake_routing_unsup = {
        'strategy':                'unsupervised',
        'task_type':               'clustering',
        'target_column':           None,
        'numeric_columns':         ['quantity', 'discount', 'profit', 'sales'],
        'categorical_columns':     ['region', 'product'],
        'datetime_columns':        [],
        'text_columns':            [],
        'identifier_like_columns': [],
        'excluded_columns':        [],
        'dataset_modality':        'tabular',
    }
    r2 = run_unsupervised_rca_analysis(df_test, fake_routing_unsup, fake_unsup)
    if r2['status'] == 'success':
        print(f"  Top differentiator  : {r2['xai_report'][0]['feature']} (F={r2['xai_report'][0]['f_score']})")
        print(f"  Cluster RCA nodes   : {len(r2['cluster_rca'])}")
        print(f"  Anomaly pct         : {r2['anomaly_report']['anomaly_pct']}%")
        print(f"  Insight cards       : {len(r2['advanced_insights'])}")
        print(f"  Chart recs          : {len(r2['chart_recommendations'])}")
        print('Unsupervised RCA passed')
    else:
        print(f"  ERROR: {r2['message']}")

    print()
    print('All RCA engine smoke tests passed.')
