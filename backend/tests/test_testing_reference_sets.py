"""Testing references read protected bytes and the original baseline registration facts."""

from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.code_tasks.repository_acceptance import accept_repository_operation
from backend.app.infrastructure.check_runner_bundle import CheckResourceError
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import InvalidInput, strict_json_object
from backend.app.testing.asset_installation import TestingAssetInstallation as AssetInstallation
from backend.app.testing.pack_compile import digest, encoded
from backend.app.testing.reference_resources import (
    REFERENCE_MANIFEST,
    RegisteredReferenceSet,
    decode_reference_set,
)
from backend.tests.code_tasks.test_repository_baseline_acceptance import (
    BaselineInput,
    repository_service,  # noqa: F401
    resources,
)
from backend.tests.infrastructure.test_v20_command_http import package, service  # noqa: F401

PATH = '/api/v1/testing-reference-sets'


def reference(ref='reference:v1', **fields):
    return {
        'reference_set_ref': ref,
        'basis_fingerprint': 'a' * 64,
        'positive_snapshot_ids': [1],
        'negative_controls': [{'snapshot_id': 2, 'expected_failed_case_ids': ['private-1']}],
        'repeat_count': 3,
        **fields,
    }


def register_reference(root, name, data):
    directory = create_private_package(root / name)
    raw = encoded(data)
    (directory / REFERENCE_MANIFEST).write_bytes(raw)
    with PrivatePackageGuard(directory) as guard:
        original = guard.verify()
    return RegisteredReferenceSet(decode_reference_set(raw), original, digest(raw))


def baseline_fixture(runtime, commit, *, repository=1):
    """Keep original C05 identities while supplying explicit offline Git proof fixtures."""
    size = len(commit)
    request = BaselineInput(repository, commit, key=str(uuid4()))
    with resources():
        accepted = accept_repository_operation(runtime, request)
    assert accepted['code'] == 'OPERATION_ACCEPTED', accepted
    identity = accepted['data']['operation_id']
    with runtime.database.transaction(write=True) as connection:
        operation = connection.execute(
            'SELECT * FROM code_operations WHERE id=?', (identity,)
        ).fetchone()
        fixed = strict_json_object(operation['fixed_input'])
        snapshot = fixed['snapshot_id']
        at = max(operation_time(None), operation['created_at'])
        proof = encoded(
            {
                'commit_oid': commit,
                'tree_oid': 'd' * size,
                'repository_sha256': 'a' * 64,
                'closure_sha256': 'b' * 64,
                'content_sha256': 'c' * 64,
            }
        ).decode()
        connection.execute(
            'INSERT INTO code_snapshots VALUES(?,?,?,?,?,?,?,?,?,?)',
            (
                snapshot,
                repository,
                identity,
                request.execution_profile_version_id,
                commit,
                'd' * size,
                fixed['retention_ref'],
                'GIT20-BASELINE-1',
                at,
                at,
            ),
        )
        for number, facts in enumerate(
            (proof, '{}', proof, encoded({'snapshot_id': snapshot}).decode()), 1
        ):
            connection.execute(
                """UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,started_at=?,
                   ended_at=?,last_observed_at=? WHERE operation_id=? AND step_no=?""",
                (facts, at, at, at, identity, number),
            )
        connection.execute(
            "UPDATE code_operations SET status='SUCCEEDED',started_at=?,ended_at=? WHERE id=?",
            (at, at, identity),
        )
    return snapshot


@pytest.mark.parametrize(
    'changes',
    [
        {'positive_snapshot_ids': []},
        {'positive_snapshot_ids': [2]},
        {'positive_snapshot_ids': list(range(1, 22))},
        {'positive_snapshot_ids': [True]},
        {'repeat_count': 1},
        {'repeat_count': 11},
        {'negative_controls': [{'snapshot_id': 2, 'expected_failed_case_ids': []}]},
        {'negative_controls': [{'snapshot_id': 2, 'expected_failed_case_ids': ['same', 'same']}]},
        {'basis_fingerprint': 'bad'},
        {'ready': True},
    ],
)
def test_reference_input_is_closed_and_samples_distinct(changes):
    with pytest.raises((CheckResourceError, InvalidInput)):
        decode_reference_set(encoded(reference(**changes)))


def test_no_installation_has_an_empty_read_only_catalogue(service):  # noqa: F811
    database, _, client = service
    response = client.get(PATH)
    assert response.status_code == 200, response.text
    assert response.json()['data'] == {'items': []}
    assert response.json()['meta']['pagination']['total'] == 0
    for query in ({'page_size': 5}, {'name': 'other'}, {'requirement_id': 1}, {'page': 100001}):
        assert client.get(PATH, params=query).status_code == 422
    with database.transaction() as connection:
        assert (
            connection.execute('SELECT count(*) FROM testing_pack_validations').fetchone()[0] == 0
        )


def test_original_reference_counts_drift_missing_and_no_private_ids(repository_service):  # noqa: F811
    database, runtime, client = repository_service
    first, second = (baseline_fixture(runtime, char * 40) for char in ('1', '2'))
    root = Path(database.path).parent
    output = create_private_package(root / uuid4().hex[:7])
    sources = create_private_package(root / uuid4().hex[:7])
    with PrivatePackageGuard(output) as guard:
        output_id = guard.verify()
    good = register_reference(
        sources,
        'good',
        reference(
            'reference:a',
            positive_snapshot_ids=[first],
            negative_controls=[{'snapshot_id': second, 'expected_failed_case_ids': ['private-1']}],
        ),
    )
    missing = register_reference(
        sources,
        'missing',
        reference(
            'reference:b',
            positive_snapshot_ids=[99],
            negative_controls=[{'snapshot_id': second, 'expected_failed_case_ids': ['private-2']}],
        ),
    )
    runtime.catalog.testing_assets = AssetInstallation(output_id, (), (missing, good))
    response = client.get(PATH)
    assert response.status_code == 200, response.text
    assert response.json()['data']['items'] == [
        {
            'reference_set_ref': 'reference:a',
            'basis_fingerprint': 'a' * 64,
            'positive_count': 1,
            'negative_count': 1,
            'repeat_count': 3,
            'ready': True,
            'reason_codes': [],
        },
        {
            'reference_set_ref': 'reference:b',
            'basis_fingerprint': 'a' * 64,
            'positive_count': 1,
            'negative_count': 1,
            'repeat_count': 3,
            'ready': False,
            'reason_codes': ['CONTENT_NOT_READY'],
        },
    ]
    assert 'private-1' not in response.text and 'snapshot_id' not in response.text
    overflow = client.get(PATH, params={'page': 2}).json()
    assert overflow['data']['items'] == [] and overflow['meta']['pagination']['total'] == 2
    manifest = Path(good.directory.canonical_path) / REFERENCE_MANIFEST
    manifest.write_bytes(manifest.read_bytes() + b' ')
    drift = client.get(PATH).json()['data']['items'][0]
    assert drift['ready'] is False and drift['reason_codes'] == ['CONTENT_NOT_READY']
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM testing_tasks').fetchone()[0] == 0
