"""Read Coding task summaries in their original document scope."""

import re
from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.shared.code_errors import empty_conflict
from backend.app.shared.command_execution import ConfigurationNotReady
from backend.app.shared.http_boundary import handle_http
from backend.app.shared.http_projection import exact, page
from backend.app.shared.pagination import MAX_PAGE, PAGE_SIZE, page_metadata, page_offset
from backend.app.shared.validation import decimal_integer, strict_enum, strict_integer

from .authorizations import project_grant
from .coding_model_ledger import budget_facts
from .coding_model_read import coding_model_read_router
from .coding_model_wait import read_task_waits
from .configuration_identities import require_schema
from .costs import parse_money
from .execution_profile_versions import _project as project_profile
from .initial_task_view import (
    initial_task_view,
    stopping_task_view,
    validate_initial_task,
    validate_stopped_task,
)
from .repository_operations import _time
from .repository_reads import ERRORS
from .task_basis import TaskBasisUnavailable, read_task_basis
from .task_budget import budget_only_versions, budget_write_router
from .task_candidate_content_reads import candidate_content_router
from .task_candidate_reads import candidate_read_router
from .task_capture_quiescence import active_candidate_check
from .task_capture_task_view import (
    captured_task_view,
    project_published_activity,
    validate_captured_task,
)
from .task_check_api import candidate_check_actions, candidate_check_admissions, check_write_router
from .task_configuration_apply import configuration_apply_router
from .task_configuration_progress import pending_configuration
from .task_creation_api import PATH
from .task_defects import DEFECT_STATES, defect_action_reason
from .task_delivery import delivery_action_reasons
from .task_delivery_api import public_delivery_operation
from .task_delivery_view import delivery_task_view, validate_delivery_task_view
from .task_initial_configuration import (
    initial_configuration_view,
    validate_initial_configuration_view,
)
from .task_issue_reads import issue_read_router
from .task_operation_reads import task_operation_router
from .task_permission_response import permission_response_router
from .task_question_handoff import handoff_router
from .task_question_response import active_native_response, question_response_router
from .task_read_query import read_task_query
from .task_records import records_router
from .task_repairs import repair_action_reason, repair_resources_ready
from .task_report_link import link_action_reason, report_link_router, require_current_report_link
from .task_resume import resume_write_router
from .task_resume_view import resume_action_state
from .task_role_chain import RoleChainUnavailable, current_role_chain
from .task_role_handoff import original_role_result_for_reconciliation
from .task_role_reconciliation import (
    active_role_reconciliation,
    delivery_reconcile_source,
    reconciliation_router,
)
from .task_role_view import public_role_operation
from .task_session_replacement import read_session_replacement, replacement_origin
from .task_start_view import (
    START_FAILURE_CODES,
    public_start_operation,
    start_task_view,
    started_task_view,
    validate_preparing_task,
    validate_started_task,
)
from .task_stop import (
    EXECUTION_TABLES,
    _zero_scope,
    is_owned_progress,
    read_stop_progress,
    stop_operation,
)
from .task_stop_view import owned_stop_stages, owned_stop_view, validate_owned_stop_view
from .task_testing_publication import (
    publication_qualification,
    publication_router,
    read_current_publication,
)
from .task_verification_reads import verification_read_router

STATUSES = (
    'PENDING',
    'RUNNING',
    'WAITING',
    'VERIFYING',
    'AWAITING_TESTING',
    'AWAITING_ACCEPTANCE',
    'STOPPING',
    'COMPLETED',
    'TERMINATED',
)
PHASES = (
    'PREPARING',
    'BACKEND',
    'FRONTEND',
    'INTEGRATION',
    'TESTING',
    'ACCEPTANCE',
    'DELIVERY',
    'FINISHED',
)
SUMMARY_FIELDS = (
    'id',
    'document_id',
    'status',
    'phase',
    'state_version',
    'created_at',
    'updated_at',
    'current_candidate_id',
)
task_read_router = APIRouter(redirect_slashes=False)
DETAIL_PATH = '/api/v1/code-tasks/{task_id}'
INITIAL_NULL_FIELDS = (
    'workspace_id',
    'active_session_id',
    'current_candidate_id',
    'current_verification_id',
    'current_test_report_id',
    'current_delivery_plan_id',
    'current_delivery_id',
    'resume_phase',
    'started_at',
    'ended_at',
    'stop_requested_at',
    'stopped_at',
    'last_observed_at',
)


def is_code_task_detail_path(path):
    return (
        re.fullmatch(
            r'/api/v1/code-tasks/[^/]+(?:/configuration|/budget|/resume|/test-reports|/questions(?:/[^/]+/responses)?|/permissions|/(?:candidates|model-calls|operations)(?:/[^/]+)?|/candidates/[^/]+/verifications|/verifications/[^/]+)?',
            path,
        )
        is not None
    )


@dataclass(frozen=True)
class TaskListRequest:
    document_id: int
    page: int
    statuses: tuple[str, ...]
    design_revision_id: int | None

    @classmethod
    def parse(cls, request):
        query = read_task_query(
            request, singles=('page', 'design_revision_id'), arrays={'status': STATUSES}
        )
        revision_id = query.get('design_revision_id')
        return cls(
            decimal_integer(request.path_params['document_id'], 'document_id'),
            decimal_integer(query.get('page', '1'), 'page', MAX_PAGE),
            tuple(query.get('status', ())),
            None if revision_id is None else decimal_integer(revision_id, 'design_revision_id'),
        )


