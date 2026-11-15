"""Settle the original check command, then save the unique Testing report."""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.guard_request_header import PROTOCOL
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.infrastructure.project_check_result import (
    ProjectCheckDispatchResult,
    ProjectCheckUndispatched,
    project_process_facts,
)
from backend.app.infrastructure.schema_transport import compact
from backend.app.shared.time import utc_milliseconds
from backend.app.shared.validation import strict_json_object

from .browser_journal import ClosedBrowserCase
from .cli_evidence import original_cli_outcome
from .http_evidence import original_http_outcome
from .pack_compile import digest, encoded
from .plans import _version
from .run_ownership import read_original_run, require_dispatch
from .run_records import EXECUTE

_OPERATIONAL_REASONS = (
    'INPUT_CHANGED',
    'TIMEOUT',
    'OUTPUT_LIMIT',
    'EVIDENCE_INCOMPLETE',
    'ISOLATION_UNAVAILABLE',
    'RESOURCE_MISSING',
)
_RESULT_BY_REASON = {
    'INPUT_CHANGED': 'FAILED',
    'TIMEOUT': 'FAILED',
    'OUTPUT_LIMIT': 'FAILED',
    'EVIDENCE_INCOMPLETE': 'UNKNOWN',
    'ISOLATION_UNAVAILABLE': 'UNAVAILABLE',
    'RESOURCE_MISSING': 'UNAVAILABLE',
}


def _running_step(connection, operation, step, at):
    connection.execute(
        """UPDATE code_operation_steps SET status='RUNNING',started_at=COALESCE(started_at,?),
           last_observed_at=? WHERE operation_id=? AND step_type=? AND status='PENDING'""",
        (at, at, operation, step),
    )


def _finish_step(connection, operation, step, at, *, status='SUCCEEDED', result=None):
    connection.execute(
        """UPDATE code_operation_steps SET status=?,started_at=COALESCE(started_at,?),
           ended_at=?,last_observed_at=?,result_ref=?
           WHERE operation_id=? AND step_type=? AND ended_at IS NULL""",
        (status, at, at, at, None if result is None else compact(result), operation, step),
    )


def begin_case(connection, case, at):
    run = require_dispatch(connection, case)
    if any(
        value.command['status'] in ('RUNNING', 'UNKNOWN') and value.command['ended_at'] is None
        for value in run.cases
    ):
        raise StorageUnavailable('Original Testing command is already active')
    changed = connection.execute(
        """UPDATE code_commands SET status='RUNNING',started_at=?
           WHERE id=? AND operation_id=? AND status='PENDING'""",
        (at, case.command['id'], case.scope.operation_id),
    )
    if changed.rowcount != 1:
        raise StorageUnavailable('Original Testing command dispatch was fenced')
    connection.execute(
        """UPDATE code_verification_items SET result='RUNNING',started_at=COALESCE(started_at,?)
           WHERE verification_id=? AND (id=? OR evidence_kind='CONTENT_INTEGRITY') AND ended_at IS NULL""",
        (at, run.verification['id'], case.item['id']),
    )
    connection.execute(
        """UPDATE code_verifications SET status='RUNNING',stop_status='ACTIVE'
           WHERE id=? AND ended_at IS NULL""",
        (run.verification['id'],),
    )
    _running_step(connection, case.scope.operation_id, 'MATERIALIZE', at)


def begin_browser_application(connection, case, application, at):
    run = require_dispatch(connection, case)
    original = next((entry for entry in run.cases if entry.scope == case.scope), None)
    if (
        original is None
        or original.command['status'] != 'RUNNING'
        or not any(
            member.scope == application.scope and member.command['id'] == application.command['id']
            for member in original.applications
        )
    ):
        raise StorageUnavailable('Original Testing application no longer belongs to the case')
    changed = connection.execute(
        """UPDATE code_commands SET status='RUNNING',started_at=?
           WHERE id=? AND operation_id=? AND purpose='SERVICE' AND status='PENDING'""",
        (at, application.command['id'], case.scope.operation_id),
    )
    if changed.rowcount != 1:
        raise StorageUnavailable('Original Testing application dispatch was fenced')


