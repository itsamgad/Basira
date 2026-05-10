

from __future__ import annotations

import json
import math
import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

# ─── Constants ─────────────────────────────────────────────────────────────
RANDOM_STATE              = 42
INSIGHT_ENGINE_VERSION    = "insight-enhanced-v1.0"
MODEL_OUTPUT_BASE         = Path("saved_models")

# Deduplication / quality gates
MAX_INSIGHTS_PER_LAYER    = 5
MIN_INSIGHT_SCORE         = 0.25   # normalized 0-1 relevance score
PEARSON_NOTABLE           = 0.35
MIN_ROWS_STATS            = 15
TREND_WINDOW_FRAC         = 0.20
SKEW_NOTABLE              = 1.5
OUTLIER_PCT_NOTABLE       = 3.0    # %
FEATURE_TOP_N             = 12     # features considered for pattern analysis
CLUSTER_CONTRAST_MIN_DIFF = 0.30   # normalised mean difference to flag contrast


# =============================================================================
# Data-classes
# =============================================================================

@dataclass
class Insight:
    id:            str
    layer:         str   # "performance"|"feature"|"population"|"pattern"|
                         # "segment"|"anomaly"|"temporal"|"risk"
    severity:      str   # "critical"|"high"|"medium"|"low"|"info"
    title:         str
    narrative:     str   # polished analytical prose — presentation-ready
    evidence:      Dict[str, Any]
    metric_values: Dict[str, Any]
    recommended_action: str
    novelty_score: float  # 0-1, how non-obvious this finding is
    source:        str    # "supervised"|"unsupervised"|"combined"
    rank:          int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class InsightResult:
    insights:           List[Dict[str, Any]]
    narrative_summary:  str               # 3-5 sentence executive narrative
    layer_summaries:    Dict[str, str]    # one-liner per layer
    kpi_highlights:     List[Dict[str, Any]]
    trend_signals:      List[Dict[str, Any]]
    correlation_map:    List[Dict[str, Any]]
    segment_contrasts:  List[Dict[str, Any]]
    anomaly_profile:    Dict[str, Any]
    risk_flags:         List[Dict[str, Any]]
    opportunity_flags:  List[Dict[str, Any]]
    saved_model_dir:    str
    metadata:           Dict[str, Any]
    warnings:           List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(_json_safe(self.to_dict()), indent=indent, ensure_ascii=False)


# =============================================================================
# Error handling (consistent with supervised / unsupervised / rca engines)
# =============================================================================

@dataclass
class FailureReport:
    status:      str
    reason:      str
    details:     Dict[str, Any]
    suggestions: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


class BasiraInsightError(RuntimeError):
    def __init__(self, report: FailureReport) -> None:
        self.report = report
        super().__init__(report.reason)


def _insight_failure(reason: str, details: Dict[str, Any],
                     suggestions: List[str]) -> FailureReport:
    return FailureReport(status="failed", reason=reason,
                         details=_json_safe(details), suggestions=suggestions)


def _insight_raise(report: FailureReport) -> None:
    raise BasiraInsightError(report)


# =============================================================================
# Utility helpers (match project conventions)
# =============================================================================

def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, pd.DataFrame):
        return _json_safe(obj.to_dict(orient="records"))
    if isinstance(obj, pd.Series):
        return _json_safe(obj.to_list())
    if isinstance(obj, np.ndarray):
        return _json_safe(obj.tolist())
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 6)
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else round(obj, 6)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if obj is pd.NA:
        return None
    return obj if obj is None or isinstance(obj, (str, int, bool)) else str(obj)


def _write_json(path: Path, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_json_safe(data), f, indent=2, ensure_ascii=False)


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        v = float(val)
        return default if (math.isnan(v) or math.isinf(v)) else v
    except Exception:
        return default


def _severity_order(s: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}.get(s, 5)


def _novelty(base: float, boost: float = 0.0) -> float:
    return min(1.0, max(0.0, base + boost))


# =============================================================================
# Layer 1 — Performance Insights
# =============================================================================

def _performance_insights(sup_payload: Optional[Dict],
                            task_type: str) -> List[Insight]:
    insights: List[Insight] = []
    if not sup_payload:
        return insights

    reliability = sup_payload.get("reliability", {})
    test_metrics = sup_payload.get("chart_data", {}).get("summary_cards", [])
    # Flatten summary cards into a metric dict
    metrics: Dict[str, Any] = {}
    for card in test_metrics:
        if isinstance(card, dict) and "title" in card:
            metrics[card["title"]] = card.get("value")

    level = reliability.get("level", "Unknown")
    reason = reliability.get("reason", "")
    cautions = reliability.get("caution_notes", [])

    # ── Model performance headline ────────────────────────────────────────
    if task_type == "classification":
        f1m  = _safe_float(metrics.get("F1 Macro"))
        bal  = _safe_float(metrics.get("Balanced Accuracy"))
        acc  = _safe_float(metrics.get("Accuracy"))
        gap  = acc - bal  # imbalance proxy

        perf_phrase = (
            "exceptional class-level generalisation" if f1m >= 0.85 else
            "strong predictive performance"          if f1m >= 0.75 else
            "moderate but actionable performance"    if f1m >= 0.60 else
            "limited class-separation capability"
        )

        narrative = (
            f"The {sup_payload.get('best_model', 'selected model')} delivers {perf_phrase} "
            f"on this classification task: F1-macro = {f1m:.3f}, balanced accuracy = {bal:.3f}. "
        )
        if gap > 0.08:
            narrative += (
                f"A notable gap between raw accuracy ({acc:.3f}) and balanced accuracy ({bal:.3f}) "
                f"indicates the model is exploiting class-frequency imbalance — it performs better on the majority class than on rarer ones. "
            )
        narrative += reason

        insights.append(Insight(
            id="perf_classification_overview",
            layer="performance",
            severity="info" if level == "High" else "medium" if level == "Moderate" else "critical",
            title=f"Classification Performance: {level} Reliability",
            narrative=narrative.strip(),
            evidence={"level": level, "f1_macro": f1m, "balanced_accuracy": bal, "accuracy": acc},
            metric_values={"F1_macro": f1m, "balanced_accuracy": bal, "accuracy": acc},
            recommended_action=reliability.get("recommended_next_step", "Review per-class metrics."),
            novelty_score=_novelty(0.3),
            source="supervised",
        ))

        # ── F1 vs balanced accuracy gap (imbalance signal) ────────────────
        f1w = _safe_float(metrics.get("F1 Weighted", metrics.get("f1_weighted")))
        fi_gap = f1w - f1m
        if fi_gap > 0.10 and f1m > 0:
            insights.append(Insight(
                id="perf_imbalance_gap",
                layer="performance",
                severity="high",
                title="Macro vs Weighted F1 Gap Signals Minority Class Disadvantage",
                narrative=(
                    f"F1-weighted ({f1w:.3f}) exceeds F1-macro ({f1m:.3f}) by {fi_gap:.3f}. "
                    f"This gap is a diagnostic fingerprint of class imbalance: the model achieves higher "
                    f"scores by over-serving the majority class at the expense of minority classes. "
                    f"In practice, this means that rare categories — which may carry high operational "
                    f"importance — are underserved by the current model. "
                    f"A gap above 0.10 warrants targeted rebalancing before deployment."
                ),
                evidence={"f1_macro": f1m, "f1_weighted": f1w, "gap": round(fi_gap, 4)},
                metric_values={"f1_macro": f1m, "f1_weighted": f1w},
                recommended_action="Apply class_weight='balanced', SMOTE oversampling, or threshold calibration per class.",
                novelty_score=_novelty(0.55, 0.1 if fi_gap > 0.15 else 0),
                source="supervised",
            ))

    else:  # regression
        r2   = _safe_float(metrics.get("R2", metrics.get("R²")))
        rmse = _safe_float(metrics.get("RMSE"))
        mae  = _safe_float(metrics.get("MAE"))
        mape = _safe_float(metrics.get("MAPE_pct", metrics.get("MAPE")))

        rmse_mae_ratio = (rmse / mae) if mae > 0 else 1.0
        unexplained_pct = round((1 - max(r2, 0)) * 100, 1)

        narrative = (
            f"The regression model explains {round(max(r2, 0)*100, 1)}% of target variance "
            f"(R² = {r2:.3f}), leaving {unexplained_pct}% unexplained. "
        )
        if rmse_mae_ratio > 2.0:
            narrative += (
                f"The RMSE/MAE ratio of {rmse_mae_ratio:.2f} indicates heavy-tailed error: "
                f"a small number of extreme cases disproportionately inflate the RMSE. "
                f"The model is accurate for typical records but struggles at the distribution tails. "
            )
        elif rmse_mae_ratio < 1.2:
            narrative += (
                f"The RMSE/MAE ratio of {rmse_mae_ratio:.2f} is close to 1.0, indicating "
                f"a uniform error distribution without dominant outlier influence — a positive sign. "
            )

        insights.append(Insight(
            id="perf_regression_overview",
            layer="performance",
            severity="info" if r2 >= 0.80 else "medium" if r2 >= 0.55 else "critical",
            title=f"Regression Performance: R² = {r2:.3f} ({unexplained_pct}% Variance Unexplained)",
            narrative=narrative.strip(),
            evidence={"R2": r2, "RMSE": rmse, "MAE": mae, "MAPE_pct": mape, "RMSE_MAE_ratio": round(rmse_mae_ratio, 3)},
            metric_values={"R2": r2, "RMSE": rmse, "MAE": mae, "MAPE_pct": mape},
            recommended_action=(
                "If R² < 0.55, add domain-relevant features and test tree-based ensembles. "
                "If RMSE/MAE > 2.0, investigate high-residual records specifically."
            ),
            novelty_score=_novelty(0.3, 0.15 if rmse_mae_ratio > 2 else 0),
            source="supervised",
        ))

    return insights[:MAX_INSIGHTS_PER_LAYER]


# =============================================================================
# Layer 2 — Feature Insights
# =============================================================================

