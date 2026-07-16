"""
Ticker universe: S&P 500 + Nasdaq 100 (fetched live from Wikipedia)
Fallback: S&P MidCap 400 + Russell 2000 if live fetch fails
With user exclusion list (oil/gas, weapons/defense/ammo, drones/eVTOL)
"""

import logging
import ssl
import urllib.request
import pandas as pd

log = logging.getLogger(__name__)


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
    "GATX","LSTR","BCPC","CSWI","ITRI","GMED","AAON","HLNE","MGEE",
    "WSFS","HOPE","BANF","SFNC","CVBF","FFIN","UBSI","BOKF","TCBI",
    "ABCB","HTLF","IBOC","NBTB","SRCE","FULT","ISBC","TRMK","HBCP",
    "PRGS","ICFI","EXPO","HCSG","MGRC","JJSF","LANC","SEIC","UMBF",
]

RUSSELL_2000_FALLBACK = [
    "OKLO","SMR","NNE","UEC","UUUU","DNN","URG","EU","BWRX","NRGV",
    "TLN","CEG","VST","CLNE","GPRE","ALTO","REX","CVRX","PARR","DINO",
    "RKLB","ASTS","PL","JOBY","ACHR","LILM","BLADE","RDW","BBAI","KTOS",
    "AVAV","LUNR","MNTS","SPCE","VORB","ATRO","HAYW","SWBI","AXON",
    "POWW","AMMO","CODA","AEROJET","BYRN",
    "SOFI","UPST","HOOD","AFRM","DAVE","MFIN","PRAA","ENVA","CURO",
    "QFIN","LEND","ATLC","WRLD","NICK","CACC","RM","RCMT","PFSI",
    "UWMC","GHLD","HMPT","RATE","TREE","EZPW",
    "MARA","RIOT","CLSK","CIFR","WULF","IREN","HUT","BTBT","HIVE","BITF",
    "BTDR","MIGI","SATO","ACDC","GREE","NXGL",
    "PATH","DOCN","CFLT","GTLB","NCNO","BILL","FROG","SUMO","ESTC",
    "ALKT","POWI","PEGA","EGAN","SPSC","PCTY","APPF","JAMF","BRZE",
    "HUBS","ZI","EVBG","AMSWA","VERINT","KNBE","SAIL","DOMO","LPSN",
    "SPRK","WEAVE","TOST","RELY","NRDS","RELY","FRSH","SEMR","ACMR",
    "XMTR","SMAR","ASAN","TASK","TMDX","PRCT","OMCL","NXST","PLTK",
    "CRDO","NVTS","ONTO","AMBA","SITM","DIOD","MTSI","VICR","AEHR",
    "ACLS","FORM","ICHR","RMBS","CEVA","POET","LSCC","LFUS","POWI",
    "MCHP","SWKS","QRVO","AOSL","OSIS","SMTC","ALGM","AIOT","TRUP",
    "RXRX","CRSP","NTLA","EDIT","BEAM","VKTX","ALNY","MDGL","KRYS",
    "ITCI","INSM","REPL","SRPT","ACAD","ARWR","FOLD","IMVT","INVA",
    "KYMR","LGND","MGNX","NKTR","ORIC","PTGX","RCUS","RGEN","SANA",
    "TBPH","TGTX","TVTX","VRTX","XNCR","YMAB","ZYME","AGIO","ARQT",
    "BDTX","BMRN","CCCC","CDNA","CLDX","CMPS","CNTA","COGT","CPRX",
    "DNLI","ENTA","FATE","FGEN","FIXX","GKOS","HALO","HRMY","IDYA",
    "IMCR","INBX","IPSC","IRON","JANX","KALA","KROS","KURA","LEGN",
    "LPSN","LUMO","MDXG","MIRM","MNKD","MORF","NBTX","NKTR","NUVL",
    "OCUL","OMGA","PHAT","PLRX","PRAX","PRTK","PTCT","QURE","RARE",
    "RLAY","RVMD","SAGE","SEER","SESN","SLDB","SPRO","STOK","SYRS",
    "RDDT","RBLX","ETSY","PINS","BMBL","CART","VITL","GOCO","PSMT",
    "BOOT","CATO","CULP","EXPR","GCO","JOANN","OXM","PRTY","RCII",
    "SCVL","TLYS","TUEM","VSCO","WOOF","XPOF","LAZY","LESL","GIII",
    "DNUT","FAT","JACK","LOCO","NATH","PTLO","SHAK","TAST","TXRH",
    "UFPT","WING","BJRI","CBRL","CAKE","DINE","EAT","FRGI","GTIM",
    "CHPT","BE","STEM","RUN","ARRY","PLUG","FCEL","BLNK","EVGO","NKLA",
    "PTRA","WKHS","IDEX","SOLO","AYRO","HYZN","DCRB","GOEV","ARVL",
    "FFIE","RIDE","HYLN","KPLT","REE","XPEV","NIO","LI",
    "POWL","GFF","IIIN","MLI","NX","REXNORD","SXI","TNC","UFPI","WIRE",
    "AZZ","BMBL","CRS","DRQ","ESAB","GNSS","HAYN","KALU","MTRN","NVR",
    "PATK","PKOH","PRLB","ROLL","SSD","STLD","TMCO","TREX","USAP","ZEUS",
    "ASTE","BECN","BLDR","CEIX","FLR","GLDD","IESC","MYR","PRIM","TPC",
    "TMDX","PRCT","OMCL","NVCR","GKOS","INSP","NARI","SWAV","IRTC",
    "MASI","MMSI","NUVA","OSUR","PDCO","PINC","PRSC","QTWO","RGEN",
    "SHCR","SPOK","SRTX","USPH","VCEL","VREX","XTLB","ACCD","AMWL",
    "CERT","CHNG","CLOV","DOCS","HIMS","LMAT","LVGO","MDXG","MDRX",
    "ROIC","STAG","EFC","GPMT","HASI","IIPR","KREF","LADR","MFA","NREF",
    "ORC","RITM","SACH","TRTX","TWO","VRE","BXMT","CLNC","GPMT","TPVG",
    "APP","TTD","MGNI","PUBM","IAS","VNET","DV","KPLT","GATO","SKLZ",
    "DKNG","PENN","RSI","GENI","EVRI","AGS","ACEL","NCLH","CCL","RCL",
    "ZETA","NBIS","TE","DARE","QS","SERV","AUR","NVTS","RGTI",
    "FLNC","ON","TER","NXT","CYTK","PLTR","NVDA","ASTS","OKLO","RKLB",
    "SOFI","RDDT",
]


