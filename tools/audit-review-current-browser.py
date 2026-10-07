"""Independent immutable SQLite audit for saved REVIEW against newer CURRENT root flows."""
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
    assert '--controlled-scope-model' in report['native']['args']
    args=report['native']['args'];database=Path(args[args.index('--database')+1]).resolve()
    assert database.is_relative_to((ROOT/'output/playwright').resolve())
    before=sha(database);assert before==report['database_sha256']
    expected_calls=sum(2 if case['second'] else 1 for case in report['cases'])
    diagnostic=report['controlled_model']
    assert diagnostic['loopback_chat_requests']==expected_calls and diagnostic['paid_requests']==0
    assert diagnostic['server_closed'] and diagnostic['transport_closed'] and diagnostic['server_errors']==[]
    assert diagnostic['production_compatibility_proved'] is False
    checked=[]
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
        db.row_factory=sqlite3.Row
        counts={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in report['native_facts']}
        assert counts==report['native_facts'] and counts['llm_uses']==expected_calls
        for case in report['cases']:
            name=case['name'];initial=case['before'];final=case['after'];identity=initial['requirement']['id']
            root=dict(db.execute('SELECT * FROM requirements WHERE id=?',(identity,)).fetchone())
            assert root==final['requirement'] and root['document_work_state']=='IDLE'
            for field in initial['requirement']:
                if field not in ('updated_at','document_work_state','active_operation_type','active_operation_id','active_operation_started_at'):
                    assert root[field]==initial['requirement'][field],(name,field)
            current=dict(db.execute("SELECT * FROM requirement_documents WHERE requirement_id=? AND document_type='CURRENT'",(identity,)).fetchone())
            current['block_state_json']=json.loads(current['block_state_json'])
            assert current==case['edited']['current']==final['current'],name+' immutable current v4 after actual manual edit'
            assert case['after_first']['current']==initial['current'] and initial['current']['content_version']==3 and current['content_version']==4
            assert current['markdown_content']!=initial['current']['markdown_content']
            if name=='REVIEW-INVALID-SELECTION':
                assert case['invalid_observation']['rejected_without_write'] and case['invalid_observation']['input_retained']=='保留未发送说明😀'
                assert case['modified_scope']['scope_type']=='BLOCK'
                assert '😀' not in parse_markdown(current['markdown_content']).blocks[-1].plain_text
            assert db.execute("SELECT count(*) FROM requirement_documents WHERE requirement_id=? AND document_type='MANUAL_DRAFT'",(identity,)).fetchone()[0]==0
            revisions=[]
            for row in db.execute('SELECT * FROM revisions WHERE requirement_id=? ORDER BY version_no',(identity,)):
                item=dict(row);item['markdown_content']=item.pop('markdown_snapshot');item['block_state_json']=json.loads(item.pop('block_state_snapshot_json'));revisions.append(item)
            assert revisions==initial['revision_details']==final['revision_details']==case['after_first']['revision_details'] and len(revisions)==1
            assert initial['revisions']==final['revisions']==case['after_first']['revisions']
            assert db.execute('SELECT count(*) FROM comments WHERE requirement_id=?',(identity,)).fetchone()[0]==0
            runs=[dict(row) for row in db.execute('SELECT * FROM guide_runs WHERE requirement_id=? ORDER BY id',(identity,))]
            actions=[case['first']]+([case['second']] if case['second'] else [])
            assert len(runs)==1+len(actions) and runs[0]['status']=='FAILED' and runs[0]['function_type']=='INITIALIZE_REQUIREMENT'
            first_review=None
            messages=[dict(row) for row in db.execute('SELECT * FROM conversation_messages WHERE requirement_id=? ORDER BY sequence_no',(identity,))]
            assert len(messages)==1+2*len(actions) and [m['sequence_no'] for m in messages]==list(range(1,len(messages)+1))
            for number,(row,action) in enumerate(zip(runs[1:],actions)):
                read_current=initial['current'] if number==0 else current
                parsed=parse_markdown(read_current['markdown_content']);by_id={meta['block_id']:(block,meta) for block,meta in zip(parsed.blocks,read_current['block_state_json']['blocks'])}
                version=read_current['content_version']
                actual=action['actual'];scope=case['expected_scope'] if number==0 else case['modified_scope']
                assert row['id']==actual['id'] and row['status']=='COMPLETED' and row['current_step']=='FINISHED'
                assert row['error_code'] is None and row['error_message'] is None and row['retry_of_guide_run_id'] is None
                assert actual['scope']==scope=={'scope_type':row['scope_type'],'scope_ref':None if row['scope_ref_json'] is None else json.loads(row['scope_ref_json'])}
                source='USER_INSTRUCTION' if number==0 else 'REVIEW_RESULT';source_id=None if number==0 else case['first']['actual']['id']
                assert (row['source_type'],row['source_id'])==(source,source_id)
                user=messages[1+number*2];assistant=messages[2+number*2]
                assert user['id']==row['trigger_message_id'] and user['guide_run_id']==row['id'] and user['role']=='USER' and user['message_type']=='TEXT'
                assert assistant['guide_run_id']==row['id'] and assistant['role']=='ASSISTANT' and assistant['message_type']=='TEXT' and assistant['idempotency_key'] is None
                assert user['idempotency_key']==row['idempotency_key']==action['requests'][0]['key']
                assert user['content']==json.loads(action['requests'][0]['body'])['instruction']
                for request in action['requests']:
                    body=json.loads(request['body']);assert body=={'expected_version':version,'action_type':row['action_type'],'instruction':user['content'],**scope,'source_type':source,'source_id':source_id}
                    assert request['status']==202
                    record=db.execute('SELECT * FROM idempotency_records WHERE idempotency_key=?',(request['key'],)).fetchone()
                    assert record['status']=='SUCCEEDED' and record['http_status']==202
                    assert json.loads(record['success_result_json'])['data']==request['response']['data'],name+' immutable accepted receipt'
                assert len(action['requests'])==1
                audits=[dict(item) for item in db.execute('SELECT * FROM llm_uses WHERE guide_run_id=?',(row['id'],))]
                assert len(audits)==1;usage=audits[0]
                assert (usage['call_no'],usage['attempt_no'],usage['call_status'],usage['parse_status'],usage['validation_status'])==(1,1,'SUCCEEDED','SUCCEEDED','SUCCEEDED')
                assert (usage['model_name'],usage['model_version'],usage['function_type'],usage['prompt_config'])==('deepseek-v4-1-flash-260910','260910',row['function_type'],row['function_type']+'@v2')
                request=json.loads(usage['request_snapshot_json'])['request']
                assert request['model']==usage['model_name'] and request['thinking']=={'type':'disabled'} and request['max_tokens']==8192
                assert [m['role'] for m in request['messages']]==['system','user']
                context=json.loads(request['messages'][1]['content'])
                assert context['user_input']=={'message_id':user['id'],'content':user['content'],'formal_responses':None}
                # Public SECTION uses block_id; the approved model context
                # names the same exact heading heading_block_id.
                context_scope={'scope_type':'SECTION','scope_ref':{'heading_block_id':scope['scope_ref']['block_id']}} if row['scope_type']=='SECTION' else scope
                assert context['scope']==context_scope and context['source_type']==source and context['action_type']==row['action_type']
                assert context['current_document']['id']==current['id'] and context['current_document']['content_version']==version
                # The accepted Run freezes required trigger IDs. Compilation
                # adds eligible visible history; audit the full actual manifest.
                frozen=json.loads(row['read_scope_manifest_json']);manifest=context['read_manifest']
                assert manifest==json.loads(usage['context_manifest_json'])
                assert {key:value for key,value in manifest.items() if key!='message_ids'}=={key:value for key,value in frozen.items() if key!='message_ids'}
                assert set(frozen['message_ids'])<=set(manifest['message_ids'])
                assert manifest['message_ids']==[m['id'] for m in messages if m['sequence_no']<=user['sequence_no']]
                assert context['history']==[{key:m[key] for key in ('id','sequence_no','role','message_type','content')}|{'formal_responses':None} for m in messages if m['sequence_no']<user['sequence_no']]
                assert manifest['source']=={'source_type':source,'source_id':source_id}
                assert context['allowed_targets']==json.loads(row['allowed_targets_json'])['targets']
                assert [b['metadata']['block_id'] for b in context['current_document']['read_blocks']]==manifest['block_ids']
                for item in context['current_document']['read_blocks']:
                    block,meta=by_id[item['metadata']['block_id']]
                    assert item=={'markdown_content':block.markdown,'plain_text':block.plain_text,'heading_level':block.heading_level,'metadata':meta}
                trusted=json.loads(usage['trusted_output_json']);raw=json.loads(usage['raw_response_json'])
                assert json.loads(raw['choices'][0]['message']['content'])==trusted and raw['model']==usage['model_name']
                protocol=ResourceCatalog().freeze(row['action_type'],source);assert protocol.parse_output(json.dumps(trusted,ensure_ascii=False))==trusted
                final_result=json.loads(row['final_result_json']);assert final_result['assistant_message_id']==assistant['id'] and assistant['content']==trusted['message']
                assert final_result['guide_run_id']==row['id'] and final_result['status']=='COMPLETED'
                if row['action_type'] in ('ASK','REVIEW'):
                    assert context['allowed_targets']==[] and context['source'] is None and final_result['suggestion_batch_id'] is None
                    assert trusted['response_type']==('ANSWER' if row['action_type']=='ASK' else 'REVIEW_RESULT')
                    if row['action_type']=='REVIEW':
                        first_review=trusted['review_result'];assert final_result['review_result']==first_review
                        assert len(first_review['issues'])==1 and first_review['issues'][0]['block_ids']==[read_current['block_state_json']['blocks'][-1]['block_id']]
                        assert first_review['issues'][0]['evidence']==by_id[first_review['issues'][0]['block_ids'][0]][0].plain_text
                elif source=='USER_INSTRUCTION':
                    assert trusted['response_type']=='NO_CHANGE' and context['source'] is None and final_result['suggestion_batch_id'] is None
                else:
                    assert context['source']=={'guide_run_id':source_id,'reviewed_content_version':3,'review_result':first_review}
                    assert trusted['response_type']=='SUGGESTIONS' and len(trusted['suggestions'])==1
                    batch=case['final_batch'];stored=dict(db.execute('SELECT * FROM suggestion_batches WHERE guide_run_id=?',(row['id'],)).fetchone())
                    assert stored=={key:value for key,value in batch.items() if key not in ('counts','suggestions')}
                    assert (stored['source_type'],stored['source_id'],stored['status'],stored['base_content_version'],stored['applied_content_version'])==('REVIEW_RESULT',source_id,'DISCARDED',4,None)
                    assert final_result['suggestion_batch_id']==stored['id']
                    assert len(batch['suggestions'])==1
                    proposed=trusted['suggestions'][0]
                    for field in ('patch_operation','target_ref','original_content','proposed_markdown'):assert proposed[field]==case['before_batch']['suggestions'][0][field]==batch['suggestions'][0][field]
                    assert proposed['target_ref']['block_id'] in [target['block_id'] for target in context['allowed_targets']]
                    if row['scope_type']=='SELECTION':assert proposed['proposed_markdown']==proposed['original_content'].replace(scope['scope_ref']['selected_text'],'正式规则😀',1)
                    discard=[r for r in case['wire']['requests'] if r['method']=='POST' and r['path'].endswith('/discard')]
                    assert len(discard)==1 and discard[0]['status']==200
                    record=db.execute('SELECT * FROM idempotency_records WHERE idempotency_key=?',(discard[0]['key'],)).fetchone()
                    assert record['status']=='SUCCEEDED' and json.loads(record['success_result_json'])['data']==discard[0]['response']['data']
            batch_count=db.execute('SELECT count(*) FROM suggestion_batches WHERE requirement_id=?',(identity,)).fetchone()[0]
            assert batch_count==int(case['second'] is not None)
            public=case['messages']['items'];assert [item['id'] for item in public]==[item['id'] for item in messages]
            for item,persisted in zip(public,messages):
                for field in ('id','requirement_id','guide_run_id','role','message_type','content','sequence_no','created_at'):assert item[field]==persisted[field]
            checked.append({'name':name,'requirement_id':identity,'current_version':4,'reviewed_version':3,'runs':len(runs),'messages':len(messages),'llm_uses':len(actions),'batches':batch_count,'passed':True})
    assert sha(database)==before
    return {'source_evidence':path.name,'source_inputs':len(report['inputs_after']),'native_counts':counts,'database_sha256':before,'database_bytes_unchanged':True,'cases':checked,'passed':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('evidence',type=Path);args=parser.parse_args()
    now=datetime.now(timezone.utc).isoformat();result={'recorded_at':now,'audit_source_sha256':sha(Path(__file__)),'scope':'Saved v3 REVIEW, actual manual CURRENT v4, exact original or explicit replacement scope; separate full v3/v4 model reads, historical source and v4 proposal audited from immutable SQLite; no Provider count/effect or paid calls'}
    try:result.update(passed=True,audit=audit(args.evidence))
    except Exception as error:result.update(passed=False,error=f'{type(error).__name__}: {error}')
    target=ROOT/'docs/verification'/('review-current-post-audit-'+now.replace(':','-')+'.json')
    with target.open('x',encoding='utf-8') as file:json.dump(result,file,ensure_ascii=False,indent=2);file.write('\n')
    print(json.dumps({'passed':result['passed'],'evidence':str(target),'error':result.get('error')},ensure_ascii=False))
    if not result['passed']:raise SystemExit(1)
