"""Independent immutable SQLite audit for controlled ordinary-action root flows."""
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
    args=report['native']['args'];assert '--hold-review-dispatch' in args
    database=Path(args[args.index('--database')+1]).resolve();assert database.is_relative_to((ROOT/'output/playwright').resolve())
    before=sha(database);assert before==report['database_sha256']
    checked=[]
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
        db.row_factory=sqlite3.Row
        counts={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in report['native_facts']}
        assert counts==report['native_facts'] and counts['llm_uses']==0
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
            assert original['status']=='RUNNING' and original['current_step']=='PREPARING'
            assert row['action_type']=='REVIEW' and row['function_type']=='REVIEW_REQUIREMENT' and row['source_type']=='USER_INSTRUCTION' and row['source_id'] is None
            assert row['final_result_json'] is None and actual['final_result'] is None and actual['suggestion_batch_id'] is None
            assert row['scope_type']=='DOCUMENT' and row['scope_ref_json'] is None
            assert json.loads(row['allowed_targets_json'])=={'schema_version':1,'targets':[]}
            assert row['ended_at']==actual['ended_at'] and row['updated_at']==actual['updated_at']
            for field in ('created_at','started_at','waiting_user_at'):assert actual[field]==original[field]
            messages=[dict(item) for item in db.execute('SELECT * FROM conversation_messages WHERE requirement_id=? ORDER BY sequence_no',(identity,))]
            assert len(messages)==2 and [item['sequence_no'] for item in messages]==[1,2] and all(item['role']=='USER' and item['message_type']=='TEXT' for item in messages)
            assert messages[1]['id']==row['trigger_message_id'] and messages[1]['content']=='取消根验收'
            assert messages[1]['idempotency_key']==row['idempotency_key']==case['hidden'][0]['key']
            assert len(case['hidden'])==1 and case['hidden'][0]['status']==202
            accepted=db.execute('SELECT * FROM idempotency_records WHERE idempotency_key=?',(row['idempotency_key'],)).fetchone()
            assert json.loads(accepted['success_result_json'])['data']==case['accepted']
            requests=case['requests'];assert len(requests)==(2 if name=='CANCEL-unknown' else 1)
            for request in requests:
                assert request['status']==200 and 'body' not in request and request['path']=='/api/v1/guide-runs/'+str(row['id'])+'/cancel'
                record=db.execute('SELECT * FROM idempotency_records WHERE idempotency_key=?',(request['key'],)).fetchone()
                assert (record['status'],record['http_status'])==('SUCCEEDED',200)
                assert json.loads(record['success_result_json'])['data']==request['response']['data']
            if name=='CANCEL-unknown':
                assert requests[0]['key']==requests[1]['key'] and requests[0]['response']['data']==requests[1]['response']['data']
                assert requests[0]['delivered'] is False and requests[1]['delivered'] is True
            repeated=case['repeated'];assert repeated['key']!=requests[0]['key'] and repeated['status']==200
            assert repeated['payload']['data']==requests[-1]['response']['data']
            record=db.execute('SELECT * FROM idempotency_records WHERE idempotency_key=?',(repeated['key'],)).fetchone()
            assert json.loads(record['success_result_json'])['data']==repeated['payload']['data']
            assert case['protected_result']['actual_cancelled_shown']
            assert db.execute('SELECT count(*) FROM suggestion_batches WHERE requirement_id=?',(identity,)).fetchone()[0]==0
            assert db.execute('SELECT count(*) FROM comments WHERE requirement_id=?',(identity,)).fetchone()[0]==0
            assert db.execute('SELECT count(*) FROM llm_uses WHERE guide_run_id=?',(row['id'],)).fetchone()[0]==0
            for public,stored in zip(case['messages']['items'],messages):
                for field in ('id','requirement_id','guide_run_id','role','message_type','content','sequence_no','created_at'):assert public[field]==stored[field]
            checked.append({'name':name,'requirement_id':identity,'current_version':3,'runs':2,'user_messages':2,'assistant_messages':0,'llm_uses':0,'passed':True})
    assert sha(database)==before
    return {'source_evidence':path.name,'source_inputs':len(report['inputs_after']),'native_counts':counts,'database_sha256':before,'database_bytes_unchanged':True,'cases':checked,'passed':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('evidence',type=Path);args=parser.parse_args()
    now=datetime.now(timezone.utc).isoformat();result={'recorded_at':now,'audit_source_sha256':sha(Path(__file__)),'scope':'Actual root REVIEW cancellation before model boundary: hidden panel does not cancel; unknown original I17 and in-flight protection; immutable CURRENT/Baseline and USER trigger; native cancellation/idempotency/ended time; no model or Provider proof'}
    try:result.update(passed=True,audit=audit(args.evidence))
    except Exception as error:result.update(passed=False,error=f'{type(error).__name__}: {error}')
    target=ROOT/'docs/verification'/('run-cancel-post-audit-'+now.replace(':','-')+'.json')
    with target.open('x',encoding='utf-8') as file:json.dump(result,file,ensure_ascii=False,indent=2);file.write('\n')
    print(json.dumps({'passed':result['passed'],'evidence':str(target),'error':result.get('error')},ensure_ascii=False))
    if not result['passed']:raise SystemExit(1)
