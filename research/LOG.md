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

## 2026-10-01 — Run 006: history-window sensitivity (250 / 400 / 1000 bars), daily
- Pre-registered: research/runs/2026-10-01_history-window.md (amended before the run to also cover the H-B gate set). Code: research/run006.py.
- Per-trade OOS (PF / avg%): BASE (EMA+RSI gates ON): 250 -> 1.29 / +0.61; 400 -> 1.22 / +0.45; 1000 -> 1.16 / +0.36. H-B (gates OFF): 250 -> 1.35 / +0.78; 400 -> 1.41 / +0.85; 1000 -> 1.34 / +0.73.
- Signal overlap between windows: 53-66% (the same stock/day often signals under one window and not another).
- Portfolio OOS (median of 5 seeds): BASE 250: +9.8% (DD -5.9%, Sharpe 0.91); 400: +5.3% (-8.2%); 1000: +1.9% (-11.2%). H-B 250: +16.9% (DD -6.6%, Sharpe 1.31; range 14.1..24.2); 400: +15.8% (-6.8%); 1000: +9.2% (-11.9%). SPY: +15.3% (DD -8.9%, Sharpe 1.17).
- Verdict (rule: all windows OOS PF >= 1.2, avg >= +0.2%, avg span <= 0.3 pts): BASE = WINDOW-SENSITIVE (PF 1.16 at 1000 bars). H-B = ROBUST (PF 1.34-1.41, avg +0.73..+0.85, span 0.12).
- Live-equivalent window is 250 bars: BASE +9.8% OOS (below SPY), H-B +16.9% OOS (slightly above SPY, lower drawdown). One OOS year; no costs; survivorship; flip exit not modelled.
- Follow-ups: out-of-universe check (S&P 400) and cost model before any live change; decide whether to propose v11.4 = remove the 50-EMA and RSI 40-70 gates.

## 2026-10-01 — Run 007: S&P 400 generalisation and trading costs (daily, 250-bar window)
- Pre-registered: research/runs/2026-10-01_sp400-costs.md (committed before the run). Code: research/run007.py. Costs per side: 0.10% (S&P 500), 0.15% (S&P 400), stress 0.25%.
- Portfolio OOS median total return (gross / base cost / stress cost) vs benchmark:
  - S&P 500 BASE (EMA+RSI on): +9.8 / +5.9 / +0.3 %; H-B (gates off): +16.9 / +11.8 / +4.5 %; SPY +15.3%
  - S&P 400 BASE: +3.6 / -1.0 / -4.0 %; H-B: +11.4 / +5.0 / +1.0 %; IJH +11.3%, SPY +15.3%
- Full period (2022-10..2026-09) at base cost: S&P 500 H-B +58.6% (CAGR 12.2%, maxDD -17.1%, Sharpe 0.98) vs SPY +119% (-18.8%, 1.34); BASE +36.5%. S&P 400 H-B +10.4% (CAGR 2.5%, maxDD -20.3%) vs IJH +68.5% (-24.1%); BASE -5.4%.
- Per-trade OOS at base cost, H-B: S&P 500 PF 1.25 avg +0.57%; S&P 400 PF 1.19 avg +0.50%.
- Verdict: H-C (generalises, S&P 400 base cost) SUPPORTED: H-B beats BASE by +6.0 pts OOS (+5.0% vs -1.0%), better CAGR (2.5% vs -1.4%), smaller OOS drawdown (-6.9% vs -9.0%).
  H-D (survives costs: OOS avg >= +0.2% and PF >= 1.2 on BOTH universes) NOT SUPPORTED by the strict rule: S&P 500 passes (PF 1.25), S&P 400 PF 1.19 (< 1.2), avg +0.50% passes.
- Reading: removing the EMA/RSI gates is the better variant in both universes, but after costs neither universe beats buy-and-hold over the full period; per-trade edge (~0.5%) is of the same order as costs (0.2-0.3% round trip at base, 0.5% at stress). OOS year: S&P 500 H-B net +11.8% vs SPY +15.3%.
- Caveats: cost level is an assumption (large caps with a good broker may be nearer 0.02-0.05% per side); one OOS year; survivorship; flip exit not modelled.

