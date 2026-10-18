"""Offline response delivery and write separation; no external model calls."""
from datetime import timedelta
import json
import unittest

from backend.app.guide import commands
from backend.app.guide.queries import get_guide_run
from backend.app.guide.response_display import response_text
from backend.tests.guide import test_orchestrator as orchestrator_fixture
from backend.tests.infrastructure import test_model_gateway as wire
from backend.tests.messages.test_queries import cards_fixture
from backend.tests.requirements import test_create_requirement as creation


class ResponseDisplayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.h=orchestrator_fixture.OrchestratorTests();await self.h.asyncSetUp()
        # The helper has no unittest async runner of its own. Transfer its
        # ordinary cleanups to this actual runner so locks precede temp cleanup.
        for function,args,kwargs in self.h._cleanups:self.addCleanup(function,*args,**kwargs)
        self.h._cleanups.clear()

    async def asyncTearDown(self):await self.h.asyncTearDown()

    def queue_text(self,content,finish='stop'):
        self.h.queue(raw=json.dumps(wire.envelope(choices=[{'message':{'role':'assistant','content':content},'finish_reason':finish}]),ensure_ascii=False).encode())

    async def delivered(self,content):
        h=self.h;f=h.fixture;before=f.row('requirement_documents',f.created['current_document_id'])
        result=await h.advance();self.assertEqual(result['code'],'AI_FINISHED',result)
        self.assertEqual(len(h.attempts()),1);self.assertEqual(h.delays,[])
        self.assertEqual(f.row('requirement_documents',before['id']),before)
        with f.database.transaction() as c:
            rows=c.execute("SELECT * FROM conversation_messages WHERE guide_run_id=? AND role='ASSISTANT'",(f.run,)).fetchall()
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['content'],content)
        self.assertEqual(f.row('requirements',f.req)['document_work_state'],'IDLE')
        self.assertEqual(get_guide_run(f.database,f.run,catalog=f.catalog)['code'],'READ_OK')

    async def test_plain_text_delivered_once_without_json_gate(self):
        content='收到你的答案，下一步确认交付物。😀\n<script>保留文字</script>'
        self.queue_text(content);await self.delivered(content)
        self.assertEqual(self.h.attempts()[0]['parse_status'],'FAILED')
        self.assertIsNone(self.h.attempts()[0]['trusted_output_json'])

    async def test_unknown_schema_fields_display_original_without_retry(self):
        value={'schema_version':1,'response_type':'INITIALIZE_TEXT','message':'模型正常说明','confirmed_fact_patches':[],'additional_field':'完整保留'}
        content=json.dumps(value,ensure_ascii=False);self.queue_text(content);await self.delivered(content)
        self.assertEqual(self.h.attempts()[0]['validation_status'],'FAILED')

    async def test_short_card_message_preserves_original_and_interactive_structure(self):
        self.h.helper.helper.v2();cards=cards_fixture();cards['cards'][0]['related_spec_context']=[]
        value={'schema_version':1,'response_type':'INITIALIZE_CARDS','message':'已记录你的选择，继续确认细节。','cards':cards,'confirmed_fact_patches':[]}
        self.h.queue(value);await self.delivered(value['message'])
        with self.h.fixture.database.transaction() as c:
            row=c.execute("SELECT * FROM conversation_messages WHERE role='ASSISTANT'").fetchone()
            self.assertEqual(row['message_type'],'INTERACTION_CARDS');self.assertEqual(json.loads(row['structured_content_json']),cards)

    async def test_truncated_return_delivered_once(self):
        content='{"message":"已经生成的部分内容'
        self.queue_text(content,'length');await self.delivered(content)

    async def test_unconfirmed_fact_shown_but_body_not_written(self):
        value=self.h.helper.facts_candidate();value['confirmed_fact_patches'][0]['evidence'][0]['quoted_text']='不是用户的完整确认'
        content=json.dumps(value,ensure_ascii=False);self.queue_text(content);await self.delivered(content)
        self.assertEqual(self.h.attempts()[0]['validation_status'],'FAILED')

    async def test_historical_failed_run_exposes_all_saved_returns_without_message_write(self):
        h=self.h;f=h.fixture;value={'schema_version':1,'response_type':'INITIALIZE_TEXT','message':'已返回但未被旧流程采用','confirmed_fact_patches':[],'extra':'仍可读'}
        identity=h.helper.helper.candidate(value);self.assertIsNone(h.helper.helper.produce(identity))
        result=commands.fail_guide_run(f.database,{'guide_run_id':f.run,'error_code':'OUTPUT_INVALID','safe_message':'模型输出未能通过程序校验'},process_lock=f.lock,clock=lambda:creation.INSTANT+timedelta(seconds=5))
        self.assertEqual(result['code'],'RUN_FAILED',result)
        before=f.facts();read=get_guide_run(f.database,f.run,catalog=f.catalog)
        self.assertEqual(read['code'],'READ_OK',read);self.assertEqual(read['data']['returned_responses'][0]['content'],json.dumps(value,ensure_ascii=False))
        self.assertIsNone(read['data']['latest_assistant_message_id']);self.assertEqual(f.facts(),before)


class ResponseTextTests(unittest.TestCase):
    def test_all_choices_tool_refusal_and_nontext_content_are_readable(self):
        raw={'choices':[{'message':{'role':'assistant','content':'第一段','refusal':'拒绝原因'}},{'message':{'role':'assistant','content':[{'type':'text','text':'第二段'}],'tool_calls':[{'id':'call1'}]}}]}
        result=response_text(raw)
        for fragment in ('第一段','拒绝原因','第二段','call1'):self.assertIn(fragment,result)
        self.assertIsNone(response_text({'error':{'message':'未收到助手回复'}}))
