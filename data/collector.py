"""
Data collector for exchange data acquisition.
"""
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
import pandas as pd
import ccxt.async_support as ccxt
from loguru import logger

from config.settings import settings
from .models import OHLCV
from .cache import DataCache


class DataCollector:
    """
    Handles data acquisition from cryptocurrency exchanges.
    
    Features:
    - OHLCV (candle) data
    - Order book data
    - Recent trades
    - Account balances
    - Rate limit protection
    - Data caching
    """
    
    def __init__(self):
        self.exchange: Optional[ccxt.Exchange] = None
        self.cache = DataCache()
        self._rate_limiter = asyncio.Semaphore(10)
        
    async def connect(self) -> None:
        """Initialize exchange connection."""
        exchange_config = {
            'apiKey': settings.exchange.api_key,
            'secret': settings.exchange.api_secret,
            'timeout': settings.exchange.timeout,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
            }
        }
        
        if settings.exchange.testnet:
            exchange_config['options']['sandboxMode'] = True
        
        exchange_class = getattr(ccxt, settings.exchange.name)
        self.exchange = exchange_class(exchange_config)
        
        if settings.exchange.testnet:
            self.exchange.set_sandbox_mode(True)
        
        await self.exchange.load_markets()
        logger.info(f"Connected to {settings.exchange.name} ({'testnet' if settings.exchange.testnet else 'live'})")
    
    async def disconnect(self) -> None:
        """Close exchange connection."""
        if self.exchange:
            await self.exchange.close()
            logger.info("Disconnected from exchange")
    
    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 500,
        since: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Fetch OHLCV candle data.
        
        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            timeframe: Candle timeframe (e.g., '15m', '1h')
            limit: Number of candles to fetch
            since: Start timestamp in milliseconds
            
        Returns:
            DataFrame with OHLCV data
        """
        cache_key = f"ohlcv_{symbol}_{timeframe}"
        cached_data = self.cache.get(cache_key)
        
        if cached_data is not None and since is None:
            logger.debug(f"Using cached OHLCV data for {symbol}")
            return cached_data
        
        async with self._rate_limiter:
            try:
                ohlcv = await self.exchange.fetch_ohlcv(
                    symbol, timeframe, since=since, limit=limit
                )
                
                df = pd.DataFrame(
                    ohlcv,
                    columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
                )
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
                df['symbol'] = symbol
                df['timeframe'] = timeframe
                
                # Cache the data
                self.cache.set(cache_key, df, ttl=60)  # Cache for 60 seconds
                
                logger.debug(f"Fetched {len(df)} candles for {symbol} {timeframe}")
                return df
                
            except Exception as e:
                logger.error(f"Error fetching OHLCV for {symbol}: {e}")
                raise
    
    async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        """Fetch current ticker data for a symbol."""
        async with self._rate_limiter:
            try:
                ticker = await self.exchange.fetch_ticker(symbol)
                logger.debug(f"Fetched ticker for {symbol}: {ticker['last']}")
                return ticker
            except Exception as e:
                logger.error(f"Error fetching ticker for {symbol}: {e}")
                raise
    
    async def fetch_order_book(
        self,
        symbol: str,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Fetch order book data."""
        async with self._rate_limiter:
            try:
                order_book = await self.exchange.fetch_order_book(symbol, limit)
                return order_book
            except Exception as e:
                logger.error(f"Error fetching order book for {symbol}: {e}")
                raise
    
    async def fetch_recent_trades(
        self,
        symbol: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Fetch recent trades for a symbol."""
        async with self._rate_limiter:
            try:
                trades = await self.exchange.fetch_trades(symbol, limit=limit)
                return trades
            except Exception as e:
                logger.error(f"Error fetching trades for {symbol}: {e}")
                raise
    
    async def fetch_balance(self) -> Dict[str, Any]:
        """Fetch account balances."""
        async with self._rate_limiter:
            try:
                balance = await self.exchange.fetch_balance()
                logger.debug(f"Fetched balance: {balance['total']}")
                return balance
            except Exception as e:
                logger.error(f"Error fetching balance: {e}")
                raise
    
    async def fetch_historical_data(
        self,
        symbol: str,
        timeframe: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV data for backtesting.
        
        Args:
            symbol: Trading pair
            timeframe: Candle timeframe
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            
        Returns:
            DataFrame with historical OHLCV data
        """
        start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
        end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000)
        
        all_data = []
        current_ts = start_ts
        
        while current_ts < end_ts:
            df = await self.fetch_ohlcv(
                symbol, timeframe, limit=1000, since=current_ts
            )
            
            if df.empty:
                break
                
            all_data.append(df)
            current_ts = int(df.index[-1].timestamp() * 1000) + 1
            
            # Rate limit protection
            await asyncio.sleep(0.5)
        
        if all_data:
            result = pd.concat(all_data)
            result = result[~result.index.duplicated(keep='first')]
            result = result[result.index <= pd.Timestamp(end_date)]
            logger.info(f"Fetched {len(result)} historical candles for {symbol}")
            return result
        
        return pd.DataFrame()
    
    async def stream_candles(
        self,
        symbol: str,
        timeframe: str,
        callback
    ) -> None:
        """
        Stream real-time candle data.
        
        Args:
            symbol: Trading pair
            timeframe: Candle timeframe
            callback: Async callback function for new candles
        """
        logger.info(f"Starting candle stream for {symbol} {timeframe}")
        
        last_timestamp = None
        
        while True:
            try:
                df = await self.fetch_ohlcv(symbol, timeframe, limit=2)
                
                if not df.empty:
                    current_timestamp = df.index[-1]
                    
                    if last_timestamp is None or current_timestamp > last_timestamp:
                        last_timestamp = current_timestamp
                        await callback(df.iloc[-1])
                
                # Wait for next candle
                await asyncio.sleep(10)
                
            except Exception as e:
                logger.error(f"Error in candle stream: {e}")
                await asyncio.sleep(30)
