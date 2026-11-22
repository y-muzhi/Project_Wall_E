"""Publish a detached management index derived from sealed recovery evidence."""

import fcntl
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from backend.app.infrastructure.environment_backup_package import (
    private_root,
    read_evidence,
    read_policy,
    validate_location,
    verify_contents,
)
from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    absolute,
    canonical,
    check_ext4,
    decode,
    digest,
    exact,
    identity,
    persisted_write,
    protected_directory,
    read_protected,
    require,
)
from backend.app.infrastructure.environment_installation import (
    identity_record,
    sha_value,
    uuid_value,
    version_record,
)
from backend.app.infrastructure.schema_v22_publish import publish_directory

from .attachment_observation import now
from .recovery_evidence import backup_cutoff
from .recovery_catalog import attempt_view, policy_target, read_backup_index
from .registry import is_timestamp

POLICY = 'management-backup-export.v1.json'
RECEIPT = 'management-backup-export-receipt.v1.json'
SCOPE = ('manager_id', 'host_id', 'registry_generation')
INVALID = 'MANAGEMENT_BACKUP_EXPORT_INTENT_MISMATCH'
UNVERIFIED = 'MANAGEMENT_BACKUP_EXPORT_UNVERIFIED'


def export_inputs(args):
    plan = read_policy(
        args.anchor,
        args.anchor_sha256,
        POLICY,
        (
            'operation_id',
            *SCOPE,
            'environment_id',
            'indexed_at',
            'backup_policy',
            'latest_attempt',
            'points',
            'output_directory',
            'output_identity',
        ),
    )
    require(
        all(uuid_value(plan[key]) for key in ('operation_id', *SCOPE, 'environment_id'))
        and is_timestamp(plan['indexed_at'])
        and plan['indexed_at'] <= now()
        and type(plan['points']) is list
        and len(plan['points']) <= 128,
        INVALID,
    )
    output = validate_location(
        plan, 'output_directory', 'output_identity', (args.root, args.project, args.anchor.parent)
    )
    require(
        len({entry.get('backup_id') for entry in plan['points'] if type(entry) is dict})
        == len(plan['points']),
        INVALID,
    )
    policy_target(plan['backup_policy'])
    attempt_view(plan['latest_attempt'], plan['indexed_at'])
    return plan, output


def point_input(raw, output):
    selection = exact(
        raw, ('backup_id', 'package', 'local_verification', 'local_retrieval'), INVALID
    )
    details = exact(
        selection['package'],
        ('path', 'identity', 'manifest_sha256', 'maintenance_uid', 'shared_gid'),
        INVALID,
    )
    path = absolute(details['path'], INVALID)
    identity_record(details['identity'], INVALID)
    require(
        uuid_value(selection['backup_id'])
        and sha_value(details['manifest_sha256'])
        and all(
            type(details[key]) is int and 1 <= details[key] < 2**31
            for key in ('maintenance_uid', 'shared_gid')
        )
        and not path.is_relative_to(output)
        and not output.is_relative_to(path),
        INVALID,
    )
    return selection, path


def copy_evidence(folder, prefix, reference, suffix, output):
    if reference is None:
        return None
    ref = exact(reference, ('path', 'sha256'), INVALID)
    path = absolute(ref['path'], INVALID)
    require(
        sha_value(ref['sha256'])
        and not path.is_relative_to(output)
        and path.name.endswith('.json'),
        INVALID,
    )
    raw = read_protected(path)
    require(digest(raw) == ref['sha256'], UNVERIFIED)
    persisted_write(folder, f'{prefix}.{suffix}.v1.json', raw, mode=0o444)
    return ref['sha256']


def extract_point(entry, evidence_fd, env, output):
    selection, path = point_input(entry, output)
    request = selection['package']
    principal = SimpleNamespace(
        maintenance_uid=request['maintenance_uid'], group=request['shared_gid']
    )
    with private_root(path, request['identity'], principal) as directory:
        fcntl.flock(directory, fcntl.LOCK_SH | fcntl.LOCK_NB)
        manifest, measured = verify_contents(
            directory,
            principal,
            selection['backup_id'],
            expected_manifest=request['manifest_sha256'],
        )
        evidence = read_evidence(directory, principal, manifest)
    require(manifest['source_environment_id'] == env, UNVERIFIED)
    backup_id = manifest['backup_id']
    program = manifest['program_and_configuration_refs']
    return {
        **{
            field: manifest[field]
            for field in (
                'backup_id',
                'source_data_generation',
                'source_deployment_id',
                'source_control_revision',
                'logical_content_sha256',
            )
        },
        'cutoff_at': backup_cutoff(manifest['cutoff_at'], UNVERIFIED),
        'backup_manifest_sha256': measured,
        'database_bytes': manifest['database_artifact']['bytes'],
        'count_audit_state': evidence['coverage_ref']['audit_state'],
        'program_sha256': program['program_sha256'],
        'configuration_sha256': program['configuration_sha256'],
        'local_verification_sha256': copy_evidence(
            evidence_fd, backup_id, selection['local_verification'], 'local', output
        ),
        'local_retrieval_sha256': copy_evidence(
            evidence_fd, backup_id, selection['local_retrieval'], 'retrieval', output
        ),
    }


