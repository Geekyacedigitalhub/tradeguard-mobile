import json
import time
import urllib.request
from pathlib import Path

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

CONFIG_PATH=Path(__file__).with_name("config.json")

MT5_SYMBOL_MAP={
    "BTC/USD":"BTC",
    "BTCUSDT":"BTC",
    "ETH/USD":"ETH",
    "ETHUSDT":"ETH",
    "SOL/USD":"SOL",
    "SOLUSDT":"SOL",
    "XRP/USD":"XRP",
    "XRPUSDT":"XRP",
}

def load_config():
    return json.loads(CONFIG_PATH.read_text())

def request(cfg,path,method="GET",body=None):
    data=None
    headers={"X-Bridge-Secret":cfg["bridge_secret"],"X-Bridge-User":cfg["user_id"],"Content-Type":"application/json"}
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

def resolve_mt5_symbol(symbol):
    requested=str(symbol or "").strip().upper()
    mapped=MT5_SYMBOL_MAP.get(requested,requested)
    info=mt5.symbol_info(mapped)
    if info is None:
        raise RuntimeError(f"MT5 symbol unavailable for {requested}: {mapped}")
    if not info.visible and not mt5.symbol_select(mapped,True):
        raise RuntimeError(f"MT5 symbol unavailable for {requested}: {mapped}")
    return mapped

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
        "positions":[{"ticket":int(p.ticket),"symbol":p.symbol,"side":"BUY" if p.type==mt5.POSITION_TYPE_BUY else "SELL","volume":float(p.volume),"price_open":float(p.price_open),"price_current":float(p.price_current),"profit":float(p.profit)} for p in (mt5.positions_get() or [])],
    }

def heartbeat(cfg):
    snapshot=terminal_snapshot()
    return request(cfg,"/v1/bridge/heartbeat","POST",{
        "user_id":cfg["user_id"],
        "environment":cfg.get("environment","demo"),
        "terminal":"MT5",
        "connected":snapshot["connected"],
        "account":snapshot.get("account"),
        "balance":snapshot.get("balance"),
        "equity":snapshot.get("equity"),
        "positions":snapshot.get("positions",[]),
    })

def poll(cfg):
    return request(cfg,"/v1/bridge/commands?limit=10")

def report(cfg,command_id,status,result):
    return request(cfg,"/v1/bridge/commands/result","POST",{
        "command_id":command_id,
        "status":status,
        "result":result,
    })

def normalize_volume(symbol,volume):
    info=mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError("Unknown MT5 symbol: "+symbol)
    volume=float(volume)
    if volume<=0:
        raise RuntimeError("Volume must be greater than zero")
    if volume<info.volume_min or volume>info.volume_max:
        raise RuntimeError("Volume is outside the broker limits")
    steps=round((volume-info.volume_min)/info.volume_step)
    return round(info.volume_min+steps*info.volume_step,8)

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
    volume=normalize_volume(symbol,payload.get("volume"))
    price=float(tick.ask if side=="BUY" else tick.bid)
    request_data={
        "action":mt5.TRADE_ACTION_DEAL,
        "symbol":symbol,
        "volume":volume,
        "type":mt5.ORDER_TYPE_BUY if side=="BUY" else mt5.ORDER_TYPE_SELL,
        "price":price,
        "sl":float(payload["stop_loss"]),
        "tp":float(payload["take_profit"]),
        "deviation":int(payload.get("deviation",20)),
        "magic":int(payload.get("magic",260926)),
        "comment":"TradeGuard Demo",
        "type_time":mt5.ORDER_TIME_GTC,
        "type_filling":mt5.ORDER_FILLING_IOC,
    }
    result=mt5.order_send(request_data)
    if result is None:
        raise RuntimeError("MT5 order_send failed: "+str(mt5.last_error()))
    accepted={mt5.TRADE_RETCODE_DONE,mt5.TRADE_RETCODE_PLACED,mt5.TRADE_RETCODE_DONE_PARTIAL}
    if result.retcode not in accepted:
        raise RuntimeError("MT5 rejected order: "+str(result.retcode)+" "+str(result.comment))
    return {
        "executed":True,
        "mode":"demo",
        "ticket":int(result.order or result.deal),
        "retcode":int(result.retcode),
        "comment":result.comment,
        "requested_symbol":requested_symbol,
        "symbol":symbol,
        "side":side,
        "volume":volume,
        "price":price,
        "stop_loss":float(payload["stop_loss"]),
        "take_profit":float(payload["take_profit"]),
    }

