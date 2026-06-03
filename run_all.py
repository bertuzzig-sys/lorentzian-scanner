"""
Launches both scanners in parallel threads:
  - scanner.py  → [LC+VWAP] Lorentzian + Weekly VWAP + Volume spike
  - scanner_b.py → [LC] Lorentzian only
"""

import threading
import logging
import os
import time
import schedule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Import both scan functions
from scanner import run_scan as run_scan_a
from scanner_b import run_scan as run_scan_b


def run_both():
    log.info("Launching both scanners in parallel...")
    t_a = threading.Thread(target=run_scan_a, name="ScannerA")
    t_b = threading.Thread(target=run_scan_b, name="ScannerB")
    t_a.start()
    t_b.start()
    t_a.join()
    t_b.join()
    log.info("Both scanners finished.")


if __name__ == "__main__":
    log.info("run_all.py starting — both scanners will run at scheduled time.")
    run_both()  # Run once immediately on startup
    schedule_time = os.getenv("SCAN_TIME_UTC", "23:00")
    schedule.every().day.at(schedule_time).do(run_both)
    log.info("Next scheduled run at %s UTC daily.", schedule_time)
    while True:
        schedule.run_pending()
        time.sleep(60)
