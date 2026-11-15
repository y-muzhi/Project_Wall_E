"""Published ConfigurationOption metadata and the actual API20 boundary."""

import hashlib
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.infrastructure import code_configuration_catalog as catalogue
from backend.app.infrastructure.code_catalogue_admission import MANIFEST_SHA256, RELEASE_DIRECTORY
from backend.app.infrastructure.database import Database, StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.service import create_app
from backend.tests.infrastructure import test_v20_command_http as command_fixture

package = command_fixture.package
service = command_fixture.service

PATH = '/api/v1/code-configuration-options'


def encoded(value):
    return (canonical_input(value) + '\n').encode('utf-8')


def copy_release(tmp_path, change=None):
    source = catalogue.ROOT / RELEASE_DIRECTORY
    manifest = json.loads((source / 'manifest.json').read_bytes())
    data = json.loads((source / 'options.json').read_bytes())
    if change:
        change(manifest, data)
    raw = encoded(data)
    manifest['files'][0]['bytes'] = len(raw)
    manifest['files'][0]['sha256'] = hashlib.sha256(raw).hexdigest()
    authority = encoded(manifest)
    directory = tmp_path / 'copy'
    directory.mkdir()
    for name, value in (('manifest.json', authority), ('options.json', raw)):
        with (directory / name).open('xb') as stream:
            stream.write(value)
    return directory, hashlib.sha256(authority).hexdigest()


def test_actual_published_catalogue_is_nonsecret_and_does_not_claim_admission():
    with patch(
        'backend.app.infrastructure.model_profile.ModelProfile.from_environment',
        side_effect=AssertionError('No credentials'),
    ):
        loaded = catalogue.load_code_catalogue()
    assert loaded.release_id == RELEASE_DIRECTORY
    assert loaded.manifest_sha256 == MANIFEST_SHA256
    git = loaded.items('GIT')
    models = loaded.items('MODEL')
    assert len(git) == 1 and len(models) == len(catalogue.PROFILES) == 3
    assert {row['value']['model_profile_ref'] for row in models} == set(catalogue.PROFILES)
    assert all(row['ready'] is False and row['unresolved_capability_codes'] for row in git + models)
    raw = canonical_input({'items': git + models})
    assert all(secret not in raw.lower() for secret in ('api_key', 'password', 'https://', 'c:\\'))
    models[0]['value']['model_profile_ref'] = 'changed copy'
    assert (
        catalogue.load_code_catalogue().items('MODEL')[0]['value']['model_profile_ref']
        in catalogue.PROFILES
    )
    policies = loaded.items('CONTENT_POLICY')
    assert len(policies) == 1 and policies[0]['ready'] is False
    scopes = loaded.items('SCOPE')
    assert scopes == sorted(catalogue.scope_options(), key=lambda row: row['option_id'])
    for kind in set(catalogue.KINDS) - {'MODEL', 'GIT', 'CONTENT_POLICY', 'SCOPE'}:
        assert loaded.items(kind) == []


@pytest.mark.parametrize(
    'mutation',
    [
        lambda m, d: d['items'][0].update(ready=True),
        lambda m, d: d['items'][0].update(extra='private'),
        lambda m, d: d['items'][0]['value'].update(path='private'),
        lambda m, d: d['items'].append(d['items'][0]),
        lambda m, d: d['items'].reverse(),
        lambda m, d: d['items'][1]['value'].update(model_profile_ref='not-registered'),
        lambda m, d: d['items'][0].update(unresolved_capability_codes=[]),
        lambda m, d: d['items'].pop(),
        lambda m, d: m['model_profiles'][0].update(model_version='changed'),
        lambda m, d: m.update(extra='private'),
        lambda m, d: m.update(schema_version=True),
        lambda m, d: m['files'][0].update(path='../options.json'),
        lambda m, d: d['items'][0].update(kind='EXECUTOR'),
    ],
)
def test_even_matching_digest_cannot_publish_invalid_or_secret_projection(tmp_path, mutation):
    root, sha = copy_release(tmp_path, mutation)
    with pytest.raises(ConfigInvalid):
        catalogue.load_verified_catalogue(root, sha)


