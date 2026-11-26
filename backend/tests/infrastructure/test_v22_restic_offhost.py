"""Exercise the publisher and verifier with an owned repository transport fixture."""

import json
import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import pytest

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    digest,
    identity,
)

ENVIRONMENT = '673bc7cb-5050-4ce8-a9bc-b7733dde9180'
BACKUP = '0f9bc28b-39ef-456c-8c38-18b8d623a35d'
PUBLICATION = 'ef9bd422-44a3-4d0c-a2d5-f830ed815a4d'
VERIFICATION = '89f785b8-d94b-4602-834e-fd3a27112045'
SOURCE = '68dd33a1-1de7-4f5c-b44e-5f87efc009de'
VERIFIER = '52468f0f-8985-485e-b634-115df2b8a901'
SNAPSHOT = 'a' * 64
REPOSITORY = 'b' * 64
CUT = '2026-11-23T00:00:00.000Z'
STAMP = '2026-11-23T08:00:00.000Z'


def protect(path, record):
    raw = canonical(record)
    path.write_bytes(raw)
    return {'path': str(path), 'sha256': digest(raw)}


@pytest.fixture
def offhost_case(tmp_path, monkeypatch):
    pytest.importorskip('fcntl')
    from backend.app.infrastructure import (
        environment_backup_package as packaging,
    )
    from backend.app.infrastructure import (
        environment_restic_offhost as storage,
    )
    from backend.app.infrastructure import (
        environment_restic_offhost_materialize as materialize,
    )
    from backend.app.infrastructure import (
        environment_restic_offhost_publish as publish,
    )
    from backend.app.infrastructure import (
        environment_restic_offhost_verify as verify,
    )
    from backend.app.infrastructure import (
        environment_restic_restore as restore,
    )

    owner = SimpleNamespace(maintenance_uid=1000, group=1001)
    state = SimpleNamespace(
        role='PUBLISHER',
        remote=None,
        writes=0,
        restores=0,
        commands=[],
        lost=False,
        skip_write=False,
    )
    archive = tmp_path / 'local' / BACKUP
    archive.mkdir(parents=True)
    body = archive / 'database.sqlite'
    body.write_bytes(b'known source database bytes')
    manifest = {
        'backup_id': BACKUP,
        'source_environment_id': ENVIRONMENT,
        'source_data_generation': SOURCE,
        'source_deployment_id': VERIFIER,
        'source_control_revision': 47,
        'cutoff_at': CUT,
        'logical_content_sha256': digest(body.read_bytes()),
    }
    manifest_ref = protect(archive / 'backup-manifest.v1.json', manifest)
    profile = tmp_path / 'fixed-storage' / storage.PROFILE
    profile.parent.mkdir()
    profile_ref = protect(
        profile,
        {
            'format_version': 1,
            'provider': 'TENCENT_COS',
            'region': 'ap-guangzhou',
            'bucket': 'isolated-project-100000',
            'prefix': 'project/environment',
            'repository_id': REPOSITORY,
            'environment_id': ENVIRONMENT,
        },
    )

    binary = tmp_path / 'tool' / 'restic'
    binary.parent.mkdir()
    binary.write_bytes(b'pinned executable fixture')
    program = {
        'path': str(binary),
        'sha256': digest(binary.read_bytes()),
        'version': storage.VERSION,
    }
    host_machines = {'PUBLISHER': b'a' * 32, 'VERIFIER': b'b' * 32}
    installed = {}
    for role, identifier in (('PUBLISHER', SOURCE), ('VERIFIER', VERIFIER)):
        root = tmp_path / role.lower()
        private = root / 'secrets'
        private.mkdir(parents=True)
        policy = root / 'policy'
        policy.mkdir()
        work = root / 'work'
        work.mkdir()
        host_ref = protect(
            policy / storage.HOST,
            {
                'format_version': 1,
                'host_id': identifier,
                'role': role,
                'machine_id_sha256': digest(host_machines[role]),
                'maintenance_uid': owner.maintenance_uid,
                'shared_gid': owner.group,
            },
        )
        password = private / 'restic-password'
        password.write_bytes(b'owned fixture password')
        creds = private / 'storage.json'
        protect(
            creds,
            {
                'access_key_id': role + 'TestId',
                'secret_access_key': role + 'TestSecret',
                'session_token': None if role == 'PUBLISHER' else 'ScopedTemporaryToken',
            },
        )
        installed[role] = (
            root,
            policy,
            {
                'host': host_ref,
                'storage': profile_ref,
                'restic': program,
                'password_file': {'path': str(password), 'identity': identity(password.stat())},
                'storage_credentials': {'path': str(creds), 'identity': identity(creds.stat())},
                'work_directory': str(work),
                'work_identity': identity(work.stat()),
            },
        )

    def arguments(role, filename, plan):
        root, policy, references = installed[role]
        path = policy / filename
        full = {'format_version': 1, **references, **plan}
        return SimpleNamespace(
            anchor=path,
            anchor_sha256=protect(path, full)['sha256'],
            root=root / 'runtime',
            project=root / 'application',
            home=root / 'home',
            temporary=root / 'tmp',
        )

    def publication_args(**overrides):
        return arguments(
            'PUBLISHER',
            publish.POLICY,
            {
                'operation_id': PUBLICATION,
                'backup_id': BACKUP,
                'backup_manifest_sha256': manifest_ref['sha256'],
                'package_directory': str(archive),
                'package_identity': identity(archive.stat()),
                'max_publish_seconds': 30,
                'max_package_bytes': 2048,
                'max_files': 5,
                **overrides,
            },
        )

    def verification_args(proof, **overrides):
        # Preserve a Linux snapshot member name when exercising the contract on Windows.
        state.member = '/owned-sealed/' + BACKUP
        receipt = installed['VERIFIER'][1] / verify.offhost_publication_filename(PUBLICATION)
        imported = protect(receipt, {**proof, 'snapshot_subdirectory': state.member})
        return arguments(
            'VERIFIER',
            verify.POLICY,
            {
                'verification_id': VERIFICATION,
                'publication_operation_id': PUBLICATION,
                'publication_receipt': imported,
                'source_host_id': SOURCE,
                'source_host_anchor_sha256': installed['PUBLISHER'][2]['host']['sha256'],
                'max_restore_seconds': 30,
                'max_restore_bytes': 2048,
                'max_files': 5,
                **overrides,
            },
        )

    @contextmanager
    def private_root(path, expected, principal):
        assert principal == owner and identity(path.stat()) == expected
        yield path

    @contextmanager
    def private_secret(path, expected, principal):
        assert principal == owner and identity(path.stat()) == expected
        with path.open('rb') as stream:
            yield stream.fileno()

    @contextmanager
    def restored_root(parent, name, uid, gid, *, source):
        assert source is False and (uid, gid) == (owner.maintenance_uid, owner.group)
        yield parent / name

    def verify_contents(path, principal, backup, *, expected_manifest):
        assert principal == owner and backup == BACKUP
        raw = (path / 'backup-manifest.v1.json').read_bytes()
        facts = json.loads(raw)
        if (
            digest(raw) != expected_manifest
            or digest((path / body.name).read_bytes()) != facts['logical_content_sha256']
        ):
            raise EnvironmentFailure(storage.UNVERIFIED)
        return facts, digest(raw)

    def installed_record(path):
        return host_machines[state.role] if path == storage.MACHINE_ID else path.read_bytes()

    def protected_write(directory, name, raw, *, mode):
        assert mode == 0o400
        with (directory / name).open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())

    def read_owned(directory, name, **requirements):
        assert requirements['owner'] == owner.maintenance_uid
        assert requirements['group'] == owner.group
        return (directory / name).read_bytes()

    def execution(argv, deadline, cwd, code, *, environment):
        work = Path(installed[state.role][2]['work_directory'])
        assert cwd == work and argv[0] == str(binary) and deadline > 0
        assert environment['AWS_ACCESS_KEY_ID'] == state.role + 'TestId'
        assert environment['AWS_SECRET_ACCESS_KEY'] == state.role + 'TestSecret'
        assert all('TestSecret' not in part for part in argv)
        assert 'HTTP_PROXY' not in environment and environment['HOME'] == str(work)
        if argv[1:] == ['version']:
            return f'restic {storage.VERSION} fixture\n'.encode('ascii')
        assert argv[1:11] == [
            '--repo',
            's3:https://cos.ap-guangzhou.myqcloud.com/isolated-project-100000/project/environment',
            '--password-file',
            installed[state.role][2]['password_file']['path'],
            '--no-cache',
            '--quiet',
            '-o',
            's3.bucket-lookup=dns',
            '-o',
            's3.region=ap-guangzhou',
        ]
        subcommand = argv[11:]
        state.commands.append(subcommand[0])
        if subcommand == ['cat', 'config']:
            return canonical({'id': REPOSITORY})
        if subcommand[:2] == ['snapshots', '--json']:
            if state.remote is None:
                return canonical([])
            assert subcommand[-1] in (SNAPSHOT, f'wall-e-publication-{PUBLICATION}')
            return canonical(
                [
                    {
                        'id': SNAPSHOT,
                        'paths': [str(archive) if state.role == 'PUBLISHER' else state.member],
                        'tags': [
                            f'wall-e-backup-{BACKUP}',
                            f'wall-e-manifest-{manifest_ref["sha256"]}',
                            f'wall-e-publication-{PUBLICATION}',
                        ],
                    }
                ]
            )
        if subcommand[:3] == ['stats', '--json', '--mode']:
            assert subcommand[-1] == SNAPSHOT
            return canonical({'snapshots_count': 1, 'total_size': 1024, 'total_file_count': 2})
        if subcommand[0] == 'backup':
            assert state.role == 'PUBLISHER' and state.remote is None
            assert tuple(work.glob('*-intent.v1.json'))
            assert subcommand[-1] == str(archive)
            state.writes += 1
            if state.skip_write:
                raise EnvironmentFailure(code)
            state.remote = tmp_path / 'object-store'
            shutil.copytree(archive, state.remote)
            if state.lost:
                raise EnvironmentFailure(code)
            return b''
        assert state.role == 'VERIFIER' and state.remote is not None
        assert subcommand[:3] == ['restore', SNAPSHOT + ':' + state.member, '--target']
        assert subcommand[4:] == ['--overwrite', 'never', '--verify']
        state.restores += 1
        target = Path(subcommand[3])
        assert target.parent == work
        for item in state.remote.iterdir():
            shutil.copyfile(item, target / item.name)
        return b''

    for module in (packaging, storage):
        monkeypatch.setattr(module, 'absolute', lambda value, code: Path(value))
        monkeypatch.setattr(module, 'read_protected', installed_record)
    for module in (publish, verify):
        monkeypatch.setattr(module, 'now', lambda: STAMP)
    for module in (publish, verify, materialize):
        monkeypatch.setattr(module, 'persisted_write', protected_write)
    for module in (storage, publish, materialize):
        monkeypatch.setattr(
            module,
            'fcntl',
            SimpleNamespace(
                LOCK_EX=1,
                LOCK_SH=2,
                LOCK_NB=4,
                flock=lambda *args: None,
            ),
        )
        monkeypatch.setattr(module, 'private_root', private_root)
        monkeypatch.setattr(
            module,
            'os',
            SimpleNamespace(
                fstat=lambda path: path.stat(),
                fsync=lambda _: None,
                read=os.read,
                path=os.path,
            ),
        )
    monkeypatch.setattr(verify, 'os', SimpleNamespace(fsync=lambda _: None))
    monkeypatch.setattr(storage, 'fixed_password', private_secret)
    monkeypatch.setattr(storage, 'read_entry', read_owned)
    monkeypatch.setattr(storage, 'principal_for_process', lambda: owner)
    monkeypatch.setattr(
        storage, 'snapshot_file', lambda path, mode: (digest(path.read_bytes()), None)
    )
    monkeypatch.setattr(storage, 'restic_call', execution)
    for module in (publish, materialize, restore):
        monkeypatch.setattr(module, 'verify_contents', verify_contents)
    monkeypatch.setattr(
        materialize, 'publish_directory', lambda source, final: source.rename(final)
    )

    def assert_package_files(scratch):
        assert {member.name for member in scratch.iterdir()} == {
            'database.sqlite',
            'backup-manifest.v1.json',
        }

    monkeypatch.setattr(materialize, 'sync_restored_package', assert_package_files)
    monkeypatch.setattr(restore, 'audit_directory', restored_root)
    return SimpleNamespace(
        storage=storage,
        publish=publish,
        verify=verify,
        publication_args=publication_args,
        verification_args=verification_args,
        state=state,
        installed=installed,
        profile=profile,
        materialize=materialize,
        root=tmp_path,
    )


