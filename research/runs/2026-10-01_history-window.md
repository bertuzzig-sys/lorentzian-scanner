# Run 006 — Does the edge depend on how much price history the signal sees?   [pre-registered 2026-10-01, DAILY]

Why: live downloads ~365 calendar days (~250 bars) per stock; the backtests (runs 001-005) feed the Lorentzian up to 400 bars per signal;
TradingView feeds up to 2000. Replaying 10 logged live signals showed the same stock/day can flip with 365d vs 500d vs 800d of history
(advanced_ta scales features over the window it is given). If the edge exists only at one window length, it is fragile and the backtest
has not been measuring what runs live.

## Hypothesis
H: the v11.3 configuration's per-trade quality is similar across history windows of 250, 400 and 1000 bars.
Config otherwise identical to BASE v11.3 (no IWM, no VWAP gate, ADX filter ON, 50-EMA and RSI 40-70 gates, vote >= 6, 8% stop, 10-day hold).

AMENDMENT (written before run 006 was started, after run 005 results): the same pass also evaluates the run-005 H-B gate set (EMA and RSI gates OFF) by tagging,
so every window is reported for BOTH BASE (gates on) and H-B (gates off). The verdict rule below applies to each of the two configurations separately.

## Verdict rule (fixed now)
"Robust" only if, for all three windows, OOS PF >= 1.2 AND OOS avg return >= +0.2%/trade AND the OOS avg return of the three windows
spans <= 0.3 percentage points. Otherwise "window-sensitive". Also report: signals per window, and overlap between windows
(share of (ticker, signal date) pairs appearing in both), and the portfolio result (as run 004) for the 250-bar live-equivalent window.

## Data / split / caveats
Same as run 001. The 1000-bar window is truncated to the history available (about 750-1250 bars before each signal). Survivorship, no costs,
flip exit not modelled. 250 bars is the live-equivalent window.
