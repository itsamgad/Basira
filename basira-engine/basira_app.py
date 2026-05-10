"""
Basira Smart Preprocessor — Flask Backend v3.0
Intelligent, adaptive, explainable preprocessing engine.
All preprocessing decisions and transformations happen in Python only.
"""

import os, uuid, json, re, warnings
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
from scipy import stats as sp_stats
from sklearn.preprocessing import LabelEncoder

try:
    from sklearn.experimental import enable_iterative_imputer  # noqa (sklearn < 1.0)
except ImportError:
    pass
from sklearn.impute import KNNImputer, IterativeImputer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD

from flask import Flask, request, jsonify, send_file, abort

warnings.filterwarnings("ignore")

app = Flask(__name__)

UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────
ARABIC_RE = re.compile(r'[؀-ۿ]')

DATE_KEYWORDS = {
    "date", "time", "datetime", "timestamp", "created", "updated", "modified",
    "تاريخ", "وقت", "سنة", "شهر", "يوم", "created_at", "updated_at",
    "start", "end", "due", "deadline", "completion", "arrival", "departure", "recorded",
}
ID_KEYWORDS = {
    "id", "_id", "rowid", "row_id", "index", "serial", "uuid", "pk", "key",
    "رقم", "معرف", "no", "number", "num", "code", "ref", "reference",
}
TARGET_KEYWORDS = {
    "label", "target", "class", "category", "output", "result", "outcome",
    "status", "type", "grade", "verdict", "sentiment", "fraud", "churn",
    "risk", "diagnosis", "disease", "approved", "prediction",
    "تصنيف", "فئة", "نتيجة", "هدف", "نوع", "حالة", "درجة",
}
INCIDENT_KEYWORDS = {
    "ticket", "incident", "case", "request", "sla", "resolution", "issue",
    "error", "pr", "po", "rfx", "vendor", "root_cause", "complaint", "defect",
    "fault", "bug", "problem", "escalation",
}


# ─────────────────────────────────────────────────────────────
# COLUMN TYPE DETECTION
# ─────────────────────────────────────────────────────────────

def _is_datetime_col(col_name: str, series: pd.Series) -> bool:
    """Datetime if name matches OR ≥ 90% of non-null values parse as valid dates (1900–2100)."""
    cn = col_name.lower().replace(" ", "_")
    if any(k in cn for k in DATE_KEYWORDS):
        return True
    non_null = series.dropna()
    if len(non_null) < 3:
        return False
    sample = non_null.head(50).astype(str)
    try:
        parsed = pd.to_datetime(sample, errors="coerce", infer_datetime_format=True)
        if parsed.notna().mean() >= 0.90:
            return bool(parsed.dropna().dt.year.between(1900, 2100).all())
    except Exception:
        pass
    return False


def _is_id_col(col_name: str, series: pd.Series) -> bool:
    """ID if name pattern matches OR uniqueness ratio ≥ 95% in object/int column."""
    cn = col_name.lower().replace(" ", "_")
    parts = set(cn.replace("-", "_").split("_"))
    if parts & ID_KEYWORDS or any(k in cn for k in ID_KEYWORDS):
        return True
    non_null = series.dropna()
    n_total = len(non_null)
    if n_total > 20 and non_null.nunique() / n_total >= 0.95:
        if series.dtype == object or pd.api.types.is_integer_dtype(series):
            return True
    return False


def _detect_type(col_name: str, series: pd.Series) -> str:
    """
    Detect column type using layered signals:
      - empty / datetime / id first
      - native numeric → bool / int / float
      - coercion at 95% threshold → int / float
      - cardinality + average length → bool / categorical / text
    """
    non_null = series.dropna()
    if len(non_null) == 0:
        return "empty"
    if _is_datetime_col(col_name, series):
        return "datetime"
    if _is_id_col(col_name, series):
        return "id"

    if pd.api.types.is_numeric_dtype(series):
        if series.nunique() <= 2:
            return "bool"
        return "float" if pd.api.types.is_float_dtype(series) else "int"

    coerced = pd.to_numeric(
        non_null.astype(str).str.replace(",", "").str.strip(), errors="coerce"
    )
    if coerced.notna().mean() >= 0.95:
        vals = coerced.dropna()
        return "int" if (vals % 1 == 0).all() else "float"

    n_unique = non_null.nunique()
    n_total = len(non_null)
    if n_unique <= 2:
        return "bool"

    avg_len = non_null.astype(str).apply(len).mean()
    unique_ratio = n_unique / n_total if n_total > 0 else 0

    if avg_len > 30 and unique_ratio > 0.5:
        return "text"
    if n_unique <= 50 or unique_ratio < 0.3:
        return "categorical"
    if avg_len > 15:
        return "text"
    return "categorical"


def _col_stats(series: pd.Series, col_type: str) -> dict:
    out = {
        "null_count": int(series.isna().sum()),
        "null_pct": round(series.isna().mean() * 100, 1),
        "n_unique": int(series.nunique()),
        "has_arabic": bool(
            series.dropna().astype(str).apply(lambda v: bool(ARABIC_RE.search(v))).any()
        ),
    }
    if col_type in ("int", "float"):
        num = pd.to_numeric(
            series.astype(str).str.replace(",", ""), errors="coerce"
        ).dropna()
        if len(num):
            q1, q3 = num.quantile(0.25), num.quantile(0.75)
            iqr = q3 - q1
            skew = float(sp_stats.skew(num))
            out.update({
                "min": round(float(num.min()), 4), "max": round(float(num.max()), 4),
                "mean": round(float(num.mean()), 4), "median": round(float(num.median()), 4),
                "std": round(float(num.std()), 4), "skew": round(skew, 3),
                "q1": round(float(q1), 4), "q3": round(float(q3), 4),
                "iqr": round(float(iqr), 4),
                "outlier_count": int(((num < q1 - 1.5 * iqr) | (num > q3 + 1.5 * iqr)).sum()),
                "fill_strategy": "median" if abs(skew) > 1 else "mean",
            })
    elif col_type in ("categorical", "bool"):
        freq = series.value_counts()
        n_u = series.nunique()
        out["top_values"] = freq.head(5).to_dict()
        out["encoding_strategy"] = (
            "binary" if n_u <= 2 else
            "onehot" if n_u <= 10 else
            "label"  if n_u <= 50 else
            "frequency"
        )
    elif col_type == "text":
        sv = series.dropna().astype(str)
        out["avg_word_count"] = round(sv.apply(lambda v: len(v.split())).mean(), 1)
        out["avg_char_length"] = round(sv.apply(len).mean(), 1)
        out["has_arabic"] = bool(sv.apply(lambda v: bool(ARABIC_RE.search(v))).any())
    return out


