#!/usr/bin/env python3
"""
Mohab Capital | Daily Intelligence Brief
Goldman Sachs Morning Intelligence-style market email report.

Usage:
  python3 daily_report.py --now     → generate + send immediately
  python3 daily_report.py --save    → save HTML only (no send)
"""

import os, sys, json, time, smtplib, ssl, warnings
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

warnings.filterwarnings("ignore")

# ── Config ─────────────────────────────────────────────────────────────────────
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
SENDER_EMAIL   = "mohab2056@gmail.com"
RECEIVER_EMAIL = "mohab2056@gmail.com"
GMAIL_APP_PW   = os.getenv("GMAIL_APP_PASSWORD", "okgmkzilouegvfug")
ANTHROPIC_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
REPORT_HTML    = os.path.join(BASE_DIR, "test_report.html")

sys.path.insert(0, BASE_DIR)


# ── 1. Market Data ─────────────────────────────────────────────────────────────

def fetch_market_overview():
    import yfinance as yf
    symbols = {
        "S&P 500":   "^GSPC",
        "NASDAQ":    "^IXIC",
        "DOW":       "^DJI",
        "Russell 2K":"^RUT",
        "VIX":       "^VIX",
        "Gold":      "GC=F",
        "WTI Oil":   "CL=F",
        "10-Yr UST": "^TNX",
        "USD/EUR":   "EURUSD=X",
        "Bitcoin":   "BTC-USD",
    }
    results = {}
    for name, sym in symbols.items():
        try:
            hist = yf.Ticker(sym).history(period="5d", interval="1d")
            if hist.empty:
                continue
            last  = float(hist["Close"].iloc[-1])
            prev  = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else last
            chg   = last - prev
            chg_p = (chg / prev * 100) if prev else 0.0
            results[name] = {"price": last, "change": chg, "change_pct": chg_p, "symbol": sym}
        except Exception:
            pass
    return results


def fetch_ytd_benchmarks():
    import yfinance as yf
    year_start = f"{datetime.now().year}-01-01"
    out = {}
    for key, sym in [("sp500", "^GSPC"), ("nasdaq", "^IXIC")]:
        try:
            df = yf.download(sym, start=year_start, interval="1d",
                             progress=False, auto_adjust=True)
            if df is None or df.empty:
                continue
            if hasattr(df.columns, "get_level_values"):
                df.columns = df.columns.get_level_values(0)
            first = float(df["Close"].iloc[0])
            last  = float(df["Close"].iloc[-1])
            out[key] = round((last - first) / first * 100, 2)
        except Exception:
            pass
    return out


# ── 2. Macro News — filtered to genuine macro events ──────────────────────────

# Keywords that qualify a headline as macro-relevant
_MACRO_KEEP = {
    "fed", "federal reserve", "fomc", "powell", "rate", "interest rate",
    "inflation", "cpi", "pce", "ppi", "deflation", "gdp", "recession",
    "jobs", "payroll", "unemployment", "nonfarm", "labor",
    "tariff", "trade war", "sanction", "trade deal", "wto",
    "geopolit", "war", "conflict", "invasion", "nato", "iran", "russia",
    "ukraine", "china", "opec", "oil supply", "crude supply",
    "dollar", "euro", "yen", "yuan", "currency", "forex", "dxy",
    "treasury", "yield curve", "10-year", "bond", "debt ceiling",
    "bank crisis", "credit", "liquidity", "systemic",
    "earnings season", "gdp growth", "economic growth",
}

# Keywords that disqualify a headline (ETF picks, stock recommendations)
_MACRO_REJECT = {
    "best etf", "top etf", "etf to buy", "stock to buy", "stocks to buy",
    "best stock", "top stock", "analyst upgrade", "analyst downgrade",
    "price target", "stock pick", "dividend stock", "growth stock",
    "penny stock", "meme stock", "why i bought", "should you buy",
    "motley fool", "zacks rank",
}


def _is_macro(title: str) -> bool:
    tl = title.lower()
    if any(r in tl for r in _MACRO_REJECT):
        return False
    return any(k in tl for k in _MACRO_KEEP)


