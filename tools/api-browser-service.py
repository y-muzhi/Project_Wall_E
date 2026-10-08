"""Private browser verification runner: actual API/SQLite, no Provider.

Only explicit test database paths outside the default production path are
accepted. Startup uses production create_app. Stdin controls test shutdown;
Only the explicit commit-race flag adds a diagnostic read outside the business
API; it never changes a business HTTP response. Explicit private fixture
flags are isolated diagnostics and never evidence of real model production.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from backend.app.infrastructure.database import Database, ROOT
from backend.app.service import create_app
from backend.app.guide.worker import GuideWorker
from backend.app.shared.command_execution import operation_time
from backend.app.infrastructure.identifiers import entity_id, EntityKind, message_sequence
from backend.app.messages.cards import validate_cards


class HeldReviewWorker(GuideWorker):
    """Explicit private dispatch barrier for native cancellation evidence.

    REVIEW acceptance is real; orchestration waits before any model work.
    ASK/INITIALIZE/retries use the production worker. No status/result is faked.
    """
    async def _drive(self, identity, lease):
        with self.database.transaction() as connection:
            action = connection.execute('SELECT action_type FROM guide_runs WHERE id=?', (identity,)).fetchone()
        if action is not None and action[0] == 'REVIEW':
            await asyncio.Event().wait()
        else:
            await super()._drive(identity, lease)


class WaitingAskFixtureWorker(GuideWorker):
    """Isolated persisted WAITING fixture for positive I15/native UI binding.

    No model response/question/trusted output is fabricated or claimed. Only
    the named first ASK dispatch seeds the known state precondition. Its next
    dispatch runs production orchestration, with actual missing configuration.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs); self.seeded = set()

    async def _drive(self, identity, lease):
        if identity not in self.seeded:
            with self.database.transaction(write=True) as connection:
                row = connection.execute('SELECT r.action_type,m.content FROM guide_runs r '
                    'JOIN conversation_messages m ON m.id=r.trigger_message_id WHERE r.id=?', (identity,)).fetchone()
                if row is not None and row[0] == 'ASK' and row[1] == '真实等待回复夹具':
                    self.seeded.add(identity); at = operation_time(self.clock)
                    connection.execute("UPDATE guide_runs SET status='WAITING_USER',current_step='WAITING_USER',"
                        "waiting_user_at=?,updated_at=? WHERE id=? AND status='RUNNING' AND current_step='PREPARING'", (at,at,identity))
                    return
        await super()._drive(identity, lease)


