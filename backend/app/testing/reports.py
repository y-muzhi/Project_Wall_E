"""Immutable Testing report facts with independently recomputed delivery eligibility."""

from contextlib import ExitStack
from time import monotonic

from backend.app.code_tasks.check_set_content import STAGES
from backend.app.code_tasks.configuration_identities import require_schema
from backend.app.code_tasks.operation_protocol import operation_steps
from backend.app.code_tasks.repository_baseline_query import read_registered_baseline
from backend.app.code_tasks.repository_operations import _time
from backend.app.code_tasks.task_candidate_reads import _available as candidate_available
from backend.app.code_tasks.task_candidate_reads import _saved as saved_candidate
from backend.app.code_tasks.task_testing_publication import read_candidate_publication
from backend.app.code_tasks.task_verification_reads import _saved as coding_verification_view
from backend.app.infrastructure.check_runner_bundle import (
    reference,
    valid_sha256,
)
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import (
    strict_enum,
    strict_integer,
    strict_json_loads,
    strict_json_object,
)

from .assets import NOT_FOUND, _read
from .pack_compile import CompileError
from .pack_definitions import compiled_definition, hold_compiled_pack_assets
from .pack_seal import RESOURCE_ERRORS
from .pack_validation import find_registered_reference, original_validation, validation_schedule
from .plan_content import BASIS_FIELDS, parse_fixed_basis
from .plans import _version
from .reference_resources import hold_reference_set, original_baselines
from .tasks import PURPOSES, TARGETS, materials_for, optional_id, read_task_row
from .validation_evidence import owned_browser_integration, owned_check_fact, passing_children
from .verification_reads import _owned, _saved

REPORT_FIELDS = (
    'id',
    'testing_task_id',
    'verification_id',
    'plan_version_id',
    'test_pack_version_id',
    'input_fingerprint',
    'result',
    'scope_stages',
    'manual_coverage_ids',
    'uncovered_behavior_ids',
    'created_at',
)
PROVENANCE_FIELDS = (
    *BASIS_FIELDS,
    'target_kind',
    'candidate_id',
    'snapshot_id',
    'profile_version_id',
    'purpose',
    'source_code_task_id',
)
FIELDS = (
    *REPORT_FIELDS,
    'provenance',
    'eligible',
    'delivery_eligible',
    'ineligibility_reason_codes',
    'delivery_ineligibility_reason_codes',
)
REASONS = (
    'RESULT_NOT_PASSED',
    'TEST_ASSET_REVOKED',
    'SCOPE_INCOMPLETE',
    'DESIGN_MISMATCH',
    'TARGET_NOT_CURRENT',
    'NOT_CODING_CANDIDATE',
    'NOT_ACCEPTANCE',
    'CODING_CHAIN_INCOMPLETE',
    'UNCOVERED_BEHAVIOR',
    'ACTIVITY_NOT_STOPPED',
    'EVIDENCE_INCOMPLETE',
)


def project_report(value, *, report_id=None, task_id=None):
    row = exact(value, FIELDS)
    for key in REPORT_FIELDS[:5]:
        strict_integer(row[key], key)
    if (
        report_id is not None
        and row['id'] != report_id
        or task_id is not None
        and row['testing_task_id'] != task_id
    ):
        raise ValueError('Original Testing report crosses its scope')
    if not valid_sha256(row['input_fingerprint']):
        raise ValueError('Original Testing report has no input fingerprint')
    strict_enum(
        row['result'],
        'result',
        ('PASSED', 'FAILED', 'UNAVAILABLE', 'UNKNOWN', 'CANCELLED', 'INCONCLUSIVE'),
    )
    scope = row['scope_stages']
    if type(scope) is not list or scope != [stage for stage in STAGES if stage in scope]:
        raise ValueError('Original Testing report scope differs')
    _time(row['created_at'], nullable=False)
    for key in ('manual_coverage_ids', 'uncovered_behavior_ids'):
        values = row[key]
        if type(values) is not list or len(values) != len(set(values)):
            raise ValueError('Original Testing report coverage differs')
        for item in values:
            reference(item)
    if set(row['manual_coverage_ids']) & set(row['uncovered_behavior_ids']):
        raise ValueError('Original Testing report coverage overlaps')
    source = exact(row['provenance'], PROVENANCE_FIELDS)
    basis = parse_fixed_basis(source)
    if any(source[key] != expected for key, expected in basis.items()):
        raise ValueError('Original Testing report fixed basis differs')
    strict_enum(source['purpose'], 'purpose', PURPOSES)
    strict_enum(source['target_kind'], 'target_kind', TARGETS)
    strict_integer(source['profile_version_id'], 'profile_version_id')
    for key in ('candidate_id', 'snapshot_id', 'source_code_task_id'):
        optional_id(source[key], key)
    coding = source['target_kind'] == 'CANDIDATE'
    if (source['candidate_id'] is not None) != coding or (
        (source['source_code_task_id'] is not None) != coding
        or (source['snapshot_id'] is not None) == coding
    ):
        raise ValueError('Original Testing report target differs')
    for flag, key in (
        ('eligible', 'ineligibility_reason_codes'),
        ('delivery_eligible', 'delivery_ineligibility_reason_codes'),
    ):
        reasons = row[key]
        if (
            type(row[flag]) is not bool
            or type(reasons) is not list
            or reasons != [item for item in REASONS if item in reasons]
            or row[flag] != (not reasons)
        ):
            raise ValueError('Original Testing report eligibility differs')
    if not set(row['ineligibility_reason_codes']).issubset(
        row['delivery_ineligibility_reason_codes']
    ):
        raise ValueError('Original Testing delivery reasons differ')
    return row


