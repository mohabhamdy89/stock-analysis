#!/usr/bin/env python3
"""
Mohab Capital | Breaking News Alert System
Monitors RSS feeds every 20 minutes and sends immediate email alerts
when Claude AI rates a headline as CRITICAL or HIGH market impact.

Runs via launchd: com.mohab.breakingnews.plist (StartInterval=1200)
"""

import os, sys, json, ssl, time, smtplib, hashlib, warnings
import urllib.request
import xml.etree.ElementTree as ET
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
SENT_FILE      = os.path.join(BASE_DIR, "breaking_news_sent.json")
DEDUP_TTL_H    = 48   # hours before a headline hash expires
MAX_ALERTS_RUN = 3    # maximum emails per single check (flood guard)
PORTFOLIO      = ["GOOGL", "MU", "AMD", "NVDA", "SPUS", "INTC", "SPCX", "GDX"]

# ── RSS Feeds (Reuters dead, AP rsshub 403 — using Google News + Yahoo) ───────
RSS_FEEDS = [
    ("Yahoo Finance",       "https://finance.yahoo.com/rss/topstories"),
    ("Yahoo Finance SPX",   "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US"),
    ("Google News Fed/CPI", "https://news.google.com/rss/search?q=Federal+Reserve+interest+rate+inflation+CPI&hl=en-US&gl=US&ceid=US:en"),
    ("Google News Macro",   "https://news.google.com/rss/search?q=tariff+trade+war+geopolitical+invasion+OPEC+oil&hl=en-US&gl=US&ceid=US:en"),
    ("Google News Crisis",  "https://news.google.com/rss/search?q=market+crash+recession+bank+failure+GDP+jobs+NFP&hl=en-US&gl=US&ceid=US:en"),
]

# ── Trigger keywords (case-insensitive substring match) ───────────────────────
TRIGGER_KEYWORDS = [
    "fed ", "federal reserve", "fomc", "interest rate", "rate hike", "rate cut",
    "inflation", " cpi ", "pce", "ppi", " gdp", "jobs report", " nfp", "nonfarm",
    "tariff", "sanction", "trade war", "china ", "iran ", "russia ", "ukraine",
    "oil supply", "opec", "market crash", "circuit breaker",
    "earnings miss", "earnings beat", "recession", "bank failure",
    "debt ceiling", "geopolit", " war ", "invasion", "currency crisis",
    "trump", "executive order", "nuclear",
]

# ── Heuristic severity (used when ANTHROPIC_KEY not set) ──────────────────────
_CRITICAL_KW = {
    "nuclear strike", "nuclear attack", "nuclear war",
    "troops invade", "military invasion", "ground invasion",
    "stock market crash", "market circuit breaker",
    "bank failure", "bank run", "bank collapse",
    "currency crisis", "currency collapse",
    "debt ceiling default", "government shutdown",
}
_HIGH_KW = {
    "fed raises", "fed cuts", "fed hikes", "fomc raises", "fomc cuts",
    "rate hike decision", "rate cut decision", "fomc decision",
    "nonfarm payroll", "jobs report shows", "nfp beats", "nfp misses",
    "earnings miss", "earnings beat",
    "gdp contracts", "recession confirmed",
    "opec cuts output", "opec increases output", "oil supply shock",
}


# ── 1. Deduplication store ─────────────────────────────────────────────────────

def _load_sent() -> dict:
    try:
        return json.load(open(SENT_FILE))
    except Exception:
        return {}


def _save_sent(store: dict):
    try:
        with open(SENT_FILE, "w") as f:
            json.dump(store, f, indent=2)
    except Exception as e:
        print(f"  [WARN] Could not save sent store: {e}")


def _prune_sent(store: dict) -> dict:
    """Remove entries older than DEDUP_TTL_H hours."""
    cutoff = (datetime.utcnow() - timedelta(hours=DEDUP_TTL_H)).isoformat()
    return {k: v for k, v in store.items() if v.get("sent_at", "") > cutoff}


