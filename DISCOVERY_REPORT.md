# Basira Workspace Discovery Report
_Generated 2026-05-10. Exploration only — no files moved, modified, or deleted._

Scope of exploration: `~/Desktop` root, `~/Desktop/1A/`, `~/Desktop/Basira local/`, `~/Desktop/advance proj /`, `~/Desktop/work/`, `~/Desktop/basira scraperssss v/`, and the unzipped `_staging/final_model/`.

---

## 1. Core Basira files

The canonical Basira application (matching `CLAUDE.md`) is split across **two locations** — there is no single folder that has all of it.

### 1a. Desktop root — engines, orchestrator, HTML, server script (but **NO `basira_app.py`**)

| File | Size | Modified | Notes |
|---|---|---|---|
| `~/Desktop/basira_bridge_orchestrator (8).py` | 48 202 | 2026-05-09 13:13 | The orchestrator from CLAUDE.md (filename has `(8)` suffix as documented). |
| `~/Desktop/charts_engine.py` | 47 806 | 2026-05-09 03:11 | Chart-generation layer. |
| `~/Desktop/rca_engine.py` | 77 165 | **2026-05-10 01:54** | Most-recently-edited engine in the workspace. |
| `~/Desktop/supervised_engine.py` | 47 615 | 2026-04-15 06:03 | Older than the `_F` variant in the zip — see Duplicates. |
| `~/Desktop/basira_preprocessor.html` | 34 920 | 2026-05-09 03:04 | Upload + Data Health UI. |
| `~/Desktop/basira_analysis_engine.html` | 55 006 | 2026-05-09 03:11 | Engine-selection UI. |
| `~/Desktop/chart_management.html` | 29 024 | 2026-05-09 03:11 | Chart-config UI. |
| `~/Desktop/requirements.txt` | 89 | 2026-05-09 03:04 | Flask + sklearn + scipy + openpyxl/xlrd. Minimal — no `flask-cors`, no `joblib`. |
| `~/Desktop/START_SERVER.sh` | 474 | 2026-05-09 03:04 | Runs `python3 basira_app.py` — but no `basira_app.py` lives next to it. |

**Missing here:** `basira_app.py`, `unsupervised_engine.py`, `insight_engine.py`. CLAUDE.md names `basira_app.py` as the Flask entry point; `START_SERVER.sh` tries to run it from this directory, but it isn't here.

### 1b. `~/Desktop/Basira local/` — has `basira_app.py` + scraper bundle

| File | Size | Modified | Notes |
|---|---|---|---|
| `basira_app.py` | 53 669 | 2026-05-09 03:04 | The Flask entry point ("Basira Smart Preprocessor — Flask Backend v3.0"). **Only copy on disk.** |
| `basira_scraper.py` | 33 307 | 2026-05-09 13:50 | Scraper (see §2). |
| `basira_overlay.js` | 41 238 | 2026-05-09 13:50 | Browser overlay used by the scraper. |
| `basira-logo.png` | 147 733 | 2026-05-09 13:50 | Logo asset. |
| `requirements.txt` | 265 | 2026-05-09 13:50 | Unified deps (Flask + Playwright + flask-cors + joblib). Newer/wider than the Desktop-root one. |

### 1c. `_staging/final_model/Basira Final model/basira_project 2 copy/` — the four engines, "F" variant

This folder is byte-identical to the existing `~/Desktop/Basira Final model/` folder — the on-disk one and the zip are the same (verified via `diff -rq`, ignoring `__MACOSX`).

