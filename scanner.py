"""
Lorentzian Scanner — Full Filter Stack v2
Buy AND sell signals on 4H timeframe with:
  • Lorentzian green flip (buy) / red flip (sell)
  • Price above/below Weekly VWAP
  • Volume > 1.5x 20-bar average
  • Daily volume > 1M
  • Market cap $1B–$50B
"""

import os
import time
import json
import schedule
import logging
import concurrent.futures
from datetime import datetime, timedelta, timezone

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

MCAP_CACHE_FILE = "/tmp/mcap_cache.json"
MCAP_MIN = 1_000_000_000          # $1B
MCAP_MAX = 100_000_000_000         # $100B
MIN_DAILY_VOLUME = 1_000_000      # 1M shares/day
VOLUME_SPIKE_MULT = 1.5


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


# ── Market cap cache ──────────────────────────────────────────────────────────

def load_mcap_cache():
    if not os.path.exists(MCAP_CACHE_FILE):
        return {}
    try:
        with open(MCAP_CACHE_FILE) as f:
            data = json.load(f)
        # Drop entries older than 7 days
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        return {k: v for k, v in data.items() if v.get("ts", "") > cutoff}
    except Exception:
        return {}

def save_mcap_cache(cache):
    try:
        with open(MCAP_CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except Exception as e:
        log.debug("Cache save failed: %s", e)

def get_market_cap(ticker, cache):
    if ticker in cache:
        return cache[ticker]["mcap"]
    try:
        info = yf.Ticker(ticker).fast_info
        mcap = float(info.get("market_cap") or 0)
        cache[ticker] = {"mcap": mcap, "ts": datetime.now(timezone.utc).isoformat()}
        return mcap
    except Exception:
        cache[ticker] = {"mcap": 0, "ts": datetime.now(timezone.utc).isoformat()}
        return 0


# ── Per-stock scan ────────────────────────────────────────────────────────────

def scan_stock(ticker, mcap_cache):
    try:
        df = yf.download(ticker, period="6mo", interval="4h",
                         progress=False, auto_adjust=True)
        if df.empty or len(df) < 100:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]
        df.columns = [c.lower() for c in df.columns]

        last_price = float(df["close"].iloc[-1])
        if last_price < 5:
            return None

        # Approx daily volume (sum of last 6 4H bars ≈ 1 trading day)
        daily_vol = float(df["volume"].tail(6).sum())
        if daily_vol < MIN_DAILY_VOLUME:
            return None

        # Market cap filter
        mcap = get_market_cap(ticker, mcap_cache)
        if mcap < MCAP_MIN or mcap > MCAP_MAX:
            return None

        # ── Compute signals & filters ────────────────────────────────────────
        sig      = lorentzian_signal(df)
        vwap_val = float(weekly_vwap(df).iloc[-1])
        vol_ma   = float(df["volume"].rolling(20).mean().iloc[-1])
        last_vol = float(df["volume"].iloc[-1])

        last_sig = sig.iloc[-1]
        prev_sig = sig.iloc[-2]

        vol_spike = last_vol > VOLUME_SPIKE_MULT * vol_ma

        # ── BUY: fresh green flip + above VWAP + vol spike ───────────────────
        if last_sig == 1 and prev_sig != 1:
            if last_price > vwap_val and vol_spike:
                return {
                    "side":      "BUY",
                    "ticker":    ticker,
                    "price":     round(last_price, 2),
                    "vwap":      round(vwap_val, 2),
                    "vol_ratio": round(last_vol / vol_ma, 1),
                    "mcap_b":    round(mcap / 1e9, 1),
                }

        # ── SELL: fresh red flip + below VWAP + vol spike ────────────────────
        if last_sig == -1 and prev_sig != -1:
            if last_price < vwap_val and vol_spike:
                return {
                    "side":      "SELL",
                    "ticker":    ticker,
                    "price":     round(last_price, 2),
                    "vwap":      round(vwap_val, 2),
                    "vol_ratio": round(last_vol / vol_ma, 1),
                    "mcap_b":    round(mcap / 1e9, 1),
                }

        return None

    except Exception as e:
        log.debug("Error on %s: %s", ticker, e)
        return None


# ── Main scan loop ────────────────────────────────────────────────────────────

def run_scan():
    log.info("=== Lorentzian scan started ===")
    send_alert("🔍 <b>Lorentzian Scanner v2</b>\n"
               "Buy + Sell signals · 4H timeframe\n"
               "<i>Filters: Lorentz flip + Weekly VWAP + Volume spike + "
               "Mcap $1B-$50B + Vol&gt;1M/day</i>")

    tickers = list(set(get_sp500() + get_nasdaq100()))
    log.info("Total tickers: %d", len(tickers))

    mcap_cache = load_mcap_cache()
    log.info("Market cap cache: %d entries", len(mcap_cache))

    signals = []
    workers = int(os.getenv("SCAN_WORKERS", "4"))

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(scan_stock, t, mcap_cache): t for t in tickers}
        done = 0
        for future in concurrent.futures.as_completed(futures):
            done += 1
            result = future.result()
            if result:
                signals.append(result)
                log.info("%s: %s @ $%s | VWAP $%s | Vol %.1fx | Mcap $%.1fB",
                         result["side"], result["ticker"], result["price"],
                         result["vwap"], result["vol_ratio"], result["mcap_b"])
            if done % 50 == 0:
                log.info("Progress: %d / %d", done, len(tickers))

    save_mcap_cache(mcap_cache)
    log.info("Scan complete. %d signal(s) found.", len(signals))

    buys  = [s for s in signals if s["side"] == "BUY"]
    sells = [s for s in signals if s["side"] == "SELL"]

    if buys or sells:
        msg = "🎯 <b>LORENTZIAN SIGNALS</b>\n\n"
        if buys:
            msg += "🟢 <b>BUY:</b>\n"
            for s in buys:
                msg += (f"<b>{s['ticker']}</b> ${s['price']} "
                        f"(Mcap ${s['mcap_b']}B)\n"
                        f"VWAP: ${s['vwap']} · Vol: {s['vol_ratio']}x\n\n")
        if sells:
            msg += "🔴 <b>SELL:</b>\n"
            for s in sells:
                msg += (f"<b>{s['ticker']}</b> ${s['price']} "
                        f"(Mcap ${s['mcap_b']}B)\n"
                        f"VWAP: ${s['vwap']} · Vol: {s['vol_ratio']}x\n\n")
        msg += f"<i>Scanned {len(tickers)} stocks · {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC</i>"
        send_alert(msg)
    else:
        send_alert(f"✅ Scan complete — no signals today.\n"
                   f"<i>Scanned {len(tickers)} stocks · "
                   f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC</i>")


if __name__ == "__main__":
    log.info("Lorentzian Scanner v2 starting…")
    run_scan()
    schedule_time = os.getenv("SCAN_TIME_UTC", "23:00")
    schedule.every().day.at(schedule_time).do(run_scan)
    log.info("Next scheduled run at %s UTC daily.", schedule_time)
    while True:
        schedule.run_pending()
        time.sleep(60)
