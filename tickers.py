"""
Ticker universe fetchers.
Russell 2000 + S&P MidCap 400 = ~2400 stocks
$1B-$50B mcap filter applied downstream in scanner.py keeps ~600-800 of these.
"""

import logging
import pandas as pd

log = logging.getLogger(__name__)


# ── Fallback lists if Wikipedia fetch fails ─────────────────────────────────
SP_MIDCAP_400_FALLBACK = [
    "BLDR","FSLR","ENPH","SMCI","DECK","CSL","SAIA","WSM","JBL","KBR",
    "MANH","BWXT","PSTG","FIX","CW","RGA","RNR","EME","MOH","WAL",
    "BURL","SF","UTHR","CHX","XPO","ORI","CASY","RGLD","TPL","EHC",
    "ALSN","UNM","TXRH","WSO","CLF","FLR","OC","WMS","CHRD","ATR",
    "PEN","PRI","X","CACI","CIEN","TPX","BJ","GME","WBS","OLED",
    "NYT","RPM","LECO","MUSA","COKE","SWX","CHE","WEX","TKR","ELS",
    "OLN","KNX","KMX","CFR","OGE","DCI","AMG","CGNX","MIDD","CHDN",
    "RBC","SLM","ALE","PNFP","WCC","NJR","BCO","ZWS","NSP","AFG",
    "MTN","PNW","MORN","WTRG","OZK","FAF","INGR","SON","JEF","AAP",
    "SCI","SF","DAR","HRB","PR","CMC","CADE","DKS","WCC","BRX",
]

RUSSELL_2000_KEY_NAMES = [
    # Speculative growth names that fit our $1B-$50B target
    "OKLO","SMR","VST","TLN","CEG","RKLB","ASTS","PL","JOBY","ARCB",
    "SOFI","UPST","HOOD","AFRM","COIN","RIVN","LCID","FFIE","NKLA",
    "SNOW","NET","DDOG","MDB","ZS","OKTA","ESTC","CRWD","S","PATH",
    "MRNA","BNTX","RXRX","CRSP","NTLA","EDIT","BEAM","VKTX","RKT","ALNY",
    "RDDT","RBLX","ETSY","U","ABNB","PINS","HUBS","DASH","SPOT","FIVN",
    "FSLR","ENPH","BLDR","NEXT","CHPT","BE","STEM","RUN","ARRY","SEDG",
    "WULF","CIFR","MARA","CLSK","IREN","HUT","BTBT","RIOT","HIVE",
    "APP","TTD","ROKU","RBLX","SHOP","MELI","SE","NU","PYPL",
]


def _try_fetch_html(url, table_idx=None, symbol_col="Symbol"):
    try:
        tables = pd.read_html(url)
        # Try to find a table with a Symbol/Ticker column
        for i, t in enumerate(tables):
            for col_name in [symbol_col, "Ticker", "Ticker symbol"]:
                if col_name in t.columns:
                    syms = t[col_name].dropna().astype(str).str.replace(".", "-", regex=False).tolist()
                    if len(syms) > 50:  # sanity check
                        return syms
        return None
    except Exception as e:
        log.warning("Fetch %s failed: %s", url, e)
        return None


def get_sp_midcap_400():
    syms = _try_fetch_html("https://en.wikipedia.org/wiki/List_of_S%26P_400_companies")
    if syms:
        log.info("S&P MidCap 400: fetched %d tickers", len(syms))
        return syms
    log.warning("S&P 400 fallback list used")
    return SP_MIDCAP_400_FALLBACK


def get_russell_2000():
    """
    Russell 2000 has ~2000 holdings — no clean single Wikipedia source.
    We use iShares IWM holdings list as proxy.
    Falls back to curated list of high-volume Russell 2000 names that fit our criteria.
    """
    try:
        # iShares publishes the IWM (Russell 2000 ETF) holdings as CSV
        url = "https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/1467271812596.ajax?fileType=csv&fileName=IWM_holdings&dataType=fund"
        df = pd.read_csv(url, skiprows=9)
        if "Ticker" in df.columns:
            syms = df["Ticker"].dropna().astype(str).tolist()
            # Clean dashes
            syms = [s.replace(".", "-") for s in syms if s and s != "-"]
            log.info("Russell 2000: fetched %d holdings from iShares", len(syms))
            return syms
    except Exception as e:
        log.warning("Russell 2000 iShares fetch failed: %s", e)
    log.warning("Russell 2000 fallback list used (curated names only)")
    return RUSSELL_2000_KEY_NAMES


# Backwards-compatible wrappers so scanner.py doesn't need changes
def get_sp500():
    """Returns S&P MidCap 400 instead — function name kept for compatibility."""
    return get_sp_midcap_400()


def get_nasdaq100():
    """Returns Russell 2000 instead — function name kept for compatibility."""
    return get_russell_2000()
