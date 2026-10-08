"""Independent immutable SQLite audit for actual failed-root I18 new runs."""
import argparse
from contextlib import closing
from datetime import datetime,timezone
import hashlib,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.documents.markdown import parse_markdown

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def audit(path):
 report=json.loads(path.read_text(encoding='utf-8'));assert report['passed'] and report['native']['code']==0 and not report['changed_inputs'] and report['inputs_before']==report['inputs_after']
 for name,digest in report['inputs_after'].items():assert sha(ROOT/name)==digest,name
 args=report['native']['args'];assert '--controlled-retry-model' in args
 database=Path(args[args.index('--database')+1]);assert database.resolve().is_relative_to((ROOT/'output/playwright').resolve())
 before=sha(database);assert before==report['database_sha256'];model=report['controlled_model']
 expected=sum(4 if c['actual'] else 3 for c in report['cases']);assert model['paid_requests']==0 and model['loopback_chat_requests']==expected
 assert model['server_closed'] and model['transport_closed'] and not model['server_errors'] and model['production_compatibility_proved'] is False
 checked=[]
 with closing(sqlite3.connect(database.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
  db.row_factory=sqlite3.Row
  counts={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in report['native_facts']};assert counts==report['native_facts'] and counts['llm_uses']==expected and counts['suggestion_batches']==counts['suggestions']==0
  for case in report['cases']:
   identity=case['before']['requirement']['id'];original=case['original'];success=case['actual'] is not None
   assert case['original_after']==original and original['status']=='FAILED' and original['error_code']=='MODEL_ERROR' and original['final_result'] is None
   current=dict(db.execute("SELECT * FROM requirement_documents WHERE requirement_id=? AND document_type='CURRENT'",(identity,)).fetchone());current['block_state_json']=json.loads(current['block_state_json'])
   assert current==case['edited']['current']==case['after']['current'] and current['content_version']==(4 if case['name'] in ('RETRY-latest','RETRY-scope-invalid') else 3)
   assert case['failed_state']['current']==case['before']['current'] and db.execute('SELECT count(*) FROM requirement_documents WHERE requirement_id=?',(identity,)).fetchone()[0]==1
   root=dict(db.execute('SELECT * FROM requirements WHERE id=?',(identity,)).fetchone());assert root==case['after']['requirement'] and root['document_work_state']=='IDLE' and root['active_operation_id'] is None and root['status']=='ACTIVE'
   revisions=[]
   for row in db.execute('SELECT * FROM revisions WHERE requirement_id=? ORDER BY version_no',(identity,)):
    value=dict(row);value['markdown_content']=value.pop('markdown_snapshot');value['block_state_json']=json.loads(value.pop('block_state_snapshot_json'));revisions.append(value)
   assert revisions==case['before']['revision_details']==case['edited']['revision_details']==case['after']['revision_details'] and len(revisions)==1
   runs=[dict(r) for r in db.execute('SELECT * FROM guide_runs WHERE requirement_id=? ORDER BY id',(identity,))];assert len(runs)==(3 if success else 2) and runs[0]['error_code']=='CONFIG_INVALID' and runs[0]['status']=='FAILED'
   old=runs[1];assert old['id']==original['id'] and old['status']=='FAILED' and old['current_step']=='FINISHED' and old['error_code']=='MODEL_ERROR' and old['final_result_json'] is None and old['retry_of_guide_run_id'] is None
   for field in ('id','requirement_id','action_type','function_type','source_type','source_id','status','current_step','error_code','error_message','created_at','updated_at','started_at','ended_at'):assert old[field]==original[field],field
   assert old['scope_type']==original['scope']['scope_type'] and (None if old['scope_ref_json'] is None else json.loads(old['scope_ref_json']))==original['scope']['scope_ref']
   messages=[dict(m) for m in db.execute('SELECT * FROM conversation_messages WHERE requirement_id=? ORDER BY sequence_no',(identity,))];assert len(messages)==(3 if success else 2) and [m['role'] for m in messages[:2]]==['USER','USER'] and all(m['message_type']=='TEXT' for m in messages)
   user=messages[1];assert user['content']=='操作范围验收 RETRY_ROOT' and user['id']==old['trigger_message_id'] and user['guide_run_id']==old['id'] and user['idempotency_key']==old['idempotency_key']
   requests=case['requests'];assert len(requests)==(2 if case['name']=='RETRY-unknown' else 1)
   for request in requests:
    assert 'body' not in request and request['path']==f"/api/v1/guide-runs/{old['id']}/retry"
    receipt=db.execute('SELECT * FROM idempotency_records WHERE idempotency_key=?',(request['key'],)).fetchone()
    if success:assert request['status']==202 and receipt['status']=='SUCCEEDED' and receipt['http_status']==202 and json.loads(receipt['success_result_json'])['data']==request['response']['data']
    else:assert receipt is None and request['status']==(422 if case['name']=='RETRY-scope-invalid' else 409) and request['response']['error']['code']==('SCOPE_INVALID' if case['name']=='RETRY-scope-invalid' else 'WORK_STATE_CONFLICT') and request['delivered']
   if case['name']=='RETRY-unknown':assert requests[0]['key']==requests[1]['key'] and requests[0]['response']['data']==requests[1]['response']['data'] and not requests[0]['delivered'] and requests[1]['delivered']
   if success:
    new=runs[2];assert new['id']==case['retried']['id']==case['actual']['id'] and new['id']!=old['id'] and new['retry_of_guide_run_id']==old['id'] and new['trigger_type']=='RETRY' and new['trigger_message_id']==user['id'] and new['idempotency_key']==requests[-1]['key']
    for field in ('action_type','function_type','source_type','source_id','scope_type','scope_ref_json'):assert new[field]==old[field],field
    assert new['status']=='COMPLETED' and new['current_step']=='FINISHED' and new['error_code'] is None and new['cancel_reason'] is None and json.loads(new['allowed_targets_json'])=={'schema_version':1,'targets':[]}
    assert case['retried']['status']=='RUNNING' and case['retried']['current_step']=='PREPARING'
    final=json.loads(new['final_result_json']);assert final['assistant_message_id']==messages[2]['id'] and messages[2]['guide_run_id']==new['id'] and final['suggestion_batch_id'] is None
   audits=[dict(u) for u in db.execute('SELECT * FROM llm_uses WHERE guide_run_id=? ORDER BY attempt_no',(old['id'],))];assert len(audits)==3
   for i,usage in enumerate(audits):
    assert (usage['call_no'],usage['attempt_no'],usage['call_status'],usage['parse_status'],usage['validation_status'],usage['error_code'])==(1,i+1,'FAILED','NOT_STARTED','NOT_STARTED','MODEL_ERROR')
    assert usage['trusted_output_json'] is None and usage['parsed_output_json'] is None and usage['input_tokens'] is None and usage['output_tokens'] is None
    assert json.loads(usage['context_manifest_json'])['content_version']==3
   if success:
    fresh=[dict(u) for u in db.execute('SELECT * FROM llm_uses WHERE guide_run_id=?',(new['id'],))];assert len(fresh)==1
    usage=fresh[0];assert (usage['call_no'],usage['attempt_no'],usage['call_status'],usage['parse_status'],usage['validation_status'])==(1,1,'SUCCEEDED','SUCCEEDED','SUCCEEDED')
    trusted=json.loads(usage['trusted_output_json']);assert json.loads(json.loads(usage['raw_response_json'])['choices'][0]['message']['content'])==trusted and trusted['response_type']=='REVIEW_RESULT' and final['review_result']==trusted['review_result'] and messages[2]['content']==trusted['message']
    assert ResourceCatalog().freeze('REVIEW','USER_INSTRUCTION').parse_output(json.dumps(trusted,ensure_ascii=False))==trusted
    audits+=fresh
   for usage in audits:
    assert (usage['model_name'],usage['model_version'],usage['function_type'],usage['prompt_config'])==('deepseek-v4-1-flash-260910','260910','REVIEW_REQUIREMENT','REVIEW_REQUIREMENT@v2')
    wire=json.loads(usage['request_snapshot_json'])['request'];assert wire['max_tokens']==8192 and wire['thinking']=={'type':'disabled'}
    context=json.loads(wire['messages'][1]['content']);assert context['user_input']=={'message_id':user['id'],'content':user['content'],'formal_responses':None} and context['scope']==original['scope'] and context['read_manifest']==json.loads(usage['context_manifest_json'])
    document=case['before']['current'] if usage['guide_run_id']==old['id'] else current
    assert context['current_document']['content_version']==document['content_version'] and context['current_document']['id']==document['id']
    blocks={m['block_id']:(b,m) for b,m in zip(parse_markdown(document['markdown_content']).blocks,document['block_state_json']['blocks'])}
    for item in context['current_document']['read_blocks']:
     block,meta=blocks[item['metadata']['block_id']];assert item=={'markdown_content':block.markdown,'plain_text':block.plain_text,'heading_level':block.heading_level,'metadata':meta}
   assert [m['id'] for m in case['messages']['items']]==[m['id'] for m in messages]
   checked.append({'name':case['name'],'requirement_id':identity,'old_failed_run':old['id'],'new_run':runs[2]['id'] if success else None,'failed_attempts':3,'actual_user_triggers':1,'current_version':current['content_version'],'passed':True})
 assert sha(database)==before
 return {'source_evidence':path.name,'source_inputs':len(report['inputs_after']),'native_counts':counts,'database_sha256':before,'database_bytes_unchanged':True,'cases':checked,'passed':True}

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('evidence',type=Path);args=parser.parse_args()
 now=datetime.now(timezone.utc).isoformat();result={'recorded_at':now,'audit_source_sha256':sha(Path(__file__)),'scope':'Actual FAILED root/new I18 run/reused USER trigger, latest CURRENT, finite TCP attempts, original unknown replay and refusals; no paid/production compatibility proof'}
 try:result.update(passed=True,audit=audit(args.evidence))
 except Exception as error:result.update(passed=False,error=f'{type(error).__name__}: {error}')
 target=ROOT/'docs/verification'/('retry-root-post-audit-'+now.replace(':','-')+'.json')
 with target.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
 print(json.dumps({'passed':result['passed'],'evidence':str(target),'error':result.get('error')},ensure_ascii=False))
 if not result['passed']:raise SystemExit(1)
