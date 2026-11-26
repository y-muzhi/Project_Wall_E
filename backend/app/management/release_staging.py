"""Assemble the initial immutable release build from an admitted integration delivery."""

import os
import stat
import sys
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.app.infrastructure.database import SchemaMismatch
from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    absolute,
    canonical,
    decode,
    digest,
    exact,
    identity,
    protected_directory,
    require,
)
from backend.app.infrastructure.environment_installation import (
    identity_record,
    sha_value,
    uuid_value,
)
from backend.app.infrastructure.schema_v22_publish import publish_directory
from backend.app.infrastructure.schema_v22_release import load_release

from .attachment_observation import invoke_observer
from .operation_contract import commit, installed_record, path_reference
from .registry import is_timestamp
from .release_artifacts import (
    INDEX_LIMIT,
    MANIFEST,
    external_references,
    index_entries,
    snapshot_file,
)
from .release_candidates import admitted_resources, integration_delivery
from .release_publication import (
    ROLES,
    checked_root,
    copy_index_tree,
    create_read_only,
    disjoint,
    verify_fixed_release,
)
from .release_source import (
    APPLICATION,
    PROGRAM_SNAPSHOT,
    contains,
    indexed_sources,
    parse_source_manifest,
    program_sha256,
)
from .release_source import (
    MANIFEST as SOURCE_MANIFEST,
)

POLICY = 'release-build-policy.v1.json'
BUILD_RECORD = 'build-record.v1.json'
PLAN_RECEIPT = 'staging-receipt.v1.json'
INVALID = 'RELEASE_BUILD_INTENT_MISMATCH'
UNVERIFIED = 'RELEASE_BUILD_UNVERIFIED'
CONFLICT = 'RELEASE_BUILD_CONFLICT'
ROOTS = ('application', 'frontend', 'staging_root', 'publication_root')
DELIVERY = ('delivery_operation_id', 'repository_ref', 'source_commit', 'source_tree')


def load_build_plan(catalog, args):
    path = args.release_build_policy
    pin = args.release_build_policy_sha256
    require(path.is_absolute() and path.name == POLICY and sha_value(pin), INVALID)
    plan = exact(
        installed_record(path, pin, code=INVALID),
        (
            'format_version',
            *catalog.scope,
            'release_id',
            *DELIVERY,
            'runtime_manifest_sha256',
            'schema_ref',
            'source_manifest_ref',
            *ROOTS,
            'program_sha256',
            'frontend_index_sha256',
            'compatibility_refs',
            'built_at',
        ),
        INVALID,
    )
    require(
        type(plan['format_version']) is int
        and plan['format_version'] == 1
        and all(plan[key] == value for key, value in catalog.scope.items())
        and all(uuid_value(plan[key]) for key in ('release_id', *DELIVERY[:2]))
        and len(commit(plan['source_commit'])) == len(commit(plan['source_tree']))
        and plan['runtime_manifest_sha256'] == args.sha256
        and all(sha_value(plan[key]) for key in ('program_sha256', 'frontend_index_sha256'))
        and is_timestamp(plan['built_at']),
        INVALID,
    )
    path_reference(plan['schema_ref'])
    source_manifest, _ = path_reference(plan['source_manifest_ref'])
    require(source_manifest.name == SOURCE_MANIFEST, INVALID)
    external_references(plan['compatibility_refs'])
    for name in ROOTS:
        record = exact(plan[name], ('identity', 'path'), INVALID)
        absolute(record['path'], INVALID)
        identity_record(record['identity'], INVALID)
    return plan


def observe_build_source(connection, catalog, plan, pin):
    delivery, _ = integration_delivery(connection, catalog, plan['delivery_operation_id'])
    require(
        all(
            plan[key] == delivery[field]
            for key, field in (
                ('repository_ref', 'repository_ref'),
                ('source_commit', 'commit'),
                ('source_tree', 'tree'),
            )
        ),
        INVALID,
    )
    resources = admitted_resources(catalog, delivery)
    return {
        'status': 'RELEASE_BUILD_SOURCE_VERIFIED',
        'policy_sha256': pin,
        **{key: plan[key] for key in DELIVERY},
        'resource_refs': [
            {'ref': reference, 'sha256': resources[reference]} for reference in sorted(resources)
        ],
    }


