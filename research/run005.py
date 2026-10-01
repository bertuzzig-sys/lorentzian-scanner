"""
Run 005 — portfolio-level comparison of BASE (v11.3) vs H-A (ADX filter off) vs H-B (EMA/RSI gates off), daily.
Pre-registered: research/runs/2026-10-01_portfolio-variants.md. Reuses run 004's portfolio simulator.
Usage: python research/run005.py --workers 4 --out DIR   (add --sim-only to re-simulate saved trades)
"""
import argparse, concurrent.futures, logging, os, sys, time
import numpy as np, pandas as pd, yfinance as yf
from advanced_ta import LorentzianClassification as LC

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run001 as R
import run004 as P4
from run003 import filters
from backtest import (simulate_exit, fetch_bars, bench_context, get_universe, MIN_PRICE, MIN_DOLLAR_VOLUME,
                      VOLUME_MIN_RATIO, MIN_ENTRY_MOMENTUM, _LC_FEATURES, BENCHMARK)

log = logging.getLogger("run005")


def run_ticker(ticker, df, bench, start_ts):
    avg20 = df["volume"].rolling(20).mean().shift(1)
    ema50 = df["close"].ewm(span=50, adjust=False).mean()
    ret1 = df["close"].pct_change()
    ctx = bench.reindex(df.index)                       # only to align dates with earlier runs
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
        window = df.iloc[max(0, t - R.LC_WINDOW + 1):t + 1]
        sig = {}
        for name, adx_on in (("adx_on", True), ("adx_off", False)):
            try:
                row = LC(window.copy(), features=_LC_FEATURES, filterSettings=filters(adx_on)).df.iloc[-1]
            except Exception:
                continue
            sig[name] = bool(not pd.isna(row.get("startLongTrade")) and int(row["prediction"]) >= R.MIN_VOTE_NO_IWM)
        if not (sig.get("adx_on") or sig.get("adx_off")):
            continue
        tr = simulate_exit(df, t, R.RULES, None, ticker, 0, "NA")
        if not tr:
            continue
        e = df.index.get_loc(tr.entry_date); x = df.index.get_loc(tr.exit_date)
        out.append({"ticker": ticker, "signal_date": df.index[t], "entry_date": tr.entry_date, "exit_date": tr.exit_date,
                    "entry": tr.entry, "exit": tr.exit, "pnl_pct": tr.pnl_pct, "reason": tr.reason,
                    "adx_on": sig.get("adx_on", False), "adx_off": sig.get("adx_off", False),
                    "gates_ok": bool(ema_ok.iloc[t] and rsi_ok.iloc[t]),
                    "path_dates": list(df.index[e:x]), "path_close": [float(z) for z in df["close"].iloc[e:x]]})
    return out


def variants(df):
    return [("BASE  ADX on , EMA+RSI on ", df.adx_on & df.gates_ok),
            ("H-A   ADX off, EMA+RSI on ", df.adx_off & df.gates_ok),
            ("H-B   ADX on , EMA+RSI off", df.adx_on),
            ("(info) ADX off, EMA+RSI off", df.adx_off)]


def report(df, spy):
    for label, start in (("OOS (last 12 months)", R.OOS_START), ("FULL (in-sample + OOS)", R.IS_START)):
        days = spy.index[spy.index >= start]; spy_eq = spy.loc[days] / spy.loc[days].iloc[0]
        print(f"\n=== {label}: {days[0].date()} -> {days[-1].date()} ===")
        rows = []
        for name, m in variants(df):
            t = df[m & (df.entry_date >= start)]
            res = []
            for seed in range(5):
                eq, taken, avgpos = P4.simulate(t, days, seed); s = P4.stats(eq); s["taken"] = taken; s["avgpos"] = avgpos; res.append(s)
            r = pd.DataFrame(res)
            pt = R.row("", t.pnl_pct)
            rows.append({"variant": name, "signals": len(t), "taken(med)": int(r.taken.median()), "avg slots": round(r.avgpos.median(), 1),
                         "total% med": r["total %"].median(), "total% min": r["total %"].min(), "total% max": r["total %"].max(),
                         "CAGR% med": r["CAGR %"].median() if r["CAGR %"].notna().all() else None, "maxDD% med": r["max DD %"].median(),
                         "Sharpe med": r["Sharpe"].median(), "win%": pt.get("win%"), "PF": pt.get("PF"), "avg%/trade": pt.get("avg%")})
        print(pd.DataFrame(rows).to_string(index=False))
        print("SPY buy&hold:", P4.stats(spy_eq))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0); ap.add_argument("--out", default="."); ap.add_argument("--sim-only", action="store_true")
    a = ap.parse_args(); path = os.path.join(a.out, "run005_trades.pkl")
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