def fetch_macro_news(max_items=6):
    import urllib.request, xml.etree.ElementTree as ET, ssl as _ssl
    ctx = _ssl._create_unverified_context()
    feeds = [
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US",
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=SPY&region=US&lang=en-US",
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EVIX&region=US&lang=en-US",
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5ETNX&region=US&lang=en-US",
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=GC%3DF&region=US&lang=en-US",
    ]
    seen, all_items = set(), []
    for url in feeds:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8, context=ctx) as r:
                root = ET.fromstring(r.read())
            for el in root.iter("item"):
                title = (el.findtext("title") or "").strip()
                link  = (el.findtext("link")  or "").strip()
                pub   = (el.findtext("pubDate") or "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                all_items.append({"title": title, "link": link, "pub": pub})
        except Exception:
            pass

    # Prefer genuine macro headlines; fall back to all if not enough
    macro = [i for i in all_items if _is_macro(i["title"])]
    if len(macro) < 3:
        macro = all_items  # fallback: use everything
    return macro[:max_items]


# ── 3. Insider Activity ────────────────────────────────────────────────────────

def fetch_insider_activity(tickers):
    import yfinance as yf
    import pandas as pd
    rows = []
    cutoff = datetime.now() - timedelta(days=30)
    for tk in tickers:
        try:
            df = yf.Ticker(tk).insider_transactions
            if df is None or df.empty:
                continue
            for _, r in df.iterrows():
                try:
                    tx_type = str(r.get("Transaction", r.get("transaction", ""))).strip()
                    if not any(x in tx_type.lower() for x in ["purchase", "buy", "acquisition"]):
                        continue
                    shares = int(r.get("Shares", r.get("shares", 0)) or 0)
                    value  = float(r.get("Value", r.get("value", 0)) or 0)
                    if shares <= 0 or value <= 0:
                        continue
                    name  = str(r.get("Insider", r.get("Name", "Unknown"))).strip()
                    title = str(r.get("Position", r.get("Title", ""))).strip()
                    raw   = r.get("Date", r.get("date"))
                    if isinstance(raw, str):
                        tx_date = pd.to_datetime(raw).to_pydatetime().replace(tzinfo=None)
                    elif hasattr(raw, "to_pydatetime"):
                        tx_date = raw.to_pydatetime().replace(tzinfo=None)
                    else:
                        tx_date = datetime.now()
                    if tx_date < cutoff:
                        continue
                    rows.append({
                        "ticker": tk,
                        "name":   name[:28],
                        "title":  title[:24],
                        "shares": shares,
                        "value":  value,
                        "date":   tx_date.strftime("%b %d"),
                        "signal": "BUY",
                    })
                except Exception:
                    continue
        except Exception:
            pass
    rows.sort(key=lambda x: x["value"], reverse=True)
    return rows[:8]


def detect_cluster_buys(rows):
    from collections import Counter
    tally = Counter(r["ticker"] for r in rows)
    return {tk: n for tk, n in tally.items() if n >= 2}


# ── 4. Portfolio ───────────────────────────────────────────────────────────────

def fetch_portfolio():
    try:
        from stock_analysis import (read_portfolio_sheet, enrich_with_portfolio,
                                    score_stock, fetch_benchmark_returns)
        sheet_p, positions, cash, pnl_pct = read_portfolio_sheet()
        if not sheet_p:
            return [], {}, 0.0, None, None, {}
        tickers = list(positions.keys())
        raw_results = []
        for tk in tickers:
            r = score_stock(tk)
            if r:
                raw_results.append(r)
        enriched, totals = enrich_with_portfolio(raw_results, positions, cash, pnl_pct)
        bench = fetch_benchmark_returns()
        return enriched, positions, cash, pnl_pct, bench, totals
    except Exception as e:
        print(f"  Portfolio fetch error: {e}")
        return [], {}, 0.0, None, None, {}


# ── 5. Radar / Watchlist ───────────────────────────────────────────────────────

def fetch_radar_top(n=5):
    import yfinance as yf
    cache_path    = os.path.join(BASE_DIR, "radar_cache.json")
    watchlist_path = os.path.join(BASE_DIR, "watchlist.json")
    try:
        tickers = json.load(open(watchlist_path))["tickers"]
    except Exception:
        tickers = ["AAPL","MSFT","NVDA","AMZN","META","GOOGL","JPM","TSLA","NFLX","AVGO"]
    try:
        cache = json.load(open(cache_path))
    except Exception:
        cache = {}

    stocks = []
    for tk in tickers:
        try:
            entry  = cache.get(tk, {}).get("data", {})
            score  = float(entry.get("score_hybrid") or entry.get("composite") or 5.0)
            sig    = str(entry.get("sig_hybrid") or entry.get("signal") or "Neutral")
            price  = entry.get("price")
            if price in (None, "N/A", ""):
                info  = yf.Ticker(tk).info
                price = info.get("regularMarketPrice") or info.get("currentPrice") or 0
            upside = entry.get("upside", "N/A")
            earn   = entry.get("earn_date", "N/A")
            note   = ""
            if entry.get("macd") == "Bullish":
                note = "MACD Bullish"
            elif entry.get("rsi") not in (None, "N/A") and isinstance(entry.get("rsi"), (int, float)):
                rsi_v = float(entry["rsi"])
                if rsi_v < 35:
                    note = "RSI Oversold"
                elif rsi_v > 70:
                    note = "RSI Overbought"
            stocks.append({
                "ticker":   tk,
                "score":    round(score, 2),
                "signal":   sig,
                "price":    price,
                "upside":   upside,
                "earnings": earn,
                "note":     note,
            })
        except Exception:
            pass
    stocks.sort(key=lambda x: x["score"], reverse=True)
    return stocks[:n]


# ── 6. AI Analysis (Claude API) ───────────────────────────────────────────────

def _call_claude(prompt, max_tokens=600):
    if not ANTHROPIC_KEY:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        print(f"  Claude API error: {e}")
        return None


def generate_executive_summary(market, benchmarks, portfolio_totals, insider_rows):
    sp_chg   = market.get("S&P 500", {}).get("change_pct", 0.0)
    vix      = market.get("VIX", {}).get("price", 0.0)
    gold_chg = market.get("Gold", {}).get("change_pct", 0.0)
    oil_chg  = market.get("WTI Oil", {}).get("change_pct", 0.0)
    tsy_px   = market.get("10-Yr UST", {}).get("price", 0.0)
    sp_ytd   = benchmarks.get("sp500", 0.0)
    port_ytd = (portfolio_totals or {}).get("sheet_pnl_pct") if portfolio_totals else None
    n_insider = len(insider_rows)

    if ANTHROPIC_KEY:
        port_line = (f"Portfolio YTD: {port_ytd:+.1f}%" if port_ytd is not None
                     else "Portfolio data unavailable")
        bps_line  = ""
        if port_ytd is not None and sp_ytd:
            bps = int(round((port_ytd - sp_ytd) * 100))
            bps_line = (f"Portfolio outperforming S&P 500 by {abs(bps)}bps YTD."
                        if bps > 0 else f"Portfolio underperforming S&P 500 by {abs(bps)}bps YTD.")
        insider_line = (f"{n_insider} open-market insider purchase{'s' if n_insider != 1 else ''} "
                        "detected across holdings."
                        if n_insider > 0 else "No material insider transactions today.")
        prompt = (
            "You are a senior market strategist at Goldman Sachs. "
            "Write a 3-sentence executive summary for a professional daily intelligence brief. "
            "Lead with the single most important market development. "
            "Reference specific numbers. No emojis. No bullet points. Plain prose only.\n\n"
            f"Market snapshot:\n"
            f"- S&P 500 prior session: {sp_chg:+.2f}%\n"
            f"- VIX: {vix:.1f} ({'elevated' if vix > 20 else 'low'})\n"
            f"- 10-Year Treasury: {tsy_px:.2f}%\n"
            f"- Gold: {gold_chg:+.2f}%, WTI Oil: {oil_chg:+.2f}%\n"
            f"- S&P 500 YTD: {sp_ytd:+.1f}%\n"
            f"- {port_line}\n"
            f"- {bps_line}\n"
            f"- {insider_line}\n\n"
            "Write exactly 3 sentences."
        )
        result = _call_claude(prompt, max_tokens=250)
        if result:
            return result

    # Fallback
    mood   = "cautious" if vix > 20 else ("risk-on" if sp_chg > 0.5 else "mixed")
    sp_str = f"{sp_chg:+.2f}%"
    lines  = [
        f"Equity markets closed {sp_str} in the prior session with VIX at {vix:.1f}, "
        f"reflecting a {mood} tone among institutional participants.",
    ]
    if port_ytd is not None and sp_ytd:
        bps = int(round((port_ytd - sp_ytd) * 100))
        lines.append(
            f"Portfolio stands {port_ytd:+.1f}% YTD versus S&P 500 at {sp_ytd:+.1f}%, "
            + (f"outperforming by {abs(bps)}bps." if bps > 0 else f"underperforming by {abs(bps)}bps.")
        )
    if n_insider > 0:
        lines.append(
            f"{n_insider} open-market insider purchase{'s' if n_insider != 1 else ''} "
            "detected — a historically constructive signal."
        )
    return " ".join(lines)


def generate_market_narrative(market, news_items, portfolio_enriched,
                               portfolio_totals, bench, radar_stocks):
    """2-paragraph Goldman Sachs-style narrative referencing specific data."""
    if not ANTHROPIC_KEY:
        return None

    sp_chg   = market.get("S&P 500", {}).get("change_pct", 0.0)
    sp_price = market.get("S&P 500", {}).get("price", 0.0)
    vix      = market.get("VIX", {}).get("price", 0.0)
    gold_chg = market.get("Gold", {}).get("change_pct", 0.0)
    oil_chg  = market.get("WTI Oil", {}).get("change_pct", 0.0)
    tsy      = market.get("10-Yr UST", {}).get("price", 0.0)
    sp_ytd   = (bench or {}).get("sp500", {}).get("return_ytd", 0.0) if bench else 0.0

    port_ytd = (portfolio_totals or {}).get("sheet_pnl_pct") or 0.0
    port_val = (portfolio_totals or {}).get("total_portfolio_value") or 0.0
    tot_pnl  = (portfolio_totals or {}).get("total_unrealized_pnl") or 0.0

    headlines = "\n".join(f"- {i['title']}" for i in news_items[:5])

    holdings_summary = ""
    if portfolio_enriched:
        top = sorted(portfolio_enriched, key=lambda x: x.get("market_value", 0), reverse=True)[:5]
        parts = []
        for h in top:
            sig    = h.get("signal", "")
            # Recompute P&L % consistently from live price
            shares    = float(h.get("shares", 0))
            cost_ps   = float(h.get("cost_basis_ps", 0))
            price     = float(h.get("price", 0))
            total_cost = shares * cost_ps
            mv         = shares * price
            pnl_p = ((mv - total_cost) / total_cost * 100) if total_cost else 0.0
            parts.append(f"{h['ticker']} ({sig}, {pnl_p:+.1f}%)")
        holdings_summary = ", ".join(parts)

    radar_summary = ", ".join(
        f"{r['ticker']} score {r['score']}/10" for r in radar_stocks[:3]
    )

    prompt = (
        "You are a senior portfolio strategist at Goldman Sachs writing the morning intelligence brief. "
        "Write exactly 2 paragraphs of professional market narrative. Rules:\n"
        "- Reference specific numbers from the data below\n"
        "- Paragraph 1: Connect today's macro environment to what it means for risk assets broadly\n"
        "- Paragraph 2: Identify the single biggest risk and biggest opportunity for the portfolio today, "
        "naming specific holdings or watchlist names\n"
        "- Sound like a senior analyst, not a bot\n"
        "- No emojis. No headers. No bullet points. Plain prose only.\n\n"
        f"MARKET DATA:\n"
        f"S&P 500: {sp_price:,.0f} ({sp_chg:+.2f}% session), YTD {sp_ytd:+.1f}%\n"
        f"VIX: {vix:.1f} | 10-Yr Treasury: {tsy:.2f}% | Gold: {gold_chg:+.2f}% | WTI: {oil_chg:+.2f}%\n\n"
        f"TOP MACRO HEADLINES:\n{headlines}\n\n"
        f"PORTFOLIO: ${port_val:,.0f} total, {port_ytd:+.1f}% YTD, "
        f"unrealized P&L ${tot_pnl:+,.0f}\n"
        f"Top holdings: {holdings_summary}\n\n"
        f"WATCHLIST TOP SCORES: {radar_summary}\n\n"
        "Write 2 paragraphs now."
    )
    return _call_claude(prompt, max_tokens=500)


def generate_macro_analysis(headline, portfolio_tickers):
    """Returns dict with IMPACT, SECTORS, ANALYSIS (4 sentences), RELEVANCE."""
    if ANTHROPIC_KEY:
        tickers_str = ", ".join(portfolio_tickers[:10]) if portfolio_tickers else "none specified"
        prompt = (
            "You are a senior market analyst at JP Morgan. "
            f"Analyze this macro headline for a professional investor with these holdings: {tickers_str}\n\n"
            f"Headline: \"{headline}\"\n\n"
            "Respond in this EXACT format — no extra text, no markdown:\n\n"
            "IMPACT: [BULLISH / BEARISH / NEUTRAL]\n"
            "SECTORS: [up to 3 sectors, comma-separated]\n"
            "RELEVANCE: [HIGH / MEDIUM]\n"
            "ANALYSIS: [4 sentences:\n"
            "  Sentence 1 — What happened (the objective facts from the headline)\n"
            "  Sentence 2 — Why this matters for financial markets right now\n"
            f"  Sentence 3 — Specific impact on holdings ({tickers_str}) or the broader portfolio\n"
            "  Sentence 4 — What to watch for next / the key risk or catalyst ahead]"
        )
        result = _call_claude(prompt, max_tokens=300)
        if result:
            parsed = {}
            # Split off the ANALYSIS block (it may span multiple lines)
            lines = result.strip().splitlines()
            analysis_lines = []
            in_analysis = False
            for line in lines:
                if line.upper().startswith("ANALYSIS:"):
                    in_analysis = True
                    rest = line[len("ANALYSIS:"):].strip()
                    if rest:
                        analysis_lines.append(rest)
                elif in_analysis:
                    analysis_lines.append(line.strip())
                elif ":" in line and not in_analysis:
                    k, v = line.split(":", 1)
                    parsed[k.strip().upper()] = v.strip()
            if analysis_lines:
                parsed["ANALYSIS"] = " ".join(a for a in analysis_lines if a)
            if "IMPACT" in parsed:
                return parsed

    # Fallback heuristics
    h   = headline.lower()
    neg = sum(1 for w in {"fall","drop","decline","cut","warn","weak","miss","slump","crash"} if w in h)
    pos = sum(1 for w in {"rise","gain","beat","surge","strong","upgrade","rally","growth","jump"} if w in h)
    impact    = "BULLISH" if pos > neg else ("BEARISH" if neg > pos else "NEUTRAL")
    relevance = "HIGH" if any(x in h for x in ["fed","rate","inflation","gdp","jobs","tariff","war"]) else "MEDIUM"
    sector = "Broad Market"
    if any(x in h for x in ["tech","ai","chip","nvidia","apple","microsoft","software"]):
        sector = "Technology"
    elif any(x in h for x in ["bank","fed","rate","treasury","yield","credit"]):
        sector = "Financials"
    elif any(x in h for x in ["oil","energy","gas","crude","opec"]):
        sector = "Energy"
    return {
        "IMPACT":    impact,
        "SECTORS":   sector,
        "ANALYSIS":  (
            f"This development reflects ongoing uncertainty in macro conditions. "
            f"Markets are likely to reprice risk assets in response. "
            f"Portfolio holdings with rate or commodity sensitivity may see near-term volatility. "
            f"Watch for follow-through in the next session and any central bank commentary."
        ),
        "RELEVANCE": relevance,
    }


# ── 7. HTML Builder ────────────────────────────────────────────────────────────

NAVY    = "#0B1F3A"
NAVY_LT = "#1a3256"
WHITE   = "#FFFFFF"
GRAY_LT = "#F5F7FA"
GRAY    = "#6B7280"
BORDER  = "#D1D5DB"
GREEN   = "#16A34A"
RED     = "#DC2626"
GOLD    = "#B45309"


def _fmt_price(v):
    if v is None:
        return "N/A"
    try:
        v = float(v)
        if v == 0:
            return "N/A"
        return f"${v:,.2f}" if v >= 1 else f"${v:.4f}"
    except Exception:
        return "N/A"


def _sig_badge(sig):
    sig = str(sig).upper().strip()
    styles = {
        "STRONG BUY":  (GREEN,    "#DCFCE7"),
        "BUY":         ("#15803D","#D1FAE5"),
        "NEUTRAL":     (GOLD,     "#FEF3C7"),
        "SELL":        ("#EA580C","#FFEDD5"),
        "STRONG SELL": (RED,      "#FEE2E2"),
    }
    canonical = {
        "STRONGBUY": "STRONG BUY", "STRONG BUY": "STRONG BUY",
        "BUY": "BUY",
        "NEUTRAL": "NEUTRAL",
        "SELL": "SELL",
        "STRONGSELL": "STRONG SELL", "STRONG SELL": "STRONG SELL",
    }
    key = canonical.get(sig.replace(" ", ""), "NEUTRAL")
    fg, bg = styles.get(key, (GRAY, "#F3F4F6"))
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
        f'font-size:10px;font-weight:700;letter-spacing:.5px;'
        f'color:{fg};background:{bg};border:1px solid {fg}40">{key}</span>'
    )


