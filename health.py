"""
Scanner health checks.

`evaluate()` is a pure function over a metrics dict — no I/O, no globals — so the
whole rule set is unit-testable. scanner_b.py collects the metrics each run and
sends a Telegram alert only when something is actually wrong.

Every rule here exists because a real bug shipped undetected:
  - silent universe fallback   (ran on a stale 596-ticker hardcoded list for weeks)
  - alphabetical truncation    (universe silently lost every ticker after ~"M")
  - SPY MultiIndex failure     (regime defaulted to BULL at $0.00; RS filter corrupted)
  - dead tickers               (19% of the universe was delisted -> "No data: 107")
  - partial-bar scan           (deploy during market hours scanned incomplete data)
"""

SEV_CRIT = "CRIT"
SEV_WARN = "WARN"

# thresholds
MAX_NO_DATA_PCT   = 10.0     # dead/ungettable tickers as % of scanned
MIN_UNIVERSE_SIZE = 300
MAX_SCAN_SECONDS  = 1800     # 30 min
PC_DEFAULT        = 0.85     # the neutral fallback => fetch failed if seen exactly


def evaluate(m: dict) -> list[tuple[str, str]]:
    """
    Return [(severity, message), ...]. Empty list means healthy.
    Unknown/missing metrics are skipped rather than assumed broken.
    """
    issues: list[tuple[str, str]] = []

    def add(sev, msg):
        issues.append((sev, msg))

    # ── universe ─────────────────────────────────────────────────────────────
    src = m.get("universe_src") or ""
    if "STATIC" in src.upper():
        add(SEV_CRIT, f"Universe on STATIC fallback ({src}) — both live sources failed")
    elif "Wikipedia" in src:
        add(SEV_WARN, f"Universe fell back to {src} — Yahoo screener unavailable")

    size = m.get("universe_size")
    if isinstance(size, int) and size < MIN_UNIVERSE_SIZE:
        add(SEV_CRIT, f"Universe only {size} tickers (min {MIN_UNIVERSE_SIZE})")

    missing = m.get("canary_missing") or []
    if missing:
        add(SEV_WARN, f"Canary tickers absent from universe: {', '.join(missing)}")

    # ── data quality ─────────────────────────────────────────────────────────
    scanned, no_data = m.get("scanned"), m.get("no_data")
    if isinstance(scanned, int) and isinstance(no_data, int) and scanned > 0:
        pct = no_data / scanned * 100
        if pct > MAX_NO_DATA_PCT:
            add(SEV_WARN, f"No-data {no_data}/{scanned} ({pct:.0f}%) exceeds {MAX_NO_DATA_PCT:.0f}%")

    # ── benchmark / regime ───────────────────────────────────────────────────
    last, ema = m.get("benchmark_last"), m.get("benchmark_ema")
    if last is not None and ema is not None:
        if last <= 0 or ema <= 0:
            add(SEV_CRIT, f"Benchmark fetch broken ({m.get('benchmark','?')} "
                          f"last={last} ema={ema}) — regime and RS filter unreliable")

    # ── put/call ─────────────────────────────────────────────────────────────
    pc = m.get("pc_ratio")
    if pc is not None and abs(pc - PC_DEFAULT) < 1e-9:
        add(SEV_WARN, "P/C ratio is exactly the 0.85 fallback — CBOE fetch likely failed")

    # ── pipeline sanity ──────────────────────────────────────────────────────
    passed = m.get("passed")
    if isinstance(passed, int) and isinstance(scanned, int) and scanned > 200 and passed == 0:
        add(SEV_WARN, f"Zero tickers passed filters out of {scanned} — filters may be misconfigured")

    op, cap = m.get("open_positions"), m.get("max_positions")
    if isinstance(op, int) and isinstance(cap, int) and op > cap:
        add(SEV_CRIT, f"Open positions {op} exceeds cap {cap} — exit logic not clearing the book")

    secs = m.get("scan_seconds")
    if isinstance(secs, (int, float)) and secs > MAX_SCAN_SECONDS:
        add(SEV_WARN, f"Scan took {secs/60:.0f} min (> {MAX_SCAN_SECONDS/60:.0f}) — "
                      f"risk of overrunning the schedule")

    # ── informational feeds ──────────────────────────────────────────────────
    if m.get("premarket_snapshot") == "":
        add(SEV_WARN, "Pre-market snapshot empty")
    if m.get("rotation_text") == "":
        add(SEV_WARN, "Rotation snapshot empty — sector ETF fetch failed")

    return issues


def format_alert(issues: list[tuple[str, str]]) -> str:
    """Telegram message for a non-empty issue list."""
    crit = [msg for sev, msg in issues if sev == SEV_CRIT]
    warn = [msg for sev, msg in issues if sev == SEV_WARN]
    parts = ["\U0001f6a8 <b>Scanner health</b>"]
    if crit:
        parts.append("\n<b>CRITICAL</b>")
        parts += [f"• {c}" for c in crit]
    if warn:
        parts.append("\n<b>Warnings</b>")
        parts += [f"• {w}" for w in warn]
    return "\n".join(parts)


def summary_line(issues: list[tuple[str, str]]) -> str:
    """One-liner appended to the normal filter breakdown."""
    if not issues:
        return "✅ Health: OK"
    n_crit = sum(1 for s, _ in issues if s == SEV_CRIT)
    n_warn = len(issues) - n_crit
    bits = []
    if n_crit:
        bits.append(f"{n_crit} critical")
    if n_warn:
        bits.append(f"{n_warn} warning{'s' if n_warn > 1 else ''}")
    return "\U0001f6a8 Health: " + ", ".join(bits)