## 2026-10-01 — Run 008: null baseline (entries passing the same gates without the Lorentzian), S&P 500, gross
- Pre-registered: research/runs/2026-10-01_null-baseline.md (committed before the run). Code: research/run008.py. Lorentzian trades = run 007 S&P 500, 250-bar window.
- Per-trade (avg % IS / OOS): BASE gates: NULL +0.58 / +0.41 (n 51518 / 17397) vs LORENTZIAN +0.72 / +0.61 (n 1553 / 508). H-B gates: NULL +0.68 / +0.37 (n 95584 / 33034) vs LORENTZIAN +0.77 / +0.78 (n 2579 / 847).
  Differences (Lorentzian - null): BASE gates IS +0.14, OOS +0.20; H-B gates IS +0.09, OOS +0.41. Win % OOS: null 50.3 / 49.7 vs Lorentzian 51.2 / 51.6; PF OOS null 1.17 / 1.15 vs Lorentzian 1.29 / 1.35.
- Verdict (rule: OOS diff >= 0.2 pts AND same sign in IS): technically ADDS VALUE for both gate sets (BASE gates borderline: OOS diff exactly +0.20), but the effect is small; the in-sample differences are only +0.09..+0.14 pts.
- Portfolio OOS gross (random null picks, 20 slots, 5 seeds): NULL BASE gates +20.7% [12.7..25.3], NULL H-B gates +20.1% [13.1..30.9] vs LORENTZIAN +9.8% / +16.9% and SPY +15.3%. The null portfolio keeps the 20 slots full (near 100% invested) while the Lorentzian produces too few signals (14-16 slots used), so this comparison is dominated by exposure to a rising market; per-trade stats are the like-for-like comparison.
- Reading: most of the per-trade return (+0.4..+0.6%) comes from the filters plus market drift; the Lorentzian adds a small extra (+0.1..+0.4 pts per trade). Costs per trade (0.2-0.3% round trip) are of the same size as that extra.
- Caveats: gross, survivorship, one OOS year, flip exit not modelled, null portfolio spread is wide (12.7..30.9%).

## 2026-10-01 — Run 009: three simple strategies vs SPY with costs (daily, S&P 500 today's list)
- Pre-registered: research/runs/2026-10-01_simple-baselines.md (committed before the run). Code: research/run009.py, addendum research/run009b_null.py. Costs: 0.02%/side SPY, 0.10%/side stocks.
- Results, net, FULL (2022-10-03..2026-09-29) / OOS (last 12 months), vs SPY buy&hold (FULL +123.6%, CAGR 22.3%, DD -19.8%, Sharpe 1.34; OOS +16.8%, Sharpe 1.30):
  - S1 index trend (SPY > 200d): FULL +65.3% (CAGR 13.4%, DD -11.0%, Sharpe 1.13), OOS +13.9% (DD -5.7%, Sharpe 1.18); 87% invested, 19 switches. Label: NEITHER (lower return, lower Sharpe; smaller drawdown).
  - S2 momentum top-20 (12-1 month, monthly): FULL +668.4% (CAGR 66.7%, DD -38.4%, Sharpe 1.49), OOS +91.9%. Label by the pre-registered rule: BEATS SPY, but NOT CREDIBLE: universe look-ahead. Counting names only from their S&P 500 "Date added" gives FULL +232.6% (CAGR 35.1%, DD -29.0%, Sharpe 1.08) and OOS +65.0%; names that left the index are still missing, so the true figure is lower. Null controls: equal-weight all +115%, random 20 +80%. Not a data glitch (clipping daily moves at 15% still +568%).
  - S3 RSI(2) pullback (RSI2<10 above 200d, 20 slots): FULL +32.5% (CAGR 7.3%, DD -19.7%, Sharpe 0.54), OOS -8.6%. Gross FULL +93.5%, OOS +1.3%. Label: NEITHER; costs wipe out most of it (3798 trades).
- Verdict: no simple strategy beat holding SPY credibly. S2 cannot be judged without historical index membership (including removed names).
- Follow-ups: obtain point-in-time membership (e.g. a data vendor) before trusting any cross-sectional result; the same universe look-ahead also affects the Lorentzian runs (smaller effect for per-trade signal tests).

