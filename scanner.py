"""
Lorentzian Classification Scanner
Scans S&P500 + NASDAQ100 for fresh green signal flips on 4H timeframe.
Sends Telegram alerts. Runs daily at 23:00 UTC (6am Prague = good timing).
"""

import os
import time
import schedule
import logging
import concurrent.futures
from datetime import datetime

import pandas as pd
import numpy as np
import yfinance as yf

from alerts import send_alert
from tickers import get_sp500, get_nasdaq100

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Lorentzian Classification (pure Python) ─────────────────────────────────

def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()

def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / length, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / length, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)

def wt(high: pd.Series, low: pd.Series, close: pd.Series,
        channel_len: int = 10, avg_len: int = 21) -> pd.Series:
    hlc3 = (high + low + close) / 3
    esa = ema(hlc3, channel_len)
    d = ema((hlc3 - esa).abs(), channel_len)
    ci = (hlc3 - esa) / (0.015 * d.replace(0, np.nan))
    wt1 = ema(ci, avg_len)
    return wt1

def cci(high: pd.Series, low: pd.Series, close: pd.Series,
        length: int = 20) -> pd.Series:
    tp = (high + low + close) / 3
    sma_tp = tp.rolling(length).mean()
    mean_dev = tp.rolling(length).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - sma_tp) / (0.015 * mean_dev.replace(0, np.nan))

def adx(high: pd.Series, low: pd.Series, close: pd.Series,
        length: int = 20) -> pd.Series:
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / length, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=high.index).ewm(alpha=1 / length, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=high.index).ewm(alpha=1 / length, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / length, adjust=False).mean()

def lorentzian_distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sum(np.log1p(np.abs(a - b))))

def lorentzian_signal(df: pd.DataFrame,
                      neighbors: int = 8,
                      max_bars_back: int = 2000) -> pd.Series:
    """
    Returns a Series of signals: 1 = bullish, -1 = bearish, 0 = neutral.
    Mirrors jdehorty's Pine Script logic using KNN + Lorentzian distance.
    """
    close = df["close"]
    high  = df["high"]
    low   = df["low"]

    # Features (normalised 0-1 range helps KNN distance)
    f1 = rsi(close, 14).fillna(50)
    f2 = wt(high, low, close).fillna(0)
    f3 = cci(high, low, close, 20).fillna(0)
    f4 = adx(high, low, close, 20).fillna(20)
    f5 = rsi(close, 9).fillna(50)            # shorter RSI as 5th feature

    # Stack features into a matrix
    features = np.column_stack([f1, f2, f3, f4, f5])
    n = len(features)
    signals = np.zeros(n)

    for i in range(50, n):                    # need warmup
        look_back = min(i, max_bars_back)
        distances = []
        labels    = []

        # Sample every 4 bars (Pine Script default spacing=4)
        for j in range(i - look_back, i - 1, 4):
            dist = lorentzian_distance(features[i], features[j])
            direction = 1 if close.iloc[j + 1] > close.iloc[j] else -1
            distances.append(dist)
            labels.append(direction)

        if not distances:
            continue

        # K nearest
        sorted_pairs = sorted(zip(distances, labels))[:neighbors]
        vote = sum(lbl for _, lbl in sorted_pairs)
        signals[i] = 1 if vote > 0 else (-1 if vote < 0 else 0)

    return pd.Series(signals, index=df.index)


# ── Per-stock scan ───────────────────────────────────────────────────────────

def scan_stock(ticker: str) -> dict | None:
    try:
        df = yf.download(
            ticker,
            period="6mo",
            interval="4h",
            progress=False,
            auto_adjust=True,
        )
        if df.empty or len(df) < 100:
            return None

        df.columns = [c.lower() for c in df.columns]

        # Basic liquidity / price filter
        avg_vol    = df["volume"].mean()
        last_price = float(df["close"].iloc[-1])
        if avg_vol < 500_000 or last_price < 5:
            return None

        sig = lorentzian_signal(df)

        last = sig.iloc[-1]
        prev = sig.iloc[-2]

        # Fresh green flip: was not bullish, now bullish
        if last == 1 and prev != 1:
            return {
                "ticker": ticker,
                "price":  round(last_price, 2),
                "volume": int(avg_vol),
                "signal": "🟢 BUY",
            }

        return None

    except Exception as exc:
        log.debug("Error on %s: %s", ticker, exc)
        return None


# ── Main scan loop ───────────────────────────────────────────────────────────

def run_scan():
    log.info("=== Lorentzian scan started ===")
    send_alert("🔍 <b>Lorentzian Scanner</b>\nStarting scan of S&P500 + NASDAQ100…")

    tickers = list(set(get_sp500() + get_nasdaq100()))
    log.info("Total tickers: %d", len(tickers))

    signals = []
    workers = int(os.getenv("SCAN_WORKERS", "8"))

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(scan_stock, t): t for t in tickers}
        done = 0
        for future in concurrent.futures.as_completed(futures):
            done += 1
            result = future.result()
            if result:
                signals.append(result)
                log.info("Signal: %s @ $%s", result["ticker"], result["price"])
            if done % 50 == 0:
                log.info("Progress: %d / %d", done, len(tickers))

    log.info("Scan complete. %d signal(s) found.", len(signals))

    if signals:
        msg = "🟢 <b>LORENTZIAN GREEN SIGNALS</b>\n\n"
        for s in signals:
            msg += f"<b>{s['ticker']}</b> — ${s['price']}\n"
            msg += f"Vol avg: {s['volume']:,}\n\n"
        msg += f"<i>Scanned {len(tickers)} stocks · {datetime.utcnow():%Y-%m-%d %H:%M} UTC</i>"
        send_alert(msg)
    else:
        send_alert(
            f"✅ Scan complete — no fresh green signals.\n"
            f"<i>Scanned {len(tickers)} stocks · {datetime.utcnow():%Y-%m-%d %H:%M} UTC</i>"
        )


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("Lorentzian Scanner starting…")

    # Run once immediately on startup so Railway shows activity in logs
    run_scan()

    # Then schedule daily at 23:00 UTC (= 01:00 Prague, results ready before market open)
    schedule_time = os.getenv("SCAN_TIME_UTC", "23:00")
    schedule.every().day.at(schedule_time).do(run_scan)
    log.info("Next scheduled run at %s UTC daily.", schedule_time)

    while True:
        schedule.run_pending()
        time.sleep(60)
