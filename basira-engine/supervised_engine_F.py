from __future__ import annotations

import os

# Limit numerical-library threads for stable execution on laptops and shared environments.
# This prevents occasional OpenMP/BLAS hangs during repeated model comparison.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

import json
import math
import re
import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd

from sklearn.base import clone
from sklearn.ensemble import (
    ExtraTreesClassifier,
    ExtraTreesRegressor,
    GradientBoostingClassifier,
    GradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LinearRegression, LogisticRegression, Ridge
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
)
from sklearn.model_selection import (
    GroupShuffleSplit,
    KFold,
    ShuffleSplit,
    StratifiedGroupKFold,
    StratifiedKFold,
    StratifiedShuffleSplit,
    cross_val_predict,
)
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.svm import LinearSVC

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

RANDOM_STATE = 42
TEST_SIZE = 0.20
N_SPLITS_CV = 3

TFIDF_MAX_FEATURES = 5_000
TFIDF_NGRAM_RANGE = (1, 2)
TFIDF_MIN_DF_UNIQUE = 1
TFIDF_MIN_DF_GROUPED = 2
TFIDF_MAX_DF = 0.95
TFIDF_SUBLINEAR_TF = True

MIN_UNIQUE_GROUP_SUPPORT = 3
MIN_ROWS_PER_CLASS = 3
MIN_TOTAL_SAMPLES = 10
MIN_CLASSES = 2
MIN_MEAN_TEXT_TOKENS = 2

_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E4\u06E7\u06E8\u06EA-\u06ED]")
_TATWEEL = re.compile(r"\u0640")
_HAMZA_VARIANTS = re.compile(r"[أإآ]")
_WHITESPACE = re.compile(r"\s+")
MODEL_OUTPUT_BASE = Path("saved_models")

try:
    from xgboost import XGBClassifier, XGBRegressor
    XGBOOST_AVAILABLE = True
except Exception:
    XGBClassifier = None
    XGBRegressor = None
    XGBOOST_AVAILABLE = False

SUPERVISED_ENGINE_VERSION = "supervised-enhanced-v2.1-xgb"



@dataclass
class FailureReport:
    status: str
    reason: str
    details: Dict[str, Any]
    suggestions: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(_json_safe(self.to_dict()), indent=indent, ensure_ascii=False)


@dataclass
class SupervisedResult:
    modality: str
    task_type: str
    target_column: str
    split_strategy: str
    best_model_name: str
    cv_results: List[Dict]
    test_metrics: Dict[str, float]
    classification_report: Optional[Dict]
    confusion_matrix: Optional[List]
    preparation_summary: Dict
    saved_model_dir: str
    label_classes: Optional[List[str]]
    reliability_report: Dict[str, Any] = field(default_factory=dict)
    feature_schema: Dict[str, Any] = field(default_factory=dict)
    feature_importance: List[Dict[str, Any]] = field(default_factory=list)
    insights: List[Dict[str, Any]] = field(default_factory=list)
    narrative_insights: Dict[str, Any] = field(default_factory=dict)
    chart_recommendations: List[Dict[str, Any]] = field(default_factory=list)
    chart_data: Dict[str, Any] = field(default_factory=dict)
    dashboard_payload: Dict[str, Any] = field(default_factory=dict)
    rca_ready_payload: Dict[str, Any] = field(default_factory=dict)
    prediction_ready: bool = False
    warnings: List[str] = field(default_factory=list)


class BasiraEngineError(RuntimeError):
    def __init__(self, report: FailureReport) -> None:
        self.report = report
        super().__init__(report.reason)


def _failure(reason: str, details: Dict[str, Any], suggestions: List[str]) -> FailureReport:
    return FailureReport(status="failed", reason=reason, details=_json_safe(details), suggestions=suggestions)


def _raise(report: FailureReport) -> None:
    raise BasiraEngineError(report)


def _json_safe(obj: Any) -> Any:
    """Recursively convert any value to a JSON-serialisable form.
    Aligned across all four Basira engines — do not modify without
    updating rca_engine_enhanced.py, insight_engine_enhanced.py,
    and unsupervised_engine_enhanced.py in lock-step.
    """
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, pd.DataFrame):
        return _json_safe(obj.to_dict(orient="records"))
    if isinstance(obj, pd.Series):
        return _json_safe(obj.tolist())
    if isinstance(obj, np.ndarray):
        return _json_safe(obj.tolist())
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return None if math.isnan(v) or math.isinf(v) else round(v, 6)
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else round(obj, 6)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if obj is pd.NA:
        return None
    if obj is None or isinstance(obj, (str, int, bool)):
        return obj
    return str(obj)


def _write_json(path: Path, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_json_safe(data), f, indent=2, ensure_ascii=False)


def _normalize_arabic(text: object) -> str:
    s = str(text).strip()
    s = _DIACRITICS.sub("", s)
    s = _TATWEEL.sub("", s)
    s = _HAMZA_VARIANTS.sub("ا", s)
    s = _WHITESPACE.sub(" ", s)
    return s


def _normalize_english(text: object) -> str:
    return re.sub(r"\s+", " ", str(text).strip().lower())


def _normalize_text(text: object, language: str) -> str:
    return _normalize_arabic(text) if language == "arabic" else _normalize_english(text)


_ENCODINGS = ["utf-8-sig", "cp1256", "utf-8", "latin1"]


def _looks_broken_arabic(text: str) -> bool:
    return any(m in text for m in ["Ù", "Ø", "Ã", "\ufffd", "\\x"])


def load_file(path: Path) -> pd.DataFrame:
    if not path.exists():
        _raise(_failure(
            reason=f"Dataset file not found: '{path.name}'",
            details={"path": str(path)},
            suggestions=["Verify the file path is correct", "Ensure the file exists and is accessible"],
        ))
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls", ".xlsm"):
        try:
            return pd.read_excel(path, engine="openpyxl" if suffix == ".xlsx" else None)
        except Exception as exc:
            _raise(_failure(
                reason=f"Failed to read Excel file '{path.name}'",
                details={"file": path.name, "original_error": str(exc)},
                suggestions=["Check that the file is not password-protected or corrupted"],
            ))
    if suffix == ".csv":
        last_error: Exception = RuntimeError("No encodings tried.")
        for enc in _ENCODINGS:
            try:
                df = pd.read_csv(path, encoding=enc)
                sample = ""
                for col in df.columns:
                    vals = df[col].dropna()
                    if not vals.empty:
                        sample = str(vals.iloc[0])
                        break
                if not _looks_broken_arabic(sample):
                    return df
                last_error = ValueError(f"Encoding '{enc}' produced garbled text.")
            except Exception as exc:
                last_error = exc
        _raise(_failure(
            reason=f"Could not decode CSV file '{path.name}' with any supported encoding",
            details={"file": path.name, "tried_encodings": _ENCODINGS, "last_error": str(last_error)},
            suggestions=["Re-save the file in UTF-8 encoding", "For Arabic text, save as UTF-8-BOM or CP1256"],
        ))
    _raise(_failure(
        reason=f"Unsupported file extension: '{suffix}'",
        details={"extension": suffix},
        suggestions=["Provide a file with extension .xlsx, .xls, or .csv"],
    ))


def _classification_metrics(y_true, y_pred) -> Dict[str, float]:
    return {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "balanced_accuracy": round(float(balanced_accuracy_score(y_true, y_pred)), 4),
        "precision_weighted": round(float(precision_score(y_true, y_pred, average="weighted", zero_division=0)), 4),
        "recall_weighted": round(float(recall_score(y_true, y_pred, average="weighted", zero_division=0)), 4),
        "f1_weighted": round(float(f1_score(y_true, y_pred, average="weighted", zero_division=0)), 4),
        "f1_macro": round(float(f1_score(y_true, y_pred, average="macro", zero_division=0)), 4),
    }


def _regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    mae = float(mean_absolute_error(y_true, y_pred))
    r2 = float(r2_score(y_true, y_pred)) if len(y_true) > 1 else 0.0
    denom = np.where(np.abs(y_true) < 1e-9, np.nan, y_true)
    mape = float(np.nanmean(np.abs((y_true - y_pred) / denom)) * 100)
    if math.isnan(mape) or math.isinf(mape):
        mape = 0.0
    return {"RMSE": round(rmse, 4), "MAE": round(mae, 4), "R2": round(r2, 4), "MAPE_pct": round(mape, 4)}


