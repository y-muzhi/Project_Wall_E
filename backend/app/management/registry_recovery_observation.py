"""Observe the host bindings named by a sealed registry recovery inventory."""

from contextlib import contextmanager
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory

from backend.app.infrastructure.environment_control import read_control
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
    read_protected,
    require,
)
from backend.app.infrastructure.environment_installation import (
    database_identity,
    sha_value,
    uuid_value,
)
from backend.app.infrastructure.schema_v22_publish import publish_directory

from .attachment_observation import (
    candidate_environment,
    directory_facts,
    machine_clock,
    now,
    path_resource,
    private_control,
    public_facts,
    require_fresh,
)
from .operation_contract import load_catalog
from .registry import is_timestamp
from .registry_dispatch import dispatch_lock
from .registry_installation import require_registry_root
from .registry_recovery import recovery_scope, verify_pause
from .registry_recovery_effects import helper_observation, resource_observation
from .registry_recovery_installation import HOST_OBSERVATIONS
from .registry_recovery_inventory import (
    DIRECTORY as INVENTORY,
    inventory_readiness,
    inventory_scope,
    protected_projection,
    read_inventory,
    write_records,
)
from .registry_recovery_readiness import prepared_slot
from .registry_snapshot import snapshot_directory
from .runtime_capacity import POLICY_PATH
from .runtime_observation import SYSTEMCTL, runtime_observation, trusted_executable

MANIFEST = 'registry-recovery-observation.v1.json'
OBSERVATIONS = 'observations.jsonl'
OBSERVED = 'MANAGEMENT_REGISTRY_RECOVERY_HOST_OBSERVED'
UNVERIFIED = 'MANAGEMENT_REGISTRY_RECOVERY_HOST_UNVERIFIED'
OBSERVATION_ERRORS = (EnvironmentFailure, OSError, ValueError, KeyError, TypeError)


def artifact_references(catalog):
    for folder, index in (
        ('candidates', catalog.candidates),
        ('resources', catalog.resources),
        ('checks', catalog.checks),
        ('release-candidates', catalog.release_candidates),
        ('release-configurations', catalog.release_configurations),
        ('backup-policies', catalog.backup_policies),
        ('restore-configurations', catalog.restore_configurations),
    ):
        for identifier, pin in sorted(index.items()):
            yield folder, identifier, catalog.directory / folder / (identifier + '.json'), pin
    for identifier, (path, pin) in sorted(catalog.backup_indexes.items()):
        yield 'backup-indexes', identifier, path, pin
    for (environment, generation), grant in sorted(catalog.prior_result_grants.items()):
        if grant['index'] is not None:
            path, pin = grant['index']
            yield 'prior-results', environment + '/' + generation, path, pin
    if catalog.capacity_policy_sha256 is not None:
        yield 'capacity', 'ordinary-capacity', POLICY_PATH, catalog.capacity_policy_sha256


def asset_observations(catalog):
    for kind, identifier, path, pin in artifact_references(catalog):
        try:
            measured = digest(read_protected(path))
            state = 'VERIFIED' if measured == pin else 'CHANGED'
        except (OSError, EnvironmentFailure):
            state, measured = 'UNKNOWN', None
        yield {
            'kind': 'CATALOG_ASSET',
            'asset_kind': kind,
            'reference': identifier,
            'expected_sha256': pin,
            'observed_sha256': measured,
            'state': state,
        }


def registered_subject(row):
    return {
        'environment_id': row['environment_id'],
        'data_generation': row['data_generation'],
        'deployment_id': row['deployment_id'],
        'purpose': row['purpose'],
        'configuration_sha256': row['configuration_sha256'],
        'program_sha256': row['program_source'],
    }