# ─────────────────────────────────────────────────────────────
# READINESS CHECK
# ─────────────────────────────────────────────────────────────

def _readiness_check(df: pd.DataFrame, label: str = "initial") -> dict:
    n_rows, n_cols = df.shape
    miss = df.isnull().mean()
    max_missing = float(miss.max()) if len(miss) > 0 else 0.0
    high_miss = list(miss[miss > 0.6].index)
    empty_cols = list(miss[miss == 1.0].index)
    n_dup = int(df.duplicated().sum())

    status = "OK"
    warns = []
    if max_missing > 0.15:
        status = "WARNING"
        warns.append(f"Max column missing ratio {max_missing:.1%} exceeds 15%")
    if n_rows < 30:
        status = "WARNING"
        warns.append(f"Only {n_rows} rows (recommended minimum: 30)")
    if empty_cols:
        warns.append(f"Fully empty columns: {empty_cols}")
    if n_dup > n_rows * 0.1:
        warns.append(f"{n_dup} duplicate rows ({n_dup/n_rows:.1%} of data)")

    return {
        "label": label, "status": status,
        "n_rows": n_rows, "n_cols": n_cols,
        "n_duplicates": n_dup,
        "max_missing_ratio": round(max_missing, 4),
        "high_missing_cols": high_miss,
        "empty_cols": empty_cols,
        "warnings": warns,
    }


# ─────────────────────────────────────────────────────────────
# ADAPTIVE NUMERIC IMPUTATION
# ─────────────────────────────────────────────────────────────

def _choose_num_imputation(df: pd.DataFrame, num_cols: list) -> tuple:
    """Returns (strategy, reason). Strategies: 'mice', 'knn', 'simple'."""
    n_rows = len(df)
    n_num = len(num_cols)
    if n_num == 0:
        return "simple", "No numeric columns require imputation"

    missing_rates = [df[c].isna().mean() for c in num_cols]
    cols_missing = [r for r in missing_rates if r > 0]
    if not cols_missing:
        return "simple", "No missing values in numeric columns"
    avg_miss = sum(cols_missing) / len(cols_missing)

    if n_rows >= 80 and n_num >= 3 and avg_miss >= 0.15:
        return "mice", (
            f"MICE (IterativeImputer): {n_rows} rows ≥ 80, {n_num} numeric cols ≥ 3, "
            f"avg missing {avg_miss:.1%} ≥ 15% — multivariate imputation is most appropriate"
        )
    if n_rows >= 200 and n_num >= 2 and 0.10 <= avg_miss <= 0.40:
        return "knn", (
            f"KNN Imputation: {n_rows} rows ≥ 200, {n_num} numeric cols ≥ 2, "
            f"avg missing {avg_miss:.1%} in [10%, 40%] — nearest-neighbor imputation appropriate"
        )
    reasons = []
    if n_rows < 80:
        reasons.append(f"small dataset ({n_rows} rows < 80)")
    if n_num < 2:
        reasons.append(f"few numeric columns ({n_num})")
    if avg_miss < 0.10:
        reasons.append(f"low missing rate ({avg_miss:.1%} < 10%)")
    return "simple", "SIMPLE imputation: " + (", ".join(reasons) or "default fallback")


def _simple_fill(df: pd.DataFrame, col: str) -> tuple:
    """Mean or median based on skewness. Returns (filled_series, description)."""
    num = pd.to_numeric(df[col].astype(str).str.replace(",", ""), errors="coerce")
    vals = num.dropna()
    if len(vals) < 3 or vals.std() == 0:
        fv = float(vals.median()) if len(vals) > 0 else 0.0
        return num.fillna(round(fv, 4)), f"median={round(fv,4)} (few values or zero variance)"
    skew = float(sp_stats.skew(vals))
    if abs(skew) > 1:
        fv = float(vals.median())
        return num.fillna(round(fv, 4)), f"median={round(fv,4)} (skew={round(skew,2)} > 1)"
    fv = float(vals.mean())
    return num.fillna(round(fv, 4)), f"mean={round(fv,4)} (skew={round(skew,2)} ≈ symmetric)"


# ─────────────────────────────────────────────────────────────
# BILINGUAL TEXT NORMALIZATION
# ─────────────────────────────────────────────────────────────

def _normalize_arabic(s: str) -> str:
    s = re.sub(r'[ؐ-ًؚ-ٰٟۖ-۪ۤ-ۭ]', '', s)
    s = s.replace('ـ', '')          # tatweel
    s = re.sub(r'[أإآ]', 'ا', s)       # alef variants
    s = s.replace('ى', 'ي')             # alef maqsura → ya
    s = s.replace('ة', 'ه')             # teh marbuta → ha
    return re.sub(r'\s+', ' ', s).strip()


def _normalize_text(value, has_arabic: bool):
    if pd.isna(value):
        return value
    s = str(value).strip()
    if has_arabic:
        s = _normalize_arabic(s)
    else:
        s = s.lower()
        s = re.sub(r'\s+', ' ', s).strip()
    return s


def _detect_language(text: str) -> str:
    if not text or not isinstance(text, str):
        return "unknown"
    arabic_chars = len(ARABIC_RE.findall(text))
    total = len(re.sub(r'\s+', '', text))
    if total == 0:
        return "unknown"
    ratio = arabic_chars / total
    if ratio > 0.6:
        return "arabic"
    if ratio > 0.2:
        return "mixed"
    return "english"


# ─────────────────────────────────────────────────────────────
# TF-IDF + TRUNCATED SVD
# ─────────────────────────────────────────────────────────────

