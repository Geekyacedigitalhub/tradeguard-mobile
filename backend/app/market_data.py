import time
import json
import httpx
from .db import connection
from .strategy import Candle

KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"
KRAKEN_TICKER_URL = "https://api.kraken.com/0/public/Ticker"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/price"
YAHOO_CHART_URLS = [
    "https://query1.finance.yahoo.com/v8/finance/chart",
    "https://query2.finance.yahoo.com/v8/finance/chart",
]

YAHOO_SYMBOLS = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "JPY=X",
    "USDCHF": "CHF=X",
    "AUDUSD": "AUDUSD=X",
    "USDCAD": "CAD=X",
    "NZDUSD": "NZDUSD=X",
    # Index fallbacks when the broker/MT5 symbol name differs.
    "NAS100": "^NDX",
    "US30": "^DJI",
    "SPX500": "^GSPC",
}

YAHOO_INTERVALS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "1d": 86400}

KRAKEN_PAIRS = {
    # Accept both the internal USDT names and the scanner's USD names.
    "BTCUSD": "XBTUSD",
    "BTCUSDT": "XBTUSD",
    "ETHUSD": "ETHUSD",
    "ETHUSDT": "ETHUSD",
    "SOLUSD": "SOLUSD",
    "SOLUSDT": "SOLUSD",
    "BNBUSD": "BNBUSD",
    "BNBUSDT": "BNBUSD",
    "XRPUSD": "XRPUSD",
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
                int(row[0]),
            )
            for row in rows
        ]

async def _yahoo_candles(symbol, interval, limit):
    yahoo_symbol = YAHOO_SYMBOLS.get(symbol)
    if not yahoo_symbol:
        raise RuntimeError("Yahoo symbol is not configured for " + symbol)
    if interval not in YAHOO_INTERVALS:
        raise RuntimeError("Unsupported Yahoo interval: " + interval)

    # Yahoo limits fine-grained intraday history. Keep the requested window
    # tight for live reads and expand it only when historical validation needs
    # more candles.
    if interval in ("1m", "5m", "15m", "30m"):
        range_value = "5d" if limit <= 1000 else "60d"
    elif interval in ("1h",):
        range_value = "1mo" if limit <= 500 else "6mo"
    else:
        range_value = "1y"

    last_error = None
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for base_url in YAHOO_CHART_URLS:
            try:
                response = await client.get(
                    f"{base_url}/{yahoo_symbol}",
                    params={
                        "range": range_value,
                        "interval": interval,
                        "events": "history",
                        "includeAdjustedClose": "true",
                    },
                )
                response.raise_for_status()
                payload = response.json()
                result = (payload.get("chart") or {}).get("result")
                if not result:
                    error = ((payload.get("chart") or {}).get("error") or {}).get("description")
                    raise RuntimeError(error or "Yahoo returned no market data")

                data = result[0]
                quote = ((data.get("indicators") or {}).get("quote") or [{}])[0]
                timestamps = data.get("timestamp") or []
                opens = quote.get("open") or []
                highs = quote.get("high") or []
                lows = quote.get("low") or []
                closes = quote.get("close") or []
                volumes = quote.get("volume") or []

                candles = []
                for i, timestamp in enumerate(timestamps):
                    if i >= len(opens) or i >= len(highs) or i >= len(lows) or i >= len(closes):
                        continue
                    values = (opens[i], highs[i], lows[i], closes[i])
                    if any(v is None for v in values):
                        continue
                    volume = volumes[i] if i < len(volumes) and volumes[i] is not None else 0
                    candles.append(
                        Candle(
                            float(values[0]),
                            float(values[1]),
                            float(values[2]),
                            float(values[3]),
                            float(volume),
                            int(timestamp),
                        )
                    )

                if not candles:
                    raise RuntimeError(f"Yahoo returned no usable {interval} candles for {symbol}")
                return candles[-limit:]
            except Exception as exc:
                last_error = exc

    raise RuntimeError(f"Yahoo market data failed for {symbol} {interval}: {last_error}")

