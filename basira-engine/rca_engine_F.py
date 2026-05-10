

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

# ─── Project constants (mirror supervised / unsupervised engines) ──────────
RANDOM_STATE = 42
RCA_ENGINE_VERSION = "rca-enhanced-v1.0"
MODEL_OUTPUT_BASE = Path("saved_models")

# Thresholds
ZSCORE_ANOMALY_THRESHOLD      = 2.5   # z-score to flag a feature value as extreme
PEARSON_STRONG_THRESHOLD      = 0.55  # |r| above this = strong correlation
PEARSON_MODERATE_THRESHOLD    = 0.30  # |r| above this = moderate correlation
FEATURE_DOMINANCE_THRESHOLD   = 35.0  # % — single feature dominance alert
CONFUSION_RATE_HIGH           = 0.25  # confusion-pair error rate = high concern
RESIDUAL_SKEW_THRESHOLD       = 0.75  # |skew| above this = systematic bias
DRIFT_WINDOW_FRACTION         = 0.20  # fraction of data used per drift window
MIN_ROWS_FOR_CORRELATION      = 15
MIN_ROWS_FOR_DRIFT             = 40


# =============================================================================
# Data-classes
# =============================================================================

@dataclass
class RCAFinding:
    """A single, self-contained root-cause finding."""
    id:             str
    category:       str          # "model_error" | "data_quality" | "feature_signal" |
                                 # "anomaly" | "class_confusion" | "cluster_structure" |
                                 # "interaction" | "drift" | "leakage_risk"
    severity:       str          # "critical" | "high" | "medium" | "low" | "info"
    title:          str
    explanation:    str          # human-readable, analytical, precise
    evidence:       Dict[str, Any]
    causal_chain:   List[str]    # ordered steps: trigger → mechanism → observed effect
    recommended_action: str
    confidence:     str          # "high" | "moderate" | "low"
    source:         str          # "supervised" | "unsupervised" | "combined"
    rank:           int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RCAResult:
    """Full RCA output, ready for dashboard and export."""
    strategy:           str          # "supervised" | "unsupervised"
    target_column:      Optional[str]
    executive_summary:  str
    findings:           List[Dict[str, Any]]
    causal_map:         List[Dict[str, Any]]  # feature → outcome relationships
    interaction_effects: List[Dict[str, Any]]
    drift_signals:      List[Dict[str, Any]]
    data_quality_flags: List[Dict[str, Any]]
    leakage_warnings:   List[Dict[str, Any]]
    priority_actions:   List[str]
    confidence_level:   str
    saved_model_dir:    str
    metadata:           Dict[str, Any]
    warnings:           List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(_json_safe(self.to_dict()), indent=indent, ensure_ascii=False)


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


class BasiraRCAError(RuntimeError):
    def __init__(self, report: FailureReport) -> None:
        self.report = report
        super().__init__(report.reason)


# =============================================================================
# Utility helpers
# =============================================================================

def _failure(reason: str, details: Dict[str, Any], suggestions: List[str]) -> FailureReport:
    return FailureReport(status="failed", reason=reason,
                         details=_json_safe(details), suggestions=suggestions)


def _raise(report: FailureReport) -> None:
    raise BasiraRCAError(report)


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


def _severity_rank(s: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}.get(s, 5)


# =============================================================================
# Core analytical primitives
# =============================================================================

def _compute_correlations(df: pd.DataFrame, target_col: Optional[str] = None,
                           top_n: int = 20) -> List[Dict[str, Any]]:
    """
    Compute Pearson correlations between all numeric pairs (or vs a target).
    Returns ranked list of strong/moderate correlation findings.
    """
    num_df = df.select_dtypes(include=[np.number]).dropna(axis=1, how="all")
    if num_df.shape[1] < 2 or len(num_df) < MIN_ROWS_FOR_CORRELATION:
        return []

    results: List[Dict[str, Any]] = []

    if target_col and target_col in num_df.columns:
        # Feature-vs-target correlations
        y = num_df[target_col]
        for col in num_df.columns:
            if col == target_col:
                continue
            x = num_df[col]
            valid = x.notna() & y.notna()
            if valid.sum() < MIN_ROWS_FOR_CORRELATION:
                continue
            try:
                r, p = stats.pearsonr(x[valid], y[valid])
                if math.isnan(r):
                    continue
                abs_r = abs(r)
                if abs_r >= PEARSON_MODERATE_THRESHOLD:
                    strength = "strong" if abs_r >= PEARSON_STRONG_THRESHOLD else "moderate"
                    direction = "positive" if r > 0 else "negative"
                    results.append({
                        "feature_a": col,
                        "feature_b": target_col,
                        "pearson_r": round(r, 4),
                        "abs_r": round(abs_r, 4),
                        "p_value": round(p, 6),
                        "strength": strength,
                        "direction": direction,
                        "type": "feature_target",
                    })
            except Exception:
                continue
    else:
        # Pairwise inter-feature correlations
        cols = num_df.columns.tolist()
        for i, a in enumerate(cols):
            for b in cols[i + 1:]:
                valid = num_df[a].notna() & num_df[b].notna()
                if valid.sum() < MIN_ROWS_FOR_CORRELATION:
                    continue
                try:
                    r, p = stats.pearsonr(num_df.loc[valid, a], num_df.loc[valid, b])
                    if math.isnan(r):
                        continue
                    abs_r = abs(r)
                    if abs_r >= PEARSON_MODERATE_THRESHOLD:
                        strength = "strong" if abs_r >= PEARSON_STRONG_THRESHOLD else "moderate"
                        results.append({
                            "feature_a": a,
                            "feature_b": b,
                            "pearson_r": round(r, 4),
                            "abs_r": round(abs_r, 4),
                            "p_value": round(p, 6),
                            "strength": strength,
                            "direction": "positive" if r > 0 else "negative",
                            "type": "feature_feature",
                        })
                except Exception:
                    continue

    results.sort(key=lambda x: x["abs_r"], reverse=True)
    return results[:top_n]


def _detect_feature_interactions(df: pd.DataFrame, target_col: str,
                                  top_features: List[str], top_n: int = 8
                                  ) -> List[Dict[str, Any]]:
    """
    Detect interaction effects: pairs of top features whose joint deviation
    from mean is disproportionately associated with target extremes.
    Uses a simple variance-explained proxy via grouped R² lift.
    """
    num_df = df.select_dtypes(include=[np.number]).copy()
    if target_col not in num_df.columns or len(num_df) < MIN_ROWS_FOR_CORRELATION:
        return []

    feat_cols = [f for f in top_features if f in num_df.columns][:6]
    if len(feat_cols) < 2:
        return []

    y = num_df[target_col].dropna()
    interactions: List[Dict[str, Any]] = []

    for i, a in enumerate(feat_cols):
        for b in feat_cols[i + 1:]:
            sub = num_df[[a, b, target_col]].dropna()
            if len(sub) < MIN_ROWS_FOR_CORRELATION:
                continue
            try:
                # Interaction term
                sub = sub.copy()
                sub["_interaction"] = (
                    (sub[a] - sub[a].mean()) / max(sub[a].std(), 1e-9) *
                    (sub[b] - sub[b].mean()) / max(sub[b].std(), 1e-9)
                )
                r_a, _  = stats.pearsonr(sub[a],            sub[target_col])
                r_b, _  = stats.pearsonr(sub[b],            sub[target_col])
                r_int,_ = stats.pearsonr(sub["_interaction"], sub[target_col])

                lift = abs(r_int) - max(abs(r_a), abs(r_b))
                if lift > 0.05 and abs(r_int) >= PEARSON_MODERATE_THRESHOLD:
                    interactions.append({
                        "feature_a": a,
                        "feature_b": b,
                        "r_a_target": round(r_a, 4),
                        "r_b_target": round(r_b, 4),
                        "r_interaction_target": round(r_int, 4),
                        "interaction_lift": round(lift, 4),
                        "strength": "strong" if abs(r_int) >= PEARSON_STRONG_THRESHOLD else "moderate",
                    })
            except Exception:
                continue

    interactions.sort(key=lambda x: x["interaction_lift"], reverse=True)
    return interactions[:top_n]


def _detect_temporal_drift(df: pd.DataFrame, target_col: Optional[str],
                            feature_importances: List[Dict[str, Any]]
                            ) -> List[Dict[str, Any]]:
    """
    Use the row index as a proxy for time (valid when data is ordered
    chronologically).  Compares first-N vs last-N rows for the top
    features and the target to detect distributional drift.
    """
    if len(df) < MIN_ROWS_FOR_DRIFT:
        return []

    window = max(int(len(df) * DRIFT_WINDOW_FRACTION), 10)
    early = df.iloc[:window]
    late  = df.iloc[-window:]

    top_feat_names = [f["feature"] for f in feature_importances[:8] if f.get("feature") in df.columns]
    cols_to_check  = top_feat_names.copy()
    if target_col and target_col in df.columns:
        cols_to_check.append(target_col)

    drift_signals: List[Dict[str, Any]] = []
    for col in cols_to_check:
        if col not in df.columns:
            continue
        try:
            e = pd.to_numeric(early[col], errors="coerce").dropna()
            l = pd.to_numeric(late[col],  errors="coerce").dropna()
            if len(e) < 5 or len(l) < 5:
                continue
            stat, p = stats.ks_2samp(e, l)
            mean_shift = float(l.mean() - e.mean())
            std_e = float(e.std()) or 1.0
            normalised_shift = abs(mean_shift) / std_e

            if p < 0.05 and normalised_shift > 0.30:
                severity = "high" if normalised_shift > 1.0 else "medium"
                direction = "increased" if mean_shift > 0 else "decreased"
                drift_signals.append({
                    "feature": col,
                    "ks_statistic": round(float(stat), 4),
                    "p_value": round(float(p), 6),
                    "mean_early": round(float(e.mean()), 4),
                    "mean_late":  round(float(l.mean()),  4),
                    "mean_shift": round(mean_shift, 4),
                    "normalised_shift": round(normalised_shift, 4),
                    "direction": direction,
                    "severity": severity,
                })
        except Exception:
            continue

    drift_signals.sort(key=lambda x: x["normalised_shift"], reverse=True)
    return drift_signals


