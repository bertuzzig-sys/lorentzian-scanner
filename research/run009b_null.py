"""
Run 009 addendum (post hoc, flagged as such): null control for S2 momentum. Same monthly rebalance, same eligibility and costs, but the 20 names are chosen
AT RANDOM (5 seeds), plus an equal-weight portfolio of ALL eligible names. If random picks from today's S&P 500 list already earn most of S2's return,
the S2 result is survivorship bias (stocks in today's list are there because they rose), not momentum.
Usage: python research/run009b_null.py
"""
import os, sys, logging
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run009 as N
from backtest import fetch_bars, get_universe


def monthly(o, c, vol, cost, mode, seed=0, n=20):
    rng = np.random.default_rng(seed); idx = c.index
    month_ends = [g.index[-1] for _, g in pd.Series(idx, index=idx).groupby([idx.year, idx.month])]
    oo = o.shift(-1) / o - 1
    ret = pd.Series(0.0, index=idx); prev_w = pd.Series(0.0, index=c.columns)
    for m, nxt in zip(month_ends[:-1], month_ends[1:]):
        i = idx.get_loc(m)
        if i < 252 or m < N.START - pd.Timedelta(days=40):
            continue
        mom = c.iloc[i - 21] / c.iloc[i - 252] - 1
        elig = ((c.iloc[i] >= 5) & ((c.iloc[i] * vol.iloc[i]) >= 5e6) & mom.notna())
        names = mom[elig].index
        if mode == "random":
            top = list(rng.choice(names, size=min(n, len(names)), replace=False))
        elif mode == "all":
            top = list(names)
        else:
            top = list(mom[elig].nlargest(n).index)
        w = pd.Series(0.0, index=c.columns); w[top] = 1 / len(top)
        seg = idx[(idx > m) & (idx <= nxt)]
        if len(seg) == 0:
            continue
        ret.loc[seg] = (oo.loc[seg, top].fillna(0.0) * (1 / len(top))).sum(axis=1)
        ret.loc[seg[0]] -= cost * (w - prev_w).abs().sum(); prev_w = w
    return ret[ret.index >= N.START].iloc[:-1]


def main():
    spy = N.spy_frame()
    bars = fetch_bars(get_universe("sp500"), 5.0); today = pd.Timestamp.today().normalize()
    bars = {k: v[v.index < today] for k, v in bars.items()}
    o, c, vol = N.panels(bars)
    rows = []
    for label, start in (("OOS", N.OOS), ("FULL", N.START)):
        rows.append({"period": label, "strategy": "SPY buy & hold", **N.stats_from_returns(N.s0_spy(spy), start)})
        rows.append({"period": label, "strategy": "S2 momentum top-20 (net)", **N.stats_from_returns(monthly(o, c, vol, N.C_STK, "mom"), start)})
        rows.append({"period": label, "strategy": "ALL eligible equal-weight, monthly (net)", **N.stats_from_returns(monthly(o, c, vol, N.C_STK, "all"), start)})
        res = pd.DataFrame([N.stats_from_returns(monthly(o, c, vol, N.C_STK, "random", seed=s), start) for s in range(5)])
        rows.append({"period": label, "strategy": "RANDOM 20, monthly (net, median of 5)", "total %": res["total %"].median(),
                     "CAGR %": res["CAGR %"].median(), "max DD %": res["max DD %"].median(), "Sharpe": res["Sharpe"].median()})
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
