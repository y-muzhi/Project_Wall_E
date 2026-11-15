"""Persist the original Coding verification and its serial offline checks."""

from dataclasses import asdict, dataclass
from hashlib import sha256
from json import dumps

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.guard_controller_binding import owner_epoch as require_owner_epoch
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import (
    EntityKind,
    entity_id,
    increment,
    require_write_transaction,
)
from backend.app.infrastructure.project_check_result import (
    ProjectCheckDispatchResult,
    ProjectCheckEvidenceUnknown,
    ProjectCheckUndispatched,
    project_process_facts,
)
from backend.app.infrastructure.runtime_launch_journal import LaunchScope
from backend.app.infrastructure.windows_task_directories import ProjectCheckInput
from backend.app.shared.validation import strict_integer, strict_json_loads, strict_json_object

from .authorizations import project_grant
from .coding_check_plan import CodingCheckPlan, CodingCheckPlanError
from .coding_project_check_scope import (
    CodingProjectCheckClaim,
    ProjectCommandSelection,
    check_claims,
    encode_check_claims,
    require_project_check_admissions,
)
from .task_candidate_commit import load_candidate_capture
from .task_initial_configuration import current_effective_configuration
from .task_records import record_project_output
from .task_start_session import original_active_session_scope
from .task_verify_candidate import TYPE as VERIFY_TYPE
from .task_verify_candidate import load_candidate_verification


@dataclass(frozen=True)
class CheckOperationOrigin:
    role: str
    current_version: int
    generation: int
    profile_version_id: int
    session_id: int
    restore: object = None


def _original(connection, operation_id):
    row = connection.execute('SELECT * FROM code_operations WHERE id=?', (operation_id,)).fetchone()
    if row is not None and row['operation_type'] == VERIFY_TYPE:
        task, candidate, steps = load_candidate_verification(connection, row)
        conditions, restore, check = steps
        profile_id = task['execution_profile_version_id']
        if conditions['status'] == 'SUCCEEDED':
            fixed = strict_json_object(conditions['result_ref'])
            if fixed['candidate_id'] != candidate['id']:
                raise StorageUnavailable('Original check condition target differs')
            profile_id = strict_integer(fixed['profile_version_id'], 'profile_version_id')
        origin = CheckOperationOrigin(
            candidate['role'],
            increment(row['expected_state_version']),
            row['control_generation'],
            profile_id,
            row['session_id'],
            restore,
        )
        return (
            origin,
            task,
            row,
            check,
            {
                'candidate_id': candidate['id'],
                'manifest_sha256': candidate['manifest_sha256'],
            },
        )

    prepared, task, operation, steps = load_candidate_capture(connection, operation_id)
    published = steps[2]
    if (
        tuple(step['status'] for step in steps[:3]) != ('SUCCEEDED',) * 3
        or published['result_ref'] is None
    ):
        raise CodingCheckPlanError('VERIFICATION_STAGE_NOT_READY')
    origin = CheckOperationOrigin(
        prepared.role,
        increment(prepared.state_version),
        prepared.binding.control_generation,
        prepared.binding.content_profile_version_id,
        prepared.session_id,
    )
    return origin, task, operation, steps[3], strict_json_object(published['result_ref'])


def _current(origin, task, operation, candidate):
    return (
        operation['status'] in ('PENDING', 'RUNNING', 'UNKNOWN')
        and task['status'] == 'VERIFYING'
        and task['phase'] == origin.role
        and task['state_version'] == origin.current_version
        and task['control_generation'] == origin.generation
        and task['stop_requested_at'] is None
        and task['active_session_id'] == origin.session_id
        and task['execution_profile_version_id'] == origin.profile_version_id
        and task['current_candidate_id'] == candidate['candidate_id']
    )


