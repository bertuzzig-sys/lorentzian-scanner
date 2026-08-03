"""
Lorentzian Scanner — Backtest Engine v2.0
=========================================
Why this exists: the live system produces ~0.14 signals/day. Reaching the
30-trade bar takes ~10 months; detecting a marginal edge (45% vs a 35% bar)
takes ~145 trades ≈ 4 years. Forward-testing cannot answer the question.
A backtest over a few hundred tickers x 3 years produces the same evidence
in an hour.

THE HEADLINE QUESTION IS THE PAYOFF RATIO, NOT THE WIN RATE.
Live results: avg win +4.20%, avg loss -5.08% => payoff 0.83 => you need a
54.7% win rate just to break even. A hard -4% stop lets every loser run to
the full stop while a 5-day time exit truncates winners. That asymmetry is
structural, and no entry signal fixes it. So this engine holds the ENTRY
constant and compares EXIT RULES over identical signals — the only way to
isolate where the money is actually lost.

BIAS WARNING (deliberate, and useful):
advanced_ta normalises the CCI and WT features with MinMaxScaler over the
whole series, so historical feature values are contaminated by future
extremes. Running LC once over full history is therefore OPTIMISTICALLY
BIASED. That makes this a KILL TEST: if the strategy loses money with the
bias in its favour, it is dead and no walk-forward is needed. Only if it
survives is the (far more expensive) per-bar walk-forward worth building.

Usage:
  python backtest.py --universe sp500 --years 3
  python backtest.py --tickers AAPL NVDA GH BURL --years 2
  python backtest.py --universe sp500 --years 3 --telegram   # report to Telegram
"""

import argparse
import concurrent.futures
import logging
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd
import yfinance as yf
from advanced_ta import LorentzianClassification

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("backtest")

# ── Parameters mirroring scanner_b.py v10.2 ──────────────────────────────────
MIN_PRICE          = 5.0
BULL_MIN_VOTE      = 6
BEAR_MIN_VOTE      = 8
BENCH_EMA_PERIOD   = 21
BENCHMARK          = "IWM"      # v10.0: universe is mid/small cap, not SPY
VOLUME_MIN_RATIO   = 0.80
MIN_ENTRY_MOMENTUM = 0.005
MIN_DOLLAR_VOLUME  = 5_000_000

_LC_FEATURES = [
    LorentzianClassification.Feature("RSI", 14, 1),
    LorentzianClassification.Feature("WT",  10, 11),
    LorentzianClassification.Feature("CCI", 20, 1),
    LorentzianClassification.Feature("ADX", 20, 2),
    LorentzianClassification.Feature("RSI",  9, 1),
]

def _lc_filters():
    return LorentzianClassification.FilterSettings(
        useVolatilityFilter=True, useRegimeFilter=True,
        useAdxFilter=True, regimeThreshold=0.0, adxThreshold=20,
        kernelFilter=LorentzianClassification.KernelFilter(useKernelSmoothing=False),
    )


# ── Exit rule variants ───────────────────────────────────────────────────────

@dataclass
class ExitRules:
    name: str
    stop_pct: float = 0.04
    max_hold: int = 5
    use_signal_flip: bool = True
    partial_at_r: float = 0.0        # take partial at N x initial risk
    partial_frac: float = 0.0        # fraction sold there
    breakeven_after_partial: bool = False
    trail_sma: int = 0               # exit on close below this SMA (0 = off)


PRESETS = [
    ExitRules("current(live)",     stop_pct=0.04, max_hold=5),
    ExitRules("hold_10",           stop_pct=0.04, max_hold=10),
    ExitRules("wide_stop_8pct",    stop_pct=0.08, max_hold=10),
    ExitRules("partial_2R_be",     stop_pct=0.04, max_hold=10,
                                   partial_at_r=2.0, partial_frac=0.5,
                                   breakeven_after_partial=True),
    ExitRules("partial_2R_trail10", stop_pct=0.04, max_hold=30,
                                   partial_at_r=2.0, partial_frac=0.5,
                                   breakeven_after_partial=True, trail_sma=10),
    ExitRules("trail10_only",      stop_pct=0.04, max_hold=30,
                                   use_signal_flip=False, trail_sma=10),
]


@dataclass
class Trade:
    ticker: str
    rule: str
    entry_date: object
    entry: float
    exit_date: object
    exit: float
    pnl_pct: float
    bars_held: int
    reason: str
    vote: int
    regime: str


