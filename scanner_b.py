"""
Lorentzian Scanner B — v3 with Phase 1 fixes
- Lorentzian KNN with correct WT(10,11), 4-bar label horizon, normalized features
- Weekly VWAP filter (re-introduced)
- User exclusion list (oil, weapons, drones)
- Alpaca IEX data source
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
from tickers import get_sp500, get_nasdaq100, filter_excluded, EXCLUDED_TICKERS

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

def wt(high, low, close, cl=10, al=11):
    """
    Wave Trend histogram (wt1 - wt2), matches TradingView Lorentzian Classification.
    FIX vs v2: al was 21, now 11 per TV default; returns histogram, not wt1.
    """
    hlc3 = (high + low + close) / 3
    esa  = ema(hlc3, cl)
    d    = ema((hlc3 - esa).abs(), cl)
    ci   = (hlc3 - esa) / (0.015 * d.replace(0, np.nan))
    wt1  = ema(ci, al)
    wt2  = wt1.rolling(4).mean()
    return wt1 - wt2

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


def lorentzian_signal(df, neighbors=8, max_bars_back=2000, label_horizon=4):
    """
    Lorentzian KNN signal generator. Phase 1 fixes:
    - WT now uses (10, 11) and returns histogram (in wt function)
    - Features normalized to roughly [0, 1] range so distance is balanced
    - Label horizon is 4-bar forward (was 1-bar), matches TradingView default
    """
    close = df["close"]; high = df["high"]; low = df["low"]

    # Raw indicator values
    f1_raw = rsi(close, 14).fillna(50)
    f2_raw = wt(high, low, close).fillna(0)
    f3_raw = cci(high, low, close, 20).fillna(0)
    f4_raw = adx(high, low, close, 20).fillna(20)
    f5_raw = rsi(close, 9).fillna(50)

    # Normalize to roughly [0, 1] so all features contribute equally to distance
    f1 = (f1_raw / 100.0).clip(0, 1)                        # RSI 14
    f2 = (np.tanh(f2_raw / 50.0) + 1.0) / 2.0               # WT histogram → tanh squash
    f3 = (np.tanh(f3_raw / 200.0) + 1.0) / 2.0              # CCI → tanh squash
    f4 = (f4_raw / 100.0).clip(0, 1)                        # ADX
    f5 = (f5_raw / 100.0).clip(0, 1)                        # RSI 9

    features = np.column_stack([f1, f2, f3, f4, f5])
    n = len(features)
    signals = np.zeros(n)

    for i in range(50, n):
        lb = min(i, max_bars_back)
        pairs = []
        for j in range(i - lb, i - label_horizon):
            if j + label_horizon >= n:
                break
            dist = lorentzian_distance(features[i], features[j])
            lbl  = 1 if close.iloc[j + label_horizon] > close.iloc[j] else -1
            pairs.append((dist, lbl))
        if not pairs:
            continue
        pairs.sort()
        vote = sum(l for _, l in pairs[:neighbors])
        signals[i] = 1 if vote > 0 else (-1 if vote < 0 else 0)

    return pd.Series(signals, index=df.index)


# ── Weekly VWAP ───────────────────────────────────────────────────────────────

def weekly_vwap(df):
    """Running weekly VWAP. Resets each Monday."""
    df = df.copy()
    df["_week"] = df.index.to_series().dt.to_period("W-FRI").dt.start_time
    tp = (df["high"] + df["low"] + df["close"]) / 3
    pv = tp * df["volume"]
    cum_pv  = pv.groupby(df["_week"]).cumsum()
    cum_vol = df["volume"].groupby(df["_week"]).cumsum()
    vwap = cum_pv / cum_vol.replace(0, np.nan)
    vwap.index = df.index
    return vwap


# ── Alpaca data fetch ─────────────────────────────────────────────────────────

def fetch_bars(ticker):
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

        # Weekly VWAP
        vwap = weekly_vwap(df)
        last_vwap = float(vwap.iloc[-1]) if not np.isnan(vwap.iloc[-1]) else None
        if last_vwap is None:
            counters["no_data"] += 1
            return None

        counters["passed"] += 1

        # Lorentzian
        sig      = lorentzian_signal(df)
        last_sig = sig.iloc[-1]
        prev_sig = sig.iloc[-2]

        # Buy: fresh flip to +1 AND price above weekly VWAP
        if last_sig == 1 and prev_sig != 1 and last_price > last_vwap:
            return {"side": "BUY", "ticker": ticker, "price": round(last_price, 2),
                    "vwap": round(last_vwap, 2)}
        # Sell: fresh flip to -1 AND price below weekly VWAP
        if last_sig == -1 and prev_sig != -1 and last_price < last_vwap:
            return {"side": "SELL", "ticker": ticker, "price": round(last_price, 2),
                    "vwap": round(last_vwap, 2)}

        # Track signals that were filtered out by VWAP
        if last_sig == 1 and prev_sig != 1:
            counters["vwap_rejected"] += 1
        elif last_sig == -1 and prev_sig != -1:
            counters["vwap_rejected"] += 1

        return None
    except Exception as e:
        log.debug("Error on %s: %s", ticker, e)
        counters["no_data"] += 1
        return None


# ── Main scan loop ────────────────────────────────────────────────────────────

def run_scan():
    log.info("=== Lorentzian v3 scan (Alpaca + VWAP + Phase 1 fixes) ===")
    send_alert("🔍 <b>Lorentzian Scanner v3 [LC+VWAP]</b>\n"
               "Data: <b>Alpaca IEX</b> · Daily · Phase 1 fixes\n"
               "<i>Filters: Lorentz flip + Weekly VWAP + Vol&gt;100K + Price&gt;$5</i>\n"
               f"<i>Excluded: oil/gas, weapons, drones ({len(EXCLUDED_TICKERS)} tickers)</i>")

    if _client is None:
        send_alert("❌ Alpaca API keys missing — set ALPACA_API_KEY and ALPACA_API_SECRET in Railway env vars.")
        return

    raw_tickers = list(set(get_sp500() + get_nasdaq100()))
    tickers = filter_excluded(raw_tickers)
    excluded_count = len(raw_tickers) - len(tickers)
    log.info("Tickers after exclusion: %d (excluded %d)", len(tickers), excluded_count)

    signals = []
    workers = int(os.getenv("SCAN_WORKERS", "8"))
    counters = {"no_data": 0, "price": 0, "volume": 0,
                "passed": 0, "vwap_rejected": 0}

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(scan_stock, t, counters): t for t in tickers}
        done = 0
        for future in concurrent.futures.as_completed(futures):
            done += 1
            result = future.result()
            if result:
                signals.append(result)
                log.info("[LC+VWAP] %s: %s @ $%s (vwap $%s)",
                         result["side"], result["ticker"], result["price"], result["vwap"])
            if done % 50 == 0:
                log.info("Progress: %d / %d", done, len(tickers))

    log.info("[LC+VWAP] Scan complete. %d signal(s) found.", len(signals))

    filter_msg = (f"📊 <b>[LC+VWAP] Filter breakdown</b>\n"
                  f"Total in universe: {len(raw_tickers)}\n"
                  f"🚫 Excluded (oil/weapons/drones): {excluded_count}\n"
                  f"📥 Scanned: {len(tickers)}\n"
                  f"✅ Passed price/vol filters: {counters['passed']}\n"
                  f"❌ No data: {counters['no_data']}\n"
                  f"❌ Price &lt;$5: {counters['price']}\n"
                  f"❌ Volume &lt;100K: {counters['volume']}\n"
                  f"🟡 Lorentz fired but rejected by VWAP: {counters['vwap_rejected']}")
    send_alert(filter_msg)

    buys  = [s for s in signals if s["side"] == "BUY"]
    sells = [s for s in signals if s["side"] == "SELL"]

    if buys or sells:
        msg = "🎯 <b>[LC+VWAP] SIGNALS</b>\n\n"
        if buys:
            msg += "🟢 <b>BUY</b> (price &gt; weekly VWAP):\n"
            for s in buys:
                msg += f"<b>{s['ticker']}</b> ${s['price']} (vwap ${s['vwap']})\n"
            msg += "\n"
        if sells:
            msg += "🔴 <b>SELL</b> (price &lt; weekly VWAP):\n"
            for s in sells:
                msg += f"<b>{s['ticker']}</b> ${s['price']} (vwap ${s['vwap']})\n"
            msg += "\n"
        msg += f"<i>Scanned {len(tickers)} stocks · {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC</i>"
        send_alert(msg)
    else:
        send_alert(f"✅ [LC+VWAP] Scan complete — no signals today.\n"
                   f"<i>Scanned {len(tickers)} stocks · "
                   f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC</i>")


if __name__ == "__main__":
    log.info("Lorentzian Scanner v3 starting...")
    run_scan()
    schedule_time = os.getenv("SCAN_TIME_UTC", "23:00")
    schedule.every().day.at(schedule_time).do(run_scan)
    log.info("Next scheduled run at %s UTC daily.", schedule_time)
    while True:
        schedule.run_pending()
        time.sleep(60)
