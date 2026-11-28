"""Keep independent restore-point evidence separate from the last backup attempt."""

import os
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
from backend.app.infrastructure.environment_restic_contract import OFFHOST_RETRIEVED, VERSION
from backend.app.management import operation_contract, recovery_catalog
from backend.app.management.backup_reconciliation import merge_points

MANAGER = '52468f0f-8985-485e-b634-115df2b8a901'
SOURCE = '673bc7cb-5050-4ce8-a9bc-b7733dde9180'
VERIFIER = '0f9bc28b-39ef-456c-8c38-18b8d623a35d'
ENVIRONMENT = 'ef9bd422-44a3-4d0c-a2d5-f830ed815a4d'
BACKUP = '89f785b8-d94b-4602-834e-fd3a27112045'
NEWER = '6d9e8956-787d-4b34-b51c-753c707da48f'
PUBLICATION = '9f65a836-0f2e-49a5-b76e-313f3789ae41'
VERIFICATION = '9c256c7c-14f3-4072-8db1-b329101bcc47'
CUTOFF = '2026-11-22T08:00:00.000Z'
RESTORED = '2026-11-23T08:00:00.000Z'
INDEXED = '2026-11-23T08:01:00.000Z'


def store(path, record):
    raw = canonical(record)
    path.write_bytes(raw)
    return digest(raw)


@pytest.fixture
def recovery_index(tmp_path, monkeypatch):
    monkeypatch.setattr(operation_contract, 'read_protected', Path.read_bytes)
    proof_dir = tmp_path / 'backup-evidence'
    proof_dir.mkdir()
    scope = {'manager_id': MANAGER, 'host_id': SOURCE, 'registry_generation': VERIFIER}
    authority = {
        'source_host_id': SOURCE,
        'verification_host_id': VERIFIER,
        'verification_anchor_sha256': 'b' * 64,
        'storage_profile_sha256': 'c' * 64,
        'repository_id': 'd' * 64,
        'observation_max_age_seconds': 3600,
    }
    common = {
        'backup_id': BACKUP,
        'source_data_generation': SOURCE,
        'source_deployment_id': MANAGER,
        'source_control_revision': 15,
        'cutoff_at': CUTOFF,
        'backup_manifest_sha256': 'e' * 64,
        'logical_content_sha256': 'f' * 64,
    }
    point = {
        **common,
        'database_bytes': 8192,
        'count_audit_state': 'EMPTY',
        'program_sha256': '1' * 64,
        'configuration_sha256': '2' * 64,
        'local_retrieval_sha256': None,
    }
    local = {
        'format_version': 1,
        'status': 'LOCAL_VERIFIED',
        'verification_id': VERIFICATION,
        'verification_policy_sha256': '3' * 64,
        'backup_id': BACKUP,
        'backup_manifest_sha256': 'e' * 64,
        'runtime_manifest_sha256': '4' * 64,
        'schema_manifest_sha256': '5' * 64,
        'program_snapshot_sha256': '6' * 64,
        'frontend_index_sha256': '7' * 64,
        'rehearsal_receipt_sha256': '8' * 64,
        'recovery_read_policy_sha256': '9' * 64,
        'environment_id': ENVIRONMENT,
        'data_generation': VERIFIER,
        'deployment_id': NEWER,
        'configuration_sha256': '0' * 64,
        'control_revision': 16,
        'run_id': NEWER,
        'verified_at': CUTOFF,
        'verified_scopes': ['DOCUMENT_CONTENT', 'DOCUMENT_HISTORY'],
        'database_sha256': 'a' * 64,
        'logical_content_sha256': 'f' * 64,
        'document_lookup': {'requirement_id': 1, 'document_id': 2, 'markdown_sha256': 'a' * 64},
        'outbound_hold_required': True,
    }
    offhost = {
        'format_version': 1,
        'status': OFFHOST_RETRIEVED,
        'verification_id': VERIFICATION,
        'verification_policy_sha256': '3' * 64,
        'publication_operation_id': PUBLICATION,
        **{key: authority[key] for key in authority if key != 'observation_max_age_seconds'},
        'source_environment_id': ENVIRONMENT,
        **common,
        'snapshot_id': '4' * 64,
        'restic_sha256': '5' * 64,
        'restic_version': VERSION,
        'snapshot_bytes': 12288,
        'snapshot_entries': 8,
        'retrieved_at': RESTORED,
    }
    point['local_verification_sha256'] = store(proof_dir / f'{BACKUP}.local.v1.json', local)
    point['offhost_verification_sha256'] = store(proof_dir / f'{BACKUP}.offhost.v1.json', offhost)
    later = {
        **point,
        'backup_id': NEWER,
        'cutoff_at': RESTORED,
        'local_verification_sha256': None,
        'offhost_verification_sha256': None,
    }
    index = {
        'format_version': 2,
        **scope,
        'environment_id': ENVIRONMENT,
        'indexed_at': INDEXED,
        'backup_policy': {
            'backup_policy_ref': MANAGER,
            'rpo_target_seconds': 86400,
            'rto_target_seconds': 14400,
        },
        'latest_attempt': {
            'operation_id': PUBLICATION,
            'status': 'FAILED',
            'observed_at': INDEXED,
            'reason_code': 'BACKUP_ASSET_UNSUPPORTED',
        },
        'offhost_authority': authority,
        'points': [point, later],
    }
    index_path = tmp_path / f'{ENVIRONMENT}.json'

    def read(at=INDEXED):
        return recovery_catalog.read_backup_index(
            SimpleNamespace(scope=scope), ENVIRONMENT, (index_path, store(index_path, index)), at
        )

    return SimpleNamespace(
        read=read,
        index=index,
        point=point,
        offhost=offhost,
        proof_dir=proof_dir,
        scope=scope,
    )


