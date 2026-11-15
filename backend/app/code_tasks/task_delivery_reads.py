"""Read exact original plan and delivery facts without consulting live Git content."""

from dataclasses import dataclass
from time import monotonic

from fastapi import APIRouter, Request

from backend.app.infrastructure.content_manifest import git_oid
from backend.app.infrastructure.content_package import (
    TargetPackageBinding,
    verify_candidate_package,
)
from backend.app.infrastructure.content_paths import ContentPathError, relative_content_path
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.git_ref_protocol import branch_ref
from backend.app.infrastructure.windows_local_paths import FileIdentity
from backend.app.infrastructure.windows_private_package import PrivatePackageGuard
from backend.app.shared.command_execution import operation_time
from backend.app.shared.http_boundary import handle_http, request_query
from backend.app.shared.http_projection import exact, page
from backend.app.shared.pagination import MAX_PAGE, PAGE_SIZE, page_metadata, page_offset
from backend.app.shared.validation import (
    decimal_integer,
    reject,
    strict_boolean,
    strict_enum,
    strict_integer,
    strict_json_object,
)

from .configuration_identities import require_schema
from .repository_operations import _time
from .repository_reads import ERRORS
from .task_candidate_commit import capture_package_limits
from .task_candidate_content_reads import (
    ChunkRequest,
    DiffRequest,
    _changed,
    _chunk,
    _diff,
    _Files,
    _project_chunk,
    _project_diff,
    _read_after,
)
from .task_candidate_reads import NOT_FOUND, NOT_READY, _saved
from .task_delivery import PREPARE, PREPARE_PATH, original_operation

PLAN = PREPARE_PATH + '/{plan_id}'
DELIVERIES = '/api/v1/code-tasks/{task_id}/deliveries'
PLAN_FIELDS = (
    'id',
    'task_id',
    'candidate_id',
    'test_report_id',
    'repository_id',
    'target_branch',
    'expected_target_commit',
    'target_tree_oid',
    'target_manifest_sha256',
    'result_tree_oid',
    'operation_id',
    'created_at',
)
DELIVERY_FIELDS = (
    'id',
    'task_id',
    'acceptance_id',
    'delivery_plan_id',
    'operation_id',
    'status',
    'git_write_status',
    'postcheck_status',
    'created_at',
    'current_window_id',
    'commit_input_sha256',
    'observed_target_commit',
    'delivered_at',
    'last_reconciled_at',
    'planned_commit_oid',
    'failure_code',
)
delivery_reads_router = APIRouter(redirect_slashes=False)


@dataclass(frozen=True)
class StoredTargetPackage:
    binding: TargetPackageBinding
    directory: FileIdentity
    manifest_sha256: str
    observed_at: str
    original_target: dict


def stored_target(connection, plan):
    operation, fixed, steps = original_operation(connection, plan['operation_id'], PREPARE)
    claim = strict_json_object(steps[2]['external_identity'])
    observed = strict_json_object(steps[1]['result_ref'])
    sealed = strict_json_object(steps[2]['result_ref'])
    published = strict_json_object(steps[3]['result_ref'])
    binding = TargetPackageBinding(
        operation['id'],
        claim['plan_id'],
        operation['control_generation'],
        claim['content_store_key'],
        claim['content_profile_version_id'],
        claim['object_format'],
        observed['target_commit'],
        observed['target_tree'],
    )
    if (
        operation['status'] != 'SUCCEEDED'
        or any(step['status'] != 'SUCCEEDED' for step in steps)
        or operation['task_id'] != plan['task_id']
        or binding.plan_id != plan['id']
        or fixed['candidate_id'] != plan['candidate_id']
        or fixed['test_report_id'] != plan['test_report_id']
        or binding.content_store_key != plan['target_content_store_key']
        or binding.target_commit != plan['expected_target_commit']
        or binding.target_tree != plan['target_tree_oid']
        or observed['repository_id'] != plan['repository_id']
        or observed['target_branch'] != plan['target_branch']
        or sealed['manifest_sha256'] != plan['target_manifest_sha256']
        or published != {'delivery_plan_id': plan['id']}
    ):
        raise StorageUnavailable('Original delivery target package differs')
    _time(observed['observed_at'], nullable=False)
    return StoredTargetPackage(
        binding,
        FileIdentity(**sealed['directory']),
        sealed['manifest_sha256'],
        observed['observed_at'],
        observed,
    )


