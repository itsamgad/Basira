from __future__ import annotations

import os


os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")


import json
import math
import sys
import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from sklearn.cluster import AgglomerativeClustering, Birch, DBSCAN, KMeans
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.mixture import GaussianMixture
from sklearn.metrics import calinski_harabasz_score, davies_bouldin_score, silhouette_score
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")


RANDOM_STATE = 42
K_RANGE = range(2, 11)
MIN_SAMPLES = 20
MIN_FEATURES = 2
PCA_VARIANCE = 0.95
MAX_HIERARCHICAL_ROWS = 5_000
MAX_SILHOUETTE_SAMPLE = 5_000
LOW_CARDINALITY_LIMIT = 50
HIGH_UNIQUE_RATIO = 0.85
MODEL_OUTPUT_BASE = Path("saved_models")
BASIRA_ENGINE_VERSION = "unsupervised-enhanced-v1.0"


# =============================================================================
# Dataclasses
# =============================================================================

@dataclass
class FailureReport:
    status: str
    reason: str
    details: Dict[str, Any]
    suggestions: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


@dataclass
class ModelResult:
    algorithm: str
    n_clusters: int
    silhouette: float
    davies_bouldin: float
    calinski_harabasz: float
    labels: List[int]
    status: str = "success"
    rank: Optional[int] = None
    main_score: Optional[float] = None
    selection_reason: str = ""
    rejected_reason: str = ""
    error: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UnsupervisedResult:

    best_algorithm: str
    best_n_clusters: int
    best_silhouette: float
    best_davies_bouldin: float
    all_model_results: List[Dict[str, Any]]
    cluster_profiles: List[Dict[str, Any]]
    pca_variance_ratio: Optional[List[float]]
    pca_n_components: Optional[int]
    preparation_summary: Dict[str, Any]
    saved_model_dir: str


    best_calinski_harabasz: float = 0.0
    cluster_quality_report: Dict[str, Any] = field(default_factory=dict)
    anomaly_report: Dict[str, Any] = field(default_factory=dict)
    feature_schema: Dict[str, Any] = field(default_factory=dict)
    feature_importance: List[Dict[str, Any]] = field(default_factory=list)
    insights: List[Dict[str, Any]] = field(default_factory=list)
    narrative_insights: Dict[str, Any] = field(default_factory=dict)
    chart_recommendations: List[Dict[str, Any]] = field(default_factory=list)
    chart_data: Dict[str, Any] = field(default_factory=dict)
    dashboard_payload: Dict[str, Any] = field(default_factory=dict)
    rca_ready_payload: Dict[str, Any] = field(default_factory=dict)
    assignment_ready: bool = False
    warnings: List[str] = field(default_factory=list)


class BasiraUnsupervisedError(RuntimeError):
    def __init__(self, report: FailureReport) -> None:
        self.report = report
        super().__init__(report.reason)


# =============================================================================
# JSON and failure helpers
# =============================================================================

_ENCODINGS = ["utf-8-sig", "cp1256", "utf-8", "latin1"]


def _failure(reason: str, details: Dict[str, Any], suggestions: List[str]) -> FailureReport:
    return FailureReport(status="failed", reason=reason, details=_json_safe(details), suggestions=suggestions)


def _raise(report: FailureReport) -> None:
    raise BasiraUnsupervisedError(report)


