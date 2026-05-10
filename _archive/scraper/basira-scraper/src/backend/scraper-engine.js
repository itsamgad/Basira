const { chromium } = require('playwright');
const { v4: uuidv4 } = require('uuid');

class ScraperEngine {
  constructor() {
    this.browser = null;
  }

  async initialize() {
    this.browser = await chromium.launch({ headless: false });
  }

  async detectListPatterns(url) {
    const context = await this.browser.newContext();
    const page = await context.newPage();
    
    try {
      await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
      
      const patterns = await page.evaluate(() => {
        const results = [];
        const selectors = [
          'article',
          '[class*="card"]',
          '[class*="item"]',
          '[class*="product"]',
          '[class*="story"]',
          'li',
          'tr',
          '.athing'
        ];

        selectors.forEach(selector => {
          const elements = document.querySelectorAll(selector);
          if (elements.length >= 3) {
            const firstElement = elements[0];
            const detectedFields = [];

            // Detect title
            const title = firstElement.querySelector('h1, h2, h3, h4, [class*="title"], .titleline a, a.storylink');
            if (title) {
              detectedFields.push({
                name: 'title',
                selector: 'h1, h2, h3, h4, [class*="title"], .titleline a, a.storylink',
                type: 'text',
                sample: title.textContent?.trim().substring(0, 50)
              });
            }

            // Detect link
            const link = firstElement.querySelector('a[href]');
            if (link) {
              detectedFields.push({
                name: 'link',
                selector: 'a[href]',
                type: 'url',
                sample: link.href?.substring(0, 50)
              });
            }

            // Detect score/points
            const score = firstElement.querySelector('[class*="score"], .score');
            if (score) {
              detectedFields.push({
                name: 'score',
                selector: '[class*="score"], .score',
                type: 'text',
                sample: score.textContent?.trim()
              });
            }

            if (detectedFields.length > 0) {
              results.push({
                selector: selector,
                itemCount: elements.length,
                confidence: 0.9,
                detectedFields
              });
            }
          }
        });

        return results.sort((a, b) => b.itemCount - a.itemCount);
      });

      return patterns;
    } finally {
      await context.close();
    }
  }

  async scrapeList(job, config, saveDataCallback) {
    const context = await this.browser.newContext();
    const page = await context.newPage();
    
    try {
      await page.goto(job.url, { waitUntil: 'networkidle', timeout: 30000 });

      const items = await page.$$eval(config.listSelector, (elements, fields) => {
        return elements.map((element, index) => {
          const item = { index };
          
          fields.forEach(field => {
            try {
              const targetElement = element.querySelector(field.selector);
              if (targetElement) {
                if (field.type === 'url') {
                  item[field.name] = targetElement.href || targetElement.getAttribute('href');
                } else {
                  item[field.name] = targetElement.textContent?.trim() || '';
                }
              }
            } catch (error) {
              item[field.name] = null;
            }
          });
          
          return item;
        });
      }, config.fields || []);

      // Save to callback (in-memory storage)
      items.forEach((item, itemIndex) => {
        config.fields.forEach(field => {
          saveDataCallback({
            id: uuidv4(),
            jobId: job.id,
            field_name: field.name,
            value: item[field.name],
            item_index: itemIndex
          });
        });
      });

      return {
        success: true,
        itemsScraped: items.length
      };
    } finally {
      await context.close();
    }
  }

  async cleanup() {
    if (this.browser) {
      await this.browser.close();
    }
  }
}

module.exports = ScraperEngine;