def observed_paths(environment, root, roots, database, socket_identity):
    return {
        kind: path_resource(kind, path, object_identity)
        for kind, path, object_identity in (
            ('INSTALLATION_ROOT', environment.environment_root, root),
            ('DATA_ROOT', environment.path('data'), roots['data']),
            ('CONTROL_ROOT', environment.path('control'), roots['control']),
            ('BUSINESS_DATABASE', environment.database, database),
            (
                'STABLE_LOCK',
                environment.path('lock') / 'environment.lock',
                environment.lock_identity,
            ),
            ('UPSTREAM_SOCKET', environment.path('runtime') / 'walle.sock', socket_identity),
        )
    }


def observed_stopped(native, environment, lock):
    with environment.directory(native, 'control') as control_directory:
        control = read_control(control_directory, environment)
        require(
            control['admission'] == 'CLOSED'
            and all(
                not os.path.lexists(environment.path('runtime') / name)
                for name in ('walle.sock', 'walle-check.sock')
            ),
            UNVERIFIED,
        )
        with environment.directory(native, 'data') as data:
            database = database_identity(environment, data)
            require(database is not None, UNVERIFIED)
        root, roots = directory_facts(environment)
        lock.assert_owned()
        require(read_control(control_directory, environment) == control, UNVERIFIED)
    return {
        'state': 'CLOSED',
        'control_revision': control['control_revision'],
        'control_sha256': digest(canonical(control)),
        'closed_reason': control['closed_reason'],
        'outbound_hold': control['outbound_hold'],
        'database_identity': database,
        'root_identities': roots,
        'paths': observed_paths(environment, root, roots, database, None),
    }


def observed_socket(environment):
    live = (environment.path('runtime') / 'walle.sock').lstat()
    require(stat.S_ISSOCK(live.st_mode) and live.st_uid == environment.application_uid, UNVERIFIED)
    return identity(live)


def observed_running(native, catalog, environment, reference):
    proof = runtime_observation(catalog, environment.environment_id)
    require(
        proof is not None
        and proof['state'] == 'RUNNING'
        and proof['candidate_ref'] == reference
        and all(
            proof[key] == getattr(environment, key)
            for key in ('data_generation', 'deployment_id', 'configuration_sha256')
        )
        and proof['program_sha256'] == environment.description['program_source']['sha256'],
        UNVERIFIED,
    )
    require_fresh(proof)
    pid = environment.lock(native).observer_pid()
    require(type(pid) is int and pid > 0, UNVERIFIED)
    control = private_control(environment)
    require(
        control['admission'] == 'OPEN'
        and control['open_receipt_ref'] == f'open-{proof["run_id"]}.v1.json',
        UNVERIFIED,
    )
    upstream = observed_socket(environment)
    root, roots = directory_facts(environment)
    with environment.directory(native, 'data') as data:
        database = database_identity(environment, data)
        require(
            database is not None
            and private_control(environment) == control
            and observed_socket(environment) == upstream
            and directory_facts(environment) == (root, roots)
            and database_identity(environment, data) == database
            and runtime_observation(catalog, environment.environment_id) == proof
            and environment.lock(native).observer_pid() == pid,
            UNVERIFIED,
        )
    require_fresh(proof)
    return {
        'state': 'RUNNING_OBSERVED',
        'proof_id': proof['proof_id'],
        'run_id': proof['run_id'],
        'lock_pid': pid,
        'control_sha256': digest(canonical(control)),
        'database_identity': database,
        'root_identities': roots,
        'paths': observed_paths(environment, root, roots, database, upstream),
    }


