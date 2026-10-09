"""
Run 010 — capitulation rebound. Pre-registered: research/runs/2026-10-01_capitulation-rebound.md
Backtest (trigger vs null) + a screen of the current state. Needs the AI Edge Lorentzian port (github.com/artificial-intelligence-edge/lorentzian-classification,
ports/python) on the path: set AIEDGE_PORT=/path/to/ports/python.
Usage: python research/run010.py --workers 4 --out DIR            (add --limit N for a smoke test)
"""
import argparse, concurrent.futures, logging, os, sys, time
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PORT = os.environ.get("AIEDGE_PORT", "/private/tmp/claude-503/-Users-test-quant-lorentzian-scanner/c67b3c46-fbd7-4b39-b616-2bb1bf6c7b93/scratchpad/aiedge/ports/python")
sys.path.insert(0, PORT)
import run001 as R
from backtest import simulate_exit, fetch_bars, get_universe, ExitRules, summarise

log = logging.getLogger("run010")
COST = 0.0015
PRIMARY = ExitRules("rebound_20d_10pct", stop_pct=0.10, max_hold=20)
SECOND = ExitRules("rebound_10d_8pct", stop_pct=0.08, max_hold=10)


def state_series(df):
    c, v = df["close"], df["volume"]
    avg20 = v.rolling(20).mean().shift(1)
    spike = ((v >= 3 * avg20) & (c / c.shift(3) - 1 <= -0.12)).to_numpy()
    n = len(df); state = np.zeros(n, bool); cv = c.to_numpy(); info = {}
    for s in np.flatnonzero(spike):
        if s < 25:
            continue
        pre = cv[max(0, s - 5):s].max(); end = min(n, s + 91)
        seg = cv[s:end]; low = np.minimum.accumulate(seg)
        cond = (low <= 0.78 * pre) & (seg >= 1.10 * low) & (seg <= 0.85 * pre); cond[0] = False
        state[s:end] |= cond
        for k in np.flatnonzero(cond):
            info[s + k] = (s, pre, low[k])
    return state, info


