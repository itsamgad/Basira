#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Basira.command — double-clickable launcher for Basira on macOS
#
# Double-click this file in Finder to launch Basira. The launcher will:
#   1. Verify Python 3 + both venvs + entry-point files
#   2. Free ports 5050 and 5051 (asks before killing anything)
#   3. Start the engine (5050) and the scraper (5051)
#   4. Wait up to 30 seconds for /health on both
#   5. Open the Basira preprocessor UI in your default browser
#   6. Tail the live server logs until you Ctrl+C or close the window
#
# First time only: macOS Gatekeeper may refuse to run an unsigned
# .command file. Right-click this file in Finder → Open → confirm.
# After that, double-click works normally.
#
# Stop with Ctrl+C or by closing the Terminal window — both servers
# shut down cleanly via the EXIT trap.
# ─────────────────────────────────────────────────────────────────────

set -u

# Resolve paths relative to this script regardless of cwd
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd -P )"
cd "$SCRIPT_DIR"

ENGINE_DIR="$SCRIPT_DIR/basira-engine"
SCRAPER_DIR="$SCRIPT_DIR/basira-scraper"
LOGS_DIR="$SCRIPT_DIR/logs"
ENGINE_PORT=5050
SCRAPER_PORT=5051

ENGINE_PID=""
SCRAPER_PID=""
SHUTDOWN_DONE=0

# Colors only when stdout is a TTY
if [ -t 1 ]; then
    BOLD=$'\033[1m'   ; RESET=$'\033[0m'
    GREEN=$'\033[0;32m' ; RED=$'\033[0;31m'
    YELLOW=$'\033[0;33m' ; CYAN=$'\033[0;36m'
else
    BOLD='' ; RESET='' ; GREEN='' ; RED='' ; YELLOW='' ; CYAN=''
fi

# ── Header ─────────────────────────────────────────────────────────
clear
echo
echo "${CYAN}╔══════════════════════════════════╗${RESET}"
echo "${CYAN}║${RESET}   🕷️  ${BOLD}BASIRA${RESET}                     ${CYAN}║${RESET}"
echo "${CYAN}║${RESET}   Intelligent Data Preprocessor  ${CYAN}║${RESET}"
echo "${CYAN}║${RESET}   v1.0                           ${CYAN}║${RESET}"
echo "${CYAN}╚══════════════════════════════════╝${RESET}"
echo

# ── Helpers ────────────────────────────────────────────────────────
die() {
    echo
    echo "${RED}✗ ${BOLD}Error:${RESET} ${RED}$1${RESET}" >&2
    if [ $# -ge 2 ] && [ -n "$2" ]; then
        echo
        echo "${YELLOW}Fix:${RESET}"
        printf '  %s\n' "$2"
    fi
    echo
    echo "Press Enter to close this window..."
    read -r _ || true
    exit 1
}

# ── 1) Environment checks ──────────────────────────────────────────
echo "${BOLD}Checking environment...${RESET}"

if ! command -v python3 >/dev/null 2>&1; then
    die "Python 3 is not installed." \
        "Install Python 3.10+ from https://www.python.org/downloads/"
fi

if [ ! -d "$ENGINE_DIR/.venv" ]; then
    die "Engine venv not found at basira-engine/.venv" \
        "cd basira-engine && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
fi

if [ ! -d "$SCRAPER_DIR/.venv" ]; then
    die "Scraper venv not found at basira-scraper/.venv" \
        "cd basira-scraper && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/playwright install chromium"
fi

if [ ! -f "$ENGINE_DIR/basira_app.py" ]; then
    die "basira-engine/basira_app.py is missing." \
        "Make sure you're running this launcher from the Basira-Workspace folder."
fi

if [ ! -f "$SCRAPER_DIR/basira_scraper.py" ]; then
    die "basira-scraper/basira_scraper.py is missing." \
        "Make sure you're running this launcher from the Basira-Workspace folder."
fi

if [ ! -f "$ENGINE_DIR/basira_preprocessor.html" ]; then
    die "basira-engine/basira_preprocessor.html is missing." \
        "The HTML UI is required — make sure the workspace is intact."
fi

PY_VER="$(python3 --version 2>&1)"
echo "  ${GREEN}✓${RESET} Python 3 found ($PY_VER)"
echo "  ${GREEN}✓${RESET} basira-engine/.venv exists"
echo "  ${GREEN}✓${RESET} basira-scraper/.venv exists"
echo "  ${GREEN}✓${RESET} entry-point files present"
echo

# ── 2) Port checks ─────────────────────────────────────────────────
free_port_or_ask() {
    local port="$1"
    local label="$2"
    local pid
    pid=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1)
    [ -z "$pid" ] && return 0

    local proc
    proc=$(ps -p "$pid" -o comm= 2>/dev/null | tr -d ' ')
    echo "${YELLOW}!${RESET} Port $port already in use by PID $pid (${proc:-unknown}) — needed for the $label."
    printf "  Kill PID $pid and continue? [y/N] "
    local reply
    read -r reply
    case "$reply" in
        [yY]|[yY][eE][sS])
            kill "$pid" 2>/dev/null
            sleep 1
            if kill -0 "$pid" 2>/dev/null; then
                kill -9 "$pid" 2>/dev/null
                sleep 1
            fi
            if kill -0 "$pid" 2>/dev/null; then
                die "Could not kill PID $pid." \
                    "Stop the process manually, then re-run Basira.command."
            fi
            echo "  ${GREEN}✓${RESET} freed port $port"
            ;;
        *)
            die "Port $port still in use — aborting." \
                "Stop the existing process or close the other Basira launcher window, then re-run."
            ;;
    esac
}

