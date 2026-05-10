"""
BASIRA BRIDGE ORCHESTRATOR - FINAL PIPELINE COORDINATOR
=========================================================
Connects Basira's final analytical engines with the visualization layer.

Pipeline:
Preprocessing / uploaded clean data
→ Bridge / Orchestrator
→ Supervised OR Unsupervised engine
→ RCA engine
→ Insight engine
→ Unified JSON payload for visualization/report

This file does NOT merge or rewrite the final engines.
It only coordinates them and exposes a Flask /analyze endpoint.

Config priority order
----------------------
1. If strategy / force_strategy == "unsupervised"  → force unsupervised.
2. If explicit target_column + task_type passed in the request → use them.
3. If config.json uploaded → use task_type, target_column, modality, etc. from config.
4. Else → fall back to internal inference.

If config specifies a target column that does NOT exist in the uploaded
dataframe, the bridge returns a clear 422 error instead of silently
picking a different column.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import traceback
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    from flask import Flask, jsonify, request
    from flask_cors import CORS
    FLASK_AVAILABLE = True
except Exception:  # pragma: no cover — allows smoke tests without Flask
    Flask   = None
    request = None
    FLASK_AVAILABLE = False
    def jsonify(obj=None, *args, **kwargs):  # type: ignore
        return obj
    def CORS(app):  # type: ignore
        return app

# Keep numerical libraries from spinning up extra threads on student devices.
os.environ.setdefault("OMP_NUM_THREADS",        "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS",   "1")
os.environ.setdefault("MKL_NUM_THREADS",        "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS",    "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")

APP_DIR    = Path(__file__).resolve().parent
UPLOAD_DIR = APP_DIR / "bridge_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Final Basira engines  (never rewrite or merge these)
# ---------------------------------------------------------------------------
from supervised_engine_F   import SupervisedEngine,   BasiraEngineError
from unsupervised_engine_F import UnsupervisedEngine, BasiraUnsupervisedError
from rca_engine_F          import RCAEngine,           BasiraRCAError
from insight_engine_F      import InsightEngine,       BasiraInsightError

# Optional chart helpers — bridge still works if charts_engine is absent.
try:
    import charts_engine  # type: ignore
except Exception:       # pragma: no cover
    charts_engine = None

# ---------------------------------------------------------------------------
# Flask application
# ---------------------------------------------------------------------------
if FLASK_AVAILABLE:
    app = Flask(__name__)
    CORS(app)
else:
    class _DummyApp:  # type: ignore
        def route(self, *a, **kw):
            def _d(f): return f
            return _d
        def run(self, *a, **kw):
            raise RuntimeError("Flask not installed. Run: pip install -r requirements.txt")
    app = _DummyApp()

BRIDGE_VERSION = "basira-bridge-v1.1"


# =============================================================================
# JSON safety  (mirrors the engines' own _json_safe for consistency)
# =============================================================================

def json_safe(obj: Any) -> Any:
    """Recursively convert NumPy / Pandas / dataclass values into JSON-safe types."""
    if is_dataclass(obj):
        return json_safe(asdict(obj))
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(obj, np.ndarray):
        return json_safe(obj.tolist())
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if obj is pd.NA:
        return None
    if obj is None or isinstance(obj, (str, int, bool)):
        return obj
    return str(obj)


def result_to_dict(result: Any) -> Dict[str, Any]:
    """Convert an engine result dataclass/object to a plain dict safely."""
    if hasattr(result, "to_dict"):
        return json_safe(result.to_dict())
    if is_dataclass(result):
        return json_safe(asdict(result))
    if isinstance(result, dict):
        return json_safe(result)
    if hasattr(result, "__dict__"):
        return json_safe(vars(result))
    return {}


# =============================================================================
# File loading
# =============================================================================

def load_uploaded_dataframe(file_storage) -> Tuple[pd.DataFrame, Path]:
    """Save and read the uploaded CSV / XLSX dataset."""
    filename = Path(file_storage.filename or "uploaded.csv").name
    suffix   = Path(filename).suffix.lower()
    if suffix not in {".csv", ".xlsx", ".xls"}:
        raise ValueError("Unsupported file type. Please upload CSV, XLSX, or XLS.")

    stamp     = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename)
    saved     = UPLOAD_DIR / f"{stamp}_{safe_name}"
    file_storage.save(saved)

    df = pd.read_csv(saved) if suffix == ".csv" else pd.read_excel(saved)
    if df.empty:
        raise ValueError("The uploaded dataset is empty.")
    df.columns = [str(c).strip() for c in df.columns]
    return df, saved


# =============================================================================
# Config.json loading and resolution
# =============================================================================

def load_optional_config(config_file_storage) -> Optional[Dict[str, Any]]:
    """
    Read and parse the optional config.json uploaded by the user.

    The preprocessor (basira_app.py) writes this file.  Returns None when no
    config file is supplied or when parsing fails (the bridge then falls back
    to internal inference).

    Parameters
    ----------
    config_file_storage : werkzeug.datastructures.FileStorage or None
        The file received under the 'config' field in the multipart request.

    Returns
    -------
    dict or None
    """
    if config_file_storage is None:
        return None
    try:
        raw = config_file_storage.read()
        if not raw:
            return None
        cfg = json.loads(raw.decode("utf-8"))
        if not isinstance(cfg, dict):
            return None
        return cfg
    except Exception as exc:
        # Log but do not crash — fall back to inference.
        print(f"[Bridge] Warning: failed to parse config.json: {exc}")
        return None


def resolve_task_from_config(
    df: pd.DataFrame,
    cfg: Dict[str, Any],
) -> Tuple[str, Optional[str]]:
    """
    Extract task_type and target_column from a preprocessor config dict.

    Rules
    -----
    - If task_type == "unsupervised", target_column is forcibly set to None.
    - If task_type is supervised and target_column is given, verify it exists
      in df.  Raise ValueError with a clear message if it is missing.

    Parameters
    ----------
    df  : The uploaded dataframe (used only for column validation).
    cfg : Parsed config.json dict from the preprocessor.

    Returns
    -------
    (task_type, target_column)  — target_column is None for unsupervised.
    """
    task_type = str(cfg.get("task_type", "")).lower().strip()
    if task_type not in {"classification", "regression", "unsupervised"}:
        # Unrecognised or missing — treat as missing so inference takes over.
        task_type = ""

    # Resolve target column (preprocessor may use either key)
    target_col = (
        cfg.get("target_column")
        or cfg.get("target_col")
        or None
    )
    if isinstance(target_col, str):
        target_col = target_col.strip() or None

    # --- Unsupervised ---
    if task_type == "unsupervised":
        return "unsupervised", None

    # --- Supervised: validate target exists ---
    if task_type in {"classification", "regression"} and target_col is not None:
        if target_col not in df.columns:
            raise ValueError(
                f"Config specifies target_column='{target_col}' "
                f"but that column does not exist in the uploaded dataframe. "
                f"Available columns: {df.columns.tolist()}"
            )
        return task_type, target_col

    # Config has a supervised task_type but no target — fall through to inference.
    if task_type in {"classification", "regression"}:
        return task_type, None   # caller will infer the target

    # task_type was empty / unrecognised
    return "", None


def build_routing_decision_from_config(
    df: pd.DataFrame,
    target_col: Optional[str],
    task_type: str,
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build the routing dict for SupervisedEngine, honouring preprocessor config.

    Uses `excluded_id_cols`, `dataset_modality`, `language_profile`, and
    `col_types` from the config when available, instead of re-inferring.

    Parameters
    ----------
    df         : Uploaded dataframe.
    target_col : Resolved target column name.
    task_type  : 'classification' or 'regression'.
    cfg        : Parsed config.json dict.
    """
    # Columns to exclude from features
    excluded_id    = list(cfg.get("excluded_id_cols", []) or [])
    excluded_empty = list(cfg.get("excluded_empty_cols", []) or [])
    excluded       = set(excluded_id + excluded_empty)
    if target_col:
        excluded.add(target_col)

    # Honour modality from config; fall back to inferring.
    dataset_modality = str(cfg.get("dataset_modality", "tabular")).lower().strip()
    if dataset_modality not in {"tabular", "text_heavy", "bilingual"}:
        dataset_modality = "tabular"

    # Language profile
    lang_profile = cfg.get("language_profile", {}) or {}
    if not isinstance(lang_profile, dict):
        lang_profile = {}
    lang = (
        lang_profile.get("dominant_language")
        or lang_profile.get("dominant")
        or "english"
    )

    # Feature columns — everything not excluded
    feature_cols = [c for c in df.columns if c not in excluded]

    # Typed column lists
    col_types = cfg.get("col_types", {}) or {}  # optional per-column type hints
    numeric_cols:   List[str] = []
    categorical_cols: List[str] = []
    datetime_cols:  List[str] = []
    text_cols:      List[str] = []

    if col_types:
        for col in feature_cols:
            ctype = str(col_types.get(col, "")).lower()
            if ctype in {"numeric", "float", "int", "integer"}:
                numeric_cols.append(col)
            elif ctype in {"datetime", "date", "time"}:
                datetime_cols.append(col)
            elif ctype in {"text", "free_text", "nlp"}:
                text_cols.append(col)
            elif ctype in {"categorical", "cat", "object", "string"}:
                categorical_cols.append(col)
            # Unknown types are silently omitted — the supervised engine handles them.
    else:
        # No col_types in config — infer from dtypes (same as build_routing_decision)
        feat_df        = df[feature_cols]
        numeric_cols   = feat_df.select_dtypes(include=[np.number]).columns.tolist()
        object_cols    = feat_df.select_dtypes(include=["object", "category"]).columns.tolist()
        datetime_cols  = [c for c in feature_cols if "date" in c.lower() or "time" in c.lower()]
        text_cols      = _text_columns(df, object_cols)
        categorical_cols = [c for c in object_cols if c not in text_cols]

    # For text-heavy modality, pick the primary text column.
    routed_text_cols: List[str] = []
    if dataset_modality in {"text_heavy", "bilingual"} and text_cols:
        routed_text_cols = [text_cols[0]]

    return {
        "task_type":              task_type,
        "target_column":         target_col,
        "text_columns":          routed_text_cols,
        "numeric_columns":       numeric_cols,
        "categorical_columns":   [c for c in categorical_cols if c not in routed_text_cols],
        "datetime_columns":      datetime_cols,
        "identifier_like_columns": excluded_id,
        "dataset_modality":      dataset_modality,
        "language_profile":      {"dominant_language": lang},
    }


