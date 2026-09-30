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
5. **Universe/config alignment check (S&P 500 vs live config).** Walk-forward and `backtest.py` used
   S&P 500 + IWM benchmark with no market-cap ceiling; live has `MAX_MARKET_CAP=300B`, which drops
   ~25 mega caps the backtest included. Confirm the backtest's ticker count/limit and either match
   live to it or measure the difference.