def observe(catalog, registry, args, tool, plan):
    command = [
        tool,
        'release-build-source',
        '--root',
        args.root,
        '--sha256',
        args.sha256,
        '--project',
        args.project,
        '--program-sha256',
        args.program_sha256,
        '--runtime-entry',
        args.runtime_entry,
        '--anchor',
        args.anchor,
        '--anchor-sha256',
        args.anchor_sha256,
        '--catalog',
        args.catalog,
        '--catalog-sha256',
        args.catalog_sha256,
        '--release-build-policy',
        args.release_build_policy,
        '--release-build-policy-sha256',
        args.release_build_policy_sha256,
    ]
    observed = exact(
        invoke_observer(registry.uid, registry.gid, command, catalog.directory / 'observations'),
        ('status', 'policy_sha256', *DELIVERY, 'resource_refs'),
        UNVERIFIED,
    )
    require(
        observed['status'] == 'RELEASE_BUILD_SOURCE_VERIFIED'
        and observed['policy_sha256'] == args.release_build_policy_sha256
        and all(observed[key] == plan[key] for key in DELIVERY),
        UNVERIFIED,
    )
    external_references(observed['resource_refs'])
    return observed['resource_refs']


def check_disjoint_roots(plan, catalog, args):
    roots = {key: absolute(plan[key]['path'], INVALID) for key in ROOTS}
    schema, _ = path_reference(plan['schema_ref'])
    source_manifest, _ = path_reference(plan['source_manifest_ref'])
    ordered = (*roots.values(), schema, source_manifest)
    require(
        all(disjoint(left, right) for i, left in enumerate(ordered) for right in ordered[:i])
        and all(
            disjoint(path, reserved)
            for path in ordered
            for reserved in (catalog.directory, args.anchor.parent, args.project, args.root)
        )
        and len(
            {(plan[key]['identity']['device'], plan[key]['identity']['inode']) for key in ROOTS}
        )
        == len(ROOTS),
        INVALID,
    )
    return roots


def application_sources(plan):
    source, pin = path_reference(plan['source_manifest_ref'])
    _, raw = snapshot_file(source, 0o444, capture=True)
    try:
        record = parse_source_manifest(raw, pin)
        files = indexed_sources(record['files'], record['object_format'])
    except (ValueError, RuntimeError, TypeError) as error:
        raise EnvironmentFailure(UNVERIFIED) from error
    require(
        record['commit'] == plan['source_commit']
        and record['tree'] == plan['source_tree']
        and program_sha256(files.values()) == plan['program_sha256'],
        UNVERIFIED,
    )
    return {
        name: (0o555 if row['mode'] == '100755' else 0o444, row['bytes'], row['sha256'])
        for name, row in files.items()
        if contains(name, APPLICATION)
    }


def report_walk_error(error):
    raise error


def index_tree(root, role):
    items = []
    for directory, children, files in os.walk(root, followlinks=False, onerror=report_walk_error):
        directory = Path(directory)
        with protected_directory(directory):
            require(not (directory != root and not (files or children)), UNVERIFIED)
            require(all(not (directory / child).is_symlink() for child in children), UNVERIFIED)
        for filename in files:
            path = directory / filename
            info = path.lstat()
            mode = stat.S_IMODE(info.st_mode)
            require(stat.S_ISREG(info.st_mode) and mode in (0o444, 0o555), UNVERIFIED)
            size = info.st_size
            sha256, _ = snapshot_file(path, mode, size)
            items.append(
                {
                    'path': path.relative_to(root).as_posix(),
                    'mode': format(mode, '04o'),
                    'bytes': size,
                    'sha256': sha256,
                }
            )
    items.sort(key=lambda item: item['path'].encode('utf-8'))
    index = {'format_version': 1, 'role': role, 'files': items}
    raw = canonical(index)
    require(len(raw) <= INDEX_LIMIT, UNVERIFIED)
    return raw, index_entries(index, role)