# =============================================================================
# Internal inference helpers  (used when no config.json is supplied)
# =============================================================================

def _looks_like_id_column(name: str, series: pd.Series) -> bool:
    lname    = name.lower().strip()
    id_terms = ["id", "uuid", "guid", "ticket", "incident", "request", "serial", "key", "code"]
    if any(t == lname or lname.endswith("_" + t) or lname.startswith(t + "_") for t in id_terms):
        return True
    n      = len(series)
    nuniq  = series.nunique(dropna=True)
    return n >= 20 and nuniq / max(n, 1) > 0.95 and ("id" in lname or "number" in lname or lname == "no")


def _text_columns(df: pd.DataFrame, candidate_cols: List[str]) -> List[str]:
    out: List[str] = []
    for col in candidate_cols:
        s = df[col].dropna().astype(str)
        if s.empty:
            continue
        avg_len      = float(s.str.len().mean())
        unique_ratio = float(s.nunique() / max(len(s), 1))
        if avg_len >= 35 and unique_ratio >= 0.30:
            out.append(col)
    return out


def infer_target_column(df: pd.DataFrame, explicit_target: Optional[str] = None) -> Optional[str]:
    """
    Infer a target column for supervised learning from df column names/content.
    Returns None when no convincing target is found (routes to unsupervised).
    Only called when NO config.json is uploaded.
    """
    if explicit_target and explicit_target in df.columns:
        return explicit_target

    exact_priority = [
        "target", "label", "class", "y", "output", "result", "outcome",
        "severity", "status", "decision", "root_cause", "root cause",
        "category", "prediction_target", "dependent_variable",
    ]
    lower_map = {c.lower().strip().replace(" ", "_"): c for c in df.columns}
    for key in exact_priority:
        norm = key.replace(" ", "_")
        if norm in lower_map:
            return lower_map[norm]

    keyword_priority = [
        "target", "label", "outcome", "result", "class", "severity", "status",
        "score", "rating", "grade", "risk", "price", "cost", "sales",
        "revenue", "profit", "amount", "total", "duration", "resolution_time",
        "sla", "delay", "failure", "root_cause",
    ]
    for kw in keyword_priority:
        for col in df.columns:
            lname = col.lower().replace(" ", "_")
            if kw in lname and not _looks_like_id_column(col, df[col]):
                if df[col].nunique(dropna=True) < len(df) * 0.98:
                    return col
    return None


