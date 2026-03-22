#!/usr/bin/env python3
"""
Interactive Telegram Bot — Price Alert Manager + Daily Report
Commands: /price /alert /alerts /remove /report /help
Stores user alerts in alerts.json via GitHub API.
Runs as a persistent polling process on Railway.
"""

import os
import json
import base64
import logging
from datetime import datetime, time as dt_time
from pathlib import Path

import yaml
import requests
import pytz
from curl_cffi import requests as curl_requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

_SESSION = curl_requests.Session(impersonate="chrome120")

# ── Config ────────────────────────────────────────────────────────────────────

BOT_TOKEN       = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])
GH_PAT          = os.environ["GH_PAT"]
GITHUB_REPO     = os.environ.get("GITHUB_REPO", "Rojios/price-alert")
ALERTS_PATH     = "alerts.json"
CONFIG_FILE     = Path(__file__).parent / "config.yaml"
TZ              = pytz.timezone("Asia/Bangkok")

SYMBOL_MAP = {
    "XAUUSD": "XAUUSD=X",
    "GOLD":   "XAUUSD=X",
    "SILVER": "SI=F",
    "GC":     "GC=F",
    "OIL":    "CL=F",
    "BTC":    "BTC-USD",
    "ETH":    "ETH-USD",
    "SET":    "^SET.BK",
    "PTT":    "PTT.BK",
    "KBANK":  "KBANK.BK",
    "SAPPE":  "SAPPE.BK",
    "NSL":    "NSL.BK",
    "SISB":   "SISB.BK",
    "BH":     "BH.BK",
    "TIDLOR": "TIDLOR.BK",
}


def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)


def normalize_symbol(raw: str) -> tuple[str, str]:
    upper = raw.upper().strip()
    return SYMBOL_MAP.get(upper, upper), upper


# ── Price Fetching ────────────────────────────────────────────────────────────

def fetch_price(symbol: str) -> tuple[float | None, float | None]:
    """
    Direct Yahoo Finance v8 API call via curl_cffi (Chrome120 impersonation).
    Returns (current_price, prev_close) or (None, None) on failure.
    """
    try:
        url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        resp = _SESSION.get(url, params={"interval": "1d", "range": "5d"}, timeout=15)
        resp.raise_for_status()
        data   = resp.json()
        result = (data.get("chart") or {}).get("result")
        if not result:
            logger.error(f"No result for {symbol}: {data}")
            return None, None
        closes = [c for c in result[0]["indicators"]["quote"][0]["close"] if c is not None]
        if not closes:
            return None, None
        current = float(closes[-1])
        prev    = float(closes[-2]) if len(closes) >= 2 else current
        return current, prev
    except Exception:
        logger.exception(f"fetch_price({symbol})")
        return None, None


# ── GitHub API ────────────────────────────────────────────────────────────────

def _gh_headers() -> dict:
    return {"Authorization": f"token {GH_PAT}", "Accept": "application/vnd.github.v3+json"}


def read_alerts() -> tuple[list, str | None]:
    url  = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{ALERTS_PATH}"
    resp = requests.get(url, headers=_gh_headers(), timeout=10)
    if resp.status_code == 404:
        return [], None
    resp.raise_for_status()
    data = resp.json()
    return json.loads(base64.b64decode(data["content"]).decode()).get("alerts", []), data["sha"]


def write_alerts(alerts: list, sha: str | None) -> None:
    url     = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{ALERTS_PATH}"
    content = base64.b64encode(
        json.dumps({"alerts": alerts}, indent=2, ensure_ascii=False).encode()
    ).decode()
    payload = {
        "message": "chore: update user alerts [skip ci]",
        "content": content,
        "committer": {"name": "Price Alert Bot", "email": "bot@noreply.local"},
    }
    if sha:
        payload["sha"] = sha
    requests.put(url, headers=_gh_headers(), json=payload, timeout=10).raise_for_status()


# ── Auth guard ────────────────────────────────────────────────────────────────