def manifest_for(plan, resources, runtime, refs):
    schema_sha = plan['schema_ref']['sha256']
    return {
        'format_version': 1,
        'release_id': plan['release_id'],
        'source_commit': plan['source_commit'],
        'target_os': sys.platform,
        'target_arch': os.uname().machine,
        **{role + '_index_ref': refs[role] for role in ROLES},
        'runtime_manifest_sha256': runtime,
        'schema_manifest_sha256': schema_sha,
        'resource_refs': resources,
        'binding_protocol': 1,
        'management_protocol': 1,
        'maintenance_contract': 1,
        'compatibility_refs': plan['compatibility_refs'],
        'verification_refs': [],
    }


def build_record(catalog, plan, manifest):
    return {
        'format_version': 1,
        **catalog.scope,
        'release_id': plan['release_id'],
        **{key: plan[key] for key in DELIVERY},
        **{
            key: manifest[key]
            for key in (
                'target_os',
                'target_arch',
                'runtime_manifest_sha256',
                'schema_manifest_sha256',
            )
        },
        **{role + '_index_sha256': manifest[role + '_index_ref']['sha256'] for role in ROLES},
        'built_at': plan['built_at'],
    }


def validate_stage(catalog, path, plan, resources, args, entry, source_files):
    with protected_directory(path):
        require(
            {file.name for file in path.iterdir()} == {'release', BUILD_RECORD, PLAN_RECEIPT},
            UNVERIFIED,
        )
    receipt = canonical({'format_version': 1, 'policy_sha256': args.release_build_policy_sha256})
    require(
        snapshot_file(path / PLAN_RECEIPT, 0o444, len(receipt))[0] == digest(receipt), UNVERIFIED
    )
    package = path / 'release'
    pin, raw = snapshot_file(package / MANIFEST, 0o444, capture=True)
    manifest = decode(raw, UNVERIFIED)
    refs = {role: manifest[role + '_index_ref'] for role in ROLES}
    require(
        raw == canonical(manifest_for(plan, resources, args.sha256, refs))
        and refs['frontend']['sha256'] == plan['frontend_index_sha256'],
        UNVERIFIED,
    )
    _, _, program = verify_fixed_release(package, pin, args.sha256, entry)
    require(program == plan['program_sha256'], UNVERIFIED)
    app_index = refs['application']
    _, app_raw = snapshot_file(package / app_index['path'], 0o444, app_index['bytes'], capture=True)
    files, _ = index_entries(decode(app_raw, UNVERIFIED), 'application')
    require(files.pop(PROGRAM_SNAPSHOT, None) is not None and files == source_files, UNVERIFIED)
    schema, schema_sha = path_reference(plan['schema_ref'])
    try:
        with protected_directory(schema):
            schema_release = load_release(
                schema, schema_sha, args.sha256, source_root=package / 'application'
            )
    except SchemaMismatch as error:
        raise EnvironmentFailure(UNVERIFIED) from error
    require(schema_release.manifest_sha256 == schema_sha, UNVERIFIED)
    build_bytes = canonical(build_record(catalog, plan, manifest))
    record_pin, _ = snapshot_file(path / BUILD_RECORD, 0o444, len(build_bytes))
    require(record_pin == digest(build_bytes), UNVERIFIED)
    with protected_directory(package) as fd:
        build_root = {'path': str(package), 'identity': identity(os.fstat(fd))}
    return pin, record_pin, build_root