def test_missing_corrupt_noncanonical_or_wrong_source_is_configuration_failure(tmp_path):
    root, sha = copy_release(tmp_path)
    with pytest.raises(ConfigInvalid):
        catalogue.load_verified_catalogue(root, '0' * 64)
    with patch.object(catalogue, 'GIT_MANIFEST_SHA256', '0' * 64), pytest.raises(ConfigInvalid):
        catalogue.load_verified_catalogue(root, sha)
    (root / 'options.json').unlink()
    with pytest.raises(ConfigInvalid):
        catalogue.load_verified_catalogue(root, sha)
    with (root / 'options.json').open('xb') as stream:
        stream.write(b'{"duplicate":1,"duplicate":2}')
    with pytest.raises(ConfigInvalid):
        catalogue.load_verified_catalogue(root, sha)


def test_prepare_real_sources_once_new_release_and_never_overwrite(tmp_path):
    root = tmp_path / 'publications'
    with patch.object(catalogue, 'ROOT', root):
        directory, sha = catalogue.prepare_catalogue('owned-r1')
        assert catalogue.load_verified_catalogue(directory, sha).release_id == 'owned-r1'
        before = {p.name: p.read_bytes() for p in directory.iterdir()}
        with pytest.raises(FileExistsError):
            catalogue.prepare_catalogue('owned-r1')
        assert {p.name: p.read_bytes() for p in directory.iterdir()} == before
        assert list(root.iterdir()) == [directory]
        for invalid in ('../x', 'A', 'a/b', '', None):
            with pytest.raises(ValueError):
                catalogue.prepare_catalogue(invalid)


def test_api20_reads_actual_registered_bytes_no_identity_or_dispatch(service):
    database, app, client = service
    for kind in catalogue.KINDS:
        response = client.get(PATH, params={'kind': kind})
        assert response.status_code == 200, response.text
        body = response.json()
        expected = catalogue.load_code_catalogue().items(kind)
        assert body['data']['items'] == expected
        assert body['meta']['pagination'] == {
            'page': 1,
            'page_size': 20,
            'total': len(expected),
            'total_pages': 1 if expected else 0,
        }
        page2 = client.get(PATH, params={'kind': kind, 'page': '2'}).json()
        assert page2['data']['items'] == []
        assert page2['meta']['pagination']['total'] == len(expected)
    with database.transaction() as connection:
        for table in (
            'code_execution_profiles',
            'code_execution_profile_versions',
            'code_check_sets',
            'code_operations',
            'llm_uses',
            'idempotency_records',
        ):
            assert connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
    assert not any(e['event'].startswith('DISPATCH') for e in app.state.walle_worker.events)


@pytest.mark.parametrize(
    'query',
    [
        '',
        'kind=',
        'kind=git',
        'kind=NO',
        'kind=GIT&kind=MODEL',
        'kind=GIT&page=0',
        'kind=GIT&page=01',
        'kind=GIT&page=100001',
        'kind=GIT&page=1&page=2',
        'kind=GIT&page_size=1',
        'kind=GIT&secret_ref=x',
    ],
)
def test_api20_rejects_bad_request_before_catalogue_or_database(service, query):
    database, app, client = service
    with (
        patch.object(database, 'transaction', side_effect=AssertionError('No database')),
        patch.object(
            app.state.walle_runtime.catalog,
            'code_configuration_options',
            side_effect=AssertionError('No catalogue'),
        ),
    ):
        response = client.get(PATH + '?' + query)
    assert response.status_code == 422, response.text
    assert response.json()['error']['code'] == 'INVALID_INPUT'


@pytest.mark.parametrize(
    'kwargs',
    [
        {'headers': {'Idempotency-Key': '00000000-0000-4000-8000-000000000001'}},
        {'content': b'{}', 'headers': {'Content-Type': 'application/json'}},
    ],
)
def test_api20_body_and_original_key_are_not_accepted(service, kwargs):
    _, _, client = service
    assert client.request('GET', PATH + '?kind=GIT', **kwargs).status_code == 422


def test_api20_configuration_failure_is_not_empty_and_does_not_leak_private_path(service):
    _, app, client = service
    with patch.object(
        app.state.walle_runtime.catalog,
        'code_configuration_options',
        side_effect=ConfigInvalid('C:\\private\\api-key'),
    ):
        response = client.get(PATH + '?kind=GIT')
    assert response.status_code == 503, response.text
    assert response.json()['data'] is None
    assert response.json()['error']['details'] == {'capability_codes': ['Q20-CONFIG']}
    assert 'private' not in response.text and 'api-key' not in response.text


