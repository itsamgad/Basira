const Database = require('better-sqlite3');
const fs = require('fs');
const path = require('path');
const { app } = require('electron');

class DatabaseManager {
  constructor() {
    this.db = null;
  }

  initialize() {
    const userDataPath = app.getPath('userData');
    const dbPath = path.join(userDataPath, 'basira-scraper.db');
    
    this.db = new Database(dbPath);
    
    const schema = fs.readFileSync(path.join(__dirname, 'schema.sql'), 'utf8');
    this.db.exec(schema);
    
    return this.db;
  }

  createJob(job) {
    const stmt = this.db.prepare(`
      INSERT INTO scraping_jobs (id, name, url, type, config)
      VALUES (?, ?, ?, ?, ?)
    `);
    return stmt.run(job.id, job.name, job.url, job.type, JSON.stringify(job.config || {}));
  }

  getJob(jobId) {
    const stmt = this.db.prepare('SELECT * FROM scraping_jobs WHERE id = ?');
    return stmt.get(jobId);
  }

  updateJobStatus(jobId, status) {
    const stmt = this.db.prepare('UPDATE scraping_jobs SET status = ? WHERE id = ?');
    return stmt.run(status, jobId);
  }

  saveScrapedData(data) {
    const stmt = this.db.prepare(`
      INSERT INTO scraped_data (id, job_id, page_id, field_id, value, item_index)
      VALUES (?, ?, ?, ?, ?, ?)
    `);
    return stmt.run(data.id, data.jobId, data.pageId, data.fieldId, data.value, data.itemIndex);
  }

  getJobData(jobId) {
    const stmt = this.db.prepare(`
      SELECT sd.*, f.name as field_name
      FROM scraped_data sd
      JOIN fields f ON sd.field_id = f.id
      WHERE sd.job_id = ?
      ORDER BY sd.item_index, f.name
    `);
    return stmt.all(jobId);
  }
}

let instance = null;

module.exports = {
  getDatabaseManager: () => {
    if (!instance) {
      instance = new DatabaseManager();
    }
    return instance;
  }
};
