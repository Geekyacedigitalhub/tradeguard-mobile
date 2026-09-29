import httpx
from .strategy import Candle

BINANCE_URL="https://api.binance.com/api/v3/klines"

async def candles_for(symbol="BTCUSDT", interval="15m", limit=200):
    async with httpx.AsyncClient(timeout=10) as client:
        r=await client.get(BINANCE_URL, params={"symbol":symbol,"interval":interval,"limit":limit})
        r.raise_for_status()
        return [Candle(float(x[1]),float(x[2]),float(x[3]),float(x[4]),float(x[5])) for x in r.json()]

async def latest_price(symbol):
    async with httpx.AsyncClient(timeout=10) as client:
        r=await client.get("https://api.binance.com/api/v3/ticker/price", params={"symbol":symbol})
        r.raise_for_status()
        return float(r.json()["price"])