def _impact_badge(impact):
    c = {"BULLISH": GREEN, "BEARISH": RED, "NEUTRAL": GOLD}.get(impact.upper(), GRAY)
    return (
        f'<span style="font-size:10px;font-weight:700;letter-spacing:.5px;'
        f'color:{c};padding:2px 6px;border:1px solid {c};border-radius:3px">'
        f'{impact.upper()}</span>'
    )


def _dot(filled):
    return (f'<span style="color:{GREEN};font-size:12px">&#9679;</span>'
            if filled else
            f'<span style="color:{BORDER};font-size:12px">&#9675;</span>')


def _css():
    return """<style>
* { box-sizing: border-box; }
body { margin: 0; padding: 0; background: #E9EDF2; }
table { border-collapse: collapse; }
a { color: #1a3256; }
@media only screen and (max-width: 600px) {
  .wrapper { width: 100% !important; }
  .hide-mobile { display: none !important; }
}
</style>"""


def _section_header(title, subtitle=""):
    sub = (
        f'<div style="font-size:11px;color:#93C5FD;margin-top:3px;'
        f'opacity:.75;font-style:italic">{subtitle}</div>'
        if subtitle else ""
    )
    return (
        f'<div style="background:{NAVY};padding:12px 20px">'
        f'<div style="font-size:10px;font-weight:700;letter-spacing:2px;'
        f'color:#93C5FD;text-transform:uppercase">{title}</div>'
        f'{sub}</div>'
    )


