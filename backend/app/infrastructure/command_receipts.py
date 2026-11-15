"""V2 original-key linearization on the existing idempotency ledger.

Callbacks perform only database work. Accepted asynchronous work must already
have its real Operation in this transaction; external dispatch follows commit.
"""

import json
from dataclasses import dataclass

from backend.app.code_tasks.command_registry import (
    REPOSITORY_OPERATIONS,
    registered_command,
    validate_registered_success,
)
from backend.app.shared.code_errors import empty_conflict, error_fact
from backend.app.shared.command_execution import Rejected
from backend.app.shared.validation import MAX_SAFE_INTEGER

from .database import SchemaMismatch
from .idempotency import Claim, Scope, Success, canonical_input

COLUMNS = (
    'capability_id,target_identity,idempotency_key,business_input_json,status,owner_epoch,'
    'created_at,updated_at,success_result_json,http_status,error_result_json'
)


@dataclass(frozen=True)
class Rejection:
    code: str
    details: object

    @property
    def result(self):
        return {'code': self.code, 'data': None, 'details': self.details}

    @property
    def http_status(self):
        return error_fact(self.code, self.details)[0]

    def encoded(self):
        if not 400 <= self.http_status < 500:
            raise ValueError('Only certain registered 4xx rejections may be persisted')
        return canonical_input(self.result)


def command_for_scope(scope):
    if not isinstance(scope, Scope) or not scope.target_identity.startswith('POST '):
        raise ValueError('A registered original POST scope is required')
    command = registered_command('POST', scope.target_identity[5:], scope.key)
    if command.scope != scope:
        raise ValueError('Command capability and path differ')
    return command


def require_v20(database):
    if database.schema_release is None:
        raise SchemaMismatch('Command control requires the explicit Schema200 database')


def _row(connection, scope):
    return connection.execute(
        'SELECT * FROM idempotency_records WHERE capability_id=? AND target_identity=? AND idempotency_key=?',
        scope.identity,
    ).fetchone()


def _insert(connection, executor, scope, input_json, status, error=None, http_status=None):
    now = executor._time()
    connection.execute(
        f'INSERT INTO idempotency_records({COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
        (
            *scope.identity,
            input_json,
            status,
            executor.owner_epoch,
            now,
            now,
            None,
            http_status,
            error,
        ),
    )


def _stored_result(row):
    if row['status'] == 'SUCCEEDED':
        result = Success(json.loads(row['success_result_json']), row['http_status'])
        result.encoded()
        return result
    result = json.loads(row['error_result_json'])
    if (
        type(result) is not dict
        or set(result) != {'code', 'data', 'details'}
        or result['data'] is not None
    ):
        raise ValueError('Corrupt original error result')
    rejection = Rejection(result['code'], result['details'])
    rejection.encoded()
    if rejection.http_status != row['http_status']:
        raise ValueError('Original status and error differ')
    return rejection


def _safe_id(value):
    return type(value) is int and 1 <= value <= MAX_SAFE_INTEGER


