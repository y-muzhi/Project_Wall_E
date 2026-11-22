"""Seal the original management facts that require independent host comparison."""

import os
import sqlite3
import stat
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    decode,
    digest,
    exact,
    no_acl,
    persisted_write,
    read_entry,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value
from backend.app.infrastructure.schema_v22_publish import publish_directory

from .registry import open_registry, verify_database
from .registry_recovery import recovery_scope, verify_pause
from .registry_recovery_installation import measured_database
from .registry_recovery_outcome import pending_operation_clause, pending_step_clause
from .registry_recovery_readiness import prepared_slot, read_ready
from .registry_snapshot import descriptor_path, snapshot_directory

DIRECTORY = 'registry-recovery-inventory'
MANIFEST = 'inventory.v1.json'
SEALED = 'MANAGEMENT_REGISTRY_RECOVERY_INVENTORY_SEALED'
UNVERIFIED = 'MANAGEMENT_REGISTRY_RECOVERY_INVENTORY_UNVERIFIED'
PROJECTIONS = {
    'environments.jsonl': (
        'SELECT environment_id,purpose,host_id,record_version,assignment_generation,registration_state,'
        'preparation_state,configuration_sha256,configuration_ref,program_source,profile_ref,'
        'assignment_control_state,fence_operation_id,'
        "json_extract(work_package_json,'$.data_generation') AS data_generation,"
        "json_extract(work_package_json,'$.deployment_id') AS deployment_id "
        'FROM managed_environments ORDER BY environment_id'
    ),
    'claims.jsonl': (
        'SELECT resource_id,environment_id,operation_id,kind,scope_ref,locator,identity_json,quota '
        'FROM resource_claims WHERE released_at IS NULL ORDER BY resource_id'
    ),
    'operations.jsonl': (
        'SELECT operation_id,registry_generation,action,environment_id,status,revision,intent_sha256 '
        'FROM management_operations AS op WHERE {pending} ORDER BY operation_id'
    ),
    'steps.jsonl': (
        'SELECT step.operation_id,step.ordinal,step.step_kind,step.status,step.executor_ref,'
        'step.external_identity_json,op.environment_id,op.registry_generation '
        'FROM management_steps AS step JOIN management_operations AS op USING(operation_id) '
        'WHERE {pending_step} '
        'ORDER BY step.operation_id,step.ordinal'
    ),
}


def inventory_scope(recovery, readiness):
    return {
        'format_version': 1,
        'status': SEALED,
        'operation_id': recovery['operation_id'],
        'source_registry_generation': recovery['registry_generation'],
        'target_registry_generation': recovery['target_registry_generation'],
        'source_registry_anchor_sha256': recovery['registry_anchor_sha256'],
        'target_anchor_sha256': readiness['target_anchor_sha256'],
        'dispatch_hold_sha256': recovery['dispatch_hold_sha256'],
        'catalog_sha256': recovery['catalog_sha256'],
        'readiness_receipt_sha256': readiness['readiness_receipt_sha256'],
        'database_sha256': readiness['database_sha256'],
    }


def write_records(path, records, *, mode=0o400):
    hashed = sha256()
    count = size = 0
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, 'wb') as output:
        for row in records:
            encoded = canonical(dict(row))
            output.write(encoded)
            hashed.update(encoded)
            count += 1
            size += len(encoded)
        output.flush()
        os.fchmod(output.fileno(), mode)
        os.fsync(output.fileno())
    return {'records': count, 'bytes': size, 'sha256': hashed.hexdigest()}


