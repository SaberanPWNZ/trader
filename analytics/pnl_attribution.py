"""Per-symbol / per-day / per-cause PnL attribution.

``daily_profit_report.py`` already prints aggregate per-day PnL, but it
can't answer "which symbol is bleeding?" or "are scheduled rebalances
making money or destroying it?". This module groups realized PnL deltas
along ``(date, symbol, cause)`` so that follow-up tooling can drop
unprofitable symbols from the trading set or disable a rebalance
trigger that's net-negative.

Pure / no I/O: callers (CLI scripts, dashboards) handle CSV reading and
report formatting. Mirrors the discipline established by
``analytics/pnl_recompute.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Dict, Iterable, List, Mapping, Optional, Tuple


# Causes we attribute realized PnL to. Free-form strings are kept for
# extensibility, but these constants guarantee callers can switch on
# the well-known ones without typo risk.
CAUSE_TRADE = "trade"            # vanilla grid fill (BUY pairing a SELL)
CAUSE_REBALANCE = "rebalance"    # PnL released because the grid was redrawn
CAUSE_STOP_LOSS = "stop_loss"    # forced exit by portfolio_stop_loss_percent
CAUSE_TAKE_PROFIT = "take_profit"  # portfolio TP / trailing TP
CAUSE_OTHER = "other"            # unknown event tag


@dataclass
class AttributionBucket:
    """Aggregate of realized PnL deltas for one ``(date, symbol, cause)``."""

    date: date
    symbol: str
    cause: str
    realized_pnl: float = 0.0
    trades: int = 0


@dataclass
class AttributionResult:
    """Output of :func:`attribute_pnl`."""

    buckets: List[AttributionBucket] = field(default_factory=list)

    def by_symbol(self) -> Dict[str, float]:
        """Sum realized PnL per symbol across all dates and causes."""
        out: Dict[str, float] = {}
        for b in self.buckets:
            out[b.symbol] = out.get(b.symbol, 0.0) + b.realized_pnl
        return out

    def by_cause(self) -> Dict[str, float]:
        """Sum realized PnL per cause across all dates and symbols."""
        out: Dict[str, float] = {}
        for b in self.buckets:
            out[b.cause] = out.get(b.cause, 0.0) + b.realized_pnl
        return out

    def by_date(self) -> Dict[date, float]:
        """Sum realized PnL per date across all symbols and causes."""
        out: Dict[date, float] = {}
        for b in self.buckets:
            out[b.date] = out.get(b.date, 0.0) + b.realized_pnl
        return out


def _coerce_float(value: object) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def _coerce_date(value: object) -> Optional[date]:
    """Best-effort date extraction from CSV ``timestamp`` field shapes.

    Accepts ``datetime``/``date`` instances directly, plus ISO-8601
    strings (with or without trailing ``Z``). Returns ``None`` on
    anything else so the caller can choose to skip the row.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            # Try plain YYYY-MM-DD as a last resort.
            try:
                return datetime.strptime(value[:10], "%Y-%m-%d").date()
            except ValueError:
                return None
    return None


def _normalize_cause(raw: object) -> str:
    """Map a free-form ``event``/``cause`` string to a known bucket label."""
    if raw is None or raw == "":
        return CAUSE_TRADE
    text = str(raw).strip().lower()
    if not text:
        return CAUSE_TRADE
    if "rebalance" in text:
        return CAUSE_REBALANCE
    if "stop" in text and "loss" in text:
        return CAUSE_STOP_LOSS
    if "take" in text and "profit" in text:
        return CAUSE_TAKE_PROFIT
    if "trailing" in text and ("tp" in text or "profit" in text):
        return CAUSE_TAKE_PROFIT
    if text in {"trade", "fill", "grid", "buy", "sell"}:
        return CAUSE_TRADE
    return CAUSE_OTHER


def attribute_pnl(
    rows: Iterable[Mapping[str, object]],
    *,
    realized_pnl_field: str = "realized_pnl",
    cumulative: bool = True,
) -> AttributionResult:
    """Group realized PnL by ``(date, symbol, cause)``.

    Each row is expected to carry at minimum ``timestamp``, ``symbol``,
    and the realized-PnL field named by ``realized_pnl_field``
    (default ``"realized_pnl"`` to match ``analytics/pnl_recompute``
    output and ``data/grid_trades.csv``). Rows may optionally carry a
    cause/event tag under one of: ``cause``, ``event``, ``trigger``,
    ``reason``. The first non-empty match wins; rows with none default
    to :data:`CAUSE_TRADE`.

    Args:
        rows: Iterable of trade records (list of dicts, ``csv.DictReader``,
            ``DataFrame.to_dict('records')``, etc).
        realized_pnl_field: Column name carrying *cumulative* (or
            *per-trade*, see ``cumulative``) realized PnL in USDT.
        cumulative: When ``True`` (default — matches the layout produced
            by ``recompute_trades`` and ``data/grid_trades.csv``), the
            attribution computes per-row deltas via differencing. When
            ``False``, the field is taken as the per-trade contribution
            directly. Differencing is symbol-scoped (each symbol has
            its own running total in those CSVs).

    Returns:
        ``AttributionResult`` whose ``buckets`` are sorted by
        ``(date, symbol, cause)`` for stable downstream rendering.
        Rows whose timestamp can't be parsed are skipped silently —
        attribution is informational and shouldn't crash a report.
    """
    aggregates: Dict[Tuple[date, str, str], AttributionBucket] = {}
    last_cum_per_symbol: Dict[str, float] = {}

    for row in rows:
        symbol_raw = row.get("symbol")
        if symbol_raw is None or symbol_raw == "":
            continue
        symbol = str(symbol_raw)

        d = _coerce_date(row.get("timestamp") or row.get("date"))
        if d is None:
            continue

        # Cause: first non-empty of cause/event/trigger/reason.
        cause_raw: object = ""
        for key in ("cause", "event", "trigger", "reason"):
            v = row.get(key)
            if v not in (None, ""):
                cause_raw = v
                break
        cause = _normalize_cause(cause_raw)

        raw_pnl = _coerce_float(row.get(realized_pnl_field, 0.0))
        if cumulative:
            previous = last_cum_per_symbol.get(symbol, 0.0)
            delta = raw_pnl - previous
            last_cum_per_symbol[symbol] = raw_pnl
        else:
            delta = raw_pnl

        # Skip rows that produce no movement *and* no cause-specific
        # event tag — they're carry-over snapshots, not realized trades.
        if delta == 0.0 and cause == CAUSE_TRADE:
            continue

        key = (d, symbol, cause)
        bucket = aggregates.get(key)
        if bucket is None:
            bucket = AttributionBucket(date=d, symbol=symbol, cause=cause)
            aggregates[key] = bucket
        bucket.realized_pnl += delta
        bucket.trades += 1

    ordered = sorted(
        aggregates.values(),
        key=lambda b: (b.date, b.symbol, b.cause),
    )
    return AttributionResult(buckets=ordered)