def test_freshness_uses_the_verified_cutoff_and_keeps_the_original_failure(recovery_index):
    case = recovery_index
    summary, points = case.read()
    assert [point['backup_id'] for point in points] == [NEWER, BACKUP]
    assert points[0]['verification_status'] == 'UNVERIFIED'
    assert points[1]['verification_status'] == 'OFFHOST_VERIFIED'
    assert points[1]['offhost_verification']['snapshot_id'] == case.offhost['snapshot_id']
    assert summary['latest_attempt']['status'] == 'FAILED'
    assert summary['latest_local']['backup_id'] == summary['latest_offhost']['backup_id'] == BACKUP
    assert summary['latest_offhost']['verified_at'] == RESTORED
    assert summary['rpo_status'] == 'MISSED'

    case.index['backup_policy']['rpo_target_seconds'] += 60
    assert case.read()[0]['rpo_status'] == 'MET'
    assert case.read('2026-11-23T09:01:00.000Z')[0]['rpo_status'] == 'UNVERIFIED'
    case.index['backup_policy'] = None
    assert case.read()[0]['rpo_status'] == 'UNVERIFIED'
    assert case.read()[0]['latest_offhost']['backup_id'] == BACKUP

    merged = merge_points(points[1], {**points[1], 'verification_status': 'LOCAL_VERIFIED'})
    assert merged['verification_status'] == 'OFFHOST_VERIFIED'
    assert merged['offhost_verification'] == points[1]['offhost_verification']


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('status', 'LOCAL_SNAPSHOT_RETRIEVED'),
        ('source_host_id', VERIFIER),
        ('verification_anchor_sha256', '6' * 64),
        ('storage_profile_sha256', '7' * 64),
        ('source_control_revision', True),
        ('cutoff_at', RESTORED),
        ('logical_content_sha256', '8' * 64),
        ('retrieved_at', '2026-11-25T08:01:00.000Z'),
    ],
)
def test_offhost_index_rejects_conflicting_evidence(recovery_index, field, value):
    case = recovery_index
    path = case.proof_dir / f'{BACKUP}.offhost.v1.json'
    case.point['offhost_verification_sha256'] = store(path, {**case.offhost, field: value})
    with pytest.raises(EnvironmentFailure, match=operation_contract.RESOURCE):
        case.read()


def test_offhost_index_requires_local_rehearsal_and_independent_host(recovery_index):
    case = recovery_index
    local = case.point['local_verification_sha256']
    case.point['local_verification_sha256'] = None
    with pytest.raises(EnvironmentFailure, match=operation_contract.RESOURCE):
        case.read()
    case.point['local_verification_sha256'] = local
    case.index['offhost_authority']['verification_host_id'] = SOURCE
    with pytest.raises(EnvironmentFailure, match=operation_contract.RESOURCE):
        case.read()