def _safe_cv_splits_classification(y: np.ndarray) -> int:
    counts = pd.Series(y).value_counts()
    min_count = int(counts.min()) if not counts.empty else 0
    return max(2, min(N_SPLITS_CV, min_count)) if min_count >= 2 else 2


def _safe_cv_splits_regression(y: np.ndarray) -> int:
    return max(2, min(N_SPLITS_CV, len(y)))


def _text_pipelines(language: str, min_df: int) -> Dict[str, Pipeline]:
    vectorizer = TfidfVectorizer(
        max_features=TFIDF_MAX_FEATURES,
        ngram_range=TFIDF_NGRAM_RANGE,
        min_df=min_df,
        max_df=TFIDF_MAX_DF,
        sublinear_tf=TFIDF_SUBLINEAR_TF,
        lowercase=False,
        analyzer="word",
    )
    return {
        "LogisticRegression": Pipeline([("tfidf", clone(vectorizer)), ("model", LogisticRegression(max_iter=3000, class_weight="balanced", random_state=RANDOM_STATE))]),
        "LinearSVC": Pipeline([("tfidf", clone(vectorizer)), ("model", LinearSVC(class_weight="balanced", random_state=RANDOM_STATE))]),
        "MultinomialNB": Pipeline([("tfidf", clone(vectorizer)), ("model", MultinomialNB())]),
    }


def _tabular_classification_pipelines() -> Dict[str, Any]:
    models: Dict[str, Any] = {
        "RandomForest": RandomForestClassifier(n_estimators=80, max_depth=12, min_samples_leaf=2, class_weight="balanced", random_state=RANDOM_STATE, n_jobs=1),
        "ExtraTrees": ExtraTreesClassifier(n_estimators=80, max_depth=None, min_samples_leaf=2, class_weight="balanced", random_state=RANDOM_STATE, n_jobs=1),
        "GradientBoosting": GradientBoostingClassifier(n_estimators=100, max_depth=4, learning_rate=0.05, subsample=0.85, random_state=RANDOM_STATE),
        "LogisticRegression": Pipeline([("scaler", StandardScaler()), ("model", LogisticRegression(max_iter=2500, class_weight="balanced", random_state=RANDOM_STATE))]),
        "LinearSVC": Pipeline([("scaler", StandardScaler()), ("model", LinearSVC(class_weight="balanced", random_state=RANDOM_STATE))]),
    }
    if XGBOOST_AVAILABLE and XGBClassifier is not None:
        models["XGBoost"] = XGBClassifier(
            n_estimators=120,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.85,
            colsample_bytree=0.85,
            reg_lambda=1.0,
            eval_metric="mlogloss",
            tree_method="hist",
            random_state=RANDOM_STATE,
            n_jobs=1,
        )
    return models


def _tabular_regression_pipelines() -> Dict[str, Any]:
    models: Dict[str, Any] = {
        "RandomForest": RandomForestRegressor(n_estimators=80, max_depth=12, min_samples_leaf=3, random_state=RANDOM_STATE, n_jobs=1),
        "ExtraTrees": ExtraTreesRegressor(n_estimators=80, max_depth=None, min_samples_leaf=3, random_state=RANDOM_STATE, n_jobs=1),
        "GradientBoosting": GradientBoostingRegressor(n_estimators=120, max_depth=5, learning_rate=0.05, subsample=0.85, random_state=RANDOM_STATE),
        "Ridge": Pipeline([("scaler", StandardScaler()), ("model", Ridge(alpha=1.0))]),
        "LinearRegression": Pipeline([("scaler", StandardScaler()), ("model", LinearRegression())]),
    }
    if XGBOOST_AVAILABLE and XGBRegressor is not None:
        models["XGBoost"] = XGBRegressor(
            n_estimators=120,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.85,
            colsample_bytree=0.85,
            reg_lambda=1.0,
            objective="reg:squarederror",
            tree_method="hist",
            random_state=RANDOM_STATE,
            n_jobs=1,
        )
    return models


def _validate_dataset_size(df: pd.DataFrame, target_col: str) -> None:
    if len(df) < MIN_TOTAL_SAMPLES:
        _raise(_failure("Dataset is too small for reliable model training", {"n_samples": len(df), "min_required": MIN_TOTAL_SAMPLES}, [f"Provide at least {MIN_TOTAL_SAMPLES} samples", "Collect more data before training"]))


def _validate_target_column(df: pd.DataFrame, target_col: str, task_type: str) -> None:
    if target_col not in df.columns:
        _raise(_failure(f"Target column '{target_col}' was not found in the dataset", {"target_column": target_col, "available_columns": df.columns.tolist()}, ["Check the target column spelling", "Review routing configuration"]))
    missing_pct = round(float(df[target_col].isna().mean() * 100), 1)
    if missing_pct > 50:
        _raise(_failure(f"Target column '{target_col}' has too many missing values to train reliably", {"missing_pct": missing_pct}, ["Fill or remove rows with missing target values", "Verify the correct target column"]))
    if task_type == "classification" and df[target_col].dropna().nunique() < MIN_CLASSES:
        _raise(_failure("Target column has insufficient class diversity for classification", {"n_unique_classes": int(df[target_col].dropna().nunique())}, ["Ensure the target has at least 2 classes", "If numeric continuous, use regression"]))


def _validate_class_balance(working: pd.DataFrame, target_col: str) -> None:
    counts = working[target_col].value_counts()
    rare = counts[counts < MIN_ROWS_PER_CLASS]
    if len(rare) == len(counts):
        _raise(_failure("All classes have fewer samples than the minimum required for training", {"class_distribution": counts.to_dict(), "min_required_per_class": MIN_ROWS_PER_CLASS}, ["Provide more labeled data per class", "Merge underrepresented classes", f"Ensure each class has at least {MIN_ROWS_PER_CLASS} samples"]))


def _validate_text_quality(series: pd.Series, text_col: str) -> None:
    non_empty = series.dropna().astype(str).str.strip()
    non_empty = non_empty[non_empty != ""]
    if non_empty.empty:
        _raise(_failure(f"Text column '{text_col}' is empty or contains only blank values", {"text_column": text_col}, ["Use a meaningful text column", "Check encoding issues"]))
    mean_tokens = non_empty.str.split().apply(len).mean()
    if mean_tokens < MIN_MEAN_TEXT_TOKENS:
        _raise(_failure(f"Text column '{text_col}' contains very short or meaningless content", {"text_column": text_col, "mean_token_count": round(float(mean_tokens), 2)}, ["Use richer textual content", "Merge multiple short text columns if applicable"]))


def _validate_feature_columns(df: pd.DataFrame, feat_cols: List[str]) -> None:
    if not feat_cols:
        _raise(_failure("No feature columns could be identified after excluding target and identifier columns", {"available_columns": df.columns.tolist()}, ["Verify routing includes valid feature columns", "Ensure the dataset has non-target useful features"]))
    fully_empty = df[feat_cols].isna().mean()[lambda s: s == 1.0].index.tolist()
    if fully_empty:
        _raise(_failure("One or more feature columns are entirely empty", {"empty_columns": fully_empty}, ["Remove empty columns", "Check that the correct sheet or file section was loaded"]))


def _rank_classification_results(cv_results: List[Dict]) -> List[Dict]:
    def key(r: Dict) -> Tuple:
        m = r.get("cv_metrics", {})
        return (r.get("status") == "success", m.get("f1_macro", 0), m.get("balanced_accuracy", 0), m.get("f1_weighted", 0), m.get("accuracy", 0))
    ranked = sorted(cv_results, key=key, reverse=True)
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
        if r.get("status") == "success":
            if i == 1:
                r["selection_reason"] = "Selected because it achieved the strongest macro F1 and balanced accuracy among successful candidates."
            else:
                r["selection_reason"] = "Not selected because a higher-ranked model achieved stronger validation performance."
                r["rejected_reason"] = "Lower validation ranking than the selected model."
        else:
            r.setdefault("selection_reason", "Not selected because validation failed.")
            r.setdefault("rejected_reason", "Model failed safely during cross-validation.")
    return ranked


