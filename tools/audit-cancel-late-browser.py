"""Independent immutable SQLite audit for actual sent-request cancellation roots."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.documents.markdown import parse_markdown


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(path):
    report=json.loads(path.read_text(encoding='utf-8'))
    assert report['passed'] and report['native']['code']==0 and not report['changed_inputs']
    assert report['inputs_before']==report['inputs_after']
    for name,digest in report['inputs_after'].items():assert sha(ROOT/name)==digest,name
    args=report['native']['args'];assert '--controlled-cancellation-model' in args
    database=Path(args[args.index('--database')+1]).resolve();assert database.is_relative_to((ROOT/'output/playwright').resolve())
    before=sha(database);assert before==report['database_sha256']
    diagnostic=report['controlled_model'];assert diagnostic['loopback_chat_requests']==len(report['cases']) and diagnostic['paid_requests']==0 and diagnostic['private_hooks_restored'] and diagnostic['server_closed'] and diagnostic['transport_closed'] and not diagnostic['server_errors'] and diagnostic['production_compatibility_proved'] is False
    checked=[]
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
        db.row_factory=sqlite3.Row
        counts={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in report['native_facts']}
        assert counts==report['native_facts'] and counts['llm_uses']==len(report['cases']) and counts['suggestion_batches']==counts['suggestions']==0
        for case in report['cases']:
            initial=case['before'];final=case['after'];identity=initial['requirement']['id'];name=case['name']
            requirement=dict(db.execute('SELECT * FROM requirements WHERE id=?',(identity,)).fetchone());assert requirement==final['requirement']
            assert requirement['document_work_state']=='IDLE' and requirement['active_operation_type'] is None and requirement['active_operation_id'] is None
            for field in initial['requirement']:
                if field not in ('updated_at','document_work_state','active_operation_type','active_operation_id','active_operation_started_at'):assert requirement[field]==initial['requirement'][field],(name,field)
            current=dict(db.execute("SELECT * FROM requirement_documents WHERE requirement_id=? AND document_type='CURRENT'",(identity,)).fetchone());current['block_state_json']=json.loads(current['block_state_json'])
            assert current==initial['current']==final['current'] and current['content_version']==3
            assert db.execute('SELECT count(*) FROM requirement_documents WHERE requirement_id=?',(identity,)).fetchone()[0]==1
            revisions=[]
            for row in db.execute('SELECT * FROM revisions WHERE requirement_id=? ORDER BY version_no',(identity,)):
                value=dict(row);value['markdown_content']=value.pop('markdown_snapshot');value['block_state_json']=json.loads(value.pop('block_state_snapshot_json'));revisions.append(value)
            assert revisions==initial['revision_details']==final['revision_details'] and len(revisions)==1
            runs=[dict(row) for row in db.execute('SELECT * FROM guide_runs WHERE requirement_id=? ORDER BY id',(identity,))]
            assert len(runs)==2 and runs[0]['status']=='FAILED' and runs[0]['function_type']=='INITIALIZE_REQUIREMENT'
            row=runs[1];actual=case['actual'];original=case['original']
            assert (row['id'],row['status'],row['current_step'],row['cancel_reason'])==(actual['id'],'CANCELLED','FINISHED','USER_REQUESTED')
            waiting=name=='CANCEL-waiting-cards';assert original['status']==('WAITING_USER' if waiting else 'RUNNING') and original['current_step']==('WAITING_USER' if waiting else 'VALIDATING' if name=='CANCEL-validated' else 'CALLING_MODEL')
            assert row['action_type']==case['action'] and row['function_type']==('ANSWER_REQUIREMENT' if waiting else 'REVIEW_REQUIREMENT') and row['source_type']=='USER_INSTRUCTION' and row['source_id'] is None
            assert row['final_result_json'] is None and actual['final_result'] is None and actual['suggestion_batch_id'] is None
            assert row['scope_type']=='DOCUMENT' and row['scope_ref_json'] is None
            assert json.loads(row['allowed_targets_json'])=={'schema_version':1,'targets':[]}
            assert row['ended_at']==actual['ended_at'] and row['updated_at']==actual['updated_at']
            for field in ('created_at','started_at','waiting_user_at'):assert actual[field]==original[field]
            messages=[dict(item) for item in db.execute('SELECT * FROM conversation_messages WHERE requirement_id=? ORDER BY sequence_no',(identity,))]
            assert len(messages)==(3 if waiting else 2) and [item['sequence_no'] for item in messages]==list(range(1,len(messages)+1)) and all(item['role']=='USER' and item['message_type']=='TEXT' for item in messages[:2]);assert [{k:m[k] for k in ('id','role','message_type','content')} for m in messages]==[{k:m[k] for k in ('id','role','message_type','content')} for m in case['before_messages']['items']]
            assert messages[1]['id']==row['trigger_message_id'] and messages[1]['content']==case['instruction']
            assert messages[1]['idempotency_key']==row['idempotency_key']==case['hidden'][0]['key']
            assert len(case['hidden'])==1 and case['hidden'][0]['status']==202
            accepted=db.execute('SELECT * FROM idempotency_records WHERE idempotency_key=?',(row['idempotency_key'],)).fetchone()
            assert json.loads(accepted['success_result_json'])['data']==case['accepted']
            requests=case['requests'];assert len(requests)==(2 if name=='CANCEL-wire-unknown' else 1)
            for request in requests:
                assert request['status']==200 and 'body' not in request and request['path']=='/api/v1/guide-runs/'+str(row['id'])+'/cancel'
                record=db.execute('SELECT * FROM idempotency_records WHERE idempotency_key=?',(request['key'],)).fetchone()
                assert (record['status'],record['http_status'])==('SUCCEEDED',200)
                assert json.loads(record['success_result_json'])['data']==request['response']['data']
            if name=='CANCEL-wire-unknown':
                assert requests[0]['key']==requests[1]['key'] and requests[0]['response']['data']==requests[1]['response']['data']
                assert requests[0]['delivered'] is False and requests[1]['delivered'] is True
            repeated=case['repeated'];assert repeated['key']!=requests[0]['key'] and repeated['status']==200
            assert repeated['payload']['data']==requests[-1]['response']['data']
            record=db.execute('SELECT * FROM idempotency_records WHERE idempotency_key=?',(repeated['key'],)).fetchone()
            assert json.loads(record['success_result_json'])['data']==repeated['payload']['data']
            assert case['protected_result']['actual_cancelled_shown']
            assert db.execute('SELECT count(*) FROM suggestion_batches WHERE requirement_id=?',(identity,)).fetchone()[0]==0
            assert db.execute('SELECT count(*) FROM comments WHERE requirement_id=?',(identity,)).fetchone()[0]==0
            audits=[dict(item) for item in db.execute('SELECT * FROM llm_uses WHERE guide_run_id=?',(row['id'],))];assert len(audits)==1
            usage=audits[0];assert (usage['call_no'],usage['attempt_no'])==(1,1) and usage['model_name']=='deepseek-v4-1-flash-260910' and usage['model_version']=='260910' and usage['prompt_config']==row['function_type']+'@v2'
            request_snapshot=json.loads(usage['request_snapshot_json'])['request'];assert request_snapshot['max_tokens']==8192 and request_snapshot['thinking']=={'type':'disabled'}
            context=json.loads(request_snapshot['messages'][1]['content']);assert context['user_input']=={'message_id':messages[1]['id'],'content':messages[1]['content'],'formal_responses':None} and context['read_manifest']==json.loads(usage['context_manifest_json']) and context['current_document']['id']==current['id'] and context['current_document']['content_version']==3
            blocks={m['block_id']:(b,m) for b,m in zip(parse_markdown(current['markdown_content']).blocks,current['block_state_json']['blocks'])}
            for item in context['current_document']['read_blocks']:
                block,meta=blocks[item['metadata']['block_id']];assert item=={'markdown_content':block.markdown,'plain_text':block.plain_text,'heading_level':block.heading_level,'metadata':meta}
            finished=case['finished'];events=[e for e in finished['events'] if e.get('guide_run_id')==row['id']];assert not finished['active_worker_ids'] and not finished['backoff_held'] and not finished['receipt_held']
            assert any(e['event']=='ACTUAL_CANCEL_CONNECTION_FINISHED' for e in events)
            if name.startswith('CANCEL-wire'):
                assert case['during']['wire_hold_armed'] and case['during']['tcp_headers_sent'] and finished['tcp_peer_closed']
                assert usage['call_status']=='CANCELLED' and usage['ended_at']==row['ended_at'] and usage['raw_response_json'] is None and usage['input_tokens'] is None and usage['output_tokens'] is None and usage['trusted_output_json'] is None and usage['parse_status']==usage['validation_status']=='NOT_STARTED'
            elif name=='CANCEL-backoff':
                assert case['during']['backoff_held'] and [e['seconds'] for e in events if e['event']=='REAL_ORCH_BACKOFF_HELD']==[2]
                assert usage['call_status']=='FAILED' and usage['error_code']=='MODEL_ERROR' and usage['ended_at']<=row['ended_at'] and json.loads(usage['raw_response_json'])=={} and usage['trusted_output_json'] is None and usage['parse_status']==usage['validation_status']=='NOT_STARTED'
            else:
                assert (usage['call_status'],usage['parse_status'],usage['validation_status'])==('SUCCEEDED','SUCCEEDED','SUCCEEDED') and usage['input_tokens']==123 and usage['output_tokens']==10
                trusted=json.loads(usage['trusted_output_json']);assert json.loads(json.loads(usage['raw_response_json'])['choices'][0]['message']['content'])==trusted
                assert ResourceCatalog().freeze(case['action'],'USER_INSTRUCTION').parse_output(json.dumps(trusted,ensure_ascii=False))==trusted
                if name=='CANCEL-validated':
                    assert case['during']['receipt_held'] and trusted['response_type']=='REVIEW_RESULT'
                    late=next(e for e in events if e['event']=='LATE_NATIVE_RECEIPT_REJECTED');assert late['persistence_code']==late['validation_code']=='STATE_CONFLICT' and late['business_facts_unchanged'] and late['facts_sha256_before']==late['facts_sha256_after'] and late['llm_use_id']==usage['id']
                else:
                    assert waiting and trusted['response_type']=='CLARIFY_CARDS' and messages[2]['role']=='ASSISTANT' and messages[2]['message_type']=='INTERACTION_CARDS' and messages[2]['content']==trusted['message'] and json.loads(messages[2]['structured_content_json'])==trusted['cards']
                    assert case['before_messages']['items'][2]['card_state']=='AVAILABLE' and case['messages']['items'][2]['card_state']=='EXPIRED' and case['card_draft'] and case['card_result']=={'storage':{},'expired_visible':True}
                    assert messages[2]['guide_run_id']==row['id']
            if not waiting:assert any(e['event']=='ACTUAL_WORKER_TASK_CANCELLED' and e['lease_retired'] for e in events)
            for public,stored in zip(case['messages']['items'],messages):
                for field in ('id','requirement_id','guide_run_id','role','message_type','content','sequence_no','created_at'):assert public[field]==stored[field]
            checked.append({'name':name,'requirement_id':identity,'current_version':3,'runs':2,'user_messages':2,'assistant_messages':1 if waiting else 0,'llm_uses':1,'passed':True})
    assert sha(database)==before
    return {'source_evidence':path.name,'source_inputs':len(report['inputs_after']),'native_counts':counts,'database_sha256':before,'database_bytes_unchanged':True,'cases':checked,'passed':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('evidence',type=Path);args=parser.parse_args()
    now=datetime.now(timezone.utc).isoformat();result={'recorded_at':now,'audit_source_sha256':sha(Path(__file__)),'scope':'Actual sent TCP/backoff/validated native receipt/WAITING cards cancellation roots; actual native SQL/unique messages/unknown original I17/late gate/expired card draft; no paid or production compatibility proof'}
    try:result.update(passed=True,audit=audit(args.evidence))
    except Exception as error:result.update(passed=False,error=f'{type(error).__name__}: {error}')
    target=ROOT/'docs/verification'/('cancel-late-post-audit-'+now.replace(':','-')+'.json')
    with target.open('x',encoding='utf-8') as file:json.dump(result,file,ensure_ascii=False,indent=2);file.write('\n')
    print(json.dumps({'passed':result['passed'],'evidence':str(target),'error':result.get('error')},ensure_ascii=False))
    if not result['passed']:raise SystemExit(1)
