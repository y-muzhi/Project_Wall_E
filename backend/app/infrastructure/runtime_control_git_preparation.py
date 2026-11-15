"""Original partially prepared CONTROL_GIT resources, before native registration.

The original PREPARE MAY already exists. Factories are trusted Guard code, never
RPC-supplied callables. This owner dispatches no process and cannot report a full
PREPARE/RELEASE success. The original directory release follows its resource order.
"""

from dataclasses import dataclass
from threading import Event, RLock, get_ident

from .guard_action_records import GuardActionStart
from .guard_git_metadata_source import GuardMetadataDirectories
from .runtime_launch_journal import LaunchOutcomeUnknown
from .windows_attribute_handles import GuardAttributeHandles
from .windows_config_copy import PrivateConfigCopy
from .windows_config_source import LockedConfigSource
from .windows_control_git_directory_release import ControlGitDirectoryRelease
from .windows_empty_directory import ReadOnlyEmptyDirectory
from .windows_executable_pin import ExecutablePin
from .windows_job import OwnedJob
from .windows_local_paths import LocalPathGuard
from .windows_native_process import TYPED_COMMANDS
from .windows_private_package import PrivatePackageGuard
from .windows_stdio import GuardStandardIO

RESOURCE_TYPES = {
    'PROGRAM': (ExecutablePin,),
    'JOB': (OwnedJob,),
    'STDIO': (GuardStandardIO,),
    'DIRECTORY': (LocalPathGuard,),
    'READ_PACKAGE': (PrivatePackageGuard,),
    'CONFIG_SOURCE': (LockedConfigSource,),
    'METADATA_DIRECTORIES': (GuardMetadataDirectories,),
    'CONTENT_DIRECTORIES': (GuardAttributeHandles,),
    'CONFIG_COPY': (PrivateConfigCopy,),
    'GLOBAL_CONFIG': (PrivateConfigCopy,),
    'HOOKS': (ReadOnlyEmptyDirectory,),
    'COMMAND': TYPED_COMMANDS,
}


class PreparationOwnerError(LaunchOutcomeUnknown):
    pass


@dataclass
class _Slot:
    value: object | None = None
    state: str = 'NOT_ALLOCATED'
    allocating: bool = False
    known_owner: bool = False
    directory_release: ControlGitDirectoryRelease | None = None