| File | Size | Modified | Notes |
|---|---|---|---|
| `supervised_engine_F.py` | 70 005 | 2026-05-09 00:51 | "Final" supervised engine. |
| `unsupervised_engine_F.py` | 64 153 | 2026-05-09 00:51 | "Final" unsupervised engine. |
| `rca_engine_F.py` | 100 308 | 2026-05-09 00:51 | "Final" RCA engine. |
| `insight_engine_F.py` | 99 173 | 2026-05-09 00:52 | The 5th engine (InsightEngine, per CLAUDE.md) — **only copy on disk**. |
| `requirements.txt` | 448 | 2026-05-09 00:02 | "Basira Analytics Engine" deps. Adds `shap>=0.44`, mentions optional `streamlit` and `transformers/torch`. |
| `saved_models/` | (dir) | — | 11 demo run folders (smoke_classification, smoke_regression, sales_profit_run, retail_unsup_run, etc.) — model artifacts, not code. |
| `data/` | (dir) | — | Sample input data. |

**Where the canonical `BasiraEngine` (Phase 1 preprocessor) lives:** It is implemented inside `Basira local/basira_app.py` — that file is the Phase-1 pipeline + Flask routes combined. There is no separate `basira_engine.py` anywhere.

### Composite picture
To assemble a working app today you would need to combine:
- `Basira local/basira_app.py` (entry point + Phase 1 preprocessing)
- Desktop-root `basira_bridge_orchestrator (8).py`, `charts_engine.py`, `rca_engine.py`, `supervised_engine.py`
- `final_model/.../insight_engine_F.py`, `unsupervised_engine_F.py` (no non-`_F` copies exist)
- The three Desktop-root HTML files
- `Basira local/requirements.txt` (the only one with the full dep set)

---

## 2. Scraper files

Three distinct scraper iterations, plus a launcher to boot the third one inside the main app:

### Iteration A — Python/Flask + Playwright (most recent, integrated)
- `~/Desktop/1A/basira_scraper.py` (33 307 B)
- `~/Desktop/Basira local/basira_scraper.py` (33 307 B, **identical MD5** `d80489168cf7fdeba0b3cb42fb331df6`)
- Companion files (`basira_overlay.js`, `basira-logo.png`, `requirements.txt`) also identical between the two folders.
- Header comment: _"Faithful Python/Flask port of the original Node.js + Electron scraper"_ — i.e. this is the **rewrite** of an older Node.js implementation. Pipes CSV → preprocessor on port 5050. Uses Playwright + a sidebar overlay (SHIFT-click to pick fields).

### Iteration B — Next.js front-end scraper (older Node.js attempt)
- `~/Desktop/basira scraperssss v/basira-scraper كامل بس امريكي اسود  /` — full Next.js project (`pages/`, `next.config.js`, `tailwind.config.js`, `node_modules`, build `out/`). Pages: `index.js`, `scraper.js`, `_app.js`.
- Comment in `webscraping_launcher.py` confirms this folder is the "Next.js project" that replaced/preceded the Python port.

### Iteration C — Launcher to embed the Next.js scraper inside the main Basira desktop app
- `~/Desktop/basira scraperssss v/webscraping_launcher.py` (17 526 B, 2026-05-07).
- Reads install path from `AppData\Basira\install_path.txt`, opens browser, listens on port **5002** (5000 = main app, 5001 = bootstrap).
- Header docs an architecture where Basira ships as a desktop app (`Basira_app/`) with multiple launchers per feature.

### Scraper-related zip archives (untouched)
In `~/Desktop/basira scraperssss v/`:
- `basira-scraper 2.zip` (305 MB, 2026-04-15) — likely largest because it includes `node_modules`.
- `basira-scraper.zip` (304 MB, 2026-05-03)
- `basira-scraper final .zip` (290 MB, 2026-03-28)
- `basira-scraper perfect image & url .zip` (288 MB, 2026-03-12)
- `basira-scraper final final .zip` (277 MB, 2026-03-11)
- `basira-src.zip` (22 MB, 2026-03-11) — much smaller; probably source-only without `node_modules`.

In `~/Desktop/` root:
- `basira-scraper.zip` (315 KB, 2026-05-06)
- `1A.zip` (153 KB, 2026-05-09) — small, source-only.

