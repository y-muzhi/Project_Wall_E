"""Private actual files, fsync/fence/retention failures; no database DDL changes."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import asyncio
import pytest
import hashlib
import json
from threading import Event
import unittest
from unittest.mock import patch

from backend.app.infrastructure.counting_journal import CountingJournal
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.execution_lease import ExecutionLease, LeasedDatabase, ExecutionRetired
from backend.app.infrastructure.model_profile import ModelProfile, DEFAULT_PROFILE, DEEPSEEK_MODEL_ID as MODEL_ID
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.infrastructure.schema_transport import compact
from backend.app.infrastructure.tokenization import TokenCounts, restore_measurement, measurement_summary
from backend.tests.requirements.test_v15_foundation import tmp_path, setup, counts
from backend.tests.documents.test_v15_documents import workspace
from backend.tests.guide.test_v15_acceptance import accept
from backend.tests.guide.test_v15_context import compiled
from backend.tests.guide.test_v15_counting import inputs, Counter, offline_gate
from backend.app.guide.collaboration_context import compile_context
from backend.app.guide.collaboration_counting import compile_counted, verify_counted
from backend.tests.infrastructure import test_tokenization as tcp

AT='2026-10-24T08:00:10.000Z'


def receipt(texts, counts=None):
    counts=[2]*len(texts) if counts is None else counts
    raw=tcp.envelope();raw['model']=MODEL_ID;raw['data']=[{'object':'tokenization','index':index,'total_tokens':count,
        'token_ids':[10]*count,'offset_mapping':[[0,0]]*count} for index,count in enumerate(counts)]
    return TokenCounts(MODEL_ID,raw['id'],raw['created'],tuple(counts),tuple(hashlib.sha256(text.encode()).hexdigest() for text in texts),
        hashlib.sha256(compact({'model':MODEL_ID,'text':list(texts)}).encode()).hexdigest(),compact(raw))


class CountingJournalTests(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def current_workspace(self, workspace):
        self.workspace=workspace

    def setUp(self):
        db,executor,catalog=self.workspace
        assert accept(self.workspace)['code']=='GUIDE_ACCEPTED'
        self.h=SimpleNamespace(database=db,lock=executor.process_lock,facts=lambda:counts(db))
        self.catalog=catalog;self.context=compiled(self.workspace)
        self.actual={'read_manifest':json.loads(self.context.manifest_json)}
        self.profile=ModelProfile('journal-offline-key',DEFAULT_PROFILE);self.texts=self.context.texts
        self.journal=CountingJournal(db,self.h.lock)

    def prepare(self):return self.journal.prepare_collaboration(1,self.context,self.profile,AT,self.catalog.collaboration)

    def load(self,identity,phase):return json.loads(self.journal._file(identity,phase).read_bytes())

    def test_actual_request_and_observed_outcome_do_not_create_chat_attempt_or_mutate_database(self):
        before=self.h.facts();identity=self.prepare();prepared=self.load(identity,'prepared')
        self.assertEqual(prepared['phase'],'PREPARED');self.assertEqual(prepared['request'],{'model':MODEL_ID,'text':list(self.texts)})
        self.assertEqual(prepared['read_manifest'],self.actual['read_manifest']);self.assertEqual(prepared['owner_epoch'],self.h.lock.owner_epoch)
        self.journal.finish(identity,self.profile,AT,status='SUCCEEDED',measurement=receipt(self.texts).evidence)
        self.assertEqual(self.load(identity,'finished')['measurement'],receipt(self.texts).evidence)
        self.assertEqual(self.h.facts(),before)
        for file in self.journal.root.iterdir():self.assertNotIn(self.profile.api_key,file.read_text(encoding='utf-8'))

    def test_capacity_rejects_before_file_and_credentials_in_private_text_are_redacted(self):
        with patch('backend.app.infrastructure.audit_data.MAX_AUDIT_BYTES',10),self.assertRaises(ValueError):self.prepare()
        self.assertFalse(self.journal.root.exists())
        echo=replace(self.context,input_json=self.context.input_json.replace('用户原话',self.profile.api_key))
        self.assertIn(self.profile.api_key,echo.input_json)
        identity=self.journal.prepare_collaboration(1,echo,self.profile,AT,self.catalog.collaboration)
        self.assertNotIn(self.profile.api_key,self.journal._file(identity,'prepared').read_text(encoding='utf-8'))

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
        with self.assertRaises(RuntimeError):CountingJournal(self.h.database,wrong).prepare_collaboration(1,self.context,self.profile,AT,self.catalog.collaboration)
        for identity in ('../'+'a'*32,'A'*32,'a'*31,True):
            with self.subTest(identity=identity),self.assertRaises(ValueError):self.journal._file(identity,'prepared')
        self.assertFalse(self.journal.root.exists())

    def test_lease_retirement_wins_before_write_no_late_record_or_directory(self):
        lease=ExecutionLease();journal=CountingJournal(LeasedDatabase(self.h.database,lease),self.h.lock);lease.retire()
        with self.assertRaises(ExecutionRetired):journal.prepare_collaboration(1,self.context,self.profile,AT,self.catalog.collaboration)
        self.assertFalse(self.journal.root.exists())

    def test_fsync_in_progress_finishes_before_retirement_then_later_write_is_fenced(self):
        lease=ExecutionLease();journal=CountingJournal(LeasedDatabase(self.h.database,lease),self.h.lock)
        entered,release,retired,requested=Event(),Event(),Event(),Event()
        import os
        original=os.fsync
        def hold(fd):entered.set();self.assertTrue(release.wait(3));original(fd)
        def retire():requested.set();lease.retire();retired.set()
        with ThreadPoolExecutor(max_workers=2) as threads,patch('backend.app.infrastructure.counting_journal.os.fsync',side_effect=hold):
            prepared=threads.submit(journal.prepare_collaboration,1,self.context,self.profile,AT,self.catalog.collaboration)
            self.assertTrue(entered.wait(3));ending=threads.submit(retire)
            self.assertTrue(requested.wait(3));self.assertFalse(retired.wait(0.05));release.set();identity=prepared.result(3);ending.result(3)
        self.assertTrue(retired.is_set());self.assertEqual(self.load(identity,'prepared')['phase'],'PREPARED')
        with self.assertRaises(ExecutionRetired):journal.finish(identity,self.profile,AT,status='INTERRUPTED')
        self.assertFalse(journal._file(identity,'finished').exists())

    def test_30_day_raw_retention_preserves_counts_request_identity_and_exact_boundary(self):
        old=self.prepare();self.journal.finish(old,self.profile,AT,status='SUCCEEDED',measurement=receipt(self.texts).evidence)
        boundary=self.prepare();self.journal.finish(boundary,self.profile,'2026-10-25T08:00:10.000Z',status='SUCCEEDED',measurement=receipt(self.texts).evidence)
        unknown=self.prepare();failed=self.prepare();self.journal.finish(failed,self.profile,AT,status='FAILED')
        before=self.journal._file(old,'prepared').read_bytes();outcome=self.load(old,'finished')
        self.assertEqual(self.journal.prune_raw('2026-11-24T08:00:10.000Z'),1)
        result=self.load(old,'finished');self.assertNotIn('response',result['measurement']);self.assertEqual(result['measurement'],measurement_summary(outcome['measurement']))
        self.assertEqual((result['at'],result['phase']),(AT,'SUCCEEDED'));self.assertEqual(self.journal._file(old,'prepared').read_bytes(),before)
        self.assertIn('response',self.load(boundary,'finished')['measurement']);self.assertFalse(self.journal._file(unknown,'finished').exists())
        self.assertEqual(self.load(failed,'finished')['phase'],'FAILED');self.assertEqual(self.journal.prune_raw('2026-11-24T08:00:10.000Z'),0)

    def test_prune_failure_keeps_original_raw_record_and_unknown_files(self):
        identity=self.prepare();self.journal.finish(identity,self.profile,AT,status='SUCCEEDED',measurement=receipt(self.texts).evidence)
        before=self.journal._file(identity,'finished').read_bytes();extra=self.journal.root/'unknown.txt';extra.write_text('kept')
        with patch('backend.app.infrastructure.counting_journal.os.replace',side_effect=OSError('controlled replace failure')),self.assertRaises(StorageUnavailable):self.journal.prune_raw('2026-11-25T08:00:10.000Z')
        self.assertEqual(self.journal._file(identity,'finished').read_bytes(),before);self.assertEqual(extra.read_text(),'kept')

    def test_full_and_summary_count_ownership_types_and_response_consistency(self):
        value=receipt(self.texts).evidence;self.assertEqual(restore_measurement(value,self.texts,expected_model=MODEL_ID).counts,(2,)*len(self.texts))
        summary=measurement_summary(value);self.assertEqual(restore_measurement(summary,self.texts,raw_required=False,expected_model=MODEL_ID).counts,(2,)*len(self.texts))
        variants=[]
        for changes in ({'created':True},{'model':'other'},{'counts':[True]*len(self.texts)},{'request_sha256':'0'*64},{'journal_id':'../bad'},{'extra':1}):variants.append({**deepcopy(value),**changes})
        bad=deepcopy(value);bad['response']['data'][0]['total_tokens']=3;variants.append(bad)
        for bad in variants:
            with self.subTest(keys=list(bad)),self.assertRaises(ConfigInvalid):restore_measurement(bad,self.texts,expected_model=MODEL_ID)
        with self.assertRaises(ConfigInvalid):restore_measurement(summary,self.texts,expected_model=MODEL_ID)

    def test_missing_preparation_or_new_process_cannot_fabricate_old_outcome(self):
        with self.assertRaises(StorageUnavailable):self.journal.finish('a'*32,self.profile,AT,status='FAILED')
        identity=self.prepare();self.h.lock.release();self.h.lock.acquire()
        with self.assertRaises(StorageUnavailable):self.journal.finish(identity,self.profile,AT,status='SUCCEEDED',measurement=receipt(self.texts).evidence)
        self.assertFalse(self.journal._file(identity,'finished').exists())

    def test_partial_preparation_remains_unknown_and_never_gets_fabricated_success(self):
        identity=self.prepare();self.journal._file(identity,'prepared').write_bytes(b'{')
        with self.assertRaises(StorageUnavailable):self.journal.finish(identity,self.profile,AT,status='SUCCEEDED',measurement=receipt(self.texts).evidence)
        self.assertFalse(self.journal._file(identity,'finished').exists());self.assertEqual(self.journal.prune_raw('2026-11-25T08:00:10.000Z'),0)

    def test_private_http_failure_details_are_redacted_and_message_expires_at_the_same_30_day_boundary(self):
        details={'body_state':'JSON_ERROR','category':'PARAMETER','code':'InvalidParameter','parameter':'text',
            'message':'provider input limit; echoed '+self.profile.api_key,'message_truncated':False,'request_id':'local-error-id'}
        old=self.prepare();boundary=self.prepare()
        for identity,at in ((old,AT),(boundary,'2026-10-25T08:00:10.000Z')):
            self.journal.finish(identity,self.profile,at,status='FAILED',failure_reason='HTTP_STATUS',http_status=400,provider_error=details)
            self.assertNotIn(self.profile.api_key,self.journal._file(identity,'finished').read_text(encoding='utf-8'))
        with self.assertRaises(ValueError):self.journal.finish(self.prepare(),self.profile,AT,status='SUCCEEDED',
            measurement=receipt(self.texts).evidence,provider_error=details)
        self.assertEqual(self.journal.prune_raw('2026-11-24T08:00:10.000Z'),1)
        value=self.load(old,'finished');self.assertIsNone(value['provider_error']['message'])
        self.assertEqual(value['provider_error']['code'],'InvalidParameter');self.assertEqual(value['http_status'],400)
        self.assertEqual(value['phase'],'FAILED');self.assertIn('provider_message_pruned_at',value)
        self.assertIsNotNone(self.load(boundary,'finished')['provider_error']['message'])
        self.assertEqual(self.journal.prune_raw('2026-11-24T08:00:10.000Z'),0)


def test_actual_trimmed_candidates_replay_and_out_of_order_cuts_reject(workspace,monkeypatch):
    offline_gate(monkeypatch);canonical=inputs(workspace,history=True,neighbors=True)
    catalog=workspace[2];profile=ModelProfile('trim-audit-offline-key',DEFAULT_PROFILE)
    journal=CountingJournal(workspace[0],workspace[1].process_lock)
    delegate=Counter(['HIGH','HIGH','OK']);records=[]
    class AuditedCounter:
        async def count(self,profile,texts):
            context=next(value for flags in ((False,False),(True,False),(True,True))
                if (value:=compile_context(canonical,catalog,omit_history=flags[0],omit_background=flags[1])).texts==texts)
            identity=journal.prepare_collaboration(1,context,profile,AT,catalog.collaboration)
            measured=replace(await delegate.count(profile,texts),journal_id=identity)
            journal.finish(identity,profile,AT,status='SUCCEEDED',measurement=measured.evidence)
            records.append(identity);return measured
    counted=asyncio.run(compile_counted(canonical,catalog,profile,counter=AuditedCounter()))
    assert len(records)==len(delegate.calls)==3
    assert [len(json.loads(texts[1])['recent_history']) for texts in delegate.calls]==[2,0,0]
    assert [len(json.loads(texts[1])['documents'][0]['blocks']) for texts in delegate.calls]==[5,5,1]
    evidence=verify_counted(counted,catalog,profile)
    assert [row['measurement']['journal_id'] for row in evidence['count_attempts']]==records
    for identity in records:
        assert json.loads(journal._file(identity,'finished').read_bytes())['phase']=='SUCCEEDED'
    changed=deepcopy(evidence);changed['count_attempts'][0],changed['count_attempts'][1]=changed['count_attempts'][1],changed['count_attempts'][0]
    with pytest.raises(ConfigInvalid):verify_counted(replace(counted,counting_json=json.dumps(changed)),catalog,profile)
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0]==0
