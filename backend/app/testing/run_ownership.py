"""Read and fence the original Testing run and its reserved case commands."""

from dataclasses import dataclass

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.guard_controller_binding import owner_epoch
from backend.app.infrastructure.runtime_launch_journal import (
    TestingLaunchScope,
    decode_launch_scope,
)
from backend.app.infrastructure.windows_task_directories import (
    ProjectCheckInput,
    SnapshotCheckInput,
)
from backend.app.shared.validation import strict_json_object

from .pack_compile import digest, encoded
from .run_records import EXECUTE, STEPS
from .tasks import materials_for, read_task_row


@dataclass(frozen=True)
class OriginalBrowserApplication:
    scope: TestingLaunchScope
    epoch: str
    command: object
    fixed: dict


@dataclass(frozen=True)
class OriginalCliCase:
    scope: TestingLaunchScope
    epoch: str
    check: ProjectCheckInput | SnapshotCheckInput
    command: object
    item: object
    case_id: str
    fixed: dict
    applications: tuple[OriginalBrowserApplication, ...] = ()


@dataclass(frozen=True)
class OriginalTestingRun:
    task: object
    operation: object
    verification: object
    pack: object
    facts: dict
    cases: tuple[OriginalCliCase, ...]

    @property
    def can_dispatch(self):
        return (
            self.task['status'] == 'RUNNING'
            and self.task['stop_requested_at'] is None
            and self.task['active_operation_id'] == self.operation['id']
            and self.task['control_generation'] == self.operation['control_generation']
            and self.operation['status'] == 'RUNNING'
        )


def _original_command(claim, expected, command, item, operation, verification, purpose):
    scope = decode_launch_scope(claim['scope'])
    epoch = owner_epoch(claim['owner_epoch'])
    if (
        type(scope) is not TestingLaunchScope
        or scope.owner_id != operation['testing_task_id']
        or scope.operation_id != operation['id']
        or scope.step_no != EXECUTE
        or scope.control_generation != operation['control_generation']
        or claim['command_execution_id'] != command['id']
        or command['testing_task_id'] != operation['testing_task_id']
        or command['task_id'] is not None
        or command['purpose'] != purpose
        or command['verification_item_id'] != item['id']
        or command['testing_profile_version_id'] != verification['testing_profile_version_id']
        or command['command_ref'] != expected['admission']['command_id']
    ):
        raise StorageUnavailable('Original Testing command ownership differs')
    return scope, epoch


def _original_case(claim, expected, commands, item, operation, verification, facts):
    command = commands[claim['command_execution_id']]
    scope, epoch = _original_command(
        claim, expected, command, item, operation, verification, 'CHECK'
    )
    if (
        claim['verification_id'] != verification['id']
        or claim['item_id'] != item['id']
        or item['check_id'] != expected['check_id']
        or claim['case_id'] != expected['case_id']
    ):
        raise StorageUnavailable('Original Testing case command ownership differs')
    applications = []
    browser = expected.get('kind') == 'BROWSER'
    if browser != ('applications' in claim) or browser != ('applications' in expected):
        raise StorageUnavailable('Original Testing browser application set differs')
    if browser:
        children = claim['applications']
        configs = expected['applications']
        if (
            type(children) is not list
            or type(configs) is not list
            or len(children) != 2
            or len(configs) != 2
            or {child['role'] for child in configs} != {'FRONTEND', 'BACKEND'}
        ):
            raise StorageUnavailable('Original Testing browser application set differs')
        for child, configured in zip(children, configs, strict=True):
            service = commands[child['command_execution_id']]
            child_scope, child_epoch = _original_command(
                child, configured, service, item, operation, verification, 'SERVICE'
            )
            if child_epoch != epoch or child_scope.controller_ref != scope.controller_ref:
                raise StorageUnavailable('Original Testing browser application controller differs')
            applications.append(
                OriginalBrowserApplication(child_scope, child_epoch, service, configured)
            )
    original = facts['target']
    owner = ('TESTING', scope.owner_id, scope.control_generation, verification['id'], item['id'])
    if facts['target_kind'] == 'SNAPSHOT':
        check = SnapshotCheckInput(
            *owner,
            **{key: value for key, value in original.items() if key != 'repository_id'},
        )
    else:
        check = ProjectCheckInput(*owner, **original)
    return OriginalCliCase(
        scope, epoch, check, command, item, claim['case_id'], expected, tuple(applications)
    )


