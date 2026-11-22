"""Prepare a detached, permanently read-only replica from one rehearsed backup."""

from contextlib import ExitStack
from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from backend.app.management.release_artifacts import indexed_files, snapshot_file

from .environment_backup import SNAPSHOT, snapshot_artifact
from .environment_backup_package import private_root, validate_location
from .environment_control import (
    CONTROL_NAME,
    initial_control,
    maintained_control,
    maintenance_name,
    read_control,
)
from .environment_files import (
    EnvironmentFailure,
    absolute,
    canonical,
    check_ext4,
    decode,
    digest,
    exact,
    identity,
    no_acl,
    persisted_write,
    protected_directory,
    read_protected,
    require,
)
from .environment_installation import (
    ANCHOR_NAME,
    CONFIG_NAME,
    RECOVERY_EVIDENCE,
    RECOVERY_FRONTEND_INDEX,
    WORKSPACE_PURPOSES,
    Installation,
    identity_record,
    load_installation,
    sha_value,
    uuid_value,
    version_record,
)
from .environment_provision import (
    _initialize_host,
    _reserve_identities,
    create_installation_files,
    installer_lock,
)
from .environment_recovery_read import (
    POLICY as READ_POLICY,
    SCOPES,
    TUPLE_FIELDS,
    read_policy as read_scope,
)
from .environment_restore import RECEIPT
from .environment_result_archive import read_sealed
from .schema_v22_publish import publish_directory

POLICY = 'recovery-replica-policy.v1.json'
INSTALL_RECEIPT = 'recovery-replica-receipt.v1.json'
DATABASE = 'wall-e.sqlite'
INVALID = 'RECOVERY_REPLICA_INTENT_MISMATCH'
UNVERIFIED = 'RECOVERY_REPLICA_UNVERIFIED'


@dataclass(frozen=True)
class RehearsedDatabase:
    installation: Installation
    descriptor: int
    receipt: dict
    receipt_bytes: bytes


def checked_ref(reference, name):
    exact(reference, ('path', 'sha256'), INVALID)
    path = absolute(reference['path'], INVALID)
    require(path.name == name and sha_value(reference['sha256']), INVALID)
    return path, reference['sha256']


def open_source(args, plan):
    anchor, anchor_sha = checked_ref(plan['source_installation'], ANCHOR_NAME)
    raw = read_protected(anchor)
    require(digest(raw) == anchor_sha, INVALID)
    details = decode(raw, INVALID)
    program = absolute(details['project'], INVALID)
    source = load_installation(anchor, anchor_sha, args.sha256, program)
    require(
        source.description['purpose'] in WORKSPACE_PURPOSES
        and 'recovery_replica' not in source.description
        and {plan['application_uid'], plan['maintenance_uid']}.isdisjoint(
            {source.application_uid, source.maintenance_uid}
        )
        and plan['shared_gid'] not in (source.group, source.ingress_group)
        and plan['deployment_id'] != source.deployment_id,
        INVALID,
    )
    return source


def load_plan(args):
    require(args.anchor.name == POLICY and sha_value(args.anchor_sha256), INVALID)
    raw = read_protected(args.anchor)
    require(digest(raw) == args.anchor_sha256, INVALID)
    plan = decode(raw, INVALID)
    operations = ('initial_operation_id', 'operation_id', 'run_id', 'deployment_id')
    identities = ('application_uid', 'maintenance_uid', 'shared_gid')
    regular = {key: value for key, value in plan.items() if key != 'fixed_restore'}
    version_record(
        regular,
        (
            *operations,
            *identities,
            'source_installation',
            'rehearsal',
            'host_root',
            'host_identity',
            'staging_root',
            'staging_identity',
            'frontend_directory',
            'frontend_index',
            'program_sha256',
        ),
        INVALID,
    )
    require(
        all(uuid_value(plan[field]) for field in operations)
        and len({plan[field] for field in operations}) == len(operations)
        and all(type(plan[field]) is int and 1 <= plan[field] < 2**31 for field in identities)
        and plan['application_uid'] != plan['maintenance_uid']
        and plan['program_sha256'] == args.program_sha256,
        INVALID,
    )
    source = open_source(args, plan)
    rehearsal = exact(plan['rehearsal'], ('path', 'identity', 'receipt_sha256'), INVALID)
    identity_record(rehearsal['identity'], INVALID)
    require(sha_value(rehearsal['receipt_sha256']), INVALID)
    source_rehearsal = absolute(rehearsal['path'], INVALID)
    frontend = absolute(plan['frontend_directory'], INVALID)
    index, index_sha = checked_ref(plan['frontend_index'], RECOVERY_FRONTEND_INDEX)
    approved = None
    schema = source.schema
    if 'fixed_restore' in plan:
        from .environment_recovery_restore import approve_fixed_restore

        approved, schema = approve_fixed_restore(args, plan, source, frontend, index, index_sha)
    boundaries = (
        args.root,
        args.project,
        args.anchor.parent,
        source.environment_root.parent,
        source.schema,
        schema,
        source_rehearsal,
        frontend,
        index.parent,
    )
    host = validate_location(plan, 'host_root', 'host_identity', boundaries)
    staging = validate_location(plan, 'staging_root', 'staging_identity', (*boundaries, host))
    socket_path = host / source.environment_id / 'runtime' / 'walle.sock'
    require(len(os.fsencode(socket_path)) <= 107, INVALID)
    installation_args = SimpleNamespace(
        host_root=host,
        project=args.project,
        schema=schema,
        frontend_input=frontend,
        application_uid=plan['application_uid'],
        maintenance_uid=plan['maintenance_uid'],
        group=plan['shared_gid'],
        ingress_group=None,
        purpose=source.description['purpose'],
        runtime_sha256=args.sha256,
        restore_preparation=approved,
    )
    measured, index_raw = snapshot_file(index, 0o444, capture=True)
    require(measured == index_sha, INVALID)
    return plan, source, source_rehearsal, installation_args, staging, index_raw


