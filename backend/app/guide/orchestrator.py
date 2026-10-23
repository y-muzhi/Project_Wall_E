"""ORCH S01-S06: actual short audit stages, one wire attempt, sole C07 writer.

Private injected profile, counter and Gateway are diagnostic boundaries.
Default execution keeps approved budgets and requires versioned AI admission.
No HTTP input may select these dependencies or a model endpoint.
"""
import asyncio
from functools import partial
import sqlite3

from backend.app.infrastructure.audit_repository import AuditRepository
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.guide_repository import GuideRepository
from backend.app.infrastructure.model_profile import ModelProfile
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ResourceCatalog, ConfigInvalid, ProtocolInvalid
from backend.app.shared.command_execution import Rejected, operation_time
from backend.app.shared.http_errors import ERRORS
from backend.app.shared.validation import InvalidInput
from .context_builder import ContextLimitExceeded
from .commands import fail_guide_run
from .contracts import GUIDE_STATUSES, GUIDE_STEPS, TASK_ERROR_CODES, execute_guide_run_input, execute_guide_run_result


SAFE_MESSAGES = {key: value[2] for key, value in ERRORS.items()} | {
    'MODEL_ERROR': '模型请求未能完成', 'OUTPUT_INVALID': '模型输出未能通过程序校验',
    'CONTEXT_LIMIT_EXCEEDED': '必要上下文超出已批准预算',
}


def _state(database, identity):
    with database.transaction() as connection:
        row = GuideRepository(connection).get(identity)
        if row is None: raise Rejected('NOT_FOUND')
        row = dict(row)
        if row['status'] not in GUIDE_STATUSES or row['current_step'] not in GUIDE_STEPS:
            raise Rejected('WORK_STATE_INCONSISTENT')
        last = connection.execute('SELECT max(call_no) FROM llm_uses WHERE guide_run_id=?', (identity,)).fetchone()[0]
        return row, last


_result = execute_guide_run_result


async def _native(function, *args, **kwargs):
    """Keep the event loop responsive and finish the current native stage.

    Cancellation does not turn an in-flight SQLite commit into a rollback.
    The worker must persist logical cancellation/recovery before retiring work.
    """
    task = asyncio.create_task(asyncio.to_thread(partial(function, *args, **kwargs)))
    try: return await asyncio.shield(task)
    except asyncio.CancelledError:
        # A second cancellation must not detach a still-writing thread.
        while not task.done():
            try: await asyncio.shield(task)
            except asyncio.CancelledError: continue
            except Exception: break
        if task.done() and not task.cancelled(): task.exception()
        raise


def _transport(database, identity, value, profile, clock):
    with database.transaction(write=True) as connection:
        return dict(AuditRepository(connection).record_transport(identity, value.raw_response, operation_time(clock),
            profile=profile, succeeded=value.succeeded, duration_ms=value.duration_ms,
            input_tokens=value.input_tokens, output_tokens=value.output_tokens, provider_request_id=value.provider_request_id,
            finish_reason=value.finish_reason, cache_info=value.cache_info))


def _parse(database, identity, clock):
    with database.transaction(write=True) as connection:
        return AuditRepository(connection).parse_response(identity, operation_time(clock))


async def execute_guide_run(database, payload, *, process_lock, catalog=None, profile=None,
                      gateway=None, counting_counter=None, clock=None, observation=None):
    """One accepted V1.5 run, bounded counts and at most one actual Chat.

    Explicit private offline dependencies cannot bypass the release gate.
    Continuation/retry commands create a new run; no loop resumes old input.
    """
    try:
        identity = execute_guide_run_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}

    async def state(): return await _native(_state, database, identity)

    async def write_failure(code):
        row, last = await state()
        if row['status'] != 'RUNNING': return _result('AI_STOPPED', row, last)
        code = code if code in TASK_ERROR_CODES else 'INTERNAL_ERROR'
        outcome = await _native(fail_guide_run, database, {'guide_run_id': identity, 'error_code': code,
            'safe_message': SAFE_MESSAGES.get(code, SAFE_MESSAGES['INTERNAL_ERROR'])}, process_lock=process_lock, clock=clock)
        if outcome['code'] not in ('RUN_FAILED', 'RUN_FINAL_UNCHANGED'): return outcome
        row, last = await state()
        if outcome['code'] == 'RUN_FINAL_UNCHANGED': return _result('AI_STOPPED', row, last)
        if row['status'] != 'FAILED' or row['error_code'] != code: raise ValueError('Failure receipt disagrees with actual state')
        return {'code': 'AI_FAILED', 'data': None, 'details': {'guide_run_id': identity, 'error_code': code}}

    async def fail(code):
        try: return await write_failure(code)
        except asyncio.CancelledError: raise
        except Rejected as error: return {'code': error.code, 'data': None, 'details': None}
        except (StorageUnavailable, sqlite3.Error): return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
        except Exception: return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}

    try:
        process_lock.assert_owned()
        if process_lock.path != ProcessLock.for_database(database.path).path: raise RuntimeError('ORCH must own this database')
        row, last = await state()
        if row['status'] != 'RUNNING': return _result('AI_STOPPED', row, last)
        if row['current_step'] != 'PREPARING':
            return {'code': 'STATE_CONFLICT', 'data': None, 'details': None}
        resources = ResourceCatalog() if catalog is None else catalog
        frozen_profile = ModelProfile.from_environment() if profile is None else profile
        if type(frozen_profile) is not ModelProfile: raise ConfigInvalid('Frozen profile is required')
        if row['function_type'] != 'collaboration_v1':
            raise ConfigInvalid('Only the current collaboration protocol can execute')
        from .collaboration_execution import execute_collaboration
        return await execute_collaboration(database, identity, process_lock=process_lock, catalog=resources,
            profile=frozen_profile, gateway=gateway, counting_counter=counting_counter,
            native=_native, state=state, fail=fail, clock=clock, observation=observation)
    except asyncio.CancelledError:
        raise
    except ContextLimitExceeded:
        return await fail('CONTEXT_LIMIT_EXCEEDED')
    except (ConfigInvalid, ProtocolInvalid):
        return await fail('CONFIG_INVALID')
    except Rejected as error:
        if error.code == 'NOT_FOUND': return {'code': 'NOT_FOUND', 'data': None, 'details': None}
        try:
            row, last = await state()
            if row['status'] != 'RUNNING': return _result('AI_STOPPED', row, last)
            # A duplicate dispatcher may lose to the original task's prepare.
            # It cannot fail that task's still-owned request.
            if error.code == 'STATE_CONFLICT': return {'code': 'STATE_CONFLICT', 'data': None, 'details': None}
            return await fail(error.code)
        except Rejected as failure:
            return {'code': failure.code, 'data': None, 'details': None}
        except (StorageUnavailable, sqlite3.Error):
            return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
        except Exception:
            return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}
    except (StorageUnavailable, sqlite3.Error):
        try: return await fail('STORAGE_UNAVAILABLE')
        except (StorageUnavailable, sqlite3.Error): return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
    except Exception:
        try: return await fail('INTERNAL_ERROR')
        except Exception: return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}