def original_report(connection, row):
    task = read_task_row(connection, row['testing_task_id'])
    if task is None:
        raise StorageUnavailable('Original Testing report owner is missing')
    scope = _owned(connection, task['id'], row['verification_id'])
    if scope is None:
        raise StorageUnavailable('Original Testing report verification is missing')
    _, verification, pack = scope
    if (
        task['status'] != 'COMPLETED'
        or task['report_id'] != row['id']
        or row['plan_version_id'] != pack['plan_version_id']
        or row['test_pack_version_id'] != pack['id']
        or task['ended_at'] is None
        or task['ended_at'] < row['created_at']
        or verification['ended_at'] is None
        or verification['ended_at'] > row['created_at']
    ):
        raise StorageUnavailable('Original Testing report ancestry differs')
    return task, verification, pack


def _held_pack(connection, catalog, pack, *, held=None):
    installation = getattr(catalog, 'testing_assets', None)
    if installation is None:
        return False
    deadline = monotonic() + 5
    try:
        with ExitStack() as locked:
            compiled = locked.enter_context(
                hold_compiled_pack_assets(connection, installation, pack, deadline=deadline)
            )
            if pack['status'] == 'PUBLISHED':
                if pack['validation_id'] is None:
                    return False
                original = original_validation(connection, pack['validation_id'])
                if original is None:
                    return False
                validation, operation, fixed, children = original
                registration = find_registered_reference(
                    installation, compiled.basis_sha256, validation['reference_set_ref']
                )
                if (
                    registration is None
                    or validation['test_pack_version_id'] != pack['id']
                    or validation['result'] != 'PASSED'
                    or operation['status'] != 'SUCCEEDED'
                    or fixed['pack_sha256'] != pack['sha256']
                    or fixed['reference_sha256'] != registration.sha256
                    or fixed['samples'] != validation_schedule(registration.reference)
                    or original_baselines(connection, registration.reference) is None
                    or not passing_children(connection, pack, compiled, children, fixed['samples'])
                ):
                    return False
                locked.enter_context(hold_reference_set(registration, deadline=deadline))
            if held is not None:
                held.enter_context(locked.pop_all())
    except (OSError, CompileError, *RESOURCE_ERRORS):
        return False
    return True


def _coding_delivery(connection, catalog, admissions, task, candidate):
    coding = connection.execute(
        'SELECT * FROM code_tasks WHERE id=?', (candidate['task_id'],)
    ).fetchone()
    if coding is None:
        raise StorageUnavailable('Original report Coding provenance is missing')
    reasons = set()
    if coding['current_candidate_id'] != candidate['id']:
        reasons.add('TARGET_NOT_CURRENT')
    if any(coding[key] != task[key] for key in BASIS_FIELDS[:3]) or materials_for(
        connection, coding['id'], module='CODING'
    ) != materials_for(connection, task['id']):
        reasons.add('DESIGN_MISMATCH')
    if reasons:
        return reasons
    if candidate['publication_operation_id'] is None or candidate['role'] != 'INTEGRATION':
        reasons.add('CODING_CHAIN_INCOMPLETE')
    else:
        read_candidate_publication(connection, candidate)
        current = connection.execute(
            """SELECT * FROM code_verifications WHERE id=? AND task_id=? AND owner_kind='CODING'
               AND candidate_id=? AND role='INTEGRATION'""",
            (coding['current_verification_id'], coding['id'], candidate['id']),
        ).fetchone()
        if (
            current is None
            or not coding_verification_view(connection, catalog, admissions, coding, current)[
                'eligible'
            ]
        ):
            reasons.add('CODING_CHAIN_INCOMPLETE')
    return reasons