def _fetch_wikipedia_table(url, name="table"):
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
            log.info("Russell 2000: fetched %d holdings from iShares", len(syms))
            return syms
    except Exception as e:
        log.warning("Russell 2000 iShares fetch failed: %s", e)
    log.warning("Russell 2000 expanded static fallback used (%d tickers)", len(RUSSELL_2000_FALLBACK))
    return RUSSELL_2000_FALLBACK


def filter_excluded(tickers):
    """Remove user-excluded tickers (oil, weapons, drones)."""
    return [t for t in tickers if t not in EXCLUDED_TICKERS]


def get_sp500():
    """Fetch actual S&P 500 constituents from Wikipedia."""
    syms = _fetch_wikipedia_table("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "S&P 500")
    if syms:
        log.info("S&P 500: fetched %d tickers", len(syms))
        return syms
    log.warning("S&P 500 fetch failed — falling back to MidCap 400")
    return get_sp_midcap_400()


def get_nasdaq100():
    """Fetch actual Nasdaq 100 constituents from Wikipedia."""
    syms = _fetch_wikipedia_table("https://en.wikipedia.org/wiki/Nasdaq-100", "Nasdaq 100")
    if syms:
        log.info("Nasdaq 100: fetched %d tickers", len(syms))
        return syms
    log.warning("Nasdaq 100 fetch failed — falling back to Russell 2000")
    return get_russell_2000()
