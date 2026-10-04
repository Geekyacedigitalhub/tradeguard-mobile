import json
import time
from datetime import datetime, timedelta, time as dt_time
import urllib.request
import urllib.parse
from pathlib import Path

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

CONFIG_PATH=Path(__file__).with_name("config.json")
PAIRING_CACHE={"user_id":None,"expires":0.0}

MT5_SYMBOL_MAP={
    "EUR/USD":"EURUSD",
    "EURUSD":"EURUSD",
    "BTC/USD":"BTC",
    "BTCUSDT":"BTC",
    "BTCUSD":"BTC",
    "ETH/USD":"ETH",
    "ETHUSDT":"ETH",
    "ETHUSD":"ETH",
    "SOL/USD":"SOL",
    "SOLUSDT":"SOL",
    "SOLUSD":"SOL",
    "XRP/USD":"XRP",
    "XRPUSDT":"XRP",
    "XRPUSD":"XRP",
    "GBP/USD":"GBPUSD",
    "GBPUSD":"GBPUSD",
    "USD/JPY":"USDJPY",
    "USDJPY":"USDJPY",
    "USD/CHF":"USDCHF",
    "USDCHF":"USDCHF",
    "AUD/USD":"AUDUSD",
    "AUDUSD":"AUDUSD",
    "USD/CAD":"USDCAD",
    "USDCAD":"USDCAD",
    "NZD/USD":"NZDUSD",
    "NZDUSD":"NZDUSD",
    "XAU/USD":"XAUUSD",
    "XAUUSD":"XAUUSD",
    "XAG/USD":"XAGUSD",
    "XAGUSD":"XAGUSD",
    "NAS100":"NAS100",
    "NASDAQ":"NAS100",
    "US30":"US30",
    "DOW":"US30",
    "SPX500":"SPX500",
    "SP500":"SPX500",
}

def load_config():
    return json.loads(CONFIG_PATH.read_text())

def pairing_request(cfg):
    bridge_id=str(cfg.get("bridge_id","windows-mt5")).strip() or "windows-mt5"
    url=cfg["api_base_url"]+"/v1/bridge/pairing?bridge_id="+urllib.parse.quote(bridge_id,safe="")
    req=urllib.request.Request(url,headers={"X-Bridge-Secret":cfg["bridge_secret"]},method="GET")
    with urllib.request.urlopen(req,timeout=15) as response:
        return json.loads(response.read().decode())

def resolve_paired_user_id(cfg):
    now=time.time()
    if PAIRING_CACHE["user_id"] and now < PAIRING_CACHE["expires"]:
        return PAIRING_CACHE["user_id"]
    try:
        result=pairing_request(cfg)
        user_id=result.get("user_id") if result.get("paired") else None
        if user_id:
            PAIRING_CACHE["user_id"]=user_id
            PAIRING_CACHE["expires"]=now+30
            return user_id
    except Exception as exc:
        # Keep the existing configured user as a temporary fallback so the
        # bridge remains backwards-compatible during pairing.
        print("Bridge pairing lookup:",exc)
    return cfg.get("user_id")

def request(cfg,path,method="GET",body=None):
    data=None
    user_id=resolve_paired_user_id(cfg)
    if not user_id:
        raise RuntimeError("MT5 bridge is not paired. Tap CONNECT MT5 in the TradeGuard app first.")
    headers={"X-Bridge-Secret":cfg["bridge_secret"],"X-Bridge-User":user_id,"Content-Type":"application/json"}
    if body is not None:
        data=json.dumps(body).encode()
    req=urllib.request.Request(cfg["api_base_url"]+path,data=data,headers=headers,method=method)
    with urllib.request.urlopen(req,timeout=15) as response:
        return json.loads(response.read().decode())

def ensure_mt5():
    if mt5 is None:
        raise RuntimeError("MetaTrader5 package is not installed")
    if not mt5.initialize():
        raise RuntimeError("MetaTrader5 initialize failed: "+str(mt5.last_error()))