def test_offhost_uploader_and_verifier_adopt_the_single_original_snapshot(offhost_case):
    case = offhost_case
    case.state.lost = True
    arguments = case.publication_args()
    source = case.publish.publish_offhost_backup_snapshot(arguments)
    assert source['status'] == 'OFFHOST_SNAPSHOT_UPLOADED'
    assert source == case.publish.publish_offhost_backup_snapshot(arguments)
    assert (case.state.writes, case.state.restores) == (1, 0)

    case.state.role = 'VERIFIER'
    verification = case.verification_args(source)
    report = case.verify.verify_offhost_backup_snapshot(verification)
    assert report['status'] == 'OFFHOST_SNAPSHOT_RETRIEVED'
    assert report['source_host_id'] != report['verification_host_id']
    assert report['source_environment_id'] == ENVIRONMENT
    assert report['snapshot_id'] == SNAPSHOT and report['backup_id'] == BACKUP
    assert report == case.verify.verify_offhost_backup_snapshot(verification)
    assert (case.state.writes, case.state.restores) == (1, 1)
    assert not tuple(Path(case.installed['VERIFIER'][2]['work_directory']).glob('.restic-*'))


def test_unknown_remote_outcome_never_writes_twice(offhost_case):
    case = offhost_case
    case.state.skip_write = True
    plan = case.publication_args()
    for _ in range(2):
        with pytest.raises(EnvironmentFailure, match=case.storage.UNVERIFIED) as rejected:
            case.publish.publish_offhost_backup_snapshot(plan)
        assert rejected.value.uncertain
    work = Path(case.installed['PUBLISHER'][2]['work_directory'])
    assert (case.state.writes, case.state.restores) == (1, 0)
    assert not tuple(work.glob('*-result.v1.json'))