def _json_safe(obj: Any) -> Any:
    """Recursively convert any value to a JSON-serialisable form.
    Aligned across all four Basira engines — do not modify without
    updating supervised_engine_enhanced.py, rca_engine_enhanced.py,
    and insight_engine_enhanced.py in lock-step.
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


def _write_json(path: Path, payload: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_json_safe(payload), f, indent=2, ensure_ascii=False)


# =============================================================================
# File loading
# =============================================================================


def _has_broken_bytes(text: str) -> bool:
    return any(marker in text for marker in ["Ù", "Ø", "Ã", "\ufffd"])


def load_file(path: Path) -> pd.DataFrame:
    if not path.exists():
        _raise(_failure(
            reason=f"Dataset not found: '{path.name}'",
            details={"path": str(path)},
            suggestions=["Verify the file path is correct and the file exists."],
        ))

    suffix = path.suffix.lower()

    if suffix in (".xlsx", ".xls", ".xlsm"):
        try:
            return pd.read_excel(path, engine="openpyxl" if suffix == ".xlsx" else None)
        except Exception as exc:
            _raise(_failure(
                reason=f"Failed to read Excel file '{path.name}'",
                details={"error": str(exc)},
                suggestions=["Ensure the file is not password-protected or corrupted."],
            ))

    if suffix == ".csv":
        last_err: Exception = RuntimeError("No encodings tried.")
        for enc in _ENCODINGS:
            try:
                df = pd.read_csv(path, encoding=enc, on_bad_lines="skip")
                sample_values: List[str] = []
                for c in df.columns:
                    s = df[c].dropna()
                    if not s.empty:
                        sample_values.append(str(s.iloc[0]))
                    if len(" ".join(sample_values)) > 500:
                        break
                if not _has_broken_bytes(" ".join(sample_values)[:500]):
                    return df
                last_err = ValueError(f"Encoding '{enc}' produced garbled text.")
            except Exception as exc:
                last_err = exc
        _raise(_failure(
            reason=f"Could not decode CSV '{path.name}' with any supported encoding.",
            details={"tried_encodings": _ENCODINGS, "last_error": str(last_err)},
            suggestions=["Re-save the file in UTF-8 or UTF-8-BOM encoding and retry."],
        ))

    _raise(_failure(
        reason=f"Unsupported file extension: '{suffix}'",
        details={"extension": suffix},
        suggestions=["Provide a .csv, .xlsx, .xls, or .xlsm file."],
    ))


# =============================================================================
# Validation and preprocessing
# =============================================================================


def _clean_col_name(col: Any) -> str:
    s = str(col).strip()
    return s if s else "unnamed_column"


def _is_identifier_like(name: str, series: pd.Series, n_rows: int) -> bool:
    lower = name.lower().strip()
    key_terms = [
        "id", "uuid", "guid", "key", "index", "row", "record", "ticket", "incident",
        "case", "request", "req", "pr", "po", "rfx", "email", "phone", "mobile",
    ]
    unique_ratio = series.nunique(dropna=True) / max(n_rows, 1)
    if lower in {"id", "index", "row", "key"}:
        return True
    if any(term in lower for term in key_terms) and unique_ratio >= 0.70:
        return True
    if unique_ratio >= 0.98 and not pd.api.types.is_float_dtype(series):
        return True
    return False


def _is_datetime_like_name(name: str) -> bool:
    lower = name.lower()
    return any(t in lower for t in ["date", "time", "timestamp", "created", "resolved", "closed", "opened"])


def _validate_prepared(X: np.ndarray, feature_names: List[str], n_rows: int) -> None:
    if n_rows < MIN_SAMPLES:
        _raise(_failure(
            reason="Dataset is too small for reliable unsupervised learning.",
            details={"n_rows": n_rows, "min_required": MIN_SAMPLES},
            suggestions=[f"Provide at least {MIN_SAMPLES} rows."],
        ))
    if len(feature_names) < MIN_FEATURES:
        _raise(_failure(
            reason="Insufficient usable features for clustering.",
            details={"usable_features": feature_names, "min_required": MIN_FEATURES},
            suggestions=[
                "Ensure the dataset contains at least two informative numeric or low-cardinality categorical features.",
                "Run Basira preprocessing first to generate model-ready numeric features.",
            ],
        ))
    if X.shape[0] < MIN_SAMPLES or X.shape[1] < MIN_FEATURES:
        _raise(_failure(
            reason="Prepared feature matrix is too small for clustering.",
            details={"matrix_shape": X.shape},
            suggestions=["Check that preprocessing did not remove too many rows or features."],
        ))


def _preprocess(df: pd.DataFrame) -> Tuple[np.ndarray, pd.DataFrame, List[int], Dict[str, Any], Dict[str, Any], StandardScaler]:
    """Prepare a model-ready matrix while keeping row mapping for dashboard outputs."""
    if df.empty:
        _raise(_failure(
            reason="Input dataset is empty.",
            details={"shape": df.shape},
            suggestions=["Upload a dataset with rows and columns."],
        ))

    original = df.copy()
    original.columns = [_clean_col_name(c) for c in original.columns]
    n_rows = len(original)

    dropped_id_like: List[str] = []
    dropped_datetime_like: List[str] = []
    dropped_high_cardinality_text: List[str] = []
    dropped_constant: List[str] = []
    numeric_columns: List[str] = []
    categorical_columns: List[str] = []
    encoded_categoricals: List[str] = []
    text_embedding_columns: List[str] = []

    working_parts: List[pd.DataFrame] = []

    for col in original.columns:
        s = original[col]
        if _is_identifier_like(col, s, n_rows):
            dropped_id_like.append(col)
            continue

        if pd.api.types.is_numeric_dtype(s):
            if s.nunique(dropna=True) <= 1:
                dropped_constant.append(col)
                continue
            numeric_columns.append(col)
            if col.startswith("text_emb_") or col.startswith("[NLP]") or "embedding" in col.lower():
                text_embedding_columns.append(col)
            working_parts.append(pd.DataFrame({col: pd.to_numeric(s, errors="coerce")}))
            continue

        if pd.api.types.is_datetime64_any_dtype(s) or _is_datetime_like_name(col):
            dropped_datetime_like.append(col)
            continue

        nunique = int(s.nunique(dropna=True))
        unique_ratio = nunique / max(n_rows, 1)
        avg_len = float(s.dropna().astype(str).map(len).mean()) if s.notna().any() else 0.0

        if nunique <= LOW_CARDINALITY_LIMIT and unique_ratio <= 0.50:
            categorical_columns.append(col)
            tmp = s.astype("object").where(s.notna(), "Unknown").astype(str)
            dummies = pd.get_dummies(tmp, prefix=col, dummy_na=False, dtype=float)
            if not dummies.empty:
                encoded_categoricals.append(col)
                working_parts.append(dummies)
        else:
            dropped_high_cardinality_text.append(col)

    if not working_parts:
        _raise(_failure(
            reason="No usable clustering features could be created.",
            details={"columns": original.columns.tolist()},
            suggestions=[
                "Run Basira preprocessing to generate numeric, categorical, datetime, or embedding features.",
                "Remove identifier-only columns or provide more analytical variables.",
            ],
        ))

    features_df = pd.concat(working_parts, axis=1)
    features_df = features_df.loc[:, ~features_df.columns.duplicated()].copy()

    for c in features_df.columns:
        features_df[c] = pd.to_numeric(features_df[c], errors="coerce")
    empty_cols = features_df.columns[features_df.isna().all()].tolist()
    if empty_cols:
        features_df.drop(columns=empty_cols, inplace=True)
        dropped_constant.extend(empty_cols)

    imputer = SimpleImputer(strategy="median")
    imputed = pd.DataFrame(imputer.fit_transform(features_df), columns=features_df.columns, index=features_df.index)
    nunique_after = imputed.nunique(dropna=True)
    near_constant = nunique_after[nunique_after <= 1].index.tolist()
    if near_constant:
        imputed.drop(columns=near_constant, inplace=True)
        dropped_constant.extend(near_constant)

    row_mask = imputed.notna().all(axis=1)
    imputed = imputed.loc[row_mask].copy()
    row_indices = imputed.index.astype(int).tolist()

    scaler = StandardScaler()
    X = scaler.fit_transform(imputed)

    feature_schema = {
        "feature_columns": imputed.columns.tolist(),
        "numeric_columns": numeric_columns,
        "categorical_columns": categorical_columns,
        "encoded_categoricals": encoded_categoricals,
        "text_embedding_columns": text_embedding_columns,
        "identifier_like_columns": dropped_id_like,
        "dropped_datetime_like_columns": dropped_datetime_like,
        "dropped_high_cardinality_text_columns": dropped_high_cardinality_text,
        "dropped_constant_or_empty_columns": sorted(set(dropped_constant)),
        "row_indices_used": row_indices,
        "feature_fill_values": {str(c): round(float(imputed[c].median()), 6) for c in imputed.columns},
    }

    prep_summary = {
        "initial_rows": int(len(df)),
        "initial_columns": int(df.shape[1]),
        "rows_used": int(imputed.shape[0]),
        "features_used": int(imputed.shape[1]),
        "feature_columns": imputed.columns.tolist(),
        "numeric_features": len(numeric_columns),
        "categorical_features_encoded": len(encoded_categoricals),
        "text_embedding_features": len(text_embedding_columns),
        "dropped_id_like": dropped_id_like,
        "dropped_datetime_like": dropped_datetime_like,
        "dropped_high_cardinality_text": dropped_high_cardinality_text,
        "dropped_constant_or_empty": sorted(set(dropped_constant)),
        "missing_values_after_imputation": int(pd.isna(imputed).sum().sum()),
    }

    _validate_prepared(X, imputed.columns.tolist(), imputed.shape[0])
    return X, imputed, row_indices, prep_summary, feature_schema, scaler


# =============================================================================
# Dimensionality reduction
# =============================================================================


def _apply_pca(X: np.ndarray) -> Tuple[np.ndarray, Optional[PCA], Optional[List[float]], Optional[int]]:
    if X.shape[1] <= 2:
        return X, None, None, None
    max_components = min(X.shape[0] - 1, X.shape[1])
    if max_components < 2:
        return X, None, None, None
    pca = PCA(n_components=min(PCA_VARIANCE, 0.999999), random_state=RANDOM_STATE, svd_solver="full")
    X_pca = pca.fit_transform(X)
    variance = [round(float(v), 6) for v in pca.explained_variance_ratio_]
    return X_pca, pca, variance, int(X_pca.shape[1])


# =============================================================================
# Clustering algorithms and scoring
# =============================================================================


def _cluster_count(labels: np.ndarray) -> int:
    return len(set(labels.tolist()) - {-1})


def _score_labels(X: np.ndarray, labels: np.ndarray) -> Tuple[float, float, float]:
    n_clusters = _cluster_count(labels)
    if n_clusters < 2 or n_clusters >= len(labels):
        return -1.0, 99.0, -1.0
    try:
        sil = silhouette_score(X, labels, sample_size=min(MAX_SILHOUETTE_SAMPLE, len(X)), random_state=RANDOM_STATE)
    except Exception:
        sil = -1.0
    try:
        db = davies_bouldin_score(X, labels)
    except Exception:
        db = 99.0
    try:
        ch = calinski_harabasz_score(X, labels)
    except Exception:
        ch = -1.0
    return round(float(sil), 6), round(float(db), 6), round(float(ch), 6)


def _make_success_result(algorithm: str, labels: np.ndarray, X: np.ndarray, params: Dict[str, Any]) -> Optional[ModelResult]:
    n_clusters = _cluster_count(labels)
    sil, db, ch = _score_labels(X, labels)
    if sil < 0 or n_clusters < 2:
        return None
    return ModelResult(
        algorithm=algorithm,
        n_clusters=n_clusters,
        silhouette=sil,
        davies_bouldin=db,
        calinski_harabasz=ch,
        labels=[int(x) for x in labels.tolist()],
        params=params,
    )


def _failed_result(algorithm: str, error: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "algorithm": algorithm,
        "n_clusters": 0,
        "silhouette": -1.0,
        "davies_bouldin": 99.0,
        "calinski_harabasz": -1.0,
        "labels": [],
        "status": "failed",
        "rank": None,
        "main_score": None,
        "selection_reason": "Model failed safely and was excluded from best-model selection.",
        "rejected_reason": "Training or scoring failed.",
        "error": error,
        "params": params or {},
    }


def _run_kmeans_family(X: np.ndarray) -> Tuple[List[ModelResult], List[Dict[str, Any]], Dict[str, Any]]:
    results: List[ModelResult] = []
    failed: List[Dict[str, Any]] = []
    fitted_models: Dict[str, Any] = {}
    for k in K_RANGE:
        if k >= len(X):
            break
        for name, estimator in [
            ("KMeans", KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=10)),
        ]:
            params = {"n_clusters": k}
            try:
                labels = estimator.fit_predict(X)
                result = _make_success_result(name, labels, X, params)
                if result:
                    results.append(result)
                    fitted_models[f"{name}_k{k}"] = estimator
            except Exception as exc:
                failed.append(_failed_result(name, str(exc), params))
    return results, failed, fitted_models


def _run_gaussian_mixture(X: np.ndarray) -> Tuple[List[ModelResult], List[Dict[str, Any]], Dict[str, Any]]:
    results: List[ModelResult] = []
    failed: List[Dict[str, Any]] = []
    fitted_models: Dict[str, Any] = {}
    for k in K_RANGE:
        if k >= len(X):
            break
        params = {"n_components": k, "covariance_type": "full"}
        try:
            gmm = GaussianMixture(n_components=k, covariance_type="full", random_state=RANDOM_STATE, reg_covar=1e-6)
            labels = gmm.fit_predict(X)
            result = _make_success_result("GaussianMixture", labels, X, params)
            if result:
                results.append(result)
                fitted_models[f"GaussianMixture_k{k}"] = gmm
        except Exception as exc:
            failed.append(_failed_result("GaussianMixture", str(exc), params))
    return results, failed, fitted_models


def _run_agglomerative(X: np.ndarray) -> Tuple[List[ModelResult], List[Dict[str, Any]]]:
    results: List[ModelResult] = []
    failed: List[Dict[str, Any]] = []
    if len(X) > MAX_HIERARCHICAL_ROWS:
        failed.append(_failed_result(
            "AgglomerativeClustering",
            f"Skipped because row count {len(X)} exceeds safe limit {MAX_HIERARCHICAL_ROWS}.",
            {"safe_limit": MAX_HIERARCHICAL_ROWS},
        ))
        return results, failed
    for k in K_RANGE:
        if k >= len(X):
            break
        params = {"n_clusters": k, "linkage": "ward"}
        try:
            agg = AgglomerativeClustering(n_clusters=k, linkage="ward")
            labels = agg.fit_predict(X)
            result = _make_success_result("AgglomerativeClustering", labels, X, params)
            if result:
                results.append(result)
        except Exception as exc:
            failed.append(_failed_result("AgglomerativeClustering", str(exc), params))
    return results, failed


def _run_hierarchical_linkage(X: np.ndarray) -> Tuple[List[ModelResult], List[Dict[str, Any]]]:
    results: List[ModelResult] = []
    failed: List[Dict[str, Any]] = []
    if len(X) > MAX_HIERARCHICAL_ROWS:
        failed.append(_failed_result(
            "HierarchicalWard",
            f"Skipped because row count {len(X)} exceeds safe limit {MAX_HIERARCHICAL_ROWS}.",
            {"safe_limit": MAX_HIERARCHICAL_ROWS},
        ))
        return results, failed
    try:
        Z = linkage(X, method="ward")
        for k in [2, 3, 4, 5, 6]:
            if k >= len(X):
                break
            labels = fcluster(Z, t=k, criterion="maxclust") - 1
            result = _make_success_result("HierarchicalWard", labels.astype(int), X, {"n_clusters": k, "method": "ward"})
            if result:
                results.append(result)
    except Exception as exc:
        failed.append(_failed_result("HierarchicalWard", str(exc), {"method": "ward"}))
    return results, failed


def _run_birch(X: np.ndarray) -> Tuple[List[ModelResult], List[Dict[str, Any]], Dict[str, Any]]:
    results: List[ModelResult] = []
    failed: List[Dict[str, Any]] = []
    fitted_models: Dict[str, Any] = {}
    for k in K_RANGE:
        if k >= len(X):
            break
        params = {"n_clusters": k, "threshold": 0.5}
        try:
            birch = Birch(n_clusters=k, threshold=0.5)
            labels = birch.fit_predict(X)
            result = _make_success_result("Birch", labels, X, params)
            if result:
                results.append(result)
                fitted_models[f"Birch_k{k}"] = birch
        except Exception as exc:
            failed.append(_failed_result("Birch", str(exc), params))
    return results, failed, fitted_models


def _run_dbscan_grid(X: np.ndarray) -> Tuple[List[ModelResult], List[Dict[str, Any]]]:
    results: List[ModelResult] = []
    failed: List[Dict[str, Any]] = []
    eps_values = [0.3, 0.5, 0.8, 1.0, 1.5, 2.0]
    min_samples_values = [4, 5, 8, 10]
    for eps in eps_values:
        for min_samples in min_samples_values:
            params = {"eps": eps, "min_samples": min_samples}
            try:
                db = DBSCAN(eps=eps, min_samples=min_samples)
                labels = db.fit_predict(X)
                n_clusters = _cluster_count(labels)
                noise_pct = round(float(np.mean(labels == -1) * 100), 4)
                if n_clusters < 2 or noise_pct > 60:
                    continue
                result = _make_success_result("DBSCAN", labels, X, {**params, "noise_pct": noise_pct})
                if result:
                    results.append(result)
            except Exception as exc:
                failed.append(_failed_result("DBSCAN", str(exc), params))
    return results, failed


def _rank_results(successful: List[ModelResult], failed: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not successful:
        return failed

    max_ch = max([r.calinski_harabasz for r in successful if r.calinski_harabasz is not None] or [1.0])
    for r in successful:
        db_component = 1.0 / (1.0 + max(r.davies_bouldin, 0.0))
        ch_component = (r.calinski_harabasz / max_ch) if max_ch > 0 else 0.0
        r.main_score = round(float((0.60 * r.silhouette) + (0.25 * db_component) + (0.15 * ch_component)), 6)

    ranked = sorted(successful, key=lambda r: (r.main_score or -1, r.silhouette, -r.davies_bouldin, r.calinski_harabasz), reverse=True)
    top_score = ranked[0].main_score or 0.0
    payloads: List[Dict[str, Any]] = []
    for i, r in enumerate(ranked, start=1):
        r.rank = i
        if i == 1:
            r.selection_reason = (
                "Selected because it achieved the strongest combined clustering score, prioritizing "
                "Silhouette, Davies-Bouldin, and Calinski-Harabasz metrics."
            )
            r.rejected_reason = ""
        else:
            gap = round(float(top_score - (r.main_score or 0.0)), 6)
            r.selection_reason = "Evaluated successfully but not selected as the best clustering structure."
            r.rejected_reason = f"Lower combined clustering score than the selected model by {gap}."
        payloads.append(_json_safe(asdict(r)))

    # Failed models go after successful leaderboard.
    payloads.extend(failed)
    return payloads


# =============================================================================
# Cluster profiles, quality, feature importance, anomaly detection
# =============================================================================


def _profile_clusters(features_df: pd.DataFrame, labels: List[int], row_indices: List[int]) -> List[Dict[str, Any]]:
    working = features_df.copy().reset_index(drop=True)
    working["_cluster"] = labels
    working["_source_row_index"] = row_indices[: len(working)]
    global_means = working.drop(columns=["_cluster", "_source_row_index"]).mean(numeric_only=True)

    profiles: List[Dict[str, Any]] = []
    for cid in sorted([c for c in set(labels) if c >= 0]):
        sub = working[working["_cluster"] == cid]
        size = int(len(sub))
        size_pct = round(100.0 * size / max(len(working), 1), 2)
        feature_means = sub.drop(columns=["_cluster", "_source_row_index"]).mean(numeric_only=True)
        diffs = (feature_means - global_means).sort_values(key=lambda x: x.abs(), ascending=False)
        distinctive = []
        for feat, diff in diffs.head(6).items():
            direction = "higher" if diff > 0 else "lower"
            distinctive.append({
                "feature": feat,
                "cluster_mean": round(float(feature_means.get(feat, 0.0)), 6),
                "global_mean": round(float(global_means.get(feat, 0.0)), 6),
                "difference": round(float(diff), 6),
                "direction": direction,
            })
        label_str = "Cluster " + str(cid)
        if distinctive:
            top = distinctive[0]
            label_str = f"{top['direction'].title()} {top['feature']} segment"
        profiles.append({
            "cluster_id": int(cid),
            "size": size,
            "size_pct": size_pct,
            "label": label_str,
            "feature_means": {str(k): round(float(v), 6) for k, v in feature_means.head(20).items()},
            "distinctive_features": distinctive,
            "sample_row_indices": [int(x) for x in sub["_source_row_index"].head(10).tolist()],
        })
    return profiles


def _build_cluster_quality_report(best: Dict[str, Any], all_results: List[Dict[str, Any]], labels: List[int]) -> Dict[str, Any]:
    sil = float(best.get("silhouette") or -1)
    db = float(best.get("davies_bouldin") or 99)
    ch = float(best.get("calinski_harabasz") or -1)
    n_clusters = int(best.get("n_clusters") or 0)
    counts = pd.Series(labels).value_counts().sort_index()
    counts = counts[counts.index >= 0]
    imbalance_ratio = float(counts.max() / max(counts.min(), 1)) if len(counts) else 0.0

    warnings_list: List[str] = []
    if sil >= 0.50:
        level = "High"
        reason = "Clusters are well separated according to Silhouette score."
    elif sil >= 0.25:
        level = "Moderate"
        reason = "Cluster structure exists but should be interpreted with caution."
        warnings_list.append("Silhouette score indicates moderate separation, so profiles should be validated with domain knowledge.")
    else:
        level = "Low"
        reason = "Cluster separation is weak; results are exploratory."
        warnings_list.append("Weak Silhouette score. Treat clusters as exploratory patterns, not final segments.")

    if imbalance_ratio >= 10:
        warnings_list.append("Cluster sizes are highly imbalanced; small clusters may represent anomalies or rare patterns.")

    confidence = max(0, min(100, int(round((sil + 1) / 2 * 100))))
    return {
        "level": level,
        "confidence_score": confidence,
        "reason": reason,
        "best_algorithm": best.get("algorithm"),
        "n_clusters": n_clusters,
        "silhouette": round(sil, 6),
        "davies_bouldin": round(db, 6),
        "calinski_harabasz": round(ch, 6),
        "cluster_size_imbalance_ratio": round(imbalance_ratio, 4),
        "warnings": warnings_list,
        "output_policy": {
            "show_full_dashboard": level in {"High", "Moderate"},
            "allow_decision_language": level == "High",
            "caution_required": level in {"Moderate", "Low"},
            "mark_outputs_as_exploratory": level == "Low",
        },
        "leaderboard_size": len([r for r in all_results if r.get("status") == "success"]),
    }


def _extract_feature_importance(features_df: pd.DataFrame, labels: List[int]) -> List[Dict[str, Any]]:
    working = features_df.copy().reset_index(drop=True)
    labels_arr = np.array(labels)
    valid_mask = labels_arr >= 0
    working = working.loc[valid_mask].copy()
    labels_arr = labels_arr[valid_mask]
    if working.empty or len(set(labels_arr.tolist())) < 2:
        return []

    global_mean = working.mean(axis=0)
    global_var = working.var(axis=0).replace(0, np.nan)
    scores: Dict[str, float] = {}
    for col in working.columns:
        between = 0.0
        for cid in sorted(set(labels_arr.tolist())):
            sub = working.loc[labels_arr == cid, col]
            if len(sub) == 0:
                continue
            between += len(sub) * float((sub.mean() - global_mean[col]) ** 2)
        score = between / max(float(global_var[col]) * len(working), 1e-9)
        if not math.isnan(score) and not math.isinf(score):
            scores[col] = max(float(score), 0.0)

    total = sum(scores.values()) or 1.0
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:20]
    output = []
    for rank, (feat, score) in enumerate(ranked, start=1):
        impact_pct = round(float(score / total * 100), 4)
        if impact_pct >= 30:
            level = "Critical"
        elif impact_pct >= 15:
            level = "High"
        elif impact_pct >= 5:
            level = "Medium"
        else:
            level = "Low"
        output.append({
            "rank": rank,
            "feature": feat,
            "importance": round(float(score), 6),
            "impact_pct": impact_pct,
            "direction": "cluster-separating",
            "importance_level": level,
            "explanation": f"'{feat}' contributes {impact_pct}% of the observed separation between clusters.",
        })
    return output


def _detect_anomalies(X: np.ndarray, features_df: pd.DataFrame, row_indices: List[int], labels: List[int]) -> Dict[str, Any]:
    contamination = min(0.08, max(0.02, 10 / max(len(X), 1)))
    try:
        iso = IsolationForest(contamination=contamination, random_state=RANDOM_STATE)
        pred = iso.fit_predict(X)
        scores = -iso.decision_function(X)
    except Exception as exc:
        return {
            "status": "failed",
            "reason": str(exc),
            "anomaly_count": 0,
            "anomaly_pct": 0.0,
            "top_anomalies": [],
            "feature_drivers": [],
        }

    flags = pred == -1
    anomaly_count = int(flags.sum())
    anomaly_pct = round(100.0 * anomaly_count / max(len(X), 1), 4)

    scaled = pd.DataFrame(StandardScaler().fit_transform(features_df), columns=features_df.columns)
    abs_z = scaled.abs()
    top_anomalies: List[Dict[str, Any]] = []
    anomaly_indices = np.where(flags)[0]
    top_order = sorted(anomaly_indices, key=lambda i: scores[i], reverse=True)[:20]
    for i in top_order:
        top_features = abs_z.iloc[i].sort_values(ascending=False).head(5)
        top_anomalies.append({
            "row_position": int(i),
            "source_row_index": int(row_indices[i]) if i < len(row_indices) else int(i),
            "cluster_id": int(labels[i]) if i < len(labels) else None,
            "anomaly_score": round(float(scores[i]), 6),
            "top_deviation_features": [
                {"feature": str(feat), "abs_z_score": round(float(val), 6)}
                for feat, val in top_features.items()
            ],
        })

    driver_totals = abs_z.loc[flags].mean(axis=0).sort_values(ascending=False) if anomaly_count > 0 else pd.Series(dtype=float)
    feature_drivers = [
        {"feature": str(k), "mean_abs_z_score": round(float(v), 6)}
        for k, v in driver_totals.head(10).items()
    ]

    if anomaly_pct > 10:
        level = "High"
        message = "A high share of records appear unusual and should be reviewed before decision-making."
    elif anomaly_pct > 4:
        level = "Moderate"
        message = "A moderate anomaly rate was detected; flagged records may explain unusual cluster behavior."
    else:
        level = "Low"
        message = "Anomaly rate is low and unlikely to distort the overall clustering structure."

    return {
        "status": "success",
        "method": "IsolationForest",
        "contamination": round(float(contamination), 6),
        "level": level,
        "message": message,
        "anomaly_count": anomaly_count,
        "anomaly_pct": anomaly_pct,
        "top_anomalies": top_anomalies,
        "feature_drivers": feature_drivers,
    }


# =============================================================================
# Dashboard data, insights, RCA-ready payload
# =============================================================================


def _histogram(values: List[float], bins: int = 12) -> Dict[str, Any]:
    arr = np.array([v for v in values if v is not None and not pd.isna(v)], dtype=float)
    if len(arr) == 0:
        return {"labels": [], "counts": []}
    counts, edges = np.histogram(arr, bins=min(bins, max(2, len(arr))))
    labels = [f"{edges[i]:.2f}–{edges[i+1]:.2f}" for i in range(len(counts))]
    return {"labels": labels, "counts": [int(c) for c in counts.tolist()]}


def _build_chart_data(
    features_df: pd.DataFrame,
    X_pca: np.ndarray,
    labels: List[int],
    profiles: List[Dict[str, Any]],
    all_results: List[Dict[str, Any]],
    feature_importance: List[Dict[str, Any]],
    anomaly_report: Dict[str, Any],
    quality_report: Dict[str, Any],
) -> Dict[str, Any]:
    label_series = pd.Series(labels)
    cluster_counts = label_series[label_series >= 0].value_counts().sort_index()
    cluster_labels = [f"Cluster {int(i)}" for i in cluster_counts.index.tolist()]

    leaderboard_success = [r for r in all_results if r.get("status") == "success"]
    pca_points = []
    if X_pca.shape[1] >= 2:
        sample_n = min(1000, len(X_pca))
        for i in range(sample_n):
            pca_points.append({"x": round(float(X_pca[i, 0]), 6), "y": round(float(X_pca[i, 1]), 6), "cluster": int(labels[i])})

    return {
        "summary_cards": [
            {"title": "Best Algorithm", "value": quality_report.get("best_algorithm"), "metric": "Selected clustering method"},
            {"title": "Clusters", "value": quality_report.get("n_clusters"), "metric": "Detected segments"},
            {"title": "Silhouette", "value": quality_report.get("silhouette"), "metric": "Separation quality"},
            {"title": "Davies-Bouldin", "value": quality_report.get("davies_bouldin"), "metric": "Lower is better"},
            {"title": "Quality", "value": quality_report.get("level"), "metric": "Reliability level"},
            {"title": "Anomalies", "value": f"{anomaly_report.get('anomaly_pct', 0)}%", "metric": "IsolationForest"},
        ],
        "model_leaderboard_bar": {
            "chart_type": "bar",
            "labels": [f"{r.get('algorithm')} k={r.get('n_clusters')}" for r in leaderboard_success[:10]],
            "values": [r.get("main_score") for r in leaderboard_success[:10]],
            "metric": "combined_clustering_score",
        },
        "cluster_size_doughnut": {
            "chart_type": "doughnut",
            "labels": cluster_labels,
            "values": [int(v) for v in cluster_counts.values.tolist()],
        },
        "feature_importance_bar": {
            "chart_type": "horizontal_bar",
            "labels": [x["feature"] for x in feature_importance[:12]],
            "values": [x["impact_pct"] for x in feature_importance[:12]],
        },
        "pca_cluster_scatter": {
            "chart_type": "scatter",
            "x_label": "PC1",
            "y_label": "PC2",
            "points": pca_points,
        },
        "cluster_profile_table": profiles,
        "silhouette_leaderboard": {
            "chart_type": "bar",
            "labels": [f"{r.get('algorithm')} k={r.get('n_clusters')}" for r in leaderboard_success[:10]],
            "values": [r.get("silhouette") for r in leaderboard_success[:10]],
        },
        "anomaly_score_histogram": {
            "chart_type": "histogram",
            **_histogram([a.get("anomaly_score") for a in anomaly_report.get("top_anomalies", [])], bins=8),
        },
        "top_anomalies_table": anomaly_report.get("top_anomalies", []),
    }


def _build_chart_recommendations(quality_report: Dict[str, Any], anomaly_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    exploratory = quality_report.get("level") == "Low"
    recommendations = [
        ("summary_cards", "kpi_cards", "Unsupervised Summary", "Overview", "Best for showing clustering quality and anomaly status."),
        ("model_leaderboard_bar", "bar", "Clustering Model Leaderboard", "Model Selection", "Compares all successful clustering candidates."),
        ("cluster_size_doughnut", "doughnut", "Cluster Size Distribution", "Cluster Profiles", "Shows the relative size of each discovered segment."),
        ("feature_importance_bar", "horizontal_bar", "Top Cluster-Separating Features", "Explainability", "Ranks the variables that separate clusters most strongly."),
        ("pca_cluster_scatter", "scatter", "2D Cluster Map", "Pattern Exploration", "Displays cluster separation in reduced dimensional space."),
        ("cluster_profile_table", "table", "Cluster Profiles", "Cluster Profiles", "Summarizes each cluster's distinctive characteristics."),
        ("anomaly_score_histogram", "histogram", "Anomaly Score Distribution", "Anomaly Detection", "Shows unusual-record intensity among flagged records."),
        ("top_anomalies_table", "table", "Top Anomalous Records", "Anomaly Detection", "Lists records requiring further investigation."),
    ]
    output = []
    for priority, (chart_id, chart_type, title, section, reason) in enumerate(recommendations, start=1):
        output.append({
            "chart_id": chart_id,
            "chart_type": chart_type,
            "title": title,
            "priority": priority,
            "reason": reason,
            "dashboard_section": section,
            "exploratory": exploratory,
        })
    if anomaly_report.get("level") in {"High", "Moderate"}:
        output.append({
            "chart_id": "top_anomalies_table",
            "chart_type": "table",
            "title": "Anomaly Review Priority",
            "priority": 0,
            "reason": "Anomaly level requires investigation before relying on all cluster patterns.",
            "dashboard_section": "Risk Alerts",
            "exploratory": exploratory,
        })
    return sorted(output, key=lambda x: x["priority"])


def _generate_insights(
    quality_report: Dict[str, Any],
    best: Dict[str, Any],
    profiles: List[Dict[str, Any]],
    feature_importance: List[Dict[str, Any]],
    anomaly_report: Dict[str, Any],
) -> List[Dict[str, Any]]:
    severity = "success" if quality_report.get("level") == "High" else "warning" if quality_report.get("level") == "Moderate" else "danger"
    top_feature = feature_importance[0] if feature_importance else {}
    largest_cluster = max(profiles, key=lambda p: p.get("size", 0)) if profiles else {}
    smallest_cluster = min(profiles, key=lambda p: p.get("size", 0)) if profiles else {}
    return [
        {
            "id": "cluster_quality",
            "title": "Cluster Quality",
            "value": quality_report.get("level"),
            "metric": f"Silhouette = {quality_report.get('silhouette')}",
            "description": quality_report.get("reason"),
            "action": "Use clusters confidently." if severity == "success" else "Validate cluster profiles with domain knowledge.",
            "severity": severity,
        },
        {
            "id": "best_algorithm",
            "title": "Best Clustering Method",
            "value": best.get("algorithm"),
            "metric": f"k = {best.get('n_clusters')}",
            "description": best.get("selection_reason", "Selected based on combined clustering metrics."),
            "action": "Use this result as the primary segmentation output.",
            "severity": "success",
        },
        {
            "id": "primary_cluster_driver",
            "title": "Primary Cluster Driver",
            "value": top_feature.get("feature", "N/A"),
            "metric": f"{top_feature.get('impact_pct', 0)}% separation impact",
            "description": top_feature.get("explanation", "No strong feature driver was available."),
            "action": "Use this feature first when explaining why clusters differ.",
            "severity": "success" if top_feature else "warning",
        },
        {
            "id": "cluster_size_pattern",
            "title": "Cluster Size Pattern",
            "value": f"Largest: {largest_cluster.get('size_pct', 0)}%",
            "metric": f"Smallest: {smallest_cluster.get('size_pct', 0)}%",
            "description": "Cluster sizes indicate whether the data naturally forms balanced groups or rare segments.",
            "action": "Review very small clusters as possible niche behavior or anomalies.",
            "severity": "warning" if quality_report.get("cluster_size_imbalance_ratio", 0) >= 10 else "success",
        },
        {
            "id": "anomaly_detection",
            "title": "Anomaly Detection",
            "value": f"{anomaly_report.get('anomaly_pct', 0)}%",
            "metric": f"{anomaly_report.get('anomaly_count', 0)} flagged records",
            "description": anomaly_report.get("message", "Anomaly analysis completed."),
            "action": "Investigate top anomalies before operational decisions." if anomaly_report.get("level") != "Low" else "Anomaly level is acceptable.",
            "severity": "danger" if anomaly_report.get("level") == "High" else "warning" if anomaly_report.get("level") == "Moderate" else "success",
        },
    ]


def _generate_narrative_insights(
    quality_report: Dict[str, Any],
    best: Dict[str, Any],
    profiles: List[Dict[str, Any]],
    feature_importance: List[Dict[str, Any]],
    anomaly_report: Dict[str, Any],
) -> Dict[str, Any]:
    top_feature = feature_importance[0] if feature_importance else {"feature": "N/A", "impact_pct": 0}
    quality = quality_report.get("level", "Unknown")
    if quality == "High":
        confidence_phrase = "a strong and interpretable segmentation structure"
    elif quality == "Moderate":
        confidence_phrase = "a useful but caution-required segmentation structure"
    else:
        confidence_phrase = "an exploratory segmentation structure with weak separation"
    return {
        "headline": "Basira discovered hidden segments in the dataset.",
        "summary": (
            f"The unsupervised engine evaluated multiple clustering algorithms and selected "
            f"{best.get('algorithm')} with {best.get('n_clusters')} clusters. The result shows {confidence_phrase}."
        ),
        "key_finding": (
            f"The strongest cluster-separating feature is '{top_feature.get('feature')}', "
            f"contributing {top_feature.get('impact_pct')}% of the separation signal."
        ),
        "cluster_profile_summary": (
            f"{len(profiles)} cluster profiles were generated, each describing size, distinctive features, and sample records."
        ),
        "risk_alert": anomaly_report.get("message", "No anomaly message available."),
        "recommended_action": (
            "Use the cluster profiles to understand repeated patterns, then investigate anomalies and small clusters as RCA candidates."
        ),
        "dashboard_note": "Display model leaderboard, cluster sizes, PCA scatter, top drivers, and anomaly tables together for a complete view.",
    }


def _build_rca_ready_payload(
    best: Dict[str, Any],
    profiles: List[Dict[str, Any]],
    feature_importance: List[Dict[str, Any]],
    anomaly_report: Dict[str, Any],
    quality_report: Dict[str, Any],
) -> Dict[str, Any]:
    recommended_focus = []
    if feature_importance:
        recommended_focus.append(f"Investigate operational meaning of top cluster driver: {feature_importance[0]['feature']}.")
    small_clusters = [p for p in profiles if p.get("size_pct", 0) < 5]
    if small_clusters:
        recommended_focus.append("Review very small clusters as potential rare behaviors or unresolved anomalies.")
    if anomaly_report.get("anomaly_count", 0) > 0:
        recommended_focus.append("Investigate top anomalous records and their highest deviation features.")
    if quality_report.get("level") == "Low":
        recommended_focus.append("Validate cluster stability before drawing strong RCA conclusions.")
    return {
        "status": "ready",
        "strategy": "unsupervised",
        "best_algorithm": best.get("algorithm"),
        "n_clusters": best.get("n_clusters"),
        "quality_level": quality_report.get("level"),
        "primary_driver": feature_importance[0] if feature_importance else None,
        "top_drivers": feature_importance[:10],
        "cluster_profiles": profiles,
        "anomaly_report": {
            "level": anomaly_report.get("level"),
            "anomaly_count": anomaly_report.get("anomaly_count"),
            "anomaly_pct": anomaly_report.get("anomaly_pct"),
            "top_anomalies": anomaly_report.get("top_anomalies", [])[:10],
            "feature_drivers": anomaly_report.get("feature_drivers", [])[:10],
            "status": anomaly_report.get("status", "success"),
        },
        "recommended_rca_focus": recommended_focus,
    }


def _build_dashboard_payload(
    best: Dict[str, Any],
    all_results: List[Dict[str, Any]],
    quality_report: Dict[str, Any],
    anomaly_report: Dict[str, Any],
    feature_importance: List[Dict[str, Any]],
    profiles: List[Dict[str, Any]],
    insights: List[Dict[str, Any]],
    narrative: Dict[str, Any],
    chart_recs: List[Dict[str, Any]],
    chart_data: Dict[str, Any],
    rca_ready: Dict[str, Any],
    warnings_list: List[str],
) -> Dict[str, Any]:
    return {
        "status": "ready",
        "strategy": "unsupervised",
        "best_algorithm": best.get("algorithm"),
        "best_model": best.get("algorithm"),      # alias: matches supervised key name
        "best_n_clusters": best.get("n_clusters"),
        "model_leaderboard": all_results,
        "quality": quality_report,
        "reliability": quality_report,            # alias: matches supervised key name
        "anomaly_report": anomaly_report,
        "feature_importance": feature_importance,
        "cluster_profiles": profiles,
        "summary_cards": chart_data.get("summary_cards", []),
        "insights": insights,
        "narrative": narrative,
        "chart_recommendations": chart_recs,
        "chart_data": chart_data,
        "rca_ready": rca_ready,
        "warnings": warnings_list,
        "rendering_notes": {
            "preferred_layout": "unsupervised_clustering_dashboard",
            "show_caution_banner": quality_report.get("output_policy", {}).get("caution_required", True),
            "allow_export_report": True,
            "supports_multiple_charts": True,
        },
    }


# =============================================================================
# Persistence
# =============================================================================


def _save_artifacts(
    output_dir: Path,
    best_payload: Dict[str, Any],
    best_model: Optional[Any],
    scaler: StandardScaler,
    pca_model: Optional[PCA],
    feature_schema: Dict[str, Any],
    preparation_summary: Dict[str, Any],
    all_results: List[Dict[str, Any]],
    profiles: List[Dict[str, Any]],
    quality_report: Dict[str, Any],
    anomaly_report: Dict[str, Any],
    feature_importance: List[Dict[str, Any]],
    chart_data: Dict[str, Any],
    chart_recommendations: List[Dict[str, Any]],
    insights: List[Dict[str, Any]],
    narrative: Dict[str, Any],
    dashboard_payload: Dict[str, Any],
    rca_ready: Dict[str, Any],
    labels: List[int],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(scaler, output_dir / "scaler.pkl")
    if pca_model is not None:
        joblib.dump(pca_model, output_dir / "pca.pkl")
    if best_model is not None:
        joblib.dump(best_model, output_dir / "best_cluster_model.pkl")

    metadata = {
        "basira_engine_version": BASIRA_ENGINE_VERSION,
        "strategy": "unsupervised",
        "best_algorithm": best_payload.get("algorithm"),
        "best_n_clusters": best_payload.get("n_clusters"),
        "created_at": datetime.now().isoformat(),
        "random_state": RANDOM_STATE,
        "number_of_rows_used": preparation_summary.get("rows_used"),
        "number_of_features_used": preparation_summary.get("features_used"),
        "assignment_ready": best_model is not None,
        "model_selection_metric": "combined_score = 0.60*silhouette + 0.25*(1/(1+DB)) + 0.15*normalized_CH",
    }

    labels_df = pd.DataFrame({
        "row_position": list(range(len(labels))),
        "source_row_index": feature_schema.get("row_indices_used", list(range(len(labels))))[: len(labels)],
        "cluster_label": labels,
    })
    labels_df.to_csv(output_dir / "cluster_assignments.csv", index=False)

    _write_json(output_dir / "metadata.json", metadata)
    _write_json(output_dir / "feature_schema.json", feature_schema)
    _write_json(output_dir / "preparation_summary.json", preparation_summary)
    _write_json(output_dir / "all_model_results.json", all_results)
    _write_json(output_dir / "cluster_quality_report.json", quality_report)
    _write_json(output_dir / "cluster_profiles.json", profiles)
    _write_json(output_dir / "anomaly_report.json", anomaly_report)
    _write_json(output_dir / "feature_importance.json", feature_importance)
    _write_json(output_dir / "chart_data.json", chart_data)
    _write_json(output_dir / "chart_recommendations.json", chart_recommendations)
    _write_json(output_dir / "insights.json", insights)
    _write_json(output_dir / "narrative_insights.json", narrative)
    _write_json(output_dir / "dashboard_payload.json", dashboard_payload)
    _write_json(output_dir / "rca_ready_payload.json", rca_ready)

    _write_json(output_dir / "unsupervised_results.json", {
        "project": "Basira",
        "phase": "Unsupervised Analytics",
        "metadata": metadata,
        "best_model": best_payload,
        "all_models": all_results,
        "cluster_profiles": profiles,
        "quality_report": quality_report,
        "anomaly_report": anomaly_report,
        "dashboard_payload": dashboard_payload,
    })


# =============================================================================
# Engine
# =============================================================================

class UnsupervisedEngine:
    def __init__(self, output_name: str = "unsupervised_run") -> None:
        self.output_dir = MODEL_OUTPUT_BASE / output_name

    def run(self, df: pd.DataFrame) -> UnsupervisedResult:
        warnings_list: List[str] = []
        print("=" * 70)
        print("  Basira — Enhanced Unsupervised Analytics Engine")
        print("=" * 70)

        X_scaled, features_df, row_indices, prep_summary, feature_schema, scaler = _preprocess(df)
        print(f"  Features  : {features_df.shape[1]}  |  Rows: {features_df.shape[0]}")

        X_model, pca_model, variance, pca_n = _apply_pca(X_scaled)
        if pca_n is not None:
            print(f"  PCA       : {X_scaled.shape[1]} → {pca_n} components ({sum(variance or []):.1%} variance)")

        all_success: List[ModelResult] = []
        all_failed: List[Dict[str, Any]] = []
        fitted_models: Dict[str, Any] = {}

        for runner in [_run_kmeans_family, _run_gaussian_mixture, _run_birch]:
            results, failed, fitted = runner(X_model)
            all_success.extend(results)
            all_failed.extend(failed)
            fitted_models.update(fitted)

        results, failed = _run_agglomerative(X_model)
        all_success.extend(results)
        all_failed.extend(failed)

        results, failed = _run_hierarchical_linkage(X_model)
        all_success.extend(results)
        all_failed.extend(failed)

        results, failed = _run_dbscan_grid(X_model)
        all_success.extend(results)
        all_failed.extend(failed)

        if not all_success:
            _raise(_failure(
                reason="No clustering algorithm produced valid results.",
                details={"n_rows": prep_summary["rows_used"], "n_features": prep_summary["features_used"], "failed_models": all_failed[:5]},
                suggestions=[
                    "Ensure the dataset has enough numeric diversity.",
                    "Remove duplicate or constant columns.",
                    "Run Basira preprocessing first to generate robust model-ready features.",
                ],
            ))

        all_results = _rank_results(all_success, all_failed)
        best = all_results[0]
        labels = [int(x) for x in best.get("labels", [])]
        print(f"  Best model: {best['algorithm']}  k={best['n_clusters']}  "
              f"Silhouette={best['silhouette']:.4f}  DB={best['davies_bouldin']:.4f}  CH={best['calinski_harabasz']:.2f}")

        profiles = _profile_clusters(features_df, labels, row_indices)
        quality_report = _build_cluster_quality_report(best, all_results, labels)
        warnings_list.extend(quality_report.get("warnings", []))
        feature_importance = _extract_feature_importance(features_df, labels)
        anomaly_report = _detect_anomalies(X_model, features_df, row_indices, labels)
        if anomaly_report.get("status") == "failed":
            warnings_list.append(f"Anomaly detection failed: {anomaly_report.get('reason')}")

        chart_data = _build_chart_data(features_df, X_model, labels, profiles, all_results, feature_importance, anomaly_report, quality_report)
        chart_recommendations = _build_chart_recommendations(quality_report, anomaly_report)
        insights = _generate_insights(quality_report, best, profiles, feature_importance, anomaly_report)
        narrative = _generate_narrative_insights(quality_report, best, profiles, feature_importance, anomaly_report)
        rca_ready = _build_rca_ready_payload(best, profiles, feature_importance, anomaly_report, quality_report)
        dashboard_payload = _build_dashboard_payload(
            best=best,
            all_results=all_results,
            quality_report=quality_report,
            anomaly_report=anomaly_report,
            feature_importance=feature_importance,
            profiles=profiles,
            insights=insights,
            narrative=narrative,
            chart_recs=chart_recommendations,
            chart_data=chart_data,
            rca_ready=rca_ready,
            warnings_list=warnings_list,
        )

        model_key = f"{best.get('algorithm')}_k{best.get('n_clusters')}"
        best_model = fitted_models.get(model_key)
        assignment_ready = best_model is not None and hasattr(best_model, "predict")

        _save_artifacts(
            output_dir=self.output_dir,
            best_payload=best,
            best_model=best_model if assignment_ready else None,
            scaler=scaler,
            pca_model=pca_model,
            feature_schema=feature_schema,
            preparation_summary=prep_summary,
            all_results=all_results,
            profiles=profiles,
            quality_report=quality_report,
            anomaly_report=anomaly_report,
            feature_importance=feature_importance,
            chart_data=chart_data,
            chart_recommendations=chart_recommendations,
            insights=insights,
            narrative=narrative,
            dashboard_payload=dashboard_payload,
            rca_ready=rca_ready,
            labels=labels,
        )

        print(f"  Quality   : {quality_report['level']} ({quality_report['confidence_score']}%)")
        print(f"  Anomalies : {anomaly_report.get('anomaly_pct', 0)}%")
        print(f"  Saved     → {self.output_dir}")
        print("=" * 70)

        return UnsupervisedResult(
            best_algorithm=str(best.get("algorithm")),
            best_n_clusters=int(best.get("n_clusters") or 0),
            best_silhouette=float(best.get("silhouette") or -1.0),
            best_davies_bouldin=float(best.get("davies_bouldin") or 99.0),
            all_model_results=all_results,
            cluster_profiles=profiles,
            pca_variance_ratio=variance,
            pca_n_components=pca_n,
            preparation_summary=prep_summary,
            saved_model_dir=str(self.output_dir),
            best_calinski_harabasz=float(best.get("calinski_harabasz") or -1.0),
            cluster_quality_report=quality_report,
            anomaly_report=anomaly_report,
            feature_schema=feature_schema,
            feature_importance=feature_importance,
            insights=insights,
            narrative_insights=narrative,
            chart_recommendations=chart_recommendations,
            chart_data=chart_data,
            dashboard_payload=dashboard_payload,
            rca_ready_payload=rca_ready,
            assignment_ready=assignment_ready,
            warnings=warnings_list,
        )


    def _prepare_for_assignment(self, new_df: pd.DataFrame, schema: Dict[str, Any]) -> pd.DataFrame:
        """Prepare new records for cluster assignment using the saved training schema."""
        original = new_df.copy()
        original.columns = [_clean_col_name(c) for c in original.columns]
        feature_columns = schema.get("feature_columns", [])
        fill_values = schema.get("feature_fill_values", {})
        if not feature_columns:
            _raise(_failure(
                reason="Saved feature schema does not contain training feature columns.",
                details={"schema_keys": list(schema.keys())},
                suggestions=["Re-run clustering with the updated engine to save a complete schema."],
            ))

        prepared = pd.DataFrame(0.0, index=original.index, columns=feature_columns)

        # Direct numeric / engineered columns that already exist in the new input.
        for col in feature_columns:
            if col in original.columns:
                prepared[col] = pd.to_numeric(original[col], errors="coerce")

        # Rebuild one-hot columns for categoricals and align only to known training columns.
        for cat_col in schema.get("categorical_columns", []):
            if cat_col in original.columns:
                tmp = original[cat_col].astype("object").where(original[cat_col].notna(), "Unknown").astype(str)
                dummies = pd.get_dummies(tmp, prefix=cat_col, dummy_na=False, dtype=float)
                for dcol in dummies.columns:
                    if dcol in prepared.columns:
                        prepared[dcol] = dummies[dcol].astype(float)

        for col in prepared.columns:
            fill = fill_values.get(col, 0.0)
            prepared[col] = pd.to_numeric(prepared[col], errors="coerce").fillna(fill)
        return prepared

    def assign_clusters(self, new_df: pd.DataFrame, model_dir: Optional[str] = None) -> Dict[str, Any]:
        """Assign new records to saved clusters when the selected clustering model supports prediction."""
        directory = Path(model_dir) if model_dir else self.output_dir
        model_path = directory / "best_cluster_model.pkl"
        scaler_path = directory / "scaler.pkl"
        schema_path = directory / "feature_schema.json"
        pca_path = directory / "pca.pkl"
        if not model_path.exists():
            _raise(_failure(
                reason="Saved clustering model is not assignment-ready.",
                details={"model_path": str(model_path)},
                suggestions=[
                    "Use the saved cluster_assignments.csv for the training data.",
                    "Re-run clustering; KMeans, Birch, or GaussianMixture selections can support new-record assignment.",
                ],
            ))
        if not scaler_path.exists() or not schema_path.exists():
            _raise(_failure(
                reason="Saved preprocessing artifacts are missing for cluster assignment.",
                details={"scaler_path": str(scaler_path), "schema_path": str(schema_path)},
                suggestions=["Train and save the unsupervised engine before assigning new records."],
            ))

        model = joblib.load(model_path)
        scaler = joblib.load(scaler_path)
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)

        X_new_df = self._prepare_for_assignment(new_df, schema)
        X_scaled = scaler.transform(X_new_df)
        if pca_path.exists():
            pca = joblib.load(pca_path)
            X_model = pca.transform(X_scaled)
        else:
            X_model = X_scaled

        labels = model.predict(X_model)
        rows = [{"row_index": int(i), "assigned_cluster": int(label)} for i, label in enumerate(labels)]
        return _json_safe({
            "status": "success",
            "strategy": "unsupervised_cluster_assignment",
            "n_rows": len(rows),
            "assignments": rows,
            "warnings": [],
        })


# =============================================================================
# Convenience entry point
# =============================================================================


def run_from_file(file_path: Path, output_name: str = "unsupervised_run") -> UnsupervisedResult:
    df = load_file(file_path)
    engine = UnsupervisedEngine(output_name=output_name)
    return engine.run(df)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python unsupervised_engine_enhanced.py <dataset.csv|xlsx> [output_name]")
        sys.exit(1)
    path = Path(sys.argv[1])
    output = sys.argv[2] if len(sys.argv) >= 3 else "unsupervised_demo_run"
    try:
        result = run_from_file(path, output_name=output)
        print(
            f"Unsupervised: {result.best_algorithm} k={result.best_n_clusters} "
            f"silhouette={result.best_silhouette:.4f} quality={result.cluster_quality_report.get('level')} "
            f"anomalies={result.anomaly_report.get('anomaly_pct', 0)}%"
        )
    except BasiraUnsupervisedError as exc:
        print(exc.report.to_json())
        sys.exit(2)
