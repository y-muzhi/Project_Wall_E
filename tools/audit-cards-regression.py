"""Closed real I36 regression facts; seeded card availability is only a precondition."""
import argparse,hashlib,json,sqlite3
from contextlib import closing
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def audit(path):
 r=json.loads(path.read_text(encoding='utf-8'));assert r['passed'] and r['inputs_before']==r['inputs_after'] and not r['changed_inputs'] and r['native']['code']==0
 assert '--seed-cards-fixture' in r['native']['args']
 for name,digest in r['inputs_after'].items():assert sha(ROOT/name)==digest,name
 database=Path(r['database']['path']);assert database.resolve().is_relative_to((ROOT/'output/playwright').resolve());before=sha(database);assert before==r['database']['sha256']
 with closing(sqlite3.connect(database.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
  db.row_factory=sqlite3.Row
  counts={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in r['native_facts']};assert counts==r['native_facts'] and counts['llm_uses']==0
  for key in ('initialization','waiting','expired'):
   case=r['cards'][key];assert case['passed'] and case['current_unchanged']
   for item in case['messages']:
    row=dict(db.execute('SELECT * FROM conversation_messages WHERE id=?',(item['id'],)).fetchone())
    for field in ('id','requirement_id','guide_run_id','sequence_no','role','content','message_type','reply_to_message_id','created_at'):assert row[field]==item[field]
    assert (None if row['structured_content_json'] is None else json.loads(row['structured_content_json']))==item['structured_content']
   formal=case['formal'];responses=db.execute("SELECT * FROM conversation_messages WHERE reply_to_message_id=? AND message_type='CARD_RESPONSE'",(case['message_id'],)).fetchall();assert len(responses)==(0 if formal is None else 1)
   if formal:
    assert responses[0]['id']==formal['id'] and responses[0]['guide_run_id']==formal['guide_run_id']
    run=db.execute('SELECT * FROM guide_runs WHERE id=?',(formal['guide_run_id'],)).fetchone();assert run['status']=='FAILED' and run['error_code']=='CONFIG_INVALID' and run['trigger_message_id']==formal['id']
    assert (formal['guide_run_id']!=case['source_id'])==(key=='initialization')
  for request in r['cards']['whole_group_wires']:
   if request['status']==202:
    receipt=db.execute('SELECT * FROM idempotency_records WHERE idempotency_key=?',(request['key'],)).fetchone();data=json.loads(receipt['success_result_json'])['data'];body=json.loads(request['body'])
    assert receipt['status']=='SUCCEEDED' and receipt['http_status']==202 and data['card_state']=='ANSWERED' and data['response_message']['structured_content']==body
    row=db.execute('SELECT * FROM conversation_messages WHERE id=?',(data['response_message']['id'],)).fetchone();assert row['idempotency_key']==request['key'] and json.loads(row['structured_content_json'])==body
   else:assert request['status']==409
 assert sha(database)==before
 return {'passed':True,'source_evidence':path.name,'source_inputs':len(r['inputs_after']),'native_counts':counts,'database_sha256':before,'database_bytes_unchanged':True,'scope':'I36 formal uniqueness/receipts, public messages and later CONFIG_INVALID run preserve answers; fixture card availability is not C07/Provider proof'}
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('evidence',type=Path);args=parser.parse_args();now=datetime.now(timezone.utc).isoformat();r={'recorded_at':now,'audit_source_sha256':sha(Path(__file__))}
 try:r.update(passed=True,audit=audit(args.evidence))
 except Exception as e:r.update(passed=False,error=f'{type(e).__name__}: {e}')
 p=ROOT/'docs/verification'/('cards-regression-post-audit-'+now.replace(':','-')+'.json');p.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'passed':r['passed'],'evidence':str(p),'error':r.get('error')},ensure_ascii=False))
 if not r['passed']:raise SystemExit(1)
