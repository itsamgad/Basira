import { useState, useEffect, useRef } from 'react';

// ── Design System CSS ────────────────────────────────────────────────────────
const DESIGN_CSS = `
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;700&family=Noto+Sans+Arabic:wght@300;400;600;700&display=swap');

:root{
  --bg:#f0f4f8;--surface:#ffffff;--surface-2:#f8fafc;
  --surface-glass:rgba(255,255,255,0.88);
  --accent:#0ea5e9;--accent-2:#6366f1;
  --accent-dim:rgba(14,165,233,0.10);--accent-glow:rgba(14,165,233,0.20);
  --success:#22c55e;--warning:#f59e0b;--danger:#ef4444;--purple:#8b5cf6;
  --text:#0f172a;--text-2:#334155;--text-dim:#64748b;--text-muted:#94a3b8;
  --border:#e2e8f0;--border-2:#cbd5e1;
  --mono:'JetBrains Mono',monospace;
  --sans:'Plus Jakarta Sans','Noto Sans Arabic',system-ui,sans-serif;
  --r:14px;--r-lg:20px;--r-xl:26px;
  --shadow:0 1px 3px rgba(0,0,0,.06),0 2px 8px rgba(0,0,0,.04);
  --shadow-md:0 4px 16px rgba(0,0,0,.07);
  --shadow-lg:0 12px 40px rgba(0,0,0,.10);
  --tr:.18s cubic-bezier(.4,0,.2,1);
}
[data-theme="dark"]{
  --bg:#080e1a;--surface:#111827;--surface-2:#1a2332;
  --surface-glass:rgba(17,24,39,0.92);
  --accent:#38bdf8;--accent-dim:rgba(56,189,248,0.12);--accent-glow:rgba(56,189,248,0.22);
  --text:#f1f5f9;--text-2:#e2e8f0;--text-dim:#94a3b8;--text-muted:#64748b;
  --border:rgba(255,255,255,0.07);--border-2:rgba(255,255,255,0.13);
  --shadow:0 1px 3px rgba(0,0,0,.3),0 2px 8px rgba(0,0,0,.2);
  --shadow-md:0 4px 20px rgba(0,0,0,.35);--shadow-lg:0 12px 48px rgba(0,0,0,.45);
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;outline:none;}
html{font-size:16px;-webkit-font-smoothing:antialiased;}
body{font-family:var(--sans);background:var(--bg);color:var(--text);transition:background var(--tr),color var(--tr);}

/* Nav */
.bs-nav{
  height:64px;display:flex;align-items:center;justify-content:space-between;
  padding:0 5%;background:var(--surface-glass);backdrop-filter:blur(28px);
  border-bottom:1px solid var(--border);position:sticky;top:0;z-index:1000;gap:16px;
}
.bs-brand{font-weight:800;color:var(--accent);font-size:1.45rem;letter-spacing:-1px;font-family:var(--mono);}
[dir="rtl"] .bs-brand{font-size:1.55rem;letter-spacing:0;font-family:'Noto Sans Arabic',var(--sans);}
.bs-nav-actions{display:flex;align-items:center;gap:8px;}
.bs-icon-btn{
  width:36px;height:36px;border-radius:10px;border:1px solid var(--border);
  background:transparent;color:var(--text-dim);cursor:pointer;
  display:flex;align-items:center;justify-content:center;transition:var(--tr);
  font-size:15px;
}
.bs-icon-btn:hover{background:var(--accent-dim);color:var(--accent);border-color:var(--accent);}

/* Page */
.bs-page{min-height:calc(100vh - 64px);padding:36px 5% 48px;display:flex;flex-direction:column;gap:24px;}

/* Cards */
.bs-card{
  background:var(--surface);border:1px solid var(--border);
  border-radius:var(--r-lg);padding:24px 28px;box-shadow:var(--shadow);
}

/* Buttons */
.bs-btn{
  display:inline-flex;align-items:center;justify-content:center;gap:8px;
  padding:11px 22px;border-radius:var(--r);font-family:var(--sans);
  font-weight:700;font-size:.9rem;cursor:pointer;
  border:1.5px solid transparent;transition:var(--tr);white-space:nowrap;
}
.bs-btn-primary{background:var(--accent);color:#fff;border-color:var(--accent);}
.bs-btn-primary:hover{filter:brightness(1.08);}
.bs-btn-primary:active{transform:scale(.98);}
.bs-btn-ghost{background:var(--surface-2);border-color:var(--border-2);color:var(--text-dim);}
.bs-btn-ghost:hover{border-color:var(--accent);color:var(--accent);background:var(--accent-dim);}
.bs-btn-full{width:100%;}

/* Inputs */
.bs-input{
  width:100%;padding:12px 16px;border-radius:var(--r);
  background:var(--surface-2);border:1.5px solid var(--border);
  color:var(--text);font-family:var(--sans);font-size:.95rem;transition:var(--tr);
}
.bs-input:focus{border-color:var(--accent);}
.bs-input.error{border-color:var(--danger);}
.bs-input-sm{padding:10px 14px;font-size:.86rem;}

/* Error banner */
.bs-error-banner{
  display:flex;align-items:center;gap:10px;
  padding:11px 16px;background:rgba(239,68,68,.07);
  border:1px solid rgba(239,68,68,.22);border-radius:var(--r);
  font-size:.83rem;color:var(--danger);font-weight:600;
}

/* Toggle */
.bs-toggle{
  width:42px;height:24px;border-radius:99px;cursor:pointer;
  position:relative;transition:background var(--tr);flex-shrink:0;border:none;
}
.bs-toggle-thumb{
  position:absolute;top:3px;width:18px;height:18px;
  border-radius:50%;background:white;transition:left var(--tr);
}

/* Feature cards */
.bs-feat-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;}
.bs-feat-card{
  background:var(--surface);border:1px solid var(--border);
  border-radius:var(--r-lg);padding:18px;box-shadow:var(--shadow);transition:var(--tr);
}
.bs-feat-card:hover{transform:translateY(-3px);box-shadow:var(--shadow-md);border-color:var(--accent);}
.bs-feat-label{font-size:1.1rem;font-weight:800;color:var(--accent);font-family:var(--mono);margin-bottom:4px;}
.bs-feat-desc{font-size:.75rem;color:var(--text-muted);}

/* History */
.bs-history-item{
  background:var(--surface);border:1px solid var(--border);
  border-radius:var(--r-lg);padding:16px 18px;
  display:flex;align-items:center;gap:14px;
  transition:var(--tr);box-shadow:var(--shadow);
}
.bs-history-item:hover{border-color:var(--accent);box-shadow:var(--shadow-md);}
.bs-history-icon{
  width:42px;height:42px;border-radius:12px;
  background:var(--accent-dim);border:1px solid var(--border);
  display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0;
}
.bs-history-meta{font-size:.75rem;color:var(--text-dim);margin-top:2px;}

/* Sidebar */
.bs-sidebar{
  width:220px;min-width:220px;background:var(--surface);
  border-inline-end:1px solid var(--border);
  padding:20px 16px;display:flex;flex-direction:column;gap:18px;overflow-y:auto;
}
.bs-sidebar-section-title{
  font-size:.65rem;font-weight:800;color:var(--text-muted);
  letter-spacing:1.2px;text-transform:uppercase;margin-bottom:8px;
}
.bs-stat-row{
  display:flex;justify-content:space-between;align-items:center;
  padding:9px 12px;background:var(--surface-2);
  border-radius:10px;border:1px solid var(--border);
}
.bs-stat-label{font-size:.75rem;color:var(--text-dim);}
.bs-stat-value{font-size:.88rem;font-weight:800;font-family:var(--mono);}
.bs-field-chip{
  padding:8px 12px;background:var(--surface-2);border-radius:10px;
  border:1px solid var(--border);font-size:.78rem;color:var(--text);
  display:flex;align-items:center;gap:8px;
}

/* Results table */
.bs-table-wrap{border-radius:var(--r-lg);border:1px solid var(--border);overflow:hidden;box-shadow:var(--shadow);}
.bs-table{width:100%;border-collapse:collapse;font-size:.8rem;}
.bs-table th{
  color:var(--accent);text-align:start;padding:11px 14px;
  border-bottom:2px solid var(--border);font-family:var(--mono);font-size:.72rem;
  background:var(--accent-dim);white-space:nowrap;cursor:pointer;user-select:none;
}
.bs-table th:hover{background:var(--accent-glow);}
.bs-table td{padding:10px 14px;border-bottom:1px solid var(--border);vertical-align:middle;}
.bs-table tr:hover td{background:var(--accent-dim);}
.bs-table tr:last-child td{border-bottom:none;}

/* Spinner */
.bs-spinner{
  width:56px;height:56px;border-radius:50%;
  border:3px solid var(--border);border-top-color:var(--accent);
  animation:bs-spin 1s linear infinite;
}
@keyframes bs-spin{to{transform:rotate(360deg)}}
@keyframes bs-pulse{0%,100%{opacity:1}50%{opacity:.5}}

/* Progress bar */
.bs-progress-track{height:6px;background:var(--border);border-radius:99px;overflow:hidden;}
.bs-progress-fill{
  height:100%;border-radius:99px;
  background:linear-gradient(to right,var(--accent),var(--success));
  animation:bs-pulse 2s ease-in-out infinite;
  transition:width .8s ease;
}

/* Status badge */
.bs-badge{
  display:inline-flex;align-items:center;gap:5px;
  padding:3px 10px;border-radius:18px;
  font-size:.66rem;font-weight:800;letter-spacing:.5px;
  background:var(--accent-dim);color:var(--accent);border:1px solid rgba(14,165,233,.2);
}

/* Advanced panel */
.bs-advanced-panel{
  margin-top:14px;display:flex;flex-direction:column;gap:10px;
  padding:16px;background:var(--surface-2);border-radius:var(--r-lg);border:1px solid var(--border);
}
.bs-toggle-row{
  display:flex;align-items:center;justify-content:space-between;
  padding:12px 16px;background:var(--surface);border-radius:var(--r);
  border:1.5px solid var(--border);transition:var(--tr);
}
.bs-toggle-row.active{border-color:var(--accent);background:var(--accent-dim);}
.bs-toggle-row-label{font-size:.86rem;font-weight:700;color:var(--text);}
.bs-toggle-row-desc{font-size:.72rem;color:var(--text-dim);margin-top:2px;}

/* Proxy inputs */
.bs-proxy-grid{display:flex;flex-direction:column;gap:8px;margin-top:10px;}
.bs-input-row{display:flex;gap:8px;}
select.bs-input{cursor:pointer;}

/* Section header */
.bs-section-head{
  display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;
}
.bs-section-title{
  font-size:.72rem;font-weight:800;color:var(--text-muted);
  letter-spacing:1.2px;text-transform:uppercase;
}

/* Loading center */
.bs-center{min-height:calc(100vh - 64px);display:flex;flex-direction:column;}
.bs-loading-box{
  flex:1;display:flex;align-items:center;justify-content:center;
}
.bs-loading-inner{text-align:center;max-width:420px;padding:48px 24px;}
.bs-loading-title{font-size:1.3rem;font-weight:800;color:var(--text);margin-bottom:10px;}
.bs-loading-sub{font-size:.86rem;color:var(--text-dim);line-height:1.7;}
.bs-status-card{
  background:var(--surface-2);border:1px solid var(--border);
  border-radius:var(--r-lg);padding:20px;margin-top:24px;text-align:left;
}
.bs-selecting-hint{
  padding:12px 18px;background:var(--accent-dim);
  border:1px solid rgba(14,165,233,.2);border-radius:var(--r);
  color:var(--accent);font-size:.84rem;margin-top:18px;
}

/* Results layout */
.bs-results-layout{display:flex;flex:1;overflow:hidden;height:calc(100vh - 64px);}
.bs-results-main{flex:1;overflow:auto;padding:24px 28px;}

/* Search bar */
.bs-search-row{display:flex;align-items:center;gap:12px;margin-bottom:14px;}
.bs-count-badge{font-size:.75rem;color:var(--text-muted);font-family:var(--mono);flex-shrink:0;}

/* Empty state */
.bs-empty{padding:40px;text-align:center;color:var(--text-muted);font-size:.86rem;}

/* Scrollbar */
::-webkit-scrollbar{width:5px;height:5px;}
::-webkit-scrollbar-track{background:transparent;}
::-webkit-scrollbar-thumb{background:var(--border-2);border-radius:10px;}
::-webkit-scrollbar-thumb:hover{background:var(--accent);}

@media(max-width:640px){
  .bs-feat-grid{grid-template-columns:1fr 1fr;}
  .bs-page{padding:20px 4% 32px;}
}
`;

