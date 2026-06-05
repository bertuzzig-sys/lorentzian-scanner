"""
Lorentzian Scanner B — v5 TV-equivalent implementation
=======================================================
Fixes vs v4:
- KNN: replaced sort-and-take-k with TV's distance-accumulation algorithm
  (threshold grows as training loop iterates; skips every 4th bar)
- Features: RSI/ADX normalized to [-1,1] (bounded), WT uses wt1 (not histogram)
  normalized via tanh/60; CCI via tanh/100 — exactly matching Pine source
- Volatility filter: ATR(1) > ATR(10)  [TV default: ON]
- Regime filter: EMA(ohlc4,20) slope / ATR(10) > -0.1  [TV default: ON]
- Early signal flip: stat counter only — NOT a signal gate (TV behaviour)
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

def wt1_series(high, low, close, cl=10, al=11):
    """
    Wave Trend wt1 line (NOT the histogram).
    TV Lorentzian uses wt1 as the raw WT feature, then normalises via tanh/60.
    """
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
    atr_ = tr.ewm(alpha=1/n, adjust=False).mean()
    pdi  = 100 * pd.Series(pdm, index=high.index).ewm(alpha=1/n, adjust=False).mean() / atr_
    mdi  = 100 * pd.Series(mdm, index=high.index).ewm(alpha=1/n, adjust=False).mean() / atr_
    dx   = 100 * (pdi-mdi).abs() / (pdi+mdi).replace(0, np.nan)
    return dx.ewm(alpha=1/n, adjust=False).mean()

def atr_series(high, low, close, n):
    """ATR using RMA (EWM alpha=1/n), matches Pine's ta.atr()."""
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()


def lorentzian_distance(a, b):
    return float(np.sum(np.log1p(np.abs(a - b))))


def lorentzian_signal(df, neighbors=8, max_bars_back=2000, label_horizon=4):
    """
    Lorentzian KNN — v5, TV-equivalent.

    Key algorithm (matches Pine / JS reference):
    - For each bar i, iterate training bars oldest to newest, skipping bar if index % 4 == 0
    - Maintain a sliding list (max size = neighbors) of (distance, label) pairs
      where each new entry must have distance >= running threshold (lastDistance)
    - When list overflows, raise threshold to list[round(neighbors*3/4)] and drop oldest
    - Vote = sum of labels; filters applied before updating signal
    - Signal is sticky: holds previous value when vote is 0 OR filters fail
    """
    close = df["close"]; high = df["high"]; low = df["low"]; open_ = df["open"]

    # ── Feature series (TV defaults) ─────────────────────────────────────────
    # Feature 1: RSI(14)  → bounded [-1, 1]
    f1 = ((rsi(close, 14).fillna(50) / 100.0) * 2 - 1).clip(-1, 1)
    # Feature 2: WT wt1(10,11) → tanh(x / 60)
    f2 = np.tanh(wt1_series(high, low, close, 10, 11).fillna(0) / 60.0)
    # Feature 3: CCI(20) → tanh(x / 100)
    f3 = np.tanh(cci(high, low, close, 20).fillna(0) / 100.0)
    # Feature 4: ADX(20) → bounded [-1, 1]
    f4 = ((adx(high, low, close, 20).fillna(20) / 100.0) * 2 - 1).clip(-1, 1)
    # Feature 5: RSI(9) → bounded [-1, 1]
    f5 = ((rsi(close, 9).fillna(50) / 100.0) * 2 - 1).clip(-1, 1)

    features = np.column_stack([f1, f2, f3, f4, f5])
    n = len(features)

    # ── Training labels: +1 / -1 / 0 at bar i+4 ─────────────────────────────
    y_train = np.zeros(n)
    for i in range(n - label_horizon):
        if   close.iloc[i + label_horizon] > close.iloc[i]: y_train[i] =  1
        elif close.iloc[i + label_horizon] < close.iloc[i]: y_train[i] = -1

    # ── Volatility filter: ATR(1) > ATR(10) ──────────────────────────────────
    atr1  = atr_series(high, low, close, 1).values
    atr10 = atr_series(high, low, close, 10).values

    # ── Regime filter: EMA(ohlc4,20) slope / ATR(10) > -0.1 ─────────────────
    ohlc4      = (open_ + high + low + close) / 4
    ema20      = ema(ohlc4, 20).values
    ema20_prev = np.concatenate([[np.nan], ema20[:-1]])
    regime_val = np.where(
        atr10 > 0,
        ((ema20 - ema20_prev) / atr10) * 100,
        np.nan
    )

    # ── KNN loop ──────────────────────────────────────────────────────────────
    signals        = np.zeros(n)
    current_signal = 0

    for i in range(50, n):
        train_end   = i - label_horizon
        train_start = max(0, train_end - max_bars_back + 1)

        last_distance   = -1.0
        local_distances = []
        local_preds     = []

        for j in range(train_start, train_end + 1):
            if j % 4 == 0:
                continue                           # TV skips every 4th training bar

            dist = lorentzian_distance(features[i], features[j])

            if dist >= last_distance:
                last_distance = dist
                local_distances.append(dist)
                local_preds.append(y_train[j])

                if len(local_preds) > neighbors:
                    q_idx         = min(len(local_distances) - 1,
                                        round(neighbors * 3 / 4))
                    last_distance = local_distances[q_idx]
                    local_distances.pop(0)
                    local_preds.pop(0)

        vote = sum(local_preds)

        # ── Filters ───────────────────────────────────────────────────────────
        vol_ok    = bool(atr1[i] > atr10[i]) \
                    if not (np.isnan(atr1[i]) or np.isnan(atr10[i])) else True
        regime_ok = bool(regime_val[i] > -0.1) \
                    if not np.isnan(regime_val[i]) else True
        filters_ok = vol_ok and regime_ok

        # Sticky signal: only update on definitive vote AND passing filters
        if   vote > 0 and filters_ok: current_signal =  1
        elif vote < 0 and filters_ok: current_signal = -1
        # else: hold (Pine's nz(signal[1]))

        signals[i] = current_signal

    return pd.Series(signals, index=df.index)


