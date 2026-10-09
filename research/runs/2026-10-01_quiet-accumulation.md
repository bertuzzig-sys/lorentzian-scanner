# Run 011 — "Quiet accumulation, then explosion" (the GRAIL 1h example)   [pre-registered 2026-10-01, DAILY]

Pattern read from Gianluca's GRAIL chart: weeks of a quiet, slowly drifting price while volume builds, a Lorentzian long label inside that base, then a gap-and-run of
+80% on volume ~40x normal. Question: can the quiet, building-volume base be identified IN ADVANCE (before the move), does the Lorentzian long signal inside it help,
and is the average result better than the market's? Selection warning: examples are picked with hindsight; for every GRAIL there are many bases that go nowhere.
This test measures that base rate.

## Definitions (fixed now; daily bars; nothing tuned)
- Volume building: average volume of the last 10 days >= 1.5x the average of the 60 days before those (days t-70..t-11).
- Quiet, slowly rising price: 20-day close-to-close return between 0% and +10%, and the 20-day high-low range of closes <= 15% of the 20-day mean close.
- STATE on day t = both conditions + liquidity (price >= $5, dollar volume >= $5M).
- TRIGGER: STATE and a fresh Lorentzian long flip on day t (TradingView settings: RSI(9) first feature, regime -0.1, ADX off, kernel on; vote >= 6; causal one-pass AI Edge port).
- Entry next open. Exit: 10% stop / 20-day max hold (same primary exit as run 010). Cost 0.15% per side. Universe: S&P 1500 (today's list). Split IS 2022-10-03..2025-09-30, OOS 2025-10-01..2026-09-29.

## Controls
- NULL-A: STATE days without the trigger. NULL-B: a random 5% sample (fixed seed) of ALL liquid stock-days (the unconditional drift of the universe).

## Verdict rules
- EDGE: TRIGGER net OOS n >= 100, average >= +0.5% per trade, PF >= 1.2.
- TRIGGER adds value: OOS average >= NULL-A + 0.5 points and IS difference has the same sign.
- STATE adds value (the volume-building idea itself): NULL-A OOS average >= NULL-B + 0.5 points and IS difference same sign.
- Also report: share of trades that gain >= +20% within the 20 days ("explosion rate"), share that lose >= 10%, and how much of total profit comes from the best 5% of trades.
- Otherwise not supported; OOS n < 100 -> inconclusive.

## Caveats
Survivorship (today's index lists; here it mostly flatters "explosions" because stocks that ran up stay in indexes), daily bars (GRAIL example is 1h), one OOS year,
the +80% GRAIL gap was almost certainly a news event, which a price/volume pattern cannot know in advance.
