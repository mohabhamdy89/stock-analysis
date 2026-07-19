#!/usr/bin/env python3
"""
Mohab Capital | Daily Intelligence Brief — v3 (complete rebuild)
Answers one question: "What do I do today and why?"

Usage:
  python3 daily_report.py          → generate + send immediately
  python3 daily_report.py --save   → save HTML only (no send)
  python3 daily_report.py --now    → same as default
"""

import os, sys, json, time, smtplib, ssl, warnings
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Config ─────────────────────────────────────────────────────────────────────
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
SENDER_EMAIL   = "mohab2056@gmail.com"
RECEIVER_EMAIL = "mohab2056@gmail.com"
GMAIL_APP_PW   = os.getenv("GMAIL_APP_PASSWORD", "okgmkzilouegvfug")
ANTHROPIC_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
REPORT_HTML    = os.path.join(BASE_DIR, "test_report.html")

# Hardcoded fallback (matches Google Sheets exactly)
FALLBACK_PORTFOLIO = {
    "GOOGL": {"shares": 60,  "cost_basis": 242.69},
    "MU":    {"shares": 20,  "cost_basis": 923.49},
    "AMD":   {"shares": 30,  "cost_basis": 507.26},
    "NVDA":  {"shares": 70,  "cost_basis": 198.75},
    "SPUS":  {"shares": 250, "cost_basis": 50.05},
    "INTC":  {"shares": 140, "cost_basis": 108.74},
    "SPCX":  {"shares": 100, "cost_basis": 138.33},
    "GDX":   {"shares": 120, "cost_basis": 75.40},
}
FALLBACK_CASH = 8681.43

# ── 1. Market Prices ───────────────────────────────────────────────────────────

MARKET_SYMBOLS = {
    "SPX":  "^GSPC",
    "NDX":  "^IXIC",
    "VIX":  "^VIX",
    "GOLD": "GC=F",
    "OIL":  "CL=F",
    "10Y":  "^TNX",
    "EUR":  "EURUSD=X",
    "BTC":  "BTC-USD",
}

def fetch_market_snapshot():
    import yfinance as yf
    out = {}
    for label, sym in MARKET_SYMBOLS.items():
        try:
            h = yf.Ticker(sym).history(period="5d", interval="1d")
            if h.empty:
                continue
            last = float(h["Close"].iloc[-1])
            prev = float(h["Close"].iloc[-2]) if len(h) >= 2 else last
            chg  = last - prev
            pct  = (chg / prev * 100) if prev else 0.0
            out[label] = {"price": last, "change": chg, "pct": pct, "symbol": sym}
        except Exception:
            pass
    return out


