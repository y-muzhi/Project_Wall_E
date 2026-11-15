"""Fixed prerequisites and nonsecret reads for an original pack validation."""

from time import monotonic

from backend.app.code_tasks.command_registry import registered_command
from backend.app.code_tasks.configuration_identities import require_schema
from backend.app.code_tasks.operation_protocol import operation_steps
from backend.app.code_tasks.repository_operations import OPERATION_FIELDS, STEP_FIELDS, _time
from backend.app.infrastructure.check_runner_bundle import reference, valid_sha256
from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.shared.command_execution import (
    ConfigurationNotReady,
    execute_idempotent,
    operation_time,
)
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import (
    strict_enum,
    strict_integer,
    strict_json_loads,
    strict_json_object,
)

from .assets import NOT_FOUND, _read, sealed_pack_facts
from .cli_plan import read_fixed_profile, select_cli_plan
from .pack_definitions import compiled_definition, hold_compiled_pack_assets
from .pack_lifecycle import pack_rejection
from .pack_seal import RESOURCE_ERRORS
from .reference_resources import SOURCE_ERRORS, hold_reference_set, original_baselines
from .run_records import accept_internal_cli_run
from .run_target import fixed_run_target
from .plans import _version
from .plan_content import BASIS_FIELDS
from .task_views import SUMMARY, project_task_summary
from .tasks import grant_rejection, insert_task, read_task_row
from .validation_evidence import passing_children

RESULTS = ('PENDING', 'RUNNING', 'PASSED', 'FAILED', 'UNAVAILABLE', 'UNKNOWN')
FIELDS = (
    'id',
    'test_pack_version_id',
    'profile_version_id',
    'reference_set_ref',
    'operation_id',
    'testing_task_ids',
    'result',
    'created_at',
    'ended_at',
    'testing_tasks',
)
MAX_CHILDREN = 200
PUBLIC_INPUT = (
    'expected_state_version',
    'profile_version_id',
    'authorization_id',
    'reference_set_ref',
)
ORIGINAL_INPUT = (*PUBLIC_INPUT, 'validation_id', 'pack_sha256', 'reference_sha256', 'samples')


def _original_samples(value):
    if type(value) is not list or not 4 <= len(value) <= MAX_CHILDREN:
        raise ValueError('Original Testing validation schedule has invalid length')
    groups = {}
    sequence = []
    for entry in value:
        sample = exact(entry, ('snapshot_id', 'repeat_no', 'expected_failed_case_ids'))
        identity = strict_integer(sample['snapshot_id'], 'snapshot_id')
        repeat = strict_integer(sample['repeat_no'], 'repeat_no', maximum=10)
        failures = sample['expected_failed_case_ids']
        if type(failures) is not list or len(failures) != len(set(failures)):
            raise ValueError('Original Testing validation failure set differs')
        for case in failures:
            reference(case)
        original = groups.setdefault(identity, [])
        if (
            original
            and original[-1]['expected_failed_case_ids'] != failures
            or repeat != len(original) + 1
        ):
            raise ValueError('Original Testing validation repetitions differ')
        if not sequence or sequence[-1] != identity:
            sequence.append(identity)
        original.append(sample)
    lengths = {len(rows) for rows in groups.values()}
    polarities = [bool(groups[identity][0]['expected_failed_case_ids']) for identity in sequence]
    if (
        len(sequence) != len(groups)
        or not 2 <= len(groups) <= 20
        or len(lengths) != 1
        or min(lengths) < 2
        or polarities != sorted(polarities)
        or not polarities[-1]
        or polarities[0]
    ):
        raise ValueError('Original Testing validation schedule differs')
    return value


def validation_schedule(fixed):
    result = []
    for snapshot in fixed.positive_snapshot_ids:
        for run in range(1, fixed.repeat_count + 1):
            result.append(
                {'snapshot_id': snapshot, 'repeat_no': run, 'expected_failed_case_ids': []}
            )
    for control in fixed.negative_controls:
        for run in range(1, fixed.repeat_count + 1):
            result.append(
                {
                    'snapshot_id': control.snapshot_id,
                    'repeat_no': run,
                    'expected_failed_case_ids': list(control.expected_failed_case_ids),
                }
            )
    return result


