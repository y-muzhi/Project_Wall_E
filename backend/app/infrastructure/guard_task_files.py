"""Reserve and observe the original TASK file roles over the authenticated Guard pipe."""

from dataclasses import asdict
from time import monotonic

from backend.app.shared.validation import strict_json_object

from .guard_action_journal import GuardActionJournal
from .guard_request_header import parse_guard_request_header
from .guard_task_basis_protocol import BasisStageResult, decode_basis_stage
from .guard_task_network import task_network_unlaunched_after_stop
from .guard_task_sources import TaskSourceError, _hex, hold_guard_task_sources
from .runtime_control_git import MAX_CONTROLLER_SCOPES
from .runtime_launch_journal import LaunchFenceError, _bytes
from .windows_config_source import LockedFileSource
from .windows_local_paths import PathBoundaryError
from .windows_private_package import PackageSecurityError
from .windows_private_record import PrivateRecordAppend, PrivateRecordError
from .windows_task_basis import BasisCopyReceipt, BasisCopySpec, TaskBasisTransferError
from .windows_task_basis_group import BasisCopyPlan, TaskBasisGroup
from .windows_task_directories import TaskLpacDirectories

_MARKER_BYTES = 4096
_HELD_BYTES = 32768
_MARKER_SUFFIX = '.task-files.json'
_HELD_SUFFIX = '.task-files-held.json'


def _marker(original, digest):
    return {
        'schema_version': 1,
        'scope': original.scope.key,
        'owner_epoch': original.owner_epoch,
        'prepare_input_sha256': original.input_sha256,
        'binding_ref': original.allocated_binding_ref,
        'directory_nonce': original.directory_nonce,
        'basis_plan_sha256': digest,
    }


def _read_original(package, name, limit):
    path = package.path / name
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    identity = package.verify_member(name, directory=False)
    with LockedFileSource(path, max_file_bytes=limit, expected_file=identity) as source:
        return source.snapshot.raw


def _publish_original(package, name, raw, limit):
    with PrivateRecordAppend(package, name, raw, max_record_bytes=limit) as pending:
        pending.publish()


def find_task_file_reservation(actions, scope):
    with actions._journal._scope(scope):
        raw = _read_original(actions._journal._package, scope.key + _MARKER_SUFFIX, _MARKER_BYTES)
        if raw is None:
            return None
        actual = strict_json_object(raw)
        original = actions.find(scope, 'PREPARE')
        digest = actual.get('basis_plan_sha256')
        if original is None or scope.step_no != 4 or not _hex(digest, 64):
            raise TaskSourceError('ORIGINAL_TASK_FILE_RESERVATION_UNVERIFIED')
        if raw != _bytes(_marker(original, digest)):
            raise TaskSourceError('ORIGINAL_TASK_FILE_RESERVATION_DIFFERS')
        return original, digest


def _held_bytes(original, digest, facts):
    return _bytes(
        {'reservation': _marker(original, digest), 'directories': [asdict(fact) for fact in facts]}
    )


def reserve_task_files(owner, request, parent, root, *, peer, program, timeout_ms, cancelled):
    value = request.input
    digest = value.get('basis_plan_sha256')
    scope = request.target_scope
    if value.get('reserve_files') is not True or scope.step_no != 4 or not _hex(digest, 64):
        raise TaskSourceError('ORIGINAL_TASK_FILE_RESERVATION_INPUT_REQUIRED')

    with hold_guard_task_sources(
        owner,
        request,
        parent,
        peer=peer,
        program=program,
        timeout_ms=timeout_ms,
        cancelled=cancelled,
        runtime_root=root,
    ) as (registry, actions, checkpoint, interrupted):
        if (
            len(owner._task_directories.keys() | owner._task_profiles.keys())
            >= MAX_CONTROLLER_SCOPES
        ):
            raise TaskSourceError('CONTROLLER_TASK_FILE_CAPACITY_EXHAUSTED')
        accepted = actions.begin(request)
        if not accepted.first_accepted:
            return
        original = accepted.record
        journal = registry._journal
        with journal._gate:
            checkpoint()
            _publish_original(
                journal._package,
                scope.key + _MARKER_SUFFIX,
                _bytes(_marker(original, digest)),
                _MARKER_BYTES,
            )
        checkpoint()
        directories = TaskLpacDirectories(
            root, actions, accepted, request, owner.binding, registry._controller
        )
        owner._task_directories[scope.key] = directories
        try:
            facts = directories.allocate(cancelled=interrupted)
            with journal._gate:
                directories._require_open(interrupted)
                _publish_original(
                    journal._package,
                    scope.key + _HELD_SUFFIX,
                    _held_bytes(original, digest, facts),
                    _HELD_BYTES,
                )
        except (OSError, PackageSecurityError, PathBoundaryError, PrivateRecordError) as error:
            retained = getattr(error, 'retained_owner', None)
            if retained is not None and retained is not directories:
                raise
            # The registered owner retains the exact partial native allocation.
            raise TaskSourceError('ORIGINAL_TASK_FILE_ALLOCATION_UNVERIFIED') from error
        checkpoint()


