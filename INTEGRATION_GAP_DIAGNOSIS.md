# Integration Gap Diagnosis — Phase 3 endpoint trace
_Investigation 2026-05-10. No code modified._

---

## TL;DR

**Both bugs share one root cause: the HTML never walks past `/open-browser`.**

Phase 3 wired the entry-point card to `POST /open-browser` and stops there. After that:

- The overlay's "Extract" button **does not extract**. It only sets `window.basiraResults` (a CSS-selector spec) and shows a "Ready!" splash. The actual scrape needs `POST /extract-data` to run, and **nobody calls it**.
- Even if the scrape ran, `POST /send-to-preprocessor` would still need to be invoked to push the CSV to the engine, and **nobody calls that either**.
- The engine HTML has zero listener / poller / message-bus to receive data from outside, so even an out-of-band push wouldn't surface in the UI.

The "missing row-count selector" turns out to be a different artifact: it never existed in the Python scraper. It existed in the Next.js scraper iteration (`_archive/scraper/basira-scraper/`) as a small number input next to the URL field. The Python scraper's **backend** already accepts `rowLimit`; only the **UI** for it was never carried over.

---

## 1. `/send-to-preprocessor` — what it sends to the engine

`basira-scraper/basira_scraper.py:710–738`

```python
@app.route("/send-to-preprocessor", methods=["POST", "OPTIONS"])
def send_to_preprocessor():
    body = request.get_json(...)
    job_id = body.get("jobId")
    csv_path = OUTPUT_DIR / f"{job_id}.csv"
    if not csv_path.exists():
        return jsonify({"error": f"No CSV for job {job_id}"}), 404
    with csv_path.open("rb") as f:
        files = {"file": (csv_path.name, f, "text/csv")}
        r = requests.post(PREPROCESSOR_URL, files=files, timeout=300)
    payload = r.json()
    return jsonify({
        "success":          r.ok,
        "preprocessor_url": PREPROCESSOR_URL,
        "status_code":      r.status_code,
        "result":           payload,    # ← full engine response
        "csv_sent":         csv_path.name,
    }), (200 if r.ok else 502)
```

- **Method**: `POST`
- **Body**: JSON `{"jobId": "..."}` — only the jobId. The CSV must already exist on disk at `OUTPUT_DIR/<jobId>.csv` (written by `/extract-data`).
- **What it sends to the engine**: `multipart/form-data` POST with field name **`file`**, mimetype `text/csv`. The CSV body is read from disk.
- **What it returns**: a wrapper JSON containing the engine's full response under `result`. Wraps the engine's HTTP code in `status_code`. Returns 200 on engine success, 502 on engine error, 503 if the engine isn't running, 404 if the scraped CSV doesn't exist.

This is good news: the scraper already returns the engine's full preprocessing result. **No engine-side changes are needed** to make scraped data flow into the same UI as uploaded data.

---

## 2. `/upload-process` on the engine — does it accept programmatic POSTs?

`basira-engine/basira_app.py:1192–1278`

```python
@app.route("/upload-process", methods=["POST"])
def upload_process():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file  = request.files["file"]
    ...
    return jsonify({
        "status": "ok",
        "task_type": ...,
        "target_col": ...,
        "summary": ...,
        "col_meta": ...,
        "audit": ...,
        "preview": ...,
        "downloads": {...},
    })
```

- ✅ **Yes, it's a fully programmatic API.** Pure JSON in/out, no redirects, no HTML responses, no session cookies, no CSRF. Wildcard CORS via `add_cors`. OPTIONS preflight handled separately at line 1181.
- ✅ The shape it accepts is exactly what the scraper sends (multipart with field name `file`, .csv/.xlsx/.xls).
- ✅ The shape it returns is exactly what `renderResults()` in the HTML already consumes (the dropzone path uses the same endpoint and the same render function).

**Implication:** The engine side is already correct. If the HTML can get back the same JSON the dropzone gets, it can call its existing `renderResults()` and the rest "just works."

---

## 3. The overlay's "Extract" button — what it actually does

`basira-scraper/basira_overlay.js:988–1018`

```js
function extract() {
    var itemSelector = ...;
    var containerSelector = ...;
    window.basiraResults = {
        parentSelector: containerSelector,
        itemSelector:   itemSelector,
        loadingMethod:  loadingMethod,
        paginationSelector: paginationButton ? paginationButton.selector : null,
        loadMoreSelector:   loadMoreButton ? loadMoreButton.selector : null,
        fields: selectedFields.map(function(f){
            return {name:f.name, selector:f.selector, sample:f.sample, type: f.type || 'text'};
        })
    };
    var panel = document.getElementById('basira-panel');
    panel.innerHTML = '<div ...>...<h3>Ready!</h3>...</div>';
}
```

