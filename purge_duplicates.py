"""
One-shot: permanently remove the 'duplicate removed' tombstone rows.

cleanup_duplicates.py marks duplicate OPEN rows as CLOSED with
exit_reason='duplicate removed' and pnl_pct=0 — it never deletes them. They
accumulate and distort any aggregate computed over the sheet. As of
2026-08-14 they were 181 of 807 rows (22%), which pulls every average toward
zero unless you remember to filter them out every single time.

Safety:
  - Only rows whose exit_reason is exactly 'duplicate removed' are touched.
  - A row with status OPEN is never touched, whatever its exit_reason says.
  - Contiguous rows are deleted as blocks, bottom-up, so indices stay valid.
  - DRY_RUN defaults to TRUE: it reports and changes nothing.

Run inside Railway (has GOOGLE_SHEETS_CREDS + GOOGLE_SHEET_ID):
    python purge_duplicates.py                 # dry run, safe
    DRY_RUN=false python purge_duplicates.py   # actually deletes

Copy the spreadsheet before running with DRY_RUN=false.
Do not run while a scan is in progress — the scanner addresses rows by index.
"""
import os
import json
import base64

TOMBSTONE = "duplicate removed"
DRY_RUN = os.getenv("DRY_RUN", "true").lower() != "false"


def main():
    creds_b64 = os.getenv("GOOGLE_SHEETS_CREDS", "")
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
    if not creds_b64 or not sheet_id:
        raise SystemExit("Missing GOOGLE_SHEETS_CREDS or GOOGLE_SHEET_ID")

    import gspread
    from google.oauth2.service_account import Credentials

    creds_json = json.loads(base64.b64decode(creds_b64).decode())
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(sheet_id).worksheet("Signals")

    data = ws.get_all_records()
    total = len(data)

    victims = []
    for i, row in enumerate(data):
        status = str(row.get("status", "")).strip().upper()
        reason = str(row.get("exit_reason", "")).strip().lower()
        if status == "OPEN":
            continue
        if reason == TOMBSTONE:
            victims.append(i + 2)   # +1 header row, +1 for 1-based indexing

    open_rows = sum(
        1 for r in data
        if str(r.get("status", "")).strip().upper() == "OPEN"
    )

    print(f"Rows (excluding header): {total}")
    print(f"OPEN positions:          {open_rows}  (never touched)")
    print(f"Tombstones to purge:     {len(victims)}")
    print(f"Rows that would remain:  {total - len(victims)}")

    if not victims:
        print("Nothing to do.")
        return

    if DRY_RUN:
        print("\nDRY RUN — nothing deleted.")
        print("Re-run with DRY_RUN=false to apply.")
        return

    # Group into contiguous blocks, then delete bottom-up so that the indices
    # of not-yet-deleted rows stay valid as rows disappear beneath them.
    blocks = []
    for r in sorted(victims):
        if blocks and r == blocks[-1][1] + 1:
            blocks[-1][1] = r
        else:
            blocks.append([r, r])

    for start, end in sorted(blocks, reverse=True):
        ws.delete_rows(start, end)

    print(f"Deleted {len(victims)} rows in {len(blocks)} blocks.")
    print(f"{total - len(victims)} rows remain.")


if __name__ == "__main__":
    main()
