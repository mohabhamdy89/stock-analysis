#!/usr/bin/env python3
"""
Stock Analysis Live Dashboard Server  —  http://localhost:8080
Reads live portfolio from Google Sheets, runs 10 technical indicators,
streams real-time updates, and generates Portfolio Advisor recommendations.
"""
import json, os, sys, threading
from datetime import datetime
from flask import Flask, Response, jsonify

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stock_analysis import (
    score_stock, PORTFOLIOS,
    read_portfolio_sheet, enrich_with_portfolio, generate_advisor_recs,
    generate_dashboard, fetch_benchmark_returns,
)

app = Flask(__name__)

_lock            = threading.Lock()
_results         = {}   # {portfolio_name: [enriched result dicts]}
_advisor_recs    = []
_portfolio_totals= {}
_benchmarks      = {}
_updated         = None
_busy            = False


# ── Serialization ──────────────────────────────────────────────────────────────

def _j(r):
    return {
        "ticker":             r["ticker"],
        "price":              float(r["price"]),
        "signal":             r["signal"],
        "score":              int(r["score"]),
        "scores":             {k: int(v) for k, v in r["scores"].items()},
        "details":            dict(r["details"]),
        "timestamp":          r["timestamp"],
        "shares":             float(r.get("shares",             0)),
        "cost_basis_ps":      float(r.get("cost_basis_ps",      0)),
        "total_cost":         float(r.get("total_cost",         0)),
        "market_value":       float(r.get("market_value",       0)),
        "unrealized_pnl":     float(r.get("unrealized_pnl",     0)),
        "unrealized_pnl_pct": float(r.get("unrealized_pnl_pct", 0)),
        "weight_pct":         float(r.get("weight_pct",         0)),
    }


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return _HTML


@app.route("/api/data")
def api_data():
    with _lock:
        return jsonify({
            "portfolios":       {n: [_j(r) for r in rs] for n, rs in _results.items()},
            "advisor_recs":     _advisor_recs,
            "portfolio_totals": _portfolio_totals,
            "benchmarks":       _benchmarks,
            "updated":          _updated,
            "busy":             _busy,
        })