def auth_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id != ALLOWED_CHAT_ID:
            await update.message.reply_text("⛔ Unauthorized")
            return
        return await func(update, context)
    wrapper.__name__ = func.__name__
    return wrapper


# ── Daily Report ──────────────────────────────────────────────────────────────

async def build_report() -> str:
    config  = load_config()
    symbols = config.get("daily_report", {}).get("symbols", [])
    now_str = datetime.now(TZ).strftime("%d %b %Y  %H:%M %Z")
    lines   = [f"📈 <b>Daily Report</b>\n🕐 {now_str}\n"]

    for item in symbols:
        sym  = item["symbol"]
        name = item.get("name", sym)
        current, prev = fetch_price(sym)
        if current is None:
            lines.append(f"• <b>{name}</b> : ❌ N/A")
            continue
        pct   = (current - prev) / prev * 100 if prev else 0
        arrow = "▲" if pct >= 0 else "▼"
        lines.append(
            f"• <b>{name}</b> : {current:,.2f}  {arrow} {abs(pct):.2f}%"
        )

    return "\n".join(lines)


async def daily_report_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Running daily report job")
    try:
        text = await build_report()
        await context.bot.send_message(
            chat_id=ALLOWED_CHAT_ID, text=text, parse_mode="HTML"
        )
    except Exception:
        logger.exception("Daily report job failed")


# ── Command handlers ──────────────────────────────────────────────────────────

@auth_only
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 <b>Price Alert Bot</b>\n\n"
        "<b>ดูราคา</b>\n"
        "/price XAUUSD\n"
        "/price PTT.BK\n\n"
        "<b>ตั้ง Alert</b>\n"
        "/alert XAUUSD above 4700\n"
        "/alert XAUUSD below 4400\n"
        "/alert XAUUSD change 1.5\n\n"
        "<b>จัดการ Alert</b>\n"
        "/alerts       — ดู alert ทั้งหมด\n"
        "/remove 2     — ลบ alert หมายเลข 2\n\n"
        "<b>Daily Report</b>\n"
        "/report       — ดู report ตอนนี้เลย\n"
        "📅 ส่งอัตโนมัติ ทุกวัน 17:00 น.\n\n"
        "<b>Symbols</b>\n"
        "XAUUSD, GC, BTC, ETH\n"
        "SET, PTT, KBANK, SAPPE\n"
        "NSL, SISB, BH, TIDLOR",
        parse_mode="HTML",
    )


@auth_only
async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /price XAUUSD")
        return

    yf_sym, label = normalize_symbol(context.args[0])
    await update.message.reply_text("⏳ กำลังดึงราคา...")

    current, prev = fetch_price(yf_sym)
    if current is None:
        await update.message.reply_text(
            f"❌ ดึงราคา {label} ไม่ได้\nลองใช้ symbol เต็ม เช่น PTT.BK, SAPPE.BK"
        )
        return

    pct     = (current - prev) / prev * 100 if prev else 0
    arrow   = "▲" if pct >= 0 else "▼"
    now_str = datetime.now(TZ).strftime("%d %b %Y  %H:%M %Z")

    await update.message.reply_text(
        f"💰 <b>{label}</b>\n"
        f"ราคา    : <b>{current:,.2f}</b>\n"
        f"เมื่อวาน : {prev:,.2f}\n"
        f"เปลี่ยน  : {arrow} {abs(pct):.2f}%\n"
        f"🕐 {now_str}",
        parse_mode="HTML",
    )


@auth_only
async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ กำลังดึงราคา...")
    text = await build_report()
    await update.message.reply_text(text, parse_mode="HTML")


