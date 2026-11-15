"""Program-only original observation capture and atomic SAVE_OBSERVATION.

Captures are internal data, never client-submitted attestation or execution admission.
Git/native validation happens before the short publication transaction.
"""

from dataclasses import dataclass, field

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.git_repository_metadata import RepositoryMetadataLease
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.schema_transport import compact
from backend.app.infrastructure.windows_worktree_heads import WorktreeHeadLease, _key, metadata_head
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_integer, strict_json_object

from .configuration_identities import require_schema
from .operation_protocol import operation_steps
from .repository_acceptance import verify_saved_repository_acceptance
from .repository_observations import project_observation


@dataclass(frozen=True)
class RepositoryObservationCapture:
    root: str = field(repr=False)
    common_directory: str = field(repr=False)
    object_format: str
    repository_fingerprint: str
    worktree_fingerprint: str
    payload_json: str = field(repr=False)


def capture_repository_observation(metadata, heads):
    if type(metadata) is not RepositoryMetadataLease or type(heads) is not WorktreeHeadLease:
        raise ValueError('Original metadata and HEAD owners required')
    facts = metadata.verify()
    location = metadata.location.verify()
    bindings = heads.verify()
    if _key(heads._common.identity) != _key(location.common_directory):
        raise ValueError('Original common directory differs')
    branches = heads._branches
    if tuple(sorted((row.full_ref, row.commit_oid) for row in branches)) != facts.heads:
        raise ValueError('Original branch observations differ')
    heads.verify_observation(heads._listing, branches)
    head_source = metadata.location._sources[str(metadata.location._git.path / 'HEAD')]
    kind, value = metadata_head(head_source.verify().raw, format=facts.object_format)
    by_ref = {row.full_ref: row.commit_oid for row in branches}
    if kind == 'BRANCH':
        if value not in by_ref:
            raise ValueError('Original HEAD has no direct branch')
        commit = by_ref[value]
    else:
        commit = value
    worktrees = []
    selected = []
    for entry, binding in zip(heads._listing.entries, bindings, strict=True):
        if _key(binding.root) == _key(location.root):
            selected.append(entry)
        worktrees.append(
            {
                'canonical_path': binding.root.canonical_path,
                'head_commit': entry.head_oid,
                'branch_ref': entry.branch_ref,
            }
        )
    if len(selected) != 1 or (not selected[0].bare and selected[0].head_oid != commit):
        raise ValueError('Original selected worktree differs')
    payload = {
        'head_commit': commit,
        'local_branches': [
            {'full_ref': row.full_ref, 'commit_oid': row.commit_oid} for row in branches
        ],
        'worktrees': worktrees,
        'observed_at': operation_time(None),
        'status': 'READABLE',
    }
    project_observation(
        {'id': 1, 'repository_id': 1, 'operation_id': 1, **payload}, facts.object_format
    )
    metadata.verify()
    heads.verify()
    return RepositoryObservationCapture(
        location.root.canonical_path,
        location.common_directory.canonical_path,
        facts.object_format,
        facts.fingerprint_sha256,
        heads.fingerprint_sha256,
        canonical_input(payload),
    )


@dataclass(frozen=True)
class RepositoryObservationSource:
    repository_id: int
    root: str = field(repr=False)
    common_directory: str = field(repr=False)
    object_format: str


def _original(connection, operation_id):
    operation = connection.execute(
        'SELECT * FROM code_operations WHERE id=?', (operation_id,)
    ).fetchone()
    if (
        operation is None
        or operation['operation_type'] != 'REFRESH_REPOSITORY'
        or operation['resource_kind'] != 'REPOSITORY'
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
        raise StorageUnavailable('Original repository refresh required')
    verify_saved_repository_acceptance(connection, operation)
    repository_id = operation['resource_id']
    if strict_json_object(operation['fixed_input']) != {'repository_id': repository_id}:
        raise StorageUnavailable('Original refresh input differs')
    steps = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation_id,),
    ).fetchall()
    if [(row['step_no'], row['step_type']) for row in steps] != list(
        enumerate(operation_steps('RESOURCE', 'REFRESH_REPOSITORY'), 1)
    ) or any(row['fixed_input'] != operation['fixed_input'] for row in steps):
        raise StorageUnavailable('Original refresh steps differ')
    return operation, steps


def _repository_source(connection, repository_id):
    row = connection.execute(
        'SELECT canonical_root,git_common_dir,object_format FROM code_repositories WHERE id=?',
        (repository_id,),
    ).fetchone()
    if row is None:
        raise StorageUnavailable('Original refresh repository is missing')
    return RepositoryObservationSource(
        repository_id, row['canonical_root'], row['git_common_dir'], row['object_format']
    )