def _integration_observed(connection, task, verification, pack, items):
    _, compiled = compiled_definition(connection, pack)
    definitions = compiled.check_set.value()['items'][1:]
    observed = set()
    for definition, cases in zip(definitions, compiled.case_packs, strict=True):
        stages = set(definition['stages']).intersection(('INTEGRATION', 'ACCEPTANCE'))
        if not stages or cases.driver_kind not in ('HTTP', 'BROWSER'):
            continue
        if definition['target']['application_mode'] != 'REAL_CANDIDATE':
            continue
        if cases.driver_kind == 'HTTP' and len(definition['target']['command_ids']) < 2:
            # A single service's owned endpoint does not establish the deployed
            # frontend/backend connection required for final Coding acceptance.
            continue
        item = next((entry for entry in items if entry['check_id'] == definition['check_id']), None)
        if item is None or item['result'] != 'PASSED':
            continue
        command = owned_check_fact(connection, task, verification, item, cases)
        if command is None:
            continue
        if cases.driver_kind == 'BROWSER':
            if owned_browser_integration(connection, task, verification, item):
                observed.update(stages)
            continue
        prepared = connection.execute(
            """SELECT result,runtime_binding_ref FROM code_runtime_observations
               WHERE task_id IS NULL AND testing_task_id=? AND operation_id=? AND command_id=?
               AND control_generation=? AND kind='PREPARE' ORDER BY observed_at DESC,id DESC LIMIT 1""",
            (task['id'], verification['operation_id'], command['id'], task['control_generation']),
        ).fetchone()
        binding = strict_json_object(command['runtime_binding'])
        if (
            prepared is not None
            and prepared['result'] == 'VERIFIED'
            and prepared['runtime_binding_ref'] == binding['guard_run_ref']
        ):
            observed.update(stages)
    return observed == {'INTEGRATION', 'ACCEPTANCE'}


def _completed_run_steps(connection, original):
    if original is None or original['started_at'] is None or original['ended_at'] is None:
        return False
    rows = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (original['id'],),
    ).fetchall()
    steps = operation_steps('TESTING', 'RUN_TEST')
    if len(rows) != len(steps):
        return False
    previous = original['started_at']
    for number, (step, name) in enumerate(zip(rows, steps, strict=True), 1):
        if (
            step['step_no'] != number
            or step['step_type'] != name
            or step['status'] != 'SUCCEEDED'
            or any(step[key] is None for key in ('started_at', 'ended_at', 'last_observed_at'))
            or not previous
            <= step['started_at']
            <= step['ended_at']
            <= step['last_observed_at']
            <= original['ended_at']
        ):
            return False
        previous = step['ended_at']
    return True


