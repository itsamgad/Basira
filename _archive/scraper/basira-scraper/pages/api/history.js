const fs = require('fs');
const path = require('path');

const HISTORY_FILE = path.join(process.cwd(), 'scrape-history.json');

function readHistory() {
  try {
    if (!fs.existsSync(HISTORY_FILE)) return [];
    return JSON.parse(fs.readFileSync(HISTORY_FILE, 'utf8'));
  } catch (e) {
    return [];
  }
}

function writeHistory(history) {
  fs.writeFileSync(HISTORY_FILE, JSON.stringify(history, null, 2));
}

export default function handler(req, res) {
  const { action } = req.query;

  // GET all history
  if (action === 'list' && req.method === 'GET') {
    const history = readHistory();
    return res.status(200).json({ success: true, history });
  }

  // POST — add a new entry
  if (action === 'add' && req.method === 'POST') {
    const { url, jobId, rows, failedItems, fields, loadingMethod, duration } = req.body;
    const history = readHistory();
    const entry = {
      id: jobId,
      url,
      hostname: (() => { try { return new URL(url).hostname; } catch (e) { return url; } })(),
      timestamp: new Date().toISOString(),
      rows,
      failedItems: failedItems || 0,
      fields: fields || [],
      loadingMethod: loadingMethod || 'auto-scroll',
      duration: duration || 0,
    };
    // Keep newest first, cap at 50 entries
    history.unshift(entry);
    if (history.length > 50) history.splice(50);
    writeHistory(history);
    return res.status(200).json({ success: true, entry });
  }

  // DELETE — remove a single entry
  if (action === 'delete' && req.method === 'DELETE') {
    const { id } = req.query;
    const history = readHistory().filter(e => e.id !== id);
    writeHistory(history);
    return res.status(200).json({ success: true });
  }

  // DELETE all
  if (action === 'clear' && req.method === 'DELETE') {
    writeHistory([]);
    return res.status(200).json({ success: true });
  }

  return res.status(400).json({ error: 'Invalid action' });
}
