"""Prepare Coding HANDOFF checks from a fixed candidate and admitted CheckSet."""

from dataclasses import dataclass, field

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.shared.http_boundary import HTTP_REQUEST_BYTES
from backend.app.shared.validation import strict_json_loads, strict_json_object

from .authorizations import project_grant
from .check_set_content import STAGES, CheckSetContent, parse_check_set_content
from .check_set_versions import _find, resource_check, resource_snapshot
from .execution_profile_content import commands
from .task_basis import read_task_basis
from .task_role_chain import RoleChain, RoleChainUnavailable, current_role_chain

CODING_STAGES = STAGES[:3]


class CodingCheckPlanError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class CodingCheckPlan:
    task_id: int
    candidate_id: int
    profile_version_id: int
    check_set_version_id: int
    scope_stages: tuple[str, ...]
    selected_check_ids: tuple[str, ...]
    check_set_sha256: str
    _selection_json: str = field(repr=False)
    role_chain: RoleChain

    def selection(self):
        return strict_json_object(self._selection_json)


def select_handoff_checks(content, stages):
    if (
        type(content) is not CheckSetContent
        or content.owner_module != 'CODING'
        or type(stages) is not tuple
        or not stages
        or stages != CODING_STAGES[: len(stages)]
    ):
        raise CodingCheckPlanError('VERIFICATION_STAGE_NOT_READY')
    source = content.value()
    selected = [
        item for item in source['items'] if any(stage in item['stages'] for stage in stages)
    ]
    for stage in stages:
        if not any(
            item['required']
            and stage in item['stages']
            and item['evidence_rule']['kind'] == 'CONTENT_INTEGRITY'
            for item in selected
        ):
            raise CodingCheckPlanError('CHECK_CONFIGURATION_INVALID')
    coverage = []
    for item in source['coverage_plan']:
        applicable = [stage for stage in stages if stage in item['stages']]
        if not applicable:
            continue
        if item['mode'] == 'AUTO' and not all(
            any(
                check['check_id'] in item['check_ids'] and stage in check['stages']
                for check in selected
            )
            for stage in applicable
        ):
            raise CodingCheckPlanError('CHECK_CONFIGURATION_INVALID')
        coverage.append(item)
    return {
        'protocol_version': source['protocol_version'],
        'items': selected,
        'coverage_plan': coverage,
    }


def _check_basis(connection, task, selection):
    materials, _ = read_task_basis(connection, task)
    fixed = {(task['document_id'], task['design_revision_id'])}
    fixed.update((item['document_id'], item['revision_id']) for item in materials)
    for item in selection['coverage_plan']:
        for ref in item['basis_refs']:
            pair = (ref['document_id'], ref['revision_id'])
            if pair not in fixed:
                raise CodingCheckPlanError('CHECK_CONFIGURATION_INVALID')
            version = connection.execute(
                """SELECT markdown_snapshot FROM revisions WHERE document_id=? AND id=?
                   AND requirement_id=? AND revision_type='CONTENT'""",
                (*pair, task['requirement_id']),
            ).fetchone()
            if version is None or ref['quote'] not in version['markdown_snapshot']:
                raise CodingCheckPlanError('CHECK_CONFIGURATION_INVALID')


def require_handoff_command_scope(selection, fixed_commands, scope, snapshot):
    """A published CheckSet cannot add command or network authority to a task."""
    declared = {item['command_id']: item for item in fixed_commands}
    required = set()
    for item in selection['items']:
        if item['command_id'] is not None:
            required.add(item['command_id'])
        if item['target'] is not None:
            required.update(item['target']['command_ids'])
    if not required.issubset(scope['allowed_command_ids']):
        raise CodingCheckPlanError('AUTHORIZATION_NOT_APPLICABLE')
    for command_id in sorted(required):
        command = declared.get(command_id)
        resource = _find(snapshot, 'COMMAND', 'command_id', command_id)
        if command is None or resource is None or resource['value'] != command:
            raise CodingCheckPlanError('CHECK_CONFIGURATION_INVALID')
        network = command['network_scope_ref']
        if network is not None and network not in scope['network_targets']:
            raise CodingCheckPlanError('AUTHORIZATION_NOT_APPLICABLE')


