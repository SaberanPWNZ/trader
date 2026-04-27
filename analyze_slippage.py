#!/usr/bin/env python3
"""Slippage report for ``data/grid_live_trades.csv``.

Thin CLI wrapper around :mod:`analytics.slippage`. Reads the live
trades CSV, drops rows without a recorded ``expected_price`` (fills
that pre-date Step A's expected-price tracking, manual orders, or
restarts) and prints overall + per-symbol stats:

    count, mean bps, max adverse bps, max favourable bps

Sign convention matches :func:`analytics.slippage.compute_slippage_bps`
— positive bps are *adverse* (worse than expected), negative are
favourable.

Usage::

    python analyze_slippage.py
    python analyze_slippage.py --file data/grid_live_trades.csv

The script is read-only — no files are modified.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from typing import Dict, List, Optional

from analytics.slippage import (
    SlippageStats,
    compute_slippage_bps,
    summarize_slippage,
)


DEFAULT_PATH = "data/grid_live_trades.csv"


def _parse_float(value: object) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def collect_slippage_bps(
    rows,
) -> Dict[str, List[float]]:
    """Group bps measurements by symbol.

    Rows whose ``expected_price`` or ``price`` cannot be parsed, or
    whose ``side`` is empty, are skipped silently — slippage reporting
    is informational and shouldn't crash on a half-written CSV.
    """
    by_symbol: Dict[str, List[float]] = {}
    for row in rows:
        symbol = (row.get("symbol") or "").strip()
        if not symbol:
            continue
        side = (row.get("side") or "").strip()
        if not side:
            continue
        expected = _parse_float(row.get("expected_price"))
        actual = _parse_float(row.get("price"))
        if expected is None or actual is None:
            continue
        bps = compute_slippage_bps(
            expected_price=expected,
            actual_price=actual,
            side=side,
        )
        if bps is None:
            continue
        by_symbol.setdefault(symbol, []).append(bps)
    return by_symbol


def _format_stats(label: str, stats: SlippageStats) -> str:
    if stats.count == 0:
        return f"  {label:<20s} (no data)"
    return (
        f"  {label:<20s} n={stats.count:>4d} "
        f"mean={stats.mean_bps:+7.2f}bps "
        f"max_adverse={stats.max_adverse_bps:6.2f}bps "
        f"max_favourable={stats.max_favourable_bps:6.2f}bps"
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--file",
        "-f",
        default=DEFAULT_PATH,
        help=f"Path to the live trades CSV (default: {DEFAULT_PATH}).",
    )
    args = parser.parse_args(argv)

    if not os.path.exists(args.file):
        print(f"❌ File not found: {args.file}", file=sys.stderr)
        return 1

    with open(args.file, "r", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or "expected_price" not in reader.fieldnames:
            print(
                f"❌ {args.file} has no 'expected_price' column. "
                "It pre-dates expected-price tracking; nothing to report.",
                file=sys.stderr,
            )
            return 1
        rows = list(reader)

    by_symbol = collect_slippage_bps(rows)

    print(f"📈 Slippage report: {args.file}")
    print(f"   Rows scanned: {len(rows)}")

    all_bps: List[float] = []
    for vals in by_symbol.values():
        all_bps.extend(vals)

    overall = summarize_slippage(all_bps)
    if overall.count == 0:
        print("\n  No rows with both 'expected_price' and 'price' parseable — "
              "report is empty.")
        return 0

    print()
    print(_format_stats("OVERALL", overall))
    print()
    print("  Per-symbol:")
    for symbol in sorted(by_symbol):
        stats = summarize_slippage(by_symbol[symbol])
        print(_format_stats(symbol, stats))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