def _headline_hash(title: str) -> str:
    return hashlib.sha1(title.lower().strip().encode()).hexdigest()[:16]


def _already_sent(title: str, store: dict) -> bool:
    return _headline_hash(title) in store


# ── 2. RSS Fetching ────────────────────────────────────────────────────────────

_SSL_CTX = ssl._create_unverified_context()


def fetch_all_headlines() -> list:
    """Fetch from all feeds, return deduplicated list of {title, source, pub, link}."""
    seen_titles, items = set(), []
    for feed_name, url in RSS_FEEDS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as r:
                root = ET.fromstring(r.read())
            count = 0
            for el in root.iter("item"):
                title = (el.findtext("title") or "").strip()
                link  = (el.findtext("link")  or "").strip()
                pub   = (el.findtext("pubDate") or "").strip()
                if not title or title in seen_titles:
                    continue
                if not _is_recent(pub, max_hours=6):
                    continue
                seen_titles.add(title)
                items.append({"title": title, "source": feed_name,
                               "link": link, "pub": pub})
                count += 1
            print(f"  Feed OK  [{feed_name}] — {count} new headlines")
        except Exception as e:
            print(f"  Feed FAIL [{feed_name}]: {str(e)[:80]}")
    return items


def _matches_trigger(title: str) -> bool:
    tl = " " + title.lower() + " "
    return any(kw in tl for kw in TRIGGER_KEYWORDS)


def filter_headlines(items: list) -> list:
    return [i for i in items if _matches_trigger(i["title"])]


# ── 3. Claude API Assessment ───────────────────────────────────────────────────

def assess_with_claude(headline: str, source: str):
    if not ANTHROPIC_KEY:
        return None
    try:
        import anthropic
        port = ", ".join(PORTFOLIO)
        prompt = (
            "You are a senior market analyst. Rate this headline's immediate market impact.\n\n"
            f"Headline: {headline}\n"
            f"Source: {source}\n"
            f"Investor portfolio: {port}\n\n"
            "Respond in valid JSON only — no extra text, no markdown:\n"
            "{\n"
            '  "rating": "CRITICAL" or "HIGH" or "MEDIUM" or "LOW",\n'
            '  "reasoning": "One sentence explaining the rating.",\n'
            '  "affected_sectors": ["sector1", "sector2"],\n'
            '  "portfolio_impact": {"TICKER": "bullish" or "bearish" or "neutral"},\n'
            '  "action": "One clear sentence: what should the investor consider right now."\n'
            "}\n\n"
            "Only include portfolio tickers actually affected. "
            "CRITICAL = immediate severe market reaction expected. "
            "HIGH = significant move likely within 24h. "
            "MEDIUM = notable but contained. LOW = minimal impact."
        )
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=350,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        # Robustly extract JSON even if Claude adds extra text
        start = text.find("{")
        end   = text.rfind("}") + 1
        if start >= 0 and end > start:
            result = json.loads(text[start:end])
            # Normalise rating to uppercase
            result["rating"] = str(result.get("rating", "MEDIUM")).upper()
            return result
    except Exception as e:
        print(f"  Claude error: {e}")
    return None


