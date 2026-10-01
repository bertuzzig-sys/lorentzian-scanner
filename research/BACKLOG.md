# Research Backlog

Pick 1–3 items per run. Each needs a written rationale first (see `PROTOCOL.md`).

1. **Run `event_study.py` on real data.** Scaffold is built and self-tested only.
   Hypothesis: KNN divergence vs TradingView -> d+1 overnight gap-and-fade.
2. **Fix `MIN_MARKET_CAP` and re-test the Minervini gate.** Current config misconfigured
   (PF 1.40 large caps vs 0.90 small caps; IWM benchmark). Gate stays disabled
   (`USE_MINERVINI=false`) until re-tested.
3. **[DONE run 001 — see LOG.md; follow-up: parity + flip exit] Re-validate the ~55% win rate post-KNN rewrite.** The figure predates the rewrite.
   Use `walk_forward.py`; report by market-cap segment.
4. **Test VWAP + volume filter variations.** The filter stack is where the edge appears to be
   (raw Lorentzian ≈ random). Note IEX volume is a ~3% sample.
5. **Universe/config alignment check (S&P 500 vs live config).** Correction 2026-10-01 from the live startup message: Railway overrides the cap band to
   $10B-$5,000B (code default is $800M-$300B), so mega caps ARE scanned; names under $10B (about 15 S&P 500 names, e.g. NCLH, MOS, AOS) are excluded,
   while the backtests included them (OOS n ~12, negative PF, too few to judge). Watchlist names CRDO, RIOT, ARWR are not in the S&P 500 and are not scanned.
   Decide whether to match the backtest (drop the $10B floor) or keep it.
6. **FINRA daily short-sale volume ratio as a filter (daily bars only).** Free files at
   cdn.finra.org/equity/regsho/daily/CNMSshvolYYYYMMDD.txt. Noisy (mostly market-maker hedging); needs ~2 years of
   files and a definition fixed before looking. Not usable on 4h bars. Not now: TRACE (bonds only), ATS weekly
   dark-pool data (weeks of delay), paid real-time block prints.
7. **4h rebuild.** Live scanner and all runs so far are DAILY; Gianluca trades the 4h TradingView signal.
   Blocked on matching TradingView first (see LOG 2026-09-30 F5 check). Then port filters/exits to 4h (defined first),
   re-run IS/OOS, then re-test the volume-spike idea on 4h.
