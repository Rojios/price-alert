"""
Shared TradingView TA helper — used by both bot.py and alert.py
Provides: get_indicators(yf_sym, interval)
"""

from tradingview_ta import TA_Handler, Interval

# yfinance symbol → TradingView TA params
TV_SYMBOLS: dict[str, dict] = {
    "XAUUSD=X": {"symbol": "XAUUSD",  "exchange": "OANDA",   "screener": "forex"},
    "GC=F":     {"symbol": "GC1!",    "exchange": "COMEX",   "screener": "america"},
    "SI=F":     {"symbol": "SI1!",    "exchange": "COMEX",   "screener": "america"},
    "CL=F":     {"symbol": "CL1!",    "exchange": "NYMEX",   "screener": "america"},
    "BTC-USD":  {"symbol": "BTCUSDT", "exchange": "BINANCE", "screener": "crypto"},
    "ETH-USD":  {"symbol": "ETHUSDT", "exchange": "BINANCE", "screener": "crypto"},
    "PTT.BK":   {"symbol": "PTT",     "exchange": "SET",     "screener": "thailand"},
    "KBANK.BK": {"symbol": "KBANK",   "exchange": "SET",     "screener": "thailand"},
}

INTERVAL_MAP: dict[str, str] = {
    "1m":  Interval.INTERVAL_1_MINUTE,
    "5m":  Interval.INTERVAL_5_MINUTES,
    "15m": Interval.INTERVAL_15_MINUTES,
    "1h":  Interval.INTERVAL_1_HOUR,
    "4h":  Interval.INTERVAL_4_HOURS,
    "1d":  Interval.INTERVAL_1_DAY,
    "1w":  Interval.INTERVAL_1_WEEK,
}

# Alert types that use indicators (not price)
INDICATOR_ALERT_TYPES = {
    "rsi_above", "rsi_below",
    "macd_bullish", "macd_bearish",
    "recommend_buy", "recommend_sell",
}


def get_indicators(yf_sym: str, interval: str = "1h") -> dict | None:
    """
    Fetch TradingView technical indicators for a symbol.
    Returns dict with RSI, MACD, EMA, recommendation — or None on failure.
    """
    tv = TV_SYMBOLS.get(yf_sym)
    if not tv:
        return None
    try:
        handler = TA_Handler(
            symbol=tv["symbol"],
            exchange=tv["exchange"],
            screener=tv["screener"],
            interval=INTERVAL_MAP.get(interval, Interval.INTERVAL_1_HOUR),
        )
        analysis = handler.get_analysis()
        ind = analysis.indicators
        return {
            "rsi":           ind.get("RSI"),
            "macd":          ind.get("MACD.macd"),
            "macd_signal":   ind.get("MACD.signal"),
            "macd_hist":     ind.get("MACD.hist"),
            "ema20":         ind.get("EMA20"),
            "ema50":         ind.get("EMA50"),
            "ema200":        ind.get("EMA200"),
            "close":         ind.get("close"),
            "recommendation": analysis.summary.get("RECOMMENDATION"),
            "buy_count":     analysis.summary.get("BUY"),
            "sell_count":    analysis.summary.get("SELL"),
            "neutral_count": analysis.summary.get("NEUTRAL"),
        }
    except Exception:
        return None


def check_indicator_condition(alert_type: str, threshold: float, ind: dict) -> bool:
    """Return True if the indicator condition is met."""
    if alert_type == "rsi_above":
        v = ind.get("rsi")
        return v is not None and v > threshold

    if alert_type == "rsi_below":
        v = ind.get("rsi")
        return v is not None and v < threshold

    if alert_type == "macd_bullish":
        m, s = ind.get("macd"), ind.get("macd_signal")
        return m is not None and s is not None and m > s

    if alert_type == "macd_bearish":
        m, s = ind.get("macd"), ind.get("macd_signal")
        return m is not None and s is not None and m < s

    if alert_type == "recommend_buy":
        return ind.get("recommendation") in ("STRONG_BUY", "BUY")

    if alert_type == "recommend_sell":
        return ind.get("recommendation") in ("STRONG_SELL", "SELL")

    return False


def format_indicators(label: str, yf_sym: str, ind: dict, interval: str) -> str:
    """Format indicator dict into a readable Telegram message."""
    rsi  = ind.get("rsi")
    macd = ind.get("macd")
    sig  = ind.get("macd_signal")
    hist = ind.get("macd_hist")
    e20  = ind.get("ema20")
    e50  = ind.get("ema50")
    e200 = ind.get("ema200")
    rec  = ind.get("recommendation", "N/A")
    buys = ind.get("buy_count", 0)
    sells = ind.get("sell_count", 0)
    neu  = ind.get("neutral_count", 0)

    rec_emoji = {
        "STRONG_BUY": "🟢", "BUY": "🟩",
        "NEUTRAL": "⬜️",
        "SELL": "🟥", "STRONG_SELL": "🔴",
    }.get(rec, "⬜️")

    macd_arrow = "▲" if (macd and sig and macd > sig) else "▼"

    return (
        f"📊 <b>{label}</b> ({interval.upper()})\n\n"
        f"RSI(14)   : <b>{rsi:.1f}</b>\n"
        f"MACD      : {macd:.4f} | Signal: {sig:.4f} {macd_arrow}\n"
        f"MACD Hist : {hist:.4f}\n"
        f"EMA20/50/200: {e20:.2f} / {e50:.2f} / {e200:.2f}\n\n"
        f"Recommendation: {rec_emoji} <b>{rec}</b>\n"
        f"Buy: {buys}  Sell: {sells}  Neutral: {neu}"
    )
