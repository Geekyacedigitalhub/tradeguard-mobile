import time
import asyncio
import json
import os
from datetime import datetime, timezone
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
    "XAUUSD": "GC=F",
    "XAGUSD": "SI=F",
    # Index fallbacks when the broker/MT5 symbol name differs.
    "NAS100": "^NDX",
    "US30": "^DJI",
    "SPX500": "^GSPC",
}

YAHOO_INTERVALS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "1d": 86400}

# Short-lived latest-price cache for position marking. This avoids repeatedly
# downloading the same quote data while the 15s position monitor is running.
_LATEST_PRICE_CACHE = {}
_LATEST_PRICE_CACHE_TTL = 20

# Process-local cache prevents every market scan from re-reading hundreds of
# candles from Neon. The cloud sync job remains the source of fresh candles.
_STORED_CANDLE_CACHE = {}
_STORED_CANDLE_CACHE_TTL = 240
# Deduplicate simultaneous provider requests for the same candle set.
_CLOUD_FETCH_TASKS = {}
# Prevent overlapping full cloud-sync runs from downloading the same windows twice.
_CLOUD_SYNC_TASK = None

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

def _ensure_cloud_candle_table():
    with connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cloud_market_candles (
                symbol TEXT NOT NULL, timeframe TEXT NOT NULL, candle_time BIGINT NOT NULL,
                open NUMERIC NOT NULL, high NUMERIC NOT NULL, low NUMERIC NOT NULL, close NUMERIC NOT NULL,
                volume NUMERIC NOT NULL DEFAULT 0, source TEXT NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (symbol,timeframe,candle_time)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS cloud_market_candles_lookup_idx ON cloud_market_candles(symbol,timeframe,candle_time DESC)")

def _store_cloud_candles(symbol, interval, candles, source="cloud"):
    if not candles: return 0
    rows=[(symbol.upper(),interval,int(c.time),float(c.open),float(c.high),float(c.low),float(c.close),float(c.volume or 0),source) for c in candles if c.time is not None]
    if not rows: return 0

    # The provider returns a rolling window, but almost all of those candles
    # already exist in Neon. Only write the current/new candles so cloud sync
    # does not repeatedly transfer hundreds of unchanged rows.
    with connection() as conn:
        latest=conn.execute(
            "SELECT MAX(candle_time) FROM cloud_market_candles WHERE symbol=%s AND timeframe=%s",
            (symbol.upper(),interval),
        ).fetchone()
        latest_time=int(latest[0]) if latest and latest[0] is not None else None
        if latest_time is not None:
            rows=[row for row in rows if row[2] >= latest_time]
        if not rows:
            return 0
        with conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO cloud_market_candles (symbol,timeframe,candle_time,open,high,low,close,volume,source,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (symbol,timeframe,candle_time) DO UPDATE SET open=EXCLUDED.open,high=EXCLUDED.high,low=EXCLUDED.low,close=EXCLUDED.close,volume=EXCLUDED.volume,source=EXCLUDED.source,updated_at=NOW()
            """,rows)
    return len(rows)

def _stored_cloud_candles(symbol, interval, limit):
    # History is intentionally long-lived in Postgres. Only the newest stored
    # candle must be fresh; filtering every historical row by freshness would
    # make a 220-candle live request impossible for a 5m feed.
    freshness={"5m":"20 minutes","15m":"50 minutes","1h":"3 hours"}.get(interval)
    if not freshness: return None

    cache_key=(symbol.upper(),interval)
    requested_limit=int(limit)
    cached=_STORED_CANDLE_CACHE.get(cache_key)
    now=time.monotonic()
    if cached and now-cached["time"] < _STORED_CANDLE_CACHE_TTL and len(cached["candles"]) >= requested_limit:
        return cached["candles"][-requested_limit:]

    try:
        read_limit=max(300,requested_limit)
        with connection() as conn:
            rows=conn.execute(
                """SELECT open,high,low,close,volume,candle_time
                   FROM cloud_market_candles
                   WHERE symbol=%s AND timeframe=%s
                   ORDER BY candle_time DESC
                   LIMIT %s""",
                (symbol.upper(),interval,read_limit)
            ).fetchall()
        if len(rows)<min(50,requested_limit):
            return None
        newest=int(rows[0][5])
        freshness_seconds={"5m":1200,"15m":3000,"1h":10800}[interval]
        if newest < int(time.time())-freshness_seconds:
            return None
        rows=list(reversed(rows))
        candles=[Candle(float(r[0]),float(r[1]),float(r[2]),float(r[3]),float(r[4]),int(r[5])) for r in rows]
        _STORED_CANDLE_CACHE[cache_key]={"time":time.monotonic(),"candles":candles}
        return candles[-requested_limit:]
    except Exception:
        return None

async def sync_cloud_market_data():
    global _CLOUD_SYNC_TASK
    existing=_CLOUD_SYNC_TASK
    if existing:
        return await existing

    async def run_sync():
        now=datetime.now(timezone.utc)
        due_15m=now.minute % 15 == 0
        due_1h=now.minute == 0
        report={"updated":0,"failed":0,"skipped":0,"time":now.isoformat(),"symbols":[]}
        targets=[]
        for symbol in YAHOO_SYMBOLS:
            targets.append((symbol,"5m"))
            if due_15m: targets.append((symbol,"15m"))
            if due_1h: targets.append((symbol,"1h"))
        for symbol,pair in KRAKEN_PAIRS.items():
            if symbol.endswith("USDT"): continue
            targets.append((symbol,"5m"))
            if due_15m: targets.append((symbol,"15m"))
            if due_1h: targets.append((symbol,"1h"))
        semaphore=asyncio.Semaphore(6)

        async def sync_one(symbol,interval):
            async with semaphore:
                try:
                    stored = _stored_cloud_candles(symbol, interval, 300)
                    if stored:
                        return {"symbol":symbol,"interval":interval,"candles":0,"source":"neon-cache","skipped":True}
                    if symbol in YAHOO_SYMBOLS:
                        candles=await _yahoo_candles(symbol,interval,300); source="yahoo-cloud"
                    else:
                        kraken_minutes={"5m":5,"15m":15,"1h":60}[interval]
                        candles=await _kraken_candles(KRAKEN_PAIRS[symbol],kraken_minutes,300); source="kraken-cloud"
                    count=_store_cloud_candles(symbol,interval,candles,source)
                    return {"symbol":symbol,"interval":interval,"candles":count,"source":source}
                except Exception as exc:
                    error_text=str(exc)[:180]
                    print(f"CLOUD_SYNC_ERROR {symbol} {interval}: {error_text}", flush=True)
                    return {"symbol":symbol,"interval":interval,"error":error_text}

        results=await asyncio.gather(*(sync_one(symbol,interval) for symbol,interval in targets))
        for item in results:
            if "error" in item:
                report["failed"]+=1
            else:
                report["updated"]+=int(item.get("candles") or 0)
            report["symbols"].append(item)
        return report

    task=asyncio.create_task(run_sync())
    _CLOUD_SYNC_TASK=task
    try:
        return await task
    finally:
        if _CLOUD_SYNC_TASK is task:
            _CLOUD_SYNC_TASK=None

async def _cloud_provider_candles(symbol, interval, limit):
    key=(symbol.upper(),interval,int(limit))
    existing=_CLOUD_FETCH_TASKS.get(key)
    if existing:
        return await existing

    async def fetch():
        if symbol in YAHOO_SYMBOLS:
            try:
                return await _yahoo_candles(symbol, interval, limit)
            except Exception:
                pass
        kraken_pair=KRAKEN_PAIRS.get(symbol)
        if kraken_pair:
            try:
                kraken_minutes={"5m":5,"15m":15,"1h":60}.get(interval)
                if not kraken_minutes:
                    raise RuntimeError("Unsupported Kraken interval: " + interval)
                return await _kraken_candles(kraken_pair, kraken_minutes, limit)
            except Exception:
                pass
        raise RuntimeError(
            f"Cloud market data unavailable for {symbol} {interval}; "
            "MT5 is optional and is not required for TradeGuard analysis."
        )

    task=asyncio.create_task(fetch())
    _CLOUD_FETCH_TASKS[key]=task
    try:
        return await task
    finally:
        if _CLOUD_FETCH_TASKS.get(key) is task:
            _CLOUD_FETCH_TASKS.pop(key,None)

async def candles_for(symbol="BTCUSDT", interval="15m", limit=200, user_id=None):
    """
    Cloud-first market data.

    TradeGuard's analysis must not depend on a Windows MT5 terminal being
    online. Public/cloud market feeds are therefore tried first. The MT5
    bridge is retained only as an optional broker-specific fallback for
    symbols that the cloud feeds cannot supply.
    """
    symbol = symbol.upper()

    # Persistent cloud candles are preferred once the free cron service has
    # populated them. Direct provider access remains a bootstrap/recovery path.
    stored=_stored_cloud_candles(symbol,interval,limit)
    if stored:
        return stored

    # FX/index symbols use Yahoo first and crypto uses Kraken first. Provider
    # requests are deduplicated so concurrent scans share one outbound call.
    try:
        candles=await _cloud_provider_candles(symbol,interval,limit)
        try: _store_cloud_candles(symbol,interval,candles,"cloud-provider")
        except Exception: pass
        return candles
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

    # Binance remains the last-resort crypto fallback, preserving the original
    # provider order after the optional MT5 broker-specific fallback.
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
    symbol = symbol.upper()
    now = __import__("time").monotonic()
    cached = _LATEST_PRICE_CACHE.get(symbol)
    if cached and now - cached["time"] < _LATEST_PRICE_CACHE_TTL:
        return cached["price"]

    price = None
    yahoo_symbol = YAHOO_SYMBOLS.get(symbol)
    if yahoo_symbol:
        try:
            async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "TradeGuard/1.0"}) as client:
                # Position marking does not need a full day's 1-minute history.
                # Keep this response small because the monitor runs continuously.
                response = await client.get(
                    f"{YAHOO_CHART_URLS[0]}/{yahoo_symbol}",
                    params={"range": "1h", "interval": "1m", "events": "history"},
                )
                response.raise_for_status()
                payload = response.json()
                result = ((payload.get("chart") or {}).get("result") or [None])[0]
                if result:
                    quote = (((result.get("indicators") or {}).get("quote") or [{}])[0])
                    closes = [v for v in (quote.get("close") or []) if v is not None]
                    if closes:
                        price = float(closes[-1])
        except Exception:
            pass

    if price is None:
        kraken_pair = KRAKEN_PAIRS.get(symbol)
        if kraken_pair:
            try:
                price = await _kraken_price(kraken_pair)
            except Exception:
                pass

    if price is None:
        async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "TradeGuard/1.0"}) as client:
            response = await client.get(BINANCE_TICKER_URL, params={"symbol": symbol})
            response.raise_for_status()
            price = float(response.json()["price"])

    _LATEST_PRICE_CACHE[symbol] = {"time": __import__("time").monotonic(), "price": price}
    return price
