"""Prepare the fixed ordinary installation for one independent release validation."""

import os
from contextlib import ExitStack
from dataclasses import dataclass
from types import SimpleNamespace

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    absolute,
    check_ext4,
    decode,
    exact,
    identity,
    protected_directory,
    require,
)
from backend.app.infrastructure.environment_installation import (
    ANCHOR_NAME,
    CANDIDATE_PURPOSE,
    business_origin,
    identity_record,
    load_installation,
    read_access_policy,
    sha_value,
    uuid_value,
)

from .attachment_observation import directory_facts
from .operation_contract import installed_record, path_reference
from .registry_installation import managed_id
from .release_artifacts import MANIFEST, indexed_files, snapshot_file, verify_release_details
from .release_candidates import installed_candidate

POLICY = 'candidate-validation-policy.v1.json'
UNVERIFIED = 'CANDIDATE_VALIDATION_UNVERIFIED'
CONFLICT = 'CANDIDATE_VALIDATION_INSTALLATION_CONFLICT'
IDS = ('environment_id', 'data_generation', 'deployment_id')


@dataclass(frozen=True)
class CandidateInstallation:
    identities: tuple[str, str, str]
    program_sha: str
    schema_sha: str
    host_identity: dict
    binding: dict
    public_origin: str


def load_policy(path, expected, catalog, registry):
    require(path.is_absolute() and path.name == POLICY and sha_value(expected), UNVERIFIED)
    loaded = installed_record(path, expected, code=UNVERIFIED)
    endpoint_field = ('business_endpoint',) if 'business_endpoint' in loaded else ()
    record = exact(
        loaded,
        (
            'format_version',
            *catalog.scope,
            'operation_id',
            'release_id',
            'candidate_sha256',
            'delivery_operation_id',
            'manifest_sha256',
            'host_root',
            *IDS,
            'application_uid',
            'maintenance_uid',
            'shared_gid',
            'ingress_gid',
            *endpoint_field,
        ),
        UNVERIFIED,
    )
    require(
        type(record['format_version']) is int
        and record['format_version'] == 1
        and all(record[key] == value for key, value in catalog.scope.items())
        and all(
            uuid_value(record[key])
            for key in ('operation_id', 'release_id', 'delivery_operation_id', *IDS)
        )
        and len({record[key] for key in IDS}) == len(IDS)
        and all(sha_value(record[key]) for key in ('candidate_sha256', 'manifest_sha256'))
        and all(
            managed_id(record[key])
            for key in ('application_uid', 'maintenance_uid', 'shared_gid', 'ingress_gid')
        )
        and len({record['application_uid'], record['maintenance_uid'], registry.uid}) == 3
        and len({record['shared_gid'], record['ingress_gid'], registry.gid}) == 3,
        UNVERIFIED,
    )
    try:
        endpoint = (
            exact(record['business_endpoint'], ('domain', 'port'), UNVERIFIED)
            if endpoint_field
            else {}
        )
        public_origin = business_origin(record['environment_id'], **endpoint)
    except EnvironmentFailure as error:
        raise EnvironmentFailure(UNVERIFIED) from error
    location = exact(record['host_root'], ('path', 'identity'), UNVERIFIED)
    identity_record(location['identity'], UNVERIFIED)
    host = absolute(location['path'], UNVERIFIED)
    socket = str(host / record['environment_id'] / 'runtime' / 'walle.sock')
    require(
        not (host.is_relative_to(catalog.directory) or catalog.directory.is_relative_to(host))
        and socket.isascii()
        and len(socket) <= 100
        and all(char.isalnum() or char in '/._-' for char in socket),
        UNVERIFIED,
    )
    with protected_directory(host) as fd:
        require(identity(os.fstat(fd)) == location['identity'], UNVERIFIED)
        check_ext4(fd)
    return record, host, public_origin


def check_bound_candidate(expected, observation, checked):
    require(
        type(observation) is dict
        and observation.get('status') == 'RELEASE_CANDIDATE_PACKAGED'
        and all(
            observation.get(key) == expected[key]
            for key in (
                'release_id',
                'candidate_sha256',
                'delivery_operation_id',
                'manifest_sha256',
            )
        )
        and all(
            observation.get(key) == checked[key]
            for key in (
                'source_commit',
                'runtime_manifest_sha256',
                'schema_manifest_sha256',
                'target_os',
                'target_arch',
                'application_files',
                'frontend_files',
            )
        ),
        UNVERIFIED,
    )


def inspect_candidate(catalog, registry, args, plan, tool, *, host):
    from .release_publication import checked_root, disjoint, observe_candidate, publication_inputs

    descriptor = installed_candidate(catalog, plan['release_id'], plan['candidate_sha256'])
    anchor, manifest_sha = path_reference(descriptor['manifest_ref'])
    schema, schema_sha = path_reference(descriptor['schema_ref'])
    require(
        manifest_sha == plan['manifest_sha256']
        and descriptor['delivery_operation_id'] == plan['delivery_operation_id'],
        UNVERIFIED,
    )
    staged = getattr(args, 'release_publication_policy', None) is not None
    with ExitStack() as roots:
        if staged:
            publication, source, output, staged_descriptor, pin = publication_inputs(catalog, args)
            require(
                publication['release_id'] == plan['release_id']
                and publication['candidate_sha256'] == plan['candidate_sha256']
                and staged_descriptor == descriptor
                and pin == manifest_sha
                and disjoint(host, output),
                UNVERIFIED,
            )
            roots.enter_context(checked_root(source, publication['build_root']['identity']))
            roots.enter_context(checked_root(output, publication['publication_root']['identity']))
            anchor = source / MANIFEST
        observed = observe_candidate(catalog, registry, args, plan, tool, staged=staged)
        checked, manifest = verify_release_details(anchor, manifest_sha, args.sha256)
        check_bound_candidate(plan, observed, checked)
        require(checked['schema_manifest_sha256'] == schema_sha, UNVERIFIED)
    return anchor, schema, manifest


