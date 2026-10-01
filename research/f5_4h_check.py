"""F5 (FFIV) 4h check: TradingView markers (dates estimated from the screenshot) vs Python walk-forward long flips.
Needs ffiv4h.pkl (4h bars built from yfinance 60m data: 09:30 and 13:30 ET). Exploratory, not a pre-registered test."""
import sys, time, pandas as pd, numpy as np
sys.path.insert(0,"/Users/test/quant/lorentzian-scanner")
from advanced_ta import LorentzianClassification as LC
b=pd.read_pickle("ffiv4h.pkl"); b.columns=[c.lower() for c in b.columns]
b=b[b.index<pd.Timestamp.today(tz="America/New_York").normalize()]      # complete bars only
b.index=b.index.tz_localize(None)
n=len(b); anchor=b.index.get_loc(pd.Timestamp("2026-08-28 13:30"))
last=n-1; print("bars from crosshair to last complete bar:",last-anchor, b.index[-1])
# marker x positions read off the screenshot (green = long). last candle ~x=1600 (partial bar excluded), crosshair x=1457
ppb=(1600-1457)/(last-anchor+1)      # +1: today's partial bar at the right edge
xs=[373,491,697,769,837,1137,1320,1445]
print("px/bar",round(ppb,2))
marks=[b.index[int(round(anchor-(1457-x)/ppb))] for x in xs]
print("green markers (approx):",[str(m) for m in marks])
F=LC.Feature
feat=[F("RSI",9,1),F("WT",10,11),F("CCI",20,1),F("ADX",20,2),F("RSI",9,1)]
fs=LC.FilterSettings(useVolatilityFilter=True,useRegimeFilter=True,useAdxFilter=True,regimeThreshold=-0.1,adxThreshold=20,kernelFilter=LC.KernelFilter(useKernelSmoothing=False))
t0=time.time(); flips=[]
for t in range(n-430,n):
    r=LC(b.iloc[max(0,t-1999):t+1].copy(),features=feat,filterSettings=fs).df.iloc[-1]
    if not pd.isna(r.get("startLongTrade")): flips.append((b.index[t],int(r["prediction"])))
print("python long flips (4h, chart settings), last 430 bars:",round(time.time()-t0),"s");
for d,v in flips: print("  ",d,v)
pd.to_pickle((marks,flips),"f5_result.pkl")
for m in marks:
    near=[(str(d),v) for d,v in flips if abs(b.index.get_loc(d)-b.index.get_loc(m))<=3]
    print("marker",m,"-> python flip within 3 bars:",near or "NONE")
