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
            t = yf.Ticker(sym)
            hist = t.history(period="5d", interval="1d")
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


# ── 2. Macro News ──────────────────────────────────────────────────────────────

def fetch_macro_news(max_items=6):
    import urllib.request, xml.etree.ElementTree as ET, ssl
    ctx = ssl._create_unverified_context()
    feeds = [
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US",
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=SPY&region=US&lang=en-US",
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EVIX&region=US&lang=en-US",
    ]
    seen, items = set(), []
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
                items.append({"title": title, "link": link, "pub": pub})
                if len(items) >= max_items * 2:
                    break
        except Exception:
            pass
    return items[:max_items]


# ── 3. Insider Activity ────────────────────────────────────────────────────────

def fetch_insider_activity(tickers):
    import yfinance as yf
    import pandas as pd
    rows = []
    cutoff = datetime.now() - timedelta(days=30)
    for tk in tickers:
        try:
            t = yf.Ticker(tk)
            df = t.insider_transactions
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
                    name   = str(r.get("Insider", r.get("Name", "Unknown"))).strip()
                    title  = str(r.get("Position", r.get("Title", ""))).strip()
                    tx_date_raw = r.get("Date", r.get("date"))
                    if isinstance(tx_date_raw, str):
                        try:
                            tx_date = pd.to_datetime(tx_date_raw).to_pydatetime().replace(tzinfo=None)
                        except Exception:
                            tx_date = datetime.now()
                    elif hasattr(tx_date_raw, "to_pydatetime"):
                        tx_date = tx_date_raw.to_pydatetime().replace(tzinfo=None)
                    else:
                        tx_date = datetime.now()
                    if tx_date < cutoff:
                        continue
                    rows.append({
                        "ticker":  tk,
                        "name":    name[:28],
                        "title":   title[:24],
                        "shares":  shares,
                        "value":   value,
                        "date":    tx_date.strftime("%b %d"),
                        "signal":  "BUY",
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
            return [], {}, 0.0, None, None
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
    cache_path = os.path.join(BASE_DIR, "radar_cache.json")
    watchlist_path = os.path.join(BASE_DIR, "watchlist.json")
    try:
        tickers = json.load(open(watchlist_path))["tickers"]
    except Exception:
        tickers = ["AAPL","MSFT","NVDA","AMZN","META","GOOGL","JPM","TSLA","NFLX","AVGO"]
    try:
        cache = json.load(open(cache_path))
    except Exception:
        cache = {}

    import yfinance as yf
    stocks = []
    for tk in tickers:
        try:
            entry = cache.get(tk, {}).get("data", {})
            score = float(entry.get("score_hybrid") or entry.get("composite") or 5.0)
            sig   = str(entry.get("sig_hybrid") or entry.get("signal") or "Neutral")
            price = entry.get("price")
            if price in (None, "N/A", ""):
                info = yf.Ticker(tk).info
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
                "ticker":  tk,
                "score":   round(score, 2),
                "signal":  sig,
                "price":   price,
                "upside":  upside,
                "earnings": earn,
                "note":    note,
            })
        except Exception:
            pass
    stocks.sort(key=lambda x: x["score"], reverse=True)
    return stocks[:n]


# ── 6. AI Analysis (Claude API or fallback) ───────────────────────────────────