def protected_projection(directory, name, owner, group, expected, *, mode=0o400):
    expected = exact(expected, ('records', 'bytes', 'sha256'), UNVERIFIED)
    require(
        all(type(expected[key]) is int and expected[key] >= 0 for key in ('records', 'bytes'))
        and sha_value(expected['sha256']),
        UNVERIFIED,
    )
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    fd = os.open(name, flags, dir_fd=directory)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(before.st_mode)
            and before.st_nlink == 1
            and before.st_uid == owner
            and before.st_gid == group
            and stat.S_IMODE(before.st_mode) == mode
            and before.st_size == expected['bytes'],
            UNVERIFIED,
        )
        no_acl(stream.fileno())
        count = 0
        hashed = sha256()
        while part := stream.read(128 * 1024):
            count += part.count(b'\n')
            hashed.update(part)
        after = os.fstat(stream.fileno())
        require(
            count == expected['records']
            and hashed.hexdigest() == expected['sha256']
            and (before.st_ctime_ns, before.st_mtime_ns) == (after.st_ctime_ns, after.st_mtime_ns),
            UNVERIFIED,
        )


def read_inventory(directory, target, scope, *, expected=None):
    raw = read_entry(directory, MANIFEST, owner=target.uid, group=target.gid, reject_writers=0o377)
    pin = digest(raw)
    require(expected is None or expected == pin, UNVERIFIED)
    record = exact(decode(raw, UNVERIFIED), (*scope, 'artifacts'), UNVERIFIED)
    require(
        all(canonical(record[key]) == canonical(value) for key, value in scope.items())
        and set(os.listdir(directory)) == {*PROJECTIONS, MANIFEST},
        UNVERIFIED,
    )
    artifacts = exact(record['artifacts'], PROJECTIONS, UNVERIFIED)
    for name, metadata in artifacts.items():
        protected_projection(directory, name, target.uid, target.gid, metadata)
    return {**record, 'inventory_receipt_sha256': pin}


def inventory_readiness(native, target, proof, placement, expected):
    ready = read_ready(proof, target, placement, measured_database(native, target))
    require(ready is not None and ready['readiness_receipt_sha256'] == expected, UNVERIFIED)
    return ready


def stage_inventory(native, target, proof, data, scope, readiness, lock):
    output = descriptor_path(proof)
    with TemporaryDirectory(prefix='.walle-registry-inventory-', dir=output) as temporary:
        stage = Path(temporary)
        with open_registry(native, target, data, read_only=False) as database:
            database.execute('PRAGMA query_only=ON')
            require(
                verify_database(database, target, integrity=True) == readiness['prepared_at'],
                UNVERIFIED,
            )
            database.row_factory = sqlite3.Row
            conditions = {
                'pending': pending_operation_clause(database, include_completed_backups=True),
                'pending_step': pending_step_clause(database),
            }
            indexes = {
                name: write_records(stage / name, database.execute(query.format(**conditions)))
                for name, query in PROJECTIONS.items()
            }
        require(
            measured_database(native, target)
            == (readiness['database_bytes'], readiness['database_sha256']),
            UNVERIFIED,
        )
        with snapshot_directory(native, target, proof, stage.name) as directory:
            persisted_write(
                directory, MANIFEST, canonical({**scope, 'artifacts': indexes}), mode=0o400
            )
            read_inventory(directory, target, scope)
            os.fsync(directory)
        lock.assert_owned()
        publish_directory(stage, output / DIRECTORY)


def inventory_registry_recovery(native, installation, args):
    recovery = recovery_scope(installation, args)
    expected = args.registry_readiness_receipt_sha256
    require(sha_value(expected), UNVERIFIED)
    with installation.lock(native) as lock:
        verify_pause(installation, recovery)
        with (
            prepared_slot(native, installation, args, recovery, installer=False) as (
                placement,
                target,
                _,
            ),
            target.private_directory(native, 'proof') as proof,
            target.private_directory(native, 'data') as data,
        ):
            ready = inventory_readiness(native, target, proof, placement, expected)
            scope = inventory_scope(recovery, ready)
            if DIRECTORY not in os.listdir(proof):
                stage_inventory(native, target, proof, data, scope, ready, lock)
            try:
                with snapshot_directory(native, target, proof, DIRECTORY) as directory:
                    result = read_inventory(directory, target, scope)
                require(
                    inventory_readiness(native, target, proof, placement, expected) == ready,
                    UNVERIFIED,
                )
                lock.assert_owned()
                verify_pause(installation, recovery)
                os.fsync(proof)
            except (OSError, ValueError, EnvironmentFailure) as error:
                raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
    return result
