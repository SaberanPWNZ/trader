"""
Logging configuration.
"""
import sys
from pathlib import Path
from loguru import logger

from config.settings import settings


def setup_logging() -> None:
    """
    Configure application logging.
    
    Sets up:
    - Console output with colors
    - File logging with rotation
    - Separate error log file
    """
    # Remove default handler
    logger.remove()
    
    # Console handler
    logger.add(
        sys.stdout,
        level=settings.monitoring.log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
               "<level>{message}</level>",
        colorize=True
    )
    
    # File logging
    if settings.monitoring.log_to_file:
        log_dir = Path(settings.monitoring.log_dir)
        log_dir.mkdir(exist_ok=True)
        
        # General log file
        logger.add(
            log_dir / "trading_{time:YYYY-MM-DD}.log",
            level=settings.monitoring.log_level,
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
            rotation="00:00",  # Rotate at midnight
            retention="30 days",
            compression="gz"
        )
        
        # Error log file
        logger.add(
            log_dir / "errors_{time:YYYY-MM-DD}.log",
            level="ERROR",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
            rotation="00:00",
            retention="90 days",
            compression="gz"
        )
        
        # Trade log file (INFO and above from execution module)
        logger.add(
            log_dir / "trades_{time:YYYY-MM-DD}.log",
            level="INFO",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {message}",
            filter=lambda record: "execution" in record["name"].lower() or "trade" in record["message"].lower(),
            rotation="00:00",
            retention="365 days"
        )
    
    logger.info("Logging configured")


class TradingLogger:
    """
    Specialized logger for trading events.
    
    Provides structured logging for:
    - Signal generation
    - Order execution
    - Position updates
    - Risk events
    """
    
    def __init__(self, name: str = "trading"):
        self.name = name
    
    def signal(self, symbol: str, signal_type: str, confidence: float, **kwargs) -> None:
        """Log trading signal."""
        extra_info = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        logger.info(
            f"SIGNAL | {symbol} | {signal_type} | confidence={confidence:.2f}"
            + (f" | {extra_info}" if extra_info else "")
        )
    
    def order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        amount: float,
        price: float = None,
        status: str = "submitted",
        **kwargs
    ) -> None:
        """Log order event."""
        price_str = f"@ {price:.2f}" if price else "@ MARKET"
        logger.info(
            f"ORDER | {status.upper()} | {symbol} | {side.upper()} | "
            f"{amount:.6f} {price_str}"
        )
    
    def position(
        self,
        symbol: str,
        side: str,
        action: str,
        entry_price: float = None,
        exit_price: float = None,
        pnl: float = None
    ) -> None:
        """Log position event."""
        if action == "opened":
            logger.info(f"POSITION | OPENED | {symbol} | {side.upper()} | entry={entry_price:.2f}")
        elif action == "closed":
            pnl_str = f"+{pnl:.2f}" if pnl >= 0 else f"{pnl:.2f}"
            logger.info(
                f"POSITION | CLOSED | {symbol} | {side.upper()} | "
                f"exit={exit_price:.2f} | PnL={pnl_str}"
            )
    
    def risk_event(self, event_type: str, **kwargs) -> None:
        """Log risk event."""
        details = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        logger.warning(f"RISK | {event_type} | {details}")
    
    def error(self, component: str, message: str, **kwargs) -> None:
        """Log error event."""
        details = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        logger.error(f"ERROR | {component} | {message}" + (f" | {details}" if details else ""))


# Global trading logger instance
trading_logger = TradingLogger()
