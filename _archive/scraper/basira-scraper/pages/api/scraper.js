const { chromium } = require('playwright');
const { overlayScript } = require('../../src/utils/overlay-injector');
const fs = require('fs');
const path = require('path');

const DATA_DIR = path.join(process.cwd(), 'scrape-data');
if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });

const activeBrowsers = new Map();
const jobsData = new Map();
const jobsProgress = new Map();

// ── USER AGENT POOL ────────────────────────────────────────────────────────
const USER_AGENTS = [
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
];
const randomUA = () => USER_AGENTS[Math.floor(Math.random() * USER_AGENTS.length)];

// Random human delay: base ± 40% jitter
const humanDelay = (base) => base * 0.6 + Math.random() * base * 0.8;

export default async function handler(req, res) {
  const { action } = req.query;

  try {

    // ── OPEN BROWSER ──────────────────────────────────────────────────
    if (action === 'open-browser' && req.method === 'POST') {
      const { url, jobId, lang, stealth, proxy } = req.body;

      // Build launch options
      const launchOptions = { headless: false, args: ['--start-maximized'] };
      if (proxy && proxy.host) {
        launchOptions.proxy = {
          server: `${proxy.protocol || 'http'}://${proxy.host}:${proxy.port || 8080}`,
          ...(proxy.username ? { username: proxy.username } : {}),
          ...(proxy.password ? { password: proxy.password } : {}),
        };
      }

      const browser = await chromium.launch(launchOptions);

      // Build context options
      const contextOptions = { viewport: null };
      if (stealth) {
        contextOptions.userAgent = randomUA();
        contextOptions.locale = 'en-US';
        contextOptions.timezoneId = 'America/New_York';
        contextOptions.extraHTTPHeaders = {
          'Accept-Language': 'en-US,en;q=0.9',
          'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        };
      }

      const context = await browser.newContext(contextOptions);

      // Stealth: hide webdriver flag
      if (stealth) {
        await context.addInitScript(() => {
          Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
          Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
          Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
          window.chrome = { runtime: {} };
        });
      }

      const page = await context.newPage();
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.evaluate((l) => { window.basiraLang = l || 'en'; }, lang || 'en');
      await page.addScriptTag({ content: overlayScript });

      activeBrowsers.set(jobId, { browser, context, page, stealth: !!stealth, startTime: Date.now(), url });
      jobsProgress.set(jobId, { status: 'idle', currentPage: 0, totalPages: '?', itemsCollected: 0, failedItems: 0, error: null });
      return res.status(200).json({ success: true, jobId });
    }

    // ── CHECK SELECTION ───────────────────────────────────────────────
    if (action === 'check-selection' && req.method === 'GET') {
      const { jobId } = req.query;
      const bd = activeBrowsers.get(jobId);
      if (!bd || bd.page.isClosed()) return res.status(200).json({ pending: true });
      try {
        const cancelled = await bd.page.evaluate(() => window.basiraSelectionCancelled);
        if (cancelled) { await bd.browser.close(); activeBrowsers.delete(jobId); return res.status(200).json({ cancelled: true }); }
        const results = await bd.page.evaluate(() => window.basiraResults);
        if (results) return res.status(200).json({ completed: true, results });
        return res.status(200).json({ pending: true });
      } catch (e) { return res.status(200).json({ pending: true }); }
    }

    // ── GET PROGRESS ──────────────────────────────────────────────────
    if (action === 'get-progress' && req.method === 'GET') {
      const { jobId } = req.query;
      return res.status(200).json(jobsProgress.get(jobId) || { status: 'idle' });
    }

    // ── EXTRACT DATA ──────────────────────────────────────────────────
    if (action === 'extract-data' && req.method === 'POST') {
      const { jobId, rowLimit } = req.body;
      const bd = activeBrowsers.get(jobId);
      if (!bd) return res.status(404).json({ error: 'Browser session not found' });

      const { page } = bd;
      const sel = await page.evaluate(() => window.basiraResults);
      const { parentSelector, itemSelector, fields, loadingMethod, paginationSelector, loadMoreSelector } = sel;
      const maxRows = rowLimit && rowLimit > 0 ? rowLimit : Infinity;

      console.log('Container:', parentSelector, '| Item:', itemSelector, '| Method:', loadingMethod, '| Limit:', maxRows);
      jobsProgress.set(jobId, { status: 'running', currentPage: 1, totalPages: '?', itemsCollected: 0, failedItems: 0, error: null });

      let data = [];
      let validItemIndex = 0;
      let failedItems = 0;

      if (loadingMethod === 'pagination') {
        const result = await paginationLoad(page, parentSelector, itemSelector, paginationSelector, fields, jobId, maxRows);
        data = result.allData;
        validItemIndex = result.totalLoaded;
        failedItems = result.failedItems;

      } else {
        if (loadingMethod === 'auto-scroll') {
          await autoScroll(page, parentSelector, itemSelector, maxRows);
        } else if (loadingMethod === 'load-more') {
          await loadMoreLoad(page, parentSelector, itemSelector, loadMoreSelector, maxRows);
        }

        const items = await page.$$(`${parentSelector} ${itemSelector}`);
        const limitedItems = maxRows < Infinity ? items.slice(0, maxRows) : items;
        console.log('Extracting from', limitedItems.length, 'items (limit:', maxRows, ')...');
        jobsProgress.set(jobId, { status: 'running', currentPage: 1, totalPages: 1, itemsCollected: 0, failedItems: 0, error: null });

        for (let i = 0; i < limitedItems.length; i++) {
          const { rowData, hasData } = await extractItemWithRetry(limitedItems[i], fields, page, 3);
          if (hasData) {
            for (const field of fields) {
              data.push({ item_index: validItemIndex, field_name: field.name, value: rowData[field.name] || 'N/A' });
            }
            validItemIndex++;
          } else { failedItems++; }

          if (i % 10 === 0) {
            const p = jobsProgress.get(jobId);
            jobsProgress.set(jobId, { ...p, itemsCollected: validItemIndex, failedItems });
          }
        }
      }

      jobsProgress.set(jobId, { status: 'done', currentPage: 0, totalPages: 0, itemsCollected: validItemIndex, failedItems, error: null });
      console.log(`✅ Extracted ${validItemIndex} items, ${failedItems} failed`);

      jobsData.set(jobId, data);

      // Persist to disk so "View" works after restart
      try {
        fs.writeFileSync(path.join(DATA_DIR, jobId + '.json'), JSON.stringify({ fields, data }, null, 2));
      } catch (we) { console.warn('Data persist failed:', we.message); }

      // Save to history
      const duration = Math.round((Date.now() - (bd.startTime || Date.now())) / 1000);
      try {
        await fetch(`http://localhost:${process.env.PORT || 3000}/api/history?action=add`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: bd.url || '', jobId, rows: validItemIndex, failedItems, fields, loadingMethod, duration })
        });
      } catch (he) { console.warn('History save failed:', he.message); }

      await bd.browser.close();
      activeBrowsers.delete(jobId);

      return res.status(200).json({ success: true, itemsScraped: validItemIndex, failedItems, fields });
    }

    // ── GET DATA ──────────────────────────────────────────────────────
    if (action === 'get-data' && req.method === 'GET') {
      const { jobId } = req.query;
      // Try memory first, then disk
      let data = jobsData.get(jobId);
      let fields = null;
      if (!data) {
        const filePath = path.join(DATA_DIR, jobId + '.json');
        if (fs.existsSync(filePath)) {
          const saved = JSON.parse(fs.readFileSync(filePath, 'utf8'));
          data = saved.data;
          fields = saved.fields;
        }
      }
      if (!data) return res.status(404).json({ error: 'Data not found' });
      return res.status(200).json({ success: true, data, fields });
    }

    return res.status(400).json({ error: 'Invalid action' });

  } catch (error) {
    console.error('API Error:', error);
    const jobId = (req.body || {}).jobId || (req.query || {}).jobId;
    if (jobId) {
      const p = jobsProgress.get(jobId) || {};
      jobsProgress.set(jobId, { ...p, status: 'error', error: error.message });
    }
    return res.status(500).json({ error: error.message });
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// SHARED: extract one field value from an element
// ─────────────────────────────────────────────────────────────────────────────
async function extractFieldValue(element, field, pageUrl) {
  if (field.type === 'image') {
    const src = await element.getAttribute('src') || await element.getAttribute('data-src') || await element.getAttribute('data-lazy') || '';
    try { return src ? new URL(src, pageUrl).href : ''; } catch (e) { return src; }
  }
  if (field.type === 'link') {
    const href = await element.getAttribute('href') || '';
    try { return href ? new URL(href, pageUrl).href : ''; } catch (e) { return href; }
  }
  if (field.type === 'price') {
    const raw = await element.textContent();
    return (raw || '').replace(/[£$€¥₹,\s]/g, '').trim();
  }
  // text — detect star ratings stored as CSS class names
  const className = await element.getAttribute('class') || '';
  const starMatch = className.match(/\b(One|Two|Three|Four|Five)\b/i);
  if (starMatch) {
    const map = { one: '1', two: '2', three: '3', four: '4', five: '5' };
    return map[starMatch[1].toLowerCase()] || starMatch[1];
  }
  return (await element.textContent() || '').trim();
}

// ─────────────────────────────────────────────────────────────────────────────
// Extract one item, retrying up to maxRetries times
// ─────────────────────────────────────────────────────────────────────────────
async function extractItemWithRetry(item, fields, page, maxRetries = 3) {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const rowData = {};
      let hasData = false;
      const pageUrl = page.url();

      for (const field of fields) {
        try {
          const el = await item.$(field.selector);
          if (el) {
            const value = await extractFieldValue(el, field, pageUrl);
            if (value) { rowData[field.name] = value; hasData = true; }
          }
        } catch (fe) {
          console.warn(`Field "${field.name}" failed (attempt ${attempt}):`, fe.message);
        }
      }
      return { rowData, hasData };
    } catch (err) {
      console.warn(`Item attempt ${attempt}/${maxRetries} failed:`, err.message);
      if (attempt < maxRetries) await new Promise(r => setTimeout(r, 500 * attempt));
    }
  }
  return { rowData: {}, hasData: false };
}