def close_demo_position(command):
    ensure_mt5()
    if mt5 is None:
        raise RuntimeError("MetaTrader5 package is not installed")
    payload=command.get("payload") or {}
    ticket=int(payload.get("ticket",0))
    if ticket<=0:
        raise RuntimeError("A valid MT5 position ticket is required")
    positions=mt5.positions_get(ticket=ticket)
    if not positions:
        raise RuntimeError("MT5 position not found: "+str(ticket))
    position=positions[0]
    symbol=position.symbol
    side=mt5.ORDER_TYPE_SELL if position.type==mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
    tick=mt5.symbol_info_tick(symbol)
    if tick is None:
        raise RuntimeError("No market tick available for "+symbol)
    requested_volume=payload.get("volume")
    volume=float(position.volume if requested_volume is None else requested_volume)
    if volume<=0 or volume>float(position.volume):
        raise RuntimeError("Close volume exceeds the open position")
    price=float(tick.bid if position.type==mt5.POSITION_TYPE_BUY else tick.ask)
    request_data={
        "action":mt5.TRADE_ACTION_DEAL,
        "symbol":symbol,
        "volume":volume,
        "type":side,
        "position":ticket,
        "price":price,
        "deviation":int(payload.get("deviation",20)),
        "magic":int(payload.get("magic",260926)),
        "comment":"TradeGuard Demo Close",
        "type_time":mt5.ORDER_TIME_GTC,
        "type_filling":mt5.ORDER_FILLING_IOC,
    }
    result=mt5.order_send(request_data)
    if result is None:
        raise RuntimeError("MT5 close request failed: "+str(mt5.last_error()))
    accepted={mt5.TRADE_RETCODE_DONE,mt5.TRADE_RETCODE_PLACED,mt5.TRADE_RETCODE_DONE_PARTIAL}
    if result.retcode not in accepted:
        raise RuntimeError("MT5 rejected close: "+str(result.retcode)+" "+str(result.comment))
    remaining=mt5.positions_get(ticket=ticket) or []
    remaining_volume=float(remaining[0].volume) if remaining else 0.0
    return {"executed":True,"mode":"demo","ticket":ticket,"symbol":symbol,"closed_volume":volume,"remaining_volume":remaining_volume,"retcode":int(result.retcode),"comment":result.comment,"price":price}

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
        return {"connected":True,"positions":[{"ticket":int(p.ticket),"symbol":p.symbol,"side":"BUY" if p.type==mt5.POSITION_TYPE_BUY else "SELL","volume":float(p.volume),"price_open":float(p.price_open),"price_current":float(p.price_current),"profit":float(p.profit)} for p in positions]}
    raise RuntimeError("Unsupported bridge command: "+command_type)

def main():
    cfg=load_config()
    if cfg.get("environment","demo")!="demo":
        raise RuntimeError("Bridge is locked to DEMO mode until live execution is explicitly enabled.")
    if mt5 is None:
        print("MetaTrader5 package not installed. Install it on the Windows MT5 machine.")
    heartbeat(cfg)
    print("TradeGuard MT5 Bridge connected in DEMO mode.")
    last_heartbeat=0.0
    while True:
        try:
            now=time.time()
            if now-last_heartbeat>=15:
                heartbeat(cfg)
                last_heartbeat=now
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