echo "${BOLD}Checking ports...${RESET}"
free_port_or_ask "$ENGINE_PORT"  "engine"
free_port_or_ask "$SCRAPER_PORT" "scraper"
echo "  ${GREEN}✓${RESET} ports $ENGINE_PORT and $SCRAPER_PORT ready"
echo

# ── 3) Cleanup trap (registered BEFORE starting servers) ───────────
shutdown() {
    [ "$SHUTDOWN_DONE" = "1" ] && return
    SHUTDOWN_DONE=1
    echo
    echo "${BOLD}Stopping Basira...${RESET}"

    # Kill children first (Flask debug-reloader spawns a child),
    # then the launcher's direct subprocess.
    if [ -n "$ENGINE_PID" ] && kill -0 "$ENGINE_PID" 2>/dev/null; then
        pkill -P "$ENGINE_PID" 2>/dev/null || true
        kill "$ENGINE_PID" 2>/dev/null
    fi
    if [ -n "$SCRAPER_PID" ] && kill -0 "$SCRAPER_PID" 2>/dev/null; then
        pkill -P "$SCRAPER_PID" 2>/dev/null || true
        kill "$SCRAPER_PID" 2>/dev/null
    fi
    sleep 1

    # Belt-and-suspenders: anything still bound to our ports gets cleaned.
    for port in "$ENGINE_PORT" "$SCRAPER_PORT"; do
        local pid
        pid=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1)
        [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null
    done

    echo "  ${GREEN}✓${RESET} engine stopped"
    echo "  ${GREEN}✓${RESET} scraper stopped"
    echo "Goodbye."
}
trap shutdown SIGINT SIGTERM SIGHUP EXIT

# ── 4) Start servers ───────────────────────────────────────────────
mkdir -p "$LOGS_DIR"
ENGINE_LOG="$LOGS_DIR/engine.log"
SCRAPER_LOG="$LOGS_DIR/scraper.log"
: > "$ENGINE_LOG"
: > "$SCRAPER_LOG"

echo "${BOLD}Starting servers...${RESET}"

(
    cd "$ENGINE_DIR" && exec ./.venv/bin/python basira_app.py
) >>"$ENGINE_LOG" 2>&1 &
ENGINE_PID=$!

(
    cd "$SCRAPER_DIR" && exec ./.venv/bin/python basira_scraper.py
) >>"$SCRAPER_LOG" 2>&1 &
SCRAPER_PID=$!

echo "  Engine  PID $ENGINE_PID  → logs/engine.log"
echo "  Scraper PID $SCRAPER_PID  → logs/scraper.log"
echo

# ── 5) Wait for /health on both (max 30s, with progress dots) ──────
printf "${BOLD}Waiting for both services...${RESET} "
DEADLINE=$(( $(date +%s) + 30 ))
READY=0
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
    e=$(curl -sf -o /dev/null -w "%{http_code}" "http://127.0.0.1:$ENGINE_PORT/health"  2>/dev/null || echo "x")
    s=$(curl -sf -o /dev/null -w "%{http_code}" "http://127.0.0.1:$SCRAPER_PORT/health" 2>/dev/null || echo "x")
    if [ "$e" = "200" ] && [ "$s" = "200" ]; then
        READY=1
        break
    fi

    # Detect early death and surface the log tail
    if ! kill -0 "$ENGINE_PID" 2>/dev/null; then
        echo
        echo "${RED}✗ Engine died during startup. Last 20 lines of logs/engine.log:${RESET}"
        tail -20 "$ENGINE_LOG"
        die "Engine failed to start." "Check logs/engine.log for the full traceback."
    fi
    if ! kill -0 "$SCRAPER_PID" 2>/dev/null; then
        echo
        echo "${RED}✗ Scraper died during startup. Last 20 lines of logs/scraper.log:${RESET}"
        tail -20 "$SCRAPER_LOG"
        die "Scraper failed to start." "Check logs/scraper.log for the full traceback."
    fi

    printf "."
    sleep 1
done

if [ "$READY" != "1" ]; then
    echo
    echo "${RED}✗ Servers did not become healthy within 30 seconds.${RESET}"
    echo "  --- last 10 lines of logs/engine.log ---"
    tail -10 "$ENGINE_LOG"
    echo "  --- last 10 lines of logs/scraper.log ---"
    tail -10 "$SCRAPER_LOG"
    die "Servers failed to start." "Inspect the full logs in the logs/ folder."
fi
echo " ${GREEN}ready${RESET}"

# ── 6) Announce + open the UI ──────────────────────────────────────
echo "  ${GREEN}✓${RESET} Engine  ready on http://localhost:$ENGINE_PORT"
echo "  ${GREEN}✓${RESET} Scraper ready on http://localhost:$SCRAPER_PORT"
echo

# basira_preprocessor.html is NOT served by the engine (only /health,
# /upload-process and /download/<file> are wired). The HTML must be
# opened as a local file; CORS is wildcard, so file:// → :5050 works.
HTML_FILE="$ENGINE_DIR/basira_preprocessor.html"
echo "${BOLD}Opening Basira UI in your default browser...${RESET}"
open "$HTML_FILE"
echo "  → file://$HTML_FILE"
echo

# ── 7) Hold open with live logs until user closes ──────────────────
echo "${BOLD}Basira is running.${RESET} Press ${CYAN}Ctrl+C${RESET} or close this window to stop."
echo "${YELLOW}─────── live server logs (engine + scraper) ───────${RESET}"
tail -n 0 -f "$ENGINE_LOG" "$SCRAPER_LOG"
