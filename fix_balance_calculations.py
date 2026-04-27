#!/usr/bin/env python3
"""Recompute balance / PnL / total_value / ROI for ``data/grid_trades.csv``.

Thin CLI wrapper around :func:`analytics.pnl_recompute.recompute_trades`
— see that module for the actual math. This script handles only the
file-system concerns (backup, CSV read/write, summary print).
"""
import csv
import shutil
from datetime import datetime

from analytics.pnl_recompute import recompute_trades

OUTPUT_FIELDS = [
    "timestamp",
    "symbol",
    "side",
    "price",
    "amount",
    "value",
    "realized_pnl",
    "unrealized_pnl",
    "balance",
    "total_value",
    "roi_percent",
]


def fix_balance_calculations(initial_balance: float = 1000.0) -> None:
    trades_file = "data/grid_trades.csv"
    backup_file = (
        f"data/grid_trades_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )

    shutil.copy(trades_file, backup_file)
    print(f"✅ Backup created: {backup_file}")

    with open(trades_file, "r") as f:
        trades = list(csv.DictReader(f))

    result = recompute_trades(trades, initial_balance=initial_balance)

    # Round monetary fields to 10 decimals to match legacy CSV format.
    rows_for_csv = []
    for row in result.rows:
        rows_for_csv.append(
            {
                "timestamp": row["timestamp"],
                "symbol": row["symbol"],
                "side": row["side"],
                "price": row["price"],
                "amount": row["amount"],
                "value": row["value"],
                "realized_pnl": round(row["realized_pnl"], 10),
                "unrealized_pnl": round(row["unrealized_pnl"], 10),
                "balance": round(row["balance"], 10),
                "total_value": round(row["total_value"], 10),
                "roi_percent": round(row["roi_percent"], 10),
            }
        )

    with open(trades_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows_for_csv)

    print(f"✅ Виправлено {len(rows_for_csv)} записів")

    last = rows_for_csv[-1]
    print(f"\n📊 Підсумок після виправлення:")
    print(f"💰 Balance (готівка):    ${last['balance']:.2f}")
    print(f"📈 Realized PnL:         ${last['realized_pnl']:.2f}")
    print(f"📊 Unrealized PnL:       ${last['unrealized_pnl']:.2f}")
    print(f"💎 Total Value:          ${last['total_value']:.2f}")
    print(f"📊 ROI:                  {last['roi_percent']:.2f}%")

    print(f"\n🔍 Відкриті позиції:")
    total_cost = 0.0
    for symbol, lots in result.positions.items():
        if lots:
            cost = sum(lot.price * lot.amount for lot in lots)
            total_cost += cost
            print(f"  {symbol}: {len(lots)} позицій, вартість: ${cost:.2f}")

    print(
        f"\n✅ Перевірка: Balance + Cost Basis = "
        f"${last['balance']:.2f} + ${total_cost:.2f} = "
        f"${last['balance'] + total_cost:.2f}"
    )


if __name__ == "__main__":
    fix_balance_calculations()
