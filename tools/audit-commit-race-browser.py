"""Independent read-only closed SQLite proof of C07 winning a real I17 race."""
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
 report=json.loads(path.read_text(encoding='utf-8'))
 assert report['passed'] and report['native']['code']==0 and not report['changed_inputs'] and report['inputs_before']==report['inputs_after']
 for name,digest in report['inputs_after'].items():assert sha(ROOT/name)==digest,name
 args=report['native']['args'];assert '--controlled-commit-race-model' in args
 database=Path(args[args.index('--database')+1]);assert database.resolve().is_relative_to((ROOT/'output/playwright').resolve())
 before=sha(database);assert before==report['database_sha256'];model=report['controlled_model']
 assert model['paid_requests']==0 and model['loopback_chat_requests']==len(report['cases']) and model['private_hooks_restored']
 assert model['server_closed'] and model['transport_closed'] and not model['server_errors'] and model['production_compatibility_proved'] is False
 checked=[]
 with closing(sqlite3.connect(database.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
  db.row_factory=sqlite3.Row
  counts={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in report['native_facts']}
  assert counts==report['native_facts'] and counts['llm_uses']==len(report['cases']) and counts['suggestion_batches']==counts['suggestions']==0
  for case in report['cases']:
   initial=case['before'];after=case['after'];identity=initial['requirement']['id'];run_id=case['actual']['id']
   current=dict(db.execute("SELECT * FROM requirement_documents WHERE requirement_id=? AND document_type='CURRENT'",(identity,)).fetchone());current['block_state_json']=json.loads(current['block_state_json'])
   assert current==initial['current']==after['current'] and current['content_version']==3
   root=dict(db.execute('SELECT * FROM requirements WHERE id=?',(identity,)).fetchone());assert root==after['requirement'] and root['document_work_state']=='IDLE' and root['active_operation_id'] is None
   revisions=[]
   for row in db.execute('SELECT * FROM revisions WHERE requirement_id=? ORDER BY version_no',(identity,)):
    item=dict(row);item['markdown_content']=item.pop('markdown_snapshot');item['block_state_json']=json.loads(item.pop('block_state_snapshot_json'));revisions.append(item)
   assert revisions==initial['revision_details']==after['revision_details'] and len(revisions)==1
   assert initial['revisions']==after['revisions']
   runs=[dict(row) for row in db.execute('SELECT * FROM guide_runs WHERE requirement_id=? ORDER BY id',(identity,))]
   assert len(runs)==2 and runs[0]['status']=='FAILED' and runs[0]['error_code']=='CONFIG_INVALID'
   run=runs[1];assert run['id']==run_id and run['status']=='COMPLETED' and run['current_step']=='FINISHED' and run['cancel_reason'] is None
   assert run['action_type']=='REVIEW' and run['function_type']=='REVIEW_REQUIREMENT' and run['source_type']=='USER_INSTRUCTION' and run['source_id'] is None
   assert run['scope_type']=='DOCUMENT' and run['scope_ref_json'] is None and json.loads(run['allowed_targets_json'])=={'schema_version':1,'targets':[]}
   assert run['error_code'] is None and run['ended_at']==case['actual']['ended_at'] and run['retry_of_guide_run_id'] is None
   events=case['race']['events'];assert events==model['commit_race']['events'] and len(events)==3
   assert [e['event'] for e in events]==['C07_NATIVE_GATE_HELD','I17_NATIVE_WRITE_BEGIN','C07_NATIVE_GATE_RELEASED']
   assert events[0]['in_transaction'] and events[0]['current_step']=='PERSISTING' and events[0]['status']=='RUNNING'
   assert events[1]['gate_held'] and events[1]['gate_identity']==run_id and events[1]['guide_run_id']==run_id and events[1]['in_transaction'] is False
   assert events[0]['thread_id']==events[2]['thread_id'] and events[0]['thread_id']!=events[1]['thread_id']
   assert all(events[i]['monotonic_ns']<events[i+1]['monotonic_ns'] for i in range(2))
   assert case['original']['status']=='RUNNING' and case['original']['current_step']=='VALIDATING'
   request=case['requests'][0];assert len(case['requests'])==1 and request['status']==409 and request['delivered'] and 'body' not in request
   assert request['response']['error']['code']=='STATE_CONFLICT' and request['response']['data'] is None and request['key']==events[1]['idempotency_key']
   assert db.execute('SELECT count(*) FROM idempotency_records WHERE idempotency_key=?',(request['key'],)).fetchone()[0]==0
   messages=[dict(row) for row in db.execute('SELECT * FROM conversation_messages WHERE requirement_id=? ORDER BY sequence_no',(identity,))]
   assert len(messages)==3 and [m['role'] for m in messages]==['USER','USER','ASSISTANT'] and all(m['message_type']=='TEXT' for m in messages)
   assert messages[1]['content']=='操作范围验收 COMMIT_RACE' and messages[1]['id']==run['trigger_message_id'] and messages[1]['idempotency_key']==run['idempotency_key']
   final=json.loads(run['final_result_json']);assert final['assistant_message_id']==messages[2]['id'] and final['status']=='COMPLETED' and final['suggestion_batch_id'] is None
   audits=[dict(row) for row in db.execute('SELECT * FROM llm_uses WHERE guide_run_id=?',(run_id,))];assert len(audits)==1
   usage=audits[0];assert (usage['call_no'],usage['attempt_no'],usage['call_status'],usage['parse_status'],usage['validation_status'])==(1,1,'SUCCEEDED','SUCCEEDED','SUCCEEDED')
   assert (usage['model_name'],usage['model_version'],usage['prompt_config'])==('deepseek-v4-1-flash-260910','260910','REVIEW_REQUIREMENT@v2')
   wire=json.loads(usage['request_snapshot_json'])['request'];assert wire['max_tokens']==8192 and wire['thinking']=={'type':'disabled'} and wire['model']==usage['model_name']
   context=json.loads(wire['messages'][1]['content']);assert context['user_input']=={'message_id':messages[1]['id'],'content':messages[1]['content'],'formal_responses':None}
   assert context['current_document']['content_version']==3 and context['current_document']['id']==current['id'] and context['allowed_targets']==[] and context['read_manifest']==json.loads(usage['context_manifest_json'])
   pairs={m['block_id']:(b,m) for b,m in zip(parse_markdown(current['markdown_content']).blocks,current['block_state_json']['blocks'])}
   for item in context['current_document']['read_blocks']:
    block,meta=pairs[item['metadata']['block_id']];assert item=={'markdown_content':block.markdown,'plain_text':block.plain_text,'heading_level':block.heading_level,'metadata':meta}
   trusted=json.loads(usage['trusted_output_json']);raw=json.loads(usage['raw_response_json']);assert json.loads(raw['choices'][0]['message']['content'])==trusted
   assert ResourceCatalog().freeze('REVIEW','USER_INSTRUCTION').parse_output(json.dumps(trusted,ensure_ascii=False))==trusted and trusted['response_type']=='REVIEW_RESULT'
   assert final['review_result']==trusted['review_result'] and messages[2]['content']==trusted['message']
   assert case['result']['final_shown'] and not case['result']['cancelled_shown'] and not model['commit_race']['held']
   for public,row in zip(case['messages']['items'],messages):
    for field in ('id','requirement_id','guide_run_id','role','message_type','content','sequence_no','created_at'):assert public[field]==row[field]
   checked.append({'name':case['name'],'requirement_id':identity,'committed_run':run_id,'native_race_events':3,'cancel_http':409,'unique_assistant':messages[2]['id'],'passed':True})
 assert sha(database)==before
 return {'source_evidence':path.name,'source_inputs':len(report['inputs_after']),'native_counts':counts,'database_sha256':before,'database_bytes_unchanged':True,'cases':checked,'passed':True}

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('evidence',type=Path);args=parser.parse_args()
 now=datetime.now(timezone.utc).isoformat();result={'recorded_at':now,'audit_source_sha256':sha(Path(__file__)),'scope':'Actual C07 PERSISTING transaction versus public I17 native BEGIN, final result/idempotency/unchanged CURRENT and Baseline; no paid or production compatibility proof'}
 try:result.update(passed=True,audit=audit(args.evidence))
 except Exception as error:result.update(passed=False,error=f'{type(error).__name__}: {error}')
 target=ROOT/'docs/verification'/('commit-race-post-audit-'+now.replace(':','-')+'.json')
 with target.open('x',encoding='utf-8') as file:json.dump(result,file,ensure_ascii=False,indent=2);file.write('\n')
 print(json.dumps({'passed':result['passed'],'evidence':str(target),'error':result.get('error')},ensure_ascii=False))
 if not result['passed']:raise SystemExit(1)
