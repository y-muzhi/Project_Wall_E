"""Document-driven contracts against isolated SQLite and actual compiled Wire."""
from copy import deepcopy
from dataclasses import replace
import json
import ast
from pathlib import Path

import pytest

from backend.tests.requirements.test_v15_foundation import tmp_path, setup, create, counts
from backend.tests.documents.test_v15_documents import document
from backend.tests.guide.test_v15_acceptance import accept
from backend.tests.guide.test_v15_context import compiled
from backend.tests.guide.test_v15_progress import delta, evidence
from backend.app.guide.commands import cancel_guide_run
from backend.app.guide.progress_application import apply_progress, ProgressInvalid
from backend.app.infrastructure.resources import ResourceCatalog, ProtocolInvalid
from backend.app.infrastructure.collaboration_resources import CollaborationResources, ROOT
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.requirements.discussion import empty_discussion, validate_discussion


@pytest.fixture(scope='module')
def catalog():
    return ResourceCatalog()


@pytest.fixture
def workspace(setup, catalog):
    create(setup[1])
    return *setup, catalog


@pytest.mark.parametrize(('document_kind', 'profile'), [
    ('REQUIREMENT_BRIEF', 'brief'), ('DESIGN', 'design'), ('SPECIFICATION', 'specification'),
])
def test_actual_wire_uses_owned_document_type_and_has_no_independent_phase(workspace, document_kind, profile):
    current = document(workspace, kind=document_kind)['data']['document']
    assert accept(workspace, target={'kind': 'EXISTING', 'document_id': current['id'], 'expected_content_version': 1},
                  scope={'scope_type': 'DOCUMENT', 'scope_ref': None})['code'] == 'GUIDE_ACCEPTED'
    context = compiled(workspace)
    assert context.input['project_position']['document_kind'] == profile
    assert context.input['current_request']['basis_ref']['document_kind'] == profile
    assert context.input['current_request']['basis_ref']['guide_key'] == 'collaboration.' + profile
    assert 'phase' not in context.canonical['discussion']
    assert 'phase_ref' not in context.input['current_request']['basis_ref']
    assert 'phase_kind' not in context.input['project_position']
    assert '文档指引 collaboration.' + profile in context.system
    # Exercise the browser fixture's real response factory without starting a
    # service. Both ordinary and rich progress must follow the owned type.
    from backend.tests.guide.test_v15_execution import output, delta as execution_delta
    from backend.tests.guide.test_v15_cards import group
    from backend.tests.guide.test_v15_progress import topic
    tree = ast.parse(Path('tools/serve-v15-offline.py').read_text(encoding='utf-8'))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    factory = next(node for node in main.body if isinstance(node, ast.FunctionDef) and node.name == 'returned')
    namespace = {'catalog': workspace[2], 'output': output, 'delta': execution_delta,
                 'group': group, 'topic': topic, 'evidence': evidence}
    exec(compile(ast.Module(body=[factory], type_ignores=[]), 'offline-response-factory', 'exec'), namespace)
    for instruction in ('本轮继续讨论', '[progress-layout]'):
        wire = context.input
        wire['current_request']['content'] = instruction
        selected = replace(context, input_json=json.dumps(wire, ensure_ascii=False))
        response = namespace['returned'](selected)
        workspace[2].collaboration.validate('OutputDiscuss', response)
        progressed = apply_progress(selected.canonical['discussion'], response['progress_delta'],
                                    selected, 5, workspace[2].collaboration)
        assert len(progressed['topics']) == (4 if instruction == '[progress-layout]' else 1)
        assert 'phase' not in progressed


def test_generation_uses_new_document_type_without_rebinding_source_assistant(workspace):
    assert accept(workspace, operation='GENERATE', target={
        'kind': 'NEW', 'name': '设计方案', 'document_kind': 'design', 'template_ref': None,
    })['code'] == 'GUIDE_ACCEPTED'
    context = compiled(workspace)
    assert context.input['current_request']['basis_ref']['guide_key'] == 'collaboration.design'
    assert context.canonical['discussion']['binding']['target_document_id'] is None
    assert counts(workspace[0])['requirement_documents'] == 1


