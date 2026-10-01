# Lorentzian Scanner — project notes for Claude
(Move this file into the cloned repo as CLAUDE.md)

## What this is
Python implementation of jdehorty's Lorentzian Classification, scanning the S&P 500 (~503 tickers; universe switched from
mid/small caps on 2026-09-17, commit 09e9434) on daily candles. Signals via Telegram, logged to Google Sheets.
Goal: a reliable, evidence-based signal system — NOT a TradingView mirror.

## Infrastructure
- GitHub: bertuzzig-sys/lorentzian-scanner. Railway service "balanced-ambition" (US West, UTC-7; 9am Railway = 11am Prague).
- Data: the scanner code downloads yfinance daily bars (consolidated tape, 365 calendar days ≈ 250 bars; checked 2026-10-01 — no Alpaca
  code in the repo; ALPACA_* env vars exist on Railway but are unused). Backtests also use yfinance, so they share the live data source.
- Google Sheet "Lorenzian": keep the Signals tab at position one so CSV export gets current data.
- Locally: max 4 parallel workers (macOS file-handle limit).

## Open workstreams
1. Core scanner: live. KNN directional divergence vs TradingView unresolved (e.g. AAP). ~55% win rate predates KNN rewrite — re-validate.
2. Minervini gate (minervini.py, in scanner_b.py + backtest.py): look-ahead clean, disabled (USE_MINERVINI=false).
   Blocked on MIN_MARKET_CAP misconfig (PF 1.40 large caps vs 0.90 small caps; IWM benchmark). Fix config before enabling.
3. event_study.py: scaffold built and self-tested, not yet run on real data. Hypothesis: KNN divergence vs TV -> d+1 overnight gap-and-fade.

## Validated learnings
- Raw Lorentzian signal ≈ random (49–54% WR). Daily S&P 500 walk-forward (research/LOG.md runs 001–004): per-trade edge is small but positive
  (OOS PF ~1.25, +0.5%/trade, 8% stop / 10-day hold); as a 20-slot portfolio it trailed SPY buy-and-hold (OOS +2–8% vs +15%).
- IWM regime/RS gate and the weekly-VWAP gate showed no measurable effect (runs 001/003); removed in v11.3 (branch feature/remove-iwm-vwap).
- The signal depends on how much history it sees (advanced_ta scales features over the window): same stock/day can flip with 365d vs 500d.
- TradingView chart settings (read 2026-10-01): ADX filter OFF, regime -0.1, RSI9 first feature, Trade with Kernel ON, feed BATS (thin). Exact
  TradingView matching is not achievable with our data; the scanner is judged on its own backtest and live results.
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
