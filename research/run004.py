"""
Run 004 — portfolio backtest of the v11.3 configuration (daily):
  Lorentzian long flip (ADX filter on, vote >= 6) + live gates (price, dollar volume, volume ratio, +0.5% day,
  above 50-EMA, RSI 40-70) with NO IWM and NO VWAP gate. 8% stop, 10-day hold, entry next open.
Portfolio rules (assumptions, fixed before looking): equal-weight 5% of current equity per position, max 20 open,
one position per ticker, same-day conflicts resolved at random (5 seeds), no sector cap (needs sector data),
cash earns 0, no costs/slippage, daily mark-to-market. Compared with SPY buy-and-hold over the same days.
Usage: python research/run004.py --workers 4 --out DIR        (add --sim-only to re-simulate from saved trades)
"""
import argparse, concurrent.futures, logging, os, sys, time
import numpy as np, pandas as pd, yfinance as yf
from advanced_ta import LorentzianClassification as LC

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run001 as R
from backtest import (simulate_exit, fetch_bars, bench_context, get_universe, MIN_PRICE, MIN_DOLLAR_VOLUME,
                      VOLUME_MIN_RATIO, MIN_ENTRY_MOMENTUM, _LC_FEATURES, _lc_filters, BENCHMARK)

log = logging.getLogger("run004")
MAX_POS, ALLOC = 20, 0.05


def run_ticker(ticker, df, bench, start_ts):
    avg20 = df["volume"].rolling(20).mean().shift(1)
    ema50 = df["close"].ewm(span=50, adjust=False).mean()
    ret1 = df["close"].pct_change()
    ctx = bench.reindex(df.index)                         # only used to align dates with run 001
    d = df["close"].diff()
    g = d.clip(lower=0).ewm(com=13, adjust=False).mean()
    ls = (-d.clip(upper=0)).ewm(com=13, adjust=False).mean()
    rsi = 100 - 100 / (1 + g / ls.replace(0, np.nan))
    c, v = df["close"], df["volume"]
    ok = ((df.index >= start_ts) & ctx["min_vote"].notna() & (c >= MIN_PRICE) & (c * v >= MIN_DOLLAR_VOLUME)
          & (avg20.isna() | (avg20 <= 0) | (v >= VOLUME_MIN_RATIO * avg20))
          & ret1.notna() & ctx["bench_ret"].notna() & (ret1 >= MIN_ENTRY_MOMENTUM)
          & (ema50.isna() | (c >= ema50)) & (rsi.isna() | ((rsi >= 40) & (rsi <= 70))))
    out = []
    for t in [int(i) for i in np.flatnonzero(ok.to_numpy()) if R.LC_MIN_BARS <= i < len(df) - 1]:
        try:
            row = LC(df.iloc[max(0, t - R.LC_WINDOW + 1):t + 1].copy(), features=_LC_FEATURES,
                     filterSettings=_lc_filters()).df.iloc[-1]
        except Exception:
            continue
        if pd.isna(row.get("startLongTrade")) or int(row["prediction"]) < R.MIN_VOTE_NO_IWM:
            continue
        tr = simulate_exit(df, t, R.RULES, None, ticker, 0, "NA")
        if not tr:
            continue
        e = df.index.get_loc(tr.entry_date); x = df.index.get_loc(tr.exit_date)
        out.append({"ticker": ticker, "signal_date": df.index[t], "entry_date": tr.entry_date, "exit_date": tr.exit_date,
                    "entry": tr.entry, "exit": tr.exit, "pnl_pct": tr.pnl_pct, "reason": tr.reason,
                    "path_dates": list(df.index[e:x]), "path_close": [float(z) for z in df["close"].iloc[e:x]]})
    return out


def simulate(trades, days, seed):
    rng = np.random.default_rng(seed)
    cash, open_pos, taken = 1.0, {}, 0
    by_entry = trades.groupby("entry_date")
    eq, npos = [], []
    for day in days:
        # exits first
        for tk in [k for k, p in open_pos.items() if p["exit_date"] == day]:
            p = open_pos.pop(tk); cash += p["shares"] * p["exit"]
        # entries
        if day in by_entry.groups:
            cand = by_entry.get_group(day).sample(frac=1, random_state=int(rng.integers(1e9)))
            for _, r in cand.iterrows():
                if len(open_pos) >= MAX_POS or r.ticker in open_pos:
                    continue
                equity = cash + sum(p["shares"] * p["last"] for p in open_pos.values())
                notional = min(ALLOC * equity, cash)
                if notional <= 0: continue
                open_pos[r.ticker] = {"shares": notional / r.entry, "exit": r.exit, "exit_date": r.exit_date,
                                      "last": r.entry, "path": dict(zip(r.path_dates, r.path_close))}
                cash -= notional; taken += 1
        for p in open_pos.values():                      # mark to market
            if day in p["path"]: p["last"] = p["path"][day]
        eq.append(cash + sum(p["shares"] * p["last"] for p in open_pos.values())); npos.append(len(open_pos))
    return pd.Series(eq, index=days), taken, float(np.mean(npos))


def stats(eq):
    r = eq.pct_change().dropna(); yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    return {"total %": round((eq.iloc[-1] / eq.iloc[0] - 1) * 100, 1),
            "CAGR %": round(((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) * 100, 1) if yrs > 0.2 else None,
            "max DD %": round(((eq / eq.cummax()) - 1).min() * 100, 1),
            "Sharpe": round(r.mean() / r.std() * np.sqrt(252), 2) if r.std() > 0 else None}


def report(trades, spy):
    for label, start in (("OOS (last 12 months)", R.OOS_START), ("FULL (in-sample + OOS)", R.IS_START)):
        t = trades[trades.entry_date >= start]
        days = spy.index[spy.index >= start]
        spy_eq = spy.loc[days] / spy.loc[days].iloc[0]
        print(f"\n=== {label}: {days[0].date()} -> {days[-1].date()} | signals {len(t)} ===")
        rows, taken_l, avgpos_l = [], [], []
        for seed in range(5):
            eq, taken, avgpos = simulate(t, days, seed); rows.append(stats(eq)); taken_l.append(taken); avgpos_l.append(avgpos)
        df = pd.DataFrame(rows)
        print("strategy, 5 random seeds (same-day conflicts):"); print(df.to_string(index=False))
        print(f"trades taken: {min(taken_l)}-{max(taken_l)} of {len(t)} signals | avg open positions {np.mean(avgpos_l):.1f} of {MAX_POS}")
        print("SPY buy&hold:", stats(spy_eq))
    t = trades
    print("\nPer-trade (all signals, no portfolio limits):", R.row("all", t.pnl_pct))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0); ap.add_argument("--out", default="."); ap.add_argument("--sim-only", action="store_true")
    a = ap.parse_args(); path = os.path.join(a.out, "run004_trades.pkl")
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
