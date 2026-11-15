"""Judge the original positive and negative child executions against one sealed pack."""

from hashlib import sha256

from backend.app.code_tasks.repository_operations import _time
from backend.app.infrastructure.check_case_evidence import validated_assertions
from backend.app.infrastructure.check_runner_bundle import CheckResourceError, valid_sha256
from backend.app.infrastructure.guard_request_header import PROTOCOL, TESTING_CHECK_PROTOCOL
from backend.app.shared.validation import (
    raw_text,
    strict_integer,
    strict_json_loads,
    strict_json_object,
)

from .http_evidence import check_http_assertions
from .pack_compile import digest, encoded
from .run_ownership import read_original_run
from .run_records import EXECUTE


def expected_checks(compiled):
    required = {
        f'controlled-{number}': {
            case.case_id: {assertion.assertion_id for assertion in case.assertions}
            for case in member.cases
        }
        for number, member in enumerate(compiled.case_packs, 1)
    }
    stages = compiled.check_set.value()['items'][0]['stages']
    return stages, {'content-integrity': {}, **required}


def _case_facts(connection, item, assertions):
    rows = connection.execute(
        'SELECT * FROM code_verification_case_results WHERE item_id=? ORDER BY case_id',
        (item['id'],),
    ).fetchall()
    if (
        len(rows) != len(assertions)
        or set(assertions) != {row['case_id'] for row in rows}
        or item['expected_case_count'] != len(rows)
        or item['executed_case_count'] != len(rows)
    ):
        return None
    failed = set()
    for row in rows:
        try:
            values = validated_assertions(
                strict_json_loads(row['assertion_results'], 'assertion_results'),
                assertions[row['case_id']],
            )
        except (CheckResourceError, TypeError, ValueError):
            return None
        if (
            row['capture_status'] not in ('FULL', 'REDACTED')
            or row['result'] not in ('PASSED', 'FAILED')
            or (row['result'] == 'FAILED') != any(value['result'] == 'FAILED' for value in values)
        ):
            return None
        if row['result'] == 'FAILED':
            failed.add(row['case_id'])
    if (
        (item['result'] == 'FAILED') != bool(failed)
        or item['failed_case_count'] != len(failed)
        or item['passed_case_count'] != len(rows) - len(failed)
    ):
        return None
    return failed


def _bound_command(command, verification, driver):
    if command['process_identity'] is None or command['runtime_binding'] is None:
        return None
    binding = strict_json_object(command['runtime_binding'])
    process = strict_json_object(command['process_identity'])
    if set(process) != {'pid', 'created_at', 'ownership_ref'}:
        return None
    strict_integer(process['pid'], 'pid', maximum=(1 << 32) - 1)
    _time(process['created_at'], nullable=False)
    raw_text(process['ownership_ref'], 'ownership_ref', 1, 1024)
    status_matches = (
        command['status'] == 'SUCCEEDED'
        if driver == 'HTTP'
        else command['status'] == ('SUCCEEDED' if command['exit_code'] == 0 else 'FAILED')
    )
    run_kind = 'CHECK_DRIVER' if driver == 'BROWSER' else 'TASK'
    protocol = PROTOCOL if driver == 'BROWSER' else TESTING_CHECK_PROTOCOL
    if (
        set(binding)
        != {
            'runtime_policy_version',
            'run_kind',
            'guard_run_ref',
            'appcontainer_profile_ref',
            'job_refs',
            'manifest_ref',
        }
        or binding['run_kind'] != run_kind
        or binding['runtime_policy_version'] != protocol
        or any(
            type(binding[field]) is not str or not binding[field]
            for field in ('appcontainer_profile_ref', 'guard_run_ref', 'manifest_ref')
        )
        or type(binding['job_refs']) is not list
        or not binding['job_refs']
        or any(type(ref) is not str or not ref for ref in binding['job_refs'])
        or len(binding['job_refs']) != len(set(binding['job_refs']))
        or process['ownership_ref'] != binding['guard_run_ref']
        or command['started_at'] is None
        or command['ended_at'] is None
        or type(command['exit_code']) is not int
        or not 0 <= command['exit_code'] <= 0xFFFFFFFF
        or not status_matches
        or (driver == 'BROWSER' and command['exit_code'] != 0)
        or not verification['created_at'] <= process['created_at'] <= command['ended_at']
        or not verification['created_at'] <= command['started_at'] <= command['ended_at']
        or verification['ended_at'] is None
        or command['ended_at'] > verification['ended_at']
    ):
        return None
    return binding


