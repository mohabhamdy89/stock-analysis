#!/usr/bin/env python3
"""News Terminal UI — CSS, JS, and HTML strings for the News Terminal tab."""

NEWS_CSS = """
/* ── News Terminal ─────────────────────────────────────────────────────────── */
.nt-wrap{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;padding:24px 36px;max-width:1600px;margin:0 auto}
.nt-panel{border-radius:12px;border:1px solid #e2e8f0;overflow:hidden;display:flex;flex-direction:column;height:640px;box-shadow:0 1px 3px rgba(0,0,0,.04)}
.nt-hdr{background:#1e293b;color:#f1f5f9;padding:13px 18px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;gap:8px}
.nt-hdr-title{font-size:.74rem;font-weight:800;letter-spacing:1.4px;text-transform:uppercase;white-space:nowrap}
.nt-hdr-sub{font-size:.63rem;color:#64748b;font-weight:500;text-align:right;line-height:1.3}
.nt-body{flex:1;overflow-y:auto;background:#ffffff}
.nt-item{padding:12px 16px;border-bottom:1px solid #f1f5f9;transition:background .1s}
.nt-item:last-child{border-bottom:none}
.nt-item:hover{background:#f8fafc}
.nt-title{font-size:.82rem;font-weight:600;color:#1a1a1a;line-height:1.45;margin-bottom:5px}
.nt-meta{display:flex;align-items:center;gap:5px;font-size:.66rem;color:#94a3b8;flex-wrap:wrap}
.nt-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.nt-dot.pos{background:#16a34a}.nt-dot.neg{background:#dc2626}.nt-dot.neu{background:#d97706}
.nt-sep{color:#e2e8f0}
.nt-ticker-grp{border-bottom:1px solid #e2e8f0}
.nt-ticker-grp:last-child{border-bottom:none}
.nt-ticker-hdr{padding:7px 14px;background:#f8fafc;border-bottom:1px solid #f1f5f9;display:flex;align-items:center;gap:8px}
.nt-badge{display:inline-flex;align-items:center;padding:2px 9px;border-radius:10px;background:#1e293b;color:#f1f5f9;font-size:.62rem;font-weight:800;letter-spacing:.5px}
.nt-no-news{padding:10px 16px;font-size:.75rem;color:#94a3b8;font-style:italic}
.nt-empty{padding:48px 20px;text-align:center;color:#94a3b8;font-size:.8rem}
.nt-loading{padding:48px 20px;text-align:center;color:#94a3b8;font-size:.8rem}
.nt-refresh-btn{padding:4px 11px;border:1px solid #334155;border-radius:14px;background:none;color:#94a3b8;font-size:.63rem;font-weight:600;cursor:pointer;transition:all .15s;white-space:nowrap}
.nt-refresh-btn:hover{background:#334155;color:#f1f5f9}
@media(max-width:1100px){.nt-wrap{grid-template-columns:1fr 1fr}}
@media(max-width:700px){.nt-wrap{grid-template-columns:1fr;padding:12px 14px}}
"""

NEWS_JS = r"""
// ── News Terminal ─────────────────────────────────────────────────────────────
let newsInitialized = false;

function initNews() { loadNews(false); }

function loadNews(force) {
  ['nt-hot', 'nt-market', 'nt-portfolio'].forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.innerHTML = '<div class="nt-loading">Loading\u2026</div>';
  });
  fetch('/api/news' + (force ? '?force=1' : ''))
    .then(function(r) { return r.json(); })
    .then(function(data) { renderNews(data); })
    .catch(function() {
      ['nt-hot', 'nt-market', 'nt-portfolio'].forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.innerHTML = '<div class="nt-empty">Failed to load headlines</div>';
      });
    });
}

function _ntEsc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function _ntItem(item) {
  var dotCls = item.sentiment === 'positive' ? 'pos'
             : item.sentiment === 'negative' ? 'neg' : 'neu';
  var parts  = [item.source, item.time_ago].filter(Boolean)
               .map(_ntEsc).join('<span class="nt-sep"> \u00b7 </span>');
  return (
    '<div class="nt-item">' +
    '<div class="nt-title">' + _ntEsc(item.title) + '</div>' +
    '<div class="nt-meta"><span class="nt-dot ' + dotCls + '"></span>' + parts + '</div>' +
    '</div>'
  );
}

function renderNews(data) {
  var hot  = data.hot    || [];
  var mkt  = data.market || [];
  var port = data.portfolio || {};

  var hotEl = document.getElementById('nt-hot');
  if (hotEl) {
    hotEl.innerHTML = hot.length
      ? hot.map(_ntItem).join('')
      : '<div class="nt-empty">No headlines available</div>';
  }

  var mktEl = document.getElementById('nt-market');
  if (mktEl) {
    mktEl.innerHTML = mkt.length
      ? mkt.map(_ntItem).join('')
      : '<div class="nt-empty">No headlines available</div>';
  }

  var portEl = document.getElementById('nt-portfolio');
  if (portEl) {
    var tickers = Object.keys(port);
    if (!tickers.length) {
      portEl.innerHTML = '<div class="nt-empty">No portfolio tickers found</div>';
    } else {
      portEl.innerHTML = tickers.map(function(ticker) {
        var items = port[ticker] || [];
        var rows  = items.length
          ? items.map(_ntItem).join('')
          : '<div class="nt-no-news">No relevant headlines found</div>';
        return (
          '<div class="nt-ticker-grp">' +
          '<div class="nt-ticker-hdr">' +
          '<span class="nt-badge">' + _ntEsc(ticker) + '</span>' +
          '</div>' +
          rows +
          '</div>'
        );
      }).join('');
    }
  }
}
"""

NEWS_HTML = (
    '<div class="nt-wrap">'

    # ── Panel 1: Hot News ─────────────────────────────────────────────────────
    '<div class="nt-panel">'
    '<div class="nt-hdr">'
    '<span class="nt-hdr-title">&#128293;&nbsp; Hot News</span>'
    '<button class="nt-refresh-btn" onclick="loadNews(true)">&#8635; Refresh</button>'
    '</div>'
    '<div class="nt-body" id="nt-hot">'
    '<div class="nt-loading">Loading\u2026</div>'
    '</div>'
    '</div>'

    # ── Panel 2: Market News ──────────────────────────────────────────────────
    '<div class="nt-panel">'
    '<div class="nt-hdr">'
    '<span class="nt-hdr-title">&#128240;&nbsp; Market News</span>'
    '<span class="nt-hdr-sub">Fed &nbsp;\u00b7&nbsp; Rates &nbsp;\u00b7&nbsp; Oil &nbsp;\u00b7&nbsp; Gold &nbsp;\u00b7&nbsp; Crypto</span>'
    '</div>'
    '<div class="nt-body" id="nt-market">'
    '<div class="nt-loading">Loading\u2026</div>'
    '</div>'
    '</div>'

    # ── Panel 3: Portfolio News ───────────────────────────────────────────────
    '<div class="nt-panel">'
    '<div class="nt-hdr">'
    '<span class="nt-hdr-title">&#128202;&nbsp; Portfolio News</span>'
    '<span class="nt-hdr-sub">Live from Google Sheets</span>'
    '</div>'
    '<div class="nt-body" id="nt-portfolio">'
    '<div class="nt-loading">Loading\u2026</div>'
    '</div>'
    '</div>'

    '</div>'  # /nt-wrap
)