def _associations(connection, command, result):
    """Use verified stored identities, never a body or a client's module label."""
    coding = testing = operation = None
    if not isinstance(result, Success):
        return coding, testing, operation
    data = result.result['data']
    validate_registered_success(command, data, result.result['code'], result.http_status)
    for field in ('task_id', 'testing_task_id', 'operation_id'):
        if data.get(field) is not None and not _safe_id(data[field]):
            raise ValueError('Invalid persisted receipt identity')
    coding = data.get('task_id')
    testing = data.get('testing_task_id')
    if command.route.capability_id == 'APP-CODE-CMD-C32':
        coding = data['id']
        fields = (
            'document_id',
            'requirement_id',
            'design_revision_id',
            'repository_id',
            'base_snapshot_id',
            'target_branch',
            'created_at',
        )
        owner = connection.execute(
            'SELECT ' + ','.join(fields) + ' FROM code_tasks WHERE id=?', (coding,)
        ).fetchone()
        if owner is None or any(owner[key] != data[key] for key in fields):
            raise ValueError('Original task receipt differs from its fixed owner')
        materials = connection.execute(
            'SELECT document_id,revision_id FROM code_task_materials WHERE task_id=?', (coding,)
        )
        if {tuple(item) for item in materials} != {
            (item['document_id'], item['revision_id']) for item in data['material_refs']
        }:
            raise ValueError('Original task receipt differs from its fixed material')
    if command.route.capability_id == 'APP-CODE-CMD-C37' and result.http_status == 200:
        coding = data['id']
        stopped = connection.execute(
            'SELECT t.status,t.document_id,t.requirement_id,t.state_version,'
            "(SELECT id FROM code_operations o WHERE o.task_id=t.id AND o.resource_kind='TASK' "
            "AND o.operation_type='TERMINATE' AND o.status='SUCCEEDED') AS termination_operation_id "
            'FROM code_tasks t WHERE t.id=?',
            (coding,),
        ).fetchone()
        if stopped is None or any(
            stopped[field] != data[field]
            for field in (
                'status',
                'document_id',
                'requirement_id',
                'state_version',
                'termination_operation_id',
            )
        ):
            raise ValueError('Terminal response differs from its original task')
    capability = command.route.capability_id
    if (
        capability == 'APP-CODE-CMD-C58'
        and connection.execute(
            'SELECT 1 FROM code_defects WHERE id=? AND task_id=? AND candidate_id=?',
            (data['defect_id'], coding, data['candidate_id']),
        ).fetchone()
        is None
    ):
        raise ValueError('Original Coding defect receipt has no immutable owner')
    if (
        capability in ('APP-TEST-CMD-C27', 'APP-TEST-CMD-C29', 'APP-TEST-CMD-C31')
        and result.http_status == 200
    ):
        testing = data['id']
        if testing != command.route.match(command.path)['testing_task_id']:
            raise ValueError('Original Testing response differs from its path owner')
        owner = connection.execute(
            'SELECT requirement_id,document_id,state_version,status FROM testing_tasks WHERE id=?',
            (testing,),
        ).fetchone()
        if owner is None or (
            owner['requirement_id'] != data['requirement_id']
            or owner['document_id'] != data['document_id']
            or owner['state_version'] < data['state_version']
            or capability == 'APP-TEST-CMD-C31'
            and (
                owner['status'] != data['status'] or owner['state_version'] != data['state_version']
            )
        ):
            raise ValueError('Original Testing response differs from its fixed owner')
    if (coding is not None and command.route.module != 'CODE') or (
        testing is not None and command.route.module != 'TEST'
    ):
        raise ValueError('Receipt identity crosses command modules')
    for identity, table in ((coding, 'code_tasks'), (testing, 'testing_tasks')):
        if (
            identity is not None
            and connection.execute(f'SELECT 1 FROM {table} WHERE id=?', (identity,)).fetchone()
            is None
        ):
            raise ValueError('Receipt task identity has no real owner')
    operation = data.get('operation_id')
    if operation is not None:
        row = connection.execute(
            'SELECT * FROM code_operations WHERE id=?', (operation,)
        ).fetchone()
        if row is None:
            raise ValueError('Accepted operation must exist')
        if command.route.capability_id == 'APP-CODE-CMD-C37':
            if row['resource_kind'] != 'TASK' or row['operation_type'] != 'TERMINATE':
                raise ValueError('Termination receipt belongs to another operation')
            if row['idempotency_key'] != command.key:
                from backend.app.code_tasks.task_stop import original_stop_result

                if original_stop_result(connection, row) != result:
                    raise ValueError('Repeated termination differs from the original acceptance')
            elif data['state_version'] != row['expected_state_version'] + 1:
                raise ValueError('Original stop receipt differs from its fenced version')
        elif capability == 'APP-TEST-CMD-C31':
            if row['resource_kind'] != 'TESTING_TASK' or row['operation_type'] != 'TERMINATE':
                raise ValueError('Testing termination belongs to another operation')
            if row['idempotency_key'] != command.key:
                from backend.app.testing.task_stop import original_stop_result

                if original_stop_result(connection, row) != result:
                    raise ValueError('Repeated Testing termination differs from the original')
            elif data['state_version'] != row['expected_state_version'] + 1:
                raise ValueError('Original Testing stop differs from its fenced version')
        elif row['idempotency_key'] != command.key:
            raise ValueError('Accepted operation must belong to the original key')
        testing_control = {
            'APP-TEST-CMD-C26': 'DRAFT_PLAN',
            'APP-TEST-CMD-C28': 'RUN_TEST',
            'APP-TEST-CMD-C30': 'RESUME',
            'APP-TEST-CMD-C32': 'RECONCILE',
        }.get(capability)
        if testing_control is not None and (
            row['resource_kind'] != 'TESTING_TASK'
            or row['operation_type'] != testing_control
            or row['task_id'] is not None
            or row['testing_task_id'] != data['testing_task_id']
            or row['resource_id'] != data['testing_task_id']
            or data['state_version']
            != row['expected_state_version'] + int(testing_control in ('RUN_TEST', 'DRAFT_PLAN'))
        ):
            raise ValueError('Original Testing control receipt crosses scope or version')
        if capability in ('APP-TEST-CMD-C18', 'APP-TEST-CMD-C19') and (
            row['resource_kind'] != 'TEST_PACK_VERSION'
            or row['resource_id'] != data['test_pack_version_id']
            or row['resource_id'] != command.route.match(command.path)['id']
            or row['operation_type']
            != ('SEAL_PACK' if capability == 'APP-TEST-CMD-C18' else 'VALIDATE_PACK')
            or row['task_id'] is not None
            or row['testing_task_id'] is not None
        ):
            raise ValueError('Original Testing asset receipt crosses pack or action scope')
        if command.route.capability_id == 'APP-CODE-CMD-C35' and (
            row['resource_kind'] != 'TASK'
            or row['operation_type'] != 'START'
            or data['state_version'] != row['expected_state_version'] + 1
        ):
            raise ValueError('Original START receipt differs from the accepted operation')
        coding_control = {
            'APP-CODE-CMD-C59': 'REPAIR',
            'APP-CODE-CMD-C62': 'PREPARE_DELIVERY',
            'APP-CODE-CMD-C64': 'DELIVER',
        }.get(capability)
        if coding_control is not None and (
            row['resource_kind'] != 'TASK'
            or row['operation_type'] != coding_control
            or row['testing_task_id'] is not None
            or row['task_id'] != data['task_id']
            or row['resource_id'] != data['task_id']
            or data['state_version'] != row['expected_state_version'] + 1
        ):
            raise ValueError('Original Coding lifecycle receipt crosses scope or version')
        if (
            coding_control == 'REPAIR'
            and connection.execute(
                'SELECT 1 FROM code_repairs WHERE operation_id=? AND task_id=?',
                (operation, data['task_id']),
            ).fetchone()
            is None
        ):
            raise ValueError('Original repair receipt has no repair')
        if (
            coding_control == 'DELIVER'
            and connection.execute(
                """SELECT 1 FROM code_deliveries WHERE id=? AND acceptance_id=? AND operation_id=?
               AND task_id=?""",
                (data['delivery_id'], data['acceptance_id'], operation, data['task_id']),
            ).fetchone()
            is None
        ):
            raise ValueError('Original delivery receipt has no acceptance')
        expected = REPOSITORY_OPERATIONS.get(command.route.capability_id)
        if expected is not None and (
            row['resource_kind'] != 'REPOSITORY'
            or row['resource_id'] != data['resource_id']
            or row['operation_type'] != expected
            or row['task_id'] is not None
            or row['testing_task_id'] is not None
            or (
                expected != 'REGISTER_REPOSITORY'
                and command.route.match(command.path)['id'] != row['resource_id']
            )
        ):
            raise ValueError('Original repository receipt owner differs')
        is_testing = row['resource_kind'].startswith('TEST')
        if is_testing != (command.route.module == 'TEST'):
            raise ValueError('Accepted operation belongs to the other module')
        if (coding is not None and coding != row['task_id']) or (
            testing is not None and testing != row['testing_task_id']
        ):
            raise ValueError('Receipt and operation owners differ')
        coding, testing = row['task_id'], row['testing_task_id']
        path = command.route.match(command.path)
        for field, actual in (('task_id', coding), ('testing_task_id', testing)):
            if field in path and path[field] != actual:
                raise ValueError('Accepted operation differs from the original path owner')
    if result.result['code'] == 'OPERATION_ACCEPTED' and operation is None:
        raise ValueError('Asynchronous acceptance requires a real durable operation')
    return coding, testing, operation


