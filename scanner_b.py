"""
Lorentzian Scanner B — v8.0 (Smart Filters + Risk Management)
===========================
Changes from v7.0:
- Stop loss: -4% hard stop on all open positions (exit immediately)
- Pre-earnings filter: skip any signal with earnings within 5 trading days
- Market regime: SPY 21-EMA check — bear mode raises MIN_VOTE to 8
- Volume confirmation: today's volume must be ≥ 80% of 20-day average
- Relative strength: stock 1d return must beat SPY 1d return
- Position sizing: vote=8 signals labeled LARGE (2x), vote 6-7 STANDARD
"""

import os
import time
import fcntl
import schedule
import logging
import concurrent.futures
from datetime import datetime, date, timezone, timedelta

import pandas as pd
import numpy as np
import yfinance as yf
from advanced_ta import LorentzianClassification

from alerts import send_alert
from tickers import get_sp500, get_nasdaq100, filter_excluded, EXCLUDED_TICKERS
import sheets_logger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

MIN_DAILY_VOLUME   = 100_000
MIN_PRICE          = 5.0
BULL_MIN_VOTE      = 6        # SPY above 21-EMA (bull regime)
BEAR_MIN_VOTE      = 8        # SPY below 21-EMA (bear regime) — raise bar
SPY_EMA_PERIOD     = 21       # candles for SPY regime EMA
STOP_LOSS_PCT      = 0.04     # hard stop: exit if position down ≥ 4%
VOLUME_MIN_RATIO   = 0.80     # today's volume must be ≥ 80% of 20-day avg
EARNINGS_SKIP_DAYS = 5        # skip signal if earnings within N trading days
REENTRY_VWAP_PCT   = 0.03     # re-entry window: 0–3% above weekly VWAP
REENTRY_MAX_SHOW   = 15       # max re-entries shown (closest to VWAP first)
EXIT_DAYS          = 5        # flag for review after N trading days
TV_BASE_URL        = "https://www.tradingview.com/chart/?symbol="
LOCK_FILE          = "/tmp/lorentzian_scan.lock"

# Derived at runtime — set in run_scan() after SPY check
MIN_VOTE  = BULL_MIN_VOTE
SPY_REGIME = "BULL"   # updated each run

