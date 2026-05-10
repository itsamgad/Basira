# Application-Level Verification — `basira-engine/`
_Run 2026-05-10. Read-only test of the reorganized files; no source code modified._

**Outcome: all 5 verification steps passed.**

| # | Step | Result |
|---|---|---|
| 1 | Create + activate `.venv` | ✅ Pass |
| 2 | `pip install -r requirements.txt` | ✅ Pass |
| 3 | Import all four `_F` engines | ✅ Pass |
| 4 | `basira_app.py` on port 5050, `GET /health` | ✅ Pass — HTTP 200 |
| 5 | `orchestrator.py` on port 5001, `GET /health` | ✅ Pass — HTTP 200 |

---

## Environment

- Working dir: `/Users/amghbd/Desktop/Basira-Workspace/basira-engine`
- Python: **3.13.5** (CLAUDE.md requires 3.10+ — satisfied)
- Venv: `basira-engine/.venv/` (gitignored)
- pip upgraded from 25.1.1 → 26.1.1 inside venv
- Host machine: macOS Darwin 25.3.0 / arm64

---

## Step 1 — Create venv and activate

```
$ python3 -m venv .venv
$ source .venv/bin/activate
$ python --version
Python 3.13.5
$ echo $VIRTUAL_ENV
/Users/amghbd/Desktop/Basira-Workspace/basira-engine/.venv
```

**Result:** ✅ Venv created, Python 3.13.5 active.

---

## Step 2 — `pip install -r requirements.txt`

`requirements.txt` requested: `numpy>=1.26, pandas>=2.1, scipy>=1.11, scikit-learn>=1.4, joblib>=1.3, openpyxl>=3.1, xlrd>=2.0, shap>=0.44, flask>=3.0, flask-cors>=4.0` (optional `streamlit`/`torch`/`transformers`/`langdetect`/`sentencepiece` left commented).

**Result:** ✅ All 27 packages (10 direct + 17 transitive) installed cleanly. No errors, no warnings about resolver conflicts.

Resolved versions:
```
numpy 2.4.4         pandas 3.0.2         scipy 1.17.1
scikit-learn 1.8.0  joblib 1.5.3         openpyxl 3.1.5
xlrd 2.0.2          shap 0.51.0          flask 3.1.3
flask-cors 6.0.2
```

Transitive: `blinker, click, cloudpickle, et-xmlfile, itsdangerous, jinja2, llvmlite, markupsafe, numba, packaging, python-dateutil, six, slicer, threadpoolctl, tqdm, typing-extensions, werkzeug`.

---

## Step 3 — Engine import test

```
$ python -c "from supervised_engine_F  import SupervisedEngine,  BasiraEngineError; \
              from unsupervised_engine_F import UnsupervisedEngine, BasiraUnsupervisedError; \
              from rca_engine_F          import RCAEngine,         BasiraRCAError; \
              from insight_engine_F      import InsightEngine,     BasiraInsightError; \
              print('All 4 engines imported OK')"
All 4 engines imported OK
```

**Result:** ✅ All 4 engine modules and 8 expected symbols imported with no errors. Confirms the orchestrator's import line `from rca_engine_F import RCAEngine, BasiraRCAError` (and equivalents for the other three engines) will resolve correctly in the new layout.

---

## Step 4 — `basira_app.py` health check

Port wiring confirmed at `basira_app.py:1223` → `app.run(debug=True, host="0.0.0.0", port=5050)`.

Server start (background):
```
🚀 Basira Smart Preprocessor v3.0 — http://localhost:5050
 * Serving Flask app 'basira_app'
 * Debug mode: on
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:5050
 * Running on http://172.20.10.11:5050
```

`lsof` confirmed listener on `*:5050 (LISTEN)`.

Curl request and response:
```
$ curl -i http://127.0.0.1:5050/health
HTTP 200
{
  "status": "ok",
  "version": "3.0"
}
```

Server log entry: `127.0.0.1 - - [10/May/2026 04:09:42] "GET /health HTTP/1.1" 200 -`.

Stopped via `pkill -f basira_app.py`; port 5050 released cleanly.

**Result:** ✅ Pass.

**Side note (not a failure):** `basira_app.py` hardcodes `debug=True` in the `app.run()` call. `FLASK_DEBUG=0` had no effect because the kwarg overrides the env var. Worth flagging for production, but does not affect this verification.

---

## Step 5 — `orchestrator.py` health check

Port wiring confirmed at `orchestrator.py:1152` → `app.run(host="0.0.0.0", port=5001, debug=False)`.

Server start (background):
```
🚀 BASIRA BRIDGE ORCHESTRATOR
   Final pipeline coordinator: Model → RCA → Insight → Visualization

  Health  : http://127.0.0.1:5001/health
  Analyze : http://127.0.0.1:5001/analyze

 * Serving Flask app 'orchestrator'
 * Debug mode: off
 * Running on http://127.0.0.1:5001
 * Running on http://172.20.10.11:5001
```

`lsof` confirmed listener on `*:5001 (LISTEN)`.

Curl request and response:
```
$ curl -i http://127.0.0.1:5001/health
HTTP 200
{
  "pipeline": [
    "supervised_engine_F",
    "unsupervised_engine_F",
    "rca_engine_F",
    "insight_engine_F",
    "visualization_payload"
  ],
  "service": "Basira Bridge Orchestrator",
  "status": "ok",
  "version": "basira-bridge-v1.1"
}
```

Notable: the orchestrator's `/health` reports the full engine pipeline by module name, and **all four module names match the `_F` files we placed in `basira-engine/`** — the orchestrator is wired to the canonical engine set.

Server log entry: `127.0.0.1 - - [10/May/2026 04:10:39] "GET /health HTTP/1.1" 200 -`.

Stopped via `pkill -f orchestrator.py`; port 5001 released cleanly.

**Result:** ✅ Pass.

---

## What this verification did NOT cover

- No `POST /analyze` round-trip; only `/health` was exercised.
- No engine-level model fitting / inference (no run against `data/` samples).
- No HTML UI (`basira_preprocessor.html`, etc.) was loaded in a browser.
- No interaction between `basira_app.py` (5050) and `orchestrator.py` (5001) was tested.
- `START_SERVER.sh` was not invoked; the venv-based launch was used instead.

These are the next layers of testing if you want to take the verification deeper.

---

## Summary

The reorganization preserved the runnable application: every engine module imports, both Flask services bind their expected ports, and both `/health` endpoints respond 200 OK. The orchestrator's reported pipeline confirms it is wired to the four `_F` engines now sitting in `basira-engine/`.