def find_registered_reference(installation, basis, selected=None):
    if installation is None:
        return None
    return next(
        (
            entry
            for entry in installation.reference_sets
            if entry.reference.basis_fingerprint == basis
            and (selected is None or entry.reference.reference_set_ref == selected)
        ),
        None,
    )


def _read_validation_prerequisites(connection, runtime, request, runtime_resources):
    pack = connection.execute(
        'SELECT * FROM testing_pack_versions WHERE id=?', (request.identity,)
    ).fetchone()
    if pack is None:
        return NOT_FOUND
    plan = connection.execute(
        'SELECT * FROM testing_plan_versions WHERE id=?', (pack['plan_version_id'],)
    ).fetchone()
    if plan is None:
        raise StorageUnavailable('Original Testing plan is missing')
    if pack['status'] == 'REVOKED' or plan['status'] == 'REVOKED':
        return pack_rejection('TEST_ASSET_REVOKED', pack)
    if pack['state_version'] != request.expected:
        return pack_rejection('VERSION_CONFLICT', pack)
    if pack['status'] != 'SEALED' or plan['status'] != 'PUBLISHED':
        return pack_rejection('INVALID_STATE', pack)
    _, seal = sealed_pack_facts(connection, pack)
    installation = getattr(runtime.catalog, 'testing_assets', None)
    entry = find_registered_reference(installation, seal['basis_fingerprint'], request.reference)
    if entry is None:
        raise ConfigurationNotReady('Q20-CHECKS')
    profile = connection.execute(
        'SELECT * FROM testing_profile_versions WHERE id=?', (request.profile,)
    ).fetchone()
    if profile is None:
        return NOT_FOUND
    grant = connection.execute(
        'SELECT * FROM testing_authorizations WHERE id=?', (request.authorization,)
    ).fetchone()
    if (
        grant is None
        or grant['status'] != 'APPROVED_UNBOUND'
        or grant['scope_kind'] != 'PACK_VALIDATION'
        or grant['testing_task_id'] is not None
        or grant['validation_id'] is not None
        or grant['profile_version_id'] != profile['id']
        or grant['budget_limit_cny'] != '0.000000'
    ):
        return grant_rejection(request.authorization)
    if (
        connection.execute(
            """SELECT 1 FROM testing_pack_validations WHERE test_pack_version_id=?
           AND result IN ('PENDING','RUNNING','UNKNOWN') AND ended_at IS NULL""",
            (pack['id'],),
        ).fetchone()
        is not None
    ):
        return pack_rejection('OPERATION_IN_PROGRESS', pack)
    allowed = {row['case_id'] for row in strict_json_loads(plan['cases'], 'cases')}
    schedule = validation_schedule(entry.reference)
    if any(not set(sample['expected_failed_case_ids']).issubset(allowed) for sample in schedule):
        return Rejection(
            'CHECK_CONFIGURATION_INVALID',
            {'field_errors': [{'field': 'reference_set_ref', 'reason': 'RELATION'}]},
        )
    deadline = monotonic() + 5
    try:
        with (
            hold_reference_set(entry, deadline=deadline) as fixed,
            hold_compiled_pack_assets(
                connection, installation, pack, deadline=deadline
            ) as compiled,
        ):
            if original_baselines(connection, fixed) is None:
                return pack_rejection('CONTENT_NOT_READY', pack)
            if runtime_resources is None or not runtime_resources.snapshots:
                raise ConfigurationNotReady('Q20-CHECKS')
            content = read_fixed_profile(connection, profile['id'])
            selection = select_cli_plan(
                compiled,
                content,
                runtime_resources.admissions,
                runtime_resources.browser_admissions,
            )
            if selection is None:
                raise ConfigurationNotReady('Q20-CHECKS')
            return _accept_group(
                connection,
                request,
                pack,
                compiled,
                selection,
                runtime_resources.owner,
                entry.sha256,
                schedule,
            )
    except (*SOURCE_ERRORS, *RESOURCE_ERRORS):
        return pack_rejection('CONTENT_NOT_READY', pack)


