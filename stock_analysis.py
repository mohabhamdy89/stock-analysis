#!/usr/bin/env python3
"""
Stock Technical Analysis Tool
10 indicators → Strong Buy / Buy / Neutral / Sell / Strong Sell
Outputs: terminal summary, analysis_results.csv, dashboard.html
"""

import os
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
warnings.filterwarnings("ignore")


# ── Portfolios (shared with email_alert.py) ────────────────────────────────────
PORTFOLIOS = {
    "My Portfolio": [
        "CRWV", "GOOGL", "NVDA", "SPUS", "GDX",
        "AMD",  "INTC",  "MU",   "TIGO",
    ],
    # Add more portfolios here, e.g.:
    # "Watchlist": ["AAPL", "MSFT", "TSLA", "META"],
    # "ETFs":      ["SPY", "QQQ", "IWM", "XLK"],
}


# ── Indicator Calculations ─────────────────────────────────────────────────────

def calc_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def calc_macd(close, fast=12, slow=26, signal=9):
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    line = ema_f - ema_s
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig


def calc_bollinger(close, period=20, k=2):
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    return mid + k * std, mid, mid - k * std


def calc_stochastic(high, low, close, k_period=14, d_period=3):
    lo = low.rolling(k_period).min()
    hi = high.rolling(k_period).max()
    pct_k = 100 * (close - lo) / (hi - lo)
    pct_d = pct_k.rolling(d_period).mean()
    return pct_k, pct_d


def calc_adx(high, low, close, period=14):
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()

    up   = high.diff()
    down = -low.diff()
    plus_dm  = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)

    plus_di  = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx_line = dx.ewm(span=period, adjust=False).mean()
    return adx_line, plus_di, minus_di


def calc_obv(close, volume):
    direction = np.sign(close.diff().fillna(0))
    return (volume * direction).cumsum()


def calc_atr(high, low, close, period=14):
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


# ── Signal Scoring ─────────────────────────────────────────────────────────────

