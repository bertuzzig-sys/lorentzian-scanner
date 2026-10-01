# Run 005 — Which looser variant fills the portfolio better? (ADX filter off, EMA/RSI gates off)   [pre-registered 2026-10-01, DAILY]

Context: run 004 showed the v11.3 configuration has a positive per-trade edge but, as a 20-slot portfolio, trails SPY buy-and-hold
(OOS +2..8% vs SPY +15%) and uses only ~14 of 20 slots. Runs 002/003 hinted that two filters may cost trades without adding quality.
Judged at PORTFOLIO level (return, drawdown, Sharpe vs SPY), not per trade.

## Variants (all: no IWM, no VWAP gate, vote >= 6, 8% stop, 10-day hold, same data/split/costs-free as run 004)
- BASE (v11.3): Lorentzian ADX filter ON, 50-EMA gate ON, RSI 40-70 gate ON.
- H-A: ADX filter OFF (EMA and RSI gates ON).
- H-B: EMA and RSI gates OFF (ADX filter ON).
- (info only) both off.
Rationale: H-A: TradingView default, run 003 showed 2.2x signals at similar per-trade quality. H-B: run 002 side finding
(809 vs 512 OOS signals, OOS PF 1.47 vs 1.29); these gates may block pullback entries.

## Portfolio rules (same as run 004, fixed): 5% of equity per position, max 20 open, one per ticker, same-day ties random (5 seeds),
## no sector cap, no costs, daily mark-to-market.

## Verdict rule (fixed now)
A variant is "better" only if ALL hold: OOS median total return exceeds BASE by >= 2 percentage points; full-period median CAGR exceeds
BASE; OOS median max drawdown is not worse than BASE by more than 3 points. Otherwise "no clear improvement". Beating SPY is reported
separately, never assumed. Per-trade win %, PF, avg % reported for context.
Caveats: survivorship (today's S&P 500), flip exit not modelled, yfinance data, no costs, one bullish period.
