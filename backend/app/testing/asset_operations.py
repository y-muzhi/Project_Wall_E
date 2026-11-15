"""Nonsecret projections of the original Testing resource operation."""

from backend.app.code_tasks.command_registry import registered_command
from backend.app.code_tasks.configuration_identities import require_schema
from backend.app.code_tasks.operation_protocol import operation_steps
from backend.app.code_tasks.repository_operations import OPERATION_FIELDS, STEP_FIELDS, _time
from backend.app.infrastructure.check_runner_bundle import valid_sha256
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import (
    ordinary_text,
    strict_enum,
    strict_integer,
    strict_json_object,
)

from .assets import NOT_FOUND, _read
from .findings import CLASSIFICATIONS
from .pack_seal import STEPS, operation_row, operation_steps_rows

SEAL_PATH = '/test-pack-versions/{id}/seal'
TEST_OPERATION = '/testing-operations/{id}'
FAILURES = (
    'INVALID_STATE',
    'CONFIG_NOT_READY',
    'CHECK_CONFIGURATION_INVALID',
    'CONTENT_NOT_READY',
    'TEST_ASSET_REVOKED',
)


RESOURCE_ACTIONS = {
    'PUBLISH_PLAN': ('TEST_PLAN_VERSION', '/test-plan-versions', 'plan_version_id'),
    'REVOKE_PLAN': ('TEST_PLAN_VERSION', '/test-plan-versions', 'plan_version_id'),
    'PUBLISH_PACK': ('TEST_PACK_VERSION', '/test-pack-versions', 'test_pack_version_id'),
    'REVOKE_PACK': ('TEST_PACK_VERSION', '/test-pack-versions', 'test_pack_version_id'),
    'REVIEW_FINDING': ('TESTING_FINDING', '/testing-findings', 'finding_id'),
}


def project_resource_fact(value, identity):
    row = exact(value, OPERATION_FIELDS)
    action = strict_enum(row['operation_type'], 'operation_type', tuple(RESOURCE_ACTIONS))
    kind, path, owner_key = RESOURCE_ACTIONS[action]
    owner = strict_integer(row['resource_id'], owner_key)
    revoke = action.startswith('REVOKE_')
    review = action == 'REVIEW_FINDING'
    if (
        strict_integer(row['id'], 'operation_id') != identity
        or row['resource_kind'] != kind
        or row['status'] != 'SUCCEEDED'
        or any(
            row[field] is not None
            for field in (
                'task_id',
                'testing_task_id',
                'session_id',
                'control_generation',
                'failure_code',
                'content_capture',
            )
        )
    ):
        raise ValueError('Original Testing resource action differs')
    verb = 'review' if review else 'revoke' if revoke else 'publish'
    registered_command('POST', f'/api/v1{path}/{owner}/{verb}', row['idempotency_key'])
    fixed_fields = ('expected_state_version',)
    if revoke or review:
        fixed_fields += ('reason',)
    if review:
        fixed_fields += ('classification',)
    fixed = exact(row['fixed_input'], fixed_fields)
    version = strict_integer(row['expected_state_version'], 'expected_state_version')
    if version != fixed['expected_state_version'] or (
        (revoke or review) and ordinary_text(fixed['reason'], 'reason', 1, 2000) != fixed['reason']
    ):
        raise ValueError('Original Testing resource action input differs')
    if review:
        strict_enum(fixed['classification'], 'classification', CLASSIFICATIONS[1:])
    for key in ('created_at', 'started_at', 'ended_at'):
        _time(row[key], nullable=False)
    if not row['created_at'] <= row['started_at'] <= row['ended_at']:
        raise ValueError('Original Testing resource action time differs')
    steps = operation_steps('RESOURCE', action)
    if type(row['steps']) is not list or len(row['steps']) != len(steps):
        raise ValueError('Original Testing resource action steps differ')
    result = {
        owner_key: owner,
        'state_version': version + 1,
        **(
            {'classification': fixed['classification']}
            if review
            else {
                'status': 'REVOKED' if revoke else 'PUBLISHED',
            }
        ),
    }
    previous = row['started_at']
    for number, (entry, expected) in enumerate(zip(row['steps'], steps, strict=True), 1):
        step = exact(entry, STEP_FIELDS)
        for key in ('started_at', 'ended_at', 'last_observed_at'):
            _time(step[key], nullable=False)
        if (
            step['operation_id'] != identity
            or step['step_no'] != number
            or step['step_type'] != expected
            or step['status'] != 'SUCCEEDED'
            or step['external_identity'] is not None
            or step['fixed_input'] != fixed
            or step['result_ref'] != result
            or not previous
            <= step['started_at']
            <= step['ended_at']
            <= step['last_observed_at']
            <= row['ended_at']
        ):
            raise ValueError('Original Testing resource action step differs')
        previous = step['ended_at']
    return row


