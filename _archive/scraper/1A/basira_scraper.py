"""
Basira Scraper — Flask Backend v1.0
Faithful Python/Flask port of the original Node.js + Electron scraper.

Launches a VISIBLE Chromium window (not headless), injects the Basira
overlay sidebar, lets the user click an item + SHIFT-click each field,
then runs auto-scroll / pagination / load-more with 3-retry logic and
exports JSON + a flat CSV ready for the Basira preprocessor (port 5050).

Endpoints (REST style, matches the brief):
  GET  /health                       liveness
  POST /open-browser                 launch Chromium + inject overlay
  GET  /check-selection?jobId=…      poll window.basiraResults
  GET  /get-progress?jobId=…         live progress
  POST /extract-data                 run the full scrape (blocks)
  GET  /get-data?jobId=…             saved long-format JSON
  GET  /history                      saved scrapes list
  POST /send-to-preprocessor         pipe CSV → localhost:5050
"""

import os, sys, json, base64, time, threading, atexit, random, re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin

import pandas as pd
import requests
from flask import Flask, request, jsonify

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
except ImportError:
    sys.stderr.write(
        "ERROR: playwright is not installed.\n"
        "  pip install playwright\n"
        "  playwright install chromium\n"
    )
    sys.exit(1)


# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).resolve().parent
OVERLAY_PATH = BASE_DIR / "basira_overlay.js"
LOGO_PATH    = BASE_DIR / "basira-logo.png"
OUTPUT_DIR   = BASE_DIR / "scrape_outputs"
HISTORY_FILE = BASE_DIR / "scrape_history.json"
OUTPUT_DIR.mkdir(exist_ok=True)

PREPROCESSOR_URL = "http://localhost:5050/upload-process"

# 10-string UA pool (verbatim from original)
USER_AGENTS = [
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0',
    'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0',
]

def random_ua():
    return random.choice(USER_AGENTS)

def human_delay_ms(base_ms: float) -> float:
    """base*0.6 + rand*base*0.8 — matches JS humanDelay()."""
    return base_ms * 0.6 + random.random() * base_ms * 0.8