def _apply_tfidf_svd(model_df: pd.DataFrame, text_cols: list, n_rows: int) -> tuple:
    """Returns (updated_model_df, log_string_or_None)."""
    if not text_cols:
        return model_df, None

    valid = [
        c for c in text_cols
        if c in model_df.columns
        and model_df[c].fillna("").astype(str).apply(len).mean() > 10
    ]
    if not valid:
        return model_df, "TF-IDF skipped: no text columns with meaningful content (avg > 10 chars)"
    if n_rows < 20:
        return model_df, f"TF-IDF skipped: only {n_rows} rows (minimum: 20)"

    combined = model_df[valid].fillna("").astype(str).apply(
        lambda row: " ".join(row.values), axis=1
    )
    unique_tokens = set(" ".join(combined).lower().split())
    if len(unique_tokens) < 10:
        return model_df, f"TF-IDF skipped: vocabulary too small ({len(unique_tokens)} tokens)"

    max_features = min(1000, max(300, n_rows * 3))
    tfidf = TfidfVectorizer(
        max_features=max_features, ngram_range=(1, 2),
        lowercase=True, sublinear_tf=True, strip_accents=None,
    )
    try:
        matrix = tfidf.fit_transform(combined)
    except Exception as e:
        return model_df, f"TF-IDF skipped: vectorization error — {e}"

    n_feat = matrix.shape[1]
    if n_feat > 20:
        n_comp = max(2, min(20, n_rows - 1, n_feat - 1))
        try:
            svd = TruncatedSVD(n_components=n_comp, random_state=42)
            svd_out = svd.fit_transform(matrix)
            for i in range(n_comp):
                model_df[f"text_svd_{i+1}"] = svd_out[:, i].round(6)
            explained = round(float(svd.explained_variance_ratio_.sum() * 100), 1)
            log = (
                f"TF-IDF + TruncatedSVD applied to {valid}: "
                f"max_features={max_features}, ngram=(1,2), "
                f"{n_comp} SVD components explaining {explained}% variance"
            )
        except Exception as e:
            return model_df, f"TF-IDF applied but SVD failed: {e}"
    else:
        names = tfidf.get_feature_names_out()
        tdf = pd.DataFrame(matrix.toarray(),
                           columns=[f"tfidf_{f}" for f in names],
                           index=model_df.index)
        model_df = pd.concat([model_df, tdf], axis=1)
        log = f"TF-IDF applied to {valid}: {n_feat} features kept directly (small vocabulary)"

    return model_df, log


# ─────────────────────────────────────────────────────────────
# LOW-VARIANCE / USELESS COLUMN DETECTION
# ─────────────────────────────────────────────────────────────

def _detect_low_quality_cols(df: pd.DataFrame, col_types: dict, target_col: str) -> tuple:
    """Returns (to_drop [(col, reason)], to_flag [(col, kind, detail)])."""
    to_drop, to_flag = [], []
    for col in df.columns:
        if col == target_col:
            continue
        miss = df[col].isna().mean()
        if miss == 1.0:
            to_drop.append((col, "all-empty column"))
            continue
        if miss >= 0.90:
            to_drop.append((col, f"extremely high missingness ({miss:.1%})"))
            continue
        non_null = df[col].dropna()
        n_u = non_null.nunique()
        if n_u == 1:
            to_drop.append((col, f"constant column — only value: {repr(non_null.iloc[0])}"))
            continue
        if n_u >= 2 and len(non_null) > 10:
            vc = non_null.value_counts(normalize=True)
            if float(vc.iloc[0]) >= 0.99:
                to_flag.append((
                    col, "near-constant",
                    f"{vc.index[0]!r} appears {vc.iloc[0]:.1%} of the time"
                ))
        ctype = col_types.get(col, "unknown")
        if ctype not in ("id", "text", "datetime") and len(non_null) > 20:
            if n_u / len(non_null) > 0.95:
                to_flag.append((
                    col, "high-uniqueness non-ID column",
                    f"{n_u} unique / {len(non_null)} rows = {n_u/len(non_null):.1%}"
                ))
    return to_drop, to_flag


# ─────────────────────────────────────────────────────────────
# TARGET & TASK DETECTION
# ─────────────────────────────────────────────────────────────

def _auto_detect(df: pd.DataFrame, col_types: dict) -> tuple:
    """Returns (target_col, task_type, reason)."""
    best, best_score = None, -999
    for col in df.columns:
        ctype = col_types.get(col, "unknown")
        if ctype in ("id", "datetime", "empty", "unknown"):
            continue
        cn = col.lower().replace(" ", "_")
        score = 0
        if any(k in cn for k in TARGET_KEYWORDS):
            score += 10
        score += {"categorical": 5, "bool": 4, "int": 2, "float": 2}.get(ctype, 0)
        null_pct = df[col].isna().mean()
        if null_pct < 0.05:
            score += 3
        elif null_pct > 0.40:
            score -= 8
        n_u = df[col].nunique()
        if 2 <= n_u <= 30:
            score += 2
        elif n_u > 100:
            score -= 2
        if score > best_score:
            best_score, best = score, col

    if best is None:
        return None, "unsupervised", (
            "No reliable target column found — unsupervised clustering is recommended."
        )
    ctype = col_types.get(best, "unknown")
    n_u = df[best].nunique()
    if ctype in ("categorical", "bool") or n_u <= 30:
        return best, "classification", (
            f'Target "{best}" has {n_u} distinct categorical values → Classification recommended.'
        )
    if ctype in ("int", "float") and n_u > 10:
        return best, "regression", (
            f'Target "{best}" is continuous numeric with {n_u} distinct values → Regression recommended.'
        )
    return best, "classification", (
        f'Target "{best}" detected — Classification selected as default supervised task.'
    )


def _is_incident_like(df: pd.DataFrame) -> bool:
    col_str = " ".join(df.columns).lower()
    return any(k in col_str for k in INCIDENT_KEYWORDS)


# ─────────────────────────────────────────────────────────────
# CORE PREPROCESSING ENGINE
# ─────────────────────────────────────────────────────────────

