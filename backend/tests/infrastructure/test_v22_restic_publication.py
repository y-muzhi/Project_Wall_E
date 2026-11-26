"""Verify at-most-once publication and actual archive identity before opening a receipt."""

import json
import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    digest,
    identity,
)

OPERATION = '0f9bc28b-39ef-456c-8c38-18b8d623a35d'
BACKUP = '673bc7cb-5050-4ce8-a9bc-b7733dde9180'
SNAPSHOT = 'b' * 64
REPOSITORY = 'a' * 64


@pytest.fixture
def publication(monkeypatch, tmp_path):
    pytest.importorskip('fcntl')
    from backend.app.infrastructure import environment_backup_package as package_io
    from backend.app.infrastructure import environment_restic_publish as publisher

    assets = tmp_path / 'inputs'
    repository = tmp_path / 'repository'
    package = tmp_path / 'archives' / BACKUP
    work = tmp_path / 'work'
    secrets = tmp_path / 'private'
    for path in (assets, repository, package, work, secrets):
        path.mkdir(parents=True)
    password = secrets / 'password'
    password.write_bytes(b'isolated password')
    tool = assets / 'restic'
    tool.write_bytes(b'versioned test process')
    body = package / 'database.sqlite'
    body.write_bytes(b'unique fixed data')
    seal = canonical({'backup_id': BACKUP, 'body_sha256': digest(body.read_bytes())})
    (package / 'manifest.json').write_bytes(seal)
    plan = {
        'format_version': 1,
        'operation_id': OPERATION,
        'backup_id': BACKUP,
        'backup_manifest_sha256': digest(seal),
        'restic': {
            'path': str(tool),
            'sha256': digest(tool.read_bytes()),
            'version': publisher.VERSION,
        },
        'password_file': {'path': str(password), 'identity': identity(password.stat())},
        'repository_directory': str(repository),
        'repository_identity': identity(repository.stat()),
        'repository_id': REPOSITORY,
        'package_directory': str(package),
        'package_identity': identity(package.stat()),
        'work_directory': str(work),
        'work_identity': identity(work.stat()),
        'max_publish_seconds': 15,
        'max_restore_seconds': 15,
        'max_restore_bytes': 2048,
        'max_files': 4,
    }
    policy = tmp_path / 'policy' / publisher.POLICY
    policy.parent.mkdir()

    def arguments(record):
        raw = canonical(record)
        policy.write_bytes(raw)
        return SimpleNamespace(
            anchor=policy,
            anchor_sha256=digest(raw),
            root=tmp_path / 'runtime',
            project=tmp_path / 'code',
            home=tmp_path / 'home',
            temporary=tmp_path / 'tmp',
        )

    actor = SimpleNamespace(maintenance_uid=778, group=779)

    @contextmanager
    def private_root(path, observed, owner):
        assert observed == identity(path.stat()) and owner == actor
        yield path

    @contextmanager
    def private_password(path, observed, owner):
        assert path == password and observed == identity(path.stat()) and owner == actor
        yield

    def verify_source(path, principal, backup, *, expected_manifest):
        assert principal == actor and backup == BACKUP
        measured = (path / 'manifest.json').read_bytes()
        if digest(measured) != expected_manifest or json.loads(measured)['body_sha256'] != digest(
            (path / body.name).read_bytes()
        ):
            raise EnvironmentFailure(publisher.UNVERIFIED)

    def preserved(directory, name, raw, *, mode):
        assert directory == work and mode == 0o400
        with (directory / name).open('xb') as target:
            target.write(raw)
            target.flush()
            os.fsync(target.fileno())

    monkeypatch.setattr(package_io, 'read_protected', Path.read_bytes)
    monkeypatch.setattr(package_io, 'absolute', lambda value, _: Path(value))
    monkeypatch.setattr(publisher, 'absolute', lambda value, _: Path(value))
    monkeypatch.setattr(publisher, 'principal_for_process', lambda: actor)
    monkeypatch.setattr(publisher, 'private_root', private_root)
    monkeypatch.setattr(publisher, 'fixed_password', private_password)
    monkeypatch.setattr(publisher, 'verify_contents', verify_source)
    monkeypatch.setattr(
        publisher, 'read_entry', lambda directory, name, **_: (directory / name).read_bytes()
    )
    monkeypatch.setattr(publisher, 'persisted_write', preserved)
    monkeypatch.setattr(
        publisher, 'snapshot_file', lambda path, mode: (digest(path.read_bytes()), b'')
    )
    monkeypatch.setattr(
        publisher,
        'os',
        SimpleNamespace(walk=os.walk, fsync=lambda path: None, fstat=lambda path: path.stat()),
    )
    monkeypatch.setattr(
        publisher,
        'fcntl',
        SimpleNamespace(LOCK_EX=1, LOCK_SH=2, LOCK_NB=4, flock=lambda fd, mode: None),
    )
    state = SimpleNamespace(
        rows=[], writes=0, restores=0, report='normal', repository=REPOSITORY, package=package
    )
    archive = repository / SNAPSHOT

    def commit():
        if not archive.exists():
            shutil.copytree(package, archive)
        state.rows = [
            {'id': SNAPSHOT, 'paths': [str(package)], 'tags': list(publisher.tags_for(plan))}
        ]

    def run(command, deadline, cwd, code):
        assert cwd == work and command[0] == str(tool)
        if command[1:] == ['version']:
            return f'restic {publisher.VERSION} running on fixture\n'.encode()
        assert command[1:7] == [
            '--repo',
            str(repository),
            '--password-file',
            str(password),
            '--no-cache',
            '--quiet',
        ]
        verbs = command[7:]
        if verbs == ['cat', 'config']:
            return canonical({'id': state.repository})
        if verbs == ['snapshots', '--json', '--tag', publisher.tags_for(plan)[-1]]:
            return canonical(state.rows)
        assert verbs[:4] == ['backup', '--json', '--force', '--one-file-system']
        assert verbs[-1] == str(package)
        assert list(verbs[5:-1:2]) == list(publisher.tags_for(plan))
        assert (work / f'publish-{OPERATION}-intent.v1.json').is_file()
        state.writes += 1
        if state.report in ('normal', 'lost_reply'):
            commit()
        if state.report != 'normal':
            raise EnvironmentFailure(code)
        return b''

    def retrieve(receive, directory, owner, original, binary, credential, source):
        assert receive == directory == work and binary == tool and credential == password
        assert source == repository and original['snapshot_id'] == SNAPSHOT
        assert original['snapshot_subdirectory'] == package.as_posix()
        state.restores += 1
        verify_source(archive, owner, BACKUP, expected_manifest=plan['backup_manifest_sha256'])
        return {
            'status': 'LOCAL_SNAPSHOT_RETRIEVED',
            'operation_id': OPERATION,
            'restic_sha256': plan['restic']['sha256'],
            'restic_version': publisher.VERSION,
            'snapshot_id': SNAPSHOT,
            'retrieved_at': '2026-11-23T04:00:00.000Z',
            'snapshot_bytes': 230,
            'snapshot_entries': 2,
            'repository_id': REPOSITORY,
            'backup_id': BACKUP,
            'backup_manifest_sha256': digest(seal),
        }

    monkeypatch.setattr(publisher, 'restic_call', run)
    monkeypatch.setattr(publisher, 'retrieve_into', retrieve)
    return SimpleNamespace(
        publisher=publisher,
        args=arguments(plan),
        state=state,
        plan=plan,
        arguments=arguments,
        work=work,
        commit=commit,
        archive=archive,
    )