def prepared_case(connection, case, at):
    run = require_dispatch(connection, case)
    if not any(
        item.scope == case.scope
        and item.command['status'] == 'RUNNING'
        and item.command['ended_at'] is None
        for item in run.cases
    ):
        raise StorageUnavailable('Original Testing preparation is no longer active')
    _finish_step(connection, case.scope.operation_id, 'MATERIALIZE', at)
    _finish_step(connection, case.scope.operation_id, 'PREPARE', at)
    _running_step(connection, case.scope.operation_id, 'EXECUTE', at)
    connection.execute("UPDATE testing_tasks SET phase='EXECUTE' WHERE id=?", (run.task['id'],))


def mark_unknown(connection, case, at):
    run = read_original_run(connection, case.scope.operation_id)
    if run is None:
        raise StorageUnavailable('Original Testing command no longer has an owner')
    changed = connection.execute(
        """UPDATE code_commands SET status='UNKNOWN' WHERE id=? AND operation_id=?
           AND status='RUNNING' AND ended_at IS NULL""",
        (case.command['id'], run.operation['id']),
    )
    if not changed.rowcount:
        return
    connection.execute(
        "UPDATE code_operations SET status='UNKNOWN',failure_code='EXECUTION_NOT_STOPPED' WHERE id=?",
        (run.operation['id'],),
    )
    connection.execute(
        """UPDATE code_operation_steps SET status='UNKNOWN',started_at=COALESCE(started_at,?),
           last_observed_at=? WHERE operation_id=? AND step_no=? AND ended_at IS NULL""",
        (at, at, run.operation['id'], EXECUTE),
    )
    connection.execute(
        "UPDATE code_verifications SET status='UNKNOWN',stop_status='UNKNOWN',cleanup_status='UNKNOWN' WHERE id=?",
        (run.verification['id'],),
    )
    if (
        run.can_dispatch
        and connection.execute(
            """SELECT 1 FROM code_waiting_items WHERE testing_task_id=? AND source_kind='OPERATION'
           AND source_id=? AND kind='OPERATION_RESULT' AND status='OPEN'""",
            (run.task['id'], run.operation['id']),
        ).fetchone()
        is None
    ):
        connection.execute(
            """INSERT INTO code_waiting_items(id,testing_task_id,kind,source_kind,source_id,
               resume_phase,status,created_at) VALUES(?,?,'OPERATION_RESULT','OPERATION',?,?,'OPEN',?)""",
            (
                entity_id(connection, EntityKind.WAITING_ITEM),
                run.task['id'],
                run.operation['id'],
                run.task['phase'],
                at,
            ),
        )
    if run.can_dispatch:
        connection.execute(
            """UPDATE testing_tasks SET status='WAITING',state_version=?
               WHERE id=? AND state_version=? AND status='RUNNING'""",
            (increment(run.task['state_version']), run.task['id'], run.task['state_version']),
        )


def _observation(connection, case, kind, at, reference, binding):
    identity = entity_id(connection, EntityKind.RUNTIME_OBSERVATION)
    connection.execute(
        """INSERT INTO code_runtime_observations(
           id,testing_task_id,command_id,operation_id,control_generation,runtime_binding_ref,
           kind,result,reason_codes,active_process_count,observed_at,evidence_ref)
           VALUES(?,?,?,?,?,?,?,'VERIFIED','[]',?,?,?)""",
        (
            identity,
            case.scope.owner_id,
            case.command['id'],
            case.scope.operation_id,
            case.scope.control_generation,
            binding,
            kind,
            None if kind == 'PREPARE' else 0,
            at,
            reference,
        ),
    )


