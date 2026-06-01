"""
Lorentzian Classification Scanner — with VWAP + Volume + RSI filters
Scans S&P500 + NASDAQ100 on 4H timeframe.
Sends Telegram alerts only when ALL 4 conditions are met:
  1. Lorentzian green flip
  2. Price > Weekly VWAP
  3. Volume > 1.5x 20-bar average
  4. RSI < 70 (not overbought)
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


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

def weekly_vwap(df):
    tp   = (df["high"] + df["low"] + df["close"]) / 3
    vol  = df["volume"]
    week = tp.index.to_series().dt.isocalendar().week.values
    year = tp.index.to_series().dt.isocalendar().year.values
    key  = year * 100 + week
    vwap = pd.Series(index=df.index, dtype=float)
    cum_tp_vol = cum_vol = 0.0
    prev_key = None
    for i, idx in enumerate(df.index):
        k = key[i]
        if k != prev_key:
            cum_tp_vol = cum_vol = 0.0
            prev_key = k
        cum_tp_vol += tp.iloc[i] * vol.iloc[i]
        cum_vol    += vol.iloc[i]
        vwap.iloc[i] = cum_tp_vol / cum_vol if cum_vol > 0 else np.nan
    return vwap


# ── Per-stock scan ────────────────────────────────────────────────────────────

def scan_stock(ticker):
    try:
        df = yf.download(ticker, period="6mo", interval="4h",
                         progress=False, auto_adjust=True)
        if df.empty or len(df) < 100:
            return None
        # Flatten MultiIndex columns if present (newer yfinance)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]
        df.columns = [c.lower() for c in df.columns]

        last_price = float(df["close"].iloc[-1])
        avg_vol    = df["volume"].mean()

        if avg_vol < 500_000 or last_price < 5:
            return None

        # ── Signals & filters ────────────────────────────────────────────────
        sig      = lorentzian_signal(df)
        rsi_val  = float(rsi(df["close"], 14).iloc[-1])
        vwap_val = float(weekly_vwap(df).iloc[-1])
        vol_ma   = float(df["volume"].rolling(20).mean().iloc[-1])
        last_vol = float(df["volume"].iloc[-1])

        last_sig = sig.iloc[-1]
        prev_sig = sig.iloc[-2]

        # Filter 1: fresh green flip
        if not (last_sig == 1 and prev_sig != 1):
            return None

        # Filter 2: price above weekly VWAP
        if last_price <= vwap_val:
            return None

        # Filter 3: volume spike (> 1.5x 20-bar avg)
        if last_vol <= 1.5 * vol_ma:
            return None

        # Filter 4: RSI not overbought
        if rsi_val >= 70:
            return None

        return {
            "ticker":    ticker,
            "price":     round(last_price, 2),
            "vwap":      round(vwap_val, 2),
            "rsi":       round(rsi_val, 1),
            "vol_ratio": round(last_vol / vol_ma, 1),
        }

    except Exception as e:
        log.debug("Error on %s: %s", ticker, e)
        return None


# ── Main scan loop ────────────────────────────────────────────────────────────

def run_scan():
    log.info("=== Lorentzian scan started ===")
    send_alert("🔍 <b>Lorentzian Scanner</b>\nStarting 4H scan with full filter stack…\n"
               "<i>Filters: Lorentzian flip + Weekly VWAP + Volume spike + RSI&lt;70</i>")

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
                log.info("Signal: %s @ $%s | VWAP $%s | RSI %.1f | Vol x%.1f",
                         result["ticker"], result["price"], result["vwap"],
                         result["rsi"], result["vol_ratio"])
            if done % 50 == 0:
                log.info("Progress: %d / %d", done, len(tickers))

    log.info("Scan complete. %d signal(s) found.", len(signals))

    if signals:
        msg = "🟢 <b>LORENTZIAN SIGNALS — Full Filter Stack</b>\n\n"
        for s in signals:
            msg += (f"<b>{s['ticker']}</b> — ${s['price']}\n"
                    f"VWAP: ${s['vwap']} ✅  RSI: {s['rsi']} ✅  Vol: {s['vol_ratio']}x ✅\n\n")
        msg += (f"<i>Filters: Lorentz flip + Above Weekly VWAP + "
                f"Vol&gt;1.5x + RSI&lt;70</i>\n"
                f"<i>Scanned {len(tickers)} stocks · "
                f"{datetime.utcnow():%Y-%m-%d %H:%M} UTC</i>")
        send_alert(msg)
    else:
        send_alert(f"✅ Scan complete — no signals passed all 4 filters today.\n"
                   f"<i>Scanned {len(tickers)} stocks · "
                   f"{datetime.utcnow():%Y-%m-%d %H:%M} UTC</i>")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("Lorentzian Scanner starting…")
    run_scan()
    schedule_time = os.getenv("SCAN_TIME_UTC", "23:00")
    schedule.every().day.at(schedule_time).do(run_scan)
    log.info("Next scheduled run at %s UTC daily.", schedule_time)
    while True:
        schedule.run_pending()
        time.sleep(60)
