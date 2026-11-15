"""Shared structural checks for Coding settings/Testing compiler, no execution."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib

import pytest

from backend.app.code_tasks.check_set_content import parse_check_set_content, PROTOCOL
from backend.app.code_tasks.coding_check_plan import (
    CodingCheckPlanError,
    require_handoff_command_scope,
    select_handoff_checks,
)
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.shared.validation import InvalidInput


def integrity(**changes):
    return {
        'check_id': 'integrity',
        'name': '输入完整性',
        'stages': ['BACKEND'],
        'required': True,
        'check_kind': 'CONTROLLED_ASSERTION',
        'command_id': None,
        'runner_ref': 'controlled-runner',
        'case_pack_ref': None,
        'expected_exit_codes': None,
        'environment_refs': [],
        'protected_input_refs': [],
        'target': None,
        'timeout_seconds': 20,
        'evidence_rule': {'kind': 'CONTENT_INTEGRITY'},
        **changes,
    }


def cases(**changes):
    return integrity(
        check_id='functional',
        case_pack_ref='fixed-case-pack',
        target={
            'application_mode': 'REAL_CANDIDATE',
            'external_dependency_mode': 'OFFLINE_STUB',
            'command_ids': ['candidate-service'],
            'fixture_ref': None,
        },
        evidence_rule={'kind': 'CONTROLLED_CASES'},
        **changes,
    )


def command(**changes):
    return integrity(
        check_id='project-test',
        check_kind='PROJECT_COMMAND',
        command_id='project-tests',
        expected_exit_codes=[0],
        evidence_rule={'kind': 'PROCESS_EXIT'},
        **changes,
    )


def coverage(**changes):
    return {
        'coverage_id': 'behavior-1',
        'basis_refs': [{'document_id': 1, 'revision_id': 2, 'quote': '原始依据\n原行'}],
        'stages': ['BACKEND'],
        'mode': 'AUTO',
        'check_ids': ['functional'],
        'explanation': '',
        **changes,
    }


def body(items=None, coverage_plan=None, **extra):
    return {
        'protocol_version': PROTOCOL,
        'items': [integrity(), cases(), command()] if items is None else items,
        'coverage_plan': [coverage()] if coverage_plan is None else coverage_plan,
        **extra,
    }


def parse(value, owner='CODING', limit=65536):
    return parse_check_set_content(value, owner_module=owner, max_input_bytes=limit)


def test_complete_three_kinds_preserve_exact_input_and_freeze_private_content():
    source = body()
    original = deepcopy(source)
    value = parse(source)
    assert value.value() == original
    assert value.sha256 == hashlib.sha256(canonical_input(original).encode()).hexdigest()
    source['items'][0]['stages'].append('FRONTEND')
    copied = value.value()
    copied['items'][1]['target']['command_ids'].append('other')
    assert value.value() == original
    with pytest.raises(FrozenInstanceError):
        value.owner_module = 'TESTING'
    assert '原始依据' not in repr(value)


def test_empty_draft_structure_does_not_invent_checks_or_claim_readiness():
    value = parse(body(items=[], coverage_plan=[]))
    assert value.value() == {'protocol_version': PROTOCOL, 'items': [], 'coverage_plan': []}
    assert not hasattr(value, 'ready') and not hasattr(value, 'passed')


def test_testing_compiler_can_use_acceptance_coding_settings_cannot():
    value = body(
        items=[cases(stages=['ACCEPTANCE'])], coverage_plan=[coverage(stages=['ACCEPTANCE'])]
    )
    assert parse(value, 'TESTING').owner_module == 'TESTING'
    with pytest.raises(InvalidInput):
        parse(value, 'CODING')


@pytest.mark.parametrize(
    'name,value',
    [
        ('owner_module', 'TESTING'),
        ('id', 1),
        ('version', 2),
        ('created_at', 'now'),
        ('ready', True),
        ('required_markers', ['PASS']),
        ('stdout', 'PASSED'),
    ],
)
def test_client_cannot_set_server_or_removed_result_fields(name, value):
    with pytest.raises(InvalidInput):
        parse(body(**{name: value}))


@pytest.mark.parametrize(
    'changes',
    [
        {'required': 1},
        {'timeout_seconds': True},
        {'timeout_seconds': 0},
        {'timeout_seconds': 2**53},
        {'stages': []},
        {'stages': ['BACKEND', 'BACKEND']},
        {'stages': ['ACCEPTANCE']},
        {'stages': ['backend']},
        {'runner_ref': None},
        {'runner_ref': ''},
        {'check_id': ' '},
        {'check_id': 'a\nb'},
        {'protected_input_refs': ['same', 'same']},
        {'environment_refs': ['same', 'same']},
        {'check_kind': 'EXIT_CODE_AND_MARKERS'},
        {'evidence_rule': {'kind': 'PASSED'}},
    ],
)
def test_bad_common_check_fields_rejected(changes):
    with pytest.raises(InvalidInput):
        parse(body(items=[integrity(**changes)], coverage_plan=[]))


@pytest.mark.parametrize(
    'changes',
    [
        {'command_id': None},
        {'expected_exit_codes': [False]},
        {'expected_exit_codes': []},
        {'expected_exit_codes': [0, 1]},
        {'expected_exit_codes': ['0']},
        {'case_pack_ref': 'case'},
        {'target': {}},
        {'evidence_rule': {'kind': 'CONTROLLED_CASES'}},
    ],
)
def test_project_exit_can_never_become_controlled_function_evidence(changes):
    value = command()
    value.update(changes)
    with pytest.raises(InvalidInput):
        parse(body(items=[value], coverage_plan=[]))


@pytest.mark.parametrize(
    'changes',
    [
        {'command_id': 'candidate-script'},
        {'expected_exit_codes': [0]},
        {'evidence_rule': {'kind': 'PROCESS_EXIT'}},
        {'case_pack_ref': 'case'},
        {'target': {}},
    ],
)
def test_integrity_does_not_accept_command_or_case_payload(changes):
    with pytest.raises(InvalidInput):
        parse(body(items=[integrity(**changes)], coverage_plan=[]))


@pytest.mark.parametrize(
    'changes',
    [
        {'case_pack_ref': None},
        {'target': None},
        {'command_id': 'project-test'},
        {'expected_exit_codes': [0]},
    ],
)
def test_controlled_cases_require_fixed_cases_and_target(changes):
    value = cases()
    value.update(changes)
    with pytest.raises(InvalidInput):
        parse(body(items=[value], coverage_plan=[]))


@pytest.mark.parametrize(
    'field,value',
    [
        ('application_mode', 'ARBITRARY_SCRIPT'),
        ('external_dependency_mode', 'LIVE'),
        ('command_ids', []),
        ('command_ids', ['x', 'x']),
        ('fixture_ref', ''),
        ('url', 'https://external.invalid'),
        ('argument_template', ['user free text']),
    ],
)
def test_case_target_does_not_accept_network_script_or_dynamic_arguments(field, value):
    item = cases()
    item['target'][field] = value
    with pytest.raises(InvalidInput):
        parse(body(items=[item], coverage_plan=[]))


def test_removed_marker_result_extensions_rejected_at_nested_level():
    for field in ('required_markers', 'stdout', 'result', 'evidence_summary'):
        item = integrity()
        item['evidence_rule'][field] = 'PASSED'
        with pytest.raises(InvalidInput):
            parse(body(items=[item], coverage_plan=[]))


@pytest.mark.parametrize('mode', ['MANUAL', 'NOT_APPLICABLE'])
def test_manual_range_has_explanation_and_no_automatic_mapping(mode):
    row = coverage(mode=mode, check_ids=[], explanation='必须人工核对原设计')
    assert parse(body(coverage_plan=[row])).value()['coverage_plan'][0] == row
    for changed in (coverage(mode=mode, check_ids=[]), coverage(mode=mode, explanation='说明')):
        with pytest.raises(InvalidInput):
            parse(body(coverage_plan=[changed]))


@pytest.mark.parametrize(
    'ids', [[], ['missing'], ['project-test'], ['integrity'], ['functional', 'functional']]
)
def test_auto_coverage_must_reference_controlled_function_checks_in_same_version(ids):
    with pytest.raises(InvalidInput):
        parse(body(coverage_plan=[coverage(check_ids=ids)]))


@pytest.mark.parametrize(
    'basis',
    [
        [],
        [{'document_id': 0, 'revision_id': 2, 'quote': 'text'}],
        [{'document_id': 1, 'revision_id': False, 'quote': 'text'}],
        [{'document_id': 1, 'revision_id': 2, 'quote': ''}],
        [{'document_id': 1, 'revision_id': 2, 'quote': 'text', 'url': 'unknown'}],
    ],
)
def test_coverage_basis_requires_exact_nonempty_document_revision_quote_structure(basis):
    with pytest.raises(InvalidInput):
        parse(body(coverage_plan=[coverage(basis_refs=basis)]))


def test_duplicate_checks_ranges_and_basis_rejected():
    duplicate_basis = coverage()
    duplicate_basis['basis_refs'] *= 2
    for value in (
        body(items=[integrity(), integrity()], coverage_plan=[]),
        body(coverage_plan=[coverage(), coverage()]),
        body(coverage_plan=[duplicate_basis]),
    ):
        with pytest.raises(InvalidInput):
            parse(value)


@pytest.mark.parametrize('field', ['runner_ref', 'check_id', 'case_pack_ref'])
def test_reference_unicode_and_nul_not_silently_repaired(field):
    item = cases()
    item[field] = 'x\0PRIVATE'
    with pytest.raises(InvalidInput):
        parse(body(items=[item], coverage_plan=[]))
    item[field] = '\ud800'
    with pytest.raises(InvalidInput):
        parse(body(items=[item], coverage_plan=[]))


def test_input_limit_exact_boundary_and_no_mutating_source_on_error():
    source = body()
    raw = canonical_input(source).encode()
    assert parse(source, limit=len(raw)).value() == source
    with pytest.raises(InvalidInput):
        parse(source, limit=len(raw) - 1)
    assert source == body()


@pytest.mark.parametrize('limit', [None, False, 0, 1.5, 2**53])
def test_limits_are_program_positive_safe_integers(limit):
    with pytest.raises(InvalidInput):
        parse(body(), limit=limit)


def test_display_name_and_explanation_cannot_embed_nulls():
    item = integrity(name='label\0text')
    with pytest.raises(InvalidInput):
        parse(body(items=[item], coverage_plan=[]))
    with pytest.raises(InvalidInput):
        parse(body(coverage_plan=[coverage(explanation='text\0text')]))


def test_handoff_check_selection_respects_stage_prefix_and_fixed_standard():
    items = [
        integrity(stages=['BACKEND', 'FRONTEND', 'INTEGRATION']),
        cases(stages=['FRONTEND', 'INTEGRATION']),
        command(stages=['BACKEND']),
    ]
    value = parse(body(items=items, coverage_plan=[coverage(stages=['FRONTEND'])]))
    backend = select_handoff_checks(value, ('BACKEND',))
    assert [item['check_id'] for item in backend['items']] == ['integrity', 'project-test']
    assert backend['coverage_plan'] == []
    front = select_handoff_checks(value, ('BACKEND', 'FRONTEND'))
    assert [item['check_id'] for item in front['items']] == [
        'integrity',
        'functional',
        'project-test',
    ]
    assert front['coverage_plan'][0]['coverage_id'] == 'behavior-1'
    assert value.value()['items'] == items
    with pytest.raises(CodingCheckPlanError, match='VERIFICATION_STAGE_NOT_READY'):
        select_handoff_checks(value, ('INTEGRATION',))
    with pytest.raises(CodingCheckPlanError, match='VERIFICATION_STAGE_NOT_READY'):
        select_handoff_checks(value, ('BACKEND', 'FRONTEND', 'INTEGRATION', 'ACCEPTANCE'))


def test_handoff_checks_reject_missing_integrity_and_unbound_stage_coverage():
    value = parse(
        body(
            items=[integrity(stages=['BACKEND']), cases(stages=['FRONTEND'])],
            coverage_plan=[coverage(stages=['BACKEND'])],
        )
    )
    with pytest.raises(CodingCheckPlanError, match='CHECK_CONFIGURATION_INVALID'):
        select_handoff_checks(value, ('BACKEND',))
    with pytest.raises(CodingCheckPlanError, match='CHECK_CONFIGURATION_INVALID'):
        select_handoff_checks(value, ('BACKEND', 'FRONTEND'))


def test_handoff_project_and_target_commands_require_original_profile_and_effective_scope():
    selection = select_handoff_checks(parse(body()), ('BACKEND',))
    project = {
        'command_id': 'project-tests',
        'purpose': 'CHECK',
        'network_scope_ref': None,
        'argument_template': ['test'],
    }
    service = {
        'command_id': 'candidate-service',
        'purpose': 'SERVICE',
        'network_scope_ref': 'test-endpoint',
        'argument_template': ['serve'],
    }
    fixed = [project, service]
    snapshot = {'COMMAND': [{'ready': True, 'value': row} for row in fixed]}
    scope = {
        'allowed_command_ids': ['project-tests', 'candidate-service'],
        'network_targets': ['test-endpoint'],
    }
    require_handoff_command_scope(selection, fixed, scope, snapshot)
    for allowed in (['project-tests'], ['candidate-service']):
        with pytest.raises(CodingCheckPlanError, match='AUTHORIZATION_NOT_APPLICABLE'):
            require_handoff_command_scope(
                selection, fixed, {**scope, 'allowed_command_ids': allowed}, snapshot
            )
    with pytest.raises(CodingCheckPlanError, match='AUTHORIZATION_NOT_APPLICABLE'):
        require_handoff_command_scope(selection, fixed, {**scope, 'network_targets': []}, snapshot)
    for different in ([project], [project, {**service, 'argument_template': ['other']}]):
        with pytest.raises(CodingCheckPlanError, match='CHECK_CONFIGURATION_INVALID'):
            require_handoff_command_scope(selection, different, scope, snapshot)