def test_release_preflight_requires_the_same_independent_restore_point(recovery_index, monkeypatch):
    from backend.app.infrastructure import environment_release_preflight as preflight

    case = recovery_index
    monkeypatch.setattr(preflight, 'absolute', lambda value, code: Path(value))
    monkeypatch.setattr(preflight, 'read_protected', Path.read_bytes)
    monkeypatch.setattr(preflight, 'now', lambda: INDEXED)
    point = case.point
    manifest = {
        **{
            key: point[key]
            for key in (
                'backup_id',
                'source_data_generation',
                'source_deployment_id',
                'source_control_revision',
                'logical_content_sha256',
            )
        },
        'cutoff_at': point['cutoff_at'].removesuffix('Z') + '+00:00',
        'database_artifact': {'bytes': point['database_bytes']},
    }
    evidence = case.proof_dir / f'{BACKUP}.offhost.v1.json'
    reference = {'path': str(evidence), 'sha256': point['offhost_verification_sha256']}
    plan = {
        'offhost_authority': case.index['offhost_authority'],
        'offhost_verification': reference,
    }
    pin = point['backup_manifest_sha256']
    assert (
        preflight.verify_offhost_preflight(plan, manifest, pin, ENVIRONMENT) == reference['sha256']
    )
    with pytest.raises(EnvironmentFailure, match=preflight.UNVERIFIED):
        preflight.verify_offhost_preflight(plan, manifest, 'c' * 64, ENVIRONMENT)
    forged = {**case.offhost, 'status': 'OFFHOST_SNAPSHOT_UPLOADED'}
    reference['sha256'] = store(evidence, forged)
    with pytest.raises(EnvironmentFailure, match=preflight.UNVERIFIED):
        preflight.verify_offhost_preflight(plan, manifest, pin, ENVIRONMENT)


def test_offhost_restore_binds_the_registered_point_in_the_catalog_and_physical_preflight(
    recovery_index, tmp_path, monkeypatch
):
    from backend.app.infrastructure import environment_release_preflight as release
    from backend.app.infrastructure import environment_restore_preflight as restore
    from backend.app.management import restore_operations

    case = recovery_index
    _, points = case.read()
    point = points[1]
    monkeypatch.setattr(release, 'absolute', lambda value, code: Path(value))
    monkeypatch.setattr(release, 'read_protected', Path.read_bytes)
    monkeypatch.setattr(restore, 'read_protected', Path.read_bytes)
    monkeypatch.setattr(
        restore, 'checked_ref', lambda value, name: (Path(value['path']), value['sha256'])
    )
    monkeypatch.setattr(restore, 'now', lambda: INDEXED)

    def reference(path):
        return {'path': str(path), 'sha256': digest(path.read_bytes())}

    local = reference(case.proof_dir / f'{BACKUP}.local.v1.json')
    remote = reference(case.proof_dir / f'{BACKUP}.offhost.v1.json')
    capture = {'path': str(tmp_path / 'database-capture.v1.json'), 'sha256': '1' * 64}
    preserved = {'backup_id': NEWER, 'capture_policy': capture, 'verification': {'proof': 'before'}}
    selected = {
        'backup_id': BACKUP,
        'verification': {'proof': 'selected'},
        'local_verification': local,
    }
    template = {
        'format_version': 2,
        'operation_id': PUBLICATION,
        'installation_sha256': '1' * 64,
        'source_data_generation': SOURCE,
        'source_deployment_id': MANAGER,
        'source_control_revision': 19,
        'source_configuration_sha256': '2' * 64,
        'preserved': preserved,
        'selected': selected,
        'accepted_backup_cutoff_at': CUTOFF,
        'data_handling': 'PRESERVE_CURRENT_SOURCE',
        'candidate_proof': {},
        'target_manifest': {},
        'target_schema_directory': str(tmp_path),
        'target_data_generation': ENVIRONMENT,
        'target_deployment_id': VERIFICATION,
        'target_configuration_sha256': '3' * 64,
        'data_preparation': capture,
        'offhost_authority': case.index['offhost_authority'],
        'offhost_verification': remote,
    }
    path = tmp_path / restore.OFFHOST_POLICY
    assert restore.restore_plan(path, store(path, template)) == template
    wrong_name = tmp_path / restore.POLICY
    with pytest.raises(EnvironmentFailure, match=restore.INVALID):
        restore.restore_plan(wrong_name, store(wrong_name, template))

    lookup = restore_operations.checked_restore_point
    metadata = lookup(point, ENVIRONMENT, template, INDEXED)
    assert metadata == {**point['offhost_verification'], 'verification_sha256': remote['sha256']}
    legacy = {key: value for key, value in template.items() if key not in restore.OFFHOST_FIELDS}
    legacy['format_version'] = 1
    assert lookup(point, ENVIRONMENT, legacy, INDEXED) is None
    assert restore.restore_authorization(legacy) != restore.restore_authorization(template)
    for rejected in (
        {**point, 'verification_status': 'LOCAL_VERIFIED'},
        {**point, 'local_verification': None},
        {
            **point,
            'offhost_verification': {**point['offhost_verification'], 'snapshot_id': '9' * 64},
        },
    ):
        with pytest.raises(EnvironmentFailure, match=restore_operations.CHANGED):
            lookup(rejected, ENVIRONMENT, template, INDEXED)

    registered = SimpleNamespace(source='registered')
    recovery = {
        'minimum_verification': 'OFFHOST_VERIFIED',
        'offhost_authority': template['offhost_authority'],
    }
    monkeypatch.setattr(
        restore_operations, 'read_recovery_policy', lambda *args, **kwargs: recovery
    )
    assert restore_operations.restore_recovery_policy(case, registered, template) == recovery
    with pytest.raises(EnvironmentFailure, match=restore_operations.CHANGED):
        restore_operations.restore_recovery_policy(case, registered, legacy)

    manifest = {
        **{
            key: point[key]
            for key in (
                'backup_id',
                'source_environment_id',
                'source_data_generation',
                'source_deployment_id',
                'source_control_revision',
                'logical_content_sha256',
            )
        },
        'cutoff_at': CUTOFF.removesuffix('Z') + '+00:00',
        'database_artifact': {'bytes': point['database_bytes']},
    }
    coverage = {
        'runtime_manifest_sha256': '4' * 64,
        'schema_manifest_sha256': '5' * 64,
        'schema_contract_sha256': '6' * 64,
    }
    backup = (
        {**manifest, 'backup_id': NEWER, 'cutoff_at': RESTORED.removesuffix('Z') + '+00:00'},
        'd' * 64,
        coverage,
    )
    selected_package = manifest, point['backup_manifest_sha256'], coverage
    monkeypatch.setattr(
        restore,
        'verified_backup',
        lambda _args, _ref, backup_id: backup if backup_id == NEWER else selected_package,
    )
    source = SimpleNamespace(
        facts=coverage, installation=SimpleNamespace(environment_id=ENVIRONMENT)
    )
    schema = SimpleNamespace(schema_contract_sha256=coverage['schema_contract_sha256'])
    assert restore.verify_selection(None, template, source, schema)[-1] == {
        'selected_offhost_verification_sha256': remote['sha256']
    }
    selected_package = manifest, '9' * 64, coverage
    with pytest.raises(EnvironmentFailure, match=restore.UNVERIFIED):
        restore.verify_selection(None, template, source, schema)
    selected_package = manifest, point['backup_manifest_sha256'], coverage
    store(Path(remote['path']), {**case.offhost, 'repository_id': '9' * 64})
    with pytest.raises(EnvironmentFailure, match=restore.UNVERIFIED):
        restore.verify_selection(None, template, source, schema)