def _feature_insights(feature_importance: List[Dict[str, Any]],
                       task_type: str,
                       target_col: Optional[str]) -> List[Insight]:
    insights: List[Insight] = []
    if not feature_importance:
        return insights

    top = feature_importance[0]
    top_pct = _safe_float(top.get("impact_pct"), 0)

    # Compute cumulative concentration
    cum = 0.0
    n_for_80 = len(feature_importance)
    for i, fi in enumerate(feature_importance):
        cum += _safe_float(fi.get("impact_pct"), 0)
        if cum >= 80:
            n_for_80 = i + 1
            break

    # ── Driver hierarchy ─────────────────────────────────────────────────
    top_drivers = feature_importance[:min(3, len(feature_importance))]
    driver_names = [f.get("feature", "unknown") for f in top_drivers]
    driver_cum   = sum(_safe_float(f.get("impact_pct"), 0) for f in top_drivers)
    driver_count = len(top_drivers)
    driver_label = f"Top-{driver_count}" if driver_count > 1 else "Top Feature"
    driver_phrase = ", ".join(
        f"{f.get('feature', 'unknown')} ({_safe_float(f.get('impact_pct'), 0):.1f}%)"
        for f in top_drivers
    )

    insights.append(Insight(
        id="feature_driver_hierarchy",
        layer="feature",
        severity="info",
        title=f"Feature Driver Hierarchy: {driver_label} {'Explains' if driver_count == 1 else 'Explain'} {driver_cum:.1f}% of Signal",
        narrative=(
            f"The model's predictive signal is anchored by {driver_count} main feature {'driver' if driver_count == 1 else 'drivers'}: "
            f"{driver_phrase}. "
            f"Together they explain {driver_cum:.1f}% of what the model has learned about '{target_col or 'the target'}'. "
            f"{'This high concentration means the model is easy to interpret but brittle if any dominant feature degrades.' if driver_cum > 75 else 'The remaining signal is spread across supporting features, creating a more balanced predictor set.'}"
        ),
        evidence={"top_features": [{"feature": f.get("feature"), "impact_pct": f.get("impact_pct")} for f in top_drivers],
                  "cumulative_top_driver_pct": round(driver_cum, 2),
                  "driver_count": driver_count},
        metric_values={"top_feature": driver_names[0], "top_pct": top_pct, "top_driver_cum_pct": driver_cum},
        recommended_action=(
            f"Monitor {', '.join(driver_names)} for distributional drift in production. "
            "These are the features that matter most for model performance."
        ),
        novelty_score=_novelty(0.4, 0.15 if driver_cum > 80 else 0),
        source="supervised" if task_type else "combined",
    ))

    # ── Feature concentration warning ─────────────────────────────────────
    if n_for_80 <= 2 and len(feature_importance) > 5:
        insights.append(Insight(
            id="feature_concentration_risk",
            layer="feature",
            severity="high",
            title=f"High Signal Concentration: 80% Explained by Just {n_for_80} {'Feature' if n_for_80 == 1 else 'Features'}",
            narrative=(
                f"80% of the model's total predictive signal is concentrated in only {n_for_80} {'feature' if n_for_80 == 1 else 'features'} "
                f"out of {len(feature_importance)} available. This is a concentration red flag: "
                f"when a small number of features carry nearly all the signal, the model becomes "
                f"vulnerable to feature unavailability, measurement error, or distributional shift in those features. "
                f"Additionally, high concentration can mask data leakage — a single feature "
                f"encoding future information will dominate the importance ranking."
            ),
            evidence={"n_features_for_80pct": n_for_80, "total_features": len(feature_importance)},
            metric_values={"n_features_for_80pct": n_for_80},
            recommended_action=(
                f"Audit '{top['feature']}' for leakage. Test model performance without it (ablation). "
                "Consider diversifying the feature set to reduce single-point-of-failure risk."
            ),
            novelty_score=_novelty(0.65),
            source="supervised" if task_type else "combined",
        ))

    # ── Directional insight (for linear models) ───────────────────────────
    positive_drivers = [f for f in feature_importance[:8] if f.get("direction") == "positive"]
    negative_drivers = [f for f in feature_importance[:8] if f.get("direction") == "negative"]
    if positive_drivers and negative_drivers:
        insights.append(Insight(
            id="feature_directional_split",
            layer="feature",
            severity="info",
            title="Bidirectional Feature Effects Detected",
            narrative=(
                f"Among the top model drivers, {len(positive_drivers)} {'feature' if len(positive_drivers) == 1 else 'features'} push predictions "
                f"upward ({', '.join(f['feature'] for f in positive_drivers[:3])}) while "
                f"{len(negative_drivers)} suppress the predicted outcome "
                f"({', '.join(f['feature'] for f in negative_drivers[:3])}). "
                f"This bidirectional structure means the model is capturing trade-offs: "
                f"certain conditions amplify the outcome while others dampen it. "
                f"Operationally, this is useful for levers-and-controls analysis — you can identify "
                f"which features to maximise and which to minimise."
            ),
            evidence={"positive_drivers": [f["feature"] for f in positive_drivers[:3]],
                      "negative_drivers": [f["feature"] for f in negative_drivers[:3]]},
            metric_values={"n_positive": len(positive_drivers), "n_negative": len(negative_drivers)},
            recommended_action=(
                "Present the bidirectional driver structure in the dashboard as a 'lever chart'. "
                "Positive drivers are amplifiers; negative drivers are suppressors."
            ),
            novelty_score=_novelty(0.5),
            source="supervised",
        ))

    # ── Long-tail feature landscape ───────────────────────────────────────
    low_impact = [f for f in feature_importance if _safe_float(f.get("impact_pct"), 0) < 1.0]
    if len(low_impact) > len(feature_importance) * 0.5:
        insights.append(Insight(
            id="feature_long_tail",
            layer="feature",
            severity="low",
            title=f"{len(low_impact)} Features Contribute <1% Signal Each — Long Tail Detected",
            narrative=(
                f"{len(low_impact)} out of {len(feature_importance)} features each contribute "
                f"less than 1% of the total model signal individually. While their individual "
                f"contributions are small, collectively they represent "
                f"{sum(_safe_float(f.get('impact_pct'), 0) for f in low_impact):.1f}% of total signal. "
                f"This long-tail feature landscape is typical of datasets with many correlated or "
                f"redundant columns. These features could be candidates for pruning, which would "
                f"simplify the model and reduce the risk of overfitting on noise."
            ),
            evidence={"n_low_impact_features": len(low_impact),
                      "total_features": len(feature_importance)},
            metric_values={"long_tail_collective_pct": sum(_safe_float(f.get("impact_pct"), 0) for f in low_impact)},
            recommended_action=(
                "Apply feature selection (e.g., importance threshold of 1%) to remove low-signal features. "
                "Re-train and compare performance to assess the trade-off."
            ),
            novelty_score=_novelty(0.4),
            source="supervised" if task_type else "combined",
        ))

    return insights[:MAX_INSIGHTS_PER_LAYER]


# =============================================================================
# Layer 3 — Population / Distribution Insights
# =============================================================================