def observe_environment(native, catalog, row, runtime_sha, entry):
    scope = {'kind': 'ENVIRONMENT', 'environment_id': row['environment_id']}
    try:
        require(
            row['host_id'] == catalog.scope['host_id'] and type(row['configuration_ref']) is str,
            UNVERIFIED,
        )
        attachment = exact(
            decode(row['configuration_ref'].encode('utf-8'), UNVERIFIED),
            ('candidate_ref', 'sha256'),
            UNVERIFIED,
        )
        reference = attachment['candidate_ref']
        candidate = catalog.candidate(reference, attachment['sha256'])
        environment = candidate_environment(candidate, runtime_sha)
        public = public_facts(environment)
        if public != registered_subject(row):
            return {**scope, 'state': 'CHANGED', 'registration_sha256': digest(canonical(row))}
        require(
            entry['verify_program'](environment.project) == public['program_sha256'],
            UNVERIFIED,
        )
        environment.check_hold(offline=True)
        try:
            with environment.lock(native) as lock:
                observed = observed_stopped(native, environment, lock)
        except EnvironmentFailure as error:
            if error.code != 'ENVIRONMENT_ALREADY_RUNNING':
                raise
            observed = observed_running(native, catalog, environment, reference)
        return {
            **scope,
            'binding': public,
            'installation_sha256': environment.anchor_sha256,
            **observed,
        }
    except OBSERVATION_ERRORS as error:
        return {**scope, 'state': 'UNKNOWN', 'reason_code': getattr(error, 'code', UNVERIFIED)}


def inventory_rows(directory, name):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    fd = os.open(name, flags, dir_fd=directory)
    with os.fdopen(fd, 'rb') as stream:
        for line in stream:
            yield decode(line, UNVERIFIED)


def host_observations(directory, native, catalog, runtime_sha, entry):
    yield from asset_observations(catalog)
    environments = {}
    for row in inventory_rows(directory, 'environments.jsonl'):
        require(uuid_value(row.get('environment_id')), UNVERIFIED)
        observed = observe_environment(native, catalog, row, runtime_sha, entry)
        environments[row['environment_id']] = observed
        yield observed
    for row in inventory_rows(directory, 'claims.jsonl'):
        yield resource_observation(row, environments.get(row['environment_id'], {}))
    for row in inventory_rows(directory, 'steps.jsonl'):
        yield helper_observation(row)


def observation_scope(inventory, identifier, systemctl_sha):
    return {
        'format_version': 1,
        'status': OBSERVED,
        'observation_id': identifier,
        'systemctl_sha256': systemctl_sha,
        'operation_id': inventory['operation_id'],
        'source_registry_generation': inventory['source_registry_generation'],
        'target_registry_generation': inventory['target_registry_generation'],
        'inventory_receipt_sha256': inventory['inventory_receipt_sha256'],
        'readiness_receipt_sha256': inventory['readiness_receipt_sha256'],
        'catalog_sha256': inventory['catalog_sha256'],
        'dispatch_hold_sha256': inventory['dispatch_hold_sha256'],
    }


@contextmanager
def protected_observations(path, target):
    with protected_directory(path) as directory:
        meta = os.fstat(directory)
        require_registry_root(meta, identity(meta), target.gid)
        check_ext4(directory)
        no_acl(directory)
        yield directory


def read_observation(path, target, scope, *, expected=None):
    with protected_observations(path, target) as directory:
        raw = read_entry(directory, MANIFEST, owner=0, group=target.gid, reject_writers=0o337)
        pin = digest(raw)
        require(expected is None or pin == expected, UNVERIFIED)
        record = exact(
            decode(raw, UNVERIFIED),
            (*scope, 'boot_id', 'observed_monotonic_ms', 'observed_at', 'artifact'),
            UNVERIFIED,
        )
        require(
            all(canonical(record[key]) == canonical(value) for key, value in scope.items())
            and uuid_value(record['boot_id'])
            and type(record['observed_monotonic_ms']) is int
            and record['observed_monotonic_ms'] >= 0
            and is_timestamp(record['observed_at'])
            and set(os.listdir(directory)) == {MANIFEST, OBSERVATIONS},
            UNVERIFIED,
        )
        protected_projection(directory, OBSERVATIONS, 0, target.gid, record['artifact'], mode=0o440)
    return {**record, 'observation_receipt_sha256': pin}