def test_legacy_index_still_reports_local_only(recovery_index):
    case = recovery_index
    case.index['format_version'] = 1
    del case.index['offhost_authority']
    for point in case.index['points']:
        del point['offhost_verification_sha256']
    summary, points = case.read()
    assert points[1]['verification_status'] == 'LOCAL_VERIFIED'
    assert summary['latest_offhost'] is None and summary['rpo_status'] == 'UNVERIFIED'


@pytest.mark.parametrize('version', (1, 2))
def test_export_publishes_one_protected_index_and_preserves_evidence(
    recovery_index, tmp_path, monkeypatch, version
):
    pytest.importorskip('fcntl')
    from backend.app.infrastructure import environment_backup_package
    from backend.app.management import recovery_export

    case = recovery_index
    export = tmp_path / 'registry'
    export.mkdir()
    source = tmp_path / 'archives' / BACKUP
    source.mkdir(parents=True)
    manifest_file = source / 'backup-manifest.v1.json'
    point = case.point
    manifest = {
        **{
            key: point[key]
            for key in (
                'backup_id',
                'source_data_generation',
                'source_deployment_id',
                'source_control_revision',
                'logical_content_sha256',
                'cutoff_at',
            )
        },
        'source_environment_id': ENVIRONMENT,
        'database_artifact': {'bytes': point['database_bytes']},
        'program_and_configuration_refs': {
            'program_sha256': point['program_sha256'],
            'configuration_sha256': point['configuration_sha256'],
        },
    }
    store(manifest_file, manifest)

    def reference(name):
        path = case.proof_dir / name
        return {'path': str(path), 'sha256': digest(path.read_bytes())}

    entry = {
        'backup_id': BACKUP,
        'package': {
            'path': str(source),
            'identity': identity(source.stat()),
            'manifest_sha256': point['backup_manifest_sha256'],
            'maintenance_uid': 1000,
            'shared_gid': 1001,
        },
        'local_verification': reference(f'{BACKUP}.local.v1.json'),
        'local_retrieval': None,
    }
    plan = {
        'format_version': version,
        'operation_id': VERIFICATION,
        **case.scope,
        'environment_id': ENVIRONMENT,
        'indexed_at': INDEXED,
        'backup_policy': case.index['backup_policy'],
        'latest_attempt': case.index['latest_attempt'],
        'points': [entry],
        'output_directory': str(export),
        'output_identity': identity(export.stat()),
    }
    if version == 2:
        plan['offhost_authority'] = case.index['offhost_authority']
        entry['offhost_verification'] = reference(f'{BACKUP}.offhost.v1.json')
    policy = (
        tmp_path
        / 'policy'
        / (recovery_export.OFFHOST_POLICY if version == 2 else recovery_export.POLICY)
    )
    policy.parent.mkdir()
    args = SimpleNamespace(
        anchor=policy,
        anchor_sha256=store(policy, plan),
        root=tmp_path / 'runtime',
        project=tmp_path / 'application',
    )

    @contextmanager
    def protected(folder):
        assert folder.is_dir() and not folder.is_symlink()
        yield folder

    @contextmanager
    def private(folder, expected, principal):
        assert (principal.maintenance_uid, principal.group) == (1000, 1001)
        assert identity(folder.stat()) == expected
        yield folder

    def verify(folder, principal, expected_id, *, expected_manifest):
        assert folder == source and expected_id == BACKUP
        assert manifest_file.read_bytes() == canonical(manifest)
        assert expected_manifest == point['backup_manifest_sha256']
        return manifest, expected_manifest

    def write(folder, name, raw, *, mode):
        assert mode == 0o444
        with (folder / name).open('xb') as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())

    monkeypatch.setattr(environment_backup_package, 'absolute', lambda value, code: Path(value))
    monkeypatch.setattr(environment_backup_package, 'read_protected', Path.read_bytes)
    monkeypatch.setattr(recovery_export, 'absolute', lambda value, code: Path(value))
    monkeypatch.setattr(recovery_export, 'read_protected', Path.read_bytes)
    monkeypatch.setattr(recovery_export, 'protected_directory', protected)
    monkeypatch.setattr(recovery_export, 'private_root', private)
    monkeypatch.setattr(recovery_export, 'verify_contents', verify)
    monkeypatch.setattr(
        recovery_export, 'read_evidence', lambda *_: {'coverage_ref': {'audit_state': 'EMPTY'}}
    )
    monkeypatch.setattr(recovery_export, 'persisted_write', write)
    monkeypatch.setattr(
        recovery_export, 'publish_directory', lambda stage, final: stage.rename(final)
    )
    monkeypatch.setattr(recovery_export, 'check_ext4', lambda _: None)
    monkeypatch.setattr(recovery_export, 'now', lambda: INDEXED)
    monkeypatch.setattr(
        recovery_export,
        'fcntl',
        SimpleNamespace(
            LOCK_SH=1,
            LOCK_EX=2,
            LOCK_NB=4,
            flock=lambda *args: None,
        ),
    )
    monkeypatch.setattr(
        recovery_export,
        'os',
        SimpleNamespace(
            geteuid=lambda: 0,
            fstat=lambda path: path.stat(),
            fsync=lambda _: None,
            path=os.path,
            listdir=os.listdir,
        ),
    )

    if version == 2:
        proof_path = Path(entry['offhost_verification']['path'])
        original = proof_path.read_bytes()
        proof_path.write_bytes(canonical({**case.offhost, 'status': 'LOCAL_SNAPSHOT_RETRIEVED'}))
        entry['offhost_verification'] = reference(proof_path.name)
        args.anchor_sha256 = store(policy, plan)
        with pytest.raises(EnvironmentFailure, match=operation_contract.RESOURCE):
            recovery_export.export_management_backups(args)
        assert not tuple(export.iterdir())
        proof_path.write_bytes(original)
        entry['offhost_verification'] = reference(proof_path.name)
        args.anchor_sha256 = store(policy, plan)

    result = recovery_export.export_management_backups(args)
    assert result == recovery_export.export_management_backups(args)
    target = result['backup_index']
    index = Path(target['path'])
    view, points = recovery_catalog.read_backup_index(
        SimpleNamespace(scope=case.scope), ENVIRONMENT, (index, target['sha256']), INDEXED
    )
    assert points[0]['verification_status'] == (
        'OFFHOST_VERIFIED' if version == 2 else 'LOCAL_VERIFIED'
    )
    assert (view['latest_offhost'] is not None) == (version == 2)
    assert list(export.iterdir()) == [export / VERIFICATION]
    (index.parent / 'backup-evidence' / 'unexpected.json').write_bytes(b'unexpected')
    with pytest.raises(EnvironmentFailure, match=recovery_export.UNVERIFIED):
        recovery_export.export_management_backups(args)
