"""D-010 immutable releases and actual SQLite acceptance, no model effects.

Historical card/waiting rows are labelled fixtures. All accepted transitions
and C03 reads here use actual commands and an on-disk database.
"""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from backend.app.guide.queries import get_model_context
from backend.app.infrastructure.resources import (ResourceCatalog, ConfigInvalid,
    ProtocolInvalid, DEFAULT_ROOT, V2_ROOT, V2_MANIFEST_SHA256)
from backend.tests.infrastructure.test_resources import EXPECTED, output
from backend.tests.requirements import test_create_requirement as creation
from backend.tests.guide import test_acceptance as acceptance
from backend.tests.guide import test_cards as cards
from backend.tests.guide import test_retry as retries


class VersionedResourceTests(unittest.TestCase):
    def test_all_new_freezes_v2_both_versions_restore_exactly_no_fallback(self):
        catalog=ResourceCatalog();old=ResourceCatalog(DEFAULT_ROOT)
        for name,action,source,key in EXPECTED:
            with self.subTest(function=name):
                latest=catalog.freeze(action,source)
                self.assertEqual((latest.function_type,latest.version,latest.prompt_reference,latest.context_template,latest.manifest_sha256),
                    (name,'v2',name+'@v2',key+'_CONTEXT@v2',V2_MANIFEST_SHA256))
                self.assertEqual(catalog.restore(name,'v1'),old.freeze(action,source))
                self.assertEqual(catalog.restore(name,'v2',prompt_version='v2',context_template=key+'_CONTEXT@v2'),latest)
                for version in ('v3','latest',None):
                    with self.assertRaises(ConfigInvalid):catalog.restore(name,version)
                with self.assertRaises(ConfigInvalid):catalog.restore(name,'v1',prompt_version='v2')
                with self.assertRaises(ConfigInvalid):catalog.restore(name,'v2',context_template=key+'_CONTEXT@v1')

    def test_schema_template_signature_and_budget_preserved_all_six(self):
        catalog=ResourceCatalog();old=ResourceCatalog(DEFAULT_ROOT)
        self.assertEqual(catalog.frontend_catalog,old.frontend_catalog)
        for kind,key in (('NEW','new-requirement'),('CHANGE','change-requirement')):
            self.assertEqual(catalog.template(kind,key,'v1'),old.template(kind,key,'v1'))
        for _,action,source,_ in EXPECTED:
            latest=catalog.freeze(action,source);prior=old.freeze(action,source)
            self.assertEqual((latest.input_schema_json,latest.output_schema_json),(prior.input_schema_json,prior.output_schema_json))
            self.assertEqual(latest.context_policy,{**prior.context_policy,'prompt':latest.prompt_reference})
            detached=latest.context_policy;detached['budget']['input_tokens']=1
            self.assertEqual(latest.context_policy['budget']['input_tokens'],24576)
        valid=output('ANSWER');function=catalog.freeze('ASK','USER_INSTRUCTION')
        self.assertEqual(function.parse_output(json.dumps(valid)),valid)
        with self.assertRaises(ProtocolInvalid):function.parse_output(json.dumps({**valid,'reasoning':'not allowed'}))

    def test_proposed_candidate_and_missing_versioned_release_are_not_activated(self):
        proposed=Path(__file__).resolve().parents[3]/'docs/proposals/resources-v2'
        with self.assertRaises(ConfigInvalid):ResourceCatalog(versioned_root=proposed)
        with tempfile.TemporaryDirectory(prefix='walle-v2-missing-') as directory:
            with self.assertRaises(ConfigInvalid):ResourceCatalog(versioned_root=Path(directory)/'absent')

    def test_tamper_missing_file_and_manifest_refuse_without_v1_fallback(self):
        with tempfile.TemporaryDirectory(prefix='walle-v2-frozen-') as directory:
            target=Path(directory)/'v2';shutil.copytree(V2_ROOT,target)
            self.assertEqual(ResourceCatalog(versioned_root=target).freeze('ASK','USER_INSTRUCTION').version,'v2')
            prompt=target/'prompts/ANSWER_REQUIREMENT.v2.md';original=prompt.read_bytes()
            for content in (original+b'changed',None):
                if content is None:prompt.unlink()
                else:prompt.write_bytes(content)
                with self.assertRaises(ConfigInvalid):ResourceCatalog(versioned_root=target)
                prompt.write_bytes(original)
            (target/'manifest.json').write_bytes(b'{}')
            with self.assertRaises(ConfigInvalid):ResourceCatalog(versioned_root=target)

    def test_current_release_requires_intact_legacy_resources_for_old_runs(self):
        with tempfile.TemporaryDirectory(prefix='walle-v1-missing-') as directory:
            target=Path(directory)/'v1';shutil.copytree(DEFAULT_ROOT,target)
            (target/'prompts/ANSWER_REQUIREMENT.v1.md').unlink()
            with self.assertRaises(ConfigInvalid):ResourceCatalog(target,versioned_root=V2_ROOT)


