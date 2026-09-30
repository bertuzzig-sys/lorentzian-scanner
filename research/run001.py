"""
Run 001 — pre-registered in research/runs/2026-09-30_revalidate-winrate.md

One walk-forward pass over the S&P 500 (signal uses ONLY trailing bars). Every candidate signal is
tagged so three variants are compared on IDENTICAL data:

  BASE  current live stack: IWM relative-strength gate + IWM regime (MIN_VOTE 6 bull / 8 bear)
  H-A   no IWM at all: no RS gate, no regime, MIN_VOTE fixed at 6
  H-B   H-A + hammer candle on the signal bar or the bar before

Exits: 8% stop, 10-day hold, entry = next open (v11.0 config; preset "wide_stop_8pct").
NOT modelled: live "signal flip" exit (needs per-bar LC re-run during the hold).

Nothing here touches live config. Usage:
  python research/run001.py --workers 4 [--limit N] [--out DIR]
"""
import argparse, concurrent.futures, logging, os, sys, time
import numpy as np
import pandas as pd
import yfinance as yf
from advanced_ta import LorentzianClassification

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backtest import (PRESETS, simulate_exit, summarise, fetch_bars, bench_context, get_universe,
                      _weekly_vwap, MIN_PRICE, MIN_DOLLAR_VOLUME, VOLUME_MIN_RATIO,
                      MIN_ENTRY_MOMENTUM, _LC_FEATURES, _lc_filters, BENCHMARK)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("run001")

LC_WINDOW, LC_MIN_BARS = 400, 150
MIN_VOTE_NO_IWM = 6
OOS_START = pd.Timestamp("2025-10-01")
IS_START = pd.Timestamp("2022-10-01")
RULES = next(r for r in PRESETS if r.name == "wide_stop_8pct")   # 8% stop, 10-day hold


def hammer_series(df):
    """Pre-registered hammer: lower wick >= 2x body, upper wick <= 10% of range, close in top third,
    and a net decline over the 3 bars before it. Signal bar counts if hammer on t or t-1."""
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    rng = (h - l).replace(0, np.nan)
    body = (c - o).abs()
    lower = np.minimum(o, c) - l
    upper = h - np.maximum(o, c)
    ham = (lower >= 2 * body) & (upper <= 0.10 * rng) & (c >= l + (2 / 3) * rng) & (c.shift(1) < c.shift(4))
    ham = ham.fillna(False)
    return ham | ham.shift(1, fill_value=False)


def candidates(df, bench, start_ts):
    """Same gates as scanner_b.scan_stock EXCEPT the IWM relative-strength gate (tagged instead)."""
    vwap = _weekly_vwap(df)
    avg20 = df["volume"].rolling(20).mean().shift(1)
    ema50 = df["close"].ewm(span=50, adjust=False).mean()
    ret1 = df["close"].pct_change()
    ctx = bench.reindex(df.index)
    d = df["close"].diff()
    g = d.clip(lower=0).ewm(com=13, adjust=False).mean()
    ls = (-d.clip(upper=0)).ewm(com=13, adjust=False).mean()
    rsi = 100 - 100 / (1 + g / ls.replace(0, np.nan))
    c, v = df["close"], df["volume"]
    ok = ((df.index >= start_ts) & ctx["min_vote"].notna() & (c >= MIN_PRICE)
          & (c * v >= MIN_DOLLAR_VOLUME)
          & (avg20.isna() | (avg20 <= 0) | (v >= VOLUME_MIN_RATIO * avg20))
          & ret1.notna() & ctx["bench_ret"].notna() & (ret1 >= MIN_ENTRY_MOMENTUM)
          & (ema50.isna() | (c >= ema50)) & (rsi.isna() | ((rsi >= 40) & (rsi <= 70)))
          & vwap.notna() & (c > vwap))
    pos = np.flatnonzero(ok.to_numpy())
    return [int(i) for i in pos if LC_MIN_BARS <= i < len(df) - 1], ctx, ret1


