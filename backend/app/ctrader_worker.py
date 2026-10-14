from __future__ import annotations

import asyncio
import json

from .ctrader_security import decrypt_token
from .ctrader_service import manager
from .ctrader_tokens import fresh_access_token
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
            selected_environment = str(environment or "demo").strip().lower()
            if selected_environment != "demo":
                raise RuntimeError(
                    "TradeGuard safety block: cTrader Live is read-only; broker write commands are disabled."
                )
            if command_type not in ("open_market", "close_position"):
                raise RuntimeError(f"Unsupported cTrader command: {command_type}")
            if command_type == "open_market":
                raise RuntimeError(
                    "Automated cTrader entry blocked: verified broker sizing, selected demo-account "
                    "validation, fresh quotes, and mandatory SL/TP protection are not wired "
                    "end-to-end. No order was sent."
                )

            token=fresh_access_token(str(user_id))
            await manager.authorize_account(int(account_id),token,selected_environment)
            manager.remember_account(selected_environment,int(account_id),str(user_id))

            if command_type=="close_position":
                position_id = int(payload.get("position_id") or payload.get("ticket") or 0)
                close_volume = int(payload.get("volume") or 0)
                if position_id <= 0 or close_volume <= 0:
                    raise RuntimeError(
                        "cTrader close blocked: a positive broker position ID and exact positive "
                        "remaining volume are required. No close order was sent."
                    )

                # Reconcile the selected demo account immediately before closing.
                # Never trust a stale mobile ticket or a caller-supplied volume alone.
                account_state = await manager.reconcile(int(account_id), selected_environment)
                broker_positions = list(getattr(account_state, "position", []) or [])
                matched = next(
                    (
                        position for position in broker_positions
                        if int(getattr(position, "positionId", 0) or 0) == position_id
                    ),
                    None,
                )
                if matched is None:
                    raise RuntimeError(
                        "cTrader close blocked: the position is not present on the selected "
                        "demo account. No close order was sent."
                    )
                trade_data = getattr(matched, "tradeData", None)
                remaining_volume = int(getattr(trade_data, "volume", 0) or 0)
                if remaining_volume <= 0 or close_volume > remaining_volume:
                    raise RuntimeError(
                        "cTrader close blocked: requested volume exceeds or cannot be verified "
                        "against the broker's current remaining volume. No close order was sent."
                    )

                response=await manager.close_position(
                    int(account_id),
                    position_id,
                    close_volume,
                    selected_environment,
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