def _call_claude(prompt, max_tokens=400):
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
    sp_chg  = market.get("S&P 500", {}).get("change_pct", 0.0)
    vix     = market.get("VIX", {}).get("price", 0.0)
    sp_ytd  = benchmarks.get("sp500", 0.0)
    port_ytd = (portfolio_totals or {}).get("sheet_pnl_pct") if portfolio_totals else None
    n_insider = len(insider_rows)

    if ANTHROPIC_KEY:
        port_line = (f"Portfolio YTD: {port_ytd:+.1f}%" if port_ytd is not None
                     else "Portfolio data from Google Sheets")
        insider_line = (f"{n_insider} open-market insider purchases detected in portfolio holdings."
                        if n_insider > 0 else "No material insider transactions today.")
        prompt = (
            "You are a senior market strategist at a top investment bank. "
            "Write a 3-sentence executive summary for a professional daily market intelligence brief. "
            "Be specific, use the data provided, lead with the most important insight. "
            "No emojis. No bullet points. Plain prose only.\n\n"
            f"Market data:\n"
            f"- S&P 500 prior session: {sp_chg:+.2f}%\n"
            f"- VIX: {vix:.1f}\n"
            f"- S&P 500 YTD: {sp_ytd:+.1f}%\n"
            f"- {port_line}\n"
            f"- {insider_line}\n\n"
            "Write exactly 3 sentences."
        )
        result = _call_claude(prompt, max_tokens=200)
        if result:
            return result

    # Intelligent fallback
    mood = "cautious" if vix > 20 else ("risk-on" if sp_chg > 0.5 else "mixed")
    sp_str = f"{sp_chg:+.2f}%" if sp_chg else "flat"
    summary_lines = [
        f"Equity markets closed {sp_str} in the prior session with VIX at {vix:.1f}, "
        f"reflecting a {mood} tone among institutional participants.",
    ]
    if port_ytd is not None:
        bench_diff = port_ytd - sp_ytd if sp_ytd else 0
        summary_lines.append(
            f"Portfolio stands {port_ytd:+.1f}% YTD, "
            + (f"outperforming the S&P 500 by {abs(bench_diff):.0f}bps."
               if bench_diff > 0 else f"tracking the S&P 500 benchmark.")
        )
    if n_insider > 0:
        summary_lines.append(
            f"{n_insider} open-market insider purchase{'s' if n_insider > 1 else ''} "
            f"detected across holdings — a historically constructive signal."
        )
    return " ".join(summary_lines)


def generate_macro_analysis(headline):
    if ANTHROPIC_KEY:
        prompt = (
            "You are a senior market analyst. Analyze this news headline and provide:\n"
            "1. IMPACT: exactly one word — BULLISH, BEARISH, or NEUTRAL\n"
            "2. SECTORS: comma-separated list of up to 3 affected sectors (e.g. Technology, Financials, Energy)\n"
            "3. ANALYSIS: one crisp sentence (max 20 words) explaining the investment implication\n"
            "4. RELEVANCE: HIGH or MEDIUM\n\n"
            f"Headline: {headline}\n\n"
            "Respond in this exact format (no extra text):\n"
            "IMPACT: [BULLISH/BEARISH/NEUTRAL]\n"
            "SECTORS: [sectors]\n"
            "ANALYSIS: [one sentence]\n"
            "RELEVANCE: [HIGH/MEDIUM]"
        )
        result = _call_claude(prompt, max_tokens=120)
        if result:
            parsed = {}
            for line in result.strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    parsed[k.strip().upper()] = v.strip()
            if "IMPACT" in parsed:
                return parsed
    # Fallback heuristics
    h = headline.lower()
    neg_words = {"fall","drop","decline","cut","warn","weak","miss","slump","crash","concern","risk"}
    pos_words = {"rise","gain","beat","surge","strong","upgrade","rally","growth","record","jump"}
    neg = sum(1 for w in neg_words if w in h)
    pos = sum(1 for w in pos_words if w in h)
    impact    = "BULLISH" if pos > neg else ("BEARISH" if neg > pos else "NEUTRAL")
    relevance = "HIGH" if any(x in h for x in ["fed","rate","inflation","gdp","jobs","earnings"]) else "MEDIUM"
    sector    = "Broad Market"
    if any(x in h for x in ["tech","ai","chip","semicon","software","nvidia","apple","microsoft"]):
        sector = "Technology"
    elif any(x in h for x in ["bank","rate","fed","treasury","yield","credit"]):
        sector = "Financials"
    elif any(x in h for x in ["oil","energy","gas","crude"]):
        sector = "Energy"
    elif any(x in h for x in ["consumer","retail","spending"]):
        sector = "Consumer"
    return {
        "IMPACT":    impact,
        "SECTORS":   sector,
        "ANALYSIS":  "Monitor developments for potential portfolio impact.",
        "RELEVANCE": relevance,
    }


# ── 7. HTML Builder ────────────────────────────────────────────────────────────

# Color palette
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
        return f"${v:,.2f}" if v >= 1 else f"${v:.4f}"
    except Exception:
        return "N/A"

