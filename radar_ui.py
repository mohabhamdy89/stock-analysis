"""Radar Screen UI — CSS, JS, and HTML strings injected into the main dashboard."""

# ── CSS ───────────────────────────────────────────────────────────────────────

RADAR_CSS = """
/* ── Radar Screen ─────────────────────────────────────────────────── */
.radar-wrap{padding:0 0 40px 0}
/* search bar */
.radar-search-row{display:flex;align-items:center;gap:10px;padding:16px 36px;background:#fff;border-bottom:1px solid #e2e8f0}
.radar-search-row input{flex:1;max-width:280px;padding:8px 14px;border:1px solid #e2e8f0;border-radius:20px;font-size:.84rem;outline:none;color:#1a1a1a;background:#f5f5f5;transition:border-color .15s}
.radar-search-row input:focus{border-color:#3b82f6;background:#fff}
.radar-add-btn{padding:8px 18px;background:linear-gradient(135deg,#2563eb,#4f46e5);border:none;border-radius:20px;color:#fff;font-size:.78rem;font-weight:700;cursor:pointer;transition:opacity .15s}
.radar-add-btn:hover{opacity:.85}
.radar-refresh-btn{padding:8px 16px;background:#f5f5f5;border:1px solid #e2e8f0;border-radius:20px;color:#475569;font-size:.78rem;font-weight:600;cursor:pointer;transition:background .15s;margin-left:auto}
.radar-refresh-btn:hover{background:#e2e8f0}
.radar-refresh-btn:disabled{opacity:.5;cursor:not-allowed}
.radar-ts{font-size:.72rem;color:#94a3b8;white-space:nowrap}
/* summary cards */
.radar-cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;padding:20px 36px}
.rc{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:14px 18px;box-shadow:0 1px 3px rgba(0,0,0,.04);min-width:0}
.rc-label{font-size:.6rem;font-weight:800;letter-spacing:1.2px;text-transform:uppercase;color:#94a3b8;margin-bottom:6px}
.rc-ticker{font-size:1.1rem;font-weight:900;color:#1a1a1a;margin-bottom:2px}
.rc-val{font-size:.8rem;font-weight:600;color:#475569}
.rc-val.up{color:#16a34a}.rc-val.dn{color:#dc2626}.rc-val.warn{color:#d97706}
/* main table area */
.radar-main{padding:0 36px}
.radar-tbl-wrap{border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;overflow-x:auto;box-shadow:0 1px 3px rgba(0,0,0,.04)}
table.radar-tbl{width:100%;border-collapse:collapse;min-width:1100px}
table.radar-tbl thead th{background:#f5f5f5;padding:10px 12px;font-size:.62rem;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:#94a3b8;text-align:left;white-space:nowrap;position:sticky;top:0;z-index:10}
table.radar-tbl thead th.s{cursor:pointer;user-select:none;transition:color .15s}
table.radar-tbl thead th.s:hover{color:#3b82f6}
table.radar-tbl thead th.s.desc::after{content:' ▼';color:#3b82f6}
table.radar-tbl thead th.s.asc::after{content:' ▲';color:#3b82f6}
table.radar-tbl thead th.s::after{content:' ▲▼';opacity:.25;font-size:.65em}
table.radar-tbl tbody tr.rr{border-top:1px solid #f0f0f0;cursor:pointer;transition:background .1s}
table.radar-tbl tbody tr.rr.bg-green{background:rgba(22,163,74,.05)}
table.radar-tbl tbody tr.rr.bg-yellow{background:rgba(217,119,6,.04)}
table.radar-tbl tbody tr.rr.bg-red{background:rgba(220,38,38,.04)}
table.radar-tbl tbody tr.rr:hover{filter:brightness(.97)}
table.radar-tbl td{padding:10px 12px;font-size:.82rem;vertical-align:middle;white-space:nowrap}
.r-ticker{font-size:.92rem;font-weight:800;color:#1a1a1a}
.r-name{font-size:.68rem;color:#94a3b8;font-weight:400}
.r-price{font-weight:700;color:#1a1a1a}
/* composite score pill */
.cs-pill{display:inline-flex;align-items:center;justify-content:center;width:36px;height:36px;border-radius:50%;font-size:.82rem;font-weight:900;flex-shrink:0}
.cs-pill.hi{background:rgba(22,163,74,.12);color:#16a34a}
.cs-pill.md{background:rgba(217,119,6,.1);color:#d97706}
.cs-pill.lo{background:rgba(220,38,38,.09);color:#dc2626}
/* signal badge — reuse existing .badge class */
/* RSI pill */
.rsi-val{font-size:.8rem;font-weight:700}
.rsi-val.ob{color:#dc2626}.rsi-val.os{color:#16a34a}.rsi-val.ok{color:#475569}
/* earnings */
.earn-soon{color:#dc2626;font-weight:700}
.earn-ok{color:#475569}
/* sentiment dot */
.sent-dot{display:inline-flex;align-items:center;gap:5px;font-size:.78rem;font-weight:600}
.sent-dot::before{content:'';width:7px;height:7px;border-radius:50%;flex-shrink:0}
.sent-dot.Positive{color:#16a34a}.sent-dot.Positive::before{background:#16a34a}
.sent-dot.Negative{color:#dc2626}.sent-dot.Negative::before{background:#dc2626}
.sent-dot.Neutral{color:#d97706}.sent-dot.Neutral::before{background:#d97706}
.sent-dot.NA{color:#94a3b8}.sent-dot.NA::before{background:#cbd5e1}
/* insider */
.ins-buy{color:#16a34a;font-weight:700}.ins-sell{color:#dc2626;font-weight:700}
/* remove button */
.r-rm{background:none;border:none;color:#cbd5e1;cursor:pointer;font-size:.9rem;padding:2px 6px;border-radius:4px;transition:color .15s}
.r-rm:hover{color:#dc2626}
/* detail expand */
table.radar-tbl tr.rdrow td{padding:0;border:none}
.rdinn{display:none;padding:20px 24px;background:#fafafa;border-top:1px solid #efefef}
.rdinn.open{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px}
.rdi{background:#fff;border-radius:8px;padding:10px 14px;border:1px solid #e2e8f0}
.rdi-lbl{font-size:.6rem;font-weight:800;letter-spacing:.8px;text-transform:uppercase;color:#94a3b8;margin-bottom:3px}
.rdi-val{font-size:.82rem;color:#1a1a1a;font-weight:600}
.rdi-val.up{color:#16a34a}.rdi-val.dn{color:#dc2626}.rdi-val.warn{color:#d97706}
/* headlines list */
.headlines{grid-column:1/-1;background:#fff;border-radius:8px;padding:12px 16px;border:1px solid #e2e8f0}
.headlines ul{list-style:none;margin:0;padding:0}
.headlines li{font-size:.78rem;color:#475569;padding:3px 0;border-bottom:1px solid #f5f5f5}
.headlines li:last-child{border-bottom:none}
/* loading spinner */
.radar-spinner{display:none;text-align:center;padding:40px 20px;color:#94a3b8}
.radar-spinner.show{display:block}
.spinner-ring{display:inline-block;width:32px;height:32px;border:3px solid #e2e8f0;border-top-color:#3b82f6;border-radius:50%;animation:spin .7s linear infinite;margin-bottom:10px}
@keyframes spin{to{transform:rotate(360deg)}}
/* empty / error states */
.radar-empty{text-align:center;padding:56px 20px;color:#94a3b8}
/* mobile */
@media(max-width:900px){
  .radar-cards{grid-template-columns:repeat(2,1fr)}
  .radar-search-row,.radar-main{padding-left:16px;padding-right:16px}
  .radar-cards{padding:12px 16px}
}
"""