def _rank_regression_results(cv_results: List[Dict]) -> List[Dict]:
    def key(r: Dict) -> Tuple:
        m = r.get("cv_metrics", {})
        return (r.get("status") == "success", m.get("R2", -999), -m.get("RMSE", float("inf")), -m.get("MAE", float("inf")), -m.get("MAPE_pct", float("inf")))
    ranked = sorted(cv_results, key=key, reverse=True)
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
        if r.get("status") == "success":
            if i == 1:
                r["selection_reason"] = "Selected because it achieved the best validation balance: higher R2 with lower RMSE and MAE."
            else:
                r["selection_reason"] = "Not selected because a higher-ranked model achieved stronger validation performance."
                r["rejected_reason"] = "Lower validation ranking than the selected model."
        else:
            r.setdefault("selection_reason", "Not selected because validation failed.")
            r.setdefault("rejected_reason", "Model failed safely during cross-validation.")
    return ranked


def _target_summary(y: np.ndarray, task_type: str) -> Dict[str, Any]:
    if task_type == "classification":
        counts = pd.Series(y).value_counts().to_dict()
        total = max(len(y), 1)
        return {"n_classes": len(counts), "class_distribution": counts, "minority_share_pct": round(min(counts.values()) / total * 100, 2) if counts else 0}
    s = pd.Series(y).astype(float)
    return {"mean": float(s.mean()), "std": float(s.std()), "min": float(s.min()), "max": float(s.max()), "skew": float(s.skew()) if len(s) > 2 else 0}


def _build_reliability_report(task_type: str, test_metrics: Dict[str, float], cv_results: List[Dict], target_summary: Optional[Dict] = None) -> Dict[str, Any]:
    cautions: List[str] = []
    if task_type == "classification":
        f1m = test_metrics.get("f1_macro", 0)
        bal = test_metrics.get("balanced_accuracy", 0)
        if f1m >= 0.80 and bal >= 0.80:
            level, score, reason = "High", int(round((f1m + bal) / 2 * 100)), "The model shows strong macro-level performance and balanced class recognition."
        elif f1m >= 0.60:
            level, score, reason = "Moderate", int(round(f1m * 100)), "The model is useful for decision support, but some classes may still be harder to separate."
            cautions.append("Validate minority-class behavior before using predictions operationally.")
        else:
            level, score, reason = "Low", int(round(f1m * 100)), "Class separation is weak or class imbalance may be affecting performance."
            cautions.append("Treat findings as exploratory and add more labeled samples or merge rare classes.")
    else:
        r2 = test_metrics.get("R2", 0)
        mape = test_metrics.get("MAPE_pct", 999)
        if r2 >= 0.80 and mape <= 20:
            level, score, reason = "High", int(round(min(1, max(0, r2)) * 100)), "The model explains a strong share of target variation with acceptable relative error."
        elif r2 >= 0.55:
            level, score, reason = "Moderate", int(round(min(1, max(0, r2)) * 100)), "The model has moderate predictive power and should be validated with domain expertise."
            cautions.append("Check residual patterns and high-error records before operational use.")
        else:
            level, score, reason = "Low", int(round(max(0, r2) * 100)), "The model explains limited variance in the target."
            cautions.append("Add stronger predictive features or verify whether the selected target is noisy.")
    policy = {
        "show_full_dashboard": level in ("High", "Moderate"),
        "allow_decision_language": level == "High",
        "caution_required": level != "High",
        "mark_outputs_as_exploratory": level == "Low",
    }
    return {"level": level, "confidence_score": score, "reason": reason, "caution_notes": cautions, "recommended_next_step": cautions[0] if cautions else "Use the dashboard outputs to support transparent decision-making.", "dashboard_confidence": level, "output_policy": policy}


def _unwrap_estimator(model: Any) -> Any:
    if hasattr(model, "named_steps") and "model" in model.named_steps:
        return model.named_steps["model"]
    return model