def _fmt_chg(v):
    try:
        v = float(v)
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.2f}%"
    except Exception:
        return "N/A"

def _chg_color(v):
    try:
        return GREEN if float(v) >= 0 else RED
    except Exception:
        return GRAY

def _sig_badge(sig):
    sig = str(sig).upper()
    styles = {
        "STRONG BUY":  (GREEN,   "#DCFCE7"),
        "BUY":         ("#15803D","#D1FAE5"),
        "NEUTRAL":     (GOLD,    "#FEF3C7"),
        "SELL":        ("#EA580C","#FFEDD5"),
        "STRONG SELL": (RED,     "#FEE2E2"),
    }
    # Map hybrid signals
    mapping = {
        "STRONG BUY": "STRONG BUY", "STRONGBUY": "STRONG BUY",
        "BUY": "BUY",
        "NEUTRAL": "NEUTRAL",
        "SELL": "SELL",
        "STRONG SELL": "STRONG SELL", "STRONGSELL": "STRONG SELL",
    }
    key = mapping.get(sig.replace(" ", "").upper(), "NEUTRAL")
    fg, bg = styles.get(key, (GRAY, "#F3F4F6"))
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
        f'font-size:10px;font-weight:700;letter-spacing:.5px;'
        f'color:{fg};background:{bg};border:1px solid {fg}40">'
        f'{key}</span>'
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
    return """
    <style>
      * { box-sizing: border-box; }
      body { margin: 0; padding: 0; background: #E9EDF2; }
      table { border-collapse: collapse; }
      a { color: #1a3256; }
      @media only screen and (max-width: 600px) {
        .wrapper { width: 100% !important; }
        .hide-mobile { display: none !important; }
      }
    </style>
    """

def _section_header(title, subtitle=""):
    sub = (
        f'<div style="font-size:11px;color:#9CA3AF;margin-top:3px;'
        f'font-style:italic">{subtitle}</div>' if subtitle else ""
    )
    return (
        f'<div style="background:{NAVY};padding:12px 20px;margin-bottom:0">'
        f'<div style="font-size:10px;font-weight:700;letter-spacing:2px;'
        f'color:#93C5FD;text-transform:uppercase">{title}</div>'
        f'{sub}</div>'
    )


def build_html(summary_text, market, news_items, macro_analyses,
               insider_rows, cluster_buys,
               portfolio_enriched, portfolio_totals, bench,
               radar_stocks):

    now         = datetime.now()
    date_hdr    = now.strftime("%A, %B %d %Y")
    time_hdr    = "New York Pre-Market" if now.hour < 13 else "End of Day"
    gen_ts      = now.strftime("%Y-%m-%d %H:%M:%S UTC")

    # ── WRAPPER ──────────────────────────────────────────────────────────────
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
  <div style="font-size:22px;font-weight:700;color:{WHITE};
    letter-spacing:.5px;line-height:1.2">Daily Intelligence Brief</div>
  <div style="margin-top:12px;border-top:1px solid #1E3A5F;padding-top:12px;
    display:flex;justify-content:space-between">
    <span style="font-size:11px;color:#6B8CAE">{date_hdr} &nbsp;|&nbsp; {time_hdr}</span>
    <span style="font-size:11px;color:#6B8CAE">Powered by Claude AI</span>
  </div>