def _receipt_facts(completion):
    if type(completion) is ProjectCheckUndispatched:
        return {
            'undispatched': True,
            'scope': asdict(completion.scope),
        }
    return {
        'scope': asdict(completion.result.scope),
        'prepare': completion.prepared,
        'created': completion.created,
        'stop': completion.stopped,
        'release': completion.released,
        'outcome': asdict(completion.result),
        **({'http': completion.http} if completion.http is not None else {}),
    }


def _integrity(previous, current):
    if 'CHANGED' in (previous, current):
        return 'CHANGED'
    if previous == 'UNKNOWN' or current in ('UNKNOWN', 'NOT_CHECKED'):
        return 'UNKNOWN'
    return 'VERIFIED'


def _set_case_reason(connection, item, reason):
    if reason is None:
        return
    previous = item['reason_code']
    if previous is None or _OPERATIONAL_REASONS.index(reason) < _OPERATIONAL_REASONS.index(
        previous
    ):
        connection.execute(
            'UPDATE code_verification_items SET reason_code=? WHERE id=?',
            (reason, item['id']),
        )


def _save_case_result(connection, item, outcome, at):
    connection.execute(
        """INSERT INTO code_verification_case_results(
           item_id,case_id,result,assertion_results,capture_status,observed_at) VALUES(?,?,?,?,?,?)""",
        (
            item,
            outcome['case_id'],
            outcome['result'],
            compact(outcome['assertion_results']),
            outcome['capture_status'],
            at,
        ),
    )
    connection.execute(
        """UPDATE code_verification_items SET executed_case_count=executed_case_count+1,
           passed_case_count=passed_case_count+?,failed_case_count=failed_case_count+?
           WHERE id=?""",
        (
            int(outcome['result'] == 'PASSED'),
            int(outcome['result'] == 'FAILED'),
            item,
        ),
    )


def settle_case(connection, case, definition, check_case, completion, at, *, undispatched=None):
    run = read_original_run(connection, case.scope.operation_id)
    if run is None or run.verification['ended_at'] is not None:
        raise StorageUnavailable('Original Testing run cannot accept a late current write')
    original = next((value for value in run.cases if value.scope == case.scope), None)
    if original is None or original.command['id'] != case.command['id']:
        raise StorageUnavailable('Original Testing closure crosses a command scope')
    if original.command['ended_at'] is not None:
        return
    if (
        type(completion) not in (ProjectCheckDispatchResult, ProjectCheckUndispatched)
        or completion.result.scope != original.scope
        or completion.result.check != original.check
    ):
        raise StorageUnavailable('Original Testing command closure differs')
    if original.command['status'] not in ('RUNNING', 'UNKNOWN') and not (
        original.command['status'] == 'PENDING' and type(completion) is ProjectCheckUndispatched
    ):
        raise StorageUnavailable('Original Testing command was never accepted for closure')
    native = completion.result
    outcome = None
    if type(completion) is ProjectCheckUndispatched:
        reason = undispatched or 'EVIDENCE_INCOMPLETE'
        status = 'CANCELLED' if reason == 'CANCELLED' else 'FAILED'
        reason = {
            'CANCELLED': None,
            'CONFIG_NOT_READY': 'RESOURCE_MISSING',
            'TEST_ASSET_REVOKED': 'RESOURCE_MISSING',
        }.get(reason, reason)
    elif definition.purpose == 'SERVICE':
        outcome, status, reason = original_http_outcome(completion, original, check_case)
    else:
        outcome = original_cli_outcome(
            completion, original.scope, original.check, check_case, definition
        )
        reason = None if outcome is not None else native.reason_code
        status = {
            'PASSED': 'SUCCEEDED',
            'FAILED': 'FAILED',
            'UNKNOWN': 'UNKNOWN',
            'UNAVAILABLE': 'FAILED',
            'CANCELLED': 'CANCELLED',
        }[native.result]
    process, runtime = project_process_facts(
        completion, original.fixed['admission']['runner_manifest_sha256']
    )
    binding = None if runtime is None else strict_json_object(runtime)['guard_run_ref']
    reference = 'testing-check:sha256:' + digest(encoded(_receipt_facts(completion)))
    changed = connection.execute(
        """UPDATE code_commands SET status=?,process_identity=?,runtime_binding=?,exit_code=?,ended_at=?
           WHERE id=? AND operation_id=? AND ended_at IS NULL""",
        (
            status,
            process,
            runtime,
            native.exit_code,
            at,
            original.command['id'],
            run.operation['id'],
        ),
    )
    if changed.rowcount != 1:
        raise StorageUnavailable('Original Testing command was already closed')
    if type(completion) is ProjectCheckDispatchResult and completion.prepared is not None:
        _observation(connection, original, 'PREPARE', at, reference, binding)
    for kind in ('STOP', 'CLEANUP'):
        _observation(connection, original, kind, at, reference, binding)
    if outcome is not None:
        _save_case_result(connection, original.item['id'], outcome, at)
    if (
        outcome is not None
        and run.task['status'] == 'WAITING'
        and run.operation['status'] == 'UNKNOWN'
        and run.task['control_generation'] == original.scope.control_generation
        and any(part.command['status'] == 'PENDING' for part in run.cases)
    ):
        connection.execute(
            """UPDATE code_waiting_items SET status='RESOLVED',resolved_at=?,resolution_ref=?
               WHERE testing_task_id=? AND source_kind='OPERATION' AND source_id=?
               AND kind='OPERATION_RESULT' AND status='OPEN'""",
            (
                at,
                compact({'command_execution_id': original.command['id']}),
                run.task['id'],
                run.operation['id'],
            ),
        )
    _set_case_reason(connection, original.item, reason)
    connection.execute(
        """UPDATE code_verifications SET source_integrity_status=?,stop_status='VERIFIED',
           cleanup_status='VERIFIED' WHERE id=?""",
        (
            _integrity(run.verification['source_integrity_status'], native.source_integrity),
            run.verification['id'],
        ),
    )