def prepare_coding_project_check(
    connection, scopes, plan, selected, *, owner_epoch, max_output_bytes, at
):
    """One transaction allocates original environment, verification, items and command."""
    require_write_transaction(connection)
    if (
        type(scopes) is not tuple
        or not scopes
        or any(type(scope) is not LaunchScope for scope in scopes)
        or len(scopes) != len(set(scopes))
        or type(plan) is not CodingCheckPlan
        or type(selected) is not tuple
        or len(selected) != len(scopes)
        or any(type(row) is not ProjectCommandSelection for row in selected)
    ):
        raise CodingCheckPlanError('VERIFICATION_STAGE_NOT_READY')
    scope = scopes[0]
    if scope.step_no not in (3, 4) or any(
        (part.controller_ref, part.operation_id, part.step_no)
        != (scope.controller_ref, scope.operation_id, scope.step_no)
        for part in scopes
    ):
        raise CodingCheckPlanError('VERIFICATION_STAGE_NOT_READY')
    require_owner_epoch(owner_epoch)
    strict_integer(max_output_bytes, 'max_output_bytes')
    prepared, task, operation, check_step, candidate = _original(connection, scope.operation_id)
    if (
        not _current(prepared, task, operation, candidate)
        or scope.step_no != check_step['step_no']
        or operation['status'] != ('RUNNING' if prepared.restore is None else 'PENDING')
        or (prepared.restore is not None and prepared.restore['status'] != 'PENDING')
        or task['current_verification_id'] is not None
        or check_step['status'] != 'PENDING'
        or check_step['external_identity'] is not None
        or (
            plan.task_id,
            plan.candidate_id,
            plan.profile_version_id,
            plan.role_chain.role,
            plan.role_chain.session_id,
        )
        != (
            task['id'],
            candidate['candidate_id'],
            task['execution_profile_version_id'],
            prepared.role,
            prepared.session_id,
        )
        or connection.execute(
            "SELECT 1 FROM code_commands WHERE task_id=? AND status IN ('PENDING','RUNNING','UNKNOWN')",
            (task['id'],),
        ).fetchone()
        is not None
    ):
        raise CodingCheckPlanError('VERIFICATION_STAGE_NOT_READY')
    fixed = plan.selection()
    items = fixed['items']
    integrity = [item for item in items if item['evidence_rule']['kind'] == 'CONTENT_INTEGRITY']
    profile = connection.execute(
        'SELECT commands,check_set_version_id,limits FROM code_execution_profile_versions WHERE id=?',
        (plan.profile_version_id,),
    ).fetchone()
    if profile is None or profile['check_set_version_id'] != plan.check_set_version_id:
        raise CodingCheckPlanError('CHECK_CONFIGURATION_INVALID')
    admissions = tuple(dict.fromkeys(row.admission for row in selected))
    if (
        require_project_check_admissions(
            fixed, admissions, definitions=strict_json_loads(profile['commands'])
        )
        != selected
    ):
        raise CodingCheckPlanError('CHECK_CONFIGURATION_INVALID')
    grant = connection.execute(
        """SELECT * FROM code_authorizations WHERE id=? AND task_id=?
           AND profile_version_id=? AND status='EFFECTIVE'""",
        (task['authorization_id'], task['id'], plan.profile_version_id),
    ).fetchone()
    if grant is None:
        raise CodingCheckPlanError('AUTHORIZATION_NOT_APPLICABLE')
    authorization = project_grant(grant)['scope']
    limits = strict_json_object(profile['limits'])
    if any(
        row.admission.command.command_id not in authorization['allowed_command_ids']
        for row in selected
    ) or max_output_bytes != min(
        limits['max_check_output_bytes'], authorization['limits']['max_check_output_bytes']
    ):
        raise CodingCheckPlanError('AUTHORIZATION_NOT_APPLICABLE')
    session = connection.execute(
        'SELECT * FROM code_sessions WHERE id=? AND task_id=?',
        (task['active_session_id'], task['id']),
    ).fetchone()
    if session is None:
        raise CodingCheckPlanError('VERIFICATION_STAGE_NOT_READY')
    start_scope = original_active_session_scope(connection, task, session)
    configuration = current_effective_configuration(connection, task, start_scope=start_scope)
    if configuration is None:
        raise CodingCheckPlanError('ENVIRONMENT_MISMATCH')
    environment = entity_id(connection, EntityKind.ENVIRONMENT_RECORD)
    verification = entity_id(connection, EntityKind.VERIFICATION)
    identities = {
        item['check_id']: entity_id(connection, EntityKind.VERIFICATION_ITEM) for item in items
    }
    claims = tuple(
        CodingProjectCheckClaim(
            child,
            ProjectCheckInput(
                'CODING',
                task['id'],
                task['control_generation'],
                verification,
                identities[row.check_id],
                plan.candidate_id,
                candidate['manifest_sha256'],
            ),
            entity_id(connection, EntityKind.COMMAND_EXECUTION),
            tuple(identities[item['check_id']] for item in integrity),
            prepared.session_id,
            task['state_version'],
            plan.profile_version_id,
            row.admission.runner_manifest_sha256,
            owner_epoch,
            max_output_bytes,
        )
        for child, row in zip(scopes, selected, strict=True)
    )
    claim = claims[0]
    by_item = {part.check.item_id: part for part in claims}
    restoring = prepared.restore is not None
    initial_status = 'PENDING' if restoring else 'RUNNING'
    initial_started = None if restoring else at
    runners = list(dict.fromkeys(row.admission.runner_ref for row in selected))
    runtime = list(dict.fromkeys(ref for row in selected for ref in row.admission.runtime_refs))
    resources = list(
        dict.fromkeys(
            row.admission.runner_ref + ':sha256:' + row.admission.runner_manifest_sha256
            for row in selected
        )
    )
    scope_key = sha256(
        canonical_input(
            {
                'candidate_manifest': candidate['manifest_sha256'],
                'profile_version_id': plan.profile_version_id,
                'check_set_version_id': plan.check_set_version_id,
                'purpose': 'HANDOFF',
                'stages': list(plan.scope_stages),
                'selection': fixed,
                'commands': [
                    {
                        'check_id': row.check_id,
                        'definition_sha256': row.admission.command.definition_sha256,
                    }
                    for row in selected
                ],
                'runners': resources,
                'runtime': runtime,
                'effective_configuration': configuration['id'],
                'authorization': authorization,
            }
        ).encode()
    ).hexdigest()
    connection.execute(
        """INSERT INTO code_environment_records(
               id,task_id,runtime_refs,dependency_refs,runner_refs,effective_config_application_id,
               check_resource_refs,scope_key,observed_at)
           VALUES(?,?,?,'[]',?,?,?,?,?)""",
        (
            environment,
            task['id'],
            dumps(runtime, ensure_ascii=False, separators=(',', ':')),
            dumps(runners, ensure_ascii=False, separators=(',', ':')),
            configuration['id'],
            dumps(resources, ensure_ascii=False, separators=(',', ':')),
            scope_key,
            at,
        ),
    )
    connection.execute(
        """INSERT INTO code_verifications(
               id,task_id,owner_kind,candidate_id,purpose,role,check_set_version_id,profile_version_id,
               environment_record_id,operation_id,scope_stages,selected_check_ids,status,stop_status,
               cleanup_status,source_integrity_status,created_at,backend_handoff_operation_id,frontend_handoff_operation_id)
           VALUES(?,?,'CODING',?,'HANDOFF',?,?,?,?,?,?,?,?,?,
                  'NOT_STARTED','NOT_CHECKED',?,?,?)""",
        (
            verification,
            task['id'],
            plan.candidate_id,
            plan.role_chain.role,
            plan.check_set_version_id,
            plan.profile_version_id,
            environment,
            scope.operation_id,
            dumps(plan.scope_stages, ensure_ascii=False, separators=(',', ':')),
            dumps(plan.selected_check_ids, ensure_ascii=False, separators=(',', ':')),
            initial_status,
            'NOT_STARTED' if restoring else 'ACTIVE',
            at,
            plan.role_chain.backend_handoff,
            plan.role_chain.frontend_handoff,
        ),
    )
    for item in items:
        project = by_item.get(identities[item['check_id']])
        running = project == claim and not restoring
        connection.execute(
            """INSERT INTO code_verification_items(
                   id,verification_id,check_id,required,check_kind,evidence_kind,command_execution_id,
                   result,started_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                identities[item['check_id']],
                verification,
                item['check_id'],
                item['required'],
                item['check_kind'],
                item['evidence_rule']['kind'],
                None if project is None else project.command_execution_id,
                'RUNNING' if running else 'NOT_RUN',
                at if running else None,
            ),
        )
    for part, row in zip(claims, selected, strict=True):
        running = part == claim and not restoring
        connection.execute(
            """INSERT INTO code_commands(id,task_id,operation_id,purpose,command_ref,config_version_id,
               status,created_at,session_id,verification_item_id,started_at)
               VALUES(?,?,?,'CHECK',?,?,?,?,?,?,?)""",
            (
                part.command_execution_id,
                task['id'],
                scope.operation_id,
                row.admission.command.command_id,
                plan.profile_version_id,
                'RUNNING' if running else 'PENDING',
                at,
                prepared.session_id,
                part.check.item_id,
                at if running else None,
            ),
        )
    if restoring:
        _start_verify_restore(connection, claim, at)
    connection.execute(
        """UPDATE code_operation_steps SET status=?,started_at=?,last_observed_at=?,
               external_identity=? WHERE operation_id=? AND step_no=?""",
        (
            initial_status,
            initial_started,
            initial_started,
            encode_check_claims(claims),
            scope.operation_id,
            scope.step_no,
        ),
    )
    connection.execute(
        'UPDATE code_tasks SET current_verification_id=?,updated_at=? WHERE id=?',
        (verification, at, task['id']),
    )
    return claim


def _start_verify_restore(connection, claim, at):
    checked = connection.execute(
        """UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,started_at=?,
           ended_at=?,last_observed_at=? WHERE operation_id=? AND step_no=1 AND status='PENDING' """,
        (
            canonical_input(
                {
                    'candidate_id': claim.check.candidate_id,
                    'profile_version_id': claim.profile_version_id,
                }
            ),
            at,
            at,
            at,
            claim.scope.operation_id,
        ),
    )
    if checked.rowcount != 1:
        raise StorageUnavailable('Original fixed-candidate conditions were already checked')
    connection.execute(
        """UPDATE code_operation_steps SET status='RUNNING',started_at=?,last_observed_at=?
           WHERE operation_id=? AND step_no=2 AND status='PENDING' """,
        (at, at, claim.scope.operation_id),
    )
    connection.execute(
        "UPDATE code_operations SET status='RUNNING',started_at=? WHERE id=? AND status='PENDING'",
        (at, claim.scope.operation_id),
    )


def accept_restored_check_copy(connection, claim, descriptor, *, at):
    from backend.app.infrastructure.check_input_transfer import CheckInputReadDescriptor

    require_write_transaction(connection)
    origin, task, operation, step, candidate = _original(connection, claim.scope.operation_id)
    if (
        origin.restore is None
        or origin.restore['status'] != 'RUNNING'
        or not _current(origin, task, operation, candidate)
        or task['current_verification_id'] != claim.check.verification_id
        or step['status'] != 'PENDING'
        or claim not in check_claims(step['external_identity'])
        or type(descriptor) is not CheckInputReadDescriptor
        or descriptor.scope != claim.scope
    ):
        raise StorageUnavailable('Original fixed-candidate copy is fenced')
    result = canonical_input(
        {
            'candidate_id': claim.check.candidate_id,
            'manifest_sha256': claim.check.manifest_sha256,
            'capsule_sha256': descriptor.sha256,
            'byte_count': descriptor.byte_count,
        }
    )
    connection.execute(
        """UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,ended_at=?,last_observed_at=?
           WHERE operation_id=? AND step_no=2 """,
        (result, at, at, claim.scope.operation_id),
    )
    connection.execute(
        """UPDATE code_operation_steps SET status='RUNNING',started_at=?,last_observed_at=?
           WHERE operation_id=? AND step_no=3 """,
        (at, at, claim.scope.operation_id),
    )
    connection.execute(
        "UPDATE code_verifications SET status='RUNNING',stop_status='ACTIVE' WHERE id=? AND status='PENDING'",
        (claim.check.verification_id,),
    )
    connection.execute(
        "UPDATE code_commands SET status='RUNNING',started_at=? WHERE id=? AND status='PENDING'",
        (at, claim.command_execution_id),
    )
    connection.execute(
        "UPDATE code_verification_items SET result='RUNNING',started_at=? WHERE id=? AND result='NOT_RUN'",
        (at, claim.check.item_id),
    )


def _stored_check_group(connection, prepared, task, step, candidate):
    claims = check_claims(step['external_identity'])
    first = claims[0]
    commands = connection.execute(
        """SELECT c.*,i.check_id,i.result AS item_result,i.reason_code,i.evidence_summary,i.ended_at AS item_ended_at
           FROM code_commands c JOIN code_verification_items i ON i.id=c.verification_item_id
           JOIN code_verifications v ON v.id=i.verification_id AND v.operation_id=c.operation_id
           WHERE c.operation_id=? AND c.task_id=? AND c.session_id=? AND c.purpose='CHECK'
             AND v.id=? AND v.task_id=c.task_id AND v.owner_kind='CODING' AND v.candidate_id=?
             AND v.profile_version_id=? AND i.evidence_kind='PROCESS_EXIT' ORDER BY c.id""",
        (
            step['operation_id'],
            task['id'],
            prepared.session_id,
            first.check.verification_id,
            candidate['candidate_id'],
            prepared.profile_version_id,
        ),
    ).fetchall()
    items = connection.execute(
        """SELECT id FROM code_verification_items WHERE verification_id=?
           AND evidence_kind='CONTENT_INTEGRITY' ORDER BY id""",
        (first.check.verification_id,),
    ).fetchall()
    if (
        first.scope.operation_id != step['operation_id']
        or first.scope.step_no != step['step_no']
        or first.check.owner_kind != 'CODING'
        or first.check.owner_id != task['id']
        or first.check.control_generation != prepared.generation
        or first.check.candidate_id != candidate['candidate_id']
        or first.check.manifest_sha256 != candidate['manifest_sha256']
        or first.session_id != prepared.session_id
        or first.state_version != prepared.current_version
        or first.profile_version_id != prepared.profile_version_id
        or tuple(row[0] for row in items) != first.integrity_item_ids
        or [(row['id'], row['verification_item_id']) for row in commands]
        != [(claim.command_execution_id, claim.check.item_id) for claim in claims]
        or any(row['config_version_id'] != first.profile_version_id for row in commands)
    ):
        raise StorageUnavailable('Original project check bindings differ')
    return tuple(zip(claims, commands, strict=True))


def read_interrupted_project_check(connection, operation_id):
    prepared, task, _, step, candidate = _original(connection, operation_id)
    if step['status'] not in ('PENDING', 'RUNNING', 'UNKNOWN') or step['external_identity'] is None:
        return None
    group = _stored_check_group(connection, prepared, task, step, candidate)
    active = [(claim, row) for claim, row in group if row['status'] in ('RUNNING', 'UNKNOWN')]
    restoring = prepared.restore is not None and step['status'] == 'PENDING'
    if restoring and not active and group[0][1]['status'] == 'PENDING':
        active = [group[0]]
    if len(active) > 1:
        raise StorageUnavailable('Original project checks must be serial')
    if not active:
        return None
    return active[0][0], operation_check_status(prepared, step)


def read_idle_project_check(connection, operation_id):
    prepared, task, operation, step, candidate = _original(connection, operation_id)
    if step['status'] != 'RUNNING' or step['external_identity'] is None:
        return None
    group = _stored_check_group(connection, prepared, task, step, candidate)
    if any(row['status'] in ('RUNNING', 'UNKNOWN') for _, row in group):
        return None
    pending = [(claim, row) for claim, row in group if row['status'] == 'PENDING']
    return (
        None
        if not pending
        else (
            prepared,
            task,
            operation,
            step,
            candidate,
            group,
            pending[0],
            _current(prepared, task, operation, candidate),
        )
    )


def start_following_project_check(
    connection, operation_id, selected, binding, *, max_output_bytes, at
):
    require_write_transaction(connection)
    idle = read_idle_project_check(connection, operation_id)
    if idle is None or not idle[-1]:
        raise CodingCheckPlanError('VERIFICATION_STAGE_NOT_READY')
    _, task, _, _, _, group, (claim, command), _ = idle
    if (
        claim.scope.controller_ref != binding.controller_ref
        or claim.owner_epoch != binding.owner_epoch
        or task['current_verification_id'] != claim.check.verification_id
        or claim.max_output_bytes != max_output_bytes
        or [row['check_id'] for _, row in group] != [item.check_id for item in selected]
        or any(
            row['command_ref'] != item.admission.command.command_id
            or original.runner_manifest_sha256 != item.admission.runner_manifest_sha256
            for (original, row), item in zip(group, selected, strict=True)
        )
    ):
        raise CodingCheckPlanError('CHECK_CONFIGURATION_INVALID')
    changed = connection.execute(
        "UPDATE code_commands SET status='RUNNING',started_at=? WHERE id=? AND status='PENDING'",
        (at, command['id']),
    )
    item = connection.execute(
        "UPDATE code_verification_items SET result='RUNNING',started_at=? WHERE id=? AND result='NOT_RUN'",
        (at, claim.check.item_id),
    )
    if changed.rowcount != 1 or item.rowcount != 1:
        raise StorageUnavailable('Original pending project check changed')
    connection.execute(
        """UPDATE code_verifications SET status='RUNNING',stop_status='ACTIVE',
           cleanup_status='NOT_STARTED',source_integrity_status='NOT_CHECKED' WHERE id=?""",
        (claim.check.verification_id,),
    )
    return claim, next(item for item in selected if item.check_id == command['check_id'])


def operation_check_status(origin, step):
    if origin.restore is not None and step['status'] == 'PENDING':
        return origin.restore['status']
    return step['status']


def fail_unprepared_project_check(connection, operation_id, reason, *, at):
    """A failed prerequisite may close only the original step that never dispatched."""
    require_write_transaction(connection)
    origin, task, operation, step, candidate = _original(connection, operation_id)
    if (
        not _current(origin, task, operation, candidate)
        or step['status'] != 'PENDING'
        or step['external_identity'] is not None
        or (origin.restore is not None and origin.restore['status'] != 'PENDING')
    ):
        return False
    if reason not in (
        'CHECK_CONFIGURATION_INVALID',
        'CONTENT_NOT_READY',
        'CONFIG_NOT_READY',
        'VERIFICATION_STAGE_NOT_READY',
    ):
        raise ValueError('Original project prerequisite failure differs')
    number = step['step_no'] if origin.restore is None else 1
    connection.execute(
        """UPDATE code_operation_steps SET status='FAILED',started_at=?,ended_at=?,last_observed_at=?
           WHERE operation_id=? AND step_no=? AND status='PENDING' """,
        (at, at, at, operation_id, number),
    )
    connection.execute(
        """UPDATE code_operations SET status='FAILED',failure_code=?,started_at=COALESCE(started_at,?),
           ended_at=? WHERE id=?""",
        (reason, at, at, operation_id),
    )
    return True


def verify_coding_project_check_active(connection, claim):
    prepared, task, operation, step, candidate = _original(connection, claim.scope.operation_id)
    if (
        not _current(prepared, task, operation, candidate)
        or operation['status'] != 'RUNNING'
        or task['state_version'] != claim.state_version
        or task['current_verification_id'] != claim.check.verification_id
        or operation_check_status(prepared, step) != 'RUNNING'
        or claim not in check_claims(step['external_identity'])
        or connection.execute(
            """SELECT 1 FROM code_commands WHERE id=? AND operation_id=? AND status=?""",
            (
                claim.command_execution_id,
                claim.scope.operation_id,
                'PENDING' if step['status'] == 'PENDING' else 'RUNNING',
            ),
        ).fetchone()
        is None
    ):
        raise StorageUnavailable('Original Coding project check is fenced')


def _process_facts(completion, claim):
    try:
        return project_process_facts(completion, claim.runner_manifest_sha256)
    except ProjectCheckEvidenceUnknown as error:
        raise StorageUnavailable('Original project check process differs') from error


_INTEGRITY_OUTCOMES = {
    'VERIFIED': ('PASSED', None),
    'CHANGED': ('FAILED', 'INPUT_CHANGED'),
    'UNKNOWN': ('UNKNOWN', 'EVIDENCE_INCOMPLETE'),
    'NOT_CHECKED': ('NOT_RUN', None),
}


def _project_integrity(connection, claim, group, latest):
    if len(group) == 1:
        return latest
    results = connection.execute(
        """SELECT evidence_summary FROM code_verification_items WHERE verification_id=?
           AND evidence_kind='PROCESS_EXIT' """,
        (claim.check.verification_id,),
    ).fetchall()
    observed = [
        strict_json_object(row[0])['source_integrity_status']
        for row in results
        if row[0] is not None
    ]
    if any(status not in _INTEGRITY_OUTCOMES for status in observed):
        raise StorageUnavailable('Original project copy integrity differs')
    for status in ('CHANGED', 'UNKNOWN', 'NOT_CHECKED'):
        if status in observed:
            return status
    return 'VERIFIED' if len(observed) == len(group) else 'NOT_CHECKED'


def _finish_check_group(
    connection,
    claim,
    step,
    *,
    verification_status,
    operation_status,
    integrity,
    failure_code,
    interrupted_restore,
    at,
):
    for item_id in claim.integrity_item_ids:
        result, reason = _INTEGRITY_OUTCOMES[integrity]
        observed_at = at if result != 'NOT_RUN' else None
        connection.execute(
            """UPDATE code_verification_items SET result=?,reason_code=?,started_at=COALESCE(started_at,?),
               ended_at=? WHERE id=? AND verification_id=?""",
            (result, reason, observed_at, observed_at, item_id, claim.check.verification_id),
        )
    connection.execute(
        """UPDATE code_commands SET status='CANCELLED',ended_at=?
           WHERE operation_id=? AND purpose='CHECK' AND status='PENDING' AND started_at IS NULL""",
        (at, claim.scope.operation_id),
    )
    connection.execute(
        """UPDATE code_verifications SET status=?,stop_status='VERIFIED',cleanup_status='VERIFIED',
           source_integrity_status=?,ended_at=? WHERE id=? AND operation_id=?""",
        (verification_status, integrity, at, claim.check.verification_id, claim.scope.operation_id),
    )
    if interrupted_restore:
        connection.execute(
            """UPDATE code_operation_steps SET status=?,ended_at=?,last_observed_at=?
               WHERE operation_id=? AND step_no=2""",
            (operation_status, at, at, claim.scope.operation_id),
        )
    result_ref = canonical_input({'verification_id': claim.check.verification_id})
    connection.execute(
        """UPDATE code_operation_steps SET status=?,result_ref=?,ended_at=?,last_observed_at=?
           WHERE operation_id=? AND step_no=?""",
        (
            'CANCELLED' if interrupted_restore else operation_status,
            result_ref if operation_status == 'SUCCEEDED' else None,
            at,
            at,
            claim.scope.operation_id,
            step['step_no'],
        ),
    )
    connection.execute(
        'UPDATE code_operations SET status=?,failure_code=?,ended_at=? WHERE id=?',
        (operation_status, failure_code, at, claim.scope.operation_id),
    )


def close_idle_project_check(connection, operation_id, *, failure, at):
    require_write_transaction(connection)
    idle = read_idle_project_check(connection, operation_id)
    if idle is None:
        return False
    _, _, _, step, group_candidate, group, (claim, _), current = idle
    if claim.check.candidate_id != group_candidate['candidate_id'] or not any(
        row['ended_at'] is not None for _, row in group
    ):
        raise StorageUnavailable('Original idle check group has no closed predecessor')
    _finish_check_group(
        connection,
        claim,
        step,
        verification_status='UNKNOWN' if current else 'CANCELLED',
        operation_status='FAILED' if current else 'CANCELLED',
        integrity=_project_integrity(connection, claim, group, 'NOT_CHECKED'),
        failure_code=failure if current else 'TASK_ENDED',
        interrupted_restore=False,
        at=at,
    )
    return True


def finish_coding_project_check(connection, claim, completion, *, at, allow_following=True):
    require_write_transaction(connection)
    origin, task, operation, step, candidate = _original(connection, claim.scope.operation_id)
    group = _stored_check_group(connection, origin, task, step, candidate)
    command = next((row for bound, row in group if bound == claim), None)
    if (
        type(completion) not in (ProjectCheckDispatchResult, ProjectCheckUndispatched)
        or completion.result.scope != claim.scope
        or completion.result.check != claim.check
        or command is None
    ):
        raise StorageUnavailable('Original project check result differs')
    result = completion.result
    process, binding = _process_facts(completion, claim)
    status = (
        'CANCELLED'
        if process is None or result.result == 'CANCELLED'
        else 'SUCCEEDED'
        if result.exit_code == 0
        else 'FAILED'
    )
    facts = {
        'exit_code': result.exit_code,
        'stdout': None if result.stdout is None else asdict(result.stdout),
        'stderr': None if result.stderr is None else asdict(result.stderr),
    }
    if len(group) > 1:
        facts['source_integrity_status'] = result.source_integrity
    summary = canonical_input(facts)
    if command['ended_at'] is not None:
        if (
            command['status'],
            command['exit_code'],
            command['process_identity'],
            command['runtime_binding'],
            command['item_result'],
            command['reason_code'],
            command['evidence_summary'],
            command['item_ended_at'],
        ) != (
            status,
            result.exit_code,
            process,
            binding,
            result.result,
            result.reason_code,
            summary,
            command['ended_at'],
        ):
            raise StorageUnavailable('Original project check terminal result differs')
        return
    interrupted_restore = origin.restore is not None and step['status'] == 'PENDING'
    if (
        operation_check_status(origin, step) not in ('RUNNING', 'UNKNOWN')
        or (interrupted_restore and type(completion) is not ProjectCheckUndispatched)
        or any(row['status'] in ('RUNNING', 'UNKNOWN') and bound != claim for bound, row in group)
    ):
        raise StorageUnavailable('Original project check completion was fenced')
    changed = connection.execute(
        """UPDATE code_commands SET status=?,exit_code=?,process_identity=?,runtime_binding=?,ended_at=?
           WHERE id=? AND operation_id=? AND verification_item_id=? AND status IN ('PENDING','RUNNING','UNKNOWN')""",
        (
            status,
            result.exit_code,
            process,
            binding,
            at,
            claim.command_execution_id,
            claim.scope.operation_id,
            claim.check.item_id,
        ),
    )
    if changed.rowcount != 1:
        raise StorageUnavailable('Original Coding command result lost its scope')
    if type(completion) is ProjectCheckDispatchResult:
        record_project_output(
            connection, task['id'], claim.command_execution_id, completion.display, at
        )
    connection.execute(
        """UPDATE code_verification_items SET result=?,reason_code=?,evidence_summary=?,ended_at=?
           WHERE id=? AND verification_id=?""",
        (
            result.result,
            result.reason_code,
            summary,
            at,
            claim.check.item_id,
            claim.check.verification_id,
        ),
    )
    current = _current(origin, task, operation, candidate)
    pending = any(bound != claim and row['status'] == 'PENDING' for bound, row in group)
    unresolved = result.result == 'UNKNOWN' or result.source_integrity == 'UNKNOWN'
    cancelled = not current or result.result == 'CANCELLED'
    if (
        pending
        and allow_following
        and not cancelled
        and not unresolved
        and result.source_integrity != 'CHANGED'
    ):
        connection.execute(
            """UPDATE code_operation_steps SET status='RUNNING',last_observed_at=?
               WHERE operation_id=? AND step_no=?""",
            (at, claim.scope.operation_id, step['step_no']),
        )
        connection.execute(
            "UPDATE code_operations SET status='RUNNING',failure_code=NULL WHERE id=?",
            (claim.scope.operation_id,),
        )
        return
    unresolved = unresolved or (pending and not allow_following and not cancelled)
    verification_status = (
        'CANCELLED'
        if result.result == 'CANCELLED' or (pending and cancelled)
        else 'UNKNOWN'
        if unresolved
        else 'FINISHED'
    )
    _finish_check_group(
        connection,
        claim,
        step,
        verification_status=verification_status,
        operation_status='CANCELLED' if cancelled else 'FAILED' if unresolved else 'SUCCEEDED',
        integrity=_project_integrity(connection, claim, group, result.source_integrity),
        failure_code='TASK_ENDED' if cancelled else 'EVIDENCE_INCOMPLETE' if unresolved else None,
        interrupted_restore=interrupted_restore,
        at=at,
    )


def mark_coding_project_check_unknown(connection, claim, *, at):
    require_write_transaction(connection)
    origin, _, operation, step, _ = _original(connection, claim.scope.operation_id)
    if operation_check_status(origin, step) not in (
        'RUNNING',
        'UNKNOWN',
    ) or claim not in check_claims(step['external_identity']):
        raise StorageUnavailable('Original project check unknown scope differs')
    connection.execute(
        "UPDATE code_commands SET status='UNKNOWN' WHERE id=? AND status IN ('PENDING','RUNNING')",
        (claim.command_execution_id,),
    )
    connection.execute(
        """UPDATE code_verification_items SET result='UNKNOWN',reason_code='PROCESS_STATE_UNKNOWN'
           WHERE id=? AND result IN ('NOT_RUN','RUNNING')""",
        (claim.check.item_id,),
    )
    connection.execute(
        """UPDATE code_verifications SET status='UNKNOWN',stop_status='UNKNOWN',cleanup_status='UNKNOWN',
               source_integrity_status='UNKNOWN' WHERE id=? AND status IN ('PENDING','RUNNING')""",
        (claim.check.verification_id,),
    )
    connection.execute(
        """UPDATE code_operation_steps SET status='UNKNOWN',last_observed_at=?
           WHERE operation_id=? AND step_no=?""",
        (at, claim.scope.operation_id, 2 if step['status'] == 'PENDING' else claim.scope.step_no),
    )
    if operation['status'] == 'RUNNING':
        connection.execute(
            """UPDATE code_operations SET status='UNKNOWN',failure_code='EXTERNAL_RESULT_UNKNOWN'
               WHERE id=?""",
            (claim.scope.operation_id,),
        )
