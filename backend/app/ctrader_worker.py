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
                requested=_normalize_symbol(payload.get("symbol"))
                side=str(payload.get("side") or "").upper()
                stop_loss=payload.get("stop_loss")
                take_profit=payload.get("take_profit")
                if side not in ("BUY","SELL"):
                    raise RuntimeError("Order side must be BUY or SELL")
                if not requested:
                    raise RuntimeError("Order symbol is required")
                if stop_loss is None or take_profit is None:
                    raise RuntimeError("Automated entries require both stop-loss and take-profit levels")
                try:
                    risk_amount=float(payload.get("risk_amount") or 0)
                    distance=abs(float(payload.get("entry") or 0)-float(stop_loss))
                except (TypeError,ValueError):
                    raise RuntimeError("Risk amount, entry and stop loss must be numeric")
                if not math.isfinite(risk_amount) or risk_amount<=0 or not math.isfinite(distance) or distance<=0:
                    raise RuntimeError("Order rejected: risk amount and entry-to-stop distance must be positive")
                # Do not convert account-currency risk into broker volume by an
                # arbitrary multiplier. Exact sizing needs symbol pip value and
                # deposit-currency conversion from cTrader; fail closed until the
                # caller provides a broker-validated integer volume.
                try:
                    volume=int(payload.get("broker_volume") or 0)
                except (TypeError,ValueError):
                    volume=0
                if volume<=0:
                    raise RuntimeError("Order not sent: broker-calculated volume is missing; risk sizing is not verified for this symbol/account")

                symbols=await manager.symbols(account_id,"demo")
                match=next((symbol for symbol in getattr(symbols,"symbol",[]) if _normalize_symbol(getattr(symbol,"symbolName",""))==requested),None)
                if match is None:
                    raise RuntimeError(f"cTrader symbol not found: {payload.get('symbol')}")

                # Verify the supplied protocol volume against this broker's live
                # symbol constraints immediately before submitting the order.
                # A positive integer alone is not proof that sizing is valid.
                constraints=await manager.symbol_volume_units(account_id,int(match.symbolId),"demo")
                minimum=int(constraints.get("min_volume") or 0)
                maximum=int(constraints.get("max_volume") or 0)
                step=int(constraints.get("step_volume") or 0)
                if minimum<=0 or maximum<minimum or step<=0:
                    raise RuntimeError("Order not sent: cTrader returned incomplete volume constraints for this symbol")
                if volume<minimum or volume>maximum:
                    raise RuntimeError(
                        f"Order not sent: broker volume {volume} is outside the allowed range {minimum}–{maximum}"
                    )
                if volume % step != 0:
                    raise RuntimeError(
                        f"Order not sent: broker volume {volume} does not match this symbol's volume step {step}"
                    )
                response=await manager.new_market_order(account_id,int(match.symbolId),side,volume,"demo")
                position=getattr(response,"position",None)
                position_id=int(getattr(position,"positionId",0) or 0) if position else 0
                if not position_id:
                    reconcile=await manager.reconcile(account_id,"demo")
                    candidates=[
                        p for p in getattr(reconcile,"position",[])
                        if int(getattr(getattr(p,"tradeData",None),"symbolId",0) or 0)==int(match.symbolId)
                    ]
                    if candidates:
                        position_id=int(getattr(candidates[-1],"positionId",0) or 0)
                if not position_id:
                    raise RuntimeError("cTrader has not confirmed a position ID; check the broker account before retrying")
                await manager.protect_position(
                    account_id,position_id,stop_loss=stop_loss,take_profit=take_profit,environment="demo"
                )
                result={"provider":"ctrader","status":"submitted_and_protected","symbol":payload.get("symbol"),"position_id":position_id,"environment":"demo"}

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
