"""
Run 006 — history-window sensitivity (daily). Pre-registered: research/runs/2026-10-01_history-window.md
BASE v11.3 config evaluated with the Lorentzian fed the trailing 250 / 400 / 1000 bars. Reuses run 004's portfolio simulator.
Usage: python research/run006.py --workers 4 --out DIR   (add --sim-only to re-report saved trades)
"""
import argparse, concurrent.futures, logging, os, sys, time
import numpy as np, pandas as pd, yfinance as yf
from advanced_ta import LorentzianClassification as LC

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run001 as R
import run004 as P4
from backtest import (simulate_exit, fetch_bars, bench_context, get_universe, MIN_PRICE, MIN_DOLLAR_VOLUME,
                      VOLUME_MIN_RATIO, MIN_ENTRY_MOMENTUM, _LC_FEATURES, _lc_filters, BENCHMARK)

log = logging.getLogger("run006")
WINDOWS = (250, 400, 1000)


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
    ok = ((df.index >= start_ts) & ctx["min_vote"].notna() & (c >= MIN_PRICE) & (c * v >= MIN_DOLLAR_VOLUME)
          & (avg20.isna() | (avg20 <= 0) | (v >= VOLUME_MIN_RATIO * avg20)) & ret1.notna() & ctx["bench_ret"].notna()
          & (ret1 >= MIN_ENTRY_MOMENTUM))
    ema_ok = (ema50.isna() | (c >= ema50)); rsi_ok = (rsi.isna() | ((rsi >= 40) & (rsi <= 70)))
    out = []
    for t in [int(i) for i in np.flatnonzero(ok.to_numpy()) if R.LC_MIN_BARS <= i < len(df) - 1]:
        hits = {}
        for w in WINDOWS:
            try:
                row = LC(df.iloc[max(0, t - w + 1):t + 1].copy(), features=_LC_FEATURES, filterSettings=_lc_filters()).df.iloc[-1]
            except Exception:
                continue
            if not pd.isna(row.get("startLongTrade")) and int(row["prediction"]) >= R.MIN_VOTE_NO_IWM:
                hits[w] = True
        if not hits:
            continue
        tr = simulate_exit(df, t, R.RULES, None, ticker, 0, "NA")
        if not tr:
            continue
        e = df.index.get_loc(tr.entry_date); x = df.index.get_loc(tr.exit_date)
        rec = {"gates_ok": bool(ema_ok.iloc[t] and rsi_ok.iloc[t]), "ticker": ticker, "signal_date": df.index[t], "entry_date": tr.entry_date, "exit_date": tr.exit_date,
               "entry": tr.entry, "exit": tr.exit, "pnl_pct": tr.pnl_pct, "reason": tr.reason,
               "path_dates": list(df.index[e:x]), "path_close": [float(z) for z in df["close"].iloc[e:x]]}
        for w in WINDOWS:
            rec[f"w{w}"] = bool(hits.get(w, False))
        out.append(rec)
    return out


def report(df_all, spy):
    for label, df in (('BASE (EMA+RSI gates ON)', df_all[df_all.gates_ok]), ('H-B (EMA+RSI gates OFF)', df_all)):
        print('\n' + '#' * 8, label, '#' * 8)
        report_one(df, spy)


def report_one(df, spy):
    for per, start in (("IS", R.IS_START), ("OOS", R.OOS_START)):
        sub = df[(df.signal_date >= start) & ((df.signal_date < R.OOS_START) if per == "IS" else True)]
        print(f"\n=== per-trade, {per} ===")
        print(pd.DataFrame([R.row(f"window {w}", sub[sub[f"w{w}"]].pnl_pct) for w in WINDOWS]).to_string(index=False))
    print("\n=== overlap of signals between windows (share of union that is in both) ===")
    for a in range(len(WINDOWS)):
        for b in range(a + 1, len(WINDOWS)):
            wa, wb = f"w{WINDOWS[a]}", f"w{WINDOWS[b]}"
            both = (df[wa] & df[wb]).sum(); union = (df[wa] | df[wb]).sum()
            print(f"  {WINDOWS[a]} vs {WINDOWS[b]}: {both}/{union} = {both / union * 100:.0f}%")
    start = R.OOS_START; days = spy.index[spy.index >= start]; spy_eq = spy.loc[days] / spy.loc[days].iloc[0]
    print(f"\n=== portfolio OOS {days[0].date()} -> {days[-1].date()} (5 seeds) ===")
    for w in WINDOWS:
        t = df[df[f"w{w}"] & (df.entry_date >= start)]
        res = [P4.stats(P4.simulate(t, days, s)[0]) for s in range(5)]
        r = pd.DataFrame(res)
        print(f"  window {w}: signals {len(t)} | total% median {r['total %'].median()} (min {r['total %'].min()}, max {r['total %'].max()}) | maxDD% {r['max DD %'].median()} | Sharpe {r['Sharpe'].median()}")
    print("  SPY buy&hold:", P4.stats(spy_eq))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0); ap.add_argument("--out", default="."); ap.add_argument("--sim-only", action="store_true")
    a = ap.parse_args(); path = os.path.join(a.out, "run006_trades.pkl")
    spy = yf.download("SPY", period="6y", interval="1d", auto_adjust=True, progress=False)["Close"].squeeze()
    spy.index = spy.index.tz_localize(None) if spy.index.tz is not None else spy.index
    spy = spy[spy.index < pd.Timestamp.today().normalize()]
    if a.sim_only:
        report(pd.read_pickle(path), spy); return
    tickers = [t for t in get_universe("sp500") if t != BENCHMARK]
    if a.limit: tickers = tickers[::max(1, len(tickers) // a.limit)][:a.limit]
    bench = bench_context(5.0); bars = fetch_bars(tickers, 5.0)
    today = pd.Timestamp.today().normalize()
    bars = {k: v[v.index < today] for k, v in bars.items()}; bench = bench[bench.index < today]
    trades, t0 = [], time.time()
    with concurrent.futures.ProcessPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(run_ticker, s, d, bench, R.IS_START): s for s, d in bars.items()}
        for n, f in enumerate(concurrent.futures.as_completed(futs), 1):
            try: trades += f.result()
            except Exception as exc: log.warning("%s failed: %s", futs[f], exc)
            if n % 20 == 0:
                el = time.time() - t0
                log.info("%d/%d | %d signals | %.0fs | ~%.0fs left", n, len(futs), len(trades), el, el / n * (len(futs) - n))
    df = pd.DataFrame(trades); os.makedirs(a.out, exist_ok=True); df.to_pickle(path)
    report(df, spy)


if __name__ == "__main__":
    main()