# ── HTML ──────────────────────────────────────────────────────────────────────

RADAR_HTML = (
    '<div class="radar-wrap">'

    # search + controls
    '<div class="radar-search-row">'
    '<input type="text" id="radar-search" placeholder="Add ticker (e.g. AAPL)…" maxlength="10"'
    '  onkeydown="if(event.key===\'Enter\')radarAdd()">'
    '<button class="radar-add-btn" onclick="radarAdd()">+ Add</button>'
    '<button class="radar-refresh-btn" id="radar-rbtn" onclick="radarRefresh(true)">&#8635; Refresh All</button>'
    '<span class="radar-ts" id="radar-ts"></span>'
    '</div>'

    # summary cards
    '<div class="radar-cards">'
    '<div class="rc" id="rc-best"><div class="rc-label">Best Opportunity</div>'
    '<div class="rc-ticker">—</div><div class="rc-val">—</div></div>'
    '<div class="rc" id="rc-rsi"><div class="rc-label">Most Overbought</div>'
    '<div class="rc-ticker">—</div><div class="rc-val">—</div></div>'
    '<div class="rc" id="rc-earn"><div class="rc-label">Earnings Soon</div>'
    '<div class="rc-ticker">—</div><div class="rc-val rc-val warn">—</div></div>'
    '<div class="rc" id="rc-ins"><div class="rc-label">Insider Buying</div>'
    '<div class="rc-ticker">—</div><div class="rc-val">—</div></div>'
    '</div>'

    # spinner
    '<div class="radar-main">'
    '<div class="radar-spinner" id="radar-spinner">'
    '<div class="spinner-ring"></div><div>Loading watchlist data…</div>'
    '</div>'

    # table
    '<div class="radar-tbl-wrap" id="radar-tbl-wrap" style="display:none">'
    '<table class="radar-tbl" id="radar-tbl">'
    '<thead><tr id="radar-thead"></tr></thead>'
    '<tbody id="radar-tbody"></tbody>'
    '</table>'
    '</div>'

    '</div>'  # /radar-main
    '</div>'  # /radar-wrap
)