@auth_only
async def cmd_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 3:
        await update.message.reply_text(
            "รูปแบบ:\n"
            "/alert XAUUSD above 4700\n"
            "/alert XAUUSD below 4400\n"
            "/alert XAUUSD change 1.5"
        )
        return

    yf_sym, label = normalize_symbol(args[0])
    cond     = args[1].lower()
    type_map = {"above": "price_above", "below": "price_below", "change": "pct_change"}

    if cond not in type_map:
        await update.message.reply_text("Condition ต้องเป็น: above / below / change")
        return

    try:
        threshold = float(args[2])
    except ValueError:
        await update.message.reply_text("Threshold ต้องเป็นตัวเลข เช่น 4700 หรือ 1.5")
        return

    alert_type = type_map[cond]
    alert_id   = f"{yf_sym}__{alert_type}__{threshold}"

    alerts, sha = read_alerts()
    if any(a.get("id") == alert_id for a in alerts):
        await update.message.reply_text("⚠️ Alert นี้มีอยู่แล้ว ดู /alerts")
        return

    alerts.append({
        "id":         alert_id,
        "symbol":     yf_sym,
        "label":      label,
        "type":       alert_type,
        "threshold":  threshold,
        "created_at": datetime.now(TZ).isoformat(),
    })
    write_alerts(alerts, sha)

    cond_text = {
        "price_above": f"ราคาเกิน {threshold:,.2f}",
        "price_below": f"ราคาต่ำกว่า {threshold:,.2f}",
        "pct_change":  f"เปลี่ยนแปลง ±{threshold}%",
    }[alert_type]

    await update.message.reply_text(
        f"✅ ตั้ง Alert แล้ว\n🔖 {label}\n🔔 {cond_text}"
    )


@auth_only
async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    alerts, _ = read_alerts()
    if not alerts:
        await update.message.reply_text("ยังไม่มี alert\nตั้งได้เลย เช่น /alert SAPPE above 13")
        return

    lines = ["📋 <b>Alert ที่ตั้งไว้</b>\n"]
    for i, a in enumerate(alerts, 1):
        t, thresh = a["type"], a["threshold"]
        sym  = a.get("label", a["symbol"])
        cond = (
            f"above {thresh:,.2f}" if t == "price_above" else
            f"below {thresh:,.2f}" if t == "price_below" else
            f"change ±{thresh}%"
        )
        lines.append(f"{i}. <b>{sym}</b> — {cond}")

    lines.append("\nลบ: /remove [หมายเลข]")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


@auth_only
async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /remove 2")
        return
    try:
        idx = int(context.args[0]) - 1
    except ValueError:
        await update.message.reply_text("ระบุหมายเลข เช่น /remove 2")
        return

    alerts, sha = read_alerts()
    if idx < 0 or idx >= len(alerts):
        await update.message.reply_text(f"ไม่มี alert หมายเลข {idx + 1}")
        return

    removed = alerts.pop(idx)
    write_alerts(alerts, sha)
    sym, t, thresh = removed.get("label", removed["symbol"]), removed["type"], removed["threshold"]
    cond = (
        f"above {thresh:,.2f}" if t == "price_above" else
        f"below {thresh:,.2f}" if t == "price_below" else
        f"change ±{thresh}%"
    )
    await update.message.reply_text(f"🗑 ลบแล้ว: <b>{sym}</b> — {cond}", parse_mode="HTML")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    config = load_config()
    report_cfg = config.get("daily_report", {})

    # Parse report time (default 17:00 BKK = 10:00 UTC)
    t_str = report_cfg.get("time", "17:00")
    h, m  = map(int, t_str.split(":"))
    # Convert BKK (UTC+7) to UTC
    report_time_utc = dt_time(hour=(h - 7) % 24, minute=m, tzinfo=pytz.utc)
    report_days = tuple(report_cfg.get("days", [0, 1, 2, 3, 4]))

    app = Application.builder().token(BOT_TOKEN).build()

    # Register commands
    app.add_handler(CommandHandler("start",   cmd_help))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("price",   cmd_price))
    app.add_handler(CommandHandler("report",  cmd_report))
    app.add_handler(CommandHandler("alert",   cmd_alert))
    app.add_handler(CommandHandler("alerts",  cmd_alerts))
    app.add_handler(CommandHandler("remove",  cmd_remove))

    # Schedule daily report
    app.job_queue.run_daily(
        daily_report_job,
        time=report_time_utc,
        days=report_days,
        name="daily_report",
    )
    logger.info(f"Daily report scheduled at {t_str} BKK (days={report_days})")

    logger.info("Bot polling started…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