def test_api20_holds_database_lease_and_reports_storage_failure(service):
    database, _, client = service
    with patch.object(database, 'transaction', side_effect=StorageUnavailable('private')):
        response = client.get(PATH + '?kind=GIT')
    assert response.status_code == 503
    assert response.json()['error']['details'] == {'capability_codes': ['DATABASE']}


def test_api20_does_not_initialize_legacy_database(package):
    root, _ = package
    database = Database(root / 'catalogue-legacy.sqlite')
    database.initialize()
    with TestClient(create_app(database=database)) as client:
        result = client.get(PATH + '?kind=GIT')
        assert result.status_code == 503, result.text
        assert result.json()['error']['details'] == {'capability_codes': ['DATABASE']}
    with database.transaction() as connection:
        assert connection.execute('SELECT version FROM schema_migrations').fetchone()[0] == 151


def test_real_policy_resource_corruption_is_not_an_empty_catalogue(service, tmp_path):
    from backend.app.infrastructure import content_secret_policy as policy

    _, _, client = service
    altered = tmp_path / 'altered-policy'
    with altered.open('xb') as stream:
        stream.write(b'{}')
    with patch.object(policy, 'RESOURCE', altered):
        response = client.get(PATH, params={'kind': 'CONTENT_POLICY'})
    assert response.status_code == 503, response.text
    assert response.json()['error']['code'] == 'CONFIG_NOT_READY'
    assert response.json()['data'] is None
    assert response.json()['error']['details'] == {'capability_codes': ['Q20-CONFIG']}


@pytest.mark.parametrize('release', ['code20-r1', 'code20-r2'])
def test_historical_catalogues_keep_original_bytes_and_do_not_gain_scope_entries(release):
    root = catalogue.ROOT / release
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    digest = hashlib.sha256(before['manifest.json']).hexdigest()
    loaded = catalogue.load_verified_catalogue(root, digest)
    assert loaded.items('SCOPE') == []
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before


@pytest.mark.parametrize(
    'defect',
    [
        'missing-pin',
        'wrong-pin',
        'one-missing',
        'all-missing',
        'path',
        'renamed-reference',
        'ready',
        'capabilities',
        'legacy-manifest',
    ],
)
def test_managed_scope_coverage_and_semantics_cannot_be_self_certified(tmp_path, defect):
    with patch.object(catalogue, 'ROOT', tmp_path / 'publications'):
        directory, _ = catalogue.prepare_catalogue('scope-r1')
    manifest = json.loads((directory / 'manifest.json').read_bytes())
    data = json.loads((directory / 'options.json').read_bytes())
    scopes = [row for row in data['items'] if row['kind'] == 'SCOPE']
    assert len(scopes) == 2
    if defect == 'missing-pin':
        manifest.pop('managed_read_scopes_sha256')
    elif defect == 'wrong-pin':
        manifest['managed_read_scopes_sha256'] = '0' * 64
    elif defect == 'one-missing':
        data['items'].remove(scopes[0])
    elif defect == 'all-missing':
        data['items'] = [row for row in data['items'] if row['kind'] != 'SCOPE']
    elif defect == 'path':
        scopes[0]['value']['path'] = 'C:/private'
    elif defect == 'renamed-reference':
        scopes[0]['value']['scope_ref'] = 'arbitrary-host-root'
    elif defect == 'ready':
        scopes[0]['ready'] = True
    elif defect == 'capabilities':
        scopes[0]['unresolved_capability_codes'] = []
    elif defect == 'legacy-manifest':
        manifest['schema_version'] = 1
        manifest.pop('managed_read_scopes_sha256')
    raw = encoded(data)
    manifest['files'][0].update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    authority = encoded(manifest)
    copy = tmp_path / 'mutated'
    copy.mkdir()
    for name, value in [('manifest.json', authority), ('options.json', raw)]:
        with (copy / name).open('xb') as stream:
            stream.write(value)
    with pytest.raises(ConfigInvalid):
        catalogue.load_verified_catalogue(copy, hashlib.sha256(authority).hexdigest())


def test_managed_scope_resource_corruption_fails_closed_at_api20(service, tmp_path):
    from backend.app.infrastructure import managed_read_scopes

    _, _, client = service
    missing = tmp_path / 'missing-managed-scopes'
    with patch.object(managed_read_scopes, 'RESOURCE', missing):
        response = client.get(PATH, params={'kind': 'SCOPE'})
    assert response.status_code == 503
    assert response.json()['error']['details'] == {'capability_codes': ['Q20-CONFIG']}
    assert str(missing) not in response.text
