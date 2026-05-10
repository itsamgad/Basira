# webscraping_launcher.py  —  inside Basira_app/
"""
Basira Web-Scraping Launcher
============================
لانشير مستقل لخاصية الويب سكريبنق فقط.

نفس فلسفة launcher.py الرئيسي بالضبط:
  - يقرأ مسار التثبيت من AppData\\Basira\\install_path.txt
  - إذا ما لقاه يستخدم مجلد هذا الملف نفسه
  - يشغّل الخدمة بدون نافذة console
  - ينتظر فتح البورت
  - يفتح المتصفح تلقائياً
  - يكتب لوق في AppData\\Basira\\webscraping_launcher.log

البورت المخصص: 5002
  - 5000 = Main App (محجوز)
  - 5001 = Bootstrap (محجوز)
  - 5002 = Web Scraper  ← هذا اللانشير
  - باقي اللانشيرات لازم تستخدم 5003, 5004, ... وهكذا

المسار المتوقع:
  Basira_app/
  ├── webscraping_launcher.py        ← هذا الملف
  ├── basira-scraper/                ← مجلد مشروع Next.js
  │   ├── package.json
  │   ├── pages/
  │   └── ...
  └── ... (باقي ملفات Basira)
"""

import os
import sys
import time
import json
import shutil
import socket
import webbrowser
import subprocess
import urllib.request
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
# 1) تحديد مسار التثبيت  —  بنفس طريقة launcher.py الأصلي بالضبط
# ═══════════════════════════════════════════════════════════════════════════════

def get_install_dir() -> Path:
    """
    يرجّع مسار مجلد Basira_app.

    أولاً يقرأ من AppData (الي حطّه installer)، وإذا ما لقاه
    يستخدم مجلد هذا الملف نفسه.
    """
    appdata = Path(os.environ.get("LOCALAPPDATA", "")) / "Basira"
    path_file = appdata / "install_path.txt"
    if path_file.exists():
        saved = path_file.read_text(encoding="utf-8").strip()
        if saved and Path(saved).exists():
            return Path(saved)
    # Fallback: هذا الملف موجود داخل Basira_app/
    return Path(__file__).resolve().parent


# ═══════════════════════════════════════════════════════════════════════════════
# 2) ثوابت  —  كلها مسارات صريحة، بدون أي ملف عائم
# ═══════════════════════════════════════════════════════════════════════════════

INSTALL_DIR    = get_install_dir()
SCRAPER_DIR    = INSTALL_DIR / "basira-scraper"          # مجلد مشروع Next.js
SCRAPER_PKG    = SCRAPER_DIR / "package.json"            # للتأكد إنه موجود
NODE_MODULES   = SCRAPER_DIR / "node_modules"            # مؤشّر إنه npm install تم
NEXT_BUILD_DIR = SCRAPER_DIR / ".next"                   # مؤشّر إنه npm build تم

APPDATA_DIR    = Path(os.environ.get("LOCALAPPDATA", "")) / "Basira"
LOG_FILE       = APPDATA_DIR / "webscraping_launcher.log"

SCRAPER_PORT   = 5002                                     # ← مختلف عن 5000/5001
SCRAPER_URL    = f"http://127.0.0.1:{SCRAPER_PORT}"
HEALTH_TIMEOUT = 60                                       # Next.js dev يحتاج وقت أطول


# ═══════════════════════════════════════════════════════════════════════════════
# 3) Logging
# ═══════════════════════════════════════════════════════════════════════════════

def log(msg: str) -> None:
    line = f"[scraper-launcher] {msg}"
    print(line, flush=True)
    try:
        APPDATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# 4) Helpers — Port checking
# ═══════════════════════════════════════════════════════════════════════════════

def is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_for_port(port: int, timeout: int = HEALTH_TIMEOUT) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_port_open(port):
            return True
        time.sleep(0.5)
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# 5) Node.js / npm checks
# ═══════════════════════════════════════════════════════════════════════════════