# ── Trade simulation ─────────────────────────────────────────────────────────

def simulate_exit(bars, sig_i, rules, signal_series, ticker, vote, regime):
    """
    Simulate one trade from a signal on bar `sig_i`.

    Entry = NEXT bar's open (the signal comes from the prior close and is acted
    on at the following open — logging the signal-bar close was a real bug in
    the live system).

    Within each bar, worst-case ordering — never assume the favourable fill:
      1. open gaps at/below stop  -> fill at the OPEN (gap through)
      2. low touches stop         -> fill at the STOP
      3. high reaches partial tgt -> book partial, optionally stop->breakeven
      4. close below trail SMA    -> fill at the CLOSE
      5. LC signal flip           -> fill at the CLOSE
      6. max hold reached         -> fill at the CLOSE
    """
    n = len(bars)
    ent_i = sig_i + 1
    if ent_i >= n:
        return None
    entry = float(bars["open"].iloc[ent_i])
    if not np.isfinite(entry) or entry <= 0:
        return None

    stop = entry * (1 - rules.stop_pct)
    risk = entry - stop
    realised, remaining, took_partial = 0.0, 1.0, False

    def out(i, px, reason):
        pnl = realised + remaining * (px - entry) / entry
        return Trade(ticker, rules.name, bars.index[ent_i], round(entry, 4),
                     bars.index[i], round(px, 4), round(pnl * 100, 4),
                     i - ent_i + 1, reason, vote, regime)

    last_i = min(n - 1, ent_i + rules.max_hold)
    for i in range(ent_i, last_i + 1):
        o = float(bars["open"].iloc[i]); h = float(bars["high"].iloc[i])
        l = float(bars["low"].iloc[i]);  c = float(bars["close"].iloc[i])
        held = i - ent_i + 1

        if i > ent_i and o <= stop:
            return out(i, o, "gap_through_stop")
        if l <= stop:
            return out(i, stop, "stop")

        if rules.partial_at_r > 0 and not took_partial and risk > 0:
            tgt = entry + rules.partial_at_r * risk
            if h >= tgt:
                realised += rules.partial_frac * (tgt - entry) / entry
                remaining -= rules.partial_frac
                took_partial = True
                if rules.breakeven_after_partial:
                    stop = entry

        if rules.trail_sma and held > 1 and i >= rules.trail_sma:
            sma = float(bars["close"].iloc[i - rules.trail_sma + 1: i + 1].mean())
            if c < sma:
                return out(i, c, f"below_sma{rules.trail_sma}")

        if rules.use_signal_flip and signal_series is not None and held > 1:
            try:
                if int(signal_series.iloc[i]) != 1:
                    return out(i, c, "signal_flip")
            except (ValueError, TypeError):
                pass

        if held >= rules.max_hold:
            return out(i, c, "max_hold")

    return out(last_i, float(bars["close"].iloc[last_i]), "eod")


# ── Signal generation (entry held CONSTANT across exit variants) ─────────────

def collect_signals(df, lc, bench_ctx, start_ts):
    """Return [(bar_index, vote, regime)] for every fresh long flip that passes gates."""
    vwap  = _weekly_vwap(df)
    avg20 = df["volume"].rolling(20).mean().shift(1)
    ema50 = df["close"].ewm(span=50, adjust=False).mean()
    ret1  = df["close"].pct_change()
    ctx   = bench_ctx.reindex(df.index)

    delta = df["close"].diff()
    gain  = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    rsi   = 100 - 100 / (1 + gain / loss.replace(0, np.nan))

    out = []
    for i in range(100, len(df) - 1):
        d = df.index[i]
        if d < start_ts or pd.isna(ctx["min_vote"].iloc[i]):
            continue
        c   = float(df["close"].iloc[i])
        vol = float(df["volume"].iloc[i])
        if c < MIN_PRICE or c * vol < MIN_DOLLAR_VOLUME:
            continue
        v20 = avg20.iloc[i]
        if pd.notna(v20) and v20 > 0 and vol < VOLUME_MIN_RATIO * v20:
            continue
        sr = ret1.iloc[i]; br = ctx["bench_ret"].iloc[i]
        if pd.isna(sr) or pd.isna(br) or sr <= br or sr < MIN_ENTRY_MOMENTUM:
            continue
        if pd.notna(ema50.iloc[i]) and c < float(ema50.iloc[i]):
            continue
        r = rsi.iloc[i]
        if pd.notna(r) and not (40 <= float(r) <= 70):
            continue
        wv = vwap.iloc[i]
        if pd.isna(wv) or c <= float(wv):
            continue
        row  = lc.iloc[i]
        vote = int(row["prediction"])
        if pd.isna(row["startLongTrade"]) or vote < int(ctx["min_vote"].iloc[i]):
            continue
        out.append((i, vote, str(ctx["regime"].iloc[i])))
    return out


