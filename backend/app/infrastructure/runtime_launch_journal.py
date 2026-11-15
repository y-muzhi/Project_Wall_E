"""Runtime Guard's private launch-nonce fence; never WALL-E business state.

Inputs are an authenticated controller reference, original step and immutable
input digest. Native callbacks run only after durable dispatch intent. Outputs
describe the fence/history, never 'stopped', task completion or OS absence.
"""

import hashlib
import json
import os
import re
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from threading import RLock
from uuid import UUID, uuid4

from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_json_object

from .guard_service_diagnostics import GuardFailureStage, diagnostic_for_failure
from .process_lock import ProcessLock
from .windows_local_paths import LocalPathGuard, local_absolute_path
from .windows_private_package import PrivatePackageGuard
from .windows_private_record import PrivateRecordError

MAX_STATE_BYTES = 65536
MAX_LAUNCH_RECORDS = 100000
CREATE_STATES = ('NONE', 'MAY_HAVE_BEEN_SENT', 'RESOURCE_RECORDED')
RESUME_STATES = ('NONE', 'MAY_HAVE_BEEN_SENT', 'ACKNOWLEDGED')


class LaunchFenceError(RuntimeError):
    pass


class LaunchOutcomeUnknown(LaunchFenceError):
    pass


def _hex(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise LaunchFenceError('GUARD_DIGEST_INVALID')
    return value


def _positive(value):
    if type(value) is not int or not 1 <= value <= MAX_SAFE_INTEGER:
        raise LaunchFenceError('GUARD_STEP_ID_INVALID')
    return value


def _bytes(value):
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False
        )
        + '\n'
    ).encode('utf-8')


def _now():
    return datetime.now(UTC).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def _resource(value):
    if type(value) is not str or re.fullmatch('[a-zA-Z0-9_-]{16,128}', value) is None:
        raise LaunchFenceError('GUARD_RESOURCE_REFERENCE_INVALID')
    return value


@dataclass(frozen=True)
class LaunchScope:
    controller_ref: str
    operation_id: int
    step_no: int
    nonce: str

    def __post_init__(self):
        _hex(self.controller_ref)
        _positive(self.operation_id)
        _positive(self.step_no)
        _resource(self.nonce)

    @property
    def key(self):
        return hashlib.sha256(_bytes(asdict(self))).hexdigest()


@dataclass(frozen=True)
class TestingLaunchScope(LaunchScope):
    owner_id: int
    control_generation: int
    owner_kind: str = 'TESTING'

    def __post_init__(self):
        super().__post_init__()
        if self.owner_kind != 'TESTING':
            raise LaunchFenceError('ORIGINAL_TESTING_LAUNCH_OWNER_REQUIRED')
        _positive(self.owner_id)
        _positive(self.control_generation)


def decode_launch_scope(value):
    if type(value) is dict:
        fields = set(value)
        for scope_type in (LaunchScope, TestingLaunchScope):
            if fields == set(scope_type.__dataclass_fields__):
                return scope_type(**value)
    raise LaunchFenceError('ORIGINAL_LAUNCH_SCOPE_FIELDS_REQUIRED')


@dataclass(frozen=True)
class LaunchFence:
    schema_version: int
    scope: LaunchScope
    input_sha256: str | None
    create_state: str
    resume_state: str
    resource_ref: str | None
    stop_closed: bool
    record_revision: int
    updated_at: str