@pytest.mark.parametrize('report', ('normal', 'lost_reply'))
def test_confirmed_original_snapshot_is_published_only_once(publication, report):
    case = publication
    case.state.report = report
    original = case.publisher.publish_backup_snapshot(case.args)
    assert original['status'] == 'LOCAL_SNAPSHOT_PUBLISHED'
    assert original['snapshot_id'] == SNAPSHOT
    assert original['backup_id'] == BACKUP
    assert case.publisher.publish_backup_snapshot(case.args) == original
    assert (case.state.writes, case.state.restores) == (1, 1)
    changed = case.arguments({**case.plan, 'max_files': 3})
    with pytest.raises(EnvironmentFailure, match=case.publisher.INVALID):
        case.publisher.publish_backup_snapshot(changed)
    assert case.state.writes == 1


def test_unknown_publication_never_dispatches_again_and_late_snapshot_can_be_adopted(publication):
    case = publication
    case.state.report = 'unknown'
    for _ in range(2):
        with pytest.raises(EnvironmentFailure, match=case.publisher.UNVERIFIED) as failed:
            case.publisher.publish_backup_snapshot(case.args)
        assert failed.value.uncertain
    assert (case.state.writes, case.state.restores) == (1, 0)
    assert not tuple(case.work.glob('*-result.v1.json'))
    case.commit()
    result = case.publisher.publish_backup_snapshot(case.args)
    assert result['snapshot_id'] == SNAPSHOT
    assert (case.state.writes, case.state.restores) == (1, 1)