def infer_task_type(df: pd.DataFrame, target_col: str) -> str:
    """Infer classification vs regression from target column distribution."""
    s           = df[target_col].dropna()
    if s.empty:
        return "classification"
    numeric     = pd.to_numeric(s, errors="coerce")
    num_ratio   = numeric.notna().mean()
    nunique     = s.nunique(dropna=True)
    n           = len(s)
    if num_ratio >= 0.95 and nunique > max(20, int(0.15 * n)):
        return "regression"
    return "classification"


def build_routing_decision(df: pd.DataFrame, target_col: str, task_type: str) -> Dict[str, Any]:
    """
    Build the routing dict for SupervisedEngine using purely internal inference.
    Only called when no config.json is available.
    """
    id_cols      = [c for c in df.columns if c != target_col and _looks_like_id_column(c, df[c])]
    feature_cols = [c for c in df.columns if c != target_col and c not in id_cols]
    feat_df      = df[feature_cols]
    numeric_cols = feat_df.select_dtypes(include=[np.number]).columns.tolist()
    object_cols  = feat_df.select_dtypes(include=["object", "category", "string"]).columns.tolist()
    datetime_cols = [c for c in feature_cols if "date" in c.lower() or "time" in c.lower()]
    text_cols     = _text_columns(df, object_cols)

    dataset_modality  = "tabular"
    routed_text_cols: List[str] = []
    if task_type == "classification" and text_cols:
        longest = max(text_cols, key=lambda c: df[c].dropna().astype(str).str.len().mean())
        avg_len = df[longest].dropna().astype(str).str.len().mean()
        if avg_len >= 50 and len(numeric_cols) <= 5:
            dataset_modality = "text_heavy"
            routed_text_cols = [longest]

    lang = "english"
    if routed_text_cols:
        sample = " ".join(df[routed_text_cols[0]].dropna().astype(str).head(50).tolist())
        if re.search(r"[\u0600-\u06FF]", sample):
            lang = "arabic"

    return {
        "task_type":               task_type,
        "target_column":          target_col,
        "text_columns":           routed_text_cols,
        "numeric_columns":        numeric_cols,
        "categorical_columns":    [c for c in object_cols if c not in routed_text_cols],
        "datetime_columns":       datetime_cols,
        "identifier_like_columns": id_cols,
        "dataset_modality":       dataset_modality,
        "language_profile":       {"dominant_language": lang},
    }