def _population_insights(df: Optional[pd.DataFrame],
                           target_col: Optional[str],
                           feature_importance: List[Dict[str, Any]]) -> List[Insight]:
    insights: List[Insight] = []
    if df is None or len(df) < MIN_ROWS_STATS:
        return insights

    important_cols = [f["feature"] for f in feature_importance[:FEATURE_TOP_N] if f.get("feature") in df.columns]
    if target_col and target_col in df.columns:
        important_cols = [target_col] + [c for c in important_cols if c != target_col]

    skewed: List[Dict] = []
    bimodal_hints: List[Dict] = []
    heavy_tails: List[Dict] = []

    for col in important_cols[:10]:
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(s) < MIN_ROWS_STATS:
            continue
        skw    = float(s.skew())
        kurt   = float(stats.kurtosis(s))
        q1, q3 = float(s.quantile(0.25)), float(s.quantile(0.75))
        iqr    = q3 - q1
        outlier_pct = 100 * float(((s < q1 - 3*iqr) | (s > q3 + 3*iqr)).mean()) if iqr > 0 else 0.0

        if abs(skw) > SKEW_NOTABLE:
            skewed.append({"col": col, "skew": round(skw, 3), "direction": "right" if skw > 0 else "left"})
        if kurt > 3.0:
            heavy_tails.append({"col": col, "kurtosis": round(kurt, 3), "outlier_pct": round(outlier_pct, 2)})
        # Bimodality hint: high std relative to range with roughly symmetric tails
        std = float(s.std())
        rng = float(s.max() - s.min())
        cv  = std / max(abs(float(s.mean())), 1e-9)
        if cv > 0.6 and abs(skw) < 0.5 and len(s) >= 40:
            bimodal_hints.append({"col": col, "cv": round(cv, 3), "skew": round(skw, 3)})

    # ── Skewness ────────────────────────────────────────────────────────
    if skewed:
        top_skewed = sorted(skewed, key=lambda x: abs(x["skew"]), reverse=True)[:3]
        names = [f"{s['col']} (skew={s['skew']})" for s in top_skewed]
        insights.append(Insight(
            id="pop_skewed_features",
            layer="population",
            severity="medium",
            title=f"{len(skewed)} {'Feature Shows' if len(skewed) == 1 else 'Features Show'} Significant Skewness",
            narrative=(
                f"{len(skewed)} features exhibit skewness above {SKEW_NOTABLE}: "
                f"{', '.join(names)}. "
                f"Skewed distributions cause linear and distance-based models to overweight "
                f"the tails — where extreme values live — and underweight typical values. "
                f"{'Right-skewed' if top_skewed[0]['direction'] == 'right' else 'Left-skewed'} features "
                f"in particular create disproportionate influence from rare high values, "
                f"which can simulate apparent importance that doesn't generalise. "
                f"Tree-based models are relatively robust to this, but normalisation is important "
                f"for distance-based algorithms and linear models."
            ),
            evidence={"skewed_features": top_skewed},
            metric_values={"n_skewed": len(skewed), "worst_skew": top_skewed[0]["skew"] if top_skewed else 0},
            recommended_action=(
                "Apply log or Box-Cox transformation to highly skewed features before "
                "feeding into linear models or distance-based clustering."
            ),
            novelty_score=_novelty(0.45, 0.1 if len(skewed) > 4 else 0),
            source="combined",
        ))

    # ── Heavy tails ─────────────────────────────────────────────────────
    if heavy_tails:
        top_ht = sorted(heavy_tails, key=lambda x: x["kurtosis"], reverse=True)[:2]
        insights.append(Insight(
            id="pop_heavy_tails",
            layer="population",
            severity="medium",
            title="Heavy-Tailed Distributions Detected in Key Features",
            narrative=(
                f"{len(heavy_tails)} {'feature exhibits' if len(heavy_tails) == 1 else 'features exhibit'} excess kurtosis (heavy tails), "
                f"notably: {', '.join(h['col'] + ' (kurt=' + str(h['kurtosis']) + ')' for h in top_ht)}. "
                f"Heavy tails mean the feature contains more extreme values than a normal distribution "
                f"would predict. These extremes have outsized influence on mean-based statistics "
                f"and RMSE. If outlier_pct is elevated ({top_ht[0]['outlier_pct']:.1f}% in the worst case), "
                f"these are genuine outlier concentrations that can distort model training. "
                f"They may represent system anomalies, data entry errors, or natural but rare events."
            ),
            evidence={"heavy_tail_features": top_ht},
            metric_values={"n_heavy_tail": len(heavy_tails)},
            recommended_action=(
                "Winsorise (cap) extreme values at the 1st/99th percentile or investigate outlier records. "
                "Use median-based statistics rather than mean for summary reporting."
            ),
            novelty_score=_novelty(0.5),
            source="combined",
        ))

    # ── Bimodality hint ──────────────────────────────────────────────────
    if bimodal_hints:
        top_bm = bimodal_hints[0]
        insights.append(Insight(
            id="pop_bimodality_hint",
            layer="population",
            severity="low",
            title=f"Possible Bimodal Distribution in '{top_bm['col']}'",
            narrative=(
                f"'{top_bm['col']}' has a high coefficient of variation ({top_bm['cv']:.2f}) "
                f"with near-zero skewness ({top_bm['skew']:.2f}), which is a common statistical "
                f"signature of a bimodal or multi-modal distribution — two overlapping sub-populations. "
                f"If confirmed, this suggests the column may encode two naturally distinct groups "
                f"(e.g., low-volume vs high-volume customers, day vs night measurements). "
                f"A bimodal feature is often a natural segmentation axis and may warrant "
                f"engineering into a binary indicator or segment label."
            ),
            evidence={"feature": top_bm["col"], "cv": top_bm["cv"], "skew": top_bm["skew"]},
            metric_values={"cv": top_bm["cv"]},
            recommended_action=(
                f"Plot the distribution of '{top_bm['col']}'. If bimodal, create a binary "
                f"feature encoding which mode each record belongs to."
            ),
            novelty_score=_novelty(0.65),
            source="combined",
        ))

    # ── Target variable profile ──────────────────────────────────────────
    if target_col and target_col in df.columns:
        tgt = pd.to_numeric(df[target_col], errors="coerce").dropna()
        if len(tgt) >= MIN_ROWS_STATS:
            tgt_skw  = float(tgt.skew())
            tgt_std  = float(tgt.std())
            tgt_mean = float(tgt.mean())
            cv_tgt   = tgt_std / max(abs(tgt_mean), 1e-9)
            if cv_tgt > 1.0:
                insights.append(Insight(
                    id="pop_target_high_variance",
                    layer="population",
                    severity="medium",
                    title=f"Target Variable '{target_col}' Has High Coefficient of Variation ({cv_tgt:.2f})",
                    narrative=(
                        f"The target variable '{target_col}' has a coefficient of variation of "
                        f"{cv_tgt:.2f} (std/mean = {tgt_std:.3f}/{tgt_mean:.3f}), indicating high "
                        f"relative spread. Targets with high variance are intrinsically harder to predict — "
                        f"the model must explain a wide range of outcomes with the available features. "
                        f"{'The target is also right-skewed (skew=' + str(round(tgt_skw, 2)) + '), ' + 'which can cause under-prediction at high values.' if tgt_skw > 1.0 else ''} "
                        f"This context is important when interpreting RMSE and MAE: high variance means "
                        f"even a 'good' model will show substantial absolute errors."
                    ),
                    evidence={"target": target_col, "cv": round(cv_tgt, 4),
                              "std": round(tgt_std, 4), "mean": round(tgt_mean, 4), "skew": round(tgt_skw, 4)},
                    metric_values={"cv": cv_tgt, "std": tgt_std, "mean": tgt_mean},
                    recommended_action=(
                        f"Report predictions alongside a confidence band. "
                        f"Consider normalising '{target_col}' or predicting on a log scale."
                    ),
                    novelty_score=_novelty(0.5),
                    source="supervised",
                ))

    return insights[:MAX_INSIGHTS_PER_LAYER]


# =============================================================================
# Layer 4 — Pattern Insights (Correlations, Non-linearity)
# =============================================================================

def _pattern_insights(df: Optional[pd.DataFrame],
                       feature_importance: List[Dict[str, Any]],
                       target_col: Optional[str]) -> List[Insight]:
    insights: List[Insight] = []
    if df is None or len(df) < MIN_ROWS_STATS:
        return insights

    imp_names = [f["feature"] for f in feature_importance[:FEATURE_TOP_N] if f.get("feature") in df.columns]
    num_df    = df[imp_names].select_dtypes(include=[np.number]) if imp_names else pd.DataFrame()
    if num_df.shape[1] < 2:
        return insights

    corr_matrix = num_df.corr()
    multicollinear_pairs: List[Dict] = []
    moderate_pairs:       List[Dict] = []

    cols = corr_matrix.columns.tolist()
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            r = _safe_float(corr_matrix.loc[a, b])
            if abs(r) >= 0.80:
                multicollinear_pairs.append({"a": a, "b": b, "r": round(r, 4)})
            elif abs(r) >= PEARSON_NOTABLE:
                moderate_pairs.append({"a": a, "b": b, "r": round(r, 4)})

    # ── Multicollinearity ────────────────────────────────────────────────
    if multicollinear_pairs:
        pair = multicollinear_pairs[0]
        insights.append(Insight(
            id="pattern_multicollinearity",
            layer="pattern",
            severity="high",
            title=f"Multicollinearity Detected: '{pair['a']}' and '{pair['b']}' (r = {pair['r']})",
            narrative=(
                f"'{pair['a']}' and '{pair['b']}' are highly correlated (r = {pair['r']}), "
                f"indicating near-redundant information. When two features are this correlated, "
                f"a model may arbitrarily split importance between them, making individual "
                f"feature importance scores unstable and unreliable — removing one could "
                f"cause the other's importance to jump significantly. "
                f"This also inflates model complexity without adding new predictive value. "
                f"A total of {len(multicollinear_pairs)} multicollinear pair(s) were detected "
                f"among the top features."
            ),
            evidence={"multicollinear_pairs": multicollinear_pairs[:4]},
            metric_values={"n_multicollinear_pairs": len(multicollinear_pairs), "max_r": pair["r"]},
            recommended_action=(
                f"Choose one of '{pair['a']}' or '{pair['b']}' to retain — prefer the one with "
                "clearer domain interpretability. Apply VIF analysis for a rigorous collinearity audit."
            ),
            novelty_score=_novelty(0.60),
            source="combined",
        ))

    # ── Feature-target non-linearity detection ────────────────────────────
    if target_col and target_col in df.columns:
        tgt = pd.to_numeric(df[target_col], errors="coerce")
        nonlinear_candidates: List[Dict] = []
        for col in imp_names[:8]:
            x = pd.to_numeric(df[col], errors="coerce")
            valid = x.notna() & tgt.notna()
            if valid.sum() < MIN_ROWS_STATS:
                continue
            try:
                linear_r, _  = stats.pearsonr(x[valid], tgt[valid])
                # Spearman captures monotonic non-linear rank correlation
                spear_r, _   = stats.spearmanr(x[valid], tgt[valid])
                nonlinearity = abs(spear_r) - abs(linear_r)
                if nonlinearity > 0.10 and abs(spear_r) >= PEARSON_NOTABLE:
                    nonlinear_candidates.append({
                        "feature": col,
                        "pearson_r": round(float(linear_r), 4),
                        "spearman_r": round(float(spear_r), 4),
                        "nonlinearity_lift": round(float(nonlinearity), 4),
                    })
            except Exception:
                continue

        nonlinear_candidates.sort(key=lambda x: x["nonlinearity_lift"], reverse=True)
        if nonlinear_candidates:
            top_nl = nonlinear_candidates[0]
            insights.append(Insight(
                id="pattern_nonlinearity",
                layer="pattern",
                severity="medium",
                title=f"Non-linear Relationship Detected: '{top_nl['feature']}' → '{target_col}'",
                narrative=(
                    f"'{top_nl['feature']}' shows a stronger monotonic (Spearman r = {top_nl['spearman_r']}) "
                    f"than linear relationship (Pearson r = {top_nl['pearson_r']}) with '{target_col}', "
                    f"with a non-linearity lift of {top_nl['nonlinearity_lift']:.3f}. "
                    f"This means the feature affects the target in a curved or threshold-based way — "
                    f"not a straight proportional increase. "
                    f"Linear models will systematically under-capture this relationship, "
                    f"while tree-based models handle it better. "
                    f"{'This may explain why a tree-based model outperformed linear alternatives.' if top_nl['nonlinearity_lift'] > 0.15 else ''}"
                ),
                evidence={"nonlinear_features": nonlinear_candidates[:3]},
                metric_values={"top_nonlinearity_lift": top_nl["nonlinearity_lift"]},
                recommended_action=(
                    f"Engineer binned or polynomial versions of '{top_nl['feature']}'. "
                    "Prefer tree-based or kernel-based models if non-linearity is pervasive."
                ),
                novelty_score=_novelty(0.65, 0.1 if top_nl["nonlinearity_lift"] > 0.20 else 0),
                source="supervised",
            ))

    # ── Moderate inter-feature correlations ──────────────────────────────
    if moderate_pairs and len(insights) < MAX_INSIGHTS_PER_LAYER:
        insights.append(Insight(
            id="pattern_feature_correlations",
            layer="pattern",
            severity="low",
            title=f"{len(moderate_pairs)} Moderate Feature-Pair Correlations Detected",
            narrative=(
                f"{len(moderate_pairs)} feature pairs among the top drivers show moderate "
                f"correlation (|r| ≥ {PEARSON_NOTABLE}). While not collinear enough to be redundant, "
                f"these relationships suggest shared underlying variance. "
                f"The strongest: {moderate_pairs[0]['a']} — {moderate_pairs[0]['b']} (r = {moderate_pairs[0]['r']}). "
                f"In ensemble tree models, this inter-feature correlation is handled implicitly; "
                f"in linear models, it can inflate variance of coefficient estimates."
            ),
            evidence={"moderate_pairs": moderate_pairs[:4]},
            metric_values={"n_moderate_pairs": len(moderate_pairs)},
            recommended_action="Review these pairs for potential interaction terms or dimensionality reduction.",
            novelty_score=_novelty(0.35),
            source="combined",
        ))

    return insights[:MAX_INSIGHTS_PER_LAYER]


