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
4. Live at `https://USERNAME.github.io/basira/` after ~1 min.

> GitHub Pages serves at the repo's path — links inside `index.html`
> all use relative URLs (`assets/...`), so no rewrite is needed.

---

## Before you publish — placeholders to update

The site currently has placeholder URLs and credit lines marked with
`<!-- TODO: ... -->` comments. Search for the literal string `USERNAME`
in `index.html` and replace each occurrence with your GitHub handle.

Other one-off edits in `index.html`:

| Where | What to replace |
|---|---|
| `<meta property="og:url">` and `og:image` | the deployed site URL once Vercel/Netlify gives you one |
| Footer **"Built by Your Name"** | your name |
| Footer **"Final-year project at Your University"** | your university |
| License (footer) | confirm or change `MIT` |
| `assets/screenshots/upload.png` etc. | drop real PNGs into `assets/screenshots/` and replace the placeholder `<div class="shot">` with `<img>` |

For real download buttons:

1. On GitHub, **Releases → Draft a new release**, tag e.g. `v1.0.0`.
2. Upload `Basira-macOS.zip` and `Basira-Windows.zip` as release assets.
3. The placeholder URLs already point to
   `https://github.com/USERNAME/basira/releases/latest/download/Basira-macOS.zip`
   — just replace `USERNAME`.

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
