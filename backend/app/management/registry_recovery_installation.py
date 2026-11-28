"""Place a pinned recovered database in a new, inactive registry installation slot."""

from contextlib import ExitStack, contextmanager
from hashlib import file_digest
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.app.infrastructure.environment_backup import snapshot_artifact
from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    check_ext4,
    decode,
    digest,
    exact,
    identity,
    no_acl,
    persisted_write,
    protected_directory,
    read_entry,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value
from backend.app.infrastructure.schema_v22_publish import publish_directory

from .registry import allow_file, is_timestamp
from .registry_dispatch import dispatch_lock
from .registry_dispatch import OPEN_INTENT, RETIRED_HOLD
from .registry_installation import (
    ANCHOR_NAME,
    DATABASE_NAME,
    GENERATIONS,
    SOURCE_ANCHOR,
    load_installation,
    require_registry_root,
)
from .registry_recovery import (
    STORE,
    recovery_file_receipt,
    recovery_scope,
    verify_pause,
)
from .registry_snapshot import MAX_SQLITE_BYTES, snapshot_directory

RECEIPT = 'registry-recovery-installation.v1.json'
HOST_OBSERVATIONS = 'recovery-host-observations'
SELECTION_RECEIPT = 'registry-recovery-selection.v1.json'
ENTRY_INPUTS = 'registry-recovery-entry-inputs'
RECOVERY_ENTRY = 'registry-recovery-entry'
ENTRY_INTENT = 'registry-recovery-entry-admission-intent.v1.json'
ENTRY_ADMISSION = 'registry-recovery-entry-admission.v1.json'
PLACED = 'MANAGEMENT_REGISTRY_INSTALLATION_PLACED_CLOSED'
UNVERIFIED = 'MANAGEMENT_REGISTRY_INSTALLATION_UNVERIFIED'


def placement_scope(installation, args, recovery, source):
    return {
        'format_version': 1,
        'status': PLACED,
        'operation_id': recovery['operation_id'],
        'source_registry_generation': installation.registry_generation,
        'source_registry_anchor_sha256': installation.sha256,
        'target_registry_generation': recovery['target_registry_generation'],
        'dispatch_hold_sha256': recovery['dispatch_hold_sha256'],
        'recovery_policy_sha256': recovery['recovery_policy_sha256'],
        'recovery_preparation_sha256': args.registry_recovery_receipt_sha256,
        'source_database_bytes': source['database_artifact']['bytes'],
        'source_database_sha256': source['database_artifact']['sha256'],
        'prepared_at': source['prepared_at'],
        'schema_version': source['schema_version'],
    }


@contextmanager
def new_generation_root(native, installation, root):
    stable = installation.anchor.parent
    if GENERATIONS not in os.listdir(root):
        with TemporaryDirectory(prefix='.walle-registry-slots-', dir=stable) as temporary:
            stage = Path(temporary)
            with protected_directory(stage) as staged:
                os.fchown(staged, 0, installation.gid)
                os.fchmod(staged, 0o2750)
                os.fsync(staged)
            publish_directory(stage, stable / GENERATIONS)
    fd = native.open_beneath(root, GENERATIONS, os.O_DIRECTORY | os.O_RDONLY)
    try:
        meta = os.fstat(fd)
        require(meta.st_uid == 0, UNVERIFIED)
        require_registry_root(meta, identity(meta), installation.gid)
        no_acl(fd)
        check_ext4(fd)
        os.fsync(root)
        yield fd
    finally:
        os.close(fd)


def place_database(native, prior, source, original, directory):
    flags = os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = native.open_beneath(directory, DATABASE_NAME, flags, 0o600)
    with os.fdopen(fd, 'wb') as output:
        measured = snapshot_artifact(source, MAX_SQLITE_BYTES, prior.uid, prior.gid, sink=output)
        require(measured == original, UNVERIFIED)
        os.fchown(output.fileno(), prior.uid, prior.gid)
        os.fchmod(output.fileno(), 0o600)
        output.flush()
        os.fsync(output.fileno())
        return identity(os.fstat(output.fileno()))


def anchor_for_slot(prior, args, scope, root_identity, directories, database):
    return {
        'format_version': 2,
        'root': str(prior.anchor.parent),
        'root_identity': prior.root_facts,
        'manager_id': prior.manager_id,
        'host_id': prior.host_id,
        'manager_uid': prior.uid,
        'manager_gid': prior.gid,
        'registry_generation': scope['target_registry_generation'],
        'runtime_manifest_sha256': args.sha256,
        'generation_root_identity': root_identity,
        'directories': {**directories, 'lock': prior.directories['lock']},
        'lock_identity': prior.lock_facts,
        'database_identity': database,
        'source_registry_generation': prior.registry_generation,
        'source_registry_anchor_sha256': prior.sha256,
        'recovery_preparation_sha256': scope['recovery_preparation_sha256'],
    }