def read_profile_check_basis(connection, task, profile, stages):
    """Read immutable selection/basis without claiming a proposed grant is effective."""
    version = connection.execute(
        "SELECT * FROM code_check_set_versions WHERE id=? AND owner_module='CODING'",
        (profile['check_set_version_id'],),
    ).fetchone()
    if version is None:
        raise StorageUnavailable('Original Coding CheckSet is missing')
    content = parse_check_set_content(
        {
            'protocol_version': version['protocol_version'],
            'items': strict_json_loads(version['items']),
            'coverage_plan': strict_json_loads(version['coverage_plan']),
        },
        owner_module='CODING',
        max_input_bytes=HTTP_REQUEST_BYTES,
    )
    selected = select_handoff_checks(content, stages)
    _check_basis(connection, task, selected)
    return version, content, selected


def validate_profile_check_selection(connection, catalog, task, profile, stages, scope):
    """Share actual resource/scope rules; callers prove their own grant lifecycle."""
    version, content, selected = read_profile_check_basis(connection, task, profile, stages)
    snapshot = resource_snapshot(catalog, selected['items'])
    missing, ready = resource_check(selected, snapshot)
    if missing is not None or not ready:
        raise CodingCheckPlanError('CHECK_CONFIGURATION_INVALID')
    fixed = commands(strict_json_loads(profile['commands']), HTTP_REQUEST_BYTES)
    require_handoff_command_scope(selected, fixed, scope, snapshot)
    return version, content, selected, fixed


def read_coding_check_selection(connection, catalog, task):
    """Resolve the current proven role prefix and EFFECTIVE grant before capture."""
    try:
        chain = current_role_chain(connection, task)
    except RoleChainUnavailable as error:
        raise CodingCheckPlanError('VERIFICATION_STAGE_NOT_READY') from error
    if task['stop_requested_at'] is not None or task['status'] not in ('RUNNING', 'VERIFYING'):
        raise CodingCheckPlanError('VERIFICATION_STAGE_NOT_READY')
    profile = connection.execute(
        'SELECT check_set_version_id,commands FROM code_execution_profile_versions WHERE id=?',
        (task['execution_profile_version_id'],),
    ).fetchone()
    if profile is None:
        raise StorageUnavailable('Original Coding check profile is missing')
    grant = connection.execute(
        """SELECT * FROM code_authorizations WHERE id=? AND task_id=?
           AND profile_version_id=? AND status='EFFECTIVE'""",
        (task['authorization_id'], task['id'], task['execution_profile_version_id']),
    ).fetchone()
    if grant is None:
        raise CodingCheckPlanError('AUTHORIZATION_NOT_APPLICABLE')
    version, content, selected, fixed = validate_profile_check_selection(
        connection, catalog, task, profile, chain.stages, project_grant(grant)['scope']
    )
    return version['id'], content.sha256, selected, fixed, chain


def read_coding_handoff_plan(connection, catalog, task_id, candidate_id, *, comparison_task=None):
    task = comparison_task
    if task is None:
        task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
    candidate = connection.execute(
        'SELECT role,control_generation FROM code_candidates WHERE id=? AND task_id=?',
        (candidate_id, task_id),
    ).fetchone()
    if (
        task is None
        or task['id'] != task_id
        or task['current_candidate_id'] != candidate_id
        or task['status'] != 'VERIFYING'
        or candidate is None
        or candidate['role'] != task['phase']
        or candidate['control_generation'] != task['control_generation']
    ):
        raise CodingCheckPlanError('VERIFICATION_STAGE_NOT_READY')
    version_id, check_set_sha256, selected, _, chain = read_coding_check_selection(
        connection, catalog, task
    )
    return CodingCheckPlan(
        task['id'],
        candidate_id,
        task['execution_profile_version_id'],
        version_id,
        chain.stages,
        tuple(item['check_id'] for item in selected['items']),
        check_set_sha256,
        canonical_input(selected),
        chain,
    )