def _owned_observations(connection, command, task, verification, binding):
    rows = connection.execute(
        """SELECT kind,result,active_process_count,observed_at,runtime_binding_ref,evidence_ref
           FROM code_runtime_observations WHERE testing_task_id=? AND task_id IS NULL
           AND operation_id=? AND command_id=? AND control_generation=?
           AND kind IN ('PREPARE','STOP','CLEANUP') ORDER BY observed_at,id""",
        (task['id'], verification['operation_id'], command['id'], task['control_generation']),
    ).fetchall()
    expected = {'PREPARE': None, 'STOP': 0, 'CLEANUP': 0}
    if (
        len(rows) != len(expected)
        or {row['kind'] for row in rows} != set(expected)
        or len({row['evidence_ref'] for row in rows}) != 1
        or any(
            row['result'] != 'VERIFIED'
            or row['runtime_binding_ref'] != binding['guard_run_ref']
            or row['active_process_count'] != expected[row['kind']]
            or not verification['created_at'] <= row['observed_at'] <= verification['ended_at']
            or not row['evidence_ref'].startswith('testing-check:sha256:')
            or not valid_sha256(row['evidence_ref'].removeprefix('testing-check:sha256:'))
            for row in rows
        )
    ):
        return False
    return rows[0]['evidence_ref']


def _owned_project_case(connection, command, task, verification, item, case, binding, driver):
    if not _owned_observations(connection, command, task, verification, binding):
        return False
    if driver == 'CLI' and command['command_ref'] != case.steps[0].operands[0]:
        return False
    saved = connection.execute(
        """SELECT assertion_results,capture_status,observed_at FROM code_verification_case_results
           WHERE item_id=? AND case_id=?""",
        (item['id'], case.case_id),
    ).fetchone()
    if saved is None or not command['ended_at'] <= saved['observed_at'] <= verification['ended_at']:
        return False
    values = strict_json_loads(saved['assertion_results'], 'assertion_results')
    if driver == 'HTTP':
        operation = connection.execute(
            """SELECT fixed_input FROM code_operations WHERE id=? AND testing_task_id=?
               AND task_id IS NULL AND operation_type='RUN_TEST'""",
            (verification['operation_id'], task['id']),
        ).fetchone()
        if operation is None:
            return False
        original = strict_json_object(operation['fixed_input'])
        facts = original.get('facts')
        if type(facts) is not dict or digest(encoded(facts)) != verification['input_fingerprint']:
            return False
        exact = [
            entry
            for entry in facts['runtime']['cases']
            if entry['check_id'] == item['check_id'] and entry['case_id'] == case.case_id
        ]
        if (
            len(exact) != 1
            or exact[0]['admission']['command_id'] != command['command_ref']
            or any(step.operands[0] != exact[0]['endpoint_ref'] for step in case.steps)
        ):
            return False
        try:
            _, redacted = check_http_assertions(case, values)
        except CheckResourceError:
            return False
        return saved['capture_status'] == ('REDACTED' if redacted else 'FULL')
    assertions = {
        row['assertion_id']: row
        for row in validated_assertions(values, {entry.assertion_id for entry in case.assertions})
    }
    if driver == 'BROWSER':
        return _browser_assertions(case, assertions, saved['capture_status'])
    for definition in case.assertions:
        value = assertions[definition.assertion_id]
        (expected_value,) = definition.operands
        actual = value['actual_value']
        if definition.op == 'EXIT_CODE':
            if type(actual) is not int or actual != command['exit_code']:
                return False
            matches = actual == expected_value
        elif definition.op == 'STDOUT_BYTES':
            if (
                type(actual) is not str
                or not actual.startswith('sha256:')
                or not valid_sha256(actual[7:])
            ):
                return False
            matches = actual[7:] == sha256(expected_value).hexdigest()
        else:
            return False
        if (value['result'] == 'PASSED') != matches:
            return False
    return True


