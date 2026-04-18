#!/usr/bin/env python3
"""
WhatsApp Price Alert System
────────────────────────────────────────────────────────────────
Fires two kinds of alerts during US market hours (9:30am–4pm EST):

  🚨 PRICE ALERT   — stock moves ±5% from yesterday's close
  📊 SIGNAL CHANGE — technical signal upgrades or downgrades
                     (e.g. BUY → STRONG BUY, NEUTRAL → SELL)

Alerts are deduplicated per day via alert_state.json.
Signal history is persisted in signal_history.json.

Run modes
─────────────────────────────────────────────────────────────────
  python3 price_alerts.py          → one check-and-alert pass (used by launchd)
  python3 price_alerts.py --test   → force-run ignoring market hours
  python3 price_alerts.py --setup  → install / reload the launchd agent and exit
"""

import sys, os, json, socket
from datetime import datetime, date
from typing import Optional
import pytz
import yfinance as yf

# ── Force IPv4 for all outbound connections ────────────────────────────────────
# iPhone hotspot NAT64 breaks TLS to api.twilio.com; IPv4 works fine.
_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = _ipv4_getaddrinfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stock_analysis import score_stock, PORTFOLIOS, read_portfolio_sheet

# ── Twilio / WhatsApp config ───────────────────────────────────────────────────
ACCOUNT_SID     = "ACe9139834482e433d802d69a7bbc14865"
AUTH_TOKEN      = "f2cafc2f1718e912b1ba4ec81bbaa358"
TWILIO_WA       = "whatsapp:+14155238886"
MY_WA           = "whatsapp:+201220605072"

# ── Alert thresholds ───────────────────────────────────────────────────────────
PRICE_THRESHOLD = 5.0          # % daily move that triggers a price alert

# ── File paths ─────────────────────────────────────────────────────────────────
_DIR            = os.path.dirname(os.path.abspath(__file__))
STATE_FILE      = os.path.join(_DIR, "alert_state.json")
SIGNAL_FILE     = os.path.join(_DIR, "signal_history.json")
LOG_FILE        = os.path.join(_DIR, "price_alerts.log")

# ── Market hours (EST / New York) ──────────────────────────────────────────────
_TZ             = pytz.timezone("America/New_York")
_OPEN           = (9, 30)
_CLOSE          = (16, 0)


# ── Helpers ────────────────────────────────────────────────────────────────────

def log(msg: str):
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def is_market_hours() -> bool:
    now = datetime.now(_TZ)
    if now.weekday() >= 5:          # Saturday / Sunday
        return False
    t = (now.hour, now.minute)
    return _OPEN <= t < _CLOSE