// ── Translations ─────────────────────────────────────────────────────────────
const T = {
  en: {
    brand: 'Basira', subtitle: 'Extract structured data from any website — visually, no code needed',
    start: 'Start →', back: '← New Scrape',
    openingBrowser: 'Opening Browser', loading: 'Loading',
    selectionActive: 'Visual Selection Active',
    selectionDesc: 'The browser is open. Click any item, then SHIFT+Click fields you want, then click Extract.',
    waiting: 'Waiting for your selection…',
    extracting: 'Extracting Data', collectingItems: 'Collecting items across all pages',
    complete: 'Extraction Complete', summary: 'Summary',
    rows: 'Rows', columns: 'Columns', totalCells: 'Total Cells', fillRate: 'Fill Rate',
    fields: 'Fields', export: 'Export',
    dlCSV: '↓ CSV', dlExcel: '↓ Excel', extractedData: 'Extracted Data',
    history: 'Recent Scrapes', noHistory: 'No scrapes yet — start one above',
    stealth: 'Stealth Mode', stealthDesc: 'Rotate user agents & add human delays',
    proxy: 'Proxy', proxyPlaceholder: 'host:port', proxyUser: 'Username', proxyPass: 'Password',
    advanced: 'Advanced Options', ago: 'ago', justNow: 'just now',
    maxRows: 'Max rows', urlError: 'Please paste a website URL — e.g. https://example.com',
    rowError: 'Must be a number greater than 0',
    browserError: 'Could not open the browser. Check the URL and try again.',
    f1: 'JS Support', f2: 'Bilingual', f3: 'Point & Click', f4: 'All Load Methods',
    sortAsc: '↑', sortDesc: '↓', sortNone: '↕',
  },
  ar: {
    brand: 'بصيرة', subtitle: 'استخرج بيانات منظمة من أي موقع — بالنقر بس، بدون كود',
    start: 'ابدأ ←', back: 'كشط جديد →',
    openingBrowser: 'جاري فتح المتصفح', loading: 'جاري التحميل',
    selectionActive: 'وضع الاختيار شغّال',
    selectionDesc: 'المتصفح مفتوح. انقر على أي عنصر، ثم SHIFT+انقر على الحقول، ثم اضغط استخراج.',
    waiting: '...في انتظار اختيارك',
    extracting: 'جاري استخراج البيانات', collectingItems: 'يجمع العناصر من كل الصفحات',
    complete: 'اكتمل الاستخراج', summary: 'ملخص',
    rows: 'الصفوف', columns: 'الأعمدة', totalCells: 'إجمالي الخلايا', fillRate: 'نسبة الاكتمال',
    fields: 'الحقول', export: 'تصدير',
    dlCSV: '↓ CSV', dlExcel: '↓ Excel', extractedData: 'البيانات المستخرجة',
    history: 'آخر عمليات الكشط', noHistory: 'لا توجد عمليات بعد — ابدأ أولى عملياتك',
    stealth: 'وضع التخفي', stealthDesc: 'تغيير هوية المتصفح وإضافة تأخير بشري',
    proxy: 'بروكسي', proxyPlaceholder: 'host:port', proxyUser: 'اسم المستخدم', proxyPass: 'كلمة المرور',
    advanced: 'خيارات متقدمة', ago: 'مضى', justNow: 'الآن',
    maxRows: 'الحد الأقصى', urlError: 'الرجاء إدخال رابط — مثال: https://example.com',
    rowError: 'أدخل رقماً أكبر من صفر',
    browserError: 'تعذّر فتح المتصفح. تحقق من الرابط وأعد المحاولة.',
    f1: 'مواقع ديناميكية', f2: 'ثنائي اللغة', f3: 'تحديد ذكي', f4: 'كل طرق التحميل',
    sortAsc: '↑', sortDesc: '↓', sortNone: '↕',
  },
};

