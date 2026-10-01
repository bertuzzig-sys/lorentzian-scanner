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

## 2026-09-30 — Exploratory: F5 4h, TradingView markers vs Python (NOT pre-registered)
- Question: does the Python Lorentzian (walk-forward, chart settings: RSI9/WT/CCI/ADX/RSI9, regime -0.1, ADX 20) reproduce the green long markers on Gianluca's 4h TradingView chart?
- Method: 4h bars from yfinance 60m (09:30 / 13:30 ET). Chart crosshair bar identified as 2026-08-28 13:30 (open matches exactly; H/L/C differ by cents; TV volume 15.79K vs 140K here, so TV uses a smaller feed). Marker dates estimated from pixel positions (+-3-5 bars error).
- Result: chart shows 8 green markers (Jan-Aug 2026); Python produced 5 long flips (21 Apr, 29 Apr, 29 Jun, 4 Aug, 27 Aug). Within 3 bars: 1 of 8. Within ~9 bars: 4 of 8. The 4 markers in Jan-Mar had no Python flip at all.
- Verdict: signals do NOT match on 4h. Cause unknown (feed differences, settings not fully known e.g. kernel/trade-with-kernel options, window length). Too imprecise to tune against.
- Next: exact marker timestamps (TradingView "Export chart data" includes indicator plots) and full indicator settings; then test variants against the exact dates. Do not build the 4h backtest on an unmatched signal.
- Also observed: 4h TradingView raw rate ~8 long markers per ~10 months on one stock (~0.8/month/stock) before any scanner filters.

