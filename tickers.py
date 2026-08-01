"""
Ticker universe — layered, fail-safe, and self-reporting.

Universe sources, tried in order (each guarded by MIN_UNIVERSE):
  1. Yahoo screener  — true market-cap screen ($800M–$300B), NYSE/Nasdaq, liquid.
                       Includes names S&P indices exclude for profitability or
                       domicile reasons (CRDO, BE, RIOT, ARWR ...).
  2. S&P 1500        — S&P 500 + 400 + 600 from Wikipedia (~1,506 tickers).
                       Quality-screened but excludes unprofitable growth names.
  3. Static list     — emergency floor only. Stale; equals pre-Aug-2026 behaviour.

Whichever source wins is reported in the Telegram header, so a silent fallback
can never go unnoticed again (that bug shipped for weeks).
"""

import os
import ssl
import json
import time
import logging
import urllib.request

import pandas as pd

log = logging.getLogger(__name__)

# ── Universe sizing / guards ──────────────────────────────────────────────────
MIN_MARKET_CAP = int(os.getenv("MIN_MARKET_CAP", 800_000_000))        # $800M floor
MAX_MARKET_CAP = int(os.getenv("MAX_MARKET_CAP", 300_000_000_000))    # $300B ceiling
MIN_PRICE_SCR  = float(os.getenv("MIN_PRICE", 5.0))
MIN_AVG_VOL    = int(os.getenv("MIN_AVG_VOL", 300_000))               # 3m avg shares/day
MIN_UNIVERSE   = int(os.getenv("MIN_UNIVERSE", 300))   # reject any source smaller
MAX_UNIVERSE   = int(os.getenv("MAX_UNIVERSE", 2200))  # cap scan time / yf load
CACHE_PATH     = "/tmp/universe_cache.json"
CACHE_TTL_S    = 6 * 24 * 3600     # refresh weekly-ish

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


# ── Exclusion list ────────────────────────────────────────────────────────────
EXCLUDED_TICKERS = {
    # Oil & Gas (E&P, services, midstream, refining)
    "PR", "CHRD", "CHX", "DRQ", "DINO", "PARR", "NOV", "CLNE",
    # Weapons / Defense / Ammo / Defense contractors
    "KTOS", "AVAV", "POWW", "AMMO", "SWBI", "BYRN", "AXON",
    "BWXT", "CW", "CACI", "SAIC", "KBR", "BBAI", "ATRO",
    # Drones / eVTOL
    "ACHR", "JOBY",
    # Defense data analytics (user request)
    "PLTR",
}


# ── 1. Yahoo screener ─────────────────────────────────────────────────────────

def _yahoo_screen_universe() -> list:
    """
    Market-cap + liquidity screen straight from Yahoo. Paginates 250 at a time
    (Yahoo's hard page limit). Returns [] on any failure.
    """
    import yfinance as yf
    from yfinance import EquityQuery

    q = EquityQuery("and", [
        EquityQuery("eq",    ["region", "us"]),
        EquityQuery("is-in", ["exchange", "NMS", "NYQ"]),
        EquityQuery("btwn",  ["intradaymarketcap", MIN_MARKET_CAP, MAX_MARKET_CAP]),
        EquityQuery("gte",   ["intradayprice", MIN_PRICE_SCR]),
        EquityQuery("gte",   ["avgdailyvol3m", MIN_AVG_VOL]),
    ])

    syms, offset, page = [], 0, 250
    while offset < MAX_UNIVERSE + page:
        try:
            resp = yf.screen(q, offset=offset, size=page,
                             sortField="intradaymarketcap", sortAsc=False)
        except Exception as exc:
            log.warning("Yahoo screener page at offset %d failed: %s", offset, exc)
            break
        quotes = (resp or {}).get("quotes", []) or []
        if not quotes:
            break
        syms += [q_.get("symbol") for q_ in quotes if q_.get("symbol")]
        if len(quotes) < page:
            break
        offset += page
        time.sleep(0.5)          # be polite; Yahoo rate-limits aggressively

    # Preserve the market-cap DESC order the screener returned. Sorting here
    # (e.g. sorted(set(...))) would make the MAX_UNIVERSE slice alphabetical,
    # silently dropping every ticker after ~"M". That bug shipped once.
    seen, out = set(), []
    for s in syms:
        s = (s or "").replace(".", "-")
        if s and len(s) <= 6 and s not in seen:
            seen.add(s)
            out.append(s)
    log.info("Yahoo screener returned %d symbols (market-cap order)", len(out))
    return out


# ── 2. S&P 1500 via Wikipedia ─────────────────────────────────────────────────