def _driver_facts(driver, runner_sha256):
    if driver.released is None:
        return None, None, None, 'NOT_CHECKED'
    released = driver.released
    native = released['native']
    check = released['check']
    exit = check['exit']
    if native['process_state'] == 'NOT_CREATED':
        if exit is not None:
            raise StorageUnavailable('Original CHECK_DRIVER exit differs')
        return None, None, None, check['source_integrity']
    if (
        native['run_kind'] != 'CHECK_DRIVER'
        or native['process_state'] != 'EXITED'
        or exit is None
        or native['process_identity'] is None
    ):
        raise StorageUnavailable('Original CHECK_DRIVER root evidence differs')
    process = native['process_identity']
    start = datetime(1601, 1, 1, tzinfo=UTC) + timedelta(
        microseconds=int(process['creation_time_hex'], 16) // 10
    )
    return (
        canonical_input(
            {
                'pid': process['pid'],
                'created_at': utc_milliseconds(start),
                'ownership_ref': native['resource_ref'],
            }
        ),
        canonical_input(
            {
                'runtime_policy_version': PROTOCOL,
                'run_kind': 'CHECK_DRIVER',
                'guard_run_ref': native['resource_ref'],
                'appcontainer_profile_ref': process['appcontainer_sid'],
                'job_refs': [native['job_ref']],
                'manifest_ref': runner_sha256,
            }
        ),
        exit['exit_code'],
        check['source_integrity'],
    )


