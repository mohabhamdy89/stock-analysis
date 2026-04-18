#!/usr/bin/env python3
"""
Stock Analysis Live Dashboard Server  —  http://localhost:8080
Reads live portfolio from Google Sheets, runs 10 technical indicators,
streams real-time updates, and generates Portfolio Advisor recommendations.
"""
import json, os, sys, threading
from datetime import datetime
from flask import Flask, Response, jsonify, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stock_analysis import (
    score_stock, PORTFOLIOS,
    read_portfolio_sheet, enrich_with_portfolio, generate_advisor_recs,
    generate_dashboard, fetch_benchmark_returns,
)
from radar import get_all_radar, get_radar_stock, load_watchlist, save_watchlist
from radar_ui import RADAR_CSS, RADAR_JS, RADAR_HTML

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


# ── Radar routes ───────────────────────────────────────────────────────────────

@app.route("/api/radar/data")
def api_radar_data():
    force   = request.args.get("force") == "1"
    tickers = load_watchlist()
    stocks  = get_all_radar(tickers, force=force)
    return jsonify({"stocks": stocks})


@app.route("/api/radar/watchlist", methods=["GET", "POST"])
def api_radar_watchlist():
    if request.method == "GET":
        return jsonify({"tickers": load_watchlist()})
    body   = request.get_json(force=True, silent=True) or {}
    action = body.get("action", "")
    ticker = (body.get("ticker") or "").upper().strip()
    tickers = load_watchlist()
    if action == "add" and ticker and ticker not in tickers:
        if len(tickers) < 25:
            tickers.append(ticker)
            save_watchlist(tickers)
    elif action == "remove" and ticker in tickers:
        tickers.remove(ticker)
        save_watchlist(tickers)
    return jsonify({"tickers": tickers})


@app.route("/api/radar/stock/<ticker>")
def api_radar_stock(ticker):
    force = request.args.get("force") == "1"
    data  = get_radar_stock(ticker.upper(), force=force)
    return jsonify(data)


# ── CSS ────────────────────────────────────────────────────────────────────────