def build_html(summary_text, market_narrative,
               market, news_items, macro_analyses,
               insider_rows, cluster_buys,
               portfolio_enriched, portfolio_totals, bench,
               radar_stocks):

    now      = datetime.now()
    date_hdr = now.strftime("%A, %B %d %Y")
    time_hdr = "New York Pre-Market" if now.hour < 13 else "End of Day"
    gen_ts   = now.strftime("%Y-%m-%d %H:%M:%S UTC")

    def wrap(inner):
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
{_css()}
</head>
<body style="margin:0;padding:20px 0;background:#E9EDF2;
  font-family:Arial,Helvetica,'Helvetica Neue',sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" role="presentation">
<tr><td align="center">
<table class="wrapper" width="680" cellpadding="0" cellspacing="0"
  style="max-width:680px;width:100%" role="presentation">
{inner}
</table>
</td></tr>
</table>
</body>
</html>"""

    rows = ""

    # ── HEADER ───────────────────────────────────────────────────────────────
    rows += f"""
<tr><td>
<div style="background:{NAVY};padding:28px 32px 20px">
  <div style="font-size:11px;font-weight:700;letter-spacing:3px;
    color:#93C5FD;margin-bottom:6px">MOHAB CAPITAL</div>
  <div style="font-size:22px;font-weight:700;color:{WHITE};letter-spacing:.5px;line-height:1.2">
    Daily Intelligence Brief</div>
  <div style="margin-top:12px;border-top:1px solid #1E3A5F;padding-top:12px">
    <span style="font-size:11px;color:#6B8CAE">{date_hdr} &nbsp;|&nbsp; {time_hdr}
    &nbsp;&nbsp;&nbsp; Powered by Claude AI</span>
  </div>
