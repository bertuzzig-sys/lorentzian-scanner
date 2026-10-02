# Lorentzian Scanner — research summary (30 Sep – 1 Oct 2026)

Written for Gianluca. Plain words first, details after. Full numbers: `research/LOG.md`; raw outputs: `research/runs/*_output.txt`.

## 1. Bottom line

1. **The live scanner is not broken, but it has not clearly beaten simply holding SPY.** It has a small positive edge per trade (about +0.5% per trade, 55% wins in the
   practice years, 51% in the last year). As a 20-position portfolio it earned less than SPY over the same days, and trading costs take away most of the edge.
2. **Most of the return comes from the filters and a rising market, not from the Lorentzian.** Entries through the same filters on random days earned +0.4% to +0.6% per
   trade. The Lorentzian adds only about +0.1 to +0.4 points on top (run 008).
3. **IWM and the VWAP gate do nothing measurable.** Removing them is safe (branch ready, not deployed). The 50-day-average and RSI(40–70) gates look like they
   *cost* signals; removing them was better in every test, but still not better than holding SPY after costs.
4. **The signal changes with how much history it sees.** The same stock and day can signal with 365 days of history and not with 500. Live uses about 250 bars; my early
   backtests used 400. Fixed in later runs (run 006 onwards).
5. **Matching TradingView exactly is not possible with our data.** Your chart runs on the small BATS feed (free plan). Settings were read exactly and compared;
   the difference is the data, not the settings. We decided to stop chasing it.
6. **No simple alternative strategy beat SPY credibly** (index trend filter, RSI(2) pullbacks, momentum). The momentum result (+668%) is an artifact of using today's
   S&P 500 list (69 of 503 names joined after the test started); corrected, it is +233%, and it is still too high because removed names are missing.

Not financial advice. All results are backtests: one mostly bullish period, today's index lists (survivorship), no live flip exit, costs are assumptions.

## 2. What changed (and what did not)

| Item | State |
|---|---|
| Live scanner on `main` | **Unchanged** (v11.2). Nothing was deployed or pushed to `main`. |
| Branch `research/protocol` | Research docs, runs 001–009, logging fix (stops the Telegram token appearing in logs), Prospero tracker removed, CLAUDE.md updated, TradingView Pine script. **Not merged.** |
| Branch `feature/remove-iwm-vwap` | v11.3: IWM regime/RS gate and weekly-VWAP gate removed, fixed vote 6. Stacked on the branch above. **Not merged.** Replay check: 5 of 7 past live signals reproduced on yfinance data. |
| Telegram token | Rotated by you on 1 Oct; scanner restarted and the new startup message arrived. |
| Live data source | yfinance daily bars (365 calendar days). CLAUDE.md used to say Alpaca; corrected. |
| Live market-cap band | From Railway: $10B – $5,000B (code default is $800M – $300B). Names under $10B are skipped. |
| TradingView | Read-only look at your indicator settings; no layout changed. Reminder task switched off. |

## 3. What each run found (daily bars, S&P 500 unless stated; OOS = last 12 months, held out)

| Run | Question | Answer |
|---|---|---|
| 001 | Does the signal work out of sample? Does IWM matter? | Yes, weakly: OOS PF 1.25, +0.52%/trade. Removing IWM: same (PF 1.27, +0.54%). |
| 002 | Volume spike, pullback, then Lorentzian signal | Inconclusive: only 3 signals in 4 years. The signal almost never turns long right after a spike and drop. |
| 003 | Does ADX filter / VWAP gate matter? | VWAP gate: no (it removes ~4% of signals). ADX off: 2.2x more signals, similar quality. |
| 004 | As a 20-slot portfolio vs SPY | Last year +2% to +8% vs SPY +15%; 4 years +49% to +61% vs +119%. Lower drawdown (−12% vs −19%). |
| 005 | Looser variants as a portfolio | Dropping the 50-day-average and RSI gates: last year +14.5% (vs +6.4%), smaller drop. ADX off: worse. |
| 006 | Does it depend on history length? | Current setup: yes (window-sensitive). Without the two gates: robust. At the live 250 bars: +9.8% vs +16.9%. |
| 007 | Mid-caps (S&P 400) and trading costs | Without the two gates is better on mid-caps too, but after costs (0.10–0.15%/side) neither beats holding. S&P 500 net last year +11.8% vs SPY +15.3%; 4 years +59% vs +119%. S&P 400: +10% vs index fund +69%. |
| 008 | Does the Lorentzian beat random entries through the same filters? | Barely: +0.1 to +0.4 points per trade. A fully invested random-pick portfolio made +20% in the last year. Exposure matters more than the signal. |
| 009 | Three simple strategies vs SPY | Index trend filter: +65% over 4 years (smaller drawdown, lower return). RSI(2) pullbacks: +33%. Momentum: not trustworthy (see above). None beat SPY credibly. |

