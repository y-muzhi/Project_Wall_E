"""Recover a durable parsed return without dispatch, counting or provider I/O."""
from datetime import datetime, timedelta
import json

from backend.app.infrastructure.guide_repository import GuideRepository
from backend.app.infrastructure.model_profile import ModelProfile
from backend.app.infrastructure.resources import ConfigInvalid, ProtocolInvalid
from backend.app.shared.command_execution import Rejected
from backend.app.infrastructure.audit_repository import AuditRepository
from .collaboration_results import _persist_in_transaction


def eligible(run, request):
    return (request.recovery_reason == 'STARTUP' and run['id'] not in request.live_run_ids or
        request.recovery_reason == 'NO_PROGRESS' and
        datetime.fromisoformat(request.operation_time[:-1]+'+00:00')-datetime.fromisoformat(run['updated_at'][:-1]+'+00:00') >= timedelta(minutes=15))


def complete_saved_returns(database, request, process_lock, catalog):
    with database.transaction() as connection:
        candidates = []
        for run in GuideRepository(connection).running():
            if not eligible(run, request): continue
            full = GuideRepository(connection).get(run['id'])
            rows = connection.execute('SELECT id,request_snapshot_json,ended_at,parse_status,call_status FROM llm_uses WHERE guide_run_id=? ORDER BY id', (run['id'],)).fetchall()
            if full['function_type'] != 'collaboration_v1' or full['current_step'] not in ('VALIDATING', 'CALLING_MODEL') or len(rows) != 1:
                continue
            row = rows[0]
            if row['ended_at'] is None or row['call_status'] != 'SUCCEEDED': continue
            candidates.append((dict(full), dict(row)))
    completed = []
    for run, row in candidates:
        try:
            # No environment credentials are loaded. This profile can only
            # validate the already persisted request and received usage.
            profile = ModelProfile.from_snapshot(json.loads(row['request_snapshot_json'])['profile'])
            process_lock.assert_owned()
            with database.transaction(write=True) as connection:
                actual = GuideRepository(connection).get(run['id'])
                if actual['status'] != 'RUNNING' or actual['updated_at'] != run['updated_at'] or not eligible(actual, request):
                    raise Rejected('STATE_CONFLICT')
                expected = run['updated_at']
                if row['parse_status'] == 'NOT_STARTED':
                    AuditRepository(connection).parse_response(row['id'], request.operation_time)
                    expected = request.operation_time
                result = _persist_in_transaction(connection, row['id'], profile=profile, catalog=catalog,
                    at=request.operation_time, recovery_updated_at=expected)
            if result['code'] == 'AI_RESULT_PERSISTED': completed.append(run['id'])
        except (Rejected, ConfigInvalid, ProtocolInvalid, ValueError, KeyError, TypeError):
            # Invalid or stale proof grants no recovery write authority. The
            # normal scan below decides from the latest actual row; storage
            # failures remain errors instead of being hidden as interruption.
            continue
    return completed