def _accept_group(connection, request, pack, compiled, selection, owner, reference_sha, schedule):
    plan = _version(connection, pack['plan_version_id'])
    if plan is None:
        raise StorageUnavailable('Original Testing validation plan is missing')
    at = max(operation_time(None), pack['created_at'])
    validation = entity_id(connection, EntityKind.TEST_PACK_VALIDATION)
    operation = entity_id(connection, EntityKind.OPERATION_RECORD)
    original = canonical_input(
        {
            **request.business_input(),
            'validation_id': validation,
            'pack_sha256': pack['sha256'],
            'reference_sha256': reference_sha,
            'samples': schedule,
        }
    )
    connection.execute(
        """INSERT INTO code_operations(id,resource_kind,resource_id,operation_type,idempotency_key,
           expected_state_version,fixed_input,status,created_at,started_at)
           VALUES(?,'TEST_PACK_VERSION',?,'VALIDATE_PACK',?,?,?,'RUNNING',?,?)""",
        (operation, pack['id'], request.idempotency_key, request.expected, original, at, at),
    )
    connection.execute(
        """INSERT INTO testing_pack_validations(id,test_pack_version_id,profile_version_id,
           reference_set_ref,operation_id,result,created_at) VALUES(?,?,?,?,?,'RUNNING',?)""",
        (validation, pack['id'], request.profile, request.reference, operation, at),
    )
    grant = connection.execute(
        """UPDATE testing_authorizations SET status='EFFECTIVE',validation_id=?
           WHERE id=? AND scope_kind='PACK_VALIDATION' AND status='APPROVED_UNBOUND'
           AND testing_task_id IS NULL AND validation_id IS NULL""",
        (validation, request.authorization),
    )
    if grant.rowcount != 1:
        raise StorageUnavailable('Original Testing validation authorization changed')
    children = []
    basis = {key: plan[key] for key in BASIS_FIELDS}
    for sample in schedule:
        identity = entity_id(connection, EntityKind.TESTING_TASK)
        data = {
            **basis,
            'target_kind': 'SNAPSHOT',
            'candidate_id': None,
            'snapshot_id': sample['snapshot_id'],
            'purpose': 'PACK_VALIDATION',
            'profile_version_id': request.profile,
            'authorization_id': request.authorization,
            'budget_limit_cny': '0.000000',
            'plan_version_id': plan['id'],
            'test_pack_version_id': pack['id'],
            'previous_testing_task_id': None,
        }
        insert_task(connection, identity, data, at=at, validation_id=validation, ready=True)
        connection.execute(
            'INSERT INTO testing_validation_tasks(validation_id,testing_task_id) VALUES(?,?)',
            (validation, identity),
        )
        children.append(identity)
        task = {
            **dict(read_task_row(connection, identity)),
            'material_refs': basis['material_refs'],
        }
        target = fixed_run_target(connection, task)
        accept_internal_cli_run(connection, task, pack, compiled, selection, owner, target)
    steps = operation_steps('RESOURCE', 'VALIDATE_PACK')
    results = (
        {'reference_set_ref': request.reference, 'reference_sha256': reference_sha},
        {'testing_task_ids': children},
        None,
        None,
    )
    for number, (name, facts) in enumerate(zip(steps, results, strict=True), 1):
        done = facts is not None
        connection.execute(
            """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input,
               result_ref,started_at,ended_at,last_observed_at) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                operation,
                number,
                name,
                'SUCCEEDED' if done else 'PENDING',
                original,
                canonical_input(facts) if done else None,
                at if done else None,
                at if done else None,
                at if done else None,
            ),
        )
    return Success(
        {
            'code': 'OPERATION_ACCEPTED',
            'data': {
                'operation_id': operation,
                'test_pack_version_id': pack['id'],
                'validation_id': validation,
            },
            'details': None,
        },
        202,
    )


def validate_pack(runtime, request, *, runtime_resources=None):
    require_schema(runtime)
    return execute_idempotent(
        runtime.commands(),
        request.command.route.capability_id,
        request,
        lambda connection: _read_validation_prerequisites(
            connection, runtime, request, runtime_resources
        ),
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset({'CONFIG_NOT_READY'}),
    )


def _terminal_child(connection, child):
    if child['status'] in ('COMPLETED', 'TERMINATED'):
        return True
    original = child['active_operation_id']
    return (
        child['status'] == 'WAITING'
        and original is not None
        and connection.execute(
            """SELECT 1 FROM code_operations o JOIN code_verifications v ON v.operation_id=o.id
           WHERE o.id=? AND o.testing_task_id=? AND o.operation_type='RUN_TEST'
           AND o.status='CANCELLED' AND v.testing_task_id=o.testing_task_id
           AND v.stop_status='VERIFIED' AND v.cleanup_status='VERIFIED'""",
            (original, child['id']),
        ).fetchone()
        is not None
    )


def _validation_result(connection, catalog, validation, fixed, children):
    if any(child['status'] == 'TERMINATED' for child in children):
        return 'FAILED'
    if any(child['status'] != 'COMPLETED' for child in children):
        return 'UNAVAILABLE'
    reports = connection.execute(
        """SELECT r.result FROM testing_reports r JOIN testing_validation_tasks j
           ON j.testing_task_id=r.testing_task_id WHERE j.validation_id=?""",
        (validation['id'],),
    ).fetchall()
    if len(reports) != len(children):
        raise StorageUnavailable('Original Testing validation reports are missing')
    outcomes = {row['result'] for row in reports}
    if 'UNKNOWN' in outcomes:
        return 'UNKNOWN'
    if 'UNAVAILABLE' in outcomes or 'CANCELLED' in outcomes:
        return 'UNAVAILABLE'
    installation = getattr(catalog, 'testing_assets', None)
    pack = connection.execute(
        'SELECT * FROM testing_pack_versions WHERE id=?', (validation['test_pack_version_id'],)
    ).fetchone()
    if pack is None or pack['sha256'] != fixed['pack_sha256']:
        raise StorageUnavailable('Original Testing validation pack differs')
    if installation is None or pack['status'] != 'SEALED':
        return 'UNAVAILABLE'
    deadline = monotonic() + 5
    try:
        with hold_compiled_pack_assets(
            connection, installation, pack, deadline=deadline
        ) as compiled:
            registration = find_registered_reference(
                installation, compiled.basis_sha256, validation['reference_set_ref']
            )
            if registration is None or registration.sha256 != fixed['reference_sha256']:
                return 'UNAVAILABLE'
            with hold_reference_set(registration, deadline=deadline) as reference_set:
                if (
                    validation_schedule(reference_set) != fixed['samples']
                    or original_baselines(connection, reference_set) is None
                ):
                    return 'UNAVAILABLE'
                return (
                    'PASSED'
                    if passing_children(connection, pack, compiled, children, fixed['samples'])
                    else 'FAILED'
                )
    except (*SOURCE_ERRORS, *RESOURCE_ERRORS):
        return 'UNAVAILABLE'


def _finish_validation(connection, group, operation, fixed, result):
    at = max(operation_time(None), group['created_at'])
    settled = canonical_input(
        {'validation_id': group['id'], 'pack_sha256': fixed['pack_sha256'], 'result': result}
    )
    for name in ('OBSERVE_CHILDREN', 'SAVE_VALIDATION'):
        changed = connection.execute(
            """UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,
               started_at=COALESCE(started_at,?),ended_at=?,last_observed_at=?
               WHERE operation_id=? AND step_type=? AND ended_at IS NULL""",
            (settled if name == 'SAVE_VALIDATION' else None, at, at, at, operation['id'], name),
        )
        if changed.rowcount != 1:
            raise StorageUnavailable('Original Testing validation settlement was fenced')
    connection.execute(
        'UPDATE testing_pack_validations SET result=?,ended_at=? WHERE id=? AND ended_at IS NULL',
        (result, at, group['id']),
    )
    connection.execute(
        'UPDATE code_operations SET status=?,failure_code=?,ended_at=? WHERE id=? AND ended_at IS NULL',
        (
            'FAILED' if result == 'UNKNOWN' else 'SUCCEEDED',
            'EXTERNAL_RESULT_UNKNOWN' if result == 'UNKNOWN' else None,
            at,
            operation['id'],
        ),
    )


def advance_pending_validation_results(runtime):
    runtime.commands().process_lock.assert_owned()
    with runtime.database.transaction(write=True) as connection:
        rows = connection.execute(
            """SELECT v.id FROM testing_pack_validations v
               JOIN code_operations o ON o.id=v.operation_id AND o.operation_type='VALIDATE_PACK'
               WHERE v.ended_at IS NULL AND v.result IN ('RUNNING','UNKNOWN')
               AND o.ended_at IS NULL ORDER BY v.id"""
        ).fetchall()
        for (identity,) in rows:
            group, operation, fixed, children = original_validation(connection, identity)
            if all(_terminal_child(connection, child) for child in children):
                result = _validation_result(connection, runtime.catalog, group, fixed, children)
                _finish_validation(connection, group, operation, fixed, result)
                return True
            unresolved = (
                connection.execute(
                    """SELECT 1 FROM code_commands c JOIN testing_validation_tasks j ON j.testing_task_id=c.testing_task_id
                   WHERE j.validation_id=? AND c.status='UNKNOWN' AND c.ended_at IS NULL""",
                    (group['id'],),
                ).fetchone()
                is not None
            )
            if unresolved and group['result'] == 'RUNNING':
                at = operation_time(None)
                connection.execute(
                    "UPDATE testing_pack_validations SET result='UNKNOWN' WHERE id=?",
                    (group['id'],),
                )
                connection.execute(
                    "UPDATE code_operations SET status='UNKNOWN',failure_code='EXECUTION_NOT_STOPPED' WHERE id=?",
                    (operation['id'],),
                )
                connection.execute(
                    """UPDATE code_operation_steps SET status='UNKNOWN',
                       started_at=COALESCE(started_at,?),last_observed_at=?
                       WHERE operation_id=? AND step_type='OBSERVE_CHILDREN' AND ended_at IS NULL""",
                    (at, at, operation['id']),
                )
                return True
    return False


def project_validation(value, identity):
    row = exact(value, FIELDS)
    for key in ('id', 'test_pack_version_id', 'profile_version_id', 'operation_id'):
        strict_integer(row[key], key)
    reference(row['reference_set_ref'])
    result = strict_enum(row['result'], 'result', RESULTS)
    _time(row['created_at'], nullable=False)
    _time(row['ended_at'])
    if (
        row['id'] != identity
        or result in ('PENDING', 'RUNNING')
        and row['ended_at'] is not None
        or result in ('PASSED', 'FAILED', 'UNAVAILABLE')
        and row['ended_at'] is None
        or row['ended_at'] is not None
        and row['ended_at'] < row['created_at']
    ):
        raise ValueError('Original Testing validation outcome differs')
    ids, children = row['testing_task_ids'], row['testing_tasks']
    if type(ids) is not list or not 4 <= len(ids) <= MAX_CHILDREN or ids != sorted(set(ids)):
        raise ValueError('Original Testing validation child identities differ')
    if type(children) is not list or len(children) != len(ids):
        raise ValueError('Original Testing validation summaries differ')
    for child_id, child in zip(ids, children, strict=True):
        projected = project_task_summary(child)
        if strict_integer(child_id, 'testing_task_id') != projected['id'] or (
            projected['target_kind'] != 'SNAPSHOT' or projected['purpose'] != 'PACK_VALIDATION'
        ):
            raise ValueError('Original Testing validation child crosses its scope')
        if result == 'PASSED' and projected['status'] != 'COMPLETED':
            raise ValueError('A non-complete child cannot support a passing validation')
    return row


def original_validation(connection, identity):
    row = connection.execute(
        'SELECT * FROM testing_pack_validations WHERE id=?', (identity,)
    ).fetchone()
    if row is None:
        return None
    operation = connection.execute(
        """SELECT * FROM code_operations WHERE id=? AND resource_kind='TEST_PACK_VERSION'
           AND resource_id=? AND operation_type='VALIDATE_PACK'
           AND task_id IS NULL AND testing_task_id IS NULL""",
        (row['operation_id'], row['test_pack_version_id']),
    ).fetchone()
    if operation is None:
        raise StorageUnavailable('Original Testing validation operation is missing')
    fixed = exact(strict_json_object(operation['fixed_input']), ORIGINAL_INPUT)
    if (
        fixed['validation_id'] != row['id']
        or fixed['profile_version_id'] != row['profile_version_id']
        or fixed['reference_set_ref'] != row['reference_set_ref']
        or not valid_sha256(fixed['pack_sha256'])
        or not valid_sha256(fixed['reference_sha256'])
        or strict_integer(fixed['expected_state_version'], 'expected_state_version')
        != operation['expected_state_version']
    ):
        raise StorageUnavailable('Original Testing validation input differs')
    children = connection.execute(
        """SELECT t.* FROM testing_tasks t JOIN testing_validation_tasks j ON j.testing_task_id=t.id
           WHERE j.validation_id=? ORDER BY t.id""",
        (identity,),
    ).fetchall()
    samples = _original_samples(fixed['samples'])
    if len(samples) != len(children) or any(
        child['kind'] != 'PACK_VALIDATION'
        or child['target_kind'] != 'SNAPSHOT'
        or child['purpose'] != 'PACK_VALIDATION'
        or child['validation_id'] != identity
        or child['test_pack_version_id'] != row['test_pack_version_id']
        or child['profile_version_id'] != row['profile_version_id']
        or child['authorization_id'] != fixed['authorization_id']
        or child['snapshot_id'] != sample['snapshot_id']
        for child, sample in zip(children, samples, strict=True)
    ):
        raise StorageUnavailable('Original Testing validation children differ')
    return row, operation, fixed, children


def _saved_validation_result(step, row, operation, fixed):
    if (
        step is None
        or step['step_type'] != 'SAVE_VALIDATION'
        or step['status'] != 'SUCCEEDED'
        or step['operation_id'] != operation['id']
        or step['fixed_input'] != operation['fixed_input']
        or step['ended_at'] != row['ended_at']
    ):
        raise StorageUnavailable('Original validation final step is missing')
    saved = exact(
        strict_json_object(step['result_ref']), ('validation_id', 'pack_sha256', 'result')
    )
    if saved != {
        'validation_id': row['id'],
        'pack_sha256': fixed['pack_sha256'],
        'result': row['result'],
    }:
        raise StorageUnavailable('Original validation final step differs')
    return {'validation_id': saved['validation_id'], 'result': saved['result']}


def _verify_passing_validation(connection, row, operation, fixed, children):
    pack = connection.execute(
        'SELECT * FROM testing_pack_versions WHERE id=?', (row['test_pack_version_id'],)
    ).fetchone()
    if (
        pack is None
        or pack['sha256'] != fixed['pack_sha256']
        or operation['status'] != 'SUCCEEDED'
        or operation['ended_at'] != row['ended_at']
    ):
        raise StorageUnavailable('Original passing validation operation differs')
    step = connection.execute(
        "SELECT * FROM code_operation_steps WHERE operation_id=? AND step_type='SAVE_VALIDATION'",
        (operation['id'],),
    ).fetchone()
    _saved_validation_result(step, row, operation, fixed)
    _, compiled = compiled_definition(connection, pack)
    if not passing_children(connection, pack, compiled, children, fixed['samples']):
        raise StorageUnavailable('Original passing validation has incomplete child evidence')


def read_validation(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        try:
            original = original_validation(connection, request.identity)
            if original is None:
                return NOT_FOUND.result
            row, operation, fixed, children = original
            if row['result'] == 'PASSED':
                _verify_passing_validation(connection, row, operation, fixed, children)
            result = {
                **dict(row),
                'testing_task_ids': [child['id'] for child in children],
                'testing_tasks': [{key: child[key] for key in SUMMARY} for child in children],
            }
            return _read(project_validation(result, request.identity))
        except (TypeError, ValueError, KeyError) as error:
            raise StorageUnavailable('Original Testing validation is unreadable') from error


def project_validation_operation(value, identity):
    row = exact(value, OPERATION_FIELDS)
    pack = strict_integer(row['resource_id'], 'test_pack_version_id')
    strict_integer(row['id'], 'operation_id')
    if (
        row['id'] != identity
        or row['resource_kind'] != 'TEST_PACK_VERSION'
        or row['operation_type'] != 'VALIDATE_PACK'
        or any(
            row[key] is not None
            for key in (
                'task_id',
                'testing_task_id',
                'session_id',
                'control_generation',
                'content_capture',
            )
        )
    ):
        raise ValueError('Original validation operation crosses pack ownership')
    registered_command(
        'POST', f'/api/v1/test-pack-versions/{pack}/validations', row['idempotency_key']
    )
    fixed = exact(
        row['fixed_input'],
        ('expected_state_version', 'profile_version_id', 'authorization_id', 'reference_set_ref'),
    )
    if (
        strict_integer(fixed['expected_state_version'], 'expected_state_version')
        != row['expected_state_version']
    ):
        raise ValueError('Original validation operation CAS differs')
    for field in ('profile_version_id', 'authorization_id'):
        strict_integer(fixed[field], field)
    reference(fixed['reference_set_ref'])
    states = ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'UNKNOWN', 'CANCELLED')
    strict_enum(row['status'], 'status', states)
    _time(row['created_at'], nullable=False)
    _time(row['started_at'])
    _time(row['ended_at'])
    if row['failure_code'] is not None:
        strict_enum(
            row['failure_code'],
            'failure_code',
            (
                'CONFIG_NOT_READY',
                'CONTENT_NOT_READY',
                'EXECUTION_NOT_STOPPED',
                'TEST_ASSET_REVOKED',
                'EXTERNAL_RESULT_UNKNOWN',
            ),
        )
    expected = operation_steps('RESOURCE', 'VALIDATE_PACK')
    if type(row['steps']) is not list or len(row['steps']) != len(expected):
        raise ValueError('Original validation operation step sequence differs')
    for number, (step, name) in enumerate(zip(row['steps'], expected, strict=True), 1):
        exact(step, STEP_FIELDS)
        if (
            step['step_no'] != number
            or step['step_type'] != name
            or step['operation_id'] != identity
            or step['external_identity'] is not None
            or step['fixed_input'] != fixed
        ):
            raise ValueError('Original validation step crosses scope')
        strict_enum(step['status'], 'step.status', states)
        for field in ('started_at', 'ended_at', 'last_observed_at'):
            _time(step[field])
        if step['result_ref'] is not None:
            if name != 'SAVE_VALIDATION' or step['status'] != 'SUCCEEDED':
                raise ValueError('Original validation step result is private or incomplete')
            result = exact(step['result_ref'], ('validation_id', 'result'))
            strict_integer(result['validation_id'], 'validation_id')
            strict_enum(result['result'], 'result', RESULTS)
    return row


def read_validation_operation(runtime, identity):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        validation = connection.execute(
            'SELECT id FROM testing_pack_validations WHERE operation_id=?',
            (identity,),
        ).fetchone()
        if validation is None:
            return NOT_FOUND.result
        try:
            original = original_validation(connection, validation['id'])
            if original is None:
                raise StorageUnavailable('Original Testing validation is missing')
            row, operation, fixed, children = original
            public = {key: fixed[key] for key in PUBLIC_INPUT}
            steps = connection.execute(
                'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
                (identity,),
            ).fetchall()
            if any(step['fixed_input'] != operation['fixed_input'] for step in steps):
                raise StorageUnavailable('Original validation inputs differ')
            observed = []
            for step in steps:
                step_result = None
                if step['step_type'] == 'SAVE_VALIDATION' and step['status'] == 'SUCCEEDED':
                    step_result = _saved_validation_result(step, row, operation, fixed)
                    if row['result'] == 'PASSED':
                        _verify_passing_validation(connection, row, operation, fixed, children)
                observed.append(
                    {
                        **dict(step),
                        'fixed_input': public,
                        'external_identity': None,
                        'result_ref': step_result,
                    }
                )
            data = {
                **dict(operation),
                'fixed_input': public,
                'content_capture': None,
                'steps': observed,
            }
            return _read(project_validation_operation(data, identity))
        except (KeyError, TypeError, ValueError) as error:
            raise StorageUnavailable('Original validation operation is unreadable') from error
