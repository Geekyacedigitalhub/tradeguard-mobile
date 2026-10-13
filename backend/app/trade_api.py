from fastapi import APIRouter, Depends, HTTPException
from .auth import current_user
from .db import connection
from .risk_api import approve_trade
from .trade_manager import get_position, list_positions, close_position, open_paper_position
from .account_sync import live_account_metrics
from .risk_metrics import consecutive_losses
from .validation_gate import latest_validation_gate
from .profit_engine import evaluate_opportunity
from .learning import learning_gate
from .optimizer import optimizer_gate
from .execution import execution_snapshot, execution_provider
import time

_MT5_CONNECTION_CACHE={}
_MT5_CONNECTION_CACHE_TTL=5

def _broker_connection_snapshot(user_id):
    key=str(user_id)
    cached=_MT5_CONNECTION_CACHE.get(key)
    now=time.monotonic()
    if cached and now-cached[0] < _MT5_CONNECTION_CACHE_TTL:
        return cached[1]
    with connection() as conn:
        row=conn.execute("""SELECT ae.payload,ae.created_at,ast.updated_at FROM audit_events ae LEFT JOIN account_state ast ON ast.user_id=ae.user_id WHERE ae.user_id=%s AND ae.event_type='broker_connection' ORDER BY ae.created_at DESC LIMIT 1""",(user_id,)).fetchone()
    if not row:
        snapshot={"connected":False,"positions":None,"payload":{}}
    else:
        from datetime import datetime,timezone
        payload=row[0] or {}
        last_seen=row[2] or row[1]
        age=(datetime.now(timezone.utc)-last_seen).total_seconds()
        snapshot={
            "connected":bool(payload.get("connected")) and age<=45 and payload.get("terminal")=="MT5 Cloud EA",
            "positions":payload.get("positions") if isinstance(payload.get("positions"),list) else None,
            "payload":payload,
            "last_seen":last_seen,
            "age_seconds":max(0.0,round(age,1)),
        }
    _MT5_CONNECTION_CACHE[key]=(now,snapshot)
    return snapshot

def mt5_connected(user_id):
    snapshot=_broker_connection_snapshot(user_id)
    # Production execution is owned by the cloud MT5 EA. The old
    # Windows/Python bridge must never become the mobile fallback path.
    return bool(snapshot["connected"])

def mt5_connection_status(user_id):
    snapshot=_broker_connection_snapshot(user_id)
    payload=snapshot.get("payload") or {}
    connected=bool(snapshot.get("connected"))
    return {
        "connected":connected,
        "execution":"MT5_CLOUD_EA" if connected else "OFFLINE",
        "terminal":payload.get("terminal"),
        "environment":payload.get("environment"),
        "account":payload.get("account"),
        "last_heartbeat":snapshot.get("last_seen"),
        "heartbeat_age_seconds":snapshot.get("age_seconds"),
        "positions_count":len(snapshot.get("positions") or []),
    }

def queue_bridge_command(user_id,command_type,payload):
    with connection() as conn:
        row=conn.execute("INSERT INTO bridge_commands (user_id,command_type,payload) VALUES (%s,%s,%s::jsonb) RETURNING id",(user_id,command_type,__import__("json").dumps(payload))).fetchone()
    return int(row[0])


router = APIRouter(prefix="/v1/trades", tags=["trades"])

def serialize(p):
    return {k:v for k,v in p.__dict__.items() if k != "user_id"}

@router.get("")
def trades(status: str | None = None, user=Depends(current_user)):
    # This endpoint serves TradeGuard's internal journal records only.
    # Broker-confirmed cTrader positions are fetched from the dedicated
    # cTrader account snapshot endpoint; never mix legacy MT5 heartbeat data
    # into the app's trade list.
    return {"trades":[serialize(p) for p in list_positions(status,user["id"])]}

