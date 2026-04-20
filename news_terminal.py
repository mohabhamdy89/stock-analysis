#!/usr/bin/env python3
"""News Terminal — RSS fetching for Hot News, Market News, and Portfolio News panels."""

import ssl, time, threading, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

_SSL_CTX = ssl._create_unverified_context()

_POS = {
    "beats","beat","strong","surge","soar","rally","upgrade","outperform",
    "growth","record","profit","gain","positive","bullish","raises","jumps",
    "rises","boom","boosted","climbs","optimistic","tops","breakthrough",
}
_NEG = {
    "miss","missed","weak","fall","drop","decline","downgrade","underperform",
    "loss","cut","concern","lawsuit","investigation","bearish","layoff","warning",
    "tumbles","slumps","falls","drops","lowers","crash","crisis","fears",
    "plunges","recession","disappoints","downturn","warns","volatile",
}


def _sentiment(title):
    words = set(title.lower().replace(",", "").replace(".", "").split())
    pos   = len(words & _POS)
    neg   = len(words & _NEG)
    if pos > neg: return "positive"
    if neg > pos: return "negative"
    return "neutral"


def _time_ago(pub_date_str):
    if not pub_date_str:
        return ""
    try:
        dt   = parsedate_to_datetime(pub_date_str)
        now  = datetime.now(timezone.utc)
        secs = int((now - dt).total_seconds())
        if secs < 60:    return "just now"
        if secs < 3600:  return f"{secs // 60}m ago"
        if secs < 86400: return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"
    except Exception:
        return ""


def _fetch_rss(symbol, count=10):
    """Fetch Yahoo Finance RSS headlines for one symbol."""
    try:
        url = (f"https://feeds.finance.yahoo.com/rss/2.0/headline"
               f"?s={symbol}&region=US&lang=en-US")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8, context=_SSL_CTX) as r:
            root = ET.fromstring(r.read())
        items = []
        for item in root.iter("item"):
            title    = item.findtext("title",   "").strip()
            source   = item.findtext("source",  "").strip()
            pub_date = item.findtext("pubDate", "").strip()
            if not title:
                continue
            items.append({
                "title":     title,
                "source":    source or "Yahoo Finance",
                "time_ago":  _time_ago(pub_date),
                "sentiment": _sentiment(title),
            })
            if len(items) >= count:
                break
        return items
    except Exception:
        return []


# ── Three panel fetchers ───────────────────────────────────────────────────────

def fetch_hot_news():
    """Top 5 breaking market headlines from ^GSPC, ^IXIC, ^DJI — deduplicated."""
    seen, out = set(), []
    for sym in ["^GSPC", "^IXIC", "^DJI"]:
        for item in _fetch_rss(sym, count=8):
            if item["title"] not in seen:
                seen.add(item["title"])
                out.append(item)
    return out[:5]


def fetch_market_news():
    """Macro headlines from GLD, USO, BTC-USD, ^TNX — deduplicated, top 5."""
    seen, out = set(), []
    for sym in ["GLD", "USO", "BTC-USD", "^TNX"]:
        for item in _fetch_rss(sym, count=6):
            if item["title"] not in seen:
                seen.add(item["title"])
                out.append(item)
    return out[:5]


def fetch_portfolio_news(tickers):
    """Top 2 relevant headlines per portfolio ticker. Returns {ticker: [items]}."""
    result = {}
    for ticker in tickers:
        items = _fetch_rss(ticker, count=8)
        tk_l  = ticker.lower().replace("-", "")
        relevant = [
            i for i in items
            if tk_l in i["title"].lower().replace("-", "").replace(".", "")
        ]
        result[ticker] = (relevant or items)[:2]
    return result


# ── Cache ──────────────────────────────────────────────────────────────────────

_cache      = {"data": None, "ts": 0.0}
_cache_lock = threading.Lock()
NEWS_TTL    = 900  # 15 minutes


def get_all_news(tickers, force=False):
    with _cache_lock:
        if (not force and _cache["data"] is not None
                and (time.time() - _cache["ts"]) < NEWS_TTL):
            return _cache["data"]
    data = {
        "hot":       fetch_hot_news(),
        "market":    fetch_market_news(),
        "portfolio": fetch_portfolio_news(tickers),
    }
    with _cache_lock:
        _cache["data"] = data
        _cache["ts"]   = time.time()
    return data