def verify_validation_frontend(frontend, project, binding):
    package = project.parent
    require(project == package / 'application', UNVERIFIED)
    manifest_sha, raw = snapshot_file(package / MANIFEST, 0o444, capture=True)
    require(manifest_sha == binding['manifest_sha256'], UNVERIFIED)
    manifest = decode(raw, UNVERIFIED)
    require(manifest['release_id'] == binding['release_id'], UNVERIFIED)
    index = exact(manifest['frontend_index_ref'], ('sha256', 'path', 'bytes'), UNVERIFIED)
    require(
        index['sha256'] == binding['frontend_index_sha256']
        and index['path'] == 'frontend-index.v1.json'
        and type(index['bytes']) is int
        and index['bytes'] > 0,
        UNVERIFIED,
    )
    digest, raw = snapshot_file(package / index['path'], 0o444, index['bytes'], capture=True)
    require(digest == index['sha256'], UNVERIFIED)
    indexed_files(decode(raw, UNVERIFIED), frontend, 'frontend')


def existing_candidate_installation(args, validation):
    environment_id, data_generation, deployment_id = validation.identities
    root = args.host_root / environment_id
    if not os.path.lexists(root):
        return None
    try:
        anchor = root / ANCHOR_NAME
        anchor_sha, _ = snapshot_file(anchor, 0o444, capture=True)
        current = load_installation(anchor, anchor_sha, args.runtime_sha256, args.project)
        expected = {
            'environment_id': environment_id,
            'data_generation': data_generation,
            'deployment_id': deployment_id,
            'schema': args.schema,
            'application_uid': args.application_uid,
            'maintenance_uid': args.maintenance_uid,
            'group': args.group,
            'ingress_group': args.ingress_group,
        }
        require(all(getattr(current, key) == value for key, value in expected.items()), CONFLICT)
        description = current.description
        require(
            description['purpose'] == CANDIDATE_PURPOSE
            and description['release_validation'] == validation.binding
            and description['program_source']
            == {'kind': 'FIXED_RELEASE', 'sha256': validation.program_sha}
            and description['schema_manifest_sha256'] == validation.schema_sha
            and read_access_policy(current)['public_origin'] == validation.public_origin,
            CONFLICT,
        )
        directory_facts(current)
        verify_validation_frontend(current.path('frontend'), args.project, validation.binding)
    except (EnvironmentFailure, OSError, ValueError, KeyError, TypeError) as error:
        raise EnvironmentFailure(CONFLICT, uncertain=True) from error
    return {
        'anchor': str(anchor),
        'anchor_sha256': anchor_sha,
        'environment_id': environment_id,
        'data_generation': data_generation,
        'deployment_id': deployment_id,
    }


def prepare_candidate_validation(catalog, registry, args, entry, tool):
    from backend.app.infrastructure.environment_provision import provision

    require(os.geteuid() == 0, UNVERIFIED)
    policy_sha = args.candidate_validation_policy_sha256
    plan, host, public_origin = load_policy(
        args.candidate_validation_policy, policy_sha, catalog, registry
    )
    anchor, schema, manifest = inspect_candidate(catalog, registry, args, plan, tool, host=host)
    protected_inputs = (anchor.parent, schema, args.root, args.project, args.anchor.parent)
    require(
        all(
            not host.is_relative_to(path) and not path.is_relative_to(host)
            for path in protected_inputs
        ),
        UNVERIFIED,
    )
    project = anchor.parent / 'application'
    program_sha = entry['verify_program'](project)
    require(sha_value(program_sha), UNVERIFIED)
    binding = {
        **{
            key: plan[key]
            for key in (
                'operation_id',
                'release_id',
                'candidate_sha256',
                'delivery_operation_id',
                'manifest_sha256',
            )
        },
        'policy_sha256': policy_sha,
        'frontend_index_sha256': manifest['frontend_index_ref']['sha256'],
    }
    validation = CandidateInstallation(
        tuple(plan[key] for key in IDS),
        program_sha,
        manifest['schema_manifest_sha256'],
        plan['host_root']['identity'],
        binding,
        public_origin,
    )
    installed = provision(
        SimpleNamespace(
            purpose=CANDIDATE_PURPOSE,
            host_root=host,
            project=project,
            frontend_input=anchor.parent / 'frontend',
            schema=schema,
            runtime_sha256=args.sha256,
            application_uid=plan['application_uid'],
            maintenance_uid=plan['maintenance_uid'],
            group=plan['shared_gid'],
            ingress_group=plan['ingress_gid'],
        ),
        validation=validation,
    )
    return {
        **installed,
        'status': 'CANDIDATE_INSTALLATION_PREPARED',
        'operation_id': binding['operation_id'],
        'release_id': binding['release_id'],
        'manifest_sha256': binding['manifest_sha256'],
    }