def _load_json(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_json(path: str, data: dict):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _today() -> str:
    return date.today().isoformat()


# ── State helpers (deduplication) ─────────────────────────────────────────────

def already_alerted(state: dict, key: str) -> bool:
    return state.get(_today(), {}).get(key, False)


def mark_alerted(state: dict, key: str) -> dict:
    today = _today()
    if today not in state:
        state[today] = {}
    state[today][key] = True
    # Purge dates older than today to keep the file small
    state = {k: v for k, v in state.items() if k == today}
    _save_json(STATE_FILE, state)
    return state


# ── Signal history ─────────────────────────────────────────────────────────────

def load_signal_history() -> dict:
    return _load_json(SIGNAL_FILE)


def save_signal_history(history: dict):
    _save_json(SIGNAL_FILE, history)


# ── Price data ─────────────────────────────────────────────────────────────────

def get_price_data(ticker: str) -> Optional[dict]:
    """Returns yesterday_close, current price, and % change."""
    try:
        df = yf.download(ticker, period="5d", interval="1d",
                         progress=False, auto_adjust=True)
        if df is None or df.empty or len(df) < 2:
            return None
        if hasattr(df.columns, "get_level_values"):
            df.columns = df.columns.get_level_values(0)
        prev  = float(df["Close"].iloc[-2])
        price = float(df["Close"].iloc[-1])
        pct   = (price - prev) / prev * 100
        return {"prev_close": prev, "price": price, "pct_change": pct}
    except Exception as e:
        log(f"  ⚠  {ticker} fetch error: {e}")
        return None


# ── WhatsApp sender ────────────────────────────────────────────────────────────

def send_whatsapp(body: str) -> bool:
    try:
        from twilio.rest import Client
        Client(ACCOUNT_SID, AUTH_TOKEN).messages.create(
            from_=TWILIO_WA, to=MY_WA, body=body)
        log(f"  ✅ Sent: {body[:80]}...")
        return True
    except Exception as e:
        log(f"  ❌ Twilio error: {e}")
        return False


# ── Alert builders ─────────────────────────────────────────────────────────────

def price_alert_msg(ticker: str, pct: float, price: float,
                    signal: str, shares: float, pnl: float) -> str:
    direction = "UP" if pct >= 0 else "DOWN"
    sign      = "+" if pnl >= 0 else ""
    return (
        f"🚨 PRICE ALERT: {ticker} is {direction} {abs(pct):.1f}% today | "
        f"Price: ${price:.2f} | "
        f"Signal: {signal} | "
        f"Position: {int(shares)} shares | "
        f"P&L today: {sign}${abs(pnl):.0f}"
    )


def signal_change_msg(ticker: str, old_sig: str, new_sig: str,
                      price: float, shares: float) -> str:
    arrow = "upgraded" if _signal_rank(new_sig) > _signal_rank(old_sig) else "downgraded"
    return (
        f"📊 SIGNAL CHANGE: {ticker} {arrow} from {old_sig} to {new_sig} | "
        f"Price: ${price:.2f} | "
        f"Your position: {int(shares)} shares"
    )


_RANK = {"STRONG SELL": 1, "SELL": 2, "NEUTRAL": 3, "BUY": 4, "STRONG BUY": 5}

def _signal_rank(sig: str) -> int:
    return _RANK.get(sig, 0)


# ── Main check ─────────────────────────────────────────────────────────────────

def check_and_alert():
    log("Starting portfolio check...")

    # Load positions from Google Sheets; fall back to hardcoded PORTFOLIOS
    _sheet_portfolios, positions, _cash, _ = read_portfolio_sheet()
    active_portfolios = _sheet_portfolios if _sheet_portfolios else PORTFOLIOS

    state   = _load_json(STATE_FILE)
    history = load_signal_history()
    tickers = [t for lst in active_portfolios.values() for t in lst]

    for ticker in tickers:
        data = get_price_data(ticker)
        if not data:
            continue

        pct   = data["pct_change"]
        price = data["price"]
        pos   = positions.get(ticker, {})
        shares = float(pos.get("shares", 0))

        # ── Price alert ───────────────────────────────────────────────────────
        if abs(pct) >= PRICE_THRESHOLD:
            direction = "UP" if pct >= 0 else "DOWN"
            alert_key = f"price_{ticker}_{direction}"
            if not already_alerted(state, alert_key):
                result = score_stock(ticker)
                signal = result["signal"] if result else "N/A"
                pnl    = shares * (price - data["prev_close"])
                msg    = price_alert_msg(ticker, pct, price, signal, shares, pnl)
                if send_whatsapp(msg):
                    state = mark_alerted(state, alert_key)
            else:
                log(f"  {ticker:<6} {pct:+.2f}%  price alert already sent today")
        else:
            log(f"  {ticker:<6} {pct:+.2f}%  below threshold")

        # ── Signal change alert ───────────────────────────────────────────────
        # score_stock already called above for price alerts; call it here if not yet done
        if abs(pct) < PRICE_THRESHOLD:
            result = score_stock(ticker)
        if result is None:
            continue

        new_sig  = result["signal"]
        old_sig  = history.get(ticker)
        sig_key  = f"signal_{ticker}_{old_sig}_to_{new_sig}"

        if old_sig and old_sig != new_sig:
            if not already_alerted(state, sig_key):
                msg = signal_change_msg(ticker, old_sig, new_sig, price, shares)
                if send_whatsapp(msg):
                    state = mark_alerted(state, sig_key)
            else:
                log(f"  {ticker:<6} signal change {old_sig}→{new_sig} already sent today")

        # Always update history with latest signal
        history[ticker] = new_sig

    save_signal_history(history)
    log("Check complete.")


# ── launchd setup ──────────────────────────────────────────────────────────────

_PLIST_LABEL = "com.stockalerts.pricecheck"
_PLIST_PATH  = os.path.expanduser(f"~/Library/LaunchAgents/{_PLIST_LABEL}.plist")
_PYTHON      = "/Library/Frameworks/Python.framework/Versions/3.9/bin/python3"
_SCRIPT      = os.path.abspath(__file__)
_SCRIPT_DIR  = os.path.dirname(_SCRIPT)


def setup_launchd():
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_PLIST_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>{_PYTHON}</string>
        <string>{_SCRIPT}</string>
    </array>

    <!-- Run every 30 minutes (1800 seconds). The script exits immediately
         outside market hours, so this causes no extra work. -->
    <key>StartInterval</key>
    <integer>1800</integer>

    <key>WorkingDirectory</key>
    <string>{_SCRIPT_DIR}</string>

    <key>StandardOutPath</key>
    <string>{LOG_FILE}</string>

    <key>StandardErrorPath</key>
    <string>{LOG_FILE}</string>

    <!-- Start automatically when you log in -->
    <key>RunAtLoad</key>
    <false/>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/Library/Frameworks/Python.framework/Versions/3.9/bin</string>
    </dict>
</dict>
</plist>
"""
    os.makedirs(os.path.dirname(_PLIST_PATH), exist_ok=True)
    with open(_PLIST_PATH, "w") as f:
        f.write(plist)
    print(f"  ✅ Plist written → {_PLIST_PATH}")

    # Unload any old version first (ignore errors if not loaded)
    os.system(f"launchctl unload '{_PLIST_PATH}' 2>/dev/null")
    ret = os.system(f"launchctl load '{_PLIST_PATH}'")
    if ret == 0:
        print("  ✅ launchd agent loaded — will run every 30 minutes automatically.")
    else:
        print("  ⚠  launchctl load returned a non-zero exit code.")
        print(f"     Try manually:  launchctl load '{_PLIST_PATH}'")

    print(f"\n  To check status:  launchctl list | grep stockalerts")
    print(f"  To stop:          launchctl unload '{_PLIST_PATH}'")
    print(f"  Logs:             tail -f '{LOG_FILE}'")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--setup" in sys.argv:
        setup_launchd()
        sys.exit(0)

    force = "--test" in sys.argv
    if not force and not is_market_hours():
        log("Outside market hours — exiting.")
        sys.exit(0)

    check_and_alert()
