from __future__ import annotations

import asyncio
import json
import math

from .ctrader_service import manager
from .ctrader_tokens import fresh_access_token
from .notifications_api import notification_event, send_push
from .db import connection
from .ctrader_execution_guard import entry_block_reason, command_block_reason, close_binding_block_reason, bot_entry_block_reason
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


def _fail_stale_ctrader_commands() -> int:
    """Mark abandoned in-flight commands uncertain; never replay broker actions blindly."""
    result = {
        "provider": "ctrader",
        "status": "submitted_unconfirmed",
        "error": "Worker stopped responding after claiming this command. Broker outcome is unknown; reconcile the cTrader account before retrying.",
    }
    with connection() as conn:
        rows = conn.execute(
            """UPDATE bridge_commands
                  SET status='failed', completed_at=now(), result=%s::jsonb
                WHERE status='processing'
                  AND payload->>'execution_provider'='ctrader'
                  AND claimed_at < now() - interval '15 minutes'
                RETURNING id,user_id,command_type,payload""",
            (json.dumps(result),),
        ).fetchall()

    # Surface uncertain close/protection outcomes through the same Alerts path
    # as normal worker outcomes. Notification failure must not undo recovery.
    for row in rows:
        try:
            command_id, user_id, command_type, payload = row
            if isinstance(payload, str):
                payload = json.loads(payload)
            if not isinstance(payload, dict):
                payload = {}
            _publish_position_alert(
                str(user_id), command_type, payload,
                {**result, "command_id": command_id}, failed=True,
            )
        except Exception:
            pass
    return len(rows)


def _finish(command_id: int, result: dict, status: str) -> None:
    with connection() as conn:
        conn.execute(
            """UPDATE bridge_commands
                  SET status=%s,claimed_at=COALESCE(claimed_at,now()),
                      completed_at=now(),result=%s::jsonb
                WHERE id=%s AND status='processing'""",
            (status, json.dumps(result), command_id),
        )


def _validated_selected_account(account_row) -> tuple[int, str]:
    """Validate the latest selected-account row without coercing invalid IDs."""
    if not account_row or len(account_row) < 2:
        raise RuntimeError("No selected cTrader account is connected")
    raw_account_id, raw_environment = account_row[0], account_row[1]
    if isinstance(raw_account_id, bool) or not isinstance(raw_account_id, int) or raw_account_id <= 0:
        raise RuntimeError("Selected cTrader account ID is invalid; refresh accounts and select it again")
    if not isinstance(raw_environment, str) or raw_environment.strip().lower() not in ("demo", "live"):
        raise RuntimeError("Selected cTrader account has no valid environment binding; refresh accounts and select it again")
    return raw_account_id, raw_environment.strip().lower()


def _assert_selected_account_binding(user_id, account_id: int, environment: str) -> None:
    """Fail closed if the user changed the selected cTrader account while a command was waiting."""
    with connection() as conn:
        row = conn.execute(
            "SELECT account_id,environment FROM ctrader_connections WHERE user_id=%s",
            (user_id,),
        ).fetchone()
    current_account_id, current_environment = _validated_selected_account(row)
    if current_account_id != account_id:
        raise RuntimeError("Selected cTrader account changed before broker execution; request was not sent")
    if current_environment != environment:
        raise RuntimeError("Selected cTrader environment changed before broker execution; request was not sent")


def _preflight_command_block_reason(environment: str, account_id: int, command_type: str, payload) -> str | None:
    """Validate policy and queued account binding before opening a broker session."""
    reason = command_block_reason(environment, command_type, payload)
    if reason:
        return reason
    if command_type in ("close_position", "close_all_positions", "protect_position"):
        reason = close_binding_block_reason(environment, account_id, payload)
        if reason and command_type == "protect_position":
            return reason.replace("cTrader close blocked", "cTrader protection blocked")
        return reason
    return None


def _close_volume_for_snapshot(requested_volume: int, before_volume: int, manual_close: bool) -> int:
    """A manual 'close position' closes the full freshly reconciled position.

    The mobile volume is only a snapshot hint; using it as authority can leave
    a remainder if the position grew after the screen was rendered.
    """
    return before_volume if manual_close else requested_volume


def _close_all_result(environment: str, account_id: int, results: list[dict]) -> dict:
    """Summarize close attempts without treating partial reductions as full closes."""
    attempted_count = len(results)
    confirmed_closed_count = sum(item.get("status") == "confirmed_closed" for item in results)
    if attempted_count == 0:
        aggregate_status = "no_open_positions"
    elif confirmed_closed_count == attempted_count:
        aggregate_status = "confirmed_closed"
    elif confirmed_closed_count:
        aggregate_status = "partially_closed"
    else:
        aggregate_status = "unconfirmed"
    return {
        "provider": "ctrader",
        "status": aggregate_status,
        "environment": environment,
        "account_id": account_id,
        "attempted_count": attempted_count,
        "confirmed_closed_count": confirmed_closed_count,
        "positions": results,
    }


