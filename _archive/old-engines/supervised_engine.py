from __future__ import annotations

import json
import re
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import joblib
import numpy as np
import pandas as pd

from sklearn.base import clone
from sklearn.ensemble import (
    GradientBoostingClassifier,
    GradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, Ridge
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


RANDOM_STATE       = 42
TEST_SIZE          = 0.20
N_SPLITS_CV        = 3

TFIDF_MAX_FEATURES = 5_000
TFIDF_NGRAM_RANGE  = (1, 2)
TFIDF_MIN_DF_UNIQUE  = 1
TFIDF_MIN_DF_GROUPED = 2
TFIDF_MAX_DF       = 0.95
TFIDF_SUBLINEAR_TF = True

MIN_UNIQUE_GROUP_SUPPORT = 3
MIN_ROWS_PER_CLASS       = 3
MIN_TOTAL_SAMPLES        = 10
MIN_CLASSES              = 2
MIN_MEAN_TEXT_TOKENS     = 2

_DIACRITICS     = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E4\u06E7\u06E8\u06EA-\u06ED]")
_TATWEEL        = re.compile(r"\u0640")
_HAMZA_VARIANTS = re.compile(r"[أإآ]")
_WHITESPACE     = re.compile(r"\s+")

MODEL_OUTPUT_BASE = Path("saved_models")


@dataclass
class FailureReport:
    status:      str
    reason:      str
    details:     Dict[str, Any]
    suggestions: List[str]

    def to_dict(self) -> Dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


@dataclass
class SupervisedResult:
    modality:              str
    task_type:             str
    target_column:         str
    split_strategy:        str
    best_model_name:       str
    cv_results:            List[Dict]
    test_metrics:          Dict[str, float]
    classification_report: Optional[Dict]
    confusion_matrix:      Optional[List]
    preparation_summary:   Dict
    saved_model_dir:       str
    label_classes:         Optional[List[str]]


class BasiraEngineError(RuntimeError):
    def __init__(self, report: FailureReport) -> None:
        self.report = report
        super().__init__(report.reason)


def _failure(
    reason: str,
    details: Dict[str, Any],
    suggestions: List[str],
) -> FailureReport:
    return FailureReport(
        status="failed",
        reason=reason,
        details=details,
        suggestions=suggestions,
    )


def _raise(report: FailureReport) -> None:
    raise BasiraEngineError(report)


def _normalize_arabic(text: object) -> str:
    s = str(text).strip()
    s = _DIACRITICS.sub("", s)
    s = _TATWEEL.sub("", s)
    s = _HAMZA_VARIANTS.sub("ا", s)
    s = _WHITESPACE.sub(" ", s)
    return s


def _normalize_english(text: object) -> str:
    s = str(text).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _normalize_text(text: object, language: str) -> str:
    if language == "arabic":
        return _normalize_arabic(text)
    return _normalize_english(text)


_ENCODINGS = ["utf-8-sig", "cp1256", "utf-8", "latin1"]


def _looks_broken_arabic(text: str) -> bool:
    broken = ["Ù", "Ø", "Ã", "\ufffd", "\\x"]
    if any(m in text for m in broken):
        return True
    arabic_chars = sum(1 for ch in text if "\u0600" <= ch <= "\u06FF")
    return arabic_chars == 0


def load_file(path: Path) -> pd.DataFrame:
    if not path.exists():
        _raise(_failure(
            reason=f"Dataset file not found: '{path.name}'",
            details={"path": str(path)},
            suggestions=[
                "Verify the file path is correct",
                "Ensure the file exists and is accessible",
            ],
        ))

    suffix = path.suffix.lower()

    if suffix in (".xlsx", ".xls", ".xlsm"):
        try:
            return pd.read_excel(path, engine="openpyxl" if suffix == ".xlsx" else None)
        except Exception as exc:
            msg = str(exc)
            if any(k in msg.lower() for k in ("image", "picture", "drawing", "unsupported")):
                _raise(_failure(
                    reason=f"The Excel file '{path.name}' contains embedded images or unsupported content",
                    details={"file": path.name, "original_error": str(exc)},
                    suggestions=[
                        "Remove embedded images or drawings from the Excel file",
                        "Save a clean copy without media content and retry",
                    ],
                ))
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
                    first_valid = df[col].dropna()
                    if not first_valid.empty:
                        sample = str(first_valid.iloc[0])
                        break
                if not _looks_broken_arabic(sample):
                    return df
                last_error = ValueError(f"Encoding '{enc}' produced garbled text.")
            except Exception as exc:
                last_error = exc
        _raise(_failure(
            reason=f"Could not decode CSV file '{path.name}' with any supported encoding",
            details={"file": path.name, "tried_encodings": _ENCODINGS, "last_error": str(last_error)},
            suggestions=[
                "Re-save the file in UTF-8 encoding",
                "If the file contains Arabic text, save as UTF-8-BOM or CP1256",
            ],
        ))

    _raise(_failure(
        reason=f"Unsupported file extension: '{suffix}'",
        details={"extension": suffix},
        suggestions=["Provide a file with extension .xlsx, .xls, or .csv"],
    ))


