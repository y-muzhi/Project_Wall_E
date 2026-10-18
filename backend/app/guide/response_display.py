"""Model returns are readable even when they cannot drive business writes.

Only persisted, credential-scrubbed response messages are exposed. There is
no output Schema, equivalence, evidence, or progression gate on this path.
"""
import json

from backend.app.infrastructure.audit_repository import AuditRepository, _owned
from backend.app.infrastructure.guide_repository import GuideRepository
from backend.app.infrastructure.identifiers import EntityKind, entity_id, message_sequence
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.shared.command_execution import Rejected, operation_time
from backend.app.shared.validation import strict_json_object


def response_text(raw):
    """Keep all returned assistant messages, including partial/non-JSON text."""
    if not isinstance(raw, dict):return None
    messages=[]
    for choice in raw.get('choices', []) if isinstance(raw.get('choices'), list) else []:
        message=choice.get('message') if isinstance(choice,dict) else None
        if not isinstance(message,dict):continue
        content=message.get('content')
        if isinstance(content,str) and content:messages.append(content)
        elif content is not None:messages.append(json.dumps(content,ensure_ascii=False,indent=2))
        extras={key:value for key,value in message.items() if key not in ('role','content') and value is not None}
        if extras:messages.append(json.dumps(extras,ensure_ascii=False,indent=2))
    return '\n\n'.join(messages) or None


def returned_responses(connection, run_id):
    result=[]
    for row in connection.execute('SELECT id,call_no,attempt_no,raw_response_json FROM llm_uses WHERE guide_run_id=? AND raw_response_json IS NOT NULL ORDER BY call_no,attempt_no,id',(run_id,)):
        content=response_text(strict_json_object(row['raw_response_json']))
        if content is not None:
            result.append({'llm_use_id':row['id'],'call_no':row['call_no'],'attempt_no':row['attempt_no'],'content':content})
    return result


def persist_returned_response(database, llm_use_id, *, process_lock, clock=None):
    """Publish an actual response as TEXT without applying model operations.

    Failed parse/write checks remain failed in the audit; completion here only
    means the response was delivered. Cancellation and ownership still apply.
    """
    process_lock.assert_owned()
    if process_lock.path != ProcessLock.for_database(database.path).path:raise RuntimeError('Display lock must own this database')
    at=operation_time(clock)
    with database.transaction(write=True) as connection:
        row=AuditRepository(connection).get(llm_use_id)
        if row is None:raise Rejected('NOT_FOUND')
        run=GuideRepository(connection).get(row['guide_run_id']);root=_owned(connection,run)
        if run['status']!='RUNNING':raise Rejected('STATE_CONFLICT')
        latest=connection.execute('SELECT id FROM llm_uses WHERE guide_run_id=? ORDER BY call_no DESC,attempt_no DESC LIMIT 1',(run['id'],)).fetchone()
        if latest is None or latest['id']!=llm_use_id or row['ended_at'] is None:raise Rejected('STATE_CONFLICT')
        if at < max(run['updated_at'],root['updated_at'],row['ended_at']):raise ValueError('Display cannot precede the response')
        content=response_text(strict_json_object(row['raw_response_json']))
        if content is None:raise Rejected('OUTPUT_INVALID')
        identity=entity_id(connection,EntityKind.MESSAGE)
        connection.execute("INSERT INTO conversation_messages VALUES (?,?,?,?,'ASSISTANT',?,'TEXT',NULL,NULL,NULL,?)",
            (identity,root['id'],run['id'],message_sequence(connection,root['id']),content,at))
        effects={'guide_run_id':run['id'],'status':'COMPLETED','assistant_message_id':identity,'current_document':None,'suggestion_batch_id':None}
        changed=connection.execute("UPDATE guide_runs SET status='COMPLETED',current_step='FINISHED',final_result_json=?,ended_at=?,updated_at=?,error_code=NULL,error_message=NULL WHERE id=? AND status='RUNNING'",
            (canonical_input(effects),at,at,run['id']))
        if changed.rowcount!=1:raise Rejected('STATE_CONFLICT')
        RequirementRepository(connection).recover_occupancy(root,None,None,at)
        return {'code':'AI_RESULT_PERSISTED','data':effects,'details':None}