def _detect_data_quality_issues(df: pd.DataFrame,
                                  feature_importances: List[Dict[str, Any]]
                                  ) -> List[Dict[str, Any]]:
    """
    Examine the raw dataframe for data-quality patterns that can cause
    model misbehaviour: high missingness, near-zero variance, extreme
    skewness, and outlier concentration in important features.
    """
    issues: List[Dict[str, Any]] = []
    important_feats = {f["feature"]: f.get("impact_pct", 0) for f in feature_importances[:15]}

    for col in df.columns:
        s = df[col]
        miss_pct = round(100 * s.isna().mean(), 2)
        if miss_pct > 20:
            severity = "high" if miss_pct > 50 else "medium"
            issues.append({
                "column": col,
                "issue_type": "high_missingness",
                "severity": severity,
                "detail": f"{miss_pct:.1f}% of values are missing.",
                "impact": "high" if col in important_feats else "low",
                "recommendation": (
                    "Impute with domain-aware strategy or flag as a binary "
                    "'is_missing' feature to preserve information."
                ),
            })

        if pd.api.types.is_numeric_dtype(s):
            num = pd.to_numeric(s, errors="coerce").dropna()
            if len(num) < 5:
                continue
            std = float(num.std())
            if std == 0:
                issues.append({
                    "column": col,
                    "issue_type": "zero_variance",
                    "severity": "medium",
                    "detail": "Column has constant value — carries no information.",
                    "impact": "high" if col in important_feats else "low",
                    "recommendation": "Drop this column before modelling.",
                })
                continue

            skewness = float(num.skew())
            if abs(skewness) > 3.0:
                issues.append({
                    "column": col,
                    "issue_type": "extreme_skewness",
                    "severity": "medium",
                    "detail": f"Skewness = {skewness:.2f}. Distribution is heavily tailed.",
                    "impact": "high" if col in important_feats else "low",
                    "recommendation": (
                        "Apply log or Box-Cox transformation to reduce skew before "
                        "feeding to linear models or distance-based algorithms."
                    ),
                })

            # Outlier concentration via IQR
            q1, q3 = float(num.quantile(0.25)), float(num.quantile(0.75))
            iqr = q3 - q1
            if iqr > 0:
                outlier_pct = round(100 * ((num < q1 - 3 * iqr) | (num > q3 + 3 * iqr)).mean(), 2)
                if outlier_pct > 3.0:
                    severity = "high" if outlier_pct > 10 else "medium"
                    issues.append({
                        "column": col,
                        "issue_type": "outlier_concentration",
                        "severity": severity,
                        "detail": f"{outlier_pct:.1f}% of values fall beyond 3×IQR.",
                        "impact": "high" if col in important_feats else "low",
                        "recommendation": (
                            "Cap outliers (winsorise) or investigate whether they "
                            "represent genuine extreme events vs data-entry errors."
                        ),
                    })

    return sorted(issues, key=lambda x: (x["impact"] != "high", _severity_rank(x["severity"])))


def _analyse_residuals(residuals: np.ndarray,
                        y_pred: np.ndarray,
                        feature_matrix: Optional[pd.DataFrame] = None
                        ) -> Dict[str, Any]:
    """
    Deep residual analysis for regression RCA.
    Detects: systematic bias, heteroscedasticity, skew, outlier drivers.
    """
    res   = np.asarray(residuals, dtype=float)
    pred  = np.asarray(y_pred,    dtype=float)
    valid = np.isfinite(res) & np.isfinite(pred)
    res, pred = res[valid], pred[valid]

    if len(res) < 5:
        return {"status": "insufficient_data"}

    mean_res  = float(np.mean(res))
    std_res   = float(np.std(res))
    skewness  = float(stats.skew(res))
    kurtosis  = float(stats.kurtosis(res))
    abs_res   = np.abs(res)

    # Shapiro-Wilk normality test (capped at 5000 samples)
    sw_stat, sw_p = None, None
    try:
        sample = res if len(res) <= 5000 else np.random.default_rng(RANDOM_STATE).choice(res, 5000, replace=False)
        sw_stat, sw_p = stats.shapiro(sample)
        sw_stat, sw_p = round(float(sw_stat), 4), round(float(sw_p), 4)
    except Exception:
        pass

    # Heteroscedasticity: correlation between |residual| and predicted value
    hetero_r, hetero_p = None, None
    try:
        hetero_r, hetero_p = stats.pearsonr(pred, abs_res)
        hetero_r = round(float(hetero_r), 4)
        hetero_p = round(float(hetero_p), 6)
    except Exception:
        pass

    # Bias direction
    if abs(mean_res) > 0.1 * std_res:
        bias = "systematic_overprediction" if mean_res < 0 else "systematic_underprediction"
    else:
        bias = "unbiased"

    # Quadrant analysis: where do errors concentrate?
    median_pred = float(np.median(pred))
    high_pred_err = float(abs_res[pred >= median_pred].mean()) if (pred >= median_pred).sum() > 0 else 0
    low_pred_err  = float(abs_res[pred <  median_pred].mean()) if (pred <  median_pred).sum() > 0 else 0
    error_concentration = "high_value_range" if high_pred_err > 1.3 * low_pred_err else \
                          "low_value_range"  if low_pred_err  > 1.3 * high_pred_err else "uniform"

    # Feature-residual correlations (if feature matrix available)
    feature_residual_correlations: List[Dict[str, Any]] = []
    if feature_matrix is not None and len(feature_matrix) == len(res):
        num_cols = feature_matrix.select_dtypes(include=[np.number]).columns.tolist()
        for col in num_cols[:20]:
            try:
                x = pd.to_numeric(feature_matrix[col], errors="coerce")
                valid_mask = x.notna()
                if valid_mask.sum() < MIN_ROWS_FOR_CORRELATION:
                    continue
                r, p = stats.pearsonr(x[valid_mask], res[valid_mask])
                if abs(r) >= PEARSON_MODERATE_THRESHOLD and not math.isnan(r):
                    feature_residual_correlations.append({
                        "feature": col,
                        "pearson_r": round(float(r), 4),
                        "p_value": round(float(p), 6),
                        "interpretation": (
                            f"Higher '{col}' values associate with "
                            f"{'over-prediction' if r < 0 else 'under-prediction'}."
                        ),
                    })
            except Exception:
                continue
        feature_residual_correlations.sort(key=lambda x: abs(x["pearson_r"]), reverse=True)

    return {
        "status": "success",
        "n_samples": int(len(res)),
        "mean_residual": round(mean_res, 6),
        "std_residual": round(std_res, 6),
        "skewness": round(skewness, 4),
        "kurtosis": round(kurtosis, 4),
        "bias_type": bias,
        "error_concentration": error_concentration,
        "shapiro_wilk": {"statistic": sw_stat, "p_value": sw_p,
                         "normal": sw_p is not None and sw_p > 0.05},
        "heteroscedasticity": {
            "pearson_r_abs_res_vs_pred": hetero_r,
            "p_value": hetero_p,
            "detected": hetero_r is not None and abs(hetero_r) > 0.30,
        },
        "high_pred_mean_abs_error": round(high_pred_err, 6),
        "low_pred_mean_abs_error":  round(low_pred_err, 6),
        "feature_residual_correlations": feature_residual_correlations[:10],
    }


def _analyse_confusion_matrix(conf_mat: List[List[int]],
                                label_classes: List[str],
                                clf_report: Optional[Dict]
                                ) -> Dict[str, Any]:
    """
    Deep confusion matrix analysis:
    - Most-confused pairs with confusion rate
    - Asymmetric confusion (A→B vs B→A) to distinguish one-way ambiguity
    - Per-class error rate and precision/recall imbalance
    """
    arr = np.asarray(conf_mat, dtype=float)
    n = arr.shape[0]
    findings: List[Dict[str, Any]] = []

    row_totals = arr.sum(axis=1)  # true counts per class

    pairs: List[Dict[str, Any]] = []
    for i in range(n):
        for j in range(n):
            if i == j or arr[i, j] == 0:
                continue
            true_label = label_classes[i] if i < len(label_classes) else str(i)
            pred_label = label_classes[j] if j < len(label_classes) else str(j)
            confusion_count = int(arr[i, j])
            confusion_rate  = float(arr[i, j] / max(row_totals[i], 1))
            # Is the confusion asymmetric?
            reverse_count   = int(arr[j, i]) if j < n and i < n else 0
            asymmetry_ratio = confusion_count / max(reverse_count, 1)

            pairs.append({
                "actual":            true_label,
                "predicted":         pred_label,
                "confusion_count":   confusion_count,
                "confusion_rate":    round(confusion_rate, 4),
                "reverse_count":     reverse_count,
                "asymmetry_ratio":   round(float(asymmetry_ratio), 2),
                "one_directional":   asymmetry_ratio > 3.0,
                "severity": "high" if confusion_rate > CONFUSION_RATE_HIGH else "medium",
            })

    pairs.sort(key=lambda x: (x["confusion_count"]), reverse=True)

    # Per-class error rate
    per_class: List[Dict[str, Any]] = []
    for i in range(n):
        total_true = int(row_totals[i])
        correct    = int(arr[i, i])
        error_rate = round(1 - correct / max(total_true, 1), 4)
        label      = label_classes[i] if i < len(label_classes) else str(i)

        prec, rec, f1 = None, None, None
        if clf_report:
            cr = clf_report.get(label, {})
            prec = cr.get("precision")
            rec  = cr.get("recall")
            f1   = cr.get("f1-score")

        per_class.append({
            "class":      label,
            "total_true": total_true,
            "correct":    correct,
            "error_rate": error_rate,
            "precision":  round(float(prec), 4) if prec is not None else None,
            "recall":     round(float(rec),  4) if rec  is not None else None,
            "f1_score":   round(float(f1),   4) if f1   is not None else None,
            "weakness_type": (
                "low_recall"    if rec  is not None and float(rec)  < 0.5 else
                "low_precision" if prec is not None and float(prec) < 0.5 else
                "balanced_weakness" if f1 is not None and float(f1) < 0.5 else
                "acceptable"
            ),
        })

    per_class.sort(key=lambda x: x["error_rate"], reverse=True)

    return {
        "confused_pairs":      pairs[:8],
        "per_class_analysis":  per_class,
        "total_misclassified": int(arr.sum() - np.trace(arr)),
        "overall_error_rate":  round(float((arr.sum() - np.trace(arr)) / max(arr.sum(), 1)), 4),
    }