SYMBOL_ALIASES={
    "EURUSD":["EURUSD","EURUSD.a","EURUSDm"],
    "GBPUSD":["GBPUSD","GBPUSD.a","GBPUSDm"],
    "USDJPY":["USDJPY","USDJPY.a","USDJPYm"],
    "USDCHF":["USDCHF","USDCHF.a","USDCHFm"],
    "AUDUSD":["AUDUSD","AUDUSD.a","AUDUSDm"],
    "USDCAD":["USDCAD","USDCAD.a","USDCADm"],
    "NZDUSD":["NZDUSD","NZDUSD.a","NZDUSDm"],
    "XAUUSD":["XAUUSD","GOLD","XAUUSD.a","XAUUSDm"],
    "XAGUSD":["XAGUSD","SILVER","XAGUSD.a","XAGUSDm"],
    "BTCUSD":["BTCUSD","BTC","BTCUSD.a","BTCUSDm"],
    "ETHUSD":["ETHUSD","ETH","ETHUSD.a","ETHUSDm"],
    "NAS100":["NAS100","USTEC","US100","NASDAQ100","NAS100.cash","USTEC.cash"],
    "US30":["US30","DJ30","DOW30","WALLSTREET30","US30.cash","DJ30.cash"],
    "SPX500":["SPX500","US500","SP500","SPX500.cash","US500.cash"],
}

def resolve_mt5_symbol(symbol):
    requested=str(symbol or "").strip().upper()
    mapped=MT5_SYMBOL_MAP.get(requested,requested)
    candidates_to_try=[]
    for value in [mapped, requested, *SYMBOL_ALIASES.get(requested,[])]:
        value=str(value).strip().upper()
        if value and value not in candidates_to_try:
            candidates_to_try.append(value)

    # Prefer exact configured aliases first.
    for candidate_name in candidates_to_try:
        info=mt5.symbol_info(candidate_name)
        if info is not None:
            if not info.visible and not mt5.symbol_select(candidate_name,True):
                continue
            print(f"MT5 symbol resolved {requested} -> {candidate_name}")
            return candidate_name

    # Brokers commonly append suffixes such as .a, m, _pro, or .cash.
    normalized_targets={
        "".join(ch for ch in value if ch.isalnum())
        for value in candidates_to_try
    }
    for candidate in (mt5.symbols_get() or []):
        name=str(candidate.name)
        n="".join(ch for ch in name.upper() if ch.isalnum())
        if any(n==target or n.startswith(target) or target.startswith(n) for target in normalized_targets):
            if not candidate.visible and not mt5.symbol_select(name,True):
                continue
            print(f"MT5 symbol resolved {requested} -> {name}")
            return name

    raise RuntimeError(f"MT5 symbol unavailable for {requested}; tried {', '.join(candidates_to_try)}")

def terminal_snapshot():
    if mt5 is None:
        return {"connected":False,"error":"MetaTrader5 package is not installed"}
    try:
        ensure_mt5()
    except Exception as exc:
        return {"connected":False,"error":str(exc)}
    account=mt5.account_info()
    if account is None:
        return {"connected":False,"error":str(mt5.last_error())}
    return {
        "connected":True,
        "account":str(account.login),
        "balance":float(account.balance),
        "equity":float(account.equity),
        "margin":float(account.margin),
        "free_margin":float(account.margin_free),
        "currency":account.currency,
        "positions":[{"ticket":int(p.ticket),"symbol":p.symbol,"side":"BUY" if p.type==mt5.POSITION_TYPE_BUY else "SELL","volume":float(p.volume),"price_open":float(p.price_open),"price_current":float(p.price_current),"stop_loss":float(p.sl),"take_profit":float(p.tp),"profit":float(p.profit)} for p in (mt5.positions_get() or [])],
        "today_pl":float(sum(float(d.profit)+float(d.commission)+float(d.swap) for d in (mt5.history_deals_get(datetime.combine(datetime.now().date(),dt_time.min),datetime.now()) or []) if getattr(d,"entry",None) in (mt5.DEAL_ENTRY_OUT,mt5.DEAL_ENTRY_OUT_BY,mt5.DEAL_ENTRY_INOUT))),
    }

def heartbeat(cfg):
    snapshot=terminal_snapshot()
    # Keep the heartbeat focused on fields required by account/risk tracking
    # and broker-side close detection. Avoid sending unused MT5 account fields.
    return request(cfg,"/v1/bridge/heartbeat","POST",{
        "user_id":cfg["user_id"],
        "environment":cfg.get("environment","demo"),
        "terminal":"MT5",
        "connected":snapshot["connected"],
        "account":snapshot.get("account"),
        "balance":snapshot.get("balance"),
        "equity":snapshot.get("equity"),
        "today_pl":snapshot.get("today_pl"),
        "positions":snapshot.get("positions",[]),
    })