def heuristic_assessment(headline: str) -> dict:
    """Rule-based fallback when ANTHROPIC_KEY is not set."""
    tl = " " + headline.lower() + " "
    if any(k in tl for k in _CRITICAL_KW):
        rating = "CRITICAL"
    elif any(k in tl for k in _HIGH_KW):
        rating = "HIGH"
    else:
        rating = "MEDIUM"

    # Rough sector + portfolio impact detection
    impact = {}
    if any(k in tl for k in ["tech", "ai ", "chip", "semiconductor", "nvda", "amd", "nvidia", "intel"]):
        bias = "bearish" if any(k in tl for k in ["crash", "decline", "fall", "concern"]) else "bullish"
        for tk in ["NVDA", "AMD", "INTC", "GOOGL"]: impact[tk] = bias
    if any(k in tl for k in ["gold", "safe haven", "risk-off", "geopolit", " war ", "iran", "ukraine", "russia", "invasion", "nuclear"]):
        impact["GDX"] = "bullish"
    if any(k in tl for k in ["oil", "crude", "opec", "energy"]):
        impact["GDX"] = "bullish"
    if any(k in tl for k in ["rate hike", "higher rates", "hawkish"]):
        for tk in ["NVDA", "AMD", "GOOGL", "MU"]: impact[tk] = "bearish"
        impact["GDX"] = impact.get("GDX", "neutral")
    if not impact:
        impact = {tk: "monitor" for tk in PORTFOLIO[:4]}

    sectors = []
    if any(k in tl for k in ["fed", "rate", "inflation", "gdp", "jobs"]): sectors.append("Macro")
    if any(k in tl for k in ["tech", "ai", "chip", "semiconductor"]): sectors.append("Technology")
    if any(k in tl for k in ["oil", "energy", "opec"]): sectors.append("Energy")
    if any(k in tl for k in ["gold", "safe haven", "war", "geopolit"]): sectors.append("Commodities / Defense")
    if not sectors: sectors = ["Broad Market"]

    return {
        "rating":           rating,
        "reasoning":        "Matched high-priority trigger keywords — Claude API unavailable.",
        "affected_sectors": sectors,
        "portfolio_impact": impact,
        "action":           "Monitor this development closely and assess exposure to affected holdings.",
    }


# ── 4. Email Alert ─────────────────────────────────────────────────────────────

def _parse_pub_dt(pub_str: str):
    """Return UTC-aware datetime from RFC-2822 pubDate string, or None."""
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(pub_str)
    except Exception:
        return None


def _is_recent(pub_str: str, max_hours: int = 6) -> bool:
    """Return True if article is within max_hours old (or has no parseable date)."""
    dt = _parse_pub_dt(pub_str)
    if dt is None:
        return True  # no date → don't filter out
    from datetime import timezone
    age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    return age_h <= max_hours


def _pub_fmt(pub_str: str) -> str:
    try:
        dt   = _parse_pub_dt(pub_str)
        if dt is None:
            return pub_str[:20] if pub_str else "just now"
        from datetime import timezone
        mins = int((datetime.now(timezone.utc) - dt).total_seconds() / 60)
        if mins < 60:   return f"{mins}m ago"
        if mins < 1440: return f"{mins // 60}h ago"
        return dt.strftime("%b %d, %H:%M")
    except Exception:
        return pub_str[:20] if pub_str else "just now"


def build_alert_html(item: dict, assessment: dict) -> str:
    rating   = assessment.get("rating", "HIGH")
    reason   = assessment.get("reasoning", "")
    sectors  = ", ".join(assessment.get("affected_sectors", []))
    action   = assessment.get("action", "")
    impacts  = assessment.get("portfolio_impact", {})
    age      = _pub_fmt(item.get("pub", ""))
    source   = item.get("source", "")
    link     = item.get("link", "")
    headline = item["title"]
    now_ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Color scheme by severity
    if rating == "CRITICAL":
        hdr_bg, hdr_badge_bg, accent = "#7F1D1D", "#DC2626", "#FEE2E2"
        badge_label = "CRITICAL"
    else:
        hdr_bg, hdr_badge_bg, accent = "#78350F", "#D97706", "#FEF3C7"
        badge_label = "HIGH"

    # Build portfolio impact rows
    impact_rows = ""
    for tk, bias in impacts.items():
        bias_upper = str(bias).upper()
        if "BULL" in bias_upper:
            bias_col, bias_bg = "#15803D", "#DCFCE7"
        elif "BEAR" in bias_upper:
            bias_col, bias_bg = "#DC2626", "#FEE2E2"
        else:
            bias_col, bias_bg = "#92400E", "#FEF3C7"
        impact_rows += (
            f'<tr>'
            f'<td style="padding:7px 12px;font-weight:700;font-size:12px;color:#0F172A;'
            f'border-bottom:1px solid #F1F5F9">{tk}</td>'
            f'<td style="padding:7px 12px;border-bottom:1px solid #F1F5F9">'
            f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
            f'font-size:10px;font-weight:700;letter-spacing:.5px;'
            f'background:{bias_bg};color:{bias_col}">{bias_upper}</span></td>'
            f'</tr>'
        )

    link_html = (
        f'<a href="{link}" style="color:#2563EB;font-size:11px;text-decoration:none">'
        f'Read full article &rarr;</a>'
        if link else ""
    )

    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