- ❌ The button **does not extract data**, **does not open a tab**, **does not call any URL**, **does not show a "Send" button**. It just sets a JS global on `window` and paints a "Ready!" splash. That's exactly the "ready" state the user reported.
- The overlay JS contains **zero `fetch()` / XHR calls** anywhere (`grep -nE 'fetch\(|XMLHttpRequest' basira_overlay.js` → empty). All cross-process talk happens through Playwright reading `window.basiraResults` from the OS thread that owns the browser.

So the overlay is doing its job (capturing selectors), but it's only step 1 of 3. The next two steps (`/extract-data` then `/send-to-preprocessor`) need an external orchestrator. Today there is none.

---

## 4. Current overlay vs archived overlay — diff result

```
$ diff -q basira-scraper/basira_overlay.js _archive/scraper/Basira-local-leftovers/basira_overlay.js
(no output — files are identical)
$ md5 -q both files → 2971b265a88a1a72f2a0f5a5a0502086 in both
```

**The current overlay is byte-identical to the archived one.** Phase 2 didn't drop anything from the Python-port lineage.

The "row-count selector" the user remembers belongs to a **different scraper iteration** — the older **Next.js** scraper at `_archive/scraper/basira-scraper/`. It's a small `<input type="number">` rendered in `pages/index.js:419`:

```jsx
<input className="bs-input bs-input-sm" type="number"
       placeholder={t.maxRows} min="1" value={rowLimit}
       onChange={e => { setRowLimit(e.target.value); ... }}
       style={{ width: 110, textAlign: 'center' }} />
```

It was placed inline next to the URL input. The React state was passed all the way through to `/api/scraper?action=extract-data` as `{ jobId, rowLimit }` (`pages/index.js:599`).

**Backend support today**: the Python scraper's `/extract-data` already reads `rowLimit` (`basira_scraper.py:670`):

```python
row_limit = body.get("rowLimit", 0)   # 0 = unlimited
result = _pw_run(_op_extract_data, job_id, row_limit)
```

So we have a backend-ready feature with no UI. Adding the input is a one-line modal field.

---

## 5. Engine HTML — any logic to receive scraped data?

`basira-engine/basira_preprocessor.html`

```
$ grep -nE 'postMessage|addEventListener.*message|URLSearchParams|polling|setInterval|location\.search'
(zero matches)
$ grep -nE 'fromScraper|scraper.*receive|jobId|preFilledFile'
(zero matches outside the Phase-3 scraper-modal CSS)
```

❌ Zero receiver logic of any kind. No `postMessage`, no polling, no URL-param parsing, no jobId tracking. The HTML treats the dropzone as the only way data arrives. Phase 3 is fire-and-forget — `launchScraper()` shows "Chromium will open shortly", closes the modal after 3.5 seconds, and doesn't track the jobId past that point.

---

## Actual data flow today

```
Browser (engine HTML on file:// or :5050)
  │
  │  click "no data? no problem"
  ├──► open modal
  │
  │  click 🚀 Launch Chromium
  ├──► POST :5051/open-browser  {"url":"…"}            ✅ works
  │     │
  │     ◀── 200 {"jobId":"…","success":true}            (HTML drops jobId on the floor)
  │
  ├──► show "Chromium will open shortly", close modal   ✅ works
  │
  │
  Chromium window
  │
  │  user clicks one item → SHIFT-clicks each field → "Extract"
  ├──► overlay extract():
  │     window.basiraResults = {…}                       ✅ works
  │     paint "Ready!" splash                            ✅ works
  │
  │
  ❌ NOTHING calls   :5051/check-selection?jobId=…
  ❌ NOTHING calls   :5051/extract-data       {jobId,rowLimit}
  ❌ NOTHING calls   :5051/send-to-preprocessor {jobId}
  ❌ HTML has no listener even if the chain ran out-of-band
  │
  ▼
END.  User sees "Ready!" in Chromium, no further progress.
       basira_preprocessor.html still shows the empty dropzone.
```

This matches the user report exactly: launched ✓ → selected ✓ → "ready" ✓ → nothing → nothing.

---

## Proposed end-to-end flow

The simplest cohesive plan: **the engine HTML drives the whole chain from the user's browser**. Backend already supports every step.