## 2026-09-30 — Exploratory: AI Edge port (github.com/artificial-intelligence-edge/lorentzian-classification) + F5 4h, ADX filter
- Reviewed repo (MIT, created 2026-06-25, 68 stars; pure Python, no network/subprocess calls, no deps). Cloned to scratchpad only, not vendored. Claims parity with TradingView exports; I re-ran its validate-fixtures: 4 fixtures, 0 mismatches (their own baselines, not independently verified as genuine TV exports).
- It normalises features with a running min/max (Pine-like, causal). advanced_ta (our lib) uses sklearn MinMaxScaler over the whole series.
- advanced_ta vs TradingView export baselines (single full-series run, default settings, last 1500 bars): long signals on the same bar 26/26 (Coinbase BTC 1d) and 28/29 (BTC 1h); raw prediction numbers identical on only 17-19% of bars. So the math is close on long-flip timing.
- F5 4h, same settings on both libraries: advanced_ta walk-forward with ADX filter ON (our scanner's setting) gives the same 5 dates as the AI Edge port with ADX filter ON. With ADX filter OFF (TradingView default) the port gives 8 long signals (chart shows 8), 6/8 within 9 bars of the estimated marker dates, 3/8 within 3 bars.
- Finding: the scanner's ADX filter (ON since v9.3) is the most likely cause of the TradingView mismatch. The chart's Inputs line shows "ADX 20 threshold" but not whether the filter toggle is on. Needs confirmation from the Inputs tab.
- Caveats: marker dates read from a screenshot (+-3-5 bars); TradingView feed differs (volume 15.79K vs 140K); one stock.
- Consequence: all backtests (run 001/002) used ADX filter ON. The TV-chart configuration (ADX off) is untested.
- Follow-up (pre-register first): run 003 = ADX filter on vs off, on daily and on 4h; port gives a causal single pass (no per-bar walk-forward) so 4h runs become cheap.

## 2026-10-01 — Run 003: ADX filter on/off and VWAP gate on/off (daily)
- Hypotheses: H-1 ADX filter OFF vs ON; H-2 VWAP gate OFF vs ON. Pre-registered: research/runs/2026-10-01_adx-and-vwap.md. Code: research/run003.py. Same data/split/exits as run 001, no IWM, MIN_VOTE 6.
- Result (IS / OOS):
  - BASELINE (ADX on, VWAP on): n 1491 / 512 · WR 56.6 / 51.6 · PF 1.47 / 1.27 · avg +0.85 / +0.54
  - H-1 ADX off:                n 3375 / 1132 · WR 54.5 / 51.9 · PF 1.33 / 1.32 · avg +0.64 / +0.69
  - H-2 VWAP off:               n 1549 / 532  · WR 56.4 / 51.3 · PF 1.45 / 1.22 · avg +0.81 / +0.46
- Verdict (rule: OOS avg differs >= 0.2% AND same sign in IS): H-1 no measurable quality difference (IS -0.21, OOS +0.15, opposite signs) BUT ADX off produces ~2.2x as many signals. H-2 no measurable difference; the VWAP gate removes only ~4% of otherwise-passing signals (it is almost redundant with the other gates).
- Correction to the 2026-09-30 entry: ADX on/off is not the main cause of the TradingView mismatch. On CLH 4h (axis-calibrated dates) ADX off/on gave 9/8 signals; 5 of 12 chart labels reproduced within ~1 day either way. TradingView's 4h bars come from a thin feed (CLH 29 Sep 13:30 bar: TV O313.40 H313.40 L309.71 C310.76 vol 5.07K vs consolidated O310.80 H312.65 L309.68 C311.58 vol 131K), which likely explains part of the mismatch. Needs TradingView's own OHLC export to settle.
- Caveats: daily only; survivorship; flip exit not modelled; the ADX-off signals would be capped by the 20-position limit in practice.

## 2026-10-01 — Run 004: portfolio backtest of the v11.3 configuration (descriptive, daily)
- Config: Lorentzian long flip (ADX on, vote >= 6) + live gates (price, dollar vol, volume ratio, +0.5% day, 50-EMA, RSI 40-70); NO IWM, NO VWAP gate; 8% stop, 10-day hold. Code: research/run004.py. Portfolio assumptions fixed in the docstring before running: 5% of equity per position, max 20 open, one per ticker, random order for same-day conflicts (5 seeds), no sector cap, no costs, daily mark-to-market.
- Result OOS (2025-10-01..2026-09-30, 540 signals, 385-392 taken, avg 14 of 20 slots used): strategy +2.3% to +7.5% (median ~6.5%), max drawdown -7.2% to -8.9%, Sharpe 0.27-0.74. SPY buy&hold: +15.3%, max DD -8.9%, Sharpe 1.17.
- Result full period (2022-10..2026-09, 2086 signals, ~1420 taken): strategy +49% to +61% (CAGR 10.5-12.6%), max DD -11.7% to -12.5%, Sharpe 1.00-1.17. SPY: +119% (CAGR 21.7%), max DD -18.8%, Sharpe 1.34.
- Per-trade (all signals, no limits): n 2086, win 55.1%, PF 1.38, avg +0.72%.
- Verdict: positive per-trade edge, but as a portfolio it did NOT beat SPY buy-and-hold in this (bullish) sample; lower drawdown, lower Sharpe. Numbers are optimistic (survivorship, no costs, no flip exit).
- Follow-ups: pre-register portfolio-level tests (ADX off / relaxed EMA-RSI gates fill more slots); model the flip exit; compare against SPY always.

## 2026-10-01 — Exact TradingView settings read from the chart (CLH 4h, Gianluca's layout)
- Method: read the indicator's input values through the TradingView page (read-only; no data export, no changes to the layout).
- Chart symbol is BATS:CLH (Cboe BATS feed, free plan), not the consolidated tape.
- Settings: source close; neighbors 8; max bars back 2000; features RSI 9/1, WT 10/11, CCI 20/1, ADX 20/2, RSI 9/1; volatility filter ON; regime filter ON, threshold -0.1; ADX filter OFF (threshold 20); EMA filter OFF; SMA filter OFF; Trade with Kernel ON; kernel smoothing OFF (lookback 8, weight 8, level 25, lag 2); dynamic exits OFF.
- Differences vs live scanner (daily, advanced_ta): ADX filter ON vs OFF; regime threshold 0.0 vs -0.1; first feature RSI 14 vs RSI 9.
- The earlier CLH 4h comparison ("ADX filter OFF (TV default)", RSI 9 first feature, regime -0.1, kernel filter ON) already used exactly these settings: 9 Python signals vs 12 chart labels, 5/12 within ~1 day. So the remaining mismatch is not the settings; the likely cause is the data feed (BATS bars vs consolidated yfinance bars), which cannot be fixed with yfinance or Alpaca IEX.

## 2026-10-01 — Exploratory: live signal vs history length; data source correction
- Correction: the live scanner downloads yfinance daily bars (365 calendar days); only CLAUDE.md mentioned Alpaca. Earlier statements that live uses the thin Alpaca IEX feed were wrong. Backtest and live share the data source.
- Replay of the 10 logged live signals (17-29 Sep) with the live 365-day window: 8/10 reproduce as fresh long flips (FFIV, A, P, DXCM, MAR, TT, CCL, ZBRA); MMM and BIIB do not.
- Same stocks/dates with 500 or 800 calendar days of history: A and P no longer flip long, FFIV vote 8 -> 4 -> 2. The signal is sensitive to history length.
- Backtest windows (run 001-005) use 400 bars (~1.6y) per signal; live uses ~250 bars. This is a backtest-vs-live gap; to be tested (windows 250 / 400 / 1000) as a pre-registered run.

## 2026-10-01 — Run 005: portfolio-level variants (ADX filter off, EMA/RSI gates off), daily
- Pre-registered: research/runs/2026-10-01_portfolio-variants.md. Code: research/run005.py. Portfolio rules as run 004 (5%/position, max 20, 5 random seeds, no costs).
- OOS (last 12 months), median of 5 seeds [min..max]:
  - BASE (ADX on, EMA+RSI on):  signals 538, taken 390, avg slots 14.0 · total +6.4% [2.5..6.9] · maxDD -7.2% · Sharpe 0.64 · per-trade WR 51.3 PF 1.21 avg +0.45%
  - H-A (ADX off):              signals 1181, taken 517, slots 17.3 · +1.9% [0.3..5.1] · maxDD -9.1% · Sharpe 0.20 · PF 1.32 avg +0.70%
  - H-B (EMA+RSI gates off):    signals 846, taken 455, slots 16.4 · +14.5% [10.4..19.4] · maxDD -6.8% · Sharpe 1.20 · WR 52.8 PF 1.40 avg +0.84%
  - SPY buy&hold: +15.3%, maxDD -8.9%, Sharpe 1.17
- Full period median: BASE +53.4% (CAGR 11.3%, DD -12.1%); H-A +61.8% (12.8%, -13.6%); H-B +66.4% (13.6%, -15.5%); SPY +119% (21.7%, -18.8%).
- Verdict by the pre-registered rule (OOS median >= +2 pts vs BASE, full CAGR > BASE, OOS DD not worse by > 3 pts): H-B PASSES (+8.1 pts OOS, CAGR 13.6 vs 11.3, OOS DD -6.8 vs -7.2). H-A does NOT (OOS +1.9% vs +6.4%).
- Caveats: one OOS year; wide seed spread (H-B 10.4..19.4); full-period DD is worse for H-B (-15.5 vs -12.1); full period still trails SPY; survivorship, no costs, flip exit not modelled, backtest window 400 bars vs live ~250 (run 006 tests this).
- Follow-ups: run 006 (history window) now also evaluates the H-B gate set; out-of-universe check (S&P 400) before any live change.
