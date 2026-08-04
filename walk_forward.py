"""
Walk-Forward Backtest (Stage 2) — the decisive test
===================================================
Stage 1 (backtest.py) ran LorentzianClassification ONCE over each ticker's full
history. advanced_ta normalises the CCI and WT features with MinMaxScaler over
the whole series, so every historical feature value is contaminated by future
extremes. Stage 1 is therefore an OPTIMISTIC UPPER BOUND, not a result.

This file removes that bias. For every candidate bar t it re-runs LC on ONLY
the trailing window ending at t, and uses the signal at the last bar of that
window — the one bar whose features could not have seen the future.

WHY THIS IS AFFORDABLE
A naive walk-forward is one LC run per ticker per bar: 200 x 750 = 150,000 runs.
But the cheap gates (price, dollar volume, volume ratio, RS vs benchmark,
momentum, 50-EMA, RSI band, VWAP) need no LC at all and reject ~91% of bar-days
(Stage 1: 186 of 2083 passed). So we vectorise those first and run LC only on
survivors — roughly a 10x reduction.

PRE-REGISTERED BAR (fixed 2026-08-01, before any Stage 2 result existed):
    PASS = profit factor >= 1.2 AND expectancy >= +0.2%/trade, large caps, n > 500
    FAIL = the Stage 1 edge was the look-ahead bias. Stop. Do not add a filter
           and retest — that was ruled out in advance.

Usage:
  python walk_forward.py --universe sp500 --limit 200 --years 3
  python walk_forward.py --tickers AAPL MSFT NVDA --years 2 --verbose
"""

import argparse
import concurrent.futures
import logging
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd
import yfinance as yf
from advanced_ta import LorentzianClassification

from backtest import (ExitRules, PRESETS, simulate_exit, summarise, fmt,
                      fetch_bars, bench_context, get_universe, _weekly_vwap,
                      MIN_PRICE, MIN_DOLLAR_VOLUME, VOLUME_MIN_RATIO,
                      MIN_ENTRY_MOMENTUM, _LC_FEATURES, _lc_filters, BENCHMARK)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("walkfwd")

LC_WINDOW = 400      # trailing bars fed to LC (live uses ~365d of daily bars)
LC_MIN_BARS = 150    # LC needs a warmup; skip candidates before this


def cheap_candidates(df, bench_ctx, start_ts):
    """
    Vectorised pre-filters — everything that does NOT need the Lorentzian.
    Returns integer bar positions that survive. These gates are identical to
    scanner_b.scan_stock, so the only thing LC adds is the flip + vote test.
    """
    vwap  = _weekly_vwap(df)
    avg20 = df["volume"].rolling(20).mean().shift(1)
    ema50 = df["close"].ewm(span=50, adjust=False).mean()
    ret1  = df["close"].pct_change()
    ctx   = bench_ctx.reindex(df.index)

    delta = df["close"].diff()
    gain  = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    rsi   = 100 - 100 / (1 + gain / loss.replace(0, np.nan))

    c, v = df["close"], df["volume"]
    ok = (
        (df.index >= start_ts)
        & ctx["min_vote"].notna()
        & (c >= MIN_PRICE)
        & (c * v >= MIN_DOLLAR_VOLUME)
        & (avg20.isna() | (avg20 <= 0) | (v >= VOLUME_MIN_RATIO * avg20))
        & ret1.notna() & ctx["bench_ret"].notna()
        & (ret1 > ctx["bench_ret"])
        & (ret1 >= MIN_ENTRY_MOMENTUM)
        & (ema50.isna() | (c >= ema50))
        & (rsi.isna() | ((rsi >= 40) & (rsi <= 70)))
        & vwap.notna() & (c > vwap)
    )
    pos = np.flatnonzero(ok.to_numpy())
    # need LC warmup behind, and one bar ahead to fill the entry
    return [int(i) for i in pos if i >= LC_MIN_BARS and i < len(df) - 1], ctx


