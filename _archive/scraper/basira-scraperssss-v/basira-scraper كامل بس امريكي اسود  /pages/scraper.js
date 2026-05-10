import { useState, useEffect } from 'react';
import { useRouter } from 'next/router';

const ipcRenderer = typeof window !== 'undefined' && window.require 
  ? window.require('electron').ipcRenderer 
  : null;

export default function Scraper() {
  const router = useRouter();
  const { jobId, url } = router.query;
  
  const [patterns, setPatterns] = useState([]);
  const [selectedPattern, setSelectedPattern] = useState(null);
  const [fields, setFields] = useState([]);
  const [status, setStatus] = useState('idle');
  const [extractedData, setExtractedData] = useState([]);

  const detectPatterns = async () => {
    setStatus('detecting');
    const result = await ipcRenderer?.invoke('detect-patterns', url);
    if (result?.success) {
      setPatterns(result.patterns);
      if (result.patterns.length > 0) {
        setSelectedPattern(result.patterns[0]);
        setFields(result.patterns[0].detectedFields || []);
      }
    }
    setStatus('idle');
  };

  const startScraping = async () => {
    setStatus('scraping');
    const result = await ipcRenderer?.invoke('start-scraping', jobId, {
      listSelector: selectedPattern.selector,
      fields: fields.map((f, idx) => ({ id: `field-${idx}`, ...f }))
    });
    
    if (result?.success) {
      setStatus('completed');
      loadData();
    }
  };

  const loadData = async () => {
    const result = await ipcRenderer?.invoke('get-job-data', jobId);
    if (result?.success) {
      setExtractedData(result.data);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 flex">
      {/* Left Sidebar */}
      <aside className="w-80 border-r border-slate-800 p-6">
        <button 
          onClick={() => router.push('/')}
          className="mb-6 text-slate-400 hover:text-slate-300"
        >
          ← Back
        </button>

        <h2 className="text-lg font-semibold mb-4">Tools</h2>

        <div className="space-y-4">
          <button
            onClick={detectPatterns}
            disabled={status === 'detecting'}
            className="btn-primary w-full"
          >
            {status === 'detecting' ? 'Detecting...' : 'Detect Patterns'}
          </button>

          {patterns.length > 0 && (
            <div className="bg-slate-900 rounded-xl p-4">
              <h3 className="text-sm font-semibold mb-3">Patterns Found</h3>
              {patterns.map((pattern, idx) => (
                <button
                  key={idx}
                  onClick={() => {
                    setSelectedPattern(pattern);
                    setFields(pattern.detectedFields || []);
                  }}
                  className={`w-full p-3 rounded-lg mb-2 text-left ${
                    selectedPattern === pattern
                      ? 'bg-blue-500/20 border-2 border-blue-500/50'
                      : 'bg-slate-800 border border-slate-700'
                  }`}
                >
                  <div className="text-xs font-mono text-slate-400">{pattern.selector}</div>
                  <div className="text-sm">{pattern.itemCount} items</div>
                </button>
              ))}
            </div>
          )}

          {selectedPattern && (
            <div className="bg-slate-900 rounded-xl p-4">
              <h3 className="text-sm font-semibold mb-3">Fields ({fields.length})</h3>
              {fields.map((field, idx) => (
                <div key={idx} className="mb-2 p-2 bg-slate-800 rounded">
                  <div className="text-sm font-medium">{field.name}</div>
                  <div className="text-xs text-slate-500 truncate">{field.sample}</div>
                </div>
              ))}
            </div>
          )}

          {selectedPattern && (
            <button
              onClick={startScraping}
              disabled={status === 'scraping'}
              className="btn-primary w-full"
            >
              {status === 'scraping' ? 'Scraping...' : 'Start Extraction'}
            </button>
          )}

          {status === 'completed' && (
            <div className="bg-slate-900 rounded-xl p-4">
              <h3 className="text-sm font-semibold mb-2">Results</h3>
              <div className="text-3xl font-bold bg-gradient-to-r from-blue-400 to-teal-400 bg-clip-text text-transparent">
                {extractedData.length}
              </div>
              <div className="text-sm text-slate-400">items extracted</div>
              <button 
                onClick={loadData}
                className="mt-3 text-sm text-blue-400 hover:text-blue-300"
              >
                Refresh Data
              </button>
            </div>
          )}
        </div>
      </aside>

      {/* Main Content */}
      <div className="flex-1 p-6">
        <div className="bg-slate-900 rounded-xl p-6 h-full">
          <div className="flex items-center justify-between mb-6">
            <h1 className="text-xl font-semibold">Scraping: {url}</h1>
            <div className="text-sm text-slate-400">Status: {status}</div>
          </div>

          {extractedData.length > 0 && (
            <div className="bg-slate-800 rounded-lg p-4 max-h-96 overflow-y-auto">
              <h3 className="font-semibold mb-3">Extracted Data Preview</h3>
              <div className="space-y-2 text-sm">
                {extractedData.slice(0, 20).map((item, idx) => (
                  <div key={idx} className="p-2 bg-slate-900 rounded">
                    <span className="text-slate-400">{item.field_name}:</span>{' '}
                    <span className="text-slate-200">{item.value || 'N/A'}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
