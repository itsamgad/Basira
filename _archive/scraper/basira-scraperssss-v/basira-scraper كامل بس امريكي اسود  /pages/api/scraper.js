const { chromium } = require('playwright');
const { v4: uuidv4 } = require('uuid');
const { overlayScript } = require('../../src/utils/overlay-injector');

const activeBrowsers = new Map();
const jobsData = new Map();

export default async function handler(req, res) {
  const { action } = req.query;

  try {
    if (action === 'open-browser' && req.method === 'POST') {
      const { url, jobId } = req.body;
      const browser = await chromium.launch({ headless: false, args: ['--start-maximized'] });
      const context = await browser.newContext({ viewport: null });
      const page = await context.newPage();
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.addScriptTag({ content: overlayScript });
      activeBrowsers.set(jobId, { browser, context, page });
      return res.status(200).json({ success: true, jobId });
    }

    if (action === 'check-selection' && req.method === 'GET') {
      const { jobId } = req.query;
      const browserData = activeBrowsers.get(jobId);
      if (!browserData || browserData.page.isClosed()) {
        return res.status(200).json({ pending: true });
      }
      try {
        const cancelled = await browserData.page.evaluate(() => window.basiraSelectionCancelled);
        if (cancelled) {
          await browserData.browser.close();
          activeBrowsers.delete(jobId);
          return res.status(200).json({ cancelled: true });
        }
        const results = await browserData.page.evaluate(() => window.basiraResults);
        if (results) return res.status(200).json({ completed: true, results });
        return res.status(200).json({ pending: true });
      } catch (error) {
        return res.status(200).json({ pending: true });
      }
    }

    if (action === 'extract-data' && req.method === 'POST') {
      const { jobId } = req.body;
      const browserData = activeBrowsers.get(jobId);
      if (!browserData) return res.status(404).json({ error: 'Browser session not found' });

      const { page } = browserData;
      const selectionData = await page.evaluate(() => window.basiraResults);
      const { parentSelector, itemSelector, fields, loadingMethod, paginationSelector, loadMoreSelector } = selectionData;

      console.log('Container:', parentSelector);
      console.log('Item selector:', itemSelector);
      console.log('Fields:', fields);
      console.log('Loading method:', loadingMethod);

      let data = [];
      let validItemIndex = 0;

      // Helper: extract all items from current page DOM
      async function extractCurrentPage() {
        const items = await page.$$(parentSelector + ' ' + itemSelector);
        console.log('Extracting', items.length, 'items from current page...');
        for (const item of items) {
          const rowData = {};
          let hasData = false;
          for (const field of fields) {
            try {
              const element = await item.$(field.selector);
              if (element) {
                const value = await element.textContent();
                const cleanValue = value ? value.trim() : '';
                if (cleanValue) { rowData[field.name] = cleanValue; hasData = true; }
              }
            } catch (err) {}
          }
          if (hasData) {
            for (const field of fields) {
              data.push({ item_index: validItemIndex, field_name: field.name, value: rowData[field.name] || 'N/A' });
            }
            validItemIndex++;
          }
        }
        console.log('Total collected so far:', validItemIndex);
      }

      if (loadingMethod === 'auto-scroll') {
        console.log('Using AUTO-SCROLL...');
        await autoScroll(page, parentSelector, itemSelector);
        await extractCurrentPage();

      } else if (loadingMethod === 'pagination') {
        console.log('Using PAGINATION...');
        console.log('Pagination selector:', paginationSelector);
        await paginationLoad(page, parentSelector, itemSelector, paginationSelector, extractCurrentPage);

      } else if (loadingMethod === 'load-more') {
        console.log('Using LOAD MORE...');
        await loadMoreLoad(page, parentSelector, itemSelector, loadMoreSelector);
        await extractCurrentPage();
      }

      console.log('DONE. Total items extracted:', validItemIndex);
      jobsData.set(jobId, data);
      await browserData.browser.close();
      activeBrowsers.delete(jobId);
      return res.status(200).json({ success: true, itemsScraped: validItemIndex, fields });
    }

    if (action === 'get-data' && req.method === 'GET') {
      const { jobId } = req.query;
      const data = jobsData.get(jobId);
      if (!data) return res.status(404).json({ error: 'Data not found' });
      return res.status(200).json({ success: true, data });
    }

    return res.status(400).json({ error: 'Invalid action' });

  } catch (error) {
    console.error('API Error:', error);
    return res.status(500).json({ error: error.message });
  }
}