</div>
</td></tr>
"""

    # ── MARKET TICKER BAR ─────────────────────────────────────────────────────
    ticker_cells = ""
    for name, d in market.items():
        p    = d.get("price", 0.0)
        chg  = d.get("change_pct", 0.0)
        col  = GREEN if chg >= 0 else RED
        sign = "+" if chg >= 0 else ""
        # Abbreviated names for the bar
        short = {"S&P 500":"SPX","NASDAQ":"NDX","DOW":"DJIA",
                 "Russell 2K":"RUT","VIX":"VIX","Gold":"GOLD",
                 "WTI Oil":"OIL","10-Yr UST":"10Y","USD/EUR":"EUR","Bitcoin":"BTC"}.get(name, name[:4])
        fmt_p = f"{p:,.0f}" if p > 100 else f"{p:.2f}"
        ticker_cells += (
            f'<td style="padding:8px 12px;border-right:1px solid #E5E7EB;'
            f'white-space:nowrap;vertical-align:top">'
            f'<div style="font-size:9px;font-weight:700;letter-spacing:1px;color:{GRAY}">{short}</div>'
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
{_section_header("EXECUTIVE SUMMARY", "AI-generated market intelligence")}
<div style="background:{WHITE};padding:20px 24px;border:1px solid {BORDER};border-top:none">
  <div style="font-size:14px;line-height:1.75;color:#1F2937;font-style:italic">
    {summary_text}
  </div>
</div>
</td></tr>
"""

    # ── SECTION 1: MACRO ──────────────────────────────────────────────────────
    rows += f"""
<tr><td style="padding-top:20px">
{_section_header("MARKET-MOVING DEVELOPMENTS",
                 "Events with potential portfolio impact — assessed by AI")}
<div style="background:{WHITE};border:1px solid {BORDER};border-top:none">
"""
    for i, (item, analysis) in enumerate(zip(news_items, macro_analyses)):
        bg = WHITE if i % 2 == 0 else GRAY_LT
        impact   = analysis.get("IMPACT", "NEUTRAL")
        sectors  = analysis.get("SECTORS", "Broad Market")
        ai_note  = analysis.get("ANALYSIS", "")
        relevance= analysis.get("RELEVANCE", "MEDIUM")
        rel_dots = (
            _dot(True) + "&nbsp;" + _dot(True) + " HIGH"
            if relevance == "HIGH"
            else _dot(True) + "&nbsp;" + _dot(False) + " MEDIUM"
        )

        # Format pub date nicely
        pub = item.get("pub", "")
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(pub)
            mins_ago = int((datetime.now(dt.tzinfo) - dt).total_seconds() / 60)
            pub_str = (f"{mins_ago}m ago" if mins_ago < 120
                       else f"{mins_ago//60}h ago" if mins_ago < 1440
                       else dt.strftime("%b %d"))
        except Exception:
            pub_str = pub[:16] if pub else ""

        rows += f"""
  <div style="padding:14px 20px;background:{bg};border-bottom:1px solid {BORDER}">
    <div style="font-size:13px;font-weight:700;color:#111827;line-height:1.4;
      margin-bottom:5px">{item['title']}</div>
    <div style="font-size:10px;color:{GRAY};margin-bottom:8px">
      Yahoo Finance &nbsp;&middot;&nbsp; {pub_str}
    </div>
    <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td style="font-size:10px;color:{GRAY};padding-right:16px">
        <span style="font-weight:700;color:#374151">Impact:</span>&nbsp;
        {_impact_badge(impact)}&nbsp;
        <span style="color:{GRAY}">for {sectors}</span>
      </td>
      <td style="font-size:10px;color:{GRAY};text-align:right;white-space:nowrap">
        <span style="font-weight:700;color:#374151">Relevance:</span>&nbsp;{rel_dots}
      </td>
    </tr>
    </table>
    {"<div style='font-size:11px;color:#4B5563;margin-top:7px;font-style:italic'>Analysis: " + ai_note + "</div>" if ai_note else ""}
  </div>
"""
    rows += "</div></td></tr>\n"

    # ── SECTION 2: INSIDER ACTIVITY ───────────────────────────────────────────
    rows += f"""
<tr><td style="padding-top:20px">
{_section_header("INSTITUTIONAL & INSIDER SIGNALS",
                 "Material transactions by C-suite executives — open market only")}
<div style="background:{WHITE};border:1px solid {BORDER};border-top:none">
"""
    # Cluster buy alerts
    for tk, count in cluster_buys.items():
        combined = sum(r["value"] for r in insider_rows if r["ticker"] == tk)
        rows += (
            f'<div style="background:#FFFBEB;border-left:4px solid {GOLD};'
            f'padding:12px 20px;margin:8px;border-radius:4px">'
            f'<span style="font-size:11px;font-weight:700;color:{GOLD};letter-spacing:1px">'
            f'CLUSTER BUY DETECTED &mdash; {tk}</span><br>'
            f'<span style="font-size:11px;color:#92400E">'
            f'{count} executives purchased shares in the past 30 days. '
            f'Combined value: ${combined/1e6:.1f}M. Historically bullish signal.</span>'
            f'</div>'
        )

    if insider_rows:
        rows += """
  <table width="100%" cellpadding="0" cellspacing="0">
  <thead>
  <tr style="background:#F9FAFB;border-bottom:2px solid #E5E7EB">
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
  </tr>
  </thead>
  <tbody>
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
    <td style="padding:10px 14px;font-size:12px;font-weight:700;color:{GREEN};
      text-align:right">{val_fmt}</td>
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
        t = portfolio_totals
        sp_ytd  = (bench or {}).get("sp500", {}).get("return_ytd", 0) if bench else 0
        port_ytd = t.get("sheet_pnl_pct") or t.get("total_unrealized_pnl_pct") or 0
        alpha    = (port_ytd - sp_ytd) if sp_ytd else 0
        total_mv = t.get("total_portfolio_value") or t.get("total_market_value") or 0
        tot_pnl  = t.get("total_unrealized_pnl") or 0
        tot_pct  = t.get("total_unrealized_pnl_pct") or 0

        pnl_col   = GREEN if tot_pnl  >= 0 else RED
        alpha_col = GREEN if alpha    >= 0 else RED

        # Summary row
        rows += f"""
  <div style="background:{NAVY};padding:14px 20px">
  <table width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <td style="padding:0 20px 0 0">
      <div style="font-size:9px;font-weight:700;letter-spacing:1.5px;color:#93C5FD">
        TOTAL VALUE</div>
      <div style="font-size:18px;font-weight:700;color:{WHITE}">${total_mv:,.0f}</div>
    </td>
    <td style="padding:0 20px;border-left:1px solid #1E3A5F">
      <div style="font-size:9px;font-weight:700;letter-spacing:1.5px;color:#93C5FD">
        UNREALIZED P&amp;L</div>
      <div style="font-size:18px;font-weight:700;color:{pnl_col}">
        {"+" if tot_pnl >= 0 else ""}{tot_pnl:,.0f} ({tot_pct:+.1f}%)</div>
    </td>
    <td style="padding:0 0 0 20px;border-left:1px solid #1E3A5F">
      <div style="font-size:9px;font-weight:700;letter-spacing:1.5px;color:#93C5FD">
        YTD vs S&P 500</div>
      <div style="font-size:18px;font-weight:700;color:{alpha_col}">
        {port_ytd:+.1f}% vs {sp_ytd:+.1f}%
        <span style="font-size:12px">({alpha:+.0f}bps)</span></div>
    </td>
  </tr>
  </table>
  </div>
