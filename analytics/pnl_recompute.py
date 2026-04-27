"""Pure FIFO PnL / portfolio-value recomputation.

This module exists because three root-level ``fix_*.py`` scripts each
re-implemented the same FIFO BUY → SELL pairing, the same definition of
``total_value = balance + cost_basis + unrealized_pnl``, and the same
ROI formula. Independently. With zero tests. Drift between them was a
matter of when, not if.

Everything here is intentionally pure — no file I/O, no exchange calls —
so the CLI scripts handle CSV reading/writing/backups and this module
owns the arithmetic.

Public API
----------

``RecomputeResult``: dataclass returned by :func:`recompute_trades`,
exposing the corrected per-row records, the final per-symbol position
book (FIFO lots), the final balance, and cumulative realized PnL.

``recompute_trades(rows, *, initial_balance, current_prices=None)``:
walks through ``rows`` (each a mapping with ``symbol``/``side``/``price``/
``amount``/``value`` keys) in order and emits a corrected row for each.

``unrealized_from_positions(positions, current_prices)``: utility for
single-shot recompute against a snapshot of live prices (used by
``fix_last_record.py``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional


# Per-symbol open lot. Mirrors the dict shape used by the legacy fix
# scripts so the public surface is unchanged for callers that read
# ``RecomputeResult.positions`` directly.
@dataclass
class Lot:
    price: float
    amount: float
    value: float


@dataclass
class RecomputeResult:
    """Output of :func:`recompute_trades`."""

    rows: List[Dict[str, object]] = field(default_factory=list)
    positions: Dict[str, List[Lot]] = field(default_factory=dict)
    final_balance: float = 0.0
    realized_pnl: float = 0.0


def _coerce_float(value: object) -> float:
    """Tolerant float coercion — CSV rows arrive with string fields."""
    if value is None or value == "":
        return 0.0
    return float(value)


def unrealized_from_positions(
    positions: Mapping[str, Iterable[Lot]],
    current_prices: Mapping[str, float],
) -> "tuple[float, float]":
    """Return ``(total_unrealized_pnl, total_cost_basis)`` for ``positions``.

    Symbols missing from ``current_prices`` (or priced ≤ 0) are treated
    as "no live mark available": their cost basis still counts toward
    the running total but they contribute 0 to unrealized PnL. This
    matches the behaviour of the legacy ``fix_*.py`` scripts.
    """
    total_unrealized = 0.0
    total_cost_basis = 0.0
    for symbol, lots in positions.items():
        market_price = current_prices.get(symbol, 0.0) or 0.0
        for lot in lots:
            total_cost_basis += lot.price * lot.amount
            if market_price > 0:
                total_unrealized += (market_price - lot.price) * lot.amount
    return total_unrealized, total_cost_basis


def recompute_trades(
    rows: Iterable[Mapping[str, object]],
    *,
    initial_balance: float,
    current_prices: Optional[Mapping[str, float]] = None,
) -> RecomputeResult:
    """Recompute balance / PnL / total_value / ROI for a trade history.

    Walks ``rows`` in order, treating each entry as one filled order.
    BUY rows debit ``balance`` and append a lot to the symbol's FIFO
    queue; SELL rows credit ``balance`` and pop the oldest matching lot,
    adding ``(sell_price - lot.price) * lot.amount`` to ``realized_pnl``.

    Unrealized PnL on each row is computed against the *most-recent
    seen trade price per symbol* — i.e. trades are their own "live
    mark" within the historical playback. After playback, callers can
    optionally pass ``current_prices`` to remark all open lots at live
    quotes by reading ``RecomputeResult.positions`` and feeding it to
    :func:`unrealized_from_positions`.

    Args:
        rows: Iterable of mappings with at least ``symbol``, ``side``,
            ``price``, ``amount``, ``value`` keys. Other keys are
            preserved when present (``timestamp`` is propagated).
        initial_balance: Starting USDT balance for the account.
        current_prices: Optional override mapping ``symbol -> price``.
            When provided, *every* row's unrealized PnL is computed
            against these prices instead of the playback price (used
            for hypothetical "what if I marked everything to current
            quotes" reports).

    Returns:
        ``RecomputeResult`` with the corrected per-row records (same
        order as input), the residual position book, the final cash
        balance, and cumulative realized PnL.

    Notes:
        SELL with no matching open lot is a no-op for the position
        book (there's nothing to pop), but still credits ``balance`` —
        this preserves balance conservation against legacy CSVs that
        may contain orphan SELLs from manual interventions.
    """
    balance = float(initial_balance)
    realized_pnl = 0.0
    positions: Dict[str, List[Lot]] = {}
    last_seen_price: Dict[str, float] = {}

    out_rows: List[Dict[str, object]] = []

    for trade in rows:
        symbol = str(trade["symbol"])
        side = str(trade["side"]).upper()
        price = _coerce_float(trade["price"])
        amount = _coerce_float(trade["amount"])
        value = _coerce_float(trade.get("value", price * amount))

        if side == "BUY":
            balance -= value
            positions.setdefault(symbol, []).append(
                Lot(price=price, amount=amount, value=value)
            )
        elif side == "SELL":
            balance += value
            lots = positions.get(symbol, [])
            if lots:
                lot = lots.pop(0)
                realized_pnl += (price - lot.price) * lot.amount
        # Unknown sides are skipped (no balance change, no position change).

        last_seen_price[symbol] = price

        # Mark-to-market source: explicit override snapshot, else the
        # most-recent trade price seen per symbol.
        prices_for_mark = current_prices if current_prices is not None else last_seen_price
        unrealized, cost_basis = unrealized_from_positions(positions, prices_for_mark)

        total_value = balance + cost_basis + unrealized
        roi_percent = (
            ((total_value - initial_balance) / initial_balance) * 100.0
            if initial_balance > 0
            else 0.0
        )

        out_rows.append(
            {
                "timestamp": trade.get("timestamp"),
                "symbol": symbol,
                "side": side,
                "price": price,
                "amount": amount,
                "value": value,
                "realized_pnl": realized_pnl,
                "unrealized_pnl": unrealized,
                "balance": balance,
                "total_value": total_value,
                "roi_percent": roi_percent,
            }
        )

    return RecomputeResult(
        rows=out_rows,
        positions=positions,
        final_balance=balance,
        realized_pnl=realized_pnl,
    )
