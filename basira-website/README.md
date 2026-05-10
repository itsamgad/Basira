# Basira Marketing Site

Static landing page at `basira-website/`. **No build step**, no
`node_modules/`, no framework. Three files do the whole job:

```
basira-website/
├── index.html         # ~310 lines — markup + content
├── styles.css         # ~290 lines — custom CSS, mirrors the app's #0ea5e9 palette
├── script.js          # ~50  lines — sticky-nav shadow + offset-anchor scroll
├── assets/
│   ├── basira-logo.png
│   └── screenshots/
│       └── .gitkeep   # drop real screenshots here before going live
└── README.md          # this file
```

The only external resource is **Inter** loaded once from Google Fonts.
Everything else is local — works offline once cached, and works from a
plain `file://` open if you want to preview without a server.

## Local preview

The simplest:

```bash
cd basira-website
python3 -m http.server 8000
open http://localhost:8000
```

Or just **double-click `index.html`** — Google Fonts and the local logo
both work over `file://`.

---

## Build the installer ZIPs (do this first)

The Mac and Windows download buttons in `index.html` point at relative
URLs — `downloads/Basira-macOS.zip` and `downloads/Basira-Windows.zip` —
so they work locally and on every static host (Vercel, Netlify, GitHub
Pages) with the same build artifacts. The ZIPs themselves are NOT
checked into git (they're build outputs, regenerated per release).

Build them from the workspace root **before** deploying:

```bash
cd ~/Desktop/Basira-Workspace

# macOS installer — bundles the .app, .command, both Python projects
# and docs. Excludes venvs (re-created on the user's machine), runtime
# logs, the cache folder, scraper outputs, and git metadata.
zip -r basira-website/downloads/Basira-macOS.zip \
    Basira.app Basira.command \
    basira-engine/ basira-scraper/ docs/ \
    -x '*/.venv/*' '*/logs/*' '*/__pycache__/*' '*/.git/*' '*/scrape_outputs/*'

# Windows installer — bundles the .bat scripts, both Python projects
# and docs. Same exclusions.
zip -r basira-website/downloads/Basira-Windows.zip \
    Basira.bat setup.bat \
    basira-engine/ basira-scraper/ docs/ \
    -x '*/.venv/*' '*/logs/*' '*/__pycache__/*' '*/.git/*' '*/scrape_outputs/*'
```

The Mac ZIP excludes the `.bat` files and the Windows ZIP excludes the
`.app`/`.command` files indirectly (they aren't listed) — each user
gets only what they need, no platform-cross junk.

**Expected size:** ~1–2 MB per ZIP. The venvs and the Playwright
Chromium binary (~250 MB combined) are NOT in the ZIP — they're
created on first run by `setup.bat` (Windows) or by the
manual venv steps documented in `docs/HOW_TO_LAUNCH.md` (macOS).

Re-run these commands every time you ship a new release.

---

## Deploy — three free options

### Option 1 — Vercel (recommended)

1. Open <https://vercel.com/new>.
2. Drag the `basira-website/` folder onto the page.
3. Click **Deploy**.
4. Live at `https://basira-XXX.vercel.app` in ~30 seconds.

You can connect a custom domain later (Vercel → Settings → Domains).

### Option 2 — Netlify

1. Open <https://app.netlify.com/drop>.
2. Drag the `basira-website/` folder onto the drop area.
3. Live at `https://basira-XXX.netlify.app`.

### Option 3 — GitHub Pages (requires public repo)

1. Push the project to GitHub.
2. **Settings → Pages → Source**: *Deploy from a branch*.
3. Choose `main` branch, `/basira-website` folder.
4. Live at `https://itsamgad.github.io/basira/` after ~1 min.

> GitHub Pages serves at the repo's path — links inside `index.html`
> all use relative URLs (`assets/...`, `downloads/...`), so no rewrite
> is needed.

---

## Public access — free subdomain vs custom domain

### Free subdomain (recommended to start)

Each of the three deploy options gives you a free, instant subdomain
on the host's apex:

| Host | Subdomain shape | Cost |
|---|---|---|
| Vercel  | `basira-XXX.vercel.app`           | $0 |
| Netlify | `basira-XXX.netlify.app`          | $0 |
| GitHub Pages | `itsamgad.github.io/basira/` | $0 |

Vercel and Netlify both let you rename the random `XXX` suffix in
their dashboard (Settings → Domains for Vercel, Domain management
for Netlify) — you can ship as `basira-three.vercel.app` if it's
available.

### Custom domain ($10–20/year)

If you want `basira.com` or similar, the workflow is the same on
all three hosts:

1. **Buy the domain** — Namecheap, Cloudflare Registrar, Porkbun, or
   any registrar of your choice. Common annual prices: `.com` ≈ $12,
   `.app` ≈ $14, `.io` ≈ $40, `.dev` ≈ $14.
2. **Connect it on the host:**
   - Vercel: Project → Settings → Domains → Add → enter the domain.
   - Netlify: Site → Domain management → Add custom domain.
   - GitHub Pages: Settings → Pages → Custom domain.
3. **Point DNS:** the host gives you either a CNAME (e.g.
   `cname.vercel-dns.com`) or A records to set at your registrar.
   DNS propagates in 5 minutes to a few hours.
4. **HTTPS:** all three hosts auto-provision a free Let's Encrypt
   certificate once DNS resolves.

If `basira.com` is already taken, common available alternatives to
search for:

- `basira.app`, `basira.dev`, `basira.io`
- `getbasira.com`, `basiraml.com`, `basira-tools.com`
- `tryba.sh`, `basira.tools`, `usebasira.com`
- the bilingual angle: `basira.ai` or `basira-data.com`

Check availability first via your registrar's search box — prices
vary by extension and any matching trademarks.

---

## Before you publish — placeholders to update

Project metadata (name, university, GitHub handle, license) is already
filled. What remains:

| Where in `index.html` | What to do |
|---|---|
| `<meta property="og:url">` and `og:image` (lines 10–15) | Currently `https://basira-three.vercel.app` — confirm this is the actual subdomain after Vercel deploys, or update if Vercel assigns a different one. |
| `<div class="shot">` placeholders (lines ~200, 209, 218) | Drop real PNGs into `assets/screenshots/` (`upload.png`, `audit.png`, `scraper.png`) and replace the `<div class="shot">` blocks with `<img src="assets/screenshots/upload.png" alt="...">` etc. |
| License (footer) | Currently `MIT` — confirm or change to whatever you ship under. |

**For real download buttons:** the buttons in `index.html` already
point at the relative paths `downloads/Basira-macOS.zip` and
`downloads/Basira-Windows.zip`. Just run the two `zip -r` commands
in the *Build the installer ZIPs* section above before each deploy —
the ZIPs go into `basira-website/downloads/` and the buttons pick
them up automatically. (The ZIPs themselves are gitignored, so
you'll re-build them on each ship.)

---

## Design notes

- Color palette and tokens (`--accent: #0ea5e9`, `--a2: #6366f1`, etc.)
  match `basira-engine/basira_preprocessor.html` so the marketing site
  feels like the app.
- Mobile breakpoint at **768 px**: 3-column grids collapse to single
  column, hero font size drops, navbar links hide (Download CTA stays).
- No heavy animations — `transform: translateY(-2px)` + shadow on
  card hovers, that's it.
- Hero headline uses a subtle `linear-gradient(90deg, #0ea5e9, #6366f1)`
  text-clip — same gradient as the app's progress bar.