def preprocess(df: pd.DataFrame, file_name: str) -> dict:
    audit = []
    original_shape = df.shape

    # ── READINESS CHECK (BEFORE) ────────────────────────────
    rb = _readiness_check(df, "before_preprocessing")
    audit.append({
        "step": "Data Readiness Check (Before Preprocessing)",
        "detail": (
            f"Status: {rb['status']} | {rb['n_rows']} rows × {rb['n_cols']} cols | "
            f"Max missing ratio: {rb['max_missing_ratio']:.1%} | "
            f"Duplicate rows: {rb['n_duplicates']}"
            + (f" | ⚠ {'; '.join(rb['warnings'])}" if rb['warnings'] else " | All checks passed")
        ),
    })

    # ── 1. COLUMN TYPE DETECTION ─────────────────────────────
    col_types = {col: _detect_type(col, df[col]) for col in df.columns}
    col_stats  = {col: _col_stats(df[col], col_types[col]) for col in df.columns}
    audit.append({
        "step": "Column Type Detection",
        "detail": (
            "Detected types — " +
            ", ".join(f'"{c}": {t}' for c, t in col_types.items()) +
            " | Rules: numeric≥95% parse, datetime≥90% parse (years 1900–2100), "
            "ID if name pattern or uniqueness≥95%, categorical if unique ratio<30% or ≤50 values, "
            "text if avg length>30 chars and high cardinality"
        ),
    })

    # ── 2. AUTO-DETECT TARGET + TASK ────────────────────────
    target_col, task_type, task_reason = _auto_detect(df, col_types)
    audit.append({
        "step": "Task & Target Detection",
        "detail": task_reason + (f' | Target column: "{target_col}"' if target_col else ""),
    })

    # ── 3. IDENTIFY EXCLUDED COLUMNS ────────────────────────
    id_cols       = [c for c in df.columns if col_types[c] == "id"]
    datetime_cols = [c for c in df.columns if col_types[c] == "datetime"]
    empty_cols    = [c for c in df.columns if col_types[c] == "empty"]
    excl_cols     = set(id_cols + empty_cols)

    work_cols = [c for c in df.columns if c not in excl_cols]
    df_clean  = df[work_cols].copy()

    excl_detail = []
    if id_cols:
        excl_detail.append(f"ID columns excluded from model: {id_cols}")
    if empty_cols:
        excl_detail.append(f"Fully empty columns dropped: {empty_cols}")
    audit.append({
        "step": "Column Selection",
        "detail": (
            f"Kept {len(work_cols)}/{len(df.columns)} columns. "
            + (" | ".join(excl_detail) if excl_detail else "No columns excluded.")
        ),
    })

    # ── 4. INCIDENT-LIKE DATASET DETECTION ──────────────────
    is_incident = _is_incident_like(df)
    if is_incident:
        audit.append({
            "step": "Dataset Context — Incident/Operational Data Detected",
            "detail": (
                "Column names suggest incident/ticket/operational data "
                "(keywords matched: ticket, incident, case, request, SLA, resolution, etc.). "
                "Outliers will always be preserved — they likely represent significant operational events."
            ),
        })

    # ── 5. LOW-QUALITY COLUMN DETECTION ─────────────────────
    lq_drop, lq_flag = _detect_low_quality_cols(df_clean, col_types, target_col)
    if lq_drop:
        drop_names = [c for c, _ in lq_drop]
        df_clean.drop(columns=[c for c in drop_names if c in df_clean.columns], inplace=True)
        work_cols = [c for c in work_cols if c not in drop_names]
        audit.append({
            "step": "Low-Quality Column Removal",
            "detail": (
                f"Dropped {len(lq_drop)} column(s): " +
                " | ".join(f'"{c}": {r}' for c, r in lq_drop)
            ),
        })
    if lq_flag:
        audit.append({
            "step": "Low-Quality Column Flags (Review Recommended)",
            "detail": " | ".join(f'"{c}" ({k}): {d}' for c, k, d in lq_flag),
        })

    # ── 6. REMOVE EXACT DUPLICATE ROWS ──────────────────────
    n_before = len(df_clean)
    df_clean.drop_duplicates(inplace=True)
    df_clean.reset_index(drop=True, inplace=True)
    dup_removed = n_before - len(df_clean)
    audit.append({
        "step": "Duplicate Row Removal",
        "detail": (
            f"Removed {dup_removed} exact duplicate rows (all columns matched). "
            f"Remaining: {len(df_clean)} rows."
        ),
    })

    # ── 7. REPEATED-ID DETECTION (FLAG ONLY) ────────────────
    repeated_id_info = []
    for ic in id_cols:
        if ic in df.columns:
            vc = df[ic].value_counts()
            reps = vc[vc > 1]
            if len(reps):
                repeated_id_info.append(f'"{ic}": {len(reps)} repeated ID values')
    if repeated_id_info:
        audit.append({
            "step": "Repeated ID Detection (Rows Preserved)",
            "detail": (
                "; ".join(repeated_id_info) +
                " — Rows kept. Repeated IDs may represent valid repeated events "
                "(e.g., multiple incidents per case number, repeated transactions). "
                "A repeat_flag column has been noted in the config."
            ),
        })

    # ── 8. DROP COLUMNS WITH > 60% MISSING (NOT TARGET) ─────
    high_miss = [
        c for c in df_clean.columns
        if c != target_col and df_clean[c].isna().mean() > 0.60
    ]
    if high_miss:
        df_clean.drop(columns=high_miss, inplace=True)
        audit.append({
            "step": "High-Missing Columns Dropped (> 60% missing)",
            "detail": (
                f"Dropped {len(high_miss)} column(s) — too sparse for reliable imputation: {high_miss}"
            ),
        })

    # ── 9. DATETIME FEATURE EXTRACTION ──────────────────────
    dt_in_work = [c for c in datetime_cols if c in df_clean.columns]
    extracted_dt = []
    for col in dt_in_work:
        parsed = pd.to_datetime(df_clean[col], errors="coerce")
        new_cols = {
            f"{col}_year":       parsed.dt.year,
            f"{col}_month":      parsed.dt.month,
            f"{col}_day":        parsed.dt.day,
            f"{col}_hour":       parsed.dt.hour,
            f"{col}_dow":        parsed.dt.dayofweek,
            # Saudi weekend: Friday=4, Saturday=5 in pandas (0=Monday)
            f"{col}_is_weekend": parsed.dt.dayofweek.isin([4, 5]).astype(int),
            f"{col}_missing":    parsed.isna().astype(int),
        }
        for nc, vs in new_cols.items():
            df_clean[nc] = vs
        df_clean.drop(columns=[col], inplace=True)
        extracted_dt.append(col)
    if extracted_dt:
        audit.append({
            "step": "Datetime Feature Extraction",
            "detail": (
                f"Extracted from {extracted_dt}: year, month, day, hour, day_of_week, "
                f"is_weekend (Saudi logic — Friday & Saturday), missing_flag. "
                f"Raw datetime columns removed. {len(extracted_dt) * 7} new features created."
            ),
        })

    work_cols = list(df_clean.columns)

    # ── 10. ADAPTIVE MISSING VALUE IMPUTATION ───────────────
    num_miss_cols = [
        c for c in work_cols
        if c != target_col
        and (
            col_types.get(c, "") in ("int", "float")
            or pd.api.types.is_numeric_dtype(df_clean[c])
        )
        and df_clean[c].isna().any()
    ]
    cat_miss_cols = [
        c for c in work_cols
        if c != target_col
        and col_types.get(c, "") in ("categorical", "bool")
        and df_clean[c].isna().any()
    ]
    text_miss_cols = [
        c for c in work_cols
        if col_types.get(c, "") == "text" and df_clean[c].isna().any()
    ]

    impute_strategy, impute_reason = _choose_num_imputation(df_clean, num_miss_cols)
    fill_log = []
    before_counts = {c: int(df_clean[c].isna().sum()) for c in num_miss_cols}

    # Numeric imputation
    if num_miss_cols:
        if impute_strategy == "mice":
            try:
                imp = IterativeImputer(max_iter=10, random_state=42)
                num_data = df_clean[num_miss_cols].apply(pd.to_numeric, errors="coerce")
                imputed = imp.fit_transform(num_data)
                for i, c in enumerate(num_miss_cols):
                    df_clean[c] = imputed[:, i].round(4)
                fill_log.append(
                    f"MICE applied to {len(num_miss_cols)} columns: " +
                    ", ".join(f'"{c}" ({before_counts[c]} missing)' for c in num_miss_cols)
                )
            except Exception as e:
                impute_strategy = "simple"
                impute_reason += f" (MICE failed: {e}, fell back to SIMPLE)"
                for c in num_miss_cols:
                    filled, desc = _simple_fill(df_clean, c)
                    df_clean[c] = filled
                    fill_log.append(f'"{c}": {desc}')

        elif impute_strategy == "knn":
            try:
                k = max(2, min(5, len(df_clean) // 10))
                imp = KNNImputer(n_neighbors=k)
                num_data = df_clean[num_miss_cols].apply(pd.to_numeric, errors="coerce")
                imputed = imp.fit_transform(num_data)
                for i, c in enumerate(num_miss_cols):
                    df_clean[c] = imputed[:, i].round(4)
                fill_log.append(
                    f"KNN (k={k}) applied to {len(num_miss_cols)} columns: " +
                    ", ".join(f'"{c}" ({before_counts[c]} missing)' for c in num_miss_cols)
                )
            except Exception as e:
                impute_strategy = "simple"
                impute_reason += f" (KNN failed: {e}, fell back to SIMPLE)"
                for c in num_miss_cols:
                    filled, desc = _simple_fill(df_clean, c)
                    df_clean[c] = filled
                    fill_log.append(f'"{c}": {desc}')

        else:  # simple
            for c in num_miss_cols:
                filled, desc = _simple_fill(df_clean, c)
                df_clean[c] = filled
                fill_log.append(f'"{c}": {desc} ({before_counts[c]} missing filled)')

    # Categorical imputation (mode)
    cat_fill_parts = []
    for c in cat_miss_cols:
        n_miss = int(df_clean[c].isna().sum())
        mode_v = df_clean[c].mode()
        fill_v = mode_v.iloc[0] if len(mode_v) > 0 else "unknown"
        df_clean[c] = df_clean[c].fillna(fill_v)
        cat_fill_parts.append(f'"{c}": mode="{fill_v}" ({n_miss} filled)')
    if cat_fill_parts:
        fill_log.append("Categorical → mode: " + " | ".join(cat_fill_parts))

    # Text: missing flag only — no imputation
    text_flag_parts = []
    for c in text_miss_cols:
        flag_col = f"{c}_missing_flag"
        df_clean[flag_col] = df_clean[c].isna().astype(int)
        if flag_col not in work_cols:
            work_cols.append(flag_col)
        text_flag_parts.append(f'"{c}": missing_flag added (text not imputed — content must not be invented)')
    if text_flag_parts:
        fill_log.append("Text columns: " + " | ".join(text_flag_parts))

    if fill_log:
        audit.append({
            "step": "Missing Value Imputation",
            "detail": (
                f"Numeric strategy: {impute_strategy.upper()} | Reason: {impute_reason} | "
                + " | ".join(fill_log)
            ),
        })

    # ── 11. DROP TARGET ROWS WHERE TARGET IS NULL ────────────
    if target_col and target_col in df_clean.columns:
        n_before_t = len(df_clean)
        df_clean = df_clean[df_clean[target_col].notna()].reset_index(drop=True)
        dropped_t = n_before_t - len(df_clean)
        if dropped_t:
            audit.append({
                "step": "Target Null Row Removal",
                "detail": (
                    f"Removed {dropped_t} rows where target column '{target_col}' was null. "
                    f"Remaining: {len(df_clean)} rows."
                ),
            })

    # ── 12. OUTLIER FLAGGING (IQR — NO DELETION) ─────────────
    feat_num = [
        c for c in df_clean.columns
        if c != target_col and col_types.get(c, "") in ("int", "float")
    ]
    outlier_log = []
    for col in feat_num:
        num = pd.to_numeric(df_clean[col], errors="coerce")
        q1, q3 = num.quantile(0.25), num.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        flag = ((num < lo) | (num > hi)).astype(int)
        n_out = int(flag.sum())
        if n_out > 0:
            flag_col = f"{col}_outlier_flag"
            df_clean[flag_col] = flag
            preserve = "preserved — incident dataset" if is_incident else "preserved"
            outlier_log.append(
                f'"{col}": {n_out} outliers, IQR bounds [{round(lo,2)}, {round(hi,2)}] — {preserve}'
            )
    if outlier_log:
        audit.append({
            "step": "Outlier Detection (IQR) — Flagged, Not Removed",
            "detail": (
                "Method: IQR (lower = Q1 − 1.5×IQR, upper = Q3 + 1.5×IQR). "
                "Outliers are flagged with _outlier_flag columns. "
                "Deletion/capping avoided — outliers may represent genuine extreme events"
                + (" in this incident/operational dataset" if is_incident else "") + ". "
                + " | ".join(outlier_log)
            ),
        })

    # ── 13. TEXT NORMALIZATION + SIMPLE FEATURES ─────────────
    text_cols_present = [
        c for c in df_clean.columns if col_types.get(c, "") == "text"
    ]
    text_log = []
    for col in text_cols_present:
        has_ar = bool(
            df_clean[col].dropna().astype(str)
            .apply(lambda v: bool(ARABIC_RE.search(v))).any()
        )
        df_clean[col] = df_clean[col].apply(lambda v: _normalize_text(v, has_ar))
        df_clean[f"{col}_length"]     = df_clean[col].fillna("").astype(str).apply(len)
        df_clean[f"{col}_word_count"] = df_clean[col].fillna("").astype(str).apply(lambda v: len(v.split()))
        df_clean[f"{col}_lang"]       = df_clean[col].fillna("").astype(str).apply(_detect_language)
        norm_type = "Arabic+English bilingual" if has_ar else "English"
        text_log.append(f'"{col}" [{norm_type} normalization]')
    if text_log:
        audit.append({
            "step": "Text Normalization + Simple Feature Engineering",
            "detail": (
                ", ".join(text_log) +
                " | Arabic: diacritics removed, tatweel removed, أإآ→ا, ى→ي, ة→ه | "
                "English: lowercased, whitespace normalized | "
                "_length, _word_count, _lang features added per text column"
            ),
        })

    # ── CLEANED (HUMAN-READABLE) SNAPSHOT ────────────────────
    cleaned_df   = df_clean.copy()
    cleaned_cols = list(df_clean.columns)

    # ── 14. CATEGORICAL ENCODING (MODEL-READY COPY) ──────────
    model_df = df_clean.copy()
    enc_map, enc_log = {}, []

    cat_encode_cols = [
        c for c in cleaned_cols
        if col_types.get(c, "") in ("categorical", "bool")
        and c != target_col
        and c in model_df.columns
    ]

    for col in cat_encode_cols:
        n_u_now = model_df[col].nunique()
        strat = (
            "binary"    if n_u_now <= 2  else
            "onehot"    if n_u_now <= 10 else
            "label"     if n_u_now <= 50 else
            "frequency"
        )
        vals = model_df[col].astype(str)

        if strat == "binary":
            uniq = sorted(vals.dropna().unique())
            m = {v: i for i, v in enumerate(uniq)}
            model_df[col] = vals.map(m).fillna(0).astype(int)
            enc_map[col] = {"type": "binary", "map": m}
            enc_log.append(f'"{col}" → binary {m}')

        elif strat == "onehot":
            dummies = pd.get_dummies(model_df[col], prefix=col, drop_first=False)
            model_df = pd.concat([model_df.drop(columns=[col]), dummies], axis=1)
            enc_map[col] = {"type": "onehot", "categories": list(dummies.columns)}
            enc_log.append(f'"{col}" → one-hot ({n_u_now} categories → {len(dummies.columns)} columns)')

        elif strat == "label":
            le = LabelEncoder()
            model_df[col] = le.fit_transform(vals.fillna("__missing__"))
            enc_map[col] = {"type": "label", "classes": list(le.classes_)}
            enc_log.append(f'"{col}" → label encoding ({len(le.classes_)} classes)')

        else:  # frequency
            freq_map = vals.value_counts(normalize=True).to_dict()
            model_df[col] = vals.map(freq_map).fillna(0).round(5)
            enc_map[col] = {"type": "frequency", "top5": dict(list(freq_map.items())[:5])}
            enc_log.append(f'"{col}" → frequency encoding ({len(freq_map)} distinct values)')

    if enc_log:
        audit.append({
            "step": "Categorical Encoding (Model-Ready Dataset)",
            "detail": (
                "Rules: ≤2 unique → binary(0/1) | ≤10 → one-hot | ≤50 → label | >50 → frequency. "
                "Cleaned dataset remains human-readable. | " + " | ".join(enc_log)
            ),
        })

    # Ensure numeric types in model_df
    for col in model_df.columns:
        if col_types.get(col, "") in ("int", "float"):
            model_df[col] = pd.to_numeric(model_df[col], errors="coerce")

    # ── 15. TF-IDF + SVD (MODEL-READY ONLY) ─────────────────
    model_df, tfidf_log = _apply_tfidf_svd(model_df, text_cols_present, len(model_df))
    if tfidf_log:
        audit.append({
            "step": "TF-IDF Text Vectorization + Dimensionality Reduction",
            "detail": tfidf_log,
        })

    # ── READINESS CHECK (AFTER) ──────────────────────────────
    ra = _readiness_check(cleaned_df, "after_preprocessing")
    audit.append({
        "step": "Data Readiness Check (After Preprocessing)",
        "detail": (
            f"Status: {ra['status']} | {ra['n_rows']} rows × {ra['n_cols']} cols | "
            f"Max missing: {ra['max_missing_ratio']:.1%}"
            + (f" | ⚠ {'; '.join(ra['warnings'])}" if ra['warnings'] else " | All checks passed")
        ),
    })

    # ── SUMMARY ──────────────────────────────────────────────
    n_numeric = sum(1 for c in cleaned_cols if col_types.get(c, "") in ("int", "float"))
    n_cat     = sum(1 for c in cleaned_cols if col_types.get(c, "") in ("categorical", "bool"))
    n_text    = sum(1 for c in cleaned_cols if col_types.get(c, "") == "text")
    n_miss    = sum(1 for c in df.columns if df[c].isna().any())

    summary = {
        "original_rows":  original_shape[0],
        "original_cols":  original_shape[1],
        "cleaned_rows":   len(cleaned_df),
        "cleaned_cols":   len(cleaned_cols),
        "model_cols":     len(model_df.columns),
        "rows_removed":   original_shape[0] - len(cleaned_df),
        "cols_excluded":  len(excl_cols),
        "duplicates_removed": dup_removed,
        "n_numeric":      n_numeric,
        "n_cat":          n_cat,
        "n_text":         n_text,
        "n_datetime":     len(dt_in_work),
        "n_missing_cols": n_miss,
        "n_outlier_cols": len(outlier_log),
        "imputation_strategy": impute_strategy,
        "readiness_before": rb["status"],
        "readiness_after":  ra["status"],
        "is_incident_like": is_incident,
    }

    # ── CONFIG JSON ───────────────────────────────────────────
    arabic_count = sum(1 for s in col_stats.values() if s.get("has_arabic"))
    lang_profile = "arabic" if arabic_count > len(cleaned_cols) * 0.25 else "english"
    tfidf_applied = tfidf_log is not None and "skipped" not in str(tfidf_log)

    config = {
        "schema_version": "3.0",
        "generated_by":   "Basira Smart Preprocessor",
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "file_name":      file_name,
        "task_type":      task_type,
        "task_reason":    task_reason,
        "target_column":  target_col if task_type != "unsupervised" else None,
        "dataset_modality": (
            "bilingual" if n_text and lang_profile == "arabic"
            else "text_heavy" if n_text else "tabular"
        ),
        "language_profile": {"dominant": lang_profile, "arabic_cols": arabic_count},
        "col_types":           col_types,
        "excluded_id_cols":    id_cols,
        "excluded_empty_cols": empty_cols,
        "datetime_cols_extracted":   extracted_dt,
        "datetime_weekend_logic":    "Saudi (Friday=weekend, Saturday=weekend)",
        "imputation_strategy": {
            "numeric":          impute_strategy,
            "numeric_reason":   impute_reason,
            "categorical":      "mode",
            "text":             "missing_flag_only (no imputation)",
        },
        "encoding_strategy": {
            "rules": {
                "binary":    "unique_values ≤ 2 → 0/1 binary",
                "onehot":    "2 < unique_values ≤ 10 → one-hot encoding",
                "label":     "10 < unique_values ≤ 50 → label encoding",
                "frequency": "unique_values > 50 → frequency encoding",
            },
            "map": enc_map,
        },
        "text_processing": {
            "normalization": "bilingual (Arabic diacritics/tatweel/variants + English lowercase)",
            "simple_features": ["_length", "_word_count", "_lang"],
            "tfidf_applied": tfidf_applied,
            "tfidf_detail":  tfidf_log,
        },
        "outlier_handling": {
            "method": "IQR (Q1−1.5×IQR, Q3+1.5×IQR)",
            "action": "flag_only — _outlier_flag columns added",
            "deletion": False,
            "capping":  False,
            "reason":   "Outliers preserved — may represent genuine extreme events"
                        + (" in this incident/operational dataset" if is_incident else ""),
        },
        "repeated_ids": repeated_id_info,
        "is_incident_like": is_incident,
        "readiness": {"before": rb, "after": ra},
        "preprocessing_summary": summary,
        "audit_steps": [a["step"] for a in audit],
    }

    # ── COLUMN METADATA FOR UI ────────────────────────────────
    col_meta_ui = []
    for col in df.columns:
        st = col_stats.get(col, {})
        col_meta_ui.append({
            "name":      col,
            "type":      col_types.get(col, "unknown"),
            "null_pct":  st.get("null_pct", 0),
            "n_unique":  st.get("n_unique", 0),
            "has_arabic":    st.get("has_arabic", False),
            "outlier_count": st.get("outlier_count", 0),
            "top_values":    st.get("top_values", {}),
            "stats": {k: st.get(k) for k in ("min","max","mean","median","skew","iqr") if k in st},
            "encoding_strategy": st.get("encoding_strategy", ""),
            "is_target":   col == target_col,
            "is_id":       col_types.get(col, "") == "id",
            "is_datetime": col_types.get(col, "") == "datetime",
        })

    preview_cols = [c for c in df.columns if c not in excl_cols][:12]
    preview_rows = df[preview_cols].head(8).fillna("null").astype(str).to_dict(orient="records")

    return {
        "audit":       audit,
        "summary":     summary,
        "config":      config,
        "col_meta":    col_meta_ui,
        "preview":     {"cols": preview_cols, "rows": preview_rows},
        "task_type":   task_type,
        "task_reason": task_reason,
        "target_col":  target_col,
        "cleaned_df":  cleaned_df,
        "model_df":    model_df,
        "cleaned_cols":cleaned_cols,
    }


# ─────────────────────────────────────────────────────────────
# AUDIT REPORT HTML
# ─────────────────────────────────────────────────────────────

def build_audit_html(audit, summary, task, target, file_name):
    readiness_before = summary.get("readiness_before", "—")
    readiness_after  = summary.get("readiness_after", "—")
    imp_strategy     = summary.get("imputation_strategy", "—").upper()
    is_incident      = summary.get("is_incident_like", False)

    def badge(text, color="#0ea5e9"):
        return (f'<span style="display:inline-block;padding:2px 10px;border-radius:8px;'
                f'font-size:.75rem;font-weight:700;background:{color}22;color:{color}">{text}</span>')

    rb_color = "#ef4444" if readiness_before == "WARNING" else "#22c55e"
    ra_color = "#ef4444" if readiness_after  == "WARNING" else "#22c55e"

    rows = "".join(
        f'<tr><td style="font-weight:700;white-space:nowrap;color:#0ea5e9;'
        f'padding:10px 14px;border-bottom:1px solid #e2e8f0;vertical-align:top">{a["step"]}</td>'
        f'<td style="padding:10px 14px;border-bottom:1px solid #e2e8f0;'
        f'color:#334155;line-height:1.65">{a["detail"]}</td></tr>'
        for a in audit
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Preprocessing Audit — Basira</title>
<style>
  body{{font-family:'Segoe UI',Tahoma,sans-serif;background:#f0f4f8;color:#0f172a;padding:28px;}}
  .card{{background:#fff;border-radius:14px;padding:22px;margin-bottom:18px;box-shadow:0 1px 4px rgba(0,0,0,.08);}}
  h1{{color:#0ea5e9;margin-bottom:4px;font-size:1.5rem;}} h2{{margin-bottom:14px;font-size:1rem;color:#0f172a;}}
  table{{width:100%;border-collapse:collapse;}} th{{background:#0ea5e9;color:#fff;padding:9px 14px;text-align:left;}}
  .stat{{display:inline-block;margin:4px 10px 4px 0;font-size:.83rem;}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;margin-top:8px;}}
  .metric{{background:#f8fafc;border-radius:10px;padding:12px;text-align:center;}}
  .metric-val{{font-size:1.5rem;font-weight:800;color:#0ea5e9;}}
  .metric-lbl{{font-size:.75rem;color:#64748b;margin-top:2px;}}
</style></head><body>
<div class="card">
  <h1>📋 Preprocessing Audit Report</h1>
  <p style="color:#64748b;margin:6px 0">
    File: <strong>{file_name}</strong> &nbsp;|&nbsp;
    Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} &nbsp;|&nbsp;
    Task: {badge(task)} &nbsp;
    {f'Target: {badge(target, "#7c3aed")}' if target else ''} &nbsp;
    {'Incident Dataset: ' + badge("YES", "#f59e0b") if is_incident else ''}
  </p>
  <p style="margin:6px 0;color:#64748b">
    Readiness before: {badge(readiness_before, rb_color)} &nbsp;
    Readiness after: {badge(readiness_after, ra_color)} &nbsp;
    Imputation: {badge(imp_strategy, "#0891b2")}
  </p>
</div>
<div class="card">
  <h2>📊 Dataset Summary</h2>
  <div class="grid">
    <div class="metric"><div class="metric-val">{summary['original_rows']:,}</div><div class="metric-lbl">Original Rows</div></div>
    <div class="metric"><div class="metric-val">{summary['cleaned_rows']:,}</div><div class="metric-lbl">Cleaned Rows</div></div>
    <div class="metric"><div class="metric-val">{summary['cleaned_cols']}</div><div class="metric-lbl">Cleaned Columns</div></div>
    <div class="metric"><div class="metric-val">{summary['model_cols']}</div><div class="metric-lbl">Model-Ready Columns</div></div>
    <div class="metric"><div class="metric-val">{summary['duplicates_removed']}</div><div class="metric-lbl">Duplicates Removed</div></div>
    <div class="metric"><div class="metric-val">{summary['n_outlier_cols']}</div><div class="metric-lbl">Outlier Cols Flagged</div></div>
    <div class="metric"><div class="metric-val">{summary['n_datetime']}</div><div class="metric-lbl">Datetime Cols Expanded</div></div>
    <div class="metric"><div class="metric-val">{summary['n_text']}</div><div class="metric-lbl">Text Columns</div></div>
  </div>
</div>
<div class="card">
  <h2>🔧 Preprocessing Steps ({len(audit)} total)</h2>
  <table><thead><tr><th style="width:260px">Step</th><th>Details</th></tr></thead>
  <tbody>{rows}</tbody></table>
</div>
<div class="card" style="background:#0ea5e9;color:#fff;text-align:center;padding:14px">
  <p style="margin:0">Generated by <strong>Basira Smart Preprocessor v3.0</strong> — Python Backend Only</p>
</div>
</body></html>"""


# ─────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"]  = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


@app.route("/upload-process", methods=["OPTIONS"])
def options_upload():
    from flask import Response
    return Response(status=200)


@app.route("/health")
def health():
    return jsonify({"status": "ok", "version": "3.0"})


@app.route("/upload-process", methods=["POST"])
def upload_process():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file  = request.files["file"]
    fname = file.filename or "dataset"
    ext   = fname.rsplit(".", 1)[-1].lower()

    if ext not in ("csv", "xlsx", "xls"):
        return jsonify({"error": "Unsupported format. Use CSV or XLSX."}), 400

    uid     = uuid.uuid4().hex[:10]
    up_path = UPLOAD_DIR / f"{uid}_{fname}"
    file.save(str(up_path))

    try:
        if ext == "csv":
            df = None
            for enc in ("utf-8-sig", "utf-8", "cp1256", "latin-1"):
                try:
                    df = pd.read_csv(str(up_path), encoding=enc, low_memory=False)
                    break
                except UnicodeDecodeError:
                    continue
            if df is None:
                return jsonify({"error": "Could not decode CSV file."}), 400
        else:
            df = pd.read_excel(str(up_path), engine="openpyxl" if ext == "xlsx" else "xlrd")
    except Exception as e:
        return jsonify({"error": f"Could not read file: {e}"}), 400

    if df.empty or len(df) < 2:
        return jsonify({"error": "File is empty or has too few rows."}), 400

    df.columns = [str(c).strip() for c in df.columns]

    try:
        result = preprocess(df, fname)
    except Exception as e:
        import traceback
        return jsonify({"error": f"Preprocessing failed: {e}",
                        "traceback": traceback.format_exc()}), 500

    base = fname.rsplit(".", 1)[0]

    cleaned_path = OUTPUT_DIR / f"{uid}_cleaned_{base}.csv"
    result["cleaned_df"].to_csv(str(cleaned_path), index=False, encoding="utf-8-sig")

    model_path = OUTPUT_DIR / f"{uid}_model_{base}.csv"
    result["model_df"].to_csv(str(model_path), index=False, encoding="utf-8")

    audit_html = build_audit_html(
        result["audit"], result["summary"],
        result["task_type"], result["target_col"], fname
    )
    audit_path = OUTPUT_DIR / f"{uid}_audit_{base}.html"
    audit_path.write_text(audit_html, encoding="utf-8")

    config_path = OUTPUT_DIR / f"{uid}_config_{base}.json"
    config_path.write_text(
        json.dumps(result["config"], indent=2, ensure_ascii=False), encoding="utf-8"
    )

    def kb(p): return round(p.stat().st_size / 1024, 1)

    return jsonify({
        "status":      "ok",
        "task_type":   result["task_type"],
        "task_reason": result["task_reason"],
        "target_col":  result["target_col"],
        "summary":     result["summary"],
        "col_meta":    result["col_meta"],
        "audit":       result["audit"],
        "preview":     result["preview"],
        "downloads": {
            "cleaned": {"file": cleaned_path.name, "size_kb": kb(cleaned_path),
                        "rows": len(result["cleaned_df"]),
                        "cols": len(result["cleaned_df"].columns)},
            "model":   {"file": model_path.name,   "size_kb": kb(model_path),
                        "rows": len(result["model_df"]),
                        "cols": len(result["model_df"].columns)},
            "audit":   {"file": audit_path.name,   "size_kb": kb(audit_path)},
            "config":  {"file": config_path.name,  "size_kb": kb(config_path)},
        },
    })


@app.route("/download/<filename>")
def download_file(filename):
    safe_name = Path(filename).name
    file_path = OUTPUT_DIR / safe_name
    if not file_path.exists():
        abort(404)
    return send_file(str(file_path.resolve()), as_attachment=True, download_name=safe_name)


if __name__ == "__main__":
    print("🚀 Basira Smart Preprocessor v3.0 — http://localhost:5050")
    app.run(debug=True, host="0.0.0.0", port=5050)
