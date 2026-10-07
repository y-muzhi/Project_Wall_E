"""Independent immutable SQLite audit for actual C07/C06 formal answers and second-call context."""
import argparse
from contextlib import closing
from datetime import datetime,timezone
import hashlib,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.documents.markdown import parse_markdown
from backend.app.guide.output_evidence import card_text
from backend.app.messages.cards import validate_responses, formal_answer_text

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def audit(path):
    report=json.loads(path.read_text(encoding='utf-8'))
    assert report['passed'] and report['native']['code']==0 and report['inputs_before']==report['inputs_after'] and not report['changed_inputs']
    for name,digest in report['inputs_after'].items():assert sha(ROOT/name)==digest,name
    args=report['native']['args'];assert '--controlled-waiting-model' in args
    database=Path(args[args.index('--database')+1]);assert database.resolve().is_relative_to((ROOT/'output/playwright').resolve())
    before=sha(database);assert before==report['database_sha256'];diagnostic=report['controlled_model']
    assert diagnostic['loopback_chat_requests']==len(report['cases'])*2 and diagnostic['paid_requests']==0
    assert diagnostic['server_closed'] and diagnostic['transport_closed'] and not diagnostic['server_errors'] and diagnostic['production_compatibility_proved'] is False
    checked=[]
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
        db.row_factory=sqlite3.Row
        counts={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in report['native_facts']}
        assert counts==report['native_facts'] and counts['llm_uses']==len(report['cases'])*2 and counts['suggestion_batches']==counts['suggestions']==0
        for case in report['cases']:
            identity=case['before']['requirement']['id'];formal=case['name'].startswith('ANSWERS');cards=case['name']!='TEXT-normal'
            current=dict(db.execute("SELECT * FROM requirement_documents WHERE requirement_id=? AND document_type='CURRENT'",(identity,)).fetchone());current['block_state_json']=json.loads(current['block_state_json'])
            assert current==case['before']['current']==case['during']['current']==case['after']['current'] and current['content_version']==3
            assert db.execute('SELECT count(*) FROM requirement_documents WHERE requirement_id=?',(identity,)).fetchone()[0]==1
            root=dict(db.execute('SELECT * FROM requirements WHERE id=?',(identity,)).fetchone());assert root==case['after']['requirement'] and root['document_work_state']=='IDLE' and root['status']=='ACTIVE'
            assert case['during']['requirement']['document_work_state']=='GUIDE_ACTIVE' and case['during']['requirement']['active_operation_id']==case['waiting']['id']
            revisions=[]
            for row in db.execute('SELECT * FROM revisions WHERE requirement_id=? ORDER BY version_no',(identity,)):
                item=dict(row);item['markdown_content']=item.pop('markdown_snapshot');item['block_state_json']=json.loads(item.pop('block_state_snapshot_json'));revisions.append(item)
            assert revisions==case['before']['revision_details']==case['during']['revision_details']==case['after']['revision_details'] and len(revisions)==1
            assert case['before']['revisions']==case['after']['revisions']
            runs=[dict(row) for row in db.execute('SELECT * FROM guide_runs WHERE requirement_id=? ORDER BY id',(identity,))]
            assert len(runs)==2 and runs[0]['status']=='FAILED' and runs[0]['error_code']=='CONFIG_INVALID'
            run=runs[1];assert run['id']==case['waiting']['id']==case['actual']['id'] and run['status']=='COMPLETED' and run['current_step']=='FINISHED'
            assert run['action_type']=='ASK' and run['function_type']=='ANSWER_REQUIREMENT' and run['source_type']=='USER_INSTRUCTION' and run['source_id'] is None
            assert run['scope_type']=='DOCUMENT' and run['scope_ref_json'] is None and json.loads(run['allowed_targets_json'])=={'schema_version':1,'targets':[]}
            assert case['actual']['suggestion_batch_id'] is None and run['retry_of_guide_run_id'] is None and run['error_code'] is None
            assert case['waiting']['final_result'] is None and case['waiting']['ended_at'] is None and case['waiting']['waiting_user_at']==run['waiting_user_at']
            messages=[dict(row) for row in db.execute('SELECT * FROM conversation_messages WHERE requirement_id=? ORDER BY sequence_no',(identity,))]
            assert len(messages)==5 and [m['sequence_no'] for m in messages]==[1,2,3,4,5]
            assert [m['role'] for m in messages]==['USER','USER','ASSISTANT','USER','ASSISTANT']
            assert [m['message_type'] for m in messages]==['TEXT','TEXT','INTERACTION_CARDS' if cards else 'TEXT','CARD_RESPONSE' if formal else 'TEXT','TEXT']
            assert all(m['guide_run_id']==run['id'] for m in messages[1:]) and run['trigger_message_id']==messages[3]['id']
            if formal:
                original=json.loads(messages[2]['structured_content_json']);answers=json.loads(messages[3]['structured_content_json'])
                assert validate_responses(answers,original,ResourceCatalog().freeze('ASK','USER_INSTRUCTION'))==answers and messages[3]['content']==formal_answer_text(original,answers)
                assert messages[3]['reply_to_message_id']==messages[2]['id'] and db.execute("SELECT count(*) FROM conversation_messages WHERE reply_to_message_id=? AND message_type='CARD_RESPONSE'",(messages[2]['id'],)).fetchone()[0]==1
                assert case['formal_response']['id']==messages[3]['id']
                assert len(original['cards'])==(5 if case['name']=='ANSWERS-five' else 1)
                if case['name']=='ANSWERS-five':
                    validation=case['five_required_validation'];assert set(validation)=={'cards','incomplete_group_http_posts','invalid_card_focused','invalid_focus'} and validation['cards']==5 and validation['incomplete_group_http_posts']==0 and validation['invalid_card_focused']
                    focus=validation['invalid_focus'];assert focus['focused'] and focus['visible'] and focus['field']['top']>=max(focus['area']['top'],0) and focus['field']['bottom']<=min(focus['area']['bottom'],focus['viewport_height'])
                    assert [answer['card_key'] for answer in answers['responses']]==['first','multi','confirm','optional','last'] and answers['responses'][3]=={'card_key':'optional','selected_option_keys':[],'custom_answer':None,'skipped':True}
            else:assert messages[3]['structured_content_json'] is None and messages[3]['reply_to_message_id'] is None
            final=json.loads(run['final_result_json']);assert final['assistant_message_id']==messages[4]['id'] and final['guide_run_id']==run['id'] and final['status']=='COMPLETED' and final['suggestion_batch_id'] is None
            for action,requests in [('CREATE',case['start']),('CONTINUE',case['continuation']['requests'])]:
                user=messages[1 if action=='CREATE' else 3]
                assert len(requests)==(2 if action=='CONTINUE' and case['name'].endswith('unknown') else 1)
                for request in requests:
                    assert request['status']==202 and request['key']==user['idempotency_key']
                    body=json.loads(request['body'])
                    if action=='CONTINUE' and formal:
                        assert body==answers and request['response']['data']['response_message']['id']==user['id'] and request['response']['data']['guide_run']['id']==run['id'] and request['response']['data']['card_state']=='ANSWERED'
                    elif action=='CONTINUE':assert body=={'instruction':user['content']}
                    else:assert body=={'expected_version':3,'action_type':'ASK','instruction':user['content'],'scope_type':'DOCUMENT','scope_ref':None,'source_type':'USER_INSTRUCTION','source_id':None}
                    receipt=db.execute('SELECT * FROM idempotency_records WHERE idempotency_key=?',(request['key'],)).fetchone()
                    assert receipt['status']=='SUCCEEDED' and receipt['http_status']==202 and json.loads(receipt['success_result_json'])['data']==request['response']['data']
            if case['name']=='ANSWERS-unknown':
                attempts=case['continuation']['recovery_attempts'];assert len(attempts)==2
                assert [item['attempt'] for item in attempts]==list(range(1,len(attempts)+1))
                assert attempts[-1]['read_failed'] is False
                first=attempts[0]['requests'];assert len(first)==1 and first[0]['method']=='GET' and first[0]['status']==200 and first[0]['delivered'] is False and first[0]['path']==f'/api/v1/requirements/{identity}'
                for item in attempts[:-1]:assert item['read_failed'] and not any(row['method']=='POST' for row in item['requests'])
                assert len([row for item in attempts for row in item['requests'] if row['method']=='POST'])==1
            audits=[dict(row) for row in db.execute('SELECT * FROM llm_uses WHERE guide_run_id=? ORDER BY call_no,attempt_no',(run['id'],))];assert len(audits)==2
            parsed=parse_markdown(current['markdown_content']);blocks={meta['block_id']:(block,meta) for block,meta in zip(parsed.blocks,current['block_state_json']['blocks'])}
            for number,usage in enumerate(audits):
                user=messages[1+number*2];assistant=messages[2+number*2]
                assert (usage['call_no'],usage['attempt_no'],usage['call_status'],usage['parse_status'],usage['validation_status'])==(number+1,1,'SUCCEEDED','SUCCEEDED','SUCCEEDED')
                assert (usage['model_name'],usage['model_version'],usage['function_type'],usage['prompt_config'])==('deepseek-v4-1-flash-260910','260910','ANSWER_REQUIREMENT','ANSWER_REQUIREMENT@v2')
                request=json.loads(usage['request_snapshot_json'])['request'];assert request['model']==usage['model_name'] and request['thinking']=={'type':'disabled'} and request['max_tokens']==8192
                assert [m['role'] for m in request['messages']]==['system','user'];context=json.loads(request['messages'][1]['content'])
                assert context['user_input']=={'message_id':user['id'],'content':user['content'],'formal_responses':None if user['structured_content_json'] is None else json.loads(user['structured_content_json'])}
                assert context['action_type']=='ASK' and context['scope']=={'scope_type':'DOCUMENT','scope_ref':None} and context['source_type']=='USER_INSTRUCTION' and context['source'] is None and context['allowed_targets']==[]
                assert context['current_document']['id']==current['id'] and context['current_document']['content_version']==3
                eligible=[m for m in messages if m['sequence_no']<=user['sequence_no'] and m['message_type'] in ('TEXT','CARD_RESPONSE')]
                read_ids={m['id'] for m in eligible}|{m['reply_to_message_id'] for m in eligible if m['message_type']=='CARD_RESPONSE'}
                manifest=context['read_manifest'];assert manifest==json.loads(usage['context_manifest_json']) and manifest['message_ids']==[m['id'] for m in messages if m['id'] in read_ids]
                assert context['history']==[{key:m[key] for key in ('id','sequence_no','role','message_type','content')}|{'formal_responses':None if m['structured_content_json'] is None else json.loads(m['structured_content_json'])} for m in eligible if m['sequence_no']<user['sequence_no']]
                if formal and number==1:assert messages[2]['id'] in manifest['message_ids'] and not any(m['message_type']=='INTERACTION_CARDS' for m in context['history']) and context['user_input']['formal_responses']==answers
                for item in context['current_document']['read_blocks']:
                    block,meta=blocks[item['metadata']['block_id']];assert item=={'markdown_content':block.markdown,'plain_text':block.plain_text,'heading_level':block.heading_level,'metadata':meta}
                trusted=json.loads(usage['trusted_output_json']);raw=json.loads(usage['raw_response_json']);assert json.loads(raw['choices'][0]['message']['content'])==trusted
                assert ResourceCatalog().freeze('ASK','USER_INSTRUCTION').parse_output(json.dumps(trusted,ensure_ascii=False))==trusted and assistant['content']==trusted['message']
                assert trusted['response_type']==(('CLARIFY_CARDS' if cards else 'CLARIFY_TEXT') if number==0 else 'ANSWER')
                if cards and number==0:
                    assert json.loads(assistant['structured_content_json'])==trusted['cards'] and assistant['content']==card_text(trusted['cards'])
                    for card in trusted['cards']['cards']:
                        for related in card['related_spec_context']:assert related['content_snapshot']==blocks[related['block_id']][0].markdown
            public=case['messages']['items'];assert [m['id'] for m in public]==[m['id'] for m in messages]
            for item,row in zip(public,messages):
                for field in ('id','requirement_id','guide_run_id','role','message_type','content','sequence_no','created_at'):assert item[field]==row[field]
            if cards:
                assert case['waiting_messages']['items'][2]['card_state']=='AVAILABLE' and public[2]['card_state']==('ANSWERED' if formal else 'EXPIRED')
                assert case['card_draft'] and not case['continuation']['card_storage']
            assert db.execute('SELECT count(*) FROM comments WHERE requirement_id=?',(identity,)).fetchone()[0]==0
            checked.append({'name':case['name'],'requirement_id':identity,'continued_run':run['id'],'calls':[1,2],'messages':5,'formal_response_id':messages[3]['id'] if formal else None,'card_state':('ANSWERED' if formal else 'EXPIRED') if cards else None,'passed':True})
    assert sha(database)==before
    return {'source_evidence':path.name,'source_inputs':len(report['inputs_after']),'native_counts':counts,'database_sha256':before,'database_bytes_unchanged':True,'cases':checked,'passed':True}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('evidence',type=Path);args=parser.parse_args()
    now=datetime.now(timezone.utc).isoformat();result={'recorded_at':now,'audit_source_sha256':sha(Path(__file__)),'scope':'Actual C07 card production/C06 formal answers and same-run second-call context; real raw canonical card content remains stored, original local draft retained and same Run audited; no paid/Provider proof'}
    try:result.update(passed=True,audit=audit(args.evidence))
    except Exception as error:result.update(passed=False,error=f'{type(error).__name__}: {error}')
    target=ROOT/'docs/verification'/('card-answers-root-post-audit-'+now.replace(':','-')+'.json')
    with target.open('x',encoding='utf-8') as file:json.dump(result,file,ensure_ascii=False,indent=2);file.write('\n')
    print(json.dumps({'passed':result['passed'],'evidence':str(target),'error':result.get('error')},ensure_ascii=False))
    if not result['passed']:raise SystemExit(1)
