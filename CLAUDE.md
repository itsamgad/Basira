# Basira — Smart Preprocessing Studio

## WHY
Automated end-to-end preprocessing engine for messy tabular data
(CSV / XLSX / XLS), bilingual (Arabic + English), built around a
transparency-first audit report so users see every transformation
that touched their data.

## WHAT — Architecture

### Main files
- `basira_app.py` — Flask app entry point, routes, file intake, UI wiring
- `basira_bridge_orchestrator__8_.py` — orchestration layer between engines
  (NOTE: filename has versioning suffix `__8__`; consider renaming to
  `basira_orchestrator.py` and updating imports)
- `charts_engine.py` — visualization layer (chart generation)
- `START_SERVER.sh` — local server launcher

### HTML views
- `basira_preprocessor.html` — upload + Data Health Overview + run controls
- `basira_analysis_engine.html` — engine selection (Supervised / Unsupervised / RCA / Insight)
- `chart_management.html` — chart configuration UI

### Five engines
1. **BasiraEngine** — automated preprocessing pipeline (Phase 1)
2. **SupervisedEngine** — classification + regression with auto-model selection (Phase 2)
3. **UnsupervisedEngine** — clustering + anomaly detection (Phase 3)
4. **RCAEngine** — root cause analysis with causal findings
5. **InsightEngine** — prioritized insights across 8 layers

## Pipeline thresholds — DO NOT change without explicit user approval

### Schema inference
- Numeric: >95% of values parseable as numbers
- Datetime: >90% parseable as dates, range **1980 – 2050**
- Text: high cardinality + average string length >18 characters

### Missing-value strategy selection
- **MICE**: ≥3 numeric columns AND missing ratio ≥15% AND ≥80 rows
- **KNN**: ≥2 numeric columns AND missing ratio ≥10% AND ≥200 rows
- **Simple (Mean / Median)**: default fallback, choice based on skewness
- **Categorical**: Bayesian (Naive Bayes) if conditions met, otherwise Mode

### Text pipeline
- TF-IDF: 8 000 features
- Truncated SVD: 16 components

### Outlier handling — IQR method
- Incident-like datasets (detected by keywords): flag and PRESERVE
- General datasets: winsorize

### Supervised
- Models evaluated: Random Forest, Gradient Boosting, Ridge, Linear
- Cross-validation: k = 3

### Unsupervised
- Models: K-Means, Agglomerative, DBSCAN
- Selection: composite score of Silhouette + Davies-Bouldin + Calinski-Harabasz

### RCA
- 9 finding categories (data_quality, drift, leakage, …)
- Severity levels: Critical → High → Medium → Low → Info

## Bilingual normalization rules — NON-NEGOTIABLE
- Arabic: remove diacritics, unify Hamzas, remove Tatweel
- English: lowercase, whitespace compression
- Replace 20+ missing tokens (English + Arabic, e.g. `N/A`, `لا يوجد`) → `NaN`

## Output artifacts (always produced together)
1. Cleaned CSV (preprocessed dataset)
2. Audit Report (log of every transformation: row, column, action, before/after)
3. Text Features (SVD embeddings)
4. Model Input (final unified numeric matrix)

## User journey (keep this in mind for any UX change)
Upload → Data Health Overview → choose Target / Incident Mode →
Run Basira (the "black box") → review Audit Report → pick an engine →
export the ready-to-use package.

## HOW — Working on this repo
- Python 3.10+
- Install: `pip install -r requirements.txt`
- Run locally: `bash START_SERVER.sh`
- Test changes against a messy sample CSV (Arabic + English, missing values,
  mixed dates) before committing.

## Conventions
- Do NOT auto-format files unrelated to the current task.
- Keep engines decoupled — engines never import each other directly;
  cross-engine communication only through the orchestrator.
- Never silently drop rows — every removal MUST be logged to the audit report.
- Preserve the audit-report contract: every transformation logs
  `{row, column, action, before, after}`.
- Bilingual logic must be tested with both Arabic and English fixtures.

## Current known issues / housekeeping
- `requirements.txt` lists **Flask** but original spec mentions Streamlit —
  reconcile which framework the project actually uses and update the spec.
- `basira_bridge_orchestrator__8_.py` has a versioning suffix in its name —
  rename to `basira_orchestrator.py` and update all imports.
- No automated tests yet — first priority is `tests/test_thresholds.py`
  covering the boundary cases of each pipeline threshold above.

## When in doubt
Ask before changing thresholds, the audit-report schema, or the engine
boundaries. These are the load-bearing parts of Basira.
