"""
Run 002 — volume spike + pullback + Lorentzian (no IWM). Pre-registered in
research/runs/2026-09-30_volume-spike-pullback.md. One walk-forward pass; rows are tagged so the
H-C / H-D subsets and their reference sets come from identical data.
Usage: python research/run002.py --workers 4 --out DIR
"""
import argparse, concurrent.futures, logging, os, sys, time
import numpy as np, pandas as pd
from advanced_ta import LorentzianClassification

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run001 as R
from backtest import (simulate_exit, fetch_bars, bench_context, get_universe, _weekly_vwap, MIN_PRICE,
                      MIN_DOLLAR_VOLUME, VOLUME_MIN_RATIO, MIN_ENTRY_MOMENTUM, _LC_FEATURES, _lc_filters, BENCHMARK)

log = logging.getLogger("run002")
SPIKE_MULT, PULLBACK, LOOKBACK = 3.0, 0.95, 20


def spike_pullback(df):
    v, c = df["volume"], df["close"]
    spike = v >= SPIKE_MULT * v.rolling(20).mean().shift(1)
    hit = pd.Series(False, index=df.index)
    for k in range(1, LOOKBACK + 1):
        hit |= spike.shift(k, fill_value=False) & (c <= PULLBACK * c.shift(k))
    return hit


def run_ticker(ticker, df, bench, start_ts):
    vwap = _weekly_vwap(df)
    avg20 = df["volume"].rolling(20).mean().shift(1)
    ema50 = df["close"].ewm(span=50, adjust=False).mean()
    ret1 = df["close"].pct_change()
    ctx = bench.reindex(df.index)
    d = df["close"].diff()
    g = d.clip(lower=0).ewm(com=13, adjust=False).mean()
    ls = (-d.clip(upper=0)).ewm(com=13, adjust=False).mean()
    rsi = 100 - 100 / (1 + g / ls.replace(0, np.nan))
    c, v = df["close"], df["volume"]
    ema_ok = ema50.isna() | (c >= ema50)
    rsi_ok = rsi.isna() | ((rsi >= 40) & (rsi <= 70))
    sp = spike_pullback(df)
    ok = ((df.index >= start_ts) & ctx["min_vote"].notna() & (c >= MIN_PRICE) & (c * v >= MIN_DOLLAR_VOLUME)
          & (avg20.isna() | (avg20 <= 0) | (v >= VOLUME_MIN_RATIO * avg20))
          & ret1.notna() & ctx["bench_ret"].notna() & (ret1 >= MIN_ENTRY_MOMENTUM) & vwap.notna() & (c > vwap))
    out = []
    for t in [int(i) for i in np.flatnonzero(ok.to_numpy()) if R.LC_MIN_BARS <= i < len(df) - 1]:
        window = df.iloc[max(0, t - R.LC_WINDOW + 1):t + 1]
        try:
            row = LorentzianClassification(window.copy(), features=_LC_FEATURES, filterSettings=_lc_filters()).df.iloc[-1]
        except Exception:
            continue
        if pd.isna(row.get("startLongTrade")):
            continue
        vote = int(row["prediction"])
        if vote < R.MIN_VOTE_NO_IWM:
            continue
        tr = simulate_exit(df, t, R.RULES, None, ticker, vote, "NA")
        if tr:
            out.append({"ticker": ticker, "signal_date": df.index[t], "pnl_pct": tr.pnl_pct, "reason": tr.reason,
                        "vote": vote, "live_gates": bool(ema_ok.iloc[t] and rsi_ok.iloc[t]), "spike": bool(sp.iloc[t])})
    return out


def report(df):
    sets = [("H-C ref: live gates, no spike", df.live_gates & ~df.spike),
            ("H-C: live gates + spike/pullback", df.live_gates & df.spike),
            ("H-D ref: relaxed gates, no spike", ~df.spike),
            ("H-D: relaxed gates + spike/pullback", df.spike),
            ("(newly unlocked: spike, fails EMA/RSI)", df.spike & ~df.live_gates)]
    for per in ("IS", "OOS"):
        sub = df[df.period == per]
        print(f"\n=== {per} ===")
        print(pd.DataFrame([R.row(lbl, sub[m[sub.index]].pnl_pct) for lbl, m in [(l, m) for l, m in sets]]).to_string(index=False))
    print("\n--- H-D (spike) by segment (IS | OOS) ---")
    rows = []
    for sg in [">200B", "50-200B", "10-50B", "<10B"]:
        for per in ("IS", "OOS"):
            s = df[df.spike & (df.segment == sg) & (df.period == per)]
            rows.append(R.row(f"{sg} {per}", s.pnl_pct))
    print(pd.DataFrame(rows).to_string(index=False))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0); ap.add_argument("--out", default=".")
    a = ap.parse_args()
    tickers = [t for t in get_universe("sp500") if t != BENCHMARK]
    if a.limit: tickers = tickers[::max(1, len(tickers) // a.limit)][:a.limit]
    bench = bench_context(5.0); bars = fetch_bars(tickers, 5.0)
    today = pd.Timestamp.today().normalize()
    bars = {k: v[v.index < today] for k, v in bars.items()}; bench = bench[bench.index < today]
    log.info("run002 | %d tickers", len(bars))
    trades, t0 = [], time.time()
    with concurrent.futures.ProcessPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(run_ticker, s, d, bench, R.IS_START): s for s, d in bars.items()}
        for n, f in enumerate(concurrent.futures.as_completed(futs), 1):
            try: trades += f.result()
            except Exception as exc: log.warning("%s failed: %s", futs[f], exc)
            if n % 20 == 0:
                el = time.time() - t0
                log.info("%d/%d | %d signals | %.0fs | ~%.0fs left", n, len(futs), len(trades), el, el / n * (len(futs) - n))
    df = pd.DataFrame(trades)
    caps = R.market_caps(sorted(df.ticker.unique()))
    df["segment"] = df.ticker.map(caps).map(R.seg)
    df["period"] = np.where(df.signal_date >= R.OOS_START, "OOS", "IS")
    os.makedirs(a.out, exist_ok=True); df.to_csv(os.path.join(a.out, "run002_trades.csv"), index=False)
    report(df)


if __name__ == "__main__":
    main()