def _record_browser_member(connection, run, member, facts, status, prepared, receipt, at):
    process, runtime, exit_code = facts
    changed = connection.execute(
        """UPDATE code_commands SET status=?,process_identity=?,runtime_binding=?,exit_code=?,ended_at=?
           WHERE id=? AND operation_id=? AND ended_at IS NULL AND status IN ('PENDING','RUNNING','UNKNOWN')""",
        (status, process, runtime, exit_code, at, member.command['id'], run.operation['id']),
    )
    if changed.rowcount != 1:
        raise StorageUnavailable('Original Testing browser command was already closed')
    binding = None if runtime is None else strict_json_object(runtime)['guard_run_ref']
    reference = 'testing-check:sha256:' + digest(encoded(receipt))
    if prepared:
        _observation(connection, member, 'PREPARE', at, reference, binding)
    for kind in ('STOP', 'CLEANUP'):
        _observation(connection, member, kind, at, reference, binding)
    return reference


def _save_browser_integration(connection, operation, case, services, observed, reference):
    if set(observed) != {service.command['id'] for service in services}:
        return
    row = connection.execute(
        'SELECT result_ref FROM code_operation_steps WHERE operation_id=? AND step_no=?',
        (operation, EXECUTE),
    ).fetchone()
    records = (
        [] if row['result_ref'] is None else strict_json_object(row['result_ref'])['browser_cases']
    )
    if any(old['driver_command_id'] == case.command['id'] for old in records):
        raise StorageUnavailable('Original Testing browser integration evidence already exists')
    records.append(
        {
            'driver_command_id': case.command['id'],
            'item_id': case.item['id'],
            'case_id': case.case_id,
            'applications': [
                {'command_id': service.command['id'], 'role': service.fixed['role']}
                for service in services
            ],
            'evidence_ref': reference,
        }
    )
    connection.execute(
        'UPDATE code_operation_steps SET result_ref=? WHERE operation_id=? AND step_no=? AND ended_at IS NULL',
        (compact({'browser_cases': records}), operation, EXECUTE),
    )


