const { app, BrowserWindow, ipcMain } = require('electron');
const ScraperEngine = require('../backend/scraper-engine');
const { v4: uuidv4 } = require('uuid');

let mainWindow;
let scraperEngine;
let jobsInMemory = {};
let dataInMemory = {};

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    backgroundColor: '#020617',
    show: false, // Don't show until ready
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
      webSecurity: false, // Allow loading from localhost
    },
  });

  // Load from localhost
  mainWindow.loadURL('http://localhost:3000');

  // Show window when ready
  mainWindow.once('ready-to-show', () => {
    console.log('Window ready to show');
    mainWindow.show();
  });

  // Open DevTools
  mainWindow.webContents.openDevTools();

  // Debug: Log when page finishes loading
  mainWindow.webContents.on('did-finish-load', () => {
    console.log('Page finished loading');
  });

  // Debug: Log any errors
  mainWindow.webContents.on('did-fail-load', (event, errorCode, errorDescription) => {
    console.error('Failed to load:', errorCode, errorDescription);
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// Wait for Next.js to be ready before creating window
function waitForNextJS() {
  return new Promise((resolve) => {
    const checkServer = () => {
      require('http').get('http://localhost:3000', (res) => {
        if (res.statusCode === 200) {
          console.log('Next.js server is ready');
          resolve();
        } else {
          setTimeout(checkServer, 100);
        }
      }).on('error', () => {
        setTimeout(checkServer, 100);
      });
    };
    checkServer();
  });
}

app.on('ready', async () => {
  console.log('Electron ready, waiting for Next.js...');
  
  // Wait for Next.js to be ready
  await waitForNextJS();
  
  // Initialize scraper
  scraperEngine = new ScraperEngine();
  await scraperEngine.initialize();
  console.log('Scraper engine initialized');
  
  // Create window
  createWindow();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', async () => {
  if (scraperEngine) {
    await scraperEngine.cleanup();
  }
});

// IPC Handlers
ipcMain.handle('create-job', async (event, jobData) => {
  const job = {
    id: uuidv4(),
    ...jobData,
    status: 'pending'
  };
  jobsInMemory[job.id] = job;
  dataInMemory[job.id] = [];
  console.log('Job created:', job.id);
  return { success: true, job };
});

ipcMain.handle('detect-patterns', async (event, url) => {
  console.log('Detecting patterns for:', url);
  try {
    const patterns = await scraperEngine.detectListPatterns(url);
    console.log('Found patterns:', patterns.length);
    return { success: true, patterns };
  } catch (error) {
    console.error('Pattern detection error:', error);
    return { success: false, error: error.message };
  }
});

ipcMain.handle('start-scraping', async (event, jobId, config) => {
  console.log('Starting scraping for job:', jobId);
  try {
    const job = jobsInMemory[jobId];
    job.status = 'running';
    
    const result = await scraperEngine.scrapeList(job, config, (data) => {
      dataInMemory[jobId].push(data);
    });
    
    job.status = 'completed';
    console.log('Scraping completed. Items:', result.itemsScraped);
    return { success: true, result };
  } catch (error) {
    console.error('Scraping error:', error);
    return { success: false, error: error.message };
  }
});

ipcMain.handle('get-job-data', async (event, jobId) => {
  const data = dataInMemory[jobId] || [];
  console.log('Getting data for job:', jobId, '- Items:', data.length);
  return { success: true, data };
});