// AUTO-SCROLL
async function autoScroll(page, containerSel, itemSel) {
  return await page.evaluate(async (config) => {
    const { containerSel, itemSel } = config;
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    let previousCount = 0, noNewItemsCount = 0, iteration = 0;
    while (iteration < 500) {
      iteration++;
      const items = document.querySelectorAll(containerSel + ' ' + itemSel);
      const currentCount = items.length;
      if (currentCount > previousCount) { noNewItemsCount = 0; }
      else {
        noNewItemsCount++;
        if (noNewItemsCount >= 15) break;
      }
      previousCount = currentCount;
      if (items.length > 0) items[items.length - 1].scrollIntoView({ behavior: 'smooth', block: 'center' });
      await sleep(1500);
      if (iteration % 5 === 0) { window.scrollBy(0, 200); await sleep(300); }
    }
    window.scrollTo({ top: 0, behavior: 'auto' });
    await sleep(500);
    return document.querySelectorAll(containerSel + ' ' + itemSel).length;
  }, { containerSel, itemSel });
}

// PAGINATION - extracts data on EACH page before clicking Next
async function paginationLoad(page, containerSel, itemSel, buttonSel, extractFn) {
  let pageNum = 0;
  const maxPages = 100;

  while (pageNum < maxPages) {
    pageNum++;
    console.log('--- Page', pageNum, '---');

    // Wait for items to appear
    try {
      await page.waitForSelector(containerSel + ' ' + itemSel, { timeout: 10000 });
    } catch(e) {
      console.log('No items found, stopping.');
      break;
    }

    // Extract data from this page NOW before navigating away
    await extractFn();

    // Check if next button exists and is clickable
    const canClick = await page.evaluate((sel) => {
      const btn = document.querySelector(sel);
      if (!btn) return false;
      if (btn.disabled) return false;
      if (btn.getAttribute('aria-disabled') === 'true') return false;
      if (btn.classList.contains('disabled')) return false;
      if (btn.offsetParent === null) return false;
      // Also check parent li for disabled class (common pattern)
      if (btn.parentElement && btn.parentElement.classList.contains('disabled')) return false;
      return true;
    }, buttonSel);

    if (!canClick) {
      console.log('Next button not available - all pages done.');
      break;
    }

    const urlBefore = page.url();
    console.log('Clicking next button...');

    // Wait for navigation or AJAX update
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 8000 }).catch(() => null),
      page.click(buttonSel)
    ]);

    await page.waitForTimeout(1500);

    const urlAfter = page.url();
    if (urlAfter !== urlBefore) {
      console.log('Navigated to:', urlAfter);
    } else {
      console.log('AJAX update on same page.');
    }
  }

  console.log('Pagination complete after', pageNum, 'pages.');
}

// LOAD MORE
async function loadMoreLoad(page, containerSel, itemSel, buttonSel) {
  return await page.evaluate(async (config) => {
    const { containerSel, itemSel, buttonSel } = config;
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    let iteration = 0;
    while (iteration < 100) {
      iteration++;
      const button = document.querySelector(buttonSel);
      if (!button) break;
      if (button.offsetParent === null) break;
      button.scrollIntoView({ behavior: 'smooth', block: 'center' });
      await sleep(500);
      button.click();
      await sleep(2000);
    }
    window.scrollTo({ top: 0, behavior: 'auto' });
    await sleep(500);
    return document.querySelectorAll(containerSel + ' ' + itemSel).length;
  }, { containerSel, itemSel, buttonSel });
}
