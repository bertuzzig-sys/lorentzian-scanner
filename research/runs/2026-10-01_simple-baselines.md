# Run 009 — Three simple, textbook strategies vs holding SPY (with costs)   [pre-registered 2026-10-01, DAILY]

Why: run 008 showed most of the scanner's return comes from the filters and market drift, and costs are the size of its extra edge. Before more work on
the Lorentzian, test three well-known, low-effort ideas the same careful way. Parameters are textbook defaults and are NOT tuned.

## Strategies (all long-only; signal from the close, executed at the NEXT OPEN; daily open-to-open returns)
- S1 Index trend filter: hold SPY while SPY's close is above its 200-day average, otherwise cash (0% return).
- S2 Momentum: at each month-end rank S&P 500 stocks (price >= $5, $ volume >= $5M) by 12-1 month return (close 21 days ago / close 252 days ago - 1);
  hold the top 20 equal-weight (5% each) until the next month-end; rebalance at the next open.
- S3 Pullback in uptrends (Connors-style RSI(2)): buy at next open when close > 200-day average AND RSI(2) (Wilder) < 10; exit at the next open after
  RSI(2) closes above 70, or after 10 trading days, or at an 8% stop (stop fill: open if gapped through, else the stop price). 20 slots, 5% each, one per ticker,
  random order for same-day candidates (5 seeds), price >= $5 and $ volume >= $5M.
- Reference: SPY buy-and-hold (open-to-open). Scanner H-B (run 007, S&P 500, base cost): OOS +11.8%, full period +58.6%, as a comparison line only.

## Setup (fixed now)
S&P 500 (today's list), yfinance daily, IS 2022-10-03..2025-09-30, OOS 2025-10-01..2026-09-30 (last complete bar). Costs per side: 0.02% for SPY (S1),
0.10% for individual stocks (S2 on traded notional, S3 per trade); gross also shown. No taxes, no financing, cash earns 0.

## Verdict labels (fixed now), net of costs, per strategy
- BEATS SPY: full-period CAGR > SPY's AND OOS total return > SPY's.
- BETTER RISK-ADJUSTED: full-period Sharpe > SPY's (even if the return is lower).
- NEITHER: otherwise.
Also report max drawdown, share of time invested and number of trades/rebalances.

## Caveats
Survivorship (today's S&P 500 list; hurts S2/S3 realism), one mostly bullish period, costs are assumptions, S2 holds weights fixed within the month (no drift),
S1 has very few trades (a handful of switches), so its result is mostly about the 2022 and 2025 dips.