# ── JavaScript ────────────────────────────────────────────────────────────────

RADAR_JS = r"""
// ── Radar Screen ──────────────────────────────────────────────────────────────
let radarData      = [];
let radarSort      = {col: 'composite', dir: -1};
let radarInitialized = false;
const RADAR_COLS = [
  {k:'ticker',    h:'Ticker',     s:false},
  {k:'price',     h:'Price',      s:true},
  {k:'composite', h:'Score',      s:true},
  {k:'signal',    h:'Signal',     s:false},
  {k:'rsi',       h:'RSI',        s:true},
  {k:'macd',      h:'MACD',       s:false},
  {k:'pe',        h:'P/E',        s:true},
  {k:'fpe',       h:'Fwd P/E',    s:true},
  {k:'upside',    h:'Upside',     s:true, raw:'upside_raw'},
  {k:'earn_date', h:'Earnings',   s:true, raw:'earn_days'},
  {k:'beta',      h:'Beta',       s:true},
  {k:'rs_30d',    h:'RS 30d',     s:true, raw:'rs_30d_raw'},
  {k:'sentiment', h:'Sentiment',  s:false},
  {k:'insider_type', h:'Insider', s:false},
  {k:'inst_own',  h:'Inst Own',   s:false},
  {k:'_rm',       h:'',           s:false},
];

function radarSortedData() {
  const col = radarSort.col;
  const dir = radarSort.dir;
  return [...radarData].sort((a, b) => {
    const raw = RADAR_COLS.find(c => c.k === col);
    const key = (raw && raw.raw) ? raw.raw : col;
    let av = a[key], bv = b[key];
    if (av === 'N/A' || av == null) av = dir < 0 ? -Infinity : Infinity;
    if (bv === 'N/A' || bv == null) bv = dir < 0 ? -Infinity : Infinity;
    if (typeof av === 'string') av = parseFloat(av) || av;
    if (typeof bv === 'string') bv = parseFloat(bv) || bv;
    if (av < bv) return dir;
    if (av > bv) return -dir;
    return 0;
  });
}

function radarSortBy(col) {
  radarSort.dir = (radarSort.col === col) ? radarSort.dir * -1 : -1;
  radarSort.col = col;
  renderRadarTable();
}

function rsiCls(v) {
  if (v === 'N/A' || v == null) return 'ok';
  const n = parseFloat(v);
  if (n >= 70) return 'ob';
  if (n <= 30) return 'os';
  return 'ok';
}

function csPillCls(v) {
  if (v >= 7) return 'hi';
  if (v >= 4) return 'md';
  return 'lo';
}

function rowBgCls(v) {
  if (v >= 7) return 'bg-green';
  if (v >= 4) return 'bg-yellow';
  return 'bg-red';
}

function signalBadge(sig) {
  if (!sig || sig === 'N/A') return '<span style="color:#94a3b8">N/A</span>';
  const map = {
    'STRONG BUY':'strong-buy','BUY':'buy','NEUTRAL':'neutral',
    'SELL':'sell','STRONG SELL':'strong-sell'
  };
  const cls = map[sig] || 'neutral';
  return '<span class="badge '+cls+'">'+sig+'</span>';
}

function sentDot(s) {
  const cls = s === 'N/A' ? 'NA' : s;
  return '<span class="sent-dot '+cls+'">'+s+'</span>';
}

function earnCell(d, days) {
  if (d === 'N/A') return '<span style="color:#94a3b8">N/A</span>';
  const cls = (typeof days === 'number' && days >= 0 && days <= 14) ? 'earn-soon' : 'earn-ok';
  const label = (typeof days === 'number' && days >= 0) ? days+'d' : '';
  return '<span class="'+cls+'">'+d+(label ? ' <small>('+label+')</small>' : '')+'</span>';
}

function insiderCell(type, val, daysAgo) {
  if (type === 'N/A') return '<span style="color:#94a3b8">N/A</span>';
  const cls = type === 'Buy' ? 'ins-buy' : (type === 'Sell' ? 'ins-sell' : '');
  const ago = (typeof daysAgo === 'number') ? ' <small style="color:#94a3b8">'+daysAgo+'d ago</small>' : '';
  return '<span class="'+cls+'">'+type+'</span>'+(val && val !== 'N/A' ? ' <small>'+val+'</small>' : '')+ago;
}

function renderRadarHeader() {
  const tr = document.getElementById('radar-thead');
  if (!tr) return;
  tr.innerHTML = RADAR_COLS.map(c => {
    if (!c.s) return '<th'+(c.k==='_rm'?' style="width:36px"':'')+'>'+(c.h)+'</th>';
    const active = c.k === radarSort.col;
    const dirCls = active ? (radarSort.dir < 0 ? ' desc' : ' asc') : '';
    return '<th class="s'+dirCls+'" onclick="radarSortBy(\''+c.k+'\')">'+c.h+'</th>';
  }).join('');
}

function renderRadarTable() {
  const tbody = document.getElementById('radar-tbody');
  if (!tbody) return;
  renderRadarHeader();
  const sorted = radarSortedData();
  tbody.innerHTML = '';
  if (!sorted.length) {
    tbody.innerHTML = '<tr><td colspan="'+RADAR_COLS.length+'" class="radar-empty">No stocks in watchlist. Add a ticker above.</td></tr>';
    return;
  }
  for (const r of sorted) {
    const bgCls = rowBgCls(r.composite || 0);
    const csCls = csPillCls(r.composite || 0);
    // main row
    const tr = document.createElement('tr');
    tr.className = 'rr ' + bgCls;
    tr.id = 'rr-' + r.ticker;
    tr.onclick = () => toggleRadarDetail(r.ticker);
    tr.innerHTML =
      '<td><div class="r-ticker">'+r.ticker+'</div>'+(r.name&&r.name!==r.ticker?'<div class="r-name">'+r.name+'</div>':'')+'</td>'+
      '<td class="r-price">'+(r.price!=='N/A'?'$'+r.price:r.price)+'</td>'+
      '<td><span class="cs-pill '+csCls+'">'+(r.composite||'—')+'</span></td>'+
      '<td>'+signalBadge(r.signal)+'</td>'+
      '<td><span class="rsi-val '+rsiCls(r.rsi)+'">'+r.rsi+'</span></td>'+
      '<td>'+r.macd+'</td>'+
      '<td>'+r.pe+'</td>'+
      '<td>'+r.fpe+'</td>'+
      '<td>'+(r.upside||'N/A')+'</td>'+
      '<td>'+earnCell(r.earn_date, r.earn_days)+'</td>'+
      '<td>'+r.beta+'</td>'+
      '<td>'+r.rs_30d+'</td>'+
      '<td>'+sentDot(r.sentiment||'N/A')+'</td>'+
      '<td>'+insiderCell(r.insider_type, r.insider_val, r.insider_days)+'</td>'+
      '<td>'+r.inst_own+'</td>'+
      '<td><button class="r-rm" title="Remove" onclick="event.stopPropagation();radarRemove(\''+r.ticker+'\')">&#x2715;</button></td>';
    tbody.appendChild(tr);
    // detail expand row
    const dtr = document.createElement('tr');
    dtr.className = 'rdrow';
    dtr.id = 'rdrow-' + r.ticker;
    dtr.innerHTML = '<td colspan="'+RADAR_COLS.length+'"><div class="rdinn" id="rdinn-'+r.ticker+'">'+buildRadarDetail(r)+'</div></td>';
    tbody.appendChild(dtr);
    if (r.error) {
      tr.cells[0].innerHTML += '<br><small style="color:#dc2626">'+r.error+'</small>';
    }
  }
  renderRadarCards(sorted);
  document.getElementById('radar-ts').textContent = 'Updated '+new Date().toLocaleTimeString();
}

function buildRadarDetail(r) {
  const items = [
    ['EPS Growth', r.eps_growth],
    ['Rev Growth', r.rev_growth],
    ['Profit Margin', r.margin],
    ['Analyst Target', r.target !== 'N/A' ? '$'+r.target : 'N/A'],
    ['Upside to Target', r.upside],
    ['Analyst Buy', r.analyst_buy],
    ['Analyst Hold', r.analyst_hold],
    ['Analyst Sell', r.analyst_sell],
    ['Short Interest', r.short_int],
    ['52W Position', r.w52_pos],
    ['Institutional Own', r.inst_own],
    ['Inst QoQ Change', r.inst_qoq],
    ['Insider Type', r.insider_type],
    ['Insider Value', r.insider_val],
    ['Insider Days Ago', typeof r.insider_days === 'number' ? r.insider_days+'d' : r.insider_days],
    ['MACD Direction', r.macd],
    ['Beta', r.beta],
    ['RS vs SPY 30d', r.rs_30d],
  ];
  const cells = items.map(([lbl, val]) => {
    let vcls = '';
    if (typeof val === 'string') {
      if (val.startsWith('+')) vcls = 'up';
      else if (val.startsWith('-') || val === 'Sell') vcls = 'dn';
      else if (val === 'Buy') vcls = 'up';
    }
    return '<div class="rdi"><div class="rdi-lbl">'+lbl+'</div><div class="rdi-val '+vcls+'">'+(val||'N/A')+'</div></div>';
  }).join('');
  let hlHtml = '';
  if (r.headlines && r.headlines.length) {
    hlHtml = '<div class="headlines"><div class="rdi-lbl" style="margin-bottom:6px">Recent Headlines</div><ul>'+
      r.headlines.map(h => '<li>'+h.replace(/</g,'&lt;').replace(/>/g,'&gt;')+'</li>').join('')+
      '</ul></div>';
  }
  return cells + hlHtml;
}

function toggleRadarDetail(ticker) {
  const el = document.getElementById('rdinn-' + ticker);
  if (el) el.classList.toggle('open');
}

function renderRadarCards(sorted) {
  // Best opportunity
  const best = sorted.reduce((b, r) => (!b || r.composite > b.composite) ? r : b, null);
  if (best) {
    const el = document.getElementById('rc-best');
    el.querySelector('.rc-ticker').textContent = best.ticker;
    el.querySelector('.rc-val').textContent = 'Composite: ' + best.composite;
    el.querySelector('.rc-val').className = 'rc-val up';
  }
  // Most overbought
  const obRsI = sorted.filter(r => r.rsi !== 'N/A').reduce((b, r) => {
    const rv = parseFloat(r.rsi); const bv = b ? parseFloat(b.rsi) : 0;
    return rv > bv ? r : b;
  }, null);
  if (obRsI) {
    const el = document.getElementById('rc-rsi');
    el.querySelector('.rc-ticker').textContent = obRsI.ticker;
    el.querySelector('.rc-val').textContent = 'RSI: ' + obRsI.rsi;
    const v = parseFloat(obRsI.rsi);
    el.querySelector('.rc-val').className = 'rc-val ' + (v >= 70 ? 'dn' : 'ok');
  }
  // Earnings soon
  const earnSoon = sorted.filter(r => typeof r.earn_days === 'number' && r.earn_days >= 0)
    .sort((a, b) => a.earn_days - b.earn_days)[0];
  if (earnSoon) {
    const el = document.getElementById('rc-earn');
    el.querySelector('.rc-ticker').textContent = earnSoon.ticker;
    el.querySelector('.rc-val').textContent = earnSoon.earn_date + ' (' + earnSoon.earn_days + 'd)';
    el.querySelector('.rc-val').className = 'rc-val ' + (earnSoon.earn_days <= 14 ? 'warn' : '');
  }
  // Insider buying
  const insiderBuy = sorted.filter(r => r.insider_type === 'Buy')
    .sort((a, b) => (a.insider_days || 999) - (b.insider_days || 999))[0];
  if (insiderBuy) {
    const el = document.getElementById('rc-ins');
    el.querySelector('.rc-ticker').textContent = insiderBuy.ticker;
    const dago = typeof insiderBuy.insider_days === 'number' ? insiderBuy.insider_days+'d ago' : '';
    el.querySelector('.rc-val').textContent = (insiderBuy.insider_val || 'Buy') + (dago ? ' · '+dago : '');
    el.querySelector('.rc-val').className = 'rc-val up';
  }
}

// ── Watchlist management ──────────────────────────────────────────────────────
function radarAdd() {
  const input = document.getElementById('radar-search');
  const ticker = (input.value || '').trim().toUpperCase();
  if (!ticker) return;
  input.value = '';
  if (radarData.length >= 25) { alert('Watchlist is full (max 25 stocks)'); return; }
  if (radarData.find(r => r.ticker === ticker)) return;  // already there
  // Optimistically add placeholder row, then load
  radarData.push({ticker, composite: 0, signal: 'N/A', price: '…', rsi: '…',
    macd:'…',pe:'…',fpe:'…',upside:'…',earn_date:'…',earn_days:null,beta:'…',
    rs_30d:'…',sentiment:'…',insider_type:'…',insider_val:'…',insider_days:'…',inst_own:'…'});
  renderRadarTable();
  document.getElementById('radar-tbl-wrap').style.display = '';
  // Save + fetch
  fetch('/api/radar/watchlist', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({action:'add', ticker}),
  }).then(() => {
    return fetch('/api/radar/stock/'+ticker);
  }).then(r => r.json()).then(data => {
    const idx = radarData.findIndex(r => r.ticker === ticker);
    if (idx >= 0) radarData[idx] = data;
    renderRadarTable();
  }).catch(err => console.error('radarAdd error', err));
}

function radarRemove(ticker) {
  radarData = radarData.filter(r => r.ticker !== ticker);
  renderRadarTable();
  fetch('/api/radar/watchlist', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({action:'remove', ticker}),
  }).catch(err => console.error('radarRemove error', err));
}

// ── Load / refresh ────────────────────────────────────────────────────────────
function radarRefresh(force) {
  const btn = document.getElementById('radar-rbtn');
  if (btn) { btn.disabled = true; btn.textContent = '⟳ Refreshing…'; }
  document.getElementById('radar-spinner').classList.add('show');
  document.getElementById('radar-tbl-wrap').style.display = 'none';
  const url = '/api/radar/data' + (force ? '?force=1' : '');
  fetch(url).then(r => r.json()).then(data => {
    radarData = data.stocks || [];
    renderRadarTable();
    document.getElementById('radar-spinner').classList.remove('show');
    document.getElementById('radar-tbl-wrap').style.display = '';
    if (btn) { btn.disabled = false; btn.textContent = '⟳ Refresh All'; }
  }).catch(err => {
    document.getElementById('radar-spinner').classList.remove('show');
    if (btn) { btn.disabled = false; btn.textContent = '⟳ Refresh All'; }
    console.error('radarRefresh error', err);
  });
}

function initRadar() {
  radarRefresh(false);
}
"""