def verify_target_package(stored, limits, git_limits, *, consume_file=None, active=lambda: None):
    with PrivatePackageGuard(stored.directory.canonical_path) as guard:
        if guard.verify() != stored.directory:
            raise StorageUnavailable('Original target package location differs')
        sealed = verify_candidate_package(
            guard,
            stored.binding,
            limits=limits,
            git_limits=git_limits,
            started_at=monotonic(),
            active=active,
            consume_file=consume_file,
        )
        if sealed.manifest_sha256 != stored.manifest_sha256:
            raise StorageUnavailable('Original target manifest differs')
    return sealed


@dataclass(frozen=True)
class PlanReadRequest:
    task_id: int
    plan_id: int
    page: int

    @classmethod
    def parse(cls, request):
        query = request_query(request, singles=('page',))
        return cls(
            decimal_integer(request.path_params['task_id'], 'task_id'),
            decimal_integer(request.path_params['plan_id'], 'plan_id'),
            decimal_integer(query.get('page', '1'), 'page', MAX_PAGE),
        )


@dataclass(frozen=True)
class PlanFileRequest:
    task_id: int
    plan_id: int
    path: str
    offset: int
    length: int
    side: str

    @classmethod
    def parse(cls, request):
        query = request_query(request, singles=('path', 'offset', 'length', 'side'))
        try:
            path = relative_content_path(query.get('path'))
            if len(path) > 4096:
                raise ContentPathError('CONTENT_PATH_TOO_LONG')
        except ContentPathError:
            reject('path', 'INVALID_FORMAT', '必须使用原清单中的精确相对路径')
        offset = query.get('offset', '0')
        return cls(
            decimal_integer(request.path_params['task_id'], 'task_id'),
            decimal_integer(request.path_params['plan_id'], 'plan_id'),
            path,
            0 if offset == '0' else decimal_integer(offset, 'offset'),
            decimal_integer(query.get('length', '65536'), 'length', 65536),
            strict_enum(query.get('side'), 'side', ('BEFORE', 'AFTER')),
        )

    def comparison(self, candidate_id):
        return ChunkRequest(
            self.task_id, candidate_id, self.path, self.offset, self.length, self.side
        )


