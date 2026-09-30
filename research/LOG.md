# Research Log

Append-only. One entry per test, including failures. Template is in `PROTOCOL.md`.


## 2026-09-30 — Run 001: re-validate live stack + drop IWM + hammer
- Hypotheses: H1 live stack has an out-of-sample edge; H-A dropping IWM (RS gate + regime) does not hurt; H-B Lorentzian + hammer (signal bar or bar before) beats H-A.
- Rationale/definitions: research/runs/2026-09-30_revalidate-winrate.md (hammer defined before the run, no tuning).
- Config / code ref: v11.2 (b06d1fd); harness research/run001.py. 501 S&P 500 tickers, yfinance, 8% stop / 10-day hold, no flip exit.
- Split: IS 2022-10-01..2025-09-30 | OOS 2025-10-01..2026-09-29 (fixed before the run)
- Result (IS / OOS):
  - BASE (live, IWM): WR 55.7 / 51.6 · PF 1.47 / 1.25 · avg +0.86 / +0.52 · n 1210 / 440
  - H-A (no IWM):     WR 56.5 / 51.8 · PF 1.47 / 1.27 · avg +0.85 / +0.54 · n 1488 / 514
  - H-B (hammer):     n 7 / 2 (9 total) — too few to evaluate
- Verdict: H1 NOT REFUTED (OOS PF>=1.2, avg>=+0.2%, WR>=50%) but WR 51.6% is under the 52% target and edge shrank vs IS.
  H-A: no measurable difference vs IWM (supported). H-B: inconclusive (hammer + the other gates almost never coincide).
- Caveats: survivorship (today's S&P 500), current not point-in-time cap, yfinance vs live Alpaca IEX, live flip-exit not modelled.
  Parity check: only 4 of 10 live S&P signals since 17 Sep reproduce in the harness (5 harness signals not live), so it models the strategy, not the exact live picks.
- Follow-ups: fix parity (data source / gates); model the flip exit; decide on dropping IWM; redefine hammer test only as a NEW hypothesis.

## 2026-09-30 — Run 002: volume spike + pullback + Lorentzian (replace IWM)
- Hypotheses: H-C (all live gates except IWM + spike/pullback); H-D (also drop EMA50 and RSI 40-70 gates). Definitions: research/runs/2026-09-30_volume-spike-pullback.md (fixed before the run).
- Config / code ref: research/run002.py; same data, split, exits as run 001.
- Result: H-C n = 0 / 0 (IS / OOS). H-D n = 2 / 1. Reference sets: live gates no spike n 1492 / 512 (PF 1.47 / 1.29); relaxed gates no spike n 2420 / 809 (PF 1.47 / 1.47).
- Verdict: INCONCLUSIVE (3 signals in 4 years). Not tested, not refuted.
- Why: 1396 bars pass all gates with a spike+pullback, but the Lorentzian flips long (vote >= 6) on only 3 of them. The signal almost never turns long within 20 days of a spike-and-drop.
- Side finding: relaxing EMA50 + RSI gates (no spike) adds ~60% more signals with OOS PF 1.47 vs 1.29 (n 809 vs 512). Descriptive only, not a pre-registered hypothesis; would need its own run.
- Follow-ups: a longer window (spike within 60 bars) would be a NEW hypothesis, defined before running.