class ControlGitPreparation:
    def __init__(self, registry, start):
        if (
            type(start) is not GuardActionStart
            or start.record.action != 'PREPARE'
            or start.record.phase != 'MAY_HAVE_BEEN_SENT'
            or not start.first_accepted
        ):
            raise PreparationOwnerError('ORIGINAL_FIRST_PREPARATION_INTENT_REQUIRED')
        self.registry = registry
        self.intent = start.record
        self.scope = start.record.scope
        self.binding_ref = start.record.allocated_binding_ref
        self._actor = get_ident()
        self._gate = RLock()
        self._stop = Event()
        self._slots = {name: _Slot() for name in RESOURCE_TYPES}
        self._order = []
        self._handles_released = False
        self._last_error = None
        self._transfer_active = False
        self._bound_entry = None
        self._binding_complete = False

    def _check_actor(self):
        if get_ident() != self._actor:
            raise PreparationOwnerError('ORIGINAL_PREPARATION_ACTOR_THREAD_DIFFERS')

    def _require_open(self):
        if self._stop.is_set() or self._handles_released:
            raise PreparationOwnerError('ORIGINAL_PREPARATION_CLOSED')
        with self.registry._gate:
            if self.registry._admission_closed:
                raise PreparationOwnerError('ORIGINAL_CONTROLLER_ADMISSION_CLOSED')
        self.registry._journal._require_controller_open(self.scope)
        fence = self.registry._journal.inspect(self.scope)
        if fence is not None and fence.stop_closed:
            raise PreparationOwnerError('ORIGINAL_PREPARATION_NONCE_CLOSED')

    def _retain(self, role, value, *, returned):
        with self._gate:
            slot = self._slots[role]
            if slot.value is not None and slot.value is not value:
                raise PreparationOwnerError('ORIGINAL_PREPARATION_RESOURCE_CONFLICT')
            slot.value = value
            slot.known_owner = type(value) in RESOURCE_TYPES[role]
            slot.state = 'UNVERIFIED'
        if not slot.known_owner:
            raise PreparationOwnerError('REGISTERED_PREPARATION_RESOURCE_REQUIRED')
        if returned:
            if role == 'DIRECTORY' and (not value.directory or not value.verify().is_directory):
                raise PreparationOwnerError('ORIGINAL_PREPARATION_DIRECTORY_REQUIRED')
            if role == 'READ_PACKAGE' and (
                not value.is_control_git_read_package
                or value.reader_sid != self.registry._controller.identity.user_sid
            ):
                raise PreparationOwnerError('ORIGINAL_PREPARATION_READER_DIFFERS')
            if role == 'STDIO' and (
                value.binding.scope != self.scope
                or value.binding.owner != self.registry._controller._expected
            ):
                raise PreparationOwnerError('ORIGINAL_PREPARATION_STDIO_DIFFERS')
            directory_release = self._directory_release(role, value)
            with self._gate:
                slot.directory_release = directory_release
                slot.state = 'RETAINED'

    def _directory_release(self, role, value):
        if role == 'READ_PACKAGE':
            parent = self.registry._journal._package
        elif role == 'HOOKS':
            package = self._slots['READ_PACKAGE']
            if package.state != 'RETAINED':
                raise PreparationOwnerError('ORIGINAL_READ_PACKAGE_REQUIRED_FOR_HOOKS')
            parent = package.value
        else:
            return None
        return ControlGitDirectoryRelease(parent, value, package_nonce=self.intent.directory_nonce)

    def allocate(self, role, factory):
        self._check_actor()
        if type(role) is not str or role not in RESOURCE_TYPES or not callable(factory):
            raise PreparationOwnerError('REGISTERED_PREPARATION_FACTORY_REQUIRED')
        with self._gate:
            self._require_open()
            if self._transfer_active or self._bound_entry is not None:
                raise PreparationOwnerError('ORIGINAL_PREPARATION_ALREADY_BOUND_OR_BUSY')
            slot = self._slots[role]
            if slot.state == 'RETAINED':
                return slot.value
            if slot.state != 'NOT_ALLOCATED':
                raise PreparationOwnerError('ORIGINAL_PREPARATION_REQUIRES_OBSERVATION')
            slot.state, slot.allocating = 'ALLOCATING', True
            self._order.append(role)
        try:
            with self.registry._controller.creation_handle():
                value = factory()
                # Retain BEFORE the liveness context exits: a late source exit
                # can raise after the constructor has returned its native owner.
                self._retain(role, value, returned=True)
        except BaseException as original:
            retained = getattr(original, 'retained_owner', None)
            with self._gate:
                if slot.value is None and retained is not None and retained is not self:
                    try:
                        self._retain(role, retained, returned=False)
                    except PreparationOwnerError:
                        pass
                if slot.value is None:
                    slot.state = 'UNKNOWN'
                self._last_error = 'ORIGINAL_PREPARATION_ALLOCATION_UNVERIFIED'
            error = PreparationOwnerError('ORIGINAL_PREPARATION_ALLOCATION_UNVERIFIED')
            error.retained_owner = self
            raise error from original
        finally:
            with self._gate:
                slot.allocating = False
            if self._stop.is_set() and role == 'JOB':
                self._terminate_known_job()
        try:
            self._require_open()
        except (RuntimeError, OSError) as original:
            self.request_stop()
            error = PreparationOwnerError('ORIGINAL_PREPARATION_CLOSED_AFTER_ALLOCATION')
            error.retained_owner = self
            raise error from original
        return value

    def begin_transfer(self, resources, arguments):
        self._check_actor()
        with self._gate:
            self._require_open()
            if self._transfer_active:
                raise PreparationOwnerError('ORIGINAL_PREPARATION_ALREADY_BOUND_OR_BUSY')
            for role, value in resources.items():
                slot = self._slots[role]
                if slot.state != 'RETAINED' or slot.value is not value or slot.allocating:
                    raise PreparationOwnerError('ORIGINAL_COMPLETE_PREPARATION_RESOURCES_REQUIRED')
            if any(
                slot.allocating or slot.state in ('UNKNOWN', 'UNVERIFIED')
                for slot in self._slots.values()
            ):
                raise PreparationOwnerError('ORIGINAL_PREPARATION_REQUIRES_OBSERVATION')
            if type(arguments) in TYPED_COMMANDS:
                command = self._slots['COMMAND']
                if command.state != 'RETAINED' or command.value is not arguments:
                    raise PreparationOwnerError('ORIGINAL_PREPARATION_COMMAND_REQUIRED')
            self._transfer_active = True

    def finish_transfer(self, entry, *, completed):
        self._check_actor()
        with self._gate:
            if entry is not None:
                if entry.preparation is not self or entry.scope != self.scope:
                    raise PreparationOwnerError('ORIGINAL_PREPARATION_ENTRY_DIFFERS')
                self._bound_entry = entry
            self._binding_complete = completed and not self._stop.is_set()
            self._transfer_active = False

    @property
    def handles_released(self):
        return self._handles_released

    def _terminate_known_job(self):
        slot = self._slots['JOB']
        if slot.known_owner and slot.value is not None and slot.state != 'HANDLES_RELEASED':
            try:
                slot.value.terminate_owned(1)
            except (RuntimeError, OSError) as error:
                self._last_error = 'ORIGINAL_PREPARATION_JOB_STOP_UNVERIFIED'
                failure = PreparationOwnerError(self._last_error)
                failure.retained_owner = self
                raise failure from error

    def request_stop(self):
        # Watch may set this while the actor's constructor is still in flight.
        self._stop.set()
        self.registry._journal.close_nonce(self.scope)
        if not self._gate.acquire(blocking=False):
            return False
        try:
            self._terminate_known_job()
            return not any(slot.allocating for slot in self._slots.values())
        finally:
            self._gate.release()

    def verify_no_activity(self):
        if not self._gate.acquire(blocking=False):
            raise PreparationOwnerError('ORIGINAL_PREPARATION_STILL_IN_FLIGHT')
        try:
            fence = self.registry._journal.inspect(self.scope)
            if (
                fence is None
                or not fence.stop_closed
                or self._transfer_active
                or self._bound_entry is None
                and fence.create_state != 'NONE'
                or any(
                    slot.allocating
                    or slot.state == 'UNKNOWN'
                    or slot.state == 'UNVERIFIED'
                    and not slot.known_owner
                    for slot in self._slots.values()
                )
            ):
                raise PreparationOwnerError('ORIGINAL_PREPARATION_STOP_UNVERIFIED')
            entry = self._bound_entry
            if entry is not None:
                if entry.root is None and fence.create_state != 'NONE':
                    raise PreparationOwnerError('ORIGINAL_BOUND_NATIVE_CREATE_UNVERIFIED')
                if (
                    entry.root is not None
                    and not entry.released
                    and entry.root.observe().state != 'EXITED'
                ):
                    raise PreparationOwnerError('ORIGINAL_BOUND_NATIVE_ROOT_STILL_ACTIVE')
            job = self._slots['JOB']
            if job.value is not None and job.known_owner and job.state != 'HANDLES_RELEASED':
                members = job.value.observe_members()
                if not members.complete or members.process_ids or members.assigned_count:
                    raise PreparationOwnerError('ORIGINAL_PREPARATION_JOB_STILL_ACTIVE_OR_UNKNOWN')
            elif job.value is not None and not job.known_owner:
                raise PreparationOwnerError('ORIGINAL_PREPARATION_JOB_OWNER_UNKNOWN')
            return True
        finally:
            self._gate.release()

    def verify_release_ready(self):
        self.verify_no_activity()
        with self._gate:
            for role in ('READ_PACKAGE', 'HOOKS'):
                slot = self._slots[role]
                if slot.state != 'NOT_ALLOCATED' and slot.directory_release is None:
                    raise PreparationOwnerError('ORIGINAL_PREPARATION_DIRECTORY_UNVERIFIED')

    def close_stopped_handles(self):
        self._check_actor()
        with self._gate:
            self.verify_release_ready()
            if self._bound_entry is not None and not self._bound_entry.released:
                raise PreparationOwnerError('ORIGINAL_NATIVE_HANDLE_RELEASE_REQUIRED')
            for role in reversed(self._order):
                slot = self._slots[role]
                if slot.state == 'HANDLES_RELEASED':
                    continue
                if not slot.known_owner or slot.value is None:
                    raise PreparationOwnerError('ORIGINAL_PREPARATION_HANDLE_OWNER_UNKNOWN')
                try:
                    resource = slot.directory_release or slot.value
                    resource.close()
                    slot.state = 'HANDLES_RELEASED'
                except BaseException as error:
                    error.retained_owner = self
                    raise
            self._handles_released = True

    def describe(self):
        with self._gate:
            return {
                'binding_ref': self.binding_ref,
                'phase': 'BOUND' if self._binding_complete else 'PREPARING',
                'bound_to_registry': self._bound_entry is not None,
                'stop_requested': self._stop.is_set(),
                'allocation_in_flight': self._transfer_active
                or any(slot.allocating for slot in self._slots.values()),
                'handles_released': self._handles_released,
                'resource_states': {role: slot.state for role, slot in self._slots.items()},
                'reason_code': self._last_error,
            }