def _browser_assertions(case, assertions, capture_status):
    redacted = False
    for definition in case.assertions:
        value = assertions[definition.assertion_id]
        actual = value['actual_value']
        expected = definition.operands[-1]
        if definition.op == 'TEXT':
            if (
                type(actual) is not str
                or not actual.startswith('sha256:')
                or not valid_sha256(actual[7:])
            ):
                return False
            expected = 'sha256:' + sha256(expected.encode('utf-8')).hexdigest()
            redacted = True
        elif definition.op == 'VISIBLE':
            if type(actual) is not bool:
                return False
        elif definition.op == 'COUNT':
            if type(actual) is not int or actual < 0:
                return False
        else:
            return False
        if (actual == expected) != (value['result'] == 'PASSED'):
            return False
    return capture_status == ('REDACTED' if redacted else 'FULL')


def owned_browser_integration(connection, task, verification, item):
    run = read_original_run(connection, verification['operation_id'])
    if run is None or run.task['id'] != task['id'] or run.verification['id'] != verification['id']:
        return False
    step = connection.execute(
        'SELECT result_ref FROM code_operation_steps WHERE operation_id=? AND step_no=?',
        (verification['operation_id'], EXECUTE),
    ).fetchone()
    if step is None or step['result_ref'] is None:
        return False
    records = strict_json_object(step['result_ref']).get('browser_cases')
    if type(records) is not list:
        return False
    for case in run.cases:
        if case.item['id'] != item['id'] or not case.applications:
            continue
        driver = case.command
        binding = _bound_command(driver, verification, 'BROWSER')
        if binding is None:
            continue
        evidence = _owned_observations(connection, driver, task, verification, binding)
        expected = {
            'driver_command_id': driver['id'],
            'item_id': item['id'],
            'case_id': case.case_id,
            'applications': [
                {'command_id': app.command['id'], 'role': app.fixed['role']}
                for app in case.applications
            ],
            'evidence_ref': evidence,
        }
        if not evidence or records.count(expected) != 1:
            continue
        identities = {driver['process_identity']}
        profiles = {binding['appcontainer_profile_ref']}
        jobs = set(binding['job_refs'])
        for app in case.applications:
            runtime = _bound_command(app.command, verification, 'HTTP')
            if (
                runtime is None
                or runtime['manifest_ref'] != app.fixed['admission']['runner_manifest_sha256']
                or not _owned_observations(connection, app.command, task, verification, runtime)
                or app.command['process_identity'] in identities
                or runtime['appcontainer_profile_ref'] in profiles
                or jobs.intersection(runtime['job_refs'])
            ):
                break
            identities.add(app.command['process_identity'])
            profiles.add(runtime['appcontainer_profile_ref'])
            jobs.update(runtime['job_refs'])
        else:
            if binding['manifest_ref'] == case.fixed['admission']['runner_manifest_sha256']:
                return True
    return False


def owned_check_fact(connection, task, verification, item, group):
    if item['command_execution_id'] is None or group is None:
        return None
    rows = connection.execute(
        """SELECT * FROM code_commands WHERE testing_task_id=? AND task_id IS NULL
           AND operation_id=? AND verification_item_id=? AND testing_profile_version_id=?
           AND purpose='CHECK' ORDER BY id""",
        (
            task['id'],
            verification['operation_id'],
            item['id'],
            task['profile_version_id'],
        ),
    ).fetchall()
    expected = len(group.cases)
    if len(rows) != expected or not rows or rows[0]['id'] != item['command_execution_id']:
        return None
    for index, command in enumerate(rows):
        binding = _bound_command(command, verification, group.driver_kind)
        if binding is None or not _owned_project_case(
            connection,
            command,
            task,
            verification,
            item,
            group.cases[index],
            binding,
            group.driver_kind,
        ):
            return None
    return rows[0]


def _owned_close(connection, child, verification):
    observations = connection.execute(
        """SELECT kind,result,active_process_count,observed_at FROM code_runtime_observations
           WHERE testing_task_id=? AND task_id IS NULL AND operation_id=? AND control_generation=?
           AND kind IN ('STOP','CLEANUP') ORDER BY observed_at,id""",
        (child['id'], verification['operation_id'], child['control_generation']),
    )
    latest = {row['kind']: row for row in observations}
    return verification['ended_at'] is not None and all(
        kind in latest
        and latest[kind]['result'] == 'VERIFIED'
        and latest[kind]['active_process_count'] == 0
        and verification['created_at'] <= latest[kind]['observed_at'] <= verification['ended_at']
        for kind in ('STOP', 'CLEANUP')
    )


