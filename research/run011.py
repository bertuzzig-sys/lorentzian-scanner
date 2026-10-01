"""
Run 011 — quiet accumulation, then explosion. Pre-registered: research/runs/2026-10-01_quiet-accumulation.md
Needs the AI Edge Lorentzian port on the path (AIEDGE_PORT, see run010.py). Usage: python research/run011.py --workers 4 --out DIR [--limit N]
"""
import argparse, concurrent.futures, logging, os, sys, time, zlib
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run001 as R
import run010 as T
from backtest import simulate_exit, fetch_bars, get_universe

log = logging.getLogger("run011")


def state_series(df):
    c, v = df["close"], df["volume"]
    v10 = v.rolling(10).mean(); v60 = v.shift(10).rolling(60).mean()
    r20 = c / c.shift(20) - 1
    rng = (c.rolling(20).max() - c.rolling(20).min()) / c.rolling(20).mean()
    return ((v10 >= 1.5 * v60) & (r20 >= 0.0) & (r20 <= 0.10) & (rng <= 0.15)).fillna(False).to_numpy()


def run_ticker(ticker, df, start_ts):
    if len(df) < 300:
        return []
    state = state_series(df); c, v = df["close"], df["volume"]
    liq = ((c >= 5) & (c * v >= 5e6)).to_numpy(); idx = df.index; n = len(df)
    ok = liq & (idx >= start_ts); ok[max(0, n - 22):] = False
    rng = np.random.default_rng(zlib.crc32(ticker.encode()))
    sample = ok & (rng.random(n) < 0.05)
    want = (state & ok) | sample
    if not want.any():
        return []
    buys = T.lorentz_buys(df) if (state & ok).any() else np.zeros(n, bool)
    cv = c.to_numpy(); out = []
    for t in np.flatnonzero(want):
        tr = simulate_exit(df, int(t), T.PRIMARY, None, ticker, 0, "NA")
        if not tr:
            continue
        mfe = float(cv[t + 1:t + 21].max() / tr.entry - 1) if t + 21 <= n else np.nan
        out.append({"ticker": ticker, "signal_date": idx[t], "state": bool(state[t] and ok[t]), "trigger": bool(state[t] and ok[t] and buys[t]),
                    "sample": bool(sample[t]), "entry": tr.entry, "exit": tr.exit, "mfe20": mfe})
    return out


def pnl(d, cost):
    return (d.exit * (1 - cost) / (d.entry * (1 + cost)) - 1) * 100


def report(df):
    for cost, cl in ((0.0, "gross"), (T.COST, f"net {T.COST*100:.2f}%/side")):
        d = df.copy(); d["pnl"] = pnl(d, cost); rows = []
        groups = (("TRIGGER (state + Lorentzian long)", d.trigger), ("NULL-A (state, no trigger)", d.state & ~d.trigger), ("NULL-B (random 5% of all liquid days)", d["sample"]))
        for who, m in groups:
            for per, (s_, e_) in (("IS", (R.IS_START, R.OOS_START)), ("OOS", (R.OOS_START, None))):
                sub = d[m & (d.signal_date >= s_) & ((d.signal_date < e_) if e_ is not None else True)]
                r = T.stat_row(f"{who} {per}", sub.pnl)
                if len(sub):
                    srt = sub.pnl.sort_values(ascending=False); top = srt.head(max(1, int(len(srt) * 0.05))).clip(lower=0).sum(); tot = srt.clip(lower=0).sum()
                    r.update({"explode%(>=+20% in 20d)": round((sub.mfe20 >= 0.20).mean() * 100, 1), "lose>=10%": round((sub.pnl <= -10).mean() * 100, 1),
                              "top5% share of gains": round(top / tot * 100) if tot > 0 else None})
                rows.append(r)
        print(f"\n-- {cl} --"); print(pd.DataFrame(rows).to_string(index=False))


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
    df = pd.DataFrame(rows); os.makedirs(a.out, exist_ok=True); df.to_pickle(os.path.join(a.out, "run011_trades.pkl"))
    print(f"rows {len(df)} | state {int(df.state.sum())} | trigger {int(df.trigger.sum())} | sample {int(df['sample'].sum())}")
    report(df)


if __name__ == "__main__":
    main()