def receipt_in_transaction(connection, command, row):
    receipt = {
        'lookup_status': 'NOT_FOUND',
        'record_status': None,
        'original_http_status': None,
        'original_outcome': None,
        'task_id': None,
        'testing_task_id': None,
        'operation_id': None,
    }
    if row is None:
        return receipt
    receipt['record_status'] = row['status']
    if row['status'] == 'PROCESSING':
        # An old claim alone does not establish a currently running operation.
        receipt['lookup_status'] = 'UNKNOWN'
        return receipt
    if row['status'] not in ('SUCCEEDED', 'REJECTED', 'CLOSED'):
        raise ValueError('Unknown original record state')
    result = _stored_result(row)
    coding, testing, operation = _associations(connection, command, result)
    if isinstance(result, Success):
        outcome = {'success': True, 'data': result.result['data'], 'error': None}
    else:
        _status, code, message, details = error_fact(result.code, result.details)
        outcome = {
            'success': False,
            'data': None,
            'error': {'code': code, 'message': message, 'details': details},
        }
    receipt.update(
        lookup_status='FOUND',
        original_http_status=row['http_status'],
        original_outcome=outcome,
        task_id=coding,
        testing_task_id=testing,
        operation_id=operation,
    )
    return receipt


def lookup_receipt(database, scope):
    require_v20(database)
    command = command_for_scope(scope)
    with database.transaction() as connection:
        return receipt_in_transaction(connection, command, _row(connection, scope))