def score_stock(ticker: str):
    df = yf.download(ticker, period="1y", interval="1d", progress=False, auto_adjust=True)
    if df is None or df.empty or len(df) < 60:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    close  = df["Close"].astype(float)
    high   = df["High"].astype(float)
    low    = df["Low"].astype(float)
    volume = df["Volume"].astype(float)

    price = close.iloc[-1]
    scores  = {}
    details = {}

    # 1. RSI
    r = calc_rsi(close).iloc[-1]
    if r < 30:
        scores["RSI"] = 1;  details["RSI"] = f"{r:.1f}  Oversold — Bullish"
    elif r > 70:
        scores["RSI"] = -1; details["RSI"] = f"{r:.1f}  Overbought — Bearish"
    else:
        scores["RSI"] = 0;  details["RSI"] = f"{r:.1f}  Neutral"

    # 2. MACD
    ml, sl = calc_macd(close)
    diff, prev_diff = (ml - sl).iloc[-1], (ml - sl).iloc[-2]
    if diff > 0:
        tag = "Bullish crossover" if prev_diff <= 0 else "Above signal line"
        scores["MACD"] = 1;  details["MACD"] = tag
    else:
        tag = "Bearish crossover" if prev_diff >= 0 else "Below signal line"
        scores["MACD"] = -1; details["MACD"] = tag

    # 3. 50 MA vs 200 MA
    ma50  = close.rolling(50).mean().iloc[-1]
    ma200 = close.rolling(200).mean().iloc[-1]
    if ma50 > ma200:
        scores["50MA_vs_200MA"] = 1
        details["50MA_vs_200MA"] = f"50MA {ma50:.2f} > 200MA {ma200:.2f}  Golden Cross"
    else:
        scores["50MA_vs_200MA"] = -1
        details["50MA_vs_200MA"] = f"50MA {ma50:.2f} < 200MA {ma200:.2f}  Death Cross"

    # 4. Bollinger Bands
    upper, _, lower = calc_bollinger(close)
    band_range = upper.iloc[-1] - lower.iloc[-1]
    bb_pct = (price - lower.iloc[-1]) / band_range if band_range != 0 else 0.5
    if bb_pct < 0.20:
        scores["Bollinger"] = 1;  details["Bollinger"] = f"%B={bb_pct:.2f}  Near lower band — Bullish"
    elif bb_pct > 0.80:
        scores["Bollinger"] = -1; details["Bollinger"] = f"%B={bb_pct:.2f}  Near upper band — Bearish"
    else:
        scores["Bollinger"] = 0;  details["Bollinger"] = f"%B={bb_pct:.2f}  Mid-range — Neutral"

    # 5. Volume Trend
    avg_vol    = volume.rolling(20).mean().iloc[-1]
    recent_vol = volume.iloc[-5:].mean()
    price_chg  = close.pct_change(5).iloc[-1]
    if recent_vol > avg_vol * 1.2 and price_chg > 0:
        scores["Volume"] = 1;  details["Volume"] = "High volume + price rising — Bullish"
    elif recent_vol > avg_vol * 1.2 and price_chg < 0:
        scores["Volume"] = -1; details["Volume"] = "High volume + price falling — Bearish"
    else:
        scores["Volume"] = 0;  details["Volume"] = "Normal volume — Neutral"

    # 6. Stochastic Oscillator
    kv, dv = calc_stochastic(high, low, close)
    k, d = kv.iloc[-1], dv.iloc[-1]
    if k < 20:
        scores["Stochastic"] = 1;  details["Stochastic"] = f"%K={k:.1f}  Oversold — Bullish"
    elif k > 80:
        scores["Stochastic"] = -1; details["Stochastic"] = f"%K={k:.1f}  Overbought — Bearish"
    else:
        scores["Stochastic"] = 0;  details["Stochastic"] = f"%K={k:.1f}  Neutral"

    # 7. ADX
    adx_s, plus_di, minus_di = calc_adx(high, low, close)
    av, pdi, mdi = adx_s.iloc[-1], plus_di.iloc[-1], minus_di.iloc[-1]
    if av > 25 and pdi > mdi:
        scores["ADX"] = 1;  details["ADX"] = f"ADX={av:.1f}  +DI > -DI — Strong uptrend"
    elif av > 25 and mdi > pdi:
        scores["ADX"] = -1; details["ADX"] = f"ADX={av:.1f}  -DI > +DI — Strong downtrend"
    else:
        scores["ADX"] = 0;  details["ADX"] = f"ADX={av:.1f}  Weak/no trend"

    # 8. EMA 9 vs EMA 21
    ema9  = close.ewm(span=9,  adjust=False).mean().iloc[-1]
    ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
    if ema9 > ema21:
        scores["EMA_9_vs_21"] = 1
        details["EMA_9_vs_21"] = f"EMA9 {ema9:.2f} > EMA21 {ema21:.2f}  Bullish"
    else:
        scores["EMA_9_vs_21"] = -1
        details["EMA_9_vs_21"] = f"EMA9 {ema9:.2f} < EMA21 {ema21:.2f}  Bearish"

    # 9. OBV
    obv_series = pd.Series(calc_obv(close, volume), index=close.index)
    obv_sma    = obv_series.rolling(20).mean()
    if obv_series.iloc[-1] > obv_sma.iloc[-1]:
        scores["OBV"] = 1;  details["OBV"] = "OBV above 20-SMA — Buying pressure"
    else:
        scores["OBV"] = -1; details["OBV"] = "OBV below 20-SMA — Selling pressure"

    # 10. ATR
    atr_series = calc_atr(high, low, close)
    atr_now    = atr_series.iloc[-1]
    atr_avg    = atr_series.rolling(20).mean().iloc[-1]
    price_trend = close.pct_change(10).iloc[-1]
    if atr_now > atr_avg and price_trend > 0:
        scores["ATR"] = 1;  details["ATR"] = f"ATR={atr_now:.2f}  Expanding + price up — Bullish momentum"
    elif atr_now > atr_avg and price_trend < 0:
        scores["ATR"] = -1; details["ATR"] = f"ATR={atr_now:.2f}  Expanding + price down — Bearish momentum"
    else:
        scores["ATR"] = 0;  details["ATR"] = f"ATR={atr_now:.2f}  Contracting — Consolidation"

    total = sum(scores.values())
    if   total >= 6:  signal = "STRONG BUY"
    elif total >= 3:  signal = "BUY"
    elif total >= -2: signal = "NEUTRAL"
    elif total >= -5: signal = "SELL"
    else:             signal = "STRONG SELL"

    return {
        "ticker":    ticker,
        "price":     price,
        "signal":    signal,
        "score":     total,
        "scores":    scores,
        "details":   details,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ── Terminal Output ────────────────────────────────────────────────────────────

SIGNAL_LABEL = {
    "STRONG BUY":  "🟢 STRONG BUY",
    "BUY":         "🟩 BUY",
    "NEUTRAL":     "🟡 NEUTRAL",
    "SELL":        "🟧 SELL",
    "STRONG SELL": "🔴 STRONG SELL",
}

SCORE_ARROW = {1: "▲ Bullish", 0: "─ Neutral", -1: "▼ Bearish"}


def analyze_portfolio(stocks: list, portfolio_name: str = "Portfolio"):
    print(f"\n{'='*62}")
    print(f"  {portfolio_name}  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*62}")

    results = []
    for ticker in stocks:
        print(f"  Fetching {ticker:<6} ...", end=" ", flush=True)
        result = score_stock(ticker)
        if result:
            results.append(result)
            label = SIGNAL_LABEL[result["signal"]]
            print(f"{label:<22}  Score: {result['score']:+d}/10")
        else:
            print("⚠  Insufficient data — skipped")

    if not results:
        print("  No results to display.\n")
        return pd.DataFrame(), []

    print(f"\n{'─'*62}")
    print(f"  {'TICKER':<8} {'PRICE':>8}  {'SIGNAL':<20}  SCORE")
    print(f"{'─'*62}")
    for r in sorted(results, key=lambda x: x["score"], reverse=True):
        label = SIGNAL_LABEL[r["signal"]]
        print(f"  {r['ticker']:<8} ${r['price']:>7.2f}  {label:<25}  {r['score']:+d}/10")
    print(f"{'='*62}\n")

    rows = []
    for r in results:
        row = {
            "Portfolio": portfolio_name,
            "Ticker":    r["ticker"],
            "Price":     round(r["price"], 2),
            "Signal":    r["signal"],
            "Score":     r["score"],
            "Timestamp": r["timestamp"],
        }
        for ind, s in r["scores"].items():
            row[ind] = SCORE_ARROW[s]
        rows.append(row)

    return pd.DataFrame(rows), results


def print_detail(results: list):
    print(f"\n{'='*62}")
    print("  DETAILED INDICATOR BREAKDOWN")
    print(f"{'='*62}")
    for r in results:
        label = SIGNAL_LABEL[r["signal"]]
        print(f"\n  {r['ticker']}  {label}  (Score: {r['score']:+d}/10)  |  Price: ${r['price']:.2f}")
        print(f"  {'─'*58}")
        for ind, s in r["scores"].items():
            arrow = SCORE_ARROW[s]
            print(f"    {arrow:<14}  {ind:<18}  {r['details'][ind]}")
    print()


# ── HTML Dashboard ─────────────────────────────────────────────────────────────

_IND_SHORT = {
    "RSI":          "RSI",
    "MACD":         "MACD",
    "50MA_vs_200MA":"MA50/200",
    "Bollinger":    "BB",
    "Volume":       "VOL",
    "Stochastic":   "STOCH",
    "ADX":          "ADX",
    "EMA_9_vs_21":  "EMA9/21",
    "OBV":          "OBV",
    "ATR":          "ATR",
}

_SIG = {
    "STRONG BUY":  ("strong-buy",  "#00e676"),
    "BUY":         ("buy",         "#1de9b6"),
    "NEUTRAL":     ("neutral",     "#ffd740"),
    "SELL":        ("sell",        "#ff9800"),
    "STRONG SELL": ("strong-sell", "#f44336"),
}

_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#080d1a;color:#e2e8f0;min-height:100vh}
/* ── header ── */
.hdr{background:linear-gradient(135deg,#0f1729 0%,#0a1220 60%,#111e35 100%);border-bottom:1px solid #1a2740;padding:22px 40px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;backdrop-filter:blur(16px)}
.hdr-l h1{font-size:1.55rem;font-weight:800;background:linear-gradient(135deg,#60a5fa,#a78bfa 60%,#38bdf8);-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:-.5px}
.hdr-l .sub{color:#475569;font-size:.75rem;margin-top:3px;letter-spacing:.4px}
.hdr-r{text-align:right}
.ts{color:#64748b;font-size:.8rem}
.cd{color:#60a5fa;font-size:.82rem;font-weight:700;margin-top:3px}
.rbtn{margin-top:8px;padding:6px 18px;background:linear-gradient(135deg,#3b82f6,#6366f1);border:none;border-radius:20px;color:#fff;font-size:.75rem;font-weight:700;cursor:pointer;letter-spacing:.3px;transition:opacity .15s,transform .15s}
.rbtn:hover{opacity:.85;transform:translateY(-1px)}
/* ── main ── */
.main{padding:32px 40px;max-width:1440px;margin:0 auto}
/* ── summary cards ── */
.cards{display:flex;gap:12px;margin-bottom:36px;flex-wrap:wrap}
.card{flex:1;min-width:130px;border-radius:14px;padding:18px 22px;text-align:center;border:1px solid rgba(255,255,255,.05);transition:transform .2s,box-shadow .2s;cursor:default}
.card:hover{transform:translateY(-3px)}
.card .num{font-size:2.4rem;font-weight:900;line-height:1}
.card .lbl{font-size:.65rem;font-weight:700;letter-spacing:1.2px;margin-top:5px;opacity:.7}
.card.strong-buy{background:rgba(0,230,118,.08);border-color:rgba(0,230,118,.2)}.card.strong-buy .num{color:#00e676}
.card.buy{background:rgba(29,233,182,.07);border-color:rgba(29,233,182,.18)}.card.buy .num{color:#1de9b6}
.card.neutral{background:rgba(255,215,64,.07);border-color:rgba(255,215,64,.18)}.card.neutral .num{color:#ffd740}
.card.sell{background:rgba(255,152,0,.07);border-color:rgba(255,152,0,.18)}.card.sell .num{color:#ff9800}
.card.strong-sell{background:rgba(244,67,54,.07);border-color:rgba(244,67,54,.18)}.card.strong-sell .num{color:#f44336}
/* ── section ── */
.section{margin-bottom:44px}
.sec-title{font-size:.78rem;font-weight:800;letter-spacing:2.5px;text-transform:uppercase;color:#334155;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid #1a2535;display:flex;align-items:center;gap:10px}
.sec-count{background:#1a2535;border-radius:20px;padding:2px 10px;font-size:.7rem;color:#475569}
/* ── table ── */
.tbl-wrap{border-radius:14px;border:1px solid #1a2535;overflow:hidden;overflow-x:auto}
table{width:100%;border-collapse:collapse}
thead th{background:#0b1220;padding:11px 16px;font-size:.68rem;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;color:#374151;text-align:left;white-space:nowrap}
tbody tr.stock-row{border-top:1px solid #111827;cursor:pointer;transition:background .12s}
tbody tr.stock-row:hover{background:rgba(255,255,255,.025)}
td{padding:13px 16px;font-size:.87rem;vertical-align:middle}
/* ── badge ── */
.badge{display:inline-flex;align-items:center;gap:5px;padding:5px 13px;border-radius:20px;font-size:.7rem;font-weight:800;letter-spacing:.7px;white-space:nowrap}
.badge::before{content:'';width:7px;height:7px;border-radius:50%;flex-shrink:0}
.badge.strong-buy{background:rgba(0,230,118,.13);color:#00e676;border:1px solid rgba(0,230,118,.28)}.badge.strong-buy::before{background:#00e676;box-shadow:0 0 6px #00e676}
.badge.buy{background:rgba(29,233,182,.1);color:#1de9b6;border:1px solid rgba(29,233,182,.25)}.badge.buy::before{background:#1de9b6;box-shadow:0 0 6px #1de9b6}
.badge.neutral{background:rgba(255,215,64,.09);color:#ffd740;border:1px solid rgba(255,215,64,.25)}.badge.neutral::before{background:#ffd740}
.badge.sell{background:rgba(255,152,0,.1);color:#ff9800;border:1px solid rgba(255,152,0,.25)}.badge.sell::before{background:#ff9800;box-shadow:0 0 6px #ff9800}
.badge.strong-sell{background:rgba(244,67,54,.1);color:#f44336;border:1px solid rgba(244,67,54,.25)}.badge.strong-sell::before{background:#f44336;box-shadow:0 0 6px #f44336}
/* ── score bar ── */
.sb-wrap{display:flex;align-items:center;gap:10px;min-width:170px}
.sb-bg{flex:1;height:5px;background:#1a2535;border-radius:3px;overflow:hidden;position:relative}
.sb-mid{position:absolute;left:50%;top:0;width:1px;height:100%;background:#334155}
.sb-fill{height:100%;border-radius:3px;transition:width .5s ease}
.sb-num{font-size:.85rem;font-weight:800;min-width:34px;text-align:right}
/* ── ticker / price ── */
.tc{font-size:.98rem;font-weight:800;color:#f1f5f9;letter-spacing:.3px}
.pc{font-size:.9rem;font-weight:500;color:#64748b}
/* ── pills ── */
.pills{display:flex;flex-wrap:wrap;gap:3px}
.pill{font-size:.62rem;font-weight:700;padding:3px 6px;border-radius:4px;letter-spacing:.4px;position:relative;cursor:default;transition:opacity .12s}
.pill:hover{opacity:.8}
.pill.bull{background:rgba(0,230,118,.13);color:#00e676}
.pill.bear{background:rgba(244,67,54,.1);color:#f44336}
.pill.neut{background:rgba(71,85,105,.2);color:#64748b}
.pill .tip{display:none;position:absolute;bottom:calc(100% + 7px);left:50%;transform:translateX(-50%);background:#1e293b;border:1px solid #2d3f57;border-radius:8px;padding:7px 11px;font-size:.7rem;font-weight:400;white-space:nowrap;color:#cbd5e1;z-index:500;pointer-events:none;box-shadow:0 4px 20px rgba(0,0,0,.5)}
.pill:hover .tip{display:block}
/* ── detail row ── */
.drow td{padding:0;border:none}
.dinn{display:none;padding:18px 22px;background:#060c18;border-top:1px solid #111827}
.dinn.open{display:block}
.dgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}
.di{background:#0d1525;border-radius:10px;padding:11px 15px;border:1px solid #1a2535;border-left:3px solid #1a2535}
.di.b{border-left-color:#00e676}.di.r{border-left-color:#f44336}.di.g{border-left-color:#334155}
.di-name{font-size:.65rem;font-weight:800;letter-spacing:1px;color:#374151;margin-bottom:4px;text-transform:uppercase}
.di-val{font-size:.78rem;color:#94a3b8;line-height:1.4}
/* ── footer ── */
.footer{text-align:center;padding:24px 20px;color:#1e293b;font-size:.75rem;border-top:1px solid #0f1829;margin-top:16px}
.footer a{color:#334155;text-decoration:none}
/* ── responsive ── */
@media(max-width:768px){.hdr{padding:16px 18px;flex-direction:column;gap:10px;text-align:center}.main{padding:18px}.cards{gap:8px}.card{min-width:90px;padding:12px 10px}.card .num{font-size:1.8rem}}
"""

_JS = """
(function(){
  var secs=300;
  var el=document.getElementById('cd');
  function tick(){
    var m=Math.floor(secs/60),s=secs%60;
    if(el) el.textContent='Refreshing in '+m+':'+(s<10?'0':'')+s;
    if(secs<=0){location.reload();return;}
    secs--;
    setTimeout(tick,1000);
  }
  tick();
  document.querySelectorAll('tr.sr').forEach(function(row){
    row.addEventListener('click',function(){
      var id=row.getAttribute('data-id');
      var d=document.getElementById('d'+id);
      if(d) d.classList.toggle('open');
    });
  });
})();
"""


def generate_dashboard(portfolio_results: dict, output_path: str = "dashboard.html"):
    """Generate a professional HTML dashboard. portfolio_results = {name: [result, ...]}"""

    now_str = datetime.now().strftime("%A, %B %d %Y  at  %I:%M %p")

    all_r = [r for results in portfolio_results.values() for r in results]
    sc = {s: sum(1 for r in all_r if r["signal"] == s)
          for s in ["STRONG BUY", "BUY", "NEUTRAL", "SELL", "STRONG SELL"]}

    # summary cards
    cards = (
        '<div class="cards">'
        '<div class="card strong-buy"><div class="num">' + str(sc["STRONG BUY"]) + '</div><div class="lbl">STRONG BUY</div></div>'
        '<div class="card buy"><div class="num">' + str(sc["BUY"]) + '</div><div class="lbl">BUY</div></div>'
        '<div class="card neutral"><div class="num">' + str(sc["NEUTRAL"]) + '</div><div class="lbl">NEUTRAL</div></div>'
        '<div class="card sell"><div class="num">' + str(sc["SELL"]) + '</div><div class="lbl">SELL</div></div>'
        '<div class="card strong-sell"><div class="num">' + str(sc["STRONG SELL"]) + '</div><div class="lbl">STRONG SELL</div></div>'
        '</div>'
    )

    # portfolio tables
    tables = ""
    row_id = 0
    for pname, results in portfolio_results.items():
        sorted_r = sorted(results, key=lambda x: x["score"], reverse=True)
        rows_html = ""
        for r in sorted_r:
            rid = str(row_id); row_id += 1
            cls, color = _SIG[r["signal"]]

            # score bar: score -10..+10 → 0..100%
            fill_pct = round((r["score"] + 10) / 20 * 100, 1)
            score_sign = ("+" if r["score"] > 0 else "") + str(r["score"])

            # indicator pills
            pills = ""
            for ind, s in r["scores"].items():
                short = _IND_SHORT.get(ind, ind)
                pcls  = "bull" if s == 1 else ("bear" if s == -1 else "neut")
                tip   = r["details"][ind].replace("<", "&lt;").replace(">", "&gt;")
                pills += (
                    '<span class="pill ' + pcls + '">' + short +
                    '<span class="tip">' + tip + '</span></span>'
                )

            # detail cards
            detail = ""
            for ind, s in r["scores"].items():
                dcls = "b" if s == 1 else ("r" if s == -1 else "g")
                val  = r["details"][ind].replace("<", "&lt;").replace(">", "&gt;")
                detail += (
                    '<div class="di ' + dcls + '">'
                    '<div class="di-name">' + ind.replace("_", " ") + '</div>'
                    '<div class="di-val">' + val + '</div>'
                    '</div>'
                )

            rows_html += (
                '<tr class="stock-row sr" data-id="' + rid + '">'
                '<td class="tc">' + r["ticker"] + '</td>'
                '<td class="pc">$' + f'{r["price"]:.2f}' + '</td>'
                '<td><span class="badge ' + cls + '">' + r["signal"] + '</span></td>'
                '<td><div class="sb-wrap">'
                '<div class="sb-bg"><div class="sb-mid"></div>'
                '<div class="sb-fill" style="width:' + str(fill_pct) + '%;background:' + color + '"></div>'
                '</div>'
                '<span class="sb-num" style="color:' + color + '">' + score_sign + '</span>'
                '</div></td>'
                '<td><div class="pills">' + pills + '</div></td>'
                '</tr>'
                '<tr class="drow"><td colspan="5">'
                '<div class="dinn" id="d' + rid + '">'
                '<div class="dgrid">' + detail + '</div>'
                '</div></td></tr>'
            )

        tables += (
            '<div class="section">'
            '<div class="sec-title">' + pname +
            '<span class="sec-count">' + str(len(sorted_r)) + ' stocks</span></div>'
            '<div class="tbl-wrap"><table>'
            '<thead><tr>'
            '<th>Ticker</th><th>Price</th><th>Signal</th>'
            '<th>Score &nbsp;(−10 → +10)</th>'
            '<th>Indicators &nbsp;— click row to expand</th>'
            '</tr></thead>'
            '<tbody>' + rows_html + '</tbody>'
            '</table></div></div>'
        )

    # assemble
    html_parts = [
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n',
        '<meta charset="UTF-8">\n',
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n',
        '<title>Stock Analysis Dashboard</title>\n',
        '<style>', _CSS, '</style>\n',
        '</head>\n<body>\n',
        '<div class="hdr">',
        '<div class="hdr-l">',
        '<h1>&#9654; Stock Analysis Dashboard</h1>',
        '<div class="sub">10 Technical Indicators &nbsp;·&nbsp; Yahoo Finance Data &nbsp;·&nbsp; Click any row for details</div>',
        '</div>',
        '<div class="hdr-r">',
        '<div class="ts">Updated: ' + now_str + '</div>',
        '<div class="cd" id="cd">Refreshing in 5:00</div>',
        '<button class="rbtn" onclick="location.reload()">&#8635; Refresh Now</button>',
        '</div></div>\n',
        '<div class="main">\n',
        cards, '\n',
        tables,
        '</div>\n',
        '<div class="footer">',
        'Data sourced from Yahoo Finance &nbsp;·&nbsp; Page auto-reloads every 5 min &nbsp;·&nbsp; ',
        'Re-run <code>python3 stock_analysis.py</code> to pull fresh data',
        '</div>\n',
        '<script>', _JS, '</script>\n',
        '</body>\n</html>',
    ]

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("".join(html_parts))

    print(f"  Dashboard saved → {output_path}")


# ── Google Sheets Portfolio Integration ───────────────────────────────────────

GOOGLE_SHEET_NAME = "Mohab - Investment Portfolio"
CREDENTIALS_FILE  = "google_credentials.json"


def read_portfolio_sheet():
    """Read live positions from Google Sheets.
    Returns (portfolios_dict, positions_dict, cash, portfolio_pnl_pct) or ({}, {}, 0.0, None).
      portfolios_dict  : {"My Portfolio": ["CRWV", "GOOGL", ...]}
      positions_dict   : {"CRWV": {"shares": 200.0, "cost_basis": 115.51, "pnl_pct": 1.24}, ...}
      cash             : float — cash balance read directly from sheet
      portfolio_pnl_pct: float | None — overall portfolio YTD P&L % from sheet
    """
    import warnings as _w; _w.filterwarnings("ignore")
    try:
        import gspread
        from google.oauth2.service_account import Credentials as _C
    except ImportError:
        return {}, {}, 0.0, None

    creds_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CREDENTIALS_FILE)
    if not os.path.exists(creds_path):
        return {}, {}, 0.0, None

    try:
        creds = _C.from_service_account_file(
            creds_path,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets.readonly",
                "https://www.googleapis.com/auth/drive.readonly",
            ],
        )
        rows = gspread.authorize(creds).open(GOOGLE_SHEET_NAME).sheet1.get_all_values()
    except Exception as e:
        print(f"  ⚠  Google Sheets: {e}")
        return {}, {}, 0.0, None

    # Locate header row (contains "Instrument" or "Ticker")
    header_idx = ticker_col = shares_col = cost_col = mv_col = pnl_pct_col = None
    for i, row in enumerate(rows):
        low = [c.strip().lower() for c in row]
        if any(k in low for k in ["instrument", "ticker", "symbol"]):
            header_idx = i
            for j, h in enumerate(low):
                if h in ("instrument", "ticker", "symbol", "stock"):
                    ticker_col = j
                if h in ("position", "shares", "quantity", "qty"):
                    shares_col = j
                if "avg" in h and "price" in h:
                    cost_col = j
                elif cost_col is None and "avg" in h and "cost" in h:
                    cost_col = j
                if ("market" in h and "value" in h) or ("mkt" in h and "val" in h):
                    mv_col = j
                # "Unrlzd P&L %" — the % column (not the raw $ one)
                if "unrlzd" in h and "%" in h:
                    pnl_pct_col = j
            break

    if header_idx is None or ticker_col is None:
        return {}, {}, 0.0, None

    def _n(s):
        try:
            return float(str(s).replace(",", "").replace("$", "").replace("%", "").strip() or 0)
        except Exception:
            return 0.0

    cash = 0.0
    portfolio_pnl_pct = None
    tickers, positions = [], {}
    for row in rows[header_idx + 1:]:
        if not row or len(row) <= ticker_col:
            continue
        cell = str(row[ticker_col]).strip()
        ticker = cell.upper()
        if not ticker:
            continue
        # Detect the portfolio-level P&L % summary row (e.g. "Portfolio P&L (%) YTD")
        cell_low = cell.lower()
        if "portfolio" in cell_low and ("p&l" in cell_low or "pnl" in cell_low):
            if mv_col and len(row) > mv_col:
                v = _n(row[mv_col])
                if v:
                    portfolio_pnl_pct = v
            continue
        # Detect cash rows
        if "CASH" in ticker or ticker in ("USD", "USDT", "MONEY", "LIQUIDITY"):
            if mv_col and len(row) > mv_col and _n(row[mv_col]):
                cash = _n(row[mv_col])
            elif shares_col and len(row) > shares_col:
                sh = _n(row[shares_col])
                co = _n(row[cost_col]) if cost_col and len(row) > cost_col else 1.0
                cash = sh * co if co and abs(co - 1.0) > 0.01 else sh
            continue
        if len(ticker) > 6:
            continue
        if not ticker.replace(".", "").replace("-", "").isalpha():
            continue
        shares  = _n(row[shares_col])   if shares_col   and len(row) > shares_col   else 0.0
        cost    = _n(row[cost_col])     if cost_col     and len(row) > cost_col     else 0.0
        pnl_pct = _n(row[pnl_pct_col]) if pnl_pct_col  and len(row) > pnl_pct_col  else None
        tickers.append(ticker)
        positions[ticker] = {"shares": shares, "cost_basis": cost, "pnl_pct": pnl_pct}

    return ({"My Portfolio": tickers}, positions, cash, portfolio_pnl_pct) if tickers else ({}, {}, 0.0, None)


def enrich_with_portfolio(results_list: list, positions: dict, cash: float = 0.0,
                          portfolio_pnl_pct: float = None) -> tuple:
    """Add market value, cost basis, P&L, and weight_pct to each result dict.
    Per-stock P&L % is taken directly from the sheet when available.
    Weights are calculated as % of total portfolio (equity + cash).
    Returns (enriched_list, totals_dict).
    """
    enriched, total_mv = [], 0.0
    for r in results_list:
        pos        = positions.get(r["ticker"], {})
        shares     = float(pos.get("shares",     0))
        cost_ps    = float(pos.get("cost_basis", 0))
        price      = float(r["price"])
        mv         = shares * price
        total_cost = shares * cost_ps
        pnl        = mv - total_cost
        # Prefer the sheet's P&L% if available; fall back to calculated
        sheet_pnl_pct = pos.get("pnl_pct")
        pnl_pct = float(sheet_pnl_pct) if sheet_pnl_pct is not None else (
            (pnl / total_cost * 100) if total_cost else 0.0
        )
        total_mv  += mv
        enriched.append({**r,
            "shares": shares, "cost_basis_ps": cost_ps,
            "total_cost": total_cost, "market_value": mv,
            "unrealized_pnl": pnl, "unrealized_pnl_pct": pnl_pct,
            "weight_pct": 0.0})

    total_portfolio = total_mv + cash
    for r in enriched:
        r["weight_pct"] = (r["market_value"] / total_portfolio * 100) if total_portfolio else 0.0

    all_cost = sum(r["total_cost"] for r in enriched)
    tot_pnl  = total_mv - all_cost
    cash_weight   = (cash / total_portfolio * 100) if total_portfolio else 0.0
    equity_weight = 100.0 - cash_weight if total_portfolio else 0.0
    totals = {
        "total_market_value":       round(total_mv, 2),
        "total_portfolio_value":    round(total_portfolio, 2),
        "total_cost":               round(all_cost, 2),
        "total_unrealized_pnl":     round(tot_pnl, 2),
        "total_unrealized_pnl_pct": round((tot_pnl / all_cost * 100) if all_cost else 0, 2),
        "num_positions":            len(enriched),
        "cash":                     round(cash, 2),
        "cash_weight_pct":          round(cash_weight, 2),
        "equity_weight_pct":        round(equity_weight, 2),
        "sheet_pnl_pct":            round(portfolio_pnl_pct, 2) if portfolio_pnl_pct is not None else None,
    }
    return enriched, totals


def fetch_benchmark_returns() -> dict:
    """Fetch YTD returns for S&P 500 and NASDAQ Composite."""
    symbols = {"sp500": ("S&P 500", "^GSPC"), "nasdaq": ("NASDAQ", "^IXIC")}
    result = {}
    year_start = f"{datetime.now().year}-01-01"
    for key, (name, sym) in symbols.items():
        try:
            df = yf.download(sym, start=year_start, interval="1d", progress=False, auto_adjust=True)
            if df is None or df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            first = float(df["Close"].iloc[0])
            last  = float(df["Close"].iloc[-1])
            ret   = (last - first) / first * 100
            result[key] = {"name": name, "symbol": sym, "return_ytd": round(ret, 2), "price": round(last, 2)}
        except Exception:
            pass
    return result


def generate_advisor_recs(enriched: list) -> list:
    """Combine portfolio weights with technical signals to produce recommendations."""
    if not enriched:
        return []

    # Use actual average equity weight (accounts for cash allocation)
    equity_total_w = sum(r.get("weight_pct", 0) for r in enriched)
    avg_w = equity_total_w / len(enriched) if enriched else (100.0 / len(enriched))

    def _hl(r):
        d, h = r.get("details", {}), []
        m50  = d.get("50MA_vs_200MA", "")
        if "Death Cross"  in m50: h.append("Death Cross")
        if "Golden Cross" in m50: h.append("Golden Cross")
        rsi  = d.get("RSI", "")
        if "Overbought" in rsi:   h.append("RSI Overbought")
        elif "Oversold" in rsi:   h.append("RSI Oversold")
        macd = d.get("MACD", "").lower()
        if "bullish crossover" in macd:  h.append("MACD Bullish crossover")
        elif "bearish crossover" in macd: h.append("MACD Bearish crossover")
        adx  = d.get("ADX", "")
        if "Strong uptrend"    in adx:   h.append("Strong uptrend (ADX)")
        elif "Strong downtrend" in adx:  h.append("Strong downtrend (ADX)")
        return h

    ORDER = {"EXIT": 0, "TRIM": 1, "ADD": 2, "WATCH": 3, "HOLD": 4}
    recs  = []

    for r in enriched:
        t    = r["ticker"]
        sig  = r["signal"]
        sc   = r["score"]
        w    = r.get("weight_pct", 0)
        hl   = _hl(r)
        hls  = " · ".join(hl) if hl else ""
        ss   = (f"+{sc}" if sc > 0 else str(sc)) + "/10"
        over  = w > avg_w * 1.25
        under = w < avg_w * 0.80

        if sig == "STRONG BUY":
            if under:
                tgt = round(min(avg_w * 1.4, w * 1.8), 1)
                recs.append({"type": "ADD",  "priority": 1, "ticker": t, "signal": sig, "weight": w, "target": tgt,
                    "headline": f"Add to {t} — Strong Buy but only {w:.1f}% weight",
                    "detail":   f"Score {ss}{(' · ' + hls) if hls else ''}. Consider growing {w:.1f}% → {tgt:.1f}%."})
            else:
                recs.append({"type": "HOLD", "priority": 4, "ticker": t, "signal": sig, "weight": w,
                    "headline": f"Hold {t} — Strong Buy, conviction position at {w:.1f}%",
                    "detail":   f"Score {ss}{(' · ' + hls) if hls else ''}. Well-sized."})

        elif sig == "BUY":
            if under:
                tgt = round(min(avg_w * 1.2, w * 1.4), 1)
                recs.append({"type": "ADD",  "priority": 2, "ticker": t, "signal": sig, "weight": w, "target": tgt,
                    "headline": f"Consider adding {t} — Buy signal, underweight at {w:.1f}%",
                    "detail":   f"Score {ss}{(' · ' + hls) if hls else ''}. Could grow to {tgt:.1f}%."})
            else:
                recs.append({"type": "HOLD", "priority": 5, "ticker": t, "signal": sig, "weight": w,
                    "headline": f"Hold {t} — Buy signal at {w:.1f}%",
                    "detail":   f"Score {ss}. Maintain position."})

        elif sig == "NEUTRAL":
            if over:
                tgt = round(avg_w * 0.9, 1)
                recs.append({"type": "WATCH", "priority": 3, "ticker": t, "signal": sig, "weight": w, "target": tgt,
                    "headline": f"Watch {t} — Neutral signal but overweight at {w:.1f}%",
                    "detail":   f"Score {ss}{(' · ' + hls) if hls else ''}. Elevated weight, no clear direction."})

        elif sig == "SELL":
            tgt = round(max(avg_w * 0.6, w * 0.55), 1)
            recs.append({"type": "TRIM", "priority": 1, "ticker": t, "signal": sig, "weight": w, "target": tgt,
                "headline": f"Trim {t} from {w:.1f}% to ~{tgt:.1f}% — Sell signal",
                "detail":   f"Score {ss}{(' · ' + hls) if hls else ''}. Reduce exposure."})

        elif sig == "STRONG SELL":
            recs.append({"type": "EXIT", "priority": 0, "ticker": t, "signal": sig, "weight": w,
                "headline": f"Exit {t} — Strong Sell signal ({w:.1f}% at risk)",
                "detail":   f"Score {ss}{(' · ' + hls) if hls else ''}. Clear bearish signal."})

    recs.sort(key=lambda x: (ORDER.get(x["type"], 9), -x["weight"]))
    return recs


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    # Try Google Sheets first; fall back to hardcoded PORTFOLIOS
    _sheet_portfolios, _positions, _cash, _pnl_pct = read_portfolio_sheet()
    _active_portfolios = _sheet_portfolios if _sheet_portfolios else PORTFOLIOS

    all_dfs            = []
    all_results        = []
    portfolio_results  = {}

    for name, tickers in _active_portfolios.items():
        df, results = analyze_portfolio(tickers, name)
        if not df.empty:
            all_dfs.append(df)
            all_results.extend(results)
            portfolio_results[name] = results

    print_detail(all_results)

    if all_dfs:
        pd.concat(all_dfs, ignore_index=True).to_csv("analysis_results.csv", index=False)
        print("  Results saved → analysis_results.csv")

    if portfolio_results:
        generate_dashboard(portfolio_results, "dashboard.html")

    print()