"""
        # Holdings table
        rows += """
  <table width="100%" cellpadding="0" cellspacing="0">
  <thead>
  <tr style="background:#F9FAFB;border-bottom:2px solid #E5E7EB">
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
  </tr>
  </thead>
  <tbody>
"""
        sorted_holdings = sorted(portfolio_enriched, key=lambda x: x.get("market_value", 0), reverse=True)
        for i, r in enumerate(sorted_holdings):
            bg     = WHITE if i % 2 == 0 else GRAY_LT
            pnl_d  = r.get("unrealized_pnl", 0) or 0
            pnl_p  = r.get("unrealized_pnl_pct", 0) or r.get("pnl_pct", 0) or 0
            mv     = r.get("market_value", 0) or 0
            price  = r.get("price", 0) or 0
            shares = r.get("shares", 0) or 0
            cost   = r.get("cost_basis", 0) or 0
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
  <thead>
  <tr style="background:#F9FAFB;border-bottom:2px solid #E5E7EB">
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
  </tr>
  </thead>
  <tbody>
"""
    for i, r in enumerate(radar_stocks):
        bg = WHITE if i % 2 == 0 else GRAY_LT
        score_pct = int(float(r["score"]) * 10)  # out of 100
        bar_col   = GREEN if float(r["score"]) >= 6.5 else (GOLD if float(r["score"]) >= 5 else RED)
        upside    = r.get("upside", "N/A")
        if upside not in (None, "N/A", "") and upside != "N/A":
            try:
                upside = f"{float(upside):+.1f}%"
            except Exception:
                pass
        rows += f"""
  <tr style="background:{bg};border-bottom:1px solid #F3F4F6">
    <td style="padding:10px 14px;font-weight:700;font-size:12px;color:{NAVY}">{r['ticker']}</td>
    <td style="padding:10px 14px;text-align:center">
      <div style="font-size:12px;font-weight:700;color:#111827">{r['score']}/10</div>
      <div style="width:60px;height:4px;background:#E5E7EB;border-radius:2px;
        margin:3px auto 0;overflow:hidden">
        <div style="width:{score_pct}%;height:100%;background:{bar_col};
          border-radius:2px"></div>
      </div>
    </td>
    <td style="padding:10px 14px;text-align:center">{_sig_badge(r['signal'])}</td>
    <td class="hide-mobile" style="padding:10px 14px;font-size:11px;
      font-weight:700;color:{GREEN};text-align:right">{upside}</td>
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
  <div style="font-size:9px;color:#D1D5DB;margin-top:6px">
    Generated {gen_ts}
  </div>
</div>
</td></tr>
"""

    return wrap(rows)


