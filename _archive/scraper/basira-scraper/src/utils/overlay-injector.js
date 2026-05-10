const fs = require('fs');
const path = require('path');

const logoPath = path.join(process.cwd(), 'public', 'basira-logo.png');
const logoBase64 = fs.readFileSync(logoPath).toString('base64');

const overlayScript = `
(function() {
  var _logoUrl = 'data:image/png;base64,${logoBase64}';


  var selectedFields = [];
  var isSelecting = false;
  var currentListElement = null;
  var referenceItem = null;
  var loadingMethod = 'auto-scroll';
  var paginationButton = null;
  var loadMoreButton = null;
  
  function init() {
    document.body.style.paddingRight = '400px';
    
    var panel = document.createElement('div');
    panel.id = 'basira-panel';
    panel.style.position = 'fixed';
    panel.style.top = '0';
    panel.style.right = '0';
    panel.style.width = '400px';
    panel.style.height = '100vh';
    panel.style.background = '#0f172a';
    panel.style.borderLeft = '3px solid #3b82f6';
    panel.style.zIndex = '2147483647';
    panel.style.color = '#f1f5f9';
    panel.style.overflowY = 'auto';
    panel.style.display = 'flex';
    panel.style.flexDirection = 'column';
    
    document.body.appendChild(panel);
    showStartScreen();
  }
  
  function showStartScreen() {
    var panel = document.getElementById('basira-panel');
    panel.innerHTML = '';
    
    var header = document.createElement('div');
    header.style.padding = '32px 24px 24px';
    header.style.background = 'linear-gradient(135deg,#1e293b,#0f172a)';
    header.style.borderBottom = '1px solid ' + '#334155';
    
    var headerContent = document.createElement('div');
    headerContent.style.display = 'flex';
    headerContent.style.alignItems = 'center';
    headerContent.style.gap = '16px';
    
    var logo = document.createElement('img');
    logo.src = _logoUrl;
    logo.style.width = '72px';
    logo.style.height = '72px';
    logo.style.objectFit = 'contain';
    
    var titleBox = document.createElement('div');
    var title = document.createElement('h2');
    title.style.margin = '0';
    title.style.fontSize = '26px';
    title.style.color = '#3b82f6';
    title.style.fontWeight = 'bold';
    title.textContent = 'Basira Scraper';
    
    var subtitle = document.createElement('p');
    subtitle.style.margin = '4px 0 0 0';
    subtitle.style.color = '#94a3b8';
    subtitle.style.fontSize = '13px';
    subtitle.textContent = 'Extract structured data from any website';
    
    titleBox.appendChild(title);
    titleBox.appendChild(subtitle);
    headerContent.appendChild(logo);
    headerContent.appendChild(titleBox);
    header.appendChild(headerContent);
    panel.appendChild(header);
    
    var content = document.createElement('div');
    content.style.padding = '32px 24px';
    content.style.flex = '1';
    content.style.display = 'flex';
    content.style.flexDirection = 'column';
    content.style.gap = '24px';
    
    var iconBox = document.createElement('div');
    iconBox.style.textAlign = 'center';
    iconBox.style.padding = '24px';
    
    var icon = document.createElement('img');
    icon.src = _logoUrl;
    icon.style.width = '140px';
    icon.style.height = '140px';
    icon.style.display = 'inline-block';
    icon.style.objectFit = 'contain';
    
    iconBox.appendChild(icon);
    content.appendChild(iconBox);
    
    var titleSection = document.createElement('div');
    titleSection.style.textAlign = 'center';
    
    var mainTitle = document.createElement('h3');
    mainTitle.style.margin = '0 0 12px 0';
    mainTitle.style.fontSize = '22px';
    mainTitle.style.color = '#f1f5f9';
    mainTitle.style.fontWeight = '600';
    mainTitle.textContent = 'Select Any Item';
    
    var desc = document.createElement('p');
    desc.style.margin = '0';
    desc.style.color = '#94a3b8';
    desc.style.fontSize = '14px';
    desc.style.lineHeight = '1.6';
    desc.textContent = 'Click on ANY product card, article, or list item to get started.';
    
    titleSection.appendChild(mainTitle);
    titleSection.appendChild(desc);
    content.appendChild(titleSection);
    
    var spacer = document.createElement('div');
    spacer.style.flex = '1';
    content.appendChild(spacer);
    
    var btnContainer = document.createElement('div');
    btnContainer.style.display = 'flex';
    btnContainer.style.flexDirection = 'column';
    btnContainer.style.gap = '12px';
    
    var startBtn = document.createElement('button');
    startBtn.id = 'start-btn';
    startBtn.style.background = 'linear-gradient(to right,#3b82f6,#14b8a6)';
    startBtn.style.color = 'white';
    startBtn.style.border = 'none';
    startBtn.style.padding = '16px 24px';
    startBtn.style.borderRadius = '12px';
    startBtn.style.cursor = 'pointer';
    startBtn.style.fontWeight = '600';
    startBtn.style.fontSize = '15px';
    startBtn.style.boxShadow = '0 4px 12px rgba(59,130,246,0.4)';
    startBtn.textContent = 'Start Selection';
    startBtn.onmouseover = function() { this.style.transform = 'translateY(-2px)'; };
    startBtn.onmouseout = function() { this.style.transform = 'translateY(0)'; };
    startBtn.onclick = startSelection;
    
    var cancelBtn = document.createElement('button');
    cancelBtn.style.background = 'transparent';
    cancelBtn.style.color = '#94a3b8';
    cancelBtn.style.border = '2px solid ' + '#334155';
    cancelBtn.style.padding = '14px 24px';
    cancelBtn.style.borderRadius = '12px';
    cancelBtn.style.cursor = 'pointer';
    cancelBtn.style.fontWeight = '600';
    cancelBtn.style.fontSize = '15px';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.onmouseover = function() { this.style.borderColor = '#334155'; this.style.color = '#cbd5e1'; };
    cancelBtn.onmouseout = function() { this.style.borderColor = '#334155'; this.style.color = '#94a3b8'; };
    cancelBtn.onclick = function() {
      document.body.style.paddingRight = '';
      var p = document.getElementById('basira-panel');
      if (p) p.remove();
      window.basiraSelectionCancelled = true;
    };
    
    btnContainer.appendChild(startBtn);
    btnContainer.appendChild(cancelBtn);
    content.appendChild(btnContainer);
    panel.appendChild(content);
  }
  
  function startSelection() {
    var panel = document.getElementById('basira-panel');
    panel.innerHTML = '';
    
    var header = document.createElement('div');
    header.style.padding = '24px';
    header.style.background = 'linear-gradient(135deg,#1e293b,#0f172a)';
    header.style.borderBottom = '1px solid ' + '#334155';
    header.style.display = 'flex';
    header.style.alignItems = 'center';
    header.style.gap = '12px';
    
    var logo = document.createElement('img');
    logo.src = _logoUrl;
    logo.style.width = '64px';
    logo.style.height = '64px';
    logo.style.objectFit = 'contain';
    
    var titleBox = document.createElement('div');
    var title = document.createElement('h2');
    title.style.margin = '0';
    title.style.fontSize = '20px';
    title.style.color = '#60a5fa';
    title.style.fontWeight = '600';
    title.textContent = 'Basira Scraper';
    
    var subtitle = document.createElement('p');
    subtitle.style.margin = '2px 0 0 0';
    subtitle.style.color = '#64748b';
    subtitle.style.fontSize = '11px';
    subtitle.textContent = 'Step 1: Click Item';
    
    titleBox.appendChild(title);
    titleBox.appendChild(subtitle);
    header.appendChild(logo);
    header.appendChild(titleBox);
    panel.appendChild(header);
    
    var content = document.createElement('div');
    content.style.padding = '32px 24px';
    content.style.flex = '1';
    content.style.display = 'flex';
    content.style.alignItems = 'center';
    content.style.justifyContent = 'center';
    
    var instructionBox = document.createElement('div');
    instructionBox.style.textAlign = 'center';
    instructionBox.style.maxWidth = '320px';
    
    var pointer = document.createElement('div');
    pointer.style.width = '100px';
    pointer.style.height = '100px';
    pointer.style.background = 'linear-gradient(135deg,rgba(251,191,36,0.2),rgba(245,158,11,0.2))';
    pointer.style.border = '3px solid rgba(251,191,36,0.4)';
    pointer.style.borderRadius = '24px';
    pointer.style.display = 'inline-flex';
    pointer.style.alignItems = 'center';
    pointer.style.justifyContent = 'center';
    pointer.style.fontSize = '50px';
    pointer.style.marginBottom = '24px';
    pointer.textContent = '👆';
    
    var instTitle = document.createElement('h3');
    instTitle.style.margin = '0 0 12px 0';
    instTitle.style.fontSize = '20px';
    instTitle.style.color = '#fbbf24';
    instTitle.style.fontWeight = '600';
    instTitle.textContent = 'Click any product card';
    
    var instDesc = document.createElement('p');
    instDesc.style.margin = '0';
    instDesc.style.color = '#94a3b8';
    instDesc.style.fontSize = '14px';
    instDesc.style.lineHeight = '1.6';
    instDesc.textContent = 'Hover over any item on the page and click to select it.';
    
    instructionBox.appendChild(pointer);
    instructionBox.appendChild(instTitle);
    instructionBox.appendChild(instDesc);
    content.appendChild(instructionBox);
    panel.appendChild(content);
    
    document.addEventListener('mouseover', handleHover, true);
    document.addEventListener('click', handleClick, true);
  }
  
  function handleHover(e) {
    if (e.target.closest('#basira-panel')) return;
    e.target.style.outline = '3px solid #fbbf24';
    e.target.style.outlineOffset = '2px';
    e.target.addEventListener('mouseout', function() { this.style.outline = ''; this.style.outlineOffset = ''; }, {once:true});
  }
  
  function handleClick(e) {
    if (e.target.closest('#basira-panel')) return;
    e.preventDefault();
    e.stopPropagation();
    
    document.removeEventListener('mouseover', handleHover, true);
    document.removeEventListener('click', handleClick, true);
    
    var card = e.target;
    for (var i = 0; i < 15; i++) {
      if (!card.parentElement) break;
      card = card.parentElement;
      var siblings = card.parentElement ? Array.from(card.parentElement.children) : [];
      var cardCC = card.children.length;
      var similarSiblings = siblings.filter(function(sib) {
        if (sib === card || sib.tagName !== card.tagName) return false;
        var sibCC = sib.children.length;
        if (cardCC === 0) return sibCC === 0;
        var r = sibCC / cardCC;
        return r >= 0.5 && r <= 2.0;
      });
      if (similarSiblings.length >= 2) break;
    }
    
    referenceItem = card;
    currentListElement = card.parentElement;
    referenceItem.style.outline = '3px solid #10b981';
    referenceItem.style.outlineOffset = '2px';
    
    isSelecting = true;
    document.addEventListener('click', handleFieldClick, true);
    updatePanel();
  }
  
  function handleFieldClick(e) {
    if (!isSelecting || e.target.closest('#basira-panel') || !e.shiftKey) return;
    e.preventDefault();
    e.stopPropagation();
    
    var el = e.target;
    var idx = -1;
    for (var i = 0; i < selectedFields.length; i++) {
      if (selectedFields[i].element === el) { idx = i; break; }
    }
    
    if (idx >= 0) {
      selectedFields.splice(idx, 1);
      el.style.outline = '';
      el.style.outlineOffset = '';
    } else {
      var selector = generateSelector(el);
      // Auto-detect field type
      var fieldType = 'text';
      var fieldSample = (el.textContent || '').trim().substring(0, 60);
      var targetEl = el;

      if (el.tagName === 'IMG') {
        fieldType = 'image';
        fieldSample = el.src || el.getAttribute('data-src') || '';
      } else if (el.tagName === 'A') {
        // Default link, but user can switch to text
        fieldType = 'link';
        fieldSample = el.href || '';
      } else {
        var imgs = el.getElementsByTagName('img');
        var links = el.getElementsByTagName('a');
        if (imgs.length >= 1 && imgs[0].src) {
          // Container with image inside — point selector at the img
          fieldType = 'image';
          targetEl = imgs[0];
          selector = generateSelector(imgs[0]);
          fieldSample = imgs[0].src || imgs[0].getAttribute('data-src') || '';
        } else if (links.length === 1 && (el.textContent || '').trim().length < 120) {
          fieldType = 'link';
          fieldSample = links[0].href || '';
        }
      }
      // Price detection
      var priceText = (el.textContent || '').trim();
      if (/^[£$€¥₹][\d,]+\.?\d*$/.test(priceText) || /^[\d,]+\.?\d*[£$€¥₹]$/.test(priceText)) {
        fieldType = 'price';
        fieldSample = priceText;
      }
      selectedFields.push({
        element: el,
        name: 'field_' + (selectedFields.length + 1),
        selector: selector,
        sample: fieldSample,
        type: fieldType
      });
      var outlineColor = fieldType === 'image' ? '#f59e0b' : fieldType === 'link' ? '#a78bfa' : fieldType === 'price' ? '#10b981' : '#10b981';
      el.style.outline = '3px solid ' + outlineColor;
      el.style.outlineOffset = '2px';
    }
    updatePanel();
  }
  
  function isStableClass(cls) {
    if (!cls || cls.length < 2) return false;
    if (cls.startsWith('basira')) return false;
    if (cls.indexOf(':') >= 0 || cls.indexOf('[') >= 0 || cls.indexOf('/') >= 0) return false;
    // Detect hex hashes (e.g. CSS modules: "a3f2c1") - no regex, manual check
    var hexCount = 0;
    for (var i = 0; i < cls.length; i++) {
      var c = cls[i].toLowerCase();
      if ((c >= 'a' && c <= 'f') || (c >= '0' && c <= '9')) hexCount++;
    }
    if (hexCount > 5 && hexCount >= cls.length * 0.8) return false;
    // Common Tailwind single-word utilities to skip
    var tw = ['flex','grid','block','inline','hidden','relative','absolute','fixed','sticky',
      'text','font','bg','gap','border','shadow','rounded','overflow','cursor','items',
      'justify','grow','shrink','leading','tracking','transition','animate','opacity','p','m','w','h'];
    if (tw.indexOf(cls) >= 0) return false;
    return true;
  }

  function getBestClass(el) {
    if (!el || !el.className || typeof el.className !== 'string') return null;
    var classes = el.className.split(' ').filter(isStableClass);
    if (!classes.length) return null;
    var bem = classes.filter(function(c) { return c.indexOf('__') >= 0 || c.indexOf('--') >= 0; });
    if (bem.length) return bem[0];
    classes.sort(function(a, b) { return b.length - a.length; });
    return classes[0];
  }

  function generateSelector(el) {
    var parts = [];
    var current = el;
    var maxLevels = 6;
    var dataNames = ['data-testid','data-cy','data-qa','data-test','data-key'];
    while (current && current !== referenceItem && maxLevels > 0) {
      maxLevels--;
      if (current.id && current.id.length < 60) { parts.unshift('#' + current.id); break; }
      var fd = false;
      for (var d = 0; d < dataNames.length; d++) {
        var dv = current.getAttribute(dataNames[d]);
        if (dv) { parts.unshift('[' + dataNames[d] + '="' + dv + '"]'); fd = true; break; }
      }
      if (fd) break;
      var sc = getBestClass(current);
      if (sc) {
        parts.unshift('.' + sc);
      } else {
        var tag = current.tagName.toLowerCase();
        if (current.parentElement) {
          var sibs = Array.from(current.parentElement.children).filter(function(s) { return s.tagName === current.tagName; });
          parts.unshift(sibs.length > 1 ? tag + ':nth-of-type(' + (sibs.indexOf(current) + 1) + ')' : tag);
        } else {
          parts.unshift(tag);
        }
      }
      current = current.parentElement;
    }
    return parts.join(' ') || el.tagName.toLowerCase();
  }
  
  window.selectLoadingMethod = function(method) {
    loadingMethod = method;
    if (method === 'pagination') showPaginationSelector();
    else if (method === 'load-more') showLoadMoreSelector();
    else updatePanel();
  };
  
  function updatePanel() {
    var panel = document.getElementById('basira-panel');
    panel.innerHTML = '<div style="padding:20px 24px;background:' + 'linear-gradient(135deg,#1e293b,#0f172a)' + ';border-bottom:1px solid ' + '#334155' + ';display:flex;align-items:center;gap:12px;"><img id="basira-panel-logo" style="width:52px;height:52px;object-fit:contain;"><div><h2 style="margin:0;font-size:18px;color:' + '#3b82f6' + ';font-weight:600;">Basira Scraper</h2><p style="margin:2px 0 0 0;color:' + '#64748b' + ';font-size:11px;">Extract structured data</p></div></div><div id="panel-body" style="padding:20px;flex:1;overflow-y:auto;background:' + '#0f172a' + ';"></div>';
    var panelLogo = document.getElementById('basira-panel-logo');
    if (panelLogo) panelLogo.src = _logoUrl;
    
    var body = document.getElementById('panel-body');
    
    var step1 = createStep1(selectedFields.length > 0);
    body.appendChild(step1);
    
    var step2 = createStep2();
    body.appendChild(step2);
    
    var btns = createBtns();
    body.appendChild(btns);
    
    attachListeners();
  }
  
  function createStep1(complete) {
    var section = document.createElement('div');
    section.style.marginBottom = '24px';
    
    var header = document.createElement('div');
    header.style.display = 'flex';
    header.style.alignItems = 'center';
    header.style.gap = '10px';
    header.style.marginBottom = '12px';
    
    var badge = document.createElement('div');
    badge.style.width = '32px';
    badge.style.height = '32px';
    badge.style.background = complete ? 'linear-gradient(135deg,#10b981,#14b8a6)' : '#475569';
    badge.style.borderRadius = '8px';
    badge.style.display = 'flex';
    badge.style.alignItems = 'center';
    badge.style.justifyContent = 'center';
    badge.style.color = 'white';
    badge.style.fontSize = '16px';
    badge.style.fontWeight = 'bold';
    badge.textContent = complete ? '✓' : '1';
    
    var title = document.createElement('h3');
    title.style.margin = '0';
    title.style.fontSize = '17px';
    title.style.color = '#f1f5f9';
    title.style.fontWeight = '600';
    title.textContent = 'Select';
    
    header.appendChild(badge);
    header.appendChild(title);
    section.appendChild(header);
    
    var box = document.createElement('div');
    box.style.background = 'rgba(30,41,59,0.4)';
    box.style.border = '2px dashed ' + (complete ? 'rgba(16,185,129,0.3)' : '#334155');
    box.style.borderRadius = '12px';
    box.style.padding = '16px';
    
    if (selectedFields.length === 0) {
      var emptyMsg = document.createElement('div');
      emptyMsg.style.textAlign = 'center';
      emptyMsg.style.padding = '16px';
      emptyMsg.style.color = '#64748b';
      emptyMsg.style.fontSize = '13px';
      emptyMsg.textContent = 'SHIFT+Click fields to extract';
      box.appendChild(emptyMsg);
    } else {
      for (var i = 0; i < selectedFields.length; i++) {
        var field = createFieldItem(selectedFields[i], i);
        box.appendChild(field);
      }
    }
    
    section.appendChild(box);
    return section;
  }
  
  function createFieldItem(f, idx) {
    var item = document.createElement('div');
    item.style.background = '#1e293b';
    item.style.border = '1px solid ' + '#334155';
    item.style.borderRadius = '10px';
    item.style.padding = '12px';
    item.style.marginBottom = '10px';
    
    var row = document.createElement('div');
    row.style.display = 'flex';
    row.style.gap = '8px';
    row.style.marginBottom = '8px';
    
    var input = document.createElement('input');
    input.type = 'text';
    input.value = f.name;
    input.className = 'fname';
    input.setAttribute('data-idx', idx);
    input.style.flex = '1';
    input.style.background = '#0f172a';
    input.style.border = '1px solid ' + '#334155';
    input.style.borderRadius = '8px';
    input.style.padding = '10px';
    input.style.color = '#f1f5f9';
    input.style.fontSize = '13px';
    
    var delBtn = document.createElement('button');
    delBtn.className = 'frem';
    delBtn.setAttribute('data-idx', idx);
    delBtn.style.background = '#64748b';
    delBtn.style.color = 'white';
    delBtn.style.border = 'none';
    delBtn.style.width = '32px';
    delBtn.style.height = '32px';
    delBtn.style.borderRadius = '8px';
    delBtn.style.cursor = 'pointer';
    delBtn.style.fontSize = '16px';
    delBtn.textContent = '×';
    
    row.appendChild(input);
    row.appendChild(delBtn);
    item.appendChild(row);
    
    var selector = document.createElement('div');
    selector.style.fontSize = '10px';
    selector.style.color = '#64748b';
    selector.style.fontFamily = 'monospace';
    selector.style.marginBottom = '6px';
    selector.textContent = f.selector;
    item.appendChild(selector);

    // Type toggle dropdown
    var typeColors = { text: '#3b82f6', image: '#f59e0b', link: '#a78bfa', price: '#10b981' };
    var typeLabels = { text: '📝 text', image: '🖼 image', link: '🔗 link', price: '💰 price' };
    var typeRow = document.createElement('div');
    typeRow.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:6px;';
    var typeLabel = document.createElement('span');
    typeLabel.style.cssText = 'font-size:10px;color:#64748b;';
    typeLabel.textContent = 'Type:';
    var typeSelect = document.createElement('select');
    typeSelect.setAttribute('data-idx', idx);
    typeSelect.className = 'ftype';
    typeSelect.style.cssText = 'background:' + '#0f172a' + ';border:1px solid ' + '#334155' + ';border-radius:6px;padding:3px 8px;color:' + (typeColors[f.type] || '#3b82f6') + ';font-size:11px;font-weight:600;cursor:pointer;';
    ['text','image','link','price'].forEach(function(t) {
      var opt = document.createElement('option');
      opt.value = t;
      opt.textContent = typeLabels[t];
      if (t === (f.type || 'text')) opt.selected = true;
      typeSelect.appendChild(opt);
    });
    typeRow.appendChild(typeLabel);
    typeRow.appendChild(typeSelect);
    item.appendChild(typeRow);
    
    var sample = document.createElement('div');
    sample.style.fontSize = '12px';
    sample.style.color = '#94a3b8';
    sample.style.background = true ? 'rgba(15,23,42,0.6)' : 'rgba(226,232,240,0.6)';
    sample.style.padding = '8px';
    sample.style.borderRadius = '6px';
    sample.style.overflow = 'hidden';
    sample.style.textOverflow = 'ellipsis';
    sample.style.whiteSpace = 'nowrap';
    if (f.type === 'image' && f.sample) {
      var thumb = document.createElement('img');
      thumb.src = f.sample;
      thumb.style.cssText = 'width:40px;height:40px;object-fit:cover;border-radius:4px;vertical-align:middle;margin-right:6px;';
      sample.appendChild(thumb);
      var thumbText = document.createTextNode(f.sample.substring(0, 40) + '...');
      sample.appendChild(thumbText);
    } else {
      sample.textContent = f.sample || '—';
    }
    item.appendChild(sample);
    
    return item;
  }
  
  function createStep2() {
    var section = document.createElement('div');
    section.style.marginBottom = '24px';
    
    var loadingOK = loadingMethod === 'auto-scroll' || (loadingMethod === 'pagination' && paginationButton) || (loadingMethod === 'load-more' && loadMoreButton);
    
    var header = document.createElement('div');
    header.style.display = 'flex';
    header.style.alignItems = 'center';
    header.style.gap = '10px';
    header.style.marginBottom = '12px';
    
    var badge = document.createElement('div');
    badge.style.width = '32px';
    badge.style.height = '32px';
    badge.style.background = loadingOK ? 'linear-gradient(135deg,#10b981,#14b8a6)' : '#475569';
    badge.style.borderRadius = '8px';
    badge.style.display = 'flex';
    badge.style.alignItems = 'center';
    badge.style.justifyContent = 'center';
    badge.style.color = 'white';
    badge.style.fontSize = '16px';
    badge.style.fontWeight = 'bold';
    badge.textContent = loadingOK ? '✓' : '2';
    
    var title = document.createElement('h3');
    title.style.margin = '0';
    title.style.fontSize = '17px';
    title.style.color = '#f1f5f9';
    title.style.fontWeight = '600';
    title.textContent = 'Load more items';
    
    header.appendChild(badge);
    header.appendChild(title);
    section.appendChild(header);
    
    var box = document.createElement('div');
    box.style.background = 'rgba(30,41,59,0.4)';
    box.style.border = '2px dashed ' + (loadingOK ? 'rgba(16,185,129,0.3)' : '#334155');
    box.style.borderRadius = '12px';
    box.style.padding = '14px';
    
    var opt1 = createLoadOpt('auto-scroll', '⬇️ Auto-scroll', 'Scroll automatically', loadingMethod === 'auto-scroll', true);
    var opt2 = createLoadOpt('pagination', '➡️ Pagination', 'Click next button', loadingMethod === 'pagination', paginationButton !== null);
    var opt3 = createLoadOpt('load-more', '✨ Load More', 'Click load more button', loadingMethod === 'load-more', loadMoreButton !== null);
    
    box.appendChild(opt1);
    box.appendChild(opt2);
    box.appendChild(opt3);
    section.appendChild(box);
    
    return section;
  }
  
  function createLoadOpt(method, titleTxt, descTxt, active, complete) {
    var opt = document.createElement('div');
    opt.onclick = function() { window.selectLoadingMethod(method); };
    opt.style.background = active ? 'rgba(59,130,246,0.15)' : ('rgba(30,41,59,0.6)');
    opt.style.border = '2px solid ' + (active ? '#3b82f6' : '#334155');
    opt.style.borderRadius = '10px';
    opt.style.padding = '14px';
    opt.style.marginBottom = '10px';
    opt.style.cursor = 'pointer';
    opt.style.position = 'relative';
    
    var title = document.createElement('div');
    title.style.fontWeight = '600';
    title.style.color = '#f1f5f9';
    title.style.marginBottom = '4px';
    title.style.fontSize = '14px';
    title.textContent = titleTxt;
    
    var desc = document.createElement('div');
    desc.style.fontSize = '12px';
    desc.style.color = '#94a3b8';
    desc.textContent = descTxt;
    
    opt.appendChild(title);
    opt.appendChild(desc);
    
    if (complete) {
      var check = document.createElement('div');
      check.style.position = 'absolute';
      check.style.top = '10px';
      check.style.right = '10px';
      check.style.width = '22px';
      check.style.height = '22px';
      check.style.background = 'linear-gradient(135deg,#10b981,#14b8a6)';
      check.style.borderRadius = '6px';
      check.style.color = 'white';
      check.style.fontSize = '12px';
      check.style.display = 'flex';
      check.style.alignItems = 'center';
      check.style.justifyContent = 'center';
      check.style.fontWeight = 'bold';
      check.textContent = '✓';
      opt.appendChild(check);
    }
    
    return opt;
  }
  
  function createBtns() {
    var container = document.createElement('div');
    container.style.display = 'flex';
    container.style.flexDirection = 'column';
    container.style.gap = '10px';
    container.style.marginTop = '8px';
    
    var fieldsOK = selectedFields.length > 0;
    var loadingOK = loadingMethod === 'auto-scroll' || (loadingMethod === 'pagination' && paginationButton) || (loadingMethod === 'load-more' && loadMoreButton);
    
    var extractBtn = document.createElement('button');
    extractBtn.id = 'extract-btn';
    extractBtn.disabled = !(fieldsOK && loadingOK);
    extractBtn.style.background = (fieldsOK && loadingOK) ? 'linear-gradient(to right,#3b82f6,#14b8a6)' : '#475569';
    extractBtn.style.color = 'white';
    extractBtn.style.border = 'none';
    extractBtn.style.padding = '16px';
    extractBtn.style.borderRadius = '12px';
    extractBtn.style.cursor = (fieldsOK && loadingOK) ? 'pointer' : 'not-allowed';
    extractBtn.style.fontWeight = '600';
    extractBtn.style.width = '100%';
    extractBtn.style.fontSize = '15px';
    extractBtn.style.opacity = (fieldsOK && loadingOK) ? '1' : '0.5';
    extractBtn.textContent = 'Extract (' + selectedFields.length + ')';
    
    var restartBtn = document.createElement('button');
    restartBtn.id = 'restart-btn';
    restartBtn.style.background = 'transparent';
    restartBtn.style.color = '#94a3b8';
    restartBtn.style.border = '2px solid ' + '#334155';
    restartBtn.style.padding = '14px';
    restartBtn.style.borderRadius = '12px';
    restartBtn.style.cursor = 'pointer';
    restartBtn.style.fontWeight = '600';
    restartBtn.style.width = '100%';
    restartBtn.style.fontSize = '15px';
    restartBtn.textContent = 'Start Over';
    
    container.appendChild(extractBtn);
    container.appendChild(restartBtn);
    
    return container;
  }
  
  function attachListeners() {
    var panel = document.getElementById('basira-panel');
    
    var inputs = panel.querySelectorAll('.fname');
    for (var i = 0; i < inputs.length; i++) {
      inputs[i].oninput = function() {
        selectedFields[parseInt(this.getAttribute('data-idx'))].name = this.value;
      };
    }

    var typeSelects = panel.querySelectorAll('.ftype');
    for (var i = 0; i < typeSelects.length; i++) {
      typeSelects[i].onchange = function() {
        var idx = parseInt(this.getAttribute('data-idx'));
        selectedFields[idx].type = this.value;
        updatePanel();
      };
    }
    
    var btns = panel.querySelectorAll('.frem');
    for (var i = 0; i < btns.length; i++) {
      btns[i].onclick = function() {
        var idx = parseInt(this.getAttribute('data-idx'));
        selectedFields[idx].element.style.outline = '';
        selectedFields[idx].element.style.outlineOffset = '';
        selectedFields.splice(idx, 1);
        updatePanel();
      };
    }
    
    var extractBtn = document.getElementById('extract-btn');
    if (extractBtn && !extractBtn.disabled) extractBtn.onclick = extract;
    
    var restartBtn = document.getElementById('restart-btn');
    if (restartBtn) restartBtn.onclick = function() {
      selectedFields.forEach(function(f) { f.element.style.outline = ''; f.element.style.outlineOffset = ''; });
      if (referenceItem) { referenceItem.style.outline = ''; referenceItem.style.outlineOffset = ''; }
      selectedFields = [];
      referenceItem = null;
      currentListElement = null;
      isSelecting = false;
      loadingMethod = 'auto-scroll';
      paginationButton = null;
      loadMoreButton = null;
      document.removeEventListener('click', handleFieldClick, true);
      showStartScreen();
    };
  }
  
  function showPaginationSelector() {
    var panel = document.getElementById('basira-panel');
    panel.innerHTML = '';

    var header = document.createElement('div');
    header.style.cssText = 'padding:16px 20px;background:' + 'linear-gradient(135deg,#1e293b,#0f172a)' + ';border-bottom:1px solid ' + '#334155' + ';display:flex;align-items:center;gap:12px;';
    var backBtn = document.createElement('button');
    backBtn.style.cssText = 'background:' + '#1e293b' + ';border:1px solid ' + '#334155' + ';color:' + '#94a3b8' + ';width:32px;height:32px;border-radius:8px;cursor:pointer;font-size:16px;display:flex;align-items:center;justify-content:center;flex-shrink:0;';
    backBtn.textContent = '←';
    backBtn.onclick = function() {
      document.removeEventListener('mouseover', pagHover, true);
      document.removeEventListener('click', pagClick, true);
      updatePanel();
    };
    var headerTitle = document.createElement('span');
    headerTitle.style.cssText = 'font-size:14px;font-weight:600;color:#f1f5f9;';
    headerTitle.textContent = 'Select Pagination Element';
    header.appendChild(backBtn);
    header.appendChild(headerTitle);
    panel.appendChild(header);

    var body = document.createElement('div');
    body.style.cssText = 'padding:20px;display:flex;flex-direction:column;gap:14px;';

    var steps = [
      { num: '1', title: 'Hover', desc: 'Move your cursor over the Next Page or pagination button on the page' },
      { num: '2', title: 'Click', desc: 'Click it — Basira will capture the selector automatically' }
    ];
    steps.forEach(function(s) {
      var card = document.createElement('div');
      card.style.cssText = 'background:' + '#1e293b' + ';border:1px solid ' + '#334155' + ';border-radius:12px;padding:16px;display:flex;gap:14px;align-items:flex-start;';
      var num = document.createElement('div');
      num.style.cssText = 'width:32px;height:32px;background:linear-gradient(135deg,#3b82f6,#14b8a6);border-radius:8px;display:flex;align-items:center;justify-content:center;font-weight:bold;font-size:14px;color:white;flex-shrink:0;';
      num.textContent = s.num;
      var txt = document.createElement('div');
      var t = document.createElement('div');
      t.style.cssText = 'font-size:13px;font-weight:600;color:#f1f5f9;margin-bottom:4px;';
      t.textContent = s.title;
      var d = document.createElement('div');
      d.style.cssText = 'font-size:12px;color:#64748b;line-height:1.5;';
      d.textContent = s.desc;
      txt.appendChild(t); txt.appendChild(d);
      card.appendChild(num); card.appendChild(txt);
      body.appendChild(card);
    });

    var cancelBtn = document.createElement('button');
    cancelBtn.style.cssText = 'margin-top:8px;padding:12px;background:' + '#1e293b' + ';border:1px solid ' + '#334155' + ';color:' + '#94a3b8' + ';border-radius:10px;cursor:pointer;font-size:13px;font-weight:600;width:100%;';
    cancelBtn.textContent = 'Cancel Selection';
    cancelBtn.onclick = function() {
      document.removeEventListener('mouseover', pagHover, true);
      document.removeEventListener('click', pagClick, true);
      updatePanel();
    };
    body.appendChild(cancelBtn);
    panel.appendChild(body);

    document.addEventListener('mouseover', pagHover, true);
    document.addEventListener('click', pagClick, true);
  }
  
  function pagHover(e) {
    if (e.target.closest('#basira-panel')) return;
    e.target.style.outline = '3px solid #3b82f6';
    e.target.style.outlineOffset = '2px';
    e.target.addEventListener('mouseout', function() { this.style.outline = ''; this.style.outlineOffset = ''; }, {once:true});
  }
  
  function pagClick(e) {
    if (e.target.closest('#basira-panel')) return;
    e.preventDefault();
    e.stopPropagation();
    
    paginationButton = { selector: getButtonSelector(e.target) };
    
    document.removeEventListener('mouseover', pagHover, true);
    document.removeEventListener('click', pagClick, true);
    
    updatePanel();
  }
  
  function showLoadMoreSelector() {
    var panel = document.getElementById('basira-panel');
    panel.innerHTML = '';

    var header = document.createElement('div');
    header.style.cssText = 'padding:16px 20px;background:' + 'linear-gradient(135deg,#1e293b,#0f172a)' + ';border-bottom:1px solid ' + '#334155' + ';display:flex;align-items:center;gap:12px;';
    var backBtn = document.createElement('button');
    backBtn.style.cssText = 'background:' + '#1e293b' + ';border:1px solid ' + '#334155' + ';color:' + '#94a3b8' + ';width:32px;height:32px;border-radius:8px;cursor:pointer;font-size:16px;display:flex;align-items:center;justify-content:center;flex-shrink:0;';
    backBtn.textContent = '←';
    backBtn.onclick = function() {
      document.removeEventListener('mouseover', lmHover, true);
      document.removeEventListener('click', lmClick, true);
      updatePanel();
    };
    var headerTitle = document.createElement('span');
    headerTitle.style.cssText = 'font-size:14px;font-weight:600;color:#f1f5f9;';
    headerTitle.textContent = 'Select Load More Element';
    header.appendChild(backBtn);
    header.appendChild(headerTitle);
    panel.appendChild(header);

    var body = document.createElement('div');
    body.style.cssText = 'padding:20px;display:flex;flex-direction:column;gap:14px;';

    var steps = [
      { num: '1', title: 'Hover', desc: 'Move your cursor over the Load More or Show More button on the page' },
      { num: '2', title: 'Click', desc: 'Click it — Basira will capture the selector automatically' }
    ];
    steps.forEach(function(s) {
      var card = document.createElement('div');
      card.style.cssText = 'background:' + '#1e293b' + ';border:1px solid ' + '#334155' + ';border-radius:12px;padding:16px;display:flex;gap:14px;align-items:flex-start;';
      var num = document.createElement('div');
      num.style.cssText = 'width:32px;height:32px;background:linear-gradient(135deg,#3b82f6,#14b8a6);border-radius:8px;display:flex;align-items:center;justify-content:center;font-weight:bold;font-size:14px;color:white;flex-shrink:0;';
      num.textContent = s.num;
      var txt = document.createElement('div');
      var t = document.createElement('div');
      t.style.cssText = 'font-size:13px;font-weight:600;color:#f1f5f9;margin-bottom:4px;';
      t.textContent = s.title;
      var d = document.createElement('div');
      d.style.cssText = 'font-size:12px;color:#64748b;line-height:1.5;';
      d.textContent = s.desc;
      txt.appendChild(t); txt.appendChild(d);
      card.appendChild(num); card.appendChild(txt);
      body.appendChild(card);
    });

    var cancelBtn = document.createElement('button');
    cancelBtn.style.cssText = 'margin-top:8px;padding:12px;background:' + '#1e293b' + ';border:1px solid ' + '#334155' + ';color:' + '#94a3b8' + ';border-radius:10px;cursor:pointer;font-size:13px;font-weight:600;width:100%;';
    cancelBtn.textContent = 'Cancel Selection';
    cancelBtn.onclick = function() {
      document.removeEventListener('mouseover', lmHover, true);
      document.removeEventListener('click', lmClick, true);
      updatePanel();
    };
    body.appendChild(cancelBtn);
    panel.appendChild(body);

    document.addEventListener('mouseover', lmHover, true);
    document.addEventListener('click', lmClick, true);
  }
  
  function lmHover(e) {
    if (e.target.closest('#basira-panel')) return;
    e.target.style.outline = '3px solid #3b82f6';
    e.target.style.outlineOffset = '2px';
    e.target.addEventListener('mouseout', function() { this.style.outline = ''; this.style.outlineOffset = ''; }, {once:true});
  }
  
  function lmClick(e) {
    if (e.target.closest('#basira-panel')) return;
    e.preventDefault();
    e.stopPropagation();
    
    loadMoreButton = { selector: getButtonSelector(e.target) };
    
    document.removeEventListener('mouseover', lmHover, true);
    document.removeEventListener('click', lmClick, true);
    
    updatePanel();
  }
  
  function getButtonSelector(el) {
    if (el.id) return '#' + el.id;
    var dataNames = ['data-testid','data-cy','data-qa','data-test','aria-label'];
    for (var d = 0; d < dataNames.length; d++) {
      var dv = el.getAttribute(dataNames[d]);
      if (dv) return '[' + dataNames[d] + '="' + dv + '"]';
    }
    var sc = getBestClass(el);
    if (sc) return '.' + sc;
    var path = [];
    var cur = el;
    var max = 3;
    while (cur && cur !== document.body && max > 0) {
      max--;
      var tag = cur.tagName.toLowerCase();
      var cls = getBestClass(cur);
      if (cls) { path.unshift('.' + cls); break; }
      if (cur.id) { path.unshift('#' + cur.id); break; }
      if (cur.parentElement) {
        var sibs = Array.from(cur.parentElement.children).filter(function(s) { return s.tagName === cur.tagName; });
        path.unshift(sibs.length > 1 ? tag + ':nth-of-type(' + (sibs.indexOf(cur) + 1) + ')' : tag);
      } else { path.unshift(tag); }
      cur = cur.parentElement;
    }
    return path.join(' ');
  }
  
  function extract() {
    var itemClass = getBestClass(referenceItem);
    var itemSelector = itemClass ? '.' + itemClass : referenceItem.tagName.toLowerCase();

    var containerSelector = '';
    if (currentListElement.id) {
      containerSelector = '#' + currentListElement.id;
    } else {
      var cdns = ['data-testid','data-cy','data-qa','data-test'];
      for (var cd = 0; cd < cdns.length; cd++) {
        var cdv = currentListElement.getAttribute(cdns[cd]);
        if (cdv) { containerSelector = '[' + cdns[cd] + '="' + cdv + '"]'; break; }
      }
    }
    if (!containerSelector) {
      var contClass = getBestClass(currentListElement);
      containerSelector = contClass ? '.' + contClass : currentListElement.tagName.toLowerCase();
    }
    
    window.basiraResults = {
      parentSelector: containerSelector,
      itemSelector: itemSelector,
      loadingMethod: loadingMethod,
      paginationSelector: paginationButton ? paginationButton.selector : null,
      loadMoreSelector: loadMoreButton ? loadMoreButton.selector : null,
      fields: selectedFields.map(function(f) {
        return {name:f.name, selector:f.selector, sample:f.sample, type: f.type || 'text'};
      })
    };
    
    var panel = document.getElementById('basira-panel');
    panel.innerHTML = '<div style="padding:60px 40px;text-align:center;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;"><div style="width:100px;height:100px;background:linear-gradient(135deg,#10b981,#14b8a6);border-radius:24px;display:flex;align-items:center;justify-content:center;font-size:50px;color:white;">✓</div><h3 style="margin:32px 0 12px 0;color:white;font-size:26px;font-weight:bold;">Ready!</h3><p style="margin:0;color:#94a3b8;font-size:14px;">Processing your selection...</p></div>';
  }
  
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    setTimeout(init, 1000);
  }
  
})();
`;

module.exports = { overlayScript };
