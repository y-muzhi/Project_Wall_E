"""Keep a candidate's reserved identity, seal and current-pointer CAS together."""

from dataclasses import asdict, dataclass
from hashlib import sha256
from uuid import uuid4

from backend.app.infrastructure.content_manifest import (
    CONTENT_POLICY,
    ContentLimits,
    encode_manifest,
    manifest_sha256,
)
from backend.app.infrastructure.content_package import CandidatePackageBinding, SealedCandidate
from backend.app.infrastructure.content_package_publish import PublishedCandidate
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.git_commit_closure import ClosureLimits
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import (
    EntityKind,
    entity_id,
    increment,
    require_write_transaction,
)
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.windows_local_paths import FileIdentity, local_absolute_path
from backend.app.shared.validation import strict_integer, strict_json_object

from .repository_operations import _time
from .task_capture_quiescence import capture_steps
from .task_content_limits import authorized_content_settings


@dataclass(frozen=True)
class CapturePreparation:
    binding: CandidatePackageBinding
    task_id: int
    session_id: int
    state_version: int
    base_snapshot_id: int
    parent_candidate_id: int | None
    role: str

    def fixed(self):
        return canonical_input(asdict(self))


def reserve_candidate_identity(connection, task, operation_id, session, *, state_version):
    """Run in the acceptance transaction, before writing the immutable CAPTURE step."""
    require_write_transaction(connection)
    repo = connection.execute(
        'SELECT object_format FROM code_repositories WHERE id=?', (task['repository_id'],)
    ).fetchone()
    if (
        repo is None
        or task['id'] != session['task_id']
        or task['active_session_id'] != session['id']
        or task['control_generation'] != session['control_generation']
        or session['status'] != 'ACTIVE'
        or session['role'] not in ('BACKEND', 'FRONTEND', 'INTEGRATION')
        or state_version != increment(task['state_version'])
    ):
        raise TaskExecutionError('ORIGINAL_CAPTURE_RESERVATION_DIFFERS')
    return CapturePreparation(
        CandidatePackageBinding(
            operation_id,
            entity_id(connection, EntityKind.CODE_CANDIDATE),
            task['control_generation'],
            uuid4().hex,
            task['execution_profile_version_id'],
            repo['object_format'],
        ),
        task['id'],
        session['id'],
        state_version,
        task['base_snapshot_id'],
        task['current_candidate_id'],
        session['role'],
    )


def load_candidate_capture(connection, operation_id):
    operation = connection.execute(
        """SELECT * FROM code_operations WHERE id=? AND operation_type='CAPTURE_AND_CHECK'
           AND resource_kind='TASK' AND task_id=resource_id""",
        (operation_id,),
    ).fetchone()
    if operation is None:
        raise TaskExecutionError('ORIGINAL_CAPTURE_OPERATION_MISSING')
    steps = capture_steps(connection, operation_id)
    raw = strict_json_object(steps[1]['fixed_input'])
    binding = CandidatePackageBinding(**raw.pop('binding'))
    prepared = CapturePreparation(binding=binding, **raw)
    session = connection.execute(
        'SELECT role,control_generation FROM code_sessions WHERE id=? AND task_id=?',
        (prepared.session_id, prepared.task_id),
    ).fetchone()
    task = connection.execute(
        """SELECT t.*,r.object_format FROM code_tasks t
           JOIN code_repositories r ON r.id=t.repository_id WHERE t.id=?""",
        (prepared.task_id,),
    ).fetchone()
    if (
        prepared.fixed() != steps[1]['fixed_input']
        or operation_id != binding.operation_id
        or operation['control_generation'] != binding.control_generation
        or operation['task_id'] != prepared.task_id
        or operation['session_id'] != prepared.session_id
        or prepared.state_version != increment(operation['expected_state_version'])
        or session is None
        or session['role'] != prepared.role
        or session['control_generation'] != binding.control_generation
        or task is None
        or task['base_snapshot_id'] != prepared.base_snapshot_id
        or task['object_format'] != binding.object_format
    ):
        raise StorageUnavailable('Original candidate reservation differs')
    return prepared, task, operation, steps


