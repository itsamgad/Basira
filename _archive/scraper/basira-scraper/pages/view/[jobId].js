import { useState, useEffect } from 'react';
import { useRouter } from 'next/router';

const DESIGN_CSS = `
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;700&family=Noto+Sans+Arabic:wght@300;400;600;700&display=swap');
:root{
  --bg:#f0f4f8;--surface:#ffffff;--surface-2:#f8fafc;--surface-glass:rgba(255,255,255,0.88);
  --accent:#0ea5e9;--accent-2:#6366f1;--accent-dim:rgba(14,165,233,0.10);--accent-glow:rgba(14,165,233,0.20);
  --success:#22c55e;--warning:#f59e0b;--danger:#ef4444;--purple:#8b5cf6;
  --text:#0f172a;--text-2:#334155;--text-dim:#64748b;--text-muted:#94a3b8;
  --border:#e2e8f0;--border-2:#cbd5e1;
  --mono:'JetBrains Mono',monospace;--sans:'Plus Jakarta Sans','Noto Sans Arabic',system-ui,sans-serif;
  --r:14px;--r-lg:20px;--shadow:0 1px 3px rgba(0,0,0,.06),0 2px 8px rgba(0,0,0,.04);
  --shadow-md:0 4px 16px rgba(0,0,0,.07);--shadow-lg:0 12px 40px rgba(0,0,0,.10);
  --tr:.18s cubic-bezier(.4,0,.2,1);
}
[data-theme="dark"]{
  --bg:#080e1a;--surface:#111827;--surface-2:#1a2332;--surface-glass:rgba(17,24,39,0.92);
  --accent:#38bdf8;--accent-dim:rgba(56,189,248,0.12);--accent-glow:rgba(56,189,248,0.22);
  --text:#f1f5f9;--text-2:#e2e8f0;--text-dim:#94a3b8;--text-muted:#64748b;
  --border:rgba(255,255,255,0.07);--border-2:rgba(255,255,255,0.13);
  --shadow:0 1px 3px rgba(0,0,0,.3),0 2px 8px rgba(0,0,0,.2);
  --shadow-md:0 4px 20px rgba(0,0,0,.35);--shadow-lg:0 12px 48px rgba(0,0,0,.45);
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;outline:none;}
html{font-size:16px;-webkit-font-smoothing:antialiased;}
body{font-family:var(--sans);background:var(--bg);color:var(--text);transition:background var(--tr),color var(--tr);}
.bs-nav{height:64px;display:flex;align-items:center;justify-content:space-between;padding:0 5%;background:var(--surface-glass);backdrop-filter:blur(28px);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:1000;gap:16px;}
.bs-brand{font-weight:800;color:var(--accent);font-size:1.45rem;letter-spacing:-1px;font-family:var(--mono);}
.bs-nav-actions{display:flex;align-items:center;gap:8px;}
.bs-icon-btn{width:36px;height:36px;border-radius:10px;border:1px solid var(--border);background:transparent;color:var(--text-dim);cursor:pointer;display:flex;align-items:center;justify-content:center;transition:var(--tr);font-size:15px;}
.bs-icon-btn:hover{background:var(--accent-dim);color:var(--accent);border-color:var(--accent);}
.bs-btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:11px 22px;border-radius:var(--r);font-family:var(--sans);font-weight:700;font-size:.9rem;cursor:pointer;border:1.5px solid transparent;transition:var(--tr);white-space:nowrap;}
.bs-btn-primary{background:var(--accent);color:#fff;border-color:var(--accent);}
.bs-btn-primary:hover{filter:brightness(1.08);}
.bs-btn-ghost{background:var(--surface-2);border-color:var(--border-2);color:var(--text-dim);}
.bs-btn-ghost:hover{border-color:var(--accent);color:var(--accent);background:var(--accent-dim);}
.bs-btn-full{width:100%;}
.bs-input{width:100%;padding:12px 16px;border-radius:var(--r);background:var(--surface-2);border:1.5px solid var(--border);color:var(--text);font-family:var(--sans);font-size:.95rem;transition:var(--tr);}
.bs-input:focus{border-color:var(--accent);}
.bs-sidebar{width:220px;min-width:220px;background:var(--surface);border-inline-end:1px solid var(--border);padding:20px 16px;display:flex;flex-direction:column;gap:18px;overflow-y:auto;}
.bs-sidebar-section-title{font-size:.65rem;font-weight:800;color:var(--text-muted);letter-spacing:1.2px;text-transform:uppercase;margin-bottom:8px;}
.bs-stat-row{display:flex;justify-content:space-between;align-items:center;padding:9px 12px;background:var(--surface-2);border-radius:10px;border:1px solid var(--border);}
.bs-stat-label{font-size:.75rem;color:var(--text-dim);}
.bs-stat-value{font-size:.88rem;font-weight:800;font-family:var(--mono);}
.bs-field-chip{padding:8px 12px;background:var(--surface-2);border-radius:10px;border:1px solid var(--border);font-size:.78rem;color:var(--text);display:flex;align-items:center;gap:8px;}
.bs-results-layout{display:flex;flex:1;overflow:hidden;height:calc(100vh - 64px);}
.bs-results-main{flex:1;overflow:auto;padding:24px 28px;}
.bs-table-wrap{border-radius:var(--r-lg);border:1px solid var(--border);overflow:hidden;box-shadow:var(--shadow);}
.bs-table{width:100%;border-collapse:collapse;font-size:.8rem;}
.bs-table th{color:var(--accent);text-align:start;padding:11px 14px;border-bottom:2px solid var(--border);font-family:var(--mono);font-size:.72rem;background:var(--accent-dim);white-space:nowrap;cursor:pointer;user-select:none;}
.bs-table th:hover{background:var(--accent-glow);}
.bs-table td{padding:10px 14px;border-bottom:1px solid var(--border);vertical-align:middle;}
.bs-table tr:hover td{background:var(--accent-dim);}
.bs-table tr:last-child td{border-bottom:none;}
.bs-search-row{display:flex;align-items:center;gap:12px;margin-bottom:14px;}
.bs-count-badge{font-size:.75rem;color:var(--text-muted);font-family:var(--mono);flex-shrink:0;}
.bs-empty{padding:40px;text-align:center;color:var(--text-muted);font-size:.86rem;}
.bs-badge{display:inline-flex;align-items:center;gap:5px;padding:3px 10px;border-radius:18px;background:var(--accent-dim);color:var(--accent);font-size:.66rem;font-weight:800;border:1px solid rgba(14,165,233,.2);}
.bs-spinner{width:56px;height:56px;border-radius:50%;border:3px solid var(--border);border-top-color:var(--accent);animation:bs-spin 1s linear infinite;}
@keyframes bs-spin{to{transform:rotate(360deg)}}
::-webkit-scrollbar{width:5px;height:5px;}
::-webkit-scrollbar-track{background:transparent;}
::-webkit-scrollbar-thumb{background:var(--border-2);border-radius:10px;}
::-webkit-scrollbar-thumb:hover{background:var(--accent);}
`;

