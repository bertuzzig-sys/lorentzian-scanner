"""
Lorentzian Scanner B — Alpaca data source edition
Lorentzian signal only, no VWAP, no volume spike filter.
Uses Alpaca Markets IEX feed (free tier) for reliable cloud data fetching.
"""

import os
import time
import schedule
import logging
import concurrent.futures
from datetime import datetime, timedelta, timezone

import pandas as pd
import numpy as np

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

from alerts import send_alert
from tickers import get_sp500, get_nasdaq100

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

ALPACA_KEY    = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET = os.getenv("ALPACA_API_SECRET")

if not ALPACA_KEY or not ALPACA_SECRET:
    log.warning("ALPACA_API_KEY / ALPACA_API_SECRET not set — scanner will fail on data fetch")

_client = StockHistoricalDataClient(ALPACA_KEY, ALPACA_SECRET) if ALPACA_KEY else None

MIN_DAILY_VOLUME = 100_000
MIN_PRICE = 5.0


# ── Indicators ────────────────────────────────────────────────────────────────

def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def rsi(close, n=14):
    d = close.diff()
    g = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))

def wt(high, low, close, cl=10, al=21):
    hlc3 = (high + low + close) / 3
    esa  = ema(hlc3, cl)
    d    = ema((hlc3 - esa).abs(), cl)
    ci   = (hlc3 - esa) / (0.015 * d.replace(0, np.nan))
    return ema(ci, al)

def cci(high, low, close, n=20):
    tp  = (high + low + close) / 3
    sma = tp.rolling(n).mean()
    md  = tp.rolling(n).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - sma) / (0.015 * md.replace(0, np.nan))

def adx(high, low, close, n=20):
    up   = high.diff()
    down = -low.diff()
    pdm  = np.where((up > down) & (up > 0), up, 0.0)
    mdm  = np.where((down > up) & (down > 0), down, 0.0)
    tr   = pd.concat([high-low,
                      (high-close.shift()).abs(),
                      (low-close.shift()).abs()], axis=1).max(axis=1)
    atr  = tr.ewm(alpha=1/n, adjust=False).mean()
    pdi  = 100 * pd.Series(pdm, index=high.index).ewm(alpha=1/n, adjust=False).mean() / atr
    mdi  = 100 * pd.Series(mdm, index=high.index).ewm(alpha=1/n, adjust=False).mean() / atr
    dx   = 100 * (pdi-mdi).abs() / (pdi+mdi).replace(0, np.nan)
    return dx.ewm(alpha=1/n, adjust=False).mean()

def lorentzian_distance(a, b):
    return float(np.sum(np.log1p(np.abs(a - b))))

def lorentzian_signal(df, neighbors=8, max_bars_back=2000):
    close = df["close"]; high = df["high"]; low = df["low"]
    f1 = rsi(close, 14).fillna(50)
    f2 = wt(high, low, close).fillna(0)
    f3 = cci(high, low, close, 20).fillna(0)
    f4 = adx(high, low, close, 20).fillna(20)
    f5 = rsi(close, 9).fillna(50)
    features = np.column_stack([f1, f2, f3, f4, f5])
    n = len(features)
    signals = np.zeros(n)
    for i in range(50, n):
        lb = min(i, max_bars_back)
        pairs = []
        for j in range(i - lb, i - 1, 4):
            dist = lorentzian_distance(features[i], features[j])
            lbl  = 1 if close.iloc[j+1] > close.iloc[j] else -1
            pairs.append((dist, lbl))
        if not pairs:
            continue
        vote = sum(l for _, l in sorted(pairs)[:neighbors])
        signals[i] = 1 if vote > 0 else (-1 if vote < 0 else 0)
    return pd.Series(signals, index=df.index)


# ── Alpaca data fetch ─────────────────────────────────────────────────────────

def fetch_bars(ticker):
    """Fetch ~6 months of daily OHLCV bars from Alpaca IEX feed."""
    try:
        end   = datetime.now(timezone.utc) - timedelta(minutes=20)
        start = end - timedelta(days=240)
        req = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            feed=DataFeed.IEX,
        )
        bars = _client.get_stock_bars(req)
        if not bars or ticker not in bars.data or not bars.data[ticker]:
            return None
        rows = bars.data[ticker]
        df = pd.DataFrame([{
            "timestamp": b.timestamp,
            "open":   float(b.open),
            "high":   float(b.high),
            "low":    float(b.low),
            "close":  float(b.close),
            "volume": float(b.volume),
        } for b in rows])
        df.set_index("timestamp", inplace=True)
        return df
    except Exception as e:
        log.debug("Alpaca fetch failed for %s: %s", ticker, e)
        return None


