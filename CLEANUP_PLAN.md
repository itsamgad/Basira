# Basira Workspace — Cleanup Plan
_Written 2026-05-10. Reversible: `mv` only, no `rm`. Do not execute until reviewed._

This plan consolidates everything `DISCOVERY_REPORT.md` identified into one runnable folder (`basira-engine/`) and parks every other in-scope artifact under `_archive/` so nothing is lost. Out-of-scope items (`advance proj /`, `work/`, `AnanLink-old-backup/`, MS Office `~$…` lock files, the GitHub Desktop installer zip) are not touched.

---

## 0. Source-of-truth map (what ends up in `basira-engine/`)

| Target file in `basira-engine/` | Picked from | Why |
|---|---|---|
| `basira_app.py` | `~/Desktop/Basira local/basira_app.py` | Only copy on disk. |
| `orchestrator.py` | `~/Desktop/basira_bridge_orchestrator (8).py` (renamed) | Canonical orchestrator per CLAUDE.md; rename strips the `(8)` versioning suffix. |
| `charts_engine.py` | `~/Desktop/charts_engine.py` | Only copy. |
| `supervised_engine_F.py` | `_staging/final_model/Basira Final model/basira_project 2 copy/supervised_engine_F.py` | 70 005 B / 2026-05-09 — newer & larger than Desktop-root `supervised_engine.py` (47 615 B / 2026-04-15). |
| `unsupervised_engine_F.py` | same `_staging` path | Only copy. |
| `rca_engine_F.py` | same `_staging` path | Per target spec, take the `_F` version. (Desktop-root `rca_engine.py` is 1 day newer but smaller — see §4 caveat.) |
| `insight_engine_F.py` | same `_staging` path | Only copy. |
| `requirements.txt` | `_staging/final_model/Basira Final model/basira_project 2 copy/requirements.txt` | Per spec ("more complete version, from the zip"); 448 B with `shap`, optional `torch`/`transformers`. |
| `START_SERVER.sh` | `~/Desktop/START_SERVER.sh` | Only copy. |
| `basira_preprocessor.html` | `~/Desktop/basira_preprocessor.html` | Only copy. |
| `basira_analysis_engine.html` | `~/Desktop/basira_analysis_engine.html` | Only copy. |
| `chart_management.html` | `~/Desktop/chart_management.html` | Only copy. |
| `data/` | `_staging/final_model/Basira Final model/basira_project 2 copy/data/` | Sample inputs. |
| `saved_models/` | same `_staging` path | 11 demo run folders for engines. |

Everything else in scope → `_archive/` (see §3–§6).

---

## 1. Phase 0 — Create scaffolding

```bash
mkdir -p /Users/amghbd/Desktop/Basira-Workspace/basira-engine
mkdir -p /Users/amghbd/Desktop/Basira-Workspace/_archive/scraper
mkdir -p /Users/amghbd/Desktop/Basira-Workspace/_archive/old-engines
mkdir -p /Users/amghbd/Desktop/Basira-Workspace/_archive/old-requirements
mkdir -p /Users/amghbd/Desktop/Basira-Workspace/_archive/redundant-final-model
mkdir -p /Users/amghbd/Desktop/Basira-Workspace/_archive/empty-skeletons
mkdir -p /Users/amghbd/Desktop/Basira-Workspace/_archive/zips
```

---

## 2. Phase 1 — Populate `basira-engine/`

### 2a. From Desktop root

```bash
mv "/Users/amghbd/Desktop/basira_bridge_orchestrator (8).py" \
   "/Users/amghbd/Desktop/Basira-Workspace/basira-engine/orchestrator.py"

mv "/Users/amghbd/Desktop/charts_engine.py" \
   "/Users/amghbd/Desktop/Basira-Workspace/basira-engine/charts_engine.py"

mv "/Users/amghbd/Desktop/START_SERVER.sh" \
   "/Users/amghbd/Desktop/Basira-Workspace/basira-engine/START_SERVER.sh"

mv "/Users/amghbd/Desktop/basira_preprocessor.html" \
   "/Users/amghbd/Desktop/Basira-Workspace/basira-engine/basira_preprocessor.html"

mv "/Users/amghbd/Desktop/basira_analysis_engine.html" \
   "/Users/amghbd/Desktop/Basira-Workspace/basira-engine/basira_analysis_engine.html"

mv "/Users/amghbd/Desktop/chart_management.html" \
   "/Users/amghbd/Desktop/Basira-Workspace/basira-engine/chart_management.html"
```

### 2b. From `Basira local/` — pull only `basira_app.py`

```bash
mv "/Users/amghbd/Desktop/Basira local/basira_app.py" \
   "/Users/amghbd/Desktop/Basira-Workspace/basira-engine/basira_app.py"
```

### 2c. From `_staging/` — the four `_F` engines + requirements + data + saved_models