def _publish_position_alert(user_id: str, command_type: str, payload: dict, result: dict, *, failed: bool = False) -> None:
    """Record and push actionable cTrader close/protection outcomes for the Alerts tab."""
    if command_type not in ("close_position", "close_all_positions", "protect_position"):
        return
    position_id = payload.get("position_id")
    environment = str(payload.get("environment") or result.get("environment") or "selected")
    state = "failed" if failed else str(result.get("status") or "unconfirmed")
    if command_type == "close_all_positions":
        status = str(result.get("status") or "unconfirmed")
        try:
            closed = int(result.get("confirmed_closed_count"))
            attempted = int(result.get("attempted_count"))
        except (TypeError, ValueError, OverflowError):
            closed, attempted = -1, -1
        positions = result.get("positions")
        positions_are_confirmed = (
            isinstance(positions, list)
            and len(positions) == attempted
            and all(isinstance(item, dict) and item.get("status") == "confirmed_closed" for item in positions)
        )
        fully_confirmed = (
            not failed
            and status == "confirmed_closed"
            and attempted > 0
            and closed == attempted
            and positions_are_confirmed
        )
        empty_confirmed = (
            not failed
            and status == "no_open_positions"
            and attempted == 0
            and closed == 0
            and positions == []
        )
        if not (fully_confirmed or empty_confirmed):
            event_type = "notification_close_all_unconfirmed"
            title = "TradeGuard · Close-all needs review"
            if failed and "attempted_count" not in result:
                body = f"cTrader close-all on {environment} could not be completed before broker closure was verified. Check the broker account now."
            elif closed >= 0 and attempted >= 0:
                body = f"cTrader close-all on {environment}: {closed}/{attempted} positions reported closed, but the outcome is incomplete or inconsistent. Check the broker account now."
            else:
                body = f"cTrader close-all on {environment} returned an invalid result. Check the broker account now."
        else:
            event_type = "notification_close_all_confirmed"
            title = "TradeGuard · Close-all confirmed"
            body = (
                f"cTrader close-all on {environment} confirmed {closed} positions closed."
                if fully_confirmed
                else f"cTrader reported no open positions on {environment}; nothing needed closing."
            )
    elif command_type == "close_position":
        if state == "confirmed_closed":
            event_type = "notification_trade_closed"
            title = "TradeGuard · Position close confirmed"
            body = f"Position #{position_id} was confirmed closed on cTrader {environment}."
        elif state == "confirmed_reduced":
            event_type = "notification_trade_partially_closed"
            title = "TradeGuard · Partial close confirmed"
            body = f"Position #{position_id} was reduced on cTrader {environment}; check remaining volume."
        elif state == "failed":
            event_type = "notification_trade_close_failed"
            title = "TradeGuard · Position close failed"
            body = f"Position #{position_id} was not confirmed closed on cTrader {environment}. Check the position immediately."
        else:
            event_type = "notification_trade_close_unconfirmed"
            title = "TradeGuard · Close not confirmed"
            body = f"cTrader did not confirm the requested close for position #{position_id} on {environment}. Check the broker account before retrying."
    else:
        if state == "confirmed_protected":
            event_type = "notification_position_protected"
            title = "TradeGuard · Protection confirmed"
            body = f"cTrader confirmed the requested protection for position #{position_id} on {environment}."
        elif state == "failed":
            event_type = "notification_protection_failed"
            title = "TradeGuard · Protection update failed"
            body = f"Protection was not confirmed for position #{position_id} on cTrader {environment}. Check stop-loss and take-profit at the broker."
        else:
            event_type = "notification_protection_unconfirmed"
            title = "TradeGuard · Protection unconfirmed"
            body = f"cTrader did not confirm the protection update for position #{position_id} on {environment}. Check the broker account."
    details = {
        "command_type": command_type,
        "position_id": position_id,
        "environment": environment,
        "status": state,
        "result": result,
    }
    try:
        notification_event(user_id, event_type, details)
    except Exception:
        # A history-write failure must not prevent an independent push attempt.
        pass
    try:
        send_push(user_id, title, body, {"type": event_type, "position_id": position_id, "environment": environment, "status": state})
    except Exception:
        # Command outcome remains authoritative even if notification delivery fails.
        pass