def build_slot(native, prior, args, source, original, parent_path, scope):
    with TemporaryDirectory(prefix='.walle-registry-slot-', dir=parent_path) as staging:
        stage = Path(staging)
        with ExitStack() as resources:
            fd = resources.enter_context(protected_directory(stage))
            os.fchown(fd, 0, prior.gid)
            os.fchmod(fd, 0o2750)
            children = {}
            for name in ('data', 'proof'):
                os.mkdir(name, mode=0o700, dir_fd=fd)
                child = native.open_beneath(fd, name, os.O_DIRECTORY | os.O_RDONLY)
                resources.callback(os.close, child)
                os.fchown(child, prior.uid, prior.gid)
                os.fchmod(child, 0o700)
                children[name] = child
            file_facts = place_database(native, prior, source, original, children['data'])
            directory_facts = {name: identity(os.fstat(child)) for name, child in children.items()}
            for child in children.values():
                os.fsync(child)
            anchor = canonical(
                anchor_for_slot(
                    prior, args, scope, identity(os.fstat(fd)), directory_facts, file_facts
                )
            )
            persisted_write(fd, ANCHOR_NAME, anchor, mode=0o440)
            persisted_write(
                fd,
                RECEIPT,
                canonical({**scope, 'target_anchor_sha256': digest(anchor)}),
                mode=0o440,
            )
            os.fsync(fd)
        publish_directory(stage, parent_path / scope['target_registry_generation'])


def measured_database(native, installation):
    with installation.private_directory(native, 'data') as directory:
        require(set(os.listdir(directory)) == {DATABASE_NAME}, UNVERIFIED)
        first = allow_file(
            native,
            installation,
            directory,
            DATABASE_NAME,
            expected_identity=installation.database_facts,
        )
        fd = native.open_beneath(directory, DATABASE_NAME, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            props = os.fstat(stream.fileno())
            require(
                identity(props) == identity(first) and props.st_size == first.st_size,
                UNVERIFIED,
            )
            measured = file_digest(stream, 'sha256').hexdigest()
            after = os.fstat(stream.fileno())
            require(
                (after.st_ctime_ns, after.st_mtime_ns, after.st_size)
                == (props.st_ctime_ns, props.st_mtime_ns, props.st_size),
                UNVERIFIED,
            )
        return first.st_size, measured


def read_slot_record(prior, args, path, scope, *, installer, expected=None):
    with protected_directory(path) as directory:
        files = set(os.listdir(directory)) - {
            ENTRY_INPUTS,
            RECOVERY_ENTRY,
            ENTRY_INTENT,
            ENTRY_ADMISSION,
            OPEN_INTENT,
            RETIRED_HOLD,
            HOST_OBSERVATIONS,
            SOURCE_ANCHOR,
            SELECTION_RECEIPT,
        }
        require(files == {RECEIPT, ANCHOR_NAME, 'data', 'proof'}, UNVERIFIED)
        raw = read_entry(directory, RECEIPT, owner=0, group=prior.gid, reject_writers=0o337)
        anchor = read_entry(directory, ANCHOR_NAME, owner=0, group=prior.gid, reject_writers=0o337)
    pin = digest(raw)
    require(expected is None or pin == expected, UNVERIFIED)
    result = exact(decode(raw, UNVERIFIED), (*scope, 'target_anchor_sha256'), UNVERIFIED)
    require(
        all(canonical(result[key]) == canonical(value) for key, value in scope.items())
        and sha_value(result['target_anchor_sha256'])
        and is_timestamp(result['prepared_at']),
        UNVERIFIED,
    )
    target = load_installation(
        path / ANCHOR_NAME,
        result['target_anchor_sha256'],
        args.sha256,
        installer=installer,
        prepared=True,
    )
    require(
        target.anchor == prior.anchor
        and target.manager_id == prior.manager_id
        and target.host_id == prior.host_id
        and target.registry_generation == scope['target_registry_generation']
        and target.uid == prior.uid
        and target.gid == prior.gid
        and target.root_facts == prior.root_facts
        and target.directories['lock'] == prior.directories['lock']
        and target.lock_facts == prior.lock_facts
        and target.directory_root == path
        and anchor
        == canonical(
            anchor_for_slot(
                prior,
                args,
                scope,
                target.generation_root_facts,
                {name: target.directories[name] for name in ('data', 'proof')},
                target.database_facts,
            )
        ),
        UNVERIFIED,
    )
    return {**result, 'placement_receipt_sha256': pin}, target


def read_slot(native, prior, args, path, scope):
    receipt, target = read_slot_record(prior, args, path, scope, installer=True)
    measured = measured_database(native, target)
    if measured != (scope['source_database_bytes'], scope['source_database_sha256']):
        from .registry_recovery_readiness import read_ready

        with target.private_directory(native, 'proof') as proof:
            require(read_ready(proof, target, receipt, measured) is not None, UNVERIFIED)
    return receipt


def place_recovered_registry(native, installation, args):
    recovery = recovery_scope(installation, args)
    expected = args.registry_recovery_receipt_sha256
    require(sha_value(expected), UNVERIFIED)
    parent_path = installation.anchor.parent / GENERATIONS
    with (
        dispatch_lock(installation, exclusive=True) as root,
        installation.lock(native) as lock,
        installation.private_directory(native, 'proof') as proof,
        snapshot_directory(native, installation, proof, STORE) as archives,
        snapshot_directory(native, installation, archives, recovery['operation_id']) as material,
    ):
        verify_pause(installation, recovery)
        source = recovery_file_receipt(material, installation, recovery, expected=expected)
        scope = placement_scope(installation, args, recovery, source)
        with new_generation_root(native, installation, root) as slots:
            target = parent_path / recovery['target_registry_generation']
            if target.name not in os.listdir(slots):
                lock.assert_owned()
                build_slot(
                    native,
                    installation,
                    args,
                    material,
                    source['database_artifact'],
                    parent_path,
                    scope,
                )
            try:
                result = read_slot(native, installation, args, target, scope)
                lock.assert_owned()
                verify_pause(installation, recovery)
                os.fsync(slots)
            except (OSError, ValueError, EnvironmentFailure) as error:
                raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
    return result