# =============================================================================
# Layer 5 — Segment Insights (Cluster-based)
# =============================================================================

def _segment_insights(profiles: List[Dict[str, Any]],
                       quality_report: Dict[str, Any],
                       feature_importance: List[Dict[str, Any]]) -> List[Insight]:
    insights: List[Insight] = []
    if not profiles:
        return insights

    n_clusters  = len(profiles)
    sil         = _safe_float(quality_report.get("silhouette"), 0)
    imbalance   = _safe_float(quality_report.get("cluster_size_imbalance_ratio"), 1)
    level       = quality_report.get("level", "Unknown")

    sizes    = [_safe_float(p.get("size_pct"), 0) for p in profiles]
    largest  = max(profiles, key=lambda p: _safe_float(p.get("size_pct"), 0))
    smallest = min(profiles, key=lambda p: _safe_float(p.get("size_pct"), 0))

    # ── Segmentation quality overview ─────────────────────────────────────
    quality_phrase = {
        "High": "well-separated, high-confidence segments",
        "Moderate": "reasonably distinct but boundary-blurred segments",
        "Low": "weakly separated, exploratory segments",
    }.get(level, "segments of uncertain quality")

    insights.append(Insight(
        id="segment_quality_overview",
        layer="segment",
        severity="info" if level == "High" else "medium" if level == "Moderate" else "critical",
        title=f"Segmentation Produced {n_clusters} {'High-Quality' if level == 'High' else 'Moderate-Quality' if level == 'Moderate' else 'Exploratory'} Clusters (Silhouette = {sil:.3f})",
        narrative=(
            f"The data organises into {n_clusters} {quality_phrase}. "
            f"The Silhouette score of {sil:.3f} "
            f"{'confirms strong within-cluster cohesion and clear between-cluster separation — these segments are operationally trustworthy.' if sil >= 0.50 else 'indicates moderate cohesion — segments are distinguishable but some records lie close to boundaries, limiting precision of segment-level decisions.' if sil >= 0.25 else 'reveals weak cluster structure — records are not clearly differentiated, and segments should be treated as directional hypotheses rather than definitive groupings.'} "
            f"Cluster sizes range from {_safe_float(smallest.get('size_pct'), 0):.1f}% "
            f"to {_safe_float(largest.get('size_pct'), 0):.1f}% of total population."
        ),
        evidence={"n_clusters": n_clusters, "silhouette": sil, "level": level,
                  "size_range": [_safe_float(smallest.get("size_pct"), 0), _safe_float(largest.get("size_pct"), 0)]},
        metric_values={"silhouette": sil, "n_clusters": n_clusters, "imbalance_ratio": imbalance},
        recommended_action=(
            "Use cluster labels for segmented reporting and strategy differentiation. "
            "Validate profiles with domain experts before operational deployment."
        ),
        novelty_score=_novelty(0.35),
        source="unsupervised",
    ))

    # ── Dominant segment analysis ──────────────────────────────────────────
    dominant_pct = _safe_float(largest.get("size_pct"), 0)
    if dominant_pct > 50:
        insights.append(Insight(
            id="segment_dominant_cluster",
            layer="segment",
            severity="medium",
            title=f"Dominant Segment: '{largest.get('label')}' Covers {dominant_pct:.1f}% of Population",
            narrative=(
                f"Cluster '{largest.get('label')}' is the dominant segment, containing "
                f"{dominant_pct:.1f}% of all records. A segment this large represents the "
                f"'default' or baseline behaviour in the dataset. "
                f"The remaining {100 - dominant_pct:.1f}% is split across {n_clusters - 1} smaller clusters, "
                f"which likely represent deviations from the norm — whether high-value, at-risk, "
                f"or behaviourally distinct sub-populations. "
                f"For strategic purposes, the large cluster defines the standard — "
                f"all others should be studied as divergences from it."
            ),
            evidence={"cluster_label": largest.get("label"),
                      "size_pct": dominant_pct,
                      "distinctive_features": largest.get("distinctive_features", [])[:3]},
            metric_values={"dominant_cluster_pct": dominant_pct},
            recommended_action=(
                "Use the dominant segment as the baseline for comparison. "
                "Focus investment, monitoring, and strategic action on the smaller, differentiated clusters."
            ),
            novelty_score=_novelty(0.45),
            source="unsupervised",
        ))

    # ── Cluster contrast analysis ────────────────────────────────────────
    # Find the most contrasting pair on their top distinctive feature
    contrast_findings: List[Dict] = []
    if len(profiles) >= 2:
        feat_profiles: Dict[str, List[Tuple]] = {}
        for p in profiles:
            for d in p.get("distinctive_features", [])[:2]:
                f = d.get("feature")
                if f:
                    feat_profiles.setdefault(f, []).append(
                        (p.get("label"), d.get("cluster_mean", 0), d.get("global_mean", 0))
                    )
        for feat, entries in feat_profiles.items():
            if len(entries) >= 2:
                vals  = [_safe_float(e[1]) for e in entries]
                rng   = max(vals) - min(vals)
                gmean = _safe_float(entries[0][2], 1)
                norm  = rng / max(abs(gmean), 1e-9)
                if norm > CLUSTER_CONTRAST_MIN_DIFF:
                    contrast_findings.append({"feature": feat, "range": rng, "norm_range": norm, "entries": entries})

        if contrast_findings:
            top_contrast = sorted(contrast_findings, key=lambda x: x["norm_range"], reverse=True)[0]
            feat    = top_contrast["feature"]
            entries = top_contrast["entries"]
            high_seg = max(entries, key=lambda e: _safe_float(e[1]))
            low_seg  = min(entries, key=lambda e: _safe_float(e[1]))
            insights.append(Insight(
                id="segment_sharpest_contrast",
                layer="segment",
                severity="info",
                title=f"Sharpest Segment Contrast on '{feat}'",
                narrative=(
                    f"The greatest measurable difference between segments occurs on '{feat}': "
                    f"segment '{high_seg[0]}' averages {_safe_float(high_seg[1]):.3f} "
                    f"while segment '{low_seg[0]}' averages {_safe_float(low_seg[1]):.3f} "
                    f"— a {round(top_contrast['norm_range'] * 100, 1):.0f}% normalised difference relative to the global mean. "
                    f"This contrast is the most operationally significant distinction between groups: "
                    f"if '{feat}' has business meaning (volume, frequency, duration), "
                    f"these segments represent fundamentally different operating profiles."
                ),
                evidence={"feature": feat, "high_segment": high_seg[0],
                          "low_segment": low_seg[0], "norm_range": round(top_contrast["norm_range"], 4)},
                metric_values={"norm_range": top_contrast["norm_range"]},
                recommended_action=(
                    f"Label these segments explicitly using '{feat}' as the axis. "
                    "Build separate strategies, targets, or thresholds for the high and low segments."
                ),
                novelty_score=_novelty(0.55),
                source="unsupervised",
            ))

    return insights[:MAX_INSIGHTS_PER_LAYER]


# =============================================================================
# Layer 6 — Anomaly Insights
# =============================================================================

def _anomaly_insights(anomaly_report: Dict[str, Any],
                       profiles: List[Dict[str, Any]]) -> List[Insight]:
    insights: List[Insight] = []
    if not anomaly_report or anomaly_report.get("status") == "failed":
        return insights

    pct   = _safe_float(anomaly_report.get("anomaly_pct"), 0)
    count = int(anomaly_report.get("anomaly_count", 0))
    level = anomaly_report.get("level", "Low")
    feat_drivers = anomaly_report.get("feature_drivers", [])
    top_anomalies = anomaly_report.get("top_anomalies", [])

    # ── Anomaly rate insight ──────────────────────────────────────────────
    if count > 0:
        rate_narrative = (
            f"IsolationForest flagged {count} records ({pct:.1f}% of the dataset) as anomalous. "
        )
        if level == "High":
            rate_narrative += (
                f"A {pct:.1f}% anomaly rate is high — at this level, outliers are likely "
                f"distorting cluster profiles and inflating error metrics. "
                f"They should be removed or handled separately before drawing operational conclusions. "
            )
        elif level == "Moderate":
            rate_narrative += (
                f"A {pct:.1f}% anomaly rate is moderate — flagged records merit individual review "
                f"to determine whether they represent genuine extreme events or data quality issues. "
            )
        else:
            rate_narrative += "The anomaly rate is within an acceptable range and unlikely to distort overall patterns."

        if feat_drivers:
            top_driver = feat_drivers[0].get("feature", "")
            rate_narrative += (
                f" The primary anomaly driver is '{top_driver}', "
                f"which shows the highest mean absolute z-score among flagged records."
            )

        insights.append(Insight(
            id="anomaly_rate_overview",
            layer="anomaly",
            severity="high" if level == "High" else "medium" if level == "Moderate" else "info",
            title=f"Anomaly Detection: {pct:.1f}% of Records Flagged ({count} records)",
            narrative=rate_narrative.strip(),
            evidence={"anomaly_pct": pct, "anomaly_count": count, "level": level,
                      "feature_drivers": feat_drivers[:5]},
            metric_values={"anomaly_pct": pct, "anomaly_count": count},
            recommended_action=(
                "Isolate and investigate the top-scoring anomaly records. "
                "Determine whether they are data errors, genuine extreme events, or emerging patterns."
            ) if level != "Low" else "Monitor anomaly rate at refresh — currently acceptable.",
            novelty_score=_novelty(0.50, 0.2 if level == "High" else 0),
            source="unsupervised",
        ))

    # ── Anomaly feature driver insight ────────────────────────────────────
    if feat_drivers and count > 0:
        top_3_drivers = feat_drivers[:3]
        driver_text = ", ".join(
            f"'{d.get('feature')}' (mean |z| = {_safe_float(d.get('mean_abs_z_score'), 0):.2f})"
            for d in top_3_drivers
        )
        insights.append(Insight(
            id="anomaly_feature_drivers",
            layer="anomaly",
            severity="medium",
            title="Anomalous Records Share a Common Feature Deviation Profile",
            narrative=(
                f"Among all flagged anomalous records, the features with the highest average "
                f"deviation are: {driver_text}. "
                f"This shared deviation profile suggests these anomalies are not random — "
                f"they cluster along specific dimensions of the feature space. "
                f"Operationally, this means the anomaly pattern is structured and potentially "
                f"explainable: records deviate primarily in these dimensions, "
                f"which may correspond to a specific event type, process failure, or data condition."
            ),
            evidence={"feature_drivers": top_3_drivers, "n_anomalies": count},
            metric_values={"top_driver": top_3_drivers[0].get("feature") if top_3_drivers else None},
            recommended_action=(
                f"Filter for records where '{top_3_drivers[0].get('feature')}' exceeds 3σ "
                "and examine the business context of these records specifically."
            ),
            novelty_score=_novelty(0.60),
            source="unsupervised",
        ))

    # ── Cluster-anomaly co-location ───────────────────────────────────────
    if top_anomalies and profiles:
        cluster_counts: Dict[int, int] = {}
        for a in top_anomalies:
            cid = a.get("cluster_id")
            if cid is not None:
                cluster_counts[int(cid)] = cluster_counts.get(int(cid), 0) + 1

        if cluster_counts:
            most_common_cid = max(cluster_counts, key=lambda k: cluster_counts[k])
            mc_count        = cluster_counts[most_common_cid]
            mc_profile      = next((p for p in profiles if p.get("cluster_id") == most_common_cid), {})
            mc_label        = mc_profile.get("label", f"Cluster {most_common_cid}")

            if mc_count >= 2:
                insights.append(Insight(
                    id="anomaly_cluster_colocation",
                    layer="anomaly",
                    severity="medium",
                    title=f"Anomalies Disproportionately Located in Cluster '{mc_label}'",
                    narrative=(
                        f"{mc_count} of the top anomalous records are assigned to cluster '{mc_label}'. "
                        f"This co-location is analytically significant: it means the cluster's defining "
                        f"feature profile — which makes it distinctive — also correlates with anomalous "
                        f"behaviour. Either (a) the cluster is a genuine 'edge case' segment "
                        f"whose extreme characteristics are detected as anomalies, "
                        f"or (b) the clustering algorithm is grouping unresolved outliers together. "
                        f"In either case, this cluster deserves special scrutiny before being used "
                        f"for strategic decisions."
                    ),
                    evidence={"most_anomalous_cluster": mc_label,
                              "anomaly_count_in_cluster": mc_count,
                              "cluster_distribution": dict(cluster_counts)},
                    metric_values={"anomalies_in_hotspot": mc_count},
                    recommended_action=(
                        f"Inspect cluster '{mc_label}' records manually. "
                        "Determine if anomalies are concentrated due to a specific process, "
                        "data source, or time period."
                    ),
                    novelty_score=_novelty(0.60),
                    source="unsupervised",
                ))

    return insights[:MAX_INSIGHTS_PER_LAYER]