def _classification_metrics(y_true, y_pred) -> Dict[str, float]:
    return {
        "accuracy":           round(float(accuracy_score(y_true, y_pred)), 4),
        "balanced_accuracy":  round(float(balanced_accuracy_score(y_true, y_pred)), 4),
        "precision_weighted": round(float(precision_score(y_true, y_pred, average="weighted", zero_division=0)), 4),
        "recall_weighted":    round(float(recall_score(y_true, y_pred, average="weighted", zero_division=0)), 4),
        "f1_weighted":        round(float(f1_score(y_true, y_pred, average="weighted", zero_division=0)), 4),
        "f1_macro":           round(float(f1_score(y_true, y_pred, average="macro", zero_division=0)), 4),
    }


def _regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    rmse    = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    mae     = float(mean_absolute_error(y_true, y_pred))
    r2      = float(r2_score(y_true, y_pred))
    nonzero = np.where(y_true == 0, 1, y_true)
    mape    = float(np.mean(np.abs((y_true - y_pred) / nonzero)) * 100)
    return {
        "RMSE":     round(rmse, 4),
        "MAE":      round(mae, 4),
        "R2":       round(r2, 4),
        "MAPE_pct": round(mape, 4),
    }


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
    candidates = {
        "LogisticRegression": LogisticRegression(
            max_iter=3000, class_weight="balanced", random_state=RANDOM_STATE
        ),
        "LinearSVC": LinearSVC(
            class_weight="balanced", random_state=RANDOM_STATE
        ),
        "MultinomialNB": MultinomialNB(),
    }
    return {
        name: Pipeline([("tfidf", clone(vectorizer)), ("model", clone(clf))])
        for name, clf in candidates.items()
    }


def _tabular_classification_pipelines() -> Dict[str, Any]:
    return {
        "RandomForest": RandomForestClassifier(
            n_estimators=200, max_depth=12, min_samples_leaf=3,
            class_weight="balanced", random_state=RANDOM_STATE, n_jobs=-1,
        ),
        "GradientBoosting": GradientBoostingClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.05,
            subsample=0.8, random_state=RANDOM_STATE,
        ),
        "LogisticRegression": Pipeline([
            ("scaler", StandardScaler()),
            ("model",  LogisticRegression(
                max_iter=2000, class_weight="balanced", random_state=RANDOM_STATE
            )),
        ]),
    }


def _tabular_regression_pipelines() -> Dict[str, Any]:
    from sklearn.linear_model import LinearRegression
    return {
        "RandomForest": RandomForestRegressor(
            n_estimators=200, max_depth=10, min_samples_leaf=4,
            random_state=RANDOM_STATE, n_jobs=-1,
        ),
        "GradientBoosting": GradientBoostingRegressor(
            n_estimators=200, max_depth=5, learning_rate=0.05,
            subsample=0.8, random_state=RANDOM_STATE,
        ),
        "Ridge": Pipeline([
            ("scaler", StandardScaler()),
            ("model",  Ridge(alpha=1.0)),
        ]),
        "LinearRegression": Pipeline([
            ("scaler", StandardScaler()),
            ("model",  LinearRegression()),
        ]),
    }


def _validate_dataset_size(df: pd.DataFrame, target_col: str) -> None:
    n = len(df)
    if n < MIN_TOTAL_SAMPLES:
        _raise(_failure(
            reason="Dataset is too small for reliable model training",
            details={"n_samples": n, "min_required": MIN_TOTAL_SAMPLES},
            suggestions=[
                f"Provide at least {MIN_TOTAL_SAMPLES} samples",
                "Collect more data before training",
            ],
        ))


def _validate_target_column(df: pd.DataFrame, target_col: str, task_type: str) -> None:
    if target_col not in df.columns:
        _raise(_failure(
            reason=f"Target column '{target_col}' was not found in the dataset",
            details={"target_column": target_col, "available_columns": df.columns.tolist()},
            suggestions=[
                "Check that the target column name is spelled correctly",
                "Review the routing configuration",
            ],
        ))

    n_missing = df[target_col].isna().sum()
    missing_pct = round(n_missing / len(df) * 100, 1)
    if missing_pct > 50:
        _raise(_failure(
            reason=f"Target column '{target_col}' has too many missing values to train reliably",
            details={"missing_count": int(n_missing), "missing_pct": missing_pct, "total_rows": len(df)},
            suggestions=[
                "Fill or remove rows with missing target values",
                "Verify the correct column is designated as the target",
            ],
        ))

    if task_type == "classification":
        n_classes = df[target_col].dropna().nunique()
        if n_classes < MIN_CLASSES:
            _raise(_failure(
                reason="Target column has insufficient class diversity for classification",
                details={"n_unique_classes": int(n_classes), "min_required": MIN_CLASSES},
                suggestions=[
                    "Ensure the target column contains at least 2 distinct classes",
                    "If this is a regression problem, update the task_type to 'regression'",
                ],
            ))


def _validate_class_balance(working: pd.DataFrame, target_col: str) -> None:
    class_counts = working[target_col].value_counts()
    n_classes    = len(class_counts)
    rare_classes = class_counts[class_counts < MIN_ROWS_PER_CLASS]

    if len(rare_classes) == n_classes:
        _raise(_failure(
            reason="All classes have fewer samples than the minimum required for training",
            details={
                "n_classes":             int(n_classes),
                "min_required_per_class": MIN_ROWS_PER_CLASS,
                "class_distribution":    class_counts.to_dict(),
            },
            suggestions=[
                "Provide more labelled data per class",
                "Merge underrepresented classes into broader categories",
                f"Ensure each class has at least {MIN_ROWS_PER_CLASS} samples",
            ],
        ))


