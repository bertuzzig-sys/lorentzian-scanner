# Research Protocol

Rules for every research run (manual or automated). Goal: evidence-based changes, not curve-fitting.

## Rules

1. **Scope.** Test at most 1–3 hypotheses per run. Each hypothesis gets a written rationale
   *before* any code runs (what mechanism, what result would confirm it, what would kill it).
   No blind parameter sweeps.
2. **Data split.** Tune only on older data. Validate on a held-out recent period using
   `walk_forward.py` (per-bar recompute on trailing data only). Fix the split before looking
   at results; do not move it afterwards.
3. **Log everything.** Every test, including failures and nulls, is appended to `research/LOG.md`
   (date, hypothesis, rationale, config, split, result, verdict).
4. **Report.** For each test report in-sample vs out-of-sample:
   - win rate
   - profit factor
   - avg return per trade
   - broken down by market-cap segment (and trade count per cell)
5. **Hands off live.** Never push to `main`. Never change live config (Railway env vars,
   `USE_*` flags, universe, thresholds). Output of a run = a written report + a pull request
   for review. Gianluca decides what ships.

## Report checklist

- Hypothesis + rationale (as written before the run)
- Train / validation date ranges and universe
- In-sample vs out-of-sample table (win %, PF, avg %, n) by market-cap segment
- Caveats: sample size, look-ahead risks, IEX volume (~3% sample), regime dependence
- Verdict: supported / not supported / inconclusive. Inconclusive is a valid answer.
- Recommendation (if any) as a PR, not as a live change

## Log entry template (`research/LOG.md`)

```
## YYYY-MM-DD — <short title>
- Hypothesis:
- Rationale:
- Config / code ref (commit):
- Split: train <range> | validate <range>
- Result (IS / OOS): WR x% / y% · PF x / y · avg x% / y% · n x / y
- Verdict:
- Notes / follow-ups:
```