def verify_capture_quiescence_record(connection, prepared, step):
    if step['status'] != 'SUCCEEDED' or step['result_ref'] is None:
        raise TaskExecutionError('ORIGINAL_CAPTURE_QUIESCE_REQUIRED')
    data = strict_json_object(step['result_ref'])
    proof = data['proof']
    observed = connection.execute(
        """SELECT * FROM code_runtime_observations WHERE id=? AND task_id=? AND operation_id=?
           AND control_generation=? AND kind='QUIESCE' AND result='VERIFIED'""",
        (
            data['quiesce_observation_id'],
            prepared.task_id,
            prepared.binding.operation_id,
            prepared.binding.control_generation,
        ),
    ).fetchone()
    digest = sha256(canonical_input(proof).encode('utf-8')).hexdigest()
    ref = f'sqlite:code_operation_steps/{prepared.binding.operation_id}/1#sha256={digest}'
    if (
        observed is None
        or observed['evidence_ref'] != ref
        or observed['observed_at'] != step['ended_at']
        or observed['active_process_count'] != proof['active_process_count']
    ):
        raise StorageUnavailable('Original capture runtime evidence differs')
    return proof


def capture_task_current(prepared, task):
    return (
        task['control_generation'] == prepared.binding.control_generation
        and task['state_version'] == prepared.state_version
        and task['stop_requested_at'] is None
        and task['active_session_id'] == prepared.session_id
        and task['current_candidate_id'] == prepared.parent_candidate_id
        and task['execution_profile_version_id'] == prepared.binding.content_profile_version_id
        and task['status'] in ('RUNNING', 'VERIFYING', 'AWAITING_TESTING', 'AWAITING_ACCEPTANCE')
    )


def claim_candidate_capture(connection, operation_id, *, at):
    """Allow one original source read attempt after verified QUIESCE."""
    require_write_transaction(connection)
    _time(at, nullable=False)
    prepared, task, operation, steps = load_candidate_capture(connection, operation_id)
    proof = verify_capture_quiescence_record(connection, prepared, steps[0])
    if (
        not capture_task_current(prepared, task)
        or at < steps[0]['ended_at']
        or operation['status'] != 'RUNNING'
        or steps[1]['status'] != 'PENDING'
        or steps[1]['external_identity'] is not None
    ):
        raise TaskExecutionError('ORIGINAL_CAPTURE_REQUIRES_OBSERVATION')
    connection.execute(
        """UPDATE code_operation_steps SET status='RUNNING',started_at=?,last_observed_at=?,
           external_identity=? WHERE operation_id=? AND step_no=2""",
        (
            at,
            at,
            canonical_input({'content_store_key': prepared.binding.content_store_key}),
            operation_id,
        ),
    )
    return prepared, FileIdentity(**proof['workspace'])


def _seal_result(seal, prepared, limits):
    if type(seal) is not SealedCandidate or seal.binding != prepared.binding:
        raise TaskExecutionError('ORIGINAL_CAPTURE_SEAL_DIFFERS')
    manifest = seal.manifest
    if (
        manifest.content_profile_version_id != prepared.binding.content_profile_version_id
        or manifest.object_format != prepared.binding.object_format
        or manifest.content_policy_version != CONTENT_POLICY
        or manifest_sha256(encode_manifest(manifest, limits)) != seal.manifest_sha256
    ):
        raise TaskExecutionError('ORIGINAL_CAPTURE_MANIFEST_DIFFERS')
    return {
        **prepared.binding.seal(manifest, seal.manifest_sha256, seal.captured_at),
        'file_count': manifest.file_count,
        'byte_count': manifest.byte_count,
    }


