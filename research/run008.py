"""
Run 008 — null baseline: entries that pass the same gates WITHOUT the Lorentzian signal. Pre-registered: research/runs/2026-10-01_null-baseline.md
Compares with the Lorentzian trades saved by run 007 (S&P 500, 250-bar window).
Usage: python research/run008.py --workers 4 --out DIR --lor PATH_TO_run007_sp500_trades.pkl   (--sim-only to re-report)
"""
import argparse, concurrent.futures, logging, os, sys, time
import numpy as np, pandas as pd, yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run001 as R
import run004 as P4
from backtest import (simulate_exit, fetch_bars, bench_context, get_universe, MIN_PRICE, MIN_DOLLAR_VOLUME,
                      VOLUME_MIN_RATIO, MIN_ENTRY_MOMENTUM, BENCHMARK)

log = logging.getLogger("run008")


def run_ticker(ticker, df, bench, start_ts):
    avg20 = df["volume"].rolling(20).mean().shift(1)
    ema50 = df["close"].ewm(span=50, adjust=False).mean()
    ret1 = df["close"].pct_change()
    ctx = bench.reindex(df.index)
    d = df["close"].diff()
    g = d.clip(lower=0).ewm(com=13, adjust=False).mean()
    ls = (-d.clip(upper=0)).ewm(com=13, adjust=False).mean()
    rsi = 100 - 100 / (1 + g / ls.replace(0, np.nan))
    c, v = df["close"], df["volume"]
    ema_ok = (ema50.isna() | (c >= ema50)); rsi_ok = (rsi.isna() | ((rsi >= 40) & (rsi <= 70)))
    ok = ((df.index >= start_ts) & ctx["min_vote"].notna() & (c >= MIN_PRICE) & (c * v >= MIN_DOLLAR_VOLUME)
          & (avg20.isna() | (avg20 <= 0) | (v >= VOLUME_MIN_RATIO * avg20)) & ret1.notna() & ctx["bench_ret"].notna()
          & (ret1 >= MIN_ENTRY_MOMENTUM))
    out = []
    for t in [int(i) for i in np.flatnonzero(ok.to_numpy()) if R.LC_MIN_BARS <= i < len(df) - 1]:
        tr = simulate_exit(df, t, R.RULES, None, ticker, 0, "NA")
        if not tr:
            continue
        e = df.index.get_loc(tr.entry_date); x = df.index.get_loc(tr.exit_date)
        out.append((ticker, df.index[t], tr.entry_date, tr.exit_date, tr.entry, tr.exit, tr.pnl_pct,
                    bool(ema_ok.iloc[t] and rsi_ok.iloc[t]), list(df.index[e:x]), [float(z) for z in df["close"].iloc[e:x]]))
    return out


COLS = ["ticker", "signal_date", "entry_date", "exit_date", "entry", "exit", "pnl_pct", "gates_ok", "path_dates", "path_close"]


def report(null, lor, spy):
    for name, mn, ml in (("BASE gates (EMA+RSI on)", null.gates_ok, lor.gates_ok), ("H-B gates (EMA+RSI off)", null.gates_ok | True, lor.gates_ok | True)):
        n, l = null[mn], lor[ml]
        print(f"\n=== {name}: per-trade, gross ===")
        rows = []
        for who, d in (("NULL (no Lorentzian)", n), ("LORENTZIAN", l)):
            for per, (s, e) in (("IS", (R.IS_START, R.OOS_START)), ("OOS", (R.OOS_START, None))):
                sub = d[(d.signal_date >= s) & ((d.signal_date < e) if e is not None else True)]
                rows.append({"who": who, "period": per, **{k: v for k, v in R.row("", sub.pnl_pct).items() if k}})
        print(pd.DataFrame(rows).to_string(index=False))
    days = spy.index[spy.index >= R.OOS_START]
    print(f"\n=== portfolio OOS {days[0].date()} -> {days[-1].date()}, gross, 5 seeds ===")
    for name, mn, ml in (("BASE gates", null.gates_ok, lor.gates_ok), ("H-B gates", null.gates_ok | True, lor.gates_ok | True)):
        for who, d in (("NULL", null[mn]), ("LORENTZIAN", lor[ml])):
            t = d[d.entry_date >= R.OOS_START]
            r = pd.DataFrame([P4.stats(P4.simulate(t, days, s)[0]) for s in range(5)])
            print(f"  {name:10s} {who:10s} signals {len(t):6d} | total% med {r['total %'].median():6.1f} [{r['total %'].min():.1f}..{r['total %'].max():.1f}] | maxDD {r['max DD %'].median()} | Sharpe {r['Sharpe'].median()}")
    print("  SPY buy&hold:", P4.stats(spy.loc[days] / spy.loc[days].iloc[0]))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=4); ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="."); ap.add_argument("--lor", required=True); ap.add_argument("--sim-only", action="store_true")
    a = ap.parse_args(); path = os.path.join(a.out, "run008_null_trades.pkl")
    spy = yf.download("SPY", period="6y", interval="1d", auto_adjust=True, progress=False)["Close"].squeeze()
    spy.index = spy.index.tz_localize(None) if spy.index.tz is not None else spy.index
    spy = spy[spy.index < pd.Timestamp.today().normalize()]
    lor = pd.read_pickle(a.lor)
    lor["pnl_pct"] = (lor.exit / lor.entry - 1) * 100
    if a.sim_only:
        report(pd.read_pickle(path), lor, spy); return
    tickers = [t for t in get_universe("sp500") if t != BENCHMARK]
    if a.limit: tickers = tickers[::max(1, len(tickers) // a.limit)][:a.limit]
    bench = bench_context(5.0); bars = fetch_bars(tickers, 5.0)
    today = pd.Timestamp.today().normalize()
    bars = {k: v[v.index < today] for k, v in bars.items()}; bench = bench[bench.index < today]
    rows, t0 = [], time.time()
    with concurrent.futures.ProcessPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(run_ticker, s, d, bench, R.IS_START): s for s, d in bars.items()}
        for n, f in enumerate(concurrent.futures.as_completed(futs), 1):
            try: rows += f.result()
            except Exception as exc: log.warning("%s failed: %s", futs[f], exc)
            if n % 50 == 0:
                el = time.time() - t0; log.info("%d/%d | %d candidates | %.0fs", n, len(futs), len(rows), el)
    null = pd.DataFrame(rows, columns=COLS); os.makedirs(a.out, exist_ok=True); null.to_pickle(path)
    report(null, lor, spy)


if __name__ == "__main__":
    main()