def run_ticker(ticker, df, bench, start_ts):
    cands, ctx, ret1 = candidates(df, bench, start_ts)
    ham = hammer_series(df)
    out = []
    for t in cands:
        window = df.iloc[max(0, t - LC_WINDOW + 1):t + 1]
        if len(window) < LC_MIN_BARS:
            continue
        try:
            row = LorentzianClassification(window.copy(), features=_LC_FEATURES,
                                           filterSettings=_lc_filters()).df.iloc[-1]
        except Exception:
            continue
        if pd.isna(row.get("startLongTrade")):
            continue
        vote = int(row["prediction"])
        if vote < MIN_VOTE_NO_IWM:
            continue
        tr = simulate_exit(df, t, RULES, None, ticker, vote, str(ctx["regime"].iloc[t]))
        if not tr:
            continue
        out.append({"ticker": ticker, "signal_date": df.index[t], "entry_date": tr.entry_date,
                    "pnl_pct": tr.pnl_pct, "reason": tr.reason, "vote": vote,
                    "regime": str(ctx["regime"].iloc[t]),
                    "base": bool(ret1.iloc[t] > ctx["bench_ret"].iloc[t] and vote >= int(ctx["min_vote"].iloc[t])),
                    "hammer": bool(ham.iloc[t])})
    return out


def market_caps(tickers):
    def one(s):
        try:
            return s, float(yf.Ticker(s).fast_info["market_cap"])
        except Exception:
            return s, np.nan
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        return dict(ex.map(one, tickers))


def seg(cap):
    if not np.isfinite(cap): return "unknown"
    return ">200B" if cap >= 200e9 else "50-200B" if cap >= 50e9 else "10-50B" if cap >= 10e9 else "<10B"


def row(label, pnl):
    s = summarise(list(pnl))
    if not s.get("n"):
        return {"": label, "n": 0}
    return {"": label, "n": s["n"], "win%": round(s["win_rate"], 1), "PF": round(s["profit_factor"], 2),
            "avg%": round(s["expectancy"], 2), "median%": round(float(np.median(list(pnl))), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=".")
    a = ap.parse_args()
    tickers = [t for t in get_universe("sp500") if t != BENCHMARK]
    if a.limit:
        tickers = tickers[::max(1, len(tickers) // a.limit)][:a.limit]
    bench = bench_context(5.0)
    bars = fetch_bars(tickers, 5.0)
    today = pd.Timestamp.today().normalize()
    for k in list(bars):
        bars[k] = bars[k][bars[k].index < today]      # drop a partial same-day bar
    bench = bench[bench.index < today]
    log.info("run001 | %d tickers | IS from %s | OOS from %s", len(bars), IS_START.date(), OOS_START.date())
    trades, t0 = [], time.time()
    with concurrent.futures.ProcessPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(run_ticker, s, d, bench, IS_START): s for s, d in bars.items()}
        for n, f in enumerate(concurrent.futures.as_completed(futs), 1):
            try: trades += f.result()
            except Exception as exc: log.warning("%s failed: %s", futs[f], exc)
            if n % 20 == 0:
                el = time.time() - t0
                log.info("%d/%d tickers | %d signals | %.0fs | ~%.0fs left", n, len(futs), len(trades),
                         el, el / n * (len(futs) - n))
    df = pd.DataFrame(trades)
    if df.empty:
        print("no trades"); return
    caps = market_caps(sorted(df.ticker.unique()))
    df["cap"] = df.ticker.map(caps); df["segment"] = df.cap.map(seg)
    df["period"] = np.where(df.signal_date >= OOS_START, "OOS", "IS")
    df["H-A"] = True; df["H-B"] = df.hammer; df["BASE"] = df.base
    os.makedirs(a.out, exist_ok=True)
    df.to_csv(os.path.join(a.out, "run001_trades.csv"), index=False)
    log.info("saved %d signals", len(df))
    report(df)


def report(df):
    variants = [("BASE (IWM, live)", "BASE"), ("H-A (no IWM)", "H-A"), ("H-B (no IWM + hammer)", "H-B")]
    for per in ("IS", "OOS", "ALL"):
        sub = df if per == "ALL" else df[df.period == per]
        print(f"\n=== {per} ===")
        print(pd.DataFrame([row(lbl, sub[sub[col]].pnl_pct) for lbl, col in variants]).to_string(index=False))
    for lbl, col in variants:
        print(f"\n--- {lbl}: by market-cap segment (IS | OOS) ---")
        rows = []
        for sg in [">200B", "50-200B", "10-50B", "<10B"]:
            for per in ("IS", "OOS"):
                s = df[df[col] & (df.segment == sg) & (df.period == per)]
                rows.append({**row(f"{sg} {per}", s.pnl_pct)})
        print(pd.DataFrame(rows).to_string(index=False))
    print("\n--- BASE by regime (OOS) ---")
    o = df[df.BASE & (df.period == "OOS")]
    print(pd.DataFrame([row(rg, o[o.regime == rg].pnl_pct) for rg in ("BULL", "BEAR")]).to_string(index=False))


if __name__ == "__main__":
    main()