def record_candidate_seal(connection, operation_id, seal, *, at):
    require_write_transaction(connection)
    _time(at, nullable=False)
    prepared, _, _, steps = load_candidate_capture(connection, operation_id)
    verify_capture_quiescence_record(connection, prepared, steps[0])
    limits, _ = capture_package_limits(
        connection, prepared.binding.content_profile_version_id, task_id=prepared.task_id
    )
    result = _seal_result(seal, prepared, limits)
    step = steps[1]
    if step['status'] == 'SUCCEEDED':
        if strict_json_object(step['result_ref']) != result:
            raise StorageUnavailable('Original capture result differs')
        return
    if (
        step['status'] not in ('RUNNING', 'UNKNOWN')
        or step['started_at'] is None
        or not step['started_at'] <= seal.captured_at <= at
        or strict_json_object(step['external_identity'])
        != {'content_store_key': prepared.binding.content_store_key}
        or steps[2]['status'] != 'PENDING'
    ):
        raise TaskExecutionError('ORIGINAL_CAPTURE_SEAL_NOT_CURRENT')
    connection.execute(
        """UPDATE code_operation_steps SET status='SUCCEEDED',ended_at=?,last_observed_at=?,
           result_ref=? WHERE operation_id=? AND step_no=2""",
        (at, at, canonical_input(result), operation_id),
    )


def _fixed_row(prepared, seal_result):
    return {
        'id': prepared.binding.candidate_id,
        'task_id': prepared.task_id,
        'base_snapshot_id': prepared.base_snapshot_id,
        'capture_operation_id': prepared.binding.operation_id,
        'content_store_key': prepared.binding.content_store_key,
        'content_tree_oid': seal_result['content_tree_oid'],
        'parent_candidate_id': prepared.parent_candidate_id,
        'role': prepared.role,
        'control_generation': prepared.binding.control_generation,
        'content_policy_version': CONTENT_POLICY,
        'manifest_sha256': seal_result['manifest_sha256'],
        'captured_at': seal_result['captured_at'],
        'file_count': seal_result['file_count'],
        'byte_count': seal_result['byte_count'],
    }


def commit_published_candidate(connection, operation_id, published, *, at):
    """Record the original package once. Only a current task gets its pointer."""
    require_write_transaction(connection)
    _time(at, nullable=False)
    prepared, task, operation, steps = load_candidate_capture(connection, operation_id)
    if (
        type(published) is not PublishedCandidate
        or type(published.directory) is not FileIdentity
        or not published.directory.is_directory
        or published.directory.filesystem != 'NTFS'
        or local_absolute_path(published.directory.canonical_path).name
        != prepared.binding.package_name(staged=False)
    ):
        raise TaskExecutionError('ORIGINAL_CANDIDATE_PUBLICATION_REQUIRED')
    verify_capture_quiescence_record(connection, prepared, steps[0])
    limits, _ = capture_package_limits(
        connection, prepared.binding.content_profile_version_id, task_id=prepared.task_id
    )
    seal = _seal_result(published.seal, prepared, limits)
    if (
        steps[1]['status'] != 'SUCCEEDED'
        or strict_json_object(steps[1]['result_ref']) != seal
        or at < steps[1]['ended_at']
    ):
        raise TaskExecutionError('ORIGINAL_CANDIDATE_SEAL_REQUIRED')
    fixed = _fixed_row(prepared, seal)
    result = {
        'candidate_id': fixed['id'],
        'manifest_sha256': fixed['manifest_sha256'],
        'directory': asdict(published.directory),
    }
    existing = connection.execute(
        'SELECT * FROM code_candidates WHERE capture_operation_id=?', (operation_id,)
    ).fetchone()
    if existing is not None:
        if (
            any(existing[key] != value for key, value in fixed.items())
            or steps[2]['status'] != 'SUCCEEDED'
            or strict_json_object(steps[2]['result_ref']) != result
        ):
            raise StorageUnavailable('Original candidate result differs')
        return fixed['id']
    if (
        steps[2]['status'] not in ('PENDING', 'RUNNING', 'UNKNOWN')
        or steps[3]['status'] != 'PENDING'
    ):
        raise TaskExecutionError('ORIGINAL_CANDIDATE_PUBLICATION_NOT_CURRENT')

    columns = (*fixed, 'created_at')
    connection.execute(
        'INSERT INTO code_candidates('
        + ','.join(columns)
        + ') VALUES('
        + ','.join('?' for _ in columns)
        + ')',
        (*fixed.values(), at),
    )
    connection.execute(
        """UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,
           started_at=coalesce(started_at,?),ended_at=?,last_observed_at=?
           WHERE operation_id=? AND step_no=3""",
        (canonical_input(result), at, at, at, operation_id),
    )
    if operation['status'] in ('RUNNING', 'UNKNOWN') and capture_task_current(prepared, task):
        if (
            connection.execute(
                """UPDATE code_tasks SET current_candidate_id=?,current_verification_id=NULL,
               current_test_report_id=NULL,current_delivery_plan_id=NULL,status='VERIFYING',
               phase=?,resume_phase=NULL,state_version=?,updated_at=?,last_observed_at=?
               WHERE id=? AND state_version=? AND control_generation=? AND stop_requested_at IS NULL""",
                (
                    fixed['id'],
                    prepared.role,
                    increment(prepared.state_version),
                    at,
                    at,
                    prepared.task_id,
                    prepared.state_version,
                    prepared.binding.control_generation,
                ),
            ).rowcount
            != 1
        ):
            raise StorageUnavailable('Original candidate pointer CAS differs')
        if operation['status'] == 'UNKNOWN':
            connection.execute(
                """UPDATE code_operations SET status='RUNNING',failure_code=NULL
                   WHERE id=?""",
                (operation_id,),
            )
    elif task['stop_requested_at'] is not None and operation['status'] in ('RUNNING', 'UNKNOWN'):
        connection.execute(
            """UPDATE code_operations SET status='CANCELLED',ended_at=?,failure_code='TASK_ENDED'
               WHERE id=?""",
            (at, operation_id),
        )
    return fixed['id']


