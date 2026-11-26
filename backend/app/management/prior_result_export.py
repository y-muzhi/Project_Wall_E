"""Export the original command metadata for a confirmed closed or opened restore."""

from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from backend.app.infrastructure.environment_backup_assets import audit_directory
from backend.app.infrastructure.environment_backup_package import (
    RESULTS,
    check_evidence,
    private_root,
    read_evidence,
    read_manifest,
    read_package_index,
    read_policy,
    validate_location,
)
from backend.app.infrastructure.environment_control import read_control, read_release_transition
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
    ANCHOR_NAME,
    RESTORE_MODE,
    identity_record,
    load_installation,
    sha_value,
    uuid_value,
)
from backend.app.infrastructure.environment_lock import NativeEnvironmentFiles
from backend.app.infrastructure.environment_release_gateway import (
    load_site,
    same_previous_installation,
)
from backend.app.infrastructure.environment_recovery_installation import checked_ref
from backend.app.infrastructure.environment_result_archive import (
    parse_shard,
    read_sealed,
    shard_name,
)
from backend.app.infrastructure.schema_v22_publish import publish_directory

from .prior_result_view import INDEX, archived_index, archived_shard

POLICY = 'prior-command-export-policy.v1.json'
INVALID = 'PRIOR_COMMAND_EXPORT_INTENT_MISMATCH'
UNVERIFIED = 'PRIOR_COMMAND_EXPORT_UNVERIFIED'
EXPORT = 'prior-command-export.v1.json'


@dataclass(frozen=True)
class ArchiveSelection:
    generation: str
    manifest_sha256: str
    index_sha256: str
    request: dict


def export_source(args, entry):
    plan = read_policy(
        args.anchor,
        args.anchor_sha256,
        POLICY,
        (
            'operation_id',
            'source_installation',
            'target_installation',
            'transition_sha256',
            'preserved_package',
            'selected_package',
            'output_directory',
            'output_identity',
        ),
    )
    require(uuid_value(plan['operation_id']) and sha_value(plan['transition_sha256']), INVALID)
    active = SimpleNamespace(runtime_manifest_sha256=args.sha256)
    anchor, pin = checked_ref(plan['source_installation'], ANCHOR_NAME)
    record = decode(read_protected(anchor), INVALID)
    source = load_installation(anchor, pin, args.sha256, absolute(record['project'], INVALID))
    target = load_site(plan['target_installation'], active, entry)
    binding = target.description.get('deployment_slot')
    require(
        target.project == args.project
        and binding is not None
        and binding['authorization_mode'] == RESTORE_MODE
        and target.environment_root == source.environment_root
        and target.lock_identity == source.lock_identity
        and target.roots['control'] == source.roots['control'],
        INVALID,
    )
    native = NativeEnvironmentFiles(args.root)
    with target.directory(native, 'control') as fd:
        current = read_control(fd, target)
        transition = read_release_transition(fd, target, plan['operation_id'])
        after = transition['after']
        require(
            digest(canonical(transition)) == plan['transition_sha256']
            and same_previous_installation(source, transition)
            and current['control_revision'] >= after['control_revision']
            and (current == after or current['last_opened_deployment_id'] == target.deployment_id)
            and read_control(fd, target) == current,
            UNVERIFIED,
        )
    current_generation = transition['before']['data_generation']
    selected_generation = transition['selected_source_data_generation']
    preserved = ArchiveSelection(
        current_generation,
        transition['backup_manifest_sha256'],
        transition['preserved_result_index_sha256'],
        archive_request(plan['preserved_package']),
    )
    selected = ArchiveSelection(
        selected_generation,
        transition['selected_backup_manifest_sha256'],
        transition['selected_result_index_sha256'],
        archive_request(plan['selected_package']),
    )
    output = validate_location(
        plan,
        'output_directory',
        'output_identity',
        (
            source.environment_root,
            args.root,
            args.project,
            args.anchor.parent,
            Path(preserved.request['path']),
            Path(selected.request['path']),
        ),
    )
    archives = [preserved]
    if selected_generation != current_generation:
        archives.append(selected)
    return plan, source, output, archives


def archive_request(item):
    exact(item, ('path', 'identity', 'backup_id'), INVALID)
    absolute(item['path'], INVALID)
    identity_record(item['identity'], INVALID)
    require(uuid_value(item['backup_id']), INVALID)
    return item