```
HTML (in browser)                    SCRAPER :5051                ENGINE :5050
─────────────────                    ─────────────                ────────────

modal: enter URL + rowLimit
  │
  │   POST /open-browser             ───►
  │     {url, jobId?}                                              (engine idle)
  │   ◀── {jobId, success:true}      ◄───
  │
  │   modal switches to:
  │   "Chromium opened — pick fields,
  │    then click Extract."
  │
  │   start poll loop, every ~1.5 s
  │   GET /check-selection?jobId=…   ───►
  │   ◀── {pending: true}            ◄───   (until overlay sets window.basiraResults)
  │   ...
  │   ◀── {ready: true, fields: […]} ◄───
  │
  │   modal switches to:
  │   "Extracting…" with progress bar
  │
  │   POST /extract-data             ───►
  │     {jobId, rowLimit}                  scraper drives the
  │                                        Playwright scrape
  │   (in parallel)
  │   GET /get-progress?jobId=…      ───►
  │   ◀── {currentPage,total,…}      ◄───  (live progress for the bar)
  │   ...
  │   ◀── extract response           ◄───  (CSV is now on disk)
  │
  │   POST /send-to-preprocessor     ───►
  │     {jobId}                            scraper reads CSV,
  │                                        POSTs multipart to ─►   /upload-process
  │                                                                runs preprocess()
  │                                        ◄── full result JSON ◄──
  │   ◀── {success, result:{…}}      ◄───
  │
  │   call existing renderResults(result)
  │   → table, audit log, downloads, everything the dropzone path
  │     already produces.
```

Notable: nothing about this requires touching the engine. The engine HTML just learns to be the orchestrator, and the existing `renderResults()` consumes the same JSON shape it already consumes for uploaded files.

---

## Prioritized fix plan

### Must-fix for end-to-end (the core bug)

1. **HTML — capture `jobId` from `/open-browser`** and stash it. Today the response is discarded.
2. **HTML — poll `/check-selection?jobId=…`** every ~1.5s after Chromium opens. Show "Pick your fields in Chromium…" state in the modal. Stop polling on response shape that signals ready (need to verify exact key — likely `pending:false` or presence of `fields`).
3. **HTML — on ready, call `POST /extract-data`** with `{jobId, rowLimit}`. Switch modal to "Extracting…" state. Optionally poll `/get-progress` for live page/item counts.
4. **HTML — on `/extract-data` success, call `POST /send-to-preprocessor`** with `{jobId}`. Await its response.
5. **HTML — pass the `result` field of that response to the existing `renderResults()`** — that's the same shape the dropzone already consumes; no other UI work needed.
6. **HTML — add a row-count `<input type="number" min="1">`** next to the URL field in the modal. Empty = unlimited. Pass through as `rowLimit` in step 3.

### Nice-to-have (UX polish, not blocking)

7. **Modal — live progress in step 3** (currentPage/totalPages/itemsCollected from `/get-progress`).
8. **Modal — clear status panes** for the four stages: launched / picking / extracting / sending. Use the existing pill/progress widgets in the HTML for visual continuity with the upload flow.
9. **HTML — show data origin badge** post-render ("Scraped from `<url>` — N rows × M cols on `<date>`") so the audit story stays clear.
10. **HTML — input validation**: positive integer only, or empty.
11. **Error path** — surface `/get-progress` error fields and `/send-to-preprocessor` 502/503 distinctions in the modal (engine down vs scraper crashed vs CSV missing).
12. **Overlay — explicit "Send to Basira" button** before Extract commits, so users can reconsider their selection. Not blocking — current "Extract → Ready" works, just less reversible.
13. **Cleanup endpoint** — `POST /close-browser` on the scraper so the modal can stop the Chromium process if the user cancels mid-flow. Today, closing the modal leaves Chromium running.

### Out of scope but worth flagging

- The Phase 3 commit message claimed "test passed" — strictly true (Chromium opened with overlay), but the test stopped before the chain that would actually deliver data. A future Phase verification should curl `/check-selection` → `/extract-data` → `/send-to-preprocessor` against a live scrape, not just confirm that Chromium boots.
- The user's "ready" message appears in the overlay panel itself (`<h3>Ready!</h3>` — `basira_overlay.js:1018`), not in the engine HTML. The HTML never sees it. That mismatch contributed to the user's expectation that data should appear automatically.

---

## State of the working tree

No code modified. No commits. The diagnosis lives in this file. Awaiting your fix-by-fix approval before any change to `basira_preprocessor.html`.
