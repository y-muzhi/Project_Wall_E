"""Prepare one fixed release under an existing environment's stable data and lock."""

import fcntl
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from backend.app.management.release_validation import verify_validation_frontend

from .environment_backup_package import read_policy
from .environment_files import (
    EnvironmentFailure,
    canonical,
    check_ext4,
    decode,
    digest,
    identity,
    persisted_write,
    protected_directory,
    read_protected,
    require,
)
from .environment_installation import (
    ACCESS_NAME,
    ANCHOR_NAME,
    CONFIG_NAME,
    DEPLOYMENTS,
    DIRECTORIES,
    GATEWAY_VERIFIER_REQUIRED,
    RECONFIGURE_MODE,
    RESTORE_MODE,
    WORKSPACE_PURPOSES,
    Installation,
    access_scope,
    gateway_verifier_names,
    load_installation,
    read_access_policy,
    read_restore_generation,
    restored_data_root,
    uuid_value,
    validate_access_policy,
)
from .environment_lock import LOCK_NAME, PROTOCOL, NativeEnvironmentFiles
from .environment_provision import _frontend_copy
from .environment_recovery_installation import checked_ref
from .environment_release_compatibility import checked_schema
from .environment_release_preflight import (
    candidate_target,
    compatibility,
    reconfiguration_program,
    rollback_subject,
)
from .schema_v22_publish import publish_directory

POLICY = 'release-deployment-policy.v1.json'
ROLLBACK_POLICY = 'rollback-deployment-policy.v1.json'
RECONFIGURE_POLICY = 'reconfigure-deployment-policy.v1.json'
RESTORE_POLICY = 'restore-deployment-policy.v1.json'
INVALID = 'RELEASE_DEPLOYMENT_INTENT_MISMATCH'
UNVERIFIED = 'RELEASE_DEPLOYMENT_UNVERIFIED'
CONFLICT = 'RELEASE_DEPLOYMENT_CONFLICT'


@dataclass(frozen=True)
class DeploymentTarget:
    source: Installation
    project: Path
    schema: Path
    deployment_id: str
    binding: dict
    description: dict
    access: bytes
    generation_receipt: dict | None = None
    generation_sha256: str | None = None


def reconfigured_access(plan, source):
    policy, pin = checked_ref(plan['target_access_policy'], ACCESS_NAME)
    raw = read_protected(policy)
    approved = validate_access_policy(
        decode(raw, UNVERIFIED), source.environment_root, source.environment_id
    )
    current = read_access_policy(source)
    require(
        raw == canonical(approved)
        and digest(raw) == pin
        and pin != source.description['access_policy_ref']['sha256']
        and access_scope(approved) == access_scope(current)
        and any(
            role['client_kind'] == 'WEB' and role['permission'] == 'DEVELOP'
            for role in approved['principals']
        ),
        UNVERIFIED,
    )
    return raw, {'name': ACCESS_NAME, 'sha256': pin}


