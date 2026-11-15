"""Dispatch only the confirmed original TASK launch owner over the authenticated pipe."""

from dataclasses import asdict
from time import monotonic

from .guard_action_journal import GuardActionJournal
from .guard_recovery import recover_task_scope
from .guard_request_header import parse_guard_request_header
from .guard_task_files import find_task_file_reservation
from .guard_task_launch_protocol import check_task_prepare_ack, decode_task_launch_action
from .guard_task_model_source import VERIFY_MODEL_SOURCE, verify_model_source
from .guard_task_network import (
    _rules,
    _sealed_task_plan,
    _sid,
    _verify_owned_filters_absent,
    release_stopped_task_network,
)
from .opencode_task_launch import TaskExecutionError
from .runtime_launch_journal import LaunchOutcomeUnknown
from .windows_config_source import ConfigReadError
from .windows_job import JobBoundaryError
from .windows_local_paths import PathBoundaryError
from .windows_native_process import NativeLaunchError
from .windows_private_package import PackageSecurityError
from .windows_private_record import PrivateRecordError
from .windows_process import ProcessObservationError
from .windows_stdio import StdioBoundaryError
from .windows_task_directory_release import TaskDirectoryRelease, TaskDirectoryReleaseError
from .windows_wfp import WfpObservationError


def _native_result(reference, observation):
    return {
        'run_kind': observation.get('run_kind', 'TASK'),
        'job_ref': reference,
        'resource_ref': observation['resource_ref'],
        'receipt_sha256': observation['receipt_sha256'],
        'process_identity': (
            None
            if observation['process_identity'] is None
            else asdict(observation['process_identity'])
        ),
        'process_state': observation['process_state'],
        'fence': asdict(observation['fence']),
    }


def _observe(actions, request, reference, execution, *, project_check=False):
    scope = request.target_scope
    action = request.input['observed_action']
    record = actions.find(scope, action)
    native = None if execution is None else execution._native
    fence = actions._journal.inspect(scope)
    observed = None if native is None or fence is None else native.observe()
    cleanup = 'UNKNOWN'
    if (
        action == 'RELEASE'
        and record is not None
        and native is not None
        and (
            execution._profile.release_evidence()
            or project_check
            and not execution._profile._started
        )
    ):
        native.stopped_evidence()
        deployment = execution._network
        epoch = request.owner_epoch if request.recovery is None else request.recovery.owner_epoch
        with _sealed_task_plan(actions, scope, epoch, deployment.provider, deployment.sublayer) as (
            original,
            marker,
            endpoints,
            _,
        ):
            _verify_owned_filters_absent(
                _rules(marker, _sid(original.directory_nonce), endpoints),
                deployment.provider,
                deployment.sublayer,
                marker,
            )
        cleanup = 'NETWORK_PROFILE_RELEASED'
        if record.phase == 'ACKNOWLEDGED':
            release = execution._directory_release
            if release is None or release.verify() != record.result['cleanup_ref']:
                raise TaskDirectoryReleaseError('ORIGINAL_TASK_DIRECTORY_RELEASE_EVIDENCE_DIFFERS')
            cleanup = 'COMPLETE'
    fence = actions._journal.inspect(scope) if observed is None else observed['fence']
    return {
        'observed_action': action,
        'action_phase': 'UNKNOWN' if record is None else record.phase,
        'input_sha256': None if record is None else record.input_sha256,
        'binding_ref': reference,
        'fence': None if fence is None else asdict(fence),
        'preparation': {
            'binding_ref': reference,
            'run_kind': (execution._dirs.run_kind if execution is not None else 'TASK'),
            'launch_state': (
                'PREPARING'
                if project_check and (execution is None or execution._confirmation is None)
                else 'CONFIRMED'
            ),
            'cleanup_state': cleanup,
        },
        'resource': None if observed is None else _native_result(reference, observed),
        'acknowledgement': None
        if record is None or record.phase != 'ACKNOWLEDGED'
        else record.result,
        'job_activity': None
        if observed is None
        else {
            'process_ids': list(observed['job'].process_ids),
            'assigned_count': observed['job'].assigned_count,
            'complete': observed['job'].complete,
        },
    }


