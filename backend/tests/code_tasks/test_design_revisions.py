"""Actual document confirmation history and design revision eligibility reads."""

from uuid import uuid4

from backend.app.code_tasks.design_revisions import design_revision_choice
from backend.tests.documents.test_v15_documents import document, metadata
from backend.tests.documents.test_v15_editing import candidate, finish, save, start
from backend.tests.infrastructure.test_v20_command_http import package, service
from backend.tests.requirements.test_v15_foundation import create


def test_fixed_choices_read_real_confirmation_history_and_distinguish_main_from_material(service):
    database, app, client = service
    runtime = app.state.walle_runtime
    workspace = (database, runtime.commands(), runtime.catalog)
    create(runtime.commands())
    main = document(workspace, kind='DESIGN')['data']
    other = document(workspace, kind='DESIGN', name='独立材料')['data']
    document_id, first = main['document']['id'], main['revision_id']
    path = f'/api/v1/documents/{document_id}/code-design-revisions'
    confirmed_empty = metadata(
        workspace,
        document_id,
        1,
        {'type': 'CONFIRM', 'expected_content_version': 1, 'revision_id': first},
    )
    assert confirmed_empty['code'] == 'UPDATED', confirmed_empty
    main_empty = client.get(path)
    assert main_empty.status_code == 200, main_empty.text
    (empty,) = main_empty.json()['data']['items']
    assert empty['reason_code'] == 'EMPTY_MAIN'
    assert (
        not empty['eligible']
        and empty['confirmation_event_id'] == confirmed_empty['data']['event_id']
    )
    material_empty = client.get(path + '?usage=MATERIAL').json()['data']['items'][0]
    assert material_empty['eligible'] and material_empty['reason_code'] is None

    def edit(version, markdown):
        draft = start(workspace, identity=document_id, version=version)['data']['manual_draft']
        saved = save(workspace, draft, candidate(workspace, draft, markdown))
        assert saved['code'] == 'DRAFT_SAVED', saved
        completed = finish(workspace, saved['data'])
        assert completed['code'] == 'DRAFT_COMPLETED', completed
        return completed['data']['revision_id']

    second = edit(1, '已确认的技术设计\n')
    confirmation = metadata(
        workspace,
        document_id,
        2,
        {'type': 'CONFIRM', 'expected_content_version': 2, 'revision_id': second},
    )
    assert confirmation['code'] == 'UPDATED', confirmation
    third = edit(2, '尚未确认的更新\n')
    marker = client.post(
        '/api/v1/requirements/1/revisions',
        json={'document_id': document_id, 'expected_version': 3},
        headers={'Idempotency-Key': str(uuid4())},
    )
    assert marker.status_code == 200, marker.text
    assert marker.json()['data']['revision_id'] == third

    response = client.get(path)
    assert response.status_code == 200, response.text
    latest, historical, blank = response.json()['data']['items']
    assert [row['revision_id'] for row in (latest, historical, blank)] == [third, second, first]
    assert latest['is_current'] and not latest['eligible']
    assert latest['reason_code'] == 'UNCONFIRMED' and latest['confirmation_event_id'] is None
    assert not historical['is_current'] and historical['eligible']
    assert historical['confirmation_event_id'] == confirmation['data']['event_id']
    assert blank['reason_code'] == 'EMPTY_MAIN'
    assert 'markdown_snapshot' not in response.text and 'payload_json' not in response.text
    beyond = client.get(path + '?page=2').json()
    assert beyond['data']['items'] == [] and beyond['meta']['pagination']['total'] == 3
    assert client.get(path + '?usage=MAIN&usage=MATERIAL').status_code == 422
    assert client.get(path + '?page=100001').status_code == 422
    assert client.get('/api/v1/documents/900/code-design-revisions').status_code == 404
    with database.transaction() as connection:
        assert (
            design_revision_choice(connection, document_id, other['revision_id'], usage='MAIN')
            is None
        )
        assert design_revision_choice(connection, document_id, second, usage='MAIN') == historical
