# Basira Scraper — Visual Web Scraper

Sibling project to `../basira-engine/`. Independent service — does not import
from the engine and does not need to be running for the engine to work.
The two are wired together at runtime over HTTP (port 5051 → port 5050) when
the user clicks "Send to preprocessor".

## What it does

Faithful Python/Flask port of an earlier Node.js + Electron scraper. Launches
a **visible** Chromium window (not headless), injects a sidebar overlay
(`basira_overlay.js`), and lets the user pick fields by:

1. clicking once on a representative item (anchor),
2. SHIFT-clicking each field they want to extract.

The overlay sends the field definitions back to the Flask backend, which then
runs auto-scroll / pagination / load-more with 3-retry logic, exports a flat
long-format JSON + CSV, and can pipe the CSV directly into the Basira
preprocessor.

## Port and entry point

- Entry point: `basira_scraper.py`
- Port: **5051**  (engine runs on 5050; orchestrator runs on 5001)
- URL: `http://localhost:5051`
- Health check: `GET /health`

## Endpoints

```
GET  /health                       liveness probe
POST /open-browser                 launch Chromium + inject overlay
GET  /check-selection?jobId=…      poll window.basiraResults
GET  /get-progress?jobId=…         live progress
POST /extract-data                 run the full scrape (blocks)
GET  /get-data?jobId=…             saved long-format JSON
GET  /history                      saved scrapes list
POST /send-to-preprocessor         pipe CSV → http://localhost:5050/upload-process
```

CORS is hand-rolled in an `@app.after_request` hook (allow-all). No
`flask-cors` dependency.

## Dependencies

Python (in `requirements.txt`):

- `flask>=3.0`
- `playwright>=1.40`
- `pandas>=2.0`
- `requests>=2.31`

**Browser binaries** are NOT pulled by `pip`. After `pip install`, you must
run:

```bash
playwright install chromium
```

This downloads the Chromium binary Playwright drives. Without it, the
`/open-browser` endpoint fails with `BrowserType.launch: Executable doesn't exist`.

## How to launch

```bash
cd basira-scraper
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium      # one-time, ~150 MB download
python basira_scraper.py
```

Then open `http://localhost:5051/health` in a browser to verify it's up.
The actual scraping UI is the Chromium window the backend opens via
`POST /open-browser`, not a Flask-served HTML page.

## Files in this folder

| File | Role |
|---|---|
| `basira_scraper.py`  | Flask backend — endpoints, Playwright worker thread, CSV pipe to preprocessor |
| `basira_overlay.js`  | Sidebar UI injected into every scraped page (1028 lines, vanilla JS) |
| `basira-logo.png`    | Logo asset; spliced into overlay as base64 at startup |
| `requirements.txt`   | Python deps (slimmed from the original archived bundle — engine deps removed) |

The script `_load_overlay_script()` substitutes `__BASIRA_LOGO_BASE64__` in
the JS with a base64 of the PNG, so all three files must sit next to each
other.

## Runtime artifacts (gitignored)

When the scraper runs it creates:

- `scrape_outputs/` — exported JSON / CSV per job
- `scrape_history.json` — running log of past scrapes

Both are excluded from git.

## What it does NOT do

- It does **not** import anything from `basira-engine/`. The two are linked
  only via HTTP at `http://localhost:5050/upload-process`.
- It does **not** start the engine. If you want end-to-end scrape →
  preprocess → analyse, you start the engine separately on port 5050 first.
- It is not headless. The visible Chromium window is the point — users pick
  fields by clicking.
