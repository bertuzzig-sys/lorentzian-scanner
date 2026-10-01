# Run 003 — Does the ADX filter matter? Does the weekly-VWAP gate matter?   [pre-registered 2026-10-01, DAILY bars]

Two hypotheses. Both are "does it matter" questions, answered the same way as the IWM question in run 001.
Baseline = run 001 H-A (no IWM, MIN_VOTE 6, all live gates, ADX filter ON, VWAP gate ON, regime threshold 0.0).

## Why
- ADX: the live scanner has the Lorentzian ADX filter ON (since v9.3); the TradingView default is OFF. It is unknown whether it helps.
- VWAP: CLAUDE.md says the edge sits in the VWAP + volume filter stack, but run 001/002 always required close > weekly VWAP, so its
  contribution was never measured on its own. The TradingView chart Gianluca trades has no VWAP gate.

## Variants (everything else identical to the baseline)
- H-1: ADX filter OFF  vs  ON (both with VWAP gate).
- H-2: VWAP gate OFF   vs  ON (both with ADX filter ON).
(The variant with both off is reported for information only.)

## Verdict rule (fixed now)
A change "matters" only if the out-of-sample average return per trade differs by >= 0.2% AND the in-sample difference has the same sign.
Otherwise: "no measurable difference". Report win %, PF, avg %, n for IS and OOS, overall and by market-cap segment.
OOS n < 150 for a variant -> inconclusive.

## Data / split / exits
Same as run 001: 501 S&P 500 names, yfinance daily, IS 2022-10-01..2025-09-30, OOS 2025-10-01..2026-09-29, 8% stop, 10-day hold.
Caveats as before (survivorship, current market cap, flip exit not modelled, yfinance vs live Alpaca IEX).
This is DAILY. It says nothing yet about the 4h signal Gianluca trades.
