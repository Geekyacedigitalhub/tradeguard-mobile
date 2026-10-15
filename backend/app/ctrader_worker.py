from __future__ import annotations

import asyncio
import json

from .ctrader_service import _positive_int, manager
from .ctrader_tokens import fresh_access_token
from .db import connection


def _close_effect_confirmed(previous_volume: int, requested_volume: int, observed_remaining_volume: int | None) -> bool:
    """Only confirm a close when reconciliation proves the requested reduction."""
    if observed_remaining_volume is None:
        return True
    expected_maximum = previous_volume - requested_volume
    return observed_remaining_volume > 0 and expected_maximum >= 0 and observed_remaining_volume <= expected_maximum


def _normalize_symbol(value: str) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())

async def process_ctrader_commands():
    # Claim work atomically before leaving the DB transaction. Multiple API
    # workers/instances must never process the same broker command concurrently.
    with connection() as conn:
        rows=conn.execute(
            """WITH candidates AS (
                   SELECT bc.id
                     FROM bridge_commands bc
                     JOIN ctrader_connections cc ON cc.user_id=bc.user_id
                    WHERE bc.status='pending'
                      AND cc.account_id IS NOT NULL
                      AND bc.payload ? 'risk_amount'
                    ORDER BY bc.id
                    FOR UPDATE OF bc SKIP LOCKED
                    LIMIT 10
               )
               UPDATE bridge_commands bc
                  SET status='processing',claimed_at=now()
                 FROM candidates c
                WHERE bc.id=c.id AND bc.status='pending'
               RETURNING bc.id,bc.user_id,bc.command_type,bc.payload,
                         (SELECT cc.account_id FROM ctrader_connections cc WHERE cc.user_id=bc.user_id),
                         (SELECT cc.environment FROM ctrader_connections cc WHERE cc.user_id=bc.user_id)
            """
        ).fetchall()

    for command_id,user_id,command_type,payload,account_id,environment in rows:
        close_submission_started = False
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
                position_id = _positive_int(
                    payload.get("position_id") or payload.get("ticket"),
                    "position_id",
                )
                close_volume = _positive_int(payload.get("volume"), "volume")

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

                # A close response only proves the request was acknowledged. Verify
                # the broker's resulting position state before marking the command complete.
                close_submission_started = True
                response=await manager.close_position(
                    int(account_id),
                    position_id,
                    close_volume,
                    selected_environment,
                )
                after_state = await manager.reconcile(int(account_id), selected_environment)
                after_positions = list(getattr(after_state, "position", []) or [])
                after_match = next(
                    (
                        position for position in after_positions
                        if int(getattr(position, "positionId", 0) or 0) == position_id
                    ),
                    None,
                )
                after_trade_data = getattr(after_match, "tradeData", None) if after_match is not None else None
                after_volume = int(getattr(after_trade_data, "volume", 0) or 0) if after_trade_data is not None else 0
                confirmed = _close_effect_confirmed(
                    remaining_volume,
                    close_volume,
                    None if after_match is None else after_volume,
                )
                if confirmed:
                    command_status = "completed"
                    result={
                        "provider":"ctrader",
                        "status":"confirmed",
                        "outcome":"broker_position_reconciled",
                        "position_id":position_id,
                        "requested_close_volume":close_volume,
                        "remaining_volume":after_volume,
                        "response":str(response),
                    }
                else:
                    command_status = "failed"
                    result={
                        "provider":"ctrader",
                        "status":"outcome_unknown",
                        "outcome":"close_not_confirmed_by_reconciliation",
                        "position_id":position_id,
                        "requested_close_volume":close_volume,
                        "previous_remaining_volume":remaining_volume,
                        "observed_remaining_volume":after_volume,
                        "retry_safe":False,
                        "message":"The close request was acknowledged, but the broker position change could not be confirmed. Do not retry until the account is reconciled manually.",
                    }
            else:
                raise RuntimeError(f"Unsupported cTrader command: {command_type}")

            with connection() as conn:
                conn.execute(
                    """UPDATE bridge_commands
                          SET status=%s,claimed_at=COALESCE(claimed_at,now()),
                              completed_at=now(),result=%s::jsonb
                        WHERE id=%s AND status='processing'""",
                    (command_status if command_type == "close_position" else "completed",json.dumps(result),command_id),
                )
        except Exception as exc:
            failure = {
                "provider":"ctrader",
                "status":"outcome_unknown" if close_submission_started else "failed",
                "error":str(exc),
                "retry_safe":False if close_submission_started else True,
            }
            if close_submission_started:
                failure["message"] = (
                    "A close request may have reached cTrader, but its outcome could not be verified. "
                    "Do not retry until the account is reconciled manually."
                )
            with connection() as conn:
                conn.execute(
                    """UPDATE bridge_commands
                          SET status='failed',claimed_at=COALESCE(claimed_at,now()),
                              completed_at=now(),result=%s::jsonb
                        WHERE id=%s AND status='processing'""",
                    (json.dumps(failure),command_id),
                )

async def ctrader_command_worker():
    while True:
        try:
            await process_ctrader_commands()
        except Exception:
            pass
        await asyncio.sleep(2)
