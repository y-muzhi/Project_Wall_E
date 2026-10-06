"""Explicit diagnostic six-input preparation on isolated real SQLite fixtures.

Historical REVIEW is a declared stored fixture, not Provider generation/C07.
All owned locks/directories are cleaned; no normal business database is used.
"""
from datetime import timedelta
import json

from backend.app.guide import commands
from backend.app.guide.context_builder import assemble_input
from backend.app.guide.queries import get_model_context
from backend.app.infrastructure.identifiers import EntityKind, entity_id, message_sequence
from backend.app.infrastructure.resources import ResourceCatalog
from backend.tests.guide.test_model_context import ModelContextTests, CommentModelContextTests
from backend.tests.requirements import test_create_requirement as creation

TEXT='计数封装实验：中文甲乙、emoji😀👨‍👩‍👧‍👦、引号"、反斜线\\、换行\n第二行\t制表符；不采用模型输出。'


def cases():
    result=[];helper=ModelContextTests();helper.setUp();seconds=2
    def capture(identity,action,source='USER_INSTRUCTION',fixture=helper):
        read=get_model_context(fixture.database,identity,catalog=fixture.catalog)
        fixture.assertEqual(read['code'],'READ_OK',read)
        function=fixture.catalog.freeze(action,source)
        result.append({'function_type':function.function_type,'version':function.version,'input':assemble_input(read['data'],function)})
    def cancel(identity):
        nonlocal seconds
        seconds+=1
        value=commands.cancel_guide_run(helper.executor,{'guide_run_id':identity,'idempotency_key':creation.OTHER},clock=lambda:creation.INSTANT+timedelta(seconds=seconds))
        helper.assertEqual(value['code'],'GUIDE_CANCELLED',value)
    def accept(action,**changes):
        nonlocal seconds
        seconds+=1
        value=commands.create_guide_run(helper.executor,{'requirement_id':helper.req,'expected_content_version':1,
            'action_type':action,'instruction':TEXT,'scope_type':'BLOCK','scope_ref':{'block_id':5},
            'source_type':'USER_INSTRUCTION','idempotency_key':'00000000-0000-4000-8000-000000000992',**changes},
            catalog=helper.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=seconds))
        helper.assertEqual(value['code'],'GUIDE_ACCEPTED',value)
        return value['data']['guide_run']['id']
    try:
        helper.catalog=ResourceCatalog()
        helper.created=helper.create(idempotency_key='00000000-0000-4000-8000-000000000991',initial_idea=TEXT)['data']
        helper.req=helper.created['requirement']['id'];helper.run=helper.created['guide_run_id']
        capture(helper.run,'INITIALIZE');helper.activate()
        identity=accept('ASK',idempotency_key='00000000-0000-4000-8000-000000000995');capture(identity,'ASK');cancel(identity)
        previous=accept('REVIEW')
        capture(previous,'REVIEW')
        # Explicit historical REVIEW fixture, same as model-context unit scope.
        seconds+=1
        at=f'2026-10-04T08:00:{seconds:02d}.000Z';review={'schema_version':1,'summary':'计数实验历史检查夹具😀','issues':[]}
        with helper.database.transaction(write=True) as connection:
            assistant=entity_id(connection,EntityKind.MESSAGE)
            connection.execute("INSERT INTO conversation_messages VALUES (?,?,?,?,'ASSISTANT','explicit review fixture','TEXT',NULL,NULL,NULL,?)",(assistant,helper.req,previous,message_sequence(connection,helper.req),at))
            effects={'guide_run_id':previous,'status':'COMPLETED','assistant_message_id':assistant,'current_document':None,'suggestion_batch_id':None,'review_result':review}
            connection.execute("UPDATE guide_runs SET status='COMPLETED',current_step='FINISHED',ended_at=?,updated_at=?,final_result_json=? WHERE id=?",(at,at,json.dumps(effects),previous))
        helper.assertEqual(commands.recover_runs(helper.database,{'recovery_reason':'STARTUP','live_run_ids':set(),'operation_time':at},process_lock=helper.lock)['code'],'RECOVERED')
        identity=accept('MODIFY',source_type='REVIEW_RESULT',source_id=previous,idempotency_key='00000000-0000-4000-8000-000000000993')
        capture(identity,'MODIFY','REVIEW_RESULT');cancel(identity)
        identity=accept('MODIFY',idempotency_key='00000000-0000-4000-8000-000000000994')
        capture(identity,'MODIFY');cancel(identity)
    finally:
        if not helper.doCleanups():raise RuntimeError('Native framing fixture cleanup failed')
    comment=CommentModelContextTests();comment.setUp()
    try:
        comment.catalog=ResourceCatalog();comment.assertEqual(comment.make_comment(content=TEXT)['code'],'COMMENT_CREATED')
        accepted=comment.modify();comment.assertEqual(accepted['code'],'GUIDE_ACCEPTED',accepted)
        capture(accepted['data']['id'],'MODIFY','COMMENT',comment)
    finally:
        if not comment.doCleanups():raise RuntimeError('Native comment fixture cleanup failed')
    return result
