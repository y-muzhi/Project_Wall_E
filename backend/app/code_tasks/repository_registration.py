"""Original REGISTER_REPOSITORY stages, without native dispatch or placeholder rows.

Capture uses the held original metadata owner. All persistence is short DB work;
the capture is program-private data, never a client attestation.
"""

from dataclasses import dataclass, field

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.git_repository_metadata import RepositoryMetadataLease
from backend.app.infrastructure.schema_transport import compact
from backend.app.infrastructure.windows_local_paths import local_absolute_path
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_integer, strict_json_object

from .configuration_identities import require_schema
from .repository_acceptance import verify_saved_repository_acceptance


@dataclass(frozen=True)
class RepositoryRegistrationCapture:
    selected_path: str = field(repr=False)
    canonical_root: str = field(repr=False)
    git_common_dir: str = field(repr=False)
    object_format: str
    metadata_sha256: str


def capture_repository_registration(metadata):
    if type(metadata) is not RepositoryMetadataLease:
        raise TypeError('Original repository metadata owner required')
    facts = metadata.verify()
    location = metadata.location.verify()
    result = RepositoryRegistrationCapture(
        str(metadata.location._root.path),
        location.root.canonical_path,
        location.common_directory.canonical_path,
        facts.object_format,
        facts.fingerprint_sha256,
    )
    metadata.verify()
    return result


def _original(connection, operation_id):
    operation = connection.execute(
        'SELECT * FROM code_operations WHERE id=?', (operation_id,)
    ).fetchone()
    if (
        operation is None
        or operation['resource_kind'] != 'REPOSITORY'
        or operation['operation_type'] != 'REGISTER_REPOSITORY'
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
        raise StorageUnavailable('Original repository registration required')
    verify_saved_repository_acceptance(connection, operation)
    fixed = strict_json_object(operation['fixed_input'])
    if (
        set(fixed) != {'name', 'root_path'}
        or type(fixed['name']) is not str
        or not fixed['name']
        or type(fixed['root_path']) is not str
    ):
        raise StorageUnavailable('Original repository registration input differs')
    steps = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no', (operation_id,)
    ).fetchall()
    if [(row['step_no'], row['step_type']) for row in steps] != [
        (1, 'VALIDATE'),
        (2, 'SAVE_FACT'),
    ] or any(row['fixed_input'] != operation['fixed_input'] for row in steps):
        raise StorageUnavailable('Original repository registration steps differ')
    return operation, fixed, steps


def _capture(capture, fixed):
    if type(capture) is not RepositoryRegistrationCapture:
        raise TypeError('Original registration capture required')
    if (
        str(local_absolute_path(fixed['root_path'])).casefold()
        != str(local_absolute_path(capture.selected_path)).casefold()
        or str(local_absolute_path(capture.canonical_root)) != capture.canonical_root
        or str(local_absolute_path(capture.git_common_dir)) != capture.git_common_dir
        or capture.object_format not in ('sha1', 'sha256')
        or type(capture.metadata_sha256) is not str
        or len(capture.metadata_sha256) != 64
        or any(char not in '0123456789abcdef' for char in capture.metadata_sha256)
    ):
        raise StorageUnavailable('Original selected repository capture differs')
    return capture


def start_repository_registration(runtime, operation_id):
    """Persist the original VALIDATE stage before external inspection begins."""
    require_schema(runtime)
    strict_integer(operation_id, 'operation_id')
    with runtime.database.transaction(write=True) as connection:
        operation, _, steps = _original(connection, operation_id)
        if operation['status'] == 'RUNNING' and steps[0]['status'] == 'RUNNING':
            return
        if operation['status'] != 'PENDING' or any(row['status'] != 'PENDING' for row in steps):
            raise StorageUnavailable('Original registration cannot start')
        at = operation_time(None)
        connection.execute(
            "UPDATE code_operations SET status='RUNNING',started_at=? WHERE id=?",
            (at, operation_id),
        )
        connection.execute(
            "UPDATE code_operation_steps SET status='RUNNING',started_at=?,last_observed_at=? WHERE operation_id=? AND step_no=1",
            (at, at, operation_id),
        )


def publish_repository_registration(runtime, operation_id, capture=None):
    """Create the complete reserved record and finish the original operation atomically."""
    require_schema(runtime)
    strict_integer(operation_id, 'operation_id')
    with runtime.database.transaction(write=True) as connection:
        operation, fixed, steps = _original(connection, operation_id)
        repository_id = operation['resource_id']
        existing = connection.execute(
            'SELECT * FROM code_repositories WHERE id=?', (repository_id,)
        ).fetchone()
        if existing is not None:
            if (
                operation['status'] != 'SUCCEEDED'
                or steps[0]['status'] != 'SUCCEEDED'
                or steps[1]['status'] != 'SUCCEEDED'
                or strict_json_object(steps[1]['result_ref']) != {'repository_id': repository_id}
                or existing['name'] != fixed['name']
            ):
                raise StorageUnavailable('Original repository publication is inconsistent')
            return repository_id
        if (
            operation['status'] != 'RUNNING'
            or steps[0]['status'] != 'RUNNING'
            or steps[1]['status'] != 'PENDING'
            or any(row['result_ref'] is not None for row in steps)
        ):
            raise StorageUnavailable('Original repository cannot be published')
        _capture(capture, fixed)
        expected = (
            fixed['name'],
            capture.canonical_root,
            capture.git_common_dir,
            capture.object_format,
        )
        # The unique original common-directory identity remains authoritative.
        at = operation_time(None)
        connection.execute(
            "UPDATE code_operation_steps SET status='SUCCEEDED',ended_at=?,last_observed_at=? WHERE operation_id=? AND step_no=1",
            (at, at, operation_id),
        )
        connection.execute(
            "UPDATE code_operation_steps SET status='RUNNING',started_at=?,last_observed_at=? WHERE operation_id=? AND step_no=2",
            (at, at, operation_id),
        )
        connection.execute(
            'INSERT INTO code_repositories VALUES(?,?,?,?,?,?)', (repository_id, *expected, at)
        )
        connection.execute(
            "UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,ended_at=?,last_observed_at=? WHERE operation_id=? AND step_no=2",
            (compact({'repository_id': repository_id}), at, at, operation_id),
        )
        connection.execute(
            "UPDATE code_operations SET status='SUCCEEDED',ended_at=? WHERE id=?",
            (at, operation_id),
        )
        return repository_id
