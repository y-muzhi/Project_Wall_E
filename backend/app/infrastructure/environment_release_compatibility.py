"""Publish bounded same-schema evidence from an ordinary installation and a fixed draft."""

import fcntl
import os

from backend.app.management.release_artifacts import (
    MANIFEST,
    snapshot_file,
    verify_release_details,
)

from .environment_backup_package import read_policy
from .environment_files import (
    absolute,
    canonical,
    check_ext4,
    digest,
    exact,
    identity,
    persisted_write,
    protected_directory,
    read_entry,
    require,
)
from .environment_installation import (
    CAPABILITIES,
    WORKSPACE_PURPOSES,
    identity_record,
    load_installation,
    uuid_value,
)
from .environment_recovery_installation import checked_ref
from .schema_v22_release import load_release

POLICY = 'release-compatibility-policy.v1.json'
COMPATIBILITY = 'same-schema-compatibility.v1.json'
INVALID = 'RELEASE_COMPATIBILITY_INTENT_MISMATCH'
UNVERIFIED = 'RELEASE_COMPATIBILITY_UNVERIFIED'
CONFLICT = 'RELEASE_COMPATIBILITY_CONFLICT'


def compatibility_record(
    key, source, source_schema, manifest, target_schema, target_program, *, code=UNVERIFIED
):
    required = source.description['required_capabilities']
    require(
        uuid_value(key)
        and len(required) == len(CAPABILITIES)
        and set(required) == CAPABILITIES
        and target_schema.schema_contract_sha256 == source_schema.schema_contract_sha256,
        code,
    )
    return {
        'format_version': 1,
        'compatibility_id': key,
        'mode': 'SAME_SCHEMA',
        'target_release_id': manifest['release_id'],
        'source_program_sha256': source.description['program_source']['sha256'],
        'source_configuration_sha256': source.configuration_sha256,
        'source_schema_manifest_sha256': source.description['schema_manifest_sha256'],
        'source_runtime_manifest_sha256': source.description['runtime_manifest_sha256'],
        'target_runtime_manifest_sha256': manifest['runtime_manifest_sha256'],
        'target_schema_manifest_sha256': manifest['schema_manifest_sha256'],
        'target_program_snapshot_sha256': target_program,
        'target_application_index_sha256': manifest['application_index_ref']['sha256'],
        'target_frontend_index_sha256': manifest['frontend_index_ref']['sha256'],
        'schema_contract_sha256': target_schema.schema_contract_sha256,
        'required_capabilities': required,
    }


def checked_schema(path, expected, runtime_sha):
    with protected_directory(path):
        return load_release(path, expected, runtime_sha)


def record_compatibility(args, entry):
    require(os.geteuid() == 0, UNVERIFIED)
    plan = read_policy(
        args.release_compatibility_policy,
        args.release_compatibility_policy_sha256,
        POLICY,
        (
            'compatibility_id',
            'installation_sha256',
            'candidate_draft',
            'target_schema_directory',
            'output',
        ),
    )
    key = plan['compatibility_id']
    require(uuid_value(key) and plan['installation_sha256'] == args.anchor_sha256, INVALID)
    source = load_installation(args.anchor, args.anchor_sha256, args.sha256, args.project)
    require(
        source.description['purpose'] in WORKSPACE_PURPOSES
        and 'recovery_replica' not in source.description
        and source.description['program_source']['sha256'] == args.program_sha256,
        INVALID,
    )
    draft, draft_sha = checked_ref(plan['candidate_draft'], MANIFEST)
    target_path = absolute(plan['target_schema_directory'], INVALID)
    location = exact(plan['output'], ('path', 'identity'), INVALID)
    output = absolute(location['path'], INVALID)
    identity_record(location['identity'], INVALID)
    require(
        all(
            not output.is_relative_to(path) and not path.is_relative_to(output)
            for path in (
                source.environment_root,
                args.root,
                args.project,
                source.schema,
                draft.parent,
                target_path,
                args.release_compatibility_policy.parent,
            )
        ),
        INVALID,
    )
    _, manifest = verify_release_details(draft, draft_sha, args.sha256)
    require(all(ref['ref'] != key for ref in manifest['compatibility_refs']), INVALID)
    target_project = draft.parent / 'application'
    target_program = entry['verify_program'](target_project)
    require(
        snapshot_file(target_project / 'program-snapshot.v1.json', 0o444)[0] == target_program,
        UNVERIFIED,
    )
    original = checked_schema(
        source.schema, source.description['schema_manifest_sha256'], args.sha256
    )
    target = checked_schema(target_path, manifest['schema_manifest_sha256'], args.sha256)
    raw = canonical(compatibility_record(key, source, original, manifest, target, target_program))
    with protected_directory(output) as directory:
        require(identity(os.fstat(directory)) == location['identity'], INVALID)
        check_ext4(directory)
        fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            actual = read_entry(directory, COMPATIBILITY, owner=0, reject_writers=0o222)
        except FileNotFoundError:
            persisted_write(directory, COMPATIBILITY, raw, mode=0o444)
            actual = read_entry(directory, COMPATIBILITY, owner=0, reject_writers=0o222)
        require(actual == raw, CONFLICT)
        os.fsync(directory)
    return {
        'status': 'RELEASE_COMPATIBILITY_RECORDED',
        'ref': key,
        'sha256': digest(raw),
        'path': str(output / COMPATIBILITY),
    }