class CardsFixtureWorker(GuideWorker):
    """Explicit isolated card availability preconditions, never model evidence.

    Only named I14 trigger text seeds a validated four-card assistant message
    plus its known COMPLETED initialization / WAITING ASK state. No LLMUse,
    trusted output, generated document or Provider effect is claimed. I36 and
    ordinary continuation use the unchanged production transactions/worker.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs); self.seeded = set()

    async def _drive(self, identity, lease):
        with self.database.transaction(write=True) as connection:
            row = connection.execute('SELECT r.*,m.content FROM guide_runs r JOIN conversation_messages m '
                'ON m.id=r.trigger_message_id WHERE r.id=?', (identity,)).fetchone()
            seed = row is not None and identity not in self.seeded and row['content'] in (
                '初始化卡片前置夹具', '等待卡片前置夹具', '文本替代卡片前置夹具')
            if seed:
                self.seeded.add(identity)
                option = lambda key: {'option_key':key,'label':'方案'+key,'description':'选项说明',
                    'impact':'影响说明','risks':'风险说明'}
                def card(key, kind='SINGLE_SELECT', required=True):
                    return {'card_key':key,'card_type':kind,'question':'问题'+key,'context':'原始问题背景',
                        'required':required,'options':[option('a'),option('b')],
                        'selection_rule':{'min':1,'max':3 if kind == 'MULTI_SELECT' else 1},
                        'custom_answer':{'enabled':kind != 'CONFIRM','max_length':0 if kind == 'CONFIRM' else 2000},
                        'recommendation':{'option_keys':['a'],'reason':'仅展示推荐'},
                        'related_spec_context':[]}
                cards = {'schema_version':1,'intro':'显式隔离卡片前置，非模型效果证据',
                    'cards':[card('single'),card('multi','MULTI_SELECT'),card('confirm','CONFIRM'),card('optional',required=False)]}
                validate_cards(cards, self.catalog.freeze(row['action_type'],row['source_type']))
                message = entity_id(connection,EntityKind.MESSAGE); at = operation_time(self.clock)
                connection.execute("INSERT INTO conversation_messages VALUES (?,?,?,?,'ASSISTANT',?,'INTERACTION_CARDS',?,NULL,NULL,?)",
                    (message,row['requirement_id'],identity,message_sequence(connection,row['requirement_id']),
                     '显式卡片历史前置：请回答整组问题',json.dumps(cards,ensure_ascii=False),at))
                if row['action_type'] == 'INITIALIZE':
                    current = connection.execute("SELECT id,content_version FROM requirement_documents WHERE requirement_id=? AND document_type='CURRENT'", (row['requirement_id'],)).fetchone()
                    final = {'guide_run_id':identity,'status':'COMPLETED','assistant_message_id':message,
                        'current_document':dict(current),'suggestion_batch_id':None}
                    connection.execute("UPDATE guide_runs SET status='COMPLETED',current_step='FINISHED',final_result_json=?,ended_at=?,updated_at=? WHERE id=?",
                        (json.dumps(final),at,at,identity))
                    connection.execute("UPDATE requirements SET document_work_state='IDLE',active_operation_type=NULL,active_operation_id=NULL,state_started_at=NULL,updated_at=? WHERE id=? AND active_operation_id=?",(at,row['requirement_id'],identity))
                else:
                    connection.execute("UPDATE guide_runs SET status='WAITING_USER',current_step='WAITING_USER',waiting_user_at=?,updated_at=? WHERE id=?",(at,at,identity))
                return
        await super()._drive(identity,lease)


class SuggestionFixtureWorker(GuideWorker):
    """Named isolated persisted batch precondition, not C07/model evidence.

    All five patches are validated against the real manually saved CURRENT
    and the actual I14 frozen authority. Only generation is a fixture; I20,
    decisions, completion/discard and document adoption remain production.
    """
    async def _drive(self, identity, lease):
        from backend.app.documents.sources import DocumentSources
        from backend.app.documents.snapshot import validate_snapshot
        from backend.app.documents.scopes import restore_authority
        from backend.app.documents.tables import table_model
        from backend.app.documents.patch_validation import validate_patch, validate_combination
        with self.database.transaction(write=True) as connection:
            row = connection.execute('SELECT r.*,m.content FROM guide_runs r JOIN conversation_messages m '
                'ON m.id=r.trigger_message_id WHERE r.id=?', (identity,)).fetchone()
            if row is not None and row['status']=='RUNNING' and row['current_step']=='PREPARING' and row['action_type']=='MODIFY' and row['source_type']=='USER_INSTRUCTION' and row['content']=='建议批次前置夹具':
                current = connection.execute("SELECT * FROM requirement_documents WHERE requirement_id=? AND document_type='CURRENT'", (row['requirement_id'],)).fetchone()
                snapshot = validate_snapshot(current['markdown_content'],json.loads(current['block_state_json']),DocumentSources(connection,row['requirement_id'],self.catalog))
                authority = restore_authority(snapshot,'MODIFY',row['scope_type'],None,json.loads(row['allowed_targets_json']))
                paragraphs = [(block,metadata) for block,metadata in zip(snapshot.parsed.blocks,snapshot.state['blocks']) if block.block_type=='paragraph']
                table,metadata = next((block,metadata) for block,metadata in zip(snapshot.parsed.blocks,snapshot.state['blocks']) if block.block_type=='table')
                original_row = table_model(table).rows[0]
                def patch(operation,target,original,markdown=None,selector=None,data=None):
                    return {'title':'显式前置 '+operation,'explanation':'隔离原生事务验收，非模型效果','impact':None,
                        'patch_operation':operation,'target_ref':{'block_id':target},'selector_json':selector,
                        'original_content':original,'proposed_markdown':markdown,'proposed_data_json':data}
                patches = [patch('REPLACE_BLOCK',paragraphs[0][1]['block_id'],paragraphs[0][0].markdown,'明确后的规则😀\n'),
                    patch('INSERT_BEFORE',paragraphs[1][1]['block_id'],paragraphs[1][0].markdown,'新增前置规则\n'),
                    patch('INSERT_AFTER',paragraphs[1][1]['block_id'],paragraphs[1][0].markdown,'新增后置规则\n'),
                    patch('DELETE_BLOCK',paragraphs[2][1]['block_id'],paragraphs[2][0].markdown),
                    patch('REPLACE_TABLE_ROW',metadata['block_id'],original_row.markdown,selector={'key_column_index':0,'key_value':original_row.cells[0]},data={'cells':[original_row.cells[0],'建议值😀']})]
                validate_combination(tuple(validate_patch(snapshot,patch,authority) for patch in patches))
                batch = entity_id(connection,EntityKind.BATCH); at = operation_time(self.clock)
                connection.execute("INSERT INTO suggestion_batches VALUES (?,?,?,'USER_INSTRUCTION',NULL,'显式建议前置','五种补丁隔离验证','PENDING',NULL,NULL,?,NULL,?,NULL,?)",(batch,row['requirement_id'],identity,current['content_version'],at,at))
                for order,patch in enumerate(patches,1):
                    suggestion = entity_id(connection,EntityKind.SUGGESTION)
                    connection.execute("INSERT INTO suggestions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL,'PENDING','VALID',NULL,?,NULL,?)",(suggestion,batch,order,patch['title'],patch['explanation'],patch['impact'],patch['patch_operation'],json.dumps(patch['target_ref']),None if patch['selector_json'] is None else json.dumps(patch['selector_json']),patch['original_content'],patch['proposed_markdown'],None if patch['proposed_data_json'] is None else json.dumps(patch['proposed_data_json'],ensure_ascii=False),at,at))
                final={'guide_run_id':identity,'status':'COMPLETED','assistant_message_id':None,'current_document':None,'suggestion_batch_id':batch}
                connection.execute("UPDATE guide_runs SET status='COMPLETED',current_step='FINISHED',final_result_json=?,ended_at=?,updated_at=? WHERE id=?",(json.dumps(final),at,at,identity))
                connection.execute("UPDATE requirements SET document_work_state='SUGGESTION_REVIEWING',active_operation_type='SUGGESTION_BATCH',active_operation_id=?,state_started_at=?,updated_at=? WHERE id=? AND active_operation_id=?",(batch,at,at,row['requirement_id'],identity))
                return
        await super()._drive(identity,lease)


class CommentSuggestionFixtureWorker(GuideWorker):
    """Explicit comment batch generation precondition, never model evidence.

    Only the named actual I34 comment dispatch is seeded. Validate the one
    replacement against CURRENT and the server-frozen comment authority;
    public reads, decisions, completion and discard remain production code.
    """
    async def _drive(self, identity, lease):
        from backend.app.documents.sources import DocumentSources
        from backend.app.documents.snapshot import validate_snapshot
        from backend.app.documents.scopes import restore_authority
        from backend.app.documents.patch_validation import validate_patch, validate_combination
        with self.database.transaction(write=True) as connection:
            row = connection.execute('SELECT r.*,m.content FROM guide_runs r JOIN conversation_messages m '
                'ON m.id=r.trigger_message_id WHERE r.id=?', (identity,)).fetchone()
            if (row is not None and row['status']=='RUNNING' and row['current_step']=='PREPARING'
                and row['function_type']=='MODIFY_FROM_COMMENT' and row['source_type']=='COMMENT'
                and row['content']=='评论AI建议前置夹具'):
                current = connection.execute("SELECT * FROM requirement_documents WHERE requirement_id=? AND document_type='CURRENT'", (row['requirement_id'],)).fetchone()
                snapshot = validate_snapshot(current['markdown_content'],json.loads(current['block_state_json']),DocumentSources(connection,row['requirement_id'],self.catalog))
                scope = json.loads(row['scope_ref_json'])
                authority = restore_authority(snapshot,'MODIFY',row['scope_type'],scope,json.loads(row['allowed_targets_json']))
                block = next(block for block,metadata in zip(snapshot.parsed.blocks,snapshot.state['blocks']) if metadata['block_id']==scope['block_id'])
                proposed = (block.markdown.replace(scope['selected_text'],'正式规则😀',1)
                    if row['scope_type']=='SELECTION' else '评论要求的明确规则😀\n')
                patch = {'title':'评论来源前置','explanation':'受控生成前置；非模型效果','impact':None,
                    'patch_operation':'REPLACE_BLOCK','target_ref':{'block_id':scope['block_id']},
                    'selector_json':None,'original_content':block.markdown,'proposed_markdown':proposed,'proposed_data_json':None}
                validate_combination((validate_patch(snapshot,patch,authority),))
                batch = entity_id(connection,EntityKind.BATCH); suggestion = entity_id(connection,EntityKind.SUGGESTION); at = operation_time(self.clock)
                connection.execute("INSERT INTO suggestion_batches VALUES (?,?,?,'COMMENT',?,'显式评论建议前置','一项受控生成补丁','PENDING',NULL,NULL,?,NULL,?,NULL,?)",(batch,row['requirement_id'],identity,row['source_id'],current['content_version'],at,at))
                connection.execute("INSERT INTO suggestions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL,'PENDING','VALID',NULL,?,NULL,?)",(suggestion,batch,1,patch['title'],patch['explanation'],None,'REPLACE_BLOCK',json.dumps(patch['target_ref']),None,block.markdown,proposed,None,at,at))
                final={'guide_run_id':identity,'status':'COMPLETED','assistant_message_id':None,'current_document':None,'suggestion_batch_id':batch}
                connection.execute("UPDATE guide_runs SET status='COMPLETED',current_step='FINISHED',final_result_json=?,ended_at=?,updated_at=? WHERE id=?",(json.dumps(final),at,at,identity))
                connection.execute("UPDATE requirements SET document_work_state='SUGGESTION_REVIEWING',active_operation_type='SUGGESTION_BATCH',active_operation_id=?,state_started_at=?,updated_at=? WHERE id=? AND active_operation_id=?",(batch,at,at,row['requirement_id'],identity))
                return
        await super()._drive(identity,lease)



class ControlledCommentModelWorker(GuideWorker):
    """Private loopback model boundary; real ORCH/audit/validation/C07 writes.

    Synthetic response, synthetic credential, expanded diagnostic byte budget
    and explicit private compatibility callback are not Provider proof. The
    production counting gate/resources are unchanged. Other runs remain normal
    missing-configuration failures. No SQL installs a batch or trusted audit.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from threading import Thread
        from backend.tests.infrastructure import test_model_gateway as wire
        from backend.app.infrastructure.model_gateway import ModelGateway
        from backend.app.infrastructure.model_profile import ModelProfile
        self.wire = wire; self.server = wire.ControlledServer(); self.observed = []; self.transports = []
        self.thread = Thread(target=self.server.serve_forever, kwargs={'poll_interval':0.01}, daemon=True)
        self.thread.start(); self.profile = ModelProfile.from_environment({'WALLE_MODEL_API_KEY':wire.KEY})
        def transport():
            value = wire.ForwardTransport(self.server.server_port,self.observed)
            self.transports.append(value); return value
        self.gateway = ModelGateway(transport_factory=transport)

    def compile(self, actual, function):
        from dataclasses import replace
        from backend.app.guide.context_builder import build_context
        policy = function.context_policy
        policy['budget'].update(prompt_tokens=100000,input_tokens=100000,total_tokens=120000)
        return build_context(actual,replace(function,context_json=json.dumps(policy)))

    async def _drive(self, identity, lease):
        from backend.app.infrastructure.execution_lease import LeasedDatabase
        from backend.app.guide.orchestrator import execute_guide_run
        from backend.app.documents.markdown import parse_markdown
        with self.database.transaction() as connection:
            row = connection.execute('SELECT r.*,m.content FROM guide_runs r JOIN conversation_messages m '
                'ON m.id=r.trigger_message_id WHERE r.id=?',(identity,)).fetchone()
            controlled = row is not None and row['function_type']=='MODIFY_FROM_COMMENT' and row['content']=='评论AI建议前置夹具'
            if controlled:
                current = connection.execute("SELECT * FROM requirement_documents WHERE requirement_id=? AND document_type='CURRENT'",(row['requirement_id'],)).fetchone()
                scope = json.loads(row['scope_ref_json']); state = json.loads(current['block_state_json'])
                block = next(block for block,meta in zip(parse_markdown(current['markdown_content']).blocks,state['blocks']) if meta['block_id']==scope['block_id'])
                proposed = block.markdown.replace(scope['selected_text'],'正式规则😀',1) if row['scope_type']=='SELECTION' else '评论要求的明确规则😀\n'
                patch = {'title':'评论来源补丁','explanation':'受控HTTP输出；实际程序校验','impact':None,'patch_operation':'REPLACE_BLOCK',
                    'target_ref':{'block_id':scope['block_id']},'selector_json':None,'original_content':block.markdown,'proposed_markdown':proposed,'proposed_data_json':None}
        if not controlled:
            await super()._drive(identity,lease); return
        output = {'schema_version':1,'response_type':'SUGGESTIONS','message':'本机受控评论建议','title':'C07真实评论建议','summary':'程序校验后生成一项建议','suggestions':[patch]}
        response = self.wire.envelope(model=self.profile.model_name)
        response['choices'][0]['message']['content'] = json.dumps(output,ensure_ascii=False)
        self.server.responses.append((200,json.dumps(response,ensure_ascii=False).encode('utf-8'),{},None))
        outcome = await execute_guide_run(LeasedDatabase(self.database,lease),{'guide_run_id':identity},
            process_lock=self.process_lock,catalog=self.catalog,clock=self.clock,profile=self.profile,gateway=self.gateway,
            context_compiler=self.compile,compatibility_check=lambda *args:True)
        self.events.append({'event':'CONTROLLED_MODEL_RETURNED','guide_run_id':identity,'code':outcome['code']})

    async def close(self):
        try: return await super().close()
        finally:
            await asyncio.to_thread(self.server.shutdown); self.server.server_close(); self.thread.join(2)
            if self.thread.is_alive(): raise RuntimeError('Owned loopback server did not close')

    def diagnostic_facts(self):
        return {'loopback_chat_requests':len(self.server.receipts),'model':self.profile.model_name,
            'transport_closed':all(item.closed for item in self.transports),'server_closed':not self.thread.is_alive(),
            'server_errors':self.server.errors,'production_compatibility_proved':False,'paid_requests':0,
            'context_compiler':'Explicit expanded private conservative byte budget; no production gate proof'}

