"""
Run 013 — bear-market stress test, 2005-2026. Pre-registered: research/runs/2026-10-01_bear-markets.md
Usage: python research/run013.py --workers 4 --out DIR [--limit N]      (add --sim-only to re-report saved trades)
"""
import argparse, concurrent.futures, logging, os, sys, time
import numpy as np, pandas as pd, yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run001 as R
import run004 as P4
import run007 as S7
from backtest import get_universe

log = logging.getLogger("run013")
START = pd.Timestamp("2005-01-03"); COST = 0.0010
WINDOWS = {"2008 crash": ("2007-10-09", "2009-03-09"), "2020 crash": ("2020-02-19", "2020-03-23"), "2022 bear": ("2022-01-03", "2022-10-12")}


def fetch_long(tickers):
    out = {}
    for i in range(0, len(tickers), 50):
        chunk = tickers[i:i + 50]
        try:
            raw = yf.download(chunk, start="2003-06-01", interval="1d", group_by="ticker", auto_adjust=True, progress=False, threads=False)
        except Exception as exc:
            log.warning("download error: %s", exc); continue
        if raw is None or raw.empty:
            continue
        for sym in chunk:
            try:
                d = raw[sym].copy() if len(chunk) > 1 else raw.copy()
                if isinstance(d.columns, pd.MultiIndex): d.columns = d.columns.get_level_values(-1)
                d.columns = [str(c).lower() for c in d.columns]
                if isinstance(d.index, pd.DatetimeIndex) and d.index.tz is not None: d.index = d.index.tz_localize(None)
                d = d.dropna(subset=["close"])
                if len(d) >= 400: out[sym] = d
            except (KeyError, AttributeError):
                pass
    log.info("fetched %d / %d tickers", len(out), len(tickers)); return out


def spy_bars():
    d = yf.download("SPY", start="2003-06-01", interval="1d", auto_adjust=True, progress=False)
    d.columns = [str(c).lower() for c in d.columns.get_level_values(0)]
    d.index = d.index.tz_localize(None) if d.index.tz is not None else d.index
    return d[d.index < pd.Timestamp.today().normalize()]


def per_trade(d):
    r = R.row("", d.pnl_pct); r.pop("", None); return r


def report(df, spy):
    for name, mask in (("BASE (EMA+RSI on)", df.gates_ok), ("H-B (EMA+RSI off)", df.gates_ok | True)):
        d = S7.with_cost(df[mask], COST)
        d["year"] = d.signal_date.dt.year
        print(f"\n########## {name}: per-trade, net {COST*100:.2f}%/side ##########")
        rows = [{"year": y, **per_trade(g)} for y, g in d.groupby("year")] + [{"year": "ALL", **per_trade(d)}]
        print(pd.DataFrame(rows).to_string(index=False))
        days = spy.index[spy.index >= START][:-1]
        eqs, takens = [], []
        for s in range(3):
            eq, taken, _ = P4.simulate(d, days, s); eqs.append(eq); takens.append(taken)
        eq = pd.concat(eqs, axis=1).median(axis=1)
        spy_eq = (spy.close.loc[days[0]:days[-1]] / spy.close.loc[days[0]])
        yr = pd.DataFrame({"strategy %": (eq.resample("YE").last() / eq.resample("YE").last().shift(1).fillna(1.0) - 1) * 100,
                           "SPY %": (spy_eq.resample("YE").last() / spy_eq.resample("YE").last().shift(1).fillna(1.0) - 1) * 100}).round(1)
        yr.index = yr.index.year; print(f"\n-- calendar-year returns (median of 3 seeds; trades taken {min(takens)}-{max(takens)}) --"); print(yr.T.to_string())
        print("\n-- bear windows (return % | max drawdown %) strategy vs SPY --")
        for w, (a, b) in WINDOWS.items():
            e = eq.loc[a:b]; s_ = spy_eq.loc[a:b]
            se = e / e.iloc[0]; ss = s_ / s_.iloc[0]
            ret_s, ret_b = (se.iloc[-1] - 1) * 100, (ss.iloc[-1] - 1) * 100
            dd_s, dd_b = ((se / se.cummax()) - 1).min() * 100, ((ss / ss.cummax()) - 1).min() * 100
            ok = ret_s > ret_b and dd_s > dd_b
            print(f"  {w:11s} strategy {ret_s:6.1f} | {dd_s:6.1f}    SPY {ret_b:6.1f} | {dd_b:6.1f}    -> {'SURVIVES' if ok else 'does not survive'}")
        print(f"  whole period: strategy {(eq.iloc[-1]/eq.iloc[0]-1)*100:.0f}% (maxDD {((eq/eq.cummax())-1).min()*100:.1f}%) vs SPY {(spy_eq.iloc[-1]-1)*100:.0f}% (maxDD {((spy_eq/spy_eq.cummax())-1).min()*100:.1f}%)")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=4); ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="."); ap.add_argument("--sim-only", action="store_true")
    a = ap.parse_args(); path = os.path.join(a.out, "run013_trades.pkl"); spy = spy_bars()
    if a.sim_only:
        report(pd.read_pickle(path), spy); return
    tickers = sorted(get_universe("sp500"))[::2]
    if a.limit: tickers = tickers[::max(1, len(tickers) // a.limit)][:a.limit]
    bars = fetch_long(tickers); today = pd.Timestamp.today().normalize(); bars = {k: v[v.index < today] for k, v in bars.items()}
    bench = pd.DataFrame({"bench_ret": spy.close.pct_change(), "min_vote": 6.0}, index=spy.index)
    rows, t0 = [], time.time()
    with concurrent.futures.ProcessPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(S7.run_ticker, s, d, bench, START): s for s, d in bars.items()}
        for n, f in enumerate(concurrent.futures.as_completed(futs), 1):
            try: rows += f.result()
            except Exception as exc: log.warning("%s failed: %s", futs[f], exc)
            if n % 10 == 0:
                el = time.time() - t0; log.info("%d/%d | %d signals | %.0fs | ~%.0fs left", n, len(futs), len(rows), el, el / n * (len(futs) - n))
    df = pd.DataFrame(rows); os.makedirs(a.out, exist_ok=True); df.to_pickle(path); report(df, spy)


if __name__ == "__main__":
    main()
