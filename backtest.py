"""
Lorentzian Classification Backtester
Tests 4 filter combinations on 2 years of 4H data.
Sends results to Telegram when done.
"""

import warnings
warnings.filterwarnings("ignore")

import time
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime

TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD",
    "OKLO", "PLTR", "RKLB", "SMR",
    "JPM", "GS", "BAC",
    "XOM", "CVX",
    "NFLX", "CRM", "ADBE",
    "SPY", "QQQ",
]

HOLD_CANDLES = [3, 5, 10]


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

def lorentzian_signals(df, neighbors=8, max_bars_back=2000):
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


# ── Download with retry ───────────────────────────────────────────────────────

def download_with_retry(ticker, retries=3):
    for attempt in range(retries):
        try:
            time.sleep(2)   # 2s between every download — avoids rate limit
            df = yf.download(ticker, period="2y", interval="4h",
                             progress=False, auto_adjust=True)
            if df.empty:
                return None
            # Flatten MultiIndex columns if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [col[0] for col in df.columns]
            df.columns = [c.lower() for c in df.columns]
            return df
        except Exception as e:
            wait = 15 * (attempt + 1)
            print(f"  {ticker} attempt {attempt+1} failed: {e} — waiting {wait}s")
            time.sleep(wait)
    return None


# ── Per-ticker backtest ───────────────────────────────────────────────────────

def backtest_ticker(ticker):
    print(f"  Processing {ticker}...", end=" ", flush=True)
    df = download_with_retry(ticker)

    if df is None or len(df) < 200:
        print("skipped (no data)")
        return None

    sig    = lorentzian_signals(df)
    rsi_   = rsi(df["close"], 14).fillna(50)
    wvwap  = weekly_vwap(df)
    vol_ma = df["volume"].rolling(20).mean()

    results = []
    for i in range(50, len(df) - max(HOLD_CANDLES) - 1):
        if not (sig.iloc[i] == 1 and sig.iloc[i-1] != 1):
            continue
        entry       = df["close"].iloc[i]
        above_vwap  = entry > wvwap.iloc[i] if not np.isnan(wvwap.iloc[i]) else False
        vol_spike   = df["volume"].iloc[i] > 1.5 * vol_ma.iloc[i] if not np.isnan(vol_ma.iloc[i]) else False
        rsi_ok      = rsi_.iloc[i] < 70
        rets        = {h: (df["close"].iloc[i+h] - entry) / entry * 100 for h in HOLD_CANDLES}
        results.append({"date": df.index[i], "above_vwap": above_vwap,
                         "vol_spike": vol_spike, "rsi_ok": rsi_ok,
                         **{f"ret_{h}": rets[h] for h in HOLD_CANDLES}})

    print(f"{len(results)} signals")
    return pd.DataFrame(results) if results else None


# ── Summary helper ────────────────────────────────────────────────────────────

def summarise(df, label):
    if df is None or df.empty:
        return {"Filter": label, "Signals": 0,
                **{f"WR_{h}c": "—" for h in HOLD_CANDLES},
                **{f"Avg_{h}c": "—" for h in HOLD_CANDLES}}
    row = {"Filter": label, "Signals": len(df)}
    for h in HOLD_CANDLES:
        col = f"ret_{h}"
        row[f"WR_{h}c"]  = f"{(df[col] > 0).mean()*100:.1f}%"
        row[f"Avg_{h}c"] = f"{df[col].mean():+.2f}%"
    return row


# ── Main ──────────────────────────────────────────────────────────────────────

def run_backtest():
    print("\n" + "="*60)
    print(" LORENTZIAN BACKTEST — 2 years 4H data")
    print(f" Tickers: {', '.join(TICKERS)}")
    print("="*60 + "\n")

    all_raw = []
    for ticker in TICKERS:
        raw = backtest_ticker(ticker)
        if raw is not None:
            raw["ticker"] = ticker
            all_raw.append(raw)

    if not all_raw:
        print("No data collected — possible rate limit.")
        from alerts import send_alert
        send_alert("❌ Backtest failed — Yahoo Finance rate limit hit. Try again in 1 hour.")
        return

    df = pd.concat(all_raw, ignore_index=True)
    print(f"\nTotal raw signals: {len(df)}\n")

    f1 = df
    f2 = df[df["above_vwap"]]
    f3 = df[df["above_vwap"] & df["vol_spike"]]
    f4 = df[df["above_vwap"] & df["vol_spike"] & df["rsi_ok"]]

    summary = pd.DataFrame([
        summarise(f1, "1. Lorentzian only"),
        summarise(f2, "2. + Weekly VWAP"),
        summarise(f3, "3. + VWAP + Volume"),
        summarise(f4, "4. + VWAP + Vol + RSI<70"),
    ])

    print("="*60)
    print(" RESULTS")
    print("="*60)
    print(summary.to_string(index=False))

    # Per-ticker breakdown
    ticker_rows = []
    for t in TICKERS:
        sub = f4[f4["ticker"] == t]
        if sub.empty:
            continue
        r = {"Ticker": t, "Signals": len(sub)}
        for h in HOLD_CANDLES:
            r[f"WR_{h}c"]  = f"{(sub[f'ret_{h}']>0).mean()*100:.0f}%"
            r[f"Avg_{h}c"] = f"{sub[f'ret_{h}'].mean():+.2f}%"
        ticker_rows.append(r)

    # Send to Telegram
    try:
        from alerts import send_alert
        msg = "📊 <b>BACKTEST RESULTS — 2yr 4H</b>\n\n<pre>"
        msg += f"{'Filter':<26}{'Sig':>4}{'WR3':>6}{'WR5':>6}{'WR10':>6}{'Avg5':>7}\n"
        msg += "-" * 52 + "\n"
        for _, row in summary.iterrows():
            msg += f"{row['Filter']:<26}{str(row['Signals']):>4}{str(row['WR_3c']):>6}{str(row['WR_5c']):>6}{str(row['WR_10c']):>6}{str(row['Avg_5c']):>7}\n"
        msg += "</pre>"

        if ticker_rows:
            msg += "\n<b>Per-ticker (Filter 4):</b>\n<pre>"
            for r in ticker_rows[:12]:
                msg += f"{r['Ticker']:<6}{r['Signals']:>2}sig  WR5:{r['WR_5c']}  Avg5:{r['Avg_5c']}\n"
            msg += "</pre>"

        msg += f"\n<i>Ran at {datetime.utcnow():%Y-%m-%d %H:%M} UTC</i>"
        send_alert(msg)
        print("\nResults sent to Telegram ✅")
    except Exception as e:
        print(f"\nTelegram send failed: {e}")


if __name__ == "__main__":
    run_backtest()
