# Run 002 — Volume spike, pullback, then Lorentzian signal (replaces IWM)   [pre-registered, approved 2026-09-30]

Two hypotheses (limit is 1-3). Definitions are fixed here BEFORE the run. No tuning afterwards.

## Idea (Gianluca)
A huge volume spike, then a decline, then the Lorentzian long signal says when to trade back in.
No IWM (no RS gate, no regime; MIN_VOTE fixed at 6, as in run 001 H-A).

## Definition
- Spike day s (within the 20 bars before the signal bar t): volume[s] >= 3 x its prior 20-day average volume.
- Pullback: close[t] <= 0.95 x close[s].
- Trigger: fresh Lorentzian long flip on bar t, vote >= 6 (walk-forward, trailing data only).
- Exits: 8% stop, 10-day hold, entry next open (same as run 001). Flip exit not modelled.

## Hypotheses
- H-C: keep ALL live gates (price, dollar volume, volume ratio, +0.5% day, above VWAP, above 50-day EMA, RSI 40-70)
  except IWM, and add spike+pullback. Question: is the spike subset better than the same-gate signals without it?
- H-D: same, but ALSO drop the 50-day EMA and RSI 40-70 gates.
  Rationale: a pullback after a spike naturally puts price under the 50-day EMA and RSI under 40, so those
  two gates contradict the setup. Question: does spike+pullback with those gates removed beat the same relaxed
  set without the spike condition?
  (Only these two gates are removed together; nothing else is varied.)

## Success / failure (fixed now)
Supported only if the spike subset, out-of-sample: PF >= 1.2, avg >= +0.2%/trade, n >= 100, AND avg return at least
+0.2%/trade better than its reference set (H-C ref = run-001 H-A gates; H-D ref = relaxed gates without spike)
in BOTH in-sample and out-of-sample. OOS n < 100 -> inconclusive. Anything else -> not supported.

## Split, data, caveats
Same as run 001: 501 S&P 500 names, IS 2022-10-01..2025-09-30, OOS 2025-10-01..2026-09-29, yfinance (full-market volume).
Caveats: survivorship, current market cap, live Alpaca IEX sees ~3% of volume so live spike detection may differ;
spike days are often earnings days (an earnings gap is not the same as a panic spike) - report, do not filter.
