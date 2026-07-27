"""
Prospero AI — free-signal forward-tracker
=========================================
Purpose: measure whether Prospero.ai's FREE signals actually produce alpha,
BEFORE paying for the ~$10/mo tier.

How to use:
  1. Open the "Prospero" tab in the signals Google Sheet (auto-created on first run).
  2. Each time Prospero shows a signal, add ONE row filling only three fields:
        date_added  — YYYY-MM-DD, the date the signal appeared
        ticker      — e.g. NVDA
        signal      — free text, e.g. "strong buy" / "bullish" / "top pick"
     Leave every other column blank. This script fills them in.
  3. Runs daily: fills forward returns at 5 / 10 / 21 trading days, benchmarks
     each against SPY over the SAME window, and computes alpha = stock - SPY.
  4. Posts a summary to Telegram (weekly).

Why alpha and not raw return: if Prospero says "buy X" and X gains 3% while SPY
gains 3%, there is no edge — that is market beta, not a signal.

PRE-REGISTERED DECISION CRITERIA (fixed 2026-07-21, before any data collected):
  After >= 30 scored signals at the 10-day horizon:
      SUBSCRIBE   if hit rate (alpha > 0) >= 55%  AND  mean alpha >= +1.0%
      DO NOT PAY  otherwise
  Do not move these goalposts after seeing results.
"""

import os
import json
import base64
import logging
from datetime import date, datetime, timedelta

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)

SHEET_NAME = "Prospero"
HEADERS = [
    "date_added", "ticker", "signal", "entry_price",
    "ret_5d",  "spy_5d",  "alpha_5d",
    "ret_10d", "spy_10d", "alpha_10d",
    "ret_21d", "spy_21d", "alpha_21d",
    "status",
]

HORIZONS             = (5, 10, 21)
JUDGE_HORIZON        = 10     # horizon used for the subscribe / don't-pay call
MIN_SIGNALS_TO_JUDGE = 30
HIT_RATE_BAR         = 55.0   # percent of signals with positive alpha
MEAN_ALPHA_BAR       = 1.0    # percent mean alpha


# ── Sheets ────────────────────────────────────────────────────────────────────

def _get_worksheet():
    """Return the Prospero worksheet (creating it if missing), or None."""
    creds_b64 = os.getenv("GOOGLE_SHEETS_CREDS", "")
    sheet_id  = os.getenv("GOOGLE_SHEET_ID", "")
    if not creds_b64 or not sheet_id:
        log.warning("Prospero: Sheets env vars not set — tracker disabled")
        return None
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_json = json.loads(base64.b64decode(creds_b64).decode())
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
        gc    = gspread.authorize(creds)
        sh    = gc.open_by_key(sheet_id)
        try:
            ws = sh.worksheet(SHEET_NAME)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=SHEET_NAME, rows=2000, cols=len(HEADERS))
            ws.append_row(HEADERS)
            log.info("Prospero: created '%s' tab", SHEET_NAME)
        return ws
    except Exception as exc:
        log.error("Prospero: sheet error: %s", exc)
        return None


# ── Price helpers ─────────────────────────────────────────────────────────────

def _history(ticker: str, start: date):
    """Daily bars from `start` to today, columns lowercased. None on error."""
    try:
        raw = yf.download(ticker, start=start.isoformat(), interval="1d",
                          auto_adjust=True, progress=False, threads=False)
        if raw is None or raw.empty:
            return None
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        raw.columns = [str(c).lower() for c in raw.columns]
        if isinstance(raw.index, pd.DatetimeIndex) and raw.index.tz is not None:
            raw.index = raw.index.tz_localize(None)
        return raw.dropna(subset=["close"])
    except Exception as exc:
        log.debug("Prospero: history error %s: %s", ticker, exc)
        return None


def _fwd_return(df, added: date, horizon: int):
    """
    Return (entry_close, pct_return) measured `horizon` trading days after the
    first session on/after `added`. pct_return is None if not enough days yet.
    """
    if df is None or df.empty:
        return None, None
    future = df.index[df.index >= pd.Timestamp(added)]
    if len(future) == 0:
        return None, None
    pos   = df.index.get_loc(future[0])
    entry = float(df["close"].iloc[pos])
    tgt   = pos + horizon
    if tgt >= len(df):
        return entry, None
    exit_px = float(df["close"].iloc[tgt])
    return entry, (exit_px - entry) / entry * 100


