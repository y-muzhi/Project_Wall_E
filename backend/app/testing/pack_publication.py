"""Publish only the sealed pack whose original complete validation qualifies."""

import sqlite3
from contextlib import ExitStack
from dataclasses import dataclass
from time import monotonic

from backend.app.code_tasks.configuration_identities import require_schema
from backend.app.infrastructure.check_runner_bundle import CheckResourceError
from backend.app.infrastructure.command_receipts import Rejection, read_registered_replay
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import IdempotencyConflict, RequestInProgress
from backend.app.infrastructure.identifiers import increment
from backend.app.shared.command_execution import ConfigurationNotReady, operation_time
from backend.app.shared.validation import strict_json_loads, strict_json_object

from .asset_installation import hold_compiler_sources
from .assets import NOT_FOUND, sealed_pack_facts
from .pack_compile import CompileError, basis_fingerprint, compile_pack
from .pack_lifecycle import mutate_pack, pack_rejection, save_lifecycle_operation
from .pack_seal import RESOURCE_ERRORS, SealRejected, original_targets
from .pack_storage import hold_sealed_pack, pack_content_ref
from .pack_validation import find_registered_reference, original_validation, validation_schedule
from .plans import _version
from .reference_resources import hold_reference_set, original_baselines
from .validation_evidence import passing_children

PUBLISH_PACK = 'PUBLISH_PACK'


@dataclass(frozen=True)
class Publication:
    pack_id: int
    pack_sha256: str
    validation_id: int
    validation_fixed: str
    seal_operation: int
    compiled: object
    registration: object


def _initial(connection, installation, request):
    pack = connection.execute(
        'SELECT * FROM testing_pack_versions WHERE id=?', (request.identity,)
    ).fetchone()
    if pack is None:
        return NOT_FOUND
    plan = _version(connection, pack['plan_version_id'])
    if plan is None:
        raise StorageUnavailable('Original pack has no Testing plan')
    if pack['status'] == 'REVOKED' or plan['status'] == 'REVOKED':
        return pack_rejection('TEST_ASSET_REVOKED', pack)
    if pack['state_version'] != request.expected:
        return pack_rejection('VERSION_CONFLICT', pack)
    if pack['status'] != 'SEALED' or plan['status'] != 'PUBLISHED':
        return pack_rejection('INVALID_STATE', pack)
    seal_id, seal = sealed_pack_facts(connection, pack)
    if find_registered_reference(installation, seal['basis_fingerprint']) is None:
        raise ConfigurationNotReady('Q20-CHECKS')
    latest = connection.execute(
        'SELECT id,result FROM testing_pack_validations WHERE test_pack_version_id=? ORDER BY id DESC LIMIT 1',
        (pack['id'],),
    ).fetchone()
    if latest is None or latest['result'] != 'PASSED':
        return pack_rejection('INVALID_STATE', pack)
    return pack, plan, seal_id, seal, latest['id']


def _input_error():
    return Rejection(
        'CHECK_CONFIGURATION_INVALID',
        {
            'field_errors': [{'field': 'validation_id', 'reason': 'RELATION'}],
        },
    )


def _prepare(connection, installation, request):
    initial = _initial(connection, installation, request)
    if isinstance(initial, Rejection):
        return initial
    pack, plan, seal_id, seal, identity = initial
    original = original_validation(connection, identity)
    if original is None:
        raise StorageUnavailable('Original passing Testing validation is missing')
    validation, operation, fixed, children = original
    registration = find_registered_reference(
        installation, seal['basis_fingerprint'], validation['reference_set_ref']
    )
    if registration is None:
        raise ConfigurationNotReady('Q20-CHECKS')
    if (
        fixed['pack_sha256'] != pack['sha256']
        or fixed.get('reference_sha256') != registration.sha256
        or fixed['samples'] != validation_schedule(registration.reference)
        or operation['status'] != 'SUCCEEDED'
        or validation['ended_at'] is None
        or operation['ended_at'] != validation['ended_at']
        or pack['content_ref'] != pack_content_ref(pack['id'], seal_id)
    ):
        return _input_error()
    try:
        targets = original_targets(installation, seal)
        basis = basis_fingerprint(connection, plan)
        compiled = compile_pack(
            plan, targets, pack_id=pack['id'], version=pack['version'], basis_sha256=basis
        )
    except SealRejected as error:
        raise ConfigurationNotReady('Q20-CHECKS') from error
    except CompileError:
        return _input_error()
    if compiled.sha256 != pack['sha256'] or compiled.basis_sha256 != seal['basis_fingerprint']:
        return _input_error()
    checks = connection.execute(
        'SELECT owner_module,protocol_version,items,coverage_plan FROM code_check_set_versions WHERE id=?',
        (pack['check_set_version_id'],),
    ).fetchone()
    expected = compiled.check_set.value()
    if (
        checks is None
        or checks['owner_module'] != 'TESTING'
        or checks['protocol_version'] != expected['protocol_version']
        or strict_json_loads(checks['items'], 'items') != expected['items']
        or strict_json_loads(checks['coverage_plan'], 'coverage_plan') != expected['coverage_plan']
        or original_baselines(connection, registration.reference) is None
        or not passing_children(connection, pack, compiled, children, fixed['samples'])
    ):
        return _input_error()
    steps = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation['id'],),
    ).fetchall()
    if (
        [step['step_type'] for step in steps]
        != ['FIX_REFERENCE_SET', 'CREATE_CHILD_TASKS', 'OBSERVE_CHILDREN', 'SAVE_VALIDATION']
        or any(
            step['status'] != 'SUCCEEDED' or step['fixed_input'] != operation['fixed_input']
            for step in steps
        )
        or strict_json_object(steps[-1]['result_ref'])
        != {
            'validation_id': identity,
            'pack_sha256': pack['sha256'],
            'result': 'PASSED',
        }
    ):
        return _input_error()
    return Publication(
        pack['id'],
        pack['sha256'],
        identity,
        operation['fixed_input'],
        seal_id,
        compiled,
        registration,
    )