def read_original_run(connection, operation_id):
    operation = connection.execute(
        """SELECT * FROM code_operations WHERE id=? AND resource_kind='TESTING_TASK'
           AND operation_type='RUN_TEST' AND task_id IS NULL AND resource_id=testing_task_id""",
        (operation_id,),
    ).fetchone()
    if operation is None:
        return None
    task = read_task_row(connection, operation['testing_task_id'])
    verification = connection.execute(
        """SELECT * FROM code_verifications WHERE operation_id=? AND owner_kind='TESTING'
           AND testing_task_id=? AND task_id IS NULL""",
        (operation_id, operation['testing_task_id']),
    ).fetchone()
    if (
        task is None
        or verification is None
        or task['current_verification_id'] != verification['id']
    ):
        raise StorageUnavailable('Original Testing run verification differs')
    fixed = strict_json_object(operation['fixed_input'])
    facts = fixed['facts']
    if (
        fixed['expected_state_version'] != operation['expected_state_version']
        or fixed['input_fingerprint'] != digest(encoded(facts))
        or facts['testing_task_id'] != task['id']
        or facts['control_generation'] != operation['control_generation']
        or facts['material_refs'] != materials_for(connection, task['id'])
        or any(
            facts[field] != task[field]
            for field in (
                'target_kind',
                'purpose',
                'requirement_id',
                'document_id',
                'design_revision_id',
                'profile_version_id',
                'plan_version_id',
                'test_pack_version_id',
                'validation_id',
            )
        )
        or verification['testing_profile_version_id'] != task['profile_version_id']
        or verification['candidate_id'] != task['candidate_id']
        or verification['snapshot_id'] != task['snapshot_id']
        or facts['target'].get('candidate_id') != task['candidate_id']
        or facts['target'].get('snapshot_id') != task['snapshot_id']
        or verification['purpose'] != task['purpose']
    ):
        raise StorageUnavailable('Original Testing run input differs')
    pack = connection.execute(
        'SELECT * FROM testing_pack_versions WHERE id=? AND plan_version_id=?',
        (facts['test_pack_version_id'], facts['plan_version_id']),
    ).fetchone()
    if (
        pack is None
        or pack['sha256'] != facts['test_pack_sha256']
        or pack['check_set_version_id'] != facts['check_set_version_id']
        or verification['check_set_version_id'] != facts['check_set_version_id']
        or (task['kind'] == 'PRODUCT' and pack['validation_id'] != facts['published_validation_id'])
    ):
        raise StorageUnavailable('Original Testing run pack differs')
    steps = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation_id,),
    ).fetchall()
    if [(row['step_no'], row['step_type']) for row in steps] != list(enumerate(STEPS, 1)):
        raise StorageUnavailable('Original Testing run steps differ')
    execute = strict_json_object(steps[EXECUTE - 1]['fixed_input'])
    claims = execute.pop('private_case_claims')
    if execute != fixed:
        raise StorageUnavailable('Original Testing dispatch input differs')
    commands = {
        row['id']: row
        for row in connection.execute(
            'SELECT * FROM code_commands WHERE operation_id=?', (operation_id,)
        )
    }
    items = {
        row['id']: row
        for row in connection.execute(
            'SELECT * FROM code_verification_items WHERE verification_id=?', (verification['id'],)
        )
    }
    declared = facts['runtime']['cases']
    if not claims or len(claims) != len(declared):
        raise StorageUnavailable('Original Testing command set differs')
    cases = tuple(
        _original_case(
            claim, expected, commands, items[claim['item_id']], operation, verification, facts
        )
        for claim, expected in zip(claims, declared, strict=True)
    )
    members = [member for case in cases for member in (case, *case.applications)]
    if (
        len({part.scope for part in members}) != len(members)
        or len(members) != len(commands)
        or {part.command['id'] for part in members} != set(commands)
    ):
        raise StorageUnavailable('Original Testing case scopes overlap')
    return OriginalTestingRun(task, operation, verification, pack, facts, cases)


def require_dispatch(connection, case):
    run = read_original_run(connection, case.scope.operation_id)
    if run is None or not run.can_dispatch:
        raise StorageUnavailable('Original Testing run is fenced')
    if run.task['authorization_id'] != run.facts['authorization_id']:
        raise StorageUnavailable('Original Testing authorization changed')
    return run