# =============================================================================
# Layer 7 — Temporal Insights
# =============================================================================

def _temporal_insights(df: Optional[pd.DataFrame],
                         feature_importance: List[Dict[str, Any]],
                         target_col: Optional[str]) -> List[Insight]:
    insights: List[Insight] = []
    if df is None or len(df) < 40:
        return insights

    window = max(int(len(df) * TREND_WINDOW_FRAC), 10)
    cols_to_check = [f["feature"] for f in feature_importance[:6] if f.get("feature") in df.columns]
    if target_col and target_col in df.columns:
        cols_to_check.insert(0, target_col)

    trend_signals: List[Dict] = []
    for col in cols_to_check[:6]:
        s = pd.to_numeric(df[col], errors="coerce")
        if s.notna().sum() < 20:
            continue
        try:
            # Mann-Kendall trend test proxy via Spearman correlation with index
            idx  = np.arange(len(s))
            valid = s.notna()
            sp_r, sp_p = stats.spearmanr(idx[valid], s[valid])
            if abs(sp_r) >= 0.25 and sp_p < 0.05:
                early_mean = float(s.iloc[:window].mean())
                late_mean  = float(s.iloc[-window:].mean())
                pct_change = (late_mean - early_mean) / max(abs(early_mean), 1e-9) * 100
                direction  = "upward" if sp_r > 0 else "downward"
                trend_signals.append({
                    "feature": col, "spearman_r": round(float(sp_r), 4),
                    "p_value": round(float(sp_p), 6),
                    "direction": direction, "pct_change": round(pct_change, 2),
                    "early_mean": round(early_mean, 4), "late_mean": round(late_mean, 4),
                    "is_target": col == target_col,
                })
        except Exception:
            continue

    trend_signals.sort(key=lambda x: abs(x["spearman_r"]), reverse=True)

    if trend_signals:
        top_trend = trend_signals[0]
        is_target = top_trend.get("is_target", False)
        severity  = "high" if (is_target and abs(top_trend["spearman_r"]) > 0.5) else "medium"
        insights.append(Insight(
            id="temporal_trend_detected",
            layer="temporal",
            severity=severity,
            title=f"{'Target Variable' if is_target else 'Feature'} Trend: '{top_trend['feature']}' is Drifting {top_trend['direction'].title()}",
            narrative=(
                f"'{top_trend['feature']}' shows a statistically significant {top_trend['direction']} "
                f"trend across the dataset (Spearman r = {top_trend['spearman_r']}, p = {top_trend['p_value']:.4f}). "
                f"From the first to the last {int(len(df) * TREND_WINDOW_FRAC * 100 / len(df))}% "
                f"of records, the mean has shifted from {top_trend['early_mean']:.4f} to "
                f"{top_trend['late_mean']:.4f} — a change of {top_trend['pct_change']:+.1f}%. "
                f"{'Since this is the target variable, this trend directly undermines model stability: a model trained on early data will systematically miss predictions on later data.' if is_target else 'Feature drift of this magnitude can silently degrade model performance as the distribution diverges from what the model learned.'}"
            ),
            evidence={"trend_signals": trend_signals[:3]},
            metric_values={"spearman_r": top_trend["spearman_r"], "pct_change": top_trend["pct_change"]},
            recommended_action=(
                "Implement time-based cross-validation to verify model stability over time. "
                "Retrain on the most recent data window and monitor drift continuously."
            ),
            novelty_score=_novelty(0.60, 0.15 if is_target else 0),
            source="combined",
        ))

        # Multi-signal trend insight
        multi_trend = [t for t in trend_signals if not t.get("is_target")][:3]
        if len(multi_trend) >= 2:
            names = [t["feature"] for t in multi_trend]
            insights.append(Insight(
                id="temporal_multi_feature_drift",
                layer="temporal",
                severity="medium",
                title=f"Concurrent Feature Drift: {len(multi_trend)} Features Trending Simultaneously",
                narrative=(
                    f"{len(multi_trend)} features show concurrent directional trends: "
                    f"{', '.join(names)}. Simultaneous drift across multiple features "
                    f"often signals a systemic change in the underlying data-generating process — "
                    f"such as a policy change, operational shift, or seasonal effect. "
                    f"When multiple input features drift together, the model's feature correlations "
                    f"may shift, causing compound degradation beyond what single-feature drift would produce."
                ),
                evidence={"drifting_features": multi_trend},
                metric_values={"n_drifting_features": len(multi_trend)},
                recommended_action=(
                    "Investigate the root cause of concurrent drift — is there a business event "
                    "or process change responsible? Update the model retraining schedule accordingly."
                ),
                novelty_score=_novelty(0.65),
                source="combined",
            ))

    return insights[:MAX_INSIGHTS_PER_LAYER]


# =============================================================================
# Drift helper (self-contained, no cross-engine import needed)
# =============================================================================