</div>
</td></tr>
"""

    # ── MARKET TICKER BAR ─────────────────────────────────────────────────────
    short_map = {
        "S&P 500":"SPX","NASDAQ":"NDX","DOW":"DJIA","Russell 2K":"RUT",
        "VIX":"VIX","Gold":"GOLD","WTI Oil":"OIL","10-Yr UST":"10Y",
        "USD/EUR":"EUR","Bitcoin":"BTC",
    }
    ticker_cells = ""
    for name, d in market.items():
        p    = d.get("price", 0.0)
        chg  = d.get("change_pct", 0.0)
        col  = GREEN if chg >= 0 else RED
        sign = "+" if chg >= 0 else ""
        short = short_map.get(name, name[:4])
        fmt_p = f"{p:,.0f}" if p > 100 else f"{p:.2f}"
        ticker_cells += (
            f'<td style="padding:8px 10px;border-right:1px solid #E5E7EB;'
            f'white-space:nowrap;vertical-align:top">'
            f'<div style="font-size:8px;font-weight:700;letter-spacing:1px;color:{GRAY}">{short}</div>'
            f'<div style="font-size:12px;font-weight:700;color:#111827">{fmt_p}</div>'
            f'<div style="font-size:10px;font-weight:600;color:{col}">{sign}{chg:.2f}%</div>'
            f'</td>'
        )

    rows += f"""
<tr><td>
<div style="background:{WHITE};border-bottom:3px solid {NAVY}">
<table width="100%" cellpadding="0" cellspacing="0">
<tr style="background:{GRAY_LT}">{ticker_cells}</tr>
</table>
</div>
</td></tr>
"""

    # ── EXECUTIVE SUMMARY ─────────────────────────────────────────────────────
    rows += f"""
<tr><td style="padding-top:20px">
{_section_header("EXECUTIVE SUMMARY", "AI-generated | 3-sentence brief")}
<div style="background:{WHITE};padding:20px 24px;border:1px solid {BORDER};border-top:none">
  <div style="font-size:14px;line-height:1.8;color:#1F2937;font-style:italic">
    {summary_text}
  </div>
</div>
</td></tr>
"""

    # ── MARKET NARRATIVE ─────────────────────────────────────────────────────
    if market_narrative:
        # Split into paragraphs
        paras = [p.strip() for p in market_narrative.split("\n\n") if p.strip()]
        para_html = "".join(
            f'<p style="margin:0 0 14px 0;font-size:13px;line-height:1.8;color:#1F2937">{p}</p>'
            for p in paras
        )
        rows += f"""
<tr><td style="padding-top:20px">
{_section_header("MARKET NARRATIVE", "Goldman Sachs-style morning brief — written by Claude AI")}
<div style="background:{WHITE};padding:20px 24px;border:1px solid {BORDER};border-top:none">
  {para_html}
</div>
</td></tr>
"""

    # ── SECTION 1: MACRO ──────────────────────────────────────────────────────
    rows += f"""
<tr><td style="padding-top:20px">
{_section_header("MARKET-MOVING DEVELOPMENTS",
                 "Macro events with portfolio impact — filtered & analyzed by AI")}
<div style="background:{WHITE};border:1px solid {BORDER};border-top:none">
"""
    for i, (item, analysis) in enumerate(zip(news_items, macro_analyses)):
        bg       = WHITE if i % 2 == 0 else GRAY_LT
        impact   = analysis.get("IMPACT", "NEUTRAL")
        sectors  = analysis.get("SECTORS", "Broad Market")
        ai_text  = analysis.get("ANALYSIS", "")
        relevance = analysis.get("RELEVANCE", "MEDIUM")
        rel_dots = (
            _dot(True) + "&nbsp;" + _dot(True) + "&nbsp;HIGH"
            if relevance == "HIGH"
            else _dot(True) + "&nbsp;" + _dot(False) + "&nbsp;MEDIUM"
        )

        pub = item.get("pub", "")
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(pub)
            mins = int((datetime.now(dt.tzinfo) - dt).total_seconds() / 60)
            pub_str = (f"{mins}m ago" if mins < 120
                       else f"{mins//60}h ago" if mins < 1440
                       else dt.strftime("%b %d"))
        except Exception:
            pub_str = pub[:16] if pub else ""

        rows += f"""
  <div style="padding:16px 20px;background:{bg};border-bottom:1px solid {BORDER}">
    <div style="font-size:13px;font-weight:700;color:#111827;line-height:1.4;
      margin-bottom:5px">{item['title']}</div>
    <div style="font-size:10px;color:{GRAY};margin-bottom:10px">
      Yahoo Finance &nbsp;&middot;&nbsp; {pub_str}
    </div>
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:10px">
    <tr>
      <td style="font-size:10px;color:{GRAY}">
        <span style="font-weight:700;color:#374151">Impact:</span>&nbsp;
        {_impact_badge(impact)}&nbsp;
        <span style="color:{GRAY}">for {sectors}</span>
      </td>
      <td style="font-size:10px;color:{GRAY};text-align:right;white-space:nowrap">
        <span style="font-weight:700;color:#374151">Relevance:</span>&nbsp;{rel_dots}
      </td>
    </tr>
    </table>
    <div style="font-size:12px;color:#374151;line-height:1.7;
      padding:10px 14px;background:{'#F0F7FF' if i % 2 == 0 else '#EBF4FF'};
      border-left:3px solid #3B82F6;border-radius:0 4px 4px 0">{ai_text}</div>
  </div>
"""
    rows += "</div></td></tr>\n"

    # ── SECTION 2: INSIDER ACTIVITY ───────────────────────────────────────────
    rows += f"""
<tr><td style="padding-top:20px">
{_section_header("INSTITUTIONAL & INSIDER SIGNALS",
                 "Open-market purchases by C-suite executives — last 30 days")}
