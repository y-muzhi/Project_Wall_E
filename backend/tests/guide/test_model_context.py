"""Actual C03 snapshots and frozen model inputs; no live model or C07 claim."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
import unittest
from unittest.mock import patch

from backend.app.guide.queries import get_model_context
from backend.app.guide.context_builder import assemble_input, build_context, ContextLimitExceeded
from backend.app.guide import commands
from backend.app.infrastructure.guide_repository import GuideRepository
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.infrastructure.identifiers import EntityKind, entity_id, message_sequence
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.requirements.commands import complete_initialization
from backend.tests.guide import test_recovery as recovery
from backend.tests.guide import test_acceptance as acceptance
from backend.tests.guide import test_cards as cards
from backend.tests.guide import test_comment_acceptance as comments
from backend.tests.requirements import test_create_requirement as creation


class ModelContextTests(unittest.TestCase):
    facts = recovery.RecoveryTests.facts
    payload = recovery.RecoveryTests.payload
    create = recovery.RecoveryTests.create
    row = recovery.RecoveryTests.row

    def setUp(self): recovery.RecoveryTests.setUp(self)

    def read(self, identity=None):
        return get_model_context(self.database, self.run if identity is None else identity, catalog=self.catalog)

    def activate(self):
        self.assertEqual(commands.cancel_guide_run(self.executor, {'guide_run_id': self.run, 'idempotency_key': creation.OTHER}, clock=lambda: creation.INSTANT)['code'], 'GUIDE_CANCELLED')
        self.assertEqual(complete_initialization(self.executor, {'requirement_id': self.req, 'expected_content_version': 1, 'idempotency_key': acceptance.KEY}, catalog=self.catalog, clock=lambda: creation.INSTANT)['code'], 'INITIALIZATION_COMPLETED')

    def accept(self, action='ASK', **changes):
        result = commands.create_guide_run(self.executor, {'requirement_id': self.req, 'expected_content_version': 1, 'action_type': action,
            'instruction': '正式本轮输入😀', 'scope_type': 'BLOCK', 'scope_ref': {'block_id': 5}, 'source_type': 'USER_INSTRUCTION',
            'idempotency_key': acceptance.NEXT, **changes}, catalog=self.catalog,
            clock=lambda: creation.INSTANT+timedelta(seconds=3+2*('ASK','REVIEW','MODIFY').index(action)))
        self.assertEqual(result['code'], 'GUIDE_ACCEPTED', result)
        return result['data']['guide_run']['id']

    def test_initial_complete_ten_fields_real_locked_ids_and_exact_schema_without_writes_or_provider(self):
        before, trace = self.facts(), []
        original = self.database.transaction
        @contextmanager
        def traced(*, write=False):
            self.assertFalse(write)
            with original(write=write) as connection:
                connection.set_trace_callback(trace.append); yield connection
        with patch.object(self.database, 'transaction', new=traced), patch('socket.socket.connect', side_effect=AssertionError('No Provider')):
            result = self.read()
        self.assertEqual(result['code'], 'READ_OK', result)
        value = result['data']
        self.assertEqual(set(value), {'run','requirement','current_document','template','scope','allowed_targets','user_input','history','source','read_manifest'})
        self.assertEqual(value['run'], self.row('guide_runs', self.run))
        self.assertEqual(value['user_input']['content'], 'first\nsecond')
        self.assertEqual(value['history'], []); self.assertIsNone(value['source'])
        self.assertEqual(value['template']['locked_heading_block_ids'], [1,2,4,6,8,10,12,14,16,18,20,22,24])
        function = self.catalog.freeze('INITIALIZE', 'USER_INSTRUCTION')
        model = assemble_input(value, function)
        self.assertEqual(model['read_manifest']['block_ids'], [item['metadata']['block_id'] for item in model['current_document']['read_blocks']])
        self.assertEqual(model['requirement']['initialization_mode'], 'DESIGN')
        with self.assertRaises(ContextLimitExceeded): build_context(value, function)
        self.assertEqual(self.facts(), before)
        sql = '\n'.join(trace).lower()
        for hidden in ('llm_uses', 'revisions', 'manual_draft_context', 'suggestions'): self.assertNotIn(hidden, sql)
        value['current_document']['block_state_json']['blocks'][0]['block_id'] = 999
        self.assertEqual(self.read()['data']['current_document']['block_state_json']['blocks'][0]['block_id'], 1)

    def test_real_active_ask_review_modify_inputs_neighbors_are_read_only_and_frozen_grant_is_not_expanded(self):
        self.activate()
        for action in ('ASK', 'REVIEW', 'MODIFY'):
            with self.subTest(action=action):
                identity = self.accept(action, idempotency_key=f'00000000-0000-4000-8000-{("ASK","REVIEW","MODIFY").index(action)+200:012d}')
                if action == 'MODIFY':
                    with self.database.transaction(write=True) as connection:
                        connection.execute('UPDATE guide_runs SET allowed_targets_json=? WHERE id=?', (json.dumps({'schema_version':1,'targets':[]}), identity))
                before = self.facts(); result = self.read(identity)
                self.assertEqual(result['code'], 'READ_OK', result)
                data = result['data']; function = self.catalog.freeze(action, 'USER_INSTRUCTION')
                model = assemble_input(data, function)
                self.assertEqual(data['scope']['focus_block_ids'], [5]); self.assertGreater(len(data['scope']['read_block_ids']), 1)
                self.assertEqual(model['allowed_targets'], []); self.assertEqual(model['template']['locked_heading_block_ids'], [])
                self.assertNotIn('next_block_id', model['current_document'])
                self.assertEqual(self.facts(), before)
                with self.assertRaises(ContextLimitExceeded): build_context(data, function)
                self.assertEqual(commands.cancel_guide_run(self.executor, {'guide_run_id':identity,'idempotency_key':creation.OTHER}, clock=lambda:creation.INSTANT+timedelta(seconds=4+2*('ASK','REVIEW','MODIFY').index(action)))['code'], 'GUIDE_CANCELLED')

    def test_only_ten_latest_formal_readable_history_in_ascending_order_no_future_or_other_root_messages(self):
        self.activate()
        other = self.create(idempotency_key=creation.OTHER, initial_idea='unrelated root input')['data']
        with self.database.transaction(write=True) as connection:
            repository = MessageRepository(connection)
            for index in range(12): repository.create_user_text(100+index, self.req, self.run, f'history {index}', f'00000000-0000-4000-8000-{index+100:012d}', self.at)
        identity = self.accept()
        trigger = self.row('guide_runs', identity)['trigger_message_id']
        with self.database.transaction(write=True) as connection:
            MessageRepository(connection).create_user_text(trigger+1, self.req, identity, 'future input must not enter current context', creation.OTHER, self.at)
        before = self.facts(); result = self.read(identity)
        self.assertEqual(result['code'], 'READ_OK', result)
        data = result['data']; history = data['history']
        self.assertEqual([item['content'] for item in history], [f'history {index}' for index in range(2,12)])
        self.assertEqual(data['read_manifest']['message_ids'], [*range(102,112), trigger])
        self.assertNotIn('future input', str(data)); self.assertEqual(self.facts(), before)
        self.assertTrue(all(item['requirement_id'] == self.req for item in history))
        self.assertNotIn('unrelated root input', str(data)); self.assertNotEqual(other['requirement']['id'], self.req)

    def test_wal_real_writer_commit_between_root_and_document_reads_stays_in_original_snapshot(self):
        original = GuideRepository.get
        fired = False
        def concurrent(repository, identity):
            nonlocal fired
            row = original(repository, identity)
            if not fired:
                fired = True
                with self.database.transaction(write=True) as connection:
                    connection.execute("UPDATE requirements SET title='committed title' WHERE id=?", (self.req,))
                    connection.execute('UPDATE requirement_documents SET content_version=2 WHERE id=?', (self.created['current_document_id'],))
            return row
        with patch.object(GuideRepository, 'get', new=concurrent): result = self.read()
        self.assertTrue(fired); self.assertEqual(result['code'], 'READ_OK', result)
        self.assertEqual(result['data']['current_document']['content_version'], 1)
        self.assertEqual(result['data']['requirement']['title'], '需求😀')
        before = self.facts(); self.assertEqual(self.read()['code'], 'CONTENT_VERSION_CONFLICT'); self.assertEqual(self.facts(), before)

    def test_invalid_missing_configuration_and_result_mapping_failures_never_write(self):
        before = self.facts()
        for identity in (True, 0, '1', None, {}, 9007199254740992):
            self.assertEqual(get_model_context(self.database, identity, catalog=self.catalog)['code'], 'INVALID_INPUT')
        self.assertEqual(self.read(999)['code'], 'NOT_FOUND')
        with patch.object(self.catalog, 'restore', side_effect=ConfigInvalid('private frozen config failure')):
            self.assertEqual(self.read()['code'], 'CONFIG_INVALID')
        with patch('backend.app.guide.model_context.get_model_context_result', side_effect=ValueError('private mapping error')):
            self.assertEqual(self.read(), {'code':'INTERNAL_ERROR','data':None,'details':None})
        self.assertEqual(self.facts(), before)

    def test_bad_manifest_scope_permissions_and_user_binding_refuse_without_repair(self):
        original = self.row('guide_runs', self.run)
        for fields, code in (({'trigger_message_id':None},'SOURCE_INVALID'),
            ({'scope_type':'BLOCK','scope_ref_json':'{"block_id":999}'},'SOURCE_INVALID'),
            ({'allowed_targets_json':'{"schema_version":1,"targets":[{"block_id":999,"operations":["DELETE_BLOCK"],"selection_range":null,"row_selectors":null}]}'},'SOURCE_INVALID'),
            ({'read_scope_manifest_json':json.dumps({**json.loads(original['read_scope_manifest_json']),'block_ids':[999]})},'SOURCE_INVALID')):
            with self.database.transaction(write=True) as connection:
                connection.execute('UPDATE guide_runs SET '+','.join(key+'=?' for key in fields)+' WHERE id=?', (*fields.values(), self.run))
            before = self.facts(); self.assertEqual(self.read()['code'], code); self.assertEqual(self.facts(), before)
            with self.database.transaction(write=True) as connection:
                connection.execute('UPDATE guide_runs SET '+','.join(key+'=?' for key in fields)+' WHERE id=?', (*(original[key] for key in fields), self.run))

    def test_retry_reads_existing_formal_trigger_and_new_protocol_not_old_failed_status(self):
        self.assertEqual(commands.fail_guide_run(self.database, {'guide_run_id':self.run,'error_code':'MODEL_ERROR','safe_message':'安全失败'}, process_lock=self.lock, clock=lambda:creation.INSTANT)['code'], 'RUN_FAILED')
        retried = commands.retry_guide_run(self.executor, {'guide_run_id':self.run,'idempotency_key':creation.OTHER}, catalog=self.catalog, clock=lambda:creation.INSTANT+timedelta(seconds=1))
        self.assertEqual(retried['code'], 'GUIDE_RETRY_ACCEPTED', retried)
        before = self.facts(); result = self.read(retried['data']['id']); self.assertEqual(result['code'], 'READ_OK', result)
        self.assertEqual(result['data']['user_input']['guide_run_id'], self.run)
        self.assertEqual(result['data']['run']['status'], 'RUNNING'); self.assertEqual(result['data']['history'], []); self.assertEqual(self.facts(), before)

    def test_real_review_acceptance_with_explicit_historical_result_is_formal_source_not_current_truth(self):
        self.activate(); previous = self.accept('REVIEW', scope_type='DOCUMENT', scope_ref=None)
        at = '2026-10-04T08:00:06.000Z'
        review = {'schema_version':1,'summary':'explicit historical review result','issues':[]}
        # Until C07 is connected this is an explicit historical result fixture
        # on an actually accepted REVIEW, not a model-production assertion.
        with self.database.transaction(write=True) as connection:
            assistant = entity_id(connection, EntityKind.MESSAGE)
            connection.execute("INSERT INTO conversation_messages VALUES (?,?,?,?,'ASSISTANT','historical review fixture','TEXT',NULL,NULL,NULL,?)",
                (assistant,self.req,previous,message_sequence(connection,self.req),at))
            effects = {'guide_run_id':previous,'status':'COMPLETED','assistant_message_id':assistant,'current_document':None,'suggestion_batch_id':None,'review_result':review}
            connection.execute("UPDATE guide_runs SET status='COMPLETED',current_step='FINISHED',ended_at=?,updated_at=?,final_result_json=? WHERE id=?", (at,at,json.dumps(effects),previous))
        self.assertEqual(commands.recover_runs(self.database, {'recovery_reason':'STARTUP','live_run_ids':set(),'operation_time':at}, process_lock=self.lock)['code'], 'RECOVERED')
        identity = self.accept('MODIFY', source_type='REVIEW_RESULT', source_id=previous, idempotency_key=creation.OTHER)
        before = self.facts(); result = self.read(identity); self.assertEqual(result['code'], 'READ_OK', result)
        function = self.catalog.freeze('MODIFY','REVIEW_RESULT'); model = assemble_input(result['data'], function)
        self.assertEqual(model['source'], {'guide_run_id':previous,'reviewed_content_version':1,'review_result':review})
        with self.assertRaises(ContextLimitExceeded): build_context(result['data'], function)
        self.assertEqual(self.facts(), before)
        old_manifest = json.loads(self.row('guide_runs',previous)['read_scope_manifest_json'])
        with self.database.transaction(write=True) as connection:
            connection.execute('UPDATE guide_runs SET read_scope_manifest_json=? WHERE id=?', (json.dumps({**old_manifest,'content_version':2}),previous))
        before = self.facts(); self.assertEqual(self.read(identity)['code'], 'SOURCE_INVALID'); self.assertEqual(self.facts(), before)

    def diagnostic_policy(self, function, **changes):
        # Pure compiler boundary fixture, explicitly NOT an approved catalog
        # release or proof that production can dispatch within its budgets.
        policy = function.context_policy
        policy['budget'].update(prompt_tokens=100000,input_tokens=100000,total_tokens=120000,**changes)
        return replace(function, context_json=json.dumps(policy))

    def test_pure_compiler_history_trimming_whole_messages_updates_manifest_without_mutating_actual_context(self):
        self.activate()
        with self.database.transaction(write=True) as connection:
            for index in range(12):
                MessageRepository(connection).create_user_text(100+index,self.req,self.run,'诊断历史😀'*70,f'00000000-0000-4000-8000-{100+index:012d}',self.at)
        identity = self.accept(); data = self.read(identity)['data']; before = deepcopy(data); facts = self.facts()
        function = self.diagnostic_policy(self.catalog.freeze('ASK','USER_INSTRUCTION'))
        result = build_context(data, function); retained = result.input['history']
        self.assertGreater(len(result.removed_history_ids),0)
        self.assertEqual(result.removed_history_ids, tuple(item['id'] for item in data['history'][:len(result.removed_history_ids)]))
        self.assertEqual(retained, assemble_input(data,function)['history'][len(result.removed_history_ids):])
        self.assertEqual(result.input['read_manifest']['message_ids'], [item['id'] for item in retained]+[data['user_input']['id']])
        self.assertEqual(list(json.loads(result.input_json)), function.context_policy['field_order'])
        self.assertEqual(result.system, function.prompt+'\n'+json.dumps(json.loads(function.output_schema_json),ensure_ascii=False,separators=(',',':')))
        self.assertEqual(data,before);self.assertEqual(self.facts(),facts)

    def test_pure_compiler_trims_only_optional_whole_neighbors_and_refuses_required_overflow(self):
        self.activate(); identity = self.accept('MODIFY'); data = self.read(identity)['data']; facts = self.facts()
        function = self.catalog.freeze('MODIFY','USER_INSTRUCTION')
        broad = self.diagnostic_policy(function)
        complete = build_context(data,broad)
        policy = broad.context_policy; policy['budget']['input_tokens'] = complete.input_bytes-1000
        reduced = build_context(data,replace(broad,context_json=json.dumps(policy)))
        self.assertTrue(reduced.removed_neighbor_ids)
        self.assertTrue(set(reduced.removed_neighbor_ids).isdisjoint(data['scope']['required_read_block_ids']))
        self.assertEqual(reduced.input['allowed_targets'],complete.input['allowed_targets'])
        self.assertEqual(reduced.input['read_manifest']['block_ids'],[item['metadata']['block_id'] for item in reduced.input['current_document']['read_blocks']])
        policy['budget']['input_tokens'] = len(complete.system.encode('utf-8'))+1
        with self.assertRaises(ContextLimitExceeded): build_context(data,replace(broad,context_json=json.dumps(policy)))
        self.assertEqual(self.facts(),facts)


class FormalModelContextTests(unittest.TestCase):
    facts = cards.CardSubmissionTests.facts
    payload = cards.CardSubmissionTests.payload
    create = cards.CardSubmissionTests.create
    row = cards.CardSubmissionTests.row
    initialize_cards_fixture = cards.CardSubmissionTests.initialize_cards_fixture
    message_fixture = cards.CardSubmissionTests.message_fixture
    waiting_cards_fixture = cards.CardSubmissionTests.waiting_cards_fixture
    answers = cards.CardSubmissionTests.answers
    submit = cards.CardSubmissionTests.submit

    def setUp(self): cards.CardSubmissionTests.setUp(self)

    def test_real_formal_answer_includes_only_chosen_values_and_original_card_read_identity(self):
        self.initialize_cards_fixture(); accepted = self.submit(); self.assertEqual(accepted['code'], 'CARDS_ACCEPTED')
        identity = accepted['data']['guide_run']['id']; before = self.facts()
        result = get_model_context(self.database, identity, catalog=self.catalog)
        self.assertEqual(result['code'], 'READ_OK', result)
        data = result['data']; model = assemble_input(data, self.catalog.freeze('INITIALIZE','USER_INSTRUCTION'))
        self.assertEqual(model['user_input']['content'], '选择方案\nb')
        self.assertEqual(model['user_input']['formal_responses'], {'schema_version':1,'responses':self.answers()['responses']})
        self.assertTrue(all(item['message_type'] != 'INTERACTION_CARDS' for item in model['history']))
        self.assertIn(11, model['read_manifest']['message_ids']); self.assertEqual(self.facts(), before)

    def test_invalid_formal_json_is_source_invalid_not_plain_text_fallback_or_write(self):
        self.initialize_cards_fixture(); identity = self.run
        # Explicit damaged historical response fixture. Immutable native C06
        # messages are never changed and no schema trigger is disabled.
        with self.database.transaction(write=True) as connection:
            repository = MessageRepository(connection)
            repository.create_card_response(12, self.req, identity, repository.get(11), 'damaged history fixture', {'schema_version':1,'responses':[]}, cards.KEY, self.at)
            connection.execute('UPDATE guide_runs SET trigger_message_id=12 WHERE id=?', (identity,))
        before = self.facts(); self.assertEqual(get_model_context(self.database, identity, catalog=self.catalog)['code'], 'SOURCE_INVALID'); self.assertEqual(self.facts(), before)


class CommentModelContextTests(unittest.TestCase):
    facts = comments.CommentAcceptanceTests.facts
    write_body = comments.CommentAcceptanceTests.write_body
    row = comments.CommentAcceptanceTests.row
    create_payload = comments.CommentAcceptanceTests.create_payload
    make_comment = comments.CommentAcceptanceTests.make_comment
    command_payload = comments.CommentAcceptanceTests.command_payload
    modify = comments.CommentAcceptanceTests.modify

    def setUp(self): comments.CommentAcceptanceTests.setUp(self)

    def test_actual_comment_function_input_and_orphan_recheck_have_no_repair_effect(self):
        self.assertEqual(self.make_comment()['code'], 'COMMENT_CREATED'); accepted = self.modify(); identity = accepted['data']['id']
        before = self.facts(); result = get_model_context(self.database, identity, catalog=self.catalog)
        self.assertEqual(result['code'], 'READ_OK', result)
        model = assemble_input(result['data'], self.catalog.freeze('MODIFY','COMMENT'))
        self.assertEqual(model['source']['comment_id'], 1); self.assertEqual([item['block_id'] for item in model['allowed_targets']], [1])
        self.assertEqual(self.facts(), before)
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE comments SET status='RESOLVED',resolved_at=updated_at WHERE id=1")
        before = self.facts(); self.assertEqual(get_model_context(self.database, identity, catalog=self.catalog)['code'], 'SOURCE_INVALID'); self.assertEqual(self.facts(), before)

    def test_same_version_changed_selection_body_refuses_anchor_without_writing_orphan_flag(self):
        with self.database.transaction(write=True) as connection: self.write_body(connection, 'a\n')
        self.assertEqual(self.make_comment(anchor_type='SELECTION',selection={'selected_text':'a','prefix_text':'','suffix_text':''},expected_content_version=8)['code'], 'COMMENT_CREATED')
        accepted = self.modify(expected_content_version=8); identity = accepted['data']['id']
        with self.database.transaction(write=True) as connection:
            self.write_body(connection,'b\n'); connection.execute('UPDATE requirement_documents SET content_version=8 WHERE id=201')
        before = self.facts(); result = get_model_context(self.database, identity, catalog=self.catalog)
        self.assertEqual(result['code'], 'SOURCE_INVALID')  # The old selection itself cannot resolve.
        self.assertEqual(self.row('comments',1)['anchor_status'], 'ATTACHED'); self.assertEqual(self.facts(), before)
