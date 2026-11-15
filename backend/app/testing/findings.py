"""Review an original Testing finding without changing its report or code."""

from backend.app.code_tasks.configuration_identities import require_schema
from backend.app.code_tasks.design_revisions import design_revision_choice
from backend.app.code_tasks.operation_protocol import operation_steps
from backend.app.code_tasks.repository_operations import _time
from backend.app.infrastructure.check_runner_bundle import reference
from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.infrastructure.windows_private_package import (
    PackageSecurityError,
    current_operator_sid,
)
from backend.app.shared.code_errors import empty_conflict
from backend.app.shared.command_execution import execute_idempotent, operation_time
from backend.app.shared.http_projection import exact
from backend.app.shared.pagination import PAGE_SIZE, page_metadata, page_offset
from backend.app.shared.validation import (
    MAX_SAFE_INTEGER,
    ordinary_text,
    raw_text,
    strict_enum,
    strict_integer,
    strict_json_object,
)

from .assets import NOT_FOUND, _read
from .pack_definitions import compiled_definition
from .reports import original_report
from .tasks import basis_failure, materials_for, optional_id
from .validation_evidence import _case_facts, owned_check_fact

CLASSIFICATIONS = (
    'UNCLASSIFIED',
    'PRODUCT',
    'TEST_DESIGN',
    'REQUIREMENT',
    'ENVIRONMENT',
    'UNKNOWN',
)
FIELDS = (
    'id',
    'test_report_id',
    'item_id',
    'case_id',
    'actual_behavior',
    'expected_behavior',
    'basis_ref',
    'classification',
    'state_version',
    'review_reason',
    'review_operation_id',
    'created_at',
)


def project_finding(value):
    row = exact(value, FIELDS)
    for key in ('id', 'test_report_id', 'state_version'):
        strict_integer(row[key], key)
    for key in ('item_id', 'review_operation_id'):
        optional_id(row[key], key)
    if row['case_id'] is not None:
        reference(row['case_id'])
        if row['item_id'] is None:
            raise ValueError('Original Testing finding case has no item')
    raw_text(row['actual_behavior'], 'actual_behavior', 1, 4000)
    if row['expected_behavior'] is not None:
        raw_text(row['expected_behavior'], 'expected_behavior', 1, 4000)
    basis = row['basis_ref']
    if basis is not None:
        exact(basis, ('document_id', 'revision_id', 'quote'))
        strict_integer(basis['document_id'], 'document_id')
        strict_integer(basis['revision_id'], 'revision_id')
        raw_text(basis['quote'], 'quote', 1, 4096)
    status = strict_enum(row['classification'], 'classification', CLASSIFICATIONS)
    reviewed = status != 'UNCLASSIFIED'
    if (
        reviewed != (row['review_reason'] is not None)
        or reviewed != (row['review_operation_id'] is not None)
        or reviewed
        and ordinary_text(row['review_reason'], 'review_reason', 1, 2000) != row['review_reason']
        or status == 'PRODUCT'
        and (basis is None or row['case_id'] is None or row['expected_behavior'] is None)
    ):
        raise ValueError('Original Testing finding review differs')
    _time(row['created_at'], nullable=False)
    return row


def _view(connection, row, verification):
    if (
        row['item_id'] is not None
        and connection.execute(
            'SELECT 1 FROM code_verification_items WHERE id=? AND verification_id=?',
            (row['item_id'], verification['id']),
        ).fetchone()
        is None
    ):
        raise StorageUnavailable('Original Testing finding item belongs to another verification')
    value = {key: row[key] for key in FIELDS}
    if value['basis_ref'] is not None:
        value['basis_ref'] = strict_json_object(value['basis_ref'])
    if value['review_operation_id'] is not None:
        original = connection.execute(
            """SELECT * FROM code_operations WHERE id=? AND resource_kind='TESTING_FINDING'
               AND resource_id=? AND task_id IS NULL AND testing_task_id IS NULL
               AND operation_type='REVIEW_FINDING' AND status='SUCCEEDED'""",
            (value['review_operation_id'], value['id']),
        ).fetchone()
        if original is None:
            raise StorageUnavailable('Original Testing finding review is missing')
        fixed = strict_json_object(original['fixed_input'])
        if (
            original['expected_state_version'] + 1 != value['state_version']
            or fixed['classification'] != value['classification']
            or fixed['reason'] != value['review_reason']
        ):
            raise StorageUnavailable('Original Testing finding review input differs')
    return project_finding(value)


def _report_row(connection, report_id):
    return connection.execute('SELECT * FROM testing_reports WHERE id=?', (report_id,)).fetchone()


