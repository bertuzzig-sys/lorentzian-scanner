# 🟢 Lorentzian Scanner

Automated scanner that runs the **Lorentzian Classification** algorithm (by jdehorty) on all S&P500 + NASDAQ100 stocks using 4H candles.  
Sends **Telegram alerts** whenever a fresh green signal flip is detected.

## How it works

1. Fetches 6 months of 4H OHLCV data via `yfinance`  
2. Computes RSI, WaveTrend, CCI, ADX features  
3. Runs K-Nearest Neighbours with Lorentzian distance metric  
4. Detects a **fresh green flip** (signal was not bullish → now bullish)  
5. Sends a Telegram message with ticker + price + volume  

Scan runs **daily at 23:00 UTC** (01:00 Prague) so alerts are ready before European market open.

## Railway deployment

### Environment variables

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_CHAT_ID` | Your personal chat ID |
| `SCAN_TIME_UTC` | Schedule time (default `23:00`) |
| `SCAN_WORKERS` | Parallel threads (default `8`) |

### Get Telegram credentials

1. Message `@BotFather` on Telegram → `/newbot`  
2. Copy the token it gives you → `TELEGRAM_BOT_TOKEN`  
3. Message your new bot anything  
4. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates`  
5. Find `"chat":{"id": XXXXXX}` → that number is `TELEGRAM_CHAT_ID`  

### Deploy steps

1. Fork / push this repo to GitHub  
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub  
3. Select this repo  
4. Add the environment variables above  
5. Railway auto-deploys — done ✅

## Disclaimer

This is a research tool. Not financial advice. Always confirm signals on TradingView with Volume Profile + Anchored VWAP before trading.
