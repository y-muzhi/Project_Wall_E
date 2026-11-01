"""Document ownership boundaries on real SQLite; no provider access."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.infrastructure.database import Database
from backend.app.infrastructure.idempotency import Idempotency
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.requirements.commands import create_requirement, update_discussion
from backend.app.requirements.queries import get_requirement
from backend.app.documents.commands import create_document
from backend.app.guide.commands import create_guide_run, cancel_guide_run, continue_guide_run
from backend.app.guide.queries import list_guide_runs, get_guide_run
from backend.app.guide.collaboration_context import read_canonical, compile_context
from backend.app.messages.queries import list_messages, get_message
from backend.app.shared.http_boundary import HttpRuntime
from backend.app.requirements.api import req_router
from backend.app.messages.api import message_router
from backend.app.guide.api import guide_router


@pytest.fixture
def workspace():
    with TemporaryDirectory(dir=Path(os.environ.get('WALLE_CHECK_TEMP', Path(__file__).resolve().parents[3] / 'output')), prefix='doc-ai-') as directory:
        database = Database(Path(directory) / 'test.sqlite')
        assert database.initialize()['schema_version'] == 151
        with ProcessLock.for_database(database.path) as lock:
            executor = Idempotency(database, lock)
            catalog = ResourceCatalog()
            assert create_requirement(executor, {
                'title': 'isolation', 'requirement_type': 'NEW', 'initial_idea': 'REQUIREMENT_PRIVATE_INITIAL',
                'idempotency_key': str(uuid4()),
            })['code'] == 'CREATED'
            for name in ('A', 'B'):
                assert create_document(executor, {
                    'requirement_id': 1, 'name': name, 'document_kind': 'DESIGN',
                    'template_ref': None, 'idempotency_key': str(uuid4()),
                }, catalog=catalog)['code'] == 'CREATED'
            yield database, executor, catalog, lock


def accept(workspace, document_id, **changes):
    return create_guide_run(workspace[1], {
        'requirement_id': 1, 'document_id': document_id, 'expected_discussion_version': 1,
        'operation': 'DISCUSS', 'instruction': f'ONLY_DOCUMENT_{document_id}', 'target': None,
        'scope': None, 'source_refs': [], 'proposal_ref': None, 'acknowledge_source_changes': False,
        'idempotency_key': str(uuid4()), **changes,
    }, catalog=workspace[2])


def cancel(workspace, run_id):
    return cancel_guide_run(workspace[1], {'guide_run_id': run_id, 'idempotency_key': str(uuid4())})


def messages(workspace, document_id, **changes):
    return list_messages(workspace[0], {'requirement_id': 1, 'document_id': document_id, **changes})


def test_independent_history_pending_versions_and_wire(workspace):
    database, _, catalog, _ = workspace
    one = accept(workspace, 1)
    assert one['code'] == 'GUIDE_ACCEPTED', one
    one_id = one['data']['guide_run_id']
    assert cancel(workspace, one_id)['code'] == 'GUIDE_CANCELLED'
    two = accept(workspace, 2)
    assert two['code'] == 'GUIDE_ACCEPTED', two
    with database.transaction() as connection:
        canonical = read_canonical(connection, two['data']['guide_run_id'], catalog)
    context = compile_context(canonical, catalog)
    assert 'ONLY_DOCUMENT_1' not in context.input_json
    assert 'REQUIREMENT_PRIVATE_INITIAL' not in context.input_json
    assert 'ONLY_DOCUMENT_2' in context.input_json
    for document_id, accepted in ((1, one), (2, two)):
        page = messages(workspace, document_id)
        assert page['code'] == 'READ_OK', page
        assert all(row['document_id'] == document_id and row['requirement_id'] == 1 for row in page['data']['items'])
        detail = get_requirement(database, 1, expand='discussion', document_id=document_id)
        assert detail['data']['discussion']['pending_user_message_ids'] == [accepted['data']['user_message_id']]
        assert detail['data']['requirement']['discussion_version'] == 2
        history = list_guide_runs(database, {'requirement_id': 1, 'document_id': document_id})
        assert history['code'] == 'READ_OK', history
        assert [row['id'] for row in history['data']['items']] == [accepted['data']['guide_run_id']]
        assert get_guide_run(database,accepted['data']['guide_run_id'])['data']['document_id'] == document_id
    assert get_requirement(database,1)['data']['requirement']['discussion_version'] == 1


def test_local_phase_changes_never_change_sibling_document(workspace):
    _, executor, _, _ = workspace
    result = update_discussion(executor, {
        'requirement_id': 1, 'document_id': 1, 'expected_discussion_version': 1,
        'discussion_command': {'type': 'CHANGE_PHASE', 'phase_kind': 'SOLUTION',
            'closure_message': 'A only', 'unresolved_refs': []},
        'idempotency_key': str(uuid4()),
    }, catalog=workspace[2])
    assert result['code'] == 'UPDATED', result
    assert get_requirement(workspace[0],1,expand='discussion',document_id=1)['data']['discussion']['phase']['kind'] == 'SOLUTION'
    sibling=get_requirement(workspace[0],1,expand='discussion',document_id=2)['data']
    assert sibling['discussion']['phase']['phase_ref'] == 'p1'
    assert sibling['requirement']['discussion_version'] == 1
    assert not sibling['discussion']['dispositions']


def test_explicit_cross_document_reference_only_reads_the_selected_source(workspace):
    first=accept(workspace,1)
    assert cancel(workspace,first['data']['guide_run_id'])['code']=='GUIDE_CANCELLED'
    source={'kind':'MESSAGE','message_id':first['data']['user_message_id']}
    second=accept(workspace,2,source_refs=[source])
    assert second['code']=='GUIDE_ACCEPTED', second
    with workspace[0].transaction() as connection:
        canonical=read_canonical(connection,second['data']['guide_run_id'],workspace[2])
    wire=compile_context(canonical,workspace[2]).input_json
    assert 'ONLY_DOCUMENT_1' in wire
    assert canonical['discussion']['pending_user_message_ids']==[second['data']['user_message_id']]
    assert get_message(workspace[0],1,source['message_id'])['data']['document_id']==1
    assert get_message(workspace[0],999,source['message_id'])['code']=='NOT_FOUND'
    initial = get_message(workspace[0],1,1)
    assert initial['code']=='READ_OK' and initial['data']['document_id'] is None
    assert initial['data']['content']=='REQUIREMENT_PRIVATE_INITIAL'


def test_missing_or_foreign_owner_rejected_and_continuation_keeps_owner(workspace):
    assert accept(workspace,999)['code']=='NOT_FOUND'
    assert accept(workspace,1,operation='REVISE',target={'kind':'EXISTING','document_id':2,'expected_content_version':1},scope={'scope_type':'DOCUMENT','scope_ref':None})['code']=='SOURCE_INVALID'
    assert create_guide_run(workspace[1], {'requirement_id':1})['code']=='INVALID_INPUT'
    first=accept(workspace,1)
    assert cancel(workspace,first['data']['guide_run_id'])['code']=='GUIDE_CANCELLED'
    second=continue_guide_run(workspace[1],{
        'guide_run_id':first['data']['guide_run_id'],'instruction':'continue A',
        'expected_discussion_version':2,'idempotency_key':str(uuid4())},catalog=workspace[2])
    assert second['code']=='GUIDE_CONTINUED', second
    assert get_guide_run(workspace[0],second['data']['guide_run_id'])['data']['document_id']==1
    assert get_requirement(workspace[0],1,document_id=2)['data']['requirement']['discussion_version']==1


def test_http_requires_owner_and_explicit_source_projection(workspace):
    from starlette.requests import Request
    from backend.app.messages.http_models import ListMessagesRequest, GetMessageRequest, GetMessageResponse
    from backend.app.requirements.http_models import GetRequirementRequest, GetRequirementResponse
    from backend.app.shared.validation import InvalidInput

    def request(path_params, query=''):
        return Request({'type':'http','path_params':path_params,'query_string':query.encode(),'headers':[]})
    with pytest.raises(InvalidInput):
        ListMessagesRequest.parse(request({'requirement_id':'1'}))
    parsed=ListMessagesRequest.parse(request({'requirement_id':'1'},'document_id=2'))
    assert parsed.payload['document_id']==2
    detail_request=GetRequirementRequest.parse(request({'requirement_id':'1'},'document_id=2&expand=discussion'))
    result=get_requirement(workspace[0],1,expand='discussion',document_id=detail_request.document_id)
    assert GetRequirementResponse.project(result['data'],detail_request)[0]['requirement']['id']==1
    first=messages(workspace,1)['data']['items'][0]
    source_request=GetMessageRequest.parse(request({'message_id':str(first['id'])},'requirement_id=1'))
    source=get_message(workspace[0],1,first['id'])
    assert GetMessageResponse.project(source['data'],source_request)[0]['document_id']==1


def test_actual_offline_completion_and_program_card_update_only_owner(workspace, monkeypatch):
    from backend.tests.guide.test_v15_counting import offline_gate
    from backend.tests.guide.test_v15_execution import execute, Gateway, output, delta
    from backend.tests.guide.test_v15_cards import group, body
    from backend.app.guide.commands import submit_card_responses
    offline_gate(monkeypatch)
    assert accept(workspace,1)['code']=='GUIDE_ACCEPTED'
    def returned(context):
        payload={'phase_kind':'SOLUTION','closure_summary':'A phase','unresolved_refs':[],
                 'basis_discussion_version':context.input['current_request']['basis_ref']['discussion_version']}
        return output(context,progress_delta=delta(context),cards=group('PHASE_CHANGE',payload))
    result=execute(workspace[:3],Gateway(returned))
    assert result['code']=='AI_FINISHED',result
    rows=messages(workspace,1)
    assert rows['code']=='READ_OK',rows
    card=rows['data']['items'][-1]
    assert card['document_id']==1 and card['card_state']=='AVAILABLE',card
    request=body(card,'accept')
    request['expected_discussion_version']=3
    result=submit_card_responses(workspace[1],request,catalog=workspace[2])
    assert result['code']=='PROGRAM_PROCESSED',result
    first=get_requirement(workspace[0],1,document_id=1,expand='discussion')['data']
    second=get_requirement(workspace[0],1,document_id=2,expand='discussion')['data']
    assert first['discussion']['phase']['kind']=='SOLUTION'
    assert first['discussion']['pending_user_message_ids']==[]
    assert second['discussion']['phase']['kind']=='DISCOVERY'
    assert second['discussion']['topics']==[] and second['discussion']['evidence']==[]
    formal=messages(workspace,1)['data']['items'][-1]
    assert formal['document_id']==1 and formal['program_receipt'] is not None
    with workspace[0].transaction() as connection:
        assert connection.execute("SELECT document_id FROM document_change_audits WHERE event_type='PHASE_CHANGED'").fetchone()[0]==1
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0]==1


def test_reset_tool_discards_only_named_stopped_test_database_and_preserves_config(monkeypatch):
    import importlib.util
    from types import SimpleNamespace
    from backend.app.infrastructure.database import Migration
    from backend.app.infrastructure.requirement_repository import RequirementRepository
    from backend.app.requirements.discussion import empty_discussion
    from backend.app.infrastructure.idempotency import canonical_input
    root=Path(__file__).resolve().parents[3]
    spec=importlib.util.spec_from_file_location('reset_doc_assistant',root/'tools/reset-v15-test-data.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with TemporaryDirectory(dir=Path(os.environ.get('WALLE_CHECK_TEMP', root/'output')),prefix='doc-ai-reset-test-') as temporary:
        owned=Path(temporary)
        monkeypatch.setattr(module,'ROOT',owned)
        target=owned/'data/wall-e-v1.5.sqlite'
        old=Database(target,migration=Migration(root/'backend/app/infrastructure/schemas/v1_5_evidence_150.sql',150))
        old.initialize()
        at='2026-11-01T00:00:00.000Z'
        with old.transaction(write=True) as connection:
            RequirementRepository(connection).create(1,'REQ000001',SimpleNamespace(requirement_type='NEW',title='old test'),1,empty_discussion(),at)
            connection.execute(
                "INSERT INTO conversation_messages(id,requirement_id,guide_run_id,sequence_no,role,content,message_type,structured_content_json,reply_to_message_id,idempotency_key,created_at,phase_ref,topic_refs,document_ids) VALUES (1,1,NULL,1,'USER','old','TEXT',NULL,NULL,?,?,NULL,'[]','[]')",
                (str(uuid4()),at))
        audit=target.with_name(target.name+'.count-audit')
        audit.mkdir()
        source=owned/'frozen-proof.sqlite'
        source.touch()
        config=audit/'resource.admission.json'
        config.write_bytes(canonical_input({'source_database':str(source)}).encode())
        config_bytes=config.read_bytes()
        (audit/('a'*32+'.finished.json')).write_bytes(b'{}')
        with ProcessLock.for_database(target):
            with pytest.raises(Exception):
                module.reset_test_data(target)
        assert target.is_file() and config.read_bytes()==config_bytes
        result=module.reset_test_data(target)
        assert result['schema_version']==151 and result['deleted_test_records']['requirements']==1
        assert result['deleted_count_audits']==1 and config.read_bytes()==config_bytes
        with Database(target).transaction() as connection:
            assert connection.execute('SELECT count(*) FROM requirements').fetchone()[0]==0
        with pytest.raises(ValueError):
            module.reset_test_data(source)
