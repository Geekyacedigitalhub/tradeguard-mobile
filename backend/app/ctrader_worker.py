from __future__ import annotations

import asyncio
import json
import math

from .ctrader_service import manager
from .ctrader_tokens import fresh_access_token
from .db import connection


def _normalize_symbol(value: str) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def _failed_result(reason: str) -> dict:
    return {"provider": "ctrader", "status": "failed", "error": reason}


def _finish(command_id: int, result: dict, status: str) -> None:
    with connection() as conn:
        conn.execute(
            """UPDATE bridge_commands
                  SET status=%s,claimed_at=COALESCE(claimed_at,now()),
                      completed_at=now(),result=%s::jsonb
                WHERE id=%s AND status='processing'""",
            (status, json.dumps(result), command_id),
        )


async def process_ctrader_commands():
    # Claim commands atomically so two cloud workers cannot execute the same
    # queued trade. Only TradeGuard-generated cTrader commands are eligible.
    with connection() as conn:
        rows=conn.execute(
            """WITH eligible AS (
                   SELECT bc.id
                     FROM bridge_commands bc
                     JOIN ctrader_connections cc ON cc.user_id=bc.user_id
                    WHERE bc.status='pending'
                      AND cc.account_id IS NOT NULL
                      AND bc.payload->>'execution_provider'='ctrader'
                      AND bc.payload ? 'risk_amount'
                    ORDER BY bc.id
                    FOR UPDATE OF bc SKIP LOCKED
                    LIMIT 10
               )
               UPDATE bridge_commands bc
                  SET status='processing',claimed_at=COALESCE(bc.claimed_at,now())
                 FROM eligible
                WHERE bc.id=eligible.id
               RETURNING bc.id,bc.user_id,bc.command_type,bc.payload""",
        ).fetchall()

    for command_id,user_id,command_type,payload in rows:
        try:
            with connection() as conn:
                account_row=conn.execute(
                    "SELECT account_id,environment FROM ctrader_connections WHERE user_id=%s",
                    (user_id,),
                ).fetchone()
            if not account_row or not account_row[0]:
                raise RuntimeError("No selected cTrader account is connected")
            account_id=int(account_row[0])
            environment=str(account_row[1] or "demo").lower()

            # Live account selection is deliberately read-only. This server-side
            # guard runs after command claim but before broker authorization or orders.
            if environment != "demo":
                raise RuntimeError("Automated orders are disabled for cTrader Live accounts; select a Demo account")
            if command_type not in ("open_market","close_position"):
                raise RuntimeError(f"Unsupported cTrader command: {command_type}")

            token=fresh_access_token(str(user_id))
            await manager.authorize_account(account_id,token,"demo")
            manager.remember_account("demo",account_id,str(user_id))

            if command_type=="open_market":
                # Fail closed: validating a protocol-volume step is not the same
                # as proving the requested account-currency risk. The full
                # broker-value conversion and sizing path is not wired end-to-end.
                raise RuntimeError(
                    "Automated entries are paused until broker-verified account-currency "
                    "risk sizing is connected and tested for this symbol and account"
                )

            else:
                position_id=int(payload.get("position_id") or 0)
                volume=int(payload.get("volume") or 0)
                if position_id<=0 or volume<=0:
                    raise RuntimeError("Closing a cTrader position requires a valid position ID and broker volume")
                response=await manager.close_position(account_id,position_id,volume,"demo")
                result={"provider":"ctrader","status":"submitted","position_id":position_id,"environment":"demo","response":str(response)}

            _finish(command_id,result,"completed")
        except Exception as exc:
            _finish(command_id,_failed_result(str(exc)[:240]),"failed")


async def ctrader_command_worker():
    while True:
        try:
            await process_ctrader_commands()
        except Exception as exc:
            print(f"CTRADER_COMMAND_WORKER_ERROR: {str(exc)[:180]}",flush=True)
        await asyncio.sleep(2)