## 2026-10-01 — Run 010: capitulation rebound (TTAN-style), S&P 1500, daily
- Pre-registered: research/runs/2026-10-01_capitulation-rebound.md (committed before the run). Code: research/run010.py. Lorentzian = AI Edge causal port, TradingView settings. Exit 10% stop / 20-day hold, cost 0.15%/side.
- State-days 30,529 (trigger days 920). Net, per trade (avg % / PF / n): TRIGGER IS +2.50 / 1.63 / 689, OOS +2.65 / 1.58 / 231. NULL (state, no trigger) IS +2.71 / 1.67 / 22,109, OOS +1.71 / 1.34 / 7,500.
- Verdict: EDGE rule met on paper (OOS n 231, avg +2.65%, PF 1.58). Trigger adds value: NOT supported (OOS +0.94 vs null, but IS -0.21: opposite signs). The crash-and-rebound STATE itself averages +1.7..+2.7% per 20-day trade; the Lorentzian trigger is not what produces it.
- Caveat (large): survivorship. Crashed stocks that kept falling are gone from today's index lists, so rebounds after crashes are overstated; the null shares the bias, so absolute numbers are not credible, and the trigger-vs-null comparison is the usable one.
- Screen on the last complete bar (2026-09-30), descriptive only: fresh Lorentzian long inside the state: STAA (long 2026-09-29, $22.61, 19% off the low, -22% vs pre-crash). In the state without a fresh signal (watchlist): PLAB, ON, DKS, FN, DAN, ESI, VCYT, AMKR, CBOE, VIAV, BE, BURL.

## 2026-10-01 — Run 012: unusual volume + Lorentzian long (common thread of TTAN and GRAIL), S&P 1500, daily
- Pre-registered: research/runs/2026-10-01_volume-expansion.md (committed before the run). Code: research/run012.py. Exit 10% stop / 20-day hold, cost 0.15%/side, TradingView settings, causal AI Edge port.
- Per trade, net (avg % IS / OOS; n OOS): SIG+VE +1.28 / +0.40 (712); SIG-only +1.02 / +1.56 (5019); VE-only +1.08 / +0.30 (2365); ALL random liquid days +0.84 / +0.83 (16782).
- SIG+VE split, net OOS: after a crash +0.48 (n 31); quiet base -0.61 (n 151, IS -0.05); other +0.68 (n 530).
- Portfolio (20 slots, 5 seeds): SIG+VE OOS +9.0% [3.7..20.3], maxDD -8.7%, full period +32.3% (Sharpe 0.56); all Lorentzian signals OOS +7.4%, full +35.0%; SPY OOS +16.8%, full +123.6% (Sharpe 1.34).
- Verdicts: H1 (volume adds to the signal) NOT SUPPORTED: OOS -1.16 vs SIG-only, IS +0.26 (opposite signs). H2 (signal adds to volume) NOT SUPPORTED: +0.10 OOS. H3 (beats SPY) NOT SUPPORTED: OOS +9.0% < +16.8%, full Sharpe 0.56 < 1.34.
- Reading: signals during volume expansion did WORSE than signals without it in the last year; the GRAIL-style quiet base with a Lorentzian long lost money (-0.61% per trade OOS). The Lorentzian signal alone on the S&P 1500 beat random days (+1.56 vs +0.83 OOS, +1.02 vs +0.84 IS), a small edge, but not versus SPY as a portfolio.
- Caveats: survivorship (today's index lists), one OOS year, daily bars, no live flip exit.

## 2026-10-01 — Run 011: quiet accumulation then explosion (GRAIL-style), S&P 1500, daily
- Pre-registered: research/runs/2026-10-01_quiet-accumulation.md (committed before the run). Code: research/run011.py. Exit 10% stop / 20-day hold, cost 0.15%/side.
- Net, per trade (avg % IS / OOS; n OOS): TRIGGER (quiet, volume building, Lorentzian long) -0.09 / -0.48 (151), PF 0.98 / 0.87; NULL-A (state, no trigger) +0.38 / +0.62 (4428); NULL-B (random 5% of all liquid days) +0.84 / +0.83 (16782).
- Explosion rate (max close >= +20% within 20 days): TRIGGER 5.6% IS / 2.6% OOS; NULL-A 3.0 / 3.5; random days 5.8 / 8.3. Share of trades losing >= 10% (net): TRIGGER 25.7 / 24.5; random 21.8 / 26.7.
- Verdicts: EDGE NOT SUPPORTED (OOS avg -0.48% < +0.5%, PF 0.87). Trigger adds value NOT SUPPORTED (OOS -1.10 vs NULL-A). State adds value NOT SUPPORTED (NULL-A below random days: -0.46 IS, -0.21 OOS).
- Reading: a quiet, slowly rising stock with building volume is LESS likely to explode than a random stock-day, and the Lorentzian long inside it lost money. The GRAIL example is a hindsight pick.