# Stealth: hide webdriver flag, fake plugins/languages/chrome
STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins',   { get: () => [1, 2, 3] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
window.chrome = { runtime: {} };
"""


# ─────────────────────────────────────────────────────────────
# OVERLAY SCRIPT — load once, splice logo as base64
# ─────────────────────────────────────────────────────────────
def _load_overlay_script() -> str:
    if not OVERLAY_PATH.exists():
        raise FileNotFoundError(
            f"basira_overlay.js missing at {OVERLAY_PATH}. "
            "Did you copy it next to basira_scraper.py?"
        )
    if not LOGO_PATH.exists():
        raise FileNotFoundError(
            f"basira-logo.png missing at {LOGO_PATH}. "
            "The overlay sidebar logo expects this file alongside basira_scraper.py."
        )
    js = OVERLAY_PATH.read_text(encoding="utf-8")
    logo_b64 = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    return js.replace("__BASIRA_LOGO_BASE64__", logo_b64)

OVERLAY_SCRIPT = _load_overlay_script()


# ─────────────────────────────────────────────────────────────
# PLAYWRIGHT WORKER
# All Playwright ops MUST run on the same OS thread because sync_playwright
# uses greenlets pinned to their creating thread. We serialize through one
# worker. /get-progress is a pure dict read and bypasses this so polling
# stays snappy while /extract-data is blocking the worker.
# ─────────────────────────────────────────────────────────────
_pw_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="basira-pw")
_playwright  = None  # initialised lazily on the worker thread

# Session state — keyed by jobId
_active_browsers = {}  # {jobId: {browser, context, page, stealth, start_time, url}}
_jobs_progress   = {}  # {jobId: {status, currentPage, totalPages, itemsCollected, failedItems, error}}
_jobs_data       = {}  # {jobId: long-format list of dicts}
_jobs_fields     = {}  # {jobId: list of field defs as returned by the overlay}

def _pw_ensure():
    """Lazy-init sync_playwright on whichever thread calls this (the worker)."""
    global _playwright
    if _playwright is None:
        _playwright = sync_playwright().start()
    return _playwright

def _pw_run(fn, *args, **kwargs):
    """Submit a Playwright op to the worker thread and wait for its result."""
    return _pw_executor.submit(fn, *args, **kwargs).result()


# ─────────────────────────────────────────────────────────────
# FIELD VALUE EXTRACTION (mirrors extractFieldValue in the original)
# ─────────────────────────────────────────────────────────────
_PRICE_STRIP = str.maketrans("", "", "£$€¥₹, \t\n")
_STAR_RE = re.compile(r'\b(One|Two|Three|Four|Five)\b', re.IGNORECASE)
_STAR_MAP = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5"}

def _extract_field_value(el, field, page_url):
    ftype = field.get("type", "text")
    if ftype == "image":
        src = (el.get_attribute("src")
               or el.get_attribute("data-src")
               or el.get_attribute("data-lazy")
               or "")
        if src:
            try:    return urljoin(page_url, src)
            except Exception: return src
        return ""
    if ftype == "link":
        href = el.get_attribute("href") or ""
        if href:
            try:    return urljoin(page_url, href)
            except Exception: return href
        return ""
    if ftype == "price":
        raw = el.text_content() or ""
        return raw.translate(_PRICE_STRIP).strip()
    # text — detect star-rating CSS class names
    cls = el.get_attribute("class") or ""
    m = _STAR_RE.search(cls)
    if m:
        return _STAR_MAP.get(m.group(1).lower(), m.group(1))
    return (el.text_content() or "").strip()


def _extract_item_with_retry(item, fields, page, max_retries=3):
    """Retry up to max_retries times; linear 500ms·attempt backoff."""
    page_url = page.url
    for attempt in range(1, max_retries + 1):
        try:
            row = {}
            has_data = False
            for field in fields:
                try:
                    el = item.query_selector(field["selector"])
                    if el:
                        v = _extract_field_value(el, field, page_url)
                        if v:
                            row[field["name"]] = v
                            has_data = True
                except Exception as fe:
                    print(f"  Field '{field.get('name')}' failed (attempt {attempt}): {fe}")
            return row, has_data
        except Exception as e:
            print(f"  Item attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                time.sleep(0.5 * attempt)
    return {}, False


# ─────────────────────────────────────────────────────────────
# IN-PAGE LOOPS (auto-scroll / load-more) — run as JS so they're fast
# ─────────────────────────────────────────────────────────────
_AUTO_SCROLL_JS = r"""
async ({ containerSel, itemSel, maxRows }) => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const lim = (typeof maxRows === 'number' && maxRows > 0) ? maxRows : Infinity;
  let prev = 0, noNew = 0, iter = 0;
  while (iter++ < 500) {
    const items = document.querySelectorAll(containerSel + ' ' + itemSel);
    const cur = items.length;
    if (cur >= lim) break;
    if (cur > prev) { noNew = 0; } else { if (++noNew >= 15) break; }
    prev = cur;
    if (items.length) items[items.length - 1].scrollIntoView({ behavior: 'smooth', block: 'center' });
    await sleep(1500);
    if (iter % 5 === 0) { window.scrollBy(0, 200); await sleep(300); }
  }
  window.scrollTo({ top: 0, behavior: 'auto' });
  await sleep(500);
  return document.querySelectorAll(containerSel + ' ' + itemSel).length;
}
"""

_LOAD_MORE_JS = r"""
async ({ containerSel, itemSel, buttonSel, maxRows }) => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const lim = (typeof maxRows === 'number' && maxRows > 0) ? maxRows : Infinity;
  let iter = 0;
  while (iter++ < 100) {
    const items = document.querySelectorAll(containerSel + ' ' + itemSel);
    if (items.length >= lim) break;
    const btn = document.querySelector(buttonSel);
    if (!btn || btn.offsetParent === null) break;
    btn.scrollIntoView({ behavior: 'smooth', block: 'center' });
    await sleep(500);
    btn.click();
    await sleep(2000);
  }
  window.scrollTo({ top: 0, behavior: 'auto' });
  await sleep(500);
  return document.querySelectorAll(containerSel + ' ' + itemSel).length;
}
"""

def _auto_scroll(page, container_sel, item_sel, max_rows):
    # Pass -1 for infinity (JSON cannot represent JS Infinity)
    return page.evaluate(_AUTO_SCROLL_JS, {
        "containerSel": container_sel, "itemSel": item_sel,
        "maxRows": max_rows if max_rows > 0 else -1
    })

def _load_more(page, container_sel, item_sel, button_sel, max_rows):
    return page.evaluate(_LOAD_MORE_JS, {
        "containerSel": container_sel, "itemSel": item_sel,
        "buttonSel": button_sel,
        "maxRows": max_rows if max_rows > 0 else -1
    })


# ─────────────────────────────────────────────────────────────
# PAGINATION — extracts per-page (mirrors paginationLoad)
# ─────────────────────────────────────────────────────────────
_BUTTON_READY_JS = r"""
sel => {
  const btn = document.querySelector(sel);
  if (!btn) return false;
  if (btn.disabled) return false;
  if (btn.getAttribute('aria-disabled') === 'true') return false;
  if (btn.offsetParent === null) return false;
  return true;
}
"""

def _pagination_load(page, container_sel, item_sel, button_sel, fields, job_id, max_rows):
    all_data = []
    valid_idx = 0
    failed_items = 0
    page_num = 0
    MAX_PAGES = 200
    MAX_CLICK_RETRIES = 3
    print(f"➡️ Pagination | button: {button_sel}")

    while page_num < MAX_PAGES:
        page_num += 1
        print(f"\n📄 Page {page_num}…")
        _jobs_progress[job_id] = {
            "status": "running", "currentPage": page_num, "totalPages": "?",
            "itemsCollected": valid_idx, "failedItems": failed_items, "error": None,
        }

        # Wait for items (3 retries × 10s, with 2s gap)
        items_found = False
        for t in range(3):
            try:
                page.wait_for_selector(f"{container_sel} {item_sel}", timeout=10000)
                items_found = True
                break
            except PWTimeoutError:
                print(f"  ⚠️ Items not found (try {t+1}/3)")
                page.wait_for_timeout(2000)
        if not items_found:
            print("  ❌ Items never appeared, stopping.")
            break

        items = page.query_selector_all(f"{container_sel} {item_sel}")
        print(f"  📊 {len(items)} items")

        for item in items:
            if max_rows > 0 and valid_idx >= max_rows:
                break
            row, has_data = _extract_item_with_retry(item, fields, page, 3)
            if has_data:
                for field in fields:
                    all_data.append({
                        "item_index": valid_idx,
                        "field_name": field["name"],
                        "value": row.get(field["name"], "N/A"),
                    })
                valid_idx += 1
            else:
                failed_items += 1

        print(f"  ✅ Page {page_num} done — {valid_idx} total")
        if max_rows > 0 and valid_idx >= max_rows:
            print(f"  🏁 Row limit of {max_rows} reached.")
            break

        # Next button readiness
        try:
            ready = page.evaluate(_BUTTON_READY_JS, button_sel)
        except Exception as e:
            print(f"  ⚠️ Button-ready check failed: {e}")
            ready = False
        if not ready:
            print("  🏁 No more pages.")
            break

        # Human-like click with retries
        clicked = False
        for attempt in range(1, MAX_CLICK_RETRIES + 1):
            try:
                url_before = page.url
                # Move mouse to a random spot inside the button
                try:
                    box = page.locator(button_sel).bounding_box()
                    if box:
                        x = box["x"] + box["width"] * (0.3 + random.random() * 0.4)
                        y = box["y"] + box["height"] * (0.3 + random.random() * 0.4)
                        steps = int(5 + random.random() * 10)
                        page.mouse.move(x, y, steps=steps)
                        page.wait_for_timeout(int(human_delay_ms(300)))
                except Exception:
                    pass  # bounding_box can fail for off-screen elements; just click

                page.click(button_sel, timeout=5000)
                # Best-effort wait for navigation; AJAX is fine too
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=8000)
                except PWTimeoutError:
                    pass
                page.wait_for_timeout(int(human_delay_ms(1500)))
                clicked = True
                url_after = page.url
                print("  🌐 Navigated" if url_after != url_before else "  ⚡ AJAX")
                break
            except Exception as ce:
                print(f"  ⚠️ Click attempt {attempt}/{MAX_CLICK_RETRIES}: {ce}")
                page.wait_for_timeout(2000 * attempt)
        if not clicked:
            print("  ❌ Could not click Next, stopping.")
            break

    print(f"\n✅ Pagination done — {valid_idx} items, {failed_items} failed, {page_num} pages")
    return {"totalLoaded": valid_idx, "allData": all_data, "failedItems": failed_items}


# ─────────────────────────────────────────────────────────────
# PERSISTENCE — long-format JSON + flat (wide) CSV
# ─────────────────────────────────────────────────────────────
def _save_outputs(job_id, data, fields):
    json_path = OUTPUT_DIR / f"{job_id}.json"
    json_path.write_text(
        json.dumps({"fields": fields, "data": data}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    field_names = [f["name"] for f in fields]
    if data:
        df_long = pd.DataFrame(data)
        # Pivot to wide; keep all field columns even if empty
        try:
            df_wide = df_long.pivot_table(
                index="item_index", columns="field_name", values="value", aggfunc="first"
            )
        except Exception:
            df_wide = df_long.pivot(index="item_index", columns="field_name", values="value")
        # Reorder columns to match the user's selection order
        for fn in field_names:
            if fn not in df_wide.columns:
                df_wide[fn] = ""
        df_wide = df_wide[field_names].reset_index(drop=True)
    else:
        df_wide = pd.DataFrame(columns=field_names)
    csv_path = OUTPUT_DIR / f"{job_id}.csv"
    df_wide.to_csv(csv_path, index=False, encoding="utf-8-sig")
    return json_path, csv_path


def _read_history():
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

def _write_history(hist):
    HISTORY_FILE.write_text(
        json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8"
    )

def _add_history(entry):
    hist = _read_history()
    hist.insert(0, entry)
    if len(hist) > 50:
        hist = hist[:50]
    _write_history(hist)


# ─────────────────────────────────────────────────────────────
# WORKER OPERATIONS (called via _pw_run)
# ─────────────────────────────────────────────────────────────
def _op_open_browser(url, job_id, lang, stealth, proxy):
    pw = _pw_ensure()

    launch_kwargs = {"headless": False, "args": ["--start-maximized"]}
    if proxy and proxy.get("host"):
        proxy_obj = {
            "server": f"{proxy.get('protocol', 'http')}://{proxy['host']}:{proxy.get('port', 8080)}"
        }
        if proxy.get("username"): proxy_obj["username"] = proxy["username"]
        if proxy.get("password"): proxy_obj["password"] = proxy["password"]
        launch_kwargs["proxy"] = proxy_obj

    browser = pw.chromium.launch(**launch_kwargs)
    ctx_kwargs = {"no_viewport": True}  # equivalent to viewport:null in JS
    if stealth:
        ctx_kwargs["user_agent"]  = random_ua()
        ctx_kwargs["locale"]      = "en-US"
        ctx_kwargs["timezone_id"] = "America/New_York"
        ctx_kwargs["extra_http_headers"] = {
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        }
    context = browser.new_context(**ctx_kwargs)
    if stealth:
        context.add_init_script(STEALTH_INIT_SCRIPT)

    page = context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except PWTimeoutError:
        # Page slow but probably still usable; let the user proceed
        print(f"⚠️ Navigation to {url} timed out (DOM may not be fully loaded)")

    # Set lang BEFORE injecting overlay (overlay reads window.basiraLang)
    page.evaluate("l => { window.basiraLang = l || 'en'; }", lang or "en")
    page.add_script_tag(content=OVERLAY_SCRIPT)

    _active_browsers[job_id] = {
        "browser": browser, "context": context, "page": page,
        "stealth": bool(stealth), "start_time": time.time(), "url": url,
    }
    _jobs_progress[job_id] = {
        "status": "idle", "currentPage": 0, "totalPages": "?",
        "itemsCollected": 0, "failedItems": 0, "error": None,
    }
    return {"success": True, "jobId": job_id}


def _op_check_selection(job_id):
    bd = _active_browsers.get(job_id)
    if not bd: return {"pending": True}
    page = bd["page"]
    try:
        if page.is_closed():
            return {"pending": True}
    except Exception:
        return {"pending": True}
    try:
        cancelled = page.evaluate("() => window.basiraSelectionCancelled")
        if cancelled:
            try: bd["browser"].close()
            except Exception: pass
            _active_browsers.pop(job_id, None)
            return {"cancelled": True}
        results = page.evaluate("() => window.basiraResults")
        if results:
            return {"completed": True, "results": results}
        return {"pending": True}
    except Exception as e:
        # Page may be navigating mid-eval — treat as still pending
        return {"pending": True}


def _op_extract_data(job_id, row_limit):
    bd = _active_browsers.get(job_id)
    if not bd:
        return {"error": "Browser session not found", "_status": 404}

    page = bd["page"]
    sel = page.evaluate("() => window.basiraResults")
    if not sel:
        return {"error": "No selection found in page", "_status": 400}

    fields            = sel.get("fields", [])
    parent_selector   = sel["parentSelector"]
    item_selector     = sel["itemSelector"]
    loading_method    = sel.get("loadingMethod", "auto-scroll")
    pagination_sel    = sel.get("paginationSelector")
    load_more_sel     = sel.get("loadMoreSelector")
    max_rows = int(row_limit) if row_limit and int(row_limit) > 0 else 0  # 0 = unlimited

    print(f"Container: {parent_selector} | Item: {item_selector} "
          f"| Method: {loading_method} | Limit: {max_rows or '∞'}")
    _jobs_progress[job_id] = {
        "status": "running", "currentPage": 1, "totalPages": "?",
        "itemsCollected": 0, "failedItems": 0, "error": None,
    }

    data = []
    valid_idx = 0
    failed_items = 0

    if loading_method == "pagination" and pagination_sel:
        result = _pagination_load(
            page, parent_selector, item_selector, pagination_sel, fields, job_id, max_rows
        )
        data = result["allData"]
        valid_idx = result["totalLoaded"]
        failed_items = result["failedItems"]
    else:
        if loading_method == "auto-scroll":
            _auto_scroll(page, parent_selector, item_selector, max_rows)
        elif loading_method == "load-more" and load_more_sel:
            _load_more(page, parent_selector, item_selector, load_more_sel, max_rows)

        items = page.query_selector_all(f"{parent_selector} {item_selector}")
        limited = items[:max_rows] if max_rows > 0 else items
        print(f"Extracting from {len(limited)} items (limit: {max_rows or '∞'})…")
        _jobs_progress[job_id] = {
            "status": "running", "currentPage": 1, "totalPages": 1,
            "itemsCollected": 0, "failedItems": 0, "error": None,
        }
        for i, item in enumerate(limited):
            row, has_data = _extract_item_with_retry(item, fields, page, 3)
            if has_data:
                for field in fields:
                    data.append({
                        "item_index": valid_idx,
                        "field_name": field["name"],
                        "value": row.get(field["name"], "N/A"),
                    })
                valid_idx += 1
            else:
                failed_items += 1
            if i % 10 == 0:
                p = _jobs_progress.get(job_id, {})
                _jobs_progress[job_id] = {
                    **p, "itemsCollected": valid_idx, "failedItems": failed_items
                }

    _jobs_progress[job_id] = {
        "status": "done", "currentPage": 0, "totalPages": 0,
        "itemsCollected": valid_idx, "failedItems": failed_items, "error": None,
    }
    print(f"✅ Extracted {valid_idx} items, {failed_items} failed")

    _jobs_data[job_id]   = data
    _jobs_fields[job_id] = fields

    # Persist long JSON + flat CSV
    try:
        json_path, csv_path = _save_outputs(job_id, data, fields)
        print(f"💾 Saved {json_path.name} and {csv_path.name}")
    except Exception as we:
        print(f"⚠️ Persistence failed: {we}")

    # History
    try:
        duration = round(time.time() - bd.get("start_time", time.time()))
        url = bd.get("url", "")
        try: hostname = urlparse(url).hostname or url
        except Exception: hostname = url
        _add_history({
            "id": job_id, "url": url, "hostname": hostname,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rows": valid_idx, "failedItems": failed_items, "fields": fields,
            "loadingMethod": loading_method, "duration": duration,
        })
    except Exception as he:
        print(f"⚠️ History save failed: {he}")

    # Close the visible browser
    try:
        bd["browser"].close()
    except Exception: pass
    _active_browsers.pop(job_id, None)

    return {"success": True, "itemsScraped": valid_idx,
            "failedItems": failed_items, "fields": fields}


# ─────────────────────────────────────────────────────────────
# FLASK APP + ROUTES
# ─────────────────────────────────────────────────────────────
app = Flask(__name__)

# CORS — same pattern as basira_app.py so the HTML pages can call us
@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"]  = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return resp

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "basira-scraper",
        "version": "1.0",
        "active_jobs": len(_active_browsers),
        "history_size": len(_read_history()),
    })

@app.route("/open-browser", methods=["POST", "OPTIONS"])
def open_browser():
    if request.method == "OPTIONS": return ("", 200)
    body = request.get_json(force=True, silent=True) or {}
    url     = body.get("url")
    job_id  = body.get("jobId") or f"job-{int(time.time()*1000)}"
    lang    = body.get("lang", "en")
    stealth = bool(body.get("stealth", False))   # default off, per Stage 1A spec
    proxy   = body.get("proxy")
    if not url:
        return jsonify({"error": "url is required"}), 400
    try:
        result = _pw_run(_op_open_browser, url, job_id, lang, stealth, proxy)
        return jsonify(result)
    except Exception as e:
        import traceback as tb
        return jsonify({"error": str(e), "traceback": tb.format_exc()}), 500

@app.route("/check-selection", methods=["GET"])
def check_selection():
    job_id = request.args.get("jobId")
    if not job_id:
        return jsonify({"error": "jobId is required"}), 400
    try:
        return jsonify(_pw_run(_op_check_selection, job_id))
    except Exception as e:
        return jsonify({"pending": True, "error": str(e)})

@app.route("/get-progress", methods=["GET"])
def get_progress():
    # Pure dict read — does NOT go through the Playwright worker
    job_id = request.args.get("jobId")
    if not job_id:
        return jsonify({"error": "jobId is required"}), 400
    return jsonify(_jobs_progress.get(job_id, {"status": "idle"}))

@app.route("/extract-data", methods=["POST", "OPTIONS"])
def extract_data():
    if request.method == "OPTIONS": return ("", 200)
    body = request.get_json(force=True, silent=True) or {}
    job_id    = body.get("jobId")
    row_limit = body.get("rowLimit", 0)
    if not job_id:
        return jsonify({"error": "jobId is required"}), 400
    try:
        result = _pw_run(_op_extract_data, job_id, row_limit)
        if "_status" in result:
            return jsonify({"error": result["error"]}), result["_status"]
        return jsonify(result)
    except Exception as e:
        import traceback as tb
        p = _jobs_progress.get(job_id, {})
        _jobs_progress[job_id] = {**p, "status": "error", "error": str(e)}
        return jsonify({"error": str(e), "traceback": tb.format_exc()}), 500

@app.route("/get-data", methods=["GET"])
def get_data():
    job_id = request.args.get("jobId")
    if not job_id:
        return jsonify({"error": "jobId is required"}), 400
    # Memory first
    data   = _jobs_data.get(job_id)
    fields = _jobs_fields.get(job_id)
    if data is None:
        # Disk fallback
        json_path = OUTPUT_DIR / f"{job_id}.json"
        if json_path.exists():
            try:
                payload = json.loads(json_path.read_text(encoding="utf-8"))
                data   = payload.get("data")
                fields = payload.get("fields")
            except Exception:
                pass
    if data is None:
        return jsonify({"error": "Data not found"}), 404
    return jsonify({"success": True, "data": data, "fields": fields})

@app.route("/history", methods=["GET"])
def history():
    return jsonify({"success": True, "history": _read_history()})

@app.route("/send-to-preprocessor", methods=["POST", "OPTIONS"])
def send_to_preprocessor():
    if request.method == "OPTIONS": return ("", 200)
    body = request.get_json(force=True, silent=True) or {}
    job_id = body.get("jobId")
    if not job_id:
        return jsonify({"error": "jobId is required"}), 400

    csv_path = OUTPUT_DIR / f"{job_id}.csv"
    if not csv_path.exists():
        return jsonify({"error": f"No CSV for job {job_id}"}), 404

    try:
        with csv_path.open("rb") as f:
            files = {"file": (csv_path.name, f, "text/csv")}
            r = requests.post(PREPROCESSOR_URL, files=files, timeout=300)
        try:
            payload = r.json()
        except ValueError:
            payload = {"error": "Preprocessor returned non-JSON", "body": r.text[:500]}
        return jsonify({
            "success":          r.ok,
            "preprocessor_url": PREPROCESSOR_URL,
            "status_code":      r.status_code,
            "result":           payload,
            "csv_sent":         csv_path.name,
        }), (200 if r.ok else 502)
    except requests.exceptions.ConnectionError:
        return jsonify({
            "error": "Could not connect to preprocessor at localhost:5050. "
                     "Is basira_app.py running?",
            "csv_path": str(csv_path),
        }), 503
    except Exception as e:
        return jsonify({"error": str(e), "csv_path": str(csv_path)}), 500


# ─────────────────────────────────────────────────────────────
# CLEANUP ON EXIT
# ─────────────────────────────────────────────────────────────
def _cleanup():
    for jid, bd in list(_active_browsers.items()):
        try: bd["browser"].close()
        except Exception: pass
        _active_browsers.pop(jid, None)
    global _playwright
    if _playwright is not None:
        try: _playwright.stop()
        except Exception: pass
        _playwright = None
atexit.register(_cleanup)


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🕸  Basira Scraper v1.0 — http://localhost:5051")
    print(f"   Output dir : {OUTPUT_DIR}")
    print(f"   History    : {HISTORY_FILE}")
    print(f"   Preprocessor target: {PREPROCESSOR_URL}")
    # threaded=True so /get-progress can answer while /extract-data is blocking
    # the Playwright worker thread. debug=False — the reloader breaks the
    # ThreadPoolExecutor's worker thread on each reload.
    app.run(host="0.0.0.0", port=5051, debug=False, threaded=True)
