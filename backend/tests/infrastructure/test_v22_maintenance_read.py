"""Cover database sidecars and identity admission during a closed release check."""

import sqlite3
from contextlib import closing

import pytest

from backend.app.infrastructure.environment_files import EnvironmentFailure
from backend.app.infrastructure.environment_initialize import (
    database_has_sidecars,
    read_locked_database,
)
from backend.app.infrastructure.environment_recovery_verify import (
    UNVERIFIED,
    verification_principal,
)


def test_closed_database_read_uses_checkpoint_without_creating_sidecars(tmp_path):
    database = tmp_path / 'validation.sqlite'
    with closing(sqlite3.connect(database)) as writer:
        assert writer.execute('PRAGMA journal_mode=WAL').fetchone() == ('wal',)
        writer.execute('CREATE TABLE document (revision INTEGER)')
        writer.execute('INSERT INTO document VALUES (1)')
        writer.commit()

    assert not database_has_sidecars(database)
    with read_locked_database(database) as reader:
        assert reader.execute('SELECT revision FROM document').fetchall() == [(1,)]
    assert not database_has_sidecars(database)

    with closing(sqlite3.connect(database)) as writer:
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('INSERT INTO document VALUES (2)')
        writer.commit()
        assert database_has_sidecars(database)
        wal = database.with_name(database.name + '-wal')
        original = wal.read_bytes()
        with read_locked_database(database) as reader:
            assert reader.execute('SELECT revision FROM document ORDER BY revision').fetchall() == [
                (1,),
                (2,),
            ]
        assert wal.read_bytes() == original


def test_private_probe_selects_an_existing_read_only_automation_identity():
    identifier = '573bb474-7a53-462f-88e1-8e3c97c91007'
    automation = 'automation-' + identifier
    verifier = 'gateway-check-' + identifier
    declared = [
        {'principal_id': automation, 'client_kind': 'AUTOMATION', 'permission': 'DEVELOP'},
        {'principal_id': 'read-only-web', 'client_kind': 'WEB', 'permission': 'READ_ONLY'},
        {'principal_id': verifier, 'client_kind': 'AUTOMATION', 'permission': 'READ_ONLY'},
    ]
    assert (
        verification_principal({'principals': declared}, identifier, private_socket=True)
        == verifier
    )
    with pytest.raises(EnvironmentFailure, match=UNVERIFIED):
        verification_principal({'principals': declared[:2]}, identifier, private_socket=True)
    with pytest.raises(EnvironmentFailure, match=UNVERIFIED):
        verification_principal({'principals': declared}, identifier, private_socket=False)
    replica = [{**declared[0], 'permission': 'READ_ONLY'}]
    assert (
        verification_principal({'principals': replica}, identifier, private_socket=False)
        == automation
    )


def test_immutable_verification_checks_the_physical_wal_format(tmp_path):
    from backend.app.infrastructure.environment_binding import (
        EnvironmentBinding,
        write_initial_schema,
    )
    from backend.app.infrastructure.environment_initialize import verify_locked_binding
    from backend.app.infrastructure.schema_v22_release import (
        MANIFEST,
        build_candidate,
        digest,
        load_release,
    )

    runtime = '1' * 64
    schema = tmp_path / 'locked-schema'
    schema.mkdir()
    resources = build_candidate(schema.name, runtime)
    for name, contents in resources.items():
        (schema / name).write_bytes(contents)
    release = load_release(schema, digest(resources[MANIFEST]), runtime)
    binding = EnvironmentBinding(
        '60eca284-0b38-4b98-bc15-20bcfc5634cc', 'fe9087f0-5304-4c33-8fd7-a998b2871385'
    )
    path = tmp_path / 'walle.sqlite'
    with closing(sqlite3.connect(path)) as writer:
        assert writer.execute('PRAGMA journal_mode=WAL').fetchone() == ('wal',)
        writer.execute('PRAGMA foreign_keys=ON')
        writer.isolation_level = None
        writer.execute('BEGIN IMMEDIATE')
        write_initial_schema(writer, release, binding)
        initialized = writer.execute('SELECT initialized_at FROM environment_binding').fetchone()[0]
        writer.commit()

    with read_locked_database(path) as reader:
        assert reader.execute('PRAGMA journal_mode').fetchone() == ('delete',)
        assert verify_locked_binding(reader, path, release, binding) == initialized
    assert not database_has_sidecars(path)

    with closing(sqlite3.connect(path)) as writer:
        assert writer.execute('PRAGMA journal_mode=DELETE').fetchone() == ('delete',)
    with read_locked_database(path) as reader:
        with pytest.raises(EnvironmentFailure, match='ENVIRONMENT_BINDING_MISMATCH'):
            verify_locked_binding(reader, path, release, binding)


def test_recovery_mounts_existing_document_reads_and_retains_admission(monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from backend.app.infrastructure import environment_http
    from backend.app.service import create_app

    environment = '60eca284-0b38-4b98-bc15-20bcfc5634cc'
    generation = 'fe9087f0-5304-4c33-8fd7-a998b2871385'
    installation = SimpleNamespace(
        environment_id=environment,
        data_generation=generation,
    )
    scope = SimpleNamespace(
        installation=installation,
        active=True,
        run_id=environment,
        check_current=lambda: None,
    )
    recovery = create_app(recovery=scope)
    recovery_routes = recovery.openapi()['paths']
    ordinary_routes = create_app().openapi()['paths']

    def document_reads(routes):
        return {
            path
            for path, methods in routes.items()
            if 'get' in methods and environment_http.DOCUMENT_READ.fullmatch(path)
        }

    assert (
        document_reads(recovery_routes)
        == document_reads(ordinary_routes)
        == {
            '/api/v1/requirements',
            '/api/v1/requirements/{requirement_id}',
            '/api/v1/requirements/{requirement_id}/current-document',
            '/api/v1/requirements/{requirement_id}/manual-draft',
            '/api/v1/requirements/{requirement_id}/revisions',
            '/api/v1/revisions/{revision_id}',
            '/api/v1/requirements/{requirement_id}/comments',
            '/api/v1/comments/{comment_id}',
            '/api/v1/requirements/{requirement_id}/comment-index',
            '/api/v1/requirements/{requirement_id}/messages',
            '/api/v1/conversation-messages/{message_id}',
        }
    )
    unrelated = '/api/v1/code-repositories'
    assert unrelated in ordinary_routes and unrelated not in recovery_routes
    monkeypatch.setattr(
        environment_http,
        'installed_identities',
        lambda _: (
            'http://recovery.test',
            {'reviewer': {'client_kind': 'AUTOMATION', 'permission': 'READ_ONLY'}},
        ),
    )
    headers = {
        'X-WALL-E-Auth-Principal': 'reviewer',
        'X-WALL-E-Client': 'automation-v1',
        'X-WALL-E-Environment-ID': environment,
        'X-WALL-E-Data-Generation': generation,
        'X-WALL-E-Binding-Protocol': '1',
    }
    client = TestClient(recovery, base_url='http://recovery.test', headers=headers)
    for method, path in (('GET', unrelated), ('POST', '/api/v1/requirements')):
        refused = client.request(method, path)
        assert refused.status_code == 403
        assert refused.json()['error']['code'] == 'RECOVERY_READ_ONLY'
    replay = client.get('/api/v1/requirements', headers={'X-WALL-E-Data-Generation': environment})
    assert replay.status_code == 409
    assert replay.json()['error']['code'] == 'DATA_GENERATION_MISMATCH'
