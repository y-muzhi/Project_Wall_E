"""Private actual files, fsync/fence/retention failures; no database DDL changes."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from threading import Event
import unittest
from unittest.mock import patch

from backend.app.guide.context_builder import assemble_input
from backend.app.guide.counted_context import verify_counting_evidence
from backend.app.infrastructure.counting_journal import CountingJournal
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.execution_lease import ExecutionLease, LeasedDatabase, ExecutionRetired
from backend.app.infrastructure.model_profile import ModelProfile, MODEL_ID
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.infrastructure.schema_transport import compact, function_schema
from backend.app.infrastructure.tokenization import TokenCounts, restore_measurement, measurement_summary
from backend.tests.guide import test_model_context as contexts
from backend.tests.infrastructure import test_tokenization as tcp

AT='2026-10-04T08:00:10.000Z'


def receipt(texts, counts=None):
    counts=[2]*len(texts) if counts is None else counts
    raw=tcp.envelope();raw['data']=[{'object':'tokenization','index':index,'total_tokens':count,
        'token_ids':[10]*count,'offset_mapping':[[0,0]]*count} for index,count in enumerate(counts)]
    return TokenCounts(MODEL_ID,raw['id'],raw['created'],tuple(counts),tuple(hashlib.sha256(text.encode()).hexdigest() for text in texts),
        hashlib.sha256(compact({'model':MODEL_ID,'text':list(texts)}).encode()).hexdigest(),compact(raw))


class CountingJournalTests(unittest.TestCase):
    def setUp(self):
        self.h=contexts.ModelContextTests();self.h.setUp();self.addCleanup(lambda:self.assertTrue(self.h.doCleanups()))
        self.actual=self.h.read()['data'];self.function=self.h.catalog.freeze('INITIALIZE','USER_INSTRUCTION')
        self.profile=ModelProfile('journal-offline-key');value=assemble_input(self.actual,self.function)
        self.texts=(self.function.prompt+'\n'+function_schema(self.function).schema_json,compact({key:value[key] for key in self.function.context_policy['field_order']}),*(compact(value[key]) for key in ('user_input','source','template','history')))
        self.journal=CountingJournal(self.h.database,self.h.lock)

    def prepare(self):return self.journal.prepare(self.actual,self.function,self.profile,self.texts,AT)

    def load(self,identity,phase):return json.loads(self.journal._file(identity,phase).read_bytes())

    def test_actual_request_and_observed_outcome_do_not_create_chat_attempt_or_mutate_database(self):
        before=self.h.facts();identity=self.prepare();prepared=self.load(identity,'prepared')
        self.assertEqual(prepared['phase'],'PREPARED');self.assertEqual(prepared['request'],{'model':MODEL_ID,'text':list(self.texts)})
        self.assertEqual(prepared['read_manifest'],self.actual['read_manifest']);self.assertEqual(prepared['owner_epoch'],self.h.lock.owner_epoch)
        self.journal.finish(identity,self.profile,AT,status='SUCCEEDED',measurement=receipt(self.texts).evidence)
        self.assertEqual(self.load(identity,'finished')['measurement'],receipt(self.texts).evidence)
        self.assertEqual(self.h.facts(),before)
        for file in self.journal.root.iterdir():self.assertNotIn(self.profile.api_key,file.read_text())

    def test_capacity_rejects_before_file_and_credentials_in_private_text_are_redacted(self):
        with patch('backend.app.infrastructure.audit_data.MAX_AUDIT_BYTES',10),self.assertRaises(ValueError):self.prepare()
        self.assertFalse(self.journal.root.exists())
        identity=self.journal.prepare(self.actual,self.function,self.profile,(*self.texts,self.profile.api_key),AT)
        self.assertNotIn(self.profile.api_key,self.journal._file(identity,'prepared').read_text())

    def test_repeated_finish_cannot_overwrite_observed_success(self):
        identity=self.prepare();self.journal.finish(identity,self.profile,AT,status='SUCCEEDED',measurement=receipt(self.texts).evidence)
        before=self.journal._file(identity,'finished').read_bytes()
        with self.assertRaises(StorageUnavailable):self.journal.finish(identity,self.profile,AT,status='FAILED')
        self.assertEqual(self.journal._file(identity,'finished').read_bytes(),before)

    def test_fsync_failure_records_no_success_and_does_not_retry(self):
        with patch('backend.app.infrastructure.counting_journal.os.fsync',side_effect=OSError('controlled disk failure')) as write:
            with self.assertRaises(StorageUnavailable):self.prepare()
        self.assertEqual(write.call_count,1);self.assertEqual(list(self.journal.root.glob('*.finished.json')),[])

    def test_wrong_lock_or_escaping_record_identity_refuses_before_effects(self):
        wrong=ProcessLock.for_database(self.h.database.path.with_name('other.sqlite')).acquire();self.addCleanup(wrong.release)
        with self.assertRaises(RuntimeError):CountingJournal(self.h.database,wrong).prepare(self.actual,self.function,self.profile,self.texts,AT)
        for identity in ('../'+'a'*32,'A'*32,'a'*31,True):
            with self.subTest(identity=identity),self.assertRaises(ValueError):self.journal._file(identity,'prepared')
        self.assertFalse(self.journal.root.exists())

    def test_lease_retirement_wins_before_write_no_late_record_or_directory(self):
        lease=ExecutionLease();journal=CountingJournal(LeasedDatabase(self.h.database,lease),self.h.lock);lease.retire()
        with self.assertRaises(ExecutionRetired):journal.prepare(self.actual,self.function,self.profile,self.texts,AT)
        self.assertFalse(self.journal.root.exists())

    def test_fsync_in_progress_finishes_before_retirement_then_later_write_is_fenced(self):
        lease=ExecutionLease();journal=CountingJournal(LeasedDatabase(self.h.database,lease),self.h.lock)
        entered,release,retired,requested=Event(),Event(),Event(),Event()
        import os
        original=os.fsync
        def hold(fd):entered.set();self.assertTrue(release.wait(3));original(fd)
        def retire():requested.set();lease.retire();retired.set()
        with ThreadPoolExecutor(max_workers=2) as threads,patch('backend.app.infrastructure.counting_journal.os.fsync',side_effect=hold):
            prepared=threads.submit(journal.prepare,self.actual,self.function,self.profile,self.texts,AT)
            self.assertTrue(entered.wait(3));ending=threads.submit(retire)
            self.assertTrue(requested.wait(3));self.assertFalse(retired.wait(0.05));release.set();identity=prepared.result(3);ending.result(3)
        self.assertTrue(retired.is_set());self.assertEqual(self.load(identity,'prepared')['phase'],'PREPARED')
        with self.assertRaises(ExecutionRetired):journal.finish(identity,self.profile,AT,status='INTERRUPTED')
        self.assertFalse(journal._file(identity,'finished').exists())

    def test_30_day_raw_retention_preserves_counts_request_identity_and_exact_boundary(self):
        old=self.prepare();self.journal.finish(old,self.profile,AT,status='SUCCEEDED',measurement=receipt(self.texts).evidence)
        boundary=self.prepare();self.journal.finish(boundary,self.profile,'2026-10-05T08:00:10.000Z',status='SUCCEEDED',measurement=receipt(self.texts).evidence)
        unknown=self.prepare();failed=self.prepare();self.journal.finish(failed,self.profile,AT,status='FAILED')
        before=self.journal._file(old,'prepared').read_bytes();outcome=self.load(old,'finished')
        self.assertEqual(self.journal.prune_raw('2026-11-04T08:00:10.000Z'),1)
        result=self.load(old,'finished');self.assertNotIn('response',result['measurement']);self.assertEqual(result['measurement'],measurement_summary(outcome['measurement']))
        self.assertEqual((result['at'],result['phase']),(AT,'SUCCEEDED'));self.assertEqual(self.journal._file(old,'prepared').read_bytes(),before)
        self.assertIn('response',self.load(boundary,'finished')['measurement']);self.assertFalse(self.journal._file(unknown,'finished').exists())
        self.assertEqual(self.load(failed,'finished')['phase'],'FAILED');self.assertEqual(self.journal.prune_raw('2026-11-04T08:00:10.000Z'),0)

    def test_prune_failure_keeps_original_raw_record_and_unknown_files(self):
        identity=self.prepare();self.journal.finish(identity,self.profile,AT,status='SUCCEEDED',measurement=receipt(self.texts).evidence)
        before=self.journal._file(identity,'finished').read_bytes();extra=self.journal.root/'unknown.txt';extra.write_text('kept')
        with patch('backend.app.infrastructure.counting_journal.os.replace',side_effect=OSError('controlled replace failure')),self.assertRaises(StorageUnavailable):self.journal.prune_raw('2026-11-05T08:00:10.000Z')
        self.assertEqual(self.journal._file(identity,'finished').read_bytes(),before);self.assertEqual(extra.read_text(),'kept')

    def test_full_and_summary_count_ownership_types_and_response_consistency(self):
        value=receipt(self.texts).evidence;self.assertEqual(restore_measurement(value,self.texts).counts,(2,)*6)
        summary=measurement_summary(value);self.assertEqual(restore_measurement(summary,self.texts,raw_required=False).counts,(2,)*6)
        variants=[]
        for changes in ({'created':True},{'model':'other'},{'counts':[True]*6},{'request_sha256':'0'*64},{'journal_id':'../bad'},{'extra':1}):variants.append({**deepcopy(value),**changes})
        bad=deepcopy(value);bad['response']['data'][0]['total_tokens']=3;variants.append(bad)
        for bad in variants:
            with self.subTest(keys=list(bad)),self.assertRaises(ConfigInvalid):restore_measurement(bad,self.texts)
        with self.assertRaises(ConfigInvalid):restore_measurement(summary,self.texts)

    def test_missing_preparation_or_new_process_cannot_fabricate_old_outcome(self):
        with self.assertRaises(StorageUnavailable):self.journal.finish('a'*32,self.profile,AT,status='FAILED')
        identity=self.prepare();self.h.lock.release();self.h.lock.acquire()
        with self.assertRaises(StorageUnavailable):self.journal.finish(identity,self.profile,AT,status='SUCCEEDED',measurement=receipt(self.texts).evidence)
        self.assertFalse(self.journal._file(identity,'finished').exists())

    def test_partial_preparation_remains_unknown_and_never_gets_fabricated_success(self):
        identity=self.prepare();self.journal._file(identity,'prepared').write_bytes(b'{')
        with self.assertRaises(StorageUnavailable):self.journal.finish(identity,self.profile,AT,status='SUCCEEDED',measurement=receipt(self.texts).evidence)
        self.assertFalse(self.journal._file(identity,'finished').exists());self.assertEqual(self.journal.prune_raw('2026-11-05T08:00:10.000Z'),0)


class CountedTrimAuditTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.h=contexts.ModelContextTests();self.h.setUp();self.addCleanup(lambda:self.assertTrue(self.h.doCleanups()))

    async def test_actual_trimmed_candidates_replay_and_out_of_order_cuts_reject(self):
        from backend.app.guide.counted_context import compile_counted_candidate,counting_snapshot
        from backend.app.infrastructure.message_repository import MessageRepository
        from backend.app.infrastructure.audit_repository import AuditRepository
        h=self.h;h.activate()
        with h.database.transaction(write=True) as connection:
            for index in range(2):MessageRepository(connection).create_user_text(100+index,h.req,h.run,'history'+str(index),f'00000000-0000-4000-8000-{100+index:012d}',h.at)
        identity=h.accept('MODIFY');actual=h.read(identity)['data'];function=h.catalog.freeze('MODIFY','USER_INSTRUCTION');initial=assemble_input(actual,function)
        required=set(actual['scope']['required_read_block_ids'])|{item['block_id'] for item in initial['allowed_targets']}
        optional=[item['metadata']['block_id'] for item in initial['current_document']['read_blocks'] if item['metadata']['block_id'] not in required];self.assertGreater(len(optional),1)
        class Counter:
            async def count(self,profile,texts):
                value=json.loads(texts[1]);trimmed=len(initial['current_document']['read_blocks'])-len(value['current_document']['read_blocks'])
                counts=[1000,24000 if value['history'] or trimmed<2 else 22000,100,10,100,2049 if value['history'] else 10]
                return receipt(texts,counts)
        profile=ModelProfile('trim-audit-offline-key');candidate=await compile_counted_candidate(actual,function,profile,counter=Counter())
        self.assertEqual(candidate.removed_neighbor_ids,tuple(optional[:2]));self.assertEqual(len(candidate.removed_history_ids),len(actual['history']))
        verify_counting_evidence(actual,function,system=candidate.system,input_json=candidate.input_json,manifest_json=candidate.manifest_json,evidence=candidate.counting_evidence)
        summary=counting_snapshot(candidate.counting_evidence)
        verify_counting_evidence(actual,function,system=candidate.system,input_json=candidate.input_json,manifest_json=candidate.manifest_json,evidence=summary,summary=True)
        changed=deepcopy(summary);changed['count_attempts'][-1]['removed_neighbor_ids'].reverse()
        with self.assertRaises(ConfigInvalid):verify_counting_evidence(actual,function,system=candidate.system,input_json=candidate.input_json,manifest_json=candidate.manifest_json,evidence=changed,summary=True)
        with h.database.transaction(write=True) as connection:row=AuditRepository(connection).prepare(identity,function,profile,candidate,AT,catalog=h.catalog)
        self.assertEqual(row['attempt_no'],1)
