"""Resume the original capture through the trusted stage and package owners."""

from dataclasses import asdict, dataclass
from time import monotonic

from backend.app.infrastructure.content_package import (
    seal_candidate_package,
    verify_candidate_package,
)
from backend.app.infrastructure.content_package_publish import (
    create_candidate_stage,
    publish_candidate_package,
)
from backend.app.infrastructure.content_paths import ContentPathEntry
from backend.app.infrastructure.content_secret_policy import load_secret_policy
from backend.app.infrastructure.content_selection import ContentSelection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.windows_local_paths import FileIdentity
from backend.app.infrastructure.windows_private_package import PrivatePackageGuard
from backend.app.infrastructure.windows_task_workspace_tree import CandidateWorkspaceLimits
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_json_object

from .task_candidate_commit import (
    capture_package_limits,
    capture_task_current,
    claim_candidate_capture,
    commit_published_candidate,
    load_candidate_capture,
    record_candidate_seal,
    verify_capture_quiescence_record,
)
from .task_capture_quiescence import _unsettled_inputs
from .task_model_ingress import ModelWindow
from .task_start import original_start_steps
from .task_start_session import StartSessionScope, original_active_session_scope
from .task_start_workspace import WorkspaceAllocation, workspace_allocation
from .workspace_materialization import read_workspace_manifest


@dataclass(frozen=True)
class _CaptureSource:
    workspace: FileIdentity
    owner: StartSessionScope
    window: ModelWindow
    credential: str
    proof: dict
    allocation: WorkspaceAllocation
    baseline_receipt: str
    rules: str


def _source(connection, prepared, task, steps):
    binding = prepared.binding
    if not capture_task_current(prepared, task):
        raise TaskExecutionError('ORIGINAL_CAPTURE_PHASE_FENCED')
    proof = verify_capture_quiescence_record(connection, prepared, steps[0])
    session = connection.execute(
        'SELECT * FROM code_sessions WHERE id=? AND task_id=?',
        (prepared.session_id, prepared.task_id),
    ).fetchone()
    if session is None:
        raise StorageUnavailable('Original candidate source session is missing')
    owner = original_active_session_scope(connection, task, session)
    saved = strict_json_object(session['model_window'])
    if (
        saved['state'] != 'CLOSED'
        or saved['closed_at'] is None
        or saved['closed_at'] > steps[0]['ended_at']
        or saved['native_trigger_message_id'] != proof['turn']['trigger_message_id']
        or session['native_session_id'] != proof['turn']['session_id']
        or _unsettled_inputs(
            connection,
            prepared.task_id,
            binding.operation_id,
            owner.instance_id,
            completed_capture_git=True,
        )
    ):
        raise TaskExecutionError('ORIGINAL_CAPTURE_WRITERS_UNRESOLVED')
    window = ModelWindow(
        prepared.task_id,
        owner.instance_id,
        binding.control_generation,
        owner.session_id,
        session['native_session_id'],
        saved['operation_id'],
        saved['native_trigger_message_id'],
    )
    start = connection.execute(
        'SELECT * FROM code_operations WHERE id=?', (owner.operation_id,)
    ).fetchone()
    _, start_steps = original_start_steps(connection, start)
    profile = connection.execute(
        'SELECT capture_rules FROM code_execution_profile_versions WHERE id=?',
        (binding.content_profile_version_id,),
    ).fetchone()
    allocation = workspace_allocation(start, start_steps[0])
    if allocation.snapshot_id != prepared.base_snapshot_id or profile is None:
        raise StorageUnavailable('Original capture baseline or policy differs')
    return _CaptureSource(
        FileIdentity(**proof['workspace']),
        owner,
        window,
        session['gateway_credential_ref'],
        proof,
        allocation,
        start_steps[0]['result_ref'],
        profile['capture_rules'],
    )


def _owned(runtime, cancelled):
    runtime.commands().process_lock.assert_owned()
    if cancelled():
        raise TaskExecutionError('ORIGINAL_CAPTURE_CANCELLED')


def _stamp(task, steps):
    return max(
        operation_time(None),
        task['updated_at'],
        *(step['ended_at'] for step in steps if step['ended_at']),
    )