def start_repository_observation(runtime, operation_id):
    """Mark only an untouched original accepted refresh as running."""
    require_schema(runtime)
    strict_integer(operation_id, 'operation_id')
    with runtime.database.transaction(write=True) as connection:
        operation, steps = _original(connection, operation_id)
        if (
            operation['status'] != 'PENDING'
            or operation['started_at'] is not None
            or any(
                row['status'] != 'PENDING'
                or any(
                    row[key] is not None
                    for key in (
                        'external_identity',
                        'result_ref',
                        'started_at',
                        'ended_at',
                        'last_observed_at',
                    )
                )
                for row in steps
            )
        ):
            raise StorageUnavailable('Original refresh already has execution history')
        source = _repository_source(connection, operation['resource_id'])
        at = operation_time(None)
        connection.execute(
            "UPDATE code_operations SET status='RUNNING',started_at=? WHERE id=?",
            (at, operation_id),
        )
        connection.execute(
            "UPDATE code_operation_steps SET status='RUNNING',started_at=?,last_observed_at=? WHERE operation_id=? AND step_no=1",
            (at, at, operation_id),
        )
        return source


def publish_repository_observation(
    runtime, operation_id, capture=None, *, original_read_identity=None
):
    """Own the entire short transaction; unknown commit is reconciled by original ID."""
    require_schema(runtime)
    strict_integer(operation_id, 'operation_id')
    with runtime.database.transaction(write=True) as connection:
        operation, steps = _original(connection, operation_id)
        repository_id = operation['resource_id']
        existing = connection.execute(
            'SELECT * FROM code_repository_observations WHERE operation_id=?', (operation_id,)
        ).fetchall()
        if existing:
            if (
                len(existing) != 1
                or operation['status'] != 'SUCCEEDED'
                or steps[0]['status'] != 'SUCCEEDED'
                or steps[1]['status'] != 'SUCCEEDED'
                or strict_json_object(steps[1]['result_ref'])
                != {'observation_id': existing[0]['id']}
                or existing[0]['repository_id'] != repository_id
            ):
                raise StorageUnavailable('Original observation publication is inconsistent')
            return existing[0]['id']
        completing = original_read_identity is not None
        expected = ('RUNNING', 'PENDING') if completing else ('SUCCEEDED', 'RUNNING')
        if (
            operation['status'] != 'RUNNING'
            or tuple(step['status'] for step in steps) != expected
            or any(step['result_ref'] is not None for step in steps)
            or type(capture) is not RepositoryObservationCapture
            or completing
            and (
                type(original_read_identity) is not str
                or steps[0]['external_identity'] != original_read_identity
            )
        ):
            raise StorageUnavailable('Original refresh is not publishable')
        source = _repository_source(connection, repository_id)
        if (source.root, source.common_directory, source.object_format) != (
            capture.root,
            capture.common_directory,
            capture.object_format,
        ):
            raise StorageUnavailable('Original repository binding differs')
        payload = strict_json_object(capture.payload_json)
        if set(payload) != {'head_commit', 'local_branches', 'worktrees', 'observed_at', 'status'}:
            raise StorageUnavailable('Original observation payload fields differ')
        identity = entity_id(connection, EntityKind.REPOSITORY_OBSERVATION)
        data = project_observation(
            {
                'id': identity,
                'repository_id': repository_id,
                'operation_id': operation_id,
                **payload,
            },
            capture.object_format,
        )
        at = operation_time(None)
        if completing:
            connection.execute(
                "UPDATE code_operation_steps SET status='SUCCEEDED',ended_at=?,last_observed_at=? WHERE operation_id=? AND step_no=1",
                (at, at, operation_id),
            )
            connection.execute(
                "UPDATE code_operation_steps SET status='RUNNING',started_at=?,last_observed_at=? WHERE operation_id=? AND step_no=2",
                (at, at, operation_id),
            )
        connection.execute(
            'INSERT INTO code_repository_observations VALUES(?,?,?,?,?,?,?,?)',
            (
                identity,
                repository_id,
                operation_id,
                data['head_commit'],
                compact(data['local_branches']),
                compact(data['worktrees']),
                data['observed_at'],
                data['status'],
            ),
        )
        connection.execute(
            "UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,ended_at=?,last_observed_at=? WHERE operation_id=? AND step_no=2",
            (compact({'observation_id': identity}), at, at, operation_id),
        )
        connection.execute(
            "UPDATE code_operations SET status='SUCCEEDED',ended_at=? WHERE id=?",
            (at, operation_id),
        )
        return identity
