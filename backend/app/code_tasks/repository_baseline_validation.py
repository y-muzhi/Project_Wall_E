"""Original C05 read step and its bounded, private validation evidence."""

import re
from dataclasses import dataclass, field
from time import monotonic

from backend.app.infrastructure.content_manifest import (
    ContentEntry,
    ContentLimits,
    fixed_entries_sha256,
    git_oid,
)
from backend.app.infrastructure.content_secret_policy import inspect_registered_fixed_tree
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.git_baseline_ref_guard import BaselineRefConflict
from backend.app.infrastructure.git_commit_closure import ClosureLimits, inspect_commit_closure
from backend.app.infrastructure.git_object_read import GitObjectReadError
from backend.app.infrastructure.git_ref_protocol import baseline_create
from backend.app.infrastructure.git_repository_metadata import MetadataTreeError
from backend.app.infrastructure.guard_control_git_input import GIT_RUNTIME_BUNDLE_REF
from backend.app.infrastructure.windows_local_paths import FileIdentity
from backend.app.shared.command_execution import ConfigurationNotReady, operation_time
from backend.app.shared.validation import InvalidInput, strict_integer, strict_json_object

from .configuration_identities import require_schema
from .operation_protocol import operation_steps
from .repository_acceptance import verify_saved_repository_acceptance
from .repository_baseline_input import baseline_profile


@dataclass(frozen=True)
class BaselineValidationSource:
    repository_id: int
    root: str = field(repr=False)
    common_directory: str = field(repr=False)
    format: str
    commit_oid: str
    profile_version_id: int
    secret_policy_ref: str
    read_limits: ClosureLimits
    content_limits: ContentLimits
    output_budget: int


@dataclass(frozen=True)
class BaselineValidationProof:
    commit_oid: str
    tree_oid: str
    repository_sha256: str
    closure_sha256: str
    content_sha256: str


@dataclass(frozen=True)
class BaselineInspection:
    proof: BaselineValidationProof
    entries: tuple[ContentEntry, ...] = field(repr=False)


def original_baseline(connection, operation_id):
    operation = connection.execute(
        'SELECT * FROM code_operations WHERE id=?', (operation_id,)
    ).fetchone()
    if (
        operation is None
        or operation['resource_kind'] != 'REPOSITORY'
        or operation['operation_type'] != 'REGISTER_BASE'
        or any(
            operation[key] is not None
            for key in (
                'task_id',
                'testing_task_id',
                'session_id',
                'control_generation',
                'expected_state_version',
            )
        )
    ):
        raise StorageUnavailable('Original fixed baseline operation required')
    verify_saved_repository_acceptance(connection, operation)
    steps = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation_id,),
    ).fetchall()
    if [(row['step_no'], row['step_type']) for row in steps] != list(
        enumerate(operation_steps('RESOURCE', 'REGISTER_BASE'), 1)
    ) or any(row['fixed_input'] != operation['fixed_input'] for row in steps):
        raise StorageUnavailable('Original fixed baseline steps differ')
    return operation, strict_json_object(operation['fixed_input']), steps


def read_registered_baseline(connection, snapshot_id):
    """Return the sole snapshot that actually completed the original operation."""
    strict_integer(snapshot_id, 'snapshot_id')
    row = connection.execute(
        'SELECT s.*,r.object_format FROM code_snapshots s '
        'JOIN code_repositories r ON r.id=s.repository_id WHERE s.id=?',
        (snapshot_id,),
    ).fetchone()
    if row is None:
        return None
    operation, fixed, steps = original_baseline(connection, row['registration_operation_id'])
    if (
        operation['status'] != 'SUCCEEDED'
        or any(step['status'] != 'SUCCEEDED' or step['result_ref'] is None for step in steps)
        or strict_json_object(steps[3]['result_ref']) != {'snapshot_id': snapshot_id}
        or row['repository_id'] != fixed['repository_id']
        or row['id'] != fixed['snapshot_id']
        or row['commit_oid'] != fixed['commit_oid']
        or row['content_profile_version_id'] != fixed['execution_profile_version_id']
        or row['retention_ref'] != fixed['retention_ref']
        or row['content_policy_version'] != 'GIT20-BASELINE-1'
    ):
        raise StorageUnavailable('Original registered baseline differs')
    validated = baseline_proof(steps[0]['result_ref'], row['commit_oid'], row['object_format'])
    verified = baseline_proof(steps[2]['result_ref'], row['commit_oid'], row['object_format'])
    if (
        row['content_tree_oid'] != validated.tree_oid
        or verified.tree_oid != validated.tree_oid
        or verified.content_sha256 != validated.content_sha256
    ):
        raise StorageUnavailable('Original registered baseline tree differs')
    return row


