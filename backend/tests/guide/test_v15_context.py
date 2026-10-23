"""Actual frozen acceptance -> V1.5 Canonical/Wire, with no provider I/O."""
import json
from copy import deepcopy
from uuid import uuid4

import pytest

from backend.tests.requirements.test_v15_foundation import tmp_path, setup, counts
from backend.tests.documents.test_v15_documents import workspace, document
from backend.tests.guide.test_v15_acceptance import accept
from backend.app.guide.collaboration_context import read_canonical, compile_context
from backend.app.guide.model_context import get_model_context
from backend.app.infrastructure.collaboration_resources import sha256
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.shared.command_execution import Rejected


def compiled(workspace, identity=1, **options):
    with workspace[0].transaction() as connection:
        canonical = read_canonical(connection, identity, workspace[2])
    return compile_context(canonical, workspace[2], **options)


def test_zero_document_context_is_deterministic_and_private_authority_never_reaches_wire(workspace):
    assert accept(workspace)['code'] == 'GUIDE_ACCEPTED'
    before = counts(workspace[0])
    context = compiled(workspace)
    assert get_model_context(workspace[0], 1, catalog=workspace[2])['code'] == 'READ_OK'
    assert context == compiled(workspace)
    wire, basis = context.input, context.basis
    assert wire['documents'] == [] and wire['structure'] is None
    assert wire['current_request']['content'] == '  用户原话\r\n保留空白。  '
    assert wire['recent_history'] == []
    assert wire['goal_and_decisions'][0]['ref'] == 'm1'
    assert context.input_json.count('用户原话') == 1
    assert 'allowed_targets' not in context.input_json and 'block_state' not in context.input_json
    assert basis['wire_sha256'] == sha256(context.input_json)
    assert basis['canonical_sha256'] == sha256(workspace[2].collaboration.serialize('Canonical', basis['canonical']))
    assert len(context.texts) == 8 and context.texts[3] == context.texts[4] == context.texts[5] == ''
    assert counts(workspace[0]) == before
    replayed = compile_context(basis['canonical'], workspace[2])
    assert replayed == context


def test_long_term_pending_survives_recent_ten_without_refilling_deduplicated_history(workspace):
    db, _, resources = workspace
    with db.transaction(write=True) as connection:
        root = RequirementRepository(connection).get(1);state = deepcopy(root['discussion_state_json'])
        pending = None
        for index in range(15):
            identity = entity_id(connection, EntityKind.MESSAGE)
            row = MessageRepository(connection).create_user_text(identity, 1, None, '长程原话' if index == 0 else '历史'+str(index), str(uuid4()), root['updated_at'])
            if index == 0:
                pending = identity
        state['pending_user_message_ids'] = [pending]
        RequirementRepository(connection).update_discussion(root, state, root['updated_at'])
    assert accept(workspace, expected_discussion_version=2)['code'] == 'GUIDE_ACCEPTED'
    context = compiled(workspace);wire = context.input
    assert sum(item['text'] == '长程原话' for item in wire['goal_and_decisions']) == 1
    assert len(wire['recent_history']) == 10
    assert [item['content'] for item in wire['recent_history']] == ['历史'+str(index) for index in range(5, 15)]
    trimmed = compiled(workspace, omit_history=True)
    assert trimmed.input['recent_history'] == []
    assert '长程原话' in trimmed.input_json
    assert len([item for item in trimmed.basis['omitted'] if item['reason'] == 'BUDGET_OPTIONAL_HISTORY']) == 10
    assert context.system == trimmed.system


def test_same_target_revision_source_merges_body_and_purposes_once(workspace):
    created = document(workspace, reference=workspace[2].collaboration.reference('structure.brief'))['data']['document']
    source = {'kind': 'REVISION', 'document_id': created['id'], 'revision_id': created['current_revision_id'], 'block_ids': None}
    assert accept(workspace, operation='REVISE', target={'kind': 'EXISTING', 'document_id': created['id'], 'expected_content_version': 1},
        scope={'scope_type': 'DOCUMENT', 'scope_ref': None}, source_refs=[source, source])['code'] == 'GUIDE_ACCEPTED'
    context = compiled(workspace);documents = context.input['documents']
    assert len(documents) == 1 and documents[0]['roles'] == ['TARGET', 'REFERENCE']
    assert len(documents[0]['blocks']) == 7 and len({row['ref'] for row in documents[0]['blocks']}) == 7
    assert all(row['writable'] for row in documents[0]['blocks'])
    assert len(context.canonical['documents']) == 1


