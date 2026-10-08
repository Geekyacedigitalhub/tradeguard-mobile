from __future__ import annotations

import asyncio
import json

from .ctrader_security import decrypt_token
from .ctrader_service import manager
from .db import connection

def _normalize_symbol(value: str) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())

async def process_ctrader_commands():
    with connection() as conn:
        rows=conn.execute(
            """SELECT bc.id,bc.user_id,bc.command_type,bc.payload,
                      cc.account_id,cc.environment,cc.access_token
                 FROM bridge_commands bc
                 JOIN ctrader_connections cc ON cc.user_id=bc.user_id
                WHERE bc.status='pending'
                  AND cc.account_id IS NOT NULL
                  AND bc.payload ? 'risk_amount'
                ORDER BY bc.id
                LIMIT 10"""
        ).fetchall()

    for command_id,user_id,command_type,payload,account_id,environment,encrypted_token in rows:
        try:
            token=decrypt_token(encrypted_token)
            await manager.authorize_account(int(account_id),token,environment or "demo")
            manager.remember_account(environment or "demo",int(account_id),str(user_id))

            if command_type=="open_market":
                symbols=await manager.symbols(int(account_id),environment or "demo")
                requested=_normalize_symbol(payload.get("symbol"))
                match=None
                for symbol in getattr(symbols,"symbol",[]):
                    if _normalize_symbol(getattr(symbol,"symbolName",""))==requested:
                        match=symbol
                        break
                if match is None:
                    raise RuntimeError(f"cTrader symbol not found: {payload.get('symbol')}")

                quantity=float(payload.get("quantity") or 0)
                volume=max(1,int(round(quantity*100)))
                response=await manager.new_market_order(
                    int(account_id),
                    int(match.symbolId),
                    str(payload.get("side") or "BUY"),
                    volume,
                    stop_loss=payload.get("stop_loss"),
                    take_profit=payload.get("take_profit"),
                    environment=environment or "demo",
                )
                result={"provider":"ctrader","status":"submitted","symbol":payload.get("symbol"),"response":str(response)}

            elif command_type=="close_position":
                response=await manager.close_position(
                    int(account_id),
                    int(payload.get("position_id") or payload.get("ticket") or 0),
                    int(payload.get("volume") or 0),
                    environment or "demo",
                )
                result={"provider":"ctrader","status":"submitted","response":str(response)}
            else:
                raise RuntimeError(f"Unsupported cTrader command: {command_type}")

            with connection() as conn:
                conn.execute(
                    """UPDATE bridge_commands
                          SET status='completed',claimed_at=COALESCE(claimed_at,now()),
                              completed_at=now(),result=%s::jsonb
                        WHERE id=%s AND status='pending'""",
                    (json.dumps(result),command_id),
                )
        except Exception as exc:
            with connection() as conn:
                conn.execute(
                    """UPDATE bridge_commands
                          SET status='failed',claimed_at=COALESCE(claimed_at,now()),
                              completed_at=now(),result=%s::jsonb
                        WHERE id=%s AND status='pending'""",
                    (json.dumps({"provider":"ctrader","status":"failed","error":str(exc)}),command_id),
                )

async def ctrader_command_worker():
    while True:
        try:
            await process_ctrader_commands()
        except Exception:
            pass
        await asyncio.sleep(2)
