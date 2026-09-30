# Run 001 — Re-validate the ~55% win rate (post-KNN rewrite)   [DRAFT, not yet run]

Backlog item 3. One hypothesis. Written before any code runs, per PROTOCOL.md.

## Hypothesis
H1: the current live signal stack (v11.2: Lorentzian/KNN + VWAP + volume + RS-vs-IWM gates, 8% stop,
10-day hold, MIN_VOTE 6 bull / 8 bear), computed walk-forward with no look-ahead on the S&P 500,
has a positive edge out-of-sample: win rate >= 52%, PF >= 1.2, expectancy >= +0.2%/trade.

## Rationale
- CLAUDE.md's ~55% WR predates the KNN rewrite; nothing since has re-measured it.
- Live sheet cannot answer it: 10 S&P 500 signals since 17 Sep, 1 closed. Earlier live periods used
  other universes/configs and were negative (WR 32-41%, PF 0.59-0.76), but that is a different system.
- Raw Lorentzian is ~random (49-54% WR); any edge must come from the filter stack, so the test is on
  the full live stack, not the raw signal.

## What would refute H1 (fixed now)
Out-of-sample (held-out year): PF < 1.2 OR expectancy < +0.2% OR WR < 50%. Then the edge is not
supported; stop, do not add a filter and retest (same rule as walk_forward.py's pre-registered bar).
"Inconclusive" if OOS n < 150.

## Design
- Config: frozen at v11.2 (commit b06d1fd). NOTHING is tuned in this run, so IS vs OOS is a stability
  check, not a fit/validate loop.
- Data: 4 years of daily bars, S&P 500 (all ~500 names, not the default --limit 200 sample).
- Split (fixed today): IS = first 3 years, OOS = last 12 months (2025-10-01 -> 2026-09-30).
- Report: IS vs OOS win %, PF, avg %, n — overall, by regime (IWM bull/bear), and by market-cap
  segment (>200B, 50-200B, 10-50B, <10B), with n per cell.

## Known weaknesses (report them, don't hide them)
1. Survivorship: today's S&P 500 list applied to the past inflates results. Direction: optimistic.
2. Market cap is current cap, not point-in-time. Segments are approximate.
3. Data source: backtest uses yfinance; live uses Alpaca IEX (~3% volume sample, 100K vol filter vs
   $5M dollar-volume in the harness). Gate parity between harness and scanner_b.py is unverified.
4. One OOS year, mostly one regime; low signal frequency may leave segments too thin.
5. Live MAX_MARKET_CAP=300B excludes mega caps the harness includes (backlog item 5). The >200B
   segment result shows how much that matters.

## Work needed (goes in the PR, no live changes)
1. walk_forward.py: add --start/--split-date, IS/OOS labelling, market-cap segment column, per-segment
   tables (currently: no split, no segments, default 200-ticker sample).
2. Parity check: run the harness over the last few weeks and confirm it reproduces the live signals in
   the Signals sheet (e.g. CCL, ZBRA, TT, MAR on the dates logged). If it doesn't, fix or report before
   trusting any number.
3. Run (local, 4 workers max), append result to LOG.md, open PR with report.

## Open decisions for Gianluca
- The old bar says n > 500. One OOS year may not reach that. Keep n>500 on IS+OOS combined and
  n >= 150 for OOS alone?
- OK with 3y IS / 1y OOS, or prefer 2y / 1y?