def run_guard_task_launch(owner, request, *, peer, program, timeout_ms, cancelled):
    binding = owner.binding
    if parse_guard_request_header(request.wire, binding, peer=peer) != request:
        raise TaskExecutionError('ORIGINAL_TASK_LAUNCH_REQUEST_DIFFERS')
    digest = None if request.action == VERIFY_MODEL_SOURCE else decode_task_launch_action(request)
    deadline = monotonic() + timeout_ms / 1000

    def interrupted():
        return cancelled() or monotonic() >= deadline

    def active():
        if interrupted():
            raise TaskExecutionError('ORIGINAL_TASK_LAUNCH_INTERRUPTED')

    with owner.current_registry(
        binding, peer=peer, program=program, timeout_ms=timeout_ms, cancelled=interrupted
    ) as registry:
        scope = request.target_scope
        journal = registry._journal
        actions = GuardActionJournal(journal)
        with journal._scope(scope):
            reservation = find_task_file_reservation(actions, scope)
            if reservation is None:
                raise TaskExecutionError('ORIGINAL_TASK_LAUNCH_RESERVATION_REQUIRED')
            confirmed, _ = reservation
            reference = confirmed.allocated_binding_ref
            if (
                confirmed.phase != 'ACKNOWLEDGED'
                or confirmed.owner_epoch != request.owner_epoch
                or reference != request.binding_ref
            ):
                raise TaskExecutionError('ORIGINAL_TASK_LAUNCH_BINDING_DIFFERS')
            check_task_prepare_ack(scope, reference, confirmed.result)
            dirs = owner._task_directories.get(scope.key)
            execution = None if dirs is None else dirs._execution_preparation
            native = None if execution is None else execution._native
            active()
            if request.action == 'OBSERVE':
                return _observe(actions, request, reference, execution)
            if native is None or execution._confirmation != confirmed:
                raise TaskExecutionError('ORIGINAL_TASK_NATIVE_OWNER_REQUIRED')
            if request.action == VERIFY_MODEL_SOURCE:
                resumed = actions.find(scope, 'RESUME')
                if resumed is None or resumed.phase != 'ACKNOWLEDGED':
                    raise TaskExecutionError('ORIGINAL_TASK_MODEL_RESUME_UNVERIFIED')
                try:
                    return verify_model_source(request, execution, binding.controller, active)
                except (
                    LaunchOutcomeUnknown,
                    NativeLaunchError,
                    JobBoundaryError,
                    ProcessObservationError,
                    OSError,
                ) as error:
                    if getattr(error, 'retained_owner', None) is not None:
                        raise
                    raise TaskExecutionError('ORIGINAL_TASK_MODEL_SOURCE_UNVERIFIED') from error
            return _dispatch(
                actions, request, confirmed, execution, digest, interrupted, active, deadline
            )


def run_guard_task_recovery(current, original, request, *, peer, program, timeout_ms, cancelled):
    if original is None or request.recovery is None:
        raise TaskExecutionError('ORIGINAL_TASK_RECOVERY_OWNER_REQUIRED')
    decode_task_launch_action(request)
    binding = current.binding
    target = request.target_scope
    directories = original._task_directories.get(target.key)
    deadline = monotonic() + timeout_ms / 1000

    def interrupted():
        return cancelled() or monotonic() >= deadline

    def active():
        if interrupted():
            raise TaskExecutionError('ORIGINAL_TASK_RECOVERY_INTERRUPTED')

    with recover_task_scope(
        request,
        binding,
        peer=peer,
        program=program,
        records=current._records,
        registry=original.registry,
        directories=directories,
        timeout_ms=timeout_ms,
        cancelled=interrupted,
    ) as authorized:
        active()
        actions = GuardActionJournal(authorized.registry._journal)
        reservation = find_task_file_reservation(actions, authorized.scope)
        execution = directories._execution_preparation
        if (
            reservation is None
            or execution is None
            or execution._native is None
            or reservation[0].phase != 'ACKNOWLEDGED'
            or reservation[0].owner_epoch != request.recovery.owner_epoch
            or execution._confirmation != reservation[0]
        ):
            raise TaskExecutionError('ORIGINAL_TASK_RECOVERY_LAUNCH_UNVERIFIED')
        confirmed = reservation[0]
        check_task_prepare_ack(authorized.scope, authorized.binding_ref, confirmed.result)
        if request.action == 'OBSERVE':
            return _observe(actions, request, authorized.binding_ref, execution)
        return _dispatch(
            actions,
            request,
            confirmed,
            execution,
            None,
            interrupted,
            active,
            deadline,
            recovery_controller=current._token,
        )