def _weekly_vwap(df):
    week = df.index.to_series().dt.to_period("W-FRI").dt.start_time
    tp   = (df["high"] + df["low"] + df["close"]) / 3
    v    = (tp * df["volume"]).groupby(week).cumsum() / \
           df["volume"].groupby(week).cumsum().replace(0, np.nan)
    v.index = df.index
    return v


def run_ticker(ticker, df, bench_ctx, start_ts, rules_list):
    try:
        lc = LorentzianClassification(df.copy(), features=_LC_FEATURES,
                                      filterSettings=_lc_filters()).df
    except Exception as exc:
        log.debug("LC failed %s: %s", ticker, exc)
        return []
    sigs = collect_signals(df, lc, bench_ctx, start_ts)
    if not sigs:
        return []
    trades = []
    for rules in rules_list:
        for i, vote, regime in sigs:
            t = simulate_exit(df, i, rules, lc["signal"], ticker, vote, regime)
            if t:
                trades.append(t)
    return trades


# ── Data ─────────────────────────────────────────────────────────────────────

def fetch_bars(tickers, years):
    days = int(years * 365) + 300
    out = {}
    for i in range(0, len(tickers), 50):
        chunk = tickers[i:i + 50]
        try:
            raw = yf.download(chunk, period=f"{days}d", interval="1d",
                              group_by="ticker", auto_adjust=True,
                              progress=False, threads=False)
        except Exception as exc:
            log.warning("Download error: %s", exc); continue
        if raw is None or raw.empty:
            continue
        for sym in chunk:
            try:
                d = raw[sym].copy() if len(chunk) > 1 else raw.copy()
                if isinstance(d.columns, pd.MultiIndex):
                    d.columns = d.columns.get_level_values(-1)
                d.columns = [str(c).lower() for c in d.columns]
                if isinstance(d.index, pd.DatetimeIndex) and d.index.tz is not None:
                    d.index = d.index.tz_localize(None)
                d = d.dropna(subset=["close"])
                if len(d) >= 200:
                    out[sym] = d
            except (KeyError, AttributeError):
                pass
    log.info("Fetched %d / %d tickers", len(out), len(tickers))
    return out


def bench_context(years):
    b = fetch_bars([BENCHMARK], years).get(BENCHMARK)
    if b is None:
        log.error("Could not fetch %s — aborting.", BENCHMARK); sys.exit(1)
    ema = b["close"].ewm(span=BENCH_EMA_PERIOD, adjust=False).mean()
    regime = pd.Series(np.where(b["close"] > ema, "BULL", "BEAR"), index=b.index)
    return pd.DataFrame({
        "bench_ret": b["close"].pct_change(),
        "regime": regime,
        "min_vote": regime.map({"BULL": BULL_MIN_VOTE, "BEAR": BEAR_MIN_VOTE}),
    })


# ── Stats ────────────────────────────────────────────────────────────────────

def summarise(pnl_list):
    if not pnl_list:
        return {"n": 0}
    p = pd.Series(pnl_list)
    w, l = p[p > 0], p[p <= 0]
    avg_w = float(w.mean()) if len(w) else 0.0
    avg_l = float(abs(l.mean())) if len(l) else 0.0
    payoff = avg_w / avg_l if avg_l else float("inf")
    wr = len(w) / len(p) * 100
    be = avg_l / (avg_w + avg_l) * 100 if (avg_w + avg_l) else float("nan")
    eq = p.cumsum(); dd = float((eq - eq.cummax()).min())
    pf = float(w.sum() / abs(l.sum())) if len(l) and l.sum() != 0 else float("inf")
    return {"n": len(p), "win_rate": wr, "avg_win": avg_w, "avg_loss": avg_l,
            "payoff": payoff, "breakeven_wr": be, "edge": wr - be,
            "profit_factor": pf, "expectancy": float(p.mean()),
            "total": float(p.sum()), "max_dd": dd}


