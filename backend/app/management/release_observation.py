"""Observe a stopped source and prepared target through the fixed host entry."""

import os
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

from backend.app.infrastructure.environment_command import admission_inputs
from backend.app.infrastructure.environment_control import normal_stop, read_control
from backend.app.infrastructure.environment_files import canonical, digest, exact, require
from backend.app.infrastructure.environment_installation import (
    CAPABILITIES,
    GATEWAY_VERIFIER_REQUIRED,
    WORKSPACE_PURPOSES,
    Installation,
    access_scope,
    database_identity,
    gateway_verifier_names,
    read_access_policy,
    sha_value,
    uuid_value,
)
from backend.app.infrastructure.environment_lock import NativeEnvironmentFiles
from backend.app.infrastructure.environment_release_deployment import check_stable_resources
from backend.app.infrastructure.environment_release_preflight import (
    compatibility,
    reconfiguration_program,
    rollback_subject,
)

from .attachment_observation import (
    FRESH_MS,
    candidate_environment,
    machine_clock,
    now,
    observation_path,
    publish_observation,
    require_fresh,
)
from .operation_contract import RESOURCE, installed_record, version
from .registry import is_timestamp
from .release_artifacts import verify_release_details
from .release_configuration import compatibility_reference, manifest_path, read_configuration

SOURCE = 'release-source-'
TUPLE_FIELDS = (
    'installation_sha256',
    'deployment_id',
    'data_generation',
    'configuration_sha256',
    'program_sha256',
)
SOURCE_FIELDS = (*TUPLE_FIELDS, 'control_revision', 'control_sha256', 'database_identity')
TARGET_FIELDS = TUPLE_FIELDS


@dataclass(frozen=True)
class ReleasePair:
    source: Installation
    target: Installation


def deployment_subject(installation):
    return {
        'installation_sha256': installation.anchor_sha256,
        'deployment_id': installation.deployment_id,
        'data_generation': installation.data_generation,
        'configuration_sha256': installation.configuration_sha256,
        'program_sha256': installation.description['program_source']['sha256'],
    }


def admitted_pair(config, runtime_sha, entry):
    active = SimpleNamespace(runtime_manifest_sha256=runtime_sha)
    source = candidate_environment(config.source, runtime_sha)
    target = candidate_environment(config.target, runtime_sha)
    admitted = []
    for item in (source, target):
        measured = entry['verify_program'](item.project)
        installed, schema = admission_inputs(
            SimpleNamespace(
                anchor=item.anchor, anchor_sha256=item.anchor_sha256, project=item.project
            ),
            active,
            measured,
        )
        require(installed == item, RESOURCE)
        admitted.append(schema)
    source_schema, target_schema = admitted
    manifest_file, manifest_sha = manifest_path(config)
    _, manifest = verify_release_details(manifest_file, manifest_sha, runtime_sha)
    binding = target.description.get('deployment_slot')
    require(
        binding is not None
        and binding['authorization_mode'] == config.deployment_mode
        and binding['release_id'] == config.release_ref == manifest['release_id']
        and binding['manifest_sha256'] == manifest_sha
        and manifest_file.parent / 'application' == target.project
        and binding['source_deployment_id'] == source.deployment_id
        and binding['source_configuration_sha256'] == source.configuration_sha256
        and source.environment_id == target.environment_id == config.environment_id
        and source.data_generation == target.data_generation
        and source.deployment_id != target.deployment_id
        and source.lock_identity == target.lock_identity
        and source.environment_root == target.environment_root
        and source.database == target.database
        and source.description['purpose'] == target.description['purpose']
        and (source.description['access_policy_ref'] != target.description['access_policy_ref'])
        == (config.target_access_sha256 is not None)
        and source.description['purpose'] in WORKSPACE_PURPOSES
        and all('recovery_replica' not in item.description for item in (source, target)),
        RESOURCE,
    )
    proof = {
        'compatibility_ref': compatibility_reference(config),
        'target_manifest': config.manifest_reference,
        'target_schema_directory': str(target.schema),
    }
    if config.target_access_sha256 is not None:
        access = read_access_policy(target)
        require(
            target.description['access_policy_ref']['sha256'] == config.target_access_sha256
            and access_scope(read_access_policy(source)) == access_scope(access)
            and any(
                item['client_kind'] == 'WEB' and item['permission'] == 'DEVELOP'
                for item in access['principals']
            ),
            RESOURCE,
        )
        reconfiguration_program(
            proof, source, manifest, target.description['program_source']['sha256']
        )
    elif config.rollback_source is not None:
        rollback_subject(
            {**proof, **config.rollback_source},
            source,
            manifest,
            target.description['program_source']['sha256'],
            entry,
        )
    compatibility(
        proof,
        source,
        source_schema,
        manifest,
        target_schema,
        target.description['program_source']['sha256'],
        retained=config.rollback_source is not None or config.target_access_sha256 is not None,
    )
    return ReleasePair(source, target)