class ControlledScopeModelWorker(ControlledCommentModelWorker):
    """Explicit private ordinary-action boundary; no SQL-manufactured outputs."""
    def _controlled_trigger(self, row, connection):
        return row['status']=='RUNNING' and row['content'].startswith('操作范围验收 ')

    async def _drive(self, identity, lease):
        from backend.app.infrastructure.execution_lease import LeasedDatabase
        from backend.app.guide.orchestrator import execute_guide_run
        from backend.app.documents.markdown import parse_markdown
        with self.database.transaction() as connection:
            row = connection.execute('SELECT r.*,m.content,m.message_type AS trigger_message_type,m.reply_to_message_id FROM guide_runs r JOIN conversation_messages m '
                'ON m.id=r.trigger_message_id WHERE r.id=?',(identity,)).fetchone()
            controlled = row is not None and self._controlled_trigger(row,connection)
            if controlled:
                current = connection.execute("SELECT * FROM requirement_documents WHERE requirement_id=? AND document_type='CURRENT'",(row['requirement_id'],)).fetchone()
                scope = None if row['scope_ref_json'] is None else json.loads(row['scope_ref_json'])
                pairs = list(zip(parse_markdown(current['markdown_content']).blocks,json.loads(current['block_state_json'])['blocks']))
                block,meta = next((block,meta) for block,meta in reversed(pairs) if block.block_type=='paragraph')
                if row['scope_type'] in ('BLOCK','SELECTION'):
                    block,meta = next((b,m) for b,m in pairs if m['block_id']==scope['block_id'])
        if not controlled:
            # The original initialization still runs the ordinary missing-key path.
            await GuideWorker._drive(self,identity,lease); return
        if row['action_type']=='ASK':
            output = {'schema_version':1,'response_type':'ANSWER','message':'本机受控回答：正文保持不变😀'}
        elif row['action_type']=='REVIEW':
            output = {'schema_version':1,'response_type':'REVIEW_RESULT','message':'本机受控检查：已保存检查结果😀',
                'review_result':{'schema_version':1,'summary':'检查原文中的可测试性',
                    'issues':[{'issue_key':'testability','severity':'WARNING','category':'UNTESTABLE',
                        'title':'需要验收标准','description':'受控检查项用于验证来源链路',
                        'block_ids':[meta['block_id']],'evidence':block.plain_text,'recommendation':'明确验收步骤'}]}}
        elif row['content']=='操作范围验收 NO_CHANGE' or row['trigger_message_type']=='CARD_RESPONSE':
            output = {'schema_version':1,'response_type':'NO_CHANGE','message':'本机受控无需修改：正文保持不变😀'}
        else:
            proposed = block.markdown.replace(scope['selected_text'],'正式规则😀',1) if row['scope_type']=='SELECTION' else '范围内的明确规则😀\n'
            patch = {'title':'范围内补丁','explanation':'受控HTTP输出；真实程序校验','impact':None,
                'patch_operation':'REPLACE_BLOCK','target_ref':{'block_id':meta['block_id']},'selector_json':None,
                'original_content':block.markdown,'proposed_markdown':proposed,'proposed_data_json':None}
            output = {'schema_version':1,'response_type':'SUGGESTIONS','message':'本机受控修改建议😀',
                'title':'范围内建议','summary':'仅生成建议，不直接采用','suggestions':[patch]}
        response = self.wire.envelope(model=self.profile.model_name)
        response['choices'][0]['message']['content'] = json.dumps(output,ensure_ascii=False)
        self.server.responses.append((200,json.dumps(response,ensure_ascii=False).encode('utf-8'),{},None))
        outcome = await execute_guide_run(LeasedDatabase(self.database,lease),{'guide_run_id':identity},
            process_lock=self.process_lock,catalog=self.catalog,clock=self.clock,profile=self.profile,gateway=self.gateway,
            context_compiler=self.compile,compatibility_check=lambda *args:True)
        self.events.append({'event':'CONTROLLED_SCOPE_RETURNED','guide_run_id':identity,'code':outcome['code']})


