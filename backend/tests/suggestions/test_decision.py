"""C01 decisions on real stored aggregates, no CURRENT adoption."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import timedelta
import sqlite3
import unittest
from unittest.mock import patch
from backend.app.infrastructure.database import Database, CommitOutcomeUnknown
from backend.app.infrastructure.idempotency import Idempotency, Scope
from backend.app.suggestions import commands
from backend.tests.suggestions import test_discard as fixtures
from backend.tests.requirements import test_create_requirement as creation

KEY2='00000000-0000-4000-8000-00000000000c'


class DecisionTests(unittest.TestCase):
    facts=fixtures.DiscardTests.facts
    payload=fixtures.DiscardTests.payload
    create=fixtures.DiscardTests.create
    row=fixtures.DiscardTests.row
    terminal=fixtures.DiscardTests.terminal
    batch_fixture=fixtures.DiscardTests.batch_fixture
    add_suggestion=fixtures.DiscardTests.add_suggestion
    discard=fixtures.DiscardTests.discard

    def setUp(self): fixtures.DiscardTests.setUp(self)

    def decide(self,decision='ACCEPTED',**changes):
        return commands.decide_suggestion(self.executor,{'suggestion_id':10,'decision':decision,'idempotency_key':creation.KEY,**changes},catalog=self.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=1))

    def test_decision_changes_only_decision_fields_and_batch_time_full_counts(self):
        for identity,status in ((11,'ACCEPTED'),(12,'REJECTED'),(13,'EDITED')): self.add_suggestion(identity,identity-9,status)
        original=self.row('suggestions',10);root=self.row('requirements',self.req);current=self.row('requirement_documents',self.created['current_document_id'])
        result=self.decide();self.assertEqual(result['code'],'SUGGESTION_DECIDED',result)
        self.assertEqual(result['data']['counts'],{'total':4,'pending':0,'accepted':2,'rejected':1,'edited':1})
        updated=self.row('suggestions',10)
        for field in set(original)-{'status','user_edited_content','decided_at','updated_at','validation_status','validation_error'}: self.assertEqual(updated[field],original[field])
        self.assertEqual(updated['decided_at'],updated['updated_at']);self.assertEqual(self.row('requirements',self.req),root);self.assertEqual(self.row('requirement_documents',current['id']),current)

    def test_edit_reject_accept_clear_content_and_successful_validation_result(self):
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE suggestions SET validation_status='INVALID',validation_error='safe prior validation'")
        edited=self.decide('EDITED',edited_content='\r\n# 用户😀\r\n');self.assertEqual(edited['code'],'SUGGESTION_DECIDED',edited)
        self.assertEqual(edited['data']['suggestion']['user_edited_content'],'\r\n# 用户😀\r\n')
        self.assertEqual((edited['data']['suggestion']['validation_status'],edited['data']['suggestion']['validation_error']),('VALID',None))
        rejected=self.decide('REJECTED',idempotency_key=creation.OTHER);self.assertEqual(rejected['data']['counts']['rejected'],1);self.assertIsNone(rejected['data']['suggestion']['user_edited_content'])
        accepted=self.decide('ACCEPTED',idempotency_key=KEY2);self.assertEqual(accepted['data']['counts']['accepted'],1);self.assertIsNone(accepted['data']['suggestion']['user_edited_content'])

    def test_row_edits_exact_cells_width_plain_text_no_extra_fields_and_delete_no_edit(self):
        self.add_suggestion(11,2,operation='REPLACE_TABLE_ROW');self.add_suggestion(12,3,operation='DELETE_BLOCK')
        for text in ('{"cells":["one"]}','{"cells":["one",2]}','{"cells":["one","two"],"extra":1}','{"cells":["one","two"],"cells":["bad"]}','{"cells":["one","two\\nline"]}'):
            before=self.facts();self.assertEqual(self.decide('EDITED',suggestion_id=11,edited_content=text)['code'],'PATCH_INVALID');self.assertEqual(self.facts(),before)
        text=' { "cells": ["键😀", " <b>|\\\\x " ] } '
        result=self.decide('EDITED',suggestion_id=11,edited_content=text);self.assertEqual(result['code'],'SUGGESTION_DECIDED',result);self.assertEqual(result['data']['suggestion']['user_edited_content'],text)
        before=self.facts();self.assertEqual(self.decide('EDITED',suggestion_id=12,edited_content='x')['code'],'PATCH_INVALID');self.assertEqual(self.facts(),before)

    def test_block_edit_requires_one_block_and_preserves_invalid_prior_state_on_failure(self):
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE suggestions SET validation_status='INVALID',validation_error='safe existing failure'")
        for text in (' \n\t','first\n\nsecond\n','# heading\nparagraph\n'):
            before=self.facts();self.assertEqual(self.decide('EDITED',edited_content=text)['code'],'PATCH_INVALID');self.assertEqual(self.facts(),before)
        self.assertEqual(self.decide('EDITED',edited_content='<div>inert raw HTML</div>')['code'],'SUGGESTION_DECIDED')

    def test_strict_inputs_zero_claim_and_missing_suggestion(self):
        before=self.facts()
        for payload in ({},{'suggestion_id':True,'decision':'ACCEPTED','idempotency_key':creation.KEY},{'suggestion_id':10,'decision':'PENDING','idempotency_key':creation.KEY},{'suggestion_id':10,'decision':'EDITED','idempotency_key':creation.KEY},{'suggestion_id':10,'decision':'EDITED','edited_content':'\ud800','idempotency_key':creation.KEY},{'suggestion_id':10,'decision':'ACCEPTED','edited_content':'x','idempotency_key':creation.KEY},{'suggestion_id':10,'decision':'EDITED','edited_content':'x'*100001,'idempotency_key':creation.KEY}):
            self.assertEqual(commands.decide_suggestion(self.executor,payload)['code'],'INVALID_INPUT');self.assertEqual(self.facts(),before)
        self.assertEqual(self.decide(suggestion_id=999)['code'],'NOT_FOUND');self.assertEqual(self.facts(),before)

    def test_native_occupancy_lifecycle_and_ended_batch_gates_without_current_version_gate(self):
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE requirement_documents SET markdown_content='damaged later content',content_version=9")
        self.assertEqual(self.decide()['code'],'SUGGESTION_DECIDED')
        self.assertEqual(self.discard()['code'],'BATCH_DISCARDED');before=self.facts()
        self.assertEqual(self.decide('REJECTED',idempotency_key=creation.OTHER)['code'],'STATE_CONFLICT');self.assertEqual(self.facts(),before)

    def test_atomic_sql_result_failure_and_clock_regression_preserve_original_decision(self):
        for table,predicate in (('suggestions',''),('suggestion_batches',''),('idempotency_records',"WHEN NEW.status='SUCCEEDED'")):
            with closing(sqlite3.connect(self.path)) as connection:
                connection.execute(f"CREATE TRIGGER decision_fault AFTER UPDATE ON {table} {predicate} BEGIN SELECT RAISE(ABORT,'actual decision failure'); END");connection.commit()
            before=self.facts();self.assertEqual(self.decide()['code'],'STORAGE_UNAVAILABLE');self.assertEqual(self.facts(),before)
            with closing(sqlite3.connect(self.path)) as connection: connection.execute('DROP TRIGGER decision_fault');connection.commit()
        before=self.facts()
        with patch('backend.app.suggestions.commands.decide_suggestion_result',side_effect=ValueError('private result failure')): self.assertEqual(self.decide()['code'],'INTERNAL_ERROR')
        self.assertEqual(self.facts(),before)
        result=commands.decide_suggestion(self.executor,{'suggestion_id':10,'decision':'ACCEPTED','idempotency_key':creation.KEY},catalog=self.catalog,clock=lambda:creation.INSTANT-timedelta(seconds=1))
        self.assertEqual(result['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)

    def test_normalized_input_replay_is_original_even_after_changed_decision_and_discard(self):
        first=self.decide('EDITED',edited_content='original user Markdown');self.assertEqual(first['code'],'SUGGESTION_DECIDED')
        self.assertEqual(self.decide('REJECTED',idempotency_key=creation.OTHER)['code'],'SUGGESTION_DECIDED');self.discard();before=self.facts()
        self.assertEqual(self.decide('EDITED',edited_content='original user Markdown',idempotency_key=creation.KEY.upper()),first);self.assertEqual(self.facts(),before)
        self.assertEqual(self.decide('EDITED',edited_content='other')['code'],'IDEMPOTENCY_CONFLICT');self.assertEqual(self.facts(),before)

    def test_real_commit_lost_ack_and_actual_processing_claim(self):
        class LostAck(Database):
            writes=0
            @contextmanager
            def transaction(database,*,write=False):
                with super().transaction(write=write) as connection: yield connection
                if write:
                    database.writes+=1
                    if database.writes==2: raise CommitOutcomeUnknown('after native decision commit')
        executor=Idempotency(LostAck(self.path),self.lock,clock=lambda:creation.INSTANT)
        result=commands.decide_suggestion(executor,{'suggestion_id':10,'decision':'ACCEPTED','idempotency_key':creation.KEY},catalog=self.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=1))
        self.assertEqual(result['code'],'STORAGE_UNAVAILABLE');before=self.facts();self.assertEqual(self.decide()['code'],'SUGGESTION_DECIDED');self.assertEqual(self.facts(),before)
        claim=self.executor.claim(Scope('APP-BATCH-CMD-C01','Suggestion:10',creation.OTHER),{'suggestion_id':10,'decision':'REJECTED','edited_content':None})
        before=self.facts();self.assertEqual(self.decide('REJECTED',idempotency_key=creation.OTHER)['code'],'REQUEST_IN_PROGRESS');self.assertEqual(self.facts(),before);self.executor.abandon(claim)

    def test_actual_decision_discard_competition_never_changes_after_terminal(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=[future.result() for future in (pool.submit(self.decide),pool.submit(self.discard))]
        self.assertEqual(results[1]['code'],'BATCH_DISCARDED');self.assertIn(results[0]['code'],('SUGGESTION_DECIDED','STATE_CONFLICT'))
        before=self.facts();self.assertEqual(self.decide('REJECTED',idempotency_key=creation.OTHER)['code'],'STATE_CONFLICT');self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