def run_ticker_walkforward(ticker, df, bench_ctx, start_ts, rules_list, verbose=False):
    """One LC run per surviving candidate bar, using ONLY trailing data."""
    cands, ctx = cheap_candidates(df, bench_ctx, start_ts)
    if not cands:
        return [], 0
    sigs, lc_runs = [], 0
    for t in cands:
        lo = max(0, t - LC_WINDOW + 1)
        window = df.iloc[lo:t + 1]          # ends AT t — no future bars, ever
        if len(window) < LC_MIN_BARS:
            continue
        try:
            res = LorentzianClassification(window.copy(), features=_LC_FEATURES,
                                           filterSettings=_lc_filters()).df
        except Exception:
            continue
        lc_runs += 1
        row = res.iloc[-1]                  # the only uncontaminated bar
        if pd.isna(row.get("startLongTrade")):
            continue
        vote = int(row["prediction"])
        if vote < int(ctx["min_vote"].iloc[t]):
            continue
        sigs.append((t, vote, str(ctx["regime"].iloc[t])))

    if verbose and sigs:
        log.info("%s: %d candidates -> %d LC runs -> %d signals",
                 ticker, len(cands), lc_runs, len(sigs))

    trades = []
    for rules in rules_list:
        for t, vote, regime in sigs:
            # exits legitimately use future bars — that IS the forward return.
            # only the SIGNAL had to be free of look-ahead.
            tr = simulate_exit(df, t, rules, None, ticker, vote, regime)
            if tr:
                trades.append(tr)
    return trades, lc_runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+")
    ap.add_argument("--universe", choices=["sp500", "sp400", "sp600", "sp1500"])
    ap.add_argument("--years", type=float, default=3.0)
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    tickers = [t.upper() for t in a.tickers] if a.tickers else \
              (get_universe(a.universe) if a.universe else ap.error("need --tickers or --universe"))
    tickers = [t for t in tickers if t != BENCHMARK]
    if a.limit and len(tickers) > a.limit:
        # evenly spaced sample so we don't take an alphabetical slice (that bug
        # already bit us once when the live universe was truncated at ~"M")
        idx = np.linspace(0, len(tickers) - 1, a.limit).astype(int)
        tickers = [tickers[i] for i in sorted(set(idx))]

    ctx = bench_context(a.years)
    start = ctx.index[-1] - pd.DateOffset(days=int(a.years * 365))
    log.info("WALK-FORWARD | window %s -> %s | %d tickers | LC window %d bars",
             start.date(), ctx.index[-1].date(), len(tickers), LC_WINDOW)
    log.info("Signal uses ONLY trailing data. Exits use forward bars (correct).")

    bars = fetch_bars(tickers, a.years)
    t0 = time.time()
    trades, total_lc = [], 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(run_ticker_walkforward, s, d, ctx, start, PRESETS, a.verbose): s
                for s, d in bars.items()}
        for n, f in enumerate(concurrent.futures.as_completed(futs), 1):
            try:
                tr, runs = f.result()
                trades.extend(tr); total_lc += runs
            except Exception as exc:
                log.debug("failed: %s", exc)
            if n % 10 == 0:
                el = time.time() - t0
                log.info("%d/%d tickers | %d LC runs | %.0fs elapsed | ~%.0fs left",
                         n, len(futs), total_lc, el, el / n * (len(futs) - n))

    if not trades:
        print("\nNo trades generated."); return
    df = pd.DataFrame([t.__dict__ for t in trades])
    df.to_csv("walkforward_trades.csv", index=False)

    print("\n" + "=" * 118)
    print("WALK-FORWARD RESULTS — no look-ahead in the signal")
    print("=" * 118)
    order = [r.name for r in PRESETS if r.name in set(df["rule"])]
    for name in order:
        print(fmt(name, summarise(df[df["rule"] == name]["pnl_pct"].tolist())))

    base = order[0]
    sub = df[df["rule"] == base]
    print("\n" + "-" * 118); print(f"BREAKDOWN for '{base}'"); print("-" * 118)
    for rg in sorted(sub["regime"].unique()):
        print(fmt(f"regime={rg}", summarise(sub[sub["regime"] == rg]["pnl_pct"].tolist())))
    print(fmt("vote>=8", summarise(sub[sub["vote"] >= 8]["pnl_pct"].tolist())))
    print(fmt("vote 6-7", summarise(sub[sub["vote"] < 8]["pnl_pct"].tolist())))
    print("\nExit reasons:")
    print(sub.groupby("reason")["pnl_pct"].agg(["count", "mean"]).round(2).to_string())

    print("\n" + "=" * 118)
    print("VERDICT vs PRE-REGISTERED BAR (PF >= 1.2, expectancy >= +0.2%, n > 500)")
    print("=" * 118)
    for name in order:
        s = summarise(df[df["rule"] == name]["pnl_pct"].tolist())
        if not s.get("n"):
            continue
        passed = s["profit_factor"] >= 1.2 and s["expectancy"] >= 0.2 and s["n"] > 500
        why = []
        if s["profit_factor"] < 1.2:  why.append(f"PF {s['profit_factor']:.2f}<1.2")
        if s["expectancy"] < 0.2:     why.append(f"E {s['expectancy']:+.3f}<+0.2")
        if s["n"] <= 500:             why.append(f"n {s['n']}<=500")
        print(f"  {name:22s} {'PASS' if passed else 'FAIL':4s}  {'' if passed else '(' + ', '.join(why) + ')'}")
    print("\n  A FAIL here means the Stage 1 edge was the look-ahead bias.")
    print("  Trade log: walkforward_trades.csv")


if __name__ == "__main__":
    main()