<div style="background:{WHITE};border:1px solid {BORDER};border-top:none">
"""
    for tk, count in cluster_buys.items():
        combined = sum(r["value"] for r in insider_rows if r["ticker"] == tk)
        rows += (
            f'<div style="background:#FFFBEB;border-left:4px solid {GOLD};'
            f'padding:12px 20px;margin:8px;border-radius:0 4px 4px 0">'
            f'<div style="font-size:11px;font-weight:700;color:{GOLD};letter-spacing:1px;'
            f'margin-bottom:3px">CLUSTER BUY DETECTED &mdash; {tk}</div>'
            f'<div style="font-size:11px;color:#92400E">'
            f'{count} executives purchased shares in the past 30 days. '
            f'Combined value: ${combined/1e6:.1f}M. Historically bullish signal.</div>'
            f'</div>'
        )

    if insider_rows:
        rows += """
  <table width="100%" cellpadding="0" cellspacing="0">
  <thead><tr style="background:#F9FAFB;border-bottom:2px solid #E5E7EB">
    <th style="padding:10px 14px;font-size:9px;font-weight:700;letter-spacing:1.5px;
      color:#6B7280;text-align:left;text-transform:uppercase">TICKER</th>
    <th style="padding:10px 14px;font-size:9px;font-weight:700;letter-spacing:1.5px;
      color:#6B7280;text-align:left;text-transform:uppercase">EXECUTIVE</th>
    <th class="hide-mobile" style="padding:10px 14px;font-size:9px;font-weight:700;
      letter-spacing:1.5px;color:#6B7280;text-align:left;text-transform:uppercase">TITLE</th>
    <th style="padding:10px 14px;font-size:9px;font-weight:700;letter-spacing:1.5px;
      color:#6B7280;text-align:right;text-transform:uppercase">VALUE</th>
    <th style="padding:10px 14px;font-size:9px;font-weight:700;letter-spacing:1.5px;
      color:#6B7280;text-align:center;text-transform:uppercase">DATE</th>
    <th style="padding:10px 14px;font-size:9px;font-weight:700;letter-spacing:1.5px;
      color:#6B7280;text-align:center;text-transform:uppercase">SIGNAL</th>
  </tr></thead><tbody>
"""
        for i, r in enumerate(insider_rows):
            bg = WHITE if i % 2 == 0 else GRAY_LT
            val_fmt = (f"${r['value']/1e6:.2f}M" if r["value"] >= 1e6
                       else f"${r['value']:,.0f}")
            rows += f"""
  <tr style="background:{bg};border-bottom:1px solid #F3F4F6">
    <td style="padding:10px 14px;font-weight:700;font-size:12px;color:{NAVY}">{r['ticker']}</td>
    <td style="padding:10px 14px;font-size:11px;color:#111827">{r['name']}</td>
    <td class="hide-mobile" style="padding:10px 14px;font-size:10px;color:{GRAY}">{r['title']}</td>
    <td style="padding:10px 14px;font-size:12px;font-weight:700;
      color:{GREEN};text-align:right">{val_fmt}</td>
    <td style="padding:10px 14px;font-size:10px;color:{GRAY};text-align:center">{r['date']}</td>
    <td style="padding:10px 14px;text-align:center">{_sig_badge('BUY')}</td>
  </tr>
"""
        rows += "  </tbody></table>\n"
    else:
        rows += (
            f'<div style="padding:20px 24px;font-size:12px;color:{GRAY};font-style:italic">'
            f'No material insider transactions meet screening criteria today.</div>'
        )
    rows += "</div></td></tr>\n"

    # ── SECTION 3: PORTFOLIO ──────────────────────────────────────────────────
    rows += f"""
<tr><td style="padding-top:20px">
{_section_header("PORTFOLIO PERFORMANCE",
                 "As of market close — data from Google Sheets + Yahoo Finance")}
<div style="background:{WHITE};border:1px solid {BORDER};border-top:none">
"""
    if portfolio_enriched and portfolio_totals:
        t        = portfolio_totals
        sp_ytd   = (bench or {}).get("sp500", {}).get("return_ytd", 0.0) if bench else 0.0
        port_ytd = t.get("sheet_pnl_pct") or t.get("total_unrealized_pnl_pct") or 0.0
        # FIX: convert percentage-point difference to basis points correctly
        alpha_bps = int(round((port_ytd - sp_ytd) * 100)) if sp_ytd else 0
        total_mv  = t.get("total_portfolio_value") or t.get("total_market_value") or 0
        tot_pnl   = t.get("total_unrealized_pnl") or 0
        tot_cost  = t.get("total_cost") or 0
        # FIX: always compute pct from dollar P&L for consistency
        tot_pct   = (tot_pnl / tot_cost * 100) if tot_cost else 0.0

        pnl_col   = GREEN if tot_pnl  >= 0 else RED
        alpha_col = GREEN if alpha_bps >= 0 else RED

        rows += f"""
  <div style="background:{NAVY};padding:16px 24px">
  <table width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <td style="padding-right:24px">
      <div style="font-size:9px;font-weight:700;letter-spacing:1.5px;color:#93C5FD">
        TOTAL VALUE</div>
      <div style="font-size:20px;font-weight:700;color:{WHITE}">${total_mv:,.0f}</div>
    </td>
    <td style="padding:0 24px;border-left:1px solid #1E3A5F">
      <div style="font-size:9px;font-weight:700;letter-spacing:1.5px;color:#93C5FD">
        UNREALIZED P&amp;L</div>
      <div style="font-size:20px;font-weight:700;color:{pnl_col}">
        {"+" if tot_pnl >= 0 else ""}{tot_pnl:,.0f}
        <span style="font-size:13px">({tot_pct:+.1f}%)</span></div>
    </td>
    <td style="padding-left:24px;border-left:1px solid #1E3A5F">
      <div style="font-size:9px;font-weight:700;letter-spacing:1.5px;color:#93C5FD">
        YTD vs S&amp;P 500</div>
      <div style="font-size:20px;font-weight:700;color:{alpha_col}">
        {port_ytd:+.1f}% vs {sp_ytd:+.1f}%
        <span style="font-size:12px">({alpha_bps:+d}bps)</span></div>
    </td>
  </tr>
  </table>
  </div>
