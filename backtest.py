"""
Lorentzian Classification Backtester
Tests 4 filter combinations on 2 years of 4H data:
  1. Lorentzian only
  2. Lorentzian + Weekly VWAP
  3. Lorentzian + Weekly VWAP + Volume spike
  4. Lorentzian + Weekly VWAP + Volume spike + RSI < 70

Results show: signal count, win rate, avg return at 3 / 5 / 10 candles
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime

# ── Ticker watchlist (liquid, well-known names) ──────────────────────────────
TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD",
    "OKLO", "PLTR", "RKLB", "SMR",                      # your speculative names
    "JPM", "GS", "BAC",                                  # financials
    "XOM", "CVX",                                        # energy
    "NFLX", "CRM", "ADBE",                               # tech
    "SPY", "QQQ",                                        # ETFs as benchmark
]

HOLD_CANDLES = [3, 5, 10]   # measure return at N candles after signal


# ── Technical indicators ─────────────────────────────────────────────────────

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
    """Approximate weekly VWAP: cumulative from Monday open, reset each week."""
    tp  = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"]
    week = tp.index.to_series().dt.isocalendar().week.values
    year = tp.index.to_series().dt.isocalendar().year.values
    key  = year * 100 + week
    vwap = pd.Series(index=df.index, dtype=float)
    cum_tp_vol = 0.0
    cum_vol    = 0.0
    prev_key   = None
    for i, idx in enumerate(df.index):
        k = key[i]
        if k != prev_key:
            cum_tp_vol = 0.0
            cum_vol    = 0.0
            prev_key   = k
        cum_tp_vol += tp.iloc[i] * vol.iloc[i]
        cum_vol    += vol.iloc[i]
        vwap.iloc[i] = cum_tp_vol / cum_vol if cum_vol > 0 else np.nan
    return vwap


# ── Backtest engine ───────────────────────────────────────────────────────────

def backtest_ticker(ticker):
    try:
        df = yf.download(ticker, period="2y", interval="4h",
                         progress=False, auto_adjust=True)
        if df.empty or len(df) < 200:
            return None
        # Flatten MultiIndex columns if present (newer yfinance)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]
        df.columns = [c.lower() for c in df.columns]

        sig  = lorentzian_signals(df)
        rsi_ = rsi(df["close"], 14).fillna(50)
        wvwap = weekly_vwap(df)
        vol_ma = df["volume"].rolling(20).mean()

        results = []

        for i in range(50, len(df) - max(HOLD_CANDLES) - 1):
            # Fresh green flip only
            if not (sig.iloc[i] == 1 and sig.iloc[i-1] != 1):
                continue

            entry_price = df["close"].iloc[i]
            bar_rsi     = rsi_.iloc[i]
            bar_vwap    = wvwap.iloc[i]
            bar_vol     = df["volume"].iloc[i]
            bar_vol_ma  = vol_ma.iloc[i]

            # Filter flags
            above_vwap  = entry_price > bar_vwap if not np.isnan(bar_vwap) else False
            vol_spike   = bar_vol > 1.5 * bar_vol_ma if not np.isnan(bar_vol_ma) else False
            rsi_ok      = bar_rsi < 70

            # Returns at each hold period
            rets = {}
            for h in HOLD_CANDLES:
                exit_price = df["close"].iloc[i + h]
                rets[h] = (exit_price - entry_price) / entry_price * 100

            results.append({
                "date":        df.index[i],
                "above_vwap":  above_vwap,
                "vol_spike":   vol_spike,
                "rsi_ok":      rsi_ok,
                **{f"ret_{h}": rets[h] for h in HOLD_CANDLES},
            })

        return pd.DataFrame(results) if results else None

    except Exception as e:
        print(f"  ✗ {ticker}: {e}")
        return None


def summarise(df, label):
    if df is None or df.empty:
        return {"Filter": label, "Signals": 0, **{f"WR_{h}c": "—" for h in HOLD_CANDLES},
                **{f"Avg_{h}c": "—" for h in HOLD_CANDLES}}
    row = {"Filter": label, "Signals": len(df)}
    for h in HOLD_CANDLES:
        col = f"ret_{h}"
        wr  = (df[col] > 0).mean() * 100
        avg = df[col].mean()
        row[f"WR_{h}c"]  = f"{wr:.1f}%"
        row[f"Avg_{h}c"] = f"{avg:+.2f}%"
    return row


# ── Main ──────────────────────────────────────────────────────────────────────

def run_backtest():
    print("\n" + "="*60)
    print(" LORENTZIAN BACKTEST — 2 years 4H data")
    print(f" Tickers: {', '.join(TICKERS)}")
    print("="*60 + "\n")

    all_raw = []

    for ticker in TICKERS:
        print(f"  Processing {ticker}...", end=" ", flush=True)
        raw = backtest_ticker(ticker)
        if raw is not None:
            raw["ticker"] = ticker
            all_raw.append(raw)
            print(f"{len(raw)} signals found")
        else:
            print("skipped")

    if not all_raw:
        print("No data collected.")
        return

    df = pd.concat(all_raw, ignore_index=True)
    total = len(df)
    print(f"\nTotal raw signals across all tickers: {total}\n")

    # ── 4 filter combinations ────────────────────────────────────────────────
    f1 = df                                                          # Lorentzian only
    f2 = df[df["above_vwap"]]                                       # + Weekly VWAP
    f3 = df[df["above_vwap"] & df["vol_spike"]]                     # + Volume
    f4 = df[df["above_vwap"] & df["vol_spike"] & df["rsi_ok"]]     # + RSI < 70

    summary = pd.DataFrame([
        summarise(f1, "1. Lorentzian only"),
        summarise(f2, "2. + Weekly VWAP"),
        summarise(f3, "3. + Weekly VWAP + Volume"),
        summarise(f4, "4. + Weekly VWAP + Volume + RSI<70"),
    ])

    print("="*60)
    print(" RESULTS")
    print("="*60)
    print(summary.to_string(index=False))
    print()

    # ── Per-ticker breakdown for best filter ─────────────────────────────────
    print("="*60)
    print(" PER-TICKER BREAKDOWN (Filter 4 — full stack)")
    print("="*60)
    ticker_rows = []
    for t in TICKERS:
        sub = f4[f4["ticker"] == t]
        if sub.empty:
            continue
        r = {"Ticker": t, "Signals": len(sub)}
        for h in HOLD_CANDLES:
            col = f"ret_{h}"
            r[f"WR_{h}c"]  = f"{(sub[col]>0).mean()*100:.0f}%"
            r[f"Avg_{h}c"] = f"{sub[col].mean():+.2f}%"
        ticker_rows.append(r)
    if ticker_rows:
        print(pd.DataFrame(ticker_rows).to_string(index=False))

    print("\n✅ Backtest complete.")
    print(f"   Run timestamp: {datetime.utcnow():%Y-%m-%d %H:%M} UTC\n")

    # Save CSV for further analysis
    df.to_csv("backtest_raw.csv", index=False)
    print("   Raw signals saved to backtest_raw.csv")

    # Send results to Telegram
    try:
        from alerts import send_alert
        msg = "📊 <b>BACKTEST RESULTS — 2yr 4H</b>\n\n"
        msg += "<pre>"
        msg += f"{'Filter':<35} {'Sig':>4} {'WR3':>6} {'WR5':>6} {'WR10':>6}\n"
        msg += "-"*62 + "\n"
        for _, row in summary.iterrows():
            msg += f"{row['Filter']:<35} {str(row['Signals']):>4} {str(row['WR_3c']):>6} {str(row['WR_5c']):>6} {str(row['WR_10c']):>6}\n"
        msg += "</pre>"
        if ticker_rows:
            msg += "\n<b>Best tickers (Filter 4):</b>\n<pre>"
            for r in ticker_rows[:10]:
                msg += f"{r['Ticker']:<6} {r['Signals']:>2}sig  WR5:{r['WR_5c']}  Avg:{r['Avg_5c']}\n"
            msg += "</pre>"
        send_alert(msg)
        print("   Results sent to Telegram ✅")
    except Exception as e:
        print(f"   Telegram send failed: {e}")


if __name__ == "__main__":
    run_backtest()