def test_materialized_package_recovers_the_original_publish_after_lost_receipt(
    offhost_case, monkeypatch
):
    case = offhost_case
    source = case.publish.publish_offhost_backup_snapshot(case.publication_args())
    case.state.role = 'VERIFIER'
    verification = case.verification_args(source)
    report = case.verify.verify_offhost_backup_snapshot(verification)
    directory = case.root / 'restore-packages'
    directory.mkdir()
    final = directory / BACKUP
    plan = {
        'operation_id': '68dd33a1-1de7-4f5c-b44e-5f87efc009df',
        'verification_policy': {
            'path': str(verification.anchor),
            'sha256': verification.anchor_sha256,
        },
        'verification_receipt_sha256': digest(canonical(report)),
        'output_directory': str(directory),
        'output_identity': identity(directory.stat()),
    }
    policy = verification.anchor.parent / case.materialize.POLICY
    pin = protect(policy, {'format_version': 1, **plan})['sha256']
    arguments = SimpleNamespace(**{**vars(verification), 'anchor': policy, 'anchor_sha256': pin})
    final.mkdir()
    original = final / 'owned-by-another-operation'
    original.touch()
    with pytest.raises(EnvironmentFailure, match=case.storage.UNVERIFIED):
        case.materialize.materialize_offhost_backup_package(arguments)
    assert original.exists() and case.state.restores == 1
    original.unlink()
    final.rmdir()
    with monkeypatch.context() as unexpected:
        write = case.materialize.persisted_write

        def lose_result(scope, name, raw, *, mode):
            if name.endswith('-result.v1.json'):
                raise OSError('original publication reply lost')
            write(scope, name, raw, mode=mode)

        unexpected.setattr(case.materialize, 'persisted_write', lose_result)
        with pytest.raises(EnvironmentFailure, match=case.storage.UNVERIFIED) as failed:
            case.materialize.materialize_offhost_backup_package(arguments)
        assert failed.value.uncertain
    assert (final / 'database.sqlite').read_bytes() == (
        case.state.remote / 'database.sqlite'
    ).read_bytes()
    assert case.state.restores == 2
    result = case.materialize.materialize_offhost_backup_package(arguments)
    assert result['status'] == case.materialize.MATERIALIZED
    assert result['package_identity'] == identity(final.stat())
    assert result['package_directory'] == str(final)
    assert case.materialize.materialize_offhost_backup_package(arguments) == result
    assert case.state.restores == 2
    (final / 'database.sqlite').write_bytes(b'changed after materialization')
    with pytest.raises(EnvironmentFailure, match=case.storage.UNVERIFIED):
        case.materialize.materialize_offhost_backup_package(arguments)
    assert case.state.restores == 2