async def _binance_candles(symbol, interval, limit):
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "TradeGuard/1.0"}) as client:
        response = await client.get(
            BINANCE_KLINES_URL,
            params={"symbol": symbol, "interval": interval, "limit": limit},
        )
        response.raise_for_status()
        return [
            Candle(float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5]), int(row[0] / 1000))
            for row in response.json()
        ]


def _bridge_candles(user_id, symbol, interval, limit):
    if not user_id:
        return None
    # The Windows bridge uploads symbols sequentially. Give the 5m/15m feeds
    # enough freshness budget to survive a full scan without falling through to
    # unrelated public-market providers.
    freshness = "420 seconds" if interval == "5m" else "3600 seconds" if interval == "1h" else "1200 seconds"
    with connection() as conn:
        row=conn.execute(f"""SELECT candles,updated_at FROM bridge_market_data
                            WHERE user_id=%s AND symbol=%s AND timeframe=%s
                              AND updated_at >= now() - interval '{freshness}'""",
                         (str(user_id),symbol.upper(),interval)).fetchone()
    if not row:
        return None
    candles=row[0] if isinstance(row[0],list) else json.loads(row[0])
    if len(candles)<50:
        return None
    return [Candle(float(x["open"]),float(x["high"]),float(x["low"]),float(x["close"]),float(x.get("volume",0)),int(x.get("time")) if x.get("time") is not None else None) for x in candles[-limit:]]

async def candles_for(symbol="BTCUSDT", interval="15m", limit=200, user_id=None):
    """
    Cloud-first market data.

    TradeGuard's analysis must not depend on a Windows MT5 terminal being
    online. Public/cloud market feeds are therefore tried first. The MT5
    bridge is retained only as an optional broker-specific fallback for
    symbols that the cloud feeds cannot supply.
    """
    symbol = symbol.upper()

    # FX and index symbols use the cloud Yahoo feed first. Crypto uses Kraken
    # first. This keeps Markets/Strategy/Validation independent of a user's PC.
    if symbol in YAHOO_SYMBOLS:
        try:
            return await _yahoo_candles(symbol, interval, limit)
        except Exception:
            pass

    kraken_pair = KRAKEN_PAIRS.get(symbol)
    if kraken_pair:
        try:
            return await _kraken_candles(kraken_pair, int(interval.rstrip("m")), limit)
        except Exception:
            pass

    # MT5 remains an optional broker-specific fallback, never the primary
    # source for TradeGuard market intelligence.
    if user_id and interval in ("5m", "15m", "1h"):
        try:
            bridge = _bridge_candles(user_id, symbol, interval, limit)
            if bridge:
                return bridge
        except Exception:
            pass

    # Binance is only a last-resort crypto fallback. Never send FX, metals,
    # or index symbols to Binance.
    if symbol in KRAKEN_PAIRS:
        try:
            return await _binance_candles(symbol, interval, limit)
        except Exception:
            pass

    raise RuntimeError(
        f"Cloud market data unavailable for {symbol} {interval}; "
        "MT5 is optional and is not required for TradeGuard analysis."
    )

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
    yahoo_symbol = YAHOO_SYMBOLS.get(symbol)
    if yahoo_symbol:
        try:
            async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "TradeGuard/1.0"}) as client:
                response = await client.get(f"{YAHOO_CHART_URL}/{yahoo_symbol}", params={"range": "1d", "interval": "1m"})
                response.raise_for_status()
                payload = response.json()
                result = ((payload.get("chart") or {}).get("result") or [None])[0]
                if result:
                    quote = (((result.get("indicators") or {}).get("quote") or [{}])[0])
                    closes = [v for v in (quote.get("close") or []) if v is not None]
                    if closes:
                        return float(closes[-1])
        except Exception:
            pass
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