def capture_original_candidate(
    runtime,
    driver,
    operation_id,
    *,
    workspace_parent,
    store,
    exchange,
    materialization_root,
    cancelled,
):
    """A new read of the writable source is possible only under the original claim."""
    started = monotonic()
    _owned(runtime, cancelled)
    with runtime.database.transaction(write=True) as connection:
        prepared, task, operation, steps = load_candidate_capture(connection, operation_id)
        source = _source(connection, prepared, task, steps)
        if steps[1]['status'] != 'PENDING' or operation['status'] != 'RUNNING':
            raise TaskExecutionError('ORIGINAL_CAPTURE_REQUIRES_OBSERVATION')
        limits, git_limits = capture_package_limits(
            connection, prepared.binding.content_profile_version_id, task_id=prepared.task_id
        )
        if claim_candidate_capture(connection, operation_id, at=_stamp(task, steps)) != (
            prepared,
            source.workspace,
        ):
            raise StorageUnavailable('Original capture claim changed')

    def checkpoint():
        _owned(runtime, cancelled)
        with runtime.database.transaction() as connection:
            current, current_task, original, current_steps = load_candidate_capture(
                connection, operation_id
            )
            if (
                current != prepared
                or original['status'] != 'RUNNING'
                or current_steps[1]['status'] != 'RUNNING'
                or _source(connection, current, current_task, current_steps) != source
            ):
                raise TaskExecutionError('ORIGINAL_CAPTURE_PHASE_FENCED')

    def verify_native():
        evidence = driver.observe_capture_turn(
            source.owner, source.window, source.credential, checkpoint
        )
        if evidence.scope_proof() != source.proof:
            raise TaskExecutionError('ORIGINAL_CAPTURE_NATIVE_PROOF_CHANGED')

    verify_native()
    fixed = read_workspace_manifest(
        workspace_parent,
        source.allocation,
        source.baseline_receipt,
        checkpoint,
        asdict(limits),
    )
    rules = strict_json_object(source.rules)
    selection = ContentSelection(
        product_include_paths=rules['product_include_paths'],
        nonproduct_exclude_paths=rules['nonproduct_exclude_paths'],
        new_file_mode=rules['new_file_mode'],
        baseline_entries=[ContentPathEntry(item.path, item.mode) for item in fixed.entries],
    )
    secret_policy = load_secret_policy(rules['secret_policy_ref'])
    workspace_limits = CandidateWorkspaceLimits(
        limits, git_limits.max_edges, 4096, git_limits.max_seconds
    )
    checkpoint()
    stage = create_candidate_stage(store, prepared.binding)
    with PrivatePackageGuard(stage) as package:
        sealed = seal_candidate_package(
            package,
            prepared.binding,
            source_path=source.workspace.canonical_path,
            source_identity=source.workspace,
            selection=selection,
            secret_policy=secret_policy,
            workspace_limits=workspace_limits,
            git_limits=git_limits,
            started_at=started,
            quiescent=checkpoint,
            final_quiescent=verify_native,
            exchange=exchange,
            materialization_root=materialization_root,
        )
    return reconcile_original_candidate(
        runtime,
        operation_id,
        store=store,
        materialization_root=materialization_root,
        cancelled=cancelled,
        expected=sealed,
    )


def reconcile_original_candidate(
    runtime, operation_id, *, store, materialization_root, cancelled, expected=None
):
    """Continue publication by the recorded key. Recovery cannot reopen the source."""
    _owned(runtime, cancelled)
    started = monotonic()
    with runtime.database.transaction() as connection:
        prepared, task, _, steps = load_candidate_capture(connection, operation_id)
        verify_capture_quiescence_record(connection, prepared, steps[0])
        if steps[1]['status'] not in ('RUNNING', 'UNKNOWN', 'SUCCEEDED'):
            raise TaskExecutionError('ORIGINAL_CAPTURE_SEAL_REQUIRED')
        if (
            connection.execute(
                """SELECT 1 FROM code_commands WHERE operation_id=?
               AND (status<>'SUCCEEDED' OR exit_code<>0 OR exit_code IS NULL OR ended_at IS NULL)
               LIMIT 1""",
                (operation_id,),
            ).fetchone()
            is not None
        ):
            raise TaskExecutionError('ORIGINAL_CAPTURE_GIT_ACTIVITY_UNRESOLVED')
        limits, git_limits = capture_package_limits(
            connection, prepared.binding.content_profile_version_id, task_id=prepared.task_id
        )

    def checkpoint():
        _owned(runtime, cancelled)
        with runtime.database.transaction() as connection:
            current, _, _, current_steps = load_candidate_capture(connection, operation_id)
            if current != prepared or current_steps[1]['status'] not in (
                'RUNNING',
                'UNKNOWN',
                'SUCCEEDED',
            ):
                raise TaskExecutionError('ORIGINAL_CAPTURE_RECOVERY_DIFFERS')

    # Read the retained original stage or final package before any rename. In
    # particular an old CAPTURE receipt cannot be replaced by new seal bytes.
    stage = store.path / prepared.binding.package_name(staged=True)
    final = store.path / prepared.binding.package_name(staged=False)

    def present(location):
        try:
            location.lstat()
        except FileNotFoundError:
            return False
        return True

    staged, published = present(stage), present(final)
    if staged == published:
        raise TaskExecutionError('ORIGINAL_CAPTURE_PACKAGE_LOCATION_UNVERIFIED')
    with PrivatePackageGuard(stage if staged else final) as package:
        sealed = verify_candidate_package(
            package,
            prepared.binding,
            limits=limits,
            git_limits=git_limits,
            started_at=started,
            active=checkpoint,
            materialization_root=materialization_root,
            expected=expected,
        )
    with runtime.database.transaction(write=True) as connection:
        at = max(_stamp(task, steps), sealed.captured_at)
        record_candidate_seal(connection, operation_id, sealed, at=at)
    published = publish_candidate_package(
        store,
        prepared.binding,
        limits=limits,
        git_limits=git_limits,
        started_at=started,
        active=checkpoint,
        materialization_root=materialization_root,
        expected=sealed,
    )
    with runtime.database.transaction(write=True) as connection:
        _, latest, _, latest_steps = load_candidate_capture(connection, operation_id)
        return commit_published_candidate(
            connection,
            operation_id,
            published,
            at=_stamp(latest, latest_steps),
        )