def _source(connection, catalog, fixed):
    repository_id, profile_version_id = (
        fixed['repository_id'],
        fixed['execution_profile_version_id'],
    )
    repository = connection.execute(
        'SELECT canonical_root,git_common_dir,object_format FROM code_repositories WHERE id=?',
        (repository_id,),
    ).fetchone()
    profile = baseline_profile(connection, catalog, profile_version_id)
    if repository is None or profile is None:
        raise StorageUnavailable('Original baseline repository or profile is missing')
    git, content = profile
    if git['runtime_bundle_ref'] != GIT_RUNTIME_BUNDLE_REF:
        raise ConfigurationNotReady('Q20-GIT')
    row = connection.execute(
        'SELECT limits FROM code_execution_profile_versions WHERE id=?', (profile_version_id,)
    ).fetchone()
    try:
        values = strict_json_object(row['limits'])
        output_budget = strict_integer(values['max_git_output_bytes'], 'max_git_output_bytes')
        entries = strict_integer(values['max_capture_entries'], 'max_capture_entries')
        seconds = min(
            strict_integer(values['max_git_seconds'], 'max_git_seconds'),
            strict_integer(values['max_capture_seconds'], 'max_capture_seconds'),
        )
        content_limits = ContentLimits(
            **{key: strict_integer(values[key], key) for key in ContentLimits.__dataclass_fields__}
        )
    except (ValueError, TypeError, KeyError, InvalidInput) as error:
        raise StorageUnavailable('Original baseline profile limits differ') from error
    return BaselineValidationSource(
        repository_id,
        repository['canonical_root'],
        repository['git_common_dir'],
        repository['object_format'],
        fixed['commit_oid'],
        profile_version_id,
        content['secret_policy_ref'],
        ClosureLimits(entries, entries, output_budget, output_budget, seconds),
        content_limits,
        output_budget,
    )


def start_baseline_validation(runtime, operation_id):
    require_schema(runtime)
    strict_integer(operation_id, 'operation_id')
    with runtime.database.transaction(write=True) as connection:
        operation, fixed, steps = original_baseline(connection, operation_id)
        if (
            operation['status'] != 'PENDING'
            or operation['started_at'] is not None
            or any(
                step['status'] != 'PENDING'
                or any(
                    step[key] is not None
                    for key in (
                        'external_identity',
                        'result_ref',
                        'started_at',
                        'ended_at',
                        'last_observed_at',
                    )
                )
                for step in steps
            )
        ):
            raise StorageUnavailable('Original baseline already has execution history')
        source = _source(connection, runtime.catalog, fixed)
        at = operation_time(None)
        connection.execute(
            "UPDATE code_operations SET status='RUNNING',started_at=? WHERE id=?",
            (at, operation_id),
        )
        connection.execute(
            "UPDATE code_operation_steps SET status='RUNNING',started_at=?,last_observed_at=? "
            'WHERE operation_id=? AND step_no=1',
            (at, at, operation_id),
        )
        return source


def baseline_proof(raw, commit_oid, format):
    data = strict_json_object(raw)
    if (
        set(data) != set(BaselineValidationProof.__dataclass_fields__)
        or data['commit_oid'] != commit_oid
    ):
        raise StorageUnavailable('Original baseline validation facts differ')
    git_oid(data['tree_oid'], format)
    if set(data['tree_oid']) == {'0'} or any(
        type(data[key]) is not str or re.fullmatch('[0-9a-f]{64}', data[key]) is None
        for key in ('repository_sha256', 'closure_sha256', 'content_sha256')
    ):
        raise StorageUnavailable('Original baseline validation evidence differs')
    return BaselineValidationProof(**data)


def start_baseline_pin(runtime, operation_id):
    require_schema(runtime)
    strict_integer(operation_id, 'operation_id')
    with runtime.database.transaction(write=True) as connection:
        operation, fixed, steps = original_baseline(connection, operation_id)
        if (
            operation['status'] != 'RUNNING'
            or steps[0]['status'] != 'SUCCEEDED'
            or steps[0]['external_identity'] is None
            or any(
                step['status'] != 'PENDING'
                or any(
                    step[key] is not None
                    for key in (
                        'external_identity',
                        'result_ref',
                        'started_at',
                        'ended_at',
                        'last_observed_at',
                    )
                )
                for step in steps[1:]
            )
        ):
            raise StorageUnavailable('Original baseline PIN_COMMIT is not pending')
        source = _source(connection, runtime.catalog, fixed)
        proof = baseline_proof(steps[0]['result_ref'], source.commit_oid, source.format)
        intent = baseline_create(fixed['snapshot_id'], source.commit_oid, format=source.format)
        at = operation_time(None)
        connection.execute(
            "UPDATE code_operation_steps SET status='RUNNING',started_at=?,last_observed_at=? "
            'WHERE operation_id=? AND step_no=2',
            (at, at, operation_id),
        )
        return source, proof, intent


def baseline_pinned_ref(raw):
    evidence = strict_json_object(raw)
    if set(evidence) != {'process', 'prepared', 'dispatch', 'committed', 'ref'} or any(
        type(value) is not dict for value in evidence.values()
    ):
        raise StorageUnavailable('Original baseline pin evidence differs')
    try:
        file = FileIdentity(**evidence['ref'])
    except TypeError as error:
        raise StorageUnavailable('Original baseline ref identity differs') from error
    if file.is_directory is not False or any(
        type(value) is not str or not value
        for value in (file.canonical_path, file.volume_serial, file.file_id, file.filesystem)
    ):
        raise StorageUnavailable('Original baseline ref identity differs')
    location = evidence['process'].get('location_sha256')
    if type(location) is not str or re.fullmatch('[0-9a-f]{64}', location) is None:
        raise StorageUnavailable('Original baseline location proof differs')
    return file, location