@router.post("/open")
def open_trade(signal: dict, user=Depends(current_user)):
    deep=signal.get("deep_analysis") or {}
    if deep.get("decision")!="TRADE CANDIDATE":
        raise HTTPException(409,"TradeGuard research gate: the deep analysis does not currently support execution.")
    symbol_key=str(signal.get("symbol","")).replace("/","")
    historical=latest_validation_gate(user["id"],symbol_key)
    if not historical.get("approved"):
        raise HTTPException(409,"TradeGuard historical evidence gate: "+str(historical.get("reason","validation required")))
    profit=evaluate_opportunity(signal,historical=historical)
    learning=learning_gate(user["id"],symbol_key,setup="TradeGuard MTF Price Action v2",
                           session=(signal.get("intelligence") or {}).get("session"),
                           regime=(signal.get("intelligence") or {}).get("regime"))
    optimizer=optimizer_gate(user["id"],symbol_key,setup="TradeGuard MTF Price Action v2",
                             session=(signal.get("intelligence") or {}).get("session"),
                             regime=(signal.get("intelligence") or {}).get("regime"))
    profit["learning"]=learning
    profit["optimizer"]=optimizer
    profit["risk_multiplier"]=round(
        float(profit.get("risk_multiplier") or 1.0)
        * float(learning.get("modifier") or 1.0)
        * float(optimizer.get("modifier") or 1.0),3)
    if not learning.get("approved") or not optimizer.get("approved"):
        profit["decision"]="WAIT"
        profit["tier"]="REJECT"
        profit.setdefault("vetoes",[]).append(learning.get("reason") or "Live learning gate rejected the setup.")
    if not optimizer.get("approved"):
        profit["decision"]="WAIT"
        profit["tier"]="REJECT"
        profit.setdefault("vetoes",[]).append(optimizer.get("reason") or "Optimizer rejected the setup.")
    if profit.get("decision")!="EXECUTE":
        raise HTTPException(409,"TradeGuard profit engine: "+"; ".join(profit.get("vetoes") or ["edge threshold not met"]))
    signal["profit_engine"]=profit
    account=live_account_metrics(user["id"])
    with connection() as conn:
        risk=conn.execute("SELECT risk_per_trade,daily_loss_limit,max_open_trades,max_drawdown FROM bot_state WHERE user_id=%s",(user["id"],)).fetchone()
    if not account or not risk: raise HTTPException(500,"Account state is not initialized")
    open_count=len(list_positions("open",user["id"]))
    # When MT5 is connected, broker positions are the source of truth.
    broker_snapshot=_broker_connection_snapshot(user["id"])
    if broker_snapshot["connected"] and broker_snapshot["positions"] is not None:
        open_count=len(broker_snapshot["positions"])
    decision=approve_trade(signal,balance=float(account["balance"]),equity=float(account["equity"]),today_pnl_percent=float(account["today_pl"])/max(float(account["balance"]),1)*100,drawdown_percent=float(account["drawdown"]),open_trades=open_count,consecutive_losses=consecutive_losses(user["id"]),risk_per_trade=float(risk[0]) * float(profit.get("risk_multiplier",1.0)),daily_loss_limit=float(risk[1]),max_open_trades=int(risk[2]),max_drawdown=float(risk[3]))
    if not decision["approved"]:
        raise HTTPException(409,decision["reason"])
    # Do not return a misleading queued/approved result for an entry that the
    # cloud worker must reject. cTrader Demo entries stay disabled until the
    # endpoint supplies independently verified broker sizing evidence tied to
    # the selected account and instrument. This also prevents legacy MT5
    # execution branches from being used as a fallback.
    from .ctrader_execution_guard import entry_block_reason
    entry_reason = entry_block_reason(str((execution_snapshot(user["id"]) or {}).get("environment") or "unknown"), sizing_verified=False)
    raise HTTPException(409, entry_reason or "Automated entries remain disabled until broker-verified risk sizing is available.")

    # Fail closed: no provider-specific order path is reachable until broker-verified sizing is implemented.
    raise HTTPException(409, entry_reason or "Automated entries remain disabled until broker-verified risk sizing is available.")

@router.post("/{position_id}/close")
def close_trade(position_id: int, user=Depends(current_user)):
    position=get_position(position_id,user["id"])
    if not position: raise HTTPException(404,"Position not found")
    return serialize(close_position(position))

@router.post("/close-all")
def close_all(user=Depends(current_user)):
    # The former bulk-close path used the legacy MT5 execution snapshot and
    # queued ticket-only bridge commands. Never let it operate on a cTrader
    # account or accidentally route through an old MT5 heartbeat.
    raise HTTPException(
        409,
        "Bulk close is temporarily disabled: this endpoint still uses legacy MT5 execution. "
        "No close commands were queued. Use broker-confirmed cTrader position controls.",
    )


@router.post("/account/switch")
def switch_broker_account(body: dict, user=Depends(current_user)):
    raise HTTPException(
        410,
        "Legacy MT5 account switching is disabled. Select Demo or Live in cTrader Settings.",
    )

@router.get("/execution")
def execution_status(user=Depends(current_user)):
    snapshot=execution_snapshot(user["id"])
    return {
        "connected":snapshot["connected"],
        "provider":snapshot["provider"],
        "terminal":snapshot["terminal"],
        "environment":snapshot["environment"],
        "account":snapshot["account"],
        "last_heartbeat":snapshot["last_seen"],
        "heartbeat_age_seconds":snapshot["age_seconds"],
        "positions_count":len(snapshot["positions"]),
    }

@router.get("/connection")
def mt5_connection(user=Depends(current_user)):
    return mt5_connection_status(user["id"])

@router.get("/command/{command_id}")
def bridge_command_status(command_id: int, user=Depends(current_user)):
    with connection() as conn:
        row=conn.execute("""SELECT id,command_type,status,created_at,claimed_at,completed_at,result FROM bridge_commands WHERE id=%s AND user_id=%s""",(command_id,user["id"])).fetchone()
    if not row:
        raise HTTPException(404,"Bridge command not found")
    return {"id":row[0],"type":row[1],"status":row[2],"created_at":row[3],"claimed_at":row[4],"completed_at":row[5],"result":row[6]}

