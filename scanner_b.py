"""
Lorentzian Scanner B — v6
=========================
- Algorithm: advanced-ta LorentzianClassification (validated Python port of jdehorty's Pine Script)
- Features: TV-default params (RSI 14/1, WT 10/11, CCI 20/1, ADX 20/2, RSI 9/1)
- Filters: volatility + regime (TV defaults, ON) + weekly VWAP
- Data: yfinance batch download (consolidated tape, ~50-ticker sequential chunks)
- Alerts: Telegram with TradingView one-click links + vote strength
- Vote filter: only fire on |vote| >= MIN_VOTE (default 4) — removes low-conviction noise
- No Alpaca dependency
"""

import os
import time
import schedule
import logging
import concurrent.futures
from datetime import datetime, timezone

import pandas as pd
import numpy as np
import yfinance as yf
from advanced_ta import LorentzianClassification

from alerts import send_alert
from tickers import get_sp500, get_nasdaq100, filter_excluded, EXCLUDED_TICKERS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

MIN_DAILY_VOLUME = 100_000
MIN_PRICE        = 5.0
MIN_VOTE         = 4      # min KNN vote strength — filters low-conviction signals
TV_BASE_URL      = "https://www.tradingview.com/chart/?symbol="


# ── Data fetch ──────────────────────────────────────────────────────────────