def _analyse_cluster_anomalies(anomaly_report: Dict[str, Any],
                                 profiles: List[Dict[str, Any]],
                                 feature_importance: List[Dict[str, Any]]
                                 ) -> List[Dict[str, Any]]:
    """
    Cross-reference anomaly records with cluster profiles to identify
    *which* cluster properties make anomalies structurally distinctive.
    """
    top_anomalies = anomaly_report.get("top_anomalies", [])
    if not top_anomalies:
        return []

    # Map cluster_id → profile label and distinctive features
    cluster_map: Dict[int, Dict] = {}
    for p in profiles:
        cid = p.get("cluster_id")
        if cid is not None:
            cluster_map[int(cid)] = p

    enriched: List[Dict[str, Any]] = []
    for a in top_anomalies[:15]:
        cid = a.get("cluster_id")
        profile = cluster_map.get(int(cid), {}) if cid is not None else {}
        cluster_label = profile.get("label", f"Cluster {cid}")

        # Identify which deviated features overlap with this cluster's distinctives
        anomaly_deviated = {d["feature"] for d in a.get("top_deviation_features", [])}
        cluster_distinctives = {d["feature"] for d in profile.get("distinctive_features", [])}
        overlap = anomaly_deviated & cluster_distinctives
        novelty = anomaly_deviated - cluster_distinctives  # deviated outside cluster pattern

        enriched.append({
            "row_position":         a.get("row_position"),
            "source_row_index":     a.get("source_row_index"),
            "cluster_id":           cid,
            "cluster_label":        cluster_label,
            "anomaly_score":        a.get("anomaly_score"),
            "top_deviation_features": a.get("top_deviation_features", []),
            "cluster_pattern_overlap": sorted(overlap),
            "novel_deviations":     sorted(novelty),
            "interpretation": (
                f"Record deviates from cluster '{cluster_label}' pattern "
                f"({'cluster-consistent deviation' if overlap and not novelty else 'novel deviation pattern not explained by cluster profile'}). "
                f"Primary drivers: {', '.join(list(anomaly_deviated)[:3])}."
            ),
        })

    return enriched


# =============================================================================
# RCA Finding generators
# =============================================================================

def _find_feature_signal_causes(feature_importance: List[Dict[str, Any]],
                                  correlations: List[Dict[str, Any]],
                                  task_type: str,
                                  target_col: Optional[str]
                                  ) -> List[RCAFinding]:
    """Convert feature importance + correlation evidence into causal findings."""
    findings: List[RCAFinding] = []
    if not feature_importance:
        return findings

    top = feature_importance[0]
    top_pct = _safe_float(top.get("impact_pct"), 0.0)

    # ── Single-feature dominance ──────────────────────────────────────────
    if top_pct >= FEATURE_DOMINANCE_THRESHOLD:
        severity = "critical" if top_pct >= 55 else "high"
        findings.append(RCAFinding(
            id="feature_dominance",
            category="feature_signal",
            severity=severity,
            title=f"Feature '{top['feature']}' Dominates the Model",
            explanation=(
                f"'{top['feature']}' accounts for {top_pct:.1f}% of the model's total predictive signal — "
                f"{'more than half' if top_pct >= 50 else 'a dominant share'} of what the model has learned. "
                f"This concentration has two possible root causes: "
                f"(1) '{top['feature']}' is a genuine causal driver of '{target_col or 'the outcome'}', "
                f"or (2) it is acting as a proxy or leakage variable that encodes information the model "
                f"should not be able to see at prediction time. "
                f"In either case, the model's decisions are highly sensitive to this single variable, "
                f"making it fragile if the feature distribution shifts."
            ),
            evidence={"feature": top["feature"], "impact_pct": top_pct,
                      "importance_level": top.get("importance_level"),
                      "direction": top.get("direction")},
            causal_chain=[
                f"'{top['feature']}' carries concentrated signal",
                "Model assigns disproportionate weight to this feature",
                "Predictions become brittle under feature shift or unavailability",
                "Operational risk increases if this feature is unreliable or delayed",
            ],
            recommended_action=(
                f"Audit '{top['feature']}' for data leakage (is it derived from the target or "
                f"recorded after the outcome?). If valid, monitor for feature drift in production. "
                f"Consider regularisation or ablation tests to measure performance without it."
            ),
            confidence="high",
            source="supervised",
        ))

    # ── Top driver summary ────────────────────────────────────────────────
    if len(feature_importance) >= 2:
        top_drivers = feature_importance[:min(3, len(feature_importance))]
        cum_pct = sum(_safe_float(f.get("impact_pct"), 0) for f in top_drivers)
        names = [f.get("feature", "unknown") for f in top_drivers]
        driver_label = f"Top-{len(top_drivers)}" if len(top_drivers) > 1 else "Top Feature"
        findings.append(RCAFinding(
            id="top_driver_cluster",
            category="feature_signal",
            severity="medium",
            title=f"{driver_label} Features Explain {cum_pct:.1f}% of Model Signal",
            explanation=(
                f"The strongest predictor(s) — {', '.join(names)} — collectively account for "
                f"{cum_pct:.1f}% of the model's signal. "
                f"This means the model's output can be largely explained by monitoring these variable(s). "
                f"{'The signal is highly concentrated, which can limit generalisation.' if cum_pct > 80 else 'The remaining signal is distributed across many features, suggesting a balanced predictor set.'}"
            ),
            evidence={"top_features": [{"feature": f.get("feature"), "impact_pct": f.get("impact_pct")} for f in top_drivers],
                      "cumulative_pct": cum_pct,
                      "driver_count": len(top_drivers)},
            causal_chain=[
                f"Primary driver '{names[0]}' sets the dominant signal direction",
                f"Supporting driver(s): {', '.join(names[1:]) if len(names) > 1 else 'none detected'}",
                f"Outcome is primarily determined by {cum_pct:.0f}% of available signal",
            ],
            recommended_action=(
                f"Focus data collection, validation, and monitoring effort on {', '.join(names)}. "
                "Build operational alerts for unexpected shifts in these features."
            ),
            confidence="high",
            source="supervised",
        ))

    # ── Correlation-based causality hints ────────────────────────────────
    for corr in correlations[:3]:
        if corr.get("type") != "feature_target":
            continue
        findings.append(RCAFinding(
            id=f"correlation_{corr['feature_a']}",
            category="feature_signal",
            severity="low",
            title=f"Statistical Relationship: '{corr['feature_a']}' ↔ Target",
            explanation=(
                f"'{corr['feature_a']}' shows a {corr['strength']} {corr['direction']} "
                f"linear relationship with '{target_col}' (Pearson r = {corr['pearson_r']}, "
                f"p = {corr['p_value']:.4f}). "
                f"{'This confirms the model weight assigned to this feature.' if corr['strength'] == 'strong' else 'This moderate relationship may interact with other features.'}"
            ),
            evidence=corr,
            causal_chain=[
                f"'{corr['feature_a']}' varies systematically with '{target_col}'",
                f"Direction: {corr['direction']} — {'increases in this feature correspond to increases in the outcome' if corr['direction'] == 'positive' else 'increases in this feature correspond to decreases in the outcome'}",
            ],
            recommended_action=(
                f"Validate domain-level causality: does '{corr['feature_a']}' mechanistically "
                f"influence '{target_col}', or is this a spurious correlation?"
            ),
            confidence="moderate",
            source="supervised",
        ))

    return findings


def _find_leakage_and_proxy_risks(feature_importance: List[Dict[str, Any]],
                                      target_col: Optional[str]) -> List[RCAFinding]:
    """Flag features that may encode target leakage or post-outcome proxy signal."""
    findings: List[RCAFinding] = []
    if not feature_importance or not target_col:
        return findings

    target_norm = str(target_col).lower().replace("_", "").replace("-", "")
    leakage_terms = [
        "target", "label", "outcome", "result", "status", "resolved", "closed",
        "final", "prediction", "actual", "score", "class", "category"
    ]
    for fi in feature_importance[:10]:
        feat = str(fi.get("feature", ""))
        feat_norm = feat.lower().replace("_", "").replace("-", "")
        impact = _safe_float(fi.get("impact_pct"), 0)
        name_overlap = target_norm and (target_norm in feat_norm or feat_norm in target_norm)
        suspicious_term = any(t in feat_norm for t in leakage_terms)
        extreme_dominance = impact >= 50
        if name_overlap or (suspicious_term and impact >= 25) or extreme_dominance:
            severity = "critical" if extreme_dominance or name_overlap else "high"
            findings.append(RCAFinding(
                id=f"leakage_proxy_risk_{feat_norm[:30] or 'feature'}",
                category="leakage_risk",
                severity=severity,
                title=f"Potential Leakage or Proxy Risk in '{feat}'",
                explanation=(
                    f"'{feat}' contributes {impact:.1f}% of the model signal and has a name or dominance pattern "
                    f"that may indicate target leakage or proxy leakage for '{target_col}'. Leakage occurs when a feature "
                    f"contains information that would not be available at prediction time, such as final status, post-resolution fields, "
                    f"or a column derived from the target. If this signal is illegitimate, reported performance may be inflated."
                ),
                evidence={"feature": feat, "impact_pct": impact, "target_column": target_col,
                          "name_overlap": bool(name_overlap), "suspicious_term": bool(suspicious_term),
                          "extreme_dominance": bool(extreme_dominance)},
                causal_chain=[
                    f"'{feat}' may encode post-outcome or target-related information",
                    "Model learns a shortcut rather than a deployable predictive relationship",
                    "Validation metrics may look strong but fail on truly future data",
                ],
                recommended_action=(
                    f"Audit '{feat}' before deployment. Confirm it is available before '{target_col}' is known. "
                    "Run an ablation test by removing this feature and comparing validation performance."
                ),
                confidence="moderate" if not name_overlap else "high",
                source="supervised",
            ))
    return findings