def _plan_files(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        plan = connection.execute(
            'SELECT * FROM code_delivery_plans WHERE id=? AND task_id=?',
            (request.plan_id, request.task_id),
        ).fetchone()
        if plan is None:
            return NOT_FOUND
        row = connection.execute(
            'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
            (plan['candidate_id'], request.task_id),
        ).fetchone()
        if row is None or row['content_tree_oid'] != plan['result_tree_oid']:
            raise StorageUnavailable('Original delivery result candidate differs')
        _, candidate = _saved(connection, row)
        stored = stored_target(connection, plan)
        limits, git_limits = capture_package_limits(
            connection, stored.binding.content_profile_version_id, task_id=request.task_id
        )
    compare = (
        request.comparison(plan['candidate_id'])
        if type(request) is PlanFileRequest
        else DiffRequest(request.task_id, plan['candidate_id'], request.page)
    )
    both = type(request) is PlanReadRequest
    before = _Files(compare, 'BEFORE', all_paths=both)
    after = _Files(compare, 'AFTER', all_paths=both)
    try:
        verify_target_package(stored, limits, git_limits, consume_file=before.observe)
    except (OSError, RuntimeError, ValueError):
        return NOT_READY
    failure = _read_after(candidate, after, lambda: False)
    if failure is not None:
        return failure
    return plan, stored, compare, before.files, after.files


def read_delivery_plan(runtime, request):
    selected = _plan_files(runtime, request)
    if type(selected) is dict:
        return selected
    plan, stored, _, before, after = selected
    paths = sorted(before.keys() | after.keys(), key=lambda path: path.encode('utf-8'))
    changes = []
    for path in paths:
        left, right = before.get(path), after.get(path)
        changed = _changed(left, right)
        if changed is not None:
            changes.append(_diff(path, changed, left, right))
    offset = page_offset(request.page)
    return {
        'code': 'READ_OK',
        'details': None,
        'data': {
            **{key: plan[key] for key in PLAN_FIELDS},
            'target_observed_at': stored.observed_at,
            **page_metadata(request.page, len(changes)),
            'items': changes[offset : offset + PAGE_SIZE],
        },
    }


def read_delivery_file(runtime, request):
    selected = _plan_files(runtime, request)
    if type(selected) is dict:
        return selected
    plan, _, compare, before, after = selected
    left, right = before.get(request.path), after.get(request.path)
    if (left is None and right is None) or _changed(left, right) is None:
        return NOT_FOUND
    file = left if request.side == 'BEFORE' else right
    return {
        'code': 'READ_OK',
        'details': None,
        'data': {
            **_chunk(compare, file),
            'side': request.side,
            'exists': file is not None,
            'delivery_plan_id': plan['id'],
        },
    }


class PlanResponse:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(value, request):
        fields = (*PLAN_FIELDS, 'target_observed_at')
        plan = {key: value[key] for key in fields}
        for key in (
            'id',
            'task_id',
            'candidate_id',
            'test_report_id',
            'repository_id',
            'operation_id',
        ):
            strict_integer(plan[key], key)
        if plan['id'] != request.plan_id or plan['task_id'] != request.task_id:
            raise ValueError('Original plan crosses task scope')
        branch_ref(plan['target_branch'])
        format = 'sha1' if len(plan['expected_target_commit']) == 40 else 'sha256'
        for key in ('expected_target_commit', 'target_tree_oid', 'result_tree_oid'):
            git_oid(plan[key], format)
        git_oid(plan['target_manifest_sha256'], 'sha256')
        _time(plan['target_observed_at'], nullable=False)
        _time(plan['created_at'], nullable=False)
        result, pagination = page(
            {key: item for key, item in value.items() if key not in fields},
            _project_diff,
            request.page,
        )
        paths = [item['path'].encode('utf-8') for item in result['items']]
        if paths != sorted(set(paths)):
            raise ValueError('Original plan changes are not ordered')
        return {**plan, 'target_diff_items': result['items']}, pagination


class PlanFileResponse:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(value, request):
        compare = request.comparison(strict_integer(value['candidate_id'], 'candidate_id'))
        return _project_chunk(value, compare, delivery_plan_id=request.plan_id), None


@dataclass(frozen=True)
class DeliveriesRequest:
    task_id: int
    identity: int | None
    page: int
    epoch: str | None

    @classmethod
    def parse(cls, request):
        task = decimal_integer(request.path_params['task_id'], 'task_id')
        worker = getattr(request.app.state, 'walle_repository_registration', None)
        epoch = (
            getattr(worker, 'delivery_epoch', None)
            if getattr(worker, 'delivery_writes_ready', False)
            else None
        )
        if 'delivery_id' in request.path_params:
            request_query(request)
            return cls(
                task, decimal_integer(request.path_params['delivery_id'], 'delivery_id'), 1, epoch
            )
        query = request_query(request, singles=('page',))
        return cls(task, None, decimal_integer(query.get('page', '1'), 'page', MAX_PAGE), epoch)


def _window(connection, row, epoch):
    terminal = row['status'] in ('SUCCEEDED', 'CANCELLED', 'BLOCKED')
    unknown = row['status'] == 'UNKNOWN' or row['git_write_status'] in (
        'MAY_HAVE_BEEN_SENT',
        'UNKNOWN',
    )
    window = None
    if row['current_window_id'] is not None:
        window = connection.execute(
            'SELECT * FROM code_delivery_windows WHERE id=? AND delivery_id=?',
            (row['current_window_id'], row['id']),
        ).fetchone()
        if window is None:
            raise StorageUnavailable('Original delivery window differs')
    state = 'CLOSED' if terminal else 'UNKNOWN' if unknown else 'REQUIRED'
    if not terminal and not unknown and window is not None:
        now = operation_time(None)
        if now >= window['expires_at']:
            state = 'EXPIRED'
        elif (
            epoch is not None
            and epoch == window['controller_epoch_ref']
            and now >= window['confirmed_at']
        ):
            state = 'ACTIVE'
    return {
        'state': state,
        'confirmed_at': None if window is None else window['confirmed_at'],
        'expires_at': None if window is None else window['expires_at'],
    }


def _saved_delivery(connection, row, request):
    from .task_delivery_write import load_original_delivery

    saved = load_original_delivery(connection, row['operation_id'])
    operation, fixed = saved.operation, saved.fixed
    accepted = connection.execute(
        """SELECT * FROM code_acceptances WHERE id=? AND task_id=? AND delivery_plan_id=?""",
        (row['acceptance_id'], request.task_id, row['delivery_plan_id']),
    ).fetchone()
    if (
        accepted is None
        or operation['task_id'] != request.task_id
        or fixed['candidate_id'] != accepted['candidate_id']
        or fixed['test_report_id'] != accepted['test_report_id']
        or fixed['delivery_plan_id'] != accepted['delivery_plan_id']
        or fixed['manual_risk_accepted'] != bool(accepted['manual_risk_accepted'])
    ):
        raise StorageUnavailable('Original delivery acceptance differs')
    return {
        **{key: row[key] for key in DELIVERY_FIELDS},
        'candidate_id': accepted['candidate_id'],
        'test_report_id': accepted['test_report_id'],
        'manual_risk_accepted': bool(accepted['manual_risk_accepted']),
        'delivery_window': _window(connection, row, request.epoch),
    }


def read_deliveries(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        if (
            connection.execute('SELECT 1 FROM code_tasks WHERE id=?', (request.task_id,)).fetchone()
            is None
        ):
            return NOT_FOUND
        if request.identity is not None:
            row = connection.execute(
                'SELECT * FROM code_deliveries WHERE id=? AND task_id=?',
                (request.identity, request.task_id),
            ).fetchone()
            if row is None:
                return NOT_FOUND
            data = _saved_delivery(connection, row, request)
        else:
            total = connection.execute(
                'SELECT count(*) FROM code_deliveries WHERE task_id=?', (request.task_id,)
            ).fetchone()[0]
            rows = connection.execute(
                'SELECT * FROM code_deliveries WHERE task_id=? ORDER BY id LIMIT ? OFFSET ?',
                (request.task_id, PAGE_SIZE, page_offset(request.page)),
            )
            data = {
                **page_metadata(request.page, total),
                'items': [_saved_delivery(connection, row, request) for row in rows],
            }
    return {'code': 'READ_OK', 'details': None, 'data': data}


def project_delivery(value, task):
    row = exact(
        value,
        (
            *DELIVERY_FIELDS,
            'candidate_id',
            'test_report_id',
            'manual_risk_accepted',
            'delivery_window',
        ),
    )
    for key in (
        'id',
        'task_id',
        'acceptance_id',
        'delivery_plan_id',
        'operation_id',
        'candidate_id',
        'test_report_id',
    ):
        strict_integer(row[key], key)
    if row['task_id'] != task:
        raise ValueError('Original delivery crosses task scope')
    status = strict_enum(
        row['status'],
        'status',
        ('PENDING', 'PREPARING', 'WRITING', 'UNKNOWN', 'SUCCEEDED', 'BLOCKED', 'CANCELLED'),
    )
    strict_enum(
        row['git_write_status'],
        'git_write_status',
        (
            'NOT_DISPATCHED',
            'PREPARED',
            'MAY_HAVE_BEEN_SENT',
            'CONFIRMED',
            'ABORTED_UNSENT',
            'UNKNOWN',
        ),
    )
    strict_enum(
        row['postcheck_status'], 'postcheck_status', ('NOT_RUN', 'VERIFIED', 'CONFLICT', 'UNKNOWN')
    )
    for key in ('created_at', 'delivered_at', 'last_reconciled_at'):
        _time(row[key], nullable=key != 'created_at')
    if (row['delivered_at'] is not None) != (status == 'SUCCEEDED'):
        raise ValueError('Delivery state differs from original result')
    strict_boolean(row['manual_risk_accepted'], 'manual_risk_accepted')
    window = exact(row['delivery_window'], ('state', 'confirmed_at', 'expires_at'))
    strict_enum(
        window['state'], 'window.state', ('REQUIRED', 'ACTIVE', 'EXPIRED', 'CLOSED', 'UNKNOWN')
    )
    _time(window['confirmed_at'])
    _time(window['expires_at'])
    if (window['confirmed_at'] is None) != (window['expires_at'] is None):
        raise ValueError('Original delivery window is incomplete')
    return row


class DeliveryResponse:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(value, request):
        if request.identity is None:
            return page(value, lambda row: project_delivery(row, request.task_id), request.page)
        result = project_delivery(value, request.task_id)
        if result['id'] != request.identity:
            raise ValueError('Original delivery identity differs')
        return result, None


@delivery_reads_router.get(PLAN)
async def delivery_plan_http(request: Request):
    return await handle_http(request, PlanReadRequest, PlanResponse, read_delivery_plan)


@delivery_reads_router.get(PLAN + '/file')
async def delivery_file_http(request: Request):
    return await handle_http(request, PlanFileRequest, PlanFileResponse, read_delivery_file)


@delivery_reads_router.get(DELIVERIES)
@delivery_reads_router.get(DELIVERIES + '/{delivery_id}')
async def delivery_read_http(request: Request):
    return await handle_http(request, DeliveriesRequest, DeliveryResponse, read_deliveries)