# ── 8. Send Email ──────────────────────────────────────────────────────────────

def send_email(html_body):
    if not GMAIL_APP_PW or GMAIL_APP_PW == "YOUR_APP_PASSWORD_HERE":
        print("  ERROR: GMAIL_APP_PASSWORD not configured.")
        return False

    now    = datetime.now()
    subject = f"Mohab Capital | Daily Intelligence Brief — {now.strftime('%B %d, %Y')}"

    msg           = MIMEMultipart("alternative")
    msg["Subject"]= subject
    msg["From"]   = SENDER_EMAIL
    msg["To"]     = RECEIVER_EMAIL
    msg.attach(MIMEText(html_body, "html"))

    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
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

    print("\n  [1/6] Fetching market overview...")
    market    = fetch_market_overview()
    benchmarks = fetch_ytd_benchmarks()
    print(f"        {len(market)} instruments loaded")

    print("  [2/6] Fetching macro news...")
    news_items = fetch_macro_news(max_items=6)
    print(f"        {len(news_items)} headlines")

    print("  [3/6] Fetching portfolio from Google Sheets...")
    port_result = fetch_portfolio()
    if len(port_result) == 6:
        port_enriched, positions, cash, pnl_pct, bench, port_totals = port_result
    else:
        port_enriched, positions, cash, pnl_pct, bench = port_result
        port_totals = {}
    print(f"        {len(port_enriched)} holdings loaded")

    print("  [4/6] Fetching insider activity...")
    all_tickers = list(positions.keys()) if positions else [
        "CRWV","GOOGL","NVDA","AMD","INTC","MU","GDX","SPUS","TIGO"
    ]
    insider_rows  = fetch_insider_activity(all_tickers)
    cluster_buys  = detect_cluster_buys(insider_rows)
    print(f"        {len(insider_rows)} transactions, {len(cluster_buys)} cluster buys")

    print("  [5/6] Fetching radar / watchlist...")
    radar_stocks = fetch_radar_top(5)
    print(f"        {len(radar_stocks)} top opportunities")

    print("  [6/6] Generating AI analysis...")
    ai_tag = "Claude AI" if ANTHROPIC_KEY else "rule-based fallback (set ANTHROPIC_API_KEY)"
    print(f"        Using {ai_tag}")
    summary_text  = generate_executive_summary(market, benchmarks, port_totals, insider_rows)
    macro_analyses = [generate_macro_analysis(item["title"]) for item in news_items]

    print("\n  Building HTML report...")
    html = build_html(
        summary_text, market, news_items, macro_analyses,
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
        success = send_email(html)
        if success:
            print(f"\n  CONFIRMATION: Report delivered to {RECEIVER_EMAIL}")
        else:
            print("\n  FAILED: Email not sent.")
    else:
        success = True

    elapsed = time.time() - t0
    print(f"\n  Done in {elapsed:.1f}s")
    print("="*60 + "\n")
    return success


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    send_flag = "--save" not in sys.argv
    run(send=send_flag, save=True)