def stopped_source(native, installation):
    with installation.lock(native) as lock:
        installation.check_hold()
        with installation.directory(native, 'control') as fd:
            control = read_control(fd, installation)
            require(
                normal_stop(control)
                and not os.path.lexists(installation.path('runtime') / 'walle.sock')
                and not os.path.lexists(installation.path('runtime') / 'walle-check.sock'),
                RESOURCE,
            )
            with installation.directory(native, 'data') as data:
                identity = database_identity(installation, data)
                require(identity is not None, RESOURCE)
            lock.assert_owned()
            require(read_control(fd, installation) == control, RESOURCE)
    return {
        **deployment_subject(installation),
        'control_revision': control['control_revision'],
        'control_sha256': digest(canonical(control)),
        'database_identity': identity,
    }


def capture_release_source(catalog, args, entry):
    require(os.geteuid() == 0, RESOURCE)
    registered = read_configuration(catalog, args.release_configuration_ref)
    pair = admitted_pair(registered, args.sha256, entry)
    if pair.target.ingress_group is not None:
        access = read_access_policy(pair.target)
        require(gateway_verifier_names(access), GATEWAY_VERIFIER_REQUIRED)
    native = NativeEnvironmentFiles(args.root)
    check_stable_resources(pair.target, native)
    boot, started = machine_clock()
    actual_source = stopped_source(native, pair.source)
    ended_boot, ended = machine_clock()
    require(boot == ended_boot and 0 <= ended - started <= FRESH_MS, RESOURCE)
    proof = {
        'format_version': 1,
        **catalog.scope,
        'configuration_ref': registered.reference,
        'configuration_record_sha256': registered.sha256,
        'environment_id': registered.environment_id,
        'proof_id': str(uuid4()),
        'boot_id': boot,
        'observed_at': now(),
        'observed_monotonic_ms': ended,
        'source': actual_source,
        'target': deployment_subject(pair.target),
        'required_capabilities': pair.target.description['required_capabilities'],
    }
    publish_observation(catalog, SOURCE + registered.reference, proof)
    return {
        key: proof[key]
        for key in ('configuration_ref', 'environment_id', 'proof_id', 'observed_at')
    }


def observed_configuration(catalog, registered, *, fresh):
    proof = installed_record(observation_path(catalog, SOURCE + registered.reference))
    exact(
        proof,
        (
            'format_version',
            *catalog.scope,
            'configuration_ref',
            'configuration_record_sha256',
            'environment_id',
            'proof_id',
            'boot_id',
            'observed_at',
            'observed_monotonic_ms',
            'source',
            'target',
            'required_capabilities',
        ),
        RESOURCE,
    )
    require(
        type(proof['format_version']) is int
        and proof['format_version'] == 1
        and all(proof[key] == value for key, value in catalog.scope.items())
        and proof['configuration_ref'] == registered.reference
        and proof['configuration_record_sha256'] == registered.sha256
        and proof['environment_id'] == registered.environment_id
        and uuid_value(proof['proof_id'])
        and uuid_value(proof['boot_id'])
        and is_timestamp(proof['observed_at'])
        and version(proof['observed_monotonic_ms']),
        RESOURCE,
    )
    source = exact(proof['source'], SOURCE_FIELDS, RESOURCE)
    target = exact(proof['target'], TARGET_FIELDS, RESOURCE)
    for item in (source, target):
        require(
            uuid_value(item['deployment_id'])
            and uuid_value(item['data_generation'])
            and all(
                sha_value(item[key])
                for key in ('installation_sha256', 'configuration_sha256', 'program_sha256')
            ),
            RESOURCE,
        )
    from backend.app.infrastructure.environment_installation import identity_record

    identity_record(source['database_identity'], RESOURCE)
    capabilities = proof['required_capabilities']
    require(
        source['deployment_id'] != target['deployment_id']
        and source['data_generation'] == target['data_generation']
        and (
            registered.target_access_sha256 is None
            or source['program_sha256'] == target['program_sha256']
        )
        and source['installation_sha256'] == registered.source['installation']['sha256']
        and target['installation_sha256'] == registered.target['installation']['sha256']
        and version(source['control_revision'])
        and sha_value(source['control_sha256'])
        and type(capabilities) is list
        and len(capabilities) == len(CAPABILITIES)
        and all(type(value) is str for value in capabilities)
        and set(capabilities) == CAPABILITIES,
        RESOURCE,
    )
    if fresh:
        require_fresh(proof)
    return proof