def fmt(name, s):
    if not s.get("n"):
        return f"  {name:22s} no trades"
    ok = "PASS" if s["expectancy"] > 0 and s["profit_factor"] >= 1.2 else "FAIL"
    return (f"  {name:22s} n={s['n']:5d} win={s['win_rate']:5.1f}% "
            f"W=+{s['avg_win']:5.2f}% L=-{s['avg_loss']:5.2f}% "
            f"payoff={s['payoff']:5.2f} breakeven={s['breakeven_wr']:5.1f}% "
            f"edge={s['edge']:+5.1f}pp PF={s['profit_factor']:5.2f} "
            f"E={s['expectancy']:+6.3f}% DD={s['max_dd']:7.1f}% [{ok}]")


def report(trades, telegram=False):
    if not trades:
        print("\nNo trades generated."); return
    df = pd.DataFrame([t.__dict__ for t in trades])
    df.to_csv("backtest_trades.csv", index=False)

    lines = ["", "=" * 118,
             "EXIT RULE COMPARISON  (identical entry signals, only the exit differs)",
             "=" * 118]
    order = [r.name for r in PRESETS if r.name in set(df["rule"])]
    for name in order:
        lines.append(fmt(name, summarise(df[df["rule"] == name]["pnl_pct"].tolist())))

    base = order[0] if order else None
    if base:
        sub = df[df["rule"] == base]
        lines += ["", "-" * 118, f"BREAKDOWN for '{base}'", "-" * 118]
        for rg in sorted(sub["regime"].unique()):
            lines.append(fmt(f"regime={rg}", summarise(sub[sub["regime"] == rg]["pnl_pct"].tolist())))
        lines.append(fmt("vote>=8", summarise(sub[sub["vote"] >= 8]["pnl_pct"].tolist())))
        lines.append(fmt("vote 6-7", summarise(sub[sub["vote"] < 8]["pnl_pct"].tolist())))
        lines += ["", "Exit reasons:",
                  sub.groupby("reason")["pnl_pct"].agg(["count", "mean"]).round(2).to_string()]
    lines += ["", "NOTE: LC run once over full history -> optimistically biased (see docstring).",
              "      Treat these numbers as an UPPER BOUND on true performance.",
              "Trade log: backtest_trades.csv"]
    text = "\n".join(lines)
    print(text)

    if telegram:
        try:
            from alerts import send_alert
            head = [l for l in lines if l.strip().startswith(("current", "hold_", "wide_",
                                                              "partial_", "trail"))]
            send_alert("<b>Backtest results</b>\n<pre>" + "\n".join(head[:8]) + "</pre>")
        except Exception as exc:
            log.warning("Telegram report failed: %s", exc)


def get_universe(name):
    ua = {"User-Agent": "Mozilla/5.0"}
    urls = {"sp500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            "sp400": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
            "sp600": "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"}
    syms = []
    for key in (["sp500", "sp400", "sp600"] if name == "sp1500" else [name]):
        for t in pd.read_html(urls[key], storage_options=ua):
            if "Symbol" in [str(c) for c in t.columns]:
                syms += t["Symbol"].dropna().astype(str).str.replace(".", "-", regex=False).tolist()
                break
    return sorted({s.strip() for s in syms if s and len(s) <= 6})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+")
    ap.add_argument("--universe", choices=["sp500", "sp400", "sp600", "sp1500"])
    ap.add_argument("--years", type=float, default=3.0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="cap ticker count (speed)")
    ap.add_argument("--telegram", action="store_true")
    a = ap.parse_args()

    tickers = [t.upper() for t in a.tickers] if a.tickers else \
              (get_universe(a.universe) if a.universe else ap.error("need --tickers or --universe"))
    tickers = [t for t in tickers if t != BENCHMARK]
    if a.limit:
        tickers = tickers[:a.limit]

    ctx = bench_context(a.years)
    start = ctx.index[-1] - pd.DateOffset(days=int(a.years * 365))
    log.info("Window %s -> %s | %d tickers | %d exit rules",
             start.date(), ctx.index[-1].date(), len(tickers), len(PRESETS))

    bars = fetch_bars(tickers, a.years)
    trades = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(run_ticker, s, d, ctx, start, PRESETS): s for s, d in bars.items()}
        for n, f in enumerate(concurrent.futures.as_completed(futs), 1):
            try:
                trades.extend(f.result())
            except Exception as exc:
                log.debug("ticker failed: %s", exc)
            if n % 25 == 0:
                log.info("Simulated %d / %d", n, len(futs))
    report(trades, telegram=a.telegram)


if __name__ == "__main__":
    main()