def settle_browser_case(connection, case, driver, services, at, *, undispatched=None):
    run = read_original_run(connection, case.scope.operation_id)
    if (
        run is None
        or run.verification['ended_at'] is not None
        or type(driver) is not ClosedBrowserCase
    ):
        raise StorageUnavailable('Original Testing browser case is unavailable')
    original = next((row for row in run.cases if row.scope == case.scope), None)
    if (
        original is None
        or original.command['id'] != case.command['id']
        or not original.applications
    ):
        raise StorageUnavailable('Original Testing browser case differs')
    if original.command['ended_at'] is not None:
        return
    operation = run.operation['id']
    observed = {}
    for _, role, scope, receipt in driver.traffic:
        previous = observed.setdefault(scope, (role, receipt))
        if previous != (role, receipt):
            raise StorageUnavailable('Original Testing browser application receipt differs')
    outcomes = []
    for application, completion in zip(original.applications, services, strict=True):
        if type(completion) is ProjectCheckUndispatched:
            if completion.scope != application.scope or completion.check != original.check:
                raise StorageUnavailable('Original Testing browser application scope differs')
            process, binding, exit_code, integrity, prepared = (
                None,
                None,
                None,
                'NOT_CHECKED',
                False,
            )
        else:
            if (
                completion.result.scope != application.scope
                or completion.result.check != original.check
            ):
                raise StorageUnavailable('Original Testing browser application scope differs')
            process, binding = project_process_facts(
                completion, application.fixed['admission']['runner_manifest_sha256']
            )
            exit_code, integrity = completion.result.exit_code, completion.result.source_integrity
            prepared = completion.prepared is not None
        seen = observed.pop(application.scope, None)
        if seen is not None and (
            type(completion) is ProjectCheckUndispatched
            or completion.created is None
            or seen != (application.fixed['role'], completion.created['native']['receipt_sha256'])
        ):
            raise StorageUnavailable('Original Testing browser application receipt differs')
        outcomes.append(
            (application, completion, (process, binding, exit_code), integrity, prepared, seen)
        )
    if observed:
        raise StorageUnavailable('Original Testing browser traffic crosses scope')
    process, binding, exit_code, integrity = _driver_facts(
        driver, original.fixed['admission']['runner_manifest_sha256']
    )
    for _, _, _, app_integrity, _, _ in outcomes:
        integrity = _integrity(integrity, app_integrity)
    outcome = driver.assertions[0] if driver.assertions and integrity == 'VERIFIED' else None
    reason = (
        None
        if outcome is not None
        else (
            'INPUT_CHANGED'
            if integrity == 'CHANGED'
            else {
                'CONFIG_NOT_READY': 'RESOURCE_MISSING',
                'TEST_ASSET_REVOKED': 'RESOURCE_MISSING',
                'CANCELLED': None,
                'UNAVAILABLE': 'ISOLATION_UNAVAILABLE',
                'UNKNOWN': 'EVIDENCE_INCOMPLETE',
            }.get(undispatched or driver.status, undispatched or 'EVIDENCE_INCOMPLETE')
        )
    )
    is_cancelled = undispatched == 'CANCELLED' or driver.status == 'CANCELLED'
    reference = _record_browser_member(
        connection,
        run,
        original,
        (process, binding, exit_code),
        'SUCCEEDED'
        if outcome is not None
        else 'CANCELLED'
        if is_cancelled
        else 'FAILED'
        if reason in ('RESOURCE_MISSING', 'ISOLATION_UNAVAILABLE', 'INPUT_CHANGED', 'TIMEOUT')
        else 'UNKNOWN',
        driver.prepared is not None,
        {
            'native': driver.released,
            'case_id': original.case_id,
            'traffic': [
                [n, role, asdict(scope), digest] for n, role, scope, digest in driver.traffic
            ],
        },
        at,
    )
    seen_ids = []
    for application, completion, facts, _, prepared, seen in outcomes:
        if seen:
            seen_ids.append(application.command['id'])
        _record_browser_member(
            connection,
            run,
            application,
            facts,
            'SUCCEEDED' if seen else 'CANCELLED' if is_cancelled else 'FAILED',
            prepared,
            _receipt_facts(completion),
            at,
        )
    if outcome is not None:
        _save_case_result(connection, original.item['id'], outcome, at)
        _save_browser_integration(
            connection, operation, original, original.applications, seen_ids, reference
        )
    if (
        outcome is not None
        and run.task['status'] == 'WAITING'
        and run.operation['status'] == 'UNKNOWN'
        and run.task['control_generation'] == original.scope.control_generation
        and any(part.command['status'] == 'PENDING' for part in run.cases)
    ):
        connection.execute(
            """UPDATE code_waiting_items SET status='RESOLVED',resolved_at=?,resolution_ref=?
               WHERE testing_task_id=? AND source_kind='OPERATION' AND source_id=?
               AND kind='OPERATION_RESULT' AND status='OPEN'""",
            (
                at,
                compact({'command_execution_id': original.command['id']}),
                run.task['id'],
                operation,
            ),
        )
    _set_case_reason(connection, original.item, reason)
    connection.execute(
        """UPDATE code_verifications SET source_integrity_status=?,stop_status='VERIFIED',
           cleanup_status='VERIFIED' WHERE id=?""",
        (
            _integrity(run.verification['source_integrity_status'], integrity),
            run.verification['id'],
        ),
    )