def _view(connection, catalog, admissions, row, *, held=None):
    task, verification, pack = original_report(connection, row)
    v = _saved(connection, task, verification, pack)
    plan = _version(connection, row['plan_version_id'])
    if plan is None:
        raise StorageUnavailable('Original report plan is missing')
    data = {key: row[key] for key in REPORT_FIELDS}
    for key in ('scope_stages', 'manual_coverage_ids', 'uncovered_behavior_ids'):
        data[key] = strict_json_loads(row[key], key)
    materials = materials_for(connection, task['id'])
    provenance = {
        **{
            key: task[key]
            for key in PROVENANCE_FIELDS
            if key not in ('material_refs', 'source_code_task_id')
        },
        'material_refs': materials,
        'source_code_task_id': None,
    }
    candidate = None
    if task['candidate_id'] is not None:
        candidate = connection.execute(
            'SELECT * FROM code_candidates WHERE id=?', (task['candidate_id'],)
        ).fetchone()
        if candidate is None:
            raise StorageUnavailable('Original report candidate is missing')
        provenance['source_code_task_id'] = candidate['task_id']
    reasons = set()
    if row['result'] != 'PASSED':
        reasons.add('RESULT_NOT_PASSED')
    if 'TEST_ASSET_REVOKED' in v['ineligibility_reason_codes']:
        reasons.add('TEST_ASSET_REVOKED')
    if 'ACTIVITY_NOT_STOPPED' in v['ineligibility_reason_codes']:
        reasons.add('ACTIVITY_NOT_STOPPED')
    if any(
        key in v['ineligibility_reason_codes']
        for key in ('COVERAGE_NOT_READY', 'NO_CONTROLLED_CASES')
    ):
        reasons.add('SCOPE_INCOMPLETE')
    if any(plan[key] != provenance[key] for key in BASIS_FIELDS):
        reasons.add('DESIGN_MISMATCH')
    original_run = connection.execute(
        """SELECT * FROM code_operations WHERE id=? AND testing_task_id=? AND task_id IS NULL
           AND operation_type='RUN_TEST' AND resource_kind='TESTING_TASK' AND resource_id=?""",
        (verification['operation_id'], task['id'], task['id']),
    ).fetchone()
    if (
        original_run is None
        or strict_json_object(original_run['fixed_input']).get('input_fingerprint')
        != row['input_fingerprint']
        or original_run['status'] != 'SUCCEEDED'
        or original_run['control_generation'] != task['control_generation']
        or not _completed_run_steps(connection, original_run)
        or any(
            key in v['ineligibility_reason_codes']
            for key in (
                'EVIDENCE_INCOMPLETE',
                'REQUIRED_NOT_PASSED',
                'RESOURCE_NOT_READY',
            )
        )
    ):
        reasons.add('EVIDENCE_INCOMPLETE')
    selected = set(data['scope_stages'])
    for mode, field in (('MANUAL', 'manual_coverage_ids'), ('UNCOVERED', 'uncovered_behavior_ids')):
        expected = {
            behavior['behavior_id']
            for behavior in plan['behaviors']
            if behavior['mode'] == mode and selected.intersection(behavior['stages'])
        }
        if set(data[field]) != expected:
            reasons.add('EVIDENCE_INCOMPLETE')
    if data['scope_stages'] != v['scope_stages']:
        reasons.add('SCOPE_INCOMPLETE')
    if not reasons:
        if candidate is None:
            if read_registered_baseline(connection, task['snapshot_id']) is None:
                reasons.add('EVIDENCE_INCOMPLETE')
        else:
            _, package = saved_candidate(connection, candidate)
            if not candidate_available(package):
                reasons.add('EVIDENCE_INCOMPLETE')
    delivery = set(reasons)
    if candidate is None:
        delivery.add('NOT_CODING_CANDIDATE')
    else:
        delivery.update(_coding_delivery(connection, catalog, admissions, task, candidate))
    if task['purpose'] != 'ACCEPTANCE' or task['kind'] != 'PRODUCT':
        delivery.add('NOT_ACCEPTANCE')
    if data['scope_stages'] != list(STAGES):
        delivery.add('SCOPE_INCOMPLETE')
    if data['uncovered_behavior_ids']:
        delivery.add('UNCOVERED_BEHAVIOR')
    if not delivery and not _integration_observed(connection, task, verification, pack, v['items']):
        delivery.add('EVIDENCE_INCOMPLETE')
    if not reasons and not _held_pack(connection, catalog, pack, held=held):
        reasons.add('EVIDENCE_INCOMPLETE')
        delivery.add('EVIDENCE_INCOMPLETE')
    data.update(
        provenance=provenance,
        eligible=not reasons,
        delivery_eligible=not delivery,
        ineligibility_reason_codes=[item for item in REASONS if item in reasons],
        delivery_ineligibility_reason_codes=[item for item in REASONS if item in delivery],
    )
    return project_report(data, report_id=row['id'], task_id=task['id'])


def read_report(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        field = 'testing_task_id' if request.by_task else 'id'
        row = connection.execute(
            f'SELECT * FROM testing_reports WHERE {field}=?', (request.identity,)
        ).fetchone()
        if row is None:
            return NOT_FOUND.result
        try:
            return _read(_view(connection, runtime.catalog, request.admissions, row))
        except (KeyError, TypeError, ValueError) as error:
            raise StorageUnavailable('Original Testing report is unreadable') from error