class ControlledWaitingModelWorker(ControlledScopeModelWorker):
    """Private clarification response; actual C07 creates WAITING/cards."""
    def _controlled_trigger(self, row, connection):
        if super()._controlled_trigger(row,connection): return True
        if row['status']!='RUNNING' or row['action_type'] not in ('ASK','REVIEW','MODIFY') or row['source_type']!='USER_INSTRUCTION' or row['trigger_message_type']!='CARD_RESPONSE': return False
        original=connection.execute("SELECT * FROM conversation_messages WHERE id=? AND requirement_id=? AND guide_run_id=? AND role='ASSISTANT' AND message_type='INTERACTION_CARDS'",
            (row['reply_to_message_id'],row['requirement_id'],row['id'])).fetchone()
        if original is None: return False
        initiating=connection.execute("SELECT 1 FROM conversation_messages WHERE requirement_id=? AND guide_run_id=? AND sequence_no<? AND role='USER' AND message_type='TEXT' AND content IN ('操作范围验收 WAIT_CARDS','操作范围验收 WAIT_CARDS5')",
            (row['requirement_id'],row['id'],original['sequence_no'])).fetchone()
        usage=connection.execute("SELECT * FROM llm_uses WHERE guide_run_id=? AND call_no=1 AND call_status='SUCCEEDED' AND parse_status='SUCCEEDED' AND validation_status='SUCCEEDED' ORDER BY attempt_no DESC LIMIT 1",(row['id'],)).fetchone()
        if initiating is None or usage is None: return False
        trusted=json.loads(usage['trusted_output_json'])
        return trusted['response_type']=='CLARIFY_CARDS' and trusted['message']==original['content'] and trusted['cards']==json.loads(original['structured_content_json'])

    async def _drive(self, identity, lease):
        from backend.app.infrastructure.execution_lease import LeasedDatabase
        from backend.app.guide.orchestrator import execute_guide_run
        from backend.app.documents.markdown import parse_markdown
        with self.database.transaction() as connection:
            row = connection.execute('SELECT r.*,m.content FROM guide_runs r JOIN conversation_messages m '
                'ON m.id=r.trigger_message_id WHERE r.id=?',(identity,)).fetchone()
            controlled = row is not None and row['status']=='RUNNING' and row['action_type'] in ('ASK','REVIEW','MODIFY') and row['source_type']=='USER_INSTRUCTION' and row['content'] in ('操作范围验收 WAIT_TEXT','操作范围验收 WAIT_CARDS','操作范围验收 WAIT_CARDS5')
            if controlled:
                current = connection.execute("SELECT * FROM requirement_documents WHERE requirement_id=? AND document_type='CURRENT'",(row['requirement_id'],)).fetchone()
                block,meta = list(zip(parse_markdown(current['markdown_content']).blocks,json.loads(current['block_state_json'])['blocks']))[-1]
        if not controlled:
            await super()._drive(identity,lease); return
        if row['content'] in ('操作范围验收 WAIT_CARDS','操作范围验收 WAIT_CARDS5'):
            from backend.tests.messages.test_queries import cards_fixture
            from backend.app.guide.output_evidence import card_text
            cards = cards_fixture();cards['intro']='本机受控追问😀'
            if row['content'].endswith('WAIT_CARDS5'):
                from copy import deepcopy
                base=cards['cards'][0]
                cards['cards']=[deepcopy(base) for _ in range(5)]
                for card,key,question in zip(cards['cards'],('first','multi','confirm','optional','last'),('选择方案','多选问题','确认问题','可选问题','末项问题')):
                    card.update(card_key=key,question=question)
                cards['cards'][1].update(card_type='MULTI_SELECT',selection_rule={'min':1,'max':2})
                cards['cards'][2].update(card_type='CONFIRM',custom_answer={'enabled':False,'max_length':0})
                cards['cards'][3].update(required=False,custom_answer={'enabled':False,'max_length':0})
                cards['cards'][4]['custom_answer']={'enabled':False,'max_length':0}
            for card in cards['cards']:
                card['related_spec_context']=[{'block_id':meta['block_id'],'content_snapshot':block.markdown}]
            output={'schema_version':1,'response_type':'CLARIFY_CARDS','message':card_text(cards),'cards':cards}
        else:
            output={'schema_version':1,'response_type':'CLARIFY_TEXT','message':'本机受控追问：请补充普通说明😀'}
        response=self.wire.envelope(model=self.profile.model_name)
        response['choices'][0]['message']['content']=json.dumps(output,ensure_ascii=False)
        self.server.responses.append((200,json.dumps(response,ensure_ascii=False).encode('utf-8'),{},None))
        outcome=await execute_guide_run(LeasedDatabase(self.database,lease),{'guide_run_id':identity},
            process_lock=self.process_lock,catalog=self.catalog,clock=self.clock,profile=self.profile,gateway=self.gateway,
            context_compiler=self.compile,compatibility_check=lambda *args:True)
        self.events.append({'event':'CONTROLLED_WAITING_RETURNED','guide_run_id':identity,'code':outcome['code']})


