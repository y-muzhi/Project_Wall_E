"""Creation accepts a durable real initialization run in one file transaction."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from backend.app.documents.queries import get_current_document
from backend.app.documents.scopes import resolve_scope
from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.database import Database, CommitOutcomeUnknown
from backend.app.infrastructure.idempotency import Idempotency, Scope
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ResourceCatalog, ConfigInvalid, DEFAULT_ROOT
from backend.app.requirements.commands import create_requirement
from backend.app.requirements.contracts import create_requirement_input
from backend.app.shared.validation import MAX_SAFE_INTEGER

KEY='00000000-0000-4000-8000-00000000000a'
OTHER='00000000-0000-4000-8000-00000000000b'
INSTANT=datetime(2026,10,4,8,tzinfo=timezone.utc)


class CreateRequirementTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='walle-create-real-')
        self.path=Path(self.directory.name)/'actual.sqlite'
        self.database=Database(self.path);self.database.initialize()
        self.lock=ProcessLock.for_database(self.path).acquire()
        self.addCleanup(self.directory.cleanup);self.addCleanup(self.lock.release)
        self.executor=Idempotency(self.database,self.lock,clock=lambda:INSTANT)
        self.catalog=ResourceCatalog(DEFAULT_ROOT)  # preserve all existing v1 assertions

    def payload(self,**changes):
        return {'title':'\u3000需求😀\t','requirement_type':'NEW','template_key':'new-requirement','template_version':'v1','initial_idea':'\u3000first\r\nsecond\t','initialization_mode':'DESIGN','idempotency_key':KEY,**changes}

    def create(self,**changes):
        return create_requirement(self.executor,self.payload(**changes),catalog=self.catalog,clock=lambda:INSTANT)

    def facts(self):
        with closing(sqlite3.connect(self.path)) as connection: return list(connection.iterdump())

    def test_exact_real_template_current_user_message_and_frozen_run_are_accepted_together(self):
        with patch('socket.socket.connect',side_effect=AssertionError('Creation must not access Provider')):
            result=self.create()
        self.assertEqual(result['code'],'CREATED',result);root=result['data']['requirement']
        self.assertEqual((root['id'],root['title'],root['requirement_no'],root['status'],root['document_work_state']),(1,'需求😀','REQ000001','INITIALIZING','GUIDE_ACTIVE'))
        self.assertEqual(set(result['data']),{'requirement','current_document_id','guide_run_id'})
        current=get_current_document(self.database,1,catalog=self.catalog)['data']
        self.assertEqual(current['markdown_content'],self.catalog.template('NEW','new-requirement','v1').markdown)
        self.assertEqual(current['content_version'],1)
        with self.database.transaction() as connection:
            message=dict(connection.execute('SELECT * FROM conversation_messages').fetchone());run=dict(connection.execute('SELECT * FROM guide_runs').fetchone())
            self.assertEqual((message['content'],message['sequence_no'],message['role'],message['message_type'],message['structured_content_json'],message['reply_to_message_id']),('first\nsecond',1,'USER','TEXT',None,None))
            self.assertEqual((message['guide_run_id'],run['trigger_message_id'],run['idempotency_key']),(run['id'],message['id'],KEY))
            self.assertEqual((run['function_type'],run['context_template_key'],run['context_template_version'],run['prompt_version'],run['action_type'],run['mode_snapshot']),('INITIALIZE_REQUIREMENT','INITIALIZE_CONTEXT','v1','v1','INITIALIZE','DESIGN'))
            self.assertEqual((run['status'],run['current_step'],run['started_at'],run['ended_at'],run['final_result_json']),('RUNNING','PREPARING',None,None,None))
            self.assertEqual(run['instruction_summary'],message['content'])
            manifest=json.loads(run['read_scope_manifest_json']);function=self.catalog.freeze('INITIALIZE','USER_INSTRUCTION');self.assertEqual(function.validate_read_manifest(manifest),manifest)
            self.assertEqual(manifest['message_ids'],[message['id']]);self.assertEqual((manifest['document_id'],manifest['content_version']),(current['id'],1))
            snapshot=validate_snapshot(current['markdown_content'],current['block_state_json'],DocumentSources(connection,1,self.catalog))
            scope=resolve_scope(snapshot,'INITIALIZE','DOCUMENT')
            self.assertEqual(json.loads(run['allowed_targets_json']),{'schema_version':1,'targets':scope.targets_json});self.assertEqual(manifest['block_ids'],list(scope.read_ids))
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(),[])
            for table in ('llm_uses','revisions','comments','manual_edit_sessions'):
                self.assertEqual(connection.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertNotIn('initial_idea',[r[1] for r in connection.execute('PRAGMA table_info(requirements)')])

    def test_change_type_uses_actual_change_template_and_distinct_number(self):
        self.create();result=self.create(requirement_type='CHANGE',template_key='change-requirement',idempotency_key=OTHER,initialization_mode='IDEATION')
        self.assertEqual(result['code'],'CREATED',result);root=result['data']['requirement'];self.assertEqual(root['requirement_no'],'REQ000002')
        current=get_current_document(self.database,root['id'],catalog=self.catalog)['data']
        self.assertEqual(current['markdown_content'],self.catalog.template('CHANGE','change-requirement','v1').markdown)

    def test_all_mandatory_fields_strict_text_enums_and_unicode_reject_without_claim(self):
        before=self.facts();base=self.payload()
        variants=[{k:v for k,v in base.items() if k!=missing} for missing in base]
        variants += [self.payload(**changes) for changes in ({'title':'a\nb'},{'title':'😀'*21},{'initial_idea':' '},{'initial_idea':'x'*10001},{'requirement_type':'new'},{'initialization_mode':None},{'template_key':''},{'template_version':'x'*65},{'initial_idea':'\ud800'},{'extra':1})]
        for payload in variants:
            with self.subTest(fields=list(payload)):
                self.assertEqual(create_requirement(self.executor,payload)['code'],'INVALID_INPUT');self.assertEqual(self.facts(),before)

    def test_template_mismatch_and_missing_protocol_reject_without_allocating_resources(self):
        before=self.facts()
        for fields in ({'requirement_type':'CHANGE'},{'template_key':'missing'},{'template_version':'missing'}):
            self.assertEqual(self.create(**fields)['code'],'TEMPLATE_INVALID');self.assertEqual(self.facts(),before)
        with patch.object(self.catalog,'freeze',side_effect=ConfigInvalid('frozen protocol missing')):
            self.assertEqual(self.create()['code'],'CONFIG_INVALID')
        self.assertEqual(self.facts(),before)

    def test_normalized_same_input_replays_original_resources_even_if_catalog_later_unavailable(self):
        result=self.create();before=self.facts()
        with patch.object(self.catalog,'freeze',side_effect=ConfigInvalid('not reread for replay')):
            replay=self.create(title='需求😀',initial_idea='first\nsecond',idempotency_key=KEY.upper())
        self.assertEqual(replay,result);self.assertEqual(self.facts(),before)
        self.assertEqual(self.create(initial_idea='different')['code'],'IDEMPOTENCY_CONFLICT');self.assertEqual(self.facts(),before)

    def test_each_real_insert_and_success_failure_rolls_back_all_four_aggregates_and_sequences(self):
        for table,event,predicate in (('sequences','AFTER INSERT',''),('requirements','AFTER INSERT',''),('requirement_documents','AFTER INSERT',''),('conversation_messages','AFTER INSERT',''),('guide_runs','AFTER INSERT',''),('idempotency_records','BEFORE UPDATE',"WHEN NEW.status='SUCCEEDED'")):
            with self.subTest(table=table):
                with closing(sqlite3.connect(self.path)) as connection:
                    connection.execute(f"CREATE TRIGGER creation_fault {event} ON {table} {predicate} BEGIN SELECT RAISE(ABORT,'actual create failure'); END");connection.commit()
                before=self.facts();self.assertEqual(self.create()['code'],'STORAGE_UNAVAILABLE');self.assertEqual(self.facts(),before)
                with closing(sqlite3.connect(self.path)) as connection: connection.execute('DROP TRIGGER creation_fault');connection.commit()

    def test_result_conversion_failure_after_actual_acceptance_rolls_back_everything(self):
        before=self.facts()
        with patch('backend.app.requirements.commands.create_requirement_result',side_effect=ValueError('after actual acceptance writes')):
            self.assertEqual(self.create()['code'],'INTERNAL_ERROR')
        self.assertEqual(self.facts(),before)

    def test_every_entity_and_six_digit_number_exhaustion_is_atomic(self):
        for kind,maximum in (('Requirement',MAX_SAFE_INTEGER),('RequirementDocument',MAX_SAFE_INTEGER),('ConversationMessage',MAX_SAFE_INTEGER),('GuideRun',MAX_SAFE_INTEGER),('RequirementNumber',999999)):
            with self.subTest(kind=kind):
                with self.database.transaction(write=True) as connection: connection.execute('INSERT INTO sequences VALUES (?,?)',(kind,maximum))
                before=self.facts();self.assertEqual(self.create()['code'],'CAPACITY_EXHAUSTED');self.assertEqual(self.facts(),before)
                with self.database.transaction(write=True) as connection: connection.execute('DELETE FROM sequences')

    def test_real_competing_same_key_accepts_only_one_run_and_message(self):
        with ThreadPoolExecutor(max_workers=2) as pool: results=[future.result() for future in [pool.submit(self.create),pool.submit(self.create)]]
        self.assertIn('CREATED',[result['code'] for result in results]);self.assertTrue(all(result['code'] in ('CREATED','REQUEST_IN_PROGRESS') for result in results))
        result=self.create();self.assertEqual(result['code'],'CREATED')
        with self.database.transaction() as connection:
            for table in ('requirements','requirement_documents','guide_runs','conversation_messages'):
                self.assertEqual(connection.execute('SELECT count(*) FROM '+table).fetchone()[0],1)

    def test_real_commit_lost_ack_returns_original_acceptance_without_duplicate(self):
        class LostAck(Database):
            writes=0
            @contextmanager
            def transaction(database,*,write=False):
                with super().transaction(write=write) as connection: yield connection
                if write:
                    database.writes+=1
                    if database.writes==2: raise CommitOutcomeUnknown('actual creation commit acknowledged late')
        executor=Idempotency(LostAck(self.path),self.lock,clock=lambda:INSTANT)
        self.assertEqual(create_requirement(executor,self.payload(),catalog=self.catalog,clock=lambda:INSTANT)['code'],'STORAGE_UNAVAILABLE')
        before=self.facts();self.assertEqual(self.create()['code'],'CREATED');self.assertEqual(self.facts(),before)

    def test_processing_original_input_cannot_create_business_rows(self):
        business=create_requirement_input(self.payload()).business_input()
        self.executor.claim(Scope('APP-REQ-CMD-C01','Requirements',KEY),business)
        before=self.facts();self.assertEqual(self.create()['code'],'REQUEST_IN_PROGRESS');self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
