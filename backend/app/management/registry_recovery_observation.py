"""Observe the host bindings named by a sealed registry recovery inventory."""

import os
import stat
from contextlib import contextmanager
from functools import cache
from pathlib import Path
from subprocess import SubprocessError
from tempfile import TemporaryDirectory

from backend.app.infrastructure.environment_control import read_control
from backend.app.infrastructure.environment_files import (
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
    FRESH_MS,
    candidate_environment,
    directory_facts,
    machine_clock,
    now,
    path_resource,
    private_control,
    public_facts,
    public_origin_resource,
    require_fresh,
    resource,
    verified_workspace,
)
from .operation_contract import load_catalog, path_reference
from .registry import is_timestamp
from .registry_dispatch import dispatch_lock
from .registry_installation import require_registry_root
from .registry_recovery import recovery_scope, verify_pause
from .registry_recovery_effects import (
    DEPLOYMENT_STEPS,
    checked_deployment_opening,
    current_runtime_unit,
    deployment_step_binding,
    helper_observation,
    resource_observation,
    unit_observation,
)
from .registry_recovery_installation import HOST_OBSERVATIONS
from .registry_recovery_inventory import (
    DIRECTORY as INVENTORY,
)
from .registry_recovery_inventory import (
    inventory_readiness,
    inventory_scope,
    protected_projection,
    read_inventory,
    write_records,
)
from .registry_recovery_readiness import prepared_slot
from .registry_recovery_retained_data import retained_data_observation
from .registry_recovery_stop import stopped_runtime_unit
from .registry_snapshot import snapshot_directory
from .runtime_capacity import capacity_policy_path
from .runtime_observation import (
    READY,
    SYSTEMCTL,
    controlled_release,
    runtime_observation,
    trusted_executable,
)

MANIFEST = 'registry-recovery-observation.v1.json'
OBSERVATIONS = 'observations.jsonl'
OBSERVED = 'MANAGEMENT_REGISTRY_RECOVERY_HOST_OBSERVED'
UNVERIFIED = 'MANAGEMENT_REGISTRY_RECOVERY_HOST_UNVERIFIED'
OBSERVATION_ERRORS = (EnvironmentFailure, OSError, ValueError, KeyError, TypeError, SubprocessError)


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
        yield (
            'capacity',
            'ordinary-capacity',
            capacity_policy_path(catalog),
            catalog.capacity_policy_sha256,
        )


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
        retained = retained_data_observation(native, environment, database)
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
        'retained_paths': retained,
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
        and proof['reason_code'] == READY
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
        require(database is not None, UNVERIFIED)
        retained = retained_data_observation(native, environment, database)
        require(
            private_control(environment) == control
            and observed_socket(environment) == upstream
            and directory_facts(environment) == (root, roots)
            and database_identity(environment, data) == database
            and retained_data_observation(native, environment, database) == retained
            and runtime_observation(catalog, environment.environment_id) == proof
            and environment.lock(native).observer_pid() == pid,
            UNVERIFIED,
        )
    require_fresh(proof)
    return {
        'state': 'RUNNING_OBSERVED',
        'proof_id': proof['proof_id'],
        'run_id': proof['run_id'],
        'policy_sha256': proof['policy_sha256'],
        'lock_pid': pid,
        'control_sha256': digest(canonical(control)),
        'database_identity': database,
        'root_identities': roots,
        'paths': observed_paths(environment, root, roots, database, upstream),
        'retained_paths': retained,
    }


def observed_assignment(environment, candidate, observe_workspace):
    origin = public_origin_resource(environment)
    claims = {'PUBLIC_ORIGIN': origin}
    try:
        repository, live = observe_workspace(*path_reference(candidate['workspace']))
        registered = next(
            row
            for row in repository['worktrees']
            if row['environment_id'] == environment.environment_id
        )
        worktree = next(
            row for row in live['worktrees'] if row['environment_id'] == environment.environment_id
        )
        require(
            registered['purpose'] == worktree['purpose'] == environment.description['purpose']
            and registered['branch'] == worktree['branch']
            and repository['repository_ref'] == live['repository_ref'],
            UNVERIFIED,
        )
        claims.update(
            WORKTREE=path_resource(
                'WORKTREE', absolute(registered['path'], UNVERIFIED), registered['identity']
            ),
            GIT_BRANCH=resource(
                'GIT_BRANCH', 'REPOSITORY:' + live['repository_ref'], worktree['branch']
            ),
        )
        return claims, worktree['head']
    except (*OBSERVATION_ERRORS, StopIteration):
        return claims, None