def test_local_target_reads_only_scope_neighbors_and_navigation_and_trims_only_optional_background(workspace):
    created = document(workspace, reference=workspace[2].collaboration.reference('structure.brief'))['data']['document']
    block = created['block_state_json']['blocks'][3]['block_id']
    assert accept(workspace, operation='REVISE', target={'kind': 'EXISTING', 'document_id': created['id'], 'expected_content_version': 1},
        scope={'scope_type': 'BLOCK', 'scope_ref': {'block_id': block}})['code'] == 'GUIDE_ACCEPTED'
    full = compiled(workspace);trimmed = compiled(workspace, omit_background=True)
    assert len(full.input['documents'][0]['blocks']) == 5
    assert [row['block_id'] for row in trimmed.input['documents'][0]['blocks']] == [block]
    assert trimmed.input['documents'][0]['coverage'] == 'PARTIAL'
    assert len([row for row in trimmed.basis['omitted'] if row['reason'] == 'BUDGET_OPTIONAL_BACKGROUND']) == 4
    assert all(row['writable'] == (row['block_id'] == block) for row in full.input['documents'][0]['blocks'])
    assert full.canonical['authorization'] == trimmed.canonical['authorization']


def test_generation_structure_is_task_specific_and_discussion_does_not_load_a_template(workspace):
    target = {'kind': 'NEW', 'name': '正式规格', 'document_kind': 'specification', 'template_ref': {'key': 'structure.specification', 'version': 'v1'}}
    assert accept(workspace, operation='GENERATE', target=target)['code'] == 'GUIDE_ACCEPTED'
    context = compiled(workspace)
    assert context.input['structure']['template']['markdown_content'] == workspace[2].template('NEW', 'new-requirement', 'v4').markdown
    assert context.input['documents'] == []
    assert context.input['current_request']['target'] == target


def test_runtime_discussion_version_change_stops_before_context_is_used(workspace):
    assert accept(workspace)['code'] == 'GUIDE_ACCEPTED'
    with workspace[0].transaction(write=True) as connection:
        connection.execute('UPDATE requirements SET discussion_version=discussion_version+1 WHERE id=1')
    with workspace[0].transaction() as connection, pytest.raises(Rejected) as error:
        read_canonical(connection, 1, workspace[2])
    assert error.value.code == 'DISCUSSION_VERSION_CONFLICT'


def test_selected_formal_answer_carries_only_original_question_and_chosen_labels(workspace):
    db = workspace[0]
    with db.transaction(write=True) as connection:
        root = RequirementRepository(connection).get(1);at = root['updated_at']
        card = {'card_key': 'c1', 'card_type': 'SINGLE_SELECT', 'question': '真实原题', 'context': '不得发送的选项说明', 'required': False,
            'options': [{'option_key': key, 'label': label, 'description': '完整说明不回传', 'impact': '', 'risks': ''} for key, label in [('a', '选中标签'), ('b', '未选标签')]],
            'selection_rule': {'min': 0, 'max': 1}, 'custom_answer': {'enabled': False, 'max_length': 0}, 'recommendation': None, 'related_spec_context': []}
        group = {'schema_version': 1, 'intro': '', 'purpose': 'CLARIFICATION', 'cards': [card], 'action_payload': None,
            'program_binding': {'discussion_version': 1, 'target_content_version': None, 'source_heads': []}}
        answer = {'schema_version': 1, 'responses': [{'card_key': 'c1', 'selected_option_keys': ['a'], 'custom_answer': None, 'skipped': False}], 'execution_selection': None}
        original, response = entity_id(connection, EntityKind.MESSAGE), entity_id(connection, EntityKind.MESSAGE)
        for identity, role, kind, text, structured, parent in [(original, 'ASSISTANT', 'INTERACTION_CARDS', '真实原题', group, None),
                (response, 'USER', 'CARD_RESPONSE', '重复的答案摘要', answer, original)]:
            connection.execute("INSERT INTO conversation_messages(id,requirement_id,guide_run_id,sequence_no,role,content,message_type,structured_content_json,reply_to_message_id,idempotency_key,created_at,phase_ref,topic_refs,document_ids) VALUES (?,1,NULL,?,?,?,?,?,?,?,?,NULL,'[]','[]')",
                (identity, identity, role, text, kind, json.dumps(structured), parent, str(uuid4()) if role == 'USER' else None, at))
    assert accept(workspace, source_refs=[{'kind': 'CARD_ANSWER', 'message_id': response, 'card_key': 'c1'}])['code'] == 'GUIDE_ACCEPTED'
    context = compiled(workspace)
    assert '选中标签' in context.input_json and context.input_json.count('真实原题') == 1
    assert all(text not in context.input_json for text in ['未选标签', '完整说明不回传', '不得发送的选项说明', '重复的答案摘要'])
    assert any(alias['ref'] == 'm'+str(response)+':c1' for alias in context.basis['aliases'])
    assert context == compile_context(context.canonical, workspace[2])
