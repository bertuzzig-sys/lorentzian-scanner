"""
Run 012 — unusual volume + Lorentzian long. Pre-registered: research/runs/2026-10-01_volume-expansion.md
Needs the AI Edge Lorentzian port on the path (AIEDGE_PORT, see run010.py). Usage: python research/run012.py --workers 4 --out DIR [--limit N]
"""
import argparse, concurrent.futures, logging, os, sys, time, zlib
import numpy as np, pandas as pd, yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run001 as R
import run004 as P4
import run010 as T
import run011 as Q
from backtest import simulate_exit, fetch_bars, get_universe

log = logging.getLogger("run012")


def ve_series(df):
    v = df["volume"]
    v10 = v.rolling(10).mean(); v60 = v.shift(10).rolling(60).mean()
    spike = (v >= 3 * v.rolling(20).mean().shift(1)).astype(float).rolling(10).max() > 0
    return (((v10 >= 1.5 * v60) | spike)).fillna(False).to_numpy()


def run_ticker(ticker, df, start_ts):
    if len(df) < 300:
        return []
    c, v = df["close"], df["volume"]; idx = df.index; n = len(df)
    liq = ((c >= 5) & (c * v >= 5e6)).to_numpy(); ok = liq & (idx >= start_ts); ok[max(0, n - 22):] = False
    ve = ve_series(df); crash_state, _ = T.state_series(df); quiet = Q.state_series(df)
    rng = np.random.default_rng(zlib.crc32(ticker.encode())); samp = rng.random(n) < 0.05
    buys = T.lorentz_buys(df)
    cand = (buys & ok) | (ok & samp)
    if not cand.any():
        return []
    out = []
    for t in np.flatnonzero(cand):
        tr = simulate_exit(df, int(t), T.PRIMARY, None, ticker, 0, "NA")
        if not tr:
            continue
        e = idx.get_loc(tr.entry_date); x = idx.get_loc(tr.exit_date)
        sig = bool(buys[t] and ok[t])
        grp = []
        if sig and ve[t]: grp.append("SIG+VE")
        if sig and not ve[t]: grp.append("SIG-only")
        if (not sig) and ve[t] and samp[t]: grp.append("VE-only")
        if samp[t]: grp.append("ALL")
        if not grp:
            continue
        out.append({"ticker": ticker, "signal_date": idx[t], "entry_date": tr.entry_date, "exit_date": tr.exit_date, "entry": tr.entry, "exit": tr.exit,
                    "groups": ",".join(grp), "sub": ("crash" if crash_state[t] else "quiet" if quiet[t] else "other") if sig and ve[t] else "",
                    "path_dates": list(idx[e:x]) if sig else [], "path_close": [float(z) for z in c.iloc[e:x]] if sig else []})
    return out


def has(d, g):
    return d.groups.str.split(",").apply(lambda L: g in L)


def per_trade(df):
    for cost, cl in ((0.0, "gross"), (T.COST, f"net {T.COST*100:.2f}%/side")):
        d = df.copy(); d["pnl"] = (d.exit * (1 - cost) / (d.entry * (1 + cost)) - 1) * 100; rows = []
        for g in ("SIG+VE", "SIG-only", "VE-only", "ALL"):
            for per, (s_, e_) in (("IS", (R.IS_START, R.OOS_START)), ("OOS", (R.OOS_START, None))):
                sub = d[has(d, g) & (d.signal_date >= s_) & ((d.signal_date < e_) if e_ is not None else True)]
                rows.append(T.stat_row(f"{g} {per}", sub.pnl))
        print(f"\n-- per trade, {cl} --"); print(pd.DataFrame(rows).to_string(index=False))
    d = df.copy(); d["pnl"] = (d.exit * (1 - T.COST) / (d.entry * (1 + T.COST)) - 1) * 100
    rows = []
    for sb in ("crash", "quiet", "other"):
        for per, (s_, e_) in (("IS", (R.IS_START, R.OOS_START)), ("OOS", (R.OOS_START, None))):
            sub = d[has(d, "SIG+VE") & (d["sub"] == sb) & (d.signal_date >= s_) & ((d.signal_date < e_) if e_ is not None else True)]
            rows.append(T.stat_row(f"SIG+VE / {sb} {per}", sub.pnl))
    print("\n-- info: SIG+VE split (net) --"); print(pd.DataFrame(rows).to_string(index=False))


def portfolio(df):
    spy = yf.download("SPY", period="6y", interval="1d", auto_adjust=True, progress=False)
    spy.columns = [str(c).lower() for c in spy.columns.get_level_values(0)]
    spy.index = spy.index.tz_localize(None) if spy.index.tz is not None else spy.index
    spy = spy[spy.index < pd.Timestamp.today().normalize()]
    for lab, g in (("SIG+VE", "SIG+VE"), ("all Lorentzian signals", None)):
        d = df[has(df, "SIG+VE") | has(df, "SIG-only")] if g is None else df[has(df, g)]
        d = d.copy(); d["entry"] *= 1 + T.COST; d["exit"] *= 1 - T.COST
        for pl, start in (("OOS", R.OOS_START), ("FULL", R.IS_START)):
            days = spy.index[spy.index >= start][:-1]; t = d[d.entry_date >= start]
            res = pd.DataFrame([P4.stats(P4.simulate(t, days, s)[0]) for s in range(5)])
            ref = spy.open.shift(-1) / spy.open - 1; r = ref[ref.index >= start].dropna(); eq = (1 + r).cumprod()
            print(f"portfolio {lab:24s} {pl}: signals {len(t):5d} | total% med {res['total %'].median():6.1f} [{res['total %'].min():.1f}..{res['total %'].max():.1f}] | maxDD {res['max DD %'].median()} | Sharpe {res['Sharpe'].median()} || SPY total% {(eq.iloc[-1]-1)*100:.1f}, Sharpe {P4.stats(pd.concat([pd.Series([1.0], index=[r.index[0]-pd.Timedelta(days=1)]), eq]))['Sharpe']}")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=4); ap.add_argument("--limit", type=int, default=0); ap.add_argument("--out", default=".")
    a = ap.parse_args()
    tickers = get_universe("sp1500")
    if a.limit: tickers = tickers[::max(1, len(tickers) // a.limit)][:a.limit]
    bars = fetch_bars(tickers, 5.0); today = pd.Timestamp.today().normalize(); bars = {k: v[v.index < today] for k, v in bars.items()}
    rows, t0 = [], time.time()
    with concurrent.futures.ProcessPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(run_ticker, s, d, R.IS_START): s for s, d in bars.items()}
        for n, f in enumerate(concurrent.futures.as_completed(futs), 1):
            try: rows += f.result()
            except Exception as exc: log.warning("%s failed: %s", futs[f], exc)
            if n % 100 == 0: log.info("%d/%d | %d rows | %.0fs", n, len(futs), len(rows), time.time() - t0)
    df = pd.DataFrame(rows); os.makedirs(a.out, exist_ok=True); df.to_pickle(os.path.join(a.out, "run012_trades.pkl"))
    print(f"rows {len(df)} | " + " | ".join(f"{g} {int(has(df, g).sum())}" for g in ("SIG+VE", "SIG-only", "VE-only", "ALL")))
    per_trade(df); portfolio(df)


if __name__ == "__main__":
    main()