class ControlledRetryModelWorker(ControlledScopeModelWorker):
    """Three real local 503 attempts fail; an explicit new retry run succeeds.

    Neither run status nor user message is seeded. Production ORCH chooses
    attempts/backoff and C08/C04/C07 persist their actual results.
    """
    async def _drive(self, identity, lease):
        from backend.app.infrastructure.execution_lease import LeasedDatabase
        from backend.app.guide.orchestrator import execute_guide_run
        with self.database.transaction() as connection:
            row = connection.execute('SELECT r.*,m.content FROM guide_runs r JOIN conversation_messages m '
                'ON m.id=r.trigger_message_id WHERE r.id=?',(identity,)).fetchone()
            fail_first = (row is not None and row['status']=='RUNNING' and row['action_type']=='REVIEW'
                and row['content']=='操作范围验收 RETRY_ROOT' and row['retry_of_guide_run_id'] is None)
        if not fail_first:
            await super()._drive(identity,lease); return
        for unused in range(3): self.server.responses.append((503,b'{}',{},None))
        outcome = await execute_guide_run(LeasedDatabase(self.database,lease),{'guide_run_id':identity},
            process_lock=self.process_lock,catalog=self.catalog,clock=self.clock,profile=self.profile,gateway=self.gateway,
            context_compiler=self.compile,compatibility_check=lambda *args:True)
        self.events.append({'event':'CONTROLLED_RETRY_FAILURE_RETURNED','guide_run_id':identity,'code':outcome['code']})