// ─────────────────────────────────────────────────────────────────────────────
// AUTO-SCROLL
// ─────────────────────────────────────────────────────────────────────────────
async function autoScroll(page, containerSel, itemSel, maxRows = Infinity) {
  return await page.evaluate(async ({ containerSel, itemSel, maxRows }) => {
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    let prev = 0, noNew = 0, iter = 0;
    while (iter++ < 500) {
      const items = document.querySelectorAll(`${containerSel} ${itemSel}`);
      const cur = items.length;
      if (cur >= maxRows) break; // ← stop as soon as we have enough
      if (cur > prev) { noNew = 0; } else { if (++noNew >= 15) break; }
      prev = cur;
      if (items.length) items[items.length - 1].scrollIntoView({ behavior: 'smooth', block: 'center' });
      await sleep(1500);
      if (iter % 5 === 0) { window.scrollBy(0, 200); await sleep(300); }
    }
    window.scrollTo({ top: 0, behavior: 'auto' });
    await sleep(500);
    return document.querySelectorAll(`${containerSel} ${itemSel}`).length;
  }, { containerSel, itemSel, maxRows });
}

// ─────────────────────────────────────────────────────────────────────────────
// PAGINATION — extracts per-page, retries clicks, updates live progress
// ─────────────────────────────────────────────────────────────────────────────
async function paginationLoad(page, containerSel, itemSel, buttonSel, fields, jobId, maxRows = Infinity) {
  const allData = [];
  let validItemIndex = 0;
  let failedItems = 0;
  let pageNum = 0;
  const maxPages = 200;
  const maxClickRetries = 3;

  console.log('➡️ Pagination | button:', buttonSel);

  while (pageNum < maxPages) {
    pageNum++;
    console.log(`\n📄 Page ${pageNum}...`);

    jobsProgress.set(jobId, {
      status: 'running', currentPage: pageNum, totalPages: '?',
      itemsCollected: validItemIndex, failedItems, error: null
    });

    // Wait for items (retry up to 3×)
    let itemsFound = false;
    for (let t = 0; t < 3; t++) {
      try { await page.waitForSelector(`${containerSel} ${itemSel}`, { timeout: 10000 }); itemsFound = true; break; }
      catch (e) { console.warn(`  ⚠️ Items not found (try ${t + 1}/3)`); await page.waitForTimeout(2000); }
    }
    if (!itemsFound) { console.log('  ❌ Items never appeared, stopping.'); break; }

    const items = await page.$$(`${containerSel} ${itemSel}`);
    console.log(`  📊 ${items.length} items`);

    for (const item of items) {
      if (validItemIndex >= maxRows) break;
      const { rowData, hasData } = await extractItemWithRetry(item, fields, page, 3);
      if (hasData) {
        for (const field of fields) {
          allData.push({ item_index: validItemIndex, field_name: field.name, value: rowData[field.name] || 'N/A' });
        }
        validItemIndex++;
      } else { failedItems++; }
    }

    console.log(`  ✅ Page ${pageNum} done — ${validItemIndex} total`);

    if (validItemIndex >= maxRows) {
      console.log(`  🏁 Row limit of ${maxRows} reached.`);
      break;
    }

    // Check Next button
    const buttonReady = await page.evaluate((sel) => {
      const btn = document.querySelector(sel);
      if (!btn || btn.disabled || btn.getAttribute('aria-disabled') === 'true' || btn.offsetParent === null) return false;
      return true;
    }, buttonSel);

    if (!buttonReady) { console.log('  🏁 No more pages.'); break; }

    // Click Next with retry + human-like behavior
    let clicked = false;
    for (let attempt = 1; attempt <= maxClickRetries; attempt++) {
      try {
        const urlBefore = page.url();

        // Human-like: move mouse to button before clicking
        const btnBox = await page.locator(buttonSel).boundingBox();
        if (btnBox) {
          const x = btnBox.x + btnBox.width * (0.3 + Math.random() * 0.4);
          const y = btnBox.y + btnBox.height * (0.3 + Math.random() * 0.4);
          await page.mouse.move(x, y, { steps: Math.floor(5 + Math.random() * 10) });
          await page.waitForTimeout(humanDelay(300));
        }

        const navPromise = page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 8000 }).catch(() => null);
        await page.click(buttonSel, { timeout: 5000 });
        await navPromise;
        await page.waitForTimeout(humanDelay(1500));
        clicked = true;
        const urlAfter = page.url();
        console.log(urlAfter !== urlBefore ? `  🌐 Navigated` : '  ⚡ AJAX');
        break;
      } catch (ce) {
        console.warn(`  ⚠️ Click attempt ${attempt}/${maxClickRetries}: ${ce.message}`);
        await page.waitForTimeout(2000 * attempt);
      }
    }

    if (!clicked) { console.log('  ❌ Could not click Next, stopping.'); break; }
  }

  console.log(`\n✅ Pagination done — ${validItemIndex} items, ${failedItems} failed, ${pageNum} pages`);
  return { totalLoaded: validItemIndex, allData, failedItems };
}

// ─────────────────────────────────────────────────────────────────────────────
// LOAD MORE
// ─────────────────────────────────────────────────────────────────────────────
async function loadMoreLoad(page, containerSel, itemSel, buttonSel, maxRows = Infinity) {
  return await page.evaluate(async ({ containerSel, itemSel, buttonSel, maxRows }) => {
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    let iter = 0;
    while (iter++ < 100) {
      const items = document.querySelectorAll(`${containerSel} ${itemSel}`);
      if (items.length >= maxRows) break; // ← stop as soon as we have enough
      const btn = document.querySelector(buttonSel);
      if (!btn || btn.offsetParent === null) break;
      btn.scrollIntoView({ behavior: 'smooth', block: 'center' });
      await sleep(500);
      btn.click();
      await sleep(2000);
    }
    window.scrollTo({ top: 0, behavior: 'auto' });
    await sleep(500);
    return document.querySelectorAll(`${containerSel} ${itemSel}`).length;
  }, { containerSel, itemSel, buttonSel, maxRows });
}