class VersionedAcceptanceTests(unittest.TestCase):
    def fixture(self,cls):
        fixture=cls();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.catalog=ResourceCatalog()
        return fixture

    def test_actual_new_creation_freezes_v2_and_real_c03_matches_no_provider(self):
        fixture=self.fixture(creation.CreateRequirementTests)
        result=fixture.create();self.assertEqual(result['code'],'CREATED',result)
        identity=result['data']['guide_run_id'];current=result['data']['current_document_id']
        before=fixture.facts();data=get_model_context(fixture.database,identity,catalog=fixture.catalog)['data']
        self.assertEqual(data['run']['prompt_version'],'v2')
        self.assertEqual(data['run']['context_template_version'],'v2')
        self.assertEqual(data['read_manifest']['prompt']['version'],'v2')
        self.assertEqual(data['read_manifest']['context_template']['version'],'v2')
        self.assertEqual(data['current_document']['id'],current)
        self.assertEqual(fixture.facts(),before)
        self.assertEqual(fixture.create(),result)  # actual persisted idempotent replay

    def test_actual_old_waiting_continuation_preserves_v1_and_c03(self):
        fixture=acceptance.AcceptanceTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        identity=fixture.waiting();old=fixture.row('guide_runs',identity)
        fixture.catalog=ResourceCatalog()
        result=fixture.resume();self.assertEqual(result['code'],'GUIDE_CONTINUED',result)
        current=fixture.row('guide_runs',identity)
        for field in ('function_type','prompt_version','context_template_key','context_template_version'):
            self.assertEqual(current[field],old[field])
        self.assertEqual(current['prompt_version'],'v1')
        data=get_model_context(fixture.database,identity,catalog=fixture.catalog)['data']
        self.assertEqual(data['read_manifest']['prompt']['version'],'v1')
        self.assertEqual(fixture.catalog.freeze('ASK','USER_INSTRUCTION').version,'v2')

    def test_actual_retry_uses_new_v2_keeps_failed_v1_and_existing_user(self):
        fixture=self.fixture(retries.RetryTests);old=fixture.row('guide_runs',fixture.failed)
        message=fixture.row('conversation_messages',old['trigger_message_id'])
        result=fixture.retry();self.assertEqual(result['code'],'GUIDE_RETRY_ACCEPTED',result)
        new=fixture.row('guide_runs',result['data']['id'])
        self.assertEqual((new['prompt_version'],new['context_template_version']),('v2','v2'))
        self.assertEqual(fixture.row('guide_runs',fixture.failed),old)
        self.assertEqual(old['prompt_version'],'v1')
        self.assertEqual(fixture.row('conversation_messages',message['id']),message)
        self.assertEqual(get_model_context(fixture.database,new['id'],catalog=fixture.catalog)['code'],'READ_OK')

    def test_actual_formal_response_to_immutable_old_initialize_card_creates_v2_run(self):
        fixture=cards.CardSubmissionTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.initialize_cards_fixture();old=fixture.row('conversation_messages',11)
        fixture.catalog=ResourceCatalog()
        result=fixture.submit();self.assertEqual(result['code'],'CARDS_ACCEPTED',result)
        identity=result['data']['guide_run']['id'];new=fixture.row('guide_runs',identity)
        self.assertEqual((new['prompt_version'],new['context_template_version']),('v2','v2'))
        self.assertEqual(fixture.row('conversation_messages',11),old)
        data=get_model_context(fixture.database,identity,catalog=fixture.catalog)['data']
        self.assertIn(old['id'],data['read_manifest']['message_ids'])
        self.assertIsNotNone(data['user_input']['structured_content'])