def _save(connection, request, pack, installation, reviewed):
    source = _initial(connection, installation, request)
    if isinstance(source, Rejection):
        return source
    _, _, seal, _, latest = source
    validation = original_validation(connection, latest)
    if (
        reviewed.pack_id != pack['id']
        or reviewed.pack_sha256 != pack['sha256']
        or reviewed.seal_operation != seal
        or reviewed.validation_id != latest
        or validation is None
        or validation[0]['result'] != 'PASSED'
        or validation[1]['status'] != 'SUCCEEDED'
        or validation[1]['fixed_input'] != reviewed.validation_fixed
    ):
        return pack_rejection('OPERATION_CONFLICT', pack)
    at = max(operation_time(None), pack['created_at'], validation[0]['ended_at'])
    save_lifecycle_operation(connection, request, pack, 'PUBLISHED', PUBLISH_PACK, at)
    saved = connection.execute(
        """UPDATE testing_pack_versions SET status='PUBLISHED',validation_id=?,state_version=?,published_at=?
           WHERE id=? AND status='SEALED' AND state_version=? AND sha256=?""",
        (
            latest,
            increment(pack['state_version']),
            at,
            pack['id'],
            pack['state_version'],
            pack['sha256'],
        ),
    )
    if saved.rowcount != 1:
        raise StorageUnavailable('Original pack publication lost its validated closure')
    return None


def publish_pack(runtime, request):
    require_schema(runtime)
    installation = getattr(runtime.catalog, 'testing_assets', None)
    executor = runtime.commands()

    def reject_now(connection, original, pack):
        result = _prepare(connection, installation, original)
        return (
            result if isinstance(result, Rejection) else pack_rejection('OPERATION_CONFLICT', pack)
        )

    try:
        replay = read_registered_replay(executor, request.command.scope, request.business_input())
        if replay is not None:
            return replay.result
        with runtime.database.transaction() as connection:
            reviewed = _prepare(connection, installation, request)
        if isinstance(reviewed, Rejection):
            return mutate_pack(runtime, request, reject_now)
        deadline = monotonic() + 30

        def checkpoint():
            if monotonic() >= deadline:
                raise CheckResourceError('TESTING_PUBLICATION_RESOURCE_TIMEOUT')

        with ExitStack() as locked:
            with hold_compiler_sources(
                installation, reviewed.compiled.targets, deadline=deadline, cancelled=lambda: False
            ):
                locked.enter_context(hold_reference_set(reviewed.registration, deadline=deadline))
                locked.enter_context(
                    hold_sealed_pack(
                        installation, reviewed.compiled, reviewed.seal_operation, checkpoint
                    )
                )
            checkpoint()
            return mutate_pack(
                runtime,
                request,
                lambda connection, original, pack: _save(
                    connection, original, pack, installation, reviewed
                ),
            )
    except ConfigurationNotReady as error:
        return {'code': error.code, 'data': None, 'details': error.details}
    except (IdempotencyConflict, RequestInProgress):
        return mutate_pack(runtime, request, reject_now)
    except (*RESOURCE_ERRORS, OSError):
        return {
            'code': 'CONFIG_NOT_READY',
            'data': None,
            'details': {'capability_codes': ['Q20-CHECKS']},
        }
    except (sqlite3.Error, StorageUnavailable, ValueError, KeyError, TypeError):
        return {
            'code': 'STORAGE_UNAVAILABLE',
            'data': None,
            'details': {'capability_codes': ['DATABASE']},
        }
