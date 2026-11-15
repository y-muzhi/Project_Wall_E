"""Atomically reserve the exact original Testing run and its fixed evidence graph."""

from dataclasses import asdict, dataclass
from uuid import uuid4

from backend.app.code_tasks.operation_protocol import operation_steps
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.infrastructure.runtime_launch_journal import TestingLaunchScope
from backend.app.infrastructure.schema_transport import compact
from backend.app.shared.command_execution import operation_time

from .cli_plan import SelectedBrowserCase
from .pack_compile import digest, encoded

RUN_TYPE = 'RUN_TEST'
STEPS = operation_steps('TESTING', RUN_TYPE)
EXECUTE = STEPS.index('EXECUTE') + 1


@dataclass(frozen=True)
class _InternalRun:
    expected: int
    idempotency_key: str


def accept_internal_cli_run(connection, task, pack, compiled, plan, owner, target):
    if task['kind'] != 'PACK_VALIDATION' or task['validation_id'] is None:
        raise StorageUnavailable('An original pack validation child is required')
    request = _InternalRun(task['state_version'], str(uuid4()))
    return accept_cli_run(connection, request, task, pack, compiled, plan, owner, target)


def accepted_run(task, operation, version):
    return Success(
        {
            'code': 'OPERATION_ACCEPTED',
            'data': {
                'testing_task_id': task,
                'operation_id': operation,
                'state_version': version,
            },
            'details': None,
        },
        202,
    )


def _fixed_input(task, pack, target, runtime, *, expected):
    facts = {
        'testing_task_id': task['id'],
        'control_generation': task['control_generation'],
        'purpose': task['purpose'],
        'target_kind': task['target_kind'],
        'target': target,
        'requirement_id': task['requirement_id'],
        'document_id': task['document_id'],
        'design_revision_id': task['design_revision_id'],
        'material_refs': task['material_refs'],
        'profile_version_id': task['profile_version_id'],
        'authorization_id': task['authorization_id'],
        'plan_version_id': task['plan_version_id'],
        'test_pack_version_id': task['test_pack_version_id'],
        'test_pack_sha256': pack['sha256'],
        'check_set_version_id': pack['check_set_version_id'],
        'validation_id': task['validation_id'],
        'published_validation_id': pack['validation_id'],
        'runtime': runtime.facts(),
    }
    return {
        'expected_state_version': expected,
        'input_fingerprint': digest(encoded(facts)),
        'facts': facts,
    }


def _verification(connection, task, pack, compiled, plan, operation, at, fingerprint):
    environment = entity_id(connection, EntityKind.ENVIRONMENT_RECORD)
    verification = entity_id(connection, EntityKind.VERIFICATION)
    installed = [entry.admission for entry in plan.cases]
    installed.extend(
        app.service
        for entry in plan.cases
        if type(entry) is SelectedBrowserCase
        for app in entry.admission.applications
    )
    runtime_refs = list(dict.fromkeys(ref for entry in installed for ref in entry.runtime_refs))
    runner_refs = list(dict.fromkeys(entry.runner_ref for entry in installed))
    resources = list(
        dict.fromkeys(
            [f'{entry.runner_ref}:sha256:{entry.runner_manifest_sha256}' for entry in installed]
            + [f'testing-pack:sha256:{pack["sha256"]}']
        )
    )
    connection.execute(
        """INSERT INTO code_environment_records(
           id,testing_task_id,runtime_refs,dependency_refs,runner_refs,testing_profile_version_id,
           check_resource_refs,scope_key,observed_at) VALUES(?,?,?,'[]',?,?,?,?,?)""",
        (
            environment,
            task['id'],
            compact(runtime_refs),
            compact(runner_refs),
            task['profile_version_id'],
            compact(resources),
            fingerprint,
            at,
        ),
    )
    checks = compiled.check_set.value()['items']
    connection.execute(
        """INSERT INTO code_verifications(
           id,owner_kind,testing_task_id,candidate_id,snapshot_id,purpose,check_set_version_id,
           testing_profile_version_id,environment_record_id,operation_id,scope_stages,
           selected_check_ids,status,stop_status,cleanup_status,source_integrity_status,created_at)
           VALUES(?,'TESTING',?,?,?,?,?,?,?,?,?,?,'PENDING','NOT_STARTED','NOT_STARTED','NOT_CHECKED',?)""",
        (
            verification,
            task['id'],
            task['candidate_id'],
            task['snapshot_id'],
            task['purpose'],
            pack['check_set_version_id'],
            task['profile_version_id'],
            environment,
            operation,
            compact(checks[0]['stages']),
            compact([item['check_id'] for item in checks]),
            at,
        ),
    )
    item_ids = {}
    counts = {}
    for entry in plan.cases:
        counts[entry.check_id] = counts.get(entry.check_id, 0) + 1
    for item in checks:
        identity = entity_id(connection, EntityKind.VERIFICATION_ITEM)
        item_ids[item['check_id']] = identity
        count = counts.get(item['check_id'])
        initial = 0 if count is not None else None
        connection.execute(
            """INSERT INTO code_verification_items(
               id,verification_id,check_id,required,check_kind,evidence_kind,result,
               expected_case_count,executed_case_count,passed_case_count,failed_case_count)
               VALUES(?,?,?,?,?,?,'NOT_RUN',?,?,?,?)""",
            (
                identity,
                verification,
                item['check_id'],
                item['required'],
                item['check_kind'],
                item['evidence_rule']['kind'],
                count,
                initial,
                initial,
                initial,
            ),
        )
    return verification, item_ids