# ── Per-stock scan ────────────────────────────────────────────────────────────

def scan_stock(ticker, counters):
    try:
        df = fetch_bars(ticker)
        if df is None or df.empty or len(df) < 100:
            counters["no_data"] += 1
            return None

        last_price = float(df["close"].iloc[-1])
        if last_price < MIN_PRICE:
            counters["price"] += 1
            return None

        daily_vol = float(df["volume"].iloc[-1])
        if daily_vol < MIN_DAILY_VOLUME:
            counters["volume"] += 1
            return None

        counters["passed"] += 1
        sig      = lorentzian_signal(df)
        last_sig = sig.iloc[-1]
        prev_sig = sig.iloc[-2]

        if last_sig == 1 and prev_sig != 1:
            return {"side": "BUY",  "ticker": ticker, "price": round(last_price, 2)}
        if last_sig == -1 and prev_sig != -1:
            return {"side": "SELL", "ticker": ticker, "price": round(last_price, 2)}
        return None
    except Exception as e:
        log.debug("Error on %s: %s", ticker, e)
        counters["no_data"] += 1
        return None


# ── Main scan loop ────────────────────────────────────────────────────────────

def run_scan():
    log.info("=== Lorentzian-only scan (Alpaca) started ===")
    send_alert("🔍 <b>Lorentzian Scanner B [LC]</b>\n"
               "Data: <b>Alpaca IEX</b> · Daily timeframe · Lorentzian only\n"
               "<i>Filters: Lorentz flip + Vol&gt;100K/day + Price&gt;$5</i>")

    if _client is None:
        send_alert("❌ Alpaca API keys missing — set ALPACA_API_KEY and ALPACA_API_SECRET in Railway env vars.")
        return

    tickers = list(set(get_sp500() + get_nasdaq100()))
    log.info("Total tickers: %d", len(tickers))

    signals = []
    workers = int(os.getenv("SCAN_WORKERS", "8"))
    counters = {"no_data": 0, "price": 0, "volume": 0, "passed": 0}

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(scan_stock, t, counters): t for t in tickers}
        done = 0
        for future in concurrent.futures.as_completed(futures):
            done += 1
            result = future.result()
            if result:
                signals.append(result)
                log.info("[LC] %s: %s @ $%s", result["side"], result["ticker"], result["price"])
            if done % 50 == 0:
                log.info("Progress: %d / %d", done, len(tickers))

    log.info("[LC] Scan complete. %d signal(s) found.", len(signals))
    log.info("[LC] Filter breakdown — passed: %d | no_data: %d | price<5: %d | vol<1M: %d",
             counters["passed"], counters["no_data"], counters["price"], counters["volume"])

    filter_msg = (f"📊 <b>[LC] Filter breakdown</b>\n"
                  f"Total fetched: {len(tickers)}\n"
                  f"✅ Passed all filters: {counters['passed']}\n"
                  f"❌ No data / too short: {counters['no_data']}\n"
                  f"❌ Price &lt;$5: {counters['price']}\n"
                  f"❌ Volume &lt;100K: {counters['volume']}")
    send_alert(filter_msg)

    buys  = [s for s in signals if s["side"] == "BUY"]
    sells = [s for s in signals if s["side"] == "SELL"]

    if buys or sells:
        msg = "🎯 <b>[LC] LORENTZIAN SIGNALS</b> (Alpaca)\n\n"
        if buys:
            msg += "🟢 <b>BUY:</b>\n"
            for s in buys:
                msg += f"<b>{s['ticker']}</b> ${s['price']}\n"
            msg += "\n"
        if sells:
            msg += "🔴 <b>SELL:</b>\n"
            for s in sells:
                msg += f"<b>{s['ticker']}</b> ${s['price']}\n"
            msg += "\n"
        msg += f"<i>Scanned {len(tickers)} stocks · {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC</i>"
        send_alert(msg)
    else:
        send_alert(f"✅ [LC] Scan complete — no signals today.\n"
                   f"<i>Scanned {len(tickers)} stocks · "
                   f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC</i>")


if __name__ == "__main__":
    log.info("Lorentzian Scanner B (Alpaca) starting...")
    run_scan()
    schedule_time = os.getenv("SCAN_TIME_UTC", "23:00")
    schedule.every().day.at(schedule_time).do(run_scan)
    log.info("Next scheduled run at %s UTC daily.", schedule_time)
    while True:
        schedule.run_pending()
        time.sleep(60)