def _find_classification_rca(conf_analysis: Dict[str, Any],
                               feature_importance: List[Dict[str, Any]],
                               target_col: str) -> List[RCAFinding]:
    """Derive RCA findings from confusion matrix and per-class analysis."""
    findings: List[RCAFinding] = []
    if not conf_analysis:
        return findings

    confused_pairs = conf_analysis.get("confused_pairs", [])
    per_class      = conf_analysis.get("per_class_analysis", [])
    overall_err    = conf_analysis.get("overall_error_rate", 0)

    # ── Primary confusion pair ────────────────────────────────────────────
    if confused_pairs:
        top_pair = confused_pairs[0]
        rate     = _safe_float(top_pair.get("confusion_rate"), 0)
        severity = "critical" if rate > 0.4 else "high" if rate > CONFUSION_RATE_HIGH else "medium"
        directionality = (
            f"This confusion is strongly one-directional (asymmetry ratio = "
            f"{top_pair.get('asymmetry_ratio', 1):.1f}x): '{top_pair['actual']}' is frequently "
            f"mis-labelled as '{top_pair['predicted']}', but not the reverse. "
            f"This points to a structural feature overlap or insufficient discriminative signal on the '{top_pair['actual']}' side."
            if top_pair.get("one_directional") else
            f"The confusion is bidirectional ({top_pair.get('reverse_count', 0)} reverse cases), "
            f"suggesting genuine feature ambiguity between these two classes."
        )
        findings.append(RCAFinding(
            id="primary_class_confusion",
            category="class_confusion",
            severity=severity,
            title=f"Primary Confusion: '{top_pair['actual']}' Misclassified as '{top_pair['predicted']}'",
            explanation=(
                f"{top_pair['confusion_count']} instances of class '{top_pair['actual']}' "
                f"({rate*100:.1f}% of its true population) were incorrectly predicted as "
                f"'{top_pair['predicted']}'. {directionality} "
                f"Root cause hypothesis: the features driving '{top_pair['actual']}' and "
                f"'{top_pair['predicted']}' overlap significantly in the current feature space. "
                f"The top model driver(s) — {feature_importance[0]['feature'] if feature_importance else 'unknown'} — "
                f"may not carry sufficient discriminative power to separate these two classes."
            ),
            evidence=top_pair,
            causal_chain=[
                f"'{top_pair['actual']}' and '{top_pair['predicted']}' share overlapping feature distributions",
                f"Model's top drivers do not fully separate the two classes",
                f"At decision boundary, '{top_pair['actual']}' records are pushed toward '{top_pair['predicted']}'",
                f"{top_pair['confusion_count']} misclassifications result — raising false positive rate for '{top_pair['predicted']}'",
            ],
            recommended_action=(
                f"Engineer a feature specifically designed to separate '{top_pair['actual']}' from "
                f"'{top_pair['predicted']}'. Examine raw records in both groups to find a differentiating "
                f"variable not currently in the feature set. Also verify class labelling accuracy."
            ),
            confidence="high",
            source="supervised",
        ))

    # ── Weakest class precision/recall imbalance ──────────────────────────
    weak_classes = [c for c in per_class if c.get("weakness_type") != "acceptable"]
    if weak_classes:
        weakest = weak_classes[0]
        wtype   = weakest.get("weakness_type", "")
        prec    = weakest.get("precision", 0) or 0
        rec     = weakest.get("recall", 0) or 0
        if wtype == "low_recall":
            mechanism = (
                f"The model misses {(1-rec)*100:.1f}% of true '{weakest['class']}' instances "
                f"(false negatives dominate). The class is being overshadowed by more frequent "
                f"classes during training, causing the decision boundary to be biased away from it."
            )
        elif wtype == "low_precision":
            mechanism = (
                f"The model over-predicts class '{weakest['class']}' — {(1-prec)*100:.1f}% of "
                f"predicted '{weakest['class']}' records are actually other classes (false positives dominate). "
                f"The decision boundary has expanded too broadly around this class."
            )
        else:
            mechanism = (
                f"Both precision ({prec:.3f}) and recall ({rec:.3f}) are low, indicating "
                f"the model neither reliably detects nor accurately predicts this class."
            )

        findings.append(RCAFinding(
            id="weakest_class_rca",
            category="class_confusion",
            severity="high" if weakest.get("f1_score", 1) is not None and float(weakest.get("f1_score", 1)) < 0.35 else "medium",
            title=f"Structural Weakness: Class '{weakest['class']}'",
            explanation=(
                f"Class '{weakest['class']}' has the highest error rate ({weakest.get('error_rate', 0)*100:.1f}%) "
                f"among all classes (F1 = {weakest.get('f1_score', 'N/A')}). {mechanism}"
            ),
            evidence=weakest,
            causal_chain=[
                f"Training data for '{weakest['class']}' provides insufficient discriminative signal",
                f"Model weights favour more represented or more distinct classes",
                f"'{weakest['class']}' sits close to another class's decision boundary",
                f"High error rate ({weakest.get('error_rate', 0)*100:.1f}%) observed at test time",
            ],
            recommended_action=(
                f"Collect more samples for '{weakest['class']}' if support < 50. "
                f"Apply class-weighted training or adjust the decision threshold specifically for this class. "
                f"Inspect the confusion matrix to identify the specific class it is confused with."
            ),
            confidence="high",
            source="supervised",
        ))

    return findings


def _find_regression_rca(residual_analysis: Dict[str, Any],
                           feature_importance: List[Dict[str, Any]],
                           error_cases: List[Dict[str, Any]],
                           target_col: str) -> List[RCAFinding]:
    """Derive RCA findings from residual structure and high-error records."""
    findings: List[RCAFinding] = []
    if residual_analysis.get("status") != "success":
        return findings

    bias     = residual_analysis.get("bias_type", "unbiased")
    skewness = _safe_float(residual_analysis.get("skewness"), 0)
    hetero   = residual_analysis.get("heteroscedasticity", {})
    err_conc = residual_analysis.get("error_concentration", "uniform")

    # ── Systematic bias ──────────────────────────────────────────────────
    if bias != "unbiased":
        mean_res = _safe_float(residual_analysis.get("mean_residual"), 0)
        direction = "over-predicts" if bias == "systematic_overprediction" else "under-predicts"
        findings.append(RCAFinding(
            id="systematic_bias",
            category="model_error",
            severity="high",
            title=f"Systematic {direction.title().split()[0]}-prediction Bias Detected",
            explanation=(
                f"The model consistently {direction} the target: mean residual = {mean_res:.4f} "
                f"(residuals are {'negative' if mean_res < 0 else 'positive'} on average). "
                f"Systematic bias in regression almost always has a structural root cause: "
                f"(1) a missing feature that captures a base-level effect on '{target_col}', "
                f"(2) the model is under-/over-fitting a specific range of values, "
                f"or (3) the training data distribution does not match the test distribution."
            ),
            evidence={"bias_type": bias, "mean_residual": mean_res,
                      "std_residual": residual_analysis.get("std_residual")},
            causal_chain=[
                f"Model lacks a feature that explains a base-level offset in '{target_col}'",
                f"Systematic error accumulates across all predictions in the same direction",
                f"Mean residual ({mean_res:.4f}) is non-zero, indicating persistent {bias.replace('_', ' ')}",
            ],
            recommended_action=(
                "Add intercept-type features (time effects, category baselines, or segment-level offsets). "
                "Alternatively, apply a post-hoc bias correction using the mean residual as a calibration offset."
            ),
            confidence="high",
            source="supervised",
        ))

    # ── Heteroscedasticity ────────────────────────────────────────────────
    if hetero.get("detected"):
        hr = _safe_float(hetero.get("pearson_r_abs_res_vs_pred"), 0)
        findings.append(RCAFinding(
            id="heteroscedasticity",
            category="model_error",
            severity="medium",
            title="Heteroscedastic Error: Variance Grows with Predicted Value",
            explanation=(
                f"The absolute residual correlates with the predicted value "
                f"(Pearson r = {hr:.3f}), indicating the model's error is not uniform — it grows "
                f"(or shrinks) as the predicted value increases. This is a classic sign that the "
                f"relationship between features and target is non-linear or multiplicative, not additive. "
                f"Tree-based models can partly handle this, but linear models will systematically "
                f"misrepresent confidence intervals."
            ),
            evidence=hetero,
            causal_chain=[
                "Multiplicative or log-scale relationship between features and target",
                "Model trained on additive linear scale fails to match target curvature",
                "Residual variance is heteroscedastic — wider for extreme predicted values",
            ],
            recommended_action=(
                "Apply a log or square-root transformation to the target variable before training. "
                "Alternatively, use a model that natively handles non-constant variance (e.g., quantile regression)."
            ),
            confidence="moderate",
            source="supervised",
        ))

    # ── Error concentration ───────────────────────────────────────────────
    if err_conc != "uniform":
        hi_err = residual_analysis.get("high_pred_mean_abs_error", 0)
        lo_err = residual_analysis.get("low_pred_mean_abs_error", 0)
        findings.append(RCAFinding(
            id="error_concentration",
            category="model_error",
            severity="medium",
            title=f"Errors Concentrated in {err_conc.replace('_', ' ').title()} Predictions",
            explanation=(
                f"Mean absolute error is disproportionately higher for "
                f"{'high' if err_conc == 'high_value_range' else 'low'}-value predictions "
                f"(MAE = {hi_err if err_conc == 'high_value_range' else lo_err:.4f} vs "
                f"{lo_err if err_conc == 'high_value_range' else hi_err:.4f} for the opposite range). "
                f"This indicates the model struggles specifically with extreme values of '{target_col}'. "
                f"Root cause: training data may have insufficient representation of these extremes, "
                f"or the feature set lacks variables that explain them."
            ),
            evidence={"error_concentration": err_conc,
                      "high_pred_mae": hi_err, "low_pred_mae": lo_err},
            causal_chain=[
                f"Extreme {'high' if err_conc == 'high_value_range' else 'low'} values of '{target_col}' are underrepresented in training",
                "Model under-fits the tail of the target distribution",
                f"Predictions near the {'upper' if err_conc == 'high_value_range' else 'lower'} range carry disproportionate error",
            ],
            recommended_action=(
                f"Oversample or stratify on '{target_col}' to ensure better tail representation. "
                f"Alternatively, train a separate model for extreme-value records or apply isotonic regression calibration."
            ),
            confidence="moderate",
            source="supervised",
        ))

    # ── Feature-residual correlations ─────────────────────────────────────
    for fr in residual_analysis.get("feature_residual_correlations", [])[:2]:
        r = _safe_float(fr.get("pearson_r"), 0)
        findings.append(RCAFinding(
            id=f"residual_feature_corr_{fr['feature']}",
            category="model_error",
            severity="medium",
            title=f"Unexplained Residual Signal in '{fr['feature']}'",
            explanation=(
                f"The residuals correlate with '{fr['feature']}' (r = {r:.3f}), meaning the model "
                f"has not fully extracted the information this feature contains about '{target_col}'. "
                f"{fr.get('interpretation', '')} "
                f"This can occur when the feature's relationship with the target is non-linear "
                f"and a linear/shallow model cannot capture it fully."
            ),
            evidence=fr,
            causal_chain=[
                f"'{fr['feature']}' has a non-linear or conditional effect on '{target_col}'",
                "Current model structure cannot fully capture this relationship",
                "Residuals retain systematic variation correlated with this feature",
            ],
            recommended_action=(
                f"Engineer polynomial or binned versions of '{fr['feature']}'. "
                f"Verify model complexity is sufficient to capture non-linear effects in this variable."
            ),
            confidence="moderate",
            source="supervised",
        ))

    return findings