# ── Main jobs ─────────────────────────────────────────────────────────────────

def update_prospero():
    """Fill entry price + forward returns/alpha for every pending signal row."""
    ws = _get_worksheet()
    if ws is None:
        return
    try:
        rows = ws.get_all_records()
    except Exception as exc:
        log.error("Prospero: read error: %s", exc)
        return

    pending = []
    for i, r in enumerate(rows, start=2):          # row 1 = header
        if str(r.get("status", "")).strip().upper() == "DONE":
            continue
        tkr = str(r.get("ticker", "")).strip().upper()
        raw_date = str(r.get("date_added", "")).strip()
        if not tkr or not raw_date:
            continue
        try:
            added = datetime.strptime(raw_date[:10], "%Y-%m-%d").date()
        except ValueError:
            log.warning("Prospero: bad date '%s' on row %d", raw_date, i)
            continue
        pending.append({"row": i, "ticker": tkr, "added": added})

    if not pending:
        log.info("Prospero: nothing pending.")
        return

    oldest = min(p["added"] for p in pending) - timedelta(days=10)
    spy    = _history("SPY", oldest)
    if spy is None:
        log.warning("Prospero: could not fetch SPY benchmark — aborting.")
        return

    updated = 0
    for p in pending:
        df = _history(p["ticker"], oldest)
        if df is None:
            continue
        entry, cells, complete = None, [], True
        for h in HORIZONS:
            e, ret  = _fwd_return(df,  p["added"], h)
            _, sret = _fwd_return(spy, p["added"], h)
            if e is not None:
                entry = e
            if ret is None or sret is None:
                cells.extend(["", "", ""])
                complete = False
            else:
                cells.extend([round(ret, 2), round(sret, 2), round(ret - sret, 2)])
        if entry is None:
            continue
        payload = [round(entry, 2)] + cells + ["DONE" if complete else "TRACKING"]
        try:
            ws.update(f"D{p['row']}:N{p['row']}", [payload])
            updated += 1
        except Exception as exc:
            log.warning("Prospero: update error row %d: %s", p["row"], exc)

    log.info("Prospero: updated %d row(s).", updated)


def _stats(rows, key):
    """Return (n, hit_rate_pct, mean) for a numeric column, or None."""
    vals = []
    for r in rows:
        v = r.get(key, "")
        if v in ("", None):
            continue
        try:
            vals.append(float(v))
        except (TypeError, ValueError):
            pass
    if not vals:
        return None
    wins = sum(1 for v in vals if v > 0)
    return len(vals), wins / len(vals) * 100, sum(vals) / len(vals)


def prospero_summary():
    """Post the current edge measurement + verdict to Telegram."""
    from alerts import send_alert

    ws = _get_worksheet()
    if ws is None:
        return
    try:
        rows = ws.get_all_records()
    except Exception as exc:
        log.error("Prospero: read error: %s", exc)
        return

    lines, verdict = [], ""
    for h in HORIZONS:
        s = _stats(rows, f"alpha_{h}d")
        if not s:
            continue
        n, hit, mean = s
        lines.append(f"{h}d — n={n} · hit {hit:.0f}% · mean alpha {mean:+.2f}%")
        if h == JUDGE_HORIZON:
            if n < MIN_SIGNALS_TO_JUDGE:
                verdict = f"⏳ {n}/{MIN_SIGNALS_TO_JUDGE} scored — too early to judge."
            elif hit >= HIT_RATE_BAR and mean >= MEAN_ALPHA_BAR:
                verdict = "✅ PASSES the pre-set bar — subscription worth considering."
            else:
                verdict = "❌ FAILS the pre-set bar — do not pay."

    if not lines:
        lines.append("No scored signals yet — add rows to the Prospero tab.")

    send_alert(
        "🧪 <b>Prospero free-signal tracker</b>\n"
        "<i>alpha = stock return − SPY over the same window</i>\n\n"
        + "\n".join(lines)
        + (f"\n\n<b>{verdict}</b>" if verdict else "")
        + f"\n\n<i>Bar: at {JUDGE_HORIZON}d, hit ≥{HIT_RATE_BAR:.0f}% AND "
          f"mean alpha ≥{MEAN_ALPHA_BAR:+.1f}% after {MIN_SIGNALS_TO_JUDGE} signals</i>"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)s  %(message)s")
    update_prospero()
    prospero_summary()
