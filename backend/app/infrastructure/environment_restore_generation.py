"""Place a verified recovered database and audit assets in a distinct stable data root."""

from contextlib import ExitStack, contextmanager
from hashlib import sha256
import fcntl
import os
import stat
from tempfile import TemporaryDirectory
from pathlib import Path

from .count_audit_paths import COUNT_AUDIT_ENTRY
from .environment_backup import SNAPSHOT, snapshot_artifact
from .environment_backup_assets import (
    AUDIT_COPY,
    AUDIT_INDEX,
    audit_directory,
    audit_names,
    audit_source_name,
    file_signature,
    scan_audit,
)
from .environment_backup_package import private_root, read_policy
from .environment_backup_rehearsal import LIMITS
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
    GENERATIONS,
    GENERATION_RECEIPT,
    WORKSPACE_PURPOSES,
    identity_record,
    load_installation,
    sha_value,
    uuid_value,
    validate_target_file,
)
from .environment_recovery_installation import checked_ref, rehearsal_receipt
from .environment_recovery_restore import (
    lock_frozen_source,
    match_prepared_archive,
    prepared_restore_reference,
    restore_proof_reference,
)
from .environment_restore import RECEIPT as ARCHIVE_RECEIPT, TARGET as ARCHIVE_TARGET
from .environment_result_archive import read_sealed
from .schema_v22_publish import publish_directory

POLICY = 'restore-generation-policy.v1.json'
RECEIPT = GENERATION_RECEIPT
INVALID = 'RESTORE_GENERATION_INTENT_MISMATCH'
UNVERIFIED = 'RESTORE_GENERATION_UNVERIFIED'


def generation_plan(args):
    plan = read_policy(
        args.anchor,
        args.anchor_sha256,
        POLICY,
        ('source_installation', 'prepared_data', 'readiness', 'prepared_root'),
    )
    anchor, pin = checked_ref(plan['source_installation'], ANCHOR_NAME)
    source = load_installation(anchor, pin, args.sha256, args.project)
    prepared = prepared_restore_reference(plan['prepared_data'], code=INVALID)
    ready = restore_proof_reference(
        plan['readiness'],
        'restore-readiness.v1.json',
        'RESTORE_PREPARED_COPY_VERIFIED',
        'restore_readiness_sha256',
        code=INVALID,
    )
    directory = exact(plan['prepared_root'], ('path', 'identity'), INVALID)
    identity_record(directory['identity'], INVALID)
    target = absolute(directory['path'], INVALID)
    scope = (
        'operation_id',
        'environment_id',
        'source_control_sha256',
        'restore_preflight_sha256',
        'restore_target_data_sha256',
        'target_data_generation',
        'target_deployment_id',
        'target_configuration_sha256',
    )
    require(
        source.description['purpose'] in WORKSPACE_PURPOSES
        and 'recovery_replica' not in source.description
        and source.description['program_source']['sha256'] == args.program_sha256
        and source.environment_id == prepared['environment_id']
        and all(ready[field] == prepared[field] for field in scope)
        and sha_value(ready['read_verification_sha256'])
        and sha_value(ready['read_only_configuration_sha256'])
        and ready['read_only_configuration_sha256'] != prepared['target_configuration_sha256']
        and uuid_value(prepared['target_data_generation'])
        and prepared['target_data_generation'] != source.data_generation
        and prepared['target_data_identity'] == directory['identity']
        and target.name == prepared['operation_id']
        and not source.environment_root.is_relative_to(target)
        and not target.is_relative_to(source.environment_root),
        INVALID,
    )
    return source, prepared, ready, target


def sealed_audit(archive, source, receipt):
    raw = read_sealed(archive, AUDIT_INDEX, source)
    require(
        receipt['restored_asset_index']
        == {'name': AUDIT_INDEX, 'bytes': len(raw), 'sha256': digest(raw)},
        UNVERIFIED,
    )
    index = decode(raw, UNVERIFIED)
    state, entries = index['state'], index['entries']
    require(
        state in ('ABSENT', 'EMPTY', 'FILES')
        and type(entries) is list
        and len(entries) <= LIMITS['max_audit_files']
        and (state == 'FILES') == bool(entries),
        UNVERIFIED,
    )
    names = []
    total = 0
    for item in entries:
        entry = exact(item, ('name', 'bytes', 'sha256'), UNVERIFIED)
        name, size = entry['name'], entry['bytes']
        require(
            type(name) is str
            and COUNT_AUDIT_ENTRY.fullmatch(name) is not None
            and type(size) is int
            and 0 < size <= LIMITS['max_audit_bytes']
            and sha_value(entry['sha256']),
            UNVERIFIED,
        )
        total += size
        names.append(name)
    require(sorted(set(names)) == names and total <= LIMITS['max_audit_bytes'], UNVERIFIED)
    require(
        set(os.listdir(archive))
        == {SNAPSHOT, ARCHIVE_TARGET, ARCHIVE_RECEIPT, AUDIT_INDEX}
        | ({AUDIT_COPY} if state != 'ABSENT' else set()),
        UNVERIFIED,
    )
    if state != 'ABSENT':
        with audit_directory(
            archive, AUDIT_COPY, source.maintenance_uid, source.group, source=False
        ) as fd:
            require(audit_names(fd, LIMITS['max_audit_files']) == names, UNVERIFIED)
    return state, entries