def list_code_tasks(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        document = connection.execute(
            "SELECT requirement_id FROM requirement_documents WHERE id=? AND document_type='CURRENT'",
            (request.document_id,),
        ).fetchone()
        if document is None:
            return {'code': 'NOT_FOUND', 'data': None, 'details': None}
        where = ' WHERE document_id=? AND requirement_id=?'
        bindings = [request.document_id, document['requirement_id']]
        if request.design_revision_id is not None:
            revision = connection.execute(
                'SELECT id FROM revisions WHERE id=? AND document_id=? AND requirement_id=? '
                "AND revision_type='CONTENT'",
                (request.design_revision_id, *bindings),
            ).fetchone()
            if revision is None:
                return {'code': 'NOT_FOUND', 'data': None, 'details': None}
            where += ' AND design_revision_id=?'
            bindings.append(request.design_revision_id)
        if request.statuses:
            where += ' AND status IN (' + ','.join('?' for _ in request.statuses) + ')'
            bindings.extend(request.statuses)
        total = connection.execute('SELECT count(*) FROM code_tasks' + where, bindings).fetchone()[
            0
        ]
        rows = connection.execute(
            'SELECT '
            + ','.join(SUMMARY_FIELDS)
            + ' FROM code_tasks'
            + where
            + ' ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',
            (*bindings, PAGE_SIZE, page_offset(request.page)),
        ).fetchall()
    return {
        'code': 'READ_OK',
        'data': {'items': [dict(row) for row in rows], **page_metadata(request.page, total)},
        'details': None,
    }


def project_task_summary(value):
    row = exact(value, SUMMARY_FIELDS)
    for field in ('id', 'document_id', 'state_version'):
        strict_integer(row[field], field)
    strict_enum(row['status'], 'status', STATUSES)
    strict_enum(row['phase'], 'phase', PHASES)
    for field in ('created_at', 'updated_at'):
        _time(row[field], nullable=False)
    if row['updated_at'] < row['created_at']:
        raise ValueError('Stored task time order is invalid')
    if row['current_candidate_id'] is not None:
        strict_integer(row['current_candidate_id'], 'current_candidate_id')
    return row


class TaskListResponse:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(value, request):
        data, pagination = page(value, project_task_summary, request.page)
        if any(
            row['document_id'] != request.document_id
            or (request.statuses and row['status'] not in request.statuses)
            for row in data['items']
        ):
            raise ValueError('Original task list differs from its filter')
        return data, pagination


@task_read_router.get(PATH)
async def document_code_tasks_http(request: Request):
    return await handle_http(request, TaskListRequest, TaskListResponse, list_code_tasks)


@dataclass(frozen=True)
class TaskDetailRequest:
    task_id: int
    check_admissions: tuple = ()
    native_reconcile_ready: bool = False
    repair_ready: bool = False
    delivery_ready: bool = False
    delivery_write_ready: bool = False
    delivery_cleanup_ready: bool = False
    live_configuration_ready: bool = False

    @classmethod
    def parse(cls, request):
        read_task_query(request)
        return cls(
            decimal_integer(request.path_params['task_id'], 'task_id'),
            candidate_check_admissions(request),
            bool(
                getattr(
                    getattr(request.app.state, 'walle_repository_registration', None),
                    'accepts_native_responses',
                    False,
                )
            ),
            repair_resources_ready(
                getattr(request.app.state, 'walle_repository_registration', None)
            ),
            bool(
                getattr(
                    getattr(request.app.state, 'walle_repository_registration', None),
                    'accepts_delivery_previews',
                    False,
                )
            ),
            bool(
                getattr(
                    getattr(request.app.state, 'walle_repository_registration', None),
                    'delivery_writes_ready',
                    False,
                )
            ),
            bool(
                getattr(
                    getattr(request.app.state, 'walle_repository_registration', None),
                    'delivery_finalization_ready',
                    False,
                )
            ),
            bool(
                getattr(
                    getattr(request.app.state, 'walle_repository_registration', None),
                    'accepts_live_configuration',
                    False,
                )
            ),
        )


def _has_execution_history(connection, task):
    if (
        task['status'] != 'PENDING'
        or task['phase'] != 'PREPARING'
        or task['control_generation'] != 1
        or not budget_only_versions(
            connection, task, task['state_version'], through=task['updated_at']
        )
        or any(task[field] is not None for field in INITIAL_NULL_FIELDS)
    ):
        return True
    # A Coding LLM use belongs to a session, so its evidence is already covered
    # by code_sessions without including Guide or Testing model usage.
    configuration = pending_configuration(connection, task)
    for table in EXECUTION_TABLES:
        if table == 'code_configuration_applications' and configuration is not None:
            continue
        if connection.execute(
            'SELECT 1 FROM ' + table + ' WHERE task_id=? LIMIT 1', (task['id'],)
        ).fetchone():
            return True
    return (
        connection.execute(
            'SELECT 1 FROM code_operations WHERE task_id=? AND id IS NOT ? LIMIT 1',
            (task['id'], None if configuration is None else configuration['id']),
        ).fetchone()
        is not None
    )


def _has_only_staged_start_configuration(connection, task, start):
    from .task_configuration_progress import public_configuration_operation, staged_configuration

    original = staged_configuration(connection, task['id'])
    if original is None:
        return False
    public = public_configuration_operation(connection, original)
    return (
        public['control_generation'] == start['control_generation']
        and public['expected_state_version'] < start['expected_state_version']
        and public['fixed_input']['authorization_id'] == task['authorization_id']
        and public['fixed_input']['execution_profile_version_id']
        == task['execution_profile_version_id']
        and connection.execute(
            'SELECT count(*) FROM code_configuration_applications WHERE task_id=?',
            (task['id'],),
        ).fetchone()[0]
        == 1
    )


def project_saved_task(connection, catalog, task):
    operation = None
    preparing = started = role_transition = None
    if task['status'] in ('STOPPING', 'TERMINATED'):
        operation = stop_operation(connection, task['id'])
        if operation is None:
            raise StorageUnavailable('Current stop has no original operation')
        steps, observed = read_stop_progress(connection, task, operation)
        if is_owned_progress(steps):
            materials, design = read_task_basis(connection, task)
            budget = budget_facts(
                connection, task['id'], parse_money(task['budget_limit_cny'])
            ).public()
            return owned_stop_view(
                task,
                materials,
                design.differences,
                (operation['id'], operation['status']),
                stages=owned_stop_stages(
                    steps, operation['status'], stopped=observed['stop_observation_id'] is not None
                ),
                budget=budget,
                waits=read_task_waits(connection, task['id']),
            )
    if task['status'] in ('PENDING', 'STOPPING'):
        start = connection.execute(
            "SELECT * FROM code_operations WHERE task_id=? AND operation_type='START'",
            (task['id'],),
        ).fetchone()
        if start is not None and task['phase'] == 'PREPARING':
            if start['control_generation'] != task['control_generation'] - (
                task['status'] == 'STOPPING'
            ):
                raise StorageUnavailable('Current preparing task generation differs')
            if any(
                connection.execute(
                    f'SELECT 1 FROM {table} WHERE task_id=? LIMIT 1', (task['id'],)
                ).fetchone()
                for table in EXECUTION_TABLES
                if table not in ('code_workspaces', 'code_instances', 'code_sessions')
                and not (
                    table == 'code_configuration_applications'
                    and _has_only_staged_start_configuration(connection, task, start)
                )
            ):
                raise ConfigurationNotReady('RUNTIME')
            preparing = public_start_operation(connection, start)
            instance = preparing['steps'][3]
            instance_count = connection.execute(
                'SELECT count(*) FROM code_instances WHERE task_id=?', (task['id'],)
            ).fetchone()[0]
            if instance_count != int(instance['status'] in ('RUNNING', 'UNKNOWN', 'SUCCEEDED')):
                raise StorageUnavailable('Current preparing task instance differs')
            session_count = connection.execute(
                'SELECT count(*) FROM code_sessions WHERE task_id=?', (task['id'],)
            ).fetchone()[0]
            if session_count != int(preparing['session_id'] is not None):
                raise StorageUnavailable('Current preparing task session differs')
            result = preparing['steps'][0]['result_ref']
            if task['workspace_id'] != (None if result is None else result['workspace_id']):
                raise StorageUnavailable('Current preparing task workspace differs')
    if task['status'] in (
        'RUNNING',
        'WAITING',
        'VERIFYING',
        'STOPPING',
        'AWAITING_TESTING',
        'AWAITING_ACCEPTANCE',
    ) and task['phase'] in (
        'BACKEND',
        'FRONTEND',
        'INTEGRATION',
        'TESTING',
        'ACCEPTANCE',
    ):
        start = connection.execute(
            "SELECT * FROM code_operations WHERE task_id=? AND operation_type='START' AND status='SUCCEEDED'",
            (task['id'],),
        ).fetchone()
        if start is None:
            raise StorageUnavailable('Original started task has no confirmed START')
        started = public_start_operation(connection, start)
        role_transition = connection.execute(
            """SELECT * FROM code_operations WHERE task_id=?
               AND operation_type='HANDOFF_ROLE' AND status IN ('PENDING','RUNNING','UNKNOWN')""",
            (task['id'],),
        ).fetchone()
        if (
            started['ended_at'] != task['started_at']
            or started['control_generation']
            > task['control_generation'] - (task['status'] == 'STOPPING')
            or started['expected_state_version'] + 3 > task['state_version']
            or started['steps'][0]['result_ref']['workspace_id'] != task['workspace_id']
        ):
            raise StorageUnavailable('Current started task evidence differs')
        pending_replacement = None
        if role_transition is None and task['status'] == 'WAITING':
            replacing = connection.execute(
                "SELECT * FROM code_operations WHERE task_id=? AND operation_type='REPAIR' AND status IN ('RUNNING','UNKNOWN')",
                (task['id'],),
            ).fetchone()
            if replacing is not None:
                replacement = read_session_replacement(connection, replacing, ready=False)
                if replacement is not None and replacement.target['status'] == 'PREPARING':
                    if (replacement.target['id'], replacement.target['control_generation']) != (
                        task['active_session_id'],
                        task['control_generation'],
                    ):
                        raise StorageUnavailable('Current preparing replacement differs')
                    pending_replacement = replacement
        if (
            role_transition is None
            and pending_replacement is None
            and task['phase'] != 'DELIVERY'
            and task['status']
            not in (
                'STOPPING',
                'AWAITING_TESTING',
                'AWAITING_ACCEPTANCE',
                'COMPLETED',
            )
        ):
            try:
                chain = current_role_chain(connection, task)
            except RoleChainUnavailable as error:
                raise StorageUnavailable('Current Coding role is unverified') from error
            if (
                chain.role == 'BACKEND'
                and replacement_origin(connection, task['id'], chain.session_id)
                != started['session_id']
            ):
                raise StorageUnavailable('Current BACKEND session differs')
    if task['status'] in ('STOPPING', 'TERMINATED'):
        if (
            task['status'] == 'STOPPING'
            and preparing is None
            and started is None
            and (
                task['phase'] != 'PREPARING'
                or operation['status'] != 'PENDING'
                or _zero_scope(connection, task, operation) is None
            )
        ):
            raise ConfigurationNotReady('RUNTIME')
        if task['status'] == 'TERMINATED' and observed is None:
            raise StorageUnavailable('Empty-scope terminal stop is unverified')
    elif preparing is None and started is None and _has_execution_history(connection, task):
        raise ConfigurationNotReady('RUNTIME')
    materials, design = read_task_basis(connection, task)
    grant_row = connection.execute(
        'SELECT * FROM code_authorizations WHERE id=?', (task['authorization_id'],)
    ).fetchone()
    profile_row = connection.execute(
        'SELECT * FROM code_execution_profile_versions WHERE id=?',
        (task['execution_profile_version_id'],),
    ).fetchone()
    if grant_row is None or profile_row is None:
        raise StorageUnavailable('Fixed task configuration or approval is missing')
    grant = project_grant(grant_row)
    if (
        grant['task_id'] != task['id']
        or grant['profile_version_id'] != profile_row['id']
        or grant['status']
        not in (
            ('EFFECTIVE',)
            if started
            else ('BOUND_PENDING_APPLY', 'EFFECTIVE')
            if preparing
            else ('BOUND_PENDING_APPLY',)
        )
    ):
        raise StorageUnavailable('Fixed task approval does not match its original binding')
    if preparing is not None:
        return start_task_view(
            task,
            materials,
            design.differences,
            preparing['id'],
            preparing['status'],
            preparing['steps'][0]['status'],
            None if operation is None else (operation['id'], operation['status']),
            failure_code=preparing['failure_code'],
        )
    if started is not None:
        stop = None if operation is None else (operation['id'], operation['status'])
        budget = budget_facts(
            connection, task['id'], parse_money(task['budget_limit_cny'])
        ).public()
        if task['status'] == 'COMPLETED' or (
            task['status'] == 'WAITING' and task['phase'] == 'DELIVERY'
        ):
            return delivery_task_view(connection, task, materials, design.differences, budget)
        if task['status'] in ('AWAITING_TESTING', 'AWAITING_ACCEPTANCE'):
            publication = read_current_publication(connection, task)
            try:
                chain = current_role_chain(connection, {**dict(task), 'phase': 'INTEGRATION'})
            except RoleChainUnavailable as error:
                raise StorageUnavailable('Published Coding role chain differs') from error
            refs = publication['steps'][0]['result_ref']
            if (
                task['phase']
                != ('TESTING' if task['status'] == 'AWAITING_TESTING' else 'ACCEPTANCE')
                or chain.operations
                != (refs['backend_handoff_operation_id'], refs['frontend_handoff_operation_id'])
                or publication['session_id'] != chain.session_id
                or task['current_verification_id'] is None
            ):
                raise StorageUnavailable('Published Coding candidate provenance differs')
            data = started_task_view(task, materials, design.differences, budget=budget)
            data['current_refs']['verification_id'] = task['current_verification_id']
            if task['status'] == 'AWAITING_ACCEPTANCE':
                require_current_report_link(connection, task)
                data['current_refs']['test_report_id'] = task['current_test_report_id']
                data['current_refs']['delivery_plan_id'] = task['current_delivery_plan_id']
                data['current_refs']['delivery_id'] = task['current_delivery_id']
                active_delivery = connection.execute(
                    """SELECT * FROM code_operations WHERE task_id=?
                       AND operation_type IN ('PREPARE_DELIVERY','DELIVER')
                       AND status IN ('PENDING','RUNNING','UNKNOWN') ORDER BY id""",
                    (task['id'],),
                ).fetchall()
                if len(active_delivery) > 1:
                    raise StorageUnavailable('Multiple original Coding delivery actions')
                for original in active_delivery:
                    public_delivery_operation(connection, original)
                    if (original['operation_type'] == 'DELIVER') != (
                        task['current_delivery_id'] is not None
                    ):
                        raise StorageUnavailable('Current Coding delivery operation differs')
                    data['active_operations'] = [
                        {key: original[key] for key in ('id', 'operation_type', 'status')}
                    ]
            project_published_activity(connection, task, data)
            return data
        if role_transition is not None and task['status'] in ('VERIFYING', 'WAITING'):
            public_role_operation(connection, role_transition)
            return started_task_view(
                task,
                materials,
                design.differences,
                budget=budget,
                waits=read_task_waits(connection, task['id']),
                handoff=(
                    role_transition['id'],
                    role_transition['status'],
                    task['current_verification_id'],
                ),
            )
        if task['status'] == 'VERIFYING':
            return captured_task_view(connection, task, materials, design.differences, budget)
        waits = read_task_waits(connection, task['id'])
        answer = None if stop else active_native_response(connection, task['id'])
        data = started_task_view(
            task,
            materials,
            design.differences,
            stop,
            budget=budget,
            waits=waits,
            resume=resume_action_state(connection, task, waits),
            answer=None
            if answer is None
            else (answer['id'], answer['status'], answer['operation_type']),
        )
        if task['status'] == 'RUNNING':
            capture = active_candidate_check(connection, task['id'])
            if capture is not None:
                if data['active_operations'] or capture['operation_type'] != 'CAPTURE_AND_CHECK':
                    raise StorageUnavailable(
                        'Original candidate capture conflicts with active task work'
                    )
                data['active_operations'] = [dict(capture)]
        if task['status'] in ('RUNNING', 'WAITING') and not data['active_operations']:
            repair = connection.execute(
                """SELECT id,operation_type,status FROM code_operations WHERE task_id=?
                   AND operation_type='REPAIR' AND status IN ('PENDING','RUNNING','UNKNOWN')
                   AND (control_generation=? OR EXISTS(
                       SELECT 1 FROM code_operation_steps restore WHERE restore.operation_id=code_operations.id
                           AND restore.step_no=1 AND json_extract(restore.external_identity,'$.replacement.target_generation')=?
                           AND json_extract(restore.external_identity,'$.replacement.target_session_id')=?))""",
                (
                    task['id'],
                    task['control_generation'],
                    task['control_generation'],
                    task['active_session_id'],
                ),
            ).fetchone()
            if repair is not None:
                data['active_operations'] = [dict(repair)]
        return data
    if operation is not None:
        return stopping_task_view(
            task, materials, design.differences, operation['id'], operation['status']
        )
    try:
        profile = project_profile(profile_row, connection, catalog, {})
    except ConfigInvalid as error:
        raise ConfigurationNotReady('Q20-CONFIG') from error
    data = initial_task_view(task, materials, design.differences, profile['ready'])
    data['configuration_application'] = initial_configuration_view(connection, task['id'])
    return data


def read_code_task(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        task = connection.execute(
            'SELECT * FROM code_tasks WHERE id=?', (request.task_id,)
        ).fetchone()
        if task is None:
            return {'code': 'NOT_FOUND', 'data': None, 'details': None}
        try:
            data = project_saved_task(connection, runtime.catalog, task)
            data['configuration_application'] = initial_configuration_view(connection, task['id'])
            from .task_live_configuration import project_live_configuration_activity

            project_live_configuration_activity(
                connection, task, data, request.live_configuration_ready
            )
            if task['status'] in ('RUNNING', 'VERIFYING', 'AWAITING_TESTING') and task['phase'] in (
                'BACKEND',
                'FRONTEND',
                'INTEGRATION',
                'TESTING',
            ):
                _project_candidate_actions(
                    data,
                    candidate_check_actions(
                        connection,
                        runtime.catalog,
                        task,
                        request.check_admissions,
                    ),
                )
            _project_publication_action(
                connection, runtime.catalog, task, data, request.check_admissions
            )
            if task['status'] in ('VERIFYING', 'AWAITING_TESTING', 'AWAITING_ACCEPTANCE'):
                reason = link_action_reason(connection, task)
                for action in data['available_actions']:
                    if action['action'] == 'LINK_TEST_REPORT':
                        action.update(enabled=reason is None, reason_code=reason)
            if task['status'] in DEFECT_STATES:
                reason = defect_action_reason(task)
                repair_reason = repair_action_reason(connection, task, request.repair_ready)
                for action in data['available_actions']:
                    if action['action'] == 'REGISTER_DEFECT':
                        action.update(enabled=reason is None, reason_code=reason)
                    if action['action'] == 'REPAIR':
                        action.update(enabled=repair_reason is None, reason_code=repair_reason)
            if task['status'] == 'AWAITING_ACCEPTANCE':
                preview, accept = delivery_action_reasons(connection, task, request.delivery_ready)
                reasons = {'PREPARE_DELIVERY': preview, 'ACCEPT': accept}
                for action in data['available_actions']:
                    if action['action'] in reasons:
                        reason = reasons[action['action']]
                        action.update(enabled=reason is None, reason_code=reason)
            _project_role_reconcile_action(connection, task, data, request.native_reconcile_ready)
            _project_delivery_reconcile_action(connection, task, data, request.delivery_write_ready)
            _project_delivery_resume_action(
                connection, task, data, request.delivery_write_ready, request.delivery_cleanup_ready
            )
        except TaskBasisUnavailable:
            return {
                'code': 'CONTENT_NOT_READY',
                'data': None,
                'details': {
                    **empty_conflict(),
                    'task_id': task['id'],
                    'related_entity_kind': 'TASK',
                    'related_entity_id': task['id'],
                },
            }
        except ConfigurationNotReady as error:
            return {'code': error.code, 'data': None, 'details': error.details}
    return {'code': 'READ_OK', 'data': data, 'details': None}


_CHECK_ACTIONS = ('CAPTURE_AND_CHECK', 'VERIFY_CANDIDATE')
_CHECK_PURPOSE_REASONS = (
    'TASK_STATE',
    'ROLE_CHAIN_INCOMPLETE',
    'ROLE_CHAIN_UNKNOWN',
    'SESSION_NOT_CURRENT',
    'WRITER_ACTIVE',
    'RESOURCE_NOT_READY',
    'CANDIDATE_NOT_CURRENT',
)
_CHECK_ACTION_REASONS = {
    'TASK_STATE': 'INVALID_STATE',
    'ROLE_CHAIN_INCOMPLETE': 'VERIFICATION_STAGE_NOT_READY',
    'ROLE_CHAIN_UNKNOWN': 'VERIFICATION_STAGE_NOT_READY',
    'SESSION_NOT_CURRENT': 'VERIFICATION_STAGE_NOT_READY',
    'WRITER_ACTIVE': 'WRITER_ACTIVE',
    'RESOURCE_NOT_READY': 'CONFIG_NOT_READY',
    'CANDIDATE_NOT_CURRENT': 'CONTENT_NOT_READY',
    None: None,
}


def _project_role_reconcile_action(connection, task, data, ready):
    original = next(
        (
            row
            for row in data['active_operations']
            if row['operation_type'] in ('HANDOFF_ROLE', 'REPAIR') and row['status'] == 'UNKNOWN'
        ),
        None,
    )
    if original is None or task['status'] != 'WAITING':
        return
    try:
        if original['operation_type'] == 'HANDOFF_ROLE':
            original_role_result_for_reconciliation(connection, original['id'])
        else:
            from .task_repair_runtime import (
                repair_creation_for_reconciliation,
                repair_message_for_reconciliation,
            )

            if (
                repair_message_for_reconciliation(connection, task, original['id']) is None
                and repair_creation_for_reconciliation(connection, task, original['id']) is None
            ):
                return
    except TaskExecutionError:
        return
    pending = active_role_reconciliation(connection, task['id'])
    reason = (
        'OPERATION_IN_PROGRESS' if pending is not None else None if ready else 'CONFIG_NOT_READY'
    )
    for action in data['available_actions']:
        if action['action'] == 'RECONCILE':
            action.update(enabled=reason is None, reason_code=reason, related_id=original['id'])


def _project_delivery_reconcile_action(connection, task, data, ready):
    if task['status'] != 'WAITING' or task['phase'] != 'DELIVERY':
        return
    original = connection.execute(
        """SELECT o.* FROM code_deliveries d JOIN code_operations o ON o.id=d.operation_id
           AND o.task_id=d.task_id WHERE d.id=? AND d.task_id=?""",
        (task['current_delivery_id'], task['id']),
    ).fetchone()
    if original is None or not delivery_reconcile_source(connection, task, original):
        return
    pending = active_role_reconciliation(connection, task['id'])
    reason = (
        'OPERATION_IN_PROGRESS' if pending is not None else None if ready else 'CONFIG_NOT_READY'
    )
    for item in data['available_actions']:
        if item['action'] == 'RECONCILE':
            item.update(enabled=reason is None, reason_code=reason, related_id=original['id'])


def _project_delivery_resume_action(connection, task, data, write_ready, cleanup_ready):
    if task['status'] != 'WAITING' or task['phase'] != 'DELIVERY':
        return
    from .task_delivery_finalize import resumable_finalization
    from .task_delivery_window import renewable_delivery
    from .task_resume import active_resume

    original = next(
        (row for row in data['active_operations'] if row['operation_type'] == 'DELIVER'), None
    )
    if original is None:
        return
    pending = active_resume(connection, task['id'])
    pending_id = None if pending is None else pending['id']
    if renewable_delivery(connection, task, original['id']) is not None:
        ready = write_ready
    elif (
        resumable_finalization(connection, task, original['id'], pending_resume_id=pending_id)
        is not None
    ):
        ready = cleanup_ready
    else:
        return
    reason = (
        'OPERATION_IN_PROGRESS' if pending is not None else None if ready else 'CONFIG_NOT_READY'
    )
    for item in data['available_actions']:
        if item['action'] == 'RESUME':
            item.update(enabled=reason is None, reason_code=reason, related_id=original['id'])


def _without_role_reconcile_projection(data):
    original = next(
        (
            row
            for row in data['active_operations']
            if row['operation_type'] in ('HANDOFF_ROLE', 'REPAIR') and row['status'] == 'UNKNOWN'
        ),
        None,
    )
    if original is None:
        return data
    actions = []
    for action in data['available_actions']:
        if action['action'] != 'RECONCILE' or action['related_id'] is None:
            actions.append(action)
            continue
        if (
            data['status'] != 'WAITING'
            or action['related_id'] != original['id']
            or not any(
                item['kind'] == 'OPERATION_RESULT' and item['source_id'] == original['id']
                for item in data['waiting_items']
            )
            or action['reason_code'] not in (None, 'OPERATION_IN_PROGRESS', 'CONFIG_NOT_READY')
            or action['enabled'] != (action['reason_code'] is None)
        ):
            raise ValueError('Original role reconciliation action differs')
        actions.append(
            {**action, 'enabled': False, 'reason_code': 'INVALID_STATE', 'related_id': None}
        )
    return {**data, 'available_actions': actions}


_PUBLICATION_REASONS = frozenset(
    {
        'INVALID_STATE',
        'TEST_SOURCE_MISMATCH',
        'OPERATION_CONFLICT',
        'VERIFICATION_STAGE_NOT_READY',
        'CONFIG_NOT_READY',
        'CHECK_CONFIGURATION_INVALID',
    }
)


def _project_publication_action(connection, catalog, task, data, admissions):
    if task['status'] != 'VERIFYING':
        return
    candidate = connection.execute(
        'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
        (task['current_candidate_id'], task['id']),
    ).fetchone()
    verification = connection.execute(
        "SELECT * FROM code_verifications WHERE id=? AND task_id=? AND owner_kind='CODING'",
        (task['current_verification_id'], task['id']),
    ).fetchone()
    reason = (
        'VERIFICATION_STAGE_NOT_READY'
        if task['phase'] != 'INTEGRATION'
        else 'CHECK_CONFIGURATION_INVALID'
    )
    if candidate is not None and verification is not None:
        reason, _ = publication_qualification(
            connection, catalog, task, candidate, verification, admissions
        )
    for action in data['available_actions']:
        if action['action'] == 'SUBMIT_FOR_TESTING':
            action.update(enabled=reason is None, reason_code=reason)


def _without_publication_projection(data):
    actions = []
    for action in data['available_actions']:
        if action['action'] != 'SUBMIT_FOR_TESTING' or data['status'] != 'VERIFYING':
            actions.append(action)
            continue
        reason = action['reason_code']
        if (
            action['enabled'] != (reason is None)
            or action['related_id'] is not None
            or reason is not None
            and reason not in _PUBLICATION_REASONS
            or action['enabled']
            and (data['phase'] != 'INTEGRATION' or data['current_refs']['verification_id'] is None)
        ):
            raise ValueError('Original Coding publication action differs')
        actions.append({**action, 'enabled': False, 'reason_code': 'INVALID_STATE'})
    return {**data, 'available_actions': actions}


def _project_candidate_actions(data, reasons):
    for item in data['verification_purposes']:
        reason = reasons[item['action']]
        item.update(enabled=reason is None, reason_code=reason)
    for item in data['available_actions']:
        if item['action'] in reasons:
            reason = _CHECK_ACTION_REASONS[reasons[item['action']]]
            item.update(enabled=reason is None, reason_code=reason)


def _without_candidate_action_projection(data):
    if data['status'] not in ('RUNNING', 'VERIFYING', 'AWAITING_TESTING') or data['phase'] not in (
        'BACKEND',
        'FRONTEND',
        'INTEGRATION',
        'TESTING',
    ):
        return data
    purposes = data['verification_purposes']
    if type(purposes) is not list or tuple(item['action'] for item in purposes) != _CHECK_ACTIONS:
        raise ValueError('Original candidate check purpose list differs')
    mapped = {}
    for item in purposes:
        value = exact(item, ('action', 'purpose', 'enabled', 'reason_code'))
        reason = value['reason_code']
        if (
            value['purpose'] != 'HANDOFF'
            or type(value['enabled']) is not bool
            or value['enabled'] != (reason is None)
            or (reason is not None and reason not in _CHECK_PURPOSE_REASONS)
        ):
            raise ValueError('Original candidate check purpose differs')
        mapped[value['action']] = (value['enabled'], _CHECK_ACTION_REASONS[reason])
    actions = []
    for item in data['available_actions']:
        if item['action'] not in mapped:
            actions.append(item)
            continue
        if (
            (item['enabled'], item['reason_code']) != mapped[item['action']]
            and (item['enabled'], item['reason_code']) != (False, 'INVALID_STATE')
        ) or item['related_id'] is not None:
            raise ValueError('Original candidate check action differs')
        actions.append({**item, 'enabled': False, 'reason_code': 'INVALID_STATE'})
    default = 'RESOURCE_NOT_READY' if data['status'] == 'VERIFYING' else 'TASK_STATE'
    return {
        **data,
        'available_actions': actions,
        'verification_purposes': [
            {**item, 'enabled': False, 'reason_code': default} for item in purposes
        ],
    }


def validate_saved_task_view(data, task_id):
    if data['id'] != task_id:
        raise ValueError('Task detail differs from the requested owner')
    validate_initial_configuration_view(data['configuration_application'])
    from .task_configuration_live_records import without_live_configuration_projection

    data = without_live_configuration_projection(data)
    data = _without_role_reconcile_projection(data)
    actions = []
    for action in data['available_actions']:
        if action['action'] == 'REGISTER_DEFECT' and data['status'] in DEFECT_STATES:
            if (
                action['related_id'] is not None
                or action['reason_code'] not in (None, 'INVALID_STATE', 'CANDIDATE_NOT_CURRENT')
                or action['enabled'] != (action['reason_code'] is None)
                or action['enabled']
                and defect_action_reason(data) is not None
            ):
                raise ValueError('Original Coding defect action differs')
            action = {**action, 'enabled': False, 'reason_code': 'INVALID_STATE'}
        if (
            action['action'] in ('PREPARE_DELIVERY', 'ACCEPT')
            and data['status'] == 'AWAITING_ACCEPTANCE'
        ):
            if (
                action['related_id'] is not None
                or action['reason_code']
                not in (
                    None,
                    'INVALID_STATE',
                    'OPERATION_CONFLICT',
                    'DELIVERY_NOT_AUTHORIZED',
                    'CONFIG_NOT_READY',
                    'DELIVERY_PLAN_STALE',
                )
                or action['enabled'] != (action['reason_code'] is None)
                or action['enabled']
                and data['current_refs']['delivery_id'] is not None
                or action['enabled']
                and action['action'] == 'ACCEPT'
                and data['current_refs']['delivery_plan_id'] is None
            ):
                raise ValueError('Original Coding delivery action differs')
            action = {**action, 'enabled': False, 'reason_code': 'INVALID_STATE'}
        if action['action'] == 'REPAIR' and data['status'] in DEFECT_STATES:
            if (
                action['related_id'] is not None
                or action['reason_code']
                not in (
                    None,
                    'INVALID_STATE',
                    'CANDIDATE_NOT_CURRENT',
                    'OPERATION_CONFLICT',
                    'EXTERNAL_RESULT_UNKNOWN',
                    'EXECUTION_NOT_STOPPED',
                    'CONFIG_NOT_READY',
                )
                or action['enabled'] != (action['reason_code'] is None)
                or action['enabled']
                and data['current_candidate_id'] is None
            ):
                raise ValueError('Original Coding repair action differs')
            action = {**action, 'enabled': False, 'reason_code': 'INVALID_STATE'}
        if action['action'] == 'LINK_TEST_REPORT' and data['status'] in (
            'VERIFYING',
            'AWAITING_TESTING',
            'AWAITING_ACCEPTANCE',
        ):
            if (
                action['related_id'] is not None
                or action['reason_code']
                not in (None, 'INVALID_STATE', 'TEST_SOURCE_MISMATCH', 'OPERATION_CONFLICT')
                or action['enabled'] != (action['reason_code'] is None)
                or action['enabled']
                and data['current_candidate_id'] is None
            ):
                raise ValueError('Original Coding report link action differs')
            action = {**action, 'enabled': False, 'reason_code': 'INVALID_STATE'}
        actions.append(action)
    data = {**data, 'available_actions': actions}
    data = _without_candidate_action_projection(
        _without_publication_projection({**data, 'configuration_application': None})
    )
    if any(
        operation['operation_type'] == 'START' for operation in data['active_operations']
    ) or any(
        action['action'] == 'START'
        and action['reason_code'] in START_FAILURE_CODES
        and action['related_id'] is not None
        for action in data['available_actions']
    ):
        validate_preparing_task(data, task_id)
    elif data['status'] == 'PENDING':
        validate_initial_task(data, data['document_id'], require_new=False)
    elif data['status'] in ('STOPPING', 'TERMINATED') and data['workspace_id'] is not None:
        validate_owned_stop_view(data, task_id)
    elif data['status'] == 'COMPLETED' or (
        data['status'] == 'WAITING' and data['phase'] == 'DELIVERY'
    ):
        validate_delivery_task_view(data, task_id)
    elif data['status'] in ('AWAITING_TESTING', 'AWAITING_ACCEPTANCE'):
        linked = data['status'] == 'AWAITING_ACCEPTANCE'
        if linked:
            strict_integer(data['current_refs']['test_report_id'], 'test_report_id')
            plan_id = data['current_refs']['delivery_plan_id']
            delivery_id = data['current_refs']['delivery_id']
            if plan_id is not None:
                strict_integer(plan_id, 'delivery_plan_id')
            if delivery_id is not None:
                strict_integer(delivery_id, 'delivery_id')
                if plan_id is None:
                    raise ValueError('Original Coding delivery has no plan')
        elif data['current_refs']['test_report_id'] is not None:
            raise ValueError('Unlinked Coding task has a report')
        strict_integer(data['current_candidate_id'], 'candidate_id')
        strict_integer(data['current_refs']['verification_id'], 'verification_id')
        active = data['active_operations']
        if len(active) > 1 or (active and not linked):
            raise ValueError('Original Coding delivery activity differs')
        for operation in active:
            original = exact(operation, ('id', 'operation_type', 'status'))
            strict_integer(original['id'], 'operation_id')
            strict_enum(original['status'], 'operation_status', ('PENDING', 'RUNNING', 'UNKNOWN'))
            if original['operation_type'] != (
                'DELIVER' if delivery_id is not None else 'PREPARE_DELIVERY'
            ):
                raise ValueError('Original Coding delivery operation differs')
        runtime = data['runtime']
        quiet = runtime['activity_status'] == 'QUIESCENT'
        if quiet:
            strict_integer(runtime['active_process_count'], 'active_process_count', minimum=0)
            _time(runtime['observed_at'], nullable=False)
        if (
            data['phase'] != ('ACCEPTANCE' if linked else 'TESTING')
            or (
                quiet
                and (
                    active
                    or not data['started_at'] <= runtime['observed_at'] <= data['last_observed_at']
                )
            )
            or (
                not quiet
                and (
                    runtime['activity_status'] != 'UNKNOWN'
                    or runtime['active_process_count'] is not None
                    or runtime['observed_at'] is not None
                )
            )
        ):
            raise ValueError('Published Coding task state differs')
        validate_started_task(
            {
                **data,
                'status': 'RUNNING',
                'phase': 'INTEGRATION',
                'active_operations': [],
                'current_refs': {
                    **data['current_refs'],
                    'verification_id': None,
                    'test_report_id': None,
                    'delivery_plan_id': None,
                    'delivery_id': None,
                },
                'runtime': {
                    **data['runtime'],
                    'activity_status': 'UNKNOWN',
                    'active_process_count': None,
                    'observed_at': data['last_observed_at'],
                },
            },
            task_id,
        )
    elif any(row['operation_type'] == 'HANDOFF_ROLE' for row in data['active_operations']):
        validate_started_task(data, task_id)
    elif data['status'] == 'VERIFYING':
        validate_captured_task(data, task_id)
    elif data['phase'] in ('BACKEND', 'FRONTEND', 'INTEGRATION'):
        active = data['active_operations']
        if len(active) == 1 and (
            (data['status'] == 'RUNNING' and active[0]['operation_type'] == 'CAPTURE_AND_CHECK')
            or (
                data['status'] in ('RUNNING', 'WAITING') and active[0]['operation_type'] == 'REPAIR'
            )
        ):
            capture = exact(active[0], ('id', 'operation_type', 'status'))
            strict_integer(capture['id'], 'operation_id')
            strict_enum(capture['status'], 'operation_status', ('PENDING', 'RUNNING', 'UNKNOWN'))
            data = {**data, 'active_operations': []}
        validate_started_task(data, task_id)
    else:
        validate_stopped_task(data, task_id, terminal=data['status'] == 'TERMINATED')


class TaskDetailResponse:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(data, request):
        validate_saved_task_view(data, request.task_id)
        return data, None


@task_read_router.get(DETAIL_PATH)
async def code_task_detail_http(request: Request):
    return await handle_http(request, TaskDetailRequest, TaskDetailResponse, read_code_task)


task_read_router.include_router(coding_model_read_router)
task_read_router.include_router(budget_write_router)
task_read_router.include_router(configuration_apply_router)
task_read_router.include_router(resume_write_router)
task_read_router.include_router(task_operation_router)
task_read_router.include_router(issue_read_router)
task_read_router.include_router(records_router)

task_read_router.include_router(question_response_router)
task_read_router.include_router(permission_response_router)
task_read_router.include_router(handoff_router)
task_read_router.include_router(candidate_read_router)
task_read_router.include_router(candidate_content_router)
task_read_router.include_router(verification_read_router)
task_read_router.include_router(check_write_router)
task_read_router.include_router(publication_router)
task_read_router.include_router(report_link_router)
task_read_router.include_router(reconciliation_router)
