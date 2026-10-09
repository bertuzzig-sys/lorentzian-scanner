# Run 010 — "Capitulation rebound" (the ServiceTitan 4h example): crash on huge volume, base, then a fresh Lorentzian long signal   [pre-registered 2026-10-01, DAILY]

Pattern read from Gianluca's TTAN chart: a strong run-up, then an earnings-day crash on volume ~8x normal (price fell ~45% in a few weeks), a base near the low,
then a bright-green Lorentzian long label and a rebound. Question: does a Lorentzian long signal inside this state carry an edge, and does it beat entering at
random inside the same state? Also: which stocks are in the setup NOW (screen).

## Definitions (fixed now; daily bars; nothing tuned)
- Crash day s: volume >= 3x the prior 20-day average AND 3-day return (close[s]/close[s-3]-1) <= -12%.
- State on day t (within 90 trading days after s): lowest close since s <= 0.78 x the highest close of the 5 days before s (a >= 22% drawdown); and
  close[t] >= 1.10 x that lowest close (rebound started) and close[t] <= 0.85 x the pre-crash close (not recovered).
- Trigger: a fresh Lorentzian long flip on day t with the chart settings of Gianluca's TradingView (RSI(9) first feature, regime threshold -0.1, ADX filter OFF,
  Trade-with-Kernel ON), vote >= 6, computed in one causal pass over the whole history (AI Edge Python port, validated against TradingView exports).
- Liquidity: price >= $5, dollar volume >= $5M.
- Entry next open. PRIMARY exit: 10% stop / 20-day max hold. (Info only: 8% stop / 10-day hold.)
- Universe: S&P 1500 (today's list, survivorship caveat below). Split IS 2022-10-03..2025-09-30, OOS 2025-10-01..2026-09-29. Cost 0.15% per side.

## Null control (required)
Same state, same liquidity, same exits, but ENTER ON EVERY DAY in the state WITHOUT the Lorentzian trigger.

## Verdict rules
- Edge exists if, net of costs, OOS: n >= 100, average >= +0.5% per trade, PF >= 1.2.
- Lorentzian trigger adds value if its OOS average exceeds the null's by >= 0.5 percentage points AND the IS difference has the same sign.
- Otherwise "not supported"; OOS n < 100 -> inconclusive.

## Caveats (big)
Survivorship: today's index lists contain only survivors. Stocks that crashed and KEPT FALLING are mostly gone from the lists, so rebound results will look better than
reality; the null shares this bias, so the trigger-vs-null comparison is the more trustworthy number. One OOS year. Daily bars (Gianluca trades 4h).
The current-day screen is descriptive: it lists stocks in the state today, it is not a recommendation.