def _finish_items(connection, run, at):
    integrity = run.verification['source_integrity_status']
    connection.execute(
        """UPDATE code_verification_items SET result=?,reason_code=?,
           started_at=COALESCE(started_at,?),ended_at=?
           WHERE verification_id=? AND evidence_kind='CONTENT_INTEGRITY'""",
        (
            {
                'VERIFIED': 'PASSED',
                'CHANGED': 'FAILED',
                'UNKNOWN': 'UNKNOWN',
                'NOT_CHECKED': 'NOT_RUN',
            }[integrity],
            {
                'VERIFIED': None,
                'CHANGED': 'INPUT_CHANGED',
                'UNKNOWN': 'EVIDENCE_INCOMPLETE',
                'NOT_CHECKED': None,
            }[integrity],
            at,
            at,
            run.verification['id'],
        ),
    )
    items = connection.execute(
        """SELECT * FROM code_verification_items WHERE verification_id=?
           AND evidence_kind='CONTROLLED_CASES' ORDER BY id""",
        (run.verification['id'],),
    ).fetchall()
    for item in items:
        reason = item['reason_code']
        if item['failed_case_count']:
            result = 'FAILED'
            reason = reason or 'ASSERTION_FAILED'
        elif item['expected_case_count'] == item['passed_case_count']:
            result = 'PASSED'
        elif (
            any(
                part.item['id'] == item['id'] and part.command['status'] == 'CANCELLED'
                for part in run.cases
            )
            and reason is None
        ):
            result = 'CANCELLED'
        else:
            result = _RESULT_BY_REASON.get(reason, 'UNKNOWN')
            if reason is None:
                reason = 'EVIDENCE_INCOMPLETE'
        connection.execute(
            """UPDATE code_verification_items SET result=?,reason_code=?,
               started_at=COALESCE(started_at,?),ended_at=? WHERE id=?""",
            (result, reason, at, at, item['id']),
        )


def _report_result(connection, run, uncovered):
    items = connection.execute(
        "SELECT result FROM code_verification_items WHERE verification_id=? AND evidence_kind='CONTROLLED_CASES'",
        (run.verification['id'],),
    )
    results = {item['result'] for item in items}
    if run.verification['source_integrity_status'] == 'CHANGED':
        return 'FAILED'
    for result in ('FAILED', 'UNKNOWN', 'UNAVAILABLE', 'CANCELLED'):
        if result in results:
            return result
    if run.verification['source_integrity_status'] != 'VERIFIED':
        return 'UNKNOWN'
    return 'INCONCLUSIVE' if uncovered or results != {'PASSED'} else 'PASSED'


def _save_findings(connection, run, report, definitions, at):
    rows = connection.execute(
        """SELECT c.* FROM code_verification_case_results c JOIN code_verification_items i
           ON i.id=c.item_id WHERE i.verification_id=? AND c.result='FAILED' ORDER BY i.id,c.case_id""",
        (run.verification['id'],),
    ).fetchall()
    for row in rows:
        case = definitions[row['case_id']]
        basis = None if not case.basis_refs else canonical_input(asdict(case.basis_refs[0]))
        identity = entity_id(connection, EntityKind.TESTING_FINDING)
        connection.execute(
            """INSERT INTO testing_findings(id,test_report_id,item_id,case_id,actual_behavior,
               expected_behavior,basis_ref,classification,state_version,created_at)
               VALUES(?,?,?,?,?,?,?,'UNCLASSIFIED',1,?)""",
            (
                identity,
                report,
                row['item_id'],
                row['case_id'],
                '受控断言失败：' + case.name,
                '满足固定用例的全部断言：' + case.name,
                basis,
                at,
            ),
        )


