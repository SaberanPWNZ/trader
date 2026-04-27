"""
ExchangeApiGuard: thin async wrapper that funnels every exchange API
call through ``RiskManager.record_api_error`` / ``record_api_success``.

The live grid trader has 30+ direct ``self.exchange.<method>(...)`` call
sites. Rather than instrument each one, wrap the exchange object once
and forward unchanged. Public exchange methods (the ones that actually
hit the network) are intercepted: success resets the consecutive
API-error counter on the shared ``RiskManager``, failure increments it
and — if the configured threshold is reached — activates the kill
switch, after which we invoke the optional ``on_kill_switch`` callback
so the trading loop can short-circuit on the next tick.

Non-API attribute access (``markets``, ``is_connected``, ``_exchange``
etc.) is forwarded verbatim via ``__getattr__``.
"""
from typing import Awaitable, Callable, Iterable, Optional

from loguru import logger

from risk.manager import RiskManager


# Methods on ``ExchangeClient`` (and the mock) that perform network I/O.
# Exposed as a class attribute so tests can patch / extend it without
# subclassing.
_DEFAULT_GUARDED_METHODS: frozenset = frozenset({
    "fetch_ticker",
    "fetch_ohlcv",
    "fetch_balance",
    "fetch_positions",
    "fetch_order",
    "fetch_open_orders",
    "fetch_my_trades",
    "create_order",
    "cancel_order",
})


class ExchangeApiGuard:
    """Wrap an exchange client and record API success / failure on a RiskManager.

    Args:
        exchange: The underlying ``ExchangeClient`` (or mock) instance.
        risk_manager: ``RiskManager`` whose ``state.consecutive_api_errors``
            counter is updated on every guarded call.
        on_kill_switch: Optional callback invoked the first time
            ``record_api_error`` activates the kill switch. Use it to flip
            an emergency-stop flag in the calling trader without the
            guard needing to know about higher-level state.
        guarded_methods: Override the set of method names that are
            wrapped. Defaults to all real network-hitting methods.
    """

    def __init__(
        self,
        exchange,
        risk_manager: RiskManager,
        on_kill_switch: Optional[Callable[[], None]] = None,
        guarded_methods: Optional[Iterable[str]] = None,
    ) -> None:
        self._exchange = exchange
        self._risk_manager = risk_manager
        self._on_kill_switch = on_kill_switch
        self._guarded: frozenset = (
            frozenset(guarded_methods)
            if guarded_methods is not None
            else _DEFAULT_GUARDED_METHODS
        )

    # ------------------------------------------------------------------
    # Forwarding
    # ------------------------------------------------------------------
    def __getattr__(self, name: str):
        # ``__getattr__`` is only consulted when normal lookup fails, so
        # everything in ``__init__`` (``_exchange`` etc.) is reached via
        # ``__getattribute__`` first and never recurses through here.
        attr = getattr(self._exchange, name)
        if name in self._guarded and callable(attr):
            return self._wrap(name, attr)
        return attr

    def _wrap(self, name: str, fn: Callable[..., Awaitable]):
        guard = self

        async def guarded(*args, **kwargs):
            try:
                result = await fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - re-raised below
                guard._record_error(name, exc)
                raise
            guard._risk_manager.record_api_success()
            return result

        guarded.__name__ = name
        guarded.__qualname__ = f"ExchangeApiGuard.{name}"
        return guarded

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _record_error(self, method: str, exc: BaseException) -> None:
        reason = f"{method}: {type(exc).__name__}: {exc}"
        # Truncate the reason — risk events log it verbatim and ccxt
        # exception messages can include the full HTTP response body.
        if len(reason) > 240:
            reason = reason[:237] + "..."
        was_already_killed = self._risk_manager.state.kill_switch_active
        activated = self._risk_manager.record_api_error(reason)
        if activated and not was_already_killed and self._on_kill_switch:
            try:
                self._on_kill_switch()
            except Exception as cb_err:  # pragma: no cover — defensive
                logger.error(f"on_kill_switch callback failed: {cb_err}")

    # ------------------------------------------------------------------
    # Convenience accessors used by traders that previously held a real
    # ``ExchangeClient`` reference.
    # ------------------------------------------------------------------
    @property
    def inner(self):
        """Return the wrapped exchange (for tests / introspection)."""
        return self._exchange
