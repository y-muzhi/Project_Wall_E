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


async def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--database', required=True)
    fixture = parser.add_mutually_exclusive_group()
    fixture.add_argument('--hold-review-dispatch', action='store_true')
    fixture.add_argument('--seed-waiting-ask-fixture', action='store_true')
    fixture.add_argument('--seed-cards-fixture', action='store_true')
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
    server = uvicorn.Server(uvicorn.Config(create_app(worker_factory=factory), host='127.0.0.1', port=0, workers=1,
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
    print(json.dumps({'closed': True, 'facts': facts}), flush=True)


if __name__ == '__main__': asyncio.run(main())
