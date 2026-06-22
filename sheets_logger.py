"""
Google Sheets logger for Lorentzian scanner signals.

Required Railway env vars:
  GOOGLE_SHEETS_CREDS  — base64-encoded service account JSON
  GOOGLE_SHEET_ID      — spreadsheet ID from the URL

Sheet columns (auto-created if missing):
  scan_date | ticker | type | entry_price | vwap | vote |
  status | scan_date_str | exit_date | exit_price | pnl_pct | exit_reason
"""

import os
import json
import base64
import logging
from datetime import date, timedelta

log = logging.getLogger(__name__)

SHEET_NAME = "Signals"
HEADERS = [
    "scan_date", "ticker", "type", "entry_price", "vwap", "vote",
    "status", "exit_date", "exit_price", "pnl_pct", "exit_reason"
]

# Column indices (1-based) matching HEADERS order
COL = {h: i + 1 for i, h in enumerate(HEADERS)}


def _get_worksheet():
    """Return gspread worksheet, or None if not configured."""
    creds_b64 = os.getenv("GOOGLE_SHEETS_CREDS", "")
    sheet_id  = os.getenv("GOOGLE_SHEET_ID", "")
    if not creds_b64 or not sheet_id:
        log.warning("Sheets env vars not set — logging disabled")
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
            ws = sh.add_worksheet(title=SHEET_NAME, rows=10000, cols=len(HEADERS))
            ws.append_row(HEADERS)
            log.info("Created sheet '%s' with headers", SHEET_NAME)

        return ws
    except Exception as exc:
        log.error("Sheets init failed: %s", exc)
        return None


def _trading_days_since(scan_date_str: str) -> int:
    """Count business days between scan_date and today (exclusive of today)."""
    try:
        start = date.fromisoformat(scan_date_str)
    except ValueError:
        return 0
    today   = date.today()
    count   = 0
    current = start
    while current < today:
        current += timedelta(days=1)
        if current.weekday() < 5:   # Mon–Fri
            count += 1
    return count


# ── Public API ────────────────────────────────────────────────────────────────

def log_signals(scan_date: str, buys: list, reentries: list) -> None:
    """
    Append new BUY and REENTRY signals as OPEN rows.

    buys / reentries: list of dicts with keys: ticker, price, vwap, vote
    """
    ws = _get_worksheet()
    if ws is None:
        return

    rows = []
    for s in buys:
        rows.append([
            scan_date, s["ticker"], "BUY",
            round(s["price"], 4), round(s["vwap"], 4), s["vote"],
            "OPEN", "", "", "", ""
        ])
    for s in reentries:
        rows.append([
            scan_date, s["ticker"], "REENTRY",
            round(s["price"], 4), round(s["vwap"], 4), s["vote"],
            "OPEN", "", "", "", ""
        ])

    if rows:
        try:
            ws.append_rows(rows, value_input_option="USER_ENTERED")
            log.info("Logged %d signals to Sheets", len(rows))
        except Exception as exc:
            log.error("Failed to log signals: %s", exc)


def get_open_positions() -> tuple[list, object]:
    """
    Return (open_positions, worksheet).
    open_positions: list of dicts with keys:
      row_idx, scan_date, ticker, type, entry_price, vwap, vote, days_held
    Returns ([], None) on error.
    """
    ws = _get_worksheet()
    if ws is None:
        return [], None

    try:
        all_rows = ws.get_all_records()
        open_pos = []
        for i, row in enumerate(all_rows, start=2):   # row 1 = header
            if str(row.get("status", "")).strip().upper() == "OPEN":
                open_pos.append({
                    "row_idx":     i,
                    "scan_date":   str(row["scan_date"]),
                    "ticker":      str(row["ticker"]),
                    "type":        str(row["type"]),
                    "entry_price": float(row["entry_price"]),
                    "vwap":        float(row["vwap"]),
                    "vote":        int(row["vote"]),
                    "days_held":   _trading_days_since(str(row["scan_date"])),
                })
        log.info("Found %d open positions in Sheets", len(open_pos))
        return open_pos, ws
    except Exception as exc:
        log.error("Failed to read open positions: %s", exc)
        return [], None


def close_positions(ws, exits: list) -> None:
    """
    Mark positions as CLOSED in the sheet.

    exits: list of dicts with keys:
      row_idx, exit_price, exit_reason, entry_price
    """
    if ws is None or not exits:
        return
    today = date.today().isoformat()
    for ex in exits:
        try:
            pnl = round((ex["exit_price"] - ex["entry_price"]) / ex["entry_price"] * 100, 2)
            # Columns: status(7), exit_date(8), exit_price(9), pnl_pct(10), exit_reason(11)
            ws.update(
                f"G{ex['row_idx']}:K{ex['row_idx']}",
                [["CLOSED", today, ex["exit_price"], pnl, ex["exit_reason"]]]
            )
            log.info("Closed row %d: %s %.2f%%", ex["row_idx"], ex["exit_reason"], pnl)
        except Exception as exc:
            log.error("Failed to close row %d: %s", ex["row_idx"], exc)