@dataclass(frozen=True)
class StoredCandidatePackage:
    binding: CandidatePackageBinding
    directory: FileIdentity
    limits: ContentLimits
    git_limits: ClosureLimits
    seal: dict


def read_stored_candidate_package(connection, row):
    prepared, _, _, steps = load_candidate_capture(connection, row['capture_operation_id'])
    if steps[1]['status'] != 'SUCCEEDED' or steps[2]['status'] != 'SUCCEEDED':
        raise StorageUnavailable('Original candidate is missing its publication steps')
    seal = strict_json_object(steps[1]['result_ref'])
    result = strict_json_object(steps[2]['result_ref'])
    fixed = _fixed_row(prepared, seal)
    if (
        any(row[key] != value for key, value in fixed.items())
        or set(result) != {'candidate_id', 'manifest_sha256', 'directory'}
        or result['candidate_id'] != row['id']
        or result['manifest_sha256'] != row['manifest_sha256']
    ):
        raise StorageUnavailable('Original candidate package identity differs')
    limits, git_limits = capture_package_limits(
        connection, prepared.binding.content_profile_version_id, task_id=prepared.task_id
    )
    return StoredCandidatePackage(
        prepared.binding,
        FileIdentity(**result['directory']),
        limits,
        git_limits,
        seal,
    )


def capture_package_limits(connection, profile_version_id, *, task_id):
    settings = authorized_content_settings(connection, profile_version_id, task_id)
    limits = ContentLimits(
        **{key: strict_integer(settings[key], key) for key in ContentLimits.__dataclass_fields__}
    )
    entries = strict_integer(settings['max_capture_entries'], 'max_capture_entries')
    io_bytes = strict_integer(settings['max_git_output_bytes'], 'max_git_output_bytes')
    seconds = strict_integer(settings['max_capture_seconds'], 'max_capture_seconds', maximum=300)
    return limits, ClosureLimits(min(4096, entries), entries, io_bytes, io_bytes, seconds)


def check_stored_candidate_seal(original, sealed):
    """Cross-check actual original package closure with its private SQLite receipt."""
    if (
        type(original) is not StoredCandidatePackage
        or type(sealed) is not SealedCandidate
        or original.binding != sealed.binding
    ):
        raise StorageUnavailable('Original candidate seal binding differs')
    actual = {
        **original.binding.seal(sealed.manifest, sealed.manifest_sha256, sealed.captured_at),
        'file_count': sealed.manifest.file_count,
        'byte_count': sealed.manifest.byte_count,
    }
    if original.seal != actual:
        raise StorageUnavailable('Original candidate sealed bytes differ')
