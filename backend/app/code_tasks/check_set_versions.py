"""Check standard versions: immutable saves and same-snapshot nonsecret reads."""

from datetime import datetime

from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success
from backend.app.infrastructure.identifiers import (
    EntityKind,
    entity_id,
    increment,
    require_write_transaction,
)
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.infrastructure.schema_transport import compact
from backend.app.shared.code_errors import empty_conflict
from backend.app.shared.command_execution import execute_idempotent, operation_time
from backend.app.shared.http_boundary import HTTP_REQUEST_BYTES
from backend.app.shared.validation import (
    MAX_SAFE_INTEGER,
    InvalidInput,
    strict_integer,
    strict_json_object,
)

from .check_set_content import parse_check_set_content
from .configuration_identities import require_schema

VERSION_FIELDS = (
    'id',
    'check_set_id',
    'version',
    'owner_module',
    'protocol_version',
    'items',
    'coverage_plan',
    'created_at',
    'ready',
    'unresolved_capability_codes',
)


def _invalid(field):
    return Rejection('INVALID_INPUT', {'field_errors': [{'field': field, 'reason': 'RELATION'}]})


def _basis_error(connection, content):
    for i, coverage in enumerate(content['coverage_plan']):
        for j, ref in enumerate(coverage['basis_refs']):
            row = connection.execute(
                "SELECT markdown_snapshot FROM revisions WHERE id=? AND document_id=? AND revision_type='CONTENT'",
                (ref['revision_id'], ref['document_id']),
            ).fetchone()
            if row is None or ref['quote'] not in row['markdown_snapshot']:
                return f'coverage_plan[{i}].basis_refs[{j}]'
    return None


def resource_snapshot(catalog, items):
    if not items:
        return {}
    return {
        kind: catalog.code_configuration_options(kind)
        for kind in ('RUNNER', 'CASE_PACK', 'COMMAND', 'RUNTIME')
    }


def _find(snapshot, kind, key, ref):
    rows = [entry for entry in snapshot.get(kind, ()) if entry['value'].get(key) == ref]
    if len(rows) > 1:
        raise ConfigInvalid('Ambiguous immutable check resource reference')
    if rows and type(rows[0]['ready']) is not bool:
        raise ConfigInvalid('Check resource admission must be a real boolean')
    return rows[0] if rows else None


def resource_check(content, snapshot):
    """Return first missing/incompatible reference and actual admission status."""
    ready = bool(content['items'])
    for i, item in enumerate(content['items']):
        runner = _find(snapshot, 'RUNNER', 'runner_ref', item['runner_ref'])
        if runner is None:
            return f'items[{i}].runner_ref', False
        ready = ready and runner['ready']
        if runner['value']['protocol_version'] != content['protocol_version']:
            return f'items[{i}].runner_ref', False
        if not set(item['protected_input_refs']).issubset(runner['value']['protected_input_refs']):
            return f'items[{i}].protected_input_refs', False
        capability = item['evidence_rule']['kind']
        if capability == 'PROCESS_EXIT':
            command = _find(snapshot, 'COMMAND', 'command_id', item['command_id'])
            if command is None or command['value']['purpose'] != 'CHECK':
                return f'items[{i}].command_id', False
            ready = ready and command['ready']
            capability = 'CLI'
        elif capability == 'CONTROLLED_CASES':
            cases = _find(snapshot, 'CASE_PACK', 'case_pack_ref', item['case_pack_ref'])
            if cases is None:
                return f'items[{i}].case_pack_ref', False
            ready = ready and cases['ready'] and cases['value']['case_count'] > 0
            capability = cases['value']['driver_kind']
            if not all(
                ref in cases['value']['basis_refs']
                for row in content['coverage_plan']
                if item['check_id'] in row['check_ids']
                for ref in row['basis_refs']
            ):
                return f'items[{i}].case_pack_ref', False
            for identity in item['target']['command_ids']:
                command = _find(snapshot, 'COMMAND', 'command_id', identity)
                if command is None or command['value']['purpose'] not in ('EXECUTION', 'SERVICE'):
                    return f'items[{i}].target.command_ids', False
                ready = ready and command['ready']
            if item['target']['fixture_ref'] is not None:
                # The current catalogue has no immutable fixture descriptor.
                # Do not infer that an opaque name is an admitted fixture.
                ready = False
            if item['required'] and set(item['stages']) & {'INTEGRATION', 'ACCEPTANCE'}:
                ready = ready and item['target']['application_mode'] == 'REAL_CANDIDATE'
        if capability not in runner['value']['capabilities']:
            return f'items[{i}].runner_ref', False
        for ref in item['environment_refs']:
            environment = _find(snapshot, 'RUNTIME', 'runtime_ref', ref)
            if environment is None:
                return f'items[{i}].environment_refs', False
            ready = ready and environment['ready']
    return None, bool(ready)


def readiness(content, owner, snapshot):
    missing, ready = resource_check(content, snapshot)
    stages = (
        ('BACKEND', 'FRONTEND', 'INTEGRATION')
        if owner == 'CODING'
        else {stage for item in content['items'] for stage in item['stages']}
    )
    for stage in stages:
        ready = ready and any(
            item['required']
            and stage in item['stages']
            and item['evidence_rule']['kind'] == 'CONTENT_INTEGRITY'
            for item in content['items']
        )
        if owner == 'TESTING':
            ready = ready and any(
                item['required']
                and stage in item['stages']
                and item['evidence_rule']['kind'] == 'CONTROLLED_CASES'
                for item in content['items']
            )
    return {
        'ready': bool(ready and missing is None),
        'unresolved_capability_codes': [] if ready and missing is None else ['Q20-CHECKS'],
    }