def _compute_temporal_drift_for_insights(
    df: pd.DataFrame,
    target_col: Optional[str],
    feature_importances: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Lightweight drift computation for the insight engine.
    Uses the same KS-test + normalised mean shift logic as the RCA engine
    but is self-contained so the insight engine has no import dependency
    on rca_engine_enhanced.
    """
    if len(df) < 40:
        return []

    window = max(int(len(df) * TREND_WINDOW_FRAC), 10)
    early  = df.iloc[:window]
    late   = df.iloc[-window:]

    cols = [f["feature"] for f in feature_importances[:8] if f.get("feature") in df.columns]
    if target_col and target_col in df.columns:
        cols.insert(0, target_col)

    signals: List[Dict[str, Any]] = []
    for col in cols[:8]:
        try:
            e = pd.to_numeric(early[col], errors="coerce").dropna()
            l = pd.to_numeric(late[col],  errors="coerce").dropna()
            if len(e) < 5 or len(l) < 5:
                continue
            stat, p = stats.ks_2samp(e, l)
            mean_shift   = float(l.mean() - e.mean())
            std_e        = float(e.std()) or 1.0
            norm_shift   = abs(mean_shift) / std_e
            if p < 0.05 and norm_shift > 0.30:
                signals.append({
                    "feature":           col,
                    "ks_statistic":      round(float(stat), 4),
                    "p_value":           round(float(p),    6),
                    "mean_early":        round(float(e.mean()), 4),
                    "mean_late":         round(float(l.mean()), 4),
                    "mean_shift":        round(mean_shift, 4),
                    "normalised_shift":  round(norm_shift, 4),
                    "direction":         "increased" if mean_shift > 0 else "decreased",
                    "severity":          "high" if norm_shift > 1.0 else "medium",
                    "is_target":         col == target_col,
                })
        except Exception:
            continue

    return sorted(signals, key=lambda x: x["normalised_shift"], reverse=True)


# =============================================================================
# Layer 8 — Risk & Opportunity Flags
# =============================================================================

def _risk_opportunity_insights(feature_importance: List[Dict[str, Any]],
                                 reliability: Dict[str, Any],
                                 anomaly_report: Dict[str, Any],
                                 drift_signals: List[Dict],
                                 quality_report: Optional[Dict]) -> Tuple[List[Insight], List[Insight]]:
    risks:         List[Insight] = []
    opportunities: List[Insight] = []

    level = reliability.get("level") or (quality_report or {}).get("level", "Unknown")

    # ── Leakage risk ──────────────────────────────────────────────────────
    if feature_importance:
        top     = feature_importance[0]
        top_pct = _safe_float(top.get("impact_pct"), 0)
        if top_pct > 50:
            risks.append(Insight(
                id="risk_leakage_warning",
                layer="risk",
                severity="critical",
                title=f"Data Leakage Risk: '{top['feature']}' Carries {top_pct:.1f}% of Model Signal",
                narrative=(
                    f"'{top['feature']}' alone accounts for {top_pct:.1f}% of the model's total predictive signal. "
                    f"Such extreme concentration is a strong indicator of potential data leakage — "
                    f"where a feature encodes information about the target that wouldn't be available "
                    f"at real-time prediction. Common leakage patterns include: a column derived from "
                    f"the target, a post-event label, or a proxy that captures outcome timing. "
                    f"If this feature is genuine, the model is fragile and will collapse if it ever "
                    f"becomes unavailable."
                ),
                evidence={"feature": top["feature"], "impact_pct": top_pct},
                metric_values={"impact_pct": top_pct},
                recommended_action=(
                    f"Audit '{top['feature']}' for leakage. Remove it and re-evaluate model performance. "
                    "If performance drops drastically, the feature was carrying illegitimate signal."
                ),
                novelty_score=_novelty(0.80),
                source="supervised",
            ))

    # ── Deployment readiness risk ─────────────────────────────────────────
    if level == "Low":
        risks.append(Insight(
            id="risk_deployment_not_ready",
            layer="risk",
            severity="critical",
            title="Model Not Deployment-Ready: Low Reliability Rating",
            narrative=(
                "The current model quality is rated 'Low', which means its outputs "
                "cannot support operational or financial decisions with confidence. "
                "Deploying a low-reliability model into production carries real risk: "
                "incorrect classifications or off-target predictions could lead to "
                "wasted resources, missed opportunities, or reputational damage. "
                "Before deployment, the model needs either more training data, stronger features, "
                "or a fundamental re-assessment of the prediction task."
            ),
            evidence={"reliability_level": level},
            metric_values={},
            recommended_action=(
                "Do not deploy. Revisit feature engineering, increase training data, "
                "or reconsider the problem framing. Use outputs for exploratory analysis only."
            ),
            novelty_score=_novelty(0.50),
            source="combined",
        ))

    # ── Drift-induced performance decay risk ─────────────────────────────
    if len(drift_signals) >= 2:
        risks.append(Insight(
            id="risk_drift_performance_decay",
            layer="risk",
            severity="high",
            title="Multi-Feature Drift Signals Performance Decay Risk",
            narrative=(
                f"{len(drift_signals)} features show significant distribution shift. "
                "When multiple input features drift simultaneously, the model's learnt "
                "feature relationships become misaligned with incoming data — a process called "
                "concept drift. Unlike single-feature anomalies, multi-feature drift "
                "is harder to detect via standard monitoring and tends to degrade performance "
                "gradually and silently. This risk escalates as the gap between training "
                "and production data grows."
            ),
            evidence={"n_drifting": len(drift_signals),
                      "drifting_features": [d.get("feature") for d in drift_signals[:3]]},
            metric_values={"n_drifting_features": len(drift_signals)},
            recommended_action=(
                "Establish a model performance monitoring dashboard. "
                "Set up automated retraining triggers based on drift thresholds."
            ),
            novelty_score=_novelty(0.65),
            source="combined",
        ))

    # ── Opportunity: strong model for decision automation ─────────────────
    if level == "High":
        opportunities.append(Insight(
            id="opp_decision_automation",
            layer="risk",
            severity="info",
            title="Opportunity: High Reliability Enables Decision Automation",
            narrative=(
                "The model has achieved High reliability — a signal that its predictions "
                "are consistent and well-calibrated enough to support decision automation. "
                "This creates an opportunity to move from manual review to automated "
                "rule-based or model-driven workflows for high-confidence predictions, "
                "reserving human review for the low-confidence or borderline cases. "
                "This threshold-based automation approach is standard in production ML systems."
            ),
            evidence={"reliability_level": level},
            metric_values={},
            recommended_action=(
                "Define a confidence threshold (e.g., top 20% of probability scores) for automated decisions. "
                "Build a human-in-the-loop pipeline for the remaining ambiguous predictions."
            ),
            novelty_score=_novelty(0.50),
            source="supervised",
        ))

    # ── Opportunity: anomaly investigation yields quick wins ─────────────
    anomaly_pct = _safe_float(anomaly_report.get("anomaly_pct"), 0)
    anomaly_lvl = anomaly_report.get("level", "Low")
    if anomaly_lvl in ("High", "Moderate") and anomaly_pct > 0:
        opportunities.append(Insight(
            id="opp_anomaly_investigation",
            layer="risk",
            severity="medium",
            title="Opportunity: Flagged Anomalies May Reveal Undetected Patterns",
            narrative=(
                f"The {anomaly_pct:.1f}% of records flagged as anomalous represent a concentrated "
                "pool of unusual behaviour that, if investigated, may yield disproportionate insights. "
                "In many operational datasets, anomalies correspond to the most interesting business "
                "events: fraud cases, exceptional performance, equipment failure precursors, or "
                "emerging customer segments. Treating them as noise discards their signal value. "
                "A structured anomaly review process can convert this risk into a discovery opportunity."
            ),
            evidence={"anomaly_pct": anomaly_pct, "anomaly_level": anomaly_lvl},
            metric_values={"anomaly_pct": anomaly_pct},
            recommended_action=(
                "Build a manual review queue for the top 20 anomaly records. "
                "Label them with root cause (error / extreme event / emerging pattern) "
                "and use this as future training data."
            ),
            novelty_score=_novelty(0.55),
            source="unsupervised",
        ))

    return risks[:3], opportunities[:3]


# =============================================================================
# Narrative summary builder
# =============================================================================

def _first_sentence(text: str) -> str:
    """Return a clean first sentence without duplicate punctuation."""
    if not text:
        return ""
    first = text.split(". ")[0].strip()
    return first.rstrip(". ") + "."

def _build_narrative_summary(insights: List[Insight],
                               strategy: str,
                               target_col: Optional[str],
                               level: str) -> str:
    """
    Compose a 4-6 sentence executive narrative synthesising the most
    important findings across all layers. Each sentence adds a distinct fact.
    """
    n_total    = len(insights)
    n_critical = sum(1 for i in insights if i.severity == "critical")
    n_high     = sum(1 for i in insights if i.severity == "high")

    focus_text = (
        f"predicting '{target_col}'" if target_col and strategy == "supervised"
        else "discovering hidden segments in the dataset" if strategy == "unsupervised"
        else "analysing the dataset"
    )

    opening = (
        f"Basira generated {n_total} insights across 8 analytical layers for the task of {focus_text}. "
        f"The overall analytical confidence is '{level}', with {n_critical} critical and {n_high} high-priority findings."
    )

    # Pick the most notable insight from performance, feature, and pattern layers
    perf_insight = next((i for i in insights if i.layer == "performance"), None)
    feat_insight = next((i for i in insights if i.layer == "feature" and "hierarchy" in i.id), None)
    risk_insight = next((i for i in insights if i.layer == "risk" and i.severity in ("critical", "high")), None)
    seg_insight  = next((i for i in insights if i.layer == "segment"), None)

    sentences = [opening]
    if perf_insight:
        sentences.append(_first_sentence(perf_insight.narrative))
    if feat_insight:
        sentences.append(_first_sentence(feat_insight.narrative))
    if seg_insight and strategy == "unsupervised":
        sentences.append(_first_sentence(seg_insight.narrative))
    if risk_insight:
        sentences.append(f"Most urgent risk: {risk_insight.title}. {_first_sentence(risk_insight.recommended_action)}")

    return " ".join(sentences)


# =============================================================================
# Layer summaries
# =============================================================================

def _build_layer_summaries(insights_by_layer: Dict[str, List[Insight]]) -> Dict[str, str]:
    summaries: Dict[str, str] = {}
    for layer, items in insights_by_layer.items():
        if not items:
            summaries[layer] = "No significant findings in this layer."
        else:
            top = items[0]
            summaries[layer] = f"{len(items)} finding(s). Key: {top.title}."
    return summaries


# =============================================================================
# KPI highlights builder
# =============================================================================

def _build_kpi_highlights(sup_payload: Optional[Dict],
                            unsu_payload: Optional[Dict]) -> List[Dict[str, Any]]:
    kpis: List[Dict[str, Any]] = []

    if sup_payload:
        rel = sup_payload.get("reliability", {})

        # Extract test metrics from chart_data.summary_cards (dashboard_payload path)
        metric_cards: Dict[str, Any] = {}
        for card in (sup_payload.get("chart_data", {}) or {}).get("summary_cards", []):
            if isinstance(card, dict) and "title" in card:
                metric_cards[card["title"]] = card.get("value")

        task_type = sup_payload.get("task_type", "classification")
        if task_type == "classification":
            primary_metric_label = "F1 Macro"
            primary_metric_value = metric_cards.get("F1 Macro") or metric_cards.get("f1_macro")
        else:
            primary_metric_label = "R²"
            primary_metric_value = metric_cards.get("R2") or metric_cards.get("R²")

        kpis += [
            {"label": "Model Reliability",     "value": rel.get("level", "N/A"),
             "source": "supervised"},
            {"label": "Confidence Score",       "value": f"{rel.get('confidence_score', 0)}%",
             "source": "supervised"},
            {"label": "Best Model",             "value": sup_payload.get("best_model", "N/A"),
             "source": "supervised"},
        ]
        if primary_metric_value is not None:
            kpis.append({"label": primary_metric_label, "value": primary_metric_value,
                         "source": "supervised"})

    if unsu_payload:
        qr = unsu_payload.get("quality") or unsu_payload.get("reliability") or {}
        ar = unsu_payload.get("anomaly_report", {})
        kpis += [
            {"label": "Clustering Quality",  "value": qr.get("level", "N/A"),
             "source": "unsupervised"},
            {"label": "Best Algorithm",      "value": (unsu_payload.get("best_algorithm")
                                                       or unsu_payload.get("best_model", "N/A")),
             "source": "unsupervised"},
            {"label": "Silhouette Score",    "value": qr.get("silhouette", "N/A"),
             "source": "unsupervised"},
            {"label": "Number of Clusters",  "value": qr.get("n_clusters", "N/A"),
             "source": "unsupervised"},
            {"label": "Anomaly Rate",        "value": f"{ar.get('anomaly_pct', 0)}%",
             "source": "unsupervised"},
        ]

    return kpis


# =============================================================================
# Core Insight Engine
# =============================================================================

class InsightEngine:
    def __init__(self, output_name: str = "insight_run") -> None:
        self.output_dir = MODEL_OUTPUT_BASE / output_name

    def run(
        self,
        supervised_payload:   Optional[Dict[str, Any]] = None,
        unsupervised_payload: Optional[Dict[str, Any]] = None,
        raw_df:               Optional[pd.DataFrame]   = None,
    ) -> InsightResult:
        """
        Run the full insight pipeline.
        At least one of supervised_payload or unsupervised_payload must be provided.
        Passing raw_df unlocks population, pattern, and temporal layers.
        """
        if supervised_payload is None and unsupervised_payload is None:
            _insight_raise(_insight_failure(
                "At least one of supervised_payload or unsupervised_payload must be provided.",
                {"supervised_provided": supervised_payload is not None,
                 "unsupervised_provided": unsupervised_payload is not None},
                [
                    "Pass SupervisedResult.dashboard_payload as supervised_payload.",
                    "Pass UnsupervisedResult.dashboard_payload as unsupervised_payload.",
                    "Use run_from_supervised_result() or run_from_unsupervised_result() for live objects.",
                ],
            ))

        warnings_list: List[str] = []
        if raw_df is None:
            warnings_list.append(
                "Raw dataframe was not provided; population, pattern, and temporal insights will be limited to model payload evidence."
            )

        # ── Extract key inputs ────────────────────────────────────────────
        sup    = supervised_payload   or {}
        unsu   = unsupervised_payload or {}

        task_type  = sup.get("task_type", "classification")
        target_col = sup.get("target_column")

        # ── Normalise supervised feature_importance ───────────────────────
        # dashboard_payload: feature_importance is inside rca_ready.top_drivers
        # rca_ready_payload: top_drivers at root
        # SupervisedResult object bridge: feature_importance at root (set by run_from_supervised_result)
        rca_sub_sup = sup.get("rca_ready", {}) or {}
        feature_imp_s = (
            sup.get("feature_importance")          # set by result bridge or insight payload
            or rca_sub_sup.get("top_drivers")      # dashboard_payload nested path
            or sup.get("top_drivers")              # rca_ready_payload flat path
            or []
        )

        # ── Normalise unsupervised feature_importance ─────────────────────
        feature_imp_u  = (
            unsu.get("feature_importance")         # dashboard_payload has this at root
            or (unsu.get("rca_ready") or {}).get("top_drivers")
            or unsu.get("top_drivers")
            or []
        )

        feature_imp    = feature_imp_s if feature_imp_s else feature_imp_u
        reliability    = sup.get("reliability", {})

        # quality_report: dashboard_payload uses "quality" key; rca_ready uses quality_level string
        quality_report = (
            unsu.get("quality")
            or {}
        )

        profiles       = (
            unsu.get("cluster_profiles")
            or (unsu.get("rca_ready") or {}).get("cluster_profiles")
            or []
        )
        anomaly_report = (
            unsu.get("anomaly_report")
            or (unsu.get("rca_ready") or {}).get("anomaly_report")
            or (unsu.get("rca_ready") or {}).get("anomaly_summary")  # backward compatibility for older saved payloads
            or {}
        )

        strategy = "supervised" if supervised_payload else "unsupervised"
        level    = reliability.get("level") or quality_report.get("level") or "Unknown"

        # ── Run all layers ────────────────────────────────────────────────
        all_insights: Dict[str, List[Insight]] = {}

        # L1 Performance
        try:
            all_insights["performance"] = _performance_insights(sup if sup else None, task_type)
        except Exception as e:
            warnings_list.append(f"Performance layer failed: {e}")
            all_insights["performance"] = []

        # L2 Feature
        try:
            all_insights["feature"] = _feature_insights(feature_imp, task_type, target_col)
        except Exception as e:
            warnings_list.append(f"Feature layer failed: {e}")
            all_insights["feature"] = []

        # L3 Population
        try:
            all_insights["population"] = _population_insights(raw_df, target_col, feature_imp)
        except Exception as e:
            warnings_list.append(f"Population layer failed: {e}")
            all_insights["population"] = []

        # L4 Pattern
        try:
            all_insights["pattern"] = _pattern_insights(raw_df, feature_imp, target_col)
        except Exception as e:
            warnings_list.append(f"Pattern layer failed: {e}")
            all_insights["pattern"] = []

        # L5 Segment
        try:
            all_insights["segment"] = _segment_insights(profiles, quality_report, feature_imp)
        except Exception as e:
            warnings_list.append(f"Segment layer failed: {e}")
            all_insights["segment"] = []

        # L6 Anomaly
        try:
            all_insights["anomaly"] = _anomaly_insights(anomaly_report, profiles)
        except Exception as e:
            warnings_list.append(f"Anomaly layer failed: {e}")
            all_insights["anomaly"] = []

        # L7 Temporal
        try:
            all_insights["temporal"] = _temporal_insights(raw_df, feature_imp, target_col)
        except Exception as e:
            warnings_list.append(f"Temporal layer failed: {e}")
            all_insights["temporal"] = []

        # L8 Risk & Opportunity
        drift_signals_list: List[Dict] = []
        if raw_df is not None and len(raw_df) >= 40:
            drift_signals_list = _compute_temporal_drift_for_insights(
                raw_df, target_col, feature_imp
            )

        try:
            risks, opps = _risk_opportunity_insights(
                feature_imp, reliability, anomaly_report,
                drift_signals_list, quality_report
            )
            all_insights["risk"] = risks + opps
        except Exception as e:
            warnings_list.append(f"Risk layer failed: {e}")
            all_insights["risk"] = []

        # ── Flatten, rank, deduplicate ────────────────────────────────────
        flat: List[Insight] = []
        for layer_insights in all_insights.values():
            flat.extend(layer_insights)

        flat = _deduplicate_insights(flat)
        flat.sort(key=lambda i: (_severity_order(i.severity), -i.novelty_score, i.layer))
        for idx, ins in enumerate(flat, 1):
            ins.rank = idx

        # ── Derived outputs ───────────────────────────────────────────────
        narrative_summary  = _build_narrative_summary(flat, strategy, target_col, level)
        layer_summaries    = _build_layer_summaries(all_insights)
        kpi_highlights     = _build_kpi_highlights(sup if sup else None, unsu if unsu else None)
        trend_signals      = _extract_trend_signals(all_insights.get("temporal", []))
        correlation_map    = _extract_correlation_map(all_insights.get("pattern", []))
        segment_contrasts  = _extract_segment_contrasts(all_insights.get("segment", []))
        anomaly_profile    = _extract_anomaly_profile(all_insights.get("anomaly", []))
        risk_flags         = [_json_safe(i.to_dict()) for i in all_insights.get("risk", []) if i.severity in ("critical", "high")]
        opportunity_flags  = [_json_safe(i.to_dict()) for i in all_insights.get("risk", []) if i.severity in ("info", "low", "medium") and "opp_" in i.id]

        result = InsightResult(
            insights=[_json_safe(i.to_dict()) for i in flat],
            narrative_summary=narrative_summary,
            layer_summaries=layer_summaries,
            kpi_highlights=kpi_highlights,
            trend_signals=trend_signals,
            correlation_map=correlation_map,
            segment_contrasts=segment_contrasts,
            anomaly_profile=anomaly_profile,
            risk_flags=risk_flags,
            opportunity_flags=opportunity_flags,
            saved_model_dir=str(self.output_dir),
            metadata=self._build_metadata(strategy, target_col, len(flat)),
            warnings=warnings_list,
        )
        self._save(result)
        return result

    # ─── Convenience bridges: accept live Result objects ────────────────

    def run_from_supervised_result(
        self,
        result: Any,
        unsupervised_result: Any = None,
        raw_df: Optional[pd.DataFrame] = None,
    ) -> "InsightResult":
        """
        Accept a live SupervisedResult object (and optionally a live
        UnsupervisedResult) directly — no JSON round-trip needed.

        Maps SupervisedResult.dashboard_payload fields plus the top-level
        feature_importance, reliability_report, task_type, and target_column
        attributes that are required but absent from rca_ready_payload.
        """
        sup_payload: Dict[str, Any] = {
            **(getattr(result, "dashboard_payload", {}) or {}),
            # Inject fields that dashboard_payload does not expose at root
            "feature_importance": getattr(result, "feature_importance", []),
            "task_type":          getattr(result, "task_type",          "classification"),
            "target_column":      getattr(result, "target_column",      None),
            "reliability":        getattr(result, "reliability_report", {}),
        }

        unsu_payload: Optional[Dict[str, Any]] = None
        if unsupervised_result is not None:
            unsu_payload = {
                **(getattr(unsupervised_result, "dashboard_payload", {}) or {}),
                "feature_importance": getattr(unsupervised_result, "feature_importance", []),
                "quality":            getattr(unsupervised_result, "cluster_quality_report", {}),
                "anomaly_report":     getattr(unsupervised_result, "anomaly_report", {}),
                "cluster_profiles":   getattr(unsupervised_result, "cluster_profiles", []),
            }

        return self.run(
            supervised_payload=sup_payload,
            unsupervised_payload=unsu_payload,
            raw_df=raw_df,
        )

    def run_from_unsupervised_result(
        self,
        result: Any,
        raw_df: Optional[pd.DataFrame] = None,
    ) -> "InsightResult":
        """
        Accept a live UnsupervisedResult object directly.

        Constructs the normalised unsupervised_payload from dashboard_payload
        plus the key attributes that are missing from it.
        """
        unsu_payload: Dict[str, Any] = {
            **(getattr(result, "dashboard_payload", {}) or {}),
            "feature_importance": getattr(result, "feature_importance", []),
            "quality":            getattr(result, "cluster_quality_report", {}),
            "anomaly_report":     getattr(result, "anomaly_report", {}),
            "cluster_profiles":   getattr(result, "cluster_profiles", []),
        }
        return self.run(
            supervised_payload=None,
            unsupervised_payload=unsu_payload,
            raw_df=raw_df,
        )

    def run_from_dir(
        self,
        model_dir: Path,
        raw_df_path: Optional[Path] = None,
    ) -> "InsightResult":
        """
        Load all saved payload JSONs from a prior engine output directory
        and run the insight pipeline.

        Accepts output directories from either SupervisedEngine or
        UnsupervisedEngine.  Merges dashboard_payload.json with
        rca_ready_payload.json so all fields are available.

        Parameters
        ----------
        model_dir   : Path to saved_models/<run_name> directory.
        raw_df_path : Optional path to original dataset (.csv / .xlsx).
        """
        model_dir = Path(model_dir)

        def _load(filename: str) -> Dict[str, Any]:
            p = model_dir / filename
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            return {}

        # Load files common to both strategies
        dashboard = _load("dashboard_payload.json")
        rca_ready = _load("rca_ready_payload.json")
        metadata  = _load("metadata.json")
        feat_imp  = _load("feature_importance.json")

        strategy = metadata.get("strategy", dashboard.get("strategy", "supervised"))

        # Load unsupervised-only files only when needed — supervised engine never writes them
        quality  = _load("cluster_quality_report.json") if strategy == "unsupervised" else {}
        anomaly  = _load("anomaly_report.json")         if strategy == "unsupervised" else {}
        profiles = _load("cluster_profiles.json")       if strategy == "unsupervised" else []

        raw_df: Optional[pd.DataFrame] = None
        if raw_df_path is not None:
            raw_df_path = Path(raw_df_path)
            if raw_df_path.exists():
                suffix = raw_df_path.suffix.lower()
                if suffix == ".csv":
                    raw_df = pd.read_csv(raw_df_path)
                elif suffix in (".xlsx", ".xls"):
                    raw_df = pd.read_excel(raw_df_path)

        if strategy == "unsupervised":
            # Merge all unsupervised artefacts
            unsu_payload: Dict[str, Any] = {
                **dashboard,
                "feature_importance": feat_imp if isinstance(feat_imp, list) else [],
                "quality":            quality,
                "anomaly_report":     anomaly,
                "cluster_profiles":   profiles if isinstance(profiles, list) else [],
            }
            return self.run(
                supervised_payload=None,
                unsupervised_payload=unsu_payload,
                raw_df=raw_df,
            )
        else:
            # Merge supervised artefacts
            sup_payload: Dict[str, Any] = {
                **dashboard,
                "feature_importance": feat_imp if isinstance(feat_imp, list) else [],
                "rca_ready":          rca_ready,
            }
            return self.run(
                supervised_payload=sup_payload,
                unsupervised_payload=None,
                raw_df=raw_df,
            )

    def _build_metadata(self, strategy: str, target_col: Optional[str],
                         n_insights: int) -> Dict[str, Any]:
        return {
            "basira_engine_version": INSIGHT_ENGINE_VERSION,
            "project":   "Basira",
            "phase":     "Phase 3 — Insight Generation",
            "strategy":  strategy,
            "target_column": target_col,
            "n_insights": n_insights,
            "created_at": datetime.now().isoformat(),
        }

    def _save(self, result: InsightResult) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        _write_json(self.output_dir / "insight_result.json",    result.to_dict())
        _write_json(self.output_dir / "insights.json",          result.insights)
        _write_json(self.output_dir / "kpi_highlights.json",    result.kpi_highlights)
        _write_json(self.output_dir / "risk_flags.json",        result.risk_flags)
        _write_json(self.output_dir / "opportunity_flags.json", result.opportunity_flags)
        _write_json(self.output_dir / "trend_signals.json",     result.trend_signals)
        _write_json(self.output_dir / "segment_contrasts.json", result.segment_contrasts)
        _write_json(self.output_dir / "insight_metadata.json",  result.metadata)
        # NOTE: insight_metadata.json is this engine's own run metadata.
        # run_from_dir reads the UPSTREAM engine's metadata.json (different file).
        (self.output_dir / "narrative_summary.txt").write_text(
            result.narrative_summary, encoding="utf-8"
        )


# =============================================================================
# Post-processing helpers
# =============================================================================

def _deduplicate_insights(insights: List[Insight]) -> List[Insight]:
    """Remove near-duplicate insights using a simple title-similarity gate."""
    seen_keys: set = set()
    unique: List[Insight] = []
    for ins in insights:
        key = ins.id[:40]
        if key not in seen_keys:
            seen_keys.add(key)
            unique.append(ins)
    return unique


def _extract_trend_signals(temporal_insights: List[Insight]) -> List[Dict[str, Any]]:
    signals: List[Dict] = []
    for ins in temporal_insights:
        ev = ins.evidence
        if "trend_signals" in ev:
            signals.extend(ev["trend_signals"])
    return signals[:6]


def _extract_correlation_map(pattern_insights: List[Insight]) -> List[Dict[str, Any]]:
    pairs: List[Dict] = []
    for ins in pattern_insights:
        if "multicollinear_pairs" in ins.evidence:
            pairs.extend(ins.evidence["multicollinear_pairs"])
        if "moderate_pairs" in ins.evidence:
            pairs.extend(ins.evidence["moderate_pairs"])
    return pairs[:10]


def _extract_segment_contrasts(segment_insights: List[Insight]) -> List[Dict[str, Any]]:
    contrasts: List[Dict] = []
    for ins in segment_insights:
        if "sharpest_contrast" in ins.id or "dominant" in ins.id:
            contrasts.append({"title": ins.title, "evidence": ins.evidence,
                              "narrative": ins.narrative[:200]})
    return contrasts


def _extract_anomaly_profile(anomaly_insights: List[Insight]) -> Dict[str, Any]:
    profile: Dict[str, Any] = {}
    for ins in anomaly_insights:
        if "rate_overview" in ins.id:
            profile["rate"] = ins.metric_values
            profile["summary"] = ins.narrative[:300]
        if "feature_drivers" in ins.id:
            profile["feature_drivers"] = ins.evidence.get("feature_drivers", [])
    return profile


# =============================================================================
# Smoke test
# =============================================================================

if __name__ == "__main__":
    np.random.seed(RANDOM_STATE)
    n = 300

    # Simulated supervised dashboard payload
    sup_payload = {
        "task_type": "regression",
        "target_column": "resolution_time",
        "best_model": "GradientBoosting",
        "reliability": {
            "level": "Moderate",
            "confidence_score": 68,
            "reason": "The model achieves R²=0.68 and MAPE=18.4%.",
            "caution_notes": ["Check residual patterns for high-value records."],
            "recommended_next_step": "Inspect high-residual records.",
        },
        "feature_importance": [
            {"feature": "ticket_priority", "impact_pct": 38.2, "importance_level": "Critical", "direction": "positive"},
            {"feature": "team_size",       "impact_pct": 19.1, "importance_level": "High",     "direction": "negative"},
            {"feature": "category_encoded","impact_pct": 13.4, "importance_level": "High",     "direction": "unknown"},
            {"feature": "created_hour",    "impact_pct":  8.7, "importance_level": "Medium",   "direction": "positive"},
            {"feature": "region_code",     "impact_pct":  4.2, "importance_level": "Medium",   "direction": "unknown"},
        ],
        "chart_data": {
            "summary_cards": [
                {"title": "R2", "value": 0.68},
                {"title": "RMSE", "value": 4.23},
                {"title": "MAE",  "value": 2.91},
                {"title": "MAPE_pct", "value": 18.4},
            ]
        },
    }

    # Simulated unsupervised dashboard payload
    unsu_payload = {
        "quality": {"level": "Moderate", "silhouette": 0.38, "davies_bouldin": 1.2,
                    "n_clusters": 4, "cluster_size_imbalance_ratio": 6.2},
        "cluster_profiles": [
            {"cluster_id": 0, "size": 140, "size_pct": 46.7, "label": "Higher ticket_priority segment",
             "distinctive_features": [{"feature": "ticket_priority", "direction": "higher", "difference": 1.2, "cluster_mean": 3.2, "global_mean": 2.0}]},
            {"cluster_id": 1, "size": 80,  "size_pct": 26.7, "label": "Lower team_size segment",
             "distinctive_features": [{"feature": "team_size", "direction": "lower", "difference": -2.1, "cluster_mean": 3.0, "global_mean": 5.1}]},
            {"cluster_id": 2, "size": 55,  "size_pct": 18.3, "label": "Cluster 2",
             "distinctive_features": []},
            {"cluster_id": 3, "size": 25,  "size_pct": 8.3,  "label": "Cluster 3",
             "distinctive_features": [{"feature": "created_hour", "direction": "higher", "difference": 6.0, "cluster_mean": 20.0, "global_mean": 14.0}]},
        ],
        "anomaly_report": {"status": "success", "level": "Moderate", "anomaly_pct": 6.3,
                           "anomaly_count": 19, "message": "Moderate anomaly rate detected.",
                           "feature_drivers": [{"feature": "ticket_priority", "mean_abs_z_score": 2.8},
                                               {"feature": "team_size", "mean_abs_z_score": 2.1}],
                           "top_anomalies": [{"row_position": 5, "source_row_index": 5, "cluster_id": 3, "anomaly_score": 0.42,
                                              "top_deviation_features": [{"feature": "ticket_priority", "abs_z_score": 3.1}]},
                                             {"row_position": 12, "source_row_index": 12, "cluster_id": 3, "anomaly_score": 0.38,
                                              "top_deviation_features": [{"feature": "team_size", "abs_z_score": 2.9}]}]},
        "feature_importance": [
            {"feature": "ticket_priority", "impact_pct": 41.0, "importance_level": "Critical"},
            {"feature": "team_size",       "impact_pct": 22.0, "importance_level": "High"},
            {"feature": "category_encoded","impact_pct": 15.0, "importance_level": "High"},
        ],
    }

    raw_df = pd.DataFrame({
        "ticket_priority":  np.random.choice([1, 2, 3, 4, 5], n, p=[0.05, 0.15, 0.40, 0.30, 0.10]),
        "team_size":        np.random.normal(5, 1.5, n).clip(1, 12),
        "category_encoded": np.random.randint(0, 6, n),
        "created_hour":     np.random.choice(range(24), n),
        "region_code":      np.random.randint(1, 6, n),
        "resolution_time":  np.random.exponential(8, n) + np.random.normal(0, 1, n),
    })

    result = InsightEngine("smoke_insights").run(
        supervised_payload=sup_payload,
        unsupervised_payload=unsu_payload,
        raw_df=raw_df,
    )

    print("=" * 65)
    print("INSIGHT ENGINE SMOKE TEST")
    print("=" * 65)
    print(result.narrative_summary)
    print(f"\nTotal insights: {len(result.insights)}")
    print("\nLayer summaries:")
    for layer, summary in result.layer_summaries.items():
        print(f"  {layer:12s}: {summary}")
    print(f"\nTop 5 insights by priority:")
    for ins in result.insights[:5]:
        print(f"  [{ins['severity'].upper():8s}] [{ins['layer']:12s}] {ins['title']}")
    print(f"\nRisk flags : {len(result.risk_flags)}")
    print(f"Opportunity: {len(result.opportunity_flags)}")
    print(f"Saved      → {result.saved_model_dir}")
