import httpx
from .strategy import Candle

KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"
KRAKEN_TICKER_URL = "https://api.kraken.com/0/public/Ticker"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/price"

KRAKEN_PAIRS = {
    "BTCUSDT": "XBTUSD",
    "ETHUSDT": "ETHUSD",
    "SOLUSDT": "SOLUSD",
    "BNBUSDT": "BNBUSD",
    "XRPUSDT": "XRPUSD",
}

def _kraken_result(result):
    for key, value in result.items():
        if key != "last":
            return value
    raise RuntimeError("Kraken returned no market data")

async def _kraken_candles(pair, interval_minutes, limit):
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "TradeGuard/1.0"}) as client:
        response = await client.get(
            KRAKEN_OHLC_URL,
            params={"pair": pair, "interval": interval_minutes},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError("Kraken: " + "; ".join(payload["error"]))
        rows = _kraken_result(payload.get("result") or {})
        rows = rows[-limit:]
        return [
            Candle(
                float(row[1]),
                float(row[2]),
                float(row[3]),
                float(row[4]),
                float(row[6]),
            )
            for row in rows
        ]

async def _binance_candles(symbol, interval, limit):
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "TradeGuard/1.0"}) as client:
        response = await client.get(
            BINANCE_KLINES_URL,
            params={"symbol": symbol, "interval": interval, "limit": limit},
        )
        response.raise_for_status()
        return [
            Candle(float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5]))
            for row in response.json()
        ]

async def candles_for(symbol="BTCUSDT", interval="15m", limit=200):
    kraken_pair = KRAKEN_PAIRS.get(symbol)
    if kraken_pair:
        try:
            return await _kraken_candles(kraken_pair, int(interval.rstrip("m")), limit)
        except Exception:
            pass
    return await _binance_candles(symbol, interval, limit)

async def _kraken_price(pair):
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "TradeGuard/1.0"}) as client:
        response = await client.get(KRAKEN_TICKER_URL, params={"pair": pair})
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError("Kraken: " + "; ".join(payload["error"]))
        ticker = _kraken_result(payload.get("result") or {})
        return float(ticker["c"][0])

async def latest_price(symbol):
    kraken_pair = KRAKEN_PAIRS.get(symbol)
    if kraken_pair:
        try:
            return await _kraken_price(kraken_pair)
        except Exception:
            pass
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "TradeGuard/1.0"}) as client:
        response = await client.get(BINANCE_TICKER_URL, params={"symbol": symbol})
        response.raise_for_status()
        return float(response.json()["price"])