def can_observe_baseline_pin(operation, steps):
    return (
        operation['status'] == 'UNKNOWN'
        and steps[0]['status'] == 'SUCCEEDED'
        and steps[1]['status'] == 'UNKNOWN'
        and steps[1]['result_ref'] is None
        and steps[1]['external_identity'] is not None
        and all(step['status'] == 'PENDING' for step in steps[2:])
    )


def pending_baseline_pin_observation(runtime, operation_id):
    require_schema(runtime)
    strict_integer(operation_id, 'operation_id')
    with runtime.database.transaction() as connection:
        operation, fixed, steps = original_baseline(connection, operation_id)
        if not can_observe_baseline_pin(operation, steps):
            raise StorageUnavailable('Original baseline PIN_COMMIT is not observable')
        source = _source(connection, runtime.catalog, fixed)
        proof = baseline_proof(steps[0]['result_ref'], source.commit_oid, source.format)
        intent = baseline_create(fixed['snapshot_id'], source.commit_oid, format=source.format)
        return source, proof, intent


def start_baseline_verify(runtime, operation_id, *, recovering_ref=None):
    require_schema(runtime)
    strict_integer(operation_id, 'operation_id')
    with runtime.database.transaction(write=True) as connection:
        operation, fixed, steps = original_baseline(connection, operation_id)
        expected = ('RUNNING', 'SUCCEEDED') if recovering_ref is None else ('UNKNOWN', 'UNKNOWN')
        if (
            (operation['status'], steps[1]['status']) != expected
            or steps[0]['status'] != 'SUCCEEDED'
            or any(step['external_identity'] is None for step in steps[:2])
            or any(
                step['status'] != 'PENDING'
                or any(
                    step[key] is not None
                    for key in (
                        'external_identity',
                        'result_ref',
                        'started_at',
                        'ended_at',
                        'last_observed_at',
                    )
                )
                for step in steps[2:]
            )
        ):
            raise StorageUnavailable('Original baseline VERIFY_PINNED_OBJECTS is not pending')
        source = _source(connection, runtime.catalog, fixed)
        baseline_proof(steps[0]['result_ref'], source.commit_oid, source.format)
        if recovering_ref is None:
            file, location = baseline_pinned_ref(steps[1]['result_ref'])
        else:
            file, location = recovering_ref
            if (
                type(file) is not FileIdentity
                or file.is_directory
                or steps[1]['result_ref'] is not None
                or type(location) is not str
                or re.fullmatch('[0-9a-f]{64}', location) is None
            ):
                raise StorageUnavailable('Original baseline recovery ref identity differs')
        at = operation_time(None)
        connection.execute(
            "UPDATE code_operation_steps SET status='RUNNING',started_at=?,last_observed_at=? "
            'WHERE operation_id=? AND step_no=3',
            (at, at, operation_id),
        )
        return source, (fixed['retention_ref'], file, location)


def inspect_baseline_ref(metadata, source, full_ref, location):
    if metadata.verify().location_sha256 != location:
        raise MetadataTreeError('ORIGINAL_BASELINE_PIN_LOCATION_DIFFERS', changed=True)
    actual = metadata.reference(full_ref)
    if actual is None:
        raise GitObjectReadError('ORIGINAL_BASELINE_REF_MISSING')
    if actual.kind != 'DIRECT' or actual.value != source.commit_oid:
        raise BaselineRefConflict('Original baseline ref now names a different target')
    return actual


def verify_baseline_ref(metadata, source, full_ref, file, location):
    actual = inspect_baseline_ref(metadata, source, full_ref, location)
    if actual.file != file:
        raise MetadataTreeError('ORIGINAL_BASELINE_REF_CHANGED', changed=True)


def inspect_baseline_source(
    source, metadata, read_object, *, check_active, materialization_root, consume_file=None
):
    """Use one original batch reader for both history and the selected tree."""
    snapshot = metadata.verify()
    binding = {
        'format': source.format,
        'read_object': read_object,
        'source_fingerprint': snapshot.fingerprint_sha256,
        'verify_source': lambda: metadata.verify().fingerprint_sha256,
        'check_active': check_active,
        'started_at': monotonic(),
    }
    closure = inspect_commit_closure((source.commit_oid,), limits=source.read_limits, **binding)
    tree = inspect_registered_fixed_tree(
        source.commit_oid,
        secret_policy_ref=source.secret_policy_ref,
        read_limits=source.read_limits,
        content_limits=source.content_limits,
        materialization_root=materialization_root,
        consume_file=consume_file,
        **binding,
    )
    proof = BaselineValidationProof(
        source.commit_oid,
        tree.tree_oid,
        snapshot.fingerprint_sha256,
        closure.fingerprint_sha256,
        fixed_entries_sha256(tree.entries),
    )
    return BaselineInspection(proof, tree.entries)