```bash
STAGE="/Users/amghbd/Desktop/Basira-Workspace/_staging/final_model/Basira Final model/basira_project 2 copy"
DEST="/Users/amghbd/Desktop/Basira-Workspace/basira-engine"

mv "$STAGE/supervised_engine_F.py"   "$DEST/supervised_engine_F.py"
mv "$STAGE/unsupervised_engine_F.py" "$DEST/unsupervised_engine_F.py"
mv "$STAGE/rca_engine_F.py"          "$DEST/rca_engine_F.py"
mv "$STAGE/insight_engine_F.py"      "$DEST/insight_engine_F.py"
mv "$STAGE/requirements.txt"         "$DEST/requirements.txt"
mv "$STAGE/data"                     "$DEST/data"
mv "$STAGE/saved_models"             "$DEST/saved_models"
```

After this, `basira-engine/` is complete.

---

## 3. Phase 2 — Archive scraper material (`_archive/scraper/`)

Per rules: nothing scraper-related enters `basira-engine/`.

### 3a. The whole `1A/` folder (scraper bundle, exact dup of part of `Basira local/`)

```bash
mv "/Users/amghbd/Desktop/1A" \
   "/Users/amghbd/Desktop/Basira-Workspace/_archive/scraper/1A"
```

### 3b. Remaining contents of `Basira local/` (after `basira_app.py` was pulled out in §2b)

What's left there is the scraper bundle (`basira_scraper.py`, `basira_overlay.js`, `basira-logo.png`, `requirements.txt`).

```bash
mv "/Users/amghbd/Desktop/Basira local" \
   "/Users/amghbd/Desktop/Basira-Workspace/_archive/scraper/Basira-local-leftovers"
```

### 3c. Older Next.js scraper source on Desktop root

```bash
mv "/Users/amghbd/Desktop/basira-scraper" \
   "/Users/amghbd/Desktop/Basira-Workspace/_archive/scraper/basira-scraper"
```

### 3d. The big multi-version scraper folder

```bash
mv "/Users/amghbd/Desktop/basira scraperssss v" \
   "/Users/amghbd/Desktop/Basira-Workspace/_archive/scraper/basira-scraperssss-v"
```

### 3e. Loose scraper zip archives at Desktop root

```bash
mv "/Users/amghbd/Desktop/basira-scraper.zip" \
   "/Users/amghbd/Desktop/Basira-Workspace/_archive/zips/basira-scraper.zip"

mv "/Users/amghbd/Desktop/1A.zip" \
   "/Users/amghbd/Desktop/Basira-Workspace/_archive/zips/1A.zip"
```

---

## 4. Phase 3 — Archive stale engine versions (`_archive/old-engines/`)

```bash
mv "/Users/amghbd/Desktop/supervised_engine.py" \
   "/Users/amghbd/Desktop/Basira-Workspace/_archive/old-engines/supervised_engine.py"

mv "/Users/amghbd/Desktop/rca_engine.py" \
   "/Users/amghbd/Desktop/Basira-Workspace/_archive/old-engines/rca_engine_DESKTOP_2026-05-10.py"
```

**⚠ Caveat to confirm before executing this step.** `~/Desktop/rca_engine.py` is 1 day NEWER (2026-05-10 01:54) than the `_F` version chosen for `basira-engine/` (2026-05-09 00:51), even though the `_F` one is larger. The target spec asks for `rca_engine_F.py`, so this plan archives the Desktop-root file — but if those Desktop-root edits matter, they need to be merged into `rca_engine_F.py` first. Renaming the archived copy with a date suffix (`_DESKTOP_2026-05-10`) keeps it easy to spot.

---

## 5. Phase 4 — Archive stale requirements files (`_archive/old-requirements/`)

```bash
mv "/Users/amghbd/Desktop/requirements.txt" \
   "/Users/amghbd/Desktop/Basira-Workspace/_archive/old-requirements/requirements_DESKTOP_89B.txt"
```

The 265 B `Basira local/requirements.txt` is already inside the folder being moved in §3b, so it ends up under `_archive/scraper/Basira-local-leftovers/requirements.txt` automatically — no separate command needed.

---

## 6. Phase 5 — Archive the redundant on-Desktop copy of "Basira Final model"

`~/Desktop/Basira Final model/` is byte-identical to what we unzipped (verified via `diff -rq`). After Phase 1 drains the `_staging` copy into `basira-engine/`, this on-Desktop copy is a pure duplicate.

```bash
mv "/Users/amghbd/Desktop/Basira Final model" \
   "/Users/amghbd/Desktop/Basira-Workspace/_archive/redundant-final-model/Basira Final model"
```

Also move the now-emptied `_staging/` tree (the zip is preserved separately in §7):

```bash
mv "/Users/amghbd/Desktop/Basira-Workspace/_staging" \
   "/Users/amghbd/Desktop/Basira-Workspace/_archive/redundant-final-model/_staging-emptied"
```

