"""
Ticker universe: S&P MidCap 400 + full Russell 2000
mcap filter applied in scanner.py
"""

import logging
import ssl
import urllib.request
import pandas as pd

log = logging.getLogger(__name__)


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
    "SCI","DAR","HRB","PR","CMC","CADE","DKS","BRX","FN","WTS",
    "LSCC","SAIC","RHI","COLM","CHH","HXL","RRC","KEX","JLL","BLD",
    "AGCO","HALO","NOV","MTZ","CROX","PII","CC","SLGN","R","FYBR",
    "ALV","BERY","HOG","KRC","SR","WH","AYI","NVT","EWBC","TXRH",
]

RUSSELL_2000_FALLBACK = [
    "OKLO","SMR","VST","TLN","CEG","NNE","UEC","UUUU","DNN","CCJ",
    "RKLB","ASTS","PL","JOBY","ARCB","RDW","BBAI","KTOS","AVAV",
    "SOFI","UPST","HOOD","AFRM","COIN","RIVN","LCID","NU","SE",
    "SNOW","NET","DDOG","MDB","ZS","OKTA","ESTC","CRWD","S","PATH",
    "DOCN","FROG","SUMO","CFLT","GTLB","NCNO","BILL",
    "MRNA","BNTX","RXRX","CRSP","NTLA","EDIT","BEAM","VKTX","ALNY",
    "MDGL","KRYS","ITCI","INSM","REPL","SRPT",
    "RDDT","RBLX","ETSY","U","ABNB","PINS","HUBS","DASH","SPOT","FIVN",
    "BMBL","AS","CART","WBD",
    "NEXT","CHPT","BE","STEM","RUN","ARRY","SEDG","PLUG","FCEL",
    "NIO","XPEV","LI","BLNK","EVGO",
    "WULF","CIFR","MARA","CLSK","IREN","HUT","BTBT","RIOT","HIVE","BITF",
    "APP","TTD","ROKU","SHOP","MELI","PYPL","SQ",
    "DXCM","ALGN","VEEV","WST","RMD","TFX","CRL","BIO",
    "ZETA","NBIS","TE","DARE","QS","SERV","CRDO","AUR","NVTS","RGTI",
    "FLNC","ON","TER","NXT","CYTK",
]


def _fetch_wikipedia_table(url, name="table"):
    """Fetch a Wikipedia table, falling back gracefully."""
    try:
        tables = pd.read_html(url)
        for t in tables:
            for col in ["Symbol", "Ticker", "Ticker symbol"]:
                if col in t.columns:
                    syms = t[col].dropna().astype(str).str.replace(".", "-", regex=False).tolist()
                    if len(syms) > 50:
                        return syms
    except Exception as e:
        log.warning("%s Wikipedia fetch failed: %s", name, e)
    return None


def get_sp_midcap_400():
    syms = _fetch_wikipedia_table("https://en.wikipedia.org/wiki/List_of_S%26P_400_companies", "S&P 400")
    if syms:
        log.info("S&P MidCap 400: fetched %d tickers", len(syms))
        return syms
    log.warning("S&P MidCap 400 fallback list used (%d tickers)", len(SP_MIDCAP_400_FALLBACK))
    return SP_MIDCAP_400_FALLBACK


def get_russell_2000():
    """Russell 2000 — try iShares CSV (full ~2000 names), fall back to curated list."""
    try:
        ctx = ssl.create_default_context()
        url = "https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/1467271812596.ajax?fileType=csv&fileName=IWM_holdings&dataType=fund"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            data = resp.read().decode("utf-8", errors="ignore")
        from io import StringIO
        df = pd.read_csv(StringIO(data), skiprows=9)
        if "Ticker" in df.columns:
            syms = df["Ticker"].dropna().astype(str).tolist()
            syms = [s.replace(".", "-") for s in syms if s and s != "-" and len(s) <= 5]
            log.info("Russell 2000: fetched %d holdings from iShares (full universe)", len(syms))
            return syms
    except Exception as e:
        log.warning("Russell 2000 iShares fetch failed: %s", e)
    log.warning("Russell 2000 fallback list used (%d tickers)", len(RUSSELL_2000_FALLBACK))
    return RUSSELL_2000_FALLBACK


# Backwards-compatible wrappers
def get_sp500():
    return get_sp_midcap_400()

def get_nasdaq100():
    return get_russell_2000()