const methodIcon = { 'auto-scroll': '↕️', 'pagination': '📄', 'load-more': '➕' };
const typeIcon   = { image: '🖼', link: '🔗', price: '💰', text: '📝' };

function timeAgo(iso, t) {
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 60) return t.justNow;
  if (diff < 3600) return Math.floor(diff / 60) + 'm ' + t.ago;
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ' + t.ago;
  return Math.floor(diff / 86400) + 'd ' + t.ago;
}

// ── HOME ──────────────────────────────────────────────────────────────────────
export default function Home() {
  const [url, setUrl] = useState('');
  const [showScraper, setShowScraper] = useState(false);
  const [jobId] = useState(() => 'job-' + Date.now());
  const [theme, setTheme] = useState('dark');
  const [lang, setLang] = useState('en');
  const [history, setHistory] = useState([]);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [stealth, setStealth] = useState(false);
  const [proxyEnabled, setProxyEnabled] = useState(false);
  const [proxy, setProxy] = useState({ host: '', port: '', username: '', password: '', protocol: 'http' });
  const [rowLimit, setRowLimit] = useState('');
  const [urlError, setUrlError] = useState('');
  const [rowError, setRowError] = useState('');

  const t = T[lang];
  const isAR = lang === 'ar';

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    document.documentElement.setAttribute('dir', isAR ? 'rtl' : 'ltr');
  }, [theme, lang]);

  useEffect(() => { loadHistory(); }, []);

  const loadHistory = async () => {
    try {
      const res = await fetch('/api/history?action=list');
      const data = await res.json();
      if (data.success) setHistory(data.history);
    } catch (e) {}
  };

  const deleteHistory = async (id) => {
    await fetch('/api/history?action=delete&id=' + id, { method: 'DELETE' });
    setHistory(h => h.filter(e => e.id !== id));
  };

  const handleStart = () => {
    setUrlError(''); setRowError('');
    const trimmed = url.trim();
    let valid = true;
    if (!trimmed) { setUrlError(t.urlError); valid = false; }
    if (rowLimit && (isNaN(parseInt(rowLimit)) || parseInt(rowLimit) < 1)) { setRowError(t.rowError); valid = false; }
    if (!valid) return;
    let finalUrl = trimmed;
    if (!/^https?:\/\//i.test(finalUrl)) finalUrl = 'https://' + finalUrl;
    setUrl(finalUrl);
    setShowScraper(true);
  };

  if (showScraper) return (
    <ScraperInterface url={url} jobId={jobId} lang={lang} theme={theme}
      stealth={stealth} proxy={proxyEnabled ? proxy : null}
      rowLimit={rowLimit ? parseInt(rowLimit) : null}
      onBack={() => { setShowScraper(false); loadHistory(); }} />
  );

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: DESIGN_CSS }} />

      {/* Nav */}
      <nav className="bs-nav">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <img src="/basira-logo.png" style={{ width: 36, height: 36, objectFit: 'contain' }} alt="logo" />
          <span className="bs-brand">{t.brand}</span>
        </div>
        <div className="bs-nav-actions">
          <button className="bs-icon-btn" onClick={() => setLang(lang === 'en' ? 'ar' : 'en')}
            style={{ fontWeight: 700, fontSize: 13, width: 'auto', padding: '0 12px' }}>
            {lang === 'en' ? 'AR' : 'EN'}
          </button>
          <button className="bs-icon-btn" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
            {theme === 'dark' ? '☀️' : '🌙'}
          </button>
        </div>
      </nav>

      <main className="bs-page">

        {/* Hero */}
        <div style={{ textAlign: 'center', paddingTop: 16, paddingBottom: 8 }}>
          <img src="/basira-logo.png" style={{ width: 88, height: 88, objectFit: 'contain', marginBottom: 16 }} alt="logo" />
          <h1 style={{ fontSize: '2.2rem', fontWeight: 800, letterSpacing: -1, color: 'var(--accent)', fontFamily: 'var(--mono)', marginBottom: 10 }}>
            Basira Scraper
          </h1>
          <p style={{ fontSize: '.95rem', color: 'var(--text-dim)', maxWidth: 520, margin: '0 auto' }}>{t.subtitle}</p>
        </div>

        {/* URL Card */}
        <div className="bs-card" style={{ maxWidth: 760, width: '100%', margin: '0 auto' }}>
          <div style={{ display: 'flex', gap: 10 }}>
            <input className={`bs-input${urlError ? ' error' : ''}`} type="url"
              placeholder="https://example.com"
              value={url} onChange={e => { setUrl(e.target.value); setUrlError(''); }}
              onKeyPress={e => e.key === 'Enter' && handleStart()}
              style={{ direction: 'ltr' }} />
            <input className={`bs-input bs-input-sm${rowError ? ' error' : ''}`} type="number"
              placeholder={t.maxRows} min="1" value={rowLimit}
              onChange={e => { setRowLimit(e.target.value); setRowError(''); }}
              style={{ width: 110, textAlign: 'center' }} />
            <button className="bs-btn bs-btn-primary" onClick={handleStart}>{t.start}</button>
          </div>

          {urlError && <div className="bs-error-banner" style={{ marginTop: 10 }}>⚠️ {urlError}</div>}
          {rowError && <div className="bs-error-banner" style={{ marginTop: 8 }}>⚠️ {rowError}</div>}

          {/* Advanced toggle */}
          <button onClick={() => setShowAdvanced(!showAdvanced)}
            style={{ background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer', fontSize: '.8rem', fontWeight: 600, padding: '8px 0 0', fontFamily: 'var(--sans)' }}>
            {showAdvanced ? '▲' : '▼'} {t.advanced}
          </button>

          {showAdvanced && (
            <div className="bs-advanced-panel">
              {/* Stealth */}
              <div className={`bs-toggle-row${stealth ? ' active' : ''}`}>
                <div>
                  <div className="bs-toggle-row-label">🥷 {t.stealth}</div>
                  <div className="bs-toggle-row-desc">{t.stealthDesc}</div>
                </div>
                <button className="bs-toggle" onClick={() => setStealth(!stealth)}
                  style={{ background: stealth ? 'var(--accent)' : 'var(--border-2)' }}>
                  <div className="bs-toggle-thumb" style={{ left: stealth ? 21 : 3 }} />
                </button>
              </div>

              {/* Proxy */}
              <div className={`bs-toggle-row${proxyEnabled ? ' active' : ''}`}>
                <div>
                  <div className="bs-toggle-row-label">🌐 {t.proxy}</div>
                </div>
                <button className="bs-toggle" onClick={() => setProxyEnabled(!proxyEnabled)}
                  style={{ background: proxyEnabled ? 'var(--purple)' : 'var(--border-2)' }}>
                  <div className="bs-toggle-thumb" style={{ left: proxyEnabled ? 21 : 3 }} />
                </button>
              </div>
              {proxyEnabled && (
                <div className="bs-proxy-grid">
                  <div className="bs-input-row">
                    <select className="bs-input bs-input-sm" value={proxy.protocol}
                      onChange={e => setProxy(p => ({ ...p, protocol: e.target.value }))} style={{ width: 90 }}>
                      <option>http</option><option>https</option><option>socks5</option>
                    </select>
                    <input className="bs-input bs-input-sm" placeholder={t.proxyPlaceholder} style={{ direction: 'ltr' }}
                      value={proxy.host + (proxy.port ? ':' + proxy.port : '')}
                      onChange={e => { const [h, p] = e.target.value.split(':'); setProxy(px => ({ ...px, host: h || '', port: p || '' })); }} />
                  </div>
                  <div className="bs-input-row">
                    <input className="bs-input bs-input-sm" placeholder={t.proxyUser} value={proxy.username}
                      onChange={e => setProxy(p => ({ ...p, username: e.target.value }))} />
                    <input className="bs-input bs-input-sm" placeholder={t.proxyPass} type="password" value={proxy.password}
                      onChange={e => setProxy(p => ({ ...p, password: e.target.value }))} />
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Feature cards */}
        <div className="bs-feat-grid" style={{ maxWidth: 760, width: '100%', margin: '0 auto' }}>
          {[{ l: 'JS', d: t.f1 }, { l: 'EN/AR', d: t.f2 }, { l: '👆', d: t.f3 }, { l: '⚡', d: t.f4 }].map((f, i) => (
            <div key={i} className="bs-feat-card">
              <div className="bs-feat-label">{f.l}</div>
              <div className="bs-feat-desc">{f.d}</div>
            </div>
          ))}
        </div>

        {/* History */}
        <div style={{ maxWidth: 760, width: '100%', margin: '0 auto' }}>
          <div className="bs-section-head">
            <span className="bs-section-title">🕐 {t.history}</span>
            {history.length > 0 && (
              <button onClick={async () => { await fetch('/api/history?action=clear', { method: 'DELETE' }); setHistory([]); }}
                style={{ background: 'none', border: 'none', color: 'var(--text-muted)', fontSize: '.75rem', cursor: 'pointer', fontFamily: 'var(--sans)' }}>
                Clear all
              </button>
            )}
          </div>

          {history.length === 0 ? (
            <div className="bs-card" style={{ textAlign: 'center', padding: '32px', color: 'var(--text-muted)', fontSize: '.86rem', borderStyle: 'dashed' }}>
              {t.noHistory}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {history.map((entry, i) => (
                <div key={i} className="bs-history-item">
                  <div className="bs-history-icon">{methodIcon[entry.loadingMethod] || '📊'}</div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: '.88rem', fontWeight: 700, color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', direction: 'ltr' }}>
                      {entry.hostname}
                    </div>
                    <div className="bs-history-meta">
                      <span style={{ fontFamily: 'var(--mono)' }}>{entry.rows}</span> rows · {entry.fields.length} fields · {entry.duration}s · {timeAgo(entry.timestamp, t)}
                      {entry.failedItems > 0 && <span style={{ color: 'var(--danger)', marginInlineStart: 8 }}>⚠️ {entry.failedItems} failed</span>}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                    <a href={'/view/' + entry.id} target="_blank" rel="noreferrer" className="bs-btn bs-btn-ghost"
                      style={{ padding: '7px 14px', fontSize: '.75rem', textDecoration: 'none' }}>
                      👁 View
                    </a>
                    <button onClick={() => deleteHistory(entry.id)} className="bs-icon-btn">×</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

      </main>
    </>
  );
}

// ── SCRAPER INTERFACE ─────────────────────────────────────────────────────────
function ScraperInterface({ url, jobId, lang, theme, stealth, proxy, rowLimit, onBack }) {
  const [status, setStatus] = useState('opening');
  const [extractedData, setExtractedData] = useState([]);
  const [fields, setFields] = useState([]);
  const [itemCount, setItemCount] = useState(0);
  const [failedCount, setFailedCount] = useState(0);
  const [progress, setProgress] = useState({ currentPage: 0, totalPages: '?', itemsCollected: 0 });
  const [search, setSearch] = useState('');
  const [sortCol, setSortCol] = useState(null);
  const [sortDir, setSortDir] = useState('asc');

  const t = T[lang];
  const isAR = lang === 'ar';

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    document.documentElement.setAttribute('dir', isAR ? 'rtl' : 'ltr');
  }, []);

  useEffect(() => { openBrowser(); }, []);

  const openBrowser = async () => {
    try {
      const res = await fetch('/api/scraper?action=open-browser', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, jobId, lang, stealth: !!stealth, proxy: proxy || null }),
      });
      const result = await res.json();
      if (result.success) { setStatus('selecting'); checkSelection(); }
      else setStatus('error');
    } catch (e) { setStatus('error'); }
  };

  const checkSelection = async () => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch('/api/scraper?action=check-selection&jobId=' + jobId);
        const result = await res.json();
        if (result.cancelled) { clearInterval(interval); onBack(); }
        else if (result.completed) { clearInterval(interval); setStatus('extracting'); extractData(); startProgressPolling(); }
      } catch (e) {}
    }, 1000);
  };

  const startProgressPolling = () => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch('/api/scraper?action=get-progress&jobId=' + jobId);
        const prog = await res.json();
        setProgress({ currentPage: prog.currentPage || 0, totalPages: prog.totalPages || '?', itemsCollected: prog.itemsCollected || 0 });
        if (prog.status === 'done' || prog.status === 'error') clearInterval(interval);
      } catch (e) {}
    }, 800);
  };

  const extractData = async () => {
    try {
      const res = await fetch('/api/scraper?action=extract-data', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jobId, rowLimit: rowLimit || null }),
      });
      const result = await res.json();
      if (result.success) {
        setItemCount(result.itemsScraped);
        setFailedCount(result.failedItems || 0);
        setFields(result.fields || []);
        setStatus('completed');
        loadData();
      } else setStatus('error');
    } catch (e) { setStatus('error'); }
  };

  const loadData = async () => {
    const res = await fetch('/api/scraper?action=get-data&jobId=' + jobId);
    const result = await res.json();
    if (result.success) setExtractedData(result.data);
  };

  const getTableData = () => {
    const map = {};
    extractedData.forEach(item => {
      if (!map[item.item_index]) map[item.item_index] = {};
      map[item.item_index][item.field_name] = item.value;
    });
    return Object.values(map);
  };

  const tableRows = getTableData();
  const filteredRows = tableRows
    .filter(row => !search || fields.some(f => (row[f.name] || '').toLowerCase().includes(search.toLowerCase())))
    .sort((a, b) => {
      if (!sortCol) return 0;
      const av = (a[sortCol] || '').toLowerCase(), bv = (b[sortCol] || '').toLowerCase();
      const an = parseFloat(av), bn = parseFloat(bv);
      const cmp = !isNaN(an) && !isNaN(bn) ? an - bn : av.localeCompare(bv);
      return sortDir === 'asc' ? cmp : -cmp;
    });

  const totalCells = extractedData.length;
  const fillRate = totalCells > 0 ? Math.round(((totalCells - extractedData.filter(d => !d.value || d.value === 'N/A').length) / totalCells) * 100) : 0;
  const hostname = (() => { try { return new URL(url).hostname; } catch (e) { return url; } })();

  const exportCSV = () => {
    const rows = filteredRows; if (!rows.length) return;
    const h = fields.map(f => f.name);
    const csv = [h.join(','), ...rows.map(r => h.map(k => '"' + (r[k] || '').replace(/"/g, '""') + '"').join(','))].join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' }));
    a.download = 'basira-' + Date.now() + '.csv'; a.click();
  };

  const exportExcel = () => {
    const rows = filteredRows; if (!rows.length) return;
    const script = document.createElement('script');
    script.src = 'https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js';
    script.onload = () => {
      const XLSX = window.XLSX;
      const h = fields.map(f => f.name);
      const wsData = [h, ...rows.map(r => h.map(k => {
        const v = r[k] || '';
        const field = fields.find(f => f.name === k);
        if (field && field.type === 'price') return isNaN(parseFloat(v)) ? v : parseFloat(v);
        return v;
      }))];
      const ws = XLSX.utils.aoa_to_sheet(wsData);
      ws['!cols'] = h.map((_, i) => ({ wch: Math.min(Math.max(h[i].length, ...rows.map(r => String(r[h[i]] || '').length)) + 2, 50) }));
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, 'Data');
      XLSX.writeFile(wb, 'basira-' + Date.now() + '.xlsx');
    };
    document.head.appendChild(script);
  };

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

  // ── Loading / error screens ──────────────────────────────────────────────
  if (status !== 'completed') return (
    <>
      <style dangerouslySetInnerHTML={{ __html: DESIGN_CSS }} />
      <nav className="bs-nav">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <img src="/basira-logo.png" style={{ width: 32, height: 32, objectFit: 'contain' }} alt="logo" />
          <span className="bs-brand" style={{ fontSize: '1.1rem' }}>Basira Scraper</span>
          <span style={{ color: 'var(--text-muted)', fontSize: '.75rem' }}>· {hostname}</span>
          {stealth && <span className="bs-badge">🥷 Stealth</span>}
          {proxy && <span className="bs-badge" style={{ background: 'rgba(139,92,246,.1)', color: 'var(--purple)', borderColor: 'rgba(139,92,246,.2)' }}>🌐 Proxy</span>}
        </div>
        <button className="bs-btn bs-btn-ghost" onClick={onBack} style={{ padding: '8px 16px', fontSize: '.8rem' }}>{t.back}</button>
      </nav>

      <div className="bs-loading-box">
        <div className="bs-loading-inner">
          {status === 'opening' && <>
            <div className="bs-spinner" style={{ margin: '0 auto 24px' }} />
            <div className="bs-loading-title">{t.openingBrowser}</div>
            <div className="bs-loading-sub">{t.loading} {hostname}</div>
          </>}
          {status === 'selecting' && <>
            <img src="/basira-logo.png" style={{ width: 72, height: 72, objectFit: 'contain', margin: '0 auto 24px', display: 'block' }} alt="logo" />
            <div className="bs-loading-title">{t.selectionActive}</div>
            <div className="bs-loading-sub" style={{ marginTop: 10, marginBottom: 20 }}>{t.selectionDesc}</div>
            <div className="bs-selecting-hint">{t.waiting}</div>
          </>}
          {status === 'extracting' && <>
            <div className="bs-spinner" style={{ margin: '0 auto 24px', borderTopColor: 'var(--success)' }} />
            <div className="bs-loading-title">{t.extracting}</div>
            <div className="bs-loading-sub" style={{ marginBottom: 24 }}>{t.collectingItems}</div>
            <div className="bs-status-card">
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
                <span style={{ fontSize: '.8rem', color: 'var(--text-dim)' }}>Page {progress.currentPage} of {progress.totalPages}</span>
                <span style={{ fontSize: '.8rem', fontWeight: 800, color: 'var(--success)', fontFamily: 'var(--mono)' }}>{progress.itemsCollected} items</span>
              </div>
              <div className="bs-progress-track"><div className="bs-progress-fill" style={{ width: progress.currentPage > 0 ? '60%' : '15%' }} /></div>
            </div>
          </>}
          {status === 'error' && <>
            <div style={{ width: 64, height: 64, borderRadius: '50%', background: 'rgba(239,68,68,.08)', border: '2px solid rgba(239,68,68,.2)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 28, margin: '0 auto 24px' }}>⚠️</div>
            <div className="bs-loading-title" style={{ color: 'var(--danger)' }}>Something went wrong</div>
            <div className="bs-loading-sub" style={{ marginBottom: 24 }}>{t.browserError}</div>
            <button className="bs-btn bs-btn-primary" onClick={onBack}>{t.back}</button>
          </>}
        </div>
      </div>
    </>
  );

  // ── Results ──────────────────────────────────────────────────────────────
  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: DESIGN_CSS }} />
      <nav className="bs-nav">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <img src="/basira-logo.png" style={{ width: 32, height: 32, objectFit: 'contain' }} alt="logo" />
          <span className="bs-brand" style={{ fontSize: '1.1rem' }}>Basira Scraper</span>
          <span style={{ color: 'var(--text-muted)', fontSize: '.75rem' }}>· {hostname}</span>
          {stealth && <span className="bs-badge">🥷</span>}
        </div>
        <div className="bs-nav-actions">
          <button className="bs-btn bs-btn-ghost" onClick={exportCSV} style={{ padding: '8px 14px', fontSize: '.8rem', color: 'var(--success)', borderColor: 'rgba(34,197,94,.25)', background: 'rgba(34,197,94,.07)' }}>{t.dlCSV}</button>
          <button className="bs-btn bs-btn-ghost" onClick={exportExcel} style={{ padding: '8px 14px', fontSize: '.8rem' }}>{t.dlExcel}</button>
          <button className="bs-btn bs-btn-ghost" onClick={onBack} style={{ padding: '8px 14px', fontSize: '.8rem' }}>{t.back}</button>
        </div>
      </nav>

      <div className="bs-results-layout">
        {/* Sidebar */}
        <aside className="bs-sidebar">
          <div style={{ background: 'rgba(34,197,94,.08)', border: '1px solid rgba(34,197,94,.2)', borderRadius: 12, padding: '14px', textAlign: 'center' }}>
            <div style={{ fontSize: 22, marginBottom: 4 }}>✅</div>
            <div style={{ fontSize: '.72rem', fontWeight: 800, color: 'var(--success)', letterSpacing: '.5px' }}>{t.complete}</div>
          </div>

          <div>
            <div className="bs-sidebar-section-title">{t.summary}</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {[
                { label: t.rows, value: itemCount, color: 'var(--accent)' },
                { label: t.columns, value: fields.length, color: 'var(--purple)' },
                { label: t.totalCells, value: totalCells, color: 'var(--success)' },
                { label: t.fillRate, value: fillRate + '%', color: fillRate >= 80 ? 'var(--success)' : 'var(--warning)' },
                ...(failedCount > 0 ? [{ label: '⚠️ Failed', value: failedCount, color: 'var(--danger)' }] : []),
              ].map((s, i) => (
                <div key={i} className="bs-stat-row">
                  <span className="bs-stat-label">{s.label}</span>
                  <span className="bs-stat-value" style={{ color: s.color }}>{s.value}</span>
                </div>
              ))}
            </div>
          </div>

          <div>
            <div className="bs-sidebar-section-title">{t.fields}</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              {fields.map((f, i) => (
                <div key={i} className="bs-field-chip">
                  <span>{typeIcon[f.type] || '📝'}</span>{f.name}
                </div>
              ))}
            </div>
          </div>

          <div style={{ marginTop: 'auto' }}>
            <div className="bs-sidebar-section-title">{t.export}</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
              <button className="bs-btn bs-btn-primary bs-btn-full" onClick={exportCSV}>{t.dlCSV}</button>
              <button className="bs-btn bs-btn-ghost bs-btn-full" onClick={exportExcel}>{t.dlExcel}</button>
            </div>
          </div>
        </aside>

        {/* Table */}
        <main className="bs-results-main">
          <div className="bs-search-row">
            <div style={{ flex: 1, position: 'relative' }}>
              <input className="bs-input bs-input-sm" type="text"
                placeholder="🔍 Search..." value={search}
                onChange={e => setSearch(e.target.value)}
                style={{ paddingInlineStart: 16, direction: 'ltr' }} />
            </div>
            <span className="bs-count-badge">{filteredRows.length} / {tableRows.length}</span>
          </div>

          <div className="bs-table-wrap">
            <table className="bs-table">
              <thead>
                <tr>
                  <th style={{ width: 40 }}>#</th>
                  {fields.map((f, i) => (
                    <th key={i} onClick={() => { setSortCol(f.name); setSortDir(sortCol === f.name && sortDir === 'asc' ? 'desc' : 'asc'); }}>
                      {typeIcon[f.type] || ''} {f.name} {sortCol === f.name ? (sortDir === 'asc' ? t.sortAsc : t.sortDesc) : <span style={{ opacity: .35 }}>{t.sortNone}</span>}
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