---

## 7. Phase 6 — Archive misc empty / leftover items

```bash
# Empty reorg skeleton on Desktop (created 2026-05-09, never populated)
mv "/Users/amghbd/Desktop/basira all" \
   "/Users/amghbd/Desktop/Basira-Workspace/_archive/empty-skeletons/basira-all"

# The original zip — kept for reproducibility, just moved into the archive zips folder
mv "/Users/amghbd/Desktop/Basira-Workspace/Basira Final model.zip" \
   "/Users/amghbd/Desktop/Basira-Workspace/_archive/zips/Basira Final model.zip"
```

---

## 8. Phase 7 — Verification (read-only)

```bash
echo "=== basira-engine contents ==="
ls -la "/Users/amghbd/Desktop/Basira-Workspace/basira-engine"

echo "=== _archive tree (top 3 levels) ==="
find "/Users/amghbd/Desktop/Basira-Workspace/_archive" -maxdepth 3 -mindepth 1 | sort

echo "=== Desktop root after cleanup (should no longer contain Basira code, scrapers, or HTML) ==="
ls -la "/Users/amghbd/Desktop" | grep -Ei 'basira|1A|scraper|preprocessor|analysis_engine|chart_management|orchestrator|engine\.py|START_SERVER' || echo "(clean)"
```

Expected after-state:

```
Basira-Workspace/
├── CLAUDE.md
├── DISCOVERY_REPORT.md
├── CLEANUP_PLAN.md
├── basira-engine/
│   ├── basira_app.py
│   ├── orchestrator.py
│   ├── charts_engine.py
│   ├── supervised_engine_F.py
│   ├── unsupervised_engine_F.py
│   ├── rca_engine_F.py
│   ├── insight_engine_F.py
│   ├── requirements.txt
│   ├── START_SERVER.sh
│   ├── basira_preprocessor.html
│   ├── basira_analysis_engine.html
│   ├── chart_management.html
│   ├── data/
│   └── saved_models/
└── _archive/
    ├── scraper/
    │   ├── 1A/
    │   ├── Basira-local-leftovers/
    │   ├── basira-scraper/
    │   └── basira-scraperssss-v/
    ├── old-engines/
    │   ├── supervised_engine.py
    │   └── rca_engine_DESKTOP_2026-05-10.py
    ├── old-requirements/
    │   └── requirements_DESKTOP_89B.txt
    ├── redundant-final-model/
    │   ├── Basira Final model/
    │   └── _staging-emptied/
    ├── empty-skeletons/
    │   └── basira-all/
    └── zips/
        ├── Basira Final model.zip
        ├── basira-scraper.zip
        └── 1A.zip
```

---

## 9. What this plan deliberately does NOT touch

- `~/Desktop/advance proj /` — confirmed unrelated (DemandWise / CS526 forecasting term project).
- `~/Desktop/work/` — confirmed unrelated (food-business assets, no code).
- `~/Desktop/AnanLink-old-backup/` — out of explicit scope; name suggests an unrelated older project.
- `~/Desktop/GitHubDesktop-arm64.zip` — third-party installer.
- `~/Desktop/Screenshot 2026-05-10 at 02.16.48.png`, `~/Desktop/.docx.docx`, `~/Desktop/..ai`, all `~$…` MS Office lock files — not project artifacts.
- `~/Desktop/graduation proj/`, `~/Desktop/selected topics in cs/`, `~/Desktop/game dev /` — not in the scope you defined and not referenced by Basira.

---

## 10. Reversibility

Every command in §1–§7 is `mkdir` or `mv`. No `rm`, no overwrites (every destination path is new). To undo any single step, run the same `mv` with source and destination swapped. Renames in §2a (`orchestrator.py`), §4, §5 use unique destination names, so the original filename is recoverable from the renamed-archive copy if needed.

The original zip is preserved in `_archive/zips/Basira Final model.zip`, so even the engine `_F` files can be recovered from there if anything goes wrong.

---

## 11. Open questions to confirm before I execute

1. **`rca_engine.py` ambiguity (§4 caveat).** Desktop-root copy is 1 day newer but smaller. Confirm it's safe to archive in favor of `rca_engine_F.py`, or ask me to diff them first and report which functions diverge.
2. **`requirements.txt` choice.** The spec said "the more complete version (from the zip)" → I'm using the 448 B analytics-engine one. It does **not** include `playwright` or the explicit `xlrd`/`flask` versions that the 265 B `Basira local` file had. If the goal is to install once and run preprocessor + engines + UI, the 265 B file is arguably more practical. Confirm or override.
3. **`AnanLink-old-backup/`.** Want me to leave it on Desktop, or move it to `_archive/uncertain/` for later triage?
4. **MS Office `~$…` lock files on Desktop.** Want me to sweep them into `_archive/office-locks/` as part of this cleanup, or leave them alone?

Awaiting go-ahead before running anything.
