#!/usr/bin/env python3
"""Radar Screen — server-side data fetching for watchlist stocks."""

import json, os, time, threading
from datetime import datetime, date
import urllib.request
import xml.etree.ElementTree as ET

import yfinance as yf

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_FILE = os.path.join(BASE_DIR, "watchlist.json")
DEFAULT_WATCHLIST = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL",
    "BRK.B","LLY","AVGO","JPM","TSLA","COST","NFLX",
]

_cache      = {}          # ticker -> {"data": …, "ts": float}
_cache_lock = threading.Lock()
CACHE_TTL   = 900         # 15 minutes


# ── Watchlist ─────────────────────────────────────────────────────────────────

def load_watchlist():
    try:
        with open(WATCHLIST_FILE) as f:
            return json.load(f).get("tickers", DEFAULT_WATCHLIST[:])
    except Exception:
        return DEFAULT_WATCHLIST[:]


def save_watchlist(tickers):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump({"tickers": tickers}, f, indent=2)


# ── News sentiment ─────────────────────────────────────────────────────────────

_POS = {"beats","beat","strong","surge","soar","rally","upgrade","outperform",
        "growth","record","profit","gain","positive","bullish","raises","jumps","rises"}
_NEG = {"miss","missed","weak","fall","drop","decline","downgrade","underperform",
        "loss","cut","concern","lawsuit","investigation","bearish","layoff","warning",
        "tumbles","slumps","falls","drops","lowers"}

def _news_sentiment(ticker):
    try:
        url = (f"https://feeds.finance.yahoo.com/rss/2.0/headline"
               f"?s={ticker}&region=US&lang=en-US")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            root = ET.fromstring(r.read())
        titles = [item.findtext("title", "") for item in root.iter("item")][:5]
        if not titles:
            return "N/A", []
        pos = neg = 0
        for t in titles:
            words = set(t.lower().replace(",", "").replace(".", "").split())
            pos += len(words & _POS)
            neg += len(words & _NEG)
        if pos > neg + 1:
            sent = "Positive"
        elif neg > pos + 1:
            sent = "Negative"
        else:
            sent = "Neutral"
        return sent, titles
    except Exception:
        return "N/A", []


# ── Technical layer (reuses existing score_stock) ─────────────────────────────

