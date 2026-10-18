"""CTX-002-A offline regressions; no normal DB, credentials or provider I/O."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from backend.app.guide.context_builder import assemble_input, restore_transport_input, serialize_input, transport_input
from backend.app.guide.context_projection import FIELD_ORDER, make_basis, project, basis_from_actual, document_sections
from backend.app.documents.markdown import parse_markdown
from backend.app.guide.counted_context import compile_counted_candidate, verify_counting_evidence, counting_release_for_function
from backend.app.guide.model_calls import get_model_call, list_model_calls
from backend.app.guide.model_context import get_model_context
from backend.app.guide.trusted_output import produce_trusted_output, validate_business_output
from backend.app.guide import commands
from backend.app.guide.output_evidence import fact_declaration
from backend.app.documents.patch_validation import validate_patch
from backend.app.documents.scopes import resolve_scope
from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.audit_repository import AuditRepository, verify_actual_context
from backend.app.infrastructure.counting_journal import CountingJournal
from backend.app.infrastructure.model_profile import ModelProfile, DEFAULT_PROFILE
from backend.app.infrastructure.production_ai import before_count, before_send
from backend.app.infrastructure.resources import (ResourceCatalog, ConfigInvalid, FUNCTIONS, V8_ROOT,
    DEFAULT_ROOT, V2_ROOT, V3_ROOT, V4_ROOT, V5_ROOT)
from backend.app.infrastructure.schema_transport import compact
from backend.app.shared.command_execution import Rejected
from backend.tests.infrastructure.test_context_layout import FixtureCounter
from backend.tests.requirements import test_create_requirement as creation
from backend.tests.documents.test_patch_validation import patch as patch_fixture

PROFILE = ModelProfile('offline-projection-fixture', DEFAULT_PROFILE)


class ProjectionTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = ResourceCatalog()

    def actual(self, template='v4'):
        fixture = creation.CreateRequirementTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.catalog = self.catalog
        accepted = fixture.create(template_version=template)
        self.assertEqual(accepted['code'], 'CREATED', accepted)
        identity = accepted['data']['guide_run_id']
        actual = get_model_context(fixture.database, identity, catalog=self.catalog)['data']
        function = self.catalog.restore(actual['run']['function_type'], actual['run']['prompt_version'])
        return fixture, identity, actual, function

    def test_all_tasks_keep_old_budgets_outputs_and_frozen_history(self):
        for action, source in FUNCTIONS:
            for template, version in (('v1', 'v8'), ('v2', 'v9'), ('v4', 'v9')):
                function = self.catalog.freeze(action, source, template_key='new-requirement', template_version=template)
                old_version = ('v6' if version == 'v8' else 'v7') if action == 'INITIALIZE' else ('v4' if version == 'v8' else 'v5')
                old = self.catalog.restore(function.function_type, old_version)
                self.assertEqual(function.version, version)
                self.assertEqual(function.context_policy['budget'], old.context_policy['budget'])
                self.assertEqual(function.context_policy['history_limit'], old.context_policy['history_limit'])
                self.assertEqual(function.context_policy['trim_order'], old.context_policy['trim_order'])
                self.assertEqual(function.output_schema_json, old.output_schema_json)
                self.assertTrue(before_count(PROFILE, function, counting_release_for_function(PROFILE, function)))
                with self.assertRaises(ConfigInvalid): before_count(PROFILE, old, counting_release_for_function(PROFILE, function))
                self.assertNotIn('message必须精确等于', function.prompt)
        historical = ResourceCatalog(DEFAULT_ROOT, versioned_root=V2_ROOT, extended_root=V3_ROOT, layout_root=V4_ROOT, progression_root=V5_ROOT)
        self.assertEqual(self.catalog.restore('INITIALIZE_REQUIREMENT', 'v7'), historical.restore('INITIALIZE_REQUIREMENT', 'v7'))

    def test_full_markdown_and_identity_retained_metadata_not_sent(self):
        _, _, actual, function = self.actual()
        value = assemble_input(actual, function); before = deepcopy(value)
        wire = transport_input(value, function)
        self.assertEqual(tuple(wire), FIELD_ORDER)
        self.assertEqual(wire['template']['markdown_content'], value['template']['markdown_content'])
        self.assertEqual([block['markdown_content'] for block in wire['document_context']['read_blocks']],
                         [block['markdown_content'] for block in value['current_document']['read_blocks']])
        self.assertEqual([block['block_id'] for block in wire['document_context']['read_blocks']], value['read_manifest']['block_ids'])
        encoded = compact(wire)
        for field in ('created_at', 'last_modified_at', 'created_by_type', 'read_block_metadata', 'plain_text', 'read_manifest'):
            self.assertNotIn('"' + field + '":', encoded)
        self.assertEqual(restore_transport_input(wire, function, basis=make_basis(value, function)), value)
        self.assertEqual(value, before)
        with self.assertRaises(ValueError): restore_transport_input(wire, function)

    def test_fixed_322_block_fixture_meets_character_targets_without_losing_content(self):
        _, _, actual, function = self.actual('v2')
        canonical = assemble_input(actual,function); wire=transport_input(canonical,function)
        old=deepcopy(canonical);old.pop('section_lookup')
        previous=transport_input(old,self.catalog.restore(function.function_type,'v7'))
        self.assertEqual(len(wire['document_context']['read_blocks']),322)
        self.assertEqual([item['markdown_content'] for item in wire['document_context']['read_blocks']],
            [item['markdown_content'] for item in previous['current_document']['read_blocks']])
        self.assertLessEqual(len(compact(wire)),130000)
        self.assertLessEqual(sum(len(compact(wire[key])) for key in ('task','requirement','section_index','current_request')),8000)

    def test_repeated_titles_and_sparse_reads_use_actual_heading_identity(self):
        _, _, actual, function = self.actual('v1')
        value = assemble_input(actual, function)
        template = value['current_document']['read_blocks'][0]
        parsed = parse_markdown('# 同名\n\n甲\n\n# 同名\n\n乙\n')
        metadata = [{**template['metadata'], 'block_id': index+1, 'block_type': block.block_type, 'section_path': list(block.section_path)} for index,block in enumerate(parsed.blocks)]
        value['section_lookup'] = document_sections(parsed,metadata,{1,2,4})
        value['current_document']['read_blocks'] = [{'metadata':item,'markdown_content':block.markdown,'plain_text':block.plain_text,'heading_level':block.heading_level}
            for block,item in zip(parsed.blocks,metadata) if item['block_id'] in (1,2,4)]
        wire = project(value)
        self.assertEqual([item['section_ref'] for item in wire['section_index']], ['h1','h3'])
        self.assertEqual([item['section_ref'] for item in wire['document_context']['read_blocks']], ['h1','h1','h3'])
        self.assertNotIn(3,[block['block_id'] for block in wire['document_context']['read_blocks']])

    def test_empty_row_whitelist_and_selection_are_not_grouped_as_unrestricted(self):
        _, _, actual, function = self.actual('v1')
        value = assemble_input(actual, function)
        ids = [item['metadata']['block_id'] for item in value['current_document']['read_blocks'][:4]]
        def grant(identity, selection=None, rows=None):
            return {'block_id':identity,'operations':['REPLACE_BLOCK','REPLACE_TABLE_ROW'],'selection_range':selection,'row_selectors':rows}
        value['allowed_targets'] = [grant(ids[0]),grant(ids[1]),grant(ids[2],rows=[]),grant(ids[3],selection={'start_offset':0,'end_offset':1}),grant(99999)]
        request = project(value)['current_request']
        self.assertEqual(request['capability_groups'][0]['block_ids'], ids[:2])
        self.assertEqual(request['restricted_targets'][0]['row_selectors'], [])
        self.assertEqual(request['restricted_targets'][1]['selection_range'], {'start_offset':0,'end_offset':1})
        self.assertNotIn(99999, [identity for group in request['capability_groups'] for identity in group['block_ids']])

    async def test_actual_count_send_audit_replay_and_read_details_share_wire(self):
        fixture, identity, actual, function = self.actual()
        counter = FixtureCounter()
        context = await compile_counted_candidate(actual, function, PROFILE, counter=counter)
        self.assertEqual(counter.texts[-1][:2], (context.system, context.input_json))
        self.assertTrue(before_send(PROFILE, context, function))
        with fixture.database.transaction(write=True) as connection:
            row = AuditRepository(connection).prepare(identity, function, PROFILE, context, '2026-10-04T08:00:00.000Z', catalog=self.catalog)
        saved = json.loads(row['request_snapshot_json'])
        self.assertEqual(saved['request']['messages'][1]['content'], context.input_json)
        restored = restore_transport_input(context.input, function, basis=saved['context_basis'])
        self.assertEqual(restored, assemble_input(actual, function))
        with patch('socket.socket.connect', side_effect=AssertionError('Read must remain offline')):
            detail = get_model_call(fixture.database, row['id'])['data']
            summary = list_model_calls(fixture.database, identity)['data']['items'][0]
        self.assertEqual(summary['user_message_id'], actual['user_input']['id'])
        self.assertEqual(summary['document_version'], actual['current_document']['content_version'])
        self.assertEqual(detail['selection_summary']['read_blocks'], len(restored['current_document']['read_blocks']))
        self.assertEqual(detail['selection_summary']['soft_input_target'], 49152)
        self.assertNotIn('context_basis', compact(detail))
        self.assertNotIn('canonical_input', detail['raw_request_json'])
        self.assertEqual(json.loads(detail['raw_request_json']), saved['request'])
        raw = {'model': PROFILE.model_name, 'object':'chat.completion',
            'usage':{'prompt_tokens':6000,'completion_tokens':12,'total_tokens':6012},
            'choices':[{'message':{'role':'assistant','content':compact({'schema_version':1,'response_type':'INITIALIZE_TEXT','message':'已记录','confirmed_fact_patches':[]})},'finish_reason':'stop'}]}
        with fixture.database.transaction(write=True) as connection:
            audits=AuditRepository(connection)
            audits.record_transport(row['id'],raw,'2026-10-04T08:00:01.000Z',profile=PROFILE,succeeded=True,finish_reason='stop',input_tokens=6000,output_tokens=12)
            audits.parse_response(row['id'],'2026-10-04T08:00:02.000Z')
        receipt = produce_trusted_output(fixture.database,row['id'],process_lock=fixture.lock,profile=PROFILE,catalog=self.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=3))
        self.assertIsNotNone(receipt)

    async def test_missing_tampered_or_swapped_basis_never_authorizes_adoption(self):
        fixture, identity, actual, function = self.actual('v1')
        context = await compile_counted_candidate(actual, function, PROFILE, counter=FixtureCounter())
        basis = json.loads(context.basis_json)
        changed = deepcopy(basis); changed['canonical_input']['requirement']['title'] = '伪造标题'
        with self.assertRaises(ValueError): restore_transport_input(context.input,function,basis=changed)
        changed = deepcopy(basis); changed['wire_sha256']='0'*64
        with self.assertRaises(ValueError): restore_transport_input(context.input,function,basis=changed)
        changed = deepcopy(context.input); changed['current_request']['capability_groups']=[]
        with self.assertRaises(ValueError): restore_transport_input(changed,function,basis=basis)
        for candidate in (None, changed):
            with fixture.database.transaction() as connection:
                with self.assertRaises(Rejected):
                    verify_actual_context(connection,identity,function,context.input,context.system,context.manifest_json,self.catalog,basis=candidate)
        # Re-hashing falsified private facts is not authority: actual C03 wins.
        altered = deepcopy(basis['canonical_input']); altered['requirement']['title']='伪造标题'
        forged = make_basis(altered,function)
        with fixture.database.transaction() as connection:
            with self.assertRaises(Rejected):
                verify_actual_context(connection,identity,function,project(altered),context.system,context.manifest_json,self.catalog,basis=forged)

    async def test_complete_user_text_confirmation_still_proves_and_writes_with_new_basis(self):
        fixture, identity, actual, _ = self.actual('v1')
        with fixture.database.transaction() as connection:
            current=actual['current_document']
            snapshot=validate_snapshot(current['markdown_content'],current['block_state_json'],DocumentSources(connection,1,self.catalog))
            authority=resolve_scope(snapshot,'INITIALIZE','DOCUMENT')
            target=next(identity for identity,(block,_) in snapshot.by_id.items() if block.block_type=='paragraph')
            proposed=patch_fixture(snapshot,target,proposed='需求由业务负责人确认。\n')
            declaration=fact_declaration(snapshot,validate_patch(snapshot,proposed,authority))
        cancelled=commands.cancel_guide_run(fixture.executor,{'guide_run_id':identity,'idempotency_key':str(uuid4())},clock=lambda:creation.INSTANT)
        self.assertEqual(cancelled['code'],'GUIDE_CANCELLED',cancelled)
        accepted=commands.create_guide_run(fixture.executor,{'requirement_id':1,'expected_content_version':1,'action_type':'INITIALIZE',
            'instruction':declaration,'scope_type':'DOCUMENT','source_type':'USER_INSTRUCTION','idempotency_key':str(uuid4())},catalog=self.catalog,clock=lambda:creation.INSTANT)
        self.assertEqual(accepted['code'],'GUIDE_ACCEPTED',accepted)
        identity=accepted['data']['guide_run']['id'];actual=get_model_context(fixture.database,identity,catalog=self.catalog)['data']
        function=self.catalog.restore(actual['run']['function_type'],actual['run']['prompt_version'])
        context=await compile_counted_candidate(actual,function,PROFILE,counter=FixtureCounter())
        output={'schema_version':1,'response_type':'INITIALIZE_TEXT','message':'写入明确确认的事实',
            'confirmed_fact_patches':[{'patch':proposed,'evidence':[{'message_id':actual['user_input']['id'],'quoted_text':actual['user_input']['content']}]}]}
        with fixture.database.transaction() as connection:
            validate_business_output(connection,output=output,function=function,actual=actual,
                supplied=restore_transport_input(context.input,function,basis=json.loads(context.basis_json)),catalog=self.catalog)
        raw={'model':PROFILE.model_name,'object':'chat.completion','usage':{'prompt_tokens':6000,'completion_tokens':12,'total_tokens':6012},
            'choices':[{'message':{'role':'assistant','content':compact(output)},'finish_reason':'stop'}]}
        with fixture.database.transaction(write=True) as connection:
            audits=AuditRepository(connection);row=audits.prepare(identity,function,PROFILE,context,'2026-10-04T08:00:00.000Z',catalog=self.catalog)
            audits.record_transport(row['id'],raw,'2026-10-04T08:00:01.000Z',profile=PROFILE,succeeded=True,finish_reason='stop',input_tokens=6000,output_tokens=12)
            audits.parse_response(row['id'],'2026-10-04T08:00:02.000Z')
        receipt=produce_trusted_output(fixture.database,row['id'],process_lock=fixture.lock,profile=PROFILE,catalog=self.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=3))
        self.assertIsNotNone(receipt)
        result=commands.persist_ai_result(fixture.database,{'guide_run_id':identity,'llm_use_id':row['id'],'trusted_output':receipt},
            process_lock=fixture.lock,profile=PROFILE,catalog=self.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=4))
        self.assertEqual(result['code'],'AI_RESULT_PERSISTED',result)
        self.assertEqual(result['data']['current_document']['content_version'],2)

    async def test_history_trimming_rebuilds_basis_and_counts_exact_projected_parts(self):
        _, _, actual, function = self.actual('v1')
        actual = deepcopy(actual)
        actual['history']=[{'id':900,'sequence_no':1,'role':'USER','message_type':'TEXT','content':'早期内容','structured_content':None}]
        actual['read_manifest']['message_ids']=[900,actual['user_input']['id']]
        counter=FixtureCounter(lambda texts:(1000,5000,100,10,100,2049 if json.loads(texts[5]) else 10))
        context=await compile_counted_candidate(actual,function,PROFILE,counter=counter)
        self.assertEqual(context.removed_history_ids,(900,))
        self.assertEqual(context.input['recent_history'],[])
        supplied=verify_counting_evidence(actual,function,system=context.system,input_json=context.input_json,
            manifest_json=context.manifest_json,evidence=context.counting_evidence,profile=PROFILE)
        self.assertEqual(restore_transport_input(context.input,function,basis=json.loads(context.basis_json)),supplied)
        self.assertEqual(basis_from_actual(actual,function,context.input),json.loads(context.basis_json))

    async def test_count_journal_uses_trusted_basis_and_never_sends_it(self):
        fixture, _, actual, function=self.actual('v1')
        counter=FixtureCounter(); context=await compile_counted_candidate(actual,function,PROFILE,counter=counter)
        journal=CountingJournal(fixture.database,fixture.lock)
        identity=journal.prepare(actual,function,PROFILE,counter.texts[-1],'2026-10-04T08:00:00.000Z')
        record=json.loads((journal.root/(identity+'.prepared.json')).read_text(encoding='utf-8'))
        self.assertEqual(record['read_manifest'],json.loads(context.manifest_json))
        self.assertEqual(record['request']['text'][1],context.input_json)
        self.assertNotIn('context_basis',record['request']['text'][1])

    def test_new_release_tampering_is_rejected_and_old_waiting_protocol_is_retained(self):
        old=ResourceCatalog(DEFAULT_ROOT,versioned_root=V2_ROOT,extended_root=V3_ROOT,layout_root=V4_ROOT,progression_root=V5_ROOT)
        fixture=creation.CreateRequirementTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.catalog=old;created=fixture.create()
        actual=get_model_context(fixture.database,created['data']['guide_run_id'],catalog=self.catalog)
        self.assertEqual(actual['code'],'READ_OK',actual)
        self.assertEqual(actual['data']['run']['prompt_version'],'v6')
        with tempfile.TemporaryDirectory(prefix='walle-projection-resource-') as directory:
            target=Path(directory)/'v8';shutil.copytree(V8_ROOT,target)
            path=target/'prompts/INITIALIZE_REQUIREMENT.v9.md';path.write_bytes(path.read_bytes()+b'changed')
            with self.assertRaises(ConfigInvalid):ResourceCatalog(projection_root=target)