_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#ffffff;color:#1a1a1a;min-height:100vh}
/* header */
.hdr{background:#ffffff;border-bottom:1px solid #e2e8f0;padding:20px 36px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.hdr-l h1{font-size:1.45rem;font-weight:800;background:linear-gradient(135deg,#2563eb,#7c3aed 60%,#0ea5e9);-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:-.5px}
.hdr-l .sub{color:#94a3b8;font-size:.72rem;margin-top:3px;letter-spacing:.3px}
.hdr-r{display:flex;flex-direction:column;align-items:flex-end;gap:4px}
.ts{color:#94a3b8;font-size:.78rem}
.pbar-row{display:flex;align-items:center;gap:8px;height:16px}
.pbar-bg{width:140px;height:3px;background:#e2e8f0;border-radius:2px;overflow:hidden}
.pbar-fill{height:100%;width:0%;background:linear-gradient(90deg,#3b82f6,#8b5cf6);border-radius:2px;transition:width .3s}
.pbar-txt{font-size:.7rem;color:#3b82f6;font-weight:600;min-width:130px;white-space:nowrap}
.rbtn{padding:6px 16px;background:linear-gradient(135deg,#2563eb,#4f46e5);border:none;border-radius:20px;color:#fff;font-size:.73rem;font-weight:700;cursor:pointer;transition:opacity .15s,transform .15s}
.rbtn:hover:not(:disabled){opacity:.85;transform:translateY(-1px)}
.rbtn:disabled{opacity:.4;cursor:not-allowed;transform:none}
/* tabs */
.tab-bar{background:#ffffff;border-bottom:1px solid #e2e8f0;padding:0 36px;display:flex;position:sticky;top:73px;z-index:90}
.tab-btn{padding:12px 22px;font-size:.83rem;font-weight:600;color:#64748b;border:none;background:none;cursor:pointer;border-bottom:2px solid transparent;transition:color .15s,border-color .15s;white-space:nowrap}
.tab-btn:hover{color:#1a1a1a}
.tab-btn.active{color:#2563eb;border-bottom-color:#2563eb;font-weight:700}
.tab-content{display:none}
.tab-content.active{display:block}
/* coming soon */
.coming-soon{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:100px 20px;text-align:center}
.coming-soon .cs-icon{font-size:3rem;margin-bottom:16px;opacity:.25}
.coming-soon h2{font-size:1.25rem;font-weight:700;color:#cbd5e1;margin-bottom:8px}
.coming-soon p{font-size:.88rem;color:#94a3b8}
/* portfolio strip */
.pstrip{display:flex;gap:0;border-bottom:1px solid #e2e8f0;background:#ffffff;overflow-x:auto}
.ps{flex:1;min-width:130px;padding:12px 22px;border-right:1px solid #e2e8f0;display:flex;flex-direction:column;gap:3px}
.ps:last-child{border-right:none}
.ps-lbl{font-size:.62rem;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;color:#94a3b8}
.ps-val{font-size:1.1rem;font-weight:800;color:#1a1a1a}
.ps-val.up{color:#16a34a}.ps-val.dn{color:#dc2626}
/* benchmark strip */
.bench-strip{display:none;gap:0;border-bottom:1px solid #e2e8f0;background:#f5f5f5;overflow-x:auto;align-items:stretch}
.bs{flex:1;min-width:120px;padding:10px 20px;border-right:1px solid #e2e8f0;display:flex;flex-direction:column;gap:2px}
.bs:last-child{border-right:none}
.bs-lbl{font-size:.58rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#94a3b8}
.bs-val{font-size:.88rem;font-weight:800;color:#1a1a1a}
.bs-val.up{color:#16a34a}.bs-val.dn{color:#dc2626}
.bs-val.out{color:#16a34a}.bs-val.under{color:#dc2626}.bs-val.even{color:#d97706}
.bs-sep{width:1px;background:#e2e8f0;margin:8px 0;flex-shrink:0}
.bs-divider{width:1px;background:#e2e8f0;flex-shrink:0}
/* main */
.main{padding:28px 36px;max-width:1600px;margin:0 auto}
/* advisor */
.adv{margin-bottom:36px}
.adv-hdr{font-size:.75rem;font-weight:800;letter-spacing:2px;text-transform:uppercase;color:#64748b;margin-bottom:14px;padding-bottom:9px;border-bottom:1px solid #e2e8f0;display:flex;align-items:center;gap:10px}
.adv-cnt{background:#f5f5f5;border-radius:20px;padding:2px 10px;font-size:.68rem;color:#64748b}
.adv-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px}
.ac{background:#f5f5f5;border:1px solid #e2e8f0;border-left:3px solid #e2e8f0;border-radius:10px;padding:14px 16px;transition:transform .15s,border-color .15s;box-shadow:0 1px 3px rgba(0,0,0,.04)}
.ac:hover{transform:translateY(-2px)}
.ac.add{border-left-color:#16a34a}.ac.hold{border-left-color:#3b82f6}.ac.watch{border-left-color:#d97706}.ac.trim{border-left-color:#f97316}.ac.exit{border-left-color:#dc2626}
.ac-top{display:flex;align-items:center;gap:8px;margin-bottom:7px}
.ac-badge{font-size:.62rem;font-weight:800;letter-spacing:1px;padding:3px 9px;border-radius:12px}
.ac-badge.add{background:rgba(22,163,74,.1);color:#16a34a}.ac-badge.hold{background:rgba(59,130,246,.1);color:#2563eb}.ac-badge.watch{background:rgba(217,119,6,.1);color:#d97706}.ac-badge.trim{background:rgba(249,115,22,.1);color:#f97316}.ac-badge.exit{background:rgba(220,38,38,.1);color:#dc2626}
.ac-ticker{font-size:.95rem;font-weight:800;color:#1a1a1a}
.ac-arrow{font-size:.78rem;color:#94a3b8;margin-left:auto}
.ac-headline{font-size:.8rem;color:#475569;line-height:1.4;margin-bottom:5px}
.ac-detail{font-size:.72rem;color:#94a3b8;line-height:1.5}
/* signal summary cards */
.cards{display:flex;gap:10px;margin-bottom:28px;flex-wrap:wrap}
.card{flex:1;min-width:120px;border-radius:12px;padding:16px 18px;text-align:center;border:1px solid rgba(0,0,0,.06);transition:transform .2s;background:#f5f5f5;box-shadow:0 1px 3px rgba(0,0,0,.04)}
.card:hover{transform:translateY(-2px)}
.card .num{font-size:2.2rem;font-weight:900;line-height:1;transition:transform .3s}
.card .num.bump{transform:scale(1.35)}
.card .lbl{font-size:.62rem;font-weight:700;letter-spacing:1px;margin-top:4px;opacity:.65}
.card.strong-buy{background:rgba(22,163,74,.07);border-color:rgba(22,163,74,.18)}.card.strong-buy .num{color:#16a34a}
.card.buy{background:rgba(13,148,136,.06);border-color:rgba(13,148,136,.15)}.card.buy .num{color:#0d9488}
.card.neutral{background:rgba(217,119,6,.06);border-color:rgba(217,119,6,.15)}.card.neutral .num{color:#d97706}
.card.sell{background:rgba(249,115,22,.06);border-color:rgba(249,115,22,.15)}.card.sell .num{color:#f97316}
.card.strong-sell{background:rgba(220,38,38,.06);border-color:rgba(220,38,38,.15)}.card.strong-sell .num{color:#dc2626}
/* section */
.section{margin-bottom:40px}
.sec-title{font-size:.72rem;font-weight:800;letter-spacing:2px;text-transform:uppercase;color:#64748b;margin-bottom:14px;padding-bottom:9px;border-bottom:1px solid #e2e8f0;display:flex;align-items:center;gap:10px}
.sec-count{background:#f5f5f5;border-radius:20px;padding:2px 10px;font-size:.67rem;color:#64748b}
.tbl-wrap{border-radius:12px;border:1px solid #e2e8f0;overflow:hidden;overflow-x:auto;box-shadow:0 1px 3px rgba(0,0,0,.04)}
table{width:100%;border-collapse:collapse}
thead th{background:#f5f5f5;padding:10px 13px;font-size:.64rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#94a3b8;text-align:left;white-space:nowrap}
tbody tr.sr{border-top:1px solid #ebebeb;cursor:pointer;transition:background .1s;background:#ffffff}
tbody tr.sr:hover{background:#f5f5f5}
td{padding:11px 13px;font-size:.84rem;vertical-align:middle}
/* cells */
.tc{font-size:.95rem;font-weight:800;color:#1a1a1a}
.pc{font-size:.82rem;color:#94a3b8}
.num-r{text-align:right;font-variant-numeric:tabular-nums}
.up{color:#16a34a}.dn{color:#dc2626}.ze{color:#94a3b8}
/* weight bar */
.wb-wrap{display:flex;align-items:center;gap:6px}
.wb-bg{width:52px;height:4px;background:#e2e8f0;border-radius:2px;overflow:hidden;flex-shrink:0}
.wb-fill{height:100%;border-radius:2px;background:linear-gradient(90deg,#3b82f6,#6366f1)}
.wb-lbl{font-size:.8rem;font-weight:700;color:#475569;white-space:nowrap}
/* signal badge */
.badge{display:inline-flex;align-items:center;gap:4px;padding:4px 10px;border-radius:16px;font-size:.67rem;font-weight:800;letter-spacing:.6px;white-space:nowrap}
.badge::before{content:'';width:6px;height:6px;border-radius:50%;flex-shrink:0}
.badge.strong-buy{background:rgba(22,163,74,.1);color:#16a34a;border:1px solid rgba(22,163,74,.25)}.badge.strong-buy::before{background:#16a34a;box-shadow:0 0 5px rgba(22,163,74,.4)}
.badge.buy{background:rgba(13,148,136,.1);color:#0d9488;border:1px solid rgba(13,148,136,.22)}.badge.buy::before{background:#0d9488;box-shadow:0 0 5px rgba(13,148,136,.4)}
.badge.neutral{background:rgba(217,119,6,.08);color:#d97706;border:1px solid rgba(217,119,6,.22)}.badge.neutral::before{background:#d97706}
.badge.sell{background:rgba(249,115,22,.09);color:#f97316;border:1px solid rgba(249,115,22,.22)}.badge.sell::before{background:#f97316}
.badge.strong-sell{background:rgba(220,38,38,.09);color:#dc2626;border:1px solid rgba(220,38,38,.22)}.badge.strong-sell::before{background:#dc2626}
/* score bar */
.sb-wrap{display:flex;align-items:center;gap:8px;min-width:130px}
.sb-bg{flex:1;height:4px;background:#e2e8f0;border-radius:2px;overflow:hidden;position:relative}
.sb-mid{position:absolute;left:50%;top:0;width:1px;height:100%;background:#cbd5e1}
.sb-fill{height:100%;border-radius:2px;transition:width .6s ease}
.sb-num{font-size:.8rem;font-weight:800;min-width:30px;text-align:right}
/* indicator pills */
.pills{display:flex;flex-wrap:wrap;gap:3px}
.pill{font-size:.6rem;font-weight:700;padding:2px 5px;border-radius:3px;letter-spacing:.3px;position:relative;cursor:default}
.pill:hover{opacity:.8}
.pill.bull{background:rgba(22,163,74,.1);color:#16a34a}
.pill.bear{background:rgba(220,38,38,.1);color:#dc2626}
.pill.neut{background:rgba(148,163,184,.15);color:#64748b}
.pill .tip{display:none;position:absolute;bottom:calc(100% + 6px);left:50%;transform:translateX(-50%);background:#ffffff;border:1px solid #e2e8f0;border-radius:7px;padding:6px 10px;font-size:.68rem;font-weight:400;white-space:nowrap;color:#475569;z-index:500;pointer-events:none;box-shadow:0 4px 18px rgba(0,0,0,.1)}
.pill:hover .tip{display:block}
/* detail row */
.drow td{padding:0;border:none}
.dinn{display:none;padding:16px 20px;background:#f5f5f5;border-top:1px solid #ebebeb}
.dinn.open{display:block}
.dgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px}
.di{background:#f5f5f5;border-radius:8px;padding:10px 13px;border:1px solid #e2e8f0;border-left:3px solid #e2e8f0}
.di.b{border-left-color:#16a34a}.di.r{border-left-color:#dc2626}.di.g{border-left-color:#cbd5e1}
.di-name{font-size:.62rem;font-weight:800;letter-spacing:.8px;color:#94a3b8;margin-bottom:3px;text-transform:uppercase}
.di-val{font-size:.76rem;color:#475569;line-height:1.4}
/* animations */
@keyframes shimmer{0%{opacity:.35}50%{opacity:.8}100%{opacity:.35}}
.row-loading{animation:shimmer 1.2s ease-in-out infinite}
.row-loading td{color:#e2e8f0 !important}
@keyframes rowflash{0%{background:rgba(13,148,136,.1)}100%{background:transparent}}
.row-flash{animation:rowflash .9s ease-out}
/* empty */
.empty-state{text-align:center;padding:56px 20px;color:#94a3b8}
.empty-state h2{font-size:1rem;font-weight:700;color:#cbd5e1;margin-bottom:6px}
/* footer */
.footer{text-align:center;padding:22px;color:#94a3b8;font-size:.72rem;border-top:1px solid #e2e8f0;margin-top:12px}
/* sortable headers */
thead th.s{cursor:pointer;user-select:none;transition:color .15s;white-space:nowrap}
thead th.s:hover{color:#3b82f6}
thead th.s::after{content:' ▲▼';opacity:.2;font-size:.7em}
thead th.s.desc::after{content:' ▼';opacity:1;color:#3b82f6;font-size:.8em}
thead th.s.asc::after{content:' ▲';opacity:1;color:#3b82f6;font-size:.8em}
thead th.s.desc,thead th.s.asc{color:#475569}
@media(max-width:900px){.hdr{padding:14px 16px;flex-direction:column;gap:8px}.main{padding:16px}.pstrip{flex-wrap:wrap}.adv-grid{grid-template-columns:1fr}.tab-bar{padding:0 16px}}
""" + RADAR_CSS


# ── JS ─────────────────────────────────────────────────────────────────────────

_JS = r"""
const SIG = {
  'STRONG BUY':  ['strong-buy',  '#16a34a'],
  'BUY':         ['buy',         '#0d9488'],
  'NEUTRAL':     ['neutral',     '#d97706'],
  'SELL':        ['sell',        '#f97316'],
  'STRONG SELL': ['strong-sell', '#dc2626'],
};
const IND = {
  RSI:'RSI', MACD:'MACD', '50MA_vs_200MA':'MA50/200',
  Bollinger:'BB', Volume:'VOL', Stochastic:'STOCH',
  ADX:'ADX', EMA_9_vs_21:'EMA9/21', OBV:'OBV', ATR:'ATR'
};
const CARD_IDS = {'STRONG BUY':'c-sb','BUY':'c-b','NEUTRAL':'c-n','SELL':'c-s','STRONG SELL':'c-ss'};
const REC_COLORS = {ADD:'#16a34a',HOLD:'#3b82f6',WATCH:'#d97706',TRIM:'#f97316',EXIT:'#dc2626'};

function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.toggle('active', c.id === 'tab-' + name));
  if (name === 'radar' && !radarInitialized) { radarInitialized = true; initRadar(); }
}

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
    '<br><small style="font-size:.68rem;color:#94a3b8;font-weight:600">'+eqPct.toFixed(1)+'% of portfolio</small></div>';
  document.getElementById('ps-cash').innerHTML =
    '<div class="ps-lbl">Cash</div>'+
    '<div class="ps-val">'+(cash > 0
      ? '$'+cash.toLocaleString('en-US',{maximumFractionDigits:0})+
        '<br><small style="font-size:.68rem;color:#94a3b8;font-weight:600">'+cashPct.toFixed(1)+'% of portfolio</small>'
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
""" + RADAR_JS


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

    # tab bar
    '<div class="tab-bar">'
    '<button class="tab-btn active" data-tab="portfolio" onclick="switchTab(\'portfolio\')">My Portfolio</button>'
    '<button class="tab-btn" data-tab="radar" onclick="switchTab(\'radar\')">Radar Screen</button>'
    '<button class="tab-btn" data-tab="news" onclick="switchTab(\'news\')">News Terminal</button>'
    '</div>'

    # ── My Portfolio tab ──────────────────────────────────────────────────────
    '<div class="tab-content active" id="tab-portfolio">'

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

    '</div>'  # /tab-portfolio

    # ── Radar Screen tab ──────────────────────────────────────────────────────
    '<div class="tab-content" id="tab-radar">'
    + RADAR_HTML +
    '</div>'

    # ── News Terminal tab ─────────────────────────────────────────────────────
    '<div class="tab-content" id="tab-news">'
    '<div class="coming-soon">'
    '<div class="cs-icon">&#128240;</div>'
    '<h2>News Terminal</h2>'
    '<p>Coming soon</p>'
    '</div>'
    '</div>'

    '<div class="footer">Portfolio data from Google Sheets &nbsp;·&nbsp; Prices from Yahoo Finance &nbsp;·&nbsp; '
    '<a href="http://localhost:8080" style="color:#94a3b8">localhost:8080</a></div>'

    '<script>' + _JS + '</script>'
    '</body></html>'
)


if __name__ == "__main__":
    print("\n  Stock Analysis Dashboard  →  http://localhost:8080\n")
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)
