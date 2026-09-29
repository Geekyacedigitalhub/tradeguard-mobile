import json
import time
import urllib.request
from pathlib import Path

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

CONFIG_PATH=Path(__file__).with_name("config.json")

def load_config():
    return json.loads(CONFIG_PATH.read_text())

def request(cfg,path,method="GET",body=None):
    data=None
    headers={"X-Bridge-Secret":cfg["bridge_secret"],"Content-Type":"application/json"}
    if body is not None:
        data=json.dumps(body).encode()
    req=urllib.request.Request(cfg["api_base_url"]+path,data=data,headers=headers,method=method)
    with urllib.request.urlopen(req,timeout=15) as response:
        return json.loads(response.read().decode())

def terminal_snapshot():
    if mt5 is None:
        return {"connected":False,"error":"MetaTrader5 package is not installed"}
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
    }

def heartbeat(cfg):
    snapshot=terminal_snapshot()
    return request(cfg,"/v1/bridge/heartbeat","POST",{
        "environment":cfg.get("environment","demo"),
        "terminal":"MT5",
        "connected":snapshot["connected"],
        "account":snapshot.get("account"),
    })

def poll(cfg):
    return request(cfg,"/v1/bridge/commands?limit=10")

def report(cfg,command_id,status,result):
    return request(cfg,"/v1/bridge/commands/result","POST",{
        "command_id":command_id,
        "status":status,
        "result":result,
    })

def execute_command(command,cfg):
    command_type=command["type"]
    if command_type=="ping":
        return {"mode":cfg.get("environment","demo"),"pong":True}
    if command_type=="sync_account":
        return terminal_snapshot()
    if command_type=="sync_positions":
        if mt5 is None:
            return {"connected":False,"positions":[]}
        positions=mt5.positions_get() or []
        return {
            "connected":True,
            "positions":[
                {
                    "ticket":int(p.ticket),
                    "symbol":p.symbol,
                    "side":"BUY" if p.type==mt5.POSITION_TYPE_BUY else "SELL",
                    "volume":float(p.volume),
                    "price_open":float(p.price_open),
                    "price_current":float(p.price_current),
                    "profit":float(p.profit),
                }
                for p in positions
            ],
        }
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