def publish_check_set_version(runtime, request):
    require_schema(runtime)
    catalogue_unavailable = False

    def save(connection):
        nonlocal catalogue_unavailable
        require_write_transaction(connection)
        if (
            connection.execute(
                'SELECT 1 FROM code_check_sets WHERE id=?', (request.check_set_id,)
            ).fetchone()
            is None
        ):
            return Rejection('NOT_FOUND', None)
        content = request.content.value()
        field = _basis_error(connection, content)
        if field is not None:
            return _invalid(field)
        try:
            snapshot = resource_snapshot(runtime.catalog, content['items'])
            missing, _ = resource_check(content, snapshot)
        except ConfigInvalid as error:
            catalogue_unavailable = True
            raise StorageUnavailable('Check resource catalogue unavailable') from error
        if missing is not None:
            return _invalid(missing)
        previous = connection.execute(
            'SELECT MAX(version) FROM code_check_set_versions WHERE check_set_id=?',
            (request.check_set_id,),
        ).fetchone()[0]
        high_water = connection.execute(
            "SELECT last_value FROM sequences WHERE entity_kind='CheckSetVersion'"
        ).fetchone()
        if previous == MAX_SAFE_INTEGER or (
            high_water is not None and high_water[0] == MAX_SAFE_INTEGER
        ):
            return Rejection('PRECONDITION_FAILED', empty_conflict())
        version = 1 if previous is None else increment(previous)
        identity = entity_id(connection, EntityKind.CHECK_SET_VERSION)
        connection.execute(
            'INSERT INTO code_check_set_versions(id,check_set_id,version,owner_module,protocol_version,items,coverage_plan,created_at) VALUES(?,?,?,?,?,?,?,?)',
            (
                identity,
                request.check_set_id,
                version,
                'CODING',
                content['protocol_version'],
                compact(content['items']),
                compact(content['coverage_plan']),
                operation_time(None),
            ),
        )
        return Success(
            {
                'code': 'CREATED',
                'data': {'resource_kind': 'CHECK_SET_VERSION', 'resource_id': identity},
                'details': None,
            },
            201,
        )

    result = execute_idempotent(
        runtime.commands(),
        request.command.route.capability_id,
        request,
        save,
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset(),
    )
    if catalogue_unavailable and result['code'] == 'STORAGE_UNAVAILABLE':
        result['details'] = {'capability_codes': ['Q20-CONFIG']}
    return result


def _project(row, connection, catalog, snapshots):
    data = dict(row)
    try:
        for field in ('items', 'coverage_plan'):
            encoded = data[field]
            if type(encoded) is not str or len(encoded) > HTTP_REQUEST_BYTES:
                raise ValueError('Stored version content exceeds capacity')
        raw_content = {
            'protocol_version': data['protocol_version'],
            'items': strict_json_object('{"value":' + data['items'] + '}')['value'],
            'coverage_plan': strict_json_object('{"value":' + data['coverage_plan'] + '}')['value'],
        }
        content = parse_check_set_content(
            raw_content,
            owner_module=data['owner_module'],
            max_input_bytes=HTTP_REQUEST_BYTES,
        ).value()
        if raw_content != content:
            raise ValueError('Stored version content must not be normalized on read')
        for field in ('id', 'check_set_id', 'version'):
            strict_integer(data[field], field)
        if (
            datetime.fromisoformat(data['created_at'])
            .isoformat(timespec='milliseconds')
            .replace('+00:00', 'Z')
            != data['created_at']
        ):
            raise ValueError('Invalid configuration version timestamp')
        if _basis_error(connection, content) is not None:
            raise ValueError('Stored check basis differs')
    except (ValueError, TypeError, KeyError, InvalidInput) as error:
        raise StorageUnavailable('Stored check version is invalid') from error
    key = bool(content['items'])
    if key not in snapshots:
        snapshots[key] = resource_snapshot(catalog, content['items'])
    data.update(content)
    data.update(readiness(content, data['owner_module'], snapshots[key]))
    return data


def read_check_set_version(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        row = connection.execute(
            'SELECT * FROM code_check_set_versions WHERE id=?', (request.version_id,)
        ).fetchone()
        if row is None:
            return {'code': 'NOT_FOUND', 'data': None, 'details': None}
        try:
            data = _project(row, connection, runtime.catalog, {})
        except ConfigInvalid:
            return {
                'code': 'CONFIG_NOT_READY',
                'data': None,
                'details': {'capability_codes': ['Q20-CHECKS']},
            }
    return {'code': 'READ_OK', 'data': data, 'details': None}


def list_check_set_versions(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        if (
            connection.execute(
                'SELECT 1 FROM code_check_sets WHERE id=?', (request.check_set_id,)
            ).fetchone()
            is None
        ):
            return {'code': 'NOT_FOUND', 'data': None, 'details': None}
        total = connection.execute(
            'SELECT COUNT(*) FROM code_check_set_versions WHERE check_set_id=?',
            (request.check_set_id,),
        ).fetchone()[0]
        rows = connection.execute(
            'SELECT * FROM code_check_set_versions WHERE check_set_id=? ORDER BY version DESC,id DESC LIMIT 20 OFFSET ?',
            (request.check_set_id, (request.page - 1) * 20),
        ).fetchall()
        try:
            snapshots = {}
            items = [_project(row, connection, runtime.catalog, snapshots) for row in rows]
        except ConfigInvalid:
            return {
                'code': 'CONFIG_NOT_READY',
                'data': None,
                'details': {'capability_codes': ['Q20-CHECKS']},
            }
    return {
        'code': 'READ_OK',
        'data': {
            'items': items,
            'page': request.page,
            'page_size': 20,
            'total': total,
            'total_pages': (total + 19) // 20,
        },
        'details': None,
    }