def list_findings(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        report = _report_row(connection, request.identity)
        if report is None:
            return NOT_FOUND.result
        _, verification, _ = original_report(connection, report)
        total = connection.execute(
            'SELECT count(*) FROM testing_findings WHERE test_report_id=?', (request.identity,)
        ).fetchone()[0]
        rows = connection.execute(
            'SELECT * FROM testing_findings WHERE test_report_id=? ORDER BY id LIMIT ? OFFSET ?',
            (request.identity, PAGE_SIZE, page_offset(request.page)),
        ).fetchall()
        try:
            return _read(
                {
                    **page_metadata(request.page, total),
                    'items': [_view(connection, row, verification) for row in rows],
                }
            )
        except (KeyError, TypeError, ValueError) as error:
            raise StorageUnavailable('Original Testing findings are unreadable') from error


def _product_problem(connection, finding, task, verification, pack):
    if finding['case_id'] is None or finding['expected_behavior'] is None:
        return Rejection('TEST_SOURCE_MISMATCH', empty_conflict())
    row = connection.execute(
        """SELECT i.* FROM code_verification_case_results c
           JOIN code_verification_items i ON i.id=c.item_id
           WHERE c.item_id=? AND c.case_id=? AND i.verification_id=?
           AND c.result='FAILED' AND c.capture_status IN ('FULL','REDACTED')""",
        (finding['item_id'], finding['case_id'], verification['id']),
    ).fetchone()
    if row is None:
        return Rejection('TEST_SOURCE_MISMATCH', empty_conflict())
    _, compiled = compiled_definition(connection, pack)
    groups = {f'controlled-{i}': group for i, group in enumerate(compiled.case_packs, 1)}
    group = groups.get(row['check_id'])
    if owned_check_fact(connection, task, verification, row, group) is None:
        return Rejection('TEST_SOURCE_MISMATCH', empty_conflict())
    case = (
        None
        if group is None
        else next((item for item in group.cases if item.case_id == finding['case_id']), None)
    )
    failed = None
    if group is not None:
        failed = _case_facts(
            connection,
            row,
            {
                item.case_id: {assertion.assertion_id for assertion in item.assertions}
                for item in group.cases
            },
        )
    if case is None or failed is None or case.case_id not in failed:
        return Rejection('TEST_SOURCE_MISMATCH', empty_conflict())
    basis = finding['basis_ref']
    if basis is None or not any(
        (item.document_id, item.revision_id, item.quote)
        == (basis['document_id'], basis['revision_id'], basis['quote'])
        for item in case.basis_refs
    ):
        return basis_failure('basis_ref')
    document, revision = basis['document_id'], basis['revision_id']
    main = document == task['document_id'] and revision == task['design_revision_id']
    if not main and {'document_id': document, 'revision_id': revision} not in materials_for(
        connection, task['id']
    ):
        return basis_failure('basis_ref')
    original = design_revision_choice(
        connection, document, revision, usage='MAIN' if main else 'MATERIAL', include_markdown=True
    )
    if (
        original is None
        or original['requirement_id'] != task['requirement_id']
        or basis['quote'] not in original['markdown_snapshot']
    ):
        return basis_failure('basis_ref')
    return None


def _save_review(connection, request, row, verification, actor):
    at = max(operation_time(None), row['created_at'])
    if row['review_operation_id'] is not None:
        previous = connection.execute(
            'SELECT ended_at FROM code_operations WHERE id=?', (row['review_operation_id'],)
        ).fetchone()
        if previous is None or previous['ended_at'] is None:
            raise StorageUnavailable('Previous original Testing review has no completion time')
        at = max(at, previous['ended_at'])
    identity = entity_id(connection, EntityKind.OPERATION_RECORD)
    version = increment(row['state_version'])
    fixed = canonical_input({**request.business_input(), 'actor_ref': actor})
    result = canonical_input(
        {
            'finding_id': row['id'],
            'state_version': version,
            'classification': request.classification,
        }
    )
    connection.execute(
        """INSERT INTO code_operations(id,resource_kind,resource_id,operation_type,idempotency_key,
           expected_state_version,fixed_input,status,created_at,started_at,ended_at)
           VALUES(?,'TESTING_FINDING',?,'REVIEW_FINDING',?,?,?,'SUCCEEDED',?,?,?)""",
        (identity, row['id'], request.idempotency_key, row['state_version'], fixed, at, at, at),
    )
    connection.executemany(
        """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input,result_ref,
           started_at,ended_at,last_observed_at) VALUES(?,?,?,'SUCCEEDED',?,?,?,?,?)""",
        [
            (identity, number, step, fixed, result, at, at, at)
            for number, step in enumerate(operation_steps('RESOURCE', 'REVIEW_FINDING'), 1)
        ],
    )
    changed = connection.execute(
        """UPDATE testing_findings SET classification=?,state_version=?,review_reason=?,review_operation_id=?
           WHERE id=? AND state_version=?""",
        (
            request.classification,
            version,
            request.reason,
            identity,
            row['id'],
            row['state_version'],
        ),
    )
    if changed.rowcount != 1:
        raise StorageUnavailable('Original Testing finding changed before review commit')
    return _view(
        connection,
        connection.execute('SELECT * FROM testing_findings WHERE id=?', (row['id'],)).fetchone(),
        verification,
    )


def review_finding(runtime, request):
    require_schema(runtime)

    def save(connection):
        row = connection.execute(
            'SELECT * FROM testing_findings WHERE id=?', (request.identity,)
        ).fetchone()
        if row is None:
            return NOT_FOUND
        if row['state_version'] != request.expected:
            return Rejection(
                'VERSION_CONFLICT',
                {**empty_conflict(), 'current_state_version': row['state_version']},
            )
        if row['state_version'] == MAX_SAFE_INTEGER:
            return Rejection('INVALID_STATE', empty_conflict())
        report = _report_row(connection, row['test_report_id'])
        if report is None:
            raise StorageUnavailable('Original Testing finding report is missing')
        task, verification, pack = original_report(connection, report)
        finding = _view(connection, row, verification)
        if request.classification == 'PRODUCT':
            invalid = _product_problem(connection, finding, task, verification, pack)
            if invalid is not None:
                return invalid
        try:
            actor = current_operator_sid()
        except PackageSecurityError:
            return Rejection('PERMISSION_NOT_GRANTED', {'task_id': None, 'authorization_id': None})
        return Success(
            {
                'code': 'UPDATED',
                'data': _save_review(connection, request, row, verification, actor),
                'details': None,
            },
            200,
        )

    return execute_idempotent(
        runtime.commands(),
        request.command.route.capability_id,
        request,
        save,
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset(),
    )