# =============================================================================
# Visualization payload compatibility helpers
# =============================================================================

def normalize_feature_importance(raw: Any) -> List[Dict[str, Any]]:
    """
    Accept any of the three feature-importance formats used in Basira engines
    and return a unified list that both old and new frontend adapters understand.

    Accepted key names: impact_pct | impact | importance
    """
    items = raw if isinstance(raw, list) else []
    out: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        val = item.get("impact_pct", item.get("impact", item.get("importance", 0)))
        try:
            val = float(val)
        except Exception:
            val = 0.0
        if not math.isfinite(val):
            val = 0.0
        out.append({
            **item,
            "feature":    str(item.get("feature", item.get("name", "unknown"))),
            "impact":     val,
            "impact_pct": val,
            "importance": float(item.get("importance", val) or val),
        })
    return out


def build_preview(df: pd.DataFrame, n: int = 20) -> List[Dict[str, Any]]:
    return json_safe(df.head(n).where(pd.notna(df.head(n)), None).to_dict(orient="records"))


def insight_cards_from_result(insight_result: Any) -> List[Dict[str, Any]]:
    """
    Bridge new InsightResult.insights format → old frontend advanced_insights format.
    Also preserves all new fields so the new frontend adapters also work.
    """
    data  = result_to_dict(insight_result)
    cards = []
    for ins in data.get("insights", [])[:8]:
        metric_values = ins.get("metric_values") or {}
        first_metric  = (
            next(iter(metric_values.values()), None)
            if isinstance(metric_values, dict)
            else None
        )
        cards.append({
            # Old format keys
            "id":     ins.get("id", "insight"),
            "title":  ins.get("title", "Insight"),
            "value":  str(first_metric if first_metric is not None
                         else ins.get("severity", "info")).upper(),
            "metric": ins.get("layer", ""),
            "desc":   ins.get("narrative", ins.get("desc", "")),
            "action": ins.get("recommended_action", ins.get("action", "")),
            # New format keys (kept alongside for completeness)
            "severity":          ins.get("severity", "info"),
            "layer":             ins.get("layer", ""),
            "narrative":         ins.get("narrative", ""),
            "evidence":          ins.get("evidence", {}),
            "metric_values":     metric_values,
            "recommended_action": ins.get("recommended_action", ""),
        })
    return cards


def rca_report_legacy(rca_result: Any) -> List[Dict[str, Any]]:
    """
    Bridge new RCAResult.findings format → old rca_report list format.
    Each entry keeps both old and new fields.
    """
    data   = result_to_dict(rca_result)
    legacy = []
    for f in data.get("findings", []):
        chain = f.get("causal_chain") or []
        entry = {
            # Old keys
            "id":             f.get("id", ""),
            "title":          f.get("title", "Finding"),
            "severity":       str(f.get("severity", "info")).upper(),
            "causes":         chain if chain else [f.get("explanation", "")],
            "recommendation": f.get("recommended_action", ""),
        }
        # Merge all new-format fields on top (without losing old keys).
        for k, v in f.items():
            entry.setdefault(k, v)
        legacy.append(entry)
    return legacy


def build_decision_narrative(
    strategy: str,
    model_result: Any,
    insight_result: Any,
    rca_result: Any,
) -> Dict[str, Any]:
    """Build the old-style decision_narrative dict consumed by the frontend."""
    insight_data = result_to_dict(insight_result)
    rca_data     = result_to_dict(rca_result)
    summary      = insight_data.get("narrative_summary", "")

    if strategy == "supervised":
        headline    = f"Best model: {getattr(model_result, 'best_model_name', 'Unknown')}"
        key         = (
            f"Task: {getattr(model_result, 'task_type', 'supervised')} | "
            f"Target: {getattr(model_result, 'target_column', 'target')}"
        )
        reliability = getattr(model_result, "reliability_report", {}) or {}
        risk        = reliability.get("level", "")
        action      = (
            reliability.get("recommended_next_step")
            or (rca_data.get("priority_actions") or [""])[0]
        )
    else:
        headline    = f"Best clustering: {getattr(model_result, 'best_algorithm', 'Unknown')}"
        key         = f"Discovered {getattr(model_result, 'best_n_clusters', 0)} clusters"
        quality     = getattr(model_result, "cluster_quality_report", {}) or {}
        risk        = quality.get("level", "")
        action      = (rca_data.get("priority_actions") or ["Review cluster profiles and anomaly findings."])[0]

    return {
        "headline":           headline,
        "summary":            summary,
        "key_finding":        key,
        "recommended_action": action or "Review Basira insight and RCA cards before operational use.",
        "risk_alert":         f"Quality/Reliability level: {risk}" if risk else "Review generated warnings before deployment.",
    }