def _wiki_symbols(url: str, name: str) -> list:
    """Read a Wikipedia constituents table. Proper UA — Wikipedia 403s the default."""
    try:
        tables = pd.read_html(url, storage_options=UA)
    except Exception as exc:
        log.warning("%s Wikipedia fetch failed: %s", name, exc)
        return []
    for t in tables:
        cols = [str(c) for c in t.columns]
        for col in ("Symbol", "Ticker", "Ticker symbol"):
            if col in cols:
                syms = (t[col].dropna().astype(str)
                        .str.strip().str.replace(".", "-", regex=False).tolist())
                syms = [s for s in syms if s and len(s) <= 6 and s.replace("-", "").isalpha()]
                if len(syms) > 50:
                    log.info("%s: %d tickers", name, len(syms))
                    return syms
    log.warning("%s: no constituents table matched", name)
    return []


def _sp1500_universe() -> list:
    out = []
    for url, name in (
        ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "S&P 500"),
        ("https://en.wikipedia.org/wiki/List_of_S%26P_400_companies", "S&P 400"),
        ("https://en.wikipedia.org/wiki/List_of_S%26P_600_companies", "S&P 600"),
    ):
        out += _wiki_symbols(url, name)
    return sorted(set(out))


# ── 3. Static emergency floor ─────────────────────────────────────────────────
# Deliberately unchanged from the pre-Aug-2026 list: reaching this layer means
# BOTH live sources failed, and matching old behaviour is the safe outcome.
# Known-stale (contains delisted names) — that is why the Telegram header warns.
STATIC_FALLBACK = [
    "BLDR","FSLR","ENPH","SMCI","DECK","CSL","SAIA","WSM","JBL","MANH","PSTG","FIX",
    "RGA","RNR","EME","MOH","WAL","BURL","SF","UTHR","XPO","ORI","CASY","RGLD","TPL",
    "EHC","ALSN","UNM","TXRH","WSO","CLF","FLR","OC","WMS","ATR","PEN","PRI","X",
    "CIEN","TPX","BJ","GME","WBS","OLED","NYT","RPM","LECO","MUSA","COKE","SWX","CHE",
    "WEX","TKR","ELS","OLN","KNX","KMX","CFR","OGE","DCI","AMG","CGNX","MIDD","CHDN",
    "RBC","SLM","ALE","PNFP","WCC","NJR","BCO","ZWS","NSP","AFG","MTN","PNW","MORN",
    "WTRG","OZK","FAF","INGR","SON","JEF","SCI","DAR","HRB","CMC","CADE","DKS","BRX",
    "FN","WTS","LSCC","RHI","COLM","CHH","HXL","RRC","KEX","JLL","BLD","AGCO","HALO",
    "MTZ","CROX","PII","CC","SLGN","R","FYBR","ALV","BERY","HOG","KRC","SR","WH","AYI",
    "NVT","EWBC","GATX","LSTR","BCPC","CSWI","ITRI","GMED","AAON","HLNE","MGEE","WSFS",
    "HOPE","BANF","SFNC","CVBF","FFIN","UBSI","BOKF","TCBI","ABCB","IBOC","NBTB","SRCE",
    "FULT","TRMK","PRGS","ICFI","EXPO","HCSG","MGRC","JJSF","LANC","SEIC","UMBF",
    "SOFI","UPST","HOOD","AFRM","ENVA","QFIN","CACC","PFSI","UWMC","TREE","MARA","RIOT",
    "CLSK","CIFR","WULF","IREN","HUT","BITF","BTDR","PATH","DOCN","CFLT","GTLB","NCNO",
    "BILL","ESTC","PCTY","APPF","JAMF","BRZE","HUBS","ZI","TOST","FRSH","SEMR","ACMR",
    "XMTR","SMAR","ASAN","TMDX","PRCT","OMCL","NXST","PLTK","CRDO","NVTS","ONTO","AMBA",
    "SITM","DIOD","MTSI","VICR","AEHR","ACLS","FORM","ICHR","RMBS","CEVA","LFUS","POWI",
    "MCHP","SWKS","QRVO","OSIS","SMTC","ALGM","TRUP","RXRX","CRSP","NTLA","BEAM","VKTX",
    "ALNY","MDGL","KRYS","ITCI","INSM","SRPT","ACAD","ARWR","FOLD","IMVT","KYMR","LGND",
    "PTGX","RCUS","RGEN","TGTX","VRTX","XNCR","AGIO","ARQT","BMRN","CDNA","CLDX","CPRX",
    "DNLI","GKOS","HRMY","IDYA","IMCR","JANX","KROS","KURA","LEGN","MIRM","MNKD","NUVL",
    "OCUL","PTCT","QURE","RARE","RLAY","RVMD","SAGE","STOK","RDDT","RBLX","ETSY","PINS",
    "CART","VITL","PSMT","BOOT","OXM","RCII","SCVL","VSCO","XPOF","LESL","GIII","DNUT",
    "JACK","LOCO","PTLO","SHAK","UFPT","WING","BJRI","CBRL","CAKE","EAT","CHPT","BE",
    "STEM","RUN","ARRY","PLUG","FCEL","BLNK","EVGO","QS","XPEV","NIO","LI","POWL","GFF",
    "MLI","NX","SXI","TNC","UFPI","WIRE","AZZ","CRS","ESAB","KALU","MTRN","NVR","PATK",
    "PRLB","SSD","STLD","TREX","ASTE","BECN","CEIX","GLDD","IESC","MYR","PRIM","TPC",
    "NVCR","INSP","NARI","IRTC","MASI","MMSI","OSUR","PDCO","PINC","QTWO","USPH","VCEL",
    "AMWL","CERT","CLOV","DOCS","HIMS","LMAT","MDRX","ROIC","STAG","EFC","HASI","IIPR",
    "KREF","LADR","MFA","ORC","RITM","TRTX","BXMT","APP","TTD","MGNI","PUBM","IAS","DV",
    "DKNG","PENN","RSI","GENI","NCLH","CCL","RCL","ZETA","NBIS","SERV","AUR","RGTI",
    "FLNC","ON","TER","NXT","CYTK","OKLO","SMR","NNE","UEC","UUUU","RKLB","ASTS","LUNR",
    "RDW","TLN","VST","CEG","GPRE","REX","HAYW","PRAA","EZPW","HIVE","MDXG","SPSC",
    "EGAN","PEGA","ALKT","DOMO","LPSN","WEAVE","RELY","NRDS","TASK","POET","AOSL","AIOT",
    "EDIT","REPL","INVA","MGNX","SANA","TVTX","YMAB","ZYME","CCCC","CMPS","CNTA","COGT",
    "ENTA","FATE","FGEN","IPSC","MORF","PHAT","PLRX","PRAX","SEER","SLDB","SPRO","GOCO",
    "CULP","GCO","TLYS","WOOF","FAT","NATH","DINE","GTIM","IIIN","HAYN","PKOH","USAP",
    "ZEUS","SHCR","SPOK","SRTX","VREX","ACCD","NREF","SACH","TWO","VRE","TPVG","VNET",
    "GATO","SKLZ","EVRI","AGS","ACEL","DARE","MFIN","WRLD","RM","GHLD","NXGL","AMSWA",
]


