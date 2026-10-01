"""
Run 007 — S&P 400 generalisation and trading costs (daily, 250-bar window). Pre-registered: research/runs/2026-10-01_sp400-costs.md
Usage: python research/run007.py --universe sp400|sp500 --workers 4 --out DIR   (add --sim-only to re-report saved trades)
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

log = logging.getLogger("run007")
WINDOW = 250
COSTS = {"sp500": 0.0010, "sp400": 0.0015}     # base cost per side
STRESS = 0.0025


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
        try:
            row = LC(df.iloc[max(0, t - WINDOW + 1):t + 1].copy(), features=_LC_FEATURES, filterSettings=_lc_filters()).df.iloc[-1]
        except Exception:
            continue
        if pd.isna(row.get("startLongTrade")) or int(row["prediction"]) < R.MIN_VOTE_NO_IWM:
            continue
        tr = simulate_exit(df, t, R.RULES, None, ticker, 0, "NA")
        if not tr:
            continue
        e = df.index.get_loc(tr.entry_date); x = df.index.get_loc(tr.exit_date)
        out.append({"ticker": ticker, "signal_date": df.index[t], "entry_date": tr.entry_date, "exit_date": tr.exit_date,
                    "entry": tr.entry, "exit": tr.exit, "gates_ok": bool(ema_ok.iloc[t] and rsi_ok.iloc[t]),
                    "path_dates": list(df.index[e:x]), "path_close": [float(z) for z in df["close"].iloc[e:x]]})
    return out


def with_cost(df, c):
    d = df.copy(); d["entry"] = d.entry * (1 + c); d["exit"] = d.exit * (1 - c)
    d["pnl_pct"] = (d.exit / d.entry - 1) * 100
    return d


def pt(d, start, end=None):
    s = d[(d.signal_date >= start) & ((d.signal_date < end) if end is not None else True)]
    return R.row("", s.pnl_pct)


def report(df, universe, spy, ijh):
    base = COSTS[universe]
    for cost, label in ((0.0, "GROSS (no cost)"), (base, f"BASE cost {base*100:.2f}%/side"), (STRESS, f"STRESS cost {STRESS*100:.2f}%/side")):
        d_all = with_cost(df, cost)
        print(f"\n########## {universe.upper()} | {label} ##########")
        rows = []
        for name, m in (("BASE (EMA+RSI on)", d_all.gates_ok), ("H-B (EMA+RSI off)", d_all.gates_ok | True)):
            d = d_all[m]
            for per, (s, e) in (("IS", (R.IS_START, R.OOS_START)), ("OOS", (R.OOS_START, None))):
                rows.append({"variant": name, "period": per, **{k: v for k, v in pt(d, s, e).items() if k}})
        print(pd.DataFrame(rows).to_string(index=False))
        for pl, start in (("OOS", R.OOS_START), ("FULL", R.IS_START)):
            days = spy.index[spy.index >= start]; res = {}
            for name, m in (("BASE", d_all.gates_ok), ("H-B", d_all.gates_ok | True)):
                t = d_all[m & (d_all.entry_date >= start)]
                r = pd.DataFrame([P4.stats(P4.simulate(t, days, s)[0]) for s in range(5)])
                res[name] = (len(t), r["total %"].median(), r["total %"].min(), r["total %"].max(), r["CAGR %"].median() if r["CAGR %"].notna().all() else None,
                             r["max DD %"].median(), r["Sharpe"].median())
            print(f"portfolio {pl} {days[0].date()}->{days[-1].date()} (signals | total% med [min..max] | CAGR% | maxDD% | Sharpe):")
            for k, v in res.items():
                print(f"   {k:5s} {v[0]:5d} | {v[1]:6.1f} [{v[2]:.1f}..{v[3]:.1f}] | {v[4]} | {v[5]} | {v[6]}")
            print("   SPY :", P4.stats(spy.loc[days] / spy.loc[days].iloc[0]))
            if universe == "sp400":
                print("   IJH :", P4.stats(ijh.loc[days] / ijh.loc[days].iloc[0]))


def px(sym):
    s = yf.download(sym, period="6y", interval="1d", auto_adjust=True, progress=False)["Close"].squeeze()
    s.index = s.index.tz_localize(None) if s.index.tz is not None else s.index
    return s[s.index < pd.Timestamp.today().normalize()]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--universe", choices=["sp400", "sp500"], required=True)
    ap.add_argument("--workers", type=int, default=4); ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="."); ap.add_argument("--sim-only", action="store_true")
    a = ap.parse_args(); path = os.path.join(a.out, f"run007_{a.universe}_trades.pkl")
    spy, ijh = px("SPY"), px("IJH")
    if a.sim_only:
        report(pd.read_pickle(path), a.universe, spy, ijh); return
    tickers = [t for t in get_universe(a.universe) if t != BENCHMARK]
    if a.limit: tickers = tickers[::max(1, len(tickers) // a.limit)][:a.limit]
    bench = bench_context(5.0); bars = fetch_bars(tickers, 5.0)
    today = pd.Timestamp.today().normalize()
    bars = {k: v[v.index < today] for k, v in bars.items()}; bench = bench[bench.index < today]
    log.info("run007 %s | %d tickers", a.universe, len(bars))
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
    report(df, a.universe, spy, ijh)


if __name__ == "__main__":
    main()