def find_executable(name: str) -> str:
    """
    يدوّر على exe (مثل node أو npm) في PATH.
    على ويندوز لازم نجرّب .cmd و .exe.
    """
    # shutil.which يحلّ معظم الحالات
    found = shutil.which(name)
    if found:
        return found

    if os.name == "nt":
        for ext in (".cmd", ".exe", ".bat"):
            found = shutil.which(name + ext)
            if found:
                return found

    raise FileNotFoundError(
        f"'{name}' not found in PATH. "
        f"Please install Node.js from https://nodejs.org and restart."
    )


def check_node_installed() -> tuple[str, str]:
    """يتأكد إنه Node.js + npm موجودين، ويرجّع مساراتهم."""
    node = find_executable("node")
    npm  = find_executable("npm")
    log(f"Node found  : {node}")
    log(f"npm found   : {npm}")
    return node, npm


# ═══════════════════════════════════════════════════════════════════════════════
# 6) Subprocess helpers — silent on Windows
# ═══════════════════════════════════════════════════════════════════════════════

def silent_run(cmd: list, env: dict | None = None) -> int:
    """يشغّل أمر ويستنّى ينتهي. بدون نافذة console على ويندوز."""
    kwargs: dict = {
        "cwd":   str(SCRAPER_DIR),
        "env":   env if env is not None else os.environ.copy(),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"]   = si
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    proc = subprocess.run(cmd, **kwargs)
    if proc.returncode != 0:
        log(f"  stderr: {proc.stderr.decode('utf-8', errors='ignore')[:500]}")
    return proc.returncode


def silent_popen(cmd: list, env: dict | None = None) -> subprocess.Popen:
    """يشغّل أمر في الخلفية ويرجّع process. بدون نافذة console."""
    kwargs: dict = {
        "cwd": str(SCRAPER_DIR),
        "env": env if env is not None else os.environ.copy(),
    }
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"]   = si
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(cmd, **kwargs)


# ═══════════════════════════════════════════════════════════════════════════════
# 7) Setup steps  —  npm install + playwright install (مرة واحدة فقط)
# ═══════════════════════════════════════════════════════════════════════════════

def ensure_npm_install(npm: str) -> None:
    """يشغّل npm install إذا node_modules مش موجود."""
    if NODE_MODULES.exists():
        log("npm dependencies already installed (node_modules exists)")
        return

    log("Running 'npm install' (one-time setup, may take 1-3 minutes)...")
    code = silent_run([npm, "install"])
    if code != 0:
        raise RuntimeError(f"'npm install' failed with exit code {code}")
    log("npm install completed successfully")


def ensure_playwright_browsers(npm: str) -> None:
    """
    Playwright يحتاج browsers تتنزّل أول مرة.
    نسوّيها مرة وحدة بس.
    """
    marker = SCRAPER_DIR / ".playwright_installed"
    if marker.exists():
        log("Playwright browsers already installed (marker present)")
        return

    log("Installing Playwright Chromium (one-time, may take a few minutes)...")
    # npx playwright install chromium
    npx = npm.replace("npm", "npx")
    if not Path(npx).exists():
        npx = find_executable("npx")
    code = silent_run([npx, "playwright", "install", "chromium"])
    if code != 0:
        log(f"Warning: Playwright install returned {code} (non-fatal, may already exist)")
    marker.write_text("ok", encoding="utf-8")
    log("Playwright browsers ready")


# ═══════════════════════════════════════════════════════════════════════════════
# 8) Service starter  —  Next.js dev server على البورت 5002
# ═══════════════════════════════════════════════════════════════════════════════

def start_scraper(npm: str) -> None:
    """يشغّل Next.js dev server على البورت المخصص لنا."""
    if is_port_open(SCRAPER_PORT):
        log(f"Scraper already running on :{SCRAPER_PORT}")
        return

    if not SCRAPER_PKG.exists():
        raise FileNotFoundError(
            f"Scraper project not found: {SCRAPER_PKG}\n"
            f"Make sure 'basira-scraper/' folder is next to this launcher."
        )

    # نختار dev أو start بناءً على وجود build
    if NEXT_BUILD_DIR.exists():
        script = "start"
        log(f"Production build detected → using 'npm run start' on :{SCRAPER_PORT}")
    else:
        script = "dev"
        log(f"No build found → using 'npm run dev' on :{SCRAPER_PORT}")

    # نمرّر PORT كـ env variable — Next.js يقرأه + كود السكريبر يستخدمه
    env = os.environ.copy()
    env["PORT"] = str(SCRAPER_PORT)

    # On Windows, npm.cmd needs to be called via shell-like invocation
    cmd = [npm, "run", script, "--", "-p", str(SCRAPER_PORT)]
    log(f"Launching: {' '.join(cmd)}")
    silent_popen(cmd, env=env)


# ═══════════════════════════════════════════════════════════════════════════════
# 9) Coordination with main app  (اختياري لكن موصى به)
# ═══════════════════════════════════════════════════════════════════════════════

def notify_main_app(status: str) -> None:
    """
    يبلّغ التطبيق الرئيسي (إذا كان شغّال) إنه السكريبر صار جاهز.
    إذا التطبيق الرئيسي ما شغّال، نتجاهل بصمت — هذا اللانشير مستقل.
    """
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:5000/api/services/notify",
            data=json.dumps({
                "service": "web_scraper",
                "status":  status,
                "url":     SCRAPER_URL,
                "port":    SCRAPER_PORT,
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2):
            log(f"Notified main app: scraper {status}")
    except Exception:
        # التطبيق الرئيسي مش شغّال — مش مشكلة، اللانشير مستقل
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# 10) Main
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    background = "--background" in sys.argv
    no_browser = "--no-browser" in sys.argv

    log("═" * 60)
    log("Basira Web-Scraping Launcher")
    log("═" * 60)
    log(f"Install dir   : {INSTALL_DIR}")
    log(f"Scraper dir   : {SCRAPER_DIR}")
    log(f"Target port   : {SCRAPER_PORT}")
    log(f"Background    : {background}")
    log("═" * 60)

    # ── (a) فحص Node ─────────────────────────────────────────────────────────
    try:
        node, npm = check_node_installed()
    except FileNotFoundError as e:
        log(f"FATAL: {e}")
        sys.exit(1)

    # ── (b) فحص مجلد المشروع ─────────────────────────────────────────────────
    if not SCRAPER_DIR.exists():
        log(f"FATAL: Scraper folder not found at: {SCRAPER_DIR}")
        log(f"       Place 'basira-scraper/' next to this launcher.")
        sys.exit(1)

    if not SCRAPER_PKG.exists():
        log(f"FATAL: package.json missing at: {SCRAPER_PKG}")
        sys.exit(1)

    # ── (c) إعداد أول مرة ────────────────────────────────────────────────────
    try:
        ensure_npm_install(npm)
        ensure_playwright_browsers(npm)
    except Exception as e:
        log(f"FATAL: Setup failed: {e}")
        sys.exit(1)

    # ── (d) تشغيل الخدمة ─────────────────────────────────────────────────────
    try:
        start_scraper(npm)
    except Exception as e:
        log(f"FATAL: Failed to start scraper: {e}")
        sys.exit(1)

    # ── (e) انتظار جاهزية البورت ─────────────────────────────────────────────
    log(f"Waiting for scraper on :{SCRAPER_PORT} (timeout {HEALTH_TIMEOUT}s)...")
    if not wait_for_port(SCRAPER_PORT, timeout=HEALTH_TIMEOUT):
        log(f"WARNING: Port {SCRAPER_PORT} did not open in {HEALTH_TIMEOUT}s.")
        log(f"         Check log at: {LOG_FILE}")
        sys.exit(1)
    log(f"Scraper ready  →  {SCRAPER_URL}")

    # ── (f) إبلاغ التطبيق الرئيسي (إذا شغّال) ────────────────────────────────
    notify_main_app("ready")

    # ── (g) فتح المتصفح ──────────────────────────────────────────────────────
    if not background and not no_browser:
        webbrowser.open(SCRAPER_URL)
        log(f"Browser opened →  {SCRAPER_URL}")

    log("─" * 60)
    log("Web-Scraper is running.")
    log(f"  URL : {SCRAPER_URL}")
    log(f"  Log : {LOG_FILE}")
    log("─" * 60)


if __name__ == "__main__":
    main()