def _technical(ticker):
    try:
        from stock_analysis import score_stock
        r = score_stock(ticker)
        if not r:
            return {"signal": "N/A", "score": 0, "rsi": "N/A", "macd": "N/A"}
        rsi_val = "N/A"
        rsi_raw = r["details"].get("RSI", "")
        if "RSI=" in rsi_raw:
            try:
                rsi_val = round(float(rsi_raw.split("RSI=")[1].split()[0].rstrip(",")), 1)
            except Exception:
                pass
        macd_s = r["scores"].get("MACD", 0)
        macd   = "Bullish" if macd_s == 1 else ("Bearish" if macd_s == -1 else "Neutral")
        return {"signal": r["signal"], "score": int(r["score"]),
                "rsi": rsi_val, "macd": macd}
    except Exception:
        return {"signal": "N/A", "score": 0, "rsi": "N/A", "macd": "N/A"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _f(v, dec=2):
    if v is None or v != v:   # None or NaN
        return "N/A"
    try:
        return round(float(v), dec)
    except Exception:
        return "N/A"

def _pct(v):
    if v is None or v != v:
        return "N/A"
    try:
        return f"{float(v)*100:.1f}%"
    except Exception:
        return "N/A"

def _norm(val, lo, hi, invert=False):
    """Normalise val in [lo,hi] → [0,10]; returns 5.0 on missing data."""
    if val is None or val != val:
        return 5.0
    try:
        s = (float(val) - lo) / (hi - lo) * 10
        s = max(0.0, min(10.0, s))
        return 10.0 - s if invert else s
    except Exception:
        return 5.0


# ── Main fetch ────────────────────────────────────────────────────────────────

def fetch_radar_stock(ticker):
    t    = yf.Ticker(ticker)
    info = {}
    try:
        info = t.info or {}
    except Exception:
        pass

    price    = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
    name     = info.get("shortName") or info.get("longName") or ticker

    # ── Fundamental
    pe          = info.get("trailingPE")
    fpe         = info.get("forwardPE")
    eps_growth  = info.get("earningsGrowth")
    rev_growth  = info.get("revenueGrowth")
    margin      = info.get("profitMargins")

    # ── Valuation / analyst
    target   = info.get("targetMeanPrice")
    upside   = round((target / price - 1) * 100, 1) if (target and price) else None
    analyst_buy = analyst_hold = analyst_sell = "N/A"
    try:
        rs = t.recommendations_summary
        if rs is not None and not rs.empty:
            row = rs.sort_index().iloc[-1]   # most recent period
            analyst_buy  = int(row.get("strongBuy",  0) + row.get("buy",  0))
            analyst_hold = int(row.get("hold", 0))
            analyst_sell = int(row.get("sell", 0) + row.get("strongSell", 0))
    except Exception:
        pass

    # ── Events — earnings
    earn_date = earn_days = "N/A"
    try:
        cal = t.calendar
        # cal can be dict or DataFrame depending on yfinance version
        if isinstance(cal, dict):
            ed_list = cal.get("Earnings Date", [])
        elif cal is not None and hasattr(cal, "get"):
            ed_list = cal.get("Earnings Date", [])
        elif cal is not None and not cal.empty:
            ed_list = list(cal.loc["Earnings Date"]) if "Earnings Date" in cal.index else []
        else:
            ed_list = []
        if ed_list:
            next_ed = min(
                (d.date() if hasattr(d, "date") else d) for d in ed_list if d is not None
            )
            earn_date = str(next_ed)
            earn_days = (next_ed - date.today()).days
    except Exception:
        pass

    # ── Risk
    beta      = info.get("beta")
    short_int = info.get("shortPercentOfFloat")
    w52_low   = info.get("fiftyTwoWeekLow")
    w52_high  = info.get("fiftyTwoWeekHigh")
    w52_pos   = None
    if price and w52_low and w52_high and w52_high > w52_low:
        w52_pos = round((price - w52_low) / (w52_high - w52_low) * 100, 1)

    # ── Relative strength vs SPY (30-day)
    rs_30d = None
    try:
        hist     = t.history(period="35d")["Close"]
        spy_hist = yf.Ticker("SPY").history(period="35d")["Close"]
        if len(hist) >= 20 and len(spy_hist) >= 20:
            stk_ret = (hist.iloc[-1] / hist.iloc[0] - 1) * 100
            spy_ret = (spy_hist.iloc[-1] / spy_hist.iloc[0] - 1) * 100
            rs_30d  = round(stk_ret - spy_ret, 2)
    except Exception:
        pass

    # ── Insider activity
    insider_type = insider_val = insider_days_ago = "N/A"
    try:
        ins = t.insider_transactions
        if ins is not None and not ins.empty:
            row   = ins.iloc[0]
            itype = str(row.get("Transaction", row.get("transaction", ""))).strip()
            ival  = row.get("Value", row.get("value", None))
            idate = row.get("Start Date", row.get("startDate", None))
            if idate is not None:
                if hasattr(idate, "date"):
                    idate = idate.date()
                try:
                    insider_days_ago = max(0, (date.today() - idate).days)
                except Exception:
                    pass
            il = itype.lower()
            if any(x in il for x in ("buy", "purchase", "acqui")):
                insider_type = "Buy"
            elif any(x in il for x in ("sell", "sale", "dispos")):
                insider_type = "Sell"
            else:
                insider_type = itype or "N/A"
            if ival is not None and ival == ival:  # not NaN
                try:
                    insider_val = int(float(ival))
                except Exception:
                    pass
    except Exception:
        pass

    # ── Institutional
    inst_own = info.get("heldPercentInstitutions")
    inst_qoq = None
    try:
        ih = t.institutional_holders
        if ih is not None and not ih.empty and "pctHeld" in ih.columns:
            pcts = ih["pctHeld"].dropna().astype(float).values
            if len(pcts) >= 2:
                inst_qoq = round((pcts[0] - pcts[1]) * 100, 2)
    except Exception:
        pass

    # ── Sentiment
    sentiment, headlines = _news_sentiment(ticker)

    # ── Technical
    tech = _technical(ticker)

    # ── Composite score 0–10
    tech_s  = (tech["score"] + 10) / 20 * 10

    eps_g_raw = eps_growth if isinstance(eps_growth, (int, float)) else None
    rev_g_raw = rev_growth if isinstance(rev_growth, (int, float)) else None
    mar_raw   = margin     if isinstance(margin,     (int, float)) else None
    fund_s    = _norm(eps_g_raw, -0.5, 1.0) * 0.5 + _norm(mar_raw, 0, 0.4) * 0.5

    fpe_raw   = fpe    if isinstance(fpe,    (int, float)) else None
    val_s     = _norm(upside, -20, 50) * 0.6 + _norm(fpe_raw, 50, 5, invert=True) * 0.4

    sent_map  = {"Positive": 8.0, "Neutral": 5.0, "Negative": 2.0, "N/A": 5.0}
    sent_s    = sent_map.get(sentiment, 5.0)

    ins_s     = 8.0 if insider_type == "Buy" else (3.0 if insider_type == "Sell" else 5.0)
    inst_s    = _norm(inst_qoq, -5.0, 5.0) if isinstance(inst_qoq, float) else 5.0
    inside_s  = ins_s * 0.6 + inst_s * 0.4

    beta_raw  = beta if isinstance(beta, (int, float)) else None
    risk_s    = _norm(beta_raw, 2.5, 0.3, invert=True)   # lower beta → less risk → higher score

    composite = (
        tech_s   * 0.25 +
        fund_s   * 0.20 +
        val_s    * 0.20 +
        sent_s   * 0.15 +
        inside_s * 0.10 +
        risk_s   * 0.10
    )
    composite = round(max(0.0, min(10.0, composite)), 2)

    upside_str = f"{upside:+.1f}%" if upside is not None else "N/A"
    rs_str     = f"{rs_30d:+.1f}%" if rs_30d  is not None else "N/A"

    ins_val_fmt = "N/A"
    if isinstance(insider_val, int):
        ins_val_fmt = f"${abs(insider_val):,}" if insider_val else "N/A"

    return {
        "ticker":       ticker,
        "name":         name,
        "price":        _f(price, 2),
        "composite":    composite,
        "updated":      datetime.now().strftime("%H:%M:%S"),
        # technical
        "signal":       tech["signal"],
        "tech_score":   tech["score"],
        "rsi":          tech["rsi"],
        "macd":         tech["macd"],
        # fundamental
        "pe":           _f(pe, 1),
        "fpe":          _f(fpe, 1),
        "eps_growth":   _pct(eps_growth),
        "rev_growth":   _pct(rev_growth),
        "margin":       _pct(margin),
        # valuation
        "target":       _f(target, 2),
        "upside":       upside_str,
        "upside_raw":   upside,
        "analyst_buy":  analyst_buy,
        "analyst_hold": analyst_hold,
        "analyst_sell": analyst_sell,
        # events
        "earn_date":    earn_date,
        "earn_days":    earn_days,
        # risk
        "beta":         _f(beta, 2),
        "short_int":    _pct(short_int),
        "w52_pos":      f"{w52_pos:.0f}%" if w52_pos is not None else "N/A",
        "w52_pos_raw":  w52_pos,
        # relative strength
        "rs_30d":       rs_str,
        "rs_30d_raw":   rs_30d,
        # insider
        "insider_type": insider_type,
        "insider_val":  ins_val_fmt,
        "insider_days": insider_days_ago,
        # institutional
        "inst_own":     _pct(inst_own),
        "inst_qoq":     f"{inst_qoq:+.2f}%" if isinstance(inst_qoq, float) else "N/A",
        # sentiment
        "sentiment":    sentiment,
        "headlines":    headlines,
    }


def get_radar_stock(ticker, force=False):
    ticker = ticker.upper().strip()
    with _cache_lock:
        cached = _cache.get(ticker)
        if cached and not force and (time.time() - cached["ts"]) < CACHE_TTL:
            return cached["data"]
    data = fetch_radar_stock(ticker)
    with _cache_lock:
        _cache[ticker] = {"data": data, "ts": time.time()}
    return data


def get_all_radar(tickers, force=False):
    results = []
    for ticker in tickers:
        try:
            results.append(get_radar_stock(ticker, force=force))
        except Exception as e:
            results.append({
                "ticker": ticker, "composite": 0, "error": str(e),
                "signal": "N/A", "price": "N/A",
            })
    return results