def _find_cluster_rca(profiles: List[Dict[str, Any]],
                       feature_importance: List[Dict[str, Any]],
                       quality_report: Dict[str, Any],
                       enriched_anomalies: List[Dict[str, Any]]
                       ) -> List[RCAFinding]:
    """Derive RCA findings from cluster structure and anomaly enrichment."""
    findings: List[RCAFinding] = []
    if not profiles:
        return findings

    n_clusters   = len(profiles)
    imbalance    = _safe_float(quality_report.get("cluster_size_imbalance_ratio"), 1)
    sil          = _safe_float(quality_report.get("silhouette"), 0)
    top_driver   = feature_importance[0] if feature_importance else {}
    top_feat     = top_driver.get("feature", "unknown")
    top_impact   = _safe_float(top_driver.get("impact_pct"), 0)

    # ── Primary segmentation driver ───────────────────────────────────────
    if top_driver:
        findings.append(RCAFinding(
            id="primary_segmentation_cause",
            category="cluster_structure",
            severity="info",
            title=f"'{top_feat}' is the Primary Cause of Cluster Separation",
            explanation=(
                f"'{top_feat}' contributes {top_impact:.1f}% of the total between-cluster variance, "
                f"making it the dominant axis along which the {n_clusters} discovered segments diverge. "
                f"This means the most fundamental structural difference between groups in the dataset "
                f"is driven by variation in '{top_feat}'. "
                f"{'The signal is highly concentrated — the entire segmentation is essentially a function of this one variable.' if top_impact > 40 else 'Secondary drivers add meaningful nuance to the primary segmentation.'}"
            ),
            evidence={"primary_driver": top_driver,
                      "n_clusters": n_clusters,
                      "silhouette": sil},
            causal_chain=[
                f"'{top_feat}' exhibits high variance that naturally partitions the population",
                f"Clustering algorithms detect this variance axis and form clusters around it",
                f"{n_clusters} distinct segments emerge from this data structure",
            ],
            recommended_action=(
                f"Validate the operational meaning of '{top_feat}' — does it represent a genuine "
                f"business or process distinction, or is it a data artefact? "
                f"Use it as the primary lens for segment labelling and strategy."
            ),
            confidence="high" if top_impact > 25 else "moderate",
            source="unsupervised",
        ))

    # ── Cluster size imbalance ────────────────────────────────────────────
    if imbalance >= 5:
        small_clusters  = [p for p in profiles if _safe_float(p.get("size_pct"), 0) < 5]
        largest_cluster = max(profiles, key=lambda p: _safe_float(p.get("size_pct"), 0))
        findings.append(RCAFinding(
            id="cluster_size_imbalance",
            category="cluster_structure",
            severity="high" if imbalance >= 10 else "medium",
            title=f"Highly Imbalanced Cluster Sizes (ratio = {imbalance:.1f}×)",
            explanation=(
                f"The largest cluster ('{largest_cluster.get('label')}', "
                f"{_safe_float(largest_cluster.get('size_pct'), 0):.1f}% of data) is "
                f"{imbalance:.1f}× the size of the smallest. "
                f"{'This extreme imbalance suggests that small clusters may not represent genuine natural groups — they could be anomaly concentrations, data entry quirks, or niche behavioural patterns that the algorithm has over-segmented.' if imbalance >= 10 else 'Moderate imbalance is common in real datasets but the smallest clusters warrant individual review.'} "
                f"{len(small_clusters)} cluster(s) contain less than 5% of total records."
            ),
            evidence={"imbalance_ratio": imbalance,
                      "n_small_clusters": len(small_clusters),
                      "largest_cluster_pct": _safe_float(largest_cluster.get("size_pct"), 0)},
            causal_chain=[
                "Data population is not uniformly distributed across natural groups",
                f"{'Extreme' if imbalance >= 10 else 'Moderate'} variance in group sizes drives high imbalance ratio",
                "Small clusters may be algorithmically over-specified rather than genuinely distinct",
            ],
            recommended_action=(
                f"Manually inspect the {len(small_clusters)} small cluster(s). "
                "If they represent noise, consider merging with the nearest cluster or filtering "
                "them as anomalies. If they represent rare but meaningful patterns, label them explicitly."
            ),
            confidence="high",
            source="unsupervised",
        ))

    # ── Cross-cluster distinctive feature patterns ────────────────────────
    # Find profiles with opposite polarity on the same feature — actionable contrast
    if len(profiles) >= 2:
        feat_directions: Dict[str, List[Tuple]] = {}
        for p in profiles:
            for d in p.get("distinctive_features", [])[:3]:
                f = d.get("feature")
                if f:
                    feat_directions.setdefault(f, []).append(
                        (p.get("label", f"Cluster {p['cluster_id']}"),
                         d.get("direction", ""),
                         _safe_float(d.get("difference"), 0))
                    )

        for feat, cluster_list in feat_directions.items():
            dirs = [c[1] for c in cluster_list]
            if "higher" in dirs and "lower" in dirs:
                higher_clusters = [c[0] for c in cluster_list if c[1] == "higher"]
                lower_clusters  = [c[0] for c in cluster_list if c[1] == "lower"]
                findings.append(RCAFinding(
                    id=f"bipolar_feature_{feat}",
                    category="cluster_structure",
                    severity="low",
                    title=f"Bipolar Cluster Separation on '{feat}'",
                    explanation=(
                        f"Feature '{feat}' separates clusters into two opposing camps: "
                        f"segments {', '.join(higher_clusters[:2])} show above-average values, "
                        f"while {', '.join(lower_clusters[:2])} show below-average values. "
                        f"This bipolar pattern suggests '{feat}' is a natural splitting variable "
                        f"that encodes a fundamental distinction within the population — "
                        f"potentially a volume, intensity, or frequency axis."
                    ),
                    evidence={"feature": feat, "cluster_directions": cluster_list},
                    causal_chain=[
                        f"'{feat}' has a bimodal or broadly distributed population",
                        "High and low sub-populations form naturally distinct clusters",
                        "Cluster algorithm captures this as a primary split",
                    ],
                    recommended_action=(
                        f"Use '{feat}' as a segment label axis (e.g., 'High-{feat}' vs 'Low-{feat}'). "
                        "Investigate operational differences between these two poles."
                    ),
                    confidence="moderate",
                    source="unsupervised",
                ))
                break  # one bipolar finding is sufficient

    # ── Anomaly cluster concentration ─────────────────────────────────────
    if enriched_anomalies:
        cluster_freq: Dict[str, int] = {}
        for a in enriched_anomalies:
            label = str(a.get("cluster_label", "Unknown"))
            cluster_freq[label] = cluster_freq.get(label, 0) + 1

        if cluster_freq:
            most_anomalous_cluster = max(cluster_freq, key=lambda k: cluster_freq[k])
            count = cluster_freq[most_anomalous_cluster]
            findings.append(RCAFinding(
                id="anomaly_cluster_concentration",
                category="anomaly",
                severity="high" if count >= 5 else "medium",
                title=f"Anomalies Concentrated in Cluster '{most_anomalous_cluster}'",
                explanation=(
                    f"{count} of the top anomalous records originate from cluster "
                    f"'{most_anomalous_cluster}'. This concentration suggests the cluster's "
                    f"characteristic feature profile may be structurally unusual — or the cluster "
                    f"itself is partially composed of outliers that were not filtered pre-clustering. "
                    f"Root cause: the cluster may represent a transition zone between two natural "
                    f"groups, attracting records that do not cleanly belong to either."
                ),
                evidence={"cluster_anomaly_frequency": cluster_freq, "most_anomalous": most_anomalous_cluster},
                causal_chain=[
                    f"Cluster '{most_anomalous_cluster}' sits at a distributional boundary",
                    "Records with atypical feature combinations are assigned here",
                    "Anomaly detector flags these records as deviations from the global norm",
                ],
                recommended_action=(
                    f"Review the feature profile of cluster '{most_anomalous_cluster}' to determine "
                    "whether it represents a genuine segment or a catch-all for hard-to-classify records. "
                    "Consider re-clustering after removing flagged anomalies."
                ),
                confidence="moderate",
                source="unsupervised",
            ))

    return findings


def _find_interaction_findings(interactions: List[Dict[str, Any]],
                                target_col: str) -> List[RCAFinding]:
    """Convert interaction effects into RCA findings."""
    findings: List[RCAFinding] = []
    for inter in interactions[:3]:
        a, b   = inter["feature_a"], inter["feature_b"]
        lift   = _safe_float(inter.get("interaction_lift"), 0)
        r_int  = _safe_float(inter.get("r_interaction_target"), 0)
        findings.append(RCAFinding(
            id=f"interaction_{a}_{b}",
            category="interaction",
            severity="medium",
            title=f"Interaction Effect: '{a}' × '{b}' Drives '{target_col}'",
            explanation=(
                f"The combined variation of '{a}' and '{b}' correlates more strongly with '{target_col}' "
                f"(r = {r_int:.3f}) than either feature alone (r_a = {inter.get('r_a_target', 0):.3f}, "
                f"r_b = {inter.get('r_b_target', 0):.3f}). The interaction lift = {lift:.3f}. "
                f"This means the two features amplify each other's effect: when both are above (or both below) "
                f"their means simultaneously, the impact on '{target_col}' is disproportionately large. "
                f"Standard additive models may underweight this joint effect."
            ),
            evidence=inter,
            causal_chain=[
                f"'{a}' and '{b}' have a joint effect on '{target_col}' not captured by their individual signals",
                "Interaction term adds predictive lift beyond additive combination",
                "Model may be under-fitting this compound relationship",
            ],
            recommended_action=(
                f"Engineer a multiplicative interaction feature: {a} × {b}. "
                "Test whether adding it improves cross-validated performance by more than 1-2%."
            ),
            confidence="moderate" if lift > 0.10 else "low",
            source="supervised",
        ))
    return findings