def _extract_feature_importance(model: Any, feature_names: List[str], task_type: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    warnings_: List[str] = []
    est = _unwrap_estimator(model)
    raw: Optional[np.ndarray] = None
    direction_values: Optional[np.ndarray] = None
    if hasattr(est, "feature_importances_"):
        raw = np.asarray(est.feature_importances_, dtype=float)
        direction_values = raw
    elif hasattr(est, "coef_"):
        coef = np.asarray(est.coef_, dtype=float)
        if coef.ndim > 1:
            signed = np.mean(coef, axis=0)
            raw = np.mean(np.abs(coef), axis=0)
        else:
            signed = coef
            raw = np.abs(coef)
        direction_values = signed
    else:
        warnings_.append("Feature importance is unavailable for the selected model.")
        return [], warnings_
    if raw is None or len(raw) == 0:
        return [], ["Feature importance could not be computed."]
    n = min(len(raw), len(feature_names))
    raw = raw[:n]
    feature_names = feature_names[:n]
    total = float(np.sum(np.abs(raw)))
    if total <= 0:
        return [], ["Feature importance values are all zero."]
    rows = []
    signed = direction_values[:n] if direction_values is not None else raw
    for feature, val, sgn in zip(feature_names, raw, signed):
        pct = float(abs(val) / total * 100)
        direction = "positive" if sgn > 0 else "negative" if sgn < 0 else "unknown"
        level = "Critical" if pct >= 30 else "High" if pct >= 15 else "Medium" if pct >= 5 else "Low"
        rows.append({"feature": feature, "importance": float(abs(val)), "impact_pct": round(pct, 2), "direction": direction, "importance_level": level})
    rows.sort(key=lambda r: r["impact_pct"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r["explanation"] = f"{r['feature']} contributes about {r['impact_pct']}% of the available model driver signal."
    return rows[:30], warnings_


def _histogram_payload(values: np.ndarray, bins: int = 10) -> Dict[str, Any]:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return {"labels": [], "counts": []}
    arr_min = float(np.min(arr))
    arr_max = float(np.max(arr))
    if math.isclose(arr_min, arr_max, rel_tol=1e-12, abs_tol=1e-12):
        label = f"{arr_min:.2f}"
        return {"labels": [label], "counts": [int(arr.size)]}
    safe_bins = int(min(bins, max(1, arr.size)))
    counts, edges = np.histogram(arr, bins=safe_bins)
    labels = [f"{edges[i]:.2f}–{edges[i+1]:.2f}" for i in range(len(counts))]
    return {"labels": labels, "counts": counts.astype(int).tolist()}


def _class_distribution_payload(values: np.ndarray, labels: Optional[List[str]]) -> Dict[str, Any]:
    s = pd.Series(values)
    counts = s.value_counts().sort_index()
    if labels:
        names = [labels[int(i)] if isinstance(i, (int, np.integer)) and int(i) < len(labels) else str(i) for i in counts.index]
    else:
        names = [str(i) for i in counts.index]
    return {"labels": names, "values": counts.astype(int).tolist(), "chart_type": "doughnut"}


def _build_chart_data(task_type: str, X_test: Any, y_test: np.ndarray, y_pred: np.ndarray, feature_importance: List[Dict[str, Any]], test_metrics: Dict[str, float], label_classes: Optional[List[str]] = None, confusion_matrix_data: Optional[List] = None, y_proba: Optional[np.ndarray] = None, best_model_name: str = "") -> Dict[str, Any]:
    fi_labels = [r["feature"] for r in feature_importance[:15]]
    fi_values = [r["impact_pct"] for r in feature_importance[:15]]
    summary = [{"title": "Best Model", "value": best_model_name}, {"title": "Reliability Input", "value": "metrics"}]
    if task_type == "classification":
        summary += [
            {"title": "Accuracy", "value": test_metrics.get("accuracy")},
            {"title": "F1 Macro", "value": test_metrics.get("f1_macro")},
            {"title": "Balanced Accuracy", "value": test_metrics.get("balanced_accuracy")},
            {"title": "Number of Classes", "value": len(label_classes or [])},
        ]
        confidence_payload = None
        if y_proba is not None:
            conf = np.max(y_proba, axis=1)
            confidence_payload = {"chart_type": "histogram", "mean_confidence": round(float(np.mean(conf)), 4), **_histogram_payload(conf)}
        top_errors = []
        for idx, (a, p) in enumerate(zip(y_test, y_pred)):
            if a != p:
                top_errors.append({"row_index": int(idx), "actual": label_classes[int(a)] if label_classes else int(a), "predicted": label_classes[int(p)] if label_classes else int(p)})
            if len(top_errors) >= 20:
                break
        return {
            "summary_cards": summary,
            "feature_importance_bar": {"chart_type": "horizontal_bar", "labels": fi_labels, "values": fi_values},
            "class_distribution_doughnut": _class_distribution_payload(y_test, label_classes),
            "predicted_distribution_doughnut": _class_distribution_payload(y_pred, label_classes),
            "confusion_matrix_heatmap": {"chart_type": "heatmap", "matrix": confusion_matrix_data or [], "x_labels": label_classes or [], "y_labels": label_classes or []},
            "metrics_bar": {"chart_type": "bar", "labels": ["Accuracy", "Balanced Accuracy", "F1 Macro", "F1 Weighted", "Precision Weighted", "Recall Weighted"], "values": [test_metrics.get("accuracy"), test_metrics.get("balanced_accuracy"), test_metrics.get("f1_macro"), test_metrics.get("f1_weighted"), test_metrics.get("precision_weighted"), test_metrics.get("recall_weighted")]},
            "confidence_distribution": confidence_payload,
            "top_errors": top_errors,
        }
    residuals = np.asarray(y_test, dtype=float) - np.asarray(y_pred, dtype=float)
    abs_err = np.abs(residuals)
    high_err_idx = np.argsort(abs_err)[::-1][:10]
    return {
        "summary_cards": summary + [{"title": k, "value": v} for k, v in test_metrics.items()],
        "feature_importance_bar": {"chart_type": "horizontal_bar", "labels": fi_labels, "values": fi_values},
        "actual_vs_predicted_scatter": {"chart_type": "scatter", "points": [{"x": float(a), "y": float(p)} for a, p in zip(y_test, y_pred)]},
        "residuals_plot": {"chart_type": "scatter", "points": [{"x": float(p), "y": float(r)} for p, r in zip(y_pred, residuals)]},
        "target_distribution_histogram": {"chart_type": "histogram", **_histogram_payload(np.asarray(y_test, dtype=float))},
        "prediction_error_histogram": {"chart_type": "histogram", **_histogram_payload(abs_err)},
        "metrics_bar": {"chart_type": "bar", "labels": ["R2", "RMSE", "MAE", "MAPE_pct"], "values": [test_metrics.get("R2"), test_metrics.get("RMSE"), test_metrics.get("MAE"), test_metrics.get("MAPE_pct")]},
        "top_high_error_records": [{"row_index": int(i), "actual": float(y_test[i]), "predicted": float(y_pred[i]), "absolute_error": float(abs_err[i])} for i in high_err_idx],
    }


def _build_chart_recommendations(task_type: str, chart_data: Dict[str, Any], reliability_report: Dict[str, Any], feature_importance: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    exploratory = reliability_report.get("level") == "Low"
    if task_type == "classification":
        specs = [
            ("summary_cards", "kpi_cards", "Classification KPI Summary", "Overview"),
            ("feature_importance_bar", "horizontal_bar", "Top Feature Drivers", "Explainability"),
            ("confusion_matrix_heatmap", "heatmap", "Confusion Matrix", "Model Evaluation"),
            ("class_distribution_doughnut", "doughnut", "Actual Class Distribution", "Data Profile"),
            ("predicted_distribution_doughnut", "doughnut", "Predicted Class Distribution", "Prediction Behavior"),
            ("metrics_bar", "bar", "Metrics Comparison", "Model Evaluation"),
        ]
        if chart_data.get("confidence_distribution"):
            specs.append(("confidence_distribution", "histogram", "Prediction Confidence", "Prediction Behavior"))
    else:
        specs = [
            ("summary_cards", "kpi_cards", "Regression KPI Summary", "Overview"),
            ("feature_importance_bar", "horizontal_bar", "Top Feature Drivers", "Explainability"),
            ("actual_vs_predicted_scatter", "scatter", "Actual vs Predicted", "Prediction Behavior"),
            ("residuals_plot", "scatter", "Residual Analysis", "Error Analysis"),
            ("target_distribution_histogram", "histogram", "Target Distribution", "Data Profile"),
            ("prediction_error_histogram", "histogram", "Prediction Error Distribution", "Error Analysis"),
            ("metrics_bar", "bar", "Metrics Comparison", "Model Evaluation"),
        ]
    return [{"chart_id": cid, "chart_type": ctype, "title": title, "priority": i + 1, "reason": f"Recommended to support {section.lower()} in the Basira dashboard.", "dashboard_section": section, "exploratory": exploratory} for i, (cid, ctype, title, section) in enumerate(specs) if cid in chart_data]


def _generate_insights(task_type: str, test_metrics: Dict[str, float], cv_results: List[Dict], feature_importance: List[Dict[str, Any]], reliability_report: Dict[str, Any], target_summary: Dict[str, Any], class_report: Optional[Dict] = None) -> List[Dict[str, Any]]:
    level = reliability_report.get("level", "Unknown")
    sev = "success" if level == "High" else "warning" if level == "Moderate" else "danger"
    insights = [{"id": "model_reliability", "title": "Model Reliability", "value": level, "metric": reliability_report.get("reason", ""), "description": reliability_report.get("reason", ""), "action": reliability_report.get("recommended_next_step", ""), "severity": sev}]
    if cv_results:
        best = cv_results[0]
        insights.append({"id": "best_model_selection", "title": "Best Model Selection", "value": best.get("model_name"), "metric": best.get("selection_reason"), "description": "Basira compared all suitable supervised models and selected the highest-ranked candidate.", "action": "Review the model leaderboard for alternatives.", "severity": "success"})
    if feature_importance:
        top = feature_importance[0]
        insights.append({"id": "primary_driver", "title": "Primary Feature Driver", "value": top["feature"], "metric": f"{top['impact_pct']}% impact", "description": top.get("explanation", ""), "action": f"Monitor {top['feature']} in the dashboard and RCA stage.", "severity": "success"})
    if task_type == "classification" and class_report:
        class_rows = [(k, v) for k, v in class_report.items() if isinstance(v, dict) and "f1-score" in v]
        if class_rows:
            weakest = min(class_rows, key=lambda kv: kv[1].get("f1-score", 0))
            insights.append({"id": "weakest_class", "title": "Weakest Class", "value": weakest[0], "metric": f"F1 = {round(float(weakest[1].get('f1-score', 0)), 4)}", "description": "This class is the hardest for the selected model to recognize.", "action": "Review examples from this class and consider adding more labeled records.", "severity": "warning"})
        if target_summary.get("minority_share_pct", 100) < 10:
            insights.append({"id": "class_imbalance", "title": "Class Imbalance Risk", "value": f"{target_summary.get('minority_share_pct')}%", "metric": "Minority class share", "description": "One or more classes have limited representation, which may reduce recall.", "action": "Collect additional records for minority classes or merge rare classes.", "severity": "warning"})
    if task_type == "regression":
        insights.append({"id": "prediction_error", "title": "Prediction Error", "value": test_metrics.get("RMSE"), "metric": "RMSE", "description": "RMSE summarizes typical prediction error in the target unit.", "action": "Inspect high residual records for RCA.", "severity": sev})
    return insights


def _generate_narrative_insights(task_type: str, best_model: str, test_metrics: Dict[str, float], feature_importance: List[Dict[str, Any]], reliability_report: Dict[str, Any]) -> Dict[str, Any]:
    top = feature_importance[0] if feature_importance else {}
    level = reliability_report.get("level", "Unknown")
    cautious = level != "High"
    if task_type == "classification":
        perf = f"The selected model achieved F1 Macro = {test_metrics.get('f1_macro')} and Balanced Accuracy = {test_metrics.get('balanced_accuracy')}."
    else:
        perf = f"The selected model achieved R2 = {test_metrics.get('R2')}, RMSE = {test_metrics.get('RMSE')}, and MAE = {test_metrics.get('MAE')}."
    return {
        "headline": "Basira has completed supervised model analysis.",
        "summary": f"Basira compared multiple supervised candidates and selected {best_model} as the best model for this dataset.",
        "key_finding": f"The strongest detected driver is {top.get('feature', 'not available')} with {top.get('impact_pct', 0)}% impact." if top else "No model-level feature driver was available for this model.",
        "model_performance": perf,
        "risk_alert": "Results should be treated as exploratory until more data or stronger validation is available." if cautious else "The results are strong enough for confident decision-support use.",
        "recommended_action": reliability_report.get("recommended_next_step", "Review the dashboard outputs and model leaderboard."),
        "dashboard_note": "Show caution banner." if cautious else "Full dashboard can be displayed without caution banner.",
    }


def _build_rca_ready_payload(task_type: str, target_column: str, X_test: Any, y_test: np.ndarray, y_pred: np.ndarray, feature_importance: List[Dict[str, Any]], residuals: Optional[np.ndarray] = None, label_classes: Optional[List[str]] = None, classification_report_data: Optional[Dict] = None, confusion_matrix_data: Optional[List] = None) -> Dict[str, Any]:
    top = feature_importance[0] if feature_importance else {}
    payload: Dict[str, Any] = {
        # ── Identity ──────────────────────────────────────────────────────
        "status":               "ready",
        "strategy":             "supervised",           # uniform tag used by RCA + Insight
        "task_type":            task_type,
        "target_column":        target_column,
        # ── Feature drivers ───────────────────────────────────────────────
        "primary_driver":       top,
        "top_drivers":          feature_importance[:10],
        "feature_importance":   feature_importance[:10],  # alias for downstream engines
        # ── Quality / reliability ─────────────────────────────────────────
        # quality_level is injected by _finalize_result after creation
        "quality_level":        "Moderate",             # placeholder; overwritten in _finalize_result
        # ── Classification artefacts (populated below for classification) ─
        "label_classes":           label_classes or [],
        "confusion_matrix":        confusion_matrix_data or [],
        "classification_report":   classification_report_data or {},
        # ── Regression artefacts ──────────────────────────────────────────
        "error_cases":          [],
        "residual_summary":     {},
        # ── Shared ────────────────────────────────────────────────────────
        "class_error_summary":  {},
        "recommended_rca_focus": [],
    }
    if task_type == "classification":
        if confusion_matrix_data and label_classes:
            arr = np.asarray(confusion_matrix_data)
            pairs = []
            for i in range(arr.shape[0]):
                for j in range(arr.shape[1]):
                    if i != j and arr[i, j] > 0:
                        pairs.append((int(arr[i, j]), label_classes[i], label_classes[j]))
            pairs.sort(reverse=True)
            payload["class_error_summary"] = {"most_confused_pairs": [{"count": c, "actual": a, "predicted": p} for c, a, p in pairs[:5]]}
            if pairs:
                payload["recommended_rca_focus"].append(f"Investigate why {pairs[0][1]} is confused with {pairs[0][2]}.")
        if classification_report_data:
            class_rows = [(k, v) for k, v in classification_report_data.items() if isinstance(v, dict) and "f1-score" in v]
            if class_rows:
                weakest = min(class_rows, key=lambda kv: kv[1].get("f1-score", 0))
                payload["class_error_summary"]["weakest_class"] = weakest[0]
                payload["recommended_rca_focus"].append(f"Review weak performance for class {weakest[0]}.")
    else:
        res = np.asarray(residuals if residuals is not None else np.asarray(y_test, dtype=float) - np.asarray(y_pred, dtype=float), dtype=float)
        payload["residual_summary"] = {"mean": float(np.mean(res)), "std": float(np.std(res)), "max_abs_error": float(np.max(np.abs(res))) if len(res) else 0}
        idx = np.argsort(np.abs(res))[::-1][:10]
        payload["error_cases"] = [{"row_index": int(i), "actual": float(y_test[i]), "predicted": float(y_pred[i]), "residual": float(res[i])} for i in idx]
        payload["recommended_rca_focus"].append("Investigate records with the highest residuals and compare them against top feature drivers.")
    return payload


def _build_dashboard_payload(task_type: str, target_column: str, best_model: str, cv_results: List[Dict], reliability: Dict[str, Any], chart_data: Dict[str, Any], chart_recommendations: List[Dict[str, Any]], insights: List[Dict[str, Any]], narrative: Dict[str, Any], rca_ready: Dict[str, Any], warnings_: List[str]) -> Dict[str, Any]:
    return {
        "status": "ready",
        "task_type": task_type,
        "target_column": target_column,
        "best_model": best_model,
        "model_leaderboard": cv_results,
        "reliability": reliability,
        "summary_cards": chart_data.get("summary_cards", []),
        "insights": insights,
        "narrative": narrative,
        "chart_recommendations": chart_recommendations,
        "chart_data": chart_data,
        "rca_ready": rca_ready,
        "warnings": warnings_,
        "rendering_notes": {
            "preferred_layout": "supervised_classification_dashboard" if task_type == "classification" else "supervised_regression_dashboard",
            "show_caution_banner": reliability.get("output_policy", {}).get("caution_required", True),
            "allow_export_report": True,
            "supports_multiple_charts": True,
        },
    }


class SupervisedEngine:
    def __init__(self, routing_decision: Dict[str, Any], output_name: str = "run") -> None:
        self.routing = routing_decision
        self.output_dir = MODEL_OUTPUT_BASE / output_name
        self._task_type = routing_decision["task_type"]
        self._target = routing_decision["target_column"]
        self._text_cols = routing_decision.get("text_columns", [])
        self._num_cols = routing_decision.get("numeric_columns", [])
        self._cat_cols = routing_decision.get("categorical_columns", [])
        self._dt_cols = routing_decision.get("datetime_columns", [])
        self._id_cols = routing_decision.get("identifier_like_columns", [])
        self._modality = routing_decision.get("dataset_modality", "tabular")
        self._lang = routing_decision.get("language_profile", {}).get("dominant_language", "english")
        if self._target is None:
            _raise(_failure("No target column was specified in the routing decision", {"routing_keys": list(routing_decision.keys())}, ["Specify target_column in routing", "If dataset is unlabelled, use UnsupervisedEngine"]))

    def run(self, df: pd.DataFrame) -> SupervisedResult:
        _validate_dataset_size(df, self._target)
        _validate_target_column(df, self._target, self._task_type)
        is_text = self._modality in ("text_heavy", "bilingual") and len(self._text_cols) > 0
        if is_text:
            return self._run_text_pipeline(df)
        return self._run_tabular_pipeline(df)

    def _run_text_pipeline(self, df: pd.DataFrame) -> SupervisedResult:
        if self._task_type != "classification":
            _raise(_failure("Text-heavy supervised mode currently supports classification only", {"task_type": self._task_type}, ["Use tabular regression for numeric targets", "Provide engineered text embeddings for regression"]))
        text_col = self._text_cols[0]
        target_col = self._target
        _validate_text_quality(df[text_col], text_col)
        working, prep_summary = self._prepare_text(df, text_col, target_col)
        _validate_class_balance(working, target_col)
        X = working[text_col]
        groups = working[text_col]
        label_enc = LabelEncoder()
        y = label_enc.fit_transform(working[target_col])
        unique_ratio = working[text_col].nunique() / max(len(working), 1)
        use_groups = unique_ratio < 0.90
        try:
            if use_groups:
                split_name = "GroupShuffleSplit"
                train_idx, test_idx = next(GroupShuffleSplit(n_splits=1, test_size=TEST_SIZE, random_state=RANDOM_STATE).split(X, y, groups=groups))
                X_train, X_test = X.iloc[train_idx].reset_index(drop=True), X.iloc[test_idx].reset_index(drop=True)
                y_train, y_test = y[train_idx], y[test_idx]
                g_train = groups.iloc[train_idx].reset_index(drop=True)
                cv_splits = _safe_cv_splits_classification(y_train)
                cv_strategy = StratifiedGroupKFold(n_splits=cv_splits, shuffle=True, random_state=RANDOM_STATE)
                cv_kwargs = {"groups": g_train}
                min_df = TFIDF_MIN_DF_GROUPED
            else:
                split_name = "StratifiedShuffleSplit"
                train_idx, test_idx = next(StratifiedShuffleSplit(n_splits=1, test_size=TEST_SIZE, random_state=RANDOM_STATE).split(X, y))
                X_train, X_test = X.iloc[train_idx].reset_index(drop=True), X.iloc[test_idx].reset_index(drop=True)
                y_train, y_test = y[train_idx], y[test_idx]
                cv_splits = _safe_cv_splits_classification(y_train)
                cv_strategy = StratifiedKFold(n_splits=cv_splits, shuffle=True, random_state=RANDOM_STATE)
                cv_kwargs = {}
                min_df = TFIDF_MIN_DF_UNIQUE
        except Exception:
            split_name = "FallbackShuffleSplit"
            idx = np.arange(len(X))
            rng = np.random.default_rng(RANDOM_STATE)
            rng.shuffle(idx)
            cut = int(len(idx) * (1 - TEST_SIZE))
            train_idx, test_idx = idx[:cut], idx[cut:]
            X_train, X_test = X.iloc[train_idx].reset_index(drop=True), X.iloc[test_idx].reset_index(drop=True)
            y_train, y_test = y[train_idx], y[test_idx]
            cv_strategy = StratifiedKFold(n_splits=_safe_cv_splits_classification(y_train), shuffle=True, random_state=RANDOM_STATE)
            cv_kwargs, min_df = {}, TFIDF_MIN_DF_UNIQUE
        models = _text_pipelines(self._lang, min_df)
        cv_results = self._cross_validate_classification(models, X_train, y_train, cv_strategy, cv_kwargs)
        successful = [r for r in cv_results if r.get("status") == "success"]
        if not successful:
            _raise(_failure("Cross-validation failed for all text classification candidate models", {"cv_results": cv_results}, ["Check text quality", "Increase samples per class", "Reduce number of classes"]))
        best_name = cv_results[0]["model_name"]
        best_model = clone(models[best_name])
        best_model.fit(X_train, y_train)
        y_pred = best_model.predict(X_test)
        metrics = _classification_metrics(y_test, y_pred)
        labels = label_enc.classes_.tolist()
        class_ids = np.arange(len(labels))
        clf_report = classification_report(y_test, y_pred, labels=class_ids, target_names=labels, zero_division=0, output_dict=True)
        conf_mat = confusion_matrix(y_test, y_pred, labels=class_ids).tolist()
        feat_names = []
        try:
            feat_names = best_model.named_steps["tfidf"].get_feature_names_out().tolist()
        except Exception:
            feat_names = [text_col]
        feature_importance, warnings_ = _extract_feature_importance(best_model, feat_names, "classification")
        y_proba = best_model.predict_proba(X_test) if hasattr(best_model, "predict_proba") else None
        return self._finalize_result(best_model, label_enc, target_col, "classification", split_name, best_name, cv_results, metrics, clf_report, conf_mat, prep_summary, labels, feature_importance, warnings_, X_test, y_test, y_pred, y_proba, {"feature_columns": [text_col], "text_columns": [text_col], "numeric_columns": [], "categorical_columns": [], "datetime_columns": [], "identifier_like_columns": self._id_cols, "target_column": target_col, "task_type": "classification", "modality": self._modality, "language": self._lang})

    def _run_tabular_pipeline(self, df: pd.DataFrame) -> SupervisedResult:
        target_col = self._target
        raw_feature_cols = [c for c in df.columns if c not in set(self._id_cols) | {target_col}]
        _validate_feature_columns(df, raw_feature_cols)
        X_all, y_raw, prep_summary, feature_schema = self._prepare_tabular_train(df, raw_feature_cols, target_col)
        if self._task_type == "classification":
            y_series = y_raw.astype(str)
            _validate_class_balance(pd.DataFrame({target_col: y_series}), target_col)
            label_enc: Optional[LabelEncoder] = LabelEncoder()
            y = label_enc.fit_transform(y_series)
        else:
            label_enc = None
            y = pd.to_numeric(y_raw, errors="coerce").astype(float).values
        valid = ~pd.isna(y)
        X_all = X_all.loc[valid].reset_index(drop=True)
        y = np.asarray(y)[valid]
        y_raw_valid = pd.Series(y_raw).loc[valid].reset_index(drop=True)
        if self._task_type == "classification":
            train_idx, test_idx = next(StratifiedShuffleSplit(n_splits=1, test_size=TEST_SIZE, random_state=RANDOM_STATE).split(X_all, y))
            cv_strategy = StratifiedKFold(n_splits=_safe_cv_splits_classification(y[train_idx]), shuffle=True, random_state=RANDOM_STATE)
            split_name = "StratifiedShuffleSplit"
        else:
            train_idx, test_idx = next(ShuffleSplit(n_splits=1, test_size=TEST_SIZE, random_state=RANDOM_STATE).split(X_all, y))
            cv_strategy = KFold(n_splits=_safe_cv_splits_regression(y[train_idx]), shuffle=True, random_state=RANDOM_STATE)
            split_name = "ShuffleSplit"
        X_train, X_test = X_all.iloc[train_idx], X_all.iloc[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]
        if self._task_type == "classification":
            models = _tabular_classification_pipelines()
            cv_results = self._cross_validate_classification(models, X_train, y_train, cv_strategy, {})
        else:
            models = _tabular_regression_pipelines()
            cv_results = self._cross_validate_regression(models, X_train, y_train, cv_strategy, {})
        successful = [r for r in cv_results if r.get("status") == "success"]
        if not successful:
            _raise(_failure("Cross-validation failed for all candidate models", {"cv_results": cv_results}, ["Check feature values", "Remove invalid columns", "Increase dataset size"]))
        best_name = cv_results[0]["model_name"]
        best_model = clone(models[best_name])
        best_model.fit(X_train, y_train)
        y_pred = best_model.predict(X_test)
        feature_importance, warnings_ = _extract_feature_importance(best_model, feature_schema["feature_columns"], self._task_type)
        if self._task_type == "classification":
            metrics = _classification_metrics(y_test, y_pred)
            labels = label_enc.classes_.tolist() if label_enc else []
            class_ids = np.arange(len(labels))
            clf_report = classification_report(y_test, y_pred, labels=class_ids, target_names=labels, zero_division=0, output_dict=True)
            conf_mat = confusion_matrix(y_test, y_pred, labels=class_ids).tolist()
            y_proba = best_model.predict_proba(X_test) if hasattr(best_model, "predict_proba") else None
            return self._finalize_result(best_model, label_enc, target_col, "classification", split_name, best_name, cv_results, metrics, clf_report, conf_mat, prep_summary, labels, feature_importance, warnings_, X_test, y_test, y_pred, y_proba, feature_schema)
        metrics = _regression_metrics(y_test, y_pred)
        target_std = float(np.std(y_train)) if len(y_train) > 1 else 0.0
        if target_std and metrics["RMSE"] > target_std:
            warnings_.append("RMSE is higher than the training target standard deviation; prediction errors may be unstable.")
        return self._finalize_result(best_model, None, target_col, "regression", split_name, best_name, cv_results, metrics, None, None, prep_summary, None, feature_importance, warnings_, X_test, y_test, y_pred, None, feature_schema)

    def _prepare_text(self, df: pd.DataFrame, text_col: str, target_col: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        working = df[[text_col, target_col]].copy()
        n_before = len(working)
        working = working.dropna(subset=[text_col, target_col]).copy()
        working[text_col] = working[text_col].map(lambda t: _normalize_text(t, self._lang))
        working[target_col] = working[target_col].astype(str).str.strip()
        working = working[(working[text_col] != "") & (working[target_col] != "")].copy()
        rc = working[target_col].value_counts()
        kept = rc[rc >= MIN_ROWS_PER_CLASS].index
        dropped = rc[rc < MIN_ROWS_PER_CLASS].to_dict()
        before_filter = len(working)
        working = working[working[target_col].isin(kept)].copy()
        if working.empty:
            _raise(_failure("No samples remain after removing rare classes and empty text rows", {"rows_before": n_before, "dropped_classes": dropped}, ["Provide more samples per class", "Reduce target classes", "Check text encoding"]))
        return working.reset_index(drop=True), {"rows_before": n_before, "rows_after": len(working), "dropped_missing_or_empty": n_before - before_filter, "dropped_rare_class": before_filter - len(working), "dropped_classes": dropped, "n_classes": int(working[target_col].nunique()), "class_distribution": working[target_col].value_counts().to_dict()}

    def _prepare_tabular_train(self, df: pd.DataFrame, raw_feature_cols: List[str], target_col: str) -> Tuple[pd.DataFrame, pd.Series, Dict[str, Any], Dict[str, Any]]:
        working = df[raw_feature_cols + [target_col]].copy().dropna(subset=[target_col]).reset_index(drop=True)
        numeric_cols = [c for c in raw_feature_cols if pd.api.types.is_numeric_dtype(working[c])]
        datetime_cols = [c for c in raw_feature_cols if c in self._dt_cols]
        categorical_cols = [c for c in raw_feature_cols if c not in numeric_cols and c not in datetime_cols]
        X_parts: List[pd.DataFrame] = []
        numeric_medians: Dict[str, float] = {}
        if numeric_cols:
            Xn = working[numeric_cols].apply(pd.to_numeric, errors="coerce")
            for c in numeric_cols:
                med = float(Xn[c].median()) if Xn[c].notna().any() else 0.0
                numeric_medians[c] = med
                Xn[c] = Xn[c].fillna(med)
            X_parts.append(Xn)
        datetime_medians: Dict[str, float] = {}
        dt_feature_cols: List[str] = []
        for c in datetime_cols:
            dt = pd.to_datetime(working[c], errors="coerce")
            tmp = pd.DataFrame({f"{c}_year": dt.dt.year, f"{c}_month": dt.dt.month, f"{c}_day": dt.dt.day, f"{c}_dayofweek": dt.dt.dayofweek}, index=working.index)
            for col in tmp.columns:
                med = float(tmp[col].median()) if tmp[col].notna().any() else 0.0
                datetime_medians[col] = med
                tmp[col] = tmp[col].fillna(med)
            dt_feature_cols.extend(tmp.columns.tolist())
            X_parts.append(tmp)
        category_levels: Dict[str, List[str]] = {}
        dummy_cols: List[str] = []
        if categorical_cols:
            cat = working[categorical_cols].astype("object").fillna("Unknown").astype(str)
            for c in categorical_cols:
                levels = sorted(cat[c].unique().tolist())
                category_levels[c] = levels
            Xc = pd.get_dummies(cat, prefix=categorical_cols, dummy_na=False).astype(float)
            dummy_cols = Xc.columns.tolist()
            X_parts.append(Xc)
        X = pd.concat(X_parts, axis=1) if X_parts else pd.DataFrame(index=working.index)
        X = X.replace([np.inf, -np.inf], np.nan).fillna(0)
        schema = {"raw_feature_columns": raw_feature_cols, "feature_columns": X.columns.tolist(), "numeric_columns": numeric_cols, "categorical_columns": categorical_cols, "datetime_columns": datetime_cols, "datetime_feature_columns": dt_feature_cols, "identifier_like_columns": self._id_cols, "target_column": target_col, "task_type": self._task_type, "modality": self._modality, "numeric_medians": numeric_medians, "datetime_medians": datetime_medians, "category_levels": category_levels, "dummy_columns": dummy_cols}
        prep = {"rows_before": len(df), "rows_after": len(working), "dropped_missing_target": len(df) - len(working), "n_raw_feature_columns": len(raw_feature_cols), "n_model_feature_columns": len(X.columns), "numeric_columns": numeric_cols, "categorical_columns": categorical_cols, "datetime_columns": datetime_cols, "target_summary": _target_summary(working[target_col].values, self._task_type)}
        return X, working[target_col], prep, schema

    def _prepare_tabular_for_prediction(self, new_df: pd.DataFrame, schema: Dict[str, Any]) -> pd.DataFrame:
        missing = [c for c in schema.get("raw_feature_columns", []) if c not in new_df.columns]
        if missing:
            _raise(_failure("Prediction input is missing required feature columns", {"missing_columns": missing}, ["Provide the same feature columns used during training", "Run the same preprocessing bridge before prediction"]))
        parts = []
        if schema.get("numeric_columns"):
            Xn = new_df[schema["numeric_columns"]].apply(pd.to_numeric, errors="coerce")
            for c, med in schema.get("numeric_medians", {}).items():
                if c in Xn.columns:
                    Xn[c] = Xn[c].fillna(med)
            parts.append(Xn)
        for c in schema.get("datetime_columns", []):
            dt = pd.to_datetime(new_df[c], errors="coerce")
            tmp = pd.DataFrame({f"{c}_year": dt.dt.year, f"{c}_month": dt.dt.month, f"{c}_day": dt.dt.day, f"{c}_dayofweek": dt.dt.dayofweek}, index=new_df.index)
            for col, med in schema.get("datetime_medians", {}).items():
                if col in tmp.columns:
                    tmp[col] = tmp[col].fillna(med)
            parts.append(tmp)
        if schema.get("categorical_columns"):
            cat = new_df[schema["categorical_columns"]].astype("object").fillna("Unknown").astype(str)
            Xc = pd.get_dummies(cat, prefix=schema["categorical_columns"], dummy_na=False).astype(float)
            parts.append(Xc)
        X = pd.concat(parts, axis=1) if parts else pd.DataFrame(index=new_df.index)
        return X.reindex(columns=schema.get("feature_columns", []), fill_value=0).replace([np.inf, -np.inf], np.nan).fillna(0)

    def _cross_validate_classification(self, pipelines: Dict[str, Any], X_train: Any, y_train: np.ndarray, cv: Any, cv_kwargs: Dict[str, Any]) -> List[Dict]:
        results: List[Dict] = []
        for name, pipe in pipelines.items():
            try:
                pred = cross_val_predict(clone(pipe), X_train, y_train, cv=cv, method="predict", **cv_kwargs)
                metrics = _classification_metrics(y_train, pred)
                results.append({"model_name": name, "task_type": "classification", "status": "success", "cv_metrics": metrics, "main_score": metrics["f1_macro"]})
            except Exception as exc:
                results.append({"model_name": name, "task_type": "classification", "status": "failed", "cv_metrics": {"accuracy": 0, "balanced_accuracy": 0, "precision_weighted": 0, "recall_weighted": 0, "f1_weighted": 0, "f1_macro": 0}, "main_score": 0, "error": str(exc), "rejected_reason": "Cross-validation failed."})
        return _rank_classification_results(results)

    def _cross_validate_regression(self, pipelines: Dict[str, Any], X_train: Any, y_train: np.ndarray, cv: Any, cv_kwargs: Dict[str, Any]) -> List[Dict]:
        results: List[Dict] = []
        for name, pipe in pipelines.items():
            try:
                pred = cross_val_predict(clone(pipe), X_train, y_train, cv=cv, method="predict", **cv_kwargs)
                metrics = _regression_metrics(y_train, pred)
                results.append({"model_name": name, "task_type": "regression", "status": "success", "cv_metrics": metrics, "main_score": metrics["R2"]})
            except Exception as exc:
                results.append({"model_name": name, "task_type": "regression", "status": "failed", "cv_metrics": {"R2": -999, "RMSE": float("inf"), "MAE": float("inf"), "MAPE_pct": float("inf")}, "main_score": -999, "error": str(exc), "rejected_reason": "Cross-validation failed."})
        return _rank_regression_results(results)

    def _finalize_result(self, model: Any, label_encoder: Optional[LabelEncoder], target_col: str, task_type: str, split_name: str, best_name: str, cv_results: List[Dict], test_metrics: Dict[str, float], clf_report: Optional[Dict], conf_mat: Optional[List], prep_summary: Dict[str, Any], label_classes: Optional[List[str]], feature_importance: List[Dict[str, Any]], warnings_: List[str], X_test: Any, y_test: np.ndarray, y_pred: np.ndarray, y_proba: Optional[np.ndarray], feature_schema: Dict[str, Any]) -> SupervisedResult:
        target_sum = _target_summary(y_test, task_type)
        reliability = _build_reliability_report(task_type, test_metrics, cv_results, target_sum)
        chart_data = _build_chart_data(task_type, X_test, y_test, y_pred, feature_importance, test_metrics, label_classes, conf_mat, y_proba, best_name)
        chart_recs = _build_chart_recommendations(task_type, chart_data, reliability, feature_importance)
        insights = _generate_insights(task_type, test_metrics, cv_results, feature_importance, reliability, target_sum, clf_report)
        narrative = _generate_narrative_insights(task_type, best_name, test_metrics, feature_importance, reliability)
        residuals = None if task_type == "classification" else np.asarray(y_test, dtype=float) - np.asarray(y_pred, dtype=float)
        rca_ready = _build_rca_ready_payload(task_type, target_col, X_test, y_test, y_pred, feature_importance, residuals, label_classes, clf_report, conf_mat)
        # Overwrite quality_level placeholder with the actual computed value
        rca_ready["quality_level"] = reliability.get("level", "Moderate")
        dashboard = _build_dashboard_payload(task_type, target_col, best_name, cv_results, reliability, chart_data, chart_recs, insights, narrative, rca_ready, warnings_)
        self._save_artifacts(model, label_encoder, task_type, best_name, split_name, cv_results, test_metrics, clf_report, conf_mat, prep_summary, feature_schema, reliability, feature_importance, chart_data, chart_recs, insights, narrative, dashboard, rca_ready, warnings_)
        return SupervisedResult(self._modality, task_type, target_col, split_name, best_name, cv_results, test_metrics, clf_report, conf_mat, prep_summary, str(self.output_dir), label_classes, reliability, feature_schema, feature_importance, insights, narrative, chart_recs, chart_data, dashboard, rca_ready, True, warnings_)

    def _save_artifacts(self, model: Any, label_encoder: Optional[LabelEncoder], task_type: str, best_name: str, split_name: str, cv_results: List[Dict], test_metrics: Dict[str, float], clf_report: Optional[Dict], conf_mat: Optional[List], prep_summary: Dict[str, Any], feature_schema: Dict[str, Any], reliability: Dict[str, Any], feature_importance: List[Dict[str, Any]], chart_data: Dict[str, Any], chart_recs: List[Dict[str, Any]], insights: List[Dict[str, Any]], narrative: Dict[str, Any], dashboard: Dict[str, Any], rca_ready: Dict[str, Any], warnings_: List[str]) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, self.output_dir / "model.pkl")
        joblib.dump(model, self.output_dir / "model_pipeline.joblib")
        if label_encoder is not None:
            joblib.dump(label_encoder, self.output_dir / "label_encoder.pkl")
            joblib.dump(label_encoder, self.output_dir / "label_encoder.joblib")
        metadata = {"basira_engine_version": SUPERVISED_ENGINE_VERSION, "project": "Basira", "phase": "Phase 2 — Supervised Analytics", "task_type": task_type, "modality": self._modality, "target_column": self._target, "best_model_name": best_name, "split_strategy": split_name, "random_state": RANDOM_STATE, "test_size": TEST_SIZE, "created_at": datetime.now().isoformat(), "number_of_rows_used": prep_summary.get("rows_after"), "number_of_features_used": len(feature_schema.get("feature_columns", [])), "language": self._lang, "model_selection_metric": "f1_macro/balanced_accuracy" if task_type == "classification" else "R2/RMSE/MAE", "optional_dependencies": {"xgboost_available": XGBOOST_AVAILABLE, "xgboost_used_if_available": True}, "prediction_ready": True, "warnings": warnings_}
        metrics_payload = {"test_metrics": test_metrics, "classification_report": clf_report, "confusion_matrix": conf_mat, "regression_metrics": test_metrics if task_type == "regression" else None}
        for name, payload in [("metadata.json", metadata), ("metrics.json", metrics_payload), ("cv_results.json", cv_results), ("feature_schema.json", feature_schema), ("reliability_report.json", reliability), ("feature_importance.json", feature_importance), ("chart_data.json", chart_data), ("chart_recommendations.json", chart_recs), ("insights.json", insights), ("narrative_insights.json", narrative), ("dashboard_payload.json", dashboard), ("rca_ready_payload.json", rca_ready)]:
            _write_json(self.output_dir / name, payload)

    def predict(self, new_df: pd.DataFrame, model_dir: Optional[str] = None) -> Dict[str, Any]:
        directory = Path(model_dir) if model_dir else self.output_dir
        model_path = directory / "model.pkl"
        schema_path = directory / "feature_schema.json"
        if not model_path.exists() or not schema_path.exists():
            _raise(_failure("Saved model artifacts were not found for prediction", {"model_path": str(model_path), "schema_path": str(schema_path)}, ["Train and save the model first", "Provide a valid model_dir"]))
        model = joblib.load(model_path)
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        task_type = schema.get("task_type", self._task_type)
        if schema.get("modality") in ("text_heavy", "bilingual") and schema.get("text_columns"):
            text_col = schema["text_columns"][0]
            if text_col not in new_df.columns:
                _raise(_failure("Prediction input is missing the text column used during training", {"text_column": text_col}, ["Provide the required text column", "Use the same preprocessing bridge"] ))
            X_new = new_df[text_col].map(lambda t: _normalize_text(t, schema.get("language", self._lang)))
        else:
            X_new = self._prepare_tabular_for_prediction(new_df, schema)
        pred = model.predict(X_new)
        label_encoder = None
        le_path = directory / "label_encoder.pkl"
        if le_path.exists():
            label_encoder = joblib.load(le_path)
        warnings_: List[str] = []
        rows = []
        if task_type == "classification":
            labels = label_encoder.inverse_transform(pred.astype(int)) if label_encoder is not None else pred.astype(str)
            proba = model.predict_proba(X_new) if hasattr(model, "predict_proba") else None
            if proba is None:
                warnings_.append("The selected model does not expose probability estimates.")
            for i, p in enumerate(pred):
                rows.append({"row_index": int(i), "predicted_label": str(labels[i]), "predicted_class_id": int(p), "confidence": float(np.max(proba[i])) if proba is not None else None, "confidence_available": proba is not None})
        else:
            for i, p in enumerate(pred):
                rows.append({"row_index": int(i), "predicted_value": float(p)})
        return _json_safe({"status": "success", "task_type": task_type, "n_rows": len(rows), "predictions": rows, "warnings": warnings_})


def run_from_file(file_path: Path, text_column: Optional[str] = None, target_column: Optional[str] = None, task_type: str = "classification", output_name: str = "basira_run") -> SupervisedResult:
    df = load_file(file_path)
    if text_column and text_column in df.columns:
        lang = "arabic" if df[text_column].dropna().astype(str).str.contains(r"[\u0600-\u06FF]").mean() > 0.3 else "english"
        routing = {"task_type": task_type, "target_column": target_column, "text_columns": [text_column], "numeric_columns": [], "categorical_columns": [], "datetime_columns": [], "identifier_like_columns": [], "dataset_modality": "text_heavy", "language_profile": {"dominant_language": lang}}
    else:
        dt_cols = [c for c in df.columns if "date" in c.lower() or "time" in c.lower()]
        routing = {"task_type": task_type, "target_column": target_column, "text_columns": [], "numeric_columns": df.select_dtypes(include="number").columns.tolist(), "categorical_columns": df.select_dtypes(include="object").columns.tolist(), "datetime_columns": dt_cols, "identifier_like_columns": [], "dataset_modality": "tabular", "language_profile": {"dominant_language": "english"}}
    return SupervisedEngine(routing, output_name=output_name).run(df)


if __name__ == "__main__":
    np.random.seed(RANDOM_STATE)
    n = 160
    df_cls = pd.DataFrame({"x1": np.random.normal(size=n), "x2": np.random.normal(size=n), "category": np.random.choice(["A", "B", "C"], n)})
    df_cls["label"] = np.where(df_cls["x1"] + df_cls["x2"] > 0, "positive", "negative")
    routing_cls = {"task_type": "classification", "target_column": "label", "text_columns": [], "numeric_columns": ["x1", "x2"], "categorical_columns": ["category"], "datetime_columns": [], "identifier_like_columns": [], "dataset_modality": "tabular", "language_profile": {"dominant_language": "english"}}
    res = SupervisedEngine(routing_cls, "smoke_classification_v2").run(df_cls)
    print("Classification:", res.best_model_name, res.test_metrics, res.reliability_report["level"])
    df_reg = pd.DataFrame({"x1": np.random.normal(size=n), "x2": np.random.normal(size=n), "group": np.random.choice(["A", "B"], n)})
    df_reg["target"] = 10 + 3 * df_reg["x1"] - 2 * df_reg["x2"] + np.random.normal(scale=0.3, size=n)
    routing_reg = {"task_type": "regression", "target_column": "target", "text_columns": [], "numeric_columns": ["x1", "x2"], "categorical_columns": ["group"], "datetime_columns": [], "identifier_like_columns": [], "dataset_modality": "tabular", "language_profile": {"dominant_language": "english"}}
    res2 = SupervisedEngine(routing_reg, "smoke_regression_v2").run(df_reg)
    print("Regression:", res2.best_model_name, res2.test_metrics, res2.reliability_report["level"])


