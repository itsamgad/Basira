# How to launch Basira

## Supported platforms

| Platform | First-time setup | Daily launcher | Bundled app |
|---|---|---|---|
| **macOS** (11+) | manual venv setup (see "macOS — first-time install" below) | `Basira.command` | `Basira.app` (drag to /Applications) |
| **Windows** (10+) | `setup.bat` (one-time, ~5 min) | `Basira.bat` | not bundled — `Basira.bat` is the daily entry point |

Both platforms run the **same Python backend** (`basira-engine/`,
`basira-scraper/`). Only the launcher scripts differ. Venvs and the
Playwright browser binary are platform-specific, so a workspace
copied between a Mac and a Windows machine needs `setup.bat` (or
the macOS equivalent steps) to be run again on the new machine.

---

## Running on Windows

### First-time setup (one-time, ~5 minutes)

1. Make sure **Python 3.10+** is installed.
   - Download from <https://www.python.org/downloads/>.
   - **Check the box "Add Python to PATH"** during install.
2. Open the `Basira-Workspace` folder in File Explorer.
3. **Double-click `setup.bat`**.

A console window opens and runs:

```
+----------------------------------+
|   Basira -- First-Time Setup     |
+----------------------------------+

Using Python 3.13.x
[1/4] Creating engine venv...
[2/4] Installing engine dependencies (numpy, pandas, sklearn, ...)...
[3/4] Creating scraper venv...
[4/4] Installing scraper deps + Playwright Chromium (~150 MB)...
====================================
   [OK] Setup complete.
====================================
```

When you see `Setup complete.`, close the window.

### Daily use

**Double-click `Basira.bat`** at the workspace root. The launcher will:

- Verify Python and both venvs are present
- Free ports 5050 / 5051 (asks before killing anything)
- Start the engine and scraper in minimized console windows
- Wait up to 30 s for `/health` on both
- Open the preprocessor UI in your default browser
- Stay open so you can see status

When you're done, **press any key in the launcher window** to stop both
servers. (Closing the window with the X button leaves the servers
running — see "Windows shutdown notes" below.)

### Windows shutdown notes

CMD has no equivalent of macOS's `trap EXIT`, so closing the launcher
with the X button bypasses cleanup. To recover:

- Open **Task Manager** → **Details** tab → end the two `python.exe`
  processes, **or**
- Run this one-liner in any cmd prompt:
  ```
  for /f "tokens=5" %a in ('netstat -ano ^| findstr :5050 :5051 ^| findstr LISTENING') do taskkill /F /PID %a
  ```

### Windows troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `'python' is not recognized` | Python not on PATH | Reinstall Python with the **Add Python to PATH** checkbox |
| `Engine venv not found at basira-engine\.venv` | setup.bat hasn't run | Double-click `setup.bat` once |
| `Servers did not become healthy within 30 seconds` | Inspect `logs\engine.log` and `logs\scraper.log` — last 10 lines are echoed automatically before the launcher exits | |
| Browser didn't open | Default browser not set, or path has weird characters | Paste `file:///<workspace>/basira-engine/basira_preprocessor.html` (with forward slashes) into your browser bar manually |
| Windows SmartScreen warning | First run of unsigned `.bat` | Click **More info** → **Run anyway** |

---

## macOS — first-time install

If you've just copied Basira-Workspace fresh to a Mac and the venvs
don't exist yet:

```bash
cd basira-engine
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd ../basira-scraper
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
```

(There's no `setup.command` equivalent yet — the venv setup is a
one-liner per project, run once.)

---

## Two ways to launch Basira on macOS

| | Option A — Basira.app (recommended) | Option B — Basira.command |
|---|---|---|
| Where it lives | drag to `/Applications`, launch from Launchpad/Spotlight | stays in `Basira-Workspace/`, double-click in Finder |
| What it looks like | a real Mac app with a custom spider icon | a Terminal window opens directly |
| What it does under the hood | spawns the same Terminal window via AppleScript and runs Basira.command for you | runs the same shell script directly |
| First-time Gatekeeper bypass | **right-click → Open** the first time (one-time per machine) | **right-click → Open** the first time (one-time per machine) |
| Shutdown | close the Terminal window (or Ctrl+C inside it) | close the Terminal window (or Ctrl+C inside it) |
| Pick this when | you want Basira to feel like any other Mac app | you'd rather not move anything; you live in Finder |

Both paths boot the engine on `:5050`, the scraper on `:5051`, open the
preprocessor UI in your default browser, and stream live logs from
`logs/engine.log` + `logs/scraper.log` until you stop it.

To install the app: drag **`Basira.app`** from `Basira-Workspace/` into
`/Applications/`. From then on it shows up in Launchpad and Spotlight
search like any Mac application.

## TL;DR

Double-click **`Basira.app`** (after installing) — or **`Basira.command`**
in the workspace folder. The launcher starts both servers, opens the UI
in your browser, and shuts everything down cleanly when you close the
Terminal window.

---

## Where to find the launchers

```
~/Desktop/Basira-Workspace/
├── Basira.app/             ← drag to /Applications, launch from Launchpad
├── Basira.command          ← double-click directly (technical, shows logs faster)
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

The first time you launch — whether via `Basira.app` or
`Basira.command` — macOS may refuse with a dialog like:

> **"Basira.app" cannot be opened because it is from an
> unidentified developer.**

Workaround (one-time, per machine, per file):

1. **Right-click** `Basira.app` (or `Basira.command`) in Finder.
2. Choose **Open** from the context menu.
3. Click **Open** in the confirmation dialog.

After that, plain double-click works normally for that file.

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