In `~/Desktop/`:
- `~/Desktop/basira-scraper/` (folder, last touched 2026-03-28) — older Next.js source tree.
- `~/Desktop/AnanLink-old-backup/` — name suggests an earlier project lineage; not opened during this exploration.

---

## 3. Duplicate files

### 3a. Exact byte-for-byte duplicates (verified by MD5)

| File | Locations | MD5 |
|---|---|---|
| `basira_scraper.py` (33 307 B) | `1A/`, `Basira local/` | `d80489168cf7fdeba0b3cb42fb331df6` |
| `basira_overlay.js` (41 238 B) | `1A/`, `Basira local/` | `2971b265a88a1a72f2a0f5a5a0502086` |
| `basira-logo.png` (147 733 B) | `1A/`, `Basira local/` | `52cf6fb62e9f593d94d2f0279a15ebf1` |
| `requirements.txt` (265 B, scraper bundle) | `1A/`, `Basira local/` | `81ba1c89ca93b6f6228beb80af416fb9` |
| Whole tree `basira_project 2 copy/` | `~/Desktop/Basira Final model/` and `_staging/final_model/Basira Final model/` | identical (`diff -rq` clean, modulo `__MACOSX`) |

**Opinion on which is the "latest" / canonical:** `Basira local/` is the superset — it has everything `1A/` has **plus** `basira_app.py`. `1A/` looks like a partial snapshot that was sent/received separately (there is a sibling `1A.zip` 153 KB on Desktop, suggesting it was zipped for transfer). **Keep `Basira local/`; `1A/` is redundant.** Both copies have identical timestamps (2026-05-09 13:50) on the shared files, so neither is "newer" — just duplicated.

### 3b. Same-name, different content — supervised engine

| File | Size | Modified |
|---|---|---|
| `~/Desktop/supervised_engine.py` | 47 615 | 2026-04-15 |
| `_staging/final_model/.../supervised_engine_F.py` | 70 005 | 2026-05-09 |

**Opinion:** `supervised_engine_F.py` is significantly newer (3+ weeks) and ~50% larger — almost certainly the intended-final version. The Desktop-root `supervised_engine.py` looks like a stale pre-rewrite copy.

### 3c. Same-name, different content — RCA engine

| File | Size | Modified |
|---|---|---|
| `~/Desktop/rca_engine.py` | 77 165 | **2026-05-10 01:54** |
| `_staging/final_model/.../rca_engine_F.py` | 100 308 | 2026-05-09 00:51 |

**Opinion:** This one is **ambiguous and worth your eyes**. Desktop-root is **smaller but newer by ~1 day**. Either it's a recent trimmed/refactored version, or it's a different fork that diverged before the `_F` consolidation. Do not assume newer = canonical here without diffing.

### 3d. `requirements.txt` — three flavours, none identical

| Path | Size | Notes |
|---|---|---|
| `~/Desktop/requirements.txt` | 89 B | Minimal (Flask app only). |
| `~/Desktop/Basira local/requirements.txt` | 265 B | Unified — Flask + flask-cors + joblib + Playwright. **Most complete.** |
| `_staging/final_model/.../requirements.txt` | 448 B | "Basira Analytics Engine" — adds `shap`, optional `streamlit`/`torch`/`transformers`. |

**Opinion:** `Basira local/requirements.txt` is the most realistic for actually running the unified app. The `final_model` one targets just the engines (no Flask explicitly required for engines). The Desktop-root one is the oldest/narrowest.

### 3e. `advance/` vs `meme-advannce/` (DemandWise project — see §5)
- `DemandWise.py`: 67 562 vs 67 558 bytes (4 bytes apart, same date 2026-02-27) — near-duplicates.
- `api_server.py`: 1 199 vs 557 bytes — clearly diverged.
- **Opinion:** `meme-advannce/` looks like a fork (different `api_server.py`, has its own `venv/`). The `advance/` copy with the longer `api_server.py` (1 199 B) is more developed in some areas. Without running them, treating `advance/` as primary and `meme-advannce/` as an experiment branch is the safer read.