def fetch_all_bars(tickers: list, days: int = 365) -> dict:
    """
    Batch-download daily OHLCV for all tickers via yfinance (consolidated tape).
    Downloads in sequential chunks of 50 to avoid rate-limiting.
    Returns {ticker: DataFrame} for tickers with ≥100 bars.
    """
    all_data: dict = {}
    chunk_size    = 50
    n_chunks      = (len(tickers) + chunk_size - 1) // chunk_size

    for idx in range(0, len(tickers), chunk_size):
        chunk = tickers[idx : idx + chunk_size]
        log.info("Downloading chunk %d/%d (%d tickers)…",
                 idx // chunk_size + 1, n_chunks, len(chunk))
        try:
            raw = yf.download(
                chunk,
                period=f"{days}d",
                interval="1d",
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=False,
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


def _clean_df(raw: pd.DataFrame, sym: str):
    """Normalise a raw yfinance DataFrame; return None if too short."""
    df = raw.copy()
    df.columns = [c.lower() for c in df.columns]
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df.index.name = "timestamp"
    df = df.dropna(subset=["close"])
    return df if len(df) >= 100 else None


# ── Weekly VWAP ──────────────────────────────────────────────────────────────

def weekly_vwap(df: pd.DataFrame) -> pd.Series:
    """Cumulative weekly VWAP, resets each Monday."""
    df = df.copy()
    df["_week"] = df.index.to_series().dt.to_period("W-FRI").dt.start_time
    tp       = (df["high"] + df["low"] + df["close"]) / 3
    pv       = tp * df["volume"]
    cum_pv   = pv.groupby(df["_week"]).cumsum()
    cum_vol  = df["volume"].groupby(df["_week"]).cumsum()
    vwap     = cum_pv / cum_vol.replace(0, np.nan)
    vwap.index = df.index
    return vwap


# ── Per-stock scan ────────────────────────────────────────────────────────────

def scan_stock(ticker: str, df: pd.DataFrame, counters: dict):
    try:
        last_price = float(df["close"].iloc[-1])
        if last_price < MIN_PRICE:
            counters["price"] += 1
            return None

        daily_vol = float(df["volume"].iloc[-1])
        if daily_vol < MIN_DAILY_VOLUME:
            counters["volume"] += 1
            return None

        vwap_series = weekly_vwap(df)
        last_vwap   = float(vwap_series.iloc[-1])
        if np.isnan(last_vwap):
            counters["no_data"] += 1
            return None

        counters["passed"] += 1

        lc = LorentzianClassification(
            df,
            features=[
                LorentzianClassification.Feature("RSI", 14, 1),
                LorentzianClassification.Feature("WT",  10, 11),
                LorentzianClassification.Feature("CCI", 20, 1),
                LorentzianClassification.Feature("ADX", 20, 2),
                LorentzianClassification.Feature("RSI",  9, 1),
            ],
            filterSettings=LorentzianClassification.FilterSettings(
                useVolatilityFilter=True,
                useRegimeFilter=True,
                useAdxFilter=False,
                regimeThreshold=-0.1,
                adxThreshold=20,
                kernelFilter=LorentzianClassification.KernelFilter(
                    useKernelSmoothing=False,
                ),
            ),
        )

        last = lc.df.iloc[-1]
        vote = int(last["prediction"])

        if bool(last.get("isEarlySignalFlip", False)):
            counters["early_flip"] += 1

        if not pd.isna(last["startLongTrade"]) and last_price > last_vwap and vote >= MIN_VOTE:
            return {"side": "BUY",  "ticker": ticker,
                    "price": round(last_price, 2), "vwap": round(last_vwap, 2),
                    "vote": vote}
        if not pd.isna(last["startShortTrade"]) and last_price < last_vwap and abs(vote) >= MIN_VOTE:
            return {"side": "SELL", "ticker": ticker,
                    "price": round(last_price, 2), "vwap": round(last_vwap, 2),
                    "vote": vote}

        if not pd.isna(last["startLongTrade"]) or not pd.isna(last["startShortTrade"]):
            counters["vwap_rejected"] += 1

        return None

    except Exception as exc:
        log.debug("Error on %s: %s", ticker, exc)
        counters["no_data"] += 1
        return None


# ── Main scan loop ────────────────────────────────────────────────────────────

def run_scan():
    log.info("=== Lorentzian v6 scan (advanced-ta + yfinance) ===")
    send_alert(
        "🔍 <b>Lorentzian Scanner v6 [LC+VWAP]</b>\n"
        "Data: <b>yfinance</b> · Daily · consolidated tape\n"
        "<i>Algorithm: advanced-ta (validated TV port)</i>\n"
        "<i>Filters: Volatility + Regime (TV defaults) + Weekly VWAP</i>\n"
        f"<i>Excluded: oil/gas, weapons, drones ({len(EXCLUDED_TICKERS)} tickers)</i>"
    )

    raw_tickers    = list(set(get_sp500() + get_nasdaq100()))
    tickers        = filter_excluded(raw_tickers)
    excluded_count = len(raw_tickers) - len(tickers)
    log.info("Universe: %d tickers (%d excluded)", len(tickers), excluded_count)

    all_bars = fetch_all_bars(tickers)
    no_data_count = len(tickers) - len(all_bars)

    signals  = []
    workers  = int(os.getenv("SCAN_WORKERS", "8"))
    counters = {"no_data": no_data_count, "price": 0, "volume": 0,
                "passed": 0, "vwap_rejected": 0, "early_flip": 0}

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(scan_stock, sym, df, counters): sym
            for sym, df in all_bars.items()
        }
        done = 0
        for future in concurrent.futures.as_completed(futures):
            done += 1
            result = future.result()
            if result:
                signals.append(result)
                log.info("[LC+VWAP] %s %s @ $%s (vwap $%s) vote=%s",
                         result["side"], result["ticker"],
                         result["price"], result["vwap"], result["vote"])
            if done % 50 == 0:
                log.info("Progress: %d / %d", done, len(all_bars))

    log.info("[LC+VWAP] Scan complete — %d signal(s).", len(signals))

    send_alert(
        f"📊 <b>[LC+VWAP] Filter breakdown</b>\n"
        f"Total in universe: {len(raw_tickers)}\n"
        f"🚫 Excluded (oil/weapons/drones): {excluded_count}\n"
        f"📥 Scanned: {len(tickers)}\n"
        f"✅ Passed price/vol filters: {counters['passed']}\n"
        f"❌ No data: {counters['no_data']}\n"
        f"❌ Price &lt;$5: {counters['price']}\n"
        f"❌ Volume &lt;100K: {counters['volume']}\n"
        f"ℹ️ Early signal flip (stat): {counters['early_flip']}\n"
        f"🟡 Lorentz fired, rejected by VWAP: {counters['vwap_rejected']}"
    )

    buys  = [s for s in signals if s["side"] == "BUY"]
    sells = [s for s in signals if s["side"] == "SELL"]

    if buys or sells:
        msg = "🎯 <b>[LC+VWAP] SIGNALS</b>\n\n"
        if buys:
            msg += "🟢 <b>BUY</b> (price &gt; weekly VWAP):\n"
            for s in buys:
                tv  = f'{TV_BASE_URL}{s["ticker"]}'
                msg += f'<a href="{tv}"><b>{s["ticker"]}</b></a> ${s["price"]} · vwap ${s["vwap"]} · vote +{s["vote"]}\n'
            msg += "\n"
        if sells:
            msg += "🔴 <b>SELL</b> (price &lt; weekly VWAP):\n"
            for s in sells:
                tv  = f'{TV_BASE_URL}{s["ticker"]}'
                msg += f'<a href="{tv}"><b>{s["ticker"]}</b></a> ${s["price"]} · vwap ${s["vwap"]} · vote {s["vote"]}\n'
            msg += "\n"
        msg += f"<i>Scanned {len(tickers)} stocks · {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC</i>"
        send_alert(msg)
    else:
        send_alert(
            f"✅ [LC+VWAP] No signals today.\n"
            f"<i>Scanned {len(tickers)} stocks · "
            f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC</i>"
        )


if __name__ == "__main__":
    log.info("Lorentzian Scanner v6 starting…")
    run_scan()
    schedule_time = os.getenv("SCAN_TIME_UTC", "23:00")
    schedule.every().day.at(schedule_time).do(run_scan)
    log.info("Next scheduled run at %s UTC daily.", schedule_time)
    while True:
        schedule.run_pending()
        time.sleep(60)
