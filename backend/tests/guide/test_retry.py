"""C04 actual failure/retry and latest CURRENT, no copied user message or model."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import timedelta
import json
import sqlite3
import unittest
from unittest.mock import patch
from backend.app.guide import commands
from backend.app.documents.commands import start_manual_draft, complete_manual_draft
from backend.app.requirements.commands import complete_initialization
from backend.app.infrastructure.database import Database, CommitOutcomeUnknown
from backend.app.infrastructure.idempotency import Idempotency, Scope
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.shared.validation import MAX_SAFE_INTEGER
from backend.tests.guide import test_recovery as fixtures
from backend.tests.guide import test_cards as card_fixtures
from backend.tests.guide import test_comment_acceptance as comment_fixtures
from backend.tests.requirements import test_create_requirement as creation

KEY=creation.OTHER
OTHER='00000000-0000-4000-8000-00000000000c'
NOW=creation.INSTANT+timedelta(seconds=10)


class RetryTests(unittest.TestCase):
    facts=fixtures.RecoveryTests.facts
    payload=fixtures.RecoveryTests.payload
    create=fixtures.RecoveryTests.create
    row=fixtures.RecoveryTests.row

    def setUp(self):
        fixtures.RecoveryTests.setUp(self)
        self.failed=self.run
        self.fail_run(self.run)

    def fail_run(self,identity):
        result=commands.fail_guide_run(self.database,{'guide_run_id':identity,'error_code':'MODEL_ERROR','safe_message':'真实失败收口'},process_lock=self.lock,clock=lambda:creation.INSTANT+timedelta(seconds=1))
        self.assertEqual(result['code'],'RUN_FAILED',result)

    def retry(self,**changes):
        return commands.retry_guide_run(self.executor,{'guide_run_id':self.failed,'idempotency_key':KEY,**changes},catalog=self.catalog,clock=lambda:NOW)

    def test_new_run_frozen_protocol_original_failed_and_user_trigger_preserved(self):
        old=self.row('guide_runs',self.failed);message=self.row('conversation_messages',old['trigger_message_id']);current=self.row('requirement_documents',self.created['current_document_id'])
        result=self.retry();self.assertEqual(result['code'],'GUIDE_RETRY_ACCEPTED',result);data=result['data'];new=self.row('guide_runs',data['id'])
        self.assertNotEqual(data['id'],old['id']);self.assertEqual((new['trigger_type'],new['retry_of_guide_run_id'],new['trigger_message_id'],new['idempotency_key']),('RETRY',old['id'],message['id'],KEY))
        self.assertEqual((new['status'],new['current_step'],new['started_at'],new['mode_snapshot']),('RUNNING','PREPARING',None,'DESIGN'))
        self.assertEqual(self.row('guide_runs',self.failed),old);self.assertEqual(self.row('conversation_messages',message['id']),message);self.assertEqual(self.row('requirement_documents',current['id']),current)
        self.assertEqual(self.row('requirements',self.req)['active_operation_id'],data['id'])
        with self.database.transaction() as connection: self.assertEqual(connection.execute('SELECT count(*) FROM conversation_messages').fetchone()[0],1)

    def test_latest_current_version_after_real_manual_completion_is_re_read(self):
        start=start_manual_draft(self.executor,{'requirement_id':self.req,'expected_content_version':1,'idempotency_key':OTHER},catalog=self.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=2))
        self.assertEqual(start['code'],'DRAFT_STARTED')
        complete=complete_manual_draft(self.executor,{'requirement_id':self.req,'expected_version':1,'idempotency_key':OTHER},catalog=self.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=3))
        self.assertEqual(complete['code'],'DRAFT_COMPLETED');self.assertEqual(complete['data']['content_version'],2)
        result=self.retry();self.assertEqual(result['code'],'GUIDE_RETRY_ACCEPTED',result)
        old=json.loads(self.row('guide_runs',self.failed)['read_scope_manifest_json']);new=json.loads(self.row('guide_runs',result['data']['id'])['read_scope_manifest_json'])
        self.assertEqual((old['content_version'],new['content_version']),(1,2));self.assertEqual(new['message_ids'],old['message_ids'])

    def test_same_key_freezes_original_new_run_even_after_cancel_and_missing_resources(self):
        original=self.retry();identity=original['data']['id']
        self.assertEqual(commands.cancel_guide_run(self.executor,{'guide_run_id':identity,'idempotency_key':OTHER},clock=lambda:NOW+timedelta(seconds=1))['code'],'GUIDE_CANCELLED')
        before=self.facts()
        with patch('backend.app.guide.commands.ResourceCatalog',side_effect=ConfigInvalid('missing resources')):
            self.assertEqual(commands.retry_guide_run(self.executor,{'guide_run_id':self.failed,'idempotency_key':KEY},clock=lambda:NOW),original)
        self.assertEqual(self.facts(),before)

    def test_lifecycle_invalid_missing_source_scope_and_config_have_no_new_run(self):
        before=self.facts();self.assertEqual(self.retry(guide_run_id=999)['code'],'NOT_FOUND');self.assertEqual(self.facts(),before)
        for payload in ({},{'guide_run_id':True,'idempotency_key':KEY},{'guide_run_id':self.failed,'idempotency_key':KEY,'expected_version':1}):
            self.assertEqual(commands.retry_guide_run(self.executor,payload)['code'],'INVALID_INPUT');self.assertEqual(self.facts(),before)
        with patch.object(self.catalog,'freeze',side_effect=ConfigInvalid('missing new protocol')): self.assertEqual(self.retry()['code'],'CONFIG_INVALID')
        self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE guide_runs SET scope_type='BLOCK',scope_ref_json='{\"block_id\":999}' WHERE id=?",(self.failed,))
        before=self.facts();self.assertEqual(self.retry()['code'],'SCOPE_INVALID');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute('UPDATE guide_runs SET trigger_message_id=NULL WHERE id=?',(self.failed,))
        before=self.facts();self.assertEqual(self.retry()['code'],'SOURCE_INVALID');self.assertEqual(self.facts(),before)

    def test_active_requirement_refuses_old_initialize_and_busy_root_cannot_be_repaired(self):
        result=complete_initialization(self.executor,{'requirement_id':self.req,'expected_content_version':1,'idempotency_key':OTHER},catalog=self.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=2))
        self.assertEqual(result['code'],'INITIALIZATION_COMPLETED');before=self.facts();self.assertEqual(self.retry()['code'],'STATE_CONFLICT');self.assertEqual(self.facts(),before)

    def test_real_competing_keys_make_one_new_run(self):
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda key:self.retry(idempotency_key=key),(KEY,OTHER)))
        self.assertEqual(sorted(result['code'] for result in results),['GUIDE_RETRY_ACCEPTED','WORK_STATE_CONFLICT'])
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM guide_runs WHERE retry_of_guide_run_id=?',(self.failed,)).fetchone()[0],1)
            self.assertEqual(connection.execute('SELECT count(*) FROM conversation_messages').fetchone()[0],1)

    def test_actual_sql_failures_mapping_and_capacity_roll_back_new_run_only(self):
        for table,predicate in (('guide_runs',''),('requirements',''),('idempotency_records',"WHEN NEW.status='SUCCEEDED'")):
            kind='INSERT' if table=='guide_runs' else 'UPDATE'
            with closing(sqlite3.connect(self.path)) as connection:
                connection.execute(f"CREATE TRIGGER retry_fault AFTER {kind} ON {table} {predicate} BEGIN SELECT RAISE(ABORT,'private retry'); END");connection.commit()
            before=self.facts();self.assertEqual(self.retry()['code'],'STORAGE_UNAVAILABLE');self.assertEqual(self.facts(),before)
            with closing(sqlite3.connect(self.path)) as connection: connection.execute('DROP TRIGGER retry_fault');connection.commit()
        before=self.facts()
        with patch('backend.app.guide.commands.retry_guide_run_result',side_effect=ValueError('after actual retry acceptance')): self.assertEqual(self.retry()['code'],'INTERNAL_ERROR')
        self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE sequences SET last_value=? WHERE entity_kind='GuideRun'",(MAX_SAFE_INTEGER,))
        before=self.facts();self.assertEqual(self.retry()['code'],'CAPACITY_EXHAUSTED');self.assertEqual(self.facts(),before)

    def test_true_commit_lost_ack_processing_and_replay_do_not_copy_messages(self):
        request=commands.retry_guide_run_input({'guide_run_id':self.failed,'idempotency_key':KEY});claim=self.executor.claim(Scope('APP-GUIDE-CMD-C04',f'GuideRun:{self.failed}',KEY),request.business_input())
        before=self.facts();self.assertEqual(self.retry()['code'],'REQUEST_IN_PROGRESS');self.assertEqual(self.facts(),before);self.executor.abandon(claim)
        class LostAck(Database):
            writes=0
            @contextmanager
            def transaction(database,*,write=False):
                with super().transaction(write=write) as connection: yield connection
                if write:
                    database.writes+=1
                    if database.writes==2: raise CommitOutcomeUnknown('after real retry acceptance commit')
        executor=Idempotency(LostAck(self.path),self.lock,clock=lambda:creation.INSTANT)
        self.assertEqual(commands.retry_guide_run(executor,{'guide_run_id':self.failed,'idempotency_key':KEY},catalog=self.catalog,clock=lambda:NOW)['code'],'STORAGE_UNAVAILABLE')
        before=self.facts();self.assertEqual(self.retry()['code'],'GUIDE_RETRY_ACCEPTED');self.assertEqual(self.facts(),before)


class FormalAnswerRetryTests(unittest.TestCase):
    facts=card_fixtures.CardSubmissionTests.facts
    payload=card_fixtures.CardSubmissionTests.payload
    create=card_fixtures.CardSubmissionTests.create
    row=card_fixtures.CardSubmissionTests.row
    message_fixture=card_fixtures.CardSubmissionTests.message_fixture
    initialize_cards_fixture=card_fixtures.CardSubmissionTests.initialize_cards_fixture
    answers=card_fixtures.CardSubmissionTests.answers
    submit=card_fixtures.CardSubmissionTests.submit

    def setUp(self): card_fixtures.CardSubmissionTests.setUp(self)

    def test_retry_reuses_formal_card_answer_as_trigger_after_native_failure(self):
        self.initialize_cards_fixture();accepted=self.submit();self.assertEqual(accepted['code'],'CARDS_ACCEPTED')
        failed=accepted['data']['guide_run']['id'];message=self.row('conversation_messages',accepted['data']['response_message']['id'])
        self.assertEqual(commands.fail_guide_run(self.database,{'guide_run_id':failed,'error_code':'MODEL_ERROR','safe_message':'失败'},process_lock=self.lock,clock=lambda:NOW+timedelta(seconds=1))['code'],'RUN_FAILED')
        result=commands.retry_guide_run(self.executor,{'guide_run_id':failed,'idempotency_key':OTHER},catalog=self.catalog,clock=lambda:NOW+timedelta(seconds=2));self.assertEqual(result['code'],'GUIDE_RETRY_ACCEPTED',result)
        run=self.row('guide_runs',result['data']['id']);self.assertEqual(run['trigger_message_id'],message['id']);self.assertEqual(self.row('conversation_messages',message['id']),message)
        with self.database.transaction() as connection: self.assertEqual(connection.execute("SELECT count(*) FROM conversation_messages WHERE message_type='CARD_RESPONSE'").fetchone()[0],1)


class CommentRetryTests(unittest.TestCase):
    facts=comment_fixtures.CommentAcceptanceTests.facts
    write_body=comment_fixtures.CommentAcceptanceTests.write_body
    row=comment_fixtures.CommentAcceptanceTests.row
    create_payload=comment_fixtures.CommentAcceptanceTests.create_payload
    make_comment=comment_fixtures.CommentAcceptanceTests.make_comment
    command_payload=comment_fixtures.CommentAcceptanceTests.command_payload
    modify=comment_fixtures.CommentAcceptanceTests.modify

    def setUp(self):
        comment_fixtures.CommentAcceptanceTests.setUp(self);self.make_comment();accepted=self.modify();self.assertEqual(accepted['code'],'GUIDE_ACCEPTED');self.failed=accepted['data']['id']
        self.assertEqual(commands.fail_guide_run(self.database,{'guide_run_id':self.failed,'error_code':'MODEL_ERROR','safe_message':'失败'},process_lock=self.lock,clock=lambda:comment_fixtures.NOW+timedelta(seconds=1))['code'],'RUN_FAILED')

    def retry(self):
        return commands.retry_guide_run(self.executor,{'guide_run_id':self.failed,'idempotency_key':OTHER},catalog=self.catalog,clock=lambda:comment_fixtures.NOW+timedelta(seconds=2))

    def test_retry_comment_retains_actual_anchor_ceiling_without_scope_expansion(self):
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE guide_runs SET scope_type='DOCUMENT',scope_ref_json=NULL WHERE id=?",(self.failed,))
        before=self.facts();self.assertEqual(self.retry()['code'],'SCOPE_INVALID');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE guide_runs SET scope_type='BLOCK',scope_ref_json='{\"block_id\":1}' WHERE id=?",(self.failed,))
        result=self.retry();self.assertEqual(result['code'],'GUIDE_RETRY_ACCEPTED',result)
        run=self.row('guide_runs',result['data']['id']);self.assertEqual([target['block_id'] for target in json.loads(run['allowed_targets_json'])['targets']],[1])

    def test_deleted_or_resolved_source_refuses_no_anchor_correction(self):
        from backend.app.comments.commands import resolve_comment, delete_comment
        self.assertEqual(resolve_comment(self.executor,{'comment_id':1,'idempotency_key':OTHER},clock=lambda:comment_fixtures.NOW+timedelta(seconds=2))['code'],'COMMENT_UPDATED')
        before=self.facts();self.assertEqual(self.retry()['code'],'SOURCE_INVALID');self.assertEqual(self.facts(),before)
        self.assertEqual(delete_comment(self.executor,{'comment_id':1,'idempotency_key':OTHER},clock=lambda:comment_fixtures.NOW+timedelta(seconds=2))['code'],'COMMENT_UPDATED')
        before=self.facts();self.assertEqual(self.retry()['code'],'SOURCE_INVALID');self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
