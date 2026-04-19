#!/usr/bin/env python3
"""Radar Screen — server-side data fetching for watchlist stocks."""

import json, os, ssl, time, threading
from datetime import datetime, date
import urllib.request
import xml.etree.ElementTree as ET

_SSL_CTX = ssl._create_unverified_context()

import yfinance as yf

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_FILE = os.path.join(BASE_DIR, "watchlist.json")
DEFAULT_WATCHLIST = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL",
    "BRK.B","LLY","AVGO","JPM","TSLA","COST","NFLX",
]

_cache      = {}          # ticker -> {"data": …, "ts": float}
_cache_lock = threading.Lock()
CACHE_TTL        = 900    # 15 minutes (in-memory freshness check)
CACHE_FILE       = os.path.join(BASE_DIR, "radar_cache.json")
BG_REFRESH_SECS  = 1800   # 30 minutes


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


# ── File cache ────────────────────────────────────────────────────────────────

def _load_file_cache():
    """Populate in-memory cache from disk; treat loaded entries as fresh."""
    try:
        with open(CACHE_FILE) as f:
            saved = json.load(f)
        now = time.time()
        with _cache_lock:
            for ticker, entry in saved.items():
                # Reset ts to now so entries are served without re-fetching
                _cache[ticker] = {"data": entry["data"], "ts": now}
    except Exception:
        pass


def _save_file_cache():
    """Write current in-memory cache to disk."""
    try:
        with _cache_lock:
            snapshot = dict(_cache)
        with open(CACHE_FILE, "w") as f:
            json.dump(snapshot, f)
    except Exception:
        pass


def _bg_refresh_loop():
    """Background daemon: refresh all watchlist tickers every 30 minutes."""
    while True:
        time.sleep(BG_REFRESH_SECS)
        try:
            for ticker in load_watchlist():
                try:
                    data = fetch_radar_stock(ticker)
                    with _cache_lock:
                        _cache[ticker] = {"data": data, "ts": time.time()}
                except Exception:
                    pass
            _save_file_cache()
        except Exception:
            pass


_load_file_cache()
threading.Thread(target=_bg_refresh_loop, daemon=True).start()


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
        with urllib.request.urlopen(req, timeout=6, context=_SSL_CTX) as r:
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
            # Transaction column is often empty; Text field is more reliable
            itext = str(row.get("Text", row.get("text", ""))).lower()
            itype = str(row.get("Transaction", row.get("transaction", ""))).lower()
            combined = itext + " " + itype
            ival  = row.get("Value", row.get("value", None))
            idate = row.get("Start Date", row.get("startDate", None))
            if idate is not None:
                if hasattr(idate, "date"):
                    idate = idate.date()
                try:
                    insider_days_ago = max(0, (date.today() - idate).days)
                except Exception:
                    pass
            if any(x in combined for x in ("purchase", "acqui", "bought")):
                insider_type = "Buy"
            elif any(x in combined for x in ("sale", "sell", "sold", "dispos")):
                insider_type = "Sell"
            else:
                insider_type = "N/A"
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

    # ── Hybrid Score system (0–10 each) ──────────────────────────────────────
    def _sig(s):
        if s <= 3.5:  return "Sell"
        if s <= 6.4:  return "Neutral"
        return "Buy"

    # TECH SCORE (50% weight) — existing 10-indicator logic, normalised to 0-10
    score_tech = round((tech["score"] + 10) / 20 * 10, 2)

    # FUNDAMENTAL SCORE (30% weight)
    # Components: analyst upside (30%), fwd P/E vs ~22 mkt avg (25%),
    #             revenue growth (25%), profit margin (20%)
    fpe_raw   = fpe        if isinstance(fpe,        (int, float)) else None
    rev_g_raw = rev_growth if isinstance(rev_growth, (int, float)) else None
    mar_raw   = margin     if isinstance(margin,     (int, float)) else None
    score_fund = round(max(0.0, min(10.0, (
        _norm(upside,    -20,  50)             * 0.30 +
        _norm(fpe_raw,     8,  40, invert=True) * 0.25 +   # lower fwd P/E = better
        _norm(rev_g_raw, -0.2,  0.5)           * 0.25 +
        _norm(mar_raw,    0,    0.4)            * 0.20
    ))), 2)

    # RISK SCORE (20% weight) — higher score = LOWER risk
    # Components: earnings proximity (40%), beta (35%), short interest (25%)
    earn_days_num = earn_days if isinstance(earn_days, int) else None
    if earn_days_num is None:       earn_risk = 6.0
    elif earn_days_num < 7:         earn_risk = 2.0
    elif earn_days_num < 14:        earn_risk = 4.0
    elif earn_days_num < 30:        earn_risk = 6.5
    else:                           earn_risk = 9.0

    beta_raw  = beta      if isinstance(beta,      (int, float)) else None
    short_raw = short_int if isinstance(short_int, (int, float)) else None
    score_risk = round(max(0.0, min(10.0, (
        earn_risk                             * 0.40 +
        _norm(beta_raw,  0, 2.5, invert=True) * 0.35 +   # lower beta = lower risk
        _norm(short_raw, 0, 0.30, invert=True) * 0.25    # lower short % = lower risk
    ))), 2)

    # HYBRID TOTAL
    score_hybrid = round(
        score_tech * 0.50 +
        score_fund * 0.30 +
        score_risk * 0.20,
        2
    )
    composite = score_hybrid   # keep composite alias for summary cards

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
        # hybrid scores
        "score_tech":   score_tech,   "sig_tech":   _sig(score_tech),
        "score_fund":   score_fund,   "sig_fund":   _sig(score_fund),
        "score_risk":   score_risk,   "sig_risk":   _sig(score_risk),
        "score_hybrid": score_hybrid, "sig_hybrid": _sig(score_hybrid),
        "updated":      datetime.now().strftime("%H:%M:%S"),
        # technical detail
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
    _save_file_cache()
    return results