def copy_archive(source, operation, archive, output):
    request = archive.request
    folder = absolute(request['path'], INVALID)
    with private_root(folder, request['identity'], source) as package:
        fcntl.flock(package, fcntl.LOCK_SH | fcntl.LOCK_NB)
        manifest, manifest_sha = read_manifest(
            package, source, request['backup_id'], expected_manifest=archive.manifest_sha256
        )
        require(
            manifest['source_environment_id'] == source.environment_id
            and manifest['source_data_generation'] == archive.generation
            and manifest['original_result_index_ref']['sha256'] == archive.index_sha256,
            UNVERIFIED,
        )
        evidence = read_evidence(package, source, manifest)
        capture = check_evidence(manifest, evidence, None)
        output.mkdir(mode=0o755)
        output.chmod(0o755)
        with (
            audit_directory(
                package, RESULTS, source.maintenance_uid, source.group, source=False
            ) as index_fd,
            protected_directory(output) as destination,
        ):
            reference = manifest['original_result_index_ref']
            index = read_package_index(index_fd, source, capture, reference)
            for bucket, shard in index['shards'].items():
                name = shard_name(bucket)
                raw = read_sealed(index_fd, name, source)
                parse_shard(raw, bucket, shard, index['policy_sha256'])
                persisted_write(destination, name, raw, mode=0o444)
            envelope = {
                'format_version': 1,
                'status': 'PRIOR_COMMAND_INDEX_EXPORTED',
                'operation_id': operation,
                'environment_id': source.environment_id,
                'source_data_generation': archive.generation,
                'source_deployment_id': capture['deployment_id'],
                'source_control_revision': capture['control_revision'],
                'backup_manifest_sha256': manifest_sha,
                'index_sha256': archive.index_sha256,
                **{
                    field: index[field]
                    for field in (
                        'capture_receipt_sha256',
                        'policy_sha256',
                        'entry_count',
                        'shards',
                    )
                },
            }
            raw = canonical(envelope)
            persisted_write(destination, INDEX, raw, mode=0o444)
            require(read_package_index(index_fd, source, capture, reference) == index, UNVERIFIED)
            os.fsync(destination)
    return digest(raw)


def receipt_shape(plan, source, policy_sha, indexes):
    return {
        'format_version': 1,
        'status': 'PRIOR_COMMAND_RESULTS_EXPORTED',
        'operation_id': plan['operation_id'],
        'environment_id': source.environment_id,
        'transition_sha256': plan['transition_sha256'],
        'export_policy_sha256': policy_sha,
        'indexes': indexes,
    }


def confirm_export(final, plan, source, archives, policy_sha):
    result = decode(read_protected(final / EXPORT), UNVERIFIED)
    indexes = result['indexes']
    require(
        type(indexes) is dict
        and set(indexes) == {archive.generation for archive in archives}
        and result == receipt_shape(plan, source, policy_sha, indexes),
        UNVERIFIED,
    )
    with protected_directory(final) as directory:
        require(set(os.listdir(directory)) == {EXPORT, *indexes}, UNVERIFIED)
    for archive in archives:
        identifier = archive.generation
        reference = exact(indexes[identifier], ('path', 'sha256'), UNVERIFIED)
        locator, pin = reference['path'], reference['sha256']
        path = final / identifier / INDEX
        require(locator == str(path), UNVERIFIED)
        record = archived_index(path, pin, source.environment_id, identifier)
        require(
            record['operation_id'] == plan['operation_id']
            and record['backup_manifest_sha256'] == archive.manifest_sha256
            and record['index_sha256'] == archive.index_sha256,
            UNVERIFIED,
        )
        with protected_directory(path.parent) as directory:
            require(
                set(os.listdir(directory))
                == {INDEX, *(shard_name(bucket) for bucket in record['shards'])},
                UNVERIFIED,
            )
        for bucket in record['shards']:
            archived_shard(path, record, bucket)
    return result


def export_prior_results(args, entry):
    require(os.geteuid() == 0, INVALID)
    plan, source, output, archives = export_source(args, entry)
    final = output / plan['operation_id']
    with protected_directory(output) as parent:
        require(identity(os.fstat(parent)) == plan['output_identity'], INVALID)
        check_ext4(parent)
        fcntl.flock(parent, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if os.path.lexists(final):
            result = confirm_export(final, plan, source, archives, args.anchor_sha256)
            os.fsync(parent)
            return result
        with TemporaryDirectory(prefix='.prior-command-export-', dir=output) as temporary:
            stage = Path(temporary) / 'export'
            stage.mkdir(mode=0o755)
            stage.chmod(0o755)
            indexes = {}
            for archive in archives:
                identifier = archive.generation
                measured = copy_archive(source, plan['operation_id'], archive, stage / identifier)
                indexes[identifier] = {'path': str(final / identifier / INDEX), 'sha256': measured}
            expected = receipt_shape(plan, source, args.anchor_sha256, indexes)
            with protected_directory(stage) as fd:
                persisted_write(fd, EXPORT, canonical(expected), mode=0o444)
                os.fsync(fd)
            publish_directory(stage, final)
            try:
                os.fsync(parent)
                require(
                    confirm_export(final, plan, source, archives, args.anchor_sha256) == expected,
                    UNVERIFIED,
                )
            except (OSError, ValueError, RuntimeError, TypeError, KeyError) as error:
                raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
            return expected
