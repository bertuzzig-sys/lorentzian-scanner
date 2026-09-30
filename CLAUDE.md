# Lorentzian Scanner — project notes for Claude
(Move this file into the cloned repo as CLAUDE.md)

## What this is
Python implementation of jdehorty's Lorentzian Classification, scanning ~596 US mid-cap / tech-adjacent stocks
(Russell 2000 + S&P MidCap 400 + watchlist) on daily candles. Signals via Telegram, logged to Google Sheets.
Goal: a reliable, evidence-based signal system — NOT a TradingView mirror.

## Infrastructure
- GitHub: bertuzzig-sys/lorentzian-scanner. Railway service "balanced-ambition" (US West, UTC-7; 9am Railway = 11am Prague).
- Data: Alpaca IEX daily bars (~3y). yfinance was dropped (rate-limited on Railway IPs).
- Google Sheet "Lorenzian": keep the Signals tab at position one so CSV export gets current data.
- Locally: max 4 parallel workers (macOS file-handle limit).

## Open workstreams
1. Core scanner: live. KNN directional divergence vs TradingView unresolved (e.g. AAP). ~55% win rate predates KNN rewrite — re-validate.
2. Minervini gate (minervini.py, in scanner_b.py + backtest.py): look-ahead clean, disabled (USE_MINERVINI=false).
   Blocked on MIN_MARKET_CAP misconfig (PF 1.40 large caps vs 0.90 small caps; IWM benchmark). Fix config before enabling.
3. event_study.py: scaffold built and self-tested, not yet run on real data. Hypothesis: KNN divergence vs TV -> d+1 overnight gap-and-fade.

## Validated learnings
- Raw Lorentzian signal ≈ random (49–54% WR); edge is in the VWAP + volume filter stack (~55% WR, +2.6% avg / 10d).
- KNN vote ties hold previous signal (nz(signal[1])), don't reset to 0.
- Early Signal Flip filter: reject flips within 4 bars of previous flip.
- OBV rejected. IEX volume is ~3% sample -> volume filter 100K, not 1M.
- Universe config must match the validated universe.
- Excluded sectors: oil/gas, defense, weapons, drones (29 tickers hardcoded).

## How Gianluca works
- Short, direct prompts; concise, practical answers. Works alone.
- Evidence first: backtests before deployment, synthetic validation before real data. Stops tuning once decided.
- Benchmarks: win rate, profit factor, avg return per trade, by market-cap segment.
- Don't overpromise. Flag uncertainty, failure conditions and caveats before writing code.
- Use Railway CLI for logs; fine-grained repo-scoped GitHub tokens only.
- Research runs follow `research/PROTOCOL.md` (max 1–3 hypotheses, held-out validation, log in `research/LOG.md`, never push to main or change live config; output a report + PR). Backlog: `research/BACKLOG.md`.