def enrich_chart_recommendations(
    strategy: str,
    model_result: Any,
    rca_result: Any,
    insight_result: Any,
) -> List[Dict[str, Any]]:
    """
    Take the chart recommendations already produced by the model engine and
    optionally prepend/append extra charts from charts_engine helpers.
    Deduplicates by chart id, caps at 10 charts.
    """
    recs: List[Dict[str, Any]] = list(getattr(model_result, "chart_recommendations", []) or [])

    if charts_engine is not None:
        try:
            if strategy == "supervised":
                if hasattr(charts_engine, "build_model_leaderboard_chart"):
                    extra = charts_engine.build_model_leaderboard_chart(
                        getattr(model_result, "cv_results", [])
                    )
                    if extra:
                        recs.insert(0, extra)

                if hasattr(charts_engine, "build_confusion_matrix_chart"):
                    cm     = getattr(model_result, "confusion_matrix", None)
                    labels = getattr(model_result, "label_classes", None)
                    if cm and labels:
                        extra = charts_engine.build_confusion_matrix_chart(cm, labels)
                        if extra:
                            recs.append(extra)

                # Actual vs predicted and residuals (regression)
                task_type_from_result = getattr(model_result, "task_type", "")
                rca_ready = getattr(model_result, "rca_ready_payload", {}) or {}
                if task_type_from_result == "regression" and hasattr(charts_engine, "build_actual_vs_predicted_chart"):
                    error_cases = rca_ready.get("error_cases", [])
                    target_lbl  = getattr(model_result, "target_column", "target")
                    if error_cases:
                        extra = charts_engine.build_actual_vs_predicted_chart(error_cases, target_lbl)
                        if extra:
                            recs.append(extra)
                if task_type_from_result == "regression" and hasattr(charts_engine, "build_residuals_chart"):
                    error_cases = rca_ready.get("error_cases", [])
                    if error_cases:
                        extra = charts_engine.build_residuals_chart(error_cases)
                        if extra:
                            recs.append(extra)

                # Class distribution (classification)
                if task_type_from_result == "classification" and hasattr(charts_engine, "build_class_distribution_chart"):
                    target_sum = rca_ready.get("target_summary", {})
                    if target_sum:
                        extra = charts_engine.build_class_distribution_chart(target_sum)
                        if extra:
                            recs.append(extra)

            else:  # unsupervised
                if hasattr(charts_engine, "build_cluster_profile_chart"):
                    extra = charts_engine.build_cluster_profile_chart(
                        getattr(model_result, "cluster_profiles", [])
                    )
                    if extra:
                        recs.insert(0, extra)

                if hasattr(charts_engine, "build_anomaly_chart"):
                    extra = charts_engine.build_anomaly_chart(
                        getattr(model_result, "anomaly_report", {})
                    )
                    if extra:
                        recs.append(extra)

            # Shared extras (both strategies)
            if hasattr(charts_engine, "build_rca_chart"):
                findings = result_to_dict(rca_result).get("findings", [])
                extra    = charts_engine.build_rca_chart(findings)
                if extra:
                    recs.append(extra)

            if hasattr(charts_engine, "build_insight_cards_chart"):
                insights_list = result_to_dict(insight_result).get("insights", [])
                extra         = charts_engine.build_insight_cards_chart(insights_list)
                if extra:
                    recs.append(extra)

        except Exception:
            # Never let optional chart enrichment break the main pipeline.
            pass

    # Deduplicate, fill defaults, make JSON-safe.
    cleaned: List[Dict[str, Any]] = []
    seen: set = set()
    for rec in recs:
        if not isinstance(rec, dict):
            continue
        rec = dict(rec)
        rid = rec.get("id") or rec.get("title") or f"chart_{len(cleaned)}"
        if rid in seen:
            continue
        seen.add(rid)
        rec.setdefault("id",          rid)
        rec.setdefault("type",        "bar")
        rec.setdefault("priority",    "medium")
        rec.setdefault("editable",    True)
        rec.setdefault("chartData",   rec.get("data_source", "impact"))
        rec.setdefault("data_source", rec.get("chartData", "impact"))
        cleaned.append(json_safe(rec))

    return cleaned[:10]