def prepare_target(args, entry, *, describe=False):
    policy = args.release_deployment_policy.name
    require(policy in (POLICY, ROLLBACK_POLICY, RECONFIGURE_POLICY, RESTORE_POLICY), INVALID)
    restore = policy == RESTORE_POLICY
    rollback = policy == ROLLBACK_POLICY
    reconfigure = policy == RECONFIGURE_POLICY
    require(not describe or restore, INVALID)
    plan = read_policy(
        args.release_deployment_policy,
        args.release_deployment_policy_sha256,
        policy,
        (
            'installation_sha256',
            'source_deployment_id',
            'target_deployment_id',
            'target_manifest',
            'target_schema_directory',
            'candidate_proof',
            *(('operation_id', 'target_data_generation') if restore else ('compatibility_ref',)),
            *(('previous_installation', 'previous_project') if rollback else ()),
            *(('target_access_policy',) if reconfigure else ()),
        ),
    )
    key = plan['target_deployment_id']
    source = load_installation(args.anchor, args.anchor_sha256, args.sha256, args.project)
    require(
        plan['installation_sha256'] == args.anchor_sha256
        and plan['source_deployment_id'] == source.deployment_id
        and uuid_value(key)
        and key not in (source.environment_id, source.data_generation, source.deployment_id)
        and source.description['purpose'] in WORKSPACE_PURPOSES
        and 'recovery_replica' not in source.description
        and source.description['program_source']['sha256'] == args.program_sha256,
        INVALID,
    )
    source.check_hold()
    runtime = SimpleNamespace(runtime_manifest_sha256=args.sha256)
    _, manifest, schema, program_sha = candidate_target(plan, runtime)
    program = Path(plan['target_manifest']['path']).parent / 'application'
    schema_path = Path(plan['target_schema_directory'])
    require(
        all(
            not path.is_relative_to(source.environment_root)
            and not source.environment_root.is_relative_to(path)
            for path in (program.parent, schema_path, args.root)
        )
        and (restore or reconfigure or source.project != program)
        and entry['verify_program'](program) == program_sha,
        INVALID,
    )
    original = checked_schema(
        source.schema, source.description['schema_manifest_sha256'], args.sha256, source.project
    )
    if restore:
        require(schema.schema_contract_sha256 == original.schema_contract_sha256, INVALID)
    else:
        if rollback:
            rollback_subject(plan, source, manifest, program_sha, entry)
        if reconfigure:
            reconfiguration_program(plan, source, manifest, program_sha)
        compatibility(
            plan, source, original, manifest, schema, program_sha, retained=rollback or reconfigure
        )
    base = source.description.get('deployment_slot')
    authorization = 'ROLLBACK_CODE' if rollback else 'SAME_SCHEMA'
    if restore:
        authorization = RESTORE_MODE
    elif reconfigure:
        authorization = RECONFIGURE_MODE
    binding = {
        'base_installation_sha256': (
            source.anchor_sha256 if base is None else base['base_installation_sha256']
        ),
        'base_project': str(source.project) if base is None else base['base_project'],
        'source_deployment_id': source.deployment_id,
        'source_configuration_sha256': source.configuration_sha256,
        'preparation_policy_sha256': args.release_deployment_policy_sha256,
        'authorization_mode': authorization,
        'release_id': manifest['release_id'],
        'manifest_sha256': plan['target_manifest']['sha256'],
        'frontend_index_sha256': manifest['frontend_index_ref']['sha256'],
    }
    frontend = source.environment_root / DEPLOYMENTS / key / 'frontend'
    description = {
        **source.description,
        'program_source': {'kind': 'FIXED_RELEASE', 'sha256': program_sha},
        'schema_manifest_sha256': manifest['schema_manifest_sha256'],
        'frontend_root': str(frontend),
        'deployment_slot': binding,
    }
    if reconfigure:
        access, description['access_policy_ref'] = reconfigured_access(plan, source)
    else:
        access = read_protected(source.anchor.parent / ACCESS_NAME)
        require(digest(access) == description['access_policy_ref']['sha256'], UNVERIFIED)
    if source.ingress_group is not None:
        require(gateway_verifier_names(decode(access, UNVERIFIED)), GATEWAY_VERIFIER_REQUIRED)
    receipt = None
    pin = source.restore_generation_sha256
    if restore:
        generation = plan['target_data_generation']
        require(
            uuid_value(plan['operation_id'])
            and uuid_value(generation)
            and generation
            not in (source.environment_id, source.data_generation, source.deployment_id, key),
            INVALID,
        )
        if base is not None:
            initial = load_installation(
                source.environment_root / ANCHOR_NAME,
                base['base_installation_sha256'],
                args.sha256,
                Path(base['base_project']),
                allow_slot=False,
            )
            require(generation != initial.data_generation, INVALID)
        description['data_generation'] = generation
        description['data_root'] = str(restored_data_root(source.environment_root, generation))
        pin = None
        if not describe:
            receipt, pin = read_restore_generation(
                source.environment_root, source.environment_id, generation
            )
            require(
                receipt['operation_id'] == plan['operation_id']
                and receipt['target_deployment_id'] == key
                and receipt['target_configuration_sha256'] == digest(canonical(description))
                and receipt['data_identity'] != source.roots['data'],
                UNVERIFIED,
            )
    return DeploymentTarget(
        source, program, schema_path, key, binding, description, access, receipt, pin
    )


def describe_restore_deployment(args, entry):
    require(os.geteuid() == 0, UNVERIFIED)
    target = prepare_target(args, entry, describe=True)
    return {
        'status': 'RESTORE_DEPLOYMENT_DESCRIBED',
        'environment_id': target.source.environment_id,
        'target_data_generation': target.description['data_generation'],
        'target_deployment_id': target.deployment_id,
        'target_configuration_sha256': digest(canonical(target.description)),
        'data_root': target.description['data_root'],
    }


def expected_anchor(target, frontend_identity):
    source = target.source
    roots = {**source.roots, 'frontend': frontend_identity}
    if target.generation_receipt is not None:
        roots['data'] = target.generation_receipt['data_identity']
    return {
        'format_version': 1,
        'environment_id': source.environment_id,
        'data_generation': target.description['data_generation'],
        'deployment_id': target.deployment_id,
        'configuration_sha256': digest(canonical(target.description)),
        'runtime_manifest_sha256': target.description['runtime_manifest_sha256'],
        'schema_manifest_sha256': target.description['schema_manifest_sha256'],
        'program_sha256': target.description['program_source']['sha256'],
        'lock_protocol': PROTOCOL,
        'lock_identity': source.lock_identity,
        'root_identities': roots,
        'application_uid': source.application_uid,
        'maintenance_uid': source.maintenance_uid,
        'shared_gid': source.group,
        'ingress_gid': source.ingress_group,
        'project': str(target.project),
        'schema': str(target.schema),
        **(
            {'restore_generation_sha256': target.generation_sha256}
            if target.generation_sha256
            else {}
        ),
    }