async def process_ctrader_commands():
    # A crashed worker must not leave commands processing forever. Expired claims
    # are marked uncertain, never re-queued, because the broker may have acted.
    _fail_stale_ctrader_commands()

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
                       bc.command_type IN ('close_position', 'close_all_positions', 'protect_position')
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
                bot_row=conn.execute(
                    "SELECT running,emergency_stopped FROM bot_state WHERE user_id=%s",
                    (user_id,),
                ).fetchone()
            if not account_row or not account_row[0]:
                raise RuntimeError("No selected cTrader account is connected")
            account_id, environment = _validated_selected_account(account_row)

            # Fail closed for unknown account bindings. A Live account may only
            # execute an explicitly user-initiated close; automated entries and
            # SL/TP amendments stay disabled until their Live safety path is verified.
            command_block = _preflight_command_block_reason(environment, account_id, command_type, payload)
            if command_block:
                raise RuntimeError(command_block)
            if command_type == "open_market":
                if not bot_row:
                    raise RuntimeError("cTrader entry blocked: bot state is unavailable")
                bot_block = bot_entry_block_reason(bot_row[0], bot_row[1])
                if bot_block:
                    raise RuntimeError(bot_block)

            token=fresh_access_token(str(user_id))
            await manager.authorize_account(account_id,token,environment)
            manager.remember_account(environment,account_id,str(user_id))

            if command_type=="open_market":
                block_reason=entry_block_reason(environment,sizing_verified=False)
                if block_reason:
                    raise RuntimeError(block_reason)

            elif command_type=="close_all_positions":
                before = await manager.reconcile(account_id, environment)
                open_positions = list(getattr(before, "position", []) or [])
                results = []
                for position in open_positions:
                    trade_data = getattr(position, "tradeData", None)
                    raw_position_id = getattr(position, "positionId", None)
                    raw_volume = getattr(trade_data, "volume", None)
                    if isinstance(raw_position_id, bool) or not isinstance(raw_position_id, int) or raw_position_id <= 0:
                        results.append({"status": "failed", "reason": "Broker returned an invalid position ID"})
                        continue
                    try:
                        volume = validate_protocol_volume(raw_volume, field="broker position volume")
                    except ValueError:
                        results.append({"position_id": raw_position_id, "status": "failed", "reason": "Broker returned an invalid position volume"})
                        continue
                    try:
                        _assert_selected_account_binding(user_id, account_id, environment)
                        await manager.close_position(account_id, raw_position_id, volume, environment)
                        after = await manager.reconcile(account_id, environment)
                        after_volume = position_volume_snapshot(after, raw_position_id)
                        close_status = classify_close_result(volume, volume, after_volume)
                        results.append({
                            "position_id": raw_position_id,
                            "status": close_status,
                            "volume_before": volume,
                            "requested_close_volume": volume,
                            "volume_after": after_volume,
                        })
                    except Exception as close_error:
                        # Continue through the original snapshot so one broker error
                        # does not prevent attempts to close the remaining positions.
                        results.append({
                            "position_id": raw_position_id,
                            "status": "unconfirmed",
                            "reason": str(close_error)[:180],
                        })
                result = _close_all_result(environment, account_id, results)

            elif command_type=="protect_position":
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

                _assert_selected_account_binding(user_id, account_id, environment)
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
                        "environment": environment,
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
                        "environment": environment,
                        "requested_stop_loss": stop_loss,
                        "requested_take_profit": take_profit,
                        "protection_before": before_protection,
                        "response": str(response),
                        "verification_error": str(verify_error)[:180],
                    }

            else:
                raw_position_id=payload.get("position_id")
                if isinstance(raw_position_id,bool) or not isinstance(raw_position_id,int) or raw_position_id<=0:
                    raise RuntimeError("Closing a cTrader position requires a positive integer position ID")
                position_id=raw_position_id
                try:
                    requested_volume=validate_protocol_volume(payload.get("volume"),field="close volume")
                except ValueError as exc:
                    raise RuntimeError(str(exc)) from exc
                before = await manager.reconcile(account_id, environment)
                before_volume = position_volume_snapshot(before, position_id)
                if before_volume is None:
                    raise RuntimeError("Cannot close position: broker reconcile did not find that position")
                volume = _close_volume_for_snapshot(
                    requested_volume, before_volume, payload.get("manual_close") is True
                )
                if volume > before_volume:
                    raise RuntimeError("Close volume exceeds the broker-reported open position volume")
                _assert_selected_account_binding(user_id, account_id, environment)
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
                        "client_snapshot_volume": requested_volume,
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
            _publish_position_alert(user_id, command_type, payload, result)
        except Exception as exc:
            failure_result = _failed_result(str(exc)[:240])
            _finish(command_id,failure_result,"failed")
            _publish_position_alert(user_id, command_type, payload, failure_result, failed=True)


async def ctrader_command_worker():
    while True:
        try:
            await process_ctrader_commands()
        except Exception as exc:
            print(f"CTRADER_COMMAND_WORKER_ERROR: {str(exc)[:180]}",flush=True)
        await asyncio.sleep(2)
