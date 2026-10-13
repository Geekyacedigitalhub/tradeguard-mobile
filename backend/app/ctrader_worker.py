from __future__ import annotations

import asyncio
import json
import math

from .ctrader_service import manager
from .ctrader_tokens import fresh_access_token
from .db import connection
from .ctrader_execution_guard import entry_block_reason, command_block_reason, close_binding_block_reason
from .ctrader_volume_validation import validate_protocol_volume
from .ctrader_close_verification import (
    position_volume_snapshot,
    classify_close_result,
    protection_snapshot,
    classify_protection_result,
)


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
                      AND (
                       bc.command_type IN ('close_position', 'protect_position')
                       OR bc.payload ? 'risk_amount'
                      )
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
            raw_environment = account_row[1]
            if not isinstance(raw_environment, str) or raw_environment.strip().lower() not in ("demo", "live"):
                raise RuntimeError("Selected cTrader account has no valid environment binding; refresh accounts and select it again")
            environment = raw_environment.strip().lower()

            # Fail closed for unknown account bindings. A Live account may only
            # execute an explicitly user-initiated close; automated entries and
            # SL/TP amendments stay disabled until their Live safety path is verified.
            command_block = command_block_reason(environment, command_type, payload)
            if command_block:
                raise RuntimeError(command_block)

            token=fresh_access_token(str(user_id))
            await manager.authorize_account(account_id,token,environment)
            manager.remember_account(environment,account_id,str(user_id))

            if command_type=="open_market":
                block_reason=entry_block_reason(environment,sizing_verified=False)
                if block_reason:
                    raise RuntimeError(block_reason)

            elif command_type=="protect_position":
                queued_account_id = payload.get("account_id")
                if isinstance(queued_account_id, bool) or not isinstance(queued_account_id, int) or queued_account_id <= 0:
                    raise RuntimeError("Protection command is missing its selected cTrader account binding")
                if queued_account_id != account_id:
                    raise RuntimeError("Selected cTrader account changed after this protection command was queued")
                raw_position_id = payload.get("position_id")
                if isinstance(raw_position_id, bool) or not isinstance(raw_position_id, int) or raw_position_id <= 0:
                    raise RuntimeError("Protecting a cTrader position requires a positive integer position ID")
                position_id = raw_position_id
                stop_loss = payload.get("stop_loss")
                take_profit = payload.get("take_profit")
                try:
                    from .ctrader_protection_validation import validate_protection_request
                    position_id, stop_loss, take_profit = validate_protection_request(
                        position_id, stop_loss=stop_loss, take_profit=take_profit
                    )
                except ValueError as exc:
                    raise RuntimeError(str(exc)) from exc

                before_response = await manager.reconcile(account_id, environment)
                before_protection = protection_snapshot(before_response, position_id)
                if before_protection is None:
                    raise RuntimeError("Cannot protect position: broker reconcile did not find that position")

                response = await manager.protect_position(
                    account_id, position_id, stop_loss=stop_loss,
                    take_profit=take_profit, environment=environment
                )
                try:
                    after_response = await manager.reconcile(account_id, environment)
                    after_protection = protection_snapshot(after_response, position_id)
                    protection_status = classify_protection_result(
                        before_protection, stop_loss, take_profit, after_protection
                    )
                    result = {
                        "provider": "ctrader",
                        "status": protection_status,
                        "position_id": position_id,
                        "environment": "demo",
                        "requested_stop_loss": stop_loss,
                        "requested_take_profit": take_profit,
                        "protection_before": before_protection,
                        "protection_after": after_protection,
                        "response": str(response),
                    }
                except Exception as verify_error:
                    result = {
                        "provider": "ctrader",
                        "status": "submitted_unconfirmed",
                        "position_id": position_id,
                        "environment": "demo",
                        "requested_stop_loss": stop_loss,
                        "requested_take_profit": take_profit,
                        "protection_before": before_protection,
                        "response": str(response),
                        "verification_error": str(verify_error)[:180],
                    }

            else:
                close_binding_block = close_binding_block_reason(environment, account_id, payload)
                if close_binding_block:
                    raise RuntimeError(close_binding_block)
                raw_position_id=payload.get("position_id")
                if isinstance(raw_position_id,bool) or not isinstance(raw_position_id,int) or raw_position_id<=0:
                    raise RuntimeError("Closing a cTrader position requires a positive integer position ID")
                position_id=raw_position_id
                try:
                    volume=validate_protocol_volume(payload.get("volume"),field="close volume")
                except ValueError as exc:
                    raise RuntimeError(str(exc)) from exc
                before = await manager.reconcile(account_id, environment)
                before_volume = position_volume_snapshot(before, position_id)
                if before_volume is None:
                    raise RuntimeError("Cannot close position: broker reconcile did not find that position")
                if volume > before_volume:
                    raise RuntimeError("Close volume exceeds the broker-reported open position volume")
                response = await manager.close_position(account_id, position_id, volume, environment)
                try:
                    after = await manager.reconcile(account_id, environment)
                    after_volume = position_volume_snapshot(after, position_id)
                    close_status = classify_close_result(before_volume, volume, after_volume)
                    result = {
                        "provider": "ctrader",
                        "status": close_status,
                        "position_id": position_id,
                        "environment": environment,
                        "requested_close_volume": volume,
                        "volume_before": before_volume,
                        "volume_after": after_volume,
                        "response": str(response),
                    }
                except Exception as verify_error:
                    # The close request may already have reached the broker.
                    # Preserve that uncertainty instead of falsely reporting failure.
                    result = {
                        "provider": "ctrader",
                        "status": "submitted_unconfirmed",
                        "position_id": position_id,
                        "environment": environment,
                        "requested_close_volume": volume,
                        "volume_before": before_volume,
                        "response": str(response),
                        "verification_error": str(verify_error)[:180],
                    }

            # Queue completion means the attempt finished; broker confirmation is separate.
            # Polling clients must inspect result.status before claiming an outcome.
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