def copy_database(archive, source, artifact, destination):
    with destination.open('xb') as file:
        measured = snapshot_artifact(
            archive,
            artifact['bytes'],
            source.maintenance_uid,
            source.group,
            expected_identity=artifact['identity'],
            sink=file,
        )
        require(measured == artifact, UNVERIFIED)
        file.flush()
        os.fchown(file.fileno(), source.maintenance_uid, source.group)
        os.fchmod(file.fileno(), 0o660)
        os.fsync(file.fileno())


def audit_matches(directory, name, owner, group, audit, *, published):
    state, entries = audit
    if not published and state == 'ABSENT':
        require(name not in os.listdir(directory), UNVERIFIED)
        return
    with audit_directory(directory, name, owner, group, source=published) as fd:
        if state == 'ABSENT':
            require(fd is None, UNVERIFIED)
            return
        require(fd is not None, UNVERIFIED)
        names = audit_names(fd, LIMITS['max_audit_files'])
        require(names == [item['name'] for item in entries], UNVERIFIED)
        for entry in entries:
            measured, _ = scan_audit(
                fd,
                entry['name'],
                owner,
                group,
                entry['bytes'],
                source=published,
            )
            require(measured == entry, UNVERIFIED)


def copy_audit(directory, archive, name, source, audit):
    state, entries = audit
    if state == 'ABSENT':
        return
    os.mkdir(name, 0o700, dir_fd=directory)
    with (
        closing_directory(directory, name) as target,
        audit_directory(
            archive, AUDIT_COPY, source.maintenance_uid, source.group, source=False
        ) as archived,
    ):
        for entry in entries:
            measured, _ = scan_audit(
                archived,
                entry['name'],
                source.maintenance_uid,
                source.group,
                entry['bytes'],
                source=False,
                output=target,
            )
            require(measured == entry, UNVERIFIED)
            flags = os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW
            with os.fdopen(os.open(entry['name'], flags, dir_fd=target), 'r+b') as file:
                os.fchown(file.fileno(), source.application_uid, source.group)
                os.fchmod(file.fileno(), 0o600)
                os.fsync(file.fileno())
        os.fchown(target, source.application_uid, source.group)
        os.fchmod(target, 0o700)
        os.fsync(target)


def read_database(directory, name, source, expected):
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(name, flags, dir_fd=directory), 'rb') as file:
        before = os.fstat(file.fileno())
        observed = validate_target_file(source, before)
        require(before.st_size == expected['bytes'], UNVERIFIED)
        no_acl(file.fileno())
        checksum = sha256()
        size = 0
        while block := file.read(128 * 1024):
            size += len(block)
            require(size <= expected['bytes'], UNVERIFIED)
            checksum.update(block)
        require(
            size == expected['bytes']
            and checksum.hexdigest() == expected['sha256']
            and file_signature(before)
            == file_signature(os.fstat(file.fileno()))
            == file_signature(os.stat(name, dir_fd=directory, follow_symlinks=False)),
            UNVERIFIED,
        )
    return observed


@contextmanager
def closing_directory(parent, name):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(name, flags, dir_fd=parent)
    try:
        no_acl(fd)
        check_ext4(fd)
        yield fd
    finally:
        os.close(fd)