"""
        rows += """
  <table width="100%" cellpadding="0" cellspacing="0">
  <thead><tr style="background:#F9FAFB;border-bottom:2px solid #E5E7EB">
    <th style="padding:10px 12px;font-size:9px;font-weight:700;letter-spacing:1.5px;
      color:#6B7280;text-align:left;text-transform:uppercase">TICKER</th>
    <th class="hide-mobile" style="padding:10px 12px;font-size:9px;font-weight:700;
      letter-spacing:1.5px;color:#6B7280;text-align:right;text-transform:uppercase">SHARES</th>
    <th class="hide-mobile" style="padding:10px 12px;font-size:9px;font-weight:700;
      letter-spacing:1.5px;color:#6B7280;text-align:right;text-transform:uppercase">AVG COST</th>
    <th style="padding:10px 12px;font-size:9px;font-weight:700;letter-spacing:1.5px;
      color:#6B7280;text-align:right;text-transform:uppercase">LAST</th>
    <th style="padding:10px 12px;font-size:9px;font-weight:700;letter-spacing:1.5px;
      color:#6B7280;text-align:right;text-transform:uppercase">MKT VALUE</th>
    <th style="padding:10px 12px;font-size:9px;font-weight:700;letter-spacing:1.5px;
      color:#6B7280;text-align:right;text-transform:uppercase">P&amp;L $</th>
    <th style="padding:10px 12px;font-size:9px;font-weight:700;letter-spacing:1.5px;
      color:#6B7280;text-align:right;text-transform:uppercase">P&amp;L %</th>
    <th style="padding:10px 12px;font-size:9px;font-weight:700;letter-spacing:1.5px;
      color:#6B7280;text-align:center;text-transform:uppercase">SIGNAL</th>
  </tr></thead><tbody>
"""
        sorted_h = sorted(portfolio_enriched, key=lambda x: x.get("market_value", 0), reverse=True)
        for i, r in enumerate(sorted_h):
            bg     = WHITE if i % 2 == 0 else GRAY_LT
            shares = float(r.get("shares", 0) or 0)
            # FIX: use cost_basis_ps (per-share cost from Google Sheets)
            cost   = float(r.get("cost_basis_ps", 0) or 0)
            price  = float(r.get("price", 0) or 0)
            mv     = shares * price
            tc     = shares * cost
            # FIX: always compute both P&L values from the same source
            pnl_d  = mv - tc
            pnl_p  = (pnl_d / tc * 100) if tc else 0.0
            sig    = r.get("signal", "NEUTRAL")
            pc     = GREEN if pnl_d >= 0 else RED
            rows += f"""
  <tr style="background:{bg};border-bottom:1px solid #F3F4F6">
    <td style="padding:10px 12px;font-weight:700;font-size:12px;color:{NAVY}">{r['ticker']}</td>
    <td class="hide-mobile" style="padding:10px 12px;font-size:11px;
      color:#374151;text-align:right">{shares:,.1f}</td>
    <td class="hide-mobile" style="padding:10px 12px;font-size:11px;
      color:#374151;text-align:right">{_fmt_price(cost)}</td>
    <td style="padding:10px 12px;font-size:11px;font-weight:700;
      color:#111827;text-align:right">{_fmt_price(price)}</td>
    <td style="padding:10px 12px;font-size:11px;
      color:#374151;text-align:right">${mv:,.0f}</td>
    <td style="padding:10px 12px;font-size:11px;font-weight:700;
      color:{pc};text-align:right">{"+" if pnl_d >= 0 else ""}{pnl_d:,.0f}</td>
    <td style="padding:10px 12px;font-size:11px;font-weight:700;
      color:{pc};text-align:right">{"+" if pnl_p >= 0 else ""}{pnl_p:.1f}%</td>
    <td style="padding:10px 12px;text-align:center">{_sig_badge(sig)}</td>
  </tr>
"""
        rows += "  </tbody></table>\n"
    else:
        rows += (
            f'<div style="padding:20px 24px;font-size:12px;color:{GRAY};font-style:italic">'
            f'Portfolio data unavailable — check Google Sheets connection.</div>'
        )
    rows += "</div></td></tr>\n"

    # ── SECTION 4: RADAR ──────────────────────────────────────────────────────
    rows += f"""
<tr><td style="padding-top:20px">
{_section_header("WATCHLIST — TOP OPPORTUNITIES", "Ranked by Hybrid Score")}
<div style="background:{WHITE};border:1px solid {BORDER};border-top:none">
  <table width="100%" cellpadding="0" cellspacing="0">
  <thead><tr style="background:#F9FAFB;border-bottom:2px solid #E5E7EB">
    <th style="padding:10px 14px;font-size:9px;font-weight:700;letter-spacing:1.5px;
      color:#6B7280;text-align:left;text-transform:uppercase">TICKER</th>
    <th style="padding:10px 14px;font-size:9px;font-weight:700;letter-spacing:1.5px;
      color:#6B7280;text-align:center;text-transform:uppercase">HYBRID SCORE</th>
    <th style="padding:10px 14px;font-size:9px;font-weight:700;letter-spacing:1.5px;
      color:#6B7280;text-align:center;text-transform:uppercase">SIGNAL</th>
    <th class="hide-mobile" style="padding:10px 14px;font-size:9px;font-weight:700;
      letter-spacing:1.5px;color:#6B7280;text-align:right;text-transform:uppercase">UPSIDE</th>
    <th class="hide-mobile" style="padding:10px 14px;font-size:9px;font-weight:700;
      letter-spacing:1.5px;color:#6B7280;text-align:center;text-transform:uppercase">EARNINGS</th>
    <th style="padding:10px 14px;font-size:9px;font-weight:700;letter-spacing:1.5px;
      color:#6B7280;text-align:left;text-transform:uppercase">NOTE</th>
  </tr></thead><tbody>
