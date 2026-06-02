"""
Lorentzian Backtester v3 — tests OBV + lower volume threshold
5 tickers, 5 years daily data
Compares filter stacks A/B/C
"""

import warnings
warnings.filterwarnings("ignore")

import time
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime

TICKERS = [
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN",
    # Growth / momentum
    "TSLA", "AMD", "PLTR", "OKLO", "RKLB", "SMR",
    # Mid-cap tech
    "CRM", "ADBE", "NFLX", "AVGO",
    # Financials
    "JPM", "GS", "BAC", "MS",
    # Energy
    "XOM", "CVX", "OXY",
    # Healthcare
    "UNH", "LLY", "JNJ",
    # Consumer / industrials
    "WMT", "COST", "CAT",
    # Benchmark
    "SPY",
]
HOLD_DAYS = [3, 5, 10]


# ── Indicators ────────────────────────────────────────────────────────────────

def ema(s, n): return s.ewm(span=n, adjust=False).mean()

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
    tr   = pd.concat([high-low, (high-close.shift()).abs(),
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
        if not pairs: continue
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

def obv(close, volume):
    """On-Balance Volume — cumulative volume signed by price direction."""
    direction = np.sign(close.diff().fillna(0))
    return (direction * volume).cumsum()


# ── Download ──────────────────────────────────────────────────────────────────

def download_daily(ticker):
    for attempt in range(3):
        try:
            time.sleep(3)
            df = yf.download(ticker, period="5y", interval="1d",
                             progress=False, auto_adjust=True)
            if df.empty: return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [col[0] for col in df.columns]
            df.columns = [c.lower() for c in df.columns]
            return df
        except Exception as e:
            print(f"  {ticker} attempt {attempt+1} failed: {e}")
            time.sleep(20 * (attempt + 1))
    return None


# ── Per-ticker backtest ───────────────────────────────────────────────────────

def backtest_ticker(ticker):
    print(f"\n→ {ticker}")
    df = download_daily(ticker)
    if df is None or len(df) < 200:
        print(f"  ✗ skipped"); return None
    print(f"  ✓ {len(df)} candles loaded, running KNN...")

    sig    = lorentzian_signals(df)
    wvwap  = weekly_vwap(df)
    vol_ma = df["volume"].rolling(20).mean()
    obv_   = obv(df["close"], df["volume"])
    obv_ma = obv_.rolling(20).mean()

    results = []
    for i in range(50, len(df) - max(HOLD_DAYS) - 1):
        if not (sig.iloc[i] == 1 and sig.iloc[i-1] != 1):
            continue
        entry      = df["close"].iloc[i]
        above_vwap = entry > wvwap.iloc[i] if not np.isnan(wvwap.iloc[i]) else False
        vol_spike  = df["volume"].iloc[i] > 1.5 * vol_ma.iloc[i] if not np.isnan(vol_ma.iloc[i]) else False
        obv_rising = obv_.iloc[i] > obv_ma.iloc[i] if not np.isnan(obv_ma.iloc[i]) else False
        rets       = {h: (df["close"].iloc[i+h] - entry) / entry * 100 for h in HOLD_DAYS}
        results.append({"date": df.index[i],
                        "above_vwap": above_vwap,
                        "vol_spike":  vol_spike,
                        "obv_rising": obv_rising,
                        **{f"ret_{h}": rets[h] for h in HOLD_DAYS}})
    print(f"  ✓ {len(results)} signals")
    return pd.DataFrame(results) if results else None


# ── Summary helper ────────────────────────────────────────────────────────────

def summarise(df, label):
    if df is None or df.empty:
        return {"Filter": label, "Sig": 0,
                **{f"WR{h}": "—" for h in HOLD_DAYS},
                **{f"Avg{h}": "—" for h in HOLD_DAYS}}
    row = {"Filter": label, "Sig": len(df)}
    for h in HOLD_DAYS:
        col = f"ret_{h}"
        row[f"WR{h}"]  = f"{(df[col] > 0).mean()*100:.0f}%"
        row[f"Avg{h}"] = f"{df[col].mean():+.1f}%"
    return row


# ── Main ──────────────────────────────────────────────────────────────────────

def run_backtest():
    print("="*60)
    print(" LORENTZIAN BACKTEST v3 — TESTING OBV FILTER")
    print(f" Tickers: {', '.join(TICKERS)}")
    print("="*60)

    all_raw = []
    for ticker in TICKERS:
        raw = backtest_ticker(ticker)
        if raw is not None:
            raw["ticker"] = ticker
            all_raw.append(raw)

    if not all_raw:
        print("\nNo data."); return

    df = pd.concat(all_raw, ignore_index=True)
    print(f"\nTotal signals: {len(df)}")

    # Filter stacks
    cur  = df[df["above_vwap"] & df["vol_spike"]]              # current live setup
    obv1 = df[df["above_vwap"] & df["vol_spike"] & df["obv_rising"]]  # + OBV
    # Note: we can't simulate "lower volume threshold" in backtest because
    # we have no mcap data here — but OBV alone vs not is the key question

    summary = pd.DataFrame([
        summarise(df,   "A. Lorentzian only"),
        summarise(cur,  "B. Current live (VWAP+Vol)"),
        summarise(obv1, "C. B + OBV confirmation"),
    ])
    print("\n" + summary.to_string(index=False))

    # Send to Telegram
    try:
        from alerts import send_alert
        msg = "📊 <b>BACKTEST v3 — OBV TEST</b>\n\n<pre>"
        msg += f"{'Filter':<28}{'Sig':>4}{'WR3':>5}{'WR5':>5}{'WR10':>5}\n"
        msg += "-" * 47 + "\n"
        for _, r in summary.iterrows():
            msg += f"{r['Filter']:<28}{str(r['Sig']):>4}{str(r['WR3']):>5}{str(r['WR5']):>5}{str(r['WR10']):>5}\n"
        msg += "</pre>\n"
        msg += "\n<i>If C beats B by 5%+ WR → deploy OBV. Otherwise keep B.</i>"
        send_alert(msg)
        print("\n✅ Sent to Telegram")
    except Exception as e:
        print(f"\nTelegram failed: {e}")


if __name__ == "__main__":
    run_backtest()
