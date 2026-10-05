"""ORCH S01-S06: actual short audit stages, one wire attempt, sole C07 writer.

Private injected compiler/compatibility/Gateway/sleep are diagnostic boundaries.
Default execution keeps approved budgets and refuses unproved Provider counting.
No HTTP input may select these dependencies or a model endpoint.
"""
import asyncio
from functools import partial
import sqlite3

from backend.app.infrastructure.audit_repository import AuditRepository, _owned
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.guide_repository import GuideRepository
from backend.app.infrastructure.model_gateway import ModelGateway
from backend.app.infrastructure.model_profile import ModelProfile
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ResourceCatalog, ConfigInvalid, ProtocolInvalid
from backend.app.shared.command_execution import Rejected, operation_time
from backend.app.shared.http_errors import ERRORS
from backend.app.shared.validation import InvalidInput
from .context_builder import build_context, ContextLimitExceeded
from .model_context import read_context
from .trusted_output import produce_trusted_output
from .commands import persist_ai_result, fail_guide_run
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


def _context(database, identity, resources):
    with database.transaction() as connection:
        actual = read_context(connection, identity, resources)['data']
        row = actual['run']
        function = resources.restore(row['function_type'], row['prompt_version'],
            prompt_version=row['prompt_version'], context_template=row['context_template_key']+'@'+row['context_template_version'])
        return actual, function


def _prepare(database, identity, function, profile, context, resources, clock, call_no):
    with database.transaction(write=True) as connection:
        return dict(AuditRepository(connection).prepare(identity, function, profile, context,
            operation_time(clock), catalog=resources, call_no=call_no))


def _transport(database, identity, value, profile, clock):
    with database.transaction(write=True) as connection:
        return dict(AuditRepository(connection).record_transport(identity, value.raw_response, operation_time(clock),
            profile=profile, succeeded=value.succeeded, duration_ms=value.duration_ms,
            input_tokens=value.input_tokens, output_tokens=value.output_tokens, provider_request_id=value.provider_request_id,
            finish_reason=value.finish_reason, cache_info=value.cache_info))


def _parse(database, identity, clock):
    with database.transaction(write=True) as connection:
        return AuditRepository(connection).parse_response(identity, operation_time(clock))


def _retry_context(database, identity, resources, original, profile, compiler):
    # Re-read all actual source/current/owner facts before sleeping or sending;
    # Builder keeps whole input and the same frozen protocol and approved gates.
    with database.transaction() as connection:
        run = GuideRepository(connection).get(identity); _owned(connection, run)
    actual, function = _context(database, identity, resources)
    if function != original: raise Rejected('CONFIG_INVALID')
    return compiler(actual, function)


async def execute_guide_run(database, payload, *, process_lock, catalog=None, profile=None,
                      gateway=None, context_compiler=build_context, compatibility_check=None,
                      clock=None, sleep=asyncio.sleep):
    """One logical input; WAITING_USER resumes only via its real accepting command.

    A missing compatibility check is an explicit unresolved production dependency,
    never authorization to send a paid request. Diagnostic tests install an
    offline check and expanded-budget compiler together with loopback transport.
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
        actual, function = await _native(_context, database, identity, resources)
        frozen_profile = ModelProfile.from_environment() if profile is None else profile
        if type(frozen_profile) is not ModelProfile: raise ConfigInvalid('Frozen profile is required')
        context = await _native(context_compiler, actual, function)
        if compatibility_check is None: raise ConfigInvalid('Approved same-model tokenizer/framing proof is unavailable')
        if await _native(compatibility_check, frozen_profile, context, function) is not True:
            raise ConfigInvalid('Counting compatibility was not proved')
        adapter = ModelGateway() if gateway is None else gateway
        call_no = None
        for attempt in range(1, 4):
            prepared = await _native(_prepare, database, identity, function, frozen_profile, context, resources, clock, call_no)
            call_no = prepared['call_no']
            # The request fact is now committed; network I/O owns no SQL txn.
            wire = await adapter.send(frozen_profile, context)
            await _native(_transport, database, prepared['id'], wire, frozen_profile, clock)
            row, last = await state()
            if row['status'] != 'RUNNING': return _result('AI_STOPPED', row, last)
            error_code = 'MODEL_ERROR'
            retryable = wire.retryable
            if wire.succeeded:
                parsed = await _native(_parse, database, prepared['id'], clock)
                error_code = 'OUTPUT_INVALID'
                retryable = wire.category != 'CONTENT_FILTER'
                if parsed is not None:
                    receipt = await _native(produce_trusted_output, database, prepared['id'], process_lock=process_lock,
                        profile=frozen_profile, catalog=resources, clock=clock)
                    if receipt is not None:
                        outcome = await _native(persist_ai_result, database, {'guide_run_id': identity,
                            'llm_use_id': prepared['id'], 'trusted_output': receipt}, process_lock=process_lock,
                            profile=frozen_profile, catalog=resources, clock=clock)
                        if outcome['code'] == 'AI_RESULT_PERSISTED':
                            status = outcome['data']['status']
                            code = 'AI_WAITING_USER' if status == 'WAITING_USER' else 'AI_FINISHED'
                            # Return this actual commit receipt even if the
                            # user already continued/cancelled the waiting run.
                            return _result(code, {'id': identity, 'status': status,
                                'current_step': 'WAITING_USER' if status == 'WAITING_USER' else 'FINISHED'}, call_no)
                        # Business state changes and storage/commit ambiguity
                        # never authorize an additional model request.
                        return await fail(outcome['code'])
            if not retryable or attempt == 3: return await fail(error_code)
            context = await _native(_retry_context, database, identity, resources, function, frozen_profile, context_compiler)
            await sleep(2 if attempt == 1 else 5)
            # A cancellation/version/source change during the backoff is
            # caught before the next persisted request or external send.
            context = await _native(_retry_context, database, identity, resources, function, frozen_profile, context_compiler)
            if await _native(compatibility_check, frozen_profile, context, function) is not True:
                raise ConfigInvalid('Counting compatibility was not proved')
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