def read_generation(path, source, archive_receipt, audit):
    database_name = source.database_relative.name
    audit_name = audit_source_name(source)
    expected = {database_name}
    if audit[0] != 'ABSENT':
        expected.add(audit_name)
    with protected_directory(path) as parent, closing_directory(parent, 'data') as data:
        metadata = os.fstat(data)
        require(
            (metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode))
            == (0, source.group, 0o2770)
            and identity(metadata) != source.roots['data']
            and set(os.listdir(data)) == expected,
            UNVERIFIED,
        )
        database = read_database(data, database_name, source, archive_receipt['database_artifact'])
        audit_matches(data, audit_name, source.application_uid, source.group, audit, published=True)
        return {'data_identity': identity(metadata), 'database_identity': database}


def populate_generation(staging, source, archive, archive_receipt, audit):
    staging.mkdir(mode=0o755)
    staging.chmod(0o755)
    with protected_directory(staging) as parent:
        os.mkdir('data', 0o700, dir_fd=parent)
        with closing_directory(parent, 'data') as data:
            copy_database(
                archive,
                source,
                archive_receipt['database_artifact'],
                staging / 'data' / source.database_relative.name,
            )
            copy_audit(data, archive, audit_source_name(source), source, audit)
            os.fchown(data, 0, source.group)
            os.fchmod(data, 0o2770)
            os.fsync(data)
        os.fsync(parent)


def prepare_restore_generation(args, entry, hosts):
    require(os.geteuid() == 0, INVALID)
    source, prepared, ready, origin = generation_plan(args)
    with ExitStack() as resources:
        lock = lock_frozen_source(resources, args, entry, hosts, source, prepared, code=UNVERIFIED)
        archive = resources.enter_context(
            private_root(origin, prepared['target_data_identity'], source)
        )
        fcntl.flock(archive, fcntl.LOCK_SH | fcntl.LOCK_NB)
        restored, _ = rehearsal_receipt(
            archive,
            source,
            prepared['target_restore_receipt_sha256'],
            prepared=prepared,
        )
        match_prepared_archive(prepared, restored, code=UNVERIFIED)
        audit = sealed_audit(archive, source, restored)
        home = source.environment_root / GENERATIONS
        stable = resources.enter_context(protected_directory(source.environment_root))
        if not os.path.lexists(home):
            home.mkdir(mode=0o755)
            home.chmod(0o755)
            os.fsync(stable)
        parent = resources.enter_context(protected_directory(home))
        check_ext4(parent)
        metadata = os.fstat(parent)
        require(
            (metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode)) == (0, 0, 0o755)
            and metadata.st_dev == os.fstat(stable).st_dev,
            UNVERIFIED,
        )
        final = home / prepared['target_data_generation']
        common = {
            'format_version': 1,
            'status': 'RESTORE_GENERATION_PREPARED_CLOSED',
            **{
                field: prepared[field]
                for field in (
                    'operation_id',
                    'environment_id',
                    'source_control_sha256',
                    'source_database_identity',
                    'target_data_generation',
                    'target_deployment_id',
                    'target_configuration_sha256',
                    'target_database_sha256',
                    'target_asset_index_sha256',
                    'restore_target_data_sha256',
                )
            },
            'restore_readiness_sha256': ready['restore_readiness_sha256'],
            'generation_policy_sha256': args.anchor_sha256,
            'data_root': str(final / 'data'),
            'outbound_hold_required': True,
        }

        def confirm():
            lock.assert_owned()
            with protected_directory(final) as directory:
                require(set(os.listdir(directory)) == {'data', RECEIPT}, UNVERIFIED)
            observed = {**common, **read_generation(final, source, restored, audit)}
            require(read_protected(final / RECEIPT) == canonical(observed), UNVERIFIED)
            os.fsync(parent)
            os.fsync(stable)
            return {**observed, 'restore_generation_sha256': digest(canonical(observed))}

        if os.path.lexists(final):
            artifact = restored['database_artifact']
            measured = snapshot_artifact(
                archive,
                artifact['bytes'],
                source.maintenance_uid,
                source.group,
                expected_identity=artifact['identity'],
            )
            require(measured == artifact, UNVERIFIED)
            audit_matches(
                archive,
                AUDIT_COPY,
                source.maintenance_uid,
                source.group,
                audit,
                published=False,
            )
            return confirm()
        with TemporaryDirectory(prefix='.restore-generation-', dir=home) as temporary:
            staging = Path(temporary) / 'generation'
            populate_generation(staging, source, archive, restored, audit)
            record = {**common, **read_generation(staging, source, restored, audit)}
            with protected_directory(staging) as private:
                persisted_write(private, RECEIPT, canonical(record), mode=0o444)
            lock.assert_owned()
            source.check_hold()
            publish_directory(staging, final)
            try:
                return confirm()
            except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
                raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