def build_unified_payload(
    strategy: str,
    model_result: Any,
    rca_result: Any,
    insight_result: Any,
    df: pd.DataFrame,
    uploaded_path: Path,
    predictions_or_assignments: Optional[Dict[str, Any]] = None,
    preprocessor_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Assemble the final unified JSON payload for the visualization layer.

    Includes both new pipeline fields and old frontend-compatibility fields so
    either version of basira_analysis_engine.html can render the response.
    """
    model_dict   = result_to_dict(model_result)
    rca_dict     = result_to_dict(rca_result)
    insight_dict = result_to_dict(insight_result)

    dashboard          = dict(getattr(model_result, "dashboard_payload", {}) or {})
    feature_importance = normalize_feature_importance(
        getattr(model_result, "feature_importance", [])
    )
    chart_data         = getattr(model_result, "chart_data", {}) or {}
    chart_recs         = enrich_chart_recommendations(strategy, model_result, rca_result, insight_result)

    # Ensure the dashboard_payload is rich enough for the new frontend adapters.
    dashboard.setdefault("feature_importance",     feature_importance)
    dashboard.setdefault("chart_data",             chart_data)
    dashboard.setdefault("chart_recommendations",  chart_recs)
    dashboard.setdefault("insights",               insight_dict.get("insights", []))
    dashboard.setdefault("narrative",              insight_dict.get("narrative_summary", ""))
    dashboard.setdefault("reliability",            getattr(model_result, "reliability_report", {}))
    dashboard.setdefault("best_model",             getattr(model_result, "best_model_name", None))
    dashboard.setdefault("best_algorithm",         getattr(model_result, "best_algorithm", None))

    pred_rows   = []
    assign_rows = []
    if predictions_or_assignments:
        pred_rows   = list(predictions_or_assignments.get("predictions", []) or [])
        assign_rows = list(predictions_or_assignments.get("assignments", []) or [])

    # Config provenance metadata
    cfg_used        = preprocessor_config is not None
    cfg_task_type   = str(preprocessor_config.get("task_type", ""))  if cfg_used else None
    cfg_target_col  = (
        preprocessor_config.get("target_column") or preprocessor_config.get("target_col")
    ) if cfg_used else None

    payload: Dict[str, Any] = {
        "status":        "success",
        "bridge_version": BRIDGE_VERSION,
        "strategy":      strategy,
        "task_type":     getattr(model_result, "task_type", None) if strategy == "supervised" else "unsupervised",
        "target_column": getattr(model_result, "target_column", None) if strategy == "supervised" else None,
        "uploaded_file": str(uploaded_path.name),
        "n_rows":        int(len(df)),
        "n_columns":     int(len(df.columns)),

        # Config provenance (required by specification)
        "preprocessor_config_used": cfg_used,
        "config_task_type":         cfg_task_type,
        "config_target_column":     cfg_target_col,

        # ── New final pipeline fields ──────────────────────────────────────
        "dashboard_payload":   dashboard,
        "rca_result":          rca_dict,
        "insight_result":      insight_dict,
        "chart_data":          chart_data,
        "chart_recommendations": chart_recs,
        "feature_importance":  feature_importance,
        "model_result":        model_dict,

        # ── Old visualization compatibility fields ─────────────────────────
        "xai_report":          feature_importance,
        "advanced_insights":   insight_cards_from_result(insight_result),
        "decision_narrative":  build_decision_narrative(strategy, model_result, insight_result, rca_result),
        "rca_report":          rca_report_legacy(rca_result),
        "preview":             build_preview(df),
        "data_preview":        build_preview(df),
        "predictions":         pred_rows,
        "assigned_clusters":   assign_rows,
        "cluster_assignments": assign_rows,

        # ── Helpful metadata ───────────────────────────────────────────────
        "model_performance": {
            "best_model":     getattr(model_result, "best_model_name",      None),
            "best_algorithm": getattr(model_result, "best_algorithm",       None),
            "metrics":        getattr(model_result, "test_metrics",          None),
            "reliability":    getattr(model_result, "reliability_report",    None),
            "quality":        getattr(model_result, "cluster_quality_report", None),
        },
        "warnings": (
            list(getattr(model_result,   "warnings", []) or [])
            + list(getattr(rca_result,   "warnings", []) or [])
            + list(getattr(insight_result, "warnings", []) or [])
        ),
    }
    return json_safe(payload)


# =============================================================================
# Main pipeline coordinator
# =============================================================================

def run_basira_pipeline(
    df: pd.DataFrame,
    uploaded_path: Path,
    explicit_target: Optional[str]    = None,
    explicit_task_type: Optional[str] = None,
    force_strategy: Optional[str]     = None,
    preprocessor_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Run the full Basira analytical pipeline and return a unified visualization payload.

    Priority order for strategy / target resolution
    ------------------------------------------------
    1. force_strategy == 'unsupervised'   → unsupervised, no target.
    2. explicit_target + explicit_task_type in request form → use them.
    3. preprocessor_config (config.json)  → use its task_type & target_column.
    4. Internal inference                 → infer from df column names/content.

    Parameters
    ----------
    df                  : Cleaned / model-ready dataframe from the upload.
    uploaded_path       : Path where the uploaded file was saved.
    explicit_target     : target_column from the HTTP form/query string.
    explicit_task_type  : task_type from the HTTP form/query string.
    force_strategy      : 'supervised' | 'unsupervised' override.
    preprocessor_config : Parsed config.json from the Basira preprocessor.
    """
    run_id = datetime.now().strftime("basira_%Y%m%d_%H%M%S")

    # ──────────────────────────────────────────────────────────────────────
    # Step 1: Determine strategy (force_strategy wins unconditionally)
    # ──────────────────────────────────────────────────────────────────────
    if force_strategy == "unsupervised":
        return _run_unsupervised_pipeline(
            df, uploaded_path, run_id,
            preprocessor_config=preprocessor_config,
        )

    # ──────────────────────────────────────────────────────────────────────
    # Step 2: Explicit request parameters take priority over config
    # ──────────────────────────────────────────────────────────────────────
    resolved_target    = None
    resolved_task_type = None

    if explicit_target and explicit_target in df.columns:
        resolved_target    = explicit_target
        resolved_task_type = (
            explicit_task_type
            if explicit_task_type in {"classification", "regression"}
            else infer_task_type(df, resolved_target)
        )

    # ──────────────────────────────────────────────────────────────────────
    # Step 3: Config.json (preprocessor output)
    # ──────────────────────────────────────────────────────────────────────
    if resolved_target is None and preprocessor_config is not None:
        cfg_task, cfg_target = resolve_task_from_config(df, preprocessor_config)
        # resolve_task_from_config raises ValueError if target_col is missing from df.

        if cfg_task == "unsupervised":
            return _run_unsupervised_pipeline(
                df, uploaded_path, run_id,
                preprocessor_config=preprocessor_config,
            )

        resolved_task_type = cfg_task or None
        resolved_target    = cfg_target  # may still be None if config had no target

        # If config had a supervised task_type but no target, infer the target.
        if resolved_target is None and resolved_task_type in {"classification", "regression"}:
            resolved_target = infer_target_column(df)
            if resolved_target is None:
                # Cannot find a target despite supervised task_type in config.
                # Fall back to unsupervised rather than crashing.
                return _run_unsupervised_pipeline(
                    df, uploaded_path, run_id,
                    preprocessor_config=preprocessor_config,
                )

    # ──────────────────────────────────────────────────────────────────────
    # Step 4: Pure inference (no config, no explicit params)
    # ──────────────────────────────────────────────────────────────────────
    if resolved_target is None:
        resolved_target = infer_target_column(df, explicit_target)

    if resolved_target is None:
        # No target found at all → unsupervised.
        return _run_unsupervised_pipeline(
            df, uploaded_path, run_id,
            preprocessor_config=preprocessor_config,
        )

    if resolved_task_type not in {"classification", "regression"}:
        resolved_task_type = infer_task_type(df, resolved_target)

    return _run_supervised_pipeline(
        df, uploaded_path, run_id,
        target_col=resolved_target,
        task_type=resolved_task_type,
        preprocessor_config=preprocessor_config,
    )


# =============================================================================
# Private pipeline runners
# =============================================================================

def _run_supervised_pipeline(
    df: pd.DataFrame,
    uploaded_path: Path,
    run_id: str,
    target_col: str,
    task_type: str,
    preprocessor_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute supervised engine → RCA → Insight and return unified payload."""

    # Build routing — use config fields when available, otherwise infer.
    if preprocessor_config is not None:
        routing = build_routing_decision_from_config(df, target_col, task_type, preprocessor_config)
    else:
        routing = build_routing_decision(df, target_col, task_type)

    # ── Model ──
    supervised = SupervisedEngine(routing, output_name=f"{run_id}_supervised").run(df)

    # ── RCA ──
    # Prefer rca_ready_payload (richer) over dashboard_payload.
    rca_payload = (
        getattr(supervised, "rca_ready_payload", None)
        or getattr(supervised, "dashboard_payload", {})
        or {}
    )
    rca = RCAEngine(output_name=f"{run_id}_rca").run_from_supervised(
        rca_payload,
        raw_df=df,
    )

    # ── Insights ──
    insights = InsightEngine(output_name=f"{run_id}_insights").run_from_supervised_result(
        supervised,
        raw_df=df,
    )

    # ── Predictions on the uploaded data (best-effort; non-fatal) ──
    prediction_payload: Dict[str, Any] = {"predictions": [], "warnings": []}
    try:
        # Call .predict() on the SAME supervised instance — do not create a second engine.
        result = supervised.predict(
            df.drop(columns=[target_col], errors="ignore"),
            model_dir=supervised.saved_model_dir,
        )
        # predict() returns {"status", "task_type", "n_rows", "predictions", "warnings"}
        prediction_payload = {
            "predictions": result.get("predictions", []),
            "warnings":    result.get("warnings", []),
        }
    except Exception as exc:
        prediction_payload["warnings"].append(f"Prediction table generation failed: {exc}")

    return build_unified_payload(
        strategy               = "supervised",
        model_result           = supervised,
        rca_result             = rca,
        insight_result         = insights,
        df                     = df,
        uploaded_path          = uploaded_path,
        predictions_or_assignments = prediction_payload,
        preprocessor_config    = preprocessor_config,
    )


def _run_unsupervised_pipeline(
    df: pd.DataFrame,
    uploaded_path: Path,
    run_id: str,
    preprocessor_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute unsupervised engine → RCA → Insight and return unified payload."""

    # ── Model ──
    unsupervised = UnsupervisedEngine(output_name=f"{run_id}_unsupervised").run(df)

    # ── RCA ──
    # Prefer rca_ready_payload for richer cluster/anomaly context.
    rca_payload = (
        getattr(unsupervised, "rca_ready_payload", None)
        or getattr(unsupervised, "dashboard_payload", {})
        or {}
    )
    rca = RCAEngine(output_name=f"{run_id}_rca").run_from_unsupervised(
        rca_payload,
        raw_df=df,
    )

    # ── Insights ──
    insights = InsightEngine(output_name=f"{run_id}_insights").run_from_unsupervised_result(
        unsupervised,
        raw_df=df,
    )

    # ── Cluster assignment (best-effort; non-fatal) ──
    # Call .assign_clusters() on the SAME unsupervised instance.
    assignment_payload: Dict[str, Any] = {"assignments": [], "warnings": []}
    if getattr(unsupervised, "assignment_ready", False):
        try:
            result = unsupervised.assign_clusters(
                df,
                model_dir=unsupervised.saved_model_dir,
            )
            # assign_clusters() returns {"status", "strategy", "n_rows", "assignments", "warnings"}
            assignment_payload = {
                "assignments": result.get("assignments", []),
                "warnings":    result.get("warnings", []),
            }
        except Exception as exc:
            assignment_payload["warnings"].append(f"Cluster assignment generation failed: {exc}")
    else:
        assignment_payload["warnings"].append(
            "Selected clustering model does not support predict/assignment for new data."
        )

    return build_unified_payload(
        strategy               = "unsupervised",
        model_result           = unsupervised,
        rca_result             = rca,
        insight_result         = insights,
        df                     = df,
        uploaded_path          = uploaded_path,
        predictions_or_assignments = assignment_payload,
        preprocessor_config    = preprocessor_config,
    )


# =============================================================================
# Flask endpoints
# =============================================================================

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status":   "ok",
        "service":  "Basira Bridge Orchestrator",
        "version":  BRIDGE_VERSION,
        "pipeline": [
            "supervised_engine_F",
            "unsupervised_engine_F",
            "rca_engine_F",
            "insight_engine_F",
            "visualization_payload",
        ],
    })


