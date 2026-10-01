# Run 008 — Does the Lorentzian signal add anything beyond the filters and market drift?   [pre-registered 2026-10-01, DAILY]

Question: every result so far compared the scanner with SPY, never with a NULL baseline. Over 2022-2026 the S&P 500 drifted up about 0.8% per
10 trading days, about the size of the scanner's per-trade average (+0.5..0.8%). If entries that pass the same filters but ignore the Lorentzian
earn the same, the Lorentzian adds nothing.

## Test (fixed now)
- Same S&P 500 universe, data, split, exits (8% stop, 10-day hold, entry next open) and gates as run 007 (price, $ volume, volume ratio, +0.5% day).
- NULL entries: every bar that passes those gates, WITHOUT the Lorentzian (and a second null that also requires the 50-EMA and RSI 40-70 gates).
- Compare per-trade gross results (no costs) with the Lorentzian signals from run 007 (250-bar window), for the matching gate set:
  BASE-null vs BASE (EMA+RSI on) and H-B-null vs H-B (EMA+RSI off).
- Portfolio check: the same 20-slot, 5%-per-position simulation with NULL entries chosen at random (5 seeds), gross, vs the Lorentzian portfolio and SPY.

## Verdict rule
The Lorentzian "adds value" only if its OOS average return per trade exceeds the matching NULL by >= 0.2 percentage points AND the IS difference
has the same sign. Otherwise: "no measurable value added". Report win %, PF, avg % for both, IS and OOS.
Caveats: survivorship, gross (no costs), flip exit not modelled; NULL has far more trades (so it is a population average, not a lucky draw).
