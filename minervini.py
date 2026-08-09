"""
Minervini Trend Template — vectorized, point-in-time safe.
==========================================================
Every function returns a pandas Series aligned to df.index, computed using
ONLY trailing data at each bar. This is deliberate: scanner_b.py evaluates
.iloc[-1] and backtest.py evaluates .iloc[i], so both run identical code and
cannot silently diverge.

Minervini's 8 criteria (Trend Template, "Trade Like a Stock Market Wizard"):
  1. Price > 150-day SMA and > 200-day SMA
  2. 150-day SMA > 200-day SMA
  3. 200-day SMA trending up for at least 1 month (~22 trading days)
  4. 50-day SMA > 150-day SMA and > 200-day SMA
  5. Price > 50-day SMA
  6. Price at least 30% above its 52-week low
  7. Price within 25% of its 52-week high
  8. Relative Strength rank >= 70 (cross-sectional, see rs_rank_panel)

Criteria 1-7 are per-ticker. Criterion 8 is cross-sectional and therefore
lives in rs_rank_panel(), which needs the whole universe at once.

DATA REQUIREMENT: criterion 3 needs 200 + 22 = 222 trailing bars, and the
52-week range needs 252. With a 365-calendar-day fetch you get ~250 trading
bars, which is marginal. Bump the fetch to ~500 calendar days before enabling
this in production, or MIN_BARS will reject most of the universe.
"""

import numpy as np
import pandas as pd

# Bars needed before the template can be evaluated at all.
MIN_BARS = 222

MA_FAST, MA_MID, MA_SLOW = 50, 150, 200
MA_SLOW_SLOPE_LOOKBACK = 22      # ~1 trading month
RANGE_WINDOW = 252               # ~52 weeks
MIN_PCT_ABOVE_LOW = 0.30         # criterion 6
MAX_PCT_BELOW_HIGH = 0.25        # criterion 7


def criteria(df: pd.DataFrame) -> dict[str, pd.Series]:
    """
    Return each of criteria 1-7 as a boolean Series aligned to df.index.
    Bars with insufficient history are False (via NaN comparison), which is
    the conservative direction: unverifiable trend == not in an uptrend.
    """
    close = df["close"].astype(float)

    ma50 = close.rolling(MA_FAST, min_periods=MA_FAST).mean()
    ma150 = close.rolling(MA_MID, min_periods=MA_MID).mean()
    ma200 = close.rolling(MA_SLOW, min_periods=MA_SLOW).mean()

    # min_periods below the full window would let an early, badly-estimated
    # 52w range pass criteria 6/7. Require the full window.
    hi_52w = close.rolling(RANGE_WINDOW, min_periods=RANGE_WINDOW).max()
    lo_52w = close.rolling(RANGE_WINDOW, min_periods=RANGE_WINDOW).min()

    return {
        "c1_above_150_200": (close > ma150) & (close > ma200),
        "c2_150_above_200": ma150 > ma200,
        "c3_200_rising": ma200 > ma200.shift(MA_SLOW_SLOPE_LOOKBACK),
        "c4_50_above_rest": (ma50 > ma150) & (ma50 > ma200),
        "c5_above_50": close > ma50,
        "c6_above_52w_low": close >= lo_52w * (1 + MIN_PCT_ABOVE_LOW),
        "c7_near_52w_high": close >= hi_52w * (1 - MAX_PCT_BELOW_HIGH),
    }


def template_series(df: pd.DataFrame) -> pd.Series:
    """Boolean Series: do criteria 1-7 all hold at each bar?"""
    crit = criteria(df)
    out = None
    for s in crit.values():
        out = s.fillna(False) if out is None else (out & s.fillna(False))
    return out


def failed_criteria(df: pd.DataFrame, i: int = -1) -> list[str]:
    """Names of the criteria that fail at bar i. For logging/diagnosis."""
    return [k for k, s in criteria(df).items() if not bool(s.fillna(False).iloc[i])]


# ── Criterion 8: cross-sectional relative strength ────────────────────────────

# IBD-style weighted return: most recent quarter counted twice.
_RS_LOOKBACKS = [(63, 2.0), (126, 1.0), (189, 1.0), (252, 1.0)]


def rs_score_series(df: pd.DataFrame) -> pd.Series:
    """
    Weighted trailing return. Lookbacks longer than the available history are
    dropped and the weights renormalised, so a ticker with 8 months of data is
    scored on what it has rather than silently returning NaN.
    """
    close = df["close"].astype(float)
    total = None
    weight_sum = 0.0
    for period, weight in _RS_LOOKBACKS:
        if len(close) <= period:
            continue
        ret = close / close.shift(period) - 1
        total = ret * weight if total is None else total + ret * weight
        weight_sum += weight
    if total is None:
        return pd.Series(np.nan, index=close.index)
    return total / weight_sum


def rs_rank_panel(all_bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Cross-sectional RS percentile (0-100) for every ticker at every date.

    Ranking happens per-date across whatever tickers have a score on that date,
    so it uses no future information. Returns a DataFrame indexed by date with
    one column per ticker.
    """
    scores = {}
    for sym, df in all_bars.items():
        if df is None or len(df) < 70:
            continue
        try:
            scores[sym] = rs_score_series(df)
        except Exception:
            continue
    if not scores:
        return pd.DataFrame()
    panel = pd.DataFrame(scores).sort_index()
    return panel.rank(axis=1, pct=True) * 100


def rs_rank_latest(all_bars: dict[str, pd.DataFrame]) -> dict[str, float]:
    """Latest cross-sectional RS rank per ticker. Convenience for the scanner."""
    panel = rs_rank_panel(all_bars)
    if panel.empty:
        return {}
    return panel.iloc[-1].dropna().to_dict()


# ── Single entry point used by the scanner ────────────────────────────────────

def passes(df: pd.DataFrame, rs_rank: float | None, min_rs: float = 70.0,
           require_rs: bool = True) -> tuple[bool, str]:
    """
    Evaluate the full template at the latest bar.
    Returns (passed, reason). reason is "" on success, else a short tag naming
    the first failure — surfaced in the scan counters so a gate that silently
    rejects the entire universe is visible rather than mysterious.
    """
    if df is None or len(df) < MIN_BARS:
        return False, "insufficient_history"

    fails = failed_criteria(df)
    if fails:
        return False, fails[0]

    if require_rs:
        if rs_rank is None or (isinstance(rs_rank, float) and np.isnan(rs_rank)):
            return False, "rs_unavailable"
        if rs_rank < min_rs:
            return False, "rs_rank"

    return True, ""