def fetch_sp500_ytd():
    import yfinance as yf
    try:
        start = f"{datetime.now().year}-01-01"
        df = yf.download("^GSPC", start=start, progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        cols = df.columns.get_level_values(0) if hasattr(df.columns, "get_level_values") else df.columns
        df.columns = cols
        return round((float(df["Close"].iloc[-1]) - float(df["Close"].iloc[0]))
                     / float(df["Close"].iloc[0]) * 100, 2)
    except Exception:
        return None


def fetch_current_prices(tickers):
    import yfinance as yf
    prices = {}
    for tk in tickers:
        try:
            info = yf.Ticker(tk).info
            p = (info.get("regularMarketPrice")
                 or info.get("currentPrice")
                 or info.get("previousClose"))
            if p:
                prices[tk] = float(p)
        except Exception:
            pass
        if tk not in prices:
            try:
                h = yf.Ticker(tk).history(period="2d")
                if not h.empty:
                    prices[tk] = float(h["Close"].iloc[-1])
            except Exception:
                pass
    return prices


# ── 2. Portfolio ───────────────────────────────────────────────────────────────

def fetch_portfolio():
    """Returns list of position dicts with live prices and P&L."""
    # Try Google Sheets first
    positions = {}
    cash = FALLBACK_CASH
    sheet_ytd = None
    try:
        from stock_analysis import read_portfolio_sheet
        _, pos, sh_cash, sh_ytd = read_portfolio_sheet()
        if pos:
            positions = pos        # {"TICKER": {"shares": x, "cost_basis": y, "pnl_pct": z}}
            if sh_cash:
                cash = sh_cash
            sheet_ytd = sh_ytd
    except Exception as e:
        print(f"  Sheets fallback: {e}")

    if not positions:
        positions = {tk: {"shares": v["shares"], "cost_basis": v["cost_basis"], "pnl_pct": None}
                     for tk, v in FALLBACK_PORTFOLIO.items()}

    tickers = list(positions.keys())
    prices  = fetch_current_prices(tickers)

    holdings = []
    total_mv = 0.0
    total_cost_basis = 0.0
    for tk, pos in positions.items():
        shares    = float(pos.get("shares", 0) or 0)
        cost_ps   = float(pos.get("cost_basis", 0) or 0)   # per-share, from sheet
        price     = float(prices.get(tk, 0) or 0)
        mv        = shares * price
        total_cost = shares * cost_ps
        # Use sheet pnl_pct if available, else compute from live price vs cost
        sheet_pnl_pct = pos.get("pnl_pct")
        if sheet_pnl_pct is not None:
            pnl_pct = float(sheet_pnl_pct)
            pnl_d   = total_cost * pnl_pct / 100
        elif total_cost > 0:
            pnl_d   = mv - total_cost
            pnl_pct = (pnl_d / total_cost * 100)
        else:
            pnl_d   = 0.0
            pnl_pct = 0.0
        total_mv         += mv
        total_cost_basis += total_cost
        holdings.append({
            "ticker":   tk,
            "shares":   shares,
            "cost_ps":  cost_ps,
            "price":    price,
            "mv":       mv,
            "pnl_d":    pnl_d,
            "pnl_pct":  pnl_pct,
        })

    holdings.sort(key=lambda x: x["mv"], reverse=True)
    total_pnl = sum(h["pnl_d"] for h in holdings)
    total_pnl_pct = (total_pnl / total_cost_basis * 100) if total_cost_basis else 0.0
    totals = {
        "total_mv":      total_mv,
        "total_value":   total_mv + cash,
        "total_cost":    total_cost_basis,
        "total_pnl":     total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "cash":          cash,
        "sheet_ytd":     sheet_ytd,
    }
    return holdings, totals


# ── 3. Technical Signals ───────────────────────────────────────────────────────

def fetch_signals(tickers):
    """Get hybrid score + signal for each ticker from radar cache or score_stock."""
    cache_path = os.path.join(BASE_DIR, "radar_cache.json")
    try:
        cache = json.load(open(cache_path))
    except Exception:
        cache = {}
    signals = {}
    for tk in tickers:
        entry = cache.get(tk, {}).get("data", {})
        score = entry.get("score_hybrid") or entry.get("composite")
        sig   = entry.get("sig_hybrid") or entry.get("signal")
        if not score:
            try:
                from stock_analysis import score_stock
                r = score_stock(tk)
                if r:
                    score = r["score"]
                    sig   = r["signal"]
            except Exception:
                pass
        signals[tk] = {
            "score":  round(float(score), 2) if score else 5.0,
            "signal": str(sig) if sig else "Neutral",
        }
    return signals


def fetch_radar_top(n=5):
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
        d     = cache.get(tk, {}).get("data", {})
        score = float(d.get("score_hybrid") or d.get("composite") or 5.0)
        sig   = str(d.get("sig_hybrid") or d.get("signal") or "Neutral")
        up    = d.get("upside", "N/A")
        earn  = d.get("earn_date", "N/A")
        note  = ""
        if d.get("macd") == "Bullish":
            note = "MACD bullish"
        elif isinstance(d.get("rsi"), (int, float)):
            rsi = float(d["rsi"])
            note = "RSI oversold" if rsi < 35 else ("RSI overbought" if rsi > 70 else "")
        stocks.append({"ticker": tk, "score": round(score, 2), "signal": sig,
                       "upside": up, "earnings": earn, "note": note})
    stocks.sort(key=lambda x: x["score"], reverse=True)
    return stocks[:n]


# ── 4. News — Filtered to Macro Events ────────────────────────────────────────

_MACRO_KEYWORDS = {
    "federal reserve","fed ","fomc","powell","interest rate","rate hike","rate cut",
    "inflation","cpi","pce","ppi","deflation","stagflation",
    "gdp","recession","growth","economic data",
    "jobs","payroll","unemployment","nonfarm","labor market",
    "tariff","trade war","trade deal","sanction","wto","import duty",
    "geopolit","war","conflict","invasion","nato","iran","russia","ukraine","china",
    "opec","oil supply","crude supply","energy crisis",
    "dollar index","dxy","yen","yuan","euro","currency",
    "treasury yield","yield curve","10-year","bond market",
    "debt ceiling","bank failure","credit market","systemic risk",
    "earnings beat","earnings miss","earnings surprise","revenue miss",
}
_REJECT_KEYWORDS = {
    "best etf","top etf","etf to buy","should you buy","stock to buy","stocks to buy",
    "best stock","top stock","motley fool","zacks rank","seeking alpha picks",
    "dividend aristocrat","growth stock pick","penny stock","meme stock",
    "analyst raises","price target raised","upgrade to buy",
    "fund performance","mutual fund","hedge fund return",
}

def _is_macro_relevant(title: str) -> bool:
    tl = title.lower()
    if any(r in tl for r in _REJECT_KEYWORDS):
        return False
    return any(k in tl for k in _MACRO_KEYWORDS)

def fetch_macro_news(want=5):
    import urllib.request, xml.etree.ElementTree as ET, ssl as _ssl
    ctx = _ssl._create_unverified_context()
    feeds = [
        # Google News — specific macro search
        "https://news.google.com/rss/search?q=Federal+Reserve+interest+rate+inflation&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=GDP+jobs+tariffs+geopolitics+oil+supply&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=treasury+yield+dollar+currency+trade&hl=en-US&gl=US&ceid=US:en",
        # Yahoo Finance
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US",
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5ETNX&region=US&lang=en-US",
    ]
    seen, candidates = set(), []
    for url in feeds:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8, context=ctx) as r:
                root = ET.fromstring(r.read())
            for el in root.iter("item"):
                title = (el.findtext("title") or "").strip()
                pub   = (el.findtext("pubDate") or "").strip()
                src   = (el.findtext("source") or "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                candidates.append({"title": title, "pub": pub, "source": src or "Yahoo Finance"})
        except Exception:
            pass

    # Prefer macro-relevant, fall back to all if not enough
    macro = [c for c in candidates if _is_macro_relevant(c["title"])]
    result = macro if len(macro) >= 3 else candidates
    return result[:want]


def _pub_age(pub_str):
    try:
        from email.utils import parsedate_to_datetime
        dt   = parsedate_to_datetime(pub_str)
        mins = int((datetime.now(dt.tzinfo) - dt).total_seconds() / 60)
        if mins < 60:
            return f"{mins}m ago"
        if mins < 1440:
            return f"{mins // 60}h ago"
        return dt.strftime("%b %d")
    except Exception:
        return ""


# ── 5. Claude API ─────────────────────────────────────────────────────────────

def _claude(prompt: str, max_tokens=600):
    if not ANTHROPIC_KEY:
        return None
    try:
        import anthropic
        msg = anthropic.Anthropic(api_key=ANTHROPIC_KEY).messages.create(
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        print(f"  Claude API error: {e}")
        return None


def ai_verdict(market: dict, news: list, holdings: list) -> str:
    sp  = market.get("SPX", {})
    vix = market.get("VIX", {})
    top_hls = "\n".join(f"- {n['title']}" for n in news[:3])
    tickers  = ", ".join(h["ticker"] for h in holdings[:5])
    sp_chg   = sp.get("pct", 0.0)
    vix_val  = vix.get("price", 15.0)

    if ANTHROPIC_KEY:
        result = _claude(
            "You are a senior portfolio strategist. Based on the data below, write ONE sentence "
            "that tells the investor exactly what posture to take today.\n\n"
            "Format EXACTLY: [CIRCLE] [STANCE]. [Specific action referencing 1-2 asset names].\n"
            "- Use 🔴 for risk-off / defensive / wait\n"
            "- Use 🟢 for risk-on / add to winners / bullish\n"
            "- Use 🟡 for mixed / wait for clarity / neutral\n\n"
            f"S&P 500: {sp_chg:+.2f}% | VIX: {vix_val:.1f}\n"
            f"Top headlines:\n{top_hls}\n"
            f"Portfolio holdings: {tickers}\n\n"
            "Write ONE sentence only. Be decisive. Name specific assets.",
            max_tokens=80,
        )
        if result:
            return result

    # Fallback
    if vix_val > 25 or sp_chg < -1.0:
        return f"🔴 RISK-OFF. Elevated volatility ({vix_val:.0f} VIX) — stay defensive, watch GDX and cash."
    if sp_chg > 0.8 and vix_val < 18:
        return f"🟢 RISK-ON. Momentum building — consider adding to NVDA and GOOGL on strength."
    return f"🟡 MIXED. Wait for macro clarity before repositioning; S&P {sp_chg:+.1f}%."


def ai_news_analysis(headline: str, holdings: list) -> dict:
    """Returns {facts, market_why, portfolio_impact, watch_for}."""
    tickers = ", ".join(h["ticker"] for h in holdings)
    port_ctx = "; ".join(
        f"{h['ticker']} ({h['pnl_pct']:+.1f}% P&L)" for h in holdings[:6]
    )

    if ANTHROPIC_KEY:
        raw = _claude(
            f"Headline: \"{headline}\"\n"
            f"Investor's holdings: {tickers}\n"
            f"Current P&L context: {port_ctx}\n\n"
            "Write exactly FOUR short paragraphs separated by blank lines. "
            "No headers. No bullet points. Professional financial prose only.\n\n"
            "Paragraph 1 — FACTS: What happened, 2-3 sentences of objective facts from this headline.\n"
            "Paragraph 2 — MARKET IMPACT: Why this matters for financial markets broadly. "
            "Mention specific sectors, rates, or macro dynamics. 2-3 sentences.\n"
            "Paragraph 3 — PORTFOLIO IMPACT: How this affects these specific holdings: "
            f"{tickers}. Name each relevant ticker and say BULLISH or BEARISH for that position. 2-3 sentences.\n"
            "Paragraph 4 — WATCH FOR: One specific metric, date, or event to monitor next. 1 sentence.",
            max_tokens=450,
        )
        if raw:
            parts = [p.strip() for p in raw.split("\n\n") if p.strip()]
            if len(parts) >= 3:
                return {
                    "facts":            parts[0],
                    "market_why":       parts[1] if len(parts) > 1 else "",
                    "portfolio_impact": parts[2] if len(parts) > 2 else "",
                    "watch_for":        parts[3] if len(parts) > 3 else "",
                }

    # Fallback
    h = headline.lower()
    neg = sum(1 for w in ["fall","drop","risk","warn","cut","weak","decline","concern"] if w in h)
    pos = sum(1 for w in ["rise","gain","beat","strong","surge","rally","growth"] if w in h)
    bias = "positive" if pos > neg else ("negative" if neg > pos else "mixed")
    return {
        "facts":            f"This headline signals a {bias} macro development. "
                            f"Market participants are assessing the implications for risk assets.",
        "market_why":       "The development could shift risk appetite across equity and fixed income markets. "
                            "Investors should monitor follow-through in the next session.",
        "portfolio_impact": f"Holdings in this portfolio ({tickers[:60]}) "
                            "may experience near-term volatility depending on sector exposure.",
        "watch_for":        "Monitor price action in the opening session and any central bank commentary.",
    }


def ai_portfolio_stances(holdings: list, signals: dict, news: list) -> dict:
    """Returns {TICKER: {stance, reason}} for each holding."""
    top_hls = "\n".join(f"- {n['title']}" for n in news[:4])

    if ANTHROPIC_KEY:
        holding_lines = "\n".join(
            f"{h['ticker']}: {h['shares']:.0f}sh @ ${h['cost_ps']:.2f} cost, "
            f"current ${h['price']:.2f}, P&L {h['pnl_pct']:+.1f}%, "
            f"signal={signals.get(h['ticker'], {}).get('signal','N/A')}, "
            f"score={signals.get(h['ticker'], {}).get('score', 5.0)}/10"
            for h in holdings
        )
        raw = _claude(
            "You are a portfolio manager. Given today's macro headlines and each holding's profile, "
            "assign a STANCE and write one sentence REASON for each position.\n\n"
            f"TODAY'S MACRO HEADLINES:\n{top_hls}\n\n"
            f"HOLDINGS:\n{holding_lines}\n\n"
            "For each ticker respond on ONE line in this EXACT format:\n"
            "TICKER|STANCE|One sentence reason referencing today's news or the stock's score.\n\n"
            "STANCE must be exactly one of:\n"
            "  HOLD/ADD — actively bullish, consider sizing up\n"
            "  HOLD     — maintain position, no action needed\n"
            "  WATCH    — monitor closely, risk building\n"
            "  REVIEW   — consider reducing or exiting\n\n"
            "Output one line per holding, nothing else.",
            max_tokens=600,
        )
        if raw:
            stances = {}
            for line in raw.strip().splitlines():
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 3:
                    tk = parts[0].upper()
                    stances[tk] = {"stance": parts[1], "reason": parts[2]}
            if len(stances) >= len(holdings) // 2:
                return stances

    # Fallback based on signal + P&L
    out = {}
    for h in holdings:
        sig  = signals.get(h["ticker"], {}).get("signal", "Neutral").upper()
        pnl  = h["pnl_pct"]
        if "STRONG BUY" in sig or "STRONGBUY" in sig:
            stance = "HOLD/ADD"
            reason = f"Strong buy signal and positive momentum support adding to this position."
        elif "BUY" in sig and pnl > -10:
            stance = "HOLD/ADD"
            reason = f"Buy signal intact; technical setup favors maintaining or growing the position."
        elif "SELL" in sig or "STRONG SELL" in sig:
            stance = "REVIEW"
            reason = f"Sell signal active — review position size and consider reducing exposure."
        elif pnl < -15:
            stance = "WATCH"
            reason = f"Position down {pnl:.1f}% — monitor closely for further deterioration."
        else:
            stance = "HOLD"
            reason = f"Neutral signal; maintain current allocation and watch for directional clarity."
        out[h["ticker"]] = {"stance": stance, "reason": reason}
    return out


def ai_weekly_watch(holdings: list, news: list, signals: dict) -> str:
    tickers = ", ".join(h["ticker"] for h in holdings)
    top_hls = "\n".join(f"- {n['title']}" for n in news[:3])

    if ANTHROPIC_KEY:
        result = _claude(
            "You are a portfolio strategist. Identify ONE specific event, data release, or catalyst "
            "this week that matters most for this exact portfolio.\n\n"
            f"Holdings: {tickers}\n"
            f"This week's macro backdrop:\n{top_hls}\n\n"
            "Write 2-3 sentences: Name the specific event and its date if known. "
            "Then explain exactly how a beat/positive outcome vs a miss/negative outcome "
            "would affect THIS portfolio — mention specific tickers by name. "
            "Be concrete and direct. No hedging.",
            max_tokens=200,
        )
        if result:
            return result

    # Fallback
    return (
        "Watch for any Federal Reserve commentary or economic data releases this week, "
        "as rate expectations directly impact NVDA, GOOGL, and AMD valuations. "
        "A hawkish surprise would pressure growth-oriented positions while benefiting GDX."
    )


# ── 6. HTML ────────────────────────────────────────────────────────────────────

NAVY   = "#0B1F3A"
WHITE  = "#FFFFFF"
LGRAY  = "#F8FAFC"
GRAY   = "#6B7280"
BORDER = "#E2E8F0"
GREEN  = "#16A34A"
RED    = "#DC2626"
AMBER  = "#D97706"
BLUE   = "#2563EB"

def _pct_color(v):
    try:
        return GREEN if float(v) >= 0 else RED
    except Exception:
        return GRAY

def _price(v, decimals=2):
    try:
        v = float(v)
        if v == 0:
            return "—"
        if v >= 1000:
            return f"${v:,.0f}"
        return f"${v:,.{decimals}f}"
    except Exception:
        return "—"

def _pct(v, sign=True):
    try:
        v = float(v)
        return f"{'+'if v>=0 and sign else ''}{v:.2f}%"
    except Exception:
        return "—"

def _stance_cell(stance):
    s = str(stance).upper().strip()
    if "HOLD/ADD" in s or "HOLD ADD" in s:
        icon, bg, fg = "🟢", "#DCFCE7", "#15803D"
    elif s == "HOLD":
        icon, bg, fg = "🟡", "#FEF9C3", "#92400E"
    elif s == "WATCH":
        icon, bg, fg = "🔴", "#FEE2E2", "#DC2626"
    elif s == "REVIEW":
        icon, bg, fg = "⚫", "#F3F4F6", "#374151"
    else:
        icon, bg, fg = "🟡", "#FEF9C3", "#92400E"
    return (
        f'<span style="display:inline-block;padding:3px 10px;border-radius:4px;'
        f'font-size:10px;font-weight:700;letter-spacing:.5px;'
        f'background:{bg};color:{fg}">{icon} {s}</span>'
    )

def _relevance_badge(title):
    tl = title.lower()
    if any(k in tl for k in ["fed","fomc","powell","war","invasion","cpi","nonfarm","gdp"]):
        return f'<span style="font-size:9px;font-weight:700;letter-spacing:1px;padding:2px 7px;border-radius:3px;background:#FEE2E2;color:#DC2626">CRITICAL</span>'
    if any(k in tl for k in ["rate","inflation","tariff","oil","yield","trade"]):
        return f'<span style="font-size:9px;font-weight:700;letter-spacing:1px;padding:2px 7px;border-radius:3px;background:#FEF3C7;color:#92400E">HIGH</span>'
    return f'<span style="font-size:9px;font-weight:700;letter-spacing:1px;padding:2px 7px;border-radius:3px;background:#DBEAFE;color:#1D4ED8">MEDIUM</span>'

def _section(title, subtitle=""):
    sub = (f'<div style="font-size:10px;color:rgba(147,197,253,.8);margin-top:2px">{subtitle}</div>'
           if subtitle else "")
    return (
        f'<div style="background:{NAVY};padding:11px 20px">'
        f'<div style="font-size:9px;font-weight:700;letter-spacing:2.5px;'
        f'color:#93C5FD;text-transform:uppercase">{title}</div>{sub}</div>'
    )

def _th(label, align="left"):
    return (f'<th style="padding:9px 12px;font-size:8.5px;font-weight:700;'
            f'letter-spacing:1.5px;color:#94A3B8;text-transform:uppercase;'
            f'text-align:{align};white-space:nowrap;border-bottom:2px solid {BORDER}">'
            f'{label}</th>')

def _td(content, align="left", bold=False, color=None, small=False):
    c = f"color:{color};" if color else ""
    b = "font-weight:700;" if bold else ""
    s = "font-size:10px;" if small else "font-size:11px;"
    return (f'<td style="padding:9px 12px;{s}{b}{c}text-align:{align};'
            f'border-bottom:1px solid #F1F5F9">{content}</td>')


def build_html(verdict, market, news, analyses, holdings, totals,
               stances, signals, weekly_watch, radar):

    now     = datetime.now()
    date_s  = now.strftime("%A, %B %d, %Y")
    time_s  = "Pre-Market Session" if now.hour < 14 else "End of Day"
    gen_ts  = now.strftime("%Y-%m-%d %H:%M:%S UTC")

    def page(body):
        return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
* {{box-sizing:border-box;margin:0;padding:0}}
body {{background:#DCE3EC;font-family:Arial,Helvetica,'Helvetica Neue',sans-serif}}
table {{border-collapse:collapse}}
</style></head>
<body style="padding:16px 0">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
<table width="680" cellpadding="0" cellspacing="0"
  style="max-width:680px;width:100%;background:{WHITE}">
{body}
</table>
</td></tr></table>
</body></html>"""

    H = ""   # accumulate rows

    # ── HEADER ────────────────────────────────────────────────────────────────
    H += f"""
<tr><td>
<div style="background:{NAVY};padding:24px 28px 18px">
  <div style="font-size:9px;font-weight:700;letter-spacing:3.5px;color:#60A5FA;
    margin-bottom:5px">MOHAB CAPITAL</div>
  <div style="font-size:20px;font-weight:700;color:{WHITE};line-height:1.2">
    Daily Intelligence Brief</div>
  <div style="margin-top:10px;padding-top:10px;border-top:1px solid #1E3A5F;
    font-size:10px;color:#6B8CAE;letter-spacing:.5px">
    {date_s} &nbsp;&middot;&nbsp; {time_s} &nbsp;&middot;&nbsp; Powered by Claude AI
  </div>
</div>
</td></tr>
"""

    # ── MARKET SNAPSHOT BAR ────────────────────────────────────────────────────
    cells = ""
    for label, d in market.items():
        pct  = d.get("pct", 0.0)
        col  = GREEN if pct >= 0 else RED
        px   = d.get("price", 0)
        fmt  = f"{px:,.0f}" if px >= 1000 else (f"{px:.2f}" if px >= 1 else f"{px:.4f}")
        sign = "+" if pct >= 0 else ""
        cells += (
            f'<td style="padding:10px 8px;text-align:center;'
            f'border-right:1px solid {BORDER};white-space:nowrap">'
            f'<div style="font-size:8.5px;font-weight:700;letter-spacing:1px;'
            f'color:{GRAY};margin-bottom:2px">{label}</div>'
            f'<div style="font-size:12px;font-weight:700;color:#0F172A">{fmt}</div>'
            f'<div style="font-size:10px;font-weight:600;color:{col}">{sign}{pct:.2f}%</div>'
            f'</td>'
        )
    H += f"""
<tr><td style="border-bottom:3px solid {NAVY}">
<table width="100%" cellpadding="0" cellspacing="0">
<tr style="background:{LGRAY}">{cells}</tr>
</table>
</td></tr>
"""

    # ── TODAY'S VERDICT ────────────────────────────────────────────────────────
    v_lower = verdict.lower()
    if "🔴" in verdict or "risk-off" in v_lower:
        vbg, vborder = "#FEF2F2", "#FCA5A5"
    elif "🟢" in verdict or "risk-on" in v_lower:
        vbg, vborder = "#F0FDF4", "#86EFAC"
    else:
        vbg, vborder = "#FFFBEB", "#FCD34D"

    H += f"""
<tr><td>
<div style="background:{vbg};border-left:5px solid {vborder};
  padding:16px 22px;border-bottom:1px solid {BORDER}">
  <div style="font-size:9px;font-weight:700;letter-spacing:2px;color:{GRAY};
    margin-bottom:6px">TODAY'S VERDICT</div>
  <div style="font-size:16px;font-weight:700;color:#0F172A;line-height:1.4">
    {verdict}</div>
</div>
</td></tr>
"""

    # ── MARKET-MOVING NEWS ─────────────────────────────────────────────────────
    H += f'<tr><td style="padding-top:20px">{_section("MARKET-MOVING NEWS", "Macro events only — Fed · Rates · Inflation · GDP · Jobs · Tariffs · Geopolitics · Oil · FX")}</td></tr>\n'
    H += f'<tr><td style="border:1px solid {BORDER};border-top:none">'

    for i, (item, ana) in enumerate(zip(news, analyses)):
        bg    = WHITE if i % 2 == 0 else LGRAY
        age   = _pub_age(item.get("pub",""))
        src   = item.get("source","Yahoo Finance")
        badge = _relevance_badge(item["title"])

        # Build analysis paragraphs
        para_rows = ""
        for label, key, col in [
            ("WHAT HAPPENED",      "facts",            "#1E293B"),
            ("WHY IT MATTERS",     "market_why",       "#1E3A5F"),
            ("YOUR PORTFOLIO",     "portfolio_impact",  "#14532D"),
            ("WATCH FOR",          "watch_for",         "#78350F"),
        ]:
            text = ana.get(key, "")
            if not text:
                continue
            lbg = {"WHAT HAPPENED":"#F8FAFC","WHY IT MATTERS":"#F0F7FF",
                   "YOUR PORTFOLIO":"#F0FDF4","WATCH FOR":"#FFFBEB"}.get(label, WHITE)
            para_rows += (
                f'<div style="padding:10px 16px;background:{lbg};'
                f'border-left:3px solid {"#CBD5E1" if label=="WHAT HAPPENED" else "#3B82F6" if label=="WHY IT MATTERS" else "#22C55E" if label=="YOUR PORTFOLIO" else "#F59E0B"}">'
                f'<div style="font-size:8px;font-weight:700;letter-spacing:1.5px;color:{GRAY};'
                f'margin-bottom:4px">{label}</div>'
                f'<div style="font-size:11.5px;line-height:1.7;color:{col}">{text}</div>'
                f'</div>'
            )

        H += (
            f'<div style="padding:14px 16px;background:{bg};border-bottom:1px solid {BORDER}">'
            f'<div style="font-size:13px;font-weight:700;color:#0F172A;line-height:1.4;'
            f'margin-bottom:6px">{item["title"]}</div>'
            f'<div style="font-size:9.5px;color:{GRAY};margin-bottom:10px">'
            f'{src} &nbsp;&middot;&nbsp; {age} &nbsp;&nbsp;{badge}</div>'
            f'{para_rows}'
            f'</div>'
        )

    H += "</td></tr>\n"

    # ── PORTFOLIO — WHAT TO DO TODAY ───────────────────────────────────────────
    port_subtitle = "One action per position based on today's macro backdrop + technical signals"
    H += f'<tr><td style="padding-top:20px">{_section("PORTFOLIO — WHAT TO DO TODAY", port_subtitle)}</td></tr>\n'
    H += f'<tr><td><table width="100%" cellpadding="0" cellspacing="0">'
    H += f'<thead><tr style="background:#F8FAFC">'
    for lbl, al in [("TICKER","left"),("SHARES","right"),("AVG COST","right"),
                     ("CURRENT","right"),("P&L $","right"),("P&L %","right"),
                     ("STANCE","center"),("REASON","left")]:
        H += _th(lbl, al)
    H += "</tr></thead><tbody>"

    for i, h in enumerate(holdings):
        bg     = WHITE if i % 2 == 0 else LGRAY
        pnl_c  = _pct_color(h["pnl_pct"])
        stance_data = stances.get(h["ticker"], {"stance": "HOLD", "reason": ""})
        reason = stance_data.get("reason", "")
        stance = stance_data.get("stance", "HOLD")

        H += f'<tr style="background:{bg}">'
        H += _td(f'<span style="font-weight:700;color:{NAVY};font-size:12px">{h["ticker"]}</span>', "left")
        H += _td(f'{h["shares"]:.0f}', "right", color=GRAY)
        H += _td(_price(h["cost_ps"]), "right", color=GRAY)
        H += _td(_price(h["price"]), "right", bold=True, color="#0F172A")
        H += _td(
            f'{"+" if h["pnl_d"] >= 0 else ""}{h["pnl_d"]:,.0f}',
            "right", bold=True, color=pnl_c
        )
        H += _td(_pct(h["pnl_pct"]), "right", bold=True, color=pnl_c)
        H += _td(_stance_cell(stance), "center")
        H += _td(f'<span style="font-size:10px;color:#475569;line-height:1.5">{reason}</span>', "left")
        H += "</tr>\n"

    H += "</tbody></table></td></tr>\n"

    # ── ONE THING TO WATCH ────────────────────────────────────────────────────
    H += f'<tr><td style="padding-top:20px">{_section("ONE THING TO WATCH THIS WEEK")}</td></tr>\n'
    H += f"""<tr><td>
<div style="background:#FFFBEB;border:1px solid #FCD34D;border-top:none;padding:18px 22px">
  <div style="font-size:12.5px;line-height:1.8;color:#1E293B">{weekly_watch}</div>
</div>
</td></tr>
"""

    # ── RADAR — TOP OPPORTUNITIES ──────────────────────────────────────────────
    H += f'<tr><td style="padding-top:20px">{_section("TOP WATCHLIST OPPORTUNITIES", "Ranked by Hybrid Score")}</td></tr>\n'
    H += f'<tr><td><table width="100%" cellpadding="0" cellspacing="0"><thead><tr style="background:#F8FAFC">'
    for lbl, al in [("TICKER","left"),("SCORE","center"),("SIGNAL","center"),
                     ("UPSIDE","right"),("EARNINGS","center"),("NOTE","left")]:
        H += _th(lbl, al)
    H += "</tr></thead><tbody>"

    for i, r in enumerate(radar):
        bg    = WHITE if i % 2 == 0 else LGRAY
        score = float(r["score"])
        bar_w = int(score * 10)
        bar_c = GREEN if score >= 6.5 else (AMBER if score >= 5 else RED)
        up    = r.get("upside","N/A")
        try:
            up = f"{float(up):+.1f}%" if up not in (None,"N/A","") else "N/A"
        except Exception:
            pass
        H += f'<tr style="background:{bg}">'
        H += _td(f'<span style="font-weight:700;color:{NAVY};font-size:12px">{r["ticker"]}</span>', "left")
        H += (f'<td style="padding:9px 12px;text-align:center;border-bottom:1px solid #F1F5F9">'
              f'<div style="font-size:12px;font-weight:700;color:#0F172A">{r["score"]}/10</div>'
              f'<div style="width:48px;height:3px;background:#E2E8F0;border-radius:2px;'
              f'margin:3px auto;overflow:hidden">'
              f'<div style="width:{bar_w}%;height:100%;background:{bar_c}"></div>'
              f'</div></td>')
        H += _td(f'<span style="font-size:10px;font-weight:700;color:{GREEN if "buy" in r["signal"].lower() else (RED if "sell" in r["signal"].lower() else AMBER)}">{r["signal"]}</span>', "center")
        H += _td(up, "right", bold=True, color=GREEN)
        H += _td(r.get("earnings","N/A"), "center", small=True, color=GRAY)
        H += _td(r.get("note",""), "left", small=True, color=GRAY)
        H += "</tr>\n"
    H += "</tbody></table></td></tr>\n"

    # ── FOOTER ─────────────────────────────────────────────────────────────────
    sp_ytd = fetch_sp500_ytd()
    port_ytd = totals.get("sheet_ytd")
    # Compute portfolio YTD from P&L if not in sheet
    if port_ytd is None:
        port_ytd = totals.get("total_pnl_pct")

    ytd_line = ""
    if port_ytd is not None and sp_ytd:
        bps = int(round((port_ytd - sp_ytd) * 100))
        dir_word = "outperforming" if bps >= 0 else "underperforming"
        ytd_line = (f"Portfolio YTD: {port_ytd:+.1f}% &nbsp;&middot;&nbsp; "
                    f"S&P 500 YTD: {sp_ytd:+.1f}% &nbsp;&middot;&nbsp; "
                    f"Alpha: {dir_word} by {abs(bps)}bps")

    pnl_c = GREEN if totals["total_pnl"] >= 0 else RED
    H += f"""
<tr><td style="padding-top:20px">
<div style="background:{NAVY};padding:14px 22px">
<table width="100%" cellpadding="0" cellspacing="0"><tr>
  <td style="padding-right:20px">
    <div style="font-size:8px;letter-spacing:1.5px;font-weight:700;color:#60A5FA">PORTFOLIO VALUE</div>
    <div style="font-size:17px;font-weight:700;color:{WHITE}">${totals['total_value']:,.0f}</div>
  </td>
  <td style="padding:0 20px;border-left:1px solid #1E3A5F">
    <div style="font-size:8px;letter-spacing:1.5px;font-weight:700;color:#60A5FA">CASH</div>
    <div style="font-size:17px;font-weight:700;color:{WHITE}">${totals['cash']:,.0f}</div>
  </td>
  <td style="padding-left:20px;border-left:1px solid #1E3A5F">
    <div style="font-size:8px;letter-spacing:1.5px;font-weight:700;color:#60A5FA">UNREALIZED P&amp;L</div>
    <div style="font-size:17px;font-weight:700;color:{"#86EFAC" if totals["total_pnl"]>=0 else "#FCA5A5"}">
      {"+" if totals["total_pnl"]>=0 else ""}{totals["total_pnl"]:,.0f}
      <span style="font-size:12px">({totals["total_pnl_pct"]:+.1f}%)</span></div>
  </td>
</tr></table>
</div>
<div style="padding:12px 22px;background:{LGRAY};border-top:none;text-align:center">
  <div style="font-size:10px;color:{GRAY};margin-bottom:4px">{ytd_line}</div>
  <div style="font-size:9px;color:#94A3B8">Generated {gen_ts} &nbsp;&middot;&nbsp; Not investment advice</div>
</div>
</td></tr>
"""

    return page(H)


# ── 7. Send Email ──────────────────────────────────────────────────────────────

def send_email(html_body: str) -> bool:
    subject = f"Mohab Capital | Daily Brief — {datetime.now().strftime('%b %d, %Y')}"
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
            srv.ehlo(); srv.starttls(context=ctx)
            srv.login(SENDER_EMAIL, GMAIL_APP_PW.replace(" ", ""))
            srv.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        print(f"  Sent to {RECEIVER_EMAIL}")
        return True
    except smtplib.SMTPAuthenticationError:
        print("  AUTH FAILED — check GMAIL_APP_PASSWORD")
        return False
    except Exception as e:
        print(f"  Send failed: {e}")
        return False


# ── 8. Main ────────────────────────────────────────────────────────────────────

def run(send=True, save=True):
    t0 = time.time()
    print("\n" + "="*60)
    print("  MOHAB CAPITAL | DAILY INTELLIGENCE BRIEF")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    ai_mode = "Claude API (claude-sonnet-4-6)" if ANTHROPIC_KEY else "rule-based fallback (ANTHROPIC_API_KEY not set)"
    print(f"  AI: {ai_mode}")
    print("="*60)

    print("\n  [1/8] Market snapshot...")
    market = fetch_market_snapshot()
    print(f"        {len(market)}/8 instruments")

    print("  [2/8] Portfolio from Google Sheets...")
    holdings, totals = fetch_portfolio()
    print(f"        {len(holdings)} holdings, cash ${totals['cash']:,.0f}")

    print("  [3/8] Technical signals...")
    tickers = [h["ticker"] for h in holdings]
    signals = fetch_signals(tickers)

    print("  [4/8] Radar watchlist...")
    radar = fetch_radar_top(5)

    print("  [5/8] Macro news (filtered)...")
    news = fetch_macro_news(want=5)
    print(f"        {len(news)} macro headlines")

    print("  [6/8] AI verdict...")
    verdict = ai_verdict(market, news, holdings)
    print(f"        {verdict[:60]}...")

    print("  [7/8] AI news analysis (4 paragraphs per story)...")
    analyses = []
    for i, item in enumerate(news):
        print(f"        Story {i+1}/{len(news)}: {item['title'][:50]}...")
        analyses.append(ai_news_analysis(item["title"], holdings))

    print("  [8/8] AI portfolio stances + weekly watch...")
    stances      = ai_portfolio_stances(holdings, signals, news)
    weekly_watch = ai_weekly_watch(holdings, news, signals)

    print("\n  Building HTML...")
    html = build_html(
        verdict, market, news, analyses,
        holdings, totals, stances, signals,
        weekly_watch, radar,
    )

    if save:
        with open(REPORT_HTML, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  Saved → {REPORT_HTML}")

    if send:
        ok = send_email(html)
        if ok:
            print(f"\n  CONFIRMATION: Report delivered to {RECEIVER_EMAIL}")
        else:
            print("\n  FAILED: Email not sent.")
    else:
        ok = True

    print(f"  Total time: {time.time()-t0:.1f}s")
    print("="*60 + "\n")
    return ok


if __name__ == "__main__":
    do_send = "--save" not in sys.argv
    run(send=do_send, save=True)