def _find_drift_findings(drift_signals: List[Dict[str, Any]],
                          target_col: Optional[str]) -> List[RCAFinding]:
    """Convert temporal drift signals into RCA findings."""
    findings: List[RCAFinding] = []
    for d in drift_signals[:3]:
        feat      = d.get("feature", "")
        shift     = _safe_float(d.get("mean_shift"), 0)
        norm_sh   = _safe_float(d.get("normalised_shift"), 0)
        direction = d.get("direction", "changed")
        is_target = feat == target_col
        findings.append(RCAFinding(
            id=f"drift_{feat}",
            category="drift",
            severity=d.get("severity", "medium"),
            title=f"{'Target' if is_target else 'Feature'} Drift Detected: '{feat}'",
            explanation=(
                f"'{feat}' has {direction} significantly between the earliest and most recent records "
                f"(mean shift = {shift:+.4f}, normalised by std = {norm_sh:.2f}σ, "
                f"KS statistic = {d.get('ks_statistic', 0):.3f}, p = {d.get('p_value', 0):.4f}). "
                f"{'This indicates the target variable itself has shifted — meaning the model was trained on a different distribution than it is now predicting. Prediction reliability will degrade over time.' if is_target else 'Feature drift can silently erode model performance because the model was trained on a distribution that no longer represents incoming data.'}"
            ),
            evidence=d,
            causal_chain=[
                f"'{feat}' distribution has shifted over the dataset timeline",
                "Training data represents an earlier distribution state",
                "Model predictions may be calibrated to a distribution that no longer holds",
            ],
            recommended_action=(
                "Implement a feature drift monitor in production. "
                f"Re-train the model on recent data if '{feat}' drift exceeds 0.5σ consistently. "
                "Consider time-based train/test splits to validate temporal robustness."
            ),
            confidence="high" if d.get("severity") == "high" else "moderate",
            source="supervised" if is_target else "combined",
        ))
    return findings


def _find_data_quality_rca(dq_issues: List[Dict[str, Any]],
                             feature_importance: List[Dict[str, Any]]
                             ) -> List[RCAFinding]:
    """Convert data quality issues into RCA findings, prioritising high-impact features."""
    findings: List[RCAFinding] = []
    important_features = {f["feature"] for f in feature_importance[:10]}

    for issue in dq_issues[:6]:
        col       = issue.get("column", "")
        itype     = issue.get("issue_type", "")
        is_import = col in important_features
        findings.append(RCAFinding(
            id=f"dq_{itype}_{col}",
            category="data_quality",
            severity=issue.get("severity", "medium") if is_import else "low",
            title=f"Data Quality Issue in {'Important Feature' if is_import else 'Column'} '{col}'",
            explanation=(
                f"{issue.get('detail', '')} "
                f"{'This column is in the top-10 most important features, so this quality issue directly degrades model accuracy.' if is_import else 'This column has lower model importance, but data quality issues can compound over time.'} "
                f"Issue type: {itype.replace('_', ' ')}."
            ),
            evidence=issue,
            causal_chain=[
                f"Data pipeline produces {itype.replace('_', ' ')} in '{col}'",
                f"{'Model over-relies on a noisy/incomplete signal' if is_import else 'Downstream models receive degraded feature signal'}",
                "Prediction accuracy or clustering quality is reduced",
            ],
            recommended_action=issue.get("recommendation", "Review data ingestion pipeline for this column."),
            confidence="high" if is_import else "moderate",
            source="combined",
        ))
    return findings


# =============================================================================
# Executive summary generator
# =============================================================================

def _build_executive_summary(findings: List[RCAFinding],
                               strategy: str,
                               target_col: Optional[str],
                               quality_level: str,
                               drift_signals: List[Dict],
                               dq_issues: List[Dict]) -> str:
    """
    Compose a concise, data-backed executive summary of the most important
    RCA findings — written in professional analytical prose.
    """
    n_critical = sum(1 for f in findings if f.severity == "critical")
    n_high     = sum(1 for f in findings if f.severity == "high")
    n_medium   = sum(1 for f in findings if f.severity == "medium")
    n_total    = len(findings)

    signal_quality = {"High": "reliable", "Moderate": "cautiously useful", "Low": "exploratory"}.get(quality_level, "uncertain")

    intro = (
        f"Root cause analysis identified {n_total} findings across "
        f"{n_critical} critical, {n_high} high, and {n_medium} medium severity categories. "
        f"The {'model output' if strategy == 'supervised' else 'clustering structure'} is assessed as "
        f"'{quality_level}' quality — {signal_quality} for analytical decision-making."
    )

    top_findings_text = ""
    top_items = [f for f in findings if f.severity in ("critical", "high")][:3]
    if top_items:
        items_desc = "; ".join(f"({i+1}) {f.title}" for i, f in enumerate(top_items))
        top_findings_text = f" The highest-priority findings are: {items_desc}."

    drift_text = ""
    if drift_signals:
        drifting_feats = [d.get("feature") for d in drift_signals[:2]]
        drift_text = (
            f" Temporal drift was detected in {', '.join(drifting_feats)}, "
            "suggesting the data distribution may have evolved over the collection period — "
            "a potential source of model degradation under production conditions."
        )

    dq_text = ""
    if dq_issues:
        dq_text = (
            f" {len(dq_issues)} data quality issue(s) were identified. "
            "Issues in high-importance features directly suppress model performance "
            "and should be resolved before deployment."
        )

    if target_col:
        target_text = f" The analysis focuses on predicting '{target_col}'."
    else:
        target_text = " The analysis was performed in unsupervised mode (no labelled target)."

    return (intro + target_text + top_findings_text + drift_text + dq_text).strip()


# =============================================================================
# Causal map builder
# =============================================================================

def _build_causal_map(feature_importance: List[Dict[str, Any]],
                       correlations: List[Dict[str, Any]],
                       target_col: Optional[str],
                       interaction_effects: List[Dict[str, Any]]
                       ) -> List[Dict[str, Any]]:
    """
    Build a structured causal map: each entry describes a feature's causal
    pathway to the outcome with evidence type and strength.
    """
    causal_map: List[Dict[str, Any]] = []
    added_features: set = set()

    for fi in feature_importance[:10]:
        feat = fi.get("feature", "")
        if feat in added_features:
            continue
        added_features.add(feat)

        # Find corroborating correlation evidence
        corr_evidence = next(
            (c for c in correlations if c.get("feature_a") == feat and c.get("type") == "feature_target"),
            None
        )

        # Interaction evidence
        inter_evidence = [
            i for i in interaction_effects
            if i.get("feature_a") == feat or i.get("feature_b") == feat
        ]

        causal_map.append({
            "feature": feat,
            "importance_pct": fi.get("impact_pct"),
            "importance_level": fi.get("importance_level"),
            "direction": fi.get("direction"),
            "pathway": "direct",
            "corroborated_by_correlation": corr_evidence is not None,
            "correlation_strength": corr_evidence.get("strength") if corr_evidence else None,
            "pearson_r": corr_evidence.get("pearson_r") if corr_evidence else None,
            "has_interaction_effect": len(inter_evidence) > 0,
            "interacts_with": [
                (i["feature_b"] if i["feature_a"] == feat else i["feature_a"])
                for i in inter_evidence[:2]
            ],
            "causal_narrative": (
                f"'{feat}' directly drives '{target_col or 'the outcome'}' with "
                f"{fi.get('impact_pct', 0):.1f}% model signal share. "
                f"{'Correlation analysis corroborates this relationship (r = ' + str(corr_evidence.get('pearson_r')) + ').' if corr_evidence else 'No direct linear correlation found — effect may be non-linear.'}"
                f"{' Interacts with: ' + ', '.join(i['feature_b'] if i['feature_a'] == feat else i['feature_a'] for i in inter_evidence[:2]) + '.' if inter_evidence else ''}"
            ),
        })

    return causal_map


# =============================================================================
# Priority actions builder
# =============================================================================

def _build_priority_actions(findings: List[RCAFinding],
                              drift_signals: List[Dict],
                              dq_issues: List[Dict]) -> List[str]:
    """Distill findings into an ordered, non-redundant action list."""
    actions: List[str] = []
    seen: set = set()

    for f in sorted(findings, key=lambda x: _severity_rank(x.severity)):
        action = f.recommended_action.strip()
        key = action[:60]
        if key not in seen:
            seen.add(key)
            label = f"[{f.severity.upper()}] {f.title}: {action}"
            actions.append(label)
        if len(actions) >= 10:
            break

    return actions


# =============================================================================
# Core RCA engine
# =============================================================================