def close_command(executor, scope):
    executor._owned()
    require_v20(executor.database)
    command = command_for_scope(scope)
    with executor.database.transaction(write=True) as connection:
        row = _row(connection, scope)
        if row is None:
            closed = Rejection(
                'COMMAND_CLOSED',
                {
                    'method': 'POST',
                    'path': command.path,
                    'closed_at': executor._time(),
                },
            )
            # One server timestamp is used for the complete immutable close fact.
            error = closed.encoded()
            now = closed.details['closed_at']
            connection.execute(
                f'INSERT INTO idempotency_records({COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (*scope.identity, None, 'CLOSED', executor.owner_epoch, now, now, None, 409, error),
            )
            row = _row(connection, scope)
        return {
            'close_status': 'CLOSED' if row['status'] == 'CLOSED' else 'ALREADY_RECEIVED',
            'original_receipt': receipt_in_transaction(connection, command, row),
        }


def _replay(connection, command, row, input_json):
    if row['status'] == 'CLOSED':
        return _stored_result(row)
    if row['business_input_json'] != input_json:
        return Rejection('OPERATION_CONFLICT', empty_conflict())
    if row['status'] == 'PROCESSING':
        return Rejection('OPERATION_IN_PROGRESS', empty_conflict())
    previous = _stored_result(row)
    _associations(connection, command, previous)
    return previous


def read_registered_replay(executor, scope, business_input):
    """Check the original result before external work. A miss reserves nothing."""
    executor._owned()
    require_v20(executor.database)
    command = command_for_scope(scope)
    with executor.database.transaction() as connection:
        row = _row(connection, scope)
        if row is None:
            return None
        input_json = None if row['status'] == 'CLOSED' else canonical_input(business_input)
        return _replay(connection, command, row, input_json)


def execute_registered(executor, scope, business_input, operation):
    executor._owned()
    require_v20(executor.database)
    command = command_for_scope(scope)
    with executor.database.transaction(write=True) as connection:
        row = _row(connection, scope)
        if row is not None:
            input_json = None if row['status'] == 'CLOSED' else canonical_input(business_input)
            return _replay(connection, command, row, input_json)
        input_json = canonical_input(business_input)
        _insert(connection, executor, scope, input_json, 'PROCESSING')
        claim = Claim(scope, input_json, executor.owner_epoch)
        try:
            with executor.database.reversible(connection) as attempt:
                result = operation(connection)
                if isinstance(result, Rejection):
                    result.encoded()
                    attempt.rollback()
        except Rejected as error:
            # Only known application 4xx facts qualify; storage/commit/unknown exceptions escape.
            result = Rejection(error.code, error.details)
            result.encoded()
        if isinstance(result, Rejection):
            if result.code == 'COMMAND_CLOSED':
                raise ValueError('Only the original-key close controller can create CLOSED')
            encoded = result.encoded()
            executor.assert_claim(connection, claim)
            connection.execute(
                "UPDATE idempotency_records SET status='REJECTED',error_result_json=?,http_status=?,updated_at=? "
                'WHERE capability_id=? AND target_identity=? AND idempotency_key=?',
                (encoded, result.http_status, executor._time(), *scope.identity),
            )
        elif isinstance(result, Success):
            result.encoded()
            _associations(connection, command, result)
            executor.succeed(connection, claim, result)
        else:
            raise TypeError('Registered command must return Success or a certain Rejection')
        return result