MARKET_FEED_SYMBOLS=[
    "EURUSD","GBPUSD","USDJPY","USDCHF","AUDUSD","USDCAD","NZDUSD",
    "XAUUSD","XAGUSD","BTCUSD","ETHUSD","NAS100","US30","SPX500",
]

LIVE_SYMBOLS={}
LIVE_TICKS={}

def push_live_ticks(cfg):
    if mt5 is None:
        return 0
    try:
        ensure_mt5()
        paired_user_id=resolve_paired_user_id(cfg)
        if not paired_user_id:
            return 0
        ticks=[]
        for canonical in MARKET_FEED_SYMBOLS:
            try:
                symbol=LIVE_SYMBOLS.get(canonical)
                if not symbol:
                    symbol=resolve_mt5_symbol(canonical)
                    LIVE_SYMBOLS[canonical]=symbol
                tick=mt5.symbol_info_tick(symbol)
                if tick is None:
                    continue
                time_msc=int(getattr(tick,"time_msc",0) or 0)
                if time_msc and LIVE_TICKS.get(canonical)==time_msc:
                    continue
                LIVE_TICKS[canonical]=time_msc
                bid=float(getattr(tick,"bid",0) or 0)
                ask=float(getattr(tick,"ask",0) or 0)
                price=(bid+ask)/2 if bid>0 and ask>0 else float(getattr(tick,"last",0) or bid)
                if price<=0:
                    continue
                ticks.append({
                    "symbol":canonical,
                    "bid":bid,
                    "ask":ask,
                    "price":price,
                    "time":int(getattr(tick,"time",0) or 0),
                    "time_msc":time_msc,
                })
            except Exception as exc:
                print(f"Live tick skipped {canonical}: {exc}")
        if not ticks:
            return 0
        result=request(cfg,"/v1/internal/live-ticks","POST",{"user_id":paired_user_id,"ticks":ticks})
        return len(ticks)
    except Exception as exc:
        print("Live tick stream error:",exc)
        return 0