def check_stable_resources(installation, native):
    for kind in DIRECTORIES:
        if kind == 'frontend':
            continue
        with installation.directory(native, kind) as directory:
            if kind == 'lock':
                lock = os.stat(LOCK_NAME, dir_fd=directory, follow_symlinks=False)
                require(
                    stat.S_ISREG(lock.st_mode)
                    and lock.st_uid == 0
                    and lock.st_gid == installation.group
                    and stat.S_IMODE(lock.st_mode) == 0o660
                    and lock.st_nlink == 1
                    and identity(lock) == installation.lock_identity,
                    CONFLICT,
                )


def read_prepared(final, target, runtime_sha, native):
    with protected_directory(final / 'frontend') as frontend_fd:
        check_ext4(frontend_fd)
        frontend = os.fstat(frontend_fd)
        require(stat.S_IMODE(frontend.st_mode) == 0o755 and frontend.st_gid == 0, CONFLICT)
        anchor_bytes = canonical(expected_anchor(target, identity(frontend)))
    anchor = final / ANCHOR_NAME
    require(
        {member.name for member in final.iterdir()}
        == {ANCHOR_NAME, CONFIG_NAME, ACCESS_NAME, 'frontend'}
        and read_protected(anchor) == anchor_bytes
        and read_protected(final / CONFIG_NAME) == canonical(target.description)
        and read_protected(final / ACCESS_NAME) == target.access,
        CONFLICT,
    )
    anchor_sha = digest(anchor_bytes)
    installed = load_installation(anchor, anchor_sha, runtime_sha, target.project)
    check_stable_resources(installed, native)
    verify_validation_frontend(installed.path('frontend'), target.project, target.binding)
    installed.check_hold()
    return {
        'status': 'RELEASE_DEPLOYMENT_PREPARED',
        'anchor': str(anchor),
        'anchor_sha256': anchor_sha,
        'environment_id': installed.environment_id,
        'data_generation': installed.data_generation,
        'deployment_id': installed.deployment_id,
        'configuration_sha256': installed.configuration_sha256,
        'preparation_policy_sha256': target.binding['preparation_policy_sha256'],
        'release_id': target.binding['release_id'],
        'manifest_sha256': target.binding['manifest_sha256'],
    }


def stage_deployment(staging, target):
    staging.mkdir(mode=0o755)
    staging.chmod(0o755)
    frontend = staging / 'frontend'
    frontend.mkdir(mode=0o755)
    frontend.chmod(0o755)
    _frontend_copy(target.project.parent / 'frontend', frontend, fixed=True)
    verify_validation_frontend(frontend, target.project, target.binding)
    anchor = expected_anchor(target, identity(frontend.stat(follow_symlinks=False)))
    with protected_directory(staging) as fd:
        for name, raw in (
            (CONFIG_NAME, canonical(target.description)),
            (ACCESS_NAME, target.access),
            (ANCHOR_NAME, canonical(anchor)),
        ):
            persisted_write(fd, name, raw, mode=0o444)
        os.fsync(fd)


def prepare_deployment(args, entry):
    require(os.geteuid() == 0, UNVERIFIED)
    target = prepare_target(args, entry)
    source_root = target.source.environment_root
    deployments = source_root / DEPLOYMENTS
    final = deployments / target.deployment_id
    native = NativeEnvironmentFiles(args.root)
    check_stable_resources(target.source, native)
    with protected_directory(source_root) as root_fd:
        check_ext4(root_fd)
        fcntl.flock(root_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not os.path.lexists(deployments):
            with target.source.host_admission():
                deployments.mkdir(mode=0o755)
                deployments.chmod(0o755)
                os.fsync(root_fd)
        with protected_directory(deployments) as deployment_fd:
            metadata = os.fstat(deployment_fd)
            require(stat.S_IMODE(metadata.st_mode) == 0o755 and metadata.st_gid == 0, INVALID)
            check_ext4(deployment_fd)
            if os.path.lexists(final):
                result = read_prepared(final, target, args.sha256, native)
                os.fsync(deployment_fd)
                os.fsync(root_fd)
                return result
            with TemporaryDirectory(prefix='.walle-release-', dir=deployments) as temporary:
                staging = Path(temporary) / target.deployment_id
                stage_deployment(staging, target)
                published = False
                try:
                    with target.source.host_admission():
                        publish_directory(staging, final)
                        published = True
                        os.fsync(deployment_fd)
                        os.fsync(root_fd)
                    return read_prepared(final, target, args.sha256, native)
                except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
                    if published:
                        raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
                    raise
