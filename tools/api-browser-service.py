"""Private browser verification runner: actual API/SQLite, no Provider.

Only explicit test database paths outside the default production path are
accepted. Startup uses production create_app. Stdin controls test shutdown;
there is no extra HTTP route or fake HTTP success. Explicit private fixture
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


async def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--database', required=True)
    parser.add_argument('--frontend-dist', type=Path)
    fixture = parser.add_mutually_exclusive_group()
    fixture.add_argument('--hold-review-dispatch', action='store_true')
    fixture.add_argument('--seed-waiting-ask-fixture', action='store_true')
    fixture.add_argument('--seed-cards-fixture', action='store_true')
    fixture.add_argument('--seed-suggestion-fixture', action='store_true')
    fixture.add_argument('--seed-comment-suggestion-fixture', action='store_true')
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
    server = uvicorn.Server(uvicorn.Config(create_app(worker_factory=factory, frontend_directory=args.frontend_dist), host='127.0.0.1', port=0, workers=1,
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
        if args.seed_suggestion_fixture or args.seed_comment_suggestion_fixture:
            facts.update({name: connection.execute('SELECT COUNT(*) FROM '+name).fetchone()[0] for name in ('suggestion_batches','suggestions')})
    print(json.dumps({'closed': True, 'facts': facts}), flush=True)


if __name__ == '__main__': asyncio.run(main())
