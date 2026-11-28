"""Re-attest a surviving ordinary run for a recovered management entry."""

import fcntl
import os
from dataclasses import replace
from types import SimpleNamespace

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    decode,
    digest,
    exact,
    persisted_write,
    protected_directory,
    read_entry,
    read_protected,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value

from .attachment_observation import candidate_environment
from .operation_contract import CATALOG_NAME
from .registry_dispatch import (
    OPEN_INTENT,
    dispatch_generation,
    host_dispatch,
    selected_dispatch_intent,
)
from .registry_recovery_effects import DEPLOYMENT_STEPS, START_STEP, current_runtime_unit
from .registry_recovery_entry_admission import installed_admission
from .registry_recovery_installation import ENTRY_INPUTS, HOST_OBSERVATIONS
from .registry_recovery_inventory import protected_projection
from .registry_recovery_observation import (
    MANIFEST,
    OBSERVATIONS,
    inventory_rows,
    protected_observations,
)
from .runtime_observation import POLICY, READY, capture_runtime, load_policy, runtime_observation

UNVERIFIED = 'MANAGEMENT_RECOVERED_RUNTIME_UNVERIFIED'
RUNTIME_DIRECTORY = 'recovered-runtime-'
ATTESTATION = 'recovered-runtime-attestation.v1.json'


def source_observation(installation, opened, identifier, environment_id, operation_id):
    path = installation.directory_root / HOST_OBSERVATIONS / identifier
    with protected_observations(path, installation) as directory:
        raw = read_entry(directory, MANIFEST, owner=0, group=installation.gid, reject_writers=0o337)
        require(digest(raw) == opened['observation_receipt_sha256'], UNVERIFIED)
        manifest = decode(raw, UNVERIFIED)
        require(manifest['observation_id'] == identifier, UNVERIFIED)
        protected_projection(
            directory, OBSERVATIONS, 0, installation.gid, manifest['artifact'], mode=0o440
        )
        environments = []
        starts = []
        for row in inventory_rows(directory, OBSERVATIONS):
            if row.get('environment_id') != environment_id:
                continue
            if row['kind'] == 'ENVIRONMENT':
                environments.append(row)
            if row['kind'] == 'ORIGINAL_HELPER_STEP' and row['operation_id'] == operation_id:
                starts.append(row)
        require(len(environments) == len(starts) == 1, UNVERIFIED)
    return environments[0], starts[0]


def verify_source_runtime(previous, start, environment, original, pin):
    reference = {'candidate_ref': original['candidate_ref'], 'sha256': original['candidate_sha256']}
    unit_name = f'walle-env-{environment.environment_id}-{original["operation_id"]}.service'
    unit = next((fact for fact in start['units'] if fact['unit'] == unit_name), {})
    binding = previous['binding']
    require(
        start['state'] == 'OBSERVED'
        and start['original_status'] == 'SUCCEEDED'
        and start['step_kind'] in (START_STEP, *DEPLOYMENT_STEPS)
        and previous['run_id'] == original['run_id']
        and previous['policy_sha256'] == pin
        and all(
            binding.get(key) == getattr(environment, key)
            for key in (
                'environment_id',
                'deployment_id',
                'data_generation',
                'configuration_sha256',
            )
        )
        and binding['program_sha256'] == environment.description['program_source']['sha256']
        and previous['installation_sha256'] == environment.anchor_sha256
        and previous['configuration_attachment'] == reference
        and unit.get('invocation_id') == original['invocation_id']
        and current_runtime_unit(start, unit, previous),
        UNVERIFIED,
    )


def publish_policy(directory, name, content):
    with protected_directory(directory) as handle:
        try:
            raw = read_entry(handle, name, owner=0, reject_writers=0o222)
        except FileNotFoundError:
            persisted_write(handle, name, content, mode=0o444)
        else:
            require(raw == content, UNVERIFIED)