def lorentz_buys(df):
    from lorentzian_classification import LorentzianClassification as AI, Settings
    recs = [{"time": int(ts.value // 10**9), "open": r.open, "high": r.high, "low": r.low, "close": r.close} for ts, r in df.iterrows()]
    out = AI(recs, Settings(f1=("RSI", 9, 1))).to_dataframe()
    buy = out["Buy"].astype(str).str.strip().isin(["1", "1.0", "True", "true"]).to_numpy()
    pred = pd.to_numeric(out["Prediction"], errors="coerce").fillna(0).to_numpy()
    return buy & (pred >= 6)


def run_ticker(ticker, df, start_ts):
    if len(df) < 300:
        return [], None
    state, info = state_series(df)
    if not state.any():
        return [], None
    c, v = df["close"], df["volume"]
    liq = ((c >= 5) & (c * v >= 5e6)).to_numpy()
    idxs = df.index; n = len(df)
    buys = lorentz_buys(df)
    rows = []
    for t in np.flatnonzero(state & liq & (idxs >= start_ts)):
        if t >= n - 1 - 20:
            continue
        for rules, tag in ((PRIMARY, "p"), (SECOND, "s")):
            tr = simulate_exit(df, int(t), rules, None, ticker, 0, "NA")
            if not tr:
                break
            if tag == "p":
                rec = {"ticker": ticker, "signal_date": idxs[t], "trigger": bool(buys[t]), "entry": tr.entry, "exit": tr.exit}
            else:
                rec["entry2"], rec["exit2"] = tr.entry, tr.exit
        else:
            rows.append(rec)
    scr = None
    last3 = [n - 1, n - 2, n - 3]
    for t in last3:
        if state[t] and liq[t] and buys[t]:
            s, pre, low = info[t]
            scr = {"ticker": ticker, "buy_date": idxs[t].date(), "price": round(float(c.iloc[-1]), 2), "pre_crash": round(float(pre), 2),
                   "low": round(float(low), 2), "off_low%": round((float(c.iloc[-1]) / float(low) - 1) * 100), "vs_pre%": round((float(c.iloc[-1]) / float(pre) - 1) * 100),
                   "crash_date": idxs[s].date()}
            break
    watch = None
    if scr is None and state[n - 1] and liq[n - 1]:
        s, pre, low = info[n - 1]
        watch = {"ticker": ticker, "price": round(float(c.iloc[-1]), 2), "pre_crash": round(float(pre), 2), "low": round(float(low), 2),
                 "off_low%": round((float(c.iloc[-1]) / float(low) - 1) * 100), "vs_pre%": round((float(c.iloc[-1]) / float(pre) - 1) * 100), "crash_date": idxs[s].date()}
    return rows, (scr, watch)


def stat_row(label, pnl):
    s = summarise(list(pnl))
    if not s.get("n"):
        return {"": label, "n": 0}
    return {"": label, "n": s["n"], "win%": round(s["win_rate"], 1), "PF": round(s["profit_factor"], 2), "avg%": round(s["expectancy"], 2), "median%": round(float(np.median(list(pnl))), 2)}


def report(df):
    for exit_label, e, x in (("PRIMARY exit 10% stop / 20-day hold", "entry", "exit"), ("(info) exit 8% stop / 10-day hold", "entry2", "exit2")):
        print(f"\n===== {exit_label} =====")
        for cost, cl in ((0.0, "gross"), (COST, f"net {COST*100:.2f}%/side")):
            d = df.copy(); d["pnl"] = (d[x] * (1 - cost) / (d[e] * (1 + cost)) - 1) * 100
            rows = []
            for who, m in (("TRIGGER (Lorentzian long)", d.trigger), ("NULL (state, no trigger)", ~d.trigger)):
                for per, (s_, e_) in (("IS", (R.IS_START, R.OOS_START)), ("OOS", (R.OOS_START, None))):
                    sub = d[m & (d.signal_date >= s_) & ((d.signal_date < e_) if e_ is not None else True)]
                    rows.append({**stat_row(f"{who} {per}", sub.pnl)})
            print(f"-- {cl} --"); print(pd.DataFrame(rows).to_string(index=False))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=4); ap.add_argument("--limit", type=int, default=0); ap.add_argument("--out", default=".")
    a = ap.parse_args()
    tickers = get_universe("sp1500")
    if a.limit: tickers = tickers[::max(1, len(tickers) // a.limit)][:a.limit]
    bars = fetch_bars(tickers, 5.0); today = pd.Timestamp.today().normalize()
    bars = {k: v[v.index < today] for k, v in bars.items()}
    log.info("run010 | %d tickers", len(bars))
    rows, scr, watch, t0 = [], [], [], time.time()
    with concurrent.futures.ProcessPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(run_ticker, s, d, R.IS_START): s for s, d in bars.items()}
        for n, f in enumerate(concurrent.futures.as_completed(futs), 1):
            try:
                r, extra = f.result(); rows += r
                if extra:
                    if extra[0]: scr.append(extra[0])
                    if extra[1]: watch.append(extra[1])
            except Exception as exc:
                log.warning("%s failed: %s", futs[f], exc)
            if n % 100 == 0:
                log.info("%d/%d | %d state-days | %.0fs", n, len(futs), len(rows), time.time() - t0)
    df = pd.DataFrame(rows); os.makedirs(a.out, exist_ok=True); df.to_pickle(os.path.join(a.out, "run010_trades.pkl"))
    print(f"state-days {len(df)} | trigger days {int(df.trigger.sum())}")
    report(df)
    print("\n===== SCREEN: fresh Lorentzian long in the last 3 bars, inside the crash-and-rebound state =====")
    print(pd.DataFrame(scr).sort_values("buy_date", ascending=False).to_string(index=False) if scr else "none")
    print("\n===== WATCHLIST: in the state today, no fresh long signal yet =====")
    print(pd.DataFrame(watch).sort_values("vs_pre%").to_string(index=False) if watch else "none")


if __name__ == "__main__":
    main()