def _command(connection, task, operation, item, owner, at, reference, purpose):
    identity = entity_id(connection, EntityKind.COMMAND_EXECUTION)
    scope = TestingLaunchScope(
        owner.controller_ref,
        operation,
        EXECUTE,
        uuid4().hex,
        task['id'],
        task['control_generation'],
    )
    connection.execute(
        """INSERT INTO code_commands(
           id,testing_task_id,operation_id,purpose,command_ref,testing_profile_version_id,
           status,created_at,verification_item_id) VALUES(?,?,?,?,?,?,'PENDING',?,?)""",
        (identity, task['id'], operation, purpose, reference, task['profile_version_id'], at, item),
    )
    return identity, {
        'scope': asdict(scope),
        'owner_epoch': owner.owner_epoch,
        'command_execution_id': identity,
    }


def _commands(connection, task, plan, operation, verification, items, owner, at):
    claims = []
    first_by_item = {}
    for entry in plan.cases:
        item = items[entry.check_id]
        browser = type(entry) is SelectedBrowserCase
        reference = entry.admission.command_id if browser else entry.admission.command.command_id
        identity, claim = _command(connection, task, operation, item, owner, at, reference, 'CHECK')
        first_by_item.setdefault(item, identity)
        claim.update(verification_id=verification, item_id=item, case_id=entry.case.case_id)
        if browser:
            applications = []
            for application in entry.admission.applications:
                _, child = _command(
                    connection,
                    task,
                    operation,
                    item,
                    owner,
                    at,
                    application.service.command.command_id,
                    'SERVICE',
                )
                applications.append(child)
            claim['applications'] = applications
        claims.append(claim)
    connection.executemany(
        'UPDATE code_verification_items SET command_execution_id=? WHERE id=?',
        [(command, item) for item, command in first_by_item.items()],
    )
    return claims


def accept_cli_run(connection, request, task, pack, compiled, plan, owner, target):
    at = operation_time(None)
    version = increment(request.expected)
    operation = entity_id(connection, EntityKind.OPERATION_RECORD)
    fixed = _fixed_input(task, pack, target, plan, expected=request.expected)
    raw = canonical_input(fixed)
    connection.execute(
        """INSERT INTO code_operations(
           id,testing_task_id,resource_kind,resource_id,operation_type,idempotency_key,
           expected_state_version,fixed_input,control_generation,status,created_at,started_at)
           VALUES(?,?,'TESTING_TASK',?,'RUN_TEST',?,?,?,?,'RUNNING',?,?)""",
        (
            operation,
            task['id'],
            task['id'],
            request.idempotency_key,
            request.expected,
            raw,
            task['control_generation'],
            at,
            at,
        ),
    )
    verification, items = _verification(
        connection, task, pack, compiled, plan, operation, at, fixed['input_fingerprint']
    )
    claims = _commands(connection, task, plan, operation, verification, items, owner, at)
    execute_fixed = canonical_input({**fixed, 'private_case_claims': claims})
    for number, name in enumerate(STEPS, 1):
        instant = at if number == 1 else None
        connection.execute(
            """INSERT INTO code_operation_steps(
               operation_id,step_no,step_type,status,fixed_input,
               started_at,ended_at,last_observed_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (
                operation,
                number,
                name,
                'SUCCEEDED' if number == 1 else 'PENDING',
                execute_fixed if number == EXECUTE else raw,
                instant,
                instant,
                instant,
            ),
        )
    saved = connection.execute(
        """UPDATE testing_tasks SET status='RUNNING',phase='PREPARE',state_version=?,
           active_operation_id=?,current_verification_id=?
           WHERE id=? AND state_version=? AND control_generation=? AND status='READY'
           AND active_operation_id IS NULL AND current_verification_id IS NULL
           AND stop_requested_at IS NULL""",
        (
            version,
            operation,
            verification,
            task['id'],
            request.expected,
            task['control_generation'],
        ),
    )
    if saved.rowcount != 1:
        raise StorageUnavailable('Original Testing run acceptance was fenced')
    return accepted_run(task['id'], operation, version)
