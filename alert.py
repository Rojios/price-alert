#!/usr/bin/env python3
"""
Gold/Stock Price Alert System
Fetches prices via yfinance, checks thresholds, sends Telegram alerts.
Deduplicates alerts within DEDUP_MINUTES to avoid spam.
"""

import os
import json
import sys
import yaml
import yfinance as yf
import requests
import pytz
from datetime import datetime
from pathlib import Path

CONFIG_FILE        = Path(__file__).parent / "config.yaml"
STATE_FILE         = Path(__file__).parent / "alert_state.json"
DYNAMIC_ALERTS_FILE = Path(__file__).parent / "alerts.json"
DEDUP_MINUTES      = 60


# ── Config & State ──────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ── Dynamic alerts (set via Telegram bot) ────────────────────────────────────

def load_dynamic_watchlist() -> list[dict]:
    """Load alerts.json written by bot.py and convert to watchlist format."""
    if not DYNAMIC_ALERTS_FILE.exists():
        return []
    with open(DYNAMIC_ALERTS_FILE) as f:
        entries = json.load(f).get("alerts", [])

    by_symbol: dict[str, dict] = {}
    for e in entries:
        sym = e["symbol"]
        if sym not in by_symbol:
            by_symbol[sym] = {"symbol": sym, "name": e.get("label", sym), "alerts": []}
        by_symbol[sym]["alerts"].append({
            "type":      e["type"],
            "threshold": e["threshold"],
            "message":   "",
        })
    return list(by_symbol.values())


# ── Price Fetching ───────────────────────────────────────────────────────────

def get_price(symbol: str) -> tuple[float | None, float | None]:
    """Return (current_price, prev_close) or (None, None) on failure."""
    try:
        ticker = yf.Ticker(symbol)
        # Fetch 5-day daily history for reliable prev_close
        daily = ticker.history(period="5d", interval="1d")
        if daily.empty or len(daily) < 1:
            return None, None

        current_price = float(daily["Close"].iloc[-1])
        prev_close = float(daily["Close"].iloc[-2]) if len(daily) >= 2 else current_price
        return current_price, prev_close

    except Exception as exc:
        print(f"  [ERROR] Could not fetch {symbol}: {exc}", file=sys.stderr)
        return None, None


# ── Alert Logic ──────────────────────────────────────────────────────────────

def is_dedup_clear(state: dict, key: str, now: datetime) -> bool:
    """Return True if enough time has passed since the last alert for this key."""
    if key not in state:
        return True
    try:
        last = datetime.fromisoformat(state[key])
        return (now - last).total_seconds() > DEDUP_MINUTES * 60
    except (ValueError, TypeError):
        return True


def check_condition(
    alert_type: str,
    threshold: float,
    current_price: float,
    pct_change: float,
) -> bool:
    if alert_type == "price_above":
        return current_price > threshold
    if alert_type == "price_below":
        return current_price < threshold
    if alert_type == "pct_change":
        return abs(pct_change) >= threshold
    return False


def build_message(
    name: str,
    symbol: str,
    alert_type: str,
    threshold: float,
    current_price: float,
    prev_close: float,
    pct_change: float,
    custom_msg: str,
    now: datetime,
) -> str:
    direction = "▲" if pct_change >= 0 else "▼"
    change_str = f"{direction} {abs(pct_change):.2f}%"

    if alert_type == "price_above":
        condition_line = f"📈 Price <b>above {threshold:,.2f}</b>"
    elif alert_type == "price_below":
        condition_line = f"📉 Price <b>below {threshold:,.2f}</b>"
    else:
        condition_line = f"⚡️ Change <b>{change_str}</b> (threshold ≥ {threshold}%)"

    note = f"\n💬 {custom_msg}" if custom_msg else ""
    timestamp = now.strftime("%d %b %Y  %H:%M %Z")

    return (
        f"🚨 <b>Price Alert — {name}</b>\n"
        f"🔖 {symbol}\n"
        f"{condition_line}\n"
        f"💰 Current : <b>{current_price:,.2f}</b>\n"
        f"📊 Prev Close: {prev_close:,.2f}  ({change_str})"
        f"{note}\n"
        f"🕐 {timestamp}"
    )


# ── Telegram ─────────────────────────────────────────────────────────────────

def send_telegram(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(
        url,
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        timeout=15,
    )
    resp.raise_for_status()
    print("  [OK] Telegram alert sent.")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        sys.exit("[FATAL] TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set.")

    config = load_config()
    state = load_state()
    tz = pytz.timezone(config.get("timezone", "Asia/Bangkok"))
    now = datetime.now(tz)
    state_updated = False

    print(f"=== Price Alert Run: {now.strftime('%Y-%m-%d %H:%M %Z')} ===")

    # Merge static config.yaml watchlist + dynamic alerts.json
    static    = config.get("watchlist", [])
    dynamic   = load_dynamic_watchlist()
    sym_index = {item["symbol"]: item for item in static}
    for d in dynamic:
        if d["symbol"] in sym_index:
            sym_index[d["symbol"]]["alerts"].extend(d["alerts"])
        else:
            static.append(d)
    watchlist = static

    for item in watchlist:
        symbol: str = item["symbol"]
        name: str = item.get("name", symbol)

        print(f"\n[{symbol}] {name}")
        current_price, prev_close = get_price(symbol)

        if current_price is None:
            print("  Skipping — price unavailable.")
            continue

        pct_change = (
            (current_price - prev_close) / prev_close * 100
            if prev_close
            else 0.0
        )
        print(
            f"  Price: {current_price:,.2f}  |  "
            f"Prev Close: {prev_close:,.2f}  |  "
            f"Change: {pct_change:+.2f}%"
        )

        for alert in item.get("alerts", []):
            alert_type: str = alert["type"]
            threshold: float = float(alert["threshold"])
            custom_msg: str = alert.get("message", "")

            triggered = check_condition(alert_type, threshold, current_price, pct_change)
            state_key = f"{symbol}__{alert_type}__{threshold}"

            if triggered:
                if is_dedup_clear(state, state_key, now):
                    msg = build_message(
                        name, symbol, alert_type, threshold,
                        current_price, prev_close, pct_change,
                        custom_msg, now,
                    )
                    print(f"  [ALERT] {alert_type} @ {threshold}")
                    try:
                        send_telegram(token, chat_id, msg)
                        state[state_key] = now.isoformat()
                        state_updated = True
                    except requests.RequestException as exc:
                        print(f"  [ERROR] Telegram failed: {exc}", file=sys.stderr)
                else:
                    print(f"  [SKIP] {alert_type} @ {threshold} — dedup (60 min)")
            else:
                print(f"  [--]   {alert_type} @ {threshold} — not triggered")

    if state_updated:
        save_state(state)
        print(f"\nState saved → {STATE_FILE}")
    else:
        print("\nNo new alerts fired.")


if __name__ == "__main__":
    main()
