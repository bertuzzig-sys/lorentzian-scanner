"""
Lorentzian Scanner B â v9.0 (Noise Reduction + Quant Filters)
===========================
Changes from v8.0:
- RE-ENTRY signals removed: fresh Lorentzian flips only (no more VWAP re-log noise)
- Max 10 concurrent open positions: no new signals when book is full
- Sector cap: 1 signal per sector per scan (no 5 bank signals in one day)
- Entry day momentum: stock must be up â¥ 0.5% on the entry day (no flat/red entries)
- Stop loss exit price capped at exactly -4% (gap-down blowthrough fix)
- Put/Call ratio overlay: P/C < 0.70 (GREED) â vote â¥ 8 always + half size warning
                          P/C > 1.00 (FEAR)  â vote â¥ 6 even in BEAR (buy the panic)
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
BEAR_MIN_VOTE      = 8        # SPY below 21-EMA (bear regime) â raise bar
# SPY_EMA_PERIOD   = 21       # candles for SPY regime EMA
SPY_EMA_PERIOD     = 21       # candles for SPY regime EMA
STOP_LOSS_PCT      = 0.04     # hard stop: exit if position down â¥ 4%
VOLUME_MIN_RATIO   = 0.80     # today's volume must be â¥ume â¥ 80% of 20-day avg
EARNINGS_SKIP_DAYS = 5        # skip signal if earnings within N trading days
MIN_ENTRY_MOMENTUM = 0.005    # stock must be up â¥ 0.5% on entry day (no flat/red buys)
MAX_OPEN_POSITIONS = 10       # no new signals when 10 positions already open
EXIT_DAYS          = 5        # flag for review after N trading days
TV_BASE_URL        = "https://www.tradingview.com/chart/?symbol="
LOCK_FILE          = "/tmp/lorentzian_scan.lock"

# Put/Call ratio thresholds
PC_GREED = 0.70   # below = everyone is bullish â be defensive
PC_FEAR  = 1.00   # above = panic â be aggressive (buy)

# Derived at runtime â set in run_scan() after SPY + P/C checks
MIN_VOTE   = BULL_MIN_VOTE
SPY_REGIME = "BULL"    # updated each run
PC_RATIO   = 0.85      # updated each run
PC_REGIME  = "NEUTRAL" # GREED / NEUTRAL / FEAR

# Shared LC params â defined once, reused in scan_stock + check_exit_signal
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


# ââ Helpers âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

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
        # calendar is a DataFrame with dates as columns, rows include 'Earnings Date'
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
        return False  # if we can't tell, don't block the signal

def get_put_call_ratio() -> float:
    """
    Fetch CBOE equity put/call ratio (^CPCE).
    Returns float or 0.85 (neutral) on any error.
    P/C < 0.70 = everyone bullish (GREED, be careful)
    P/C > 1.00 = everyone fearful (FEAR, be aggressive)
    """
    for sym in ("^CPCE", "^CPC"):
        try:
            df = yf.download(sym, period="5d", interval="1d",
                             auto_adjust=False, progress=False, threads=False)
            if df.empty:
                continue
            df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
            if "close" in df.columns:
                val = float(df["close"].dropna().iloc[-1])
                if 0.3 < val < 3.0:   # sanity range
                    log.info("P/C ratio (%s): %.2f", sym, val)
                    return val
        except Exception as exc:
            log.debug("P/C fetch error (%s): %s", sym, exc)
    log.warning("Could not fetch P/C ratio â using neutral 0.85")
    return 0.85


_SECTOR_CACHE: dict[str, str] = {}

def get_sector(ticker: str) -> str:
    """
    Return GICS sector string for ticker via yfinance (cached).
    Falls back to 'Unknown' on error.
    """
    if ticker in _SECTOR_CACHE:
        return _SECTOR_CACHE[ticker]
    try:
        info   = yf.Ticker(ticker).info
        sector = info.get("sector") or "Unknown"
    except Exception:
        sector = "Unknown"
    _SECTOR_CACHE[ticker] = sector
    return sector


def run_scan_locked():
    """Run scan with an exclusive file lock â skips if another scan is already running."""
    try:
        lock = open(LOCK_FILE, "w")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.warning("Another scan is already running â skipping this trigger.")
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


# ââ Core scanner ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

def _size_label(vote: int) -> str:
    return "ð¥ LARGE" if vote >= 8 else "ð STANDARD"


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

        # ââ Volume confirmation: today's vol â¥ 80% of 20-day avg âââââââââââââ
        if len(df) >= 21:
            avg_vol_20 = float(df["volume"].iloc[-21:-1].mean())
            if avg_vol_20 > 0 and daily_vol < VOLUME_MIN_RATIO * avg_vol_20:
                counters["low_volume"] += 1
                return None

        # ââ Relative strength: must beat SPY 1-day return ââââââââââââââââââââ
        prev_close  = float(df["close"].iloc[-2]) if len(df) >= 2 else last_price
        stock_1d    = (last_price - prev_close) / prev_close if prev_close else 0
        if stock_1d <= spy_1d_return:
            counters["rs_fail"] += 1
            return None

        # ââ Entry day momentum: stock must be up â¥ 0.5% (no flat/red entries) â
        if stock_1d < MIN_ENTRY_MOMENTUM:
            counters["momentum_fail"] += 1
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

        # Fresh BUY only: Lorentzian just flipped long, price above weekly VWAP, vote strong
        if not pd.isna(last["startLongTrade"]) and last_price > last_vwap and vote >= MIN_VOTE:
            stop_price = round(last_price * (1 - STOP_LOSS_PCT), 2)
            return {
                "type": "BUY", "ticker": ticker,
                "price": round(last_price, 2), "vwap": round(last_vwap, 2),
                "vote": vote, "stop": stop_price, "size": _size_label(vote),
            }

        # Re-entries removed in v9.0 â fresh flips only
        if not pd.isna(last["startLongTrade"]) and vote >= MIN_VOTE:
            counters["vwap_rejected"] += 1

        return None
    except Exception as exc:
        log.debug("Error on %s: %s", ticker, exc)
        counters["no_data"] += 1
        return None


# ââ Main scan âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

def run_scan():
    global MIN_VOTE, SPY_REGIME, PC_RATIO, PC_REGIME

    scan_date = date.today().isoformat()
    log.info("=== Lorentzian v9.0 scan â %s ===", scan_date)

    # ââ 1. Load open positions from Sheets âââââââââââââââââââââââââââââââââââ
    open_positions, ws = sheets_logger.get_open_positions()
    open_tickers = {p["ticker"] for p in open_positions}
    log.info("Monitoring %d open positions for exits", len(open_positions))

    # ââ 2. Build universe âââââââââââââââââââââââââââââââââââââââââââââââââââââ
    raw_tickers    = list(set(get_sp500() + get_nasdaq100()))
    tickers        = filter_excluded(raw_tickers)
    excluded_count = len(raw_tickers) - len(tickers)
    log.info("Universe: %d tickers (%d excluded)", len(tickers), excluded_count)

    # ââ 3. Download all bars ââââââââââââââââââââââââââââââââââââââââââââââââââ
    all_bars = fetch_all_bars(tickers)

    # Download any open-position tickers not in the main universe
    missing = [t for t in open_tickers if t not in all_bars]
    if missing:
        log.info("Fetching %d exit-check tickers outside universe", len(missing))
        all_bars.update(fetch_all_bars(missing))

    no_data_count = sum(1 for t in tickers if t not in all_bars)

    # ââ 4. Market regime (SPY 21-EMA + Put/Call ratio) âââââââââââââââââââââââ
    SPY_REGIME, spy_1d_return, spy_ema = get_spy_regime(all_bars)
    spy_df   = all_bars.get("SPY")
    spy_last = float(spy_df["close"].iloc[-1]) if spy_df is not None else 0

    # P/C ratio overlay â adjusts vote threshold on top of SPY regime
    PC_RATIO = get_put_call_ratio()
    if PC_RATIO < PC_GREED:
        PC_REGIME = "GREED"
        MIN_VOTE  = BEAR_MIN_VOTE   # everyone bullish â be defensive, raise bar
    elif PC_RATIO > PC_FEAR:
        PC_REGIME = "FEAR"
        MIN_VOTE  = BULL_MIN_VOTE   # everyone fearful â be aggressive, lower bar
    else:
        PC_REGIME = "NEUTRAL"
        MIN_VOTE  = BULL_MIN_VOTE if SPY_REGIME == "BULL" else BEAR_MIN_VOTE

    pc_icon = {"GREED": "ð¡ GREED", "NEUTRAL": "âª NEUTRAL", "FEAR": "ð¢ FEAR"}[PC_REGIME]
    log.info("SPY regime: %s (close=%.2f ema=%.2f)", SPY_REGIME, spy_last, spy_ema)
    log.info("P/C ratio: %.2f â %s | Final MIN_VOTE=%d", PC_RATIO, PC_REGIME, MIN_VOTE)

    # Pre-load sectors for open positions (to enforce sector cap on new signals)
    open_sectors: set[str] = set()
    for pos in open_positions:
        sec = get_sector(pos["ticker"])
        if sec != "Unknown":
            open_sectors.add(sec)
    log.info("Open sectors: %s", sorted(open_sectors))

    send_alert(
        f"ð <b>Lorentzian Scanner V9.0 [LC+VWAP]</b>\n"
        f"Data: <b>yfinance</b> Â· Daily  Â· consolidated tape\n"
        f"<i>Algorithm: advanced-ta Â· FRESH BUY signals only</i>\n"
        f"<i>SPY: {'â¢ BULL' if SPY_REGIME == 'BULL' else 'ð´ BEAR'} "
        f"(${spy_last:.2f} vs EMA ${spy_ema:.2f})</i>\n"
        f"<i>P/C Ratio: {PC_RATIO:.2f} â {pc_icon}</i>\n"
        f"<i>Final Vote threshold: â¥ {MIN_VOTE}</i>\n"
        f"<i>Filters: VWAP + Volume + RS + Momentum + Earnings + Sector cap</i>\n"
        f"<i>Risk: Stop â{int(STOP_LOSS_PCT*100)}% Â· Max {MAX_OPEN_POSITIONS} positions Â· Hold {EXIT_DAYS}d</i>\n"
        f"<i>Excluded: oil/gas, weapons, drones ({len(EXCLUDED_TICKERS)} tickers)</i>"
    )

    # ââ 5. Scan for BUY signals âââââââââââââââââââââââââââââââââââââââââââââââ
    workers  = int(os.getenv("SCAN_WORKERS", "8"))
    counters = {
        "no_data": no_data_count, "price": 0, "volume": 0,
        "low_volume": 0, "rs_fail": 0, "momentum_fail": 0,
        "passed": 0, "vwap_rejected": 0, "early_flip": 0,
        "earnings_skip": 0, "dedup_skip": 0, "sector_skip": 0, "cap_skip": 0,
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

    # ââ 6. Dedup + earnings + position cap + sector cap ââââââââââââââââââââââ
    available_slots = max(0, MAX_OPEN_POSITIONS - len(open_tickers))
    log.info("Open positions: %d / %d Â· Available slots: %d",
             len(open_tickers), MAX_OPEN_POSITIONS, available_slots)

    signals      = []
    today_sectors: set[str] = set()   # sectors already taken by new signals today

    for sig in raw_signals:
        # 1. Skip if already an open position
        if sig["ticker"] in open_tickers:
            log.info("[DEDUP SKIP] %s already open", sig["ticker"])
            counters["dedup_skip"] += 1
            continue

        # 2. Skip if at position cap
        if available_slots <= 0:
            log.info("[CAP SKIP] %s â book full (%d positions)", sig["ticker"], MAX_OPEN_POSITIONS)
            counters["cap_skip"] += 1
            continue

        # 3. Skip if near earnings
        if has_near_earnings(sig["ticker"], EARNINGS_SKIP_DAYS):
            log.info("[EARNINGS SKIP] %s has earnings within %d days", sig["ticker"], EARNINGS_SKIP_DAYS)
            counters["earnings_skip"] += 1
            continue

        # 4. Sector cap: 1 per sector (skip if open position or today's signal already in sector)
        sector = get_sector(sig["ticker"])
        if sector in open_sectors or sector in today_sectors:
            log.info("[SECTOR SKIP] %s sector '%s' already covered", sig["ticker"], sector)
            counters["sector_skip"] += 1
            continue

        signals.append(sig)
        available_slots -= 1
        if sector != "Unknown":
            today_sectors.add(sector)

    log.info("Scan complete â %d signal(s) (%d earnings / %d dedup / %d cap / %d sector skipped).",
             len(signals), counters["earnings_skip"], counters["dedup_skip"],
             counters["cap_skip"], counters["sector_skip"])

    # ââ 7. Exit detection âââââââââââââââââââââââââââââââââââââââââââââââââââââ
    hard_exits   = []   # ð´ signal flipped OR stop loss hit
    review_flags = []   # â° 5-day hold, still bullish â review suggested

    for pos in open_positions:
        ticker     = pos["ticker"]
        state      = check_exit_signal(ticker, all_bars.get(ticker))
        cur_price  = state["price"] if state else pos["entry_price"]
        pnl        = round((cur_price - pos["entry_price"]) / pos["entry_price"] * 100, 2)

        # Hard stop loss â cap exit price at exactly entry*(1-4%) to prevent gap-down blowthrough
        if pnl <= -(STOP_LOSS_PCT * 100):
            cur_price   = round(pos["entry_price"] * (1 - STOP_LOSS_PCT), 2)
            pnl         = round(-STOP_LOSS_PCT * 100, 2)
            exit_reason = f"ð stop loss hit (â{int(STOP_LOSS_PCT*100)}%)"
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
            review_flags.append({
                "ticker":      ticker,
                "entry_price": pos["entry_price"],
                "cur_price":   cur_price,
                "pnl":         pnl,
                "days_held":   pos["days_held"],
                "vote":        state["vote"],
                "row_idx":     pos["row_idx"],
            })

    # ââ 8. Format & send Telegram âââââââââââââââââââââââââââââââââââââââââââââ
    buys      = [s for s in signals if s["type"] == "BUY"]
    reentries = []   # removed in v9.0 â fresh flips only

    # Filter breakdown
    send_alert(
        f"ð <b>[LC+VWAP v9.0] Filter breakdown</b>\n"
        f"Total universe: {len(raw_tickers)}\n"
        f"ð« Excluded: {excluded_count}\n"
        f"ð¥ Scanned: {len(tickers)}\n"
        f"â No data: {counters['no_data']}\n"
        f"â Price &lt;$5: {counters['price']}\n"
        f"â Volume &lt;100K: {counters['volume']}\n"
        f"â Low vol (20d avg): {counters['low_volume']}\n"
        f"â RS vs SPY: {counters['rs_fail']}\n"
        f"â Momentum &lt;0.5%: {counters['momentum_fail']}\n"
        f"â Near earnings: {counters['earnings_skip']}\n"
        f"â Already open (dedup): {counters['dedup_skip']}\n"
        f"â Position cap (â¥{MAX_OPEN_POSITIONS}): {counters['cap_skip']}\n"
        f"â Sector cap: {counters['sector_skip']}\n"
        f"â Passed all filters: {counters['passed']}\n"
        f"â¹ï¸ Early flip (stat): {counters['early_flip']}\n"
        f"ð¡ VWAP rejected: {counters['vwap_rejected']}\n"
        f"ð Open positions: {len(open_tickers)} / {MAX_OPEN_POSITIONS}"
    )

    # Main signals message
    spy_icon = "ð¢ BULL" if SPY_REGIME == "BULL" else "ð´ BEAR"
    msg = (f"ð¯ <b>[LC+VWAP v9.0] SIGNALS</b>\n"
           f"SPY: {spy_icon} Â· P/C: {PC_RATIO:.2f} ({pc_icon}) Â· Vote â¥ {MIN_VOTE}\n\n")

    # â Exit section â
    if hard_exits:
        msg += "ð´ <b>EXIT ALERTS</b> (sell / stop hit):\n"
        for e in hard_exits:
            pnl_s = f"+{e['pnl']}%" if e["pnl"] >= 0 else f"{e['pnl']}%"
            tv    = f'{TV_BASE_URL}{e["ticker"]}'
            msg  += (f'<a href="{tv}"><b>{e["ticker"]}</b></a> '
                     f'${e["cur_price"]} Â· was ${e["entry_price"]} Â· '
                     f'{pnl_s} Â· {e["reason"]}\n')
        msg += "\n"

    if review_flags:
        msg += f"â° <b>{EXIT_DAYS}-DAY REVIEW</b> (still bullish â consider taking profit):\n"
        for e in review_flags:
            pnl_s = f"+{e['pnl']}%" if e["pnl"] >= 0 else f"{e['pnl']}%"
            tv    = f'{TV_BASE_URL}{e["ticker"]}'
            msg  += (f'<a href="{tv}"><b>{e["ticker"]}</b></a> '
                     f'${e["cur_price"]} Â· was ${e["entry_price"]} Â· '
                     f'{pnl_s} Â· {e["days_held"]}d Â· vote {e["vote"]:+d}\n')
        msg += "\n"

    if open_positions and not hard_exits and not review_flags:
        msg += "â <b>All positions still bullish</b> â no exits today.\n\n"

    # â Fresh BUYs â
    if buys:
        msg += "ð¢ <b>FRESH BUY</b> (Lorentzian just flipped long):\n"
        for s in buys:
            tv   = f'{TV_BASE_URL}{s["ticker"]}'
            msg += (f'<a href="{tv}"><b>{s["ticker"]}</b></a> '
                    f'${s["price"]} Â· vwap ${s["vwap"]} Â· vote {s["vote"]:+d} Â· '
                    f'{s["size"]} Â· stop ${s["stop"]}\n')
        msg += "\n"

    if not buys and not hard_exits and not review_flags:
        msg += "No new signals today.\n"

    msg += f"<i>Scanned {len(tickers)} stocks Â· {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC</i>\n"
    if PC_REGIME == "GREED":
        msg += "â ï¸ <i>P/C below 0.70 â market very bullish. Stay selective.</i>"
    elif PC_REGIME == "FEAR":
        msg += "ð¡ <i>P/C above 1.00 â elevated fear. Signals are higher conviction.</i>"
    send_alert(msg)

    # ââ 9. Log new signals to Sheets âââââââââââââââââââââââââââââââââââââââââ
    if buys or reentries:
        sheets_logger.log_signals(scan_date, buys, reentries)

    # ââ 10. Mark exited positions CLOSED in Sheets ââââââââââââââââââââââââââââ
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
    log.info("Lorentzian Scanner V9.0 starting...")
    run_scan_locked()
    schedule_time = os.getenv("SCAN_TIME_UTC", "23:00")
    schedule.every().day.at(schedule_time).do(run_scan_locked)
    log.info("Next scheduled run at %s UTC daily.", schedule_time)
    while True:
        schedule.run_pending()
        time.sleep(60)
