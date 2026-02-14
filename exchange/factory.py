from typing import Optional
from loguru import logger

from config.settings import settings
from .client import ExchangeClient


def create_exchange(
    testnet: Optional[bool] = None,
    exchange_id: Optional[str] = None
) -> ExchangeClient:
    exchange_id = exchange_id or settings.exchange.name
    testnet = testnet if testnet is not None else settings.exchange.testnet
    
    if testnet:
        api_key = settings.exchange.testnet_api_key
        api_secret = settings.exchange.testnet_api_secret
    else:
        api_key = settings.exchange.api_key
        api_secret = settings.exchange.api_secret
    
    client = ExchangeClient(
        exchange_id=exchange_id,
        api_key=api_key,
        api_secret=api_secret,
        testnet=testnet,
        rate_limit=settings.exchange.rate_limit
    )
    
    mode = 'testnet' if testnet else 'mainnet'
    logger.info(f"Created {exchange_id} client ({mode})")
    
    return client


class MockExchangeClient:
    def __init__(self, initial_balance: float = 10000.0):
        self.balance = {'USDT': {'free': initial_balance, 'used': 0, 'total': initial_balance}}
        self.orders = []
        self.positions = {}
        self._prices = {}
        self._connected = False

    async def connect(self) -> None:
        self._connected = True
        logger.info("Connected to mock exchange")

    async def disconnect(self) -> None:
        self._connected = False
        logger.info("Disconnected from mock exchange")

    def set_price(self, symbol: str, price: float) -> None:
        self._prices[symbol] = price

    async def fetch_ticker(self, symbol: str) -> dict:
        price = self._prices.get(symbol, 50000.0)
        return {
            'symbol': symbol,
            'last': price,
            'bid': price * 0.9999,
            'ask': price * 1.0001,
            'high': price * 1.02,
            'low': price * 0.98,
            'volume': 1000000,
            'timestamp': None
        }

    async def fetch_balance(self) -> dict:
        return self.balance

    async def create_order(
        self,
        symbol: str,
        type: str,
        side: str,
        amount: float,
        price: float = None,
        params: dict = None
    ) -> dict:
        ticker = await self.fetch_ticker(symbol)
        exec_price = price if price else ticker['last']
        
        order_id = f"mock_{len(self.orders) + 1}"
        fee = amount * exec_price * 0.001
        
        order = {
            'id': order_id,
            'symbol': symbol,
            'type': type,
            'side': side,
            'amount': amount,
            'filled': amount,
            'price': exec_price,
            'average': exec_price,
            'status': 'closed',
            'fee': {'cost': fee, 'currency': 'USDT'},
            'timestamp': None
        }
        
        self.orders.append(order)
        
        cost = amount * exec_price
        if side == 'buy':
            self.balance['USDT']['free'] -= cost + fee
            self.balance['USDT']['used'] += cost
        else:
            self.balance['USDT']['free'] += cost - fee
            self.balance['USDT']['used'] -= cost
        
        return order

    async def cancel_order(self, order_id: str, symbol: str) -> dict:
        return {'id': order_id, 'status': 'canceled'}

    async def fetch_order(self, order_id: str, symbol: str) -> dict:
        for order in self.orders:
            if order['id'] == order_id:
                return order
        return {}

    async def fetch_open_orders(self, symbol: str = None) -> list:
        return [o for o in self.orders if o['status'] == 'open']

    @property
    def markets(self) -> dict:
        return {
            'BTC/USDT': {'symbol': 'BTC/USDT', 'base': 'BTC', 'quote': 'USDT'},
            'ETH/USDT': {'symbol': 'ETH/USDT', 'base': 'ETH', 'quote': 'USDT'}
        }

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