def _validate_text_quality(series: pd.Series, text_col: str) -> None:
    non_empty = series.dropna().astype(str).str.strip()
    non_empty = non_empty[non_empty != ""]

    if len(non_empty) == 0:
        _raise(_failure(
            reason=f"Text column '{text_col}' is empty or contains only blank values",
            details={"text_column": text_col, "non_empty_count": 0},
            suggestions=[
                "Verify that the text column contains meaningful content",
                "Check for encoding issues that may have blanked out the text",
            ],
        ))

    mean_tokens = non_empty.str.split().apply(len).mean()
    if mean_tokens < MIN_MEAN_TEXT_TOKENS:
        _raise(_failure(
            reason=f"Text column '{text_col}' contains very short or meaningless content",
            details={
                "text_column":        text_col,
                "mean_token_count":   round(float(mean_tokens), 2),
                "min_required_tokens": MIN_MEAN_TEXT_TOKENS,
            },
            suggestions=[
                "Use a column with richer textual content",
                "Check for encoding corruption that may have shortened text values",
                "Merge multiple short text columns if applicable",
            ],
        ))


def _validate_feature_columns(df: pd.DataFrame, feat_cols: List[str]) -> None:
    if not feat_cols:
        _raise(_failure(
            reason="No feature columns could be identified after excluding target and identifier columns",
            details={"available_columns": df.columns.tolist()},
            suggestions=[
                "Verify the routing configuration includes valid feature columns",
                "Ensure the dataset contains at least one non-target column with useful data",
            ],
        ))

    missing_rate = df[feat_cols].isna().mean()
    fully_empty  = missing_rate[missing_rate == 1.0].index.tolist()
    if fully_empty:
        _raise(_failure(
            reason="One or more feature columns are entirely empty",
            details={"empty_columns": fully_empty},
            suggestions=[
                "Remove or replace the empty feature columns",
                "Check that the correct sheet or file section was loaded",
            ],
        ))