# ── Public API ────────────────────────────────────────────────────────────────

def _load_cache():
    try:
        if not os.path.exists(CACHE_PATH):
            return None
        if time.time() - os.path.getmtime(CACHE_PATH) > CACHE_TTL_S:
            return None
        with open(CACHE_PATH) as fh:
            d = json.load(fh)
        if isinstance(d.get("tickers"), list) and len(d["tickers"]) >= MIN_UNIVERSE:
            return d
    except Exception as exc:
        log.debug("Universe cache read failed: %s", exc)
    return None


def _save_cache(tickers, source):
    try:
        with open(CACHE_PATH, "w") as fh:
            json.dump({"tickers": tickers, "source": source}, fh)
    except Exception as exc:
        log.debug("Universe cache write failed: %s", exc)


def get_universe(use_cache: bool = True) -> tuple[list, str]:
    """
    Return (tickers, source_label). Never raises; always returns a usable list.
    source_label is surfaced in the Telegram header so a fallback is visible.
    """
    if use_cache:
        cached = _load_cache()
        if cached:
            log.info("Universe from cache: %s (%d)", cached["source"], len(cached["tickers"]))
            return cached["tickers"], f"{cached['source']} [cached]"

    # 1. Yahoo screener
    try:
        syms = _yahoo_screen_universe()
        if len(syms) >= MIN_UNIVERSE:
            syms = syms[:MAX_UNIVERSE]
            src = f"Yahoo screener {MIN_MARKET_CAP/1e6:.0f}M-{MAX_MARKET_CAP/1e9:.0f}B cap"
            _save_cache(syms, src)
            return syms, src
        log.warning("Yahoo screener too small (%d < %d) — falling back", len(syms), MIN_UNIVERSE)
    except Exception as exc:
        log.warning("Yahoo screener unavailable: %s", exc)

    # 2. S&P 1500 via Wikipedia
    try:
        syms = _sp1500_universe()
        if len(syms) >= MIN_UNIVERSE:
            syms = syms[:MAX_UNIVERSE]
            src = "S&P 1500 (Wikipedia)"
            _save_cache(syms, src)
            return syms, src
        log.warning("S&P 1500 too small (%d) — falling back", len(syms))
    except Exception as exc:
        log.warning("S&P 1500 unavailable: %s", exc)

    # 3. Emergency static floor
    log.warning("BOTH live universe sources failed — using stale static list")
    return sorted(set(STATIC_FALLBACK)), "STATIC fallback ⚠️ STALE"


def filter_excluded(tickers):
    """Remove user-excluded tickers (oil, weapons, drones)."""
    return [t for t in tickers if t not in EXCLUDED_TICKERS]


# ── Back-compat shims (scanner_b.py historically imported these) ──────────────
def get_sp500():
    return get_universe()[0]

def get_nasdaq100():
    return []