@router.post("/mt5/{ticket}/close")
def close_mt5_trade(ticket: int, user=Depends(current_user)):
    raise HTTPException(
        410,
        "Legacy MT5 position closing is disabled. Use the cTrader position controls.",
    )

@router.post("/ctrader/{position_id}/close")
async def close_ctrader_trade(position_id: int, body: dict, user=Depends(current_user)):
    """Queue a Demo-only cTrader close and verify broker state in the cloud worker."""
    from .ctrader_oauth_api import _connection_row
    from .ctrader_protection_validation import validate_positive_identifier
    from .ctrader_volume_validation import validate_protocol_volume

    row = _connection_row(user["id"])
    if not row or not row[0] or not row[2]:
        raise HTTPException(409, "A selected cTrader account is required")
    try:
        position_id = validate_positive_identifier(position_id, "position id")
        volume = validate_protocol_volume(body.get("volume"), field="close volume")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if str(row[1] or "demo").lower() != "demo":
        raise HTTPException(403, "Automated cTrader position changes are disabled for Live accounts")
    # Serialize close requests for this user/account/position. A mobile retry,
    # double tap, or app resume must not enqueue another close while an earlier
    # close for the same position is still waiting for broker verification.
    lock_key = f"ctrader-close:{user['id']}:{int(row[2])}:{position_id}"
    with connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (lock_key,))
        existing = conn.execute(
            """SELECT id, payload->>'volume'
                 FROM bridge_commands
                WHERE user_id=%s
                  AND command_type='close_position'
                  AND payload->>'execution_provider'='ctrader'
                  AND payload->>'account_id'=%s
                  AND payload->>'position_id'=%s
                  AND status IN ('pending','claimed','processing')
                ORDER BY id DESC
                LIMIT 1""",
            (user["id"], str(int(row[2])), str(position_id)),
        ).fetchone()
        if existing:
            if str(existing[1]) != str(volume):
                raise HTTPException(
                    409,
                    "A different close volume is already awaiting broker verification for this position. "
                    "Wait for that result before submitting another close.",
                )
            return {"queued": True, "execution": "ctrader_cloud", "command_id": int(existing[0]),
                    "position_id": position_id, "requested_close_volume": volume,
                    "duplicate_request": True,
                    "message": "This close request is already awaiting verification."}
        command_id = conn.execute(
            """INSERT INTO bridge_commands (user_id,command_type,payload)
               VALUES (%s,'close_position',%s::jsonb) RETURNING id""",
            (user["id"], __import__("json").dumps({
                "position_id": position_id,
                "account_id": int(row[2]),
                "volume": volume,
                "execution_provider": "ctrader",
                "risk_amount": 0,
            })),
        ).fetchone()[0]
    return {"queued": True, "execution": "ctrader_cloud", "command_id": int(command_id),
            "position_id": position_id, "requested_close_volume": volume,
            "duplicate_request": False}


@router.post("/ctrader/{position_id}/protect")
async def protect_ctrader_trade(position_id: int, body: dict, user=Depends(current_user)):
    """Queue a Demo-only SL/TP amendment; worker verifies broker-reconciled state."""
    from .ctrader_oauth_api import _connection_row
    from .ctrader_protection_validation import validate_protection_request

    row = _connection_row(user["id"])
    if not row or not row[0] or not row[2]:
        raise HTTPException(409, "A selected cTrader account is required")
    try:
        position_id, stop_loss, take_profit = validate_protection_request(
            position_id, stop_loss=body.get("stop_loss"), take_profit=body.get("take_profit")
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if str(row[1] or "demo").lower() != "demo":
        raise HTTPException(403, "Automated cTrader position changes are disabled for Live accounts")
    command_id = queue_bridge_command(user["id"], "protect_position", {
        "position_id": position_id,
        "account_id": int(row[2]),
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "execution_provider": "ctrader",
        "risk_amount": 0,
    })
    return {"queued": True, "execution": "ctrader_cloud", "command_id": command_id,
            "position_id": position_id, "requested_stop_loss": stop_loss,
            "requested_take_profit": take_profit}


@router.get("/ctrader/command/{command_id}")
def ctrader_command_status(command_id: int, user=Depends(current_user)):
    """Return cTrader broker outcome without translating queued into confirmed."""
    with connection() as conn:
        row = conn.execute(
            """SELECT id,command_type,status,created_at,claimed_at,completed_at,result
                 FROM bridge_commands
                WHERE id=%s AND user_id=%s AND payload->>'execution_provider'='ctrader'
                LIMIT 1""",
            (command_id, user["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(404, "cTrader command not found")
    return {
        "id": row[0], "type": row[1], "status": row[2], "created_at": row[3],
        "claimed_at": row[4], "completed_at": row[5], "result": row[6],
    }