def test_same_host_or_invalid_upload_proof_is_rejected_before_contact(offhost_case):
    case = offhost_case
    source = case.publish.publish_offhost_backup_snapshot(case.publication_args())
    case.state.role = 'VERIFIER'
    calls = list(case.state.commands)
    for forged in (
        {'source_machine_id_sha256': digest(b'b' * 32)},
        {'status': 'LOCAL_SNAPSHOT_PUBLISHED'},
        {'source_environment_id': VERIFIER},
        {'repository_id': 'f' * 64},
    ):
        plan = case.verification_args({**source, **forged})
        with pytest.raises(EnvironmentFailure, match=case.storage.UNVERIFIED):
            case.verify.verify_offhost_backup_snapshot(plan)
    assert calls == case.state.commands and case.state.restores == 0


def test_invalid_restored_bytes_never_publish_evidence(offhost_case):
    case = offhost_case
    source = case.publish.publish_offhost_backup_snapshot(case.publication_args())
    case.state.role = 'VERIFIER'
    (case.state.remote / 'database.sqlite').write_bytes(b'corrupted archive body')
    plan = case.verification_args(source)
    with pytest.raises(EnvironmentFailure, match=case.storage.UNVERIFIED):
        case.verify.verify_offhost_backup_snapshot(plan)
    work = Path(case.installed['VERIFIER'][2]['work_directory'])
    assert not list(work.iterdir())


