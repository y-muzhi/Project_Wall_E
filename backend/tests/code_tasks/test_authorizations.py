"""Scope narrowing and native approval HTTP; no grant is applied to a task."""

from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4

import pytest

from backend.app.code_tasks.authorization_scope import (
    parse_authorization_scope,
    profile_scope_error,
    resource_scope_error,
)
from backend.app.infrastructure.database import CommitOutcomeUnknown
from backend.app.infrastructure.windows_private_package import (
    PackageSecurityError,
    current_operator_sid,
)
from backend.app.shared.validation import InvalidInput
from backend.tests.infrastructure.test_v20_command_http import package, service, close
from backend.tests.code_tasks.test_execution_profile_content import body
from backend.tests.code_tasks.test_execution_profile_versions import (
    parents,
    seed_price,
    resources,
    publish as publish_profile,
)

PATH = '/api/v1/code-authorizations'


def scope():
    return {
        'read_roots': [],
        'write_workspace_only': True,
        'allowed_command_ids': [],
        'network_targets': [],
        'model_profile_refs': ['deepseek-v2'],
        'allow_local_delivery': False,
        'limits': deepcopy(body()['limits']),
    }


def approve(client, value=None, key=None):
    return client.post(
        PATH,
        json={'profile_version_id': 1, 'scope': scope()} if value is None else value,
        headers={'Idempotency-Key': key or str(uuid4())},
    )


def prepare(database, client):
    parents(client)
    seed_price(database)
    with resources():
        response = publish_profile(client)
    assert response.status_code == 201, response.text


def test_scope_immutable_and_subset_not_implicit_permission():
    value = scope()
    content = parse_authorization_scope(value, max_input_bytes=8192)
    value['limits']['max_output_tokens'] = 1
    assert content.value()['limits']['max_output_tokens'] == 100
    assert profile_scope_error(content.value(), body()) is None
    for name, change in [
        ('model_profile_refs', ['doubao-v1']),
        ('allowed_command_ids', ['undeclared']),
        ('allow_local_delivery', True),
        ('limits', {**body()['limits'], 'max_model_requests': 101}),
    ]:
        candidate = {**content.value(), name: change}
        assert profile_scope_error(candidate, body()) == 'scope.' + name


@pytest.mark.parametrize('invalid', [False, 0, 1, None, 'true'])
def test_write_workspace_only_cannot_be_disabled_or_coerced(invalid):
    with pytest.raises(InvalidInput):
        parse_authorization_scope(
            {**scope(), 'write_workspace_only': invalid}, max_input_bytes=8192
        )


@pytest.mark.parametrize(
    'invalid',
    [
        {'read_roots': ['same', 'same']},
        {'network_targets': '*'},
        {'allow_local_delivery': 'true'},
        {'environment': {'secret_refs': ['ARK_API_KEY']}},
        {'actor_ref': 'browser'},
        {'limits': {}},
        {'limits': {**body()['limits'], 'max_output_tokens': 0}},
    ],
)
def test_scope_exact_fields_and_safe_limits(invalid):
    with pytest.raises(InvalidInput):
        parse_authorization_scope({**scope(), **invalid}, max_input_bytes=8192)


def test_scope_reference_kind_is_not_guessed_from_text():
    candidate = {**scope(), 'read_roots': ['documents'], 'network_targets': ['service']}
    snapshot = {
        'SCOPE': [
            {'ready': False, 'value': {'scope_ref': 'documents', 'scope_kind': 'READ_ROOT'}},
            {'ready': False, 'value': {'scope_ref': 'service', 'scope_kind': 'NETWORK_TARGET'}},
        ]
    }
    assert resource_scope_error(candidate, snapshot) is None
    snapshot['SCOPE'][0]['value']['scope_kind'] = 'NETWORK_TARGET'
    assert resource_scope_error(candidate, snapshot) == 'scope.read_roots'


def test_real_native_actor_create_replay_read_filter_and_no_binding(service):
    database, app, client = service
    prepare(database, client)
    key = str(uuid4())
    with resources():
        first = approve(client, key=key)
        assert first.status_code == 201, first.text
        assert (
            approve(client, key=key).json()['data']
            == first.json()['data']
            == {'resource_kind': 'AUTHORIZATION', 'resource_id': 1}
        )
        detail = client.get(PATH + '/1')
        assert detail.status_code == 200, detail.text
        data = detail.json()['data']
        assert data['actor_ref'] == current_operator_sid()
        assert data['status'] == 'APPROVED_UNBOUND' and data['task_id'] is None
        assert data['scope'] == scope() and data['profile_version_id'] == 1
        assert client.get(PATH).json()['data']['items'] == [data]
        assert client.get(PATH, params={'status': 'EFFECTIVE'}).json()['data']['items'] == []
        assert client.get(PATH, params={'page': '2'}).json()['data']['items'] == []
        assert client.get(PATH, params={'task_id': '99'}).status_code == 404
    # Neither a second actor lookup nor resource preparation is needed to replay.
    with patch(
        'backend.app.code_tasks.authorizations.current_operator_sid',
        side_effect=AssertionError('replay must not approve twice'),
    ):
        assert approve(client, key=key).status_code == 201
    receipt = client.get(
        '/api/v1/code-command-receipts', params={'method': 'POST', 'path': PATH, 'request_key': key}
    )
    assert receipt.json()['data']['original_outcome']['data'] == first.json()['data']
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_authorizations').fetchone()[0] == 1
        for table in ('code_tasks', 'code_configuration_applications', 'llm_uses'):
            assert connection.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0
    assert not any(event['event'].startswith('DISPATCH') for event in app.state.walle_worker.events)