def _child_failure_cases(connection, pack, child, scope, checks, groups):
    if (
        child['status'] != 'COMPLETED'
        or child['report_id'] is None
        or child['current_verification_id'] is None
    ):
        return None
    report = connection.execute(
        """SELECT * FROM testing_reports WHERE id=? AND testing_task_id=? AND verification_id=?
           AND plan_version_id=? AND test_pack_version_id=?""",
        (
            child['report_id'],
            child['id'],
            child['current_verification_id'],
            pack['plan_version_id'],
            pack['id'],
        ),
    ).fetchone()
    verification = connection.execute(
        """SELECT * FROM code_verifications WHERE id=? AND owner_kind='TESTING' AND testing_task_id=?
           AND task_id IS NULL AND snapshot_id=? AND candidate_id IS NULL AND purpose='PACK_VALIDATION'
           AND testing_profile_version_id=? AND check_set_version_id=?""",
        (
            child['current_verification_id'],
            child['id'],
            child['snapshot_id'],
            child['profile_version_id'],
            pack['check_set_version_id'],
        ),
    ).fetchone()
    if (
        report is None
        or verification is None
        or report['result'] not in ('PASSED', 'FAILED')
        or not valid_sha256(report['input_fingerprint'])
        or strict_json_loads(report['scope_stages'], 'scope_stages') != scope
        or strict_json_loads(verification['scope_stages'], 'scope_stages') != scope
        or strict_json_loads(verification['selected_check_ids'], 'selected_check_ids')
        != list(checks)
        or verification['status'] != 'FINISHED'
        or verification['ended_at'] is None
        or report['created_at'] < verification['ended_at']
        or child['ended_at'] < report['created_at']
        or any(
            verification[key] != 'VERIFIED'
            for key in (
                'stop_status',
                'cleanup_status',
                'source_integrity_status',
            )
        )
        or not _owned_close(connection, child, verification)
    ):
        return None
    original = connection.execute(
        """SELECT fixed_input FROM code_operations WHERE id=? AND testing_task_id=? AND task_id IS NULL
           AND resource_kind='TESTING_TASK' AND resource_id=? AND operation_type='RUN_TEST'
           AND control_generation=? AND status='SUCCEEDED'""",
        (verification['operation_id'], child['id'], child['id'], child['control_generation']),
    ).fetchone()
    if (
        original is None
        or strict_json_object(original['fixed_input']).get('input_fingerprint')
        != report['input_fingerprint']
    ):
        return None
    items = connection.execute(
        'SELECT * FROM code_verification_items WHERE verification_id=?',
        (verification['id'],),
    ).fetchall()
    if len(items) != len(checks) or {item['check_id'] for item in items} != set(checks):
        return None
    failed = set()
    for item in items:
        if (
            not item['required']
            or item['result'] not in ('PASSED', 'FAILED')
            or item['reused_from_item_id'] is not None
        ):
            return None
        if item['check_id'] == 'content-integrity':
            if item['evidence_kind'] != 'CONTENT_INTEGRITY' or item['result'] != 'PASSED':
                return None
            continue
        if (
            item['evidence_kind'] != 'CONTROLLED_CASES'
            or owned_check_fact(connection, child, verification, item, groups.get(item['check_id']))
            is None
        ):
            return None
        observed = _case_facts(connection, item, checks[item['check_id']])
        if observed is None or failed.intersection(observed):
            return None
        failed.update(observed)
    return failed if (report['result'] == 'FAILED') == bool(failed) else None


def passing_children(connection, pack, compiled, children, samples):
    if len(children) != len(samples) or not children:
        return False
    scope, checks = expected_checks(compiled)
    groups = {f'controlled-{index}': group for index, group in enumerate(compiled.case_packs, 1)}
    for child, sample in zip(children, samples, strict=True):
        if child['snapshot_id'] != sample['snapshot_id']:
            return False
        failures = _child_failure_cases(connection, pack, child, scope, checks, groups)
        expected = set(sample['expected_failed_case_ids'])
        if failures is None or (not expected and failures) or not expected.issubset(failures):
            return False
    return True
