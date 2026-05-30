"""
Ticker universe fetchers.
Pulls live lists from Wikipedia so the scanner always uses current constituents.
Falls back to a hardcoded mini-list if Wikipedia is unreachable.
"""

import logging
import pandas as pd

log = logging.getLogger(__name__)

# ── Fallback lists (used if Wikipedia scrape fails) ─────────────────────────
SP500_FALLBACK = [
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO","BRK-B","JPM",
    "LLY","UNH","V","XOM","MA","HD","PG","COST","JNJ","ABBV","BAC","MRK",
    "KO","WMT","CVX","NFLX","CRM","AMD","ADBE","PEP","TMO","ACN","MCD",
    "CSCO","DHR","ABT","LIN","TXN","ORCL","NKE","PM","AMGN","NEE","QCOM",
    "IBM","RTX","GE","HON","SPGI","CAT","UPS","INTU","LOW","GS","AMAT",
    "NOW","AXP","ELV","DE","BKNG","MDLZ","ISRG","ADI","TJX","MMC",
    "VRTX","PLD","SYK","PANW","ETN","C","CB","REGN","LRCX","MO","ZTS",
    "BSX","SO","CI","AON","CME","HCA","ITW","DUK","ICE","PH","APD",
    "WM","MSI","FCX","EOG","SLB","MCO","USB","TGT","NSC","EMR","KLAC",
    "FTNT","SNPS","CDNS","MCHP","PAYX","CTAS","PCAR","ORLY","AZO","ROST",
    "OKLO","PLTR","RKLB","SMR","LEO"
]

NASDAQ100_FALLBACK = [
    "AAPL","MSFT","NVDA","AMZN","META","TSLA","AVGO","COST","GOOGL","GOOG",
    "ADBE","AMD","QCOM","PEP","CSCO","INTC","INTU","CMCSA","NFLX","TXN",
    "HON","AMGN","SBUX","GILD","ISRG","MDLZ","REGN","VRTX","PANW","LRCX",
    "MU","KLAC","SNPS","CDNS","MCHP","FTNT","PAYX","CTAS","ORLY","ABNB",
    "DDOG","CRWD","MRVL","ON","KDP","IDXX","BIIB","SIRI","FAST","DLTR",
]


def get_sp500() -> list[str]:
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        table = pd.read_html(url, attrs={"id": "constituents"})[0]
        tickers = table["Symbol"].str.replace(".", "-", regex=False).tolist()
        log.info("S&P500: fetched %d tickers from Wikipedia.", len(tickers))
        return tickers
    except Exception as exc:
        log.warning("S&P500 Wikipedia fetch failed (%s) — using fallback list.", exc)
        return SP500_FALLBACK


def get_nasdaq100() -> list[str]:
    try:
        url = "https://en.wikipedia.org/wiki/Nasdaq-100"
        tables = pd.read_html(url)
        # Find the table that has a 'Ticker' column
        for t in tables:
            if "Ticker" in t.columns:
                tickers = t["Ticker"].dropna().tolist()
                log.info("NASDAQ100: fetched %d tickers from Wikipedia.", len(tickers))
                return tickers
        raise ValueError("No Ticker column found")
    except Exception as exc:
        log.warning("NASDAQ100 Wikipedia fetch failed (%s) — using fallback list.", exc)
        return NASDAQ100_FALLBACK