"""
    for i, r in enumerate(radar_stocks):
        bg    = WHITE if i % 2 == 0 else GRAY_LT
        score = float(r["score"])
        bar_w = int(score * 10)
        bar_c = GREEN if score >= 6.5 else (GOLD if score >= 5 else RED)
        up    = r.get("upside", "N/A")
        try:
            up = f"{float(up):+.1f}%" if up not in (None, "N/A", "") else "N/A"
        except Exception:
            pass
        rows += f"""
  <tr style="background:{bg};border-bottom:1px solid #F3F4F6">
    <td style="padding:10px 14px;font-weight:700;font-size:12px;color:{NAVY}">{r['ticker']}</td>
    <td style="padding:10px 14px;text-align:center">
      <div style="font-size:12px;font-weight:700;color:#111827">{r['score']}/10</div>
      <div style="width:60px;height:4px;background:#E5E7EB;border-radius:2px;
        margin:3px auto;overflow:hidden">
        <div style="width:{bar_w}%;height:100%;background:{bar_c};border-radius:2px"></div>
      </div>
    </td>
    <td style="padding:10px 14px;text-align:center">{_sig_badge(r['signal'])}</td>
    <td class="hide-mobile" style="padding:10px 14px;font-size:11px;
      font-weight:700;color:{GREEN};text-align:right">{up}</td>
    <td class="hide-mobile" style="padding:10px 14px;font-size:10px;
      color:{GRAY};text-align:center">{r.get('earnings','N/A')}</td>
    <td style="padding:10px 14px;font-size:10px;color:{GRAY}">{r.get('note','')}</td>
  </tr>
"""
    rows += "  </tbody></table>\n</div></td></tr>\n"

    # ── FOOTER ────────────────────────────────────────────────────────────────
    rows += f"""
<tr><td style="padding-top:24px">
<div style="border-top:1px solid {BORDER};padding:20px 0 8px;text-align:center">
  <div style="font-size:10px;color:{GRAY};line-height:1.7;max-width:520px;margin:0 auto">
    This report is generated automatically using market data from Yahoo Finance
    and AI analysis from Anthropic Claude. Not investment advice.
  </div>
  <div style="font-size:10px;color:#9CA3AF;margin-top:8px">
    Mohab Capital Intelligence &nbsp;&middot;&nbsp;
    mohab2056@gmail.com &nbsp;&middot;&nbsp;
    Riyadh, Saudi Arabia
  </div>
  <div style="font-size:9px;color:#D1D5DB;margin-top:6px">Generated {gen_ts}</div>
</div>
</td></tr>
"""
    return wrap(rows)


# ── 8. Send Email ──────────────────────────────────────────────────────────────

def send_email(html_body):
    if not GMAIL_APP_PW or GMAIL_APP_PW == "YOUR_APP_PASSWORD_HERE":
        print("  ERROR: GMAIL_APP_PASSWORD not configured.")
        return False

    now     = datetime.now()
    subject = f"Mohab Capital | Daily Intelligence Brief — {now.strftime('%B %d, %Y')}"

    msg            = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = RECEIVER_EMAIL
    msg.attach(MIMEText(html_body, "html"))

    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
        with smtplib.SMTP("smtp.gmail.com", 587) as srv:
            srv.ehlo()
            srv.starttls(context=ctx)
            srv.login(SENDER_EMAIL, GMAIL_APP_PW.replace(" ", ""))
            srv.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        print(f"  Email sent to {RECEIVER_EMAIL}  [{now.strftime('%H:%M:%S')}]")
        return True
    except smtplib.SMTPAuthenticationError:
        print("  AUTH FAILED — check Gmail App Password.")
        return False
    except Exception as e:
        print(f"  Send failed: {e}")
        return False


# ── 9. Orchestrator ────────────────────────────────────────────────────────────

def run(send=True, save=True):
    t0 = time.time()
    print("\n" + "="*60)
    print("  MOHAB CAPITAL | DAILY INTELLIGENCE BRIEF")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    print("\n  [1/7] Fetching market overview...")
    market     = fetch_market_overview()
    benchmarks = fetch_ytd_benchmarks()
    print(f"        {len(market)} instruments loaded")

    print("  [2/7] Fetching macro news (filtered)...")
    news_items = fetch_macro_news(max_items=6)
    print(f"        {len(news_items)} macro headlines")

    print("  [3/7] Fetching portfolio from Google Sheets...")
    port_enriched, positions, cash, pnl_pct, bench, port_totals = fetch_portfolio()
    print(f"        {len(port_enriched)} holdings loaded")

    print("  [4/7] Fetching insider activity...")
    all_tickers = list(positions.keys()) if positions else [
        "CRWV","GOOGL","NVDA","AMD","INTC","MU","GDX","SPUS","TIGO"
    ]
    insider_rows = fetch_insider_activity(all_tickers)
    cluster_buys = detect_cluster_buys(insider_rows)
    print(f"        {len(insider_rows)} transactions, {len(cluster_buys)} cluster buys")

    print("  [5/7] Fetching radar / watchlist...")
    radar_stocks = fetch_radar_top(5)
    print(f"        {len(radar_stocks)} top opportunities")

    ai_tag = "Claude API (claude-sonnet-4-6)" if ANTHROPIC_KEY else "rule-based fallback"
    print(f"  [6/7] Generating executive summary ({ai_tag})...")
    summary_text = generate_executive_summary(market, benchmarks, port_totals, insider_rows)

    print(f"  [7/7] Generating market narrative + {len(news_items)} macro analyses ({ai_tag})...")
    market_narrative = generate_market_narrative(
        market, news_items, port_enriched, port_totals, bench, radar_stocks
    )
    macro_analyses = [
        generate_macro_analysis(item["title"], all_tickers)
        for item in news_items
    ]

    print("\n  Building HTML report...")
    html = build_html(
        summary_text, market_narrative,
        market, news_items, macro_analyses,
        insider_rows, cluster_buys,
        port_enriched, port_totals, bench,
        radar_stocks,
    )

    if save:
        with open(REPORT_HTML, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  Saved → {REPORT_HTML}")

    if send:
        print("  Sending email...")
        ok = send_email(html)
        if ok:
            print(f"\n  CONFIRMATION: Report delivered to {RECEIVER_EMAIL}")
        else:
            print("\n  FAILED: Email not sent.")
    else:
        ok = True

    print(f"\n  Done in {time.time() - t0:.1f}s")
    print("="*60 + "\n")
    return ok


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    send_flag = "--save" not in sys.argv
    run(send=send_flag, save=True)