def observe_environment(native, catalog, row, runtime_sha, entry, observe_workspace):
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
        claims, head = observed_assignment(environment, candidate, observe_workspace)
        return {
            **scope,
            'binding': public,
            'configuration_attachment': attachment,
            'installation_sha256': environment.anchor_sha256,
            'assignment_claims': claims,
            'worktree_head': head,
            **observed,
        }
    except OBSERVATION_ERRORS as error:
        return {**scope, 'state': 'UNKNOWN', 'reason_code': getattr(error, 'code', UNVERIFIED)}


def original_deployment_scope(row, step, scope, grant):
    plan = grant['confirmation'] if step['original_action'] == 'RESTORE' else grant
    source = plan['source']
    registered = registered_subject(row)
    require(
        registered['environment_id'] == scope['environment_id']
        and row['host_id'] == grant['host_id']
        and row['registration_state'] == 'ACTIVE'
        and row['preparation_state'] == 'PREPARED'
        and row['assignment_control_state'] == 'OPEN'
        and type(row['configuration_ref']) is str
        and decode(row['configuration_ref'].encode('utf-8'), UNVERIFIED)
        == plan['source_attachment']
        and all(
            registered[key] == source[key]
            for key in (
                'data_generation',
                'deployment_id',
                'configuration_sha256',
                'program_sha256',
            )
        )
        and (source['data_generation'] != scope['data_generation'])
        == (step['original_action'] == 'RESTORE')
        and source['deployment_id'] != scope['deployment_id'],
        UNVERIFIED,
    )
    return registered, plan['source_attachment']


def measured_opening_control(native, environment, policy, receipt, current, *, stopped):
    opened = receipt['opening']
    with environment.directory(native, 'control') as fd:
        control, revision = controlled_release(fd, environment, policy)
        name = f'open-{opened["run_id"]}.v1.json'
        require(
            control['open_receipt_ref'] == name
            and revision + 1 == opened['control_revision']
            and control['control_revision'] == opened['control_revision'] + (2 if stopped else 0)
            and digest(canonical(control)) == current['control_sha256'],
            UNVERIFIED,
        )
        raw = read_entry(fd, name, owner=environment.application_uid, group=environment.group)
        require(digest(raw) == opened['open_receipt_sha256'], UNVERIFIED)


def opened_target_state(native, catalog, environment, attachment, binding, receipt, policy):
    unit = stopped_runtime_unit(binding['environment_id'], receipt['opening']['operation_id'])
    before = unit_observation(unit)
    try:
        with environment.lock(native) as lock:
            closed = observed_stopped(native, environment, lock)
            require(
                closed['closed_reason'] == 'NORMAL_STOP'
                and before['state'] in ('ABSENT_OBSERVED', 'QUIET_OBSERVED')
                and before['main_pid'] == 0
                and before['cgroup_empty'] is True
                and before['invocation_id'] in (None, '0' * 32, policy['invocation_id']),
                UNVERIFIED,
            )
            measured_opening_control(native, environment, policy, receipt, closed, stopped=True)
            require(unit_observation(unit) == before, UNVERIFIED)
            lock.assert_owned()
            return {
                'state': 'OPENED_STOPPED',
                'closed_control_sha256': closed['control_sha256'],
                'database_identity': closed['database_identity'],
            }
    except EnvironmentFailure as error:
        if error.code != 'ENVIRONMENT_ALREADY_RUNNING':
            raise

    live = observed_running(native, catalog, environment, attachment['candidate_ref'])
    claim = {
        'opening_binding': binding,
        'runtime_authority': {
            'policy_sha256': receipt['runtime']['sha256'],
            'invocation_id': policy['invocation_id'],
        },
    }
    require(
        before['state'] == 'PRESENT_OBSERVED'
        and current_runtime_unit(claim, before, {**live, 'binding': public_facts(environment)}),
        UNVERIFIED,
    )
    measured_opening_control(native, environment, policy, receipt, live, stopped=False)
    require(
        unit_observation(unit) == before
        and environment.lock(native).observer_pid() == live['lock_pid'],
        UNVERIFIED,
    )
    return {'state': 'OPENED_RUNNING'}


