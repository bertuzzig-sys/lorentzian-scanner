# Run 013 — Does the scanner survive bear markets? (2005–2026)   [pre-registered 2026-10-01, DAILY]

All earlier tests cover 2022–2026, a mostly rising market. Question: how does the v11.3 scanner (BASE) and the candidate without the 50-EMA/RSI gates (H-B) behave in the 2008 crash,
the 2020 crash and the 2022 bear market, with the configuration frozen (nothing tuned)?

## Setup (fixed now)
- Live-equivalent signal: Lorentzian fed the trailing 250 bars (advanced_ta walk-forward), ADX filter ON, vote >= 6, no IWM, no VWAP gate. BASE = 50-EMA and RSI 40-70 gates ON; H-B = OFF.
  Exit 8% stop / 10-day hold, entry next open, cost 0.10% per side. Portfolio: 20 slots, 5% per position, random same-day ties (3 seeds), daily mark to market.
- Universe: a fixed half of today's S&P 500 list (every second ticker, alphabetical) to keep the run time practical. Signals from 2005-01-03 to 2026-09-29. Data: yfinance.
- Bear windows (SPY peak to trough, fixed now): 2007-10-09..2009-03-09; 2020-02-19..2020-03-23; 2022-01-03..2022-10-12. Benchmark: SPY buy and hold.

## Verdict rule (fixed now), per variant and per bear window
SURVIVES the window if (a) the portfolio return in the window is higher than SPY's return in the same window AND (b) the portfolio's maximum drawdown in the window is
smaller than SPY's. Overall: robust only if it survives all three windows. Also report per-trade net average and PF by calendar year and for 2005-2026, and calendar-year
returns vs SPY.

## Caveats (large)
Survivorship: today's S&P 500 list has none of the companies that failed or were removed, which flatters ALL years and especially 2008-2009 (many financials are missing).
So a pass here is weak evidence; a fail is strong evidence. Half the universe. No live flip exit. Costs are assumptions.
