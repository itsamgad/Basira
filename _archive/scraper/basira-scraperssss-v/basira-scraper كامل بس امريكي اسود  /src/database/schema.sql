-- Scraping Jobs
CREATE TABLE IF NOT EXISTS scraping_jobs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    type TEXT NOT NULL,
    config TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    total_pages INTEGER DEFAULT 0,
    pages_scraped INTEGER DEFAULT 0,
    total_items INTEGER DEFAULT 0
);

-- Scraped Pages
CREATE TABLE IF NOT EXISTS scraped_pages (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    FOREIGN KEY (job_id) REFERENCES scraping_jobs(id)
);

-- Fields
CREATE TABLE IF NOT EXISTS fields (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    name TEXT NOT NULL,
    selector TEXT,
    field_type TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES scraping_jobs(id)
);

-- Scraped Data
CREATE TABLE IF NOT EXISTS scraped_data (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    page_id TEXT NOT NULL,
    field_id TEXT NOT NULL,
    value TEXT,
    item_index INTEGER,
    FOREIGN KEY (job_id) REFERENCES scraping_jobs(id)
);