def _verify_held_directories(journal, original, digest, directories, cancelled):
    if directories is None or directories._original != original:
        raise TaskSourceError('ORIGINAL_TASK_FILE_OWNER_UNVERIFIED')
    directories._require_open(cancelled)
    facts = directories.verify()
    raw = _read_original(journal._package, original.scope.key + _HELD_SUFFIX, _HELD_BYTES)
    if raw != _held_bytes(original, digest, facts):
        raise TaskSourceError('ORIGINAL_TASK_FILE_RECEIPT_UNVERIFIED')
    directories._require_open(cancelled)


def _stop_task_files(owner, actions, request, directories):
    started = actions.begin(request)
    stopped = started.record
    if stopped.phase == 'ACKNOWLEDGED':
        return stopped
    journal = actions._journal
    scope = request.target_scope
    fence = journal.close_nonce(scope) if started.first_accepted else journal.inspect(scope)
    if directories is None or not task_network_unlaunched_after_stop(actions, scope, fence):
        return stopped
    try:
        directories.close()
    except (LaunchFenceError, OSError, PackageSecurityError, PathBoundaryError) as error:
        retained = getattr(error, 'retained_owner', None)
        if retained is not None and retained is not directories:
            raise
        # Keep the known original owner until the writer closure can be observed.
        return stopped
    result = actions.acknowledge(
        stopped,
        {
            'binding_ref': directories.binding_ref,
            'native': {'fence': asdict(fence), 'scope_unlaunched': True},
        },
    )
    del owner._task_directories[scope.key]
    return result


class _BasisPlanIntake:
    def __init__(self, header):
        self.identity = {key: value for key, value in header.items() if key != 'document_count'}
        self.count = header['document_count']
        self.members = []

    def append(self, part):
        last = part[-1]['number']
        if part[0]['number'] != len(self.members) + 1 or last > self.count:
            raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_PLAN_PART_DIFFERS')
        source = self.identity['source_sha256']
        self.members.extend(BasisCopySpec(**item, source_sha256=source) for item in part)
        if last != self.count:
            return None
        return BasisCopyPlan(**self.identity, members=tuple(self.members))


def _perform_basis_stage(group, stage, data):
    reference = group._dirs.binding_ref
    if stage == 'OFFER':
        if data != len(group._receipts) + 1:
            raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_MEMBER_ORDER_DIFFERS')
        offer = group.offer(data)
        return {
            'binding_ref': reference,
            'number': data,
            'writer': offer.writer,
            'file': asdict(offer.expected.file),
        }
    if stage == 'PIN':
        group.pin_written(data)
        return {'binding_ref': reference, 'number': data}
    if stage == 'CONFIRM':
        number, file = data
        spec = group._slot(number).spec
        group.confirm(BasisCopyReceipt(group._dirs.scope, reference, spec, file))
        return {'binding_ref': reference, 'number': number}
    if stage == 'FINISH':
        if group._finish_requested:
            raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_FINISH_ALREADY_REQUESTED')
        group._finish_requested = True
        evidence = group.finish()
    else:
        evidence = group.verify()
    result = asdict(evidence)
    del result['scope']
    return result