def push_market_data(cfg,full_history=False,heartbeat_callback=None):
    if mt5 is None:
        return []
    synced=[]
    try:
        ensure_mt5()
        paired_user_id=resolve_paired_user_id(cfg)
        if not paired_user_id:
            print("Market data sync skipped: bridge is not paired to a TradeGuard user")
            return []

        # Full history is only needed periodically. Normal one-minute syncs
        # send recent candles; the API merges them with the stored history.
        now=datetime.now()
        # Incremental broker data is only needed when a new candle can exist.
        # This cuts bridge -> Neon traffic dramatically while keeping the
        # scanner's 5m/15m/1h feeds fresh.
        minute=now.minute
        timeframes=[]
        if minute % 5 == 0:
            timeframes.append(("5m",mt5.TIMEFRAME_M5,5,25,5000 if full_history else 60))
        if minute % 15 == 0:
            timeframes.append(("15m",mt5.TIMEFRAME_M15,15,55,2500 if full_history else 60))
        if minute == 0:
            timeframes.append(("1h",mt5.TIMEFRAME_H1,60,120,800 if full_history else 60))
        if not timeframes:
            return []

        # Full historical loads are expensive. Keep the scanner symbols light,
        # and only refresh the symbols used by Strategy Lab with the larger
        # validation history. Normal one-minute syncs still cover every symbol.
        history_symbols={"EURUSD","GBPUSD","USDJPY","XAUUSD","XAGUSD"}
        symbols_to_sync=MARKET_FEED_SYMBOLS if not full_history else [
            symbol for symbol in MARKET_FEED_SYMBOLS if symbol in history_symbols
        ]

        for canonical in symbols_to_sync:
            try:
                symbol=resolve_mt5_symbol(canonical)
                info=mt5.symbol_info(symbol)
                if info is None:
                    print(f"Market data skipped {canonical}: symbol_info unavailable for {symbol}")
                    continue
                tick=mt5.symbol_info_tick(symbol)
                if tick is None:
                    print(f"Market data skipped {canonical}: no MT5 tick for {symbol}; error {mt5.last_error()}")
                else:
                    print(f"Market feed {canonical} -> {symbol}: bid={tick.bid} ask={tick.ask}")

                for timeframe,mt5_timeframe,bar_minutes,history_days,bar_count in timeframes:
                    try:
                        rates=mt5.copy_rates_from_pos(symbol,mt5_timeframe,1,bar_count)
                        source="copy_rates_from_pos"

                        if rates is None or len(rates)<50:
                            copy_error=mt5.last_error()
                            end_time=datetime.now()
                            start_time=end_time-timedelta(days=history_days)
                            alt_rates=mt5.copy_rates_range(symbol,mt5_timeframe,start_time,end_time)
                            if alt_rates is not None and len(alt_rates)>=50:
                                rates=alt_rates[-bar_count:]
                                source="copy_rates_range"
                                print(f"MT5 history fallback succeeded {canonical} {timeframe} -> {symbol}: {len(rates)} bars")
                            else:
                                range_error=mt5.last_error()
                                if rates is None:
                                    print(f"Market data skipped {canonical} {timeframe}: copy_rates_from_pos failed {copy_error}; copy_rates_range failed {range_error}")
                                else:
                                    print(f"Market data skipped {canonical} {timeframe}: only {len(rates)} bars; range returned {0 if alt_rates is None else len(alt_rates)}")

                        if rates is None or len(rates)<50:
                            continue

                        candles=[{
                            "time":int(row["time"]),
                            "open":float(row["open"]),
                            "high":float(row["high"]),
                            "low":float(row["low"]),
                            "close":float(row["close"]),
                            "volume":float(row["tick_volume"]),
                        } for row in rates]

                        result=request(cfg,"/v1/bridge/market-data","POST",{
                            "user_id":paired_user_id,
                            "symbol":canonical,
                            "timeframe":timeframe,
                            "candles":candles,
                        })
                        synced.append(f"{canonical} {timeframe}")
                        last_time=datetime.fromtimestamp(int(candles[-1]["time"]))
                        print(f"Market data uploaded {canonical} {timeframe}: {len(candles)} bars via {source}, last={last_time.isoformat()} response={result}")
                    except Exception as exc:
                        print(f"Market data skipped {canonical} {timeframe} ({symbol}): {exc}")
            except Exception as exc:
                print(f"Market data skipped {canonical}: {exc}")
            if heartbeat_callback:
                heartbeat_callback()
    except Exception as exc:
        print("Market data sync error:",exc)
    return synced


def poll(cfg):
    return request(cfg,"/v1/bridge/commands?limit=10")

def report(cfg,command_id,status,result):
    return request(cfg,"/v1/bridge/commands/result","POST",{
        "command_id":command_id,
        "status":status,
        "result":result,
    })

def resolve_filling_mode(symbol):
    info=mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError("Unknown MT5 symbol: "+symbol)
    flags=int(getattr(info,"filling_mode",0) or 0)
    # MetaTrader5 exposes the symbol filling flags as a bitmask:
    # FOK=1, IOC=2. Avoid SYMBOL_FILLING_* constants because some
    # Python package versions do not expose them.
    if flags & 2:
        return mt5.ORDER_FILLING_IOC
    if flags & 1:
        return mt5.ORDER_FILLING_FOK
    return mt5.ORDER_FILLING_RETURN

def normalize_volume(symbol,volume,side,price):
    info=mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError("Unknown MT5 symbol: "+symbol)

    # The risk engine sizes in base-currency units, while MT5 order volume
    # is expressed in lots. Convert units to lots using the broker contract size.
    units=float(volume)
    contract_size=float(getattr(info,"trade_contract_size",100000) or 100000)
    lots=units/contract_size

    volume_min=float(info.volume_min or 0)
    volume_max=float(info.volume_max or 0)
    volume_step=float(info.volume_step or 0)
    if volume_min<=0 or volume_max<=0 or volume_step<=0:
        raise RuntimeError("Broker returned invalid volume limits")

    lots=min(lots,volume_max)
    lots=max(lots,volume_min)

    steps=int((lots-volume_min)/volume_step)
    normalized=volume_min+(steps*volume_step)
    normalized=max(volume_min,min(normalized,volume_max))

    # Never submit an order the account cannot fund. Reduce the size to the
    # largest broker-valid step whose estimated margin fits free margin.
    account=mt5.account_info()
    order_type=mt5.ORDER_TYPE_BUY if side=="BUY" else mt5.ORDER_TYPE_SELL
    if account is not None:
        free_margin=float(account.margin_free)
        while normalized > volume_min:
            margin=mt5.order_calc_margin(order_type,symbol,normalized,float(price))
            if margin is None or float(margin) <= free_margin:
                break
            normalized=round(normalized-volume_step,8)

    if normalized < volume_min:
        margin=mt5.order_calc_margin(order_type,symbol,volume_min,float(price))
        if margin is not None and account is not None and float(margin) > float(account.margin_free):
            raise RuntimeError("Insufficient free margin for the broker minimum volume")

    return round(normalized,8)