def _read_resource_fact(connection, identity):
    original = connection.execute(
        """SELECT * FROM code_operations WHERE id=? AND task_id IS NULL AND testing_task_id IS NULL
           AND resource_kind IN ('TEST_PLAN_VERSION','TEST_PACK_VERSION','TESTING_FINDING')
           AND operation_type IN ('PUBLISH_PLAN','REVOKE_PLAN','PUBLISH_PACK','REVOKE_PACK','REVIEW_FINDING')""",
        (identity,),
    ).fetchone()
    if original is None:
        return NOT_FOUND.result
    try:
        fixed = strict_json_object(original['fixed_input'])
        review = original['operation_type'] == 'REVIEW_FINDING'
        if review:
            actor = fixed.pop('actor_ref', None)
            if (
                type(actor) is not str
                or not actor
                or connection.execute(
                    'SELECT 1 FROM testing_findings WHERE id=?', (original['resource_id'],)
                ).fetchone()
                is None
            ):
                raise StorageUnavailable('Original Testing review identity is missing')
        rows = connection.execute(
            'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
            (identity,),
        ).fetchall()
        steps = []
        for row in rows:
            step_input = strict_json_object(row['fixed_input'])
            if review and step_input.pop('actor_ref', None) != actor:
                raise StorageUnavailable('Original Testing review step actor differs')
            steps.append(
                {
                    **dict(row),
                    'fixed_input': step_input,
                    'result_ref': strict_json_object(row['result_ref']),
                }
            )
        data = {**dict(original), 'fixed_input': fixed, 'steps': steps, 'content_capture': None}
        return _read(project_resource_fact(data, identity))
    except (KeyError, TypeError, ValueError) as error:
        raise StorageUnavailable('Original Testing resource action is unreadable') from error


def _project_result(number, result, pack_id):
    if number == 1:
        fields = exact(result, ('plan_version_id',))
        strict_integer(fields['plan_version_id'], 'plan_version_id')
    elif number in (2, 3):
        fields = exact(result, ('sha256',))
        if not valid_sha256(fields['sha256']):
            raise ValueError('Original seal evidence digest differs')
    else:
        fields = exact(result, ('test_pack_version_id', 'check_set_version_id'))
        if strict_integer(fields['test_pack_version_id'], 'test_pack_version_id') != pack_id:
            raise ValueError('Original seal result crosses pack ownership')
        strict_integer(fields['check_set_version_id'], 'check_set_version_id')
    return fields


def project_seal_operation(value, identity):
    row = exact(value, OPERATION_FIELDS)
    pack = strict_integer(row['resource_id'], 'test_pack_version_id')
    status = strict_enum(row['status'], 'status', ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED'))
    if (
        strict_integer(row['id'], 'operation_id') != identity
        or row['operation_type'] != 'SEAL_PACK'
        or row['resource_kind'] != 'TEST_PACK_VERSION'
        or any(
            row[field] is not None
            for field in (
                'task_id',
                'testing_task_id',
                'session_id',
                'control_generation',
                'content_capture',
            )
        )
        or (row['failure_code'] in FAILURES if status == 'FAILED' else row['failure_code'] is None)
        is False
    ):
        raise ValueError('Original seal operation ownership differs')
    registered_command('POST', '/api/v1' + SEAL_PATH.format(id=pack), row['idempotency_key'])
    version = strict_integer(row['expected_state_version'], 'expected_state_version')
    if row['fixed_input'] != {'expected_state_version': version}:
        raise ValueError('Original seal public input differs')
    created, started, ended = (row[key] for key in ('created_at', 'started_at', 'ended_at'))
    _time(created, nullable=False)
    _time(started)
    _time(ended)
    if (
        (started is None) != (status == 'PENDING')
        or (ended is not None) != (status in ('SUCCEEDED', 'FAILED'))
        or started is not None
        and started < created
        or ended is not None
        and ended < started
    ):
        raise ValueError('Original seal operation timestamps differ')
    if type(row['steps']) is not list or len(row['steps']) != len(STEPS):
        raise ValueError('Original seal operation steps differ')
    previous = started
    active = None
    for number, step in enumerate(row['steps'], 1):
        exact(step, STEP_FIELDS)
        state = strict_enum(
            step['status'], 'step.status', ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED')
        )
        if (
            step['operation_id'] != identity
            or step['step_no'] != number
            or step['step_type'] != STEPS[number - 1]
            or step['external_identity'] is not None
            or step['fixed_input'] != row['fixed_input']
        ):
            raise ValueError('Original seal step ownership differs')
        began, last, closed = (step[key] for key in ('started_at', 'last_observed_at', 'ended_at'))
        for instant in (began, last, closed):
            _time(instant)
        result = step['result_ref']
        if state == 'PENDING':
            if any(value is not None for value in (began, last, closed, result)):
                raise ValueError('Pending seal step contains execution facts')
            active = active or 'PENDING'
            continue
        if active is not None or began is None or last is None or previous is None:
            raise ValueError('Original seal step order differs')
        if not previous <= began <= last or ended is not None and last > ended:
            raise ValueError('Original seal step timestamps differ')
        if state == 'RUNNING':
            if closed is not None or result is not None:
                raise ValueError('Running seal step contains terminal facts')
            active = 'RUNNING'
            continue
        if closed is None or not began <= closed <= last:
            raise ValueError('Original seal step completion time differs')
        previous = closed
        if state == 'FAILED':
            if result is not None:
                raise ValueError('Failed seal step contains a result')
            active = 'FAILED'
        else:
            _project_result(number, result, pack)
    if (
        active
        != {'PENDING': 'PENDING', 'RUNNING': 'RUNNING', 'FAILED': 'FAILED', 'SUCCEEDED': None}[
            status
        ]
    ):
        raise ValueError('Original seal operation and steps disagree')
    return row


def read_test_operation(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        original = operation_row(connection, request.identity)
        if original is None:
            return _read_resource_fact(connection, request.identity)
        fixed = {'expected_state_version': original['expected_state_version']}
        steps = [
            {
                **dict(step),
                'fixed_input': fixed,
                'result_ref': (
                    None if step['result_ref'] is None else strict_json_object(step['result_ref'])
                ),
            }
            for step in operation_steps_rows(connection, original)
        ]
        operation = {
            **dict(original),
            'fixed_input': fixed,
            'content_capture': None,
            'steps': steps,
        }
        try:
            return _read(project_seal_operation(operation, request.identity))
        except (KeyError, TypeError, ValueError) as error:
            raise StorageUnavailable('Original Testing operation is unreadable') from error