class ControlledCommitRaceWorker(ControlledScopeModelWorker):
    """Private barriers observe native SQL, without manufacturing run state.

    C07 holds its own real write transaction after its PERSISTING update.
    The actual public cancel request's BEGIN IMMEDIATE releases that barrier.
    SQLite still orders both transactions and production C03 decides the result.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from contextvars import ContextVar
        from threading import Event, Lock, get_ident
        import time
        from backend.app.guide import result_persistence
        self.cancel_context = ContextVar('private_cancel_request', default=None)
        self.release_gate = Event(); self.race_lock = Lock(); self.race_events = []
        self.held = False; self.gate_identity = None; self.hooks_restored = False
        self.original_validate = result_persistence.validate_business_output
        self.original_connect = self.database._connect
        def record(event, **fields):
            with self.race_lock:
                self.race_events.append({'event':event,'order':len(self.race_events)+1,
                    'monotonic_ns':time.monotonic_ns(),'thread_id':get_ident(),**fields})
        def validate(connection, **fields):
            run = connection.execute("SELECT id,status,current_step FROM guide_runs WHERE status='RUNNING' AND current_step='PERSISTING'").fetchone()
            if run is not None:
                if not connection.in_transaction: raise RuntimeError('No actual C07 transaction')
                self.release_gate.clear(); self.gate_identity = run['id']; self.held = True
                record('C07_NATIVE_GATE_HELD',guide_run_id=run['id'],status=run['status'],
                    current_step=run['current_step'],in_transaction=connection.in_transaction)
                try:
                    if not self.release_gate.wait(30):
                        record('GATE_TIMEOUT',guide_run_id=run['id']); raise RuntimeError('Finite private barrier expired')
                    record('C07_NATIVE_GATE_RELEASED',guide_run_id=run['id'])
                finally: self.held = False
            return self.original_validate(connection,**fields)
        def connect(*args, **kwargs):
            connection = self.original_connect(*args,**kwargs)
            request = self.cancel_context.get()
            def trace(sql):
                if sql == 'BEGIN IMMEDIATE' and request is not None and self.held:
                    record('I17_NATIVE_WRITE_BEGIN',guide_run_id=request['guide_run_id'],
                        idempotency_key=request['key'],gate_identity=self.gate_identity,
                        gate_held=self.held,in_transaction=connection.in_transaction)
                    self.release_gate.set()
            connection.set_trace_callback(trace)
            return connection
        self.database._connect = connect
        result_persistence.validate_business_output = validate

    def gate_facts(self):
        with self.race_lock:
            return {'held':self.held,'guide_run_id':self.gate_identity,'events':list(self.race_events)}

    async def close(self):
        self.release_gate.set()
        try: return await super().close()
        finally:
            from backend.app.guide import result_persistence
            result_persistence.validate_business_output = self.original_validate
            self.database._connect = self.original_connect
            self.hooks_restored = True

    def diagnostic_facts(self):
        return {**super().diagnostic_facts(),'commit_race':self.gate_facts(),
            'private_hooks_restored':self.hooks_restored}


async def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--database', required=True)
    parser.add_argument('--frontend-dist', type=Path)
    fixture = parser.add_mutually_exclusive_group()
    fixture.add_argument('--hold-review-dispatch', action='store_true')
    fixture.add_argument('--seed-waiting-ask-fixture', action='store_true')
    fixture.add_argument('--seed-cards-fixture', action='store_true')
    fixture.add_argument('--seed-suggestion-fixture', action='store_true')
    fixture.add_argument('--seed-comment-suggestion-fixture', action='store_true')
    fixture.add_argument('--controlled-comment-model', action='store_true')
    fixture.add_argument('--controlled-scope-model', action='store_true')
    fixture.add_argument('--controlled-waiting-model', action='store_true')
    fixture.add_argument('--controlled-commit-race-model', action='store_true')
    fixture.add_argument('--controlled-retry-model', action='store_true')
    args = parser.parse_args(); path = Path(args.database).resolve()
    if not path.is_relative_to(ROOT / 'output' / 'playwright') or not path.name.startswith('api-walle-') or path.exists():
        raise ValueError('A fresh, explicit verification output database is required')
    # Test processes must not inherit real model credentials or configuration.
    for key in list(os.environ):
        if key.startswith('WALLE_MODEL_'): del os.environ[key]
    os.environ['WALLE_DATABASE_PATH'] = str(path)
    database = Database(path); database.initialize()
    factory = (lambda db, catalog: HeldReviewWorker(db, catalog=catalog)) if args.hold_review_dispatch else None
    if args.seed_waiting_ask_fixture: factory = lambda db, catalog: WaitingAskFixtureWorker(db, catalog=catalog)
    if args.seed_cards_fixture: factory = lambda db, catalog: CardsFixtureWorker(db, catalog=catalog)
    if args.seed_suggestion_fixture: factory = lambda db, catalog: SuggestionFixtureWorker(db, catalog=catalog)
    if args.seed_comment_suggestion_fixture: factory = lambda db, catalog: CommentSuggestionFixtureWorker(db, catalog=catalog)
    controlled = []
    if args.controlled_comment_model:
        def factory(db,catalog):
            worker = ControlledCommentModelWorker(db,catalog=catalog); controlled.append(worker); return worker
    if args.controlled_scope_model:
        def factory(db,catalog):
            worker = ControlledScopeModelWorker(db,catalog=catalog); controlled.append(worker); return worker
    if args.controlled_waiting_model:
        def factory(db,catalog):
            worker = ControlledWaitingModelWorker(db,catalog=catalog); controlled.append(worker); return worker
    if args.controlled_commit_race_model:
        def factory(db,catalog):
            worker = ControlledCommitRaceWorker(db,catalog=catalog); controlled.append(worker); return worker
    if args.controlled_retry_model:
        def factory(db,catalog):
            worker = ControlledRetryModelWorker(db,catalog=catalog); controlled.append(worker); return worker
    app = create_app(worker_factory=factory, frontend_directory=args.frontend_dist)
    if args.controlled_commit_race_model:
        from starlette.responses import JSONResponse
        @app.middleware('http')
        async def private_race_observer(request, call_next):
            worker = controlled[0]
            if request.method == 'GET' and request.url.path == '/__verification__/commit-gate':
                return JSONResponse(worker.gate_facts())
            parts = request.url.path.split('/')
            if request.method == 'POST' and len(parts)==6 and parts[1:4]==['api','v1','guide-runs'] and parts[5]=='cancel' and parts[4].isdigit():
                token = worker.cancel_context.set({'guide_run_id':int(parts[4]),'key':request.headers.get('Idempotency-Key')})
                try: return await call_next(request)
                finally: worker.cancel_context.reset(token)
            return await call_next(request)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=0, workers=1,
        timeout_graceful_shutdown=10, log_level='warning'))
    task = asyncio.create_task(server.serve())
    while not server.started and not task.done(): await asyncio.sleep(0.01)
    if task.done():
        await task; raise RuntimeError('Actual API startup did not complete')
    address = server.servers[0].sockets[0].getsockname()
    print(json.dumps({'ready': True, 'url': f'http://127.0.0.1:{address[1]}'}), flush=True)
    await asyncio.to_thread(sys.stdin.readline)
    server.should_exit = True; await task
    with database.transaction() as connection:
        facts = {name: connection.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0]
            for name in ('requirements', 'requirement_documents', 'revisions', 'comments', 'guide_runs', 'llm_uses')}
        if args.seed_suggestion_fixture or args.seed_comment_suggestion_fixture or controlled:
            facts.update({name: connection.execute('SELECT COUNT(*) FROM '+name).fetchone()[0] for name in ('suggestion_batches','suggestions')})
    print(json.dumps({'closed': True, 'facts': facts, **({'controlled_model':controlled[0].diagnostic_facts()} if controlled else {})}), flush=True)


if __name__ == '__main__': asyncio.run(main())
