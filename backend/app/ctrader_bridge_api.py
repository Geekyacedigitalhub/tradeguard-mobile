import json
from datetime import datetime, timezone
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from .db import connection
from .bridge_api import require_bridge
from .learning import open_broker_trade, close_broker_trade

BRIDGE_ID = "cloud-ctrader-bot"
router = APIRouter(prefix="/v1/ctrader", tags=["ctrader-cloud"])

class Heartbeat(BaseModel):
    user_id: str
    account: str | None = None
    environment: str = "demo"
    terminal: str = "cTrader Cloud"
    connected: bool = False
    balance: float | None = None
    equity: float | None = None
    today_pl: float | None = None
    positions: list[dict] = []

class CommandResult(BaseModel):
    command_id: int
    status: str
    result: dict = {}

def _auth(user_id: str, x_bridge_token: str | None):
    if not x_bridge_token:
        raise HTTPException(401, "cTrader runtime token is required")
    return require_bridge(None, user_id, BRIDGE_ID, x_bridge_token)

@router.post("/heartbeat")
def heartbeat(body: Heartbeat, x_bridge_token: str | None = Header(default=None)):
    user_id = _auth(body.user_id, x_bridge_token)
    payload = {
        "connected": body.connected,
        "provider": "cTrader",
        "environment": body.environment,
        "account": body.account,
        "terminal": body.terminal,
        "balance": body.balance,
        "equity": body.equity,
        "today_pl": body.today_pl,
        "positions": body.positions,
    }
    with connection() as conn:
        conn.execute(
            "INSERT INTO audit_events (user_id,event_type,payload) VALUES (%s,'broker_connection',%s::jsonb)",
            (user_id, json.dumps(payload)),
        )
        if body.balance is not None or body.equity is not None:
            conn.execute(
                """UPDATE account_state
                   SET balance=COALESCE(%s,balance),
                       equity=COALESCE(%s,equity),
                       today_pl=COALESCE(%s,today_pl),
                       updated_at=now()
                   WHERE user_id=%s""",
                (body.balance, body.equity, body.today_pl, user_id),
            )
    return {"ok": True, "provider": "cTrader", "bridge_id": BRIDGE_ID}

@router.get("/commands")
def commands(limit: int = 1, user_id: str | None = None, x_bridge_token: str | None = Header(default=None)):
    if not user_id:
        raise HTTPException(400, "user_id is required")
    resolved = _auth(user_id, x_bridge_token)
    limit = max(1, min(int(limit), 5))
    with connection() as conn:
        rows = conn.execute(
            """SELECT id,command_type,payload
               FROM bridge_commands
              WHERE user_id=%s AND status='pending'
              ORDER BY id
              LIMIT %s""",
            (resolved, limit),
        ).fetchall()
        commands = []
        for command_id, command_type, payload in rows:
            updated = conn.execute(
                """UPDATE bridge_commands
                      SET status='claimed',claimed_at=now()
                    WHERE id=%s AND user_id=%s AND status='pending'
                RETURNING id""",
                (command_id, resolved),
            ).fetchone()
            if updated:
                commands.append({"id": int(command_id), "type": command_type, "payload": payload or {}})
    return {"commands": commands}

@router.post("/commands/result")
def command_result(body: CommandResult, user_id: str | None = None, x_bridge_token: str | None = Header(default=None)):
    if not user_id:
        raise HTTPException(400, "user_id is required")
    resolved = _auth(user_id, x_bridge_token)
    with connection() as conn:
        row = conn.execute(
            """UPDATE bridge_commands
                  SET status=%s,completed_at=now(),result=%s::jsonb
                WHERE id=%s AND user_id=%s AND status='claimed'
            RETURNING command_type,payload""",
            (body.status, json.dumps(body.result or {}), body.command_id, resolved),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Command not found or already completed")

    command_type, payload = row
    result = body.result or {}
    if body.status == "completed" and command_type == "open_market":
        position = result.get("position") or {}
        ticket = position.get("id") or result.get("position_id")
        if ticket is not None:
            open_broker_trade(
                resolved,
                ticket,
                position.get("symbol") or payload.get("symbol") or "UNKNOWN",
                position.get("side") or payload.get("side") or "",
                position.get("entry") or payload.get("entry"),
                position.get("stop_loss") or payload.get("stop_loss"),
                position.get("take_profit") or payload.get("take_profit"),
                {**(payload.get("learning_context") or {}), "broker": "cTrader"},
            )
    elif body.status == "completed" and command_type == "close_position":
        position = result.get("position") or {}
        ticket = position.get("id") or payload.get("ticket")
        close_broker_trade(
            resolved,
            ticket,
            position.get("exit_price") or result.get("exit_price") or 0,
            position.get("pnl") or result.get("pnl") or 0,
            result.get("reason") or "cTrader close",
        )
    return {"ok": True, "command_id": body.command_id}

@router.get("/status")
def status(user_id: str, x_bridge_token: str | None = Header(default=None)):
    resolved = _auth(user_id, x_bridge_token)
    with connection() as conn:
        row = conn.execute(
            """SELECT payload,created_at
                 FROM audit_events
                WHERE user_id=%s AND event_type='broker_connection'
                ORDER BY created_at DESC LIMIT 1""",
            (resolved,),
        ).fetchone()
    if not row:
        return {"connected": False, "provider": "cTrader", "stale": True}
    payload = row[0] or {}
    age = max(0.0, (datetime.now(timezone.utc) - row[1]).total_seconds())
    connected = bool(payload.get("connected")) and age <= 45 and payload.get("terminal") == "cTrader Cloud"
    return {
        "connected": connected,
        "provider": "cTrader",
        "terminal": payload.get("terminal"),
        "environment": payload.get("environment"),
        "account": payload.get("account"),
        "balance": payload.get("balance"),
        "equity": payload.get("equity"),
        "positions": payload.get("positions") if connected else [],
        "heartbeat_age_seconds": round(age, 1),
    }