def _decode(raw, scope):
    value = strict_json_object(raw)
    if set(value) != set(LaunchFence.__dataclass_fields__):
        raise LaunchFenceError('GUARD_STATE_FIELDS_INVALID')
    parsed_scope = decode_launch_scope(value['scope'])
    if parsed_scope != scope:
        raise LaunchFenceError('GUARD_STATE_SCOPE_DIFFERS')
    if (
        type(value['schema_version']) is not int
        or value['schema_version'] != 1
        or type(value['stop_closed']) is not bool
    ):
        raise LaunchFenceError('GUARD_STATE_VERSION_INVALID')
    if value['input_sha256'] is not None:
        _hex(value['input_sha256'])
    if value['create_state'] not in CREATE_STATES or value['resume_state'] not in RESUME_STATES:
        raise LaunchFenceError('GUARD_STATE_PHASE_INVALID')
    if value['resource_ref'] is not None:
        _resource(value['resource_ref'])
    if (value['resource_ref'] is not None) != (value['create_state'] == 'RESOURCE_RECORDED'):
        raise LaunchFenceError('GUARD_STATE_RESOURCE_DIFFERS')
    if value['input_sha256'] is None and (
        not value['stop_closed']
        or value['create_state'] != 'NONE'
        or value['resume_state'] != 'NONE'
    ):
        raise LaunchFenceError('GUARD_STATE_INPUT_MISSING')
    if value['resume_state'] != 'NONE' and value['resource_ref'] is None:
        raise LaunchFenceError('GUARD_STATE_RESUME_WITHOUT_RESOURCE')
    _positive(value['record_revision'])
    at = value['updated_at']
    if (
        type(at) is not str
        or re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z', at)
        is None
    ):
        raise LaunchFenceError('GUARD_STATE_TIME_INVALID')
    try:
        datetime.fromisoformat(at)
    except ValueError:
        raise LaunchFenceError('GUARD_STATE_TIME_INVALID') from None
    record = LaunchFence(**{**value, 'scope': parsed_scope})
    if _bytes(asdict(record)) != raw:
        raise LaunchFenceError('GUARD_STATE_NOT_CANONICAL')
    return record


@dataclass(frozen=True)
class ControllerSeal:
    schema_version: int
    controller_ref: str
    owner_epoch: str
    registration_sha256: str
    sealed_at: str

    @property
    def sha256(self):
        return hashlib.sha256(_bytes(asdict(self))).hexdigest()


def decode_controller_seal(raw, controller_ref):
    _hex(controller_ref)
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_STATE_BYTES:
        raise LaunchOutcomeUnknown('GUARD_CONTROLLER_SEAL_SIZE_INVALID')
    value = strict_json_object(raw)
    if set(value) != set(ControllerSeal.__dataclass_fields__):
        raise LaunchOutcomeUnknown('GUARD_CONTROLLER_SEAL_FIELDS_INVALID')
    if (
        type(value['schema_version']) is not int
        or value['schema_version'] != 1
        or value['controller_ref'] != controller_ref
        or type(value['owner_epoch']) is not str
    ):
        raise LaunchOutcomeUnknown('GUARD_CONTROLLER_SEAL_OWNER_INVALID')
    try:
        epoch = UUID(value['owner_epoch'])
        if epoch.version != 4 or str(epoch) != value['owner_epoch']:
            raise ValueError('Noncanonical epoch')
    except ValueError as error:
        raise LaunchOutcomeUnknown('GUARD_CONTROLLER_SEAL_EPOCH_INVALID') from error
    _hex(value['registration_sha256'])
    at = value['sealed_at']
    if (
        type(at) is not str
        or re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z', at)
        is None
    ):
        raise LaunchOutcomeUnknown('GUARD_CONTROLLER_SEAL_TIME_INVALID')
    try:
        datetime.fromisoformat(at)
    except ValueError as error:
        raise LaunchOutcomeUnknown('GUARD_CONTROLLER_SEAL_TIME_INVALID') from error
    result = ControllerSeal(**value)
    if _bytes(asdict(result)) != raw:
        raise LaunchOutcomeUnknown('GUARD_CONTROLLER_SEAL_NOT_CANONICAL')
    return result


class _ScopeGate:
    def __init__(self, controller_ref):
        self.controller_ref = controller_ref
        self.lock = RLock()
        self.users = 0