def test_restic_process_truncation_and_timeout_close_the_owned_child(tmp_path):
    pytest.importorskip('fcntl')
    from backend.app.infrastructure.environment_restic_restore import MAX_RESTIC_OUTPUT, restic_call

    def run(script, duration):
        return restic_call([sys.executable, '-B', '-c', script], duration, tmp_path, 'TEST_RESTIC')

    assert run("import sys; sys.stdout.buffer.write(b'ordered fact')", 5) == b'ordered fact'
    assert (
        len(run(f"import sys; sys.stdout.buffer.write(b'x'*{MAX_RESTIC_OUTPUT})", 5))
        == MAX_RESTIC_OUTPUT
    )
    for script, deadline in (
        (
            f"import sys,time; sys.stdout.buffer.write(b'x'*{MAX_RESTIC_OUTPUT + 1}); "
            'sys.stdout.flush(); time.sleep(20)',
            5,
        ),
        ('import time; time.sleep(20)', 0.3),
        ("import sys; sys.stdout.buffer.write(b'failed'); sys.exit(2)", 5),
    ):
        start = monotonic()
        with pytest.raises(EnvironmentFailure, match='TEST_RESTIC'):
            run(script, deadline)
        assert monotonic() - start < 4


def test_unsafe_cos_profile_never_selects_an_endpoint(offhost_case):
    case = offhost_case
    original = json.loads(case.profile.read_bytes())
    for difference in (
        {'region': 'ap-guangzhou.evil.test'},
        {'bucket': 'other%2fproject-100000'},
        {'prefix': 'project/../backup'},
        {'provider': 'ARBITRARY_ENDPOINT'},
    ):
        bad = protect(case.profile, {**original, **difference})
        with pytest.raises(EnvironmentFailure):
            case.storage.load_cos_profile(bad)
    assert not case.state.commands
