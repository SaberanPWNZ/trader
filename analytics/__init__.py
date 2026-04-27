"""Analytics helpers — pure (no I/O) post-trade math.

Currently houses :mod:`analytics.pnl_recompute`, used by both the live
trader's diagnostics and the root-level ``fix_*.py`` CSV reprocessing
scripts so the FIFO / total-value formula has exactly one source of truth.

Also exposes :mod:`analytics.pnl_attribution` for per-symbol /
per-cause realized-PnL grouping and :mod:`analytics.slippage` for
offline execution-quality measurement.
"""