def pending_deployment_observation(native, catalog, row, step, runtime_sha, entry):
    evidence = {'state': 'OPENING_UNVERIFIED', 'action': step['original_action']}
    try:
        require(
            row is not None
            and step['status'] == 'DISPATCHING'
            and step['original_operation_status'] == 'RUNNING'
            and step['cancel_requested'] == 0
            and step['result_json'] is None
            and type(step['external_identity_json']) is str,
            UNVERIFIED,
        )
        original = deployment_step_binding(step, catalog)
        if original is None:
            payload = exact(
                decode(step['external_identity_json'].encode('utf-8'), UNVERIFIED),
                ('maintenance',),
                UNVERIFIED,
            )
            grant = payload['maintenance']
            plan = grant['confirmation'] if step['original_action'] == 'RESTORE' else grant
            require(
                plan['operation_id'] == step['operation_id']
                and plan['environment_id'] == row['environment_id']
                and all(grant[key] == value for key, value in catalog.scope.items()),
                UNVERIFIED,
            )
            return {**evidence, 'state': 'MAINTENANCE_WITHOUT_OPENING'}
        binding, grant, request = original
        source, source_attachment = original_deployment_scope(row, step, binding, grant)
        evidence.update(source=source, target=binding)
        verified = checked_deployment_opening(catalog, step, grant, request)
        if verified is None:
            return {**evidence, 'state': 'OPENING_UNCONFIRMED'}
        receipt, attachment, policy = verified
        evidence.update(
            state='OPENED_RUNTIME_UNVERIFIED',
            opened_receipt_sha256=digest(canonical(receipt)),
            opened_at=receipt['opening']['opened_at'],
        )
        original_candidate = catalog.candidate(
            source_attachment['candidate_ref'], source_attachment['sha256']
        )
        target_candidate = catalog.candidate(attachment['candidate_ref'], attachment['sha256'])
        previous = candidate_environment(original_candidate, runtime_sha)
        current = candidate_environment(target_candidate, runtime_sha)
        expected = {**source, **{key: binding[key] for key in source if key in binding}}
        require(
            public_facts(previous) == source
            and public_facts(current) == expected
            and previous.environment_root == current.environment_root
            and previous.roots['control'] == current.roots['control']
            and previous.lock_identity == current.lock_identity
            and entry['verify_program'](current.project) == expected['program_sha256'],
            UNVERIFIED,
        )
        current.check_hold(offline=True)
        evidence.update(
            opened_target_state(native, catalog, current, attachment, binding, receipt, policy)
        )
    except OBSERVATION_ERRORS:
        pass
    return evidence


def inventory_rows(directory, name):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    fd = os.open(name, flags, dir_fd=directory)
    with os.fdopen(fd, 'rb') as stream:
        for line in stream:
            yield decode(line, UNVERIFIED)


def workspace_observer(args, catalog):
    @cache
    def observe_workspace(path, pin):
        try:
            return verified_workspace(
                (path, pin), args, catalog.directory / 'observations', ownership_only=True
            )
        except OBSERVATION_ERRORS:
            return None

    return observe_workspace


def host_observations(directory, native, catalog, args, entry):
    observe_workspace = workspace_observer(args, catalog)
    yield from asset_observations(catalog)
    environments = {}
    registrations = {}
    for row in inventory_rows(directory, 'environments.jsonl'):
        require(uuid_value(row.get('environment_id')), UNVERIFIED)
        observed = observe_environment(native, catalog, row, args.sha256, entry, observe_workspace)
        environments[row['environment_id']] = observed
        registrations[row['environment_id']] = row
        yield observed
    for row in inventory_rows(directory, 'claims.jsonl'):
        yield resource_observation(row, environments.get(row['environment_id'], {}))
    for row in inventory_rows(directory, 'steps.jsonl'):
        observed = helper_observation(row, catalog)
        if row['step_kind'] in DEPLOYMENT_STEPS and row['status'] in ('DISPATCHING', 'UNKNOWN'):
            registered = registrations.get(row['environment_id'])
            observed['external_deployment'] = pending_deployment_observation(
                native, catalog, registered, row, args.sha256, entry
            )
        yield observed


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
    boot, started = machine_clock()
    with TemporaryDirectory(prefix='.walle-recovery-observations-', dir=parent) as temporary:
        stage = Path(temporary)
        with protected_directory(stage) as directory:
            os.fchown(directory, 0, target.gid)
            os.fchmod(directory, 0o2750)
            artifact = write_records(stage / OBSERVATIONS, observations, mode=0o440)
            ending_boot, finished = machine_clock()
            require(boot == ending_boot and 0 <= finished - started <= FRESH_MS, UNVERIFIED)
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
            observations = host_observations(directory, native, catalog, args, entry)
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
