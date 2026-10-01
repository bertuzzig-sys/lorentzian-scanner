"""
Run 009 — three simple strategies vs SPY buy-and-hold, with costs. Pre-registered: research/runs/2026-10-01_simple-baselines.md
Usage: python research/run009.py [--limit N]
"""
import argparse, logging, os, sys
import numpy as np, pandas as pd, yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run001 as R
import run004 as P4
from backtest import fetch_bars, get_universe

log = logging.getLogger("run009")
C_SPY, C_STK = 0.0002, 0.0010
START, OOS = pd.Timestamp("2022-10-03"), R.OOS_START


def spy_frame():
    d = yf.download("SPY", period="8y", interval="1d", auto_adjust=True, progress=False)
    d.columns = [str(c).lower() for c in d.columns.get_level_values(0)]
    d.index = d.index.tz_localize(None) if d.index.tz is not None else d.index
    return d[d.index < pd.Timestamp.today().normalize()]


def stats_from_returns(ret, start):
    r = ret[ret.index >= start].dropna()
    eq = (1 + r).cumprod(); eq.index = r.index
    return P4.stats(pd.concat([pd.Series([1.0], index=[r.index[0] - pd.Timedelta(days=1)]), eq]))


def s0_spy(spy):
    return spy.open.shift(-1) / spy.open - 1


def s1_trend(spy, cost):
    sig = (spy.close > spy.close.rolling(200).mean()).astype(float)
    pos = sig.shift(1).fillna(0.0)                      # decided at the previous close, held from today's open
    r = pos * (spy.open.shift(-1) / spy.open - 1)
    r = r - cost * pos.diff().abs().fillna(0.0)         # pay when switching
    return r.dropna(), float(pos[pos.index >= START].mean()), int(pos[pos.index >= START].diff().abs().sum())


def panels(bars):
    o = pd.DataFrame({k: v["open"] for k, v in bars.items()}); c = pd.DataFrame({k: v["close"] for k, v in bars.items()})
    vol = pd.DataFrame({k: v["volume"] for k, v in bars.items()})
    return o.sort_index(), c.sort_index(), vol.sort_index()


def s2_momentum(o, c, vol, days, cost):
    idx = c.index
    month_ends = [g.index[-1] for _, g in pd.Series(idx, index=idx).groupby([idx.year, idx.month])]
    oo = o.shift(-1) / o - 1
    ret = pd.Series(0.0, index=idx); prev_w = pd.Series(0.0, index=c.columns); reb = 0
    for m, nxt in zip(month_ends[:-1], month_ends[1:]):
        i = idx.get_loc(m)
        if i < 252 or m < START - pd.Timedelta(days=40):
            continue
        mom = c.iloc[i - 21] / c.iloc[i - 252] - 1
        elig = (c.iloc[i] >= 5) & ((c.iloc[i] * vol.iloc[i]) >= 5e6) & mom.notna()
        top = mom[elig].nlargest(20).index
        w = pd.Series(0.0, index=c.columns); w[top] = 1 / len(top)
        seg = idx[(idx > m) & (idx <= nxt)]
        if len(seg) == 0:
            continue
        ret.loc[seg] = (oo.loc[seg, top].fillna(0.0) * (1 / len(top))).sum(axis=1)
        ret.loc[seg[0]] -= cost * (w - prev_w).abs().sum(); prev_w = w; reb += 1
    return ret[ret.index >= START].iloc[:-1], reb


def rsi2(close):
    d = close.diff(); g = d.clip(lower=0).ewm(alpha=0.5, adjust=False).mean(); l = (-d.clip(upper=0)).ewm(alpha=0.5, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))


def s3_trades(bars):
    rows = []
    for tk, df in bars.items():
        c, o, h, lo, v = df["close"], df["open"], df["high"], df["low"], df["volume"]
        r2 = rsi2(c); sma200 = c.rolling(200).mean()
        sig = (c > sma200) & (r2 < 10) & (c >= 5) & (c * v >= 5e6) & (df.index >= START)
        idx = df.index; n = len(df)
        for t in np.flatnonzero(sig.to_numpy()):
            if t + 1 >= n - 1:
                continue
            e = t + 1; entry = float(o.iloc[e]); stop = entry * 0.92; x = None; px = None
            for d in range(e, min(e + 10, n - 1)):
                if float(o.iloc[d]) <= stop and d > e:
                    x, px = d, float(o.iloc[d]); break          # gapped through the stop at the open
                if float(lo.iloc[d]) <= stop:
                    x, px = d + 1, stop; break                  # stop touched intraday: fill at the stop, booked next day
                if r2.iloc[d] > 70:
                    x, px = d + 1, float(o.iloc[d + 1]); break
            if x is None:
                x = min(e + 10, n - 1); px = float(o.iloc[x])
            x = min(x, n - 1)
            rows.append({"ticker": tk, "signal_date": idx[t], "entry_date": idx[e], "exit_date": idx[x], "entry": entry, "exit": px,
                         "path_dates": list(idx[e:x]), "path_close": [float(z) for z in c.iloc[e:x]]})
    return pd.DataFrame(rows)


def s3_portfolio(tr, days, cost):
    t = tr.copy(); t["entry"] = t.entry * (1 + cost); t["exit"] = t.exit * (1 - cost)
    res = []
    for s in range(5):
        eq, taken, avg = P4.simulate(t, days, s); st = P4.stats(eq); st["taken"] = taken; st["slots"] = round(avg, 1); res.append(st)
    r = pd.DataFrame(res)
    return {"total %": r["total %"].median(), "CAGR %": r["CAGR %"].median() if r["CAGR %"].notna().all() else None,
            "max DD %": r["max DD %"].median(), "Sharpe": r["Sharpe"].median(), "trades": int(r.taken.median()), "slots": r.slots.median(),
            "range": f"{r['total %'].min():.1f}..{r['total %'].max():.1f}"}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int, default=0); a = ap.parse_args()
    spy = spy_frame()
    tickers = [t for t in get_universe("sp500")]
    if a.limit: tickers = tickers[::max(1, len(tickers) // a.limit)][:a.limit]
    bars = fetch_bars(tickers, 5.0); today = pd.Timestamp.today().normalize()
    bars = {k: v[v.index < today] for k, v in bars.items()}
    o, c, vol = panels(bars)
    tr = s3_trades(bars); log.info("S3 trades: %d", len(tr))
    out = {}
    for label, start in (("OOS", OOS), ("FULL", START)):
        days = spy.index[spy.index >= start][:-1]
        print(f"\n===== {label}: {days[0].date()} -> {days[-1].date()} =====")
        rows = [{"strategy": "SPY buy & hold", "cost": "-", **stats_from_returns(s0_spy(spy), start)}]
        for cname, cs, ck in (("gross", 0.0, 0.0), ("net", C_SPY, C_STK)):
            r1, inv, sw = s1_trend(spy, cs)
            rows.append({"strategy": "S1 index trend (SPY>200d)", "cost": cname, **stats_from_returns(r1, start), "invested%": round(inv * 100), "switches": sw})
            r2, reb = s2_momentum(o, c, vol, days, ck)
            rows.append({"strategy": "S2 momentum top-20", "cost": cname, **stats_from_returns(r2, start), "rebalances": reb})
            t = tr[tr.entry_date >= start]
            s3 = s3_portfolio(t, days, ck)
            rows.append({"strategy": "S3 RSI(2) pullback", "cost": cname, **{k: v for k, v in s3.items() if k in ("total %", "CAGR %", "max DD %", "Sharpe")},
                         "trades": s3["trades"], "slots": s3["slots"], "seed range": s3["range"]})
        print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
