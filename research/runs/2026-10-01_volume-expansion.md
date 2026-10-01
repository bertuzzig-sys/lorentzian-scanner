# Run 012 — The common thread: unusual volume + a Lorentzian long signal   [pre-registered 2026-10-01, DAILY]

Gianluca's observation: both examples (TTAN crash-and-rebound, GRAIL quiet-base-then-explosion) share an increase in volume. Middle ground: instead of two narrow
price patterns, test the broad idea once. Does a Lorentzian long signal that appears DURING a volume expansion do better than one that does not, and does the
volume expansion do anything without the signal?

## Definitions (fixed now; daily bars; nothing tuned)
- Volume expansion (VE) on day t: the 10-day average volume >= 1.5x the average of the 60 days before those (days t-70..t-11)  OR  any day in the last 10 days with
  volume >= 3x its prior 20-day average.
- Signal: fresh Lorentzian long flip on day t with the TradingView settings (RSI(9) first, regime -0.1, ADX off, kernel on), vote >= 6, causal one-pass AI Edge port.
- Liquidity: price >= $5, dollar volume >= $5M. Entry next open. Exit: 10% stop / 20-day max hold. Cost 0.15%/side. Universe S&P 1500 (today's list).
- Split IS 2022-10-03..2025-09-30, OOS 2025-10-01..2026-09-29.
- Groups: SIG+VE (signal during volume expansion), SIG-only (signal, no VE), VE-only (random 5% sample, fixed seed, of volume-expansion days without a signal),
  ALL (random 5% of all liquid days, the market drift). Information only: SIG+VE split into "after a crash" (run 010 state), "quiet base" (run 011 state), "other".

## Hypotheses and verdict rules
- H1 (volume adds to the signal): OOS net average of SIG+VE >= SIG-only + 0.5 points AND the IS difference has the same sign; SIG+VE OOS n >= 100.
- H2 (the signal adds to volume): OOS net average of SIG+VE >= VE-only + 0.5 points AND same sign in IS.
- H3 (beats SPY): a 20-slot portfolio (5% per position, same-day ties random, 5 seeds) of SIG+VE trades, net of costs, has OOS total return > SPY's (+16.8% open-to-open)
  AND full-period Sharpe > SPY's (1.34). Reported with max drawdown.
Otherwise "not supported"; n < 100 -> inconclusive.

## Caveats
Survivorship (today's index lists; flatters rebounds and explosions), one OOS year, daily bars (Gianluca trades 4h), no live flip exit, costs are assumptions. Three hypotheses on top of runs
010/011 on related patterns: treat any single success as weak evidence and require it to survive a bear market before any live use.
