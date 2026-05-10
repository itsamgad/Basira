import { useState, useEffect } from 'react';

export default function Home() {
  const [url, setUrl] = useState('');
  const [showScraper, setShowScraper] = useState(false);
  const [jobId] = useState(() => 'job-' + Date.now());

  const handleStart = () => {
    if (!url) { alert('Please enter a URL'); return; }
    setShowScraper(true);
  };

  if (showScraper) {
    return <ScraperInterface url={url} jobId={jobId} onBack={() => setShowScraper(false)} />;
  }

  return (
    <div style={{ background: '#020617', minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px', fontFamily: 'system-ui, sans-serif' }}>
      <div style={{ maxWidth: '1024px', width: '100%' }}>
        <div style={{ textAlign: 'center', marginBottom: '48px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '16px', marginBottom: '24px' }}>
            <img src="/basira-logo.png" style={{ width: '64px', height: '64px', borderRadius: '16px', background: 'linear-gradient(135deg,#3b82f6,#14b8a6)', padding: '10px', objectFit: 'contain' }} />
            <h1 style={{ fontSize: '52px', fontWeight: 'bold', margin: 0, background: 'linear-gradient(to right, #60a5fa, #5eead4)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
              Basira Scraper
            </h1>
          </div>
          <p style={{ fontSize: '18px', color: '#94a3b8', marginBottom: '40px' }}>Extract structured data from any website — visually, no code needed</p>

          <div style={{ background: 'rgba(15,23,42,0.6)', backdropFilter: 'blur(12px)', borderRadius: '16px', padding: '24px', border: '1px solid #1e293b', marginBottom: '28px' }}>
            <div style={{ display: 'flex', gap: '12px' }}>
              <input type="url" placeholder="https://example.com" value={url}
                onChange={(e) => setUrl(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && handleStart()}
                style={{ flex: 1, fontSize: '16px', padding: '14px 16px', borderRadius: '12px', background: '#0f172a', border: '1px solid #334155', color: '#f1f5f9', outline: 'none' }} />
              <button onClick={handleStart}
                style={{ padding: '14px 40px', fontSize: '16px', fontWeight: '700', color: 'white', background: 'linear-gradient(to right,#3b82f6,#14b8a6)', borderRadius: '12px', border: 'none', cursor: 'pointer', whiteSpace: 'nowrap' }}>
                Start →
              </button>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: '12px' }}>
            {[{label:'JS', desc:'Full JS Support'},{label:'EN/AR', desc:'Bilingual'},{label:'Visual', desc:'Point & Click'},{label:'Fast', desc:'All Load Methods'}].map((s,i) => (
              <div key={i} style={{ background: 'rgba(15,23,42,0.5)', borderRadius: '12px', padding: '16px', border: '1px solid #1e293b' }}>
                <div style={{ fontSize: '24px', fontWeight: 'bold', background: 'linear-gradient(to right,#60a5fa,#5eead4)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', marginBottom: '4px' }}>{s.label}</div>
                <div style={{ fontSize: '12px', color: '#64748b' }}>{s.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function ScraperInterface({ url, jobId, onBack }) {
  const [status, setStatus] = useState('opening');
  const [extractedData, setExtractedData] = useState([]);
  const [fields, setFields] = useState([]);
  const [itemCount, setItemCount] = useState(0);

  useEffect(() => { openBrowser(); }, []);

  const openBrowser = async () => {
    setStatus('opening');
    const res = await fetch('/api/scraper?action=open-browser', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, jobId })
    });
    const result = await res.json();
    if (result.success) { setStatus('selecting'); checkSelection(); }
  };

  const checkSelection = async () => {
    const interval = setInterval(async () => {
      const res = await fetch(`/api/scraper?action=check-selection&jobId=${jobId}`);
      const result = await res.json();
      if (result.cancelled) { clearInterval(interval); onBack(); }
      else if (result.completed) { clearInterval(interval); setStatus('extracting'); extractData(); }
    }, 1000);
  };

  const extractData = async () => {
    const res = await fetch('/api/scraper?action=extract-data', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jobId })
    });
    const result = await res.json();
    if (result.success) {
      setItemCount(result.itemsScraped);
      setFields(result.fields || []);
      setStatus('completed');
      loadData();
    }
  };

  const loadData = async () => {
    const res = await fetch(`/api/scraper?action=get-data&jobId=${jobId}`);
    const result = await res.json();
    if (result.success) setExtractedData(result.data);
  };

  const getTableData = () => {
    const itemsByIndex = {};
    extractedData.forEach(item => {
      if (!itemsByIndex[item.item_index]) itemsByIndex[item.item_index] = {};
      itemsByIndex[item.item_index][item.field_name] = item.value;
    });
    return Object.values(itemsByIndex);
  };

  const exportCSV = () => {
    const rows = getTableData();
    if (!rows.length) return;
    const headers = fields.map(f => f.name);
    const csvContent = [
      headers.join(','),
      ...rows.map(row => headers.map(h => `"${(row[h] || '').replace(/"/g, '\"')}"` ).join(','))
    ].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `basira-export-${Date.now()}.csv`;
    a.click();
  };

  const exportExcel = () => {
    const rows = getTableData();
    if (!rows.length) return;
    const headers = fields.map(f => f.name);
    // Build HTML table that Excel can open
    const table = `<table><tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr>${rows.map(row => `<tr>${headers.map(h => `<td>${row[h] || ''}</td>`).join('')}</tr>`).join('')}</table>`;
    const blob = new Blob([`<html><body>${table}</body></html>`], { type: 'application/vnd.ms-excel' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `basira-export-${Date.now()}.xls`;
    a.click();
  };

  const tableRows = getTableData();
  const totalCells = extractedData.length;
  const naCount = extractedData.filter(d => d.value === 'N/A' || !d.value).length;
  const fillRate = totalCells > 0 ? Math.round(((totalCells - naCount) / totalCells) * 100) : 0;
  const hostname = (() => { try { return new URL(url).hostname; } catch(e) { return url; } })();

  const StatusScreen = () => (
    <div style={{ minHeight: '100vh', background: '#020617', display: 'flex', flexDirection: 'column', fontFamily: 'system-ui, sans-serif' }}>
      <header style={{ padding: '16px 24px', borderBottom: '1px solid #1e293b', display: 'flex', alignItems: 'center', gap: '12px' }}>
        <img src="/basira-logo.png" style={{ width: '36px', height: '36px', borderRadius: '8px', background: 'linear-gradient(135deg,#3b82f6,#14b8a6)', padding: '5px', objectFit: 'contain' }} />
        <span style={{ fontWeight: '700', fontSize: '16px', color: '#60a5fa' }}>Basira Scraper</span>
        <button onClick={onBack} style={{ marginLeft: 'auto', color: '#64748b', background: 'none', border: 'none', cursor: 'pointer', fontSize: '13px' }}>← Back</button>
      </header>
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '48px' }}>
        <div style={{ textAlign: 'center', maxWidth: '480px' }}>
          {status === 'opening' && <>
            <div style={{ width: '72px', height: '72px', margin: '0 auto 24px', border: '3px solid #1e293b', borderTop: '3px solid #3b82f6', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
            <h2 style={{ fontSize: '22px', color: '#f1f5f9', marginBottom: '8px' }}>Opening Browser...</h2>
            <p style={{ color: '#64748b', fontSize: '14px' }}>Loading {hostname}</p>
          </>}
          {status === 'selecting' && <>
            <div style={{ width: '72px', height: '72px', margin: '0 auto 24px', background: 'linear-gradient(135deg,#3b82f6,#14b8a6)', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '36px' }}>🖱️</div>
            <h2 style={{ fontSize: '22px', color: '#f1f5f9', marginBottom: '12px' }}>Visual Selection Active</h2>
            <p style={{ color: '#64748b', fontSize: '14px', lineHeight: '1.7', marginBottom: '20px' }}>The browser is open. Click any item on the page, then SHIFT+Click fields to extract, then click Extract.</p>
            <div style={{ padding: '12px 20px', background: 'rgba(59,130,246,0.08)', border: '1px solid rgba(59,130,246,0.2)', borderRadius: '8px', color: '#60a5fa', fontSize: '13px' }}>⏳ Waiting for your selection...</div>
          </>}
          {status === 'extracting' && <>
            <div style={{ width: '72px', height: '72px', margin: '0 auto 24px', border: '3px solid #1e293b', borderTop: '3px solid #10b981', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
            <h2 style={{ fontSize: '22px', color: '#f1f5f9', marginBottom: '8px' }}>Extracting Data...</h2>
            <p style={{ color: '#64748b', fontSize: '14px' }}>Collecting all items across pages</p>
          </>}
        </div>
      </div>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );

  if (status !== 'completed') return <StatusScreen />;

  return (
    <div style={{ minHeight: '100vh', background: '#020617', display: 'flex', flexDirection: 'column', fontFamily: 'system-ui, sans-serif' }}>
      {/* Header */}
      <header style={{ padding: '14px 28px', borderBottom: '1px solid #1e293b', display: 'flex', alignItems: 'center', gap: '12px', background: 'rgba(2,6,23,0.95)', backdropFilter: 'blur(8px)', position: 'sticky', top: 0, zIndex: 10 }}>
        <img src="/basira-logo.png" style={{ width: '36px', height: '36px', borderRadius: '8px', background: 'linear-gradient(135deg,#3b82f6,#14b8a6)', padding: '5px', objectFit: 'contain' }} />
        <span style={{ fontWeight: '700', fontSize: '16px', color: '#60a5fa' }}>Basira Scraper</span>
        <span style={{ color: '#334155', margin: '0 4px' }}>·</span>
        <span style={{ fontSize: '13px', color: '#64748b' }}>{hostname}</span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: '10px', alignItems: 'center' }}>
          <button onClick={exportCSV} style={{ padding: '8px 16px', fontSize: '13px', fontWeight: '600', color: '#10b981', background: 'rgba(16,185,129,0.1)', border: '1px solid rgba(16,185,129,0.3)', borderRadius: '8px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}>
            ↓ CSV
          </button>
          <button onClick={exportExcel} style={{ padding: '8px 16px', fontSize: '13px', fontWeight: '600', color: '#3b82f6', background: 'rgba(59,130,246,0.1)', border: '1px solid rgba(59,130,246,0.3)', borderRadius: '8px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}>
            ↓ Excel
          </button>
          <button onClick={onBack} style={{ padding: '8px 16px', fontSize: '13px', color: '#64748b', background: 'none', border: '1px solid #1e293b', borderRadius: '8px', cursor: 'pointer' }}>← New Scrape</button>
        </div>
      </header>

      <div style={{ display: 'flex', flex: 1, gap: 0 }}>
        {/* Sidebar */}
        <aside style={{ width: '260px', minWidth: '260px', borderRight: '1px solid #1e293b', padding: '24px 20px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {/* Success badge */}
          <div style={{ background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.2)', borderRadius: '12px', padding: '16px', textAlign: 'center' }}>
            <div style={{ fontSize: '28px', marginBottom: '6px' }}>✅</div>
            <div style={{ fontSize: '13px', fontWeight: '600', color: '#10b981' }}>Extraction Complete</div>
          </div>

          {/* Stats */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div style={{ fontSize: '11px', fontWeight: '700', color: '#475569', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: '2px' }}>Summary</div>
            {[
              { label: 'Rows', value: itemCount, color: '#60a5fa' },
              { label: 'Columns', value: fields.length, color: '#a78bfa' },
              { label: 'Total Cells', value: totalCells, color: '#34d399' },
              { label: 'Fill Rate', value: fillRate + '%', color: fillRate >= 80 ? '#10b981' : '#f59e0b' },
            ].map((stat, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', background: '#0f172a', borderRadius: '8px', border: '1px solid #1e293b' }}>
                <span style={{ fontSize: '13px', color: '#94a3b8' }}>{stat.label}</span>
                <span style={{ fontSize: '15px', fontWeight: '700', color: stat.color }}>{stat.value}</span>
              </div>
            ))}
          </div>

          {/* Fields list */}
          <div>
            <div style={{ fontSize: '11px', fontWeight: '700', color: '#475569', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: '8px' }}>Fields</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {fields.map((f, i) => (
                <div key={i} style={{ padding: '8px 12px', background: '#0f172a', borderRadius: '8px', border: '1px solid #1e293b', fontSize: '13px', color: '#cbd5e1', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: 'linear-gradient(135deg,#3b82f6,#14b8a6)', flexShrink: 0 }} />
                  {f.name}
                </div>
              ))}
            </div>
          </div>

          {/* Export buttons */}
          <div style={{ marginTop: 'auto' }}>
            <div style={{ fontSize: '11px', fontWeight: '700', color: '#475569', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: '8px' }}>Export</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <button onClick={exportCSV} style={{ padding: '10px', fontSize: '13px', fontWeight: '600', color: 'white', background: 'linear-gradient(to right,#10b981,#14b8a6)', border: 'none', borderRadius: '8px', cursor: 'pointer' }}>
                ↓ Download CSV
              </button>
              <button onClick={exportExcel} style={{ padding: '10px', fontSize: '13px', fontWeight: '600', color: 'white', background: 'linear-gradient(to right,#3b82f6,#6366f1)', border: 'none', borderRadius: '8px', cursor: 'pointer' }}>
                ↓ Download Excel
              </button>
            </div>
          </div>
        </aside>

        {/* Main table area */}
        <main style={{ flex: 1, overflow: 'auto', padding: '24px 28px' }}>
          <div style={{ marginBottom: '16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <h2 style={{ fontSize: '16px', fontWeight: '600', color: '#f1f5f9', margin: 0 }}>
              Extracted Data <span style={{ color: '#475569', fontWeight: '400', fontSize: '14px' }}>({tableRows.length} rows)</span>
            </h2>
          </div>

          <div style={{ borderRadius: '12px', border: '1px solid #1e293b', overflow: 'hidden' }}>
            <div style={{ overflowX: 'auto', maxHeight: 'calc(100vh - 180px)', overflowY: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
                <thead>
                  <tr style={{ background: '#0f172a', position: 'sticky', top: 0, zIndex: 1 }}>
                    <th style={{ padding: '12px 16px', textAlign: 'left', color: '#475569', fontWeight: '600', borderBottom: '1px solid #1e293b', whiteSpace: 'nowrap' }}>#</th>
                    {fields.map((field, idx) => (
                      <th key={idx} style={{ padding: '12px 16px', textAlign: 'left', color: '#60a5fa', fontWeight: '600', borderBottom: '1px solid #1e293b', whiteSpace: 'nowrap' }}>
                        {field.name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {tableRows.map((row, rowIdx) => (
                    <tr key={rowIdx} style={{ borderBottom: '1px solid #0f172a', background: rowIdx % 2 === 0 ? '#020617' : '#0a1020' }}>
                      <td style={{ padding: '10px 16px', color: '#334155', fontWeight: '600', fontSize: '12px' }}>{rowIdx + 1}</td>
                      {fields.map((field, fieldIdx) => (
                        <td key={fieldIdx} style={{ padding: '10px 16px', color: row[field.name] && row[field.name] !== 'N/A' ? '#e2e8f0' : '#334155', maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {row[field.name] || <span style={{ color: '#334155', fontStyle: 'italic' }}>N/A</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