def attach_protection(symbol, ticket, side, stop_loss, take_profit, digits):
    # A market order's order/deal ticket is not guaranteed to equal the
    # resulting position ticket. Find the TradeGuard position by symbol/magic.
    positions = mt5.positions_get(symbol=symbol) or []
    candidates = [p for p in positions if int(getattr(p, "magic", 0) or 0) == 260926]
    if not candidates:
        candidates = list(positions)
    if not candidates:
        raise RuntimeError(f"MT5 position not found after execution: {ticket}")
    position = max(candidates, key=lambda p: int(p.ticket))

    sl = round(float(stop_loss), digits)
    tp = round(float(take_profit), digits)

    if abs(float(position.sl) - sl) > 10 ** (-digits) or abs(float(position.tp) - tp) > 10 ** (-digits):
        modify = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": symbol,
            "position": int(position.ticket),
            "sl": sl,
            "tp": tp,
            "magic": 260926,
            "comment": "TradeGuard Protection",
        }
        result = mt5.order_send(modify)
        accepted = {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED, mt5.TRADE_RETCODE_DONE_PARTIAL}
        if result is None or result.retcode not in accepted:
            detail = str(result.retcode) + " " + str(result.comment) if result is not None else str(mt5.last_error())
            raise RuntimeError("MT5 accepted the trade but could not attach SL/TP: " + detail)

    verified = mt5.positions_get(symbol=symbol) or []
    verified = [p for p in verified if int(p.ticket) == int(position.ticket)]
    if not verified or float(verified[0].sl) == 0 or float(verified[0].tp) == 0:
        raise RuntimeError("MT5 position is unprotected: SL/TP verification failed")
    return verified[0]

def execute_demo_order(command):
    if mt5 is None:
        raise RuntimeError("MetaTrader5 package is not installed")
    ensure_mt5()
    payload=command.get("payload") or {}
    requested_symbol=str(payload.get("symbol","")).strip()
    side=str(payload.get("side","")).upper()
    if side not in ("BUY","SELL"):
        raise RuntimeError("Side must be BUY or SELL")
    if not requested_symbol:
        raise RuntimeError("Symbol is required")
    if payload.get("stop_loss") is None or payload.get("take_profit") is None:
        raise RuntimeError("Stop loss and take profit are required")
    symbol=resolve_mt5_symbol(requested_symbol)
    tick=mt5.symbol_info_tick(symbol)
    if tick is None:
        raise RuntimeError(f"No market tick available for {requested_symbol} ({symbol})")
    info=mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError("Unknown MT5 symbol: "+symbol)
    price=float(tick.ask if side=="BUY" else tick.bid)
    volume=normalize_volume(symbol,payload.get("volume"),side,price)
    digits=int(info.digits)
    point=float(info.point)
    min_stop_distance=max(float(getattr(info,"trade_stops_level",0) or 0)*point, point)
    sl=float(payload["stop_loss"])
    tp=float(payload["take_profit"])
    if side=="BUY":
        if sl >= price:
            sl=price-min_stop_distance
        if tp <= price:
            tp=price+min_stop_distance
        sl=min(sl,price-min_stop_distance)
        tp=max(tp,price+min_stop_distance)
    else:
        if sl <= price:
            sl=price+min_stop_distance
        if tp >= price:
            tp=price-min_stop_distance
        sl=max(sl,price+min_stop_distance)
        tp=min(tp,price-min_stop_distance)
    sl=round(sl,digits)
    tp=round(tp,digits)
    request_data={
        "action":mt5.TRADE_ACTION_DEAL,
        "symbol":symbol,
        "volume":volume,
        "type":mt5.ORDER_TYPE_BUY if side=="BUY" else mt5.ORDER_TYPE_SELL,
        "price":price,
        "sl":sl,
        "tp":tp,
        "deviation":int(payload.get("deviation",20)),
        "magic":int(payload.get("magic",260926)),
        "comment":"TradeGuard Demo",
        "type_time":mt5.ORDER_TIME_GTC,
        "type_filling":resolve_filling_mode(symbol),
    }
    result=mt5.order_send(request_data)
    if result is None:
        raise RuntimeError("MT5 order_send failed: "+str(mt5.last_error()))
    accepted={mt5.TRADE_RETCODE_DONE,mt5.TRADE_RETCODE_PLACED,mt5.TRADE_RETCODE_DONE_PARTIAL}
    if result.retcode not in accepted:
        raise RuntimeError("MT5 rejected order: "+str(result.retcode)+" "+str(result.comment))

    ticket=int(result.order or result.deal)
    try:
        position=attach_protection(symbol,ticket,side,sl,tp,digits)
    except Exception as protection_error:
        # Fail closed: never leave an automated TradeGuard position unprotected.
        try:
            close_demo_position({"payload":{"ticket":ticket}})
        except Exception as close_error:
            raise RuntimeError(f"Trade opened without protection and emergency close failed: {protection_error}; {close_error}")
        raise RuntimeError("Trade was opened but protection could not be verified. The position was closed automatically.")

    return {
        "executed":True,
        "mode":"demo",
        "ticket":int(position.ticket),
        "retcode":int(result.retcode),
        "comment":result.comment,
        "requested_symbol":requested_symbol,
        "symbol":symbol,
        "side":side,
        "volume":float(position.volume),
        "price":float(position.price_open),
        "stop_loss":float(position.sl),
        "take_profit":float(position.tp),
        "protected":True,
    }