---

## 4. Unclassified files

Things found in scope that don't fit "core Basira" or "scraper":

- `~/Desktop/AnanLink-old-backup/` — Folder name implies a different / earlier product ("AnanLink"); not opened (out of explicit scope, and the name says "old-backup"). Worth a separate look later.
- `~/Desktop/basira all/` — empty subfolders (`data collection/`, `doc/`, `model/`, `preprocessing/`, `result/`) created 2026-05-09. Looks like a planned reorg skeleton that was never populated.
- `~/Desktop/GitHubDesktop-arm64.zip` (182 MB, 2026-05-09) — installer for GitHub Desktop. Not a project file.
- `~/Desktop/Screenshot 2026-05-10 at 02.16.48.png` (2 MB) — recent screenshot, unclear context.
- `~/Desktop/.docx.docx` (12 KB, 2022) and `~/Desktop/..ai` (3 MB, 2022) — old assets, names indicate accidental file naming.
- Many `~$…` files at Desktop root — these are MS Office **temporary lock files** (left behind when Word/Excel/PowerPoint crashes or doesn't close cleanly). They are 162-byte placeholder files and can typically be deleted without consequence; they are not project artifacts.
- `~/Desktop/basira-scraper/` (folder) and `~/Desktop/basira-scraper.zip` (315 KB) at Desktop root — older scraper source tree, predates `basira scraperssss v/`. Belongs to the Scraper section conceptually but lives at Desktop root.
- `~/Desktop/Basira-Workspace/_staging/final_model/Basira Final model/__MACOSX/` — macOS metadata pollution from the zip; **safe to ignore**, not real files.
- Within `final_model/.../saved_models/`: 11 run-output folders (`smoke_classification`, `smoke_regression`, `unsupervised_demo_run`, `sales_profit_run`, `retail_unsup_run`, etc.) — these are demo/test artifacts (`.joblib`, `.pkl`, JSON reports), not source.

---

## 5. Possible separate projects

### `~/Desktop/advance proj /` — **NOT Basira. Separate project: "DemandWise"**

- `DemandWise.py` opens with `import streamlit as st` and `from pmdarima import auto_arima`; page title is `"DemandWise | AI Forecasting"`.
- `api_server.py` is a **FastAPI** server with one `/forecast` endpoint that fits an `auto_arima` model and returns `n_periods=7` predictions.
- Folder also contains `CSC 453 Term Project.pdf`, `CS526_M2_Template.pdf`, and `SalesAdvance.csv` — this is a **course term project** for CS526/CSC453 about time-series sales forecasting.
- Tech stack overlap with Basira is essentially zero: Streamlit (vs Flask), pmdarima/ARIMA (vs sklearn), FastAPI (vs Flask), forecasting (vs preprocessing/RCA).
- **Verdict:** Unrelated academic project. Should not be folded into Basira.

### `~/Desktop/work/` — **NOT Basira. Personal/business material.**

- Contents are entirely PDFs, images, Excel pricing sheets, and product photos in Arabic-named subfolders (`تسعيره /`, `قرص عقيلي /`, `منتجات/`, `مستندات confidental/`, `assets/`, `HS preformance reprorts/`).
- File names indicate a food/sweets business: `تسعيرة الحلوى بالجمله.xlsx` (wholesale sweets pricing), `قرص عقيلي 12x12cm .pdf` (a regional sweet, packaging design), `جبنة بيضاء.pdf` (white cheese), `هوية السيفه.pdf` (brand identity for "Al-Sayfah"), `HungerStation Performance Report W9.pdf`.
- **No source code of any kind.** Zero `.py`, `.html`, `.md`, `.sh` files anywhere in the tree.
- **Verdict:** Personal/business assets — completely unrelated to Basira. Leave it alone.

---

DISCOVERY_REPORT.md ready for review