def test_read_projection_preserves_all_document_topics_and_original_historical_value(catalog):
    state = empty_discussion()
    state.update(schema_version=1, phase={
        'phase_ref': 'p2', 'kind': 'SOLUTION',
        'guide_ref': CollaborationResources.load(ROOT.parent / 'v15').reference('collaboration.solution'),
        'closure': None,
    })
    state['counters'] = {'phase': 3, 'topic': 3, 'evidence': 1}
    for number in (1, 2):
        state['topics'].append({
            'topic_ref': 't' + str(number), 'phase_ref': 'p' + str(number),
            'mainline_ref': 'value', 'title': '旧主题', 'purpose': '保留主题',
            'expected_outcomes': [{'outcome_ref': 'o' + str(number), 'text': '成果', 'criterion': '有依据'}],
            'assessment': 'DISCUSSING', 'evidence_refs': [], 'dependencies': [],
            'unresolved_impacts': [], 'updated_by_message_id': 1,
        })
    state['focus_topic_ref'] = 't1'
    before = deepcopy(state)
    projected = validate_discussion(state, catalog.collaboration)
    assert state == before
    assert projected['schema_version'] == 2 and 'phase' not in projected
    assert [topic['topic_ref'] for topic in projected['topics']] == ['t1', 't2']
    assert all('phase_ref' not in topic for topic in projected['topics'])
    assert projected['focus_topic_ref'] == 't1'


def replacement_context(workspace):
    assert accept(workspace, instruction='登录本版不做。')['code'] == 'GUIDE_ACCEPTED'
    first = compiled(workspace)
    state = apply_progress(first.canonical['discussion'], delta(
        topic_changes=[], evidence_changes=[evidence(assertion='登录本版不做。', applies_to='GLOBAL', topic_refs=[])],
        focus_topic_ref=None, next_step=None,
    ), first, 2, workspace[2].collaboration)
    assert cancel_guide_run(workspace[1], {'guide_run_id': 1, 'idempotency_key': '00000000-0000-4000-8000-000000000101'})['code'] == 'GUIDE_CANCELLED'
    with workspace[0].transaction(write=True) as connection:
        repository = RequirementRepository(connection)
        root = repository.get_for_document(1, 1)
        repository.update_discussion(root, state, root['updated_at'])
    assert accept(workspace, expected_discussion_version=3, instruction='现在改为需要登录。')['code'] == 'GUIDE_ACCEPTED'
    return compiled(workspace, 2)


def replacement(context, **changes):
    current = context.input['current_request']
    return delta(
        topic_changes=[], evidence_changes=[evidence(
            change='USER_REPLACE', assertion=current['content'], applies_to='GLOBAL',
            source_refs=[current['message_ref']], supersedes=['e1'], topic_refs=[], **changes,
        )],
        focus_topic_ref=None, next_step=None, processed_user_message_ids=[current['message_id']],
    )


def test_explicit_verbatim_user_replacement_updates_effective_evidence_and_keeps_old_source(workspace):
    context = replacement_context(workspace)
    before = deepcopy(context.canonical['discussion'])
    result = apply_progress(before, replacement(context), context, 4, workspace[2].collaboration)
    assert before == context.canonical['discussion']
    assert result['evidence'][0]['state'] == 'SUPERSEDED'
    assert result['evidence'][1]['state'] == 'ACTIVE'
    assert result['evidence'][1]['origin'] == 'USER_STATEMENT'
    assert result['evidence'][0]['source_refs'] == before['evidence'][0]['source_refs']
    assert result['pending_user_message_ids'] == []


@pytest.mark.parametrize('kind', ['quote', 'source', 'scope'])
def test_uncertain_or_unread_replacement_cannot_erase_original_or_consume_pending(workspace, kind):
    context = replacement_context(workspace)
    change = replacement(context)
    item = change['evidence_changes'][0]
    if kind == 'quote':
        item['assertion'] = 'AI自行概括成另一条决定'
    elif kind == 'source':
        item['source_refs'] = ['m999']
    else:
        item['applies_to'] = ['t999']
    before = deepcopy(context.canonical['discussion'])
    with pytest.raises(ProgressInvalid):
        apply_progress(before, change, context, 4, workspace[2].collaboration)
    assert before == context.canonical['discussion']
    assert before['evidence'][0]['state'] == 'ACTIVE'
    assert before['pending_user_message_ids']


def test_current_contract_rejects_phase_actions_and_guide_profiles_have_separate_admission(catalog):
    resources = catalog.collaboration
    assert [item['document_kind'] for item in resources.release['guides']] == ['brief', 'design', 'specification']
    assert resources.release['admission']['state'] == 'OFFLINE_READY'
    assert resources.reference('collaboration.release') != CollaborationResources.load(ROOT.parent / 'v15').reference('collaboration.release')
    purpose_values = [item['properties']['purpose']['const'] for item in resources.bundle['$defs']['ModelCardGroup']['oneOf']]
    assert 'PHASE_CHANGE' not in purpose_values
    with pytest.raises(ProtocolInvalid):
        resources.validate('NextStep', {'action': 'PROPOSE_PHASE_CHANGE', 'topic_ref': None, 'reason': '旧阶段动作', 'unresolved_impacts': []})