def rehearsal_receipt(fd, source, pin, *, prepared=None):
    raw = read_sealed(fd, RECEIPT, source)
    require(digest(raw) == pin, UNVERIFIED)
    record = decode(raw, UNVERIFIED)
    original = (source.data_generation, source.deployment_id)
    if prepared is not None:
        original = (
            prepared['selected_source_data_generation'],
            prepared['selected_source_deployment_id'],
        )
    artifact = exact(record['database_artifact'], ('identity', 'bytes', 'sha256'), UNVERIFIED)
    require(
        not set(os.listdir(fd)) & {SNAPSHOT + name for name in ('-wal', '-shm', '-journal')},
        UNVERIFIED,
    )
    identity_record(artifact['identity'], UNVERIFIED)
    require(
        record['format_version'] == 2
        and record['status'] == 'DATABASE_AND_COUNT_AUDIT_RESTORE_VERIFIED'
        and record['source_environment_id'] == source.environment_id
        and (record['source_data_generation'], record['source_deployment_id']) == original
        and uuid_value(record['target_data_generation'])
        and record['target_data_generation'] not in (source.data_generation, original[0])
        and record['outbound_hold_required'] is True
        and all(
            sha_value(record[key])
            for key in ('backup_manifest_sha256', 'rehearsal_policy_sha256', 'content_sha256')
        )
        and type(artifact['bytes']) is int
        and 0 < artifact['bytes'] <= 1024**4
        and sha_value(artifact['sha256']),
        UNVERIFIED,
    )
    return record, raw


def replica_binding(plan, receipt, policy_sha):
    return {
        'operation_id': plan['operation_id'],
        'run_id': plan['run_id'],
        'preparation_policy_sha256': policy_sha,
        'backup_manifest_sha256': receipt['backup_manifest_sha256'],
        'rehearsal_receipt_sha256': plan['rehearsal']['receipt_sha256'],
        'frontend_index_sha256': plan['frontend_index']['sha256'],
    }


def replica_database(source_fd, source, receipt, path, gid):
    source_artifact = receipt['database_artifact']
    with path.open('xb') as sink:
        measured = snapshot_artifact(
            source_fd,
            source_artifact['bytes'],
            source.maintenance_uid,
            source.group,
            expected_identity=source_artifact['identity'],
            sink=sink,
        )
        require(measured == source_artifact, UNVERIFIED)
        sink.flush()
        os.fchown(sink.fileno(), 0, gid)
        os.fchmod(sink.fileno(), 0o440)
        os.fsync(sink.fileno())
        facts = os.fstat(sink.fileno())
    return {'identity': identity(facts), 'bytes': measured['bytes'], 'sha256': measured['sha256']}


