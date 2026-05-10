# How to launch Basira

## TL;DR

Double-click **`Basira.command`** at the root of `Basira-Workspace/`.
That's it. The launcher starts both servers, opens the UI in your
browser, and shuts everything down cleanly when you close the
Terminal window.

---

## Where to find the launcher

```
~/Desktop/Basira-Workspace/
├── Basira.command          ← double-click to start
├── basira-engine/
├── basira-scraper/
├── docs/
│   └── HOW_TO_LAUNCH.md    ← (you are here)
├── logs/                   ← created on first launch
│   ├── engine.log
│   └── scraper.log
└── ...
```

---

## First launch — bypass macOS Gatekeeper

The first time you double-click `Basira.command`, macOS may refuse
with a dialog like:

> **"Basira.command" cannot be opened because it is from an
> unidentified developer.**

Workaround (one-time, per machine):

1. **Right-click** `Basira.command` in Finder.
2. Choose **Open** from the context menu.
3. Click **Open** in the confirmation dialog.

After that, plain double-click works normally.

---

## What happens when you launch

A Terminal window opens and shows:

```
╔══════════════════════════════════╗
║   🕷️  BASIRA                     ║
║   Intelligent Data Preprocessor  ║
║   v1.0                           ║
╚══════════════════════════════════╝

Checking environment...
  ✓ Python 3 found (Python 3.13.5)
  ✓ basira-engine/.venv exists
  ✓ basira-scraper/.venv exists
  ✓ entry-point files present

Checking ports...
  ✓ ports 5050 and 5051 ready

Starting servers...
  Engine  PID 12345  → logs/engine.log
  Scraper PID 12346  → logs/scraper.log

Waiting for both services... ready
  ✓ Engine  ready on http://localhost:5050
  ✓ Scraper ready on http://localhost:5051

Opening Basira UI in your default browser...
  → file:///Users/.../basira-engine/basira_preprocessor.html

Basira is running. Press Ctrl+C or close this window to stop.
─────── live server logs (engine + scraper) ───────
```

Your browser opens to the Basira preprocessor UI. The Terminal
window keeps running with a live log tail of both servers.

---

## How to stop

Either:

- Press **Ctrl+C** in the Terminal window, or
- Close the Terminal window.

Both servers shut down cleanly via the launcher's exit trap. Any
leftover Chromium windows (from the scraper) are NOT auto-closed —
close them yourself when you're done.

---

## Troubleshooting

### "Port 5050 is in use" / "Port 5051 is in use"

Another Basira instance — or another app — is already bound to that
port. The launcher will ask:

```
! Port 5050 already in use by PID 9876 (python3.13) — needed for the engine.
  Kill PID 9876 and continue? [y/N]
```

Type **`y`** and press Enter to take over the port, or **`n`** to abort
and stop the conflicting process yourself.

### "Engine venv not found at basira-engine/.venv"

You haven't installed the engine dependencies yet. The launcher
prints the exact fix:

```bash
cd basira-engine
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### "Scraper venv not found at basira-scraper/.venv"

Same idea, plus the Playwright browser binary:

```bash
cd basira-scraper
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
```

### "Servers failed to start within 30 seconds"

The launcher prints the last lines of both log files before exiting.
Full logs live at:

```
logs/engine.log
logs/scraper.log
```

Common causes:

- **Python version mismatch** — basira-engine needs 3.10+
- **Stale venv** — delete `.venv/` and re-create it (steps above)
- **Port still occupied** — check with `lsof -i :5050` and `lsof -i :5051`

### Browser didn't open

The launcher uses macOS's `open` command on the path to
`basira_preprocessor.html`. The full path is printed on screen — paste
it into your browser's address bar manually if needed:

```
file:///Users/<you>/Desktop/Basira-Workspace/basira-engine/basira_preprocessor.html
```

### "Python 3 is not installed"

Install from <https://www.python.org/downloads/> (3.10 or newer).
After installation, re-run the launcher.

---

## What the launcher does NOT do

- Does not install dependencies for you. Run `pip install -r
  requirements.txt` and `playwright install chromium` yourself before
  the first launch.
- Does not auto-update the code (no `git pull`).
- Does not open Chromium for the scraper — that happens later, only
  when you click "no data? no problem" in the UI.
- Does not close Chromium windows that the scraper opened during a
  session. Close them manually.