def test_missing_profile_is_original_and_close_blocks_late_approval(service):
    database, _, client = service
    key = str(uuid4())
    assert approve(client, key=key).status_code == 404
    prepare(database, client)
    with resources():
        assert approve(client, key=key).status_code == 404
        closed = str(uuid4())
        assert (
            close(client, {'method': 'POST', 'path': PATH, 'request_key': closed}).status_code
            == 200
        )
        result = approve(client, key=closed)
        assert result.status_code == 409 and result.json()['error']['code'] == 'COMMAND_CLOSED'


def test_scope_widening_and_unregistered_roots_reject_without_approval(service):
    database, _, client = service
    prepare(database, client)
    with resources():
        for change in [
            {'read_roots': ['C:/secret']},
            {'network_targets': ['arbitrary-server']},
            {'model_profile_refs': ['doubao-v1']},
            {'allowed_command_ids': ['free-shell']},
            {'allow_local_delivery': True},
            {'limits': {**scope()['limits'], 'max_output_tokens': 101}},
        ]:
            result = approve(client, {'profile_version_id': 1, 'scope': {**scope(), **change}})
            assert result.status_code == 422, result.text
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_authorizations').fetchone()[0] == 0


def test_native_identity_failure_is_explicit_and_does_not_allocate(service):
    database, _, client = service
    prepare(database, client)
    with (
        resources(),
        patch(
            'backend.app.code_tasks.authorizations.current_operator_sid',
            side_effect=PackageSecurityError('PRIVATE'),
        ),
    ):
        result = approve(client)
    assert result.status_code == 503, result.text
    assert result.json()['error']['details'] == {'capability_codes': ['Q20-WINDOWS']}
    assert 'PRIVATE' not in result.text
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_authorizations').fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT 1 FROM sequences WHERE entity_kind='AuthorizationGrant'"
            ).fetchone()
            is None
        )


def test_input_never_accepts_approver_binding_or_effective_state(service):
    _, _, client = service
    for key, value in [
        ('actor_ref', 'browser'),
        ('approved_at', 'now'),
        ('task_id', 1),
        ('status', 'EFFECTIVE'),
    ]:
        result = approve(client, {'profile_version_id': 1, 'scope': scope(), key: value})
        assert result.status_code == 422, result.text
    for query in (
        'page=01',
        'status=ready',
        'status=EFFECTIVE&status=RETIRED',
        'task_id=0',
        'unknown=x',
    ):
        assert client.get(PATH + '?' + query).status_code == 422
    assert client.get(PATH, headers={'Idempotency-Key': str(uuid4())}).status_code == 422


def test_lost_commit_ack_recovers_original_grant_and_actor(service):
    database, _, client = service
    prepare(database, client)
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
            raise CommitOutcomeUnknown('Injected ack loss')

    with resources(), patch.object(database, 'transaction', unknown):
        assert approve(client, key=key).status_code == 503
    assert approve(client, key=key).status_code == 201
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_authorizations').fetchone()[0] == 1


def test_bad_stored_scope_is_not_silently_widened_or_repaired(service):
    from backend.app.infrastructure.schema_transport import compact

    database, _, client = service
    prepare(database, client)
    original = compact(scope())
    duplicated = '{"write_workspace_only":false,' + original[1:]
    with database.transaction(write=True) as connection:
        connection.execute(
            "INSERT INTO code_authorizations VALUES(1,NULL,1,?,'APPROVED_UNBOUND','2026-11-05T00:00:00.000Z','test-native-source')",
            (duplicated,),
        )
    for path in (PATH, PATH + '/1'):
        result = client.get(path)
        assert result.status_code == 503, result.text


def test_authorization_capacity_has_no_partial_approval(service):
    database, _, client = service
    prepare(database, client)
    with database.transaction(write=True) as connection:
        connection.execute("INSERT INTO sequences VALUES('AuthorizationGrant',9007199254740991)")
    with resources():
        result = approve(client)
    assert result.status_code == 409, result.text
    assert result.json()['error']['code'] == 'PRECONDITION_FAILED'


def test_authorization_history_pages_use_approval_time_and_id_without_inventing_rows(service):
    database, _, client = service
    prepare(database, client)
    with resources():
        assert approve(client).status_code == 201
        with database.transaction(write=True) as connection:
            row = connection.execute('SELECT * FROM code_authorizations WHERE id=1').fetchone()
            for identity in range(2, 22):
                connection.execute(
                    "INSERT INTO code_authorizations VALUES(?,NULL,1,?,'APPROVED_UNBOUND',?,?)",
                    (identity, row['scope'], row['approved_at'], row['actor_ref']),
                )
        first = client.get(PATH)
        assert first.status_code == 200, first.text
        assert [row['id'] for row in first.json()['data']['items']] == list(range(21, 1, -1))
        assert first.json()['meta']['pagination'] == {
            'page': 1,
            'page_size': 20,
            'total': 21,
            'total_pages': 2,
        }
        assert [
            row['id'] for row in client.get(PATH, params={'page': '2'}).json()['data']['items']
        ] == [1]
        assert client.get(PATH, params={'page': '3'}).json()['data']['items'] == []
        assert (
            len(client.get(PATH, params={'status': 'APPROVED_UNBOUND'}).json()['data']['items'])
            == 20
        )