def is_early_signal_flip(sig, lookback=4):
    """
    True if today's signal changed AND there was another change within `lookback` bars.
    NOTE: TV tracks this as a stat only — it does NOT suppress the signal.
    Used here purely for the Telegram counter.
    """
    if len(sig) < lookback + 2:
        return False
    if sig.iloc[-1] == sig.iloc[-2]:
        return False
    for k in range(lookback):
        idx_a = -2 - k
        idx_b = -3 - k
        if abs(idx_b) > len(sig):
            break
        if sig.iloc[idx_a] != sig.iloc[idx_b]:
            return True
    return False


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

        # Lorentzian (volatility + regime filters now inside)
        sig      = lorentzian_signal(df)
        last_sig = sig.iloc[-1]
        prev_sig = sig.iloc[-2]

        # Early flip: stat counter only — does NOT block the signal (TV behaviour)
        if is_early_signal_flip(sig, lookback=4):
            counters["early_flip"] += 1

        # BUY: fresh flip to +1 AND price above weekly VWAP
        if last_sig == 1 and prev_sig != 1 and last_price > last_vwap:
            return {"side": "BUY", "ticker": ticker, "price": round(last_price, 2),
                    "vwap": round(last_vwap, 2)}
        # SELL: fresh flip to -1 AND price below weekly VWAP
        if last_sig == -1 and prev_sig != -1 and last_price < last_vwap:
            return {"side": "SELL", "ticker": ticker, "price": round(last_price, 2),
                    "vwap": round(last_vwap, 2)}

        # Track signals filtered out by VWAP only
        if (last_sig == 1 and prev_sig != 1) or (last_sig == -1 and prev_sig != -1):
            counters["vwap_rejected"] += 1

        return None
    except Exception as e:
        log.debug("Error on %s: %s", ticker, e)
        counters["no_data"] += 1
        return None


# ── Main scan loop ────────────────────────────────────────────────────────────

def run_scan():
    log.info("=== Lorentzian v5 scan (TV-equivalent KNN + Vol/Regime filters) ===")
    send_alert("🔍 <b>Lorentzian Scanner v5 [LC+VWAP]</b>\n"
               "Data: <b>Alpaca IEX</b> · Daily · TV-equivalent KNN\n"
               "<i>Filters: Vol/Regime (TV defaults) + Weekly VWAP + Vol&gt;100K + Price&gt;$5</i>\n"
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
                "passed": 0, "vwap_rejected": 0, "early_flip": 0}

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
                  f"ℹ️ Early signal flip (stat only): {counters['early_flip']}\n"
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
    log.info("Lorentzian Scanner v5 starting...")
    run_scan()
    schedule_time = os.getenv("SCAN_TIME_UTC", "23:00")
    schedule.every().day.at(schedule_time).do(run_scan)
    log.info("Next scheduled run at %s UTC daily.", schedule_time)
    while True:
        schedule.run_pending()
        time.sleep(60)