def run_guard_task_basis(owner, request, *, peer, program, timeout_ms, cancelled):
    binding = owner.binding
    if parse_guard_request_header(request.wire, binding, peer=peer) != request:
        raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_REQUEST_DIFFERS')
    stage, reference, input_sha256, data = decode_basis_stage(request)
    deadline = monotonic() + timeout_ms / 1000

    def interrupted():
        return cancelled() or monotonic() >= deadline

    with owner.current_registry(
        binding, peer=peer, program=program, timeout_ms=timeout_ms, cancelled=interrupted
    ) as registry:
        scope = request.target_scope
        journal = registry._journal
        with journal._scope(scope):
            reservation = find_task_file_reservation(GuardActionJournal(journal), scope)
            if reservation is None:
                raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_RESERVATION_REQUIRED')
            original, digest = reservation
            if (
                reference != original.allocated_binding_ref
                or input_sha256 != original.input_sha256
                or original.owner_epoch != request.owner_epoch
            ):
                raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_BINDING_DIFFERS')
            directories = owner._task_directories.get(scope.key)
            try:
                _verify_held_directories(journal, original, digest, directories, interrupted)
                group = directories._basis_group
                if stage == 'BEGIN':
                    if directories._basis_intake is not None or group is not None:
                        raise TaskBasisTransferError('ORIGINAL_BASIS_GROUP_ALREADY_REGISTERED')
                    directories._basis_intake = _BasisPlanIntake(data)
                    return BasisStageResult({'binding_ref': reference, 'plan_sha256': digest})
                if stage == 'PLAN':
                    intake = directories._basis_intake
                    if intake is None or group is not None:
                        raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_PLAN_NOT_PENDING')
                    plan = intake.append(data)
                    if plan is not None:
                        if plan.sha256 != digest:
                            raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_PLAN_DIFFERS')
                        TaskBasisGroup(directories, plan, cancelled=lambda: False)
                        directories._basis_intake = None
                    return BasisStageResult(
                        {'binding_ref': reference, 'last_number': data[-1]['number']}
                    )
                if group is None:
                    raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_GROUP_REQUIRED')
                with group.action(interrupted):
                    return BasisStageResult(_perform_basis_stage(group, stage, data))
            except (
                LaunchFenceError,
                OSError,
                PackageSecurityError,
                PathBoundaryError,
                PrivateRecordError,
            ) as error:
                retained = getattr(error, 'retained_owner', None)
                group = None if directories is None else directories._basis_group
                if retained is not None and retained is not group:
                    raise
                raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_UNVERIFIED') from error


def run_guard_task_file_action(owner, request, *, peer, program, timeout_ms, cancelled):
    binding = owner.binding
    if parse_guard_request_header(request.wire, binding, peer=peer) != request:
        raise TaskSourceError('ORIGINAL_TASK_FILE_REQUEST_DIFFERS')
    if request.recovery is not None or request.action not in ('OBSERVE', 'STOP'):
        return None
    if request.action == 'STOP' and request.input != {}:
        raise TaskSourceError('ORIGINAL_TASK_FILE_STOP_INPUT_DIFFERS')

    with owner.current_registry(
        binding, peer=peer, program=program, timeout_ms=timeout_ms, cancelled=cancelled
    ) as registry:
        scope = request.target_scope
        journal = registry._journal
        actions = GuardActionJournal(journal)
        with journal._scope(scope):
            reservation = find_task_file_reservation(actions, scope)
            if reservation is None:
                return None
            original, digest = reservation
            reference = original.allocated_binding_ref
            if (
                original.owner_epoch != request.owner_epoch
                or request.binding_ref not in (None, reference)
                or cancelled()
            ):
                raise TaskSourceError('ORIGINAL_TASK_FILE_BINDING_DIFFERS')
            directories = owner._task_directories.get(scope.key)
            if request.action == 'STOP':
                return _stop_task_files(owner, actions, request, directories)
            observed_action = request.input['observed_action']
            observed = actions.find(scope, observed_action)
            fence = journal.inspect(scope)
            try:
                _verify_held_directories(journal, original, digest, directories, cancelled)
            except (LaunchFenceError, OSError, PackageSecurityError, PathBoundaryError):
                state = 'UNKNOWN'
            else:
                state = 'HELD'
            acknowledged = observed is not None and observed.phase == 'ACKNOWLEDGED'
            return {
                'observed_action': observed_action,
                'action_phase': 'UNKNOWN' if observed is None else observed.phase,
                'input_sha256': None if observed is None else observed.input_sha256,
                'binding_ref': reference,
                'fence': None if fence is None else asdict(fence),
                'preparation': {
                    'binding_ref': reference,
                    'run_kind': 'TASK',
                    'basis_plan_sha256': digest,
                    'directory_state': state,
                },
                'resource': None,
                'acknowledgement': {'binding_ref': reference} if acknowledged else None,
                'job_activity': None,
            }