def _dispatch(
    actions,
    request,
    confirmed,
    execution,
    digest,
    interrupted,
    active,
    deadline,
    *,
    recovery_controller=None,
):
    reference = confirmed.allocated_binding_ref
    native = execution._native
    if request.action == 'CREATE_SUSPENDED' and digest != confirmed.result['launch_input_sha256']:
        raise TaskExecutionError('ORIGINAL_TASK_CREATE_INPUT_DIFFERS')
    if request.action == 'RESUME':
        created = actions.find(request.target_scope, 'CREATE_SUSPENDED')
        if (
            created is None
            or created.phase != 'ACKNOWLEDGED'
            or created.result['native']['receipt_sha256'] != digest
        ):
            raise TaskExecutionError('ORIGINAL_TASK_RESUME_RECEIPT_DIFFERS')
    if request.action == 'RELEASE':
        try:
            deployment = execution._network
            release_stopped_task_network(
                actions,
                request,
                provider=deployment.provider,
                sublayer=deployment.sublayer,
                cancelled=interrupted,
                native=native,
            )
            active()
            if not execution._dirs.is_project_check or execution._profile._started:
                execution._profile.release_after_native_stop(
                    native, recovery_controller=recovery_controller
                )
            check_result = None
            if execution._dirs.is_project_check:
                check_result = execution.release_check_inputs(active)
            if execution._directory_release is None:
                execution._directory_release = TaskDirectoryRelease(execution._dirs, native)
            directory_ref = execution._directory_release.release(active)
            original_release = actions.find(request.target_scope, 'RELEASE')
            result = {
                'binding_ref': reference,
                'native': _native_result(reference, native.observe()),
                'cleanup_ref': directory_ref,
            }
            if check_result is not None:
                result['check'] = check_result
            if original_release.phase == 'ACKNOWLEDGED':
                if original_release.result != result:
                    raise TaskDirectoryReleaseError('ORIGINAL_TASK_RELEASE_ACK_DIFFERS')
                return original_release
            active()
            return actions.acknowledge(original_release, result)
        except (
            LaunchOutcomeUnknown,
            WfpObservationError,
            ConfigReadError,
            JobBoundaryError,
            PackageSecurityError,
            PathBoundaryError,
            PrivateRecordError,
            OSError,
        ) as error:
            if getattr(error, 'retained_owner', None) not in (
                None,
                native,
                execution,
                execution._directory_release,
            ):
                raise
            return None
    started = actions.begin(request)
    record = started.record
    if record.phase == 'ACKNOWLEDGED':
        return record
    if not started.first_accepted and request.action != 'STOP':
        return None
    try:
        if request.action == 'STOP':
            observed = execution.stop_native(active, deadline)
            execution._owner.registry.record_task_stopped(
                request.target_scope, execution.stop_native
            )
        else:
            with execution._dirs.launch_read(confirmed, interrupted):

                def checkpoint():
                    execution._dirs._require_open(interrupted)

                if request.action == 'CREATE_SUSPENDED':
                    observed = execution.create_native(digest, checkpoint, interrupted)
                else:
                    observed = execution.resume_native(digest, checkpoint, active)
        active()
        return actions.acknowledge(
            record, {'binding_ref': reference, 'native': _native_result(reference, observed)}
        )
    except (
        LaunchOutcomeUnknown,
        NativeLaunchError,
        ConfigReadError,
        JobBoundaryError,
        PathBoundaryError,
        PackageSecurityError,
        PrivateRecordError,
        ProcessObservationError,
        StdioBoundaryError,
        WfpObservationError,
        OSError,
    ) as error:
        if getattr(error, 'retained_owner', None) not in (None, native, execution):
            raise
        return None
