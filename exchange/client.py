import asyncio
from datetime import datetime
from typing import Optional, Dict, List, Any
from loguru import logger
import ccxt.async_support as ccxt


class ExchangeClient:
    def __init__(
        self,
        exchange_id: str = "binance",
        api_key: str = "",
        api_secret: str = "",
        private_key: str = "",
        testnet: bool = True,
        rate_limit: int = 1200
    ):
        self.exchange_id = exchange_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.private_key = private_key
        self.testnet = testnet
        self.rate_limit = rate_limit
        self._exchange: Optional[ccxt.Exchange] = None
        self._last_request_time: float = 0
        self._min_request_interval: float = 60.0 / rate_limit

    async def connect(self) -> None:
        exchange_class = getattr(ccxt, self.exchange_id)
        
        config = {
            'apiKey': self.api_key,
            'enableRateLimit': True,
            'rateLimit': int(60000 / self.rate_limit),
            'options': {
                'defaultType': 'spot',
                'adjustForTimeDifference': True
            }
        }
        
        if self.private_key:
            # Ed25519 private key - wrap in PEM format if needed
            private_key = self.private_key.strip()
            if not private_key.startswith('-----BEGIN'):
                private_key = f"-----BEGIN PRIVATE KEY-----\n{private_key}\n-----END PRIVATE KEY-----"
            
            config['secret'] = private_key
            logger.info("Using Ed25519 private key for authentication")
        elif self.api_secret:
            config['secret'] = self.api_secret
            logger.info("Using HMAC secret for authentication")
        else:
            raise ValueError("Either api_secret or private_key must be provided")
        
        if self.testnet:
            config['sandbox'] = True
            if self.exchange_id == 'binance':
                config['options']['defaultType'] = 'spot'
                config['urls'] = {
                    'api': {
                        'public': 'https://testnet.binance.vision/api/v3',
                        'private': 'https://testnet.binance.vision/api/v3',
                    }
                }
        
        self._exchange = exchange_class(config)
        
        await self._exchange.load_markets()
        
        logger.info(f"Connected to {self.exchange_id} ({'testnet' if self.testnet else 'mainnet'})")
        logger.info(f"Available markets: {len(self._exchange.markets)}")

    async def disconnect(self) -> None:
        if self._exchange:
            await self._exchange.close()
            self._exchange = None
            logger.info(f"Disconnected from {self.exchange_id}")

    async def _rate_limit_wait(self) -> None:
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < self._min_request_interval:
            await asyncio.sleep(self._min_request_interval - elapsed)
        self._last_request_time = asyncio.get_event_loop().time()

    async def _retry_request(self, func, *args, max_retries: int = 3, **kwargs):
        """Retry API requests with exponential backoff"""
        for attempt in range(max_retries):
            try:
                return await func(*args, **kwargs)
            except ccxt.RateLimitExceeded as e:
                if attempt == max_retries - 1:
                    raise
                wait_time = 2 ** attempt
                logger.warning(f"Rate limit exceeded, waiting {wait_time}s (attempt {attempt+1}/{max_retries})")
                await asyncio.sleep(wait_time)
            except ccxt.NetworkError as e:
                if attempt == max_retries - 1:
                    raise
                wait_time = 2 ** attempt
                logger.warning(f"Network error: {e}, retrying in {wait_time}s (attempt {attempt+1}/{max_retries})")
                await asyncio.sleep(wait_time)
            except ccxt.ExchangeError as e:
                logger.error(f"Exchange error: {e}")
                raise
            except Exception as e:
                logger.error(f"Unexpected error in API request: {e}")
                raise

    async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        await self._rate_limit_wait()
        return await self._retry_request(self._exchange.fetch_ticker, symbol)

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = '1h',
        since: Optional[int] = None,
        limit: int = 500
    ) -> List[List]:
        await self._rate_limit_wait()
        return await self._retry_request(self._exchange.fetch_ohlcv, symbol, timeframe, since, limit)

    async def fetch_balance(self) -> Dict[str, Any]:
        await self._rate_limit_wait()
        return await self._retry_request(self._exchange.fetch_balance)

    async def fetch_positions(self, symbols: Optional[List[str]] = None) -> List[Dict]:
        await self._rate_limit_wait()
        try:
            return await self._exchange.fetch_positions(symbols)
        except Exception:
            return []

    async def create_order(
        self,
        symbol: str,
        type: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        await self._rate_limit_wait()
        params = params or {}
        
        logger.info(f"Creating {type} {side} order: {amount} {symbol} @ {price or 'market'}")
        
        try:
            order = await self._retry_request(
                self._exchange.create_order,
                symbol=symbol,
                type=type,
                side=side,
                amount=amount,
                price=price,
                params=params
            )
            logger.info(f"Order created: {order['id']} status={order['status']}")
            return order
        except ccxt.InsufficientFunds as e:
            logger.error(f"Insufficient funds for {side} order: {e}")
            raise
        except ccxt.InvalidOrder as e:
            logger.error(f"Invalid order parameters: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to create order: {e}")
            raise

    async def cancel_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        await self._rate_limit_wait()
        logger.info(f"Cancelling order {order_id} for {symbol}")
        try:
            return await self._retry_request(self._exchange.cancel_order, order_id, symbol)
        except ccxt.OrderNotFound:
            logger.warning(f"Order {order_id} not found, may be already filled or cancelled")
            return {'id': order_id, 'status': 'not_found'}
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            raise

    async def fetch_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        await self._rate_limit_wait()
        return await self._exchange.fetch_order(order_id, symbol)

    async def fetch_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        await self._rate_limit_wait()
        return await self._exchange.fetch_open_orders(symbol)

    async def fetch_my_trades(
        self,
        symbol: str,
        since: Optional[int] = None,
        limit: int = 50
    ) -> List[Dict]:
        await self._rate_limit_wait()
        return await self._exchange.fetch_my_trades(symbol, since, limit)

    async def get_current_price(self, symbol: str) -> float:
        ticker = await self.fetch_ticker(symbol)
        return ticker['last']

    async def get_available_balance(self, currency: str = 'USDT') -> float:
        balance = await self.fetch_balance()
        return balance.get(currency, {}).get('free', 0.0)

    async def validate_connection(self) -> Dict[str, Any]:
        try:
            balance = await self.fetch_balance()
            return {
                'success': True,
                'exchange': self.exchange_id,
                'testnet': self.testnet,
                'balance': balance.get('USDT', {}).get('total', 0),
                'timestamp': datetime.utcnow().isoformat()
            }
        except Exception as e:
            return {
                'success': False,
                'exchange': self.exchange_id,
                'testnet': self.testnet,
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            }

    @property
    def markets(self) -> Dict:
        return self._exchange.markets if self._exchange else {}

    @property
    def is_connected(self) -> bool:
        return self._exchange is not None

    def get_market_info(self, symbol: str) -> Optional[Dict]:
        if self._exchange and symbol in self._exchange.markets:
            return self._exchange.markets[symbol]
        return None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
