"""Immutable Coding defect records with original fixed design and Testing provenance."""

from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.infrastructure.schema_transport import compact
from backend.app.infrastructure.windows_private_package import (
    PackageSecurityError,
    current_operator_sid,
)
from backend.app.shared.command_execution import execute_idempotent, operation_time
from backend.app.shared.http_boundary import handle_http, idempotency_header, request_query
from backend.app.shared.http_projection import exact, page
from backend.app.shared.pagination import MAX_PAGE, PAGE_SIZE, page_metadata, page_offset
from backend.app.shared.validation import (
    MAX_SAFE_INTEGER,
    UNICODE_WHITESPACE,
    decimal_integer,
    object_fields,
    raw_text,
    reject,
    strict_enum,
    strict_integer,
    strict_json_object,
)

from .command_registry import RegisteredCommand, registered_command
from .configuration_identities import require_schema
from .design_revisions import design_revision_choice
from .repository_operations import _time
from .repository_reads import ERRORS
from .task_question_answers import BASIS_FIELDS, EVIDENCE, EVIDENCE_FIELDS
from .task_start import start_conflict

PATH = '/code-tasks/{task_id}/defects'
_TASK_PATH = '/api/v1' + PATH
_BASE = ('candidate_id', 'expected_state_version')
_MANUAL = ('actual_behavior', 'expected_behavior', 'basis_ref', 'evidence_refs')
_IMPORT = ('testing_finding_id',)
_CREATED = ('defect_id', 'task_id', 'candidate_id')
_FIELDS = (
    'id',
    'task_id',
    'candidate_id',
    *_MANUAL,
    'testing_finding_id',
    'created_at',
    'actor_ref',
)
DEFECT_STATES = ('VERIFYING', 'AWAITING_TESTING', 'AWAITING_ACCEPTANCE', 'WAITING')
_NOT_FOUND = Rejection('NOT_FOUND', None)
defect_router = APIRouter(redirect_slashes=False)


def _nonblank(value, field, limit=None):
    fixed = raw_text(value, field, 1, limit)
    if not fixed.strip(UNICODE_WHITESPACE):
        reject(field, 'TOO_SHORT', '必须包含非空白内容')
    return fixed


def _basis(value):
    fixed = object_fields(value, 'basis_ref', BASIS_FIELDS, BASIS_FIELDS)
    return {
        'document_id': strict_integer(fixed['document_id'], 'basis_ref.document_id'),
        'revision_id': strict_integer(fixed['revision_id'], 'basis_ref.revision_id'),
        'quote': _nonblank(fixed['quote'], 'basis_ref.quote'),
    }


def _evidence(value):
    if type(value) is not list:
        reject('evidence_refs', 'INVALID_TYPE', '证据引用必须为数组')
    rows = []
    seen = set()
    for index, entry in enumerate(value):
        field = f'evidence_refs[{index}]'
        fixed = object_fields(entry, field, EVIDENCE_FIELDS, EVIDENCE_FIELDS)
        kind = strict_enum(fixed['kind'], field + '.kind', EVIDENCE)
        identity = strict_integer(fixed['id'], field + '.id')
        if (kind, identity) in seen:
            reject(field, 'DUPLICATE_PARAMETER', '证据引用不能重复')
        seen.add((kind, identity))
        rows.append({'kind': kind, 'id': identity})
    return rows


@dataclass(frozen=True)
class CreateDefectRequest:
    task_id: int
    data: dict
    command: RegisteredCommand
    body_fields = (*_BASE, *_MANUAL, *_IMPORT)

    def business_input(self):
        return self.data

    @property
    def idempotency_key(self):
        return self.command.key

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        task = decimal_integer(request.path_params['task_id'], 'task_id')
        branch = _IMPORT if 'testing_finding_id' in body else _MANUAL
        fields = (*_BASE, *branch)
        fixed = object_fields(body, 'body', fields, fields)
        data = {key: strict_integer(fixed[key], key) for key in _BASE}
        if branch == _IMPORT:
            data['testing_finding_id'] = strict_integer(
                fixed['testing_finding_id'], 'testing_finding_id'
            )
        else:
            data.update(
                actual_behavior=_nonblank(fixed['actual_behavior'], 'actual_behavior'),
                expected_behavior=_nonblank(fixed['expected_behavior'], 'expected_behavior'),
                basis_ref=_basis(fixed['basis_ref']),
                evidence_refs=_evidence(fixed['evidence_refs']),
            )
        return cls(
            task,
            data,
            registered_command(
                'POST',
                _TASK_PATH.format(task_id=task),
                idempotency_header(request, lowercase=True),
            ),
        )