def owned_control(directory, name, value, installation):
    persisted_write(directory, name, canonical(value), mode=0o440)
    fd = os.open(name, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
    try:
        os.fchown(fd, installation.maintenance_uid, installation.group)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(directory)


def prepare_contents(root, final, args, facts, plan, rehearsal, index_raw, bind):
    with protected_directory(root / 'data') as directory:
        database = replica_database(
            rehearsal.descriptor,
            rehearsal.installation,
            rehearsal.receipt,
            root / 'data' / DATABASE,
            args.group,
        )
        os.fsync(directory)
    configuration = read_protected(root / CONFIG_NAME)
    placement = SimpleNamespace(
        **{name: facts[name] for name in TUPLE_FIELDS if name != 'configuration_sha256'},
        configuration_sha256=digest(configuration),
        description=decode(configuration, UNVERIFIED),
        maintenance_uid=args.maintenance_uid,
        group=args.group,
        path=lambda kind: final / kind,
    )
    before = initial_control(placement, plan['initial_operation_id'])
    hold = maintained_control(before, plan['operation_id'], bind['preparation_policy_sha256'])
    intent = {
        'format_version': 1,
        'operation_id': plan['operation_id'],
        'plan_sha256': bind['preparation_policy_sha256'],
        'before_sha256': digest(canonical(before)),
        'before': before,
    }
    with protected_directory(root / 'control') as directory:
        owned_control(directory, maintenance_name(plan['operation_id']), intent, placement)
        owned_control(directory, CONTROL_NAME, hold, placement)
    evidence = root / RECOVERY_EVIDENCE
    evidence.mkdir(mode=0o755)
    evidence.chmod(0o755)
    policy = {
        'format_version': 1,
        'operation_id': plan['operation_id'],
        'run_id': plan['run_id'],
        **{key: getattr(placement, key) for key in TUPLE_FIELDS},
        'installation_sha256': facts['anchor_sha256'],
        'control_revision': hold['control_revision'],
        'control_sha256': digest(canonical(hold)),
        'database': database,
        'verified_scopes': list(SCOPES),
        'rehearsal_receipt': {
            'path': str(final / RECOVERY_EVIDENCE / RECEIPT),
            'sha256': bind['rehearsal_receipt_sha256'],
        },
    }
    policy_raw = canonical(policy)
    prepared = {
        'format_version': 1,
        'status': 'RECOVERY_REPLICA_PREPARED',
        **facts,
        'operation_id': plan['operation_id'],
        'run_id': plan['run_id'],
        'preparation_policy_sha256': bind['preparation_policy_sha256'],
        'recovery_read_policy': str(final / RECOVERY_EVIDENCE / READ_POLICY),
        'recovery_read_policy_sha256': digest(policy_raw),
    }
    with protected_directory(evidence) as directory:
        for name, raw in (
            (RECEIPT, rehearsal.receipt_bytes),
            (RECOVERY_FRONTEND_INDEX, index_raw),
            (READ_POLICY, policy_raw),
            (INSTALL_RECEIPT, canonical(prepared)),
        ):
            persisted_write(directory, name, raw, mode=0o444)
    with protected_directory(root) as directory:
        os.fsync(directory)
    return prepared


def read_prepared(final, args, plan, identities, binding, index_raw):
    evidence = final / RECOVERY_EVIDENCE
    prepared = decode(read_protected(evidence / INSTALL_RECEIPT), UNVERIFIED)
    version_record(
        prepared,
        (
            'status',
            'anchor',
            'anchor_sha256',
            'environment_id',
            'data_generation',
            'deployment_id',
            'operation_id',
            'run_id',
            'preparation_policy_sha256',
            'recovery_read_policy',
            'recovery_read_policy_sha256',
        ),
        UNVERIFIED,
    )
    anchor = final / ANCHOR_NAME
    record = load_installation(anchor, prepared['anchor_sha256'], args.runtime_sha256, args.project)
    require(
        prepared['status'] == 'RECOVERY_REPLICA_PREPARED'
        and prepared['anchor'] == str(anchor)
        and prepared['recovery_read_policy'] == str(evidence / READ_POLICY)
        and prepared['operation_id'] == plan['operation_id']
        and prepared['run_id'] == plan['run_id']
        and prepared['preparation_policy_sha256'] == binding['preparation_policy_sha256']
        and record.description['recovery_replica'] == binding
        and record.schema == args.schema
        and (record.environment_id, record.data_generation, record.deployment_id) == identities
        and tuple(prepared[field] for field in TUPLE_FIELDS[:3]) == identities
        and (record.application_uid, record.maintenance_uid, record.group)
        == (args.application_uid, args.maintenance_uid, args.group),
        UNVERIFIED,
    )
    policy = read_scope(evidence / READ_POLICY, prepared['recovery_read_policy_sha256'])
    receipt_raw = read_protected(evidence / RECEIPT)
    restore = decode(receipt_raw, UNVERIFIED)
    require(
        all(policy[key] == getattr(record, key) for key in TUPLE_FIELDS)
        and policy['installation_sha256'] == prepared['anchor_sha256']
        and policy['operation_id'] == plan['operation_id']
        and policy['run_id'] == plan['run_id']
        and policy['rehearsal_receipt']
        == {
            'path': str(evidence / RECEIPT),
            'sha256': binding['rehearsal_receipt_sha256'],
        }
        and digest(receipt_raw) == binding['rehearsal_receipt_sha256']
        and all(
            policy['database'][key] == restore['database_artifact'][key]
            for key in ('bytes', 'sha256')
        ),
        UNVERIFIED,
    )
    with protected_directory(record.path('control')) as fd:
        props = os.fstat(fd)
        require(
            identity(props) == record.roots['control']
            and (props.st_gid, stat.S_IMODE(props.st_mode)) == (record.group, 0o550),
            UNVERIFIED,
        )
        control = read_control(fd, record)
        expected_control = maintained_control(
            initial_control(record, plan['initial_operation_id']),
            plan['operation_id'],
            binding['preparation_policy_sha256'],
        )
        require(
            control == expected_control
            and policy['control_revision'] == control['control_revision']
            and digest(canonical(control)) == policy['control_sha256'],
            UNVERIFIED,
        )
    with protected_directory(record.path('data')) as fd:
        meta = os.fstat(fd)
        props = os.stat(DATABASE, dir_fd=fd, follow_symlinks=False)
        require(
            identity(meta) == record.roots['data']
            and (meta.st_gid, stat.S_IMODE(meta.st_mode)) == (record.group, 0o550)
            and (props.st_uid, props.st_gid) == (0, record.group)
            and identity(props) == policy['database']['identity']
            and set(os.listdir(fd)) == {DATABASE},
            UNVERIFIED,
        )
    measured, _ = snapshot_file(record.database, 0o440, policy['database']['bytes'])
    require(measured == policy['database']['sha256'], UNVERIFIED)
    frontend_sha, indexed = snapshot_file(evidence / RECOVERY_FRONTEND_INDEX, 0o444, capture=True)
    require(frontend_sha == binding['frontend_index_sha256'] and indexed == index_raw, UNVERIFIED)
    indexed_files(decode(index_raw, INVALID), record.path('frontend'), 'frontend')
    return prepared


def prepare_recovery_replica(args, entry, runtime_hosts):
    require(os.geteuid() == 0, INVALID)
    plan, source, archive, target, staging, index_raw = load_plan(args)
    front_index = decode(index_raw, INVALID)
    indexed_files(front_index, target.frontend_input, 'frontend')
    with ExitStack() as resources:
        prepared = target.restore_preparation
        if prepared is not None:
            from .environment_recovery_restore import lock_frozen_source

            lock_frozen_source(resources, args, entry, runtime_hosts, source, prepared)
        host_fd = resources.enter_context(
            installer_lock(target.host_root, expected_identity=plan['host_identity'])
        )
        staging_fd = resources.enter_context(protected_directory(staging))
        host_meta, stage_meta = os.fstat(host_fd), os.fstat(staging_fd)
        check_ext4(host_fd)
        check_ext4(staging_fd)
        no_acl(staging_fd)
        require(
            identity(host_meta) == plan['host_identity']
            and identity(stage_meta) == plan['staging_identity']
            and host_meta.st_dev == stage_meta.st_dev
            and stat.S_IMODE(stage_meta.st_mode) == 0o700,
            INVALID,
        )
        archive_fd = resources.enter_context(
            private_root(archive, plan['rehearsal']['identity'], source)
        )
        fcntl.flock(archive_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        receipt, raw = rehearsal_receipt(
            archive_fd, source, plan['rehearsal']['receipt_sha256'], prepared=prepared
        )
        if prepared is not None:
            from .environment_recovery_restore import match_prepared_archive

            match_prepared_archive(prepared, receipt)
        rehearsal = RehearsedDatabase(source, archive_fd, receipt, raw)
        identities = (
            source.environment_id,
            receipt['target_data_generation'],
            plan['deployment_id'],
        )
        binding = replica_binding(plan, receipt, args.anchor_sha256)
        final = target.host_root / source.environment_id
        _initialize_host(host_fd, target.host_root)
        if os.path.lexists(final):
            os.fsync(host_fd)
            return read_prepared(final, target, plan, identities, binding, index_raw)
        _reserve_identities(target)
        published = False
        try:
            with TemporaryDirectory(prefix='.replica-', dir=staging) as temporary:
                work = Path(temporary) / 'installation'
                facts = create_installation_files(
                    target,
                    host_fd,
                    replica=SimpleNamespace(identities=identities, binding=binding),
                    staging=work,
                )
                indexed_files(front_index, work / 'frontend', 'frontend')
                expected = prepare_contents(
                    work,
                    final,
                    target,
                    facts,
                    plan,
                    rehearsal,
                    index_raw,
                    binding,
                )
                publish_directory(work, final)
                published = True
                os.fsync(host_fd)
                os.fsync(staging_fd)
                observed = read_prepared(final, target, plan, identities, binding, index_raw)
                require(observed == expected, UNVERIFIED)
                return observed
        except (EnvironmentFailure, OSError, KeyError, ValueError, TypeError) as error:
            if published:
                raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
            raise
