import json
import time
import urllib.request
from pathlib import Path

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

def heartbeat(cfg):
    return request(cfg,"/v1/bridge/heartbeat","POST",{
        "environment":cfg.get("environment","demo"),
        "terminal":"MT5"
    })

def poll(cfg):
    return request(cfg,"/v1/bridge/commands?limit=10")

def report(cfg,command_id,status,result):
    return request(cfg,"/v1/bridge/commands/result","POST",{
        "command_id":command_id,
        "status":status,
        "result":result
    })

def execute_demo(command):
    # Safety boundary: no live MT5 execution.
    return {
        "mode":"demo",
        "executed":False,
        "message":"Command received by bridge. Live MT5 execution is disabled.",
        "command_type":command["type"]
    }

def main():
    cfg=load_config()
    heartbeat(cfg)
    print("TradeGuard MT5 Bridge connected in DEMO mode.")
    while True:
        try:
            for command in poll(cfg).get("commands",[]):
                try:
                    result=execute_demo(command)
                    report(cfg,command["id"],"completed",result)
                    print("Processed command",command["id"])
                except Exception as exc:
                    report(cfg,command["id"],"failed",{"error":str(exc)})
        except Exception as exc:
            print("Bridge connection error:",exc)
        time.sleep(max(1,int(cfg.get("poll_seconds",3))))

if __name__=="__main__":
    main()
