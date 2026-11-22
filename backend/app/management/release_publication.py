"""Seal one registered release from the fixed build into its independent publication root."""

from contextlib import contextmanager
import os
from pathlib import Path
from tempfile import TemporaryDirectory

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
    identity_record,
    sha_value,
    uuid_value,
)
from backend.app.infrastructure.schema_v22_publish import publish_directory

from .attachment_observation import invoke_observer
from .operation_contract import installed_record, path_reference
from .release_artifacts import MANIFEST, index_entries, snapshot_file, verify_release_details
from .release_candidates import installed_candidate
from .release_validation import check_bound_candidate

POLICY = 'release-publication-policy.v1.json'
INVALID = 'RELEASE_PUBLICATION_INTENT_MISMATCH'
CONFLICT = 'RELEASE_PUBLICATION_CONFLICT'
UNVERIFIED = 'RELEASE_PUBLICATION_UNVERIFIED'
ROLES = ('application', 'frontend')


def load_policy(path, expected, catalog):
    require(path.is_absolute() and path.name == POLICY and sha_value(expected), INVALID)
    record = exact(
        installed_record(path, expected, code=INVALID),
        (
            'format_version',
            *catalog.scope,
            'release_id',
            'candidate_sha256',
            'build_root',
            'publication_root',
        ),
        INVALID,
    )
    require(
        type(record['format_version']) is int
        and record['format_version'] == 1
        and all(record[key] == value for key, value in catalog.scope.items())
        and uuid_value(record['release_id'])
        and sha_value(record['candidate_sha256']),
        INVALID,
    )
    for field in ('build_root', 'publication_root'):
        root = exact(record[field], ('path', 'identity'), INVALID)
        absolute(root['path'], INVALID)
        identity_record(root['identity'], INVALID)
    return record


def disjoint(first, second):
    return not first.is_relative_to(second) and not second.is_relative_to(first)


def publication_inputs(catalog, args):
    plan = load_policy(
        args.release_publication_policy, args.release_publication_policy_sha256, catalog
    )
    descriptor = installed_candidate(catalog, plan['release_id'], plan['candidate_sha256'])
    source = absolute(plan['build_root']['path'], INVALID)
    output = absolute(plan['publication_root']['path'], INVALID)
    anchor, pin = path_reference(descriptor['manifest_ref'])
    schema, _ = path_reference(descriptor['schema_ref'])
    require(
        anchor == output / plan['release_id'] / MANIFEST
        and disjoint(source, output)
        and plan['build_root']['identity'] != plan['publication_root']['identity']
        and all(
            disjoint(root, reserved)
            for root in (source, output)
            for reserved in (catalog.directory, args.anchor.parent, args.project, args.root, schema)
        ),
        INVALID,
    )
    return plan, source, output, descriptor, pin


@contextmanager
def checked_root(path, expected):
    with protected_directory(path) as fd:
        require(identity(os.fstat(fd)) == expected, INVALID)
        check_ext4(fd)
        yield fd


def observe_candidate(catalog, registry, args, plan, tool, *, staged):
    command = [
        tool,
        'inspect-release-build' if staged else 'candidate',
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
    ]
    if staged:
        command += [
            '--release-publication-policy',
            args.release_publication_policy,
            '--release-publication-policy-sha256',
            args.release_publication_policy_sha256,
        ]
    else:
        command += [
            '--release-candidate',
            plan['release_id'],
            '--release-candidate-sha256',
            plan['candidate_sha256'],
        ]
    return invoke_observer(registry.uid, registry.gid, command, catalog.directory / 'observations')


def verify_fixed_release(root, pin, runtime_sha, entry):
    checked, manifest = verify_release_details(root / MANIFEST, pin, runtime_sha)
    program_sha = entry['verify_program'](root / 'application')
    require(sha_value(program_sha) and (root / 'frontend/index.html').is_file(), UNVERIFIED)
    return checked, manifest, program_sha