def finish_run(connection, operation_id, definitions, at):
    run = read_original_run(connection, operation_id)
    if (
        run is None
        or run.verification['ended_at'] is not None
        or any(item.command['ended_at'] is None for item in run.cases)
    ):
        return False
    _finish_items(connection, run, at)
    prepared = (
        connection.execute(
            """SELECT 1 FROM code_runtime_observations
           WHERE operation_id=? AND testing_task_id=? AND kind='PREPARE' AND result='VERIFIED'""",
            (operation_id, run.task['id']),
        ).fetchone()
        is not None
    )
    stopping = run.task['status'] == 'STOPPING'
    retired = run.task['control_generation'] != run.operation['control_generation']
    plan = _version(connection, run.pack['plan_version_id'])
    if plan is None:
        raise StorageUnavailable('Original Testing report plan disappeared')
    manual, uncovered = (
        [row['behavior_id'] for row in plan['behaviors'] if row['mode'] == mode]
        for mode in ('MANUAL', 'UNCOVERED')
    )
    result = 'CANCELLED' if stopping or retired else _report_result(connection, run, uncovered)
    verification_status = {'UNKNOWN': 'UNKNOWN', 'CANCELLED': 'CANCELLED'}.get(result, 'FINISHED')
    connection.execute(
        """UPDATE code_verifications SET status=?,stop_status='VERIFIED',cleanup_status='VERIFIED',ended_at=?
           WHERE id=? AND ended_at IS NULL""",
        (verification_status, at, run.verification['id']),
    )
    for step in ('MATERIALIZE', 'PREPARE'):
        _finish_step(
            connection, operation_id, step, at, status='SUCCEEDED' if prepared else 'CANCELLED'
        )
    execution = connection.execute(
        'SELECT result_ref FROM code_operation_steps WHERE operation_id=? AND step_no=?',
        (operation_id, EXECUTE),
    ).fetchone()['result_ref']
    _finish_step(
        connection,
        operation_id,
        'EXECUTE',
        at,
        status='SUCCEEDED' if prepared else 'CANCELLED',
        result=None if execution is None else strict_json_object(execution),
    )
    _finish_step(connection, operation_id, 'STOP', at)
    _finish_step(
        connection,
        operation_id,
        'VERIFY_INPUT',
        at,
        status='SUCCEEDED'
        if run.verification['source_integrity_status'] == 'VERIFIED'
        else 'FAILED',
    )
    _finish_step(connection, operation_id, 'CLEANUP', at)
    connection.execute(
        """UPDATE code_waiting_items SET status='RESOLVED',resolved_at=?,resolution_ref=?
           WHERE testing_task_id=? AND source_kind='OPERATION' AND source_id=?
           AND kind='OPERATION_RESULT' AND status='OPEN'""",
        (at, compact({'operation_id': operation_id}), run.task['id'], operation_id),
    )
    if stopping or retired:
        _finish_step(connection, operation_id, 'SAVE_REPORT', at, status='CANCELLED')
        connection.execute(
            "UPDATE code_operations SET status='CANCELLED',failure_code=NULL,ended_at=? WHERE id=?",
            (at, operation_id),
        )
        return True
    report = entity_id(connection, EntityKind.TEST_REPORT)
    fingerprint = strict_json_object(run.operation['fixed_input'])['input_fingerprint']
    connection.execute(
        """INSERT INTO testing_reports(id,testing_task_id,verification_id,plan_version_id,
           test_pack_version_id,input_fingerprint,result,scope_stages,manual_coverage_ids,
           uncovered_behavior_ids,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            report,
            run.task['id'],
            run.verification['id'],
            run.pack['plan_version_id'],
            run.pack['id'],
            fingerprint,
            result,
            run.verification['scope_stages'],
            compact(manual),
            compact(uncovered),
            at,
        ),
    )
    _save_findings(connection, run, report, definitions, at)
    _finish_step(connection, operation_id, 'SAVE_REPORT', at, result={'report_id': report})
    status = 'FAILED' if result == 'UNKNOWN' else 'SUCCEEDED'
    failure = 'EVIDENCE_INCOMPLETE' if result == 'UNKNOWN' else None
    connection.execute(
        'UPDATE code_operations SET status=?,failure_code=?,ended_at=? WHERE id=?',
        (status, failure, at, operation_id),
    )
    updated = connection.execute(
        """UPDATE testing_tasks SET report_id=?,active_operation_id=NULL,status='COMPLETED',
           phase='FINISHED',state_version=?,ended_at=? WHERE id=? AND active_operation_id=?
           AND state_version=? AND control_generation=?
           AND status IN ('RUNNING','WAITING') AND stop_requested_at IS NULL""",
        (
            report,
            increment(run.task['state_version']),
            at,
            run.task['id'],
            operation_id,
            run.task['state_version'],
            run.operation['control_generation'],
        ),
    )
    if updated.rowcount != 1:
        raise StorageUnavailable('Original Testing report finalization was fenced')
    return True