@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        # ── Require a data file ──────────────────────────────────────────
        if "file" not in request.files:
            return jsonify({
                "status":  "error",
                "message": "No file was uploaded under field name 'file'.",
            }), 400

        df, saved_path = load_uploaded_dataframe(request.files["file"])

        # ── Optional preprocessor config ────────────────────────────────
        # Sent by the preprocessor UI as a second multipart field "config".
        config_storage = request.files.get("config")
        preprocessor_config = load_optional_config(config_storage)

        # ── Request-level overrides (form fields / query params) ─────────
        explicit_target    = (request.form.get("target_column")
                              or request.args.get("target_column")
                              or None)
        explicit_task_type = (request.form.get("task_type")
                              or request.args.get("task_type")
                              or None)
        force_strategy     = (request.form.get("strategy")
                              or request.args.get("strategy")
                              or None)

        payload = run_basira_pipeline(
            df                  = df,
            uploaded_path       = saved_path,
            explicit_target     = explicit_target,
            explicit_task_type  = explicit_task_type,
            force_strategy      = force_strategy,
            preprocessor_config = preprocessor_config,
        )
        return jsonify(payload)

    except ValueError as exc:
        # Covers the Scenario 5 error (config target missing from df) and
        # any other user-input validation errors.
        return jsonify({
            "status":  "error",
            "message": str(exc),
        }), 422

    except (BasiraEngineError, BasiraUnsupervisedError, BasiraRCAError, BasiraInsightError) as exc:
        report = getattr(exc, "report", None)
        return jsonify({
            "status":        "error",
            "message":       str(exc),
            "engine_report": (
                json_safe(report.to_dict())
                if report is not None and hasattr(report, "to_dict")
                else None
            ),
        }), 422

    except Exception as exc:
        traceback.print_exc()
        return jsonify({
            "status":    "error",
            "message":   str(exc),
            "traceback": traceback.format_exc().splitlines()[-8:],
        }), 500


# =============================================================================
# Entry point
# =============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 72)
    print("🚀 BASIRA BRIDGE ORCHESTRATOR")
    print("   Final pipeline coordinator: Model → RCA → Insight → Visualization")
    print("=" * 72)
    print(f"\n  Health  : http://127.0.0.1:5001/health")
    print(f"  Analyze : http://127.0.0.1:5001/analyze")
    print("\n  Press Ctrl+C to stop.\n")
    app.run(host="0.0.0.0", port=5001, debug=False)