def create_read_only(path, data):
    with path.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fchmod(stream.fileno(), 0o444)
        os.fsync(stream.fileno())


def copy_members(source, target, manifest, manifest_sha):
    for role in ROLES:
        index = manifest[role + '_index_ref']
        index_path = index['path']
        measured, raw = snapshot_file(source / index_path, 0o444, index['bytes'], capture=True)
        require(measured == index['sha256'], UNVERIFIED)
        files, directories = index_entries(decode(raw, UNVERIFIED), role)
        layer = target / role
        layer.mkdir()
        ordered = sorted(directories, key=lambda path: (len(Path(path).parts), path))
        for relative in ordered:
            (layer / relative).mkdir()
        for relative, (mode, size, sha) in files.items():
            with (layer / relative).open('xb') as stream:
                measured, _ = snapshot_file(source / role / relative, mode, size, copy_to=stream)
                require(measured == sha, UNVERIFIED)
                stream.flush()
                os.fchmod(stream.fileno(), mode)
                os.fsync(stream.fileno())
        for path in [*(layer / relative for relative in reversed(ordered)), layer]:
            with protected_directory(path) as fd:
                os.fchmod(fd, 0o555)
                os.fsync(fd)
        create_read_only(target / index_path, raw)
    actual, raw = snapshot_file(source / MANIFEST, 0o444, capture=True)
    require(actual == manifest_sha, UNVERIFIED)
    create_read_only(target / MANIFEST, raw)
    with protected_directory(target) as fd:
        os.fchmod(fd, 0o555)
        os.fsync(fd)


def seal_release(catalog, registry, args, entry, tool):
    plan, source, output, descriptor, pin = publication_inputs(catalog, args)
    target = output / plan['release_id']
    expected = {
        'release_id': plan['release_id'],
        'candidate_sha256': plan['candidate_sha256'],
        'delivery_operation_id': descriptor['delivery_operation_id'],
        'manifest_sha256': pin,
    }
    published = False
    matched = False
    try:
        with checked_root(output, plan['publication_root']['identity']) as output_fd:
            if not os.path.lexists(target):
                with checked_root(source, plan['build_root']['identity']):
                    staged = observe_candidate(catalog, registry, args, plan, tool, staged=True)
                    checked, manifest, program = verify_fixed_release(
                        source, pin, args.sha256, entry
                    )
                    check_bound_candidate(expected, staged, checked)
                    with TemporaryDirectory(prefix='.seal-release-', dir=output) as temporary:
                        assembly = Path(temporary) / plan['release_id']
                        assembly.mkdir()
                        copy_members(source, assembly, manifest, pin)
                        require(
                            verify_fixed_release(assembly, pin, args.sha256, entry)[2] == program,
                            UNVERIFIED,
                        )
                        with checked_root(output, plan['publication_root']['identity']):
                            try:
                                publish_directory(assembly, target)
                                published = True
                            except FileExistsError:
                                pass
                            if published:
                                with protected_directory(Path(temporary)) as temporary_fd:
                                    os.fsync(temporary_fd)
            checked, _, program = verify_fixed_release(target, pin, args.sha256, entry)
            matched = True
            final = observe_candidate(catalog, registry, args, plan, tool, staged=False)
            check_bound_candidate(expected, final, checked)
            with checked_root(output, plan['publication_root']['identity']):
                os.fsync(output_fd)
    except (EnvironmentFailure, OSError, ValueError, KeyError, TypeError) as error:
        if published or matched:
            raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
        if os.path.lexists(target):
            raise EnvironmentFailure(CONFLICT) from error
        raise
    return {
        **expected,
        'status': 'RELEASE_PACKAGE_SEALED',
        'program_sha256': program,
        'source_commit': checked['source_commit'],
        'source_tree': final['source_tree'],
        'schema_contract_sha256': final['schema_contract_sha256'],
        'application_files': checked['application_files'],
        'frontend_files': checked['frontend_files'],
        'verification_state': final['verification_state'],
        'verification_readiness': final['verification_readiness'],
    }