class RCAEngine:
    def __init__(self, output_name: str = "rca_run") -> None:
        self.output_dir = MODEL_OUTPUT_BASE / output_name

    # ─── Public entry points ──────────────────────────────────────────────

    def run_from_supervised(
        self,
        supervised_payload: Dict[str, Any],
        raw_df: Optional[pd.DataFrame] = None,
    ) -> RCAResult:
        """
        Run RCA from any supervised engine output payload.

        Accepts any of:
          • SupervisedResult.rca_ready_payload   (from live run)
          • SupervisedResult.dashboard_payload   (from live run)
          • rca_ready_payload.json               (from disk)
          • dashboard_payload.json               (from disk)

        The method normalises whichever format is supplied, resolving the
        full set of required fields from multiple locations in priority order.
        Pass raw_df for richer correlation, interaction, drift, and
        data-quality analysis.
        """
        # ── Normalise: support both dashboard_payload and rca_ready_payload ─
        # dashboard_payload wraps rca_ready under "rca_ready".
        # rca_ready_payload is flat.  Merging both gives access to all fields.
        rca_sub: Dict[str, Any] = supervised_payload.get("rca_ready", {}) or {}
        merged: Dict[str, Any]  = {**rca_sub, **supervised_payload}

        task_type   = merged.get("task_type", "classification")
        target_col  = merged.get("target_column")

        # feature_importance: rca_ready uses "top_drivers"; dashboard uses "feature_importance"
        feature_imp = (
            merged.get("top_drivers")
            or merged.get("feature_importance")
            or []
        )

        error_cases  = merged.get("error_cases", [])
        residual_sum = merged.get("residual_summary", {})

        # Classification artefacts live in rca_ready or at dashboard root
        clf_report_data = merged.get("classification_report") or {}
        conf_mat_data   = merged.get("confusion_matrix") or []
        label_classes   = merged.get("label_classes") or []

        # quality_level: rca_ready has "quality_level"; dashboard has reliability.level
        quality_level = (
            merged.get("quality_level")
            or (merged.get("reliability") or {}).get("level")
            or "Moderate"
        )

        warnings_list: List[str] = []

        # ── Input validation ──────────────────────────────────────────────
        if not feature_imp:
            _raise(_failure(
                "Supervised payload contains no feature importance data.",
                {"keys_present": list(merged.keys())},
                [
                    "Pass SupervisedResult.rca_ready_payload or dashboard_payload.",
                    "Ensure SupervisedEngine.run() completed successfully before calling RCAEngine.",
                ],
            ))
        if task_type not in ("classification", "regression"):
            _raise(_failure(
                f"Unrecognised task_type '{task_type}' in supervised payload.",
                {"task_type": task_type},
                ["task_type must be 'classification' or 'regression'."],
            ))

        # ── Derived analytics ─────────────────────────────────────────────
        correlations:    List[Dict] = []
        interactions:    List[Dict] = []
        drift_signals:   List[Dict] = []
        dq_issues:       List[Dict] = []
        residual_detail: Dict       = {}
        conf_analysis:   Dict       = {}

        if raw_df is not None:
            try:
                correlations = _compute_correlations(raw_df, target_col)
            except Exception as e:
                warnings_list.append(f"Correlation analysis failed: {e}")
            try:
                top_feat_names = [f["feature"] for f in feature_imp[:8]]
                interactions = _detect_feature_interactions(raw_df, target_col or "", top_feat_names) if target_col else []
            except Exception as e:
                warnings_list.append(f"Interaction detection failed: {e}")
            try:
                drift_signals = _detect_temporal_drift(raw_df, target_col, feature_imp)
            except Exception as e:
                warnings_list.append(f"Drift detection failed: {e}")
            try:
                dq_issues = _detect_data_quality_issues(raw_df, feature_imp)
            except Exception as e:
                warnings_list.append(f"Data quality analysis failed: {e}")

        # ── Regression residual analysis ──────────────────────────────────
        if task_type == "regression":
            y_test  = np.array([c.get("actual", 0)    for c in error_cases], dtype=float)
            y_pred  = np.array([c.get("predicted", 0) for c in error_cases], dtype=float)
            res_arr = np.array([c.get("residual", 0)  for c in error_cases], dtype=float)

            # Use full residual summary if error_cases is partial
            mean_r = _safe_float(residual_sum.get("mean"), 0)
            std_r  = _safe_float(residual_sum.get("std"),  1)

            if len(res_arr) >= 5:
                feat_df = None
                if raw_df is not None and target_col in raw_df.columns:
                    try:
                        feat_df = raw_df.drop(columns=[target_col], errors="ignore").select_dtypes(include=[np.number])
                        if len(feat_df) != len(res_arr):
                            feat_df = None
                    except Exception:
                        feat_df = None
                residual_detail = _analyse_residuals(res_arr, y_pred, feat_df)
            else:
                # Synthesise from summary statistics
                residual_detail = {
                    "status": "summary_only",
                    "mean_residual": mean_r,
                    "std_residual":  std_r,
                    "bias_type": "systematic_underprediction" if mean_r > 0.1 * std_r
                                 else "systematic_overprediction" if mean_r < -0.1 * std_r
                                 else "unbiased",
                    "heteroscedasticity": {"detected": False},
                    "error_concentration": "unknown",
                    "feature_residual_correlations": [],
                }

        # ── Confusion matrix analysis ─────────────────────────────────────
        if task_type == "classification" and conf_mat_data and label_classes:
            try:
                conf_analysis = _analyse_confusion_matrix(conf_mat_data, label_classes, clf_report_data)
            except Exception as e:
                warnings_list.append(f"Confusion matrix analysis failed: {e}")

        # ── Assemble findings ─────────────────────────────────────────────
        all_findings: List[RCAFinding] = []
        all_findings += _find_feature_signal_causes(feature_imp, correlations, task_type, target_col)
        all_findings += _find_leakage_and_proxy_risks(feature_imp, target_col)
        if task_type == "regression":
            all_findings += _find_regression_rca(residual_detail, feature_imp, error_cases, target_col or "target")
        elif task_type == "classification":
            all_findings += _find_classification_rca(conf_analysis, feature_imp, target_col or "label")
        all_findings += _find_interaction_findings(interactions, target_col or "target")
        all_findings += _find_drift_findings(drift_signals, target_col)
        all_findings += _find_data_quality_rca(dq_issues, feature_imp)

        # Rank
        all_findings.sort(key=lambda f: (_severity_rank(f.severity), f.category))
        for i, f in enumerate(all_findings, 1):
            f.rank = i

        causal_map = _build_causal_map(feature_imp, correlations, target_col, interactions)
        priority_actions = _build_priority_actions(all_findings, drift_signals, dq_issues)
        confidence_level = _overall_confidence(all_findings, quality_level)
        exec_summary = _build_executive_summary(
            all_findings, "supervised", target_col,
            quality_level, drift_signals, dq_issues,
        )

        result = RCAResult(
            strategy="supervised",
            target_column=target_col,
            executive_summary=exec_summary,
            findings=[_json_safe(f.to_dict()) for f in all_findings],
            causal_map=causal_map,
            interaction_effects=[_json_safe(i) for i in interactions],
            drift_signals=[_json_safe(d) for d in drift_signals],
            data_quality_flags=[_json_safe(d) for d in dq_issues],
            leakage_warnings=[_json_safe(f.to_dict()) for f in all_findings if f.category == "leakage_risk"],
            priority_actions=priority_actions,
            confidence_level=confidence_level,
            saved_model_dir=str(self.output_dir),
            metadata=self._build_metadata("supervised", target_col, len(all_findings)),
            warnings=warnings_list,
        )
        self._save(result)
        return result

    def run_from_unsupervised(
        self,
        unsupervised_payload: Dict[str, Any],
        raw_df: Optional[pd.DataFrame] = None,
    ) -> RCAResult:
        """
        Run RCA from an unsupervised engine's rca_ready_payload dict.
        """
        profiles        = unsupervised_payload.get("cluster_profiles", [])
        # feature_importance: rca_ready uses "top_drivers"; dashboard uses "feature_importance"
        feature_imp = (
            unsupervised_payload.get("top_drivers")
            or unsupervised_payload.get("feature_importance")
            or []
        )
        anomaly_report = (
            unsupervised_payload.get("anomaly_report")
            or unsupervised_payload.get("anomaly_summary")  # backward compatibility for older saved payloads
            or {}
        )
        quality_level = (
            unsupervised_payload.get("quality_level")
            or (unsupervised_payload.get("quality") or {}).get("level")
            or "Moderate"
        )
        best_algorithm = (
            unsupervised_payload.get("best_algorithm")
            or (unsupervised_payload.get("quality") or {}).get("best_algorithm")
            or "Unknown"
        )
        n_clusters = (
            unsupervised_payload.get("n_clusters")
            or (unsupervised_payload.get("quality") or {}).get("n_clusters")
            or 0
        )

        # Normalise: rca_ready_payload is flat; best_model may be a string alias or dict
        _best_model_raw = unsupervised_payload.get("best_model")
        best_model_sub  = _best_model_raw if isinstance(_best_model_raw, dict) else {}
        merged_unsu: Dict[str, Any] = {**best_model_sub, **unsupervised_payload}

        # silhouette/davies_bouldin: present in best_model sub-dict or at root
        sil_val = (
            _safe_float(merged_unsu.get("silhouette"))
            or _safe_float(merged_unsu.get("best_silhouette"))
            or 0.0
        )
        db_val = (
            _safe_float(merged_unsu.get("davies_bouldin"))
            or _safe_float(merged_unsu.get("best_davies_bouldin"))
            or 99.0
        )
        ch_val = (
            _safe_float(merged_unsu.get("calinski_harabasz"))
            or _safe_float(merged_unsu.get("best_calinski_harabasz"))
            or -1.0
        )

        imbalance_ratio = (
            max(_safe_float(p.get("size_pct"), 1) for p in profiles)
            / max(min(_safe_float(p.get("size_pct"), 1) for p in profiles), 0.1)
            if len(profiles) >= 2 else 1.0
        )
        quality_report = {
            "level": quality_level,
            "silhouette": sil_val,
            "davies_bouldin": db_val,
            "calinski_harabasz": ch_val,
            "cluster_size_imbalance_ratio": imbalance_ratio,
        }

        warnings_list: List[str] = []

        # ── Input validation ──────────────────────────────────────────────
        if not feature_imp:
            _raise(_failure(
                "Unsupervised payload contains no feature importance data.",
                {"keys_present": list(unsupervised_payload.keys())},
                [
                    "Pass UnsupervisedResult.rca_ready_payload or dashboard_payload.",
                    "Ensure UnsupervisedEngine.run() completed successfully before calling RCAEngine.",
                ],
            ))

        correlations:  List[Dict] = []
        drift_signals: List[Dict] = []
        dq_issues:     List[Dict] = []
        interactions:  List[Dict] = []

        if raw_df is not None:
            try:
                correlations = _compute_correlations(raw_df)
            except Exception as e:
                warnings_list.append(f"Correlation analysis failed: {e}")
            try:
                drift_signals = _detect_temporal_drift(raw_df, None, feature_imp)
            except Exception as e:
                warnings_list.append(f"Drift detection failed: {e}")
            try:
                dq_issues = _detect_data_quality_issues(raw_df, feature_imp)
            except Exception as e:
                warnings_list.append(f"Data quality analysis failed: {e}")

        enriched_anomalies = _analyse_cluster_anomalies(
            anomaly_report if anomaly_report.get("top_anomalies") else
            {"top_anomalies": [], "anomaly_count": 0},
            profiles, feature_imp
        )

        all_findings: List[RCAFinding] = []
        all_findings += _find_cluster_rca(profiles, feature_imp, quality_report, enriched_anomalies)
        all_findings += _find_drift_findings(drift_signals, None)
        all_findings += _find_data_quality_rca(dq_issues, feature_imp)

        all_findings.sort(key=lambda f: (_severity_rank(f.severity), f.category))
        for i, f in enumerate(all_findings, 1):
            f.rank = i

        causal_map = _build_causal_map(feature_imp, correlations, None, interactions)
        priority_actions = _build_priority_actions(all_findings, drift_signals, dq_issues)
        confidence_level = _overall_confidence(all_findings, quality_level)
        exec_summary = _build_executive_summary(
            all_findings, "unsupervised", None,
            quality_level, drift_signals, dq_issues,
        )

        result = RCAResult(
            strategy="unsupervised",
            target_column=None,
            executive_summary=exec_summary,
            findings=[_json_safe(f.to_dict()) for f in all_findings],
            causal_map=causal_map,
            interaction_effects=[_json_safe(i) for i in interactions],
            drift_signals=[_json_safe(d) for d in drift_signals],
            data_quality_flags=[_json_safe(d) for d in dq_issues],
            leakage_warnings=[],
            priority_actions=priority_actions,
            confidence_level=confidence_level,
            saved_model_dir=str(self.output_dir),
            metadata=self._build_metadata("unsupervised", None, len(all_findings)),
            warnings=warnings_list,
        )
        self._save(result)
        return result

    # ─── Convenience bridges: accept live Result objects ─────────────────

    def run_from_supervised_result(
        self,
        result: Any,
        raw_df: Optional[pd.DataFrame] = None,
    ) -> "RCAResult":
        """
        Accept a live SupervisedResult object directly (no JSON round-trip needed).

        Maps all SupervisedResult attributes — including confusion_matrix,
        classification_report, label_classes, and reliability_report — which
        are absent from rca_ready_payload but required for full RCA analysis.
        """
        payload: Dict[str, Any] = {
            "task_type":             getattr(result, "task_type",             "classification"),
            "target_column":         getattr(result, "target_column",         None),
            "quality_level":         (getattr(result, "reliability_report",   {}) or {}).get("level", "Moderate"),
            "top_drivers":           getattr(result, "feature_importance",    []),
            "feature_importance":    getattr(result, "feature_importance",    []),
            "confusion_matrix":      getattr(result, "confusion_matrix",      []),
            "classification_report": getattr(result, "classification_report", {}),
            "label_classes":         getattr(result, "label_classes",         []),
            "error_cases":           (getattr(result, "rca_ready_payload",    {}) or {}).get("error_cases",    []),
            "residual_summary":      (getattr(result, "rca_ready_payload",    {}) or {}).get("residual_summary", {}),
            "reliability":           getattr(result, "reliability_report",    {}),
            "rca_ready":             getattr(result, "rca_ready_payload",     {}),
        }
        return self.run_from_supervised(payload, raw_df=raw_df)

    def run_from_unsupervised_result(
        self,
        result: Any,
        raw_df: Optional[pd.DataFrame] = None,
    ) -> "RCAResult":
        """
        Accept a live UnsupervisedResult object directly (no JSON round-trip needed).

        Maps all UnsupervisedResult attributes including best_silhouette,
        best_davies_bouldin, and best_calinski_harabasz which are absent from
        the rca_ready_payload JSON but critical for quality reporting.
        """
        payload: Dict[str, Any] = {
            "strategy":             "unsupervised",
            "best_algorithm":       getattr(result, "best_algorithm",        "Unknown"),
            "n_clusters":           getattr(result, "best_n_clusters",       0),
            "quality_level":        (getattr(result, "cluster_quality_report", {}) or {}).get("level", "Moderate"),
            "silhouette":           getattr(result, "best_silhouette",        0.0),
            "davies_bouldin":       getattr(result, "best_davies_bouldin",    99.0),
            "calinski_harabasz":    getattr(result, "best_calinski_harabasz", -1.0),
            "top_drivers":          getattr(result, "feature_importance",     []),
            "feature_importance":   getattr(result, "feature_importance",     []),
            "cluster_profiles":     getattr(result, "cluster_profiles",       []),
            "anomaly_report":       (getattr(result, "rca_ready_payload",     {}) or {}).get("anomaly_report", {}) or getattr(result, "anomaly_report", {}),
            "quality":              getattr(result, "cluster_quality_report", {}),
            "rca_ready":            getattr(result, "rca_ready_payload",      {}),
        }
        return self.run_from_unsupervised(payload, raw_df=raw_df)


    # ─── Internal helpers ─────────────────────────────────────────────────

    def _build_metadata(self, strategy: str, target_col: Optional[str],
                         n_findings: int) -> Dict[str, Any]:
        return {
            "basira_engine_version": RCA_ENGINE_VERSION,
            "project": "Basira",
            "phase": "Phase 3 — Root Cause Analysis",
            "strategy": strategy,
            "target_column": target_col,
            "n_findings": n_findings,
            "created_at": datetime.now().isoformat(),
            "random_state": RANDOM_STATE,
        }

    def _save(self, result: RCAResult) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        _write_json(self.output_dir / "rca_result.json", result.to_dict())
        _write_json(self.output_dir / "rca_findings.json", result.findings)
        _write_json(self.output_dir / "rca_causal_map.json", result.causal_map)
        _write_json(self.output_dir / "rca_priority_actions.json", result.priority_actions)
        _write_json(self.output_dir / "rca_drift_signals.json", result.drift_signals)
        _write_json(self.output_dir / "rca_data_quality_flags.json", result.data_quality_flags)
        _write_json(self.output_dir / "rca_metadata.json", result.metadata)
        # Human-readable executive summary as plain text
        (self.output_dir / "rca_executive_summary.txt").write_text(
            result.executive_summary, encoding="utf-8"
        )


