"""D-010 same-snapshot proof gates; no trusted receipt/C07/model effect claim.

Card producer rows are explicit historical fixtures. USER declarations and
formal replies, scope/manifest and original source pairs use real SQLite
commands/read transactions, with no fabricated future adoption provenance.
"""
from copy import deepcopy
from datetime import timedelta
import json
import unittest

from backend.app.guide import commands
from backend.app.guide.model_context import read_context
from backend.app.guide.output_evidence import (OutputEvidenceInvalid, card_text,
    validate_card_output, fact_declaration, validate_fact_patches)
from backend.app.documents.patch_validation import validate_patch
from backend.app.documents.patch_errors import PatchInvalid, TargetStale
from backend.app.documents.scopes import restore_authority
from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.snapshot import assign_identities, Provenance
from backend.app.documents.commands import start_manual_draft, save_manual_draft, complete_manual_draft
from backend.app.documents.tables import table_model
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.resources import ResourceCatalog, ProtocolInvalid, DEFAULT_ROOT
from backend.app.infrastructure.identifiers import entity_id, message_sequence, EntityKind
from backend.tests.documents.test_patch_validation import patch
from backend.tests.requirements import test_create_requirement as creation
from backend.tests.guide import test_cards as formal
from backend.tests.messages.test_queries import cards_fixture


class OutputEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture=creation.CreateRequirementTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups);self.fixture.catalog=ResourceCatalog()
        self.created=self.fixture.create()['data'];self.req=self.created['requirement']['id']
        self.run=self.created['guide_run_id'];self.tick=2

    def inputs(self,connection,identity=None,fixture=None):
        fixture=self.fixture if fixture is None else fixture
        data=read_context(connection,self.run if identity is None else identity,fixture.catalog)['data']
        current=data['current_document'];run=data['run'];sources=DocumentSources(connection,self.req,fixture.catalog)
        snapshot=validate_snapshot(current['markdown_content'],current['block_state_json'],sources)
        scope=restore_authority(snapshot,run['action_type'],run['scope_type'],None if run['scope_ref_json'] is None else json.loads(run['scope_ref_json']),run['allowed_targets_json'])
        function=fixture.catalog.restore(run['function_type'],run['prompt_version'])
        template=fixture.catalog.template(data['requirement']['requirement_type'],data['template']['template_key'],data['template']['template_version'])
        return data,snapshot,scope,function,template

    def initial_patch(self,operation='REPLACE_BLOCK',proposed='审批人为部门经理。\n',identity=3):
        with self.fixture.database.transaction() as connection:
            data,snapshot,scope,function,template=self.inputs(connection)
            value=patch(snapshot,identity,operation,None if operation=='DELETE_BLOCK' else proposed)
            declaration=fact_declaration(snapshot,validate_patch(snapshot,value,scope))
        return value,declaration

    def accept_text(self,text):
        if self.run is not None:
            cancelled=commands.cancel_guide_run(self.fixture.executor,{'guide_run_id':self.run,'idempotency_key':f'00000000-0000-4000-8000-{self.tick:012d}'},clock=lambda:creation.INSTANT+timedelta(seconds=self.tick))
            self.assertEqual(cancelled['code'],'GUIDE_CANCELLED',cancelled);self.tick+=1
        with self.fixture.database.transaction() as connection:
            version=connection.execute("SELECT content_version FROM requirement_documents WHERE requirement_id=? AND document_type='CURRENT'",(self.req,)).fetchone()[0]
        result=commands.create_guide_run(self.fixture.executor,{'requirement_id':self.req,'expected_content_version':version,'action_type':'INITIALIZE','instruction':text,
            'scope_type':'DOCUMENT','source_type':'USER_INSTRUCTION','idempotency_key':f'00000000-0000-4000-8000-{self.tick:012d}'},catalog=self.fixture.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=self.tick))
        self.assertEqual(result['code'],'GUIDE_ACCEPTED',result);self.run=result['data']['guide_run']['id'];self.tick+=1
        return result['data']['user_message']

    def validate(self,values,*,fixture=None,identity=None,manifest_change=None):
        fixture=self.fixture if fixture is None else fixture
        before=fixture.facts()
        try:
            with fixture.database.transaction() as connection:
                data,snapshot,scope,function,template=self.inputs(connection,identity,fixture)
                manifest=deepcopy(data['read_manifest'])
                if manifest_change is not None:manifest_change(manifest)
                output={'schema_version':1,'response_type':'INITIALIZE_TEXT','message':'待验证的原始候选','confirmed_fact_patches':values}
                return validate_fact_patches(connection,requirement_id=self.req,snapshot=snapshot,authority=scope,output=output,manifest=manifest,
                    protocol=function,catalog=fixture.catalog,template=template,locked_heading_ids=data['template']['locked_heading_block_ids'])
        finally:self.assertEqual(fixture.facts(),before)

    def test_complete_actual_user_declarations_cover_replace_both_insert_directions_and_delete(self):
        for operation in ('REPLACE_BLOCK','INSERT_BEFORE','INSERT_AFTER','DELETE_BLOCK'):
            with self.subTest(operation=operation):
                value,declaration=self.initial_patch(operation)
                user=self.accept_text('\u3000'+declaration.replace('\n','\r\n')+'\t')
                result=self.validate([{'patch':value,'evidence':[{'message_id':user['id'],'quoted_text':user['content']}]}])
                self.assertIsNotNone(result)
                self.assertFalse(hasattr(result,'state'))
                if operation=='DELETE_BLOCK':self.assertNotIn(3,result.block_ids)
                else:self.assertIn('审批人为部门经理。',result.markdown)

    def test_negation_conditional_short_quote_and_assistant_sources_never_prove_fact(self):
        value,_=self.initial_patch()
        for content,quote in (('审批人尚未确定，不能写成部门经理。','审批人'),
            ('如果以后采用部门经理审批，也许可行；目前未决定。','部门经理'),('审批人为部门经理。','审批人为部门经理。')):
            user=self.accept_text(content)
            with self.assertRaises(OutputEvidenceInvalid):self.validate([{'patch':value,'evidence':[{'message_id':user['id'],'quoted_text':quote}]}])
        _,declaration=self.initial_patch()
        # Explicit historical assistant TEXT fixture, not a model-produced fact.
        with self.fixture.database.transaction(write=True) as connection:
            assistant_id=entity_id(connection,EntityKind.MESSAGE)
            connection.execute("INSERT INTO conversation_messages VALUES (?,?,?,?,'ASSISTANT',?,'TEXT',NULL,NULL,NULL,?)",
                (assistant_id,self.req,self.run,message_sequence(connection,self.req),declaration,'2026-10-04T08:00:00.000Z'))
        self.accept_text('请继续')
        with self.assertRaises(OutputEvidenceInvalid):self.validate([{'patch':value,'evidence':[{'message_id':assistant_id,'quoted_text':declaration}]}])

    def test_complete_quote_wrong_target_new_text_direction_and_missing_manifest_reject_whole_bundle(self):
        value,declaration=self.initial_patch();user=self.accept_text(declaration)
        fact={'patch':value,'evidence':[{'message_id':user['id'],'quoted_text':user['content']}]}
        for operation in ('INSERT_BEFORE','INSERT_AFTER'):
            changed=deepcopy(fact);changed['patch']['patch_operation']=operation
            with self.assertRaises(OutputEvidenceInvalid):self.validate([changed])
        changed=deepcopy(fact);changed['patch']['proposed_markdown']='审批人为财务负责人。'
        with self.assertRaises(OutputEvidenceInvalid):self.validate([changed])
        changed=deepcopy(fact);changed['patch']['target_ref']['block_id']=5
        with self.assertRaises((OutputEvidenceInvalid,TargetStale)):self.validate([fact,changed])
        for key in ('block_ids','message_ids'):
            with self.assertRaises(OutputEvidenceInvalid):self.validate([fact],manifest_change=lambda value:value[key].clear())
        changed=deepcopy(fact);changed['evidence'][0]['quoted_text']=user['content'][:-1]
        with self.assertRaises(OutputEvidenceInvalid):self.validate([changed])

    def test_v1_nonempty_fact_proof_is_not_silently_enabled_empty_remains_possible(self):
        value,declaration=self.initial_patch()
        self.fixture.catalog=ResourceCatalog(DEFAULT_ROOT)
        user=self.accept_text(declaration)
        with self.assertRaises(OutputEvidenceInvalid):self.validate([{'patch':value,'evidence':[{'message_id':user['id'],'quoted_text':user['content']}]}])
        self.assertIsNone(self.validate([]))

    def test_complete_confirmed_locked_title_change_and_unclosed_fence_still_rejected(self):
        for identity,proposed in ((1,'# 新的标题\n'),(3,'```\n代码\n')):
            value,declaration=self.initial_patch(identity=identity,proposed=proposed);user=self.accept_text(declaration)
            with self.assertRaises((OutputEvidenceInvalid,PatchInvalid)):
                self.validate([{'patch':value,'evidence':[{'message_id':user['id'],'quoted_text':user['content']}]}])

    def test_table_row_full_declaration_uses_real_manual_committed_baseline_exact_table_selector_and_cells(self):
        self.accept_text('准备真实人工表格')
        self.assertEqual(commands.cancel_guide_run(self.fixture.executor,{'guide_run_id':self.run,'idempotency_key':creation.OTHER},clock=lambda:creation.INSTANT+timedelta(seconds=10))['code'],'GUIDE_CANCELLED')
        started=start_manual_draft(self.fixture.executor,{'requirement_id':self.req,'expected_content_version':1,'idempotency_key':formal.KEY},catalog=self.fixture.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=11))
        self.assertEqual(started['code'],'DRAFT_STARTED',started);draft=started['data']['manual_draft']
        with self.fixture.database.transaction() as connection:
            sources=DocumentSources(connection,self.req,self.fixture.catalog)
            old=validate_snapshot(draft['markdown_content'],draft['block_state_json'],sources)
            block=old.by_id[3][0];markdown=old.parsed.markdown[:block.start_offset]+'| 键 | 值 |\n| --- | --- |\n| 审批人 | 未确定 |\n'+old.parsed.markdown[block.end_offset:]
            candidate=assign_identities(markdown,list(old.by_id),old.next_block_id,old,Provenance('USER','MANUAL_EDIT',draft['id']),'2026-10-04T08:00:12.000Z',sources)
        saved=save_manual_draft(self.fixture.database,{'requirement_id':self.req,'expected_version':draft['content_version'],'markdown_content':candidate.parsed.markdown,'block_state_json':candidate.state},catalog=self.fixture.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=12))
        self.assertEqual(saved['code'],'DRAFT_SAVED',saved)
        completed=complete_manual_draft(self.fixture.executor,{'requirement_id':self.req,'expected_version':saved['data']['content_version'],'idempotency_key':formal.OTHER},catalog=self.fixture.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=13))
        self.assertEqual(completed['code'],'DRAFT_COMPLETED',completed)
        self.run=None;self.tick=20;self.accept_text('读取人工表格后的实际正文')
        with self.fixture.database.transaction() as connection:
            _,snapshot,scope,_,_=self.inputs(connection)
            table=table_model(snapshot.by_id[3][0]);value=patch(snapshot,3,'REPLACE_TABLE_ROW',None,{'key_column_index':0,'key_value':'审批人'},{'cells':['审批人','经理😀']},table.rows[0].markdown)
            declaration=fact_declaration(snapshot,validate_patch(snapshot,value,scope))
            self.assertIn('原表格：\n'+table.markdown,declaration)
            self.assertIn('行选择：{"key_column_index":0,"key_value":"审批人"}',declaration)
        user=self.accept_text(declaration);fact={'patch':value,'evidence':[{'message_id':user['id'],'quoted_text':user['content']}]}
        preview=self.validate([fact]);self.assertIn('经理😀',preview.markdown)
        changed=deepcopy(fact);changed['patch']['proposed_data_json']['cells'][1]='主任'
        with self.assertRaises(OutputEvidenceInvalid):self.validate([changed])
        changed=deepcopy(fact);changed['patch']['selector_json']['key_value']='不存在'
        with self.assertRaises(TargetStale):self.validate([changed])

    def test_exact_card_message_contains_complete_unicode_fields_and_real_raw_related_block(self):
        with self.fixture.database.transaction() as connection:
            data,snapshot,scope,function,_=self.inputs(connection)
        cards=cards_fixture();card=cards['cards'][0]
        card['question']='是否采用😀？\n完整链接[标签](https://example.org/事实)'
        card['related_spec_context']=[{'block_id':3,'content_snapshot':snapshot.by_id[3][0].markdown}]
        text=card_text(cards);self.assertIn('建议（尚未选择）：',text);self.assertIn('😀',text)
        output={'message':text,'cards':cards}
        self.assertEqual(validate_card_output(snapshot,data['read_manifest'],output,function),cards)
        original=deepcopy(output)
        for bad in ('摘要',text+'\n',text.replace('完整链接','省略')):
            with self.assertRaises(OutputEvidenceInvalid):validate_card_output(snapshot,data['read_manifest'],{**output,'message':bad},function)
        self.assertEqual(output,original)
        for related in ([{'block_id':3,'content_snapshot':'待确认。'}],[{'block_id':999,'content_snapshot':'虚构'}]):
            changed=deepcopy(output);changed['cards']['cards'][0]['related_spec_context']=related;changed['message']=card_text(changed['cards'])
            with self.assertRaises(OutputEvidenceInvalid):validate_card_output(snapshot,data['read_manifest'],changed,function)
        changed=deepcopy(output)
        changed['cards']['cards']=[{**deepcopy(card),'card_key':str(index),'question':'x'*10000,'context':'y'*10000} for index in range(5)]
        changed['message']=card_text(changed['cards'])
        with self.assertRaises(OutputEvidenceInvalid):validate_card_output(snapshot,data['read_manifest'],changed,function)

    def test_card_object_key_order_does_not_change_fixed_display_and_card_array_order_does(self):
        cards=cards_fixture();cards['cards'].append({**deepcopy(cards['cards'][0]),'card_key':'second','related_spec_context':[],'recommendation':None})
        def reverse(value):
            if type(value) is dict:return {key:reverse(child) for key,child in reversed(list(value.items()))}
            if type(value) is list:return [reverse(child) for child in value]
            return value
        text=card_text(cards);self.assertEqual(card_text(reverse(cards)),text)
        self.assertIn('\n\n卡片："second"',text);self.assertIn('相关需求原文：[]',text);self.assertFalse(text.endswith('\n'))
        changed=deepcopy(cards);changed['cards'].reverse();self.assertNotEqual(card_text(changed),text)

    def formal_fact(self, *, choice='confirm', changes=None, large=False):
        fixture=formal.CardSubmissionTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.catalog=ResourceCatalog();identity=fixture.run
        with fixture.database.transaction() as connection:
            _,snapshot,scope,function,_=self.inputs(connection,identity,fixture)
            value=patch(snapshot,3,proposed=('😀事实'*2800 if large else '审批人为部门经理。\n'))
            declaration=fact_declaration(snapshot,validate_patch(snapshot,value,scope))
        card=cards_fixture()['cards'][0]
        card.update(card_type='CONFIRM',question=declaration+'\n是否确认以上事实和变更写入需求？',required=False,
            options=[{'option_key':key,'label':label,'description':'完整事实如上','impact':'','risks':''} for key,label in (('confirm','确认以上事实和变更'),('defer','尚未确认'))],
            selection_rule={'min':1,'max':1},custom_answer={'enabled':False,'max_length':0},recommendation=None,
            related_spec_context=[{'block_id':3,'content_snapshot':snapshot.by_id[3][0].markdown}])
        if changes is not None:changes(card)
        original_cards=[card]
        if large:
            second=deepcopy(card);second['card_key']='second'
            other=patch(snapshot,5,proposed='第二条😀事实'*1300)
            second['question']=fact_declaration(snapshot,validate_patch(snapshot,other,scope))+'\n是否确认以上事实和变更写入需求？'
            second['related_spec_context']=[{'block_id':5,'content_snapshot':snapshot.by_id[5][0].markdown}]
            original_cards.append(second)
        fixture.initialize_cards_fixture(structured={'schema_version':1,'intro':'明确历史生产夹具','cards':original_cards})
        answer={'card_key':'first','selected_option_keys':[] if choice is None else [choice],'custom_answer':None,'skipped':choice is None}
        answers=[{**answer,'card_key':item['card_key']} for item in original_cards]
        result=fixture.submit(responses=answers);self.assertEqual(result['code'],'CARDS_ACCEPTED',result)
        user=result['data']['response_message'];new=result['data']['guide_run']['id']
        chunks=[user['content'][index:index+10000] for index in range(0,len(user['content']),10000)]
        return fixture,new,{'patch':value,'evidence':[{'message_id':user['id'],'quoted_text':chunk} for chunk in chunks]}

    def test_actual_formal_confirm_complete_answer_proves_only_its_original_exact_card(self):
        fixture,identity,fact=self.formal_fact()
        result=self.validate([fact],fixture=fixture,identity=identity);self.assertIn('审批人为部门经理。',result.markdown)
        with self.assertRaises(OutputEvidenceInvalid):self.validate([fact],fixture=fixture,identity=identity,manifest_change=lambda manifest:manifest['message_ids'].remove(11))
        changed=deepcopy(fact);changed['patch']['proposed_markdown']='假定事实。'
        with self.assertRaises(OutputEvidenceInvalid):self.validate([changed],fixture=fixture,identity=identity)

    def test_defer_skip_unchosen_recommendation_and_nonexact_card_do_not_prove_confirmation(self):
        for choice,changes in (('defer',None),(None,None),('defer',lambda card:card.update(recommendation={'option_keys':['confirm'],'reason':'助手建议'})),
            ('confirm',lambda card:card.update(question='是否由经理审批？')),('confirm',lambda card:card['related_spec_context'][0].update(content_snapshot='短原文'))):
            fixture,identity,fact=self.formal_fact(choice=choice,changes=changes)
            with self.assertRaises(OutputEvidenceInvalid):self.validate([fact],fixture=fixture,identity=identity)

    def test_whole_large_formal_summary_requires_all_ordered_codepoint_chunks_without_partial_repair(self):
        fixture,identity,fact=self.formal_fact(large=True)
        self.assertEqual(len(fact['evidence']),2)
        self.assertIsNotNone(self.validate([fact],fixture=fixture,identity=identity))
        for fragments in (fact['evidence'][:1],list(reversed(fact['evidence'])),fact['evidence']+[fact['evidence'][-1]]):
            changed=deepcopy(fact);changed['evidence']=fragments
            with self.assertRaises(OutputEvidenceInvalid):self.validate([changed],fixture=fixture,identity=identity)
        for quoted in ('确认以上事实和变更',fact['evidence'][0]['quoted_text'][:100]):
            changed=deepcopy(fact);changed['evidence'][0]['quoted_text']=quoted
            with self.assertRaises(OutputEvidenceInvalid):self.validate([changed],fixture=fixture,identity=identity)