def write_stage(catalog, staging, roots, plan, resources, args, entry, source_files):
    staging.mkdir(mode=0o755)
    package = staging / 'release'
    package.mkdir(mode=0o755)
    refs = {}
    for role in ROLES:
        source = roots[role]
        with checked_root(source, plan[role]['identity']):
            raw, (files, directories) = index_tree(source, role)
            if role == 'application':
                require(files == source_files, UNVERIFIED)
            else:
                require(digest(raw) == plan['frontend_index_sha256'], UNVERIFIED)
            copied = package / role
            copy_index_tree(source, copied, files, directories)
        if role == 'application':
            snapshot = canonical(entry['program_facts'](copied))
            require(digest(snapshot) == plan['program_sha256'], UNVERIFIED)
            create_read_only(copied / PROGRAM_SNAPSHOT, snapshot)
            with protected_directory(copied) as fd:
                os.fsync(fd)
            raw, _ = index_tree(copied, role)
        index_name = role + '-index.v1.json'
        refs[role] = {'path': index_name, 'sha256': digest(raw), 'bytes': len(raw)}
        create_read_only(package / index_name, raw)
    manifest = manifest_for(plan, resources, args.sha256, refs)
    create_read_only(package / MANIFEST, canonical(manifest))
    create_read_only(staging / BUILD_RECORD, canonical(build_record(catalog, plan, manifest)))
    create_read_only(
        staging / PLAN_RECEIPT,
        canonical({'format_version': 1, 'policy_sha256': args.release_build_policy_sha256}),
    )
    for path in (package, staging):
        with protected_directory(path) as fd:
            os.fchmod(fd, 0o555)
            os.fsync(fd)


def prepare_release_build(catalog, registry, args, entry, tool):
    require(os.geteuid() == 0, UNVERIFIED)
    plan = load_build_plan(catalog, args)
    roots = check_disjoint_roots(plan, catalog, args)
    resources = observe(catalog, registry, args, tool, plan)
    source_files = application_sources(plan)
    target = roots['staging_root'] / plan['release_id']
    published = matched = False
    try:
        with ExitStack() as opened:
            for key in ('staging_root', 'publication_root'):
                opened.enter_context(checked_root(roots[key], plan[key]['identity']))
            if not os.path.lexists(target):
                with TemporaryDirectory(prefix='.prepare-release-', dir=target.parent) as scratch:
                    staging = Path(scratch) / plan['release_id']
                    write_stage(catalog, staging, roots, plan, resources, args, entry, source_files)
                    validate_stage(catalog, staging, plan, resources, args, entry, source_files)
                    with checked_root(roots['staging_root'], plan['staging_root']['identity']):
                        try:
                            publish_directory(staging, target)
                            published = True
                        except FileExistsError:
                            pass
                        if published:
                            with protected_directory(staging.parent) as fd:
                                os.fsync(fd)
            pin, build_sha, build_root = validate_stage(
                catalog, target, plan, resources, args, entry, source_files
            )
            matched = True
            with checked_root(roots['staging_root'], plan['staging_root']['identity']) as fd:
                os.fsync(fd)
    except (EnvironmentFailure, OSError, ValueError, KeyError, TypeError) as error:
        if published or matched:
            raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
        if os.path.lexists(target):
            raise EnvironmentFailure(CONFLICT) from error
        raise
    candidate = {
        'format_version': 1,
        **catalog.scope,
        'release_id': plan['release_id'],
        'delivery_operation_id': plan['delivery_operation_id'],
        'manifest_ref': {
            'path': str(roots['publication_root'] / plan['release_id'] / MANIFEST),
            'sha256': pin,
        },
        'schema_ref': plan['schema_ref'],
        'build_record_ref': {'path': str(target / BUILD_RECORD), 'sha256': build_sha},
    }
    candidate_sha = digest(canonical(candidate))
    publication = {
        'format_version': 1,
        **catalog.scope,
        'release_id': plan['release_id'],
        'candidate_sha256': candidate_sha,
        'build_root': build_root,
        'publication_root': plan['publication_root'],
    }
    return {
        'status': 'RELEASE_BUILD_PREPARED',
        'candidate': candidate,
        'candidate_sha256': candidate_sha,
        'publication_policy': publication,
        'publication_policy_sha256': digest(canonical(publication)),
    }