Other findings: the live scanner's 365-day window reproduces 8 of the 10 logged live signals (MMM and BIIB do not); only 53–66% of signals are shared between history lengths;
the TradingView chart uses ADX filter OFF, regime threshold −0.1, RSI(9) as first feature, Trade-with-Kernel ON, feed BATS.

## 4. Decisions that are yours

1. **Merge the pull requests?** `research/protocol` is low risk and fixes the token leak in logs (merge first). `feature/remove-iwm-vwap` removes two gates that tested as neutral.
2. **Drop the 50-day-average and RSI gates (v11.4)?** Better than the current setup in all tests, but not better than holding SPY after costs. I did not propose deploying it.
3. **Keep the $10B market-cap floor?** The backtests included the ~15 smaller S&P 500 names; there were too few trades to judge them.
4. **What to do with the scanner overall.** Options: keep it as an idea generator, stop, or redirect the effort.
5. **Optional next projects:** (a) a separate FX/Bitcoin session-effects project with costs built in from day one; (b) a forward test (no real money) of the TradingAgents AI framework as a second opinion
   on scanner signals — needs your own AI provider key in a local file, about 2–3 months for 100 signals; (c) point-in-time index membership data (including removed companies), without which cross-sectional
   tests like momentum cannot be trusted.

## 5. What I could not do or verify

- Reproduce TradingView's signals (data feed). No paid export was used.
- Model the live "signal flip" exit (about half of live exits). It needs a re-run of the signal during each hold.
- Test periods other than 2022–2026, or any bear market that is not in that window.
- Check real trading costs; the cost levels (0.10–0.25% per side) are my assumptions.
- Judge the AI framework (TradingAgents): I only read its README and metadata.

## 6. Where things are

- `research/PROTOCOL.md` rules, `research/BACKLOG.md` open ideas, `research/LOG.md` every test with numbers, `research/runs/` pre-registrations (written before each run) and outputs.
- Harness scripts: `research/run001.py` … `run009b_null.py`, `research/f5_4h_check.py`, `research/tv_export/` (Pine script).
- To re-run: create a Python venv with `advanced-ta`, `yfinance`, `pandas`, `numpy`, `lxml`, `html5lib`, `beautifulsoup4`, `requests`, `openpyxl`; set `SSL_CERT_FILE` to certifi's bundle; run e.g.
  `python research/run007.py --universe sp500 --workers 4 --out DIR` (max 4 workers on this Mac). Raw trade files live only in the temporary scratch folder and are not kept; the outputs and numbers are in `research/runs/`.


## Update 2 Oct 2026 (runs 010–013; branch `research/capitulation-rebound`)

- **TTAN-style crash and rebound (run 010):** the setup itself looks profitable but is inflated by survivorship; the Lorentzian buy adds no consistent value.
- **GRAIL-style quiet base with building volume (run 011):** not supported. A quiet base is less likely to explode than a random day; the Lorentzian buy inside it lost money (−0.48% per trade last year).
- **Unusual volume as a filter (run 012):** made Lorentzian signals worse (+0.40% vs +1.56% per trade last year). Portfolio +9.0% vs SPY +16.8% last year.
- **Bear markets 2005–2026 (run 013):** the scanner lost money in 2008 (−19.5%) and 2020 (−8.9%) and 2022 (−13.3%), less than SPY, mostly because it is not always invested. Over 21 years it compounded +43% vs SPY +842% (survivors-only data, which flatters it). The version without the EMA/RSI gates (v11.4 idea) was worse over the long run (+21%). The 2022–2026 numbers were a favourable window.
- **Bottom line is stronger:** nothing tested beats holding SPY; the long-run per-trade edge after costs is about +0.2% to +0.3%.
- **Data note:** FMP free plan refused index membership history, delisted prices and 4-hour bars; the free long daily history adds nothing over yfinance.