const typeIcon = { image: '🖼', link: '🔗', price: '💰', text: '📝' };

export default function ViewPage() {
  const router = useRouter();
  const { jobId } = router.query;
  const [data, setData] = useState([]);
  const [fields, setFields] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [sortCol, setSortCol] = useState(null);
  const [sortDir, setSortDir] = useState('asc');

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', 'dark');
    if (!jobId) return;
    fetch('/api/scraper?action=get-data&jobId=' + jobId)
      .then(r => r.json())
      .then(result => {
        if (result.success) { setData(result.data); setFields(result.fields || []); }
        else setError('Data not found — this scrape may have been cleared.');
        setLoading(false);
      })
      .catch(() => { setError('Failed to load data.'); setLoading(false); });
  }, [jobId]);

  const tableRows = (() => {
    const map = {};
    data.forEach(item => {
      if (!map[item.item_index]) map[item.item_index] = {};
      map[item.item_index][item.field_name] = item.value;
    });
    return Object.values(map);
  })();

  const filteredRows = tableRows
    .filter(row => !search || fields.some(f => (row[f.name] || '').toLowerCase().includes(search.toLowerCase())))
    .sort((a, b) => {
      if (!sortCol) return 0;
      const av = (a[sortCol] || '').toLowerCase(), bv = (b[sortCol] || '').toLowerCase();
      const an = parseFloat(av), bn = parseFloat(bv);
      const cmp = !isNaN(an) && !isNaN(bn) ? an - bn : av.localeCompare(bv);
      return sortDir === 'asc' ? cmp : -cmp;
    });

  const renderCell = (field, row) => {
    const val = row[field.name];
    if (!val || val === 'N/A') return <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>—</span>;
    if (field.type === 'image') return (
      <a href={val} target="_blank" rel="noreferrer">
        <img src={val} alt="" style={{ width: 48, height: 48, objectFit: 'cover', borderRadius: 8, display: 'block' }}
          onError={e => { e.target.style.display = 'none'; }} />
      </a>
    );
    if (field.type === 'link') return (
      <a href={val} target="_blank" rel="noreferrer"
        style={{ color: 'var(--accent)', textDecoration: 'none', fontSize: '.78rem', display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 200 }}>
        🔗 {val.replace(/^https?:\/\//, '').substring(0, 40)}
      </a>
    );
    if (field.type === 'price') return <span style={{ color: 'var(--success)', fontWeight: 800, fontFamily: 'var(--mono)' }}>{val}</span>;
    return <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block' }}>{val}</span>;
  };

  const exportCSV = () => {
    const h = fields.map(f => f.name);
    const csv = [h.join(','), ...filteredRows.map(r => h.map(k => '"' + (r[k] || '').replace(/"/g, '""') + '"').join(','))].join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' }));
    a.download = (jobId || 'basira') + '.csv'; a.click();
  };

  const exportExcel = () => {
    const script = document.createElement('script');
    script.src = 'https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js';
    script.onload = () => {
      const XLSX = window.XLSX;
      const h = fields.map(f => f.name);
      const wsData = [h, ...filteredRows.map(r => h.map(k => {
        const v = r[k] || '';
        const field = fields.find(f => f.name === k);
        if (field && field.type === 'price') return isNaN(parseFloat(v)) ? v : parseFloat(v);
        return v;
      }))];
      const ws = XLSX.utils.aoa_to_sheet(wsData);
      ws['!cols'] = h.map((_, i) => ({ wch: Math.min(Math.max(h[i].length, ...filteredRows.map(r => String(r[h[i]] || '').length)) + 2, 50) }));
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, 'Data');
      XLSX.writeFile(wb, (jobId || 'basira') + '.xlsx');
    };
    document.head.appendChild(script);
  };

  if (loading) return (
    <>
      <style dangerouslySetInnerHTML={{ __html: DESIGN_CSS }} />
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ textAlign: 'center' }}>
          <div className="bs-spinner" style={{ margin: '0 auto 20px' }} />
          <p style={{ color: 'var(--text-dim)', fontSize: '.86rem' }}>Loading data...</p>
        </div>
      </div>
    </>
  );

  if (error) return (
    <>
      <style dangerouslySetInnerHTML={{ __html: DESIGN_CSS }} />
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ textAlign: 'center', color: 'var(--danger)', fontSize: '.9rem' }}>⚠️ {error}</div>
      </div>
    </>
  );

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: DESIGN_CSS }} />
      <nav className="bs-nav">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <img src="/basira-logo.png" style={{ width: 32, height: 32, objectFit: 'contain' }} alt="logo" />
          <span className="bs-brand" style={{ fontSize: '1.1rem' }}>Basira Scraper</span>
          <span style={{ color: 'var(--text-muted)', fontSize: '.75rem' }}>· {filteredRows.length}/{tableRows.length} rows · {fields.length} fields</span>
        </div>
        <div className="bs-nav-actions">
          <button className="bs-btn bs-btn-ghost" onClick={exportCSV} style={{ padding: '8px 14px', fontSize: '.8rem', color: 'var(--success)', borderColor: 'rgba(34,197,94,.25)', background: 'rgba(34,197,94,.07)' }}>↓ CSV</button>
          <button className="bs-btn bs-btn-ghost" onClick={exportExcel} style={{ padding: '8px 14px', fontSize: '.8rem' }}>↓ Excel</button>
        </div>
      </nav>

      <div className="bs-results-layout">
        <aside className="bs-sidebar">
          <div style={{ background: 'rgba(34,197,94,.08)', border: '1px solid rgba(34,197,94,.2)', borderRadius: 12, padding: 14, textAlign: 'center' }}>
            <div style={{ fontSize: 22, marginBottom: 4 }}>✅</div>
            <div style={{ fontSize: '.72rem', fontWeight: 800, color: 'var(--success)', letterSpacing: '.5px' }}>EXTRACTION COMPLETE</div>
          </div>
          <div>
            <div className="bs-sidebar-section-title">SUMMARY</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {[
                { label: 'Rows', value: tableRows.length, color: 'var(--accent)' },
                { label: 'Filtered', value: filteredRows.length, color: search ? 'var(--warning)' : 'var(--accent)' },
                { label: 'Columns', value: fields.length, color: 'var(--purple)' },
                { label: 'Total Cells', value: data.length, color: 'var(--success)' },
              ].map((s, i) => (
                <div key={i} className="bs-stat-row">
                  <span className="bs-stat-label">{s.label}</span>
                  <span className="bs-stat-value" style={{ color: s.color }}>{s.value}</span>
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="bs-sidebar-section-title">FIELDS</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              {fields.map((f, i) => (
                <div key={i} className="bs-field-chip">
                  <span>{typeIcon[f.type] || '📝'}</span>{f.name}
                </div>
              ))}
            </div>
          </div>
          <div style={{ marginTop: 'auto' }}>
            <div className="bs-sidebar-section-title">EXPORT</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
              <button className="bs-btn bs-btn-primary bs-btn-full" onClick={exportCSV}>↓ Download CSV</button>
              <button className="bs-btn bs-btn-ghost bs-btn-full" onClick={exportExcel}>↓ Download Excel</button>
            </div>
          </div>
        </aside>

        <main className="bs-results-main">
          <div className="bs-search-row">
            <input className="bs-input" type="text" placeholder="🔍 Search..." value={search}
              onChange={e => setSearch(e.target.value)} style={{ direction: 'ltr' }} />
            <span className="bs-count-badge">{filteredRows.length} / {tableRows.length}</span>
          </div>
          <div className="bs-table-wrap">
            <table className="bs-table">
              <thead>
                <tr>
                  <th style={{ width: 40 }}>#</th>
                  {fields.map((f, i) => (
                    <th key={i} onClick={() => { setSortCol(f.name); setSortDir(sortCol === f.name && sortDir === 'asc' ? 'desc' : 'asc'); }}>
                      {typeIcon[f.type] || ''} {f.name} {sortCol === f.name ? (sortDir === 'asc' ? '↑' : '↓') : <span style={{ opacity: .35 }}>↕</span>}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((row, ri) => (
                  <tr key={ri}>
                    <td style={{ color: 'var(--text-muted)', fontFamily: 'var(--mono)', fontSize: '.72rem' }}>{ri + 1}</td>
                    {fields.map((f, fi) => (
                      <td key={fi} style={{ maxWidth: 240 }}>{renderCell(f, row)}</td>
                    ))}
                  </tr>
                ))}
                {filteredRows.length === 0 && (
                  <tr><td colSpan={fields.length + 1} className="bs-empty">No results for "{search}"</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </main>
      </div>
    </>
  );
}