def _invalid(code, field):
    return Rejection(code, {'field_errors': [{'field': field, 'reason': 'RANGE'}]})


def _original_basis(connection, task, basis):
    doc, revision = basis['document_id'], basis['revision_id']
    main = (doc, revision) == (task['document_id'], task['design_revision_id'])
    if (
        not main
        and connection.execute(
            'SELECT 1 FROM code_task_materials WHERE task_id=? AND document_id=? AND revision_id=?',
            (task['id'], doc, revision),
        ).fetchone()
        is None
    ):
        return False
    choice = design_revision_choice(
        connection, doc, revision, usage='MAIN' if main else 'MATERIAL', include_markdown=True
    )
    return (
        choice is not None
        and choice['requirement_id'] == task['requirement_id']
        and basis['quote'] in choice['markdown_snapshot']
    )


def _from_finding(connection, task, candidate, finding_id):
    from backend.app.testing.findings import _product_problem
    from backend.app.testing.reports import original_report
    from backend.app.testing.tasks import materials_for

    source = connection.execute(
        'SELECT * FROM testing_findings WHERE id=?', (finding_id,)
    ).fetchone()
    if source is None:
        return _NOT_FOUND
    report = connection.execute(
        'SELECT * FROM testing_reports WHERE id=?', (source['test_report_id'],)
    ).fetchone()
    if report is None:
        raise StorageUnavailable('Original Testing finding report is missing')
    tester, verification, pack = original_report(connection, report)
    if (
        source['classification'] != 'PRODUCT'
        or source['review_operation_id'] is None
        or tester['target_kind'] != 'CANDIDATE'
        or tester['candidate_id'] != candidate['id']
        or any(
            tester[key] != task[key]
            for key in ('requirement_id', 'document_id', 'design_revision_id')
        )
        or materials_for(connection, tester['id'])
        != materials_for(connection, task['id'], module='CODING')
        or source['basis_ref'] is None
        or source['expected_behavior'] is None
    ):
        return start_conflict('TEST_SOURCE_MISMATCH', task)
    imported = {
        'actual_behavior': source['actual_behavior'],
        'expected_behavior': source['expected_behavior'],
        'basis_ref': _basis(strict_json_object(source['basis_ref'])),
        'evidence_refs': [],
        'testing_finding_id': source['id'],
    }
    reviewed = {**dict(source), 'basis_ref': imported['basis_ref']}
    problem = _product_problem(connection, reviewed, tester, verification, pack)
    if problem is not None:
        return problem
    if (
        connection.execute(
            'SELECT 1 FROM code_defects WHERE task_id=? AND testing_finding_id=?',
            (task['id'], source['id']),
        ).fetchone()
        is not None
    ):
        return start_conflict('OPERATION_CONFLICT', task)
    return imported


def defect_action_reason(task):
    if (
        task['status'] not in DEFECT_STATES
        or task['stop_requested_at'] is not None
        or task['state_version'] >= MAX_SAFE_INTEGER
    ):
        return 'INVALID_STATE'
    return None if task['current_candidate_id'] is not None else 'CANDIDATE_NOT_CURRENT'