class LaunchJournal:
    """One private OS-lock owner; restart seals old nonces before accepting work."""

    def __init__(self, root):
        self.root = local_absolute_path(root)
        self._gate = RLock()
        self._scope_gates = {}
        self._users = 0
        self._stack = None
        self._package = None
        self._owner = None
        self._lock_guard = None
        self._close_failed = False
        self._close_error = None
        self._volatile_closed = set()
        self._volatile_closed_controllers = set()

    def __enter__(self):
        with self._gate:
            if self._close_failed:
                raise self._closure_requires_observation()
            if self._stack is not None:
                raise LaunchFenceError('GUARD_JOURNAL_ALREADY_OPEN')
            self._stack = ExitStack()
            stage = GuardFailureStage.JOURNAL_DIRECTORY_SECURITY
            try:
                self._package = self._stack.enter_context(PrivatePackageGuard(self.root))
                stage = GuardFailureStage.JOURNAL_LOCK_CREATION
                path = self.root / 'runtime-guard.lock'
                try:
                    path.lstat()
                except FileNotFoundError:
                    self._package.publish_new_file('runtime-guard.lock', b'\0', max_file_bytes=1)
                stage = GuardFailureStage.JOURNAL_LOCK_SECURITY
                self._package.verify_member('runtime-guard.lock', directory=False)
                self._lock_guard = LocalPathGuard(path, directory=False)
                self._stack.enter_context(self._lock_guard)
                stage = GuardFailureStage.JOURNAL_LOCK_ACQUISITION
                self._owner = ProcessLock(path)
                self._stack.enter_context(self._owner)
                stage = GuardFailureStage.JOURNAL_OWNERSHIP_CHECK
                self._verify()
                stage = GuardFailureStage.JOURNAL_PRIOR_NONCES
                self._seal_prior_nonces()
                return self
            except BaseException as error:
                error.guard_diagnostic = diagnostic_for_failure(error, stage)
                self.close()
                raise

    def _verify(self):
        if self._stack is None or self._owner is None:
            raise LaunchFenceError('GUARD_JOURNAL_NOT_OPEN')
        self._owner.assert_owned()
        self._package.verify()

    def _closure_requires_observation(self):
        error = LaunchOutcomeUnknown('GUARD_JOURNAL_CLOSURE_REQUIRES_OBSERVATION')
        error.retained_owner = self
        return error

    def close(self):
        with self._gate:
            if self._close_failed:
                raise self._closure_requires_observation()
            if self._users:
                raise LaunchFenceError('GUARD_JOURNAL_HAS_ACTIVE_REQUESTS')
            if self._stack is None:
                return
            try:
                self._stack.close()
            except BaseException as error:
                self._close_failed = True
                self._close_error = error
                error.retained_owner = self
                raise
            self._stack = None
            self._package = None
            self._owner = None
            self._lock_guard = None

    def __exit__(self, kind, error, traceback):
        self.close()

    def _path(self, scope):
        if not isinstance(scope, LaunchScope):
            raise LaunchFenceError('GUARD_SCOPE_REQUIRED')
        return self.root / (scope.key + '.launch.json')

    def _read(self, scope):
        with self._gate:
            self._verify()
            path = self._path(scope)
            try:
                path.lstat()
            except FileNotFoundError:
                return None, None
            self._package.verify_member(path.name, directory=False)
            with LocalPathGuard(path, directory=False), path.open('rb') as stream:
                raw = stream.read(MAX_STATE_BYTES + 1)
            if len(raw) > MAX_STATE_BYTES:
                raise LaunchFenceError('GUARD_STATE_TOO_LARGE')
            return _decode(raw, scope), raw

    def _save(self, current, old_raw):
        with self._gate:
            self._verify()
            path = self._path(current.scope)
            raw = _bytes(asdict(current))
            _decode(raw, current.scope)
            if len(raw) > MAX_STATE_BYTES:
                raise LaunchFenceError('GUARD_STATE_TOO_LARGE')
            if old_raw is not None:
                old = _decode(old_raw, current.scope)
                if (
                    current.record_revision != old.record_revision + 1
                    or old.stop_closed
                    and not current.stop_closed
                    or current.input_sha256 != old.input_sha256
                    or old.resource_ref is not None
                    and current.resource_ref != old.resource_ref
                    or not 0
                    <= CREATE_STATES.index(current.create_state)
                    - CREATE_STATES.index(old.create_state)
                    <= 1
                    or not 0
                    <= RESUME_STATES.index(current.resume_state)
                    - RESUME_STATES.index(old.resume_state)
                    <= 1
                ):
                    raise LaunchFenceError('GUARD_STATE_CANNOT_REOPEN_OR_REBIND')
            elif (
                current.record_revision != 1
                or current.create_state != 'NONE'
                or current.resume_state != 'NONE'
            ):
                raise LaunchFenceError('GUARD_NEW_STATE_REVISION_INVALID')
            temporary = None
            try:
                name = '.launch-' + uuid4().hex + '.tmp'
                self._package.publish_new_file(name, raw, max_file_bytes=MAX_STATE_BYTES)
                temporary = self.root / name
                self._verify()
                actual = self._read(current.scope)[1]
                if actual != old_raw:
                    raise LaunchFenceError('GUARD_STATE_CHANGED_CONCURRENTLY')
                os.replace(temporary, path)
                result, readback = self._read(current.scope)
                if readback != raw:
                    raise LaunchOutcomeUnknown('GUARD_STATE_SAVE_UNVERIFIED')
                return result
            except (OSError, ValueError, PrivateRecordError) as error:
                unknown = LaunchOutcomeUnknown('GUARD_STATE_SAVE_UNVERIFIED')
                if getattr(error, 'retained_owner', None) is not None:
                    unknown.retained_owner = error.retained_owner
                raise unknown from error
            finally:
                if temporary is not None and temporary.exists():
                    temporary.unlink()

    def _next(self, current, **changes):
        if current.record_revision == MAX_SAFE_INTEGER:
            raise LaunchFenceError('GUARD_STATE_CAPACITY_EXHAUSTED')
        return replace(
            current, **changes, record_revision=current.record_revision + 1, updated_at=_now()
        )

    def _seal_prior_nonces(self):
        # No old process/Job handles are recreated from names after Guard restart.
        # Close dispatch first; actual old resources remain for separate observation.
        with os.scandir(self.root) as listing:
            names = tuple(entry.name for entry in listing if entry.name.endswith('.launch.json'))
        if len(names) > MAX_LAUNCH_RECORDS:
            raise LaunchFenceError('GUARD_STATE_CAPACITY_EXHAUSTED')
        for name in names:
            if re.fullmatch(r'[0-9a-f]{64}\.launch\.json', name) is None:
                raise LaunchFenceError('GUARD_STATE_FILENAME_INVALID')
            self._package.verify_member(name, directory=False)
            with (self.root / name).open('rb') as stream:
                raw = stream.read(MAX_STATE_BYTES + 1)
            if len(raw) > MAX_STATE_BYTES:
                raise LaunchFenceError('GUARD_STATE_TOO_LARGE')
            value = strict_json_object(raw)
            if type(value.get('scope')) is not dict:
                raise LaunchFenceError('GUARD_STATE_SCOPE_INVALID')
            scope = decode_launch_scope(value['scope'])
            if name != self._path(scope).name:
                raise LaunchFenceError('GUARD_STATE_FILENAME_DIFFERS')
            current = _decode(raw, scope)
            if not current.stop_closed:
                self._save(self._next(current, stop_closed=True), raw)

    @contextmanager
    def _scope(self, scope, *, blocking=True):
        # One original launch is serial, while another task's STOP can proceed.
        with self._gate:
            self._verify()
            self._path(scope)
            entry = self._scope_gates.get(scope.key)
            if entry is None:
                entry = _ScopeGate(scope.controller_ref)
                self._scope_gates[scope.key] = entry
            entry.users += 1
            self._users += 1
        acquired = entry.lock.acquire(blocking=blocking)
        try:
            if acquired:
                self._verify()
            yield acquired
        finally:
            if acquired:
                entry.lock.release()
            with self._gate:
                entry.users -= 1
                self._users -= 1
                if entry.users == 0:
                    del self._scope_gates[scope.key]

    def inspect(self, scope):
        with self._scope(scope):
            return self._read(scope)[0]  # None is NO_RECORD, never 'not executed'.

    def _closed(self, current):
        if current.stop_closed:
            return True
        if current.scope.key in self._volatile_closed:
            raise LaunchOutcomeUnknown('GUARD_STOP_CLOSURE_UNVERIFIED')
        return False

    def read_controller_seal(self, controller_ref):
        name = _hex(controller_ref) + '.controller-seal.json'
        with self._gate:
            self._verify()
            path = self.root / name
            try:
                path.lstat()
            except FileNotFoundError:
                return None
            try:
                self._package.verify_member(name, directory=False)
                with LocalPathGuard(path, directory=False), path.open('rb') as stream:
                    raw = stream.read(MAX_STATE_BYTES + 1)
                return decode_controller_seal(raw, controller_ref)
            except OSError as error:
                raise LaunchOutcomeUnknown('GUARD_CONTROLLER_SEAL_READ_UNVERIFIED') from error

    def _require_controller_open(self, scope):
        if self.read_controller_seal(scope.controller_ref) is not None:
            raise LaunchFenceError('GUARD_CONTROLLER_ADMISSION_CLOSED')
        if scope.controller_ref in self._volatile_closed_controllers:
            raise LaunchOutcomeUnknown('GUARD_CONTROLLER_CLOSURE_UNVERIFIED')

    def controller_scope_records(self, controller_ref):
        # Marker publication serialized with each native dispatch INTENT first.
        # Do not hold the global gate while waiting for an in-flight scope.
        _hex(controller_ref)
        with self._gate:
            if self.read_controller_seal(controller_ref) is None:
                raise LaunchOutcomeUnknown('GUARD_CONTROLLER_SEAL_REQUIRED')
            with os.scandir(self.root) as rows:
                names = []
                for row in rows:
                    if row.name.endswith('.launch.json'):
                        names.append(row.name)
                        if len(names) > MAX_LAUNCH_RECORDS:
                            raise LaunchOutcomeUnknown('GUARD_STATE_CAPACITY_EXHAUSTED')
        records = []
        for name in names:
            if re.fullmatch(r'[0-9a-f]{64}\.launch\.json', name) is None:
                raise LaunchOutcomeUnknown('GUARD_STATE_FILENAME_INVALID')
            with self._gate:
                self._package.verify_member(name, directory=False)
                with (
                    LocalPathGuard(self.root / name, directory=False),
                    (self.root / name).open('rb') as stream,
                ):
                    raw = stream.read(MAX_STATE_BYTES + 1)
            if len(raw) > MAX_STATE_BYTES:
                raise LaunchOutcomeUnknown('GUARD_STATE_TOO_LARGE')
            value = strict_json_object(raw)
            if type(value.get('scope')) is not dict:
                raise LaunchOutcomeUnknown('GUARD_STATE_SCOPE_INVALID')
            scope = decode_launch_scope(value['scope'])
            if name != scope.key + '.launch.json':
                raise LaunchOutcomeUnknown('GUARD_STATE_FILENAME_DIFFERS')
            _decode(raw, scope)
            if scope.controller_ref == controller_ref:
                with self._gate:
                    active = self._scope_gates.get(scope.key)
                    if active is not None and active.users:
                        raise LaunchOutcomeUnknown('GUARD_CONTROLLER_SCOPE_STILL_IN_FLIGHT')
                    current, _raw = self._read(scope)
                    if current is None:
                        raise LaunchOutcomeUnknown('GUARD_ORIGINAL_RESOURCE_NOT_FOUND')
                    records.append(current)
        return tuple(records)

    def close_controller_scopes(self, controller_ref):
        closed = []
        for current in self.controller_scope_records(controller_ref):
            with self._gate:
                active = self._scope_gates.get(current.scope.key)
                if active is not None and active.users:
                    raise LaunchOutcomeUnknown('GUARD_CONTROLLER_SCOPE_STILL_IN_FLIGHT')
                closed.append(self.close_nonce(current.scope))
        return tuple(closed)

    def verify_controller_closure(self, controller_ref):
        seal = self.read_controller_seal(controller_ref)
        if seal is None:
            raise LaunchOutcomeUnknown('GUARD_CONTROLLER_SEAL_REQUIRED')
        for current in self.controller_scope_records(controller_ref):
            if not current.stop_closed:
                raise LaunchOutcomeUnknown('GUARD_CONTROLLER_SCOPE_CLOSURE_UNVERIFIED')
        return seal

    def prepare(self, scope, input_sha256):
        with self._scope(scope), self._gate:
            self._require_controller_open(scope)
            current, _raw = self._read(scope)
            if current is not None:
                if self._closed(current):
                    return current
                if current.input_sha256 != _hex(input_sha256):
                    raise LaunchFenceError('GUARD_ORIGINAL_INPUT_CONFLICT')
                return current
            if scope.key in self._volatile_closed:
                raise LaunchOutcomeUnknown('GUARD_STOP_CLOSURE_UNVERIFIED')
            _hex(input_sha256)
            with self._gate:
                with os.scandir(self.root) as listing:
                    count = sum(entry.name.endswith('.launch.json') for entry in listing)
                if count >= MAX_LAUNCH_RECORDS:
                    raise LaunchFenceError('GUARD_STATE_CAPACITY_EXHAUSTED')
                return self._save(
                    LaunchFence(1, scope, input_sha256, 'NONE', 'NONE', None, False, 1, _now()),
                    None,
                )

    def close_nonce(self, scope):
        with self._scope(scope):
            self._verify()
            self._path(scope)
            self._volatile_closed.add(scope.key)
            current, raw = self._read(scope)
            if current is None:
                with self._gate:
                    with os.scandir(self.root) as listing:
                        count = sum(entry.name.endswith('.launch.json') for entry in listing)
                    if count >= MAX_LAUNCH_RECORDS:
                        raise LaunchOutcomeUnknown('GUARD_STOP_CLOSURE_CAPACITY_EXHAUSTED')
                    current = LaunchFence(1, scope, None, 'NONE', 'NONE', None, True, 1, _now())
                    return self._save(current, raw)
            elif current.stop_closed:
                return current
            else:
                current = self._next(current, stop_closed=True)
            return self._save(current, raw)  # This is not a STOP/exit acknowledgement.

    def dispatch_create(self, scope, input_sha256, native_create):
        with self._scope(scope):
            with self._gate:
                current, raw = self._read(scope)
                if current is None:
                    raise LaunchOutcomeUnknown('GUARD_ORIGINAL_PREPARE_NOT_FOUND')
                if self._closed(current):
                    return current
                if current.input_sha256 != _hex(input_sha256):
                    raise LaunchFenceError('GUARD_ORIGINAL_INPUT_CONFLICT')
                if current.create_state == 'RESOURCE_RECORDED':
                    return current
                if current.create_state != 'NONE':
                    raise LaunchOutcomeUnknown('GUARD_ORIGINAL_CREATE_REQUIRES_OBSERVATION')
                self._require_controller_open(scope)
                self._save(self._next(current, create_state='MAY_HAVE_BEEN_SENT'), raw)
            try:
                resource_ref = _resource(native_create())
            except Exception as error:
                raise LaunchOutcomeUnknown('GUARD_NATIVE_CREATE_OUTCOME_UNVERIFIED') from error
            try:
                # Reentrant STOP/native observation may have updated the same fence.
                current, raw = self._read(scope)
                if current is None or current.create_state != 'MAY_HAVE_BEEN_SENT':
                    raise LaunchOutcomeUnknown('GUARD_ORIGINAL_CREATE_STATE_UNVERIFIED')
                return self._save(
                    self._next(
                        current, create_state='RESOURCE_RECORDED', resource_ref=resource_ref
                    ),
                    raw,
                )
            except LaunchOutcomeUnknown:
                raise
            except Exception as error:
                raise LaunchOutcomeUnknown('GUARD_CREATED_RESOURCE_SAVE_UNVERIFIED') from error

    def dispatch_resume(self, scope, resource_ref, native_resume):
        with self._scope(scope):
            with self._gate:
                current, raw = self._read(scope)
                if current is None:
                    raise LaunchOutcomeUnknown('GUARD_ORIGINAL_RESOURCE_NOT_FOUND')
                if self._closed(current):
                    return current
                if (
                    current.resource_ref != _resource(resource_ref)
                    or current.create_state != 'RESOURCE_RECORDED'
                ):
                    raise LaunchFenceError('GUARD_ORIGINAL_RESOURCE_DIFFERS')
                if current.resume_state == 'ACKNOWLEDGED':
                    return current
                if current.resume_state != 'NONE':
                    raise LaunchOutcomeUnknown('GUARD_ORIGINAL_RESUME_REQUIRES_OBSERVATION')
                self._require_controller_open(scope)
                self._save(self._next(current, resume_state='MAY_HAVE_BEEN_SENT'), raw)
            # Trusted adapter raises unless its actual ResumeThread ACK is valid.
            try:
                native_resume()
            except Exception as error:
                raise LaunchOutcomeUnknown('GUARD_NATIVE_RESUME_OUTCOME_UNVERIFIED') from error
            try:
                current, raw = self._read(scope)
                if current is None or current.resume_state != 'MAY_HAVE_BEEN_SENT':
                    raise LaunchOutcomeUnknown('GUARD_ORIGINAL_RESUME_STATE_UNVERIFIED')
                return self._save(self._next(current, resume_state='ACKNOWLEDGED'), raw)
            except LaunchOutcomeUnknown:
                raise
            except Exception as error:
                raise LaunchOutcomeUnknown('GUARD_RESUME_ACK_SAVE_UNVERIFIED') from error
