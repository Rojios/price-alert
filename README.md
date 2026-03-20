# 📈 Gold & Stock Price Alert — GitHub Actions + Telegram

Runs every 15 minutes on GitHub Actions (free tier).
Fetches **GC=F** (Gold Futures) and **PTT.BK** (or any yfinance symbol), checks your thresholds, and fires a Telegram message — with 60-minute dedup so you don't get spammed.

---

## Architecture

```
GitHub Actions (cron */15)
  └── alert.py
        ├── yfinance  →  fetch current price + prev close
        ├── config.yaml  →  symbols + alert conditions
        ├── alert_state.json  →  dedup tracker (auto-committed)
        └── Telegram Bot API  →  send alert
```

---

## Setup Guide

### Step 1 — Create a Telegram Bot

1. Open Telegram → search **@BotFather**
2. Send `/newbot` → follow prompts → copy the **Bot Token**
   (looks like `7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxx`)
3. Start a chat with your new bot (or add it to a group)
4. Get your **Chat ID**:
   - Personal: message [@userinfobot](https://t.me/userinfobot) → it replies with your ID
   - Group: add [@RawDataBot](https://t.me/RawDataBot) to the group → it shows the group chat ID (starts with `-`)

---

### Step 2 — Fork / Create GitHub Repo

```bash
# Option A — clone this project
git clone <your-fork-url>
cd price-alert

# Option B — new repo
gh repo create price-alert --public --source=. --push
```

---

### Step 3 — Add GitHub Secrets

In your repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret name           | Value                          |
|-----------------------|-------------------------------|
| `TELEGRAM_BOT_TOKEN`  | `7123456789:AAHxxx...`        |
| `TELEGRAM_CHAT_ID`    | `123456789` or `-987654321`   |

---

### Step 4 — Customize `config.yaml`

```yaml
timezone: "Asia/Bangkok"

watchlist:
  - symbol: "GC=F"          # Gold Futures (COMEX)
    name: "Gold Futures"
    alerts:
      - type: price_above
        threshold: 3200
        message: "Breaking key resistance!"
      - type: pct_change
        threshold: 1.5      # alert if +/- 1.5% from previous close
```

**Alert types:**

| Type          | Triggers when…                                     |
|---------------|----------------------------------------------------|
| `price_above` | `current_price > threshold`                        |
| `price_below` | `current_price < threshold`                        |
| `pct_change`  | `abs((current - prev_close) / prev_close) >= threshold %` |

**Useful yfinance symbols:**

| Asset         | Symbol     |
|---------------|------------|
| Gold Futures  | `GC=F`     |
| Silver        | `SI=F`     |
| Crude Oil     | `CL=F`     |
| PTT           | `PTT.BK`   |
| KBANK         | `KBANK.BK` |
| S&P 500 ETF   | `SPY`      |
| Bitcoin       | `BTC-USD`  |

---

### Step 5 — Push and Enable Actions

```bash
git add .
git commit -m "feat: price alert system"
git push
```

Go to **Actions** tab → enable workflows if prompted.
Trigger a manual test run: **Actions → Price Alert → Run workflow**.

---

## How Dedup Works

`alert_state.json` tracks the last time each condition fired:

```json
{
  "GC=F__price_above__3200.0": "2026-03-20T10:15:00+07:00",
  "PTT.BK__pct_change__2.0": "2026-03-20T09:30:00+07:00"
}
```

- Same condition won't re-alert for **60 minutes**
- File is auto-committed back to the repo after each run (via `github-actions[bot]`)
- `[skip ci]` in the commit message prevents a loop trigger

---

## Sample Telegram Alert

```
🚨 Price Alert — Gold Futures (COMEX)
🔖 GC=F
📈 Price above 3,200.00
💰 Current : 3,214.50
📊 Prev Close: 3,185.20  (▲ 0.92%)
💬 Breaking key resistance!
🕐 20 Mar 2026  10:15 ICT
```

---

## Local Testing

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"
python alert.py
```

---

## Notes

- GitHub Actions free tier: 2,000 min/month for public repos (unlimited), 2,000 min for private repos.
  At 15-min intervals: ~2,880 runs/month × ~0.5 min each ≈ **1,440 min/month** — within free limits.
- GitHub may delay scheduled runs by a few minutes under load; this is normal.
- yfinance uses Yahoo Finance data — free, no API key needed.
- Market-closed periods return the last available closing price.