* {{box-sizing:border-box;margin:0;padding:0}}
body {{background:#E2E8F0;font-family:Arial,Helvetica,'Helvetica Neue',sans-serif}}
table {{border-collapse:collapse}}
</style></head>
<body style="padding:16px 0">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0"
  style="max-width:600px;width:100%;background:#FFFFFF">

<!-- ALERT HEADER -->
<tr><td>
<div style="background:{hdr_bg};padding:20px 24px">
  <div style="font-size:9px;font-weight:700;letter-spacing:3px;color:rgba(255,255,255,.6);
    margin-bottom:6px">MOHAB CAPITAL · BREAKING ALERT</div>
  <div style="display:inline-block;padding:4px 12px;border-radius:4px;
    background:{hdr_badge_bg};margin-bottom:10px">
    <span style="font-size:11px;font-weight:700;letter-spacing:1.5px;color:#FFFFFF">
      &#128680; {badge_label} IMPACT</span>
  </div>
  <div style="font-size:9px;color:rgba(255,255,255,.5);margin-top:4px">
    {source} &nbsp;&middot;&nbsp; {age}
  </div>
</div>
</td></tr>

<!-- HEADLINE -->
<tr><td>
<div style="padding:20px 24px 16px;border-bottom:2px solid {accent}">
  <div style="font-size:17px;font-weight:700;color:#0F172A;line-height:1.4">
    {headline}</div>
  <div style="margin-top:10px">{link_html}</div>
</div>
</td></tr>

<!-- IMPACT ASSESSMENT -->
<tr><td>
<div style="padding:16px 24px;background:#F8FAFC;border-bottom:1px solid #E2E8F0">
  <div style="font-size:8.5px;font-weight:700;letter-spacing:1.5px;color:#64748B;
    margin-bottom:8px">IMPACT ASSESSMENT</div>
  <div style="font-size:12px;color:#1E293B;line-height:1.6">{reason}</div>
  <div style="font-size:10px;color:#64748B;margin-top:6px">
    Affected sectors: <strong>{sectors}</strong></div>
</div>
</td></tr>

<!-- PORTFOLIO IMPACT TABLE -->
<tr><td>
<div style="padding:16px 24px 8px">
  <div style="font-size:8.5px;font-weight:700;letter-spacing:1.5px;color:#64748B;
    margin-bottom:10px">PORTFOLIO IMPACT</div>
  <table width="100%" cellpadding="0" cellspacing="0"
    style="border:1px solid #E2E8F0;border-radius:6px;overflow:hidden">
    <thead>
    <tr style="background:#F1F5F9">
      <th style="padding:7px 12px;font-size:8.5px;font-weight:700;letter-spacing:1px;
        color:#94A3B8;text-align:left;border-bottom:1px solid #E2E8F0">HOLDING</th>
      <th style="padding:7px 12px;font-size:8.5px;font-weight:700;letter-spacing:1px;
        color:#94A3B8;text-align:left;border-bottom:1px solid #E2E8F0">OUTLOOK</th>
    </tr>
    </thead>
    <tbody>{impact_rows}</tbody>
  </table>
</div>
</td></tr>

<!-- ACTION -->
<tr><td>
<div style="margin:12px 24px 20px;padding:14px 18px;
  background:{accent};border-left:4px solid {hdr_badge_bg};border-radius:0 6px 6px 0">
  <div style="font-size:8.5px;font-weight:700;letter-spacing:1.5px;
    color:{hdr_badge_bg};margin-bottom:6px">SUGGESTED ACTION</div>
  <div style="font-size:13px;font-weight:700;color:#0F172A;line-height:1.5">
    {action}</div>
</div>
</td></tr>

<!-- FOOTER -->
<tr><td>
<div style="padding:12px 24px;background:#F8FAFC;border-top:1px solid #E2E8F0;
  text-align:center">
  <div style="font-size:9px;color:#94A3B8">
    Mohab Capital Intelligence &nbsp;&middot;&nbsp; Alert generated {now_ts}
  </div>
  <div style="font-size:9px;color:#CBD5E1;margin-top:3px">
    Not investment advice. Automated alert from breaking_news_alert.py
  </div>
</div>
</td></tr>

</table></td></tr></table>
</body></html>"""


def send_alert(item: dict, assessment: dict) -> bool:
    rating   = assessment.get("rating", "HIGH")
    # Truncate headline for subject line
    short = item["title"][:70] + ("…" if len(item["title"]) > 70 else "")
    subject = f"🚨 [{rating}] Market Alert — {short}"

    msg            = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = RECEIVER_EMAIL
    msg.attach(MIMEText(build_alert_html(item, assessment), "html"))

    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
        with smtplib.SMTP("smtp.gmail.com", 587) as srv:
            srv.ehlo(); srv.starttls(context=ctx)
            srv.login(SENDER_EMAIL, GMAIL_APP_PW.replace(" ", ""))
            srv.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        print(f"  SENT  [{rating}] {item['title'][:70]}")
        return True
    except Exception as e:
        print(f"  EMAIL FAIL: {e}")
        return False


# ── 5. Main check loop ─────────────────────────────────────────────────────────

def run_check(force_send=False):
    t0  = time.time()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[{now}] Breaking News Check")
    print("=" * 55)

    # Load + prune dedup store
    store = _prune_sent(_load_sent())

    # Fetch all feeds
    print("Fetching feeds...")
    all_items = fetch_all_headlines()
    print(f"  Total headlines: {len(all_items)}")

    # Filter by trigger keywords
    candidates = filter_headlines(all_items)
    print(f"  After keyword filter: {len(candidates)}")

    # Check each candidate
    alerts_sent = 0
    for item in candidates:
        title = item["title"]

        # Skip if already alerted
        if not force_send and _already_sent(title, store):
            continue

        print(f"\n  NEW: {title[:75]}")

        # Assess impact
        assessment = assess_with_claude(title, item.get("source", ""))
        if assessment:
            print(f"       Claude → {assessment['rating']}")
        else:
            assessment = heuristic_assessment(title)
            print(f"       Heuristic → {assessment['rating']}")

        rating = assessment.get("rating", "MEDIUM")

        # Enforce per-run flood guard
        if alerts_sent >= MAX_ALERTS_RUN:
            print(f"  FLOOD GUARD: reached {MAX_ALERTS_RUN} alerts — stopping early")
            break

        # Send alert only for CRITICAL or HIGH
        if rating in ("CRITICAL", "HIGH"):
            sent = send_alert(item, assessment)
            if sent:
                alerts_sent += 1
                store[_headline_hash(title)] = {
                    "title":   title,
                    "rating":  rating,
                    "sent_at": datetime.utcnow().isoformat(),
                }
        else:
            print(f"       Skipped ({rating} — below threshold)")
            # Still mark as seen so we don't re-evaluate it
            store[_headline_hash(title)] = {
                "title":   title,
                "rating":  rating,
                "sent_at": datetime.utcnow().isoformat(),
            }

    _save_sent(store)

    elapsed = time.time() - t0
    print(f"\n  Done — {alerts_sent} alert(s) sent in {elapsed:.1f}s")
    print("=" * 55 + "\n")
    return alerts_sent


if __name__ == "__main__":
    force = "--force" in sys.argv
    run_check(force_send=force)
