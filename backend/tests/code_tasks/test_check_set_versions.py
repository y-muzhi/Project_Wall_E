"""Actual immutable check-version HTTP, original receipts and draft readiness."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4

import pytest

from backend.app.infrastructure.database import CommitOutcomeUnknown
from backend.app.infrastructure.resources import ConfigInvalid
from backend.tests.infrastructure.test_v20_command_http import package, service, close
from backend.tests.code_tasks.test_check_set_content import body, coverage, integrity

EMPTY = {'protocol_version': 'CHECK20-CONTROL-1', 'items': [], 'coverage_plan': []}
PATH = '/api/v1/code-check-sets/1/versions'


def create_parent(client):
    result = client.post(
        '/api/v1/code-check-sets',
        json={'name': '检查标准'},
        headers={'Idempotency-Key': str(uuid4())},
    )
    assert result.status_code == 201, result.text


def publish(client, value=None, key=None, path=PATH):
    return client.post(
        path,
        json=EMPTY if value is None else value,
        headers={'Idempotency-Key': key or str(uuid4())},
    )


def seed_basis(database):
    from backend.tests.infrastructure.fixtures_v151 import insert_requirement, AT
    from backend.app.documents.snapshot import create_snapshot, Provenance
    from backend.app.infrastructure.document_repository import DocumentRepository
    from backend.app.infrastructure.revision_repository import RevisionRepository

    with database.transaction(write=True) as connection:
        insert_requirement(connection)
        snapshot = create_snapshot(
            '# 依据\n\n原始依据\n原行\n', Provenance('SYSTEM', 'TEMPLATE', None), AT, lambda _: True
        )
        document = DocumentRepository(connection).create_current(
            1,
            101,
            snapshot,
            AT,
            name='设计',
            document_kind='DESIGN',
            template_ref=None,
            origin={'kind': 'MESSAGE', 'message_id': 101},
        )
        RevisionRepository(connection).insert_content(2, document, [], '原依据', AT)


def test_real_version_create_replay_read_list_and_no_implicit_execution(service):
    database, app, client = service
    create_parent(client)
    key = str(uuid4())
    first, replay = publish(client, key=key), publish(client, key=key)
    assert first.status_code == replay.status_code == 201, first.text
    assert (
        first.json()['data']
        == replay.json()['data']
        == {'resource_kind': 'CHECK_SET_VERSION', 'resource_id': 1}
    )
    detail = client.get('/api/v1/code-check-set-versions/1')
    assert detail.status_code == 200, detail.text
    data = detail.json()['data']
    assert data['owner_module'] == 'CODING' and data['version'] == 1
    assert not data['ready'] and data['unresolved_capability_codes'] == ['Q20-CHECKS']
    assert {field: data[field] for field in EMPTY} == EMPTY
    assert client.get(PATH).json()['data']['items'] == [data]
    receipt = client.get(
        '/api/v1/code-command-receipts', params={'method': 'POST', 'path': PATH, 'request_key': key}
    )
    assert receipt.json()['data']['original_outcome']['data'] == first.json()['data']
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_check_set_versions').fetchone()[0] == 1
        assert (
            connection.execute(
                "SELECT last_value FROM sequences WHERE entity_kind='CheckSetVersion'"
            ).fetchone()[0]
            == 1
        )
        for table in ('code_tasks', 'testing_tasks', 'code_operations', 'llm_uses'):
            assert connection.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0
    assert not any(event['event'].startswith('DISPATCH') for event in app.state.walle_worker.events)


def test_same_key_changed_content_conflicts_and_close_prevents_late_create(service):
    _, _, client = service
    create_parent(client)
    key = str(uuid4())
    assert publish(client, key=key).status_code == 201
    changed = body(items=[integrity()], coverage_plan=[])
    assert publish(client, changed, key).status_code == 409
    other = str(uuid4())
    assert close(client, {'method': 'POST', 'path': PATH, 'request_key': other}).status_code == 200
    result = publish(client, key=other)
    assert result.status_code == 409 and result.json()['error']['code'] == 'COMMAND_CLOSED'


def test_parent_absent_rejection_is_original_and_does_not_allocate_version(service):
    database, _, client = service
    key = str(uuid4())
    assert publish(client, key=key).status_code == 404
    create_parent(client)
    assert publish(client, key=key).status_code == 404
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_check_set_versions').fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT count(*) FROM sequences WHERE entity_kind='CheckSetVersion'"
            ).fetchone()[0]
            == 0
        )


def test_unknown_runner_rejected_without_publishing_placeholder_or_execution(service):
    database, _, client = service
    create_parent(client)
    value = body(items=[integrity()], coverage_plan=[])
    response = publish(client, value)
    assert response.status_code == 422, response.text
    assert response.json()['error']['details']['field_errors'][0]['field'] == 'items[0].runner_ref'
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_check_set_versions').fetchone()[0] == 0


def test_real_basis_quote_saved_immutably_and_wrong_quote_rejected(service):
    database, _, client = service
    create_parent(client)
    seed_basis(database)
    value = body(
        items=[], coverage_plan=[coverage(mode='MANUAL', check_ids=[], explanation='人工核对')]
    )
    response = publish(client, value)
    assert response.status_code == 201, response.text
    detail = client.get('/api/v1/code-check-set-versions/1').json()['data']
    assert detail['coverage_plan'] == value['coverage_plan']
    bad = deepcopy(value)
    bad['coverage_plan'][0]['basis_refs'][0]['quote'] = '不在原文中的引用'
    response = publish(client, bad)
    assert response.status_code == 422
    assert (
        response.json()['error']['details']['field_errors'][0]['field']
        == 'coverage_plan[0].basis_refs[0]'
    )


@pytest.mark.parametrize(
    'path',
    [
        '/api/v1/code-check-set-versions/0',
        '/api/v1/code-check-set-versions/01',
        '/api/v1/code-check-set-versions/x',
        '/api/v1/code-check-set-versions/9007199254740992',
        '/api/v1/code-check-sets/01/versions',
        PATH + '?page=01',
        PATH + '?page=1&page=2',
        PATH + '?owner_module=TESTING',
    ],
)
def test_strict_path_and_queries_before_storage(service, path):
    database, _, client = service
    with patch.object(database, 'transaction', side_effect=AssertionError('No storage')):
        response = client.get(path)
    assert response.status_code == 422, response.text


def test_pagination_and_concurrent_version_numbers_belong_to_same_parent(service):
    _, _, client = service
    create_parent(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: publish(client), range(2)))
    assert all(result.status_code == 201 for result in results), [r.text for r in results]
    listed = client.get(PATH).json()
    assert [row['version'] for row in listed['data']['items']] == [2, 1]
    assert client.get(PATH + '?page=100000').json()['data'] == {'items': []}
    assert client.get('/api/v1/code-check-sets/999/versions').status_code == 404
    assert client.get('/api/v1/code-check-set-versions/999').status_code == 404


def test_catalogue_failure_is_not_empty_or_missing_resource(service):
    database, app, client = service
    create_parent(client)
    with patch.object(
        app.state.walle_runtime.catalog,
        'code_configuration_options',
        side_effect=ConfigInvalid('PRIVATE'),
    ):
        response = publish(client, body(items=[integrity()], coverage_plan=[]))
    assert response.status_code == 503, response.text
    assert response.json()['error']['details'] == {'capability_codes': ['Q20-CONFIG']}
    assert 'PRIVATE' not in response.text
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_check_set_versions').fetchone()[0] == 0


def test_lost_commit_ack_replays_original_version_without_new_number(service):
    database, _, client = service
    create_parent(client)
    key = str(uuid4())
    transaction = database.transaction
    committed = False

    @contextmanager
    def unknown(*, write=False):
        nonlocal committed
        with transaction(write=write) as connection:
            yield connection
        if write and not committed:
            committed = True
            raise CommitOutcomeUnknown('Injected postcommit acknowledgment loss')

    with patch.object(database, 'transaction', unknown):
        first = publish(client, key=key)
    assert first.status_code == 503, first.text
    replay = publish(client, key=key)
    assert replay.status_code == 201, replay.text
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_check_set_versions').fetchone()[0] == 1


def test_persisted_invalid_nested_structure_is_not_returned_as_ready_or_empty(service):
    database, _, client = service
    create_parent(client)
    with database.transaction(write=True) as connection:
        connection.execute(
            "INSERT INTO code_check_set_versions VALUES(1,1,1,'CODING','CHECK20-CONTROL-1',?,?,'2026-11-05T00:00:00.000Z')",
            ('[{"private_extra":"PRIVATE"}]', '[]'),
        )
    for path in (PATH, '/api/v1/code-check-set-versions/1'):
        response = client.get(path)
        assert response.status_code == 503, response.text
        assert 'PRIVATE' not in response.text


def test_all_owner_versions_keep_unique_parent_version_and_coding_publication(service):
    database, _, client = service
    create_parent(client)
    with database.transaction(write=True) as connection:
        connection.execute(
            "INSERT INTO code_check_set_versions VALUES(5,1,4,'TESTING','CHECK20-CONTROL-1','[]','[]','2026-11-05T00:00:00.000Z')"
        )
        connection.execute("INSERT INTO sequences VALUES('CheckSetVersion',5)")
    created = publish(client)
    assert created.status_code == 201, created.text
    assert created.json()['data']['resource_id'] == 6
    rows = client.get(PATH).json()['data']['items']
    assert [(row['version'], row['owner_module']) for row in rows] == [
        (5, 'CODING'),
        (4, 'TESTING'),
    ]


def test_version_or_identity_capacity_rejects_without_consuming_new_id(service):
    database, _, client = service
    create_parent(client)
    with database.transaction(write=True) as connection:
        connection.execute("INSERT INTO sequences VALUES('CheckSetVersion',9007199254740991)")
    response = publish(client)
    assert response.status_code == 409, response.text
    assert response.json()['error']['code'] == 'PRECONDITION_FAILED'
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_check_set_versions').fetchone()[0] == 0


def test_body_cannot_publish_testing_or_client_version_metadata(service):
    _, _, client = service
    create_parent(client)
    for field, value in (('owner_module', 'TESTING'), ('version', 1), ('ready', True)):
        result = publish(client, {**EMPTY, field: value})
        assert result.status_code == 422, result.text


def test_resource_readiness_uses_original_registered_capabilities_and_admission():
    from backend.app.code_tasks.check_set_versions import resource_check, readiness

    content = body(
        items=[integrity(stages=['BACKEND', 'FRONTEND', 'INTEGRATION'])], coverage_plan=[]
    )
    runner = {
        'ready': True,
        'value': {
            'runner_ref': 'controlled-runner',
            'protocol_version': 'CHECK20-CONTROL-1',
            'protected_input_refs': [],
            'capabilities': ['CONTENT_INTEGRITY'],
        },
    }
    snapshot = {'RUNNER': [runner]}
    assert readiness(content, 'CODING', snapshot) == {
        'ready': True,
        'unresolved_capability_codes': [],
    }
    runner['ready'] = False
    assert readiness(content, 'CODING', snapshot)['ready'] is False
    runner['ready'] = True
    runner['value']['capabilities'] = ['CLI']
    assert resource_check(content, snapshot)[0] == 'items[0].runner_ref'
    assert readiness(content, 'CODING', snapshot)['ready'] is False


@pytest.mark.parametrize('corruption', ['duplicate', 'normalized-name'])
def test_read_never_repairs_duplicate_keys_or_stored_label_normalization(service, corruption):
    import json

    database, _, client = service
    create_parent(client)
    item = integrity()
    if corruption == 'normalized-name':
        item['name'] = '  不得修改原值  '
    raw = json.dumps([item], ensure_ascii=False)
    if corruption == 'duplicate':
        raw = raw.replace('"required": true', '"required": false, "required": true')
    with database.transaction(write=True) as connection:
        connection.execute(
            "INSERT INTO code_check_set_versions VALUES(1,1,1,'CODING','CHECK20-CONTROL-1',?,'[]','2026-11-05T00:00:00.000Z')",
            (raw,),
        )
    assert client.get('/api/v1/code-check-set-versions/1').status_code == 503