def assemble_index(plan, stage, output, final, input_sha):
    evidence = stage / 'backup-evidence'
    evidence.mkdir(mode=0o755)
    evidence.chmod(0o755)
    environment = plan['environment_id']
    with protected_directory(evidence) as fd:
        points = [extract_point(entry, fd, environment, output) for entry in plan['points']]
        os.fsync(fd)
    index = {
        'format_version': 1,
        **{
            key: plan[key]
            for key in (*SCOPE, 'environment_id', 'indexed_at', 'backup_policy', 'latest_attempt')
        },
        'points': points,
    }
    encoded = canonical(index)
    filename = environment + '.json'
    target = {
        'format_version': 1,
        'status': 'MANAGEMENT_BACKUP_INDEX_EXPORTED',
        **{key: plan[key] for key in (*SCOPE, 'environment_id', 'operation_id')},
        'export_policy_sha256': input_sha,
        'backup_index': {'path': str(final / filename), 'sha256': digest(encoded)},
        'backup_count': len(points),
    }
    with protected_directory(stage) as fd:
        persisted_write(fd, filename, encoded, mode=0o444)
        read_backup_index(
            SimpleNamespace(scope={key: plan[key] for key in SCOPE}),
            environment,
            (stage / filename, digest(encoded)),
            now(),
        )
        persisted_write(fd, RECEIPT, canonical(target), mode=0o444)
        os.fsync(fd)
    return target


def read_export(final, plan, input_sha):
    record = decode(read_protected(final / RECEIPT), UNVERIFIED)
    version_record(
        record,
        (
            'status',
            *SCOPE,
            'environment_id',
            'operation_id',
            'export_policy_sha256',
            'backup_index',
            'backup_count',
        ),
        UNVERIFIED,
    )
    reference = exact(record['backup_index'], ('path', 'sha256'), UNVERIFIED)
    path = final / (plan['environment_id'] + '.json')
    require(
        record['status'] == 'MANAGEMENT_BACKUP_INDEX_EXPORTED'
        and all(record[key] == plan[key] for key in (*SCOPE, 'environment_id', 'operation_id'))
        and record['export_policy_sha256'] == input_sha
        and reference['path'] == str(path)
        and sha_value(reference['sha256'])
        and type(record['backup_count']) is int
        and record['backup_count'] == len(plan['points'])
        and {item.name for item in final.iterdir()} == {path.name, RECEIPT, 'backup-evidence'},
        UNVERIFIED,
    )
    scope = SimpleNamespace(scope={key: plan[key] for key in SCOPE})
    _, points = read_backup_index(scope, plan['environment_id'], (path, reference['sha256']), now())
    support = {
        f'{point["backup_id"]}.{name}.v1.json'
        for point in plan['points']
        for field, name in (('local_verification', 'local'), ('local_retrieval', 'retrieval'))
        if point[field] is not None
    }
    with protected_directory(final / 'backup-evidence') as directory:
        require(set(os.listdir(directory)) == support, UNVERIFIED)
    require(len(points) == record['backup_count'], UNVERIFIED)
    return record


def export_management_backups(args):
    require(os.geteuid() == 0, INVALID)
    plan, output = export_inputs(args)
    final = output / plan['operation_id']
    intent = args.anchor_sha256
    with protected_directory(output) as directory:
        require(identity(os.fstat(directory)) == plan['output_identity'], INVALID)
        check_ext4(directory)
        fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if os.path.lexists(final):
            os.fsync(directory)
            return read_export(final, plan, intent)
        published = False
        try:
            with TemporaryDirectory(prefix='.backup-export-', dir=output) as temporary:
                stage = Path(temporary) / 'index'
                stage.mkdir(mode=0o755)
                stage.chmod(0o755)
                expected = assemble_index(plan, stage, output, final, intent)
                publish_directory(stage, final)
                published = True
                os.fsync(directory)
                result = read_export(final, plan, intent)
                require(result == expected, UNVERIFIED)
                return result
        except (EnvironmentFailure, OSError, ValueError, KeyError, TypeError) as error:
            if published:
                raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
            raise