def test_wrong_repository_or_unowned_tag_cannot_start_publication(publication):
    case = publication
    case.state.repository = 'f' * 64
    with pytest.raises(EnvironmentFailure, match=case.publisher.UNVERIFIED):
        case.publisher.publish_backup_snapshot(case.args)
    case.state.repository = REPOSITORY
    case.commit()
    with pytest.raises(EnvironmentFailure, match=case.publisher.INVALID):
        case.publisher.publish_backup_snapshot(case.args)
    assert (case.state.writes, case.state.restores) == (0, 0)
    assert not tuple(case.work.iterdir())


def test_tagged_snapshot_is_not_committed_when_restored_bytes_differ(publication):
    case = publication
    case.state.report = 'unknown'
    with pytest.raises(EnvironmentFailure, match=case.publisher.UNVERIFIED):
        case.publisher.publish_backup_snapshot(case.args)
    case.commit()
    (case.archive / 'database.sqlite').write_bytes(b'wrong data from original package')
    with pytest.raises(EnvironmentFailure, match=case.publisher.UNVERIFIED) as failed:
        case.publisher.publish_backup_snapshot(case.args)
    assert failed.value.uncertain
    assert (case.state.writes, case.state.restores) == (1, 1)
    assert not tuple(case.work.glob('*-result.v1.json'))


def test_protected_backup_index_exposes_verified_local_publication(
    publication, monkeypatch, tmp_path
):
    from backend.app.management import operation_contract, recovery_catalog

    proof = publication.publisher.publish_backup_snapshot(publication.args)
    index_path = tmp_path / 'management-index.json'
    evidence = tmp_path / 'backup-evidence'
    evidence.mkdir()
    receipt_path = evidence / f'{BACKUP}.retrieval.v1.json'
    end = '2026-11-23T05:00:00.000Z'
    scope = {'manager_id': OPERATION, 'host_id': BACKUP, 'registry_generation': OPERATION}
    catalog = SimpleNamespace(scope=scope)
    point = {
        'backup_id': BACKUP,
        'source_data_generation': OPERATION,
        'source_deployment_id': BACKUP,
        'source_control_revision': 2,
        'cutoff_at': '2026-11-23T03:30:00.000Z',
        'backup_manifest_sha256': proof['backup_manifest_sha256'],
        'database_bytes': 30,
        'logical_content_sha256': 'e' * 64,
        'count_audit_state': 'ABSENT',
        'program_sha256': 'f' * 64,
        'configuration_sha256': 'a' * 64,
        'local_verification_sha256': None,
    }
    monkeypatch.setattr(operation_contract, 'read_protected', Path.read_bytes)

    def read(raw_proof):
        raw = canonical(raw_proof)
        receipt_path.write_bytes(raw)
        index = canonical(
            {
                'format_version': 1,
                **scope,
                'environment_id': OPERATION,
                'indexed_at': end,
                'backup_policy': None,
                'latest_attempt': None,
                'points': [{**point, 'local_retrieval_sha256': digest(raw)}],
            }
        )
        index_path.write_bytes(index)
        return recovery_catalog.read_backup_index(
            catalog, OPERATION, (index_path, digest(index)), end
        )

    reference, points = read(proof)
    assert points[0]['local_snapshot_retrieval'] == {
        'snapshot_id': SNAPSHOT,
        'retrieved_at': proof['retrieved_at'],
    }
    assert points[0]['verification_status'] == 'UNVERIFIED'
    assert reference['latest_offhost'] is None and reference['rpo_status'] == 'UNVERIFIED'
    preserved = dict(proof)
    preserved.pop('policy_sha256')
    preserved.pop('publication_intent_sha256')
    preserved['status'] = 'LOCAL_SNAPSHOT_RETRIEVED'
    assert read(preserved) == (reference, points)
    for corrupt in (
        {'publication_intent_sha256': 'c' * 64},
        {'backup_manifest_sha256': 'c' * 64},
        {'retrieved_at': '2026-11-23T02:00:00.000Z'},
    ):
        with pytest.raises(EnvironmentFailure, match=operation_contract.RESOURCE):
            read({**proof, **corrupt})