def stage_observation(parent, target, scope, observations, verify_source):
    boot, _ = machine_clock()
    with TemporaryDirectory(prefix='.walle-recovery-observations-', dir=parent) as temporary:
        stage = Path(temporary)
        with protected_directory(stage) as directory:
            os.fchown(directory, 0, target.gid)
            os.fchmod(directory, 0o2750)
            artifact = write_records(stage / OBSERVATIONS, observations, mode=0o440)
            ending_boot, finished = machine_clock()
            require(boot == ending_boot, UNVERIFIED)
            body = {
                **scope,
                'boot_id': boot,
                'observed_monotonic_ms': finished,
                'observed_at': now(),
                'artifact': artifact,
            }
            persisted_write(directory, MANIFEST, canonical(body), mode=0o440)
            os.fsync(directory)
        read_observation(stage, target, scope)
        verify_source()
        publish_directory(stage, parent / scope['observation_id'])


def observation_parent(target):
    parent = target.directory_root / HOST_OBSERVATIONS
    if not os.path.lexists(parent):
        with TemporaryDirectory(
            prefix='.walle-recovery-host-', dir=target.directory_root
        ) as temporary:
            staging = Path(temporary)
            with protected_directory(staging) as directory:
                os.fchown(directory, 0, target.gid)
                os.fchmod(directory, 0o2750)
                os.fsync(directory)
            publish_directory(staging, parent)
        with protected_directory(target.directory_root) as directory:
            os.fsync(directory)
    return parent


def check_observation_args(args, recovery):
    identifier = args.registry_observation_id
    require(
        uuid_value(identifier)
        and sha_value(args.registry_inventory_receipt_sha256)
        and sha_value(args.registry_readiness_receipt_sha256)
        and sha_value(args.registry_systemctl_sha256)
        and args.catalog_sha256 == recovery['catalog_sha256'],
        UNVERIFIED,
    )
    trusted_executable(SYSTEMCTL, args.registry_systemctl_sha256)
    return identifier


def capture_observation(native, target, args, entry, catalog, directory, subject, verify_source):
    identifier = subject['observation_id']
    parent = observation_parent(target)
    with protected_observations(parent, target) as parent_fd:
        if identifier not in os.listdir(parent_fd):
            observations = host_observations(directory, native, catalog, args.sha256, entry)
            stage_observation(parent, target, subject, observations, verify_source)
        try:
            result = read_observation(parent / identifier, target, subject)
            verify_source()
            os.fsync(parent_fd)
            return result
        except (EnvironmentFailure, OSError, ValueError) as error:
            raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error


def observe_registry_recovery(native, installation, args, entry):
    recovery = recovery_scope(installation, args)
    identifier = check_observation_args(args, recovery)
    catalog = load_catalog(args.catalog, args.catalog_sha256, installation)
    with dispatch_lock(installation, exclusive=True), installation.lock(native) as lock:
        verify_pause(installation, recovery)
        with (
            prepared_slot(native, installation, args, recovery, installer=True) as (
                placement,
                target,
                _,
            ),
            target.private_directory(native, 'proof') as proof,
            snapshot_directory(native, target, proof, INVENTORY) as directory,
        ):
            ready = inventory_readiness(
                native, target, proof, placement, args.registry_readiness_receipt_sha256
            )
            scope = inventory_scope(recovery, ready)
            index = read_inventory(
                directory, target, scope, expected=args.registry_inventory_receipt_sha256
            )
            subject = observation_scope(index, identifier, args.registry_systemctl_sha256)

            def verify_source():
                require(
                    read_inventory(
                        directory, target, scope, expected=args.registry_inventory_receipt_sha256
                    )
                    == index,
                    UNVERIFIED,
                )
                lock.assert_owned()
                verify_pause(installation, recovery)

            return capture_observation(
                native, target, args, entry, catalog, directory, subject, verify_source
            )