def republish_runtime(catalog, args, entry, environment, original, dispatch_pin):
    content = canonical({**original, **catalog.scope})
    pin = digest(content)
    with protected_directory(catalog.directory) as host:
        try:
            fcntl.flock(host, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise EnvironmentFailure(UNVERIFIED) from error
        current = runtime_observation(catalog, environment.environment_id)
        require(
            current is None
            or (
                current['run_id'] == original['run_id']
                and current['policy_sha256'] == pin
                and current['state'] != 'STOPPED'
            ),
            UNVERIFIED,
        )
        name = RUNTIME_DIRECTORY + original['operation_id']
        parent = catalog.directory / 'observations'
        with protected_directory(parent) as observations:
            try:
                os.mkdir(name, 0o755, dir_fd=observations)
                os.fsync(observations)
            except FileExistsError:
                pass
        directory = parent / name
        publish_policy(directory, POLICY, content)
        path = directory / POLICY
        scope = SimpleNamespace(
            root=args.root,
            sha256=args.sha256,
            runtime_entry=args.runtime_entry,
            runtime_policy=path,
            runtime_policy_sha256=pin,
        )
        expected = None if current is None else canonical(current)
        observed = capture_runtime(catalog, scope, entry, expected=expected)
        require(observed['state'] == 'RUNNING' and observed['reason_code'] == READY, UNVERIFIED)
        receipt = {
            'format_version': 1,
            **catalog.scope,
            'registry_anchor_sha256': catalog.registry_anchor_sha256,
            'environment_id': environment.environment_id,
            'operation_id': original['operation_id'],
            'run_id': original['run_id'],
            'runtime_policy_sha256': pin,
            'source_registry_generation': original['registry_generation'],
            'source_runtime_policy_sha256': args.runtime_policy_sha256,
            'dispatch_open_sha256': dispatch_pin,
        }
        publish_policy(directory, ATTESTATION, canonical(receipt))
        return {**observed, 'runtime': {'path': str(path), 'sha256': pin}}


def capture_recovered_runtime(catalog, installation, args, entry):
    identifier = args.recovered_observation_id
    require(os.geteuid() == 0 and uuid_value(identifier), UNVERIFIED)
    with host_dispatch(installation), dispatch_generation(installation) as directory:
        opened, dispatch_pin = selected_dispatch_intent(directory, installation)
        admitted = installed_admission(
            installation, args.sha256, opened['entry_admission_receipt_sha256']
        )
        inputs = installation.directory_root / ENTRY_INPUTS / admitted['entry_id']
        require(
            args.catalog == inputs / CATALOG_NAME
            and args.catalog_sha256 == admitted['catalog_sha256'],
            UNVERIFIED,
        )
        historical = replace(
            catalog,
            scope={**catalog.scope, 'registry_generation': opened['source_registry_generation']},
        )
        original = load_policy(args.runtime_policy, args.runtime_policy_sha256, historical)
        candidate = catalog.candidate(original['candidate_ref'], original['candidate_sha256'])
        environment = candidate_environment(candidate, args.sha256)
        previous, start = source_observation(
            installation, opened, identifier, environment.environment_id, original['operation_id']
        )
        verify_source_runtime(previous, start, environment, original, args.runtime_policy_sha256)
        return republish_runtime(catalog, args, entry, environment, original, dispatch_pin)


def recovered_authority(catalog, row, run_id, limits, *, boot_id=None):
    require(row['status'] == row['original_operation_status'] == 'SUCCEEDED', UNVERIFIED)
    operation, environment = row['operation_id'], row['environment_id']
    projection = runtime_observation(catalog, environment)
    require(projection is not None and projection['run_id'] == run_id, UNVERIFIED)
    pin = projection['policy_sha256']
    directory = catalog.directory / 'observations' / (RUNTIME_DIRECTORY + operation)
    adopted = exact(
        decode(read_protected(directory / ATTESTATION), UNVERIFIED),
        (
            'format_version',
            *catalog.scope,
            'registry_anchor_sha256',
            'environment_id',
            'operation_id',
            'run_id',
            'runtime_policy_sha256',
            'source_registry_generation',
            'source_runtime_policy_sha256',
            'dispatch_open_sha256',
        ),
        UNVERIFIED,
    )
    generation = catalog.directory.parent.parent
    require(
        type(adopted['format_version']) is int
        and adopted['format_version'] == 1
        and all(adopted[key] == value for key, value in catalog.scope.items())
        and adopted['registry_anchor_sha256'] == catalog.registry_anchor_sha256
        and adopted['environment_id'] == environment
        and adopted['operation_id'] == operation
        and adopted['run_id'] == run_id
        and adopted['runtime_policy_sha256'] == pin
        and uuid_value(adopted['source_registry_generation'])
        and adopted['source_registry_generation'] != catalog.scope['registry_generation']
        and sha_value(adopted['source_runtime_policy_sha256'])
        and catalog.directory.parent.name == ENTRY_INPUTS
        and digest(read_protected(generation / OPEN_INTENT)) == adopted['dispatch_open_sha256'],
        UNVERIFIED,
    )
    policy = load_policy(directory / POLICY, pin, catalog)
    require(
        policy['operation_id'] == operation
        and policy['run_id'] == run_id
        and (boot_id is None or policy['boot_id'] == boot_id)
        and policy['memory_bytes'] == limits['memory_bytes']
        and policy['tasks'] == limits['tasks']
        and policy['cpu_quota_usec'] == limits['cpu_percent'] * 1000
        and policy['cpu_period_usec'] == 100_000,
        UNVERIFIED,
    )
    return {
        'policy_sha256': pin,
        'invocation_id': policy['invocation_id'],
        'configuration_attachment': {
            'candidate_ref': policy['candidate_ref'],
            'sha256': policy['candidate_sha256'],
        },
    }
