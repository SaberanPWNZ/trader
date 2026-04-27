#!/usr/bin/env python3
"""Fix unrealized_pnl / total_value / roi_percent in ``data/grid_trades.csv``.

Legacy variant of the recompute that *trusts* the existing ``balance``
and ``realized_pnl`` columns and only re-marks open positions with the
last trade price seen per symbol (the original implementation only
marked the symbol that was just traded, leaving stale lots at 0 — that
bug is fixed here by using ``analytics.pnl_recompute``).
"""
import csv
import shutil
from datetime import datetime

from analytics.pnl_recompute import recompute_trades


def fix_csv_calculations(initial_balance: float = 1000.0) -> None:
    trades_file = "data/grid_trades.csv"
    backup_file = (
        f"data/grid_trades_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )

    shutil.copy(trades_file, backup_file)
    print(f"✅ Backup created: {backup_file}")

    with open(trades_file, "r") as f:
        trades = list(csv.DictReader(f))

    print(f"📊 Processing {len(trades)} trades...")

    result = recompute_trades(trades, initial_balance=initial_balance)

    # Preserve the legacy semantic: trust the on-disk ``balance`` and
    # ``realized_pnl`` columns; only overwrite the marking-derived
    # fields. (Use the helper's ``unrealized_pnl`` / row-relative
    # ``total_value`` / ``roi_percent`` but rebuild the latter two off
    # the original balance + realized to stay consistent with whatever
    # the live trader recorded.)
    for original, recomputed in zip(trades, result.rows):
        original_balance = float(original.get("balance", 0) or 0)
        unrealized = recomputed["unrealized_pnl"]
        # cost_basis = total_value - balance - unrealized (from helper);
        # we re-derive against the on-disk balance.
        cost_basis = recomputed["total_value"] - recomputed["balance"] - unrealized
        correct_total_value = original_balance + cost_basis + unrealized
        correct_roi = (
            ((correct_total_value - initial_balance) / initial_balance) * 100.0
            if initial_balance > 0
            else 0.0
        )
        original["unrealized_pnl"] = f"{unrealized}"
        original["total_value"] = f"{correct_total_value}"
        original["roi_percent"] = f"{correct_roi}"

    with open(trades_file, "w", newline="") as f:
        if trades:
            writer = csv.DictWriter(f, fieldnames=trades[0].keys())
            writer.writeheader()
            writer.writerows(trades)

    print(f"✅ Fixed {len(trades)} records")

    if trades:
        last = trades[-1]
        print(f"\n📈 Last trade:")
        print(f"  Balance: ${float(last['balance']):.2f}")
        print(f"  Total Value: ${float(last['total_value']):.2f}")
        print(f"  ROI: {float(last['roi_percent']):.2f}%")
        print(f"  Realized: ${float(last['realized_pnl']):.2f}")
        print(f"  Unrealized: ${float(last['unrealized_pnl']):.2f}")


if __name__ == "__main__":
    fix_csv_calculations()