@app.route("/api/refresh")
def api_refresh():
    def stream():
        global _results, _advisor_recs, _portfolio_totals, _benchmarks, _updated, _busy
        with _lock:
            if _busy:
                yield "data: " + json.dumps({"type": "busy"}) + "\n\n"
                return
            _busy = True
        try:
            # Read live portfolio from Google Sheets (falls back to hardcoded)
            sheet_portfolios, positions, cash, portfolio_pnl_pct = read_portfolio_sheet()
            active = sheet_portfolios if sheet_portfolios else PORTFOLIOS
            if not sheet_portfolios:
                cash, portfolio_pnl_pct = 0.0, None

            pairs = [(n, t) for n, ts in active.items() for t in ts]
            total = len(pairs)
            raw   = {n: [] for n in active}

            for i, (pname, ticker) in enumerate(pairs):
                yield "data: " + json.dumps({
                    "type": "progress", "ticker": ticker,
                    "portfolio": pname, "n": i + 1, "total": total,
                }) + "\n\n"
                r = score_stock(ticker)
                if r:
                    raw[pname].append(r)
                    yield "data: " + json.dumps({
                        "type": "stock", "portfolio": pname, "result": _j(r),
                    }) + "\n\n"
                else:
                    yield "data: " + json.dumps({
                        "type": "skip", "ticker": ticker, "portfolio": pname,
                    }) + "\n\n"

            # Enrich with portfolio data and generate recommendations
            enriched_portfolios, totals = {}, {}
            all_enriched = []
            for pname, results in raw.items():
                enriched, ptotals = enrich_with_portfolio(results, positions, cash, portfolio_pnl_pct)
                enriched_portfolios[pname] = enriched
                all_enriched.extend(enriched)
                totals = ptotals  # single portfolio case

            advisor = generate_advisor_recs(all_enriched)

            # Fetch benchmark returns (S&P 500 + NASDAQ)
            bm = {}
            try:
                bm = fetch_benchmark_returns()
            except Exception:
                pass

            ts = datetime.now().strftime("%A, %B %d %Y at %I:%M %p")

            with _lock:
                _results          = enriched_portfolios
                _advisor_recs     = advisor
                _portfolio_totals = totals
                _benchmarks       = bm
                _updated          = ts

            # Regenerate static dashboard.html
            dash = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")
            try:
                generate_dashboard(raw, dash)
            except Exception:
                pass

            yield "data: " + json.dumps({"type": "done", "timestamp": ts}) + "\n\n"

        except GeneratorExit:
            pass
        except Exception as e:
            yield "data: " + json.dumps({"type": "error", "message": str(e)}) + "\n\n"
        finally:
            with _lock:
                _busy = False

    return Response(
        stream(), mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── CSS ────────────────────────────────────────────────────────────────────────

_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#060b16;color:#e2e8f0;min-height:100vh}
/* header */
.hdr{background:linear-gradient(135deg,#0d1628,#091020 60%,#0f1c33);border-bottom:1px solid #162035;padding:20px 36px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;backdrop-filter:blur(16px)}
.hdr-l h1{font-size:1.45rem;font-weight:800;background:linear-gradient(135deg,#60a5fa,#a78bfa 60%,#38bdf8);-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:-.5px}
.hdr-l .sub{color:#3d5475;font-size:.72rem;margin-top:3px;letter-spacing:.3px}
.hdr-r{display:flex;flex-direction:column;align-items:flex-end;gap:4px}
.ts{color:#3d5475;font-size:.78rem}
.pbar-row{display:flex;align-items:center;gap:8px;height:16px}
.pbar-bg{width:140px;height:3px;background:#162035;border-radius:2px;overflow:hidden}
.pbar-fill{height:100%;width:0%;background:linear-gradient(90deg,#3b82f6,#8b5cf6);border-radius:2px;transition:width .3s}
.pbar-txt{font-size:.7rem;color:#60a5fa;font-weight:600;min-width:130px;white-space:nowrap}
.rbtn{padding:6px 16px;background:linear-gradient(135deg,#2563eb,#4f46e5);border:none;border-radius:20px;color:#fff;font-size:.73rem;font-weight:700;cursor:pointer;transition:opacity .15s,transform .15s}
.rbtn:hover:not(:disabled){opacity:.85;transform:translateY(-1px)}
.rbtn:disabled{opacity:.4;cursor:not-allowed;transform:none}
/* portfolio strip */
.pstrip{display:flex;gap:0;border-bottom:1px solid #0f1a2e;background:#07101f;overflow-x:auto}
.ps{flex:1;min-width:130px;padding:12px 22px;border-right:1px solid #0f1a2e;display:flex;flex-direction:column;gap:3px}
.ps:last-child{border-right:none}
.ps-lbl{font-size:.62rem;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;color:#2d4a6e}
.ps-val{font-size:1.1rem;font-weight:800;color:#e2e8f0}
.ps-val.up{color:#00e676}.ps-val.dn{color:#f44336}
/* benchmark strip */
.bench-strip{display:none;gap:0;border-bottom:1px solid #0f1a2e;background:#060e1c;overflow-x:auto;align-items:stretch}
.bs{flex:1;min-width:120px;padding:10px 20px;border-right:1px solid #0f1a2e;display:flex;flex-direction:column;gap:2px}
.bs:last-child{border-right:none}
.bs-lbl{font-size:.58rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#1a2d45}
.bs-val{font-size:.88rem;font-weight:800;color:#e2e8f0}
.bs-val.up{color:#00e676}.bs-val.dn{color:#f44336}
.bs-val.out{color:#00e676}.bs-val.under{color:#f44336}.bs-val.even{color:#ffd740}
.bs-sep{width:1px;background:#1a2d45;margin:8px 0;flex-shrink:0}
.bs-divider{width:1px;background:#162035;flex-shrink:0}
/* main */
.main{padding:28px 36px;max-width:1600px;margin:0 auto}
/* advisor */
.adv{margin-bottom:36px}
.adv-hdr{font-size:.75rem;font-weight:800;letter-spacing:2px;text-transform:uppercase;color:#2d4a6e;margin-bottom:14px;padding-bottom:9px;border-bottom:1px solid #0f1a2e;display:flex;align-items:center;gap:10px}
.adv-cnt{background:#0f1a2e;border-radius:20px;padding:2px 10px;font-size:.68rem;color:#2d4a6e}
.adv-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px}
.ac{background:#08111e;border:1px solid #0f1a2e;border-left:3px solid #0f1a2e;border-radius:10px;padding:14px 16px;transition:transform .15s,border-color .15s}
.ac:hover{transform:translateY(-2px)}
.ac.add{border-left-color:#00e676}.ac.hold{border-left-color:#3b82f6}.ac.watch{border-left-color:#ffd740}.ac.trim{border-left-color:#ff9800}.ac.exit{border-left-color:#f44336}
.ac-top{display:flex;align-items:center;gap:8px;margin-bottom:7px}
.ac-badge{font-size:.62rem;font-weight:800;letter-spacing:1px;padding:3px 9px;border-radius:12px}
.ac-badge.add{background:rgba(0,230,118,.12);color:#00e676}.ac-badge.hold{background:rgba(59,130,246,.12);color:#60a5fa}.ac-badge.watch{background:rgba(255,215,64,.1);color:#ffd740}.ac-badge.trim{background:rgba(255,152,0,.1);color:#ff9800}.ac-badge.exit{background:rgba(244,67,54,.1);color:#f44336}
.ac-ticker{font-size:.95rem;font-weight:800;color:#f1f5f9}
.ac-arrow{font-size:.78rem;color:#2d4a6e;margin-left:auto}
.ac-headline{font-size:.8rem;color:#94a3b8;line-height:1.4;margin-bottom:5px}
.ac-detail{font-size:.72rem;color:#2d4a6e;line-height:1.5}
/* signal summary cards */
.cards{display:flex;gap:10px;margin-bottom:28px;flex-wrap:wrap}
.card{flex:1;min-width:120px;border-radius:12px;padding:16px 18px;text-align:center;border:1px solid rgba(255,255,255,.04);transition:transform .2s}
.card:hover{transform:translateY(-2px)}
.card .num{font-size:2.2rem;font-weight:900;line-height:1;transition:transform .3s}
.card .num.bump{transform:scale(1.35)}
.card .lbl{font-size:.62rem;font-weight:700;letter-spacing:1px;margin-top:4px;opacity:.65}
.card.strong-buy{background:rgba(0,230,118,.07);border-color:rgba(0,230,118,.18)}.card.strong-buy .num{color:#00e676}
.card.buy{background:rgba(29,233,182,.06);border-color:rgba(29,233,182,.15)}.card.buy .num{color:#1de9b6}
.card.neutral{background:rgba(255,215,64,.06);border-color:rgba(255,215,64,.15)}.card.neutral .num{color:#ffd740}
.card.sell{background:rgba(255,152,0,.06);border-color:rgba(255,152,0,.15)}.card.sell .num{color:#ff9800}
.card.strong-sell{background:rgba(244,67,54,.06);border-color:rgba(244,67,54,.15)}.card.strong-sell .num{color:#f44336}
/* section */
.section{margin-bottom:40px}
.sec-title{font-size:.72rem;font-weight:800;letter-spacing:2px;text-transform:uppercase;color:#2d4a6e;margin-bottom:14px;padding-bottom:9px;border-bottom:1px solid #0f1a2e;display:flex;align-items:center;gap:10px}
.sec-count{background:#0f1a2e;border-radius:20px;padding:2px 10px;font-size:.67rem;color:#2d4a6e}
.tbl-wrap{border-radius:12px;border:1px solid #0f1a2e;overflow:hidden;overflow-x:auto}
table{width:100%;border-collapse:collapse}
thead th{background:#07101f;padding:10px 13px;font-size:.64rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#2d4a6e;text-align:left;white-space:nowrap}
tbody tr.sr{border-top:1px solid #0a1422;cursor:pointer;transition:background .1s}
tbody tr.sr:hover{background:rgba(255,255,255,.02)}
td{padding:11px 13px;font-size:.84rem;vertical-align:middle}
/* cells */
.tc{font-size:.95rem;font-weight:800;color:#f1f5f9}
.pc{font-size:.82rem;color:#3d5475}
.num-r{text-align:right;font-variant-numeric:tabular-nums}
.up{color:#00e676}.dn{color:#f44336}.ze{color:#64748b}
/* weight bar */
.wb-wrap{display:flex;align-items:center;gap:6px}
.wb-bg{width:52px;height:4px;background:#0f1a2e;border-radius:2px;overflow:hidden;flex-shrink:0}
.wb-fill{height:100%;border-radius:2px;background:linear-gradient(90deg,#3b82f6,#6366f1)}
.wb-lbl{font-size:.8rem;font-weight:700;color:#94a3b8;white-space:nowrap}
/* signal badge */
.badge{display:inline-flex;align-items:center;gap:4px;padding:4px 10px;border-radius:16px;font-size:.67rem;font-weight:800;letter-spacing:.6px;white-space:nowrap}
.badge::before{content:'';width:6px;height:6px;border-radius:50%;flex-shrink:0}
.badge.strong-buy{background:rgba(0,230,118,.12);color:#00e676;border:1px solid rgba(0,230,118,.25)}.badge.strong-buy::before{background:#00e676;box-shadow:0 0 5px #00e676}
.badge.buy{background:rgba(29,233,182,.1);color:#1de9b6;border:1px solid rgba(29,233,182,.22)}.badge.buy::before{background:#1de9b6;box-shadow:0 0 5px #1de9b6}
.badge.neutral{background:rgba(255,215,64,.08);color:#ffd740;border:1px solid rgba(255,215,64,.22)}.badge.neutral::before{background:#ffd740}
.badge.sell{background:rgba(255,152,0,.09);color:#ff9800;border:1px solid rgba(255,152,0,.22)}.badge.sell::before{background:#ff9800}
.badge.strong-sell{background:rgba(244,67,54,.09);color:#f44336;border:1px solid rgba(244,67,54,.22)}.badge.strong-sell::before{background:#f44336}
/* score bar */
.sb-wrap{display:flex;align-items:center;gap:8px;min-width:130px}
.sb-bg{flex:1;height:4px;background:#0f1a2e;border-radius:2px;overflow:hidden;position:relative}
.sb-mid{position:absolute;left:50%;top:0;width:1px;height:100%;background:#1a2d45}
.sb-fill{height:100%;border-radius:2px;transition:width .6s ease}
.sb-num{font-size:.8rem;font-weight:800;min-width:30px;text-align:right}
/* indicator pills */
.pills{display:flex;flex-wrap:wrap;gap:3px}
.pill{font-size:.6rem;font-weight:700;padding:2px 5px;border-radius:3px;letter-spacing:.3px;position:relative;cursor:default}
.pill:hover{opacity:.8}
.pill.bull{background:rgba(0,230,118,.12);color:#00e676}
.pill.bear{background:rgba(244,67,54,.1);color:#f44336}
.pill.neut{background:rgba(45,74,110,.3);color:#3d5475}
.pill .tip{display:none;position:absolute;bottom:calc(100% + 6px);left:50%;transform:translateX(-50%);background:#0f1a2e;border:1px solid #1a2d45;border-radius:7px;padding:6px 10px;font-size:.68rem;font-weight:400;white-space:nowrap;color:#94a3b8;z-index:500;pointer-events:none;box-shadow:0 4px 18px rgba(0,0,0,.6)}
.pill:hover .tip{display:block}
/* detail row */
.drow td{padding:0;border:none}
.dinn{display:none;padding:16px 20px;background:#050d18;border-top:1px solid #0a1422}
.dinn.open{display:block}
.dgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px}
.di{background:#07101f;border-radius:8px;padding:10px 13px;border:1px solid #0f1a2e;border-left:3px solid #0f1a2e}
.di.b{border-left-color:#00e676}.di.r{border-left-color:#f44336}.di.g{border-left-color:#1a2d45}
.di-name{font-size:.62rem;font-weight:800;letter-spacing:.8px;color:#2d4a6e;margin-bottom:3px;text-transform:uppercase}
.di-val{font-size:.76rem;color:#64748b;line-height:1.4}
/* animations */
@keyframes shimmer{0%{opacity:.35}50%{opacity:.8}100%{opacity:.35}}
.row-loading{animation:shimmer 1.2s ease-in-out infinite}
.row-loading td{color:#0f1a2e !important}
@keyframes rowflash{0%{background:rgba(29,233,182,.1)}100%{background:transparent}}
.row-flash{animation:rowflash .9s ease-out}
/* empty */
.empty-state{text-align:center;padding:56px 20px;color:#0f1a2e}
.empty-state h2{font-size:1rem;font-weight:700;color:#1a2d45;margin-bottom:6px}
/* footer */
.footer{text-align:center;padding:22px;color:#0f1a2e;font-size:.72rem;border-top:1px solid #07101f;margin-top:12px}
/* sortable headers */
thead th.s{cursor:pointer;user-select:none;transition:color .15s;white-space:nowrap}
thead th.s:hover{color:#60a5fa}
thead th.s::after{content:' ▲▼';opacity:.2;font-size:.7em}
thead th.s.desc::after{content:' ▼';opacity:1;color:#60a5fa;font-size:.8em}
thead th.s.asc::after{content:' ▲';opacity:1;color:#60a5fa;font-size:.8em}
thead th.s.desc,thead th.s.asc{color:#94a3b8}
@media(max-width:900px){.hdr{padding:14px 16px;flex-direction:column;gap:8px}.main{padding:16px}.pstrip{flex-wrap:wrap}.adv-grid{grid-template-columns:1fr}}
"""


# ── JS ─────────────────────────────────────────────────────────────────────────

_JS = r"""
const SIG = {
  'STRONG BUY':  ['strong-buy',  '#00e676'],
  'BUY':         ['buy',         '#1de9b6'],
  'NEUTRAL':     ['neutral',     '#ffd740'],
  'SELL':        ['sell',        '#ff9800'],
  'STRONG SELL': ['strong-sell', '#f44336'],
};
const IND = {
  RSI:'RSI', MACD:'MACD', '50MA_vs_200MA':'MA50/200',
  Bollinger:'BB', Volume:'VOL', Stochastic:'STOCH',
  ADX:'ADX', EMA_9_vs_21:'EMA9/21', OBV:'OBV', ATR:'ATR'
};
const CARD_IDS = {'STRONG BUY':'c-sb','BUY':'c-b','NEUTRAL':'c-n','SELL':'c-s','STRONG SELL':'c-ss'};
const REC_COLORS = {ADD:'#00e676',HOLD:'#3b82f6',WATCH:'#ffd740',TRIM:'#ff9800',EXIT:'#f44336'};

let evtSource    = null;
let liveCounts   = {};
let portfolioData = null;
let sortCol = 'weight_pct', sortDir = -1;  // default: weight high→low

function makeHdr(label, col, extraCls) {
  if (!col) return '<th'+(extraCls?' class="'+extraCls+'"':'')+'>'+label+'</th>';
  const active = col === sortCol;
  const dirCls = active ? (sortDir === -1 ? ' desc' : ' asc') : '';
  const cls    = ['s', extraCls, dirCls].filter(Boolean).join(' ');
  return '<th class="'+cls+'" data-col="'+col+'" onclick="sortBy(\''+col+'\')">'+label+'</th>';
}

function sortBy(col) {
  sortDir = (sortCol === col) ? sortDir * -1 : -1;
  sortCol = col;
  document.querySelectorAll('thead th.s').forEach(th => {
    th.classList.remove('asc', 'desc');
    if (th.dataset.col === col) th.classList.add(sortDir === -1 ? 'desc' : 'asc');
  });
  if (portfolioData) renderAll(portfolioData);
}

// ── Formatters ────────────────────────────────────────────────────────────────
function fmt$(n) {
  if (!n) return '—';
  return '$' + Math.abs(n).toLocaleString('en-US', {minimumFractionDigits:2,maximumFractionDigits:2});
}
function fmtPct(n) {
  if (n === undefined || n === null) return '—';
  const s = (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
  return s;
}
function fmtPnl(pnl, pct) {
  if (!pnl && pnl !== 0) return '—';
  const cls = pnl > 0 ? 'up' : pnl < 0 ? 'dn' : 'ze';
  const sign = pnl >= 0 ? '+' : '-';
  return '<span class="'+cls+'">'+sign+fmt$(Math.abs(pnl))+'<br><small>'+fmtPct(pct)+'</small></span>';
}

// ── Row builders ──────────────────────────────────────────────────────────────
function pills(scores, details) {
  return Object.entries(scores).map(([k,s]) => {
    const pcls = s===1?'bull':s===-1?'bear':'neut';
    const tip = (details[k]||'').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    return '<span class="pill '+pcls+'">'+(IND[k]||k)+'<span class="tip">'+tip+'</span></span>';
  }).join('');
}
function detailGrid(scores, details) {
  return Object.entries(scores).map(([k,s]) => {
    const dcls = s===1?'b':s===-1?'r':'g';
    const val = (details[k]||'').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    return '<div class="di '+dcls+'"><div class="di-name">'+k.replace(/_/g,' ')+'</div><div class="di-val">'+val+'</div></div>';
  }).join('');
}

function buildRowCells(r) {
  const [cls, color] = SIG[r.signal] || ['neutral','#ffd740'];
  const pct  = ((r.score+10)/20*100).toFixed(1);
  const sign = (r.score>0?'+':'')+r.score;
  const hasPf = r.shares > 0;

  // Weight bar (max 25% = full bar)
  const wPct = Math.min(r.weight_pct / 25 * 100, 100).toFixed(1);
  const wCell = hasPf
    ? '<div class="wb-wrap"><div class="wb-bg"><div class="wb-fill" style="width:'+wPct+'%"></div></div><span class="wb-lbl">'+r.weight_pct.toFixed(1)+'%</span></div>'
    : '<span class="ze">—</span>';

  return (
    '<td class="tc">'+r.ticker+'</td>'+
    '<td class="pc num-r">'+(hasPf ? r.shares.toLocaleString() : '—')+'</td>'+
    '<td class="pc num-r">'+(hasPf ? '$'+r.cost_basis_ps.toFixed(2) : '—')+'</td>'+
    '<td class="num-r">'+(hasPf ? '<strong>'+fmt$(r.market_value)+'</strong>' : '—')+'</td>'+
    '<td class="num-r">'+(hasPf ? fmt$(r.total_cost) : '—')+'</td>'+
    '<td class="num-r">'+fmtPnl(hasPf ? r.unrealized_pnl : null, hasPf ? r.unrealized_pnl_pct : null)+'</td>'+
    '<td>'+wCell+'</td>'+
    '<td><span class="badge '+cls+'">'+r.signal+'</span></td>'+
    '<td><div class="sb-wrap"><div class="sb-bg"><div class="sb-mid"></div>'+
    '<div class="sb-fill" style="width:'+pct+'%;background:'+color+'"></div></div>'+
    '<span class="sb-num" style="color:'+color+'">'+sign+'</span></div></td>'+
    '<td><div class="pills">'+pills(r.scores,r.details)+'</div></td>'
  );
}

// ── DOM helpers ───────────────────────────────────────────────────────────────
function getOrMakeSection(pname) {
  const id = 'sec-'+pname.replace(/\s+/g,'-');
  let sec = document.getElementById(id);
  if (sec) return sec;
  sec = document.createElement('div');
  sec.id = id; sec.className = 'section';
  sec.innerHTML =
    '<div class="sec-title">'+pname.replace(/</g,'&lt;')+
    '<span class="sec-count" id="cnt-'+id+'">0 stocks</span></div>'+
    '<div class="tbl-wrap"><table>'+
    '<thead><tr>'+
    makeHdr('Ticker',          null,            '') +
    makeHdr('Shares',          null,            'num-r') +
    makeHdr('Avg Cost',        null,            'num-r') +
    makeHdr('Mkt Value',       'market_value',  'num-r') +
    makeHdr('Cost Basis',      'total_cost',    'num-r') +
    makeHdr('Unrealized P&L',  'unrealized_pnl','num-r') +
    makeHdr('Weight',          'weight_pct',    '') +
    makeHdr('Signal',          null,            '') +
    makeHdr('Score',           'score',         '') +
    makeHdr('Indicators \u2014 click row to expand', null, '') +
    '</tr></thead><tbody id="tbody-'+id+'"></tbody></table></div>';
  document.getElementById('portfolios').appendChild(sec);
  return sec;
}

function appendRow(pname, r) {
  getOrMakeSection(pname);
  const sid   = 'sec-'+pname.replace(/\s+/g,'-');
  const tbody = document.getElementById('tbody-'+sid);
  const tr    = document.createElement('tr');
  tr.id = 'row-'+r.ticker; tr.className = 'stock-row sr';
  tr.setAttribute('onclick', "toggleDetail('"+r.ticker+"')");
  tr.innerHTML = buildRowCells(r);
  tbody.appendChild(tr);
  const dtr = document.createElement('tr');
  dtr.className = 'drow';
  dtr.innerHTML = '<td colspan="10"><div class="dinn" id="dinn-'+r.ticker+'">'+
    '<div class="dgrid">'+detailGrid(r.scores,r.details)+'</div></div></td>';
  tbody.appendChild(dtr);
  tr.classList.add('row-flash');
  setTimeout(()=>tr.classList.remove('row-flash'),900);
  const cnt = document.getElementById('cnt-'+sid);
  if (cnt) cnt.textContent = (parseInt(cnt.textContent)||0)+1+' stocks';
}

function updateRow(r) {
  const tr = document.getElementById('row-'+r.ticker);
  if (!tr) return false;
  tr.classList.remove('row-loading');
  tr.innerHTML = buildRowCells(r);
  tr.classList.add('row-flash');
  setTimeout(()=>tr.classList.remove('row-flash'),900);
  const dinn = document.getElementById('dinn-'+r.ticker);
  if (dinn) dinn.innerHTML = '<div class="dgrid">'+detailGrid(r.scores,r.details)+'</div>';
  return true;
}

function bumpCard(signal) {
  const el = document.getElementById(CARD_IDS[signal]);
  if (!el) return;
  liveCounts[signal] = (liveCounts[signal]||0)+1;
  el.textContent = liveCounts[signal];
  el.classList.remove('bump'); void el.offsetWidth; el.classList.add('bump');
  setTimeout(()=>el.classList.remove('bump'),300);
}

// ── Portfolio summary strip ───────────────────────────────────────────────────
function renderPortfolioStrip(totals) {
  if (!totals || !totals.total_portfolio_value) return;
  const pnl      = totals.total_unrealized_pnl;
  const pnlPct   = totals.total_unrealized_pnl_pct;
  const pnlCls   = pnl >= 0 ? 'up' : 'dn';
  const pnlSign  = pnl >= 0 ? '+' : '';
  const cash     = totals.cash || 0;
  const cashPct  = totals.cash_weight_pct || 0;
  const eqMv     = totals.total_market_value || 0;
  const eqPct    = totals.equity_weight_pct || 0;
  const totalPv  = totals.total_portfolio_value;

  document.getElementById('ps-val').innerHTML =
    '<div class="ps-lbl">Total Portfolio</div>'+
    '<div class="ps-val">$'+totalPv.toLocaleString('en-US',{maximumFractionDigits:0})+'</div>';
  document.getElementById('ps-eq').innerHTML =
    '<div class="ps-lbl">Equity</div>'+
    '<div class="ps-val">$'+eqMv.toLocaleString('en-US',{maximumFractionDigits:0})+
    '<br><small style="font-size:.68rem;color:#3d5475;font-weight:600">'+eqPct.toFixed(1)+'% of portfolio</small></div>';
  document.getElementById('ps-cash').innerHTML =
    '<div class="ps-lbl">Cash</div>'+
    '<div class="ps-val">'+(cash > 0
      ? '$'+cash.toLocaleString('en-US',{maximumFractionDigits:0})+
        '<br><small style="font-size:.68rem;color:#3d5475;font-weight:600">'+cashPct.toFixed(1)+'% of portfolio</small>'
      : '<span style="color:#1a2d45">—</span>')+
    '</div>';
  document.getElementById('ps-pnl').innerHTML =
    '<div class="ps-lbl">Unrealized P&amp;L</div>'+
    '<div class="ps-val '+pnlCls+'">'+pnlSign+'$'+Math.abs(pnl).toLocaleString('en-US',{maximumFractionDigits:0})+
    '&nbsp;<small>('+pnlSign+pnlPct.toFixed(1)+'%)</small></div>';
  document.getElementById('ps-pos').innerHTML =
    '<div class="ps-lbl">Open Positions</div>'+
    '<div class="ps-val">'+totals.num_positions+'</div>';
}

// ── Benchmark comparison strip ────────────────────────────────────────────────
function renderBenchmarks(totals, benchmarks) {
  const strip = document.getElementById('bench-strip');
  if (!benchmarks || Object.keys(benchmarks).length === 0 || !totals) {
    strip.style.display = 'none';
    return;
  }
  // Prefer the sheet's portfolio P&L% (YTD); fall back to calculated unrealized P&L%
  const portRet  = totals.sheet_pnl_pct != null ? totals.sheet_pnl_pct : totals.total_unrealized_pnl_pct;
  if (portRet == null) { strip.style.display = 'none'; return; }
  strip.style.display = 'flex';
  const portCls  = portRet >= 0 ? 'up' : 'dn';
  const portSign = portRet >= 0 ? '+' : '';
  const lbl      = totals.sheet_pnl_pct != null ? 'My Portfolio (YTD)' : 'My Portfolio (P&amp;L)';

  document.getElementById('bs-port').innerHTML =
    '<div class="bs-lbl">'+lbl+'</div>'+
    '<div class="bs-val '+portCls+'">'+portSign+portRet.toFixed(2)+'%</div>';

  const pairs = [
    {bmId:'bs-sp500', vsId:'bs-vs-sp500', key:'sp500'},
    {bmId:'bs-nasdaq', vsId:'bs-vs-nasdaq', key:'nasdaq'},
  ];
  for (const {bmId, vsId, key} of pairs) {
    const bm = benchmarks[key];
    if (!bm) continue;
    const bmRet  = bm.return_ytd;
    const bmCls  = bmRet >= 0 ? 'up' : 'dn';
    const bmSign = bmRet >= 0 ? '+' : '';
    document.getElementById(bmId).innerHTML =
      '<div class="bs-lbl">'+bm.name+' (YTD)</div>'+
      '<div class="bs-val '+bmCls+'">'+bmSign+bmRet.toFixed(2)+'%</div>';
    const diff     = portRet - bmRet;
    const diffCls  = diff > 0.5 ? 'out' : diff < -0.5 ? 'under' : 'even';
    const diffLbl  = diff > 0.5 ? 'OUTPERFORMING' : diff < -0.5 ? 'UNDERPERFORMING' : 'IN LINE';
    const diffSign = diff >= 0 ? '+' : '';
    document.getElementById(vsId).innerHTML =
      '<div class="bs-lbl">vs '+bm.name+'</div>'+
      '<div class="bs-val '+diffCls+'">'+diffLbl+
      '<br><small style="font-size:.72rem;font-weight:600">'+diffSign+diff.toFixed(2)+'%</small></div>';
  }
}

// ── Portfolio Advisor ─────────────────────────────────────────────────────────
function renderAdvisor(recs) {
  const sec   = document.getElementById('advisor-section');
  const grid  = document.getElementById('adv-grid');
  const cnt   = document.getElementById('adv-count');
  if (!recs || !recs.length) { sec.style.display='none'; return; }

  sec.style.display = 'block';
  cnt.textContent = recs.length + ' suggestion' + (recs.length===1?'':'s');

  grid.innerHTML = recs.map(rec => {
    const type = rec.type.toLowerCase();
    const color = REC_COLORS[rec.type] || '#64748b';
    const arrow = rec.target
      ? '<span class="ac-arrow">'+rec.weight.toFixed(1)+'% &rarr; '+rec.target+'%</span>'
      : '<span class="ac-arrow">'+rec.weight.toFixed(1)+'%</span>';
    return (
      '<div class="ac '+type+'">'+
      '<div class="ac-top">'+
      '<span class="ac-badge '+type+'">'+rec.type+'</span>'+
      '<span class="ac-ticker">'+rec.ticker+'</span>'+
      arrow+
      '</div>'+
      '<div class="ac-headline">'+rec.headline.replace(rec.type+' ','').replace(rec.ticker+' ','')+'</div>'+
      '<div class="ac-detail">'+rec.detail+'</div>'+
      '</div>'
    );
  }).join('');
}

// ── Full render ───────────────────────────────────────────────────────────────
function renderAll(data) {
  portfolioData    = data;
  const portfolios = data.portfolios || {};
  const totals     = data.portfolio_totals || {};
  const advisor    = data.advisor_recs || [];
  const benchmarks = data.benchmarks   || {};
  const updated    = data.updated;

  renderPortfolioStrip(totals);
  renderBenchmarks(totals, benchmarks);
  renderAdvisor(advisor);

  const counts = {'STRONG BUY':0,'BUY':0,'NEUTRAL':0,'SELL':0,'STRONG SELL':0};
  const container = document.getElementById('portfolios');
  container.innerHTML = '';

  for (const [pname, results] of Object.entries(portfolios)) {
    const sorted = [...results].sort((a,b) => {
      const av = typeof a[sortCol] === 'number' ? a[sortCol] : 0;
      const bv = typeof b[sortCol] === 'number' ? b[sortCol] : 0;
      return sortDir * (bv - av);
    });
    for (const r of sorted) { appendRow(pname, r); counts[r.signal]++; }
  }
  for (const [sig, id] of Object.entries(CARD_IDS)) {
    const el = document.getElementById(id);
    if (el) el.textContent = counts[sig];
  }
  if (updated) document.getElementById('ts').textContent = 'Updated: '+updated;
}

// ── Progress bar ──────────────────────────────────────────────────────────────
function setProgress(n, total, ticker) {
  document.getElementById('pbar-fill').style.width = total>0 ? (n/total*100)+'%' : '0%';
  document.getElementById('pbar-txt').textContent = ticker ? 'Analyzing '+ticker+'…' : '';
}
function completeProgress() {
  document.getElementById('pbar-fill').style.width = '100%';
  document.getElementById('pbar-txt').textContent = 'Done';
  setTimeout(()=>{ document.getElementById('pbar-fill').style.width='0%'; document.getElementById('pbar-txt').textContent=''; }, 900);
}

// ── Refresh via SSE ───────────────────────────────────────────────────────────
function startRefresh() {
  if (evtSource) { evtSource.close(); evtSource=null; }
  const btn = document.getElementById('rbtn');
  btn.disabled=true; btn.textContent='⟳  Analyzing…';
  liveCounts = {'STRONG BUY':0,'BUY':0,'NEUTRAL':0,'SELL':0,'STRONG SELL':0};
  for (const id of Object.values(CARD_IDS)) { const el=document.getElementById(id); if(el) el.textContent='—'; }

  evtSource = new EventSource('/api/refresh');
  evtSource.onmessage = function(e) {
    const d = JSON.parse(e.data);
    if (d.type==='busy') { btn.disabled=false; btn.textContent='⟳  Refresh Now'; return; }
    if (d.type==='progress') {
      setProgress(d.n, d.total, d.ticker);
      const tr = document.getElementById('row-'+d.ticker);
      if (tr) tr.classList.add('row-loading');
    }
    else if (d.type==='stock') {
      if (!updateRow(d.result)) appendRow(d.portfolio, d.result);
      bumpCard(d.result.signal);
    }
    else if (d.type==='done') {
      evtSource.close(); evtSource=null;
      btn.disabled=false; btn.textContent='⟳  Refresh Now';
      completeProgress();
      fetch('/api/data').then(r=>r.json()).then(data=>renderAll(data));
    }
    else if (d.type==='error') {
      evtSource.close(); evtSource=null;
      btn.disabled=false; btn.textContent='⟳  Refresh Now';
      completeProgress();
    }
  };
  evtSource.onerror = function() {
    if (evtSource) { evtSource.close(); evtSource=null; }
    btn.disabled=false; btn.textContent='⟳  Refresh Now';
    completeProgress();
  };
}

function toggleDetail(ticker) {
  const el = document.getElementById('dinn-'+ticker);
  if (el) el.classList.toggle('open');
}

// ── Boot ──────────────────────────────────────────────────────────────────────
window.addEventListener('load', function() {
  fetch('/api/data').then(r=>r.json()).then(data => {
    if (data.updated && Object.keys(data.portfolios||{}).length) {
      renderAll(data);
    } else {
      document.getElementById('portfolios').innerHTML =
        '<div class="empty-state"><h2>No data yet</h2><p>Loading fresh analysis…</p></div>';
      startRefresh();
    }
  }).catch(()=>startRefresh());
});
"""


# ── HTML template ──────────────────────────────────────────────────────────────

_HTML = (
    '<!DOCTYPE html><html lang="en"><head>'
    '<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    '<title>Stock Analysis Dashboard</title>'
    '<style>' + _CSS + '</style></head><body>'

    # header
    '<div class="hdr">'
    '<div class="hdr-l">'
    '<h1>&#9654; Stock Analysis Dashboard</h1>'
    '<div class="sub">Portfolio from Google Sheets &nbsp;·&nbsp; 10 Technical Indicators &nbsp;·&nbsp; Click any row for details</div>'
    '</div>'
    '<div class="hdr-r">'
    '<div class="ts" id="ts">Loading…</div>'
    '<div class="pbar-row">'
    '<div class="pbar-bg"><div class="pbar-fill" id="pbar-fill"></div></div>'
    '<span class="pbar-txt" id="pbar-txt"></span>'
    '</div>'
    '<button class="rbtn" id="rbtn" onclick="startRefresh()">&#8635;&nbsp; Refresh Now</button>'
    '</div></div>'

    # portfolio strip
    '<div class="pstrip">'
    '<div class="ps" id="ps-val"><div class="ps-lbl">Total Portfolio</div><div class="ps-val">—</div></div>'
    '<div class="ps" id="ps-eq"><div class="ps-lbl">Equity</div><div class="ps-val">—</div></div>'
    '<div class="ps" id="ps-cash"><div class="ps-lbl">Cash</div><div class="ps-val">—</div></div>'
    '<div class="ps" id="ps-pnl"><div class="ps-lbl">Unrealized P&amp;L</div><div class="ps-val">—</div></div>'
    '<div class="ps" id="ps-pos"><div class="ps-lbl">Open Positions</div><div class="ps-val">—</div></div>'
    '</div>'

    # benchmark strip
    '<div class="bench-strip" id="bench-strip">'
    '<div class="bs" id="bs-port"><div class="bs-lbl">My Portfolio (P&amp;L)</div><div class="bs-val">—</div></div>'
    '<div class="bs-divider"></div>'
    '<div class="bs" id="bs-sp500"><div class="bs-lbl">S&amp;P 500 (YTD)</div><div class="bs-val">—</div></div>'
    '<div class="bs" id="bs-nasdaq"><div class="bs-lbl">NASDAQ (YTD)</div><div class="bs-val">—</div></div>'
    '<div class="bs-divider"></div>'
    '<div class="bs" id="bs-vs-sp500"><div class="bs-lbl">vs S&amp;P 500</div><div class="bs-val">—</div></div>'
    '<div class="bs" id="bs-vs-nasdaq"><div class="bs-lbl">vs NASDAQ</div><div class="bs-val">—</div></div>'
    '</div>'

    # main
    '<div class="main">'

    # advisor section
    '<div class="adv" id="advisor-section" style="display:none">'
    '<div class="adv-hdr">Portfolio Advisor'
    '<span class="adv-cnt" id="adv-count">0 suggestions</span></div>'
    '<div class="adv-grid" id="adv-grid"></div>'
    '</div>'

    # signal summary cards
    '<div class="cards">'
    '<div class="card strong-buy"><div class="num" id="c-sb">—</div><div class="lbl">STRONG BUY</div></div>'
    '<div class="card buy"><div class="num" id="c-b">—</div><div class="lbl">BUY</div></div>'
    '<div class="card neutral"><div class="num" id="c-n">—</div><div class="lbl">NEUTRAL</div></div>'
    '<div class="card sell"><div class="num" id="c-s">—</div><div class="lbl">SELL</div></div>'
    '<div class="card strong-sell"><div class="num" id="c-ss">—</div><div class="lbl">STRONG SELL</div></div>'
    '</div>'

    '<div id="portfolios"></div>'
    '</div>'  # /main

    '<div class="footer">Portfolio data from Google Sheets &nbsp;·&nbsp; Prices from Yahoo Finance &nbsp;·&nbsp; '
    '<a href="http://localhost:8080" style="color:#1a2d45">localhost:8080</a></div>'

    '<script>' + _JS + '</script>'
    '</body></html>'
)


if __name__ == "__main__":
    print("\n  Stock Analysis Dashboard  →  http://localhost:8080\n")
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)