# Shared LC params — defined once, reused in scan_stock + check_exit_signal
_LC_FEATURES = [
    LorentzianClassification.Feature("RSI", 14, 1),
    LorentzianClassification.Feature("WT",  10, 11),
    LorentzianClassification.Feature("CCI", 20, 1),
    LorentzianClassification.Feature("ADX", 20, 2),
    LorentzianClassification.Feature("RSI",  9, 1),
]
_LC_FILTERS = LorentzianClassification.FilterSettings(
    useVolatilityFilter=True,
    useRegimeFilter=True,
    useAdxFilter=False,
    regimeThreshold=-0.1,
    adxThreshold=20,
    kernelFilter=LorentzianClassification.KernelFilter(useKernelSmoothing=False),
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_spy_regime(all_bars: dict) -> tuple[str, float, float]:
    """
    Return (regime, spy_1d_return, spy_ema) where regime is 'BULL' or 'BEAR'.
    Downloads SPY if not already in all_bars.
    """
    df = all_bars.get("SPY")
    if df is None:
        try:
            raw = yf.download("SPY", period="60d", interval="1d",
                              auto_adjust=True, progress=False)
            raw.columns = [c.lower() for c in raw.columns]
            if isinstance(raw.index, pd.DatetimeIndex) and raw.index.tz is not None:
                raw.index = raw.index.tz_localize(None)
            df = raw.dropna(subset=["close"])
            all_bars["SPY"] = df
        except Exception as exc:
            log.warning("Could not fetch SPY for regime check: %s", exc)
            return "BULL", 0.0, 0.0

    closes = df["close"]
    ema = float(closes.ewm(span=SPY_EMA_PERIOD, adjust=False).mean().iloc[-1])
    last = float(closes.iloc[-1])
    prev = float(closes.iloc[-2]) if len(closes) >= 2 else last
    spy_1d = (last - prev) / prev
    regime = "BULL" if last > ema else "BEAR"
    return regime, spy_1d, ema


def has_near_earnings(ticker: str, trading_days: int = EARNINGS_SKIP_DAYS) -> bool:
    """
    Return True if the ticker has earnings within `trading_days` trading days.
    Uses yfinance calendar. Defaults to False (allow signal) on any error.
    """
    try:
        cal = yf.Ticker(ticker).calendar
        if cal is None or cal.empty:
            return False
        if "Earnings Date" in cal.index:
            earn_date = cal.loc["Earnings Date"].iloc[0]
        elif isinstance(cal, dict) and "Earnings Date" in cal:
            earn_date = cal["Earnings Date"]
        else:
            return False
        if pd.isna(earn_date):
            return False
        earn_dt = pd.Timestamp(earn_date).normalize()
        today   = pd.Timestamp(date.today())
        bdays   = len(pd.bdate_range(today, earn_dt))
        return 0 <= bdays <= trading_days
    except Exception:
        return False

def run_scan_locked():
    """Run scan with an exclusive file lock — skips if another scan is already running."""
    try:
        lock = open(LOCK_FILE, "w")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.warning("Another scan is already running — skipping this trigger.")
        return
    try:
        run_scan()
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def fetch_all_bars(tickers, days=365):
    all_data   = {}
    chunk_size = 50
    n_chunks   = (len(tickers) + chunk_size - 1) // chunk_size
    for idx in range(0, len(tickers), chunk_size):
        chunk = tickers[idx:idx + chunk_size]
        log.info("Downloading chunk %d/%d (%d tickers)...",
                 idx // chunk_size + 1, n_chunks, len(chunk))
        try:
            raw = yf.download(
                chunk, period=f"{days}d", interval="1d",
                group_by="ticker", auto_adjust=True,
                progress=False, threads=False,
            )
            if raw.empty:
                continue
            if len(chunk) == 1:
                df = _clean_df(raw, chunk[0])
                if df is not None:
                    all_data[chunk[0]] = df
            else:
                for sym in chunk:
                    try:
                        df = _clean_df(raw[sym], sym)
                        if df is not None:
                            all_data[sym] = df
                    except (KeyError, AttributeError):
                        pass
        except Exception as exc:
            log.warning("Chunk %d download error: %s", idx // chunk_size + 1, exc)
        if idx + chunk_size < len(tickers):
            time.sleep(2)
    log.info("Fetched data for %d / %d tickers", len(all_data), len(tickers))
    return all_data


def _clean_df(raw, sym):
    df = raw.copy()
    df.columns = [c.lower() for c in df.columns]
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df.index.name = "timestamp"
    df = df.dropna(subset=["close"])
    return df if len(df) >= 100 else None


def weekly_vwap(df):
    df = df.copy()
    df["_week"] = df.index.to_series().dt.to_period("W-FRI").dt.start_time
    tp      = (df["high"] + df["low"] + df["close"]) / 3
    pv      = tp * df["volume"]
    cum_pv  = pv.groupby(df["_week"]).cumsum()
    cum_vol = df["volume"].groupby(df["_week"]).cumsum()
    vwap    = cum_pv / cum_vol.replace(0, np.nan)
    vwap.index = df.index
    return vwap


def _run_lc(df):
    """Run LorentzianClassification; return (last_row, vote_int, signal_int)."""
    lc   = LorentzianClassification(df, features=_LC_FEATURES, filterSettings=_LC_FILTERS)
    last = lc.df.iloc[-1]
    return last, int(last["prediction"]), int(last["signal"])


def check_exit_signal(ticker: str, df) -> dict | None:
    """
    Return current LC state for an open position ticker.
    Used to detect exit conditions without affecting the main BUY scan.
    Returns {price, signal, vote} or None on error.
    """
    if df is None or len(df) < 100:
        return None
    try:
        last_price  = float(df["close"].iloc[-1])
        _, vote, signal = _run_lc(df)
        return {"price": round(last_price, 2), "signal": signal, "vote": vote}
    except Exception as exc:
        log.debug("Exit-check error on %s: %s", ticker, exc)
        return None


# ── Core scanner ──────────────────────────────────────────────────────────────

def _size_label(vote: int) -> str:
    return "🔥 LARGE" if vote >= 8 else "📊 STANDARD"


def scan_stock(ticker, df, counters, spy_1d_return: float = 0.0):
    try:
        last_price = float(df["close"].iloc[-1])
        if last_price < MIN_PRICE:
            counters["price"] += 1
            return None

        daily_vol = float(df["volume"].iloc[-1])
        if daily_vol < MIN_DAILY_VOLUME:
            counters["volume"] += 1
            return None

        # ── Volume confirmation: today's vol ≥ 80% of 20-day avg ─────────────
        if len(df) >= 21:
            avg_vol_20 = float(df["volume"].iloc[-21:-1].mean())
            if avg_vol_20 > 0 and daily_vol < VOLUME_MIN_RATIO * avg_vol_20:
                counters["low_volume"] += 1
                return None

        # ── Relative strength: must beat SPY 1-day return ────────────────────
        prev_close  = float(df["close"].iloc[-2]) if len(df) >= 2 else last_price
        stock_1d    = (last_price - prev_close) / prev_close if prev_close else 0
        if stock_1d <= spy_1d_return:
            counters["rs_fail"] += 1
            return None

        vwap_series = weekly_vwap(df)
        last_vwap   = float(vwap_series.iloc[-1])
        if np.isnan(last_vwap):
            counters["no_data"] += 1
            return None

        counters["passed"] += 1
        last, vote, signal = _run_lc(df)

        if bool(last.get("isEarlySignalFlip", False)):
            counters["early_flip"] += 1

        # Fresh BUY: Lorentzian just flipped long, price above weekly VWAP, vote strong
        if not pd.isna(last["startLongTrade"]) and last_price > last_vwap and vote >= MIN_VOTE:
            stop_price = round(last_price * (1 - STOP_LOSS_PCT), 2)
            return {
                "type": "BUY", "ticker": ticker,
                "price": round(last_price, 2), "vwap": round(last_vwap, 2),
                "vote": vote, "stop": stop_price, "size": _size_label(vote),
            }

        # Re-entry: signal still long, KNN bullish, price 0–3% above VWAP, green candle
        if signal == 1:
            pct_above  = (last_price - last_vwap) / last_vwap
            recovering = last_price > prev_close
            if 0 < pct_above <= REENTRY_VWAP_PCT and recovering and vote >= MIN_VOTE:
                counters["reentry"] += 1
                stop_price = round(last_price * (1 - STOP_LOSS_PCT), 2)
                return {
                    "type": "REENTRY", "ticker": ticker,
                    "price": round(last_price, 2), "vwap": round(last_vwap, 2),
                    "pct": round(pct_above * 100, 1), "vote": vote,
                    "stop": stop_price, "size": _size_label(vote),
                }

        if not pd.isna(last["startLongTrade"]) and vote >= MIN_VOTE:
            counters["vwap_rejected"] += 1

        return None
    except Exception as exc:
        log.debug("Error on %s: %s", ticker, exc)
        counters["no_data"] += 1
        return None


# ── Main scan ─────────────────────────────────────────────────────────────────

def run_scan():
    global MIN_VOTE, SPY_REGIME

    scan_date = date.today().isoformat()
    log.info("=== Lorentzian v8.0 scan — %s ===", scan_date)

    send_alert(
        f"🔍 <b>Lorentzian Scanner V7.0 [LC+VWAP]</b>\n"
        f"Data: <b>yfinance</b> · Daily · consolidated tape\n"
        f"<i>Algorithm: advanced-ta · BUY signals only</i>\n"
        f"<i>Filters: Volatility + Regime + Weekly VWAP + Vote ≥ {MIN_VOTE}</i>\n"
        f"<i>Excluded: oil/gas, weapons, drones ({len(EXCLUDED_TICKERS)} tickers)</i>"
    )

    # ── 1. Load open positions from Sheets ───────────────────────────────────
    open_positions, ws = sheets_logger.get_open_positions()
    open_tickers = {p["ticker"] for p in open_positions}
    log.info("Monitoring %d open positions for exits", len(open_positions))

    # ── 2. Build universe ─────────────────────────────────────────────────────
    raw_tickers    = list(set(get_sp500() + get_nasdaq100()))
    tickers        = filter_excluded(raw_tickers)
    excluded_count = len(raw_tickers) - len(tickers)
    log.info("Universe: %d tickers (%d excluded)", len(tickers), excluded_count)

    # ── 3. Download all bars ──────────────────────────────────────────────────
    all_bars = fetch_all_bars(tickers)

    # Download any open-position tickers that aren't in the main universe
    missing = [t for t in open_tickers if t not in all_bars]
    if missing:
        log.info("Fetching %d exit-check tickers outside universe", len(missing))
        all_bars.update(fetch_all_bars(missing))

    no_data_count = sum(1 for t in tickers if t not in all_bars)

    # ── 4. Market regime (SPY 21-EMA) ────────────────────────────────────────
    SPY_REGIME, spy_1d_return, spy_ema = get_spy_regime(all_bars)
    MIN_VOTE = BULL_MIN_VOTE if SPY_REGIME == "BULL" else BEAR_MIN_VOTE
    spy_df   = all_bars.get("SPY")
    spy_last = float(spy_df["close"].iloc[-1]) if spy_df is not None else 0
    log.info("SPY regime: %s (close=%.2f ema=%.2f) -> MIN_VOTE=%d",
             SPY_REGIME, spy_last, spy_ema, MIN_VOTE)

    # ── 5. Scan for BUY / REENTRY signals ────────────────────────────────────
    workers  = int(os.getenv("SCAN_WORKERS", "8"))
    counters = {
        "no_data": no_data_count, "price": 0, "volume": 0,
        "low_volume": 0, "rs_fail": 0,
        "passed": 0, "vwap_rejected": 0, "early_flip": 0, "reentry": 0,
        "earnings_skip": 0,
    }
    raw_signals  = []
    universe_set = set(tickers)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(scan_stock, sym, df, counters, spy_1d_return): sym
            for sym, df in all_bars.items() if sym in universe_set
        }
        done = 0
        for future in concurrent.futures.as_completed(futures):
            done += 1
            result = future.result()
            if result:
                raw_signals.append(result)
                log.info("[%s] %s @ $%s vote=%+d",
                         result["type"], result["ticker"], result["price"], result["vote"])
            if done % 50 == 0:
                log.info("Progress: %d / %d", done, len(futures))

    log.info("Scan complete — %d signal(s).", len(raw_signals))

    # ── 6. Dedup + pre-earnings filter
    signals = []
    for sig in raw_signals:
        if sig["ticker"] in open_tickers:
            log.info("[DEDUP SKIP] %s already open", sig["ticker"])
            counters["dedup_skip"] = counters.get("dedup_skip", 0) + 1
            continue
        if has_near_earnings(sig["ticker"], EARNINGS_SKIP_DAYS):
            log.info("[EARNINGS SKIP] %s earnings soon", sig["ticker"])
            counters["earnings_skip"] += 1
        else:
            signals.append(sig)

    log.info("After filters — %d signal(s).", len(signals))

    # ── 7. Exit detection ─────────────────────────────────────────────────────
    hard_exits   = []   # 🔴 signal flipped — definitive sell hint
    review_flags = []   # ⏰ 5-day hold, still bullish — review suggested

    for pos in open_positions:
        ticker    = pos["ticker"]
        state     = check_exit_signal(ticker, all_bars.get(ticker))
        cur_price = state["price"] if state else pos["entry_price"]
        pnl       = round((cur_price - pos["entry_price"]) / pos["entry_price"] * 100, 2)

        # Hard stop loss first, then signal checks
        if pnl <= -(STOP_LOSS_PCT * 100):
            exit_reason = f"stop loss hit ({pnl:.2f}%)"
        elif state is None:
            exit_reason = "no data / dropped from universe"
        elif state["signal"] == 0 or state["vote"] < 0:
            exit_reason = f"signal flipped (vote {state['vote']:+d})"
        else:
            exit_reason = None

        if exit_reason:
            hard_exits.append({
                "ticker":      ticker,
                "entry_price": pos["entry_price"],
                "cur_price":   cur_price,
                "pnl":         pnl,
                "reason":      exit_reason,
                "row_idx":     pos["row_idx"],
            })
        elif pos["days_held"] >= EXIT_DAYS:
            # Still bullish but held long enough — suggest review
            review_flags.append({
                "ticker":      ticker,
                "entry_price": pos["entry_price"],
                "cur_price":   cur_price,
                "pnl":         pnl,
                "days_held":   pos["days_held"],
                "vote":        state["vote"],
                "row_idx":     pos["row_idx"],
            })

    # ── 6. Format & send Telegram ─────────────────────────────────────────────
    buys      = [s for s in signals if s["type"] == "BUY"]
    reentries = sorted([s for s in signals if s["type"] == "REENTRY"], key=lambda x: x["pct"])
    top_re    = reentries[:REENTRY_MAX_SHOW]
    total_re  = len(reentries)
    shown_re  = len(top_re)

    # Filter breakdown (sent separately so signal message stays clean)
    send_alert(
        f"📊 <b>[LC+VWAP] Filter breakdown</b>\n"
        f"Total: {len(raw_tickers)}\n"
        f"🚫 Excluded: {excluded_count}\n"
        f"📥 Scanned: {len(tickers)}\n"
        f"✅ Passed price/vol: {counters['passed']}\n"
        f"❌ No data: {counters['no_data']}\n"
        f"❌ Price &lt;$5: {counters['price']}\n"
        f"❌ Volume &lt;100K: {counters['volume']}\n"
        f"❌ Low vol (20d avg): {counters['low_volume']}\n"
        f"❌ RS vs SPY: {counters['rs_fail']}\n"
        f"❌ Near earnings: {counters['earnings_skip']}\n"
        f"❌ Already open: {counters.get('dedup_skip', 0)}\n"
        f"✅ Passed all filters: {counters['passed']}\n"
        f"ℹ️ Early flip (stat): {counters['early_flip']}\n"
        f"🟡 VWAP rejected: {counters['vwap_rejected']}\n"
        f"🔄 Re-entry alerts: {total_re}"
    )

    # Main signals message
    regime_icon = "🟢 BULL" if SPY_REGIME == "BULL" else "🔴 BEAR"
    msg = f"🎯 <b>[LC+VWAP] SIGNALS</b> · Regime: {regime_icon} · Min vote: {MIN_VOTE}\n\n"

    # — Exit section (shown first so it's not missed) —
    if hard_exits:
        msg += "🔴 <b>EXIT ALERTS</b> (signal flipped — consider selling):\n"
        for e in hard_exits:
            pnl_s = f"+{e['pnl']}%" if e["pnl"] >= 0 else f"{e['pnl']}%"
            tv    = f'{TV_BASE_URL}{e["ticker"]}'
            msg  += (f'<a href="{tv}"><b>{e["ticker"]}</b></a> '
                     f'${e["cur_price"]} · was ${e["entry_price"]} · '
                     f'{pnl_s} · {e["reason"]}\n')
        msg += "\n"

    if review_flags:
        msg += f"⏰ <b>{EXIT_DAYS}-DAY REVIEW</b> (still bullish — consider taking profit):\n"
        for e in review_flags:
            pnl_s = f"+{e['pnl']}%" if e["pnl"] >= 0 else f"{e['pnl']}%"
            tv    = f'{TV_BASE_URL}{e["ticker"]}'
            msg  += (f'<a href="{tv}"><b>{e["ticker"]}</b></a> '
                     f'${e["cur_price"]} · was ${e["entry_price"]} · '
                     f'{pnl_s} · {e["days_held"]}d · vote {e["vote"]:+d}\n')
        msg += "\n"

    if open_positions and not hard_exits and not review_flags:
        msg += "✅ <b>All positions still bullish</b> — no exits today.\n\n"

    # — Fresh BUYs —
    if buys:
        msg += "🟢 <b>FRESH BUY</b> (Lorentzian just flipped long):\n"
        for s in buys:
            tv   = f'{TV_BASE_URL}{s["ticker"]}'
            msg += (f'<a href="{tv}"><b>{s["ticker"]}</b></a> '
                    f'${s["price"]} · vwap ${s["vwap"]} · vote {s["vote"]:+d} · '
                    f'{s["size"]} · stop ${s["stop"]}\n')
        msg += "\n"

    # — Re-entries —
    if top_re:
        count_label = f"top {shown_re}/{total_re}" if total_re > shown_re else str(shown_re)
        msg += f"🔄 <b>RE-ENTRY</b> (KNN bullish, near VWAP — {count_label}):\n"
        for s in top_re:
            tv   = f'{TV_BASE_URL}{s["ticker"]}'
            msg += (f'<a href="{tv}"><b>{s["ticker"]}</b></a> '
                    f'${s["price"]} · vwap ${s["vwap"]} · {s["pct"]}% above · vote {s["vote"]:+d}\n')
        msg += "\n"

    if not buys and not top_re and not hard_exits and not review_flags:
        msg += "No new signals today.\n"

    msg += f"<i>Scanned {len(tickers)} stocks · {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC</i>"
    send_alert(msg)

    # ── 7. Log new signals to Sheets ─────────────────────────────────────────
    if buys or reentries:
        sheets_logger.log_signals(scan_date, buys, reentries)

    # ── 8. Mark exited positions CLOSED in Sheets ─────────────────────────────
    if hard_exits and ws:
        sheets_logger.close_positions(ws, [
            {
                "row_idx":     e["row_idx"],
                "exit_price":  e["cur_price"],
                "exit_reason": e["reason"],
                "entry_price": e["entry_price"],
            }
            for e in hard_exits
        ])


if __name__ == "__main__":
    log.info("Lorentzian Scanner V8.0 starting...")
    run_scan_locked()
    schedule_time = os.getenv("SCAN_TIME_UTC", "23:00")
    schedule.every().day.at(schedule_time).do(run_scan_locked)
    log.info("Next scheduled run at %s UTC daily.", schedule_time)
    while True:
        schedule.run_pending()
        time.sleep(60)