def close_demo_position(command):
    ensure_mt5()
    payload=command.get("payload") or {}
    ticket=int(payload.get("ticket",0))
    if ticket<=0:
        raise RuntimeError("A valid MT5 position ticket is required")
    positions=mt5.positions_get(ticket=ticket)
    if not positions:
        raise RuntimeError("MT5 position not found: "+str(ticket))

    position=positions[0]
    symbol=position.symbol
    close_type=mt5.ORDER_TYPE_SELL if position.type==mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
    tick=mt5.symbol_info_tick(symbol)
    if tick is None:
        raise RuntimeError("No market tick available for "+symbol)

    volume=float(position.volume)
    price=float(tick.bid if position.type==mt5.POSITION_TYPE_BUY else tick.ask)

    # For closing an existing position, use the exact filling mode advertised
    # by the symbol. The previous generic fallback could still send an
    # unsupported mode and MT5 returned retcode 10030.
    info=mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError("Unknown MT5 symbol: "+symbol)

    flags=int(getattr(info,"filling_mode",0) or 0)
    fill_modes=[]
    if flags & 2:
        fill_modes.append(mt5.ORDER_FILLING_IOC)
    if flags & 1:
        fill_modes.append(mt5.ORDER_FILLING_FOK)
    # RETURN is valid for market/exchange execution only on some symbols;
    # only try it as a final fallback when the broker exposes no flags.
    if not fill_modes:
        fill_modes.append(mt5.ORDER_FILLING_RETURN)

    accepted={mt5.TRADE_RETCODE_DONE,mt5.TRADE_RETCODE_PLACED,mt5.TRADE_RETCODE_DONE_PARTIAL}
    last_error=""
    for fill_mode in fill_modes:
        request_data={
            "action":mt5.TRADE_ACTION_DEAL,
            "symbol":symbol,
            "volume":volume,
            "type":close_type,
            "position":ticket,
            "price":price,
            "deviation":int(payload.get("deviation",20)),
            "magic":int(payload.get("magic",260926)),
            "comment":"TradeGuard Demo Close",
            "type_time":mt5.ORDER_TIME_GTC,
            "type_filling":fill_mode,
        }
        result=mt5.order_send(request_data)
        if result is not None and result.retcode in accepted:
            remaining=mt5.positions_get(ticket=ticket) or []
            remaining_volume=float(remaining[0].volume) if remaining else 0.0
            return {
                "executed":True,
                "mode":"demo",
                "ticket":ticket,
                "symbol":symbol,
                "closed_volume":volume,
                "remaining_volume":remaining_volume,
                "retcode":int(result.retcode),
                "comment":result.comment,
                "price":price,
                "filling_mode":fill_mode,
            }
        last_error=(str(result.retcode)+" "+str(result.comment) if result is not None else str(mt5.last_error()))

    raise RuntimeError("MT5 rejected close: "+last_error)

