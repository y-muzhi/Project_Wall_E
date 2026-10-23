"""D-010 immutable releases and actual SQLite acceptance, no model effects.

Historical resource bytes remain protected. V1.5 deliberately excludes old
waiting/card migration; acceptance now checks fresh-data isolation instead.
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


def historical_catalog():
    """D-010 fixtures explicitly deploy v1/v2; new defaults are tested separately."""
    return ResourceCatalog(DEFAULT_ROOT, versioned_root=V2_ROOT)


class VersionedResourceTests(unittest.TestCase):
    def test_all_new_freezes_v2_both_versions_restore_exactly_no_fallback(self):
        catalog=historical_catalog();old=ResourceCatalog(DEFAULT_ROOT)
        for name,action,source,key in EXPECTED:
            with self.subTest(function=name):
                latest=catalog.freeze(action,source)
                self.assertEqual((latest.function_type,latest.version,latest.prompt_reference,latest.context_template,latest.manifest_sha256),
                    (name,'v2',name+'@v2',key+'_CONTEXT@v2',V2_MANIFEST_SHA256))
                self.assertEqual(catalog.restore(name,'v1'),old.freeze(action,source))
                self.assertEqual(catalog.restore(name,'v2',prompt_version='v2',context_template=key+'_CONTEXT@v2'),latest)
                for version in ('v4','latest',None):
                    with self.assertRaises(ConfigInvalid):catalog.restore(name,version)
                with self.assertRaises(ConfigInvalid):catalog.restore(name,'v1',prompt_version='v2')
                with self.assertRaises(ConfigInvalid):catalog.restore(name,'v2',context_template=key+'_CONTEXT@v1')

    def test_schema_template_signature_and_budget_preserved_all_six(self):
        catalog=historical_catalog();old=ResourceCatalog(DEFAULT_ROOT)
        self.assertEqual([entry for entry in catalog.frontend_catalog['templates'] if entry['template_key'] == 'change-requirement'],
                         [entry for entry in old.frontend_catalog['templates'] if entry['template_key'] == 'change-requirement'])
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
            self.assertEqual(ResourceCatalog(DEFAULT_ROOT,versioned_root=target).freeze('ASK','USER_INSTRUCTION').version,'v2')
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
    """D15-005 replaces legacy-row continuation with a fresh V1.5 database."""
    def setUp(self):
        from backend.app.infrastructure.database import Database
        from backend.app.infrastructure.idempotency import Idempotency
        from backend.app.infrastructure.process_lock import ProcessLock
        self.directory = tempfile.TemporaryDirectory(prefix='walle-v15-versioned-')
        self.addCleanup(self.directory.cleanup)
        self.database = Database(Path(self.directory.name) / 'new.sqlite')
        self.database.initialize()
        self.lock = ProcessLock.for_database(self.database.path).acquire()
        self.addCleanup(self.lock.release)
        self.executor = Idempotency(self.database, self.lock)
        self.catalog = historical_catalog()

    def create(self, **changes):
        from uuid import uuid4
        from backend.app.requirements.commands import create_requirement
        payload = {'title': 'fresh requirement', 'requirement_type': 'NEW',
            'initial_idea': 'original input', 'idempotency_key': str(uuid4())}
        return create_requirement(self.executor, {**payload, **changes}, catalog=self.catalog)

    def count(self, table):
        with self.database.transaction() as connection:
            return connection.execute('SELECT count(*) FROM ' + table).fetchone()[0]

    def test_new_creation_does_not_activate_historical_initialization(self):
        from uuid import uuid4
        key = str(uuid4())
        result = self.create(idempotency_key=key)
        self.assertEqual(result['code'], 'CREATED', result)
        self.assertEqual(result['data']['documents'], [])
        self.assertEqual(result['data']['requirement']['status'], 'PLANNING')
        self.assertEqual(self.count('guide_runs'), 0)
        self.assertEqual(self.count('llm_uses'), 0)
        self.assertEqual(self.create(idempotency_key=key), result)
        # Historical resources are still available by exact immutable version.
        self.assertEqual(self.catalog.restore('INITIALIZE_REQUIREMENT', 'v1').version, 'v1')

    def test_legacy_creation_fields_are_rejected_without_row_conversion(self):
        result = self.create(template_key='new-requirement', template_version='v1', initialization_mode='IDEATION')
        self.assertEqual(result['code'], 'INVALID_INPUT')
        self.assertEqual(self.count('requirements'), 0)
        self.assertEqual(self.count('conversation_messages'), 0)

    def test_no_hidden_run_or_context_is_created_by_a_context_read(self):
        self.create()
        result = get_model_context(self.database, 1, catalog=self.catalog)
        self.assertEqual(result['code'], 'NOT_FOUND', result)
        self.assertEqual(self.count('guide_runs'), 0)
        self.assertEqual(self.count('llm_uses'), 0)

    def test_removed_initialization_does_not_create_a_legacy_baseline(self):
        from backend.app.requirements.commands import complete_initialization
        self.create()
        result = complete_initialization(self.executor, {'requirement_id': 1}, catalog=self.catalog)
        self.assertEqual(result['code'], 'STATE_CONFLICT')
        self.assertEqual(self.count('revisions'), 0)
        self.assertEqual(self.count('requirement_documents'), 0)