class SupervisedEngine:
    def __init__(
        self,
        routing_decision: Dict[str, Any],
        output_name: str = "run",
    ) -> None:
        self.routing    = routing_decision
        self.output_dir = MODEL_OUTPUT_BASE / output_name

        self._task_type = routing_decision["task_type"]
        self._target    = routing_decision["target_column"]
        self._text_cols = routing_decision.get("text_columns", [])
        self._num_cols  = routing_decision.get("numeric_columns", [])
        self._cat_cols  = routing_decision.get("categorical_columns", [])
        self._dt_cols   = routing_decision.get("datetime_columns", [])
        self._id_cols   = routing_decision.get("identifier_like_columns", [])
        self._modality  = routing_decision.get("dataset_modality", "tabular")
        self._lang      = routing_decision.get("language_profile", {}).get("dominant_language", "english")

        if self._target is None:
            _raise(_failure(
                reason="No target column was specified in the routing decision",
                details={"routing_keys": list(routing_decision.keys())},
                suggestions=[
                    "Specify a target_column in the routing configuration",
                    "If the dataset is unlabelled, use the Unsupervised Engine instead",
                ],
            ))

    def run(self, df: pd.DataFrame) -> SupervisedResult:
        _validate_dataset_size(df, self._target)
        _validate_target_column(df, self._target, self._task_type)

        is_text = self._modality in ("text_heavy", "bilingual") and len(self._text_cols) > 0

        if is_text:
            return self._run_text_pipeline(df)
        return self._run_tabular_pipeline(df)

    def _run_text_pipeline(self, df: pd.DataFrame) -> SupervisedResult:
        text_col   = self._text_cols[0]
        target_col = self._target

        _validate_text_quality(df[text_col], text_col)

        working, prep_summary = self._prepare_text(df, text_col, target_col)

        _validate_class_balance(working, target_col)

        X      = working[text_col]
        y_raw  = working[target_col]
        groups = working[text_col]

        label_enc = LabelEncoder()
        y_encoded = label_enc.fit_transform(y_raw)

        unique_ratio = working[text_col].nunique() / max(len(working), 1)
        use_groups   = unique_ratio < 0.90

        if use_groups:
            split_name          = "GroupShuffleSplit"
            splitter            = GroupShuffleSplit(n_splits=1, test_size=TEST_SIZE, random_state=RANDOM_STATE)
            train_idx, test_idx = next(splitter.split(X, y_encoded, groups=groups))
            X_train             = X.iloc[train_idx].reset_index(drop=True)
            X_test              = X.iloc[test_idx].reset_index(drop=True)
            y_train             = y_encoded[train_idx]
            y_test              = y_encoded[test_idx]
            g_train             = groups.iloc[train_idx].reset_index(drop=True)
            cv_strategy         = StratifiedGroupKFold(n_splits=N_SPLITS_CV, shuffle=True, random_state=RANDOM_STATE)
            cv_kwargs           = {"groups": g_train}
            min_df              = TFIDF_MIN_DF_GROUPED
        else:
            split_name          = "StratifiedShuffleSplit"
            sss                 = StratifiedShuffleSplit(n_splits=1, test_size=TEST_SIZE, random_state=RANDOM_STATE)
            train_idx, test_idx = next(sss.split(X, y_encoded))
            X_train             = X.iloc[train_idx].reset_index(drop=True)
            X_test              = X.iloc[test_idx].reset_index(drop=True)
            y_train             = y_encoded[train_idx]
            y_test              = y_encoded[test_idx]
            cv_strategy         = StratifiedKFold(n_splits=N_SPLITS_CV, shuffle=True, random_state=RANDOM_STATE)
            cv_kwargs           = {}
            min_df              = TFIDF_MIN_DF_UNIQUE

        pipelines  = _text_pipelines(self._lang, min_df)
        cv_results = self._cross_validate_classification(pipelines, X_train, y_train, cv_strategy, cv_kwargs)
        best_name  = cv_results[0]["model_name"]

        best_pipeline = pipelines[best_name]
        try:
            best_pipeline.fit(X_train, y_train)
        except Exception as exc:
            _raise(_failure(
                reason=f"Model '{best_name}' failed to train on the prepared data",
                details={"model": best_name, "error": str(exc), "train_size": len(X_train)},
                suggestions=[
                    "Check for non-numeric or unexpected characters in the text column",
                    "Try reducing the number of TF-IDF features",
                    "Verify the text column contains meaningful content",
                ],
            ))

        y_pred     = best_pipeline.predict(X_test)
        metrics    = _classification_metrics(y_test, y_pred)
        clf_report = classification_report(
            y_test, y_pred,
            target_names=label_enc.classes_.tolist(),
            zero_division=0,
            output_dict=True,
        )
        conf_mat = confusion_matrix(y_test, y_pred).tolist()

        self._save_classification(
            pipeline=best_pipeline,
            label_enc=label_enc,
            prep_summary=prep_summary,
            cv_results=cv_results,
            best_name=best_name,
            test_metrics=metrics,
            clf_report=clf_report,
            conf_mat=conf_mat,
            extra_meta={
                "modality":               self._modality,
                "language":               self._lang,
                "text_column":            text_col,
                "split_strategy":         split_name,
                "group_leakage_control":  use_groups,
                "min_df":                 min_df,
            },
        )

        return SupervisedResult(
            modality=self._modality,
            task_type="classification",
            target_column=target_col,
            split_strategy=split_name,
            best_model_name=best_name,
            cv_results=cv_results,
            test_metrics=metrics,
            classification_report=clf_report,
            confusion_matrix=conf_mat,
            preparation_summary=prep_summary,
            saved_model_dir=str(self.output_dir),
            label_classes=label_enc.classes_.tolist(),
        )

    def _run_tabular_pipeline(self, df: pd.DataFrame) -> SupervisedResult:
        target_col = self._target

        exclude   = set(self._id_cols) | {target_col} | set(self._dt_cols)
        feat_cols = [c for c in df.columns if c not in exclude]

        _validate_feature_columns(df, feat_cols)

        working, prep_summary = self._prepare_tabular(df, feat_cols, target_col)

        if self._task_type == "classification":
            _validate_class_balance(working, target_col)

        X     = working[feat_cols]
        y_raw = working[target_col]

        label_enc: Optional[LabelEncoder] = None
        if self._task_type == "classification":
            label_enc = LabelEncoder()
            y         = label_enc.fit_transform(y_raw.astype(str))
        else:
            y = y_raw.values.astype(float)

        if self._dt_cols:
            dt_col         = self._dt_cols[0]
            working_sorted = working.sort_values(dt_col).reset_index(drop=True)
            X              = working_sorted[feat_cols]
            y_raw_sorted   = working_sorted[target_col]
            y              = label_enc.transform(y_raw_sorted.astype(str)) if label_enc else y_raw_sorted.values.astype(float)
            split_idx      = int(len(X) * (1 - TEST_SIZE))
            X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
            y_train, y_test = y[:split_idx], y[split_idx:]
            split_name     = "ChronologicalSplit"
            cv_strategy    = StratifiedKFold(n_splits=N_SPLITS_CV, shuffle=True, random_state=RANDOM_STATE) if self._task_type == "classification" else KFold(n_splits=N_SPLITS_CV, shuffle=True, random_state=RANDOM_STATE)
            cv_kwargs      = {}

        elif self._task_type == "classification":
            sss                 = StratifiedShuffleSplit(n_splits=1, test_size=TEST_SIZE, random_state=RANDOM_STATE)
            train_idx, test_idx = next(sss.split(X, y))
            X_train, X_test     = X.iloc[train_idx], X.iloc[test_idx]
            y_train, y_test     = y[train_idx], y[test_idx]
            split_name          = "StratifiedShuffleSplit"
            cv_strategy         = StratifiedKFold(n_splits=N_SPLITS_CV, shuffle=True, random_state=RANDOM_STATE)
            cv_kwargs           = {}

        else:
            ss                  = ShuffleSplit(n_splits=1, test_size=TEST_SIZE, random_state=RANDOM_STATE)
            train_idx, test_idx = next(ss.split(X, y))
            X_train, X_test     = X.iloc[train_idx], X.iloc[test_idx]
            y_train, y_test     = y[train_idx], y[test_idx]
            split_name          = "ShuffleSplit"
            cv_strategy         = KFold(n_splits=N_SPLITS_CV, shuffle=True, random_state=RANDOM_STATE)
            cv_kwargs           = {}

        if self._task_type == "classification":
            models     = _tabular_classification_pipelines()
            cv_results = self._cross_validate_classification(models, X_train, y_train, cv_strategy, cv_kwargs)
            best_name  = cv_results[0]["model_name"]
        else:
            models, cv_results = self._cross_validate_regression(
                _tabular_regression_pipelines(), X_train, y_train, cv_strategy, cv_kwargs
            )
            best_name = cv_results[0]["model_name"]

        best_model = models[best_name]
        try:
            best_model.fit(X_train, y_train)
        except Exception as exc:
            _raise(_failure(
                reason=f"Model '{best_name}' failed to converge or fit on the training data",
                details={"model": best_name, "error": str(exc), "train_size": len(X_train), "n_features": len(feat_cols)},
                suggestions=[
                    "Check for non-numeric values in numeric feature columns",
                    "Remove or impute remaining missing values",
                    "Verify feature column types are compatible with the selected model",
                ],
            ))

        y_pred = best_model.predict(X_test)

        if self._task_type == "classification":
            metrics    = _classification_metrics(y_test, y_pred)
            clf_report = classification_report(
                y_test, y_pred,
                target_names=label_enc.classes_.tolist(),
                zero_division=0,
                output_dict=True,
            )
            conf_mat = confusion_matrix(y_test, y_pred).tolist()
            fi       = self._extract_feature_importance(best_model, feat_cols)

            self._save_classification(
                pipeline=best_model,
                label_enc=label_enc,
                prep_summary=prep_summary,
                cv_results=cv_results,
                best_name=best_name,
                test_metrics=metrics,
                clf_report=clf_report,
                conf_mat=conf_mat,
                extra_meta={
                    "modality":           self._modality,
                    "split_strategy":     split_name,
                    "feature_columns":    feat_cols,
                    "feature_importance": fi,
                },
            )
            return SupervisedResult(
                modality=self._modality,
                task_type="classification",
                target_column=target_col,
                split_strategy=split_name,
                best_model_name=best_name,
                cv_results=cv_results,
                test_metrics=metrics,
                classification_report=clf_report,
                confusion_matrix=conf_mat,
                preparation_summary=prep_summary,
                saved_model_dir=str(self.output_dir),
                label_classes=label_enc.classes_.tolist(),
            )

        metrics = _regression_metrics(y_test, y_pred)
        fi      = self._extract_feature_importance(best_model, feat_cols)
        self._save_regression(
            model=best_model,
            prep_summary=prep_summary,
            cv_results=cv_results,
            best_name=best_name,
            test_metrics=metrics,
            feature_importance=fi,
            extra_meta={
                "modality":        self._modality,
                "split_strategy":  split_name,
                "feature_columns": feat_cols,
            },
        )
        return SupervisedResult(
            modality=self._modality,
            task_type="regression",
            target_column=target_col,
            split_strategy=split_name,
            best_model_name=best_name,
            cv_results=cv_results,
            test_metrics=metrics,
            classification_report=None,
            confusion_matrix=None,
            preparation_summary=prep_summary,
            saved_model_dir=str(self.output_dir),
            label_classes=None,
        )

    def _prepare_text(
        self, df: pd.DataFrame, text_col: str, target_col: str
    ) -> Tuple[pd.DataFrame, Dict]:
        working  = df[[text_col, target_col]].copy()
        n_before = len(working)

        working              = working.dropna(subset=[text_col, target_col]).copy()
        working[text_col]    = working[text_col].map(lambda t: _normalize_text(t, self._lang))
        working[target_col]  = working[target_col].astype(str).str.strip()
        working              = working[(working[text_col] != "") & (working[target_col] != "")].copy()
        n_after_clean        = len(working)

        unique_ratio     = working[text_col].nunique() / max(len(working), 1)
        use_group_filter = unique_ratio < 0.90

        if use_group_filter:
            ug      = working.groupby(target_col)[text_col].nunique()
            kept    = ug[ug >= MIN_UNIQUE_GROUP_SUPPORT].index
            dropped = ug[ug < MIN_UNIQUE_GROUP_SUPPORT].to_dict()
        else:
            rc      = working[target_col].value_counts()
            kept    = rc[rc >= MIN_ROWS_PER_CLASS].index
            dropped = rc[rc < MIN_ROWS_PER_CLASS].to_dict()

        n_before_filter = len(working)
        working         = working[working[target_col].isin(kept)].copy()

        if len(working) == 0:
            _raise(_failure(
                reason="No samples remain after removing rare classes and empty text rows",
                details={
                    "rows_before":           n_before,
                    "rows_after_cleaning":   n_after_clean,
                    "rows_after_filtering":  0,
                    "dropped_classes":       dropped,
                    "min_rows_per_class":    MIN_ROWS_PER_CLASS,
                },
                suggestions=[
                    "Provide more samples per class",
                    "Reduce the number of target classes",
                    "Check for encoding issues that may have blanked out text values",
                ],
            ))

        return working.reset_index(drop=True), {
            "rows_before":               n_before,
            "rows_after":                len(working),
            "dropped_missing_or_empty":  n_before - n_after_clean,
            "dropped_rare_class":        n_before_filter - len(working),
            "dropped_classes":           dropped,
            "n_classes":                 int(working[target_col].nunique()),
            "n_unique_texts":            int(working[text_col].nunique()),
            "class_distribution":        working[target_col].value_counts().to_dict(),
        }

    def _prepare_tabular(
        self, df: pd.DataFrame, feat_cols: List[str], target_col: str
    ) -> Tuple[pd.DataFrame, Dict]:
        cols = feat_cols + [target_col]
        for dt in self._dt_cols:
            if dt not in cols:
                cols.append(dt)

        working  = df[cols].copy()
        n_before = len(working)
        working  = working.dropna(subset=[target_col]).copy()

        num_feats = [c for c in feat_cols if working[c].dtype in (np.float64, np.int64, float, int)]
        for c in num_feats:
            working[c] = working[c].fillna(working[c].median())

        cat_feats = [c for c in feat_cols if c not in num_feats]
        for c in cat_feats:
            mode_val = working[c].mode()
            if len(mode_val):
                working[c] = working[c].fillna(mode_val[0])

        for dt in self._dt_cols:
            if dt in working.columns:
                working[dt]       = pd.to_datetime(working[dt], dayfirst=True, errors="coerce")
                working["_year"]  = working[dt].dt.year
                working["_month"] = working[dt].dt.month
                working["_week"]  = working[dt].dt.isocalendar().week.astype(int)
                if "_year" not in feat_cols:
                    feat_cols += ["_year", "_month", "_week"]

        if len(working) == 0:
            _raise(_failure(
                reason="No samples remain after dropping rows with missing target values",
                details={"rows_before": n_before, "rows_after": 0, "target_column": target_col},
                suggestions=[
                    "Fill missing target values before passing data to the engine",
                    "Verify the target column name is correct",
                ],
            ))

        return working.reset_index(drop=True), {
            "rows_before":       n_before,
            "rows_after":        len(working),
            "dropped_missing":   n_before - len(working),
            "n_feature_columns": len(feat_cols),
            "feature_columns":   feat_cols,
            "target_stats": {
                "nunique": int(working[target_col].nunique()),
                "dtype":   str(working[target_col].dtype),
            },
        }

    def _cross_validate_classification(
        self,
        pipelines: Dict[str, Any],
        X_train,
        y_train: np.ndarray,
        cv,
        cv_kwargs: Dict,
    ) -> List[Dict]:
        results         = []
        zero_metrics    = {k: 0.0 for k in ["accuracy", "balanced_accuracy", "f1_weighted", "f1_macro", "precision_weighted", "recall_weighted"]}
        failure_reports = []

        for name, pipe in pipelines.items():
            try:
                pred    = cross_val_predict(pipe, X_train, y_train, cv=cv, method="predict", **cv_kwargs)
                metrics = _classification_metrics(y_train, pred)
            except Exception as exc:
                failure_reports.append({"model": name, "error": str(exc)})
                metrics = zero_metrics.copy()
            results.append({"model_name": name, "cv_metrics": metrics})

        all_failed = all(r["cv_metrics"]["f1_weighted"] == 0.0 for r in results)
        if all_failed:
            _raise(_failure(
                reason="Cross-validation failed for all candidate models",
                details={
                    "n_train_samples": len(X_train),
                    "n_classes":       int(len(set(y_train))),
                    "model_errors":    failure_reports,
                },
                suggestions=[
                    "Ensure training data has sufficient samples per class",
                    "Check for class imbalance or corrupt feature values",
                    "Verify the cross-validation fold count does not exceed the number of samples",
                ],
            ))

        results.sort(
            key=lambda r: (
                r["cv_metrics"]["f1_weighted"],
                r["cv_metrics"]["balanced_accuracy"],
                r["cv_metrics"]["f1_macro"],
                r["cv_metrics"]["accuracy"],
            ),
            reverse=True,
        )
        return results

    def _cross_validate_regression(
        self,
        pipelines: Dict[str, Any],
        X_train,
        y_train: np.ndarray,
        cv,
        cv_kwargs: Dict,
    ) -> Tuple[Dict, List[Dict]]:
        results         = []
        fitted_models   = {}
        failure_reports = []

        for name, pipe in pipelines.items():
            try:
                pred    = cross_val_predict(pipe, X_train, y_train, cv=cv, method="predict", **cv_kwargs)
                metrics = _regression_metrics(y_train, pred)
            except Exception as exc:
                failure_reports.append({"model": name, "error": str(exc)})
                metrics = {"RMSE": float("inf"), "MAE": float("inf"), "R2": -1.0, "MAPE_pct": float("inf")}
            results.append({"model_name": name, "cv_metrics": metrics})
            fitted_models[name] = pipe

        all_failed = all(r["cv_metrics"]["RMSE"] == float("inf") for r in results)
        if all_failed:
            _raise(_failure(
                reason="Cross-validation failed for all candidate regression models",
                details={
                    "n_train_samples": len(X_train),
                    "model_errors":    failure_reports,
                },
                suggestions=[
                    "Check for non-numeric or infinite values in feature columns",
                    "Ensure the target column contains valid numeric values",
                    "Reduce the number of cross-validation folds if the dataset is small",
                ],
            ))

        results.sort(key=lambda r: r["cv_metrics"]["RMSE"])
        return fitted_models, results

    @staticmethod
    def _extract_feature_importance(
        model: Any, feat_cols: List[str]
    ) -> Optional[Dict[str, float]]:
        m = model.named_steps.get("model", model) if hasattr(model, "named_steps") else model
        if hasattr(m, "feature_importances_"):
            return dict(zip(feat_cols, m.feature_importances_.tolist()))
        if hasattr(m, "coef_"):
            coef = m.coef_.flatten() if m.coef_.ndim > 1 else m.coef_
            return dict(zip(feat_cols, coef.tolist()))
        return None

    def _ensure_output_dir(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _save_classification(
        self,
        pipeline: Any,
        label_enc: LabelEncoder,
        prep_summary: Dict,
        cv_results: List[Dict],
        best_name: str,
        test_metrics: Dict,
        clf_report: Dict,
        conf_mat: List,
        extra_meta: Dict,
    ) -> None:
        self._ensure_output_dir()
        joblib.dump(pipeline,  self.output_dir / "model_pipeline.joblib")
        joblib.dump(label_enc, self.output_dir / "label_encoder.joblib")

        metadata = {
            "project":   "Basira",
            "phase":     "Phase 2 — Supervised Classification",
            "task_type": "classification",
            "vectorizer": {
                "type":         "TF-IDF",
                "max_features": TFIDF_MAX_FEATURES,
                "ngram_range":  list(TFIDF_NGRAM_RANGE),
                "max_df":       TFIDF_MAX_DF,
                "sublinear_tf": TFIDF_SUBLINEAR_TF,
            } if self._modality in ("text_heavy", "bilingual") else None,
            "candidate_models":    [r["model_name"] for r in cv_results],
            "selected_model":      best_name,
            "selection_criterion": "Highest CV F1-weighted",
            "class_labels":        label_enc.classes_.tolist(),
            "preparation_summary": prep_summary,
            **extra_meta,
        }
        metrics_payload = {
            "cross_validation_results": cv_results,
            "selected_model":           best_name,
            "test_metrics":             test_metrics,
            "classification_report":    clf_report,
            "confusion_matrix":         conf_mat,
        }
        self._write_json(metadata,         "metadata.json")
        self._write_json(metrics_payload,  "metrics.json")

    def _save_regression(
        self,
        model: Any,
        prep_summary: Dict,
        cv_results: List[Dict],
        best_name: str,
        test_metrics: Dict,
        feature_importance: Optional[Dict],
        extra_meta: Dict,
    ) -> None:
        self._ensure_output_dir()
        joblib.dump(model, self.output_dir / "best_model.joblib")

        metadata = {
            "project":             "Basira",
            "phase":               "Phase 2 — Supervised Regression",
            "task_type":           "regression",
            "candidate_models":    [r["model_name"] for r in cv_results],
            "selected_model":      best_name,
            "selection_criterion": "Lowest CV RMSE",
            "preparation_summary": prep_summary,
            **extra_meta,
        }
        metrics_payload = {
            "cross_validation_results": cv_results,
            "selected_model":           best_name,
            "test_metrics":             test_metrics,
            "feature_importance":       feature_importance,
        }
        self._write_json(metadata,        "metadata.json")
        self._write_json(metrics_payload, "metrics.json")

    def _write_json(self, data: Dict, filename: str) -> None:
        with open(self.output_dir / filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def run_from_file(
    file_path: Path,
    text_column: Optional[str] = None,
    target_column: Optional[str] = None,
    task_type: str = "classification",
    output_name: str = "basira_run",
) -> SupervisedResult:
    df = load_file(file_path)

    if text_column and text_column in df.columns:
        modality = "text_heavy"
        lang     = "arabic" if df[text_column].dropna().astype(str).str.contains(
            r"[\u0600-\u06FF]"
        ).mean() > 0.3 else "english"
        routing  = {
            "task_type":               task_type,
            "target_column":           target_column,
            "text_columns":            [text_column],
            "numeric_columns":         [],
            "categorical_columns":     [],
            "datetime_columns":        [],
            "identifier_like_columns": [],
            "dataset_modality":        modality,
            "language_profile":        {"dominant_language": lang},
        }
    else:
        modality = "tabular"
        dt_cols  = [c for c in df.columns if "date" in c.lower() or "time" in c.lower()]
        routing  = {
            "task_type":               task_type,
            "target_column":           target_column,
            "text_columns":            [],
            "numeric_columns":         df.select_dtypes(include="number").columns.tolist(),
            "categorical_columns":     df.select_dtypes(include="object").columns.tolist(),
            "datetime_columns":        dt_cols,
            "identifier_like_columns": [],
            "dataset_modality":        modality,
            "language_profile":        {"dominant_language": "english"},
        }

    engine = SupervisedEngine(routing_decision=routing, output_name=output_name)
    return engine.run(df)


if __name__ == "__main__":
    import numpy as _np
    _np.random.seed(42)

    print("\n" + "━" * 70)
    print("SMOKE TEST 1 — Arabic text classification")
    print("━" * 70)
    n = 120
    arabic_texts = [
        "مشكلة في الفاتورة تم خصم مبلغ زيادة",
        "الانترنت لا يعمل في المنطقة",
        "لم يصل الطرد بعد مرور اسبوعين",
        "لا استطيع الدخول الى الحساب",
        "تم الاشتراك مرتين في نفس الخدمة",
    ]
    labels_ar = ["فاتورة", "انترنت", "شحن", "حساب", "اشتراك"]
    t1 = pd.DataFrame({
        "الشكوى":        _np.random.choice(arabic_texts, n),
        "تصنيف الشكوى": [labels_ar[arabic_texts.index(t)] for t in _np.random.choice(arabic_texts, n)],
    })
    routing1 = {
        "task_type":               "classification",
        "target_column":           "تصنيف الشكوى",
        "text_columns":            ["الشكوى"],
        "numeric_columns":         [],
        "categorical_columns":     [],
        "datetime_columns":        [],
        "identifier_like_columns": [],
        "dataset_modality":        "bilingual",
        "language_profile":        {"dominant_language": "arabic"},
    }
    e1 = SupervisedEngine(routing1, output_name="smoke_arabic")
    r1 = e1.run(t1)
    print(f"  → F1 weighted: {r1.test_metrics['f1_weighted']:.4f}")

    print("\n" + "━" * 70)
    print("SMOKE TEST 2 — Tabular regression")
    print("━" * 70)
    n2 = 400
    t2 = pd.DataFrame({
        "Store":        _np.random.randint(1, 46, n2),
        "Date":         pd.date_range("2010-02-05", periods=n2, freq="W"),
        "Holiday_Flag": _np.random.randint(0, 2, n2),
        "Temperature":  _np.random.uniform(20, 100, n2),
        "Fuel_Price":   _np.random.uniform(2.5, 4.5, n2),
        "CPI":          _np.random.uniform(126, 230, n2),
        "Unemployment": _np.random.uniform(4, 15, n2),
        "Weekly_Sales": _np.random.normal(1_500_000, 400_000, n2),
    })
    routing2 = {
        "task_type":               "regression",
        "target_column":           "Weekly_Sales",
        "text_columns":            [],
        "numeric_columns":         ["Store", "Holiday_Flag", "Temperature", "Fuel_Price", "CPI", "Unemployment"],
        "categorical_columns":     [],
        "datetime_columns":        ["Date"],
        "identifier_like_columns": [],
        "dataset_modality":        "tabular",
        "language_profile":        {"dominant_language": "english"},
    }
    e2 = SupervisedEngine(routing2, output_name="smoke_regression")
    r2 = e2.run(t2)
    print(f"  → R²: {r2.test_metrics['R2']:.4f}  RMSE: {r2.test_metrics['RMSE']:.0f}")

    print("\n" + "━" * 70)
    print("SMOKE TEST 3 — Tabular classification (English incidents)")
    print("━" * 70)
    categories   = ["Technical", "Billing", "Shipping", "Account", "Network"]
    descriptions = [
        "invoice error portal billing issue",
        "network not working connectivity problem",
        "order delayed shipment lost",
        "cannot login password reset",
        "account charged twice refund needed",
    ]
    n3 = 200
    t3 = pd.DataFrame({
        "description": _np.random.choice(descriptions, n3),
        "priority":    _np.random.choice(["High", "Medium", "Low"], n3),
        "open_days":   _np.random.randint(1, 30, n3),
        "category":    [categories[descriptions.index(d)] for d in _np.random.choice(descriptions, n3)],
    })
    routing3 = {
        "task_type":               "classification",
        "target_column":           "category",
        "text_columns":            ["description"],
        "numeric_columns":         ["open_days"],
        "categorical_columns":     ["priority"],
        "datetime_columns":        [],
        "identifier_like_columns": [],
        "dataset_modality":        "text_heavy",
        "language_profile":        {"dominant_language": "english"},
    }
    e3 = SupervisedEngine(routing3, output_name="smoke_classification")
    r3 = e3.run(t3)
    print(f"  → F1 weighted: {r3.test_metrics['f1_weighted']:.4f}")

    print("\n" + "━" * 70)
    print("SMOKE TEST 4 — Failure handling (tiny dataset)")
    print("━" * 70)
    t4 = pd.DataFrame({
        "text":   ["short"] * 5,
        "label":  ["A", "B", "C", "D", "E"],
    })
    routing4 = {
        "task_type":               "classification",
        "target_column":           "label",
        "text_columns":            ["text"],
        "numeric_columns":         [],
        "categorical_columns":     [],
        "datetime_columns":        [],
        "identifier_like_columns": [],
        "dataset_modality":        "text_heavy",
        "language_profile":        {"dominant_language": "english"},
    }
    try:
        e4 = SupervisedEngine(routing4, output_name="smoke_failure")
        e4.run(t4)
    except BasiraEngineError as err:
        print(f"  → Failure correctly caught:")
        print(err.report.to_json())

    print("\n✓ All smoke tests completed.")