def _overall_confidence(findings: List[RCAFinding], quality_level: str) -> str:
    n_high_conf = sum(1 for f in findings if f.confidence == "high")
    n_total     = max(len(findings), 1)
    ratio       = n_high_conf / n_total
    if quality_level == "High" and ratio >= 0.5:
        return "high"
    if quality_level in ("High", "Moderate") and ratio >= 0.3:
        return "moderate"
    return "low"


# =============================================================================
# Convenience entry point
# =============================================================================

def run_from_payloads(
    model_dir: Path,
    raw_df_path: Optional[Path] = None,
    output_name: str = "rca_run",
) -> RCAResult:
    """
    Load all saved payload JSONs from an engine output directory and run the
    RCA engine.  Accepts the output directory of either SupervisedEngine or
    UnsupervisedEngine.  Merges rca_ready_payload.json with
    dashboard_payload.json so that all required fields are available.

    Parameters
    ----------
    model_dir     : Path to the saved_models/<run_name> directory produced by
                    a prior supervised or unsupervised engine run.
    raw_df_path   : Optional path to the original dataset (.csv / .xlsx) for
                    richer correlation, drift, and data-quality analysis.
    output_name   : Sub-directory name for saving RCA outputs.
    """
    model_dir = Path(model_dir)

    def _load(filename: str) -> Dict[str, Any]:
        p = model_dir / filename
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    rca_ready  = _load("rca_ready_payload.json")
    dashboard  = _load("dashboard_payload.json")
    metadata   = _load("metadata.json")

    # Merge: rca_ready takes precedence for its own keys; dashboard fills the rest
    payload: Dict[str, Any] = {**dashboard, **rca_ready}

    # Inject strategy from metadata if not in payload
    if "strategy" not in payload and "strategy" in metadata:
        payload["strategy"] = metadata["strategy"]
    # Inject quality_level from reliability (supervised) or quality (unsupervised)
    if "quality_level" not in payload:
        reliability = payload.get("reliability", {}) or {}
        quality     = payload.get("quality",     {}) or {}
        payload["quality_level"] = (
            reliability.get("level") or quality.get("level") or "Moderate"
        )

    raw_df = None
    if raw_df_path is not None:
        raw_df_path = Path(raw_df_path)
        if raw_df_path.exists():
            suffix = raw_df_path.suffix.lower()
            if suffix == ".csv":
                raw_df = pd.read_csv(raw_df_path)
            elif suffix in (".xlsx", ".xls"):
                raw_df = pd.read_excel(raw_df_path)

    engine   = RCAEngine(output_name=output_name)
    strategy = payload.get("strategy", "supervised")
    if strategy == "unsupervised":
        return engine.run_from_unsupervised(payload, raw_df)
    return engine.run_from_supervised(payload, raw_df)


# =============================================================================
# Smoke test
# =============================================================================

if __name__ == "__main__":
    import sys
    np.random.seed(RANDOM_STATE)
    n = 200

    # Simulate a supervised classification rca_ready_payload
    sup_payload = {
        "strategy": "supervised",
        "task_type": "classification",
        "target_column": "category",
        "quality_level": "Moderate",
        "top_drivers": [
            {"feature": "revenue", "impact_pct": 42.1, "importance_level": "Critical", "direction": "positive"},
            {"feature": "tenure_days", "impact_pct": 21.3, "importance_level": "High", "direction": "positive"},
            {"feature": "region_encoded", "impact_pct": 12.8, "importance_level": "High", "direction": "unknown"},
        ],
        "label_classes": ["Churned", "Active", "At-Risk"],
        "confusion_matrix": [[30, 5, 3], [2, 40, 8], [4, 6, 22]],
        "classification_report": {
            "Churned":  {"precision": 0.83, "recall": 0.79, "f1-score": 0.81, "support": 38},
            "Active":   {"precision": 0.78, "recall": 0.80, "f1-score": 0.79, "support": 50},
            "At-Risk":  {"precision": 0.67, "recall": 0.69, "f1-score": 0.68, "support": 32},
        },
        "error_cases": [],
        "residual_summary": {},
        "class_error_summary": {},
    }

    df_test = pd.DataFrame({
        "revenue":       np.random.exponential(500, n),
        "tenure_days":   np.random.normal(365, 100, n),
        "region_encoded": np.random.randint(0, 5, n),
        "support_tickets": np.random.poisson(2, n),
        "category":      np.random.choice(["Churned", "Active", "At-Risk"], n),
    })

    result = RCAEngine("smoke_rca").run_from_supervised(sup_payload, raw_df=df_test)
    print("=" * 60)
    print("RCA ENGINE SMOKE TEST — SUPERVISED")
    print("=" * 60)
    print(result.executive_summary)
    print(f"\nFindings ({len(result.findings)}):")
    for f in result.findings[:5]:
        print(f"  [{f['severity'].upper()}] {f['title']}")
    print(f"\nPriority Actions:")
    for a in result.priority_actions[:3]:
        print(f"  • {a[:100]}...")
    print(f"\nSaved → {result.saved_model_dir}")