def _save(connection, request):
    task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (request.task_id,)).fetchone()
    if task is None:
        return _NOT_FOUND
    if task['status'] in ('COMPLETED', 'TERMINATED'):
        return start_conflict('TASK_ENDED', task)
    data = request.data
    if task['state_version'] != data['expected_state_version']:
        return start_conflict('VERSION_CONFLICT', task)
    reason = defect_action_reason(task)
    if reason is not None:
        return start_conflict(reason, task)
    candidate = connection.execute(
        'SELECT * FROM code_candidates WHERE id=? AND task_id=?', (data['candidate_id'], task['id'])
    ).fetchone()
    if candidate is None:
        return _NOT_FOUND
    if candidate['id'] != task['current_candidate_id']:
        return start_conflict('CANDIDATE_NOT_CURRENT', task)
    if 'testing_finding_id' in data:
        facts = _from_finding(connection, task, candidate, data['testing_finding_id'])
        if type(facts) is Rejection:
            return facts
    else:
        facts = {key: data[key] for key in _MANUAL}
        facts['testing_finding_id'] = None
    if not _original_basis(connection, task, facts['basis_ref']):
        return _invalid('BASIS_REF_INVALID', 'basis_ref')
    for index, ref in enumerate(facts['evidence_refs']):
        if connection.execute(EVIDENCE[ref['kind']], (task['id'], ref['id'])).fetchone() is None:
            return _invalid('DEFECT_SOURCE_MISMATCH', f'evidence_refs[{index}]')
    try:
        actor = current_operator_sid()
    except PackageSecurityError:
        return Rejection(
            'PERMISSION_NOT_GRANTED', {'task_id': task['id'], 'authorization_id': None}
        )
    at = max(operation_time(None), task['updated_at'])
    identity = entity_id(connection, EntityKind.CODE_DEFECT)
    connection.execute(
        """INSERT INTO code_defects(id,task_id,candidate_id,actual_behavior,expected_behavior,
           basis_ref,testing_finding_id,created_at,actor_ref) VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            identity,
            task['id'],
            candidate['id'],
            facts['actual_behavior'],
            facts['expected_behavior'],
            compact(facts['basis_ref']),
            facts['testing_finding_id'],
            at,
            actor,
        ),
    )
    for ordinal, ref in enumerate(facts['evidence_refs'], 1):
        connection.execute(
            'INSERT INTO code_defect_evidence_refs(defect_id,ordinal,kind,source_id) VALUES(?,?,?,?)',
            (identity, ordinal, ref['kind'], ref['id']),
        )
    updated = connection.execute(
        """UPDATE code_tasks SET state_version=?,updated_at=? WHERE id=? AND state_version=?
           AND current_candidate_id=? AND stop_requested_at IS NULL""",
        (increment(task['state_version']), at, task['id'], task['state_version'], candidate['id']),
    )
    if updated.rowcount != 1:
        raise StorageUnavailable('Original Coding defect candidate changed before save')
    return Success(
        {
            'code': 'CREATED',
            'data': {
                'defect_id': identity,
                'task_id': task['id'],
                'candidate_id': candidate['id'],
            },
            'details': None,
        },
        201,
    )


def create_defect(runtime, request):
    require_schema(runtime)
    return execute_idempotent(
        runtime.commands(),
        request.command.route.capability_id,
        request,
        lambda connection: _save(connection, request),
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset(),
    )


def _project(row, task):
    data = exact(row, _FIELDS)
    for key in ('id', 'task_id', 'candidate_id'):
        strict_integer(data[key], key)
    if data['task_id'] != task:
        raise ValueError('Original Coding defect owner differs')
    for key in _MANUAL[:2]:
        _nonblank(data[key], key)
    _basis(data['basis_ref'])
    _evidence(data['evidence_refs'])
    if data['testing_finding_id'] is not None:
        strict_integer(data['testing_finding_id'], 'testing_finding_id')
        if data['evidence_refs']:
            raise ValueError('Original Testing finding has foreign Coding evidence')
    _time(data['created_at'], nullable=False)
    _nonblank(data['actor_ref'], 'actor_ref', 1024)
    return data


def _stored(connection, row, task):
    data = {key: row[key] for key in _FIELDS if key != 'evidence_refs'}
    data['basis_ref'] = strict_json_object(row['basis_ref'])
    evidence = connection.execute(
        """SELECT ordinal,kind,source_id FROM code_defect_evidence_refs
           WHERE defect_id=? ORDER BY ordinal""",
        (row['id'],),
    )
    data['evidence_refs'] = []
    for ordinal, ref in enumerate(evidence, 1):
        if ref['ordinal'] != ordinal:
            raise StorageUnavailable('Original Coding defect evidence order is incomplete')
        data['evidence_refs'].append({'kind': ref['kind'], 'id': ref['source_id']})
    if (
        connection.execute(
            'SELECT 1 FROM code_candidates WHERE id=? AND task_id=?', (data['candidate_id'], task)
        ).fetchone()
        is None
    ):
        raise StorageUnavailable('Original Coding defect candidate is missing')
    return _project(data, task)


@dataclass(frozen=True)
class ReadDefectRequest:
    task_id: int
    identity: int | None
    page: int

    @classmethod
    def parse(cls, request):
        task = decimal_integer(request.path_params['task_id'], 'task_id')
        if 'defect_id' in request.path_params:
            request_query(request)
            return cls(task, decimal_integer(request.path_params['defect_id'], 'defect_id'), 1)
        query = request_query(request, singles=('page',))
        return cls(task, None, decimal_integer(query.get('page', '1'), 'page', maximum=MAX_PAGE))


def read_defects(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        if (
            connection.execute('SELECT 1 FROM code_tasks WHERE id=?', (request.task_id,)).fetchone()
            is None
        ):
            return _NOT_FOUND.result
        if request.identity is not None:
            row = connection.execute(
                'SELECT * FROM code_defects WHERE id=? AND task_id=?',
                (request.identity, request.task_id),
            ).fetchone()
            if row is None:
                return _NOT_FOUND.result
            data = _stored(connection, row, request.task_id)
        else:
            total = connection.execute(
                'SELECT count(*) FROM code_defects WHERE task_id=?', (request.task_id,)
            ).fetchone()[0]
            rows = connection.execute(
                'SELECT * FROM code_defects WHERE task_id=? ORDER BY id LIMIT ? OFFSET ?',
                (request.task_id, PAGE_SIZE, page_offset(request.page)),
            )
            data = {
                **page_metadata(request.page, total),
                'items': [_stored(connection, row, request.task_id) for row in rows],
            }
        return {'code': 'READ_OK', 'data': data, 'details': None}


class CreatedDefect:
    error_contract = 'code'
    status = 201
    success_code = 'CREATED'
    errors = ERRORS | {
        'COMMAND_CLOSED',
        'OPERATION_CONFLICT',
        'VERSION_CONFLICT',
        'INVALID_STATE',
        'TASK_ENDED',
        'CANDIDATE_NOT_CURRENT',
        'BASIS_REF_INVALID',
        'DEFECT_SOURCE_MISMATCH',
        'TEST_SOURCE_MISMATCH',
        'PERMISSION_NOT_GRANTED',
    }

    @staticmethod
    def project(value, request):
        data = exact(value, _CREATED)
        if (
            data['task_id'] != request.task_id
            or data['candidate_id'] != request.data['candidate_id']
        ):
            raise ValueError('Original Coding defect creation differs')
        for key in _CREATED:
            strict_integer(data[key], key)
        return data, None


class ReadDefect:
    error_contract = 'code'
    status = 200
    success_code = 'READ_OK'
    errors = ERRORS

    @staticmethod
    def project(value, request):
        if request.identity is None:
            return page(value, lambda row: _project(row, request.task_id), request.page)
        data = _project(value, request.task_id)
        if data['id'] != request.identity:
            raise ValueError('Original Coding defect identity differs')
        return data, None


@defect_router.post(_TASK_PATH)
async def create_defect_http(request: Request):
    return await handle_http(request, CreateDefectRequest, CreatedDefect, create_defect)


@defect_router.get(_TASK_PATH)
@defect_router.get(_TASK_PATH + '/{defect_id}')
async def read_defects_http(request: Request):
    return await handle_http(request, ReadDefectRequest, ReadDefect, read_defects)
