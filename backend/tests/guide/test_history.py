"""C02 real WAL history pages; explicit historical protocol fixtures."""
from contextlib import contextmanager
import unittest
from unittest.mock import patch
from backend.app.guide.queries import list_guide_runs, get_guide_run
from backend.app.guide.contracts import STATUS_FIELDS
from backend.app.infrastructure.database import Database
from backend.app.infrastructure.guide_repository import GuideRepository
from backend.tests.guide import test_queries as fixtures
from backend.tests.requirements import test_queries as requirement_fixtures
from backend.tests.requirements import test_create_requirement as creation


class GuideHistoryTests(unittest.TestCase):
    facts=fixtures.GuideQueryTests.facts
    payload=fixtures.GuideQueryTests.payload
    create=fixtures.GuideQueryTests.create
    row=fixtures.GuideQueryTests.row
    protocol_run_fixture=fixtures.GuideQueryTests.protocol_run_fixture

    def setUp(self):
        fixtures.GuideQueryTests.setUp(self)

    def read(self,**changes):
        return list_guide_runs(self.database,{'requirement_id':self.req,**changes})

    def test_fixed_twenty_order_created_id_and_out_of_range_preserves_page(self):
        for identity in range(10,34): self.protocol_run_fixture(identity,action='ASK')
        before=self.facts();first=self.read();second=self.read(page=2);last=self.read(page=100000)
        self.assertEqual(first['code'],'READ_OK',first)
        self.assertEqual([item['id'] for item in first['data']['items']],list(range(33,13,-1)))
        self.assertEqual([item['id'] for item in second['data']['items']],[13,12,11,10,1])
        self.assertEqual(last['data'],{'items':[],'page':100000,'page_size':20,'total':25,'total_pages':2})
        self.assertEqual(self.facts(),before)

    def test_status_action_or_and_dedupe_all_enums_without_current_action_permissions(self):
        for identity,action,status in ((10,'ASK','CANCELLED'),(11,'REVIEW','FAILED'),(12,'ASK','WAITING_USER')):
            self.protocol_run_fixture(identity,action=action)
            with self.database.transaction(write=True) as connection:
                connection.execute('UPDATE guide_runs SET status=?,current_step=?,ended_at=?,waiting_user_at=?,cancel_reason=?,error_code=?,error_message=? WHERE id=?',
                    (status,'WAITING_USER' if status=='WAITING_USER' else 'FINISHED',None if status=='WAITING_USER' else self.at,self.at if status=='WAITING_USER' else None,'USER_REQUESTED' if status=='CANCELLED' else None,'MODEL_ERROR' if status=='FAILED' else None,'safe historical fixture' if status=='FAILED' else None,identity))
        before=self.facts();result=self.read(status=['FAILED','CANCELLED','FAILED'],action_type=['ASK','REVIEW','ASK'])
        self.assertEqual([item['id'] for item in result['data']['items']],[11,10])
        self.assertEqual(self.read(status=['RUNNING','WAITING_USER','COMPLETED','FAILED','CANCELLED'],action_type=['INITIALIZE','ASK','REVIEW','MODIFY'])['data']['total'],4)
        self.assertEqual(self.read(action_type=['MODIFY'])['data']['items'],[]);self.assertEqual(self.facts(),before)

    def test_summary_never_selects_final_result_prompt_attempts_or_message_body(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE guide_runs SET status='COMPLETED',current_step='FINISHED',ended_at=?,final_result_json=? WHERE id=?",(self.at,'{"private_prompt":"private historical result"}',self.run))
        before=self.facts();trace=[];original=self.database.transaction
        @contextmanager
        def traced(*,write=False):
            with original(write=write) as connection:
                connection.set_trace_callback(trace.append);yield connection
        with patch.object(self.database,'transaction',new=traced): result=self.read()
        self.assertEqual(result['code'],'READ_OK',result);self.assertNotIn('final_result',result['data']['items'][0])
        self.assertEqual(set(result['data']['items'][0]),set(STATUS_FIELDS)-{'final_result'})
        for hidden in ('final_result_json','prompt_version','llm_uses','structured_content_json','markdown_content'):
            self.assertNotIn(hidden,'\n'.join(trace).lower())
        self.assertNotIn('private historical result',str(result));self.assertEqual(self.facts(),before)
        self.assertEqual(get_guide_run(self.database,self.run)['code'],'INTERNAL_ERROR')

    def test_missing_requirement_and_existing_empty_history_are_distinct(self):
        before=self.facts();self.assertEqual(self.read(requirement_id=999)['code'],'NOT_FOUND');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: requirement_fixtures.seed(connection,2)
        result=self.read(requirement_id=2,page=5)
        self.assertEqual(result,{'code':'READ_OK','data':{'items':[],'page':5,'page_size':20,'total':0,'total_pages':0},'details':None})

    def test_strict_inputs_are_rejected_without_writes(self):
        before=self.facts()
        for payload in ({},{'requirement_id':True},{'requirement_id':self.req,'status':None},{'requirement_id':self.req,'status':'RUNNING'},{'requirement_id':self.req,'status':['running']},{'requirement_id':self.req,'action_type':['']},{'requirement_id':self.req,'action_type':()},{'requirement_id':self.req,'page':'1'},{'requirement_id':self.req,'page':100001},{'requirement_id':self.req,'page':None},{'requirement_id':self.req,'query':1}):
            self.assertEqual(list_guide_runs(self.database,payload)['code'],'INVALID_INPUT');self.assertEqual(self.facts(),before)

    def test_count_and_items_use_one_actual_wal_snapshot_during_writer_commit(self):
        original=GuideRepository._count_history;committed=[]
        def after_count(repository,where,values):
            count=original(repository,where,values)
            self.protocol_run_fixture(10,action='ASK');committed.append(True)
            return count
        with patch.object(GuideRepository,'_count_history',new=after_count): result=self.read()
        self.assertEqual(committed,[True]);self.assertEqual(result['code'],'READ_OK',result)
        self.assertEqual((result['data']['total'],[item['id'] for item in result['data']['items']]),(1,[1]))
        self.assertEqual(self.read()['data']['total'],2)

    def test_foreign_requirement_records_never_enter_history_or_total(self):
        self.create(idempotency_key=creation.OTHER)
        result=self.read();self.assertEqual(result['data']['total'],1)
        self.assertEqual([item['id'] for item in result['data']['items']],[self.run])

    def test_broken_scope_and_result_mapping_fail_safely_without_repair(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE guide_runs SET scope_type='SECTION',scope_ref_json='{}' WHERE id=?",(self.run,))
        before=self.facts();self.assertEqual(self.read()['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE guide_runs SET scope_type='DOCUMENT',scope_ref_json=NULL WHERE id=?",(self.run,))
        before=self.facts()
        with patch('backend.app.guide.queries.list_guide_runs_result',side_effect=ValueError('private mapping failure')):
            self.assertEqual(self.read()['code'],'INTERNAL_ERROR')
        self.assertEqual(self.facts(),before)

    def test_uninitialized_storage_is_unavailable_without_creating_database(self):
        path=self.path.with_name('missing.sqlite')
        result=list_guide_runs(Database(path),{'requirement_id':self.req})
        self.assertEqual(result['code'],'STORAGE_UNAVAILABLE');self.assertFalse(path.exists())


if __name__=='__main__': unittest.main()