def switch_account(command,cfg):
    payload=command.get("payload") or {}
    profile=str(payload.get("profile","demo")).lower()
    profiles=cfg.get("profiles") or {}
    account=profiles.get(profile)
    if not account:
        raise RuntimeError("MT5 profile is not configured: "+profile)
    ensure_mt5()
    login=int(account["login"])
    password=str(account["password"])
    server=str(account["server"])
    if not mt5.login(login=login,password=password,server=server):
        raise RuntimeError("MT5 account switch failed: "+str(mt5.last_error()))
    return {"switched":True,"profile":profile,"account":str(login),"server":server,"mode":"demo" if profile=="demo" else "live"}

def execute_command(command,cfg):
    command_type=command["type"]
    if command_type=="switch_account":
        return switch_account(command,cfg)
    if command_type=="open_market":
        if cfg.get("environment","demo")!="demo":
            raise RuntimeError("Live execution is disabled")
        return execute_demo_order(command)
    if command_type=="close_position":
        if cfg.get("environment","demo")!="demo":
            raise RuntimeError("Live execution is disabled")
        return close_demo_position(command)
    if command_type=="ping":
        return {"mode":cfg.get("environment","demo"),"pong":True}
    if command_type=="sync_account":
        return terminal_snapshot()
    if command_type=="sync_positions":
        if mt5 is None:
            return {"connected":False,"positions":[]}
        positions=mt5.positions_get() or []
        return {"connected":True,"positions":[{"ticket":int(p.ticket),"symbol":p.symbol,"side":"BUY" if p.type==mt5.POSITION_TYPE_BUY else "SELL","volume":float(p.volume),"price_open":float(p.price_open),"price_current":float(p.price_current),"stop_loss":float(p.sl),"take_profit":float(p.tp),"profit":float(p.profit)} for p in positions]}
    raise RuntimeError("Unsupported bridge command: "+command_type)

def main():
    cfg=load_config()
    if cfg.get("environment","demo")!="demo":
        raise RuntimeError("Bridge is locked to DEMO mode until live execution is explicitly enabled.")
    if mt5 is None:
        print("MetaTrader5 package not installed. Install it on the Windows MT5 machine.")
    try:
        heartbeat(cfg)
    except Exception as exc:
        print("Initial heartbeat waiting:",exc)
    print("TradeGuard MT5 Bridge running in DEMO mode.")
    last_heartbeat=0.0
    last_market_sync=0.0
    last_full_history_sync=0.0
    last_tick_push=0.0

    def maybe_heartbeat():
        nonlocal last_heartbeat
        now=time.time()
        if now-last_heartbeat>=30:
            try:
                heartbeat(cfg)
                print("Heartbeat sent successfully")
            except Exception as exc:
                print("Heartbeat error:",exc)
            finally:
                last_heartbeat=now

    while True:
        try:
            maybe_heartbeat()
            now=time.time()
            if now-last_tick_push>=1:
                pushed=push_live_ticks(cfg)
                if pushed:
                    print(f"Live ticks streamed: {pushed}")
                last_tick_push=now
            if now-last_market_sync>=60:
                # Full history is a recovery/bootstrap operation, not a
                # frequent refresh. Rebuild it at most every 6 hours.
                full_history = now-last_full_history_sync >= 21600
                market_result = push_market_data(cfg,full_history=full_history,heartbeat_callback=maybe_heartbeat)
                if market_result:
                    mode_label="full history" if full_history else "incremental"
                    print(f"Market data synced ({mode_label}):", ", ".join(market_result))
                last_market_sync=now
                if full_history:
                    last_full_history_sync=now
            for command in poll(cfg).get("commands",[]):
                try:
                    result=execute_command(command,cfg)
                    report(cfg,command["id"],"completed",result)
                    print("Processed command",command["id"],command["type"])
                except Exception as exc:
                    report(cfg,command["id"],"failed",{"error":str(exc)})
                    print("Command failed:",exc)
        except Exception as exc:
            print("Bridge connection error:",exc)
        time.sleep(max(1,int(cfg.get("poll_seconds",3))))

if __name__=="__main__":
    main()
