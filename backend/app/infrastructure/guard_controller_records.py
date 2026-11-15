"""Original private controller registration, before any launch history.

Only actual CLIENT peers produce new identity/image facts. Program/package
references come from Guard's trusted installation catalogue, never an RPC body.
These records preserve provenance; they do not admit a runtime package, grant
recovery, prove an old process exited, or recreate OS resources.
"""

import hashlib
import os
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from threading import RLock

from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_json_object

from .guard_backend_program import (
    POLICY_VERSION as BACKEND_PROGRAM_POLICY,
)
from .guard_backend_program import (
    BackendProgramAdmission,
    ProtectedBackendProgram,
)
from .guard_controller_binding import GuardControllerBinding, owner_epoch
from .runtime_launch_journal import (
    MAX_LAUNCH_RECORDS,
    MAX_STATE_BYTES,
    ControllerSeal,
    LaunchJournal,
    LaunchOutcomeUnknown,
    decode_launch_scope,
    _bytes,
    _decode,
    _hex,
    _now,
    _resource,
    decode_controller_seal,
)
from .windows_config_source import LockedConfigSource
from .windows_executable_pin import ExecutableIdentity
from .windows_local_paths import FileIdentity, local_absolute_path
from .windows_private_record import PrivateRecordAppend
from .windows_process import NativeProcessIdentity

MAX_CONTROLLER_RECORDS = 100000
MAX_CONTROLLER_RECORD_BYTES = 16384


class ControllerRecordError(LaunchOutcomeUnknown):
    pass


@dataclass(frozen=True)
class GuardControllerRegistration:
    binding: GuardControllerBinding = field(repr=False)
    backend_program_ref: str
    backend_package_sha256: str
    image: ExecutableIdentity = field(repr=False)
    registered_at: str
    backend_admission: BackendProgramAdmission | None = None

    @property
    def facts(self):
        return {
            'schema_version': 1,
            'binding': asdict(self.binding),
            'backend_program_ref': self.backend_program_ref,
            'backend_package_sha256': self.backend_package_sha256,
            'image': asdict(self.image),
            'registered_at': self.registered_at,
            'backend_admission': None
            if self.backend_admission is None
            else asdict(self.backend_admission),
        }

    @property
    def sha256(self):
        return hashlib.sha256(_bytes(self.facts)).hexdigest()


def _fields(value, names):
    if type(value) is not dict or set(value) != set(names):
        raise ControllerRecordError('ORIGINAL_CONTROLLER_RECORD_FIELDS_DIFFER')


def decode_controller_registration(raw, controller_ref, epoch):
    _hex(controller_ref)
    owner_epoch(epoch)
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_CONTROLLER_RECORD_BYTES:
        raise ControllerRecordError('ORIGINAL_CONTROLLER_RECORD_SIZE_INVALID')
    value = strict_json_object(raw)
    _fields(
        value,
        (
            'schema_version',
            'binding',
            'backend_program_ref',
            'backend_package_sha256',
            'image',
            'registered_at',
            'backend_admission',
        ),
    )
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ControllerRecordError('ORIGINAL_CONTROLLER_RECORD_VERSION_INVALID')
    body = value['binding']
    _fields(body, GuardControllerBinding.__dataclass_fields__)
    native = body['controller']
    _fields(native, NativeProcessIdentity.__dataclass_fields__)
    if (
        type(native['pid']) is not int
        or not 1 <= native['pid'] <= 0xFFFFFFFF
        or type(native['creation_time_hex']) is not str
        or re.fullmatch('[0-9a-f]{16}', native['creation_time_hex']) is None
        or type(native['user_sid']) is not str
        or re.fullmatch(r'S-1-[0-9]+(?:-[0-9]+)+', native['user_sid']) is None
        or native['appcontainer_sid'] is not None
        or native['is_appcontainer'] is not False
        or native['is_lpac'] is not False
        or native['is_elevated'] is not False
    ):
        raise ControllerRecordError('ORIGINAL_CONTROLLER_NATIVE_FACTS_INVALID')
    local_absolute_path(native['image_path'])
    binding = GuardControllerBinding(
        body['installation_ref'], body['owner_epoch'], NativeProcessIdentity(**native)
    )
    if binding.controller_ref != controller_ref or binding.owner_epoch != epoch:
        raise ControllerRecordError('ORIGINAL_CONTROLLER_RECORD_BINDING_DIFFERS')
    _resource(value['backend_program_ref'])
    _hex(value['backend_package_sha256'])
    image = value['image']
    _fields(image, ExecutableIdentity.__dataclass_fields__)
    identity = image['file']
    _fields(identity, FileIdentity.__dataclass_fields__)
    if (
        type(image['byte_count']) is not int
        or not 1 <= image['byte_count'] <= MAX_SAFE_INTEGER
        or image['architecture'] != 'win-x64'
        or type(identity['volume_serial']) is not str
        or re.fullmatch('[0-9a-f]{16}', identity['volume_serial']) is None
        or type(identity['file_id']) is not str
        or re.fullmatch('[0-9a-f]{32}', identity['file_id']) is None
        or identity['is_directory'] is not False
        or identity['filesystem'] != 'NTFS'
        or type(identity['canonical_path']) is not str
        or type(native['image_path']) is not str
        or identity['canonical_path'].casefold() != native['image_path'].casefold()
    ):
        raise ControllerRecordError('ORIGINAL_CONTROLLER_IMAGE_FACTS_INVALID')
    _hex(image['sha256'])
    local_absolute_path(identity['canonical_path'])
    at = value['registered_at']
    if (
        type(at) is not str
        or re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z', at)
        is None
    ):
        raise ControllerRecordError('ORIGINAL_CONTROLLER_RECORD_TIME_INVALID')
    try:
        datetime.fromisoformat(at)
    except ValueError as error:
        raise ControllerRecordError('ORIGINAL_CONTROLLER_RECORD_TIME_INVALID') from error
    admission = value['backend_admission']
    if admission is not None:
        _fields(admission, BackendProgramAdmission.__dataclass_fields__)
        if (
            admission['policy_version'] != BACKEND_PROGRAM_POLICY
            or admission['program_ref'] != value['backend_program_ref']
            or admission['manifest_sha256'] != value['backend_package_sha256']
        ):
            raise ControllerRecordError('ORIGINAL_CONTROLLER_PROGRAM_ADMISSION_DIFFERS')
        _hex(admission['evidence_sha256'])
        admission = BackendProgramAdmission(**admission)
    result = GuardControllerRegistration(
        binding,
        value['backend_program_ref'],
        value['backend_package_sha256'],
        ExecutableIdentity(
            FileIdentity(**identity), image['byte_count'], image['sha256'], image['architecture']
        ),
        at,
        admission,
    )
    if _bytes(result.facts) != raw:
        raise ControllerRecordError('ORIGINAL_CONTROLLER_RECORD_NOT_CANONICAL')
    return result


class GuardControllerRecords:
    """Use the existing operator-only Journal and no-replace record publisher."""

    def __init__(self, journal):
        if type(journal) is not LaunchJournal:
            raise TypeError('Original Guard journal required')
        journal._verify()
        self._journal = journal
        self._gate = RLock()
        self._pending = {}
        self._retained_reads = []
        self._closing = False

    def _filename(self, controller_ref):
        return _hex(controller_ref) + '.controller.json'

    def read(self, controller_ref, epoch):
        name = self._filename(controller_ref)
        owner_epoch(epoch)
        with self._gate, self._journal._gate:
            self._journal._verify()
            path = self._journal.root / name
            try:
                path.lstat()
            except FileNotFoundError as error:
                raise ControllerRecordError('ORIGINAL_CONTROLLER_RECORD_MISSING') from error
            identity = self._journal._package.verify_member(name, directory=False)
            snapshot = self._snapshot(path, MAX_CONTROLLER_RECORD_BYTES, identity)
            record = decode_controller_registration(snapshot.raw, controller_ref, epoch)
            if self._journal._package.verify_member(name, directory=False) != identity:
                raise ControllerRecordError('ORIGINAL_CONTROLLER_RECORD_FILE_DIFFERS')
            return record

    def _snapshot(self, path, maximum, expected_file=None):
        try:
            with LockedConfigSource(
                path, max_file_bytes=maximum, expected_file=expected_file
            ) as source:
                snapshot = source.verify()
                source.verify()
                return snapshot
        except BaseException as error:
            retained = getattr(error, 'retained_owner', None)
            if type(retained) is LockedConfigSource:
                self._retained_reads.append(retained)
                error.retained_owner = self
            raise

    def _require_no_prior_history(self, controller_ref):
        # No post-hoc attestation of an old launch when its controller record
        # was absent. The journal gate prevents new scope users during the check.
        if any(
            entry.controller_ref == controller_ref and entry.users
            for entry in self._journal._scope_gates.values()
        ):
            raise ControllerRecordError('CONTROLLER_REGISTRATION_REQUIRES_QUIET_JOURNAL')
        count = 0
        with os.scandir(self._journal.root) as rows:
            for row in rows:
                launch = row.name.endswith('.launch.json')
                native = row.name.endswith('.native.json')
                if not launch and not native:
                    continue
                count += 1
                if count > MAX_LAUNCH_RECORDS:
                    raise ControllerRecordError('GUARD_STATE_CAPACITY_EXHAUSTED')
                pattern = (
                    r'[0-9a-f]{64}\.launch\.json'
                    if launch
                    else r'[0-9a-f]{64}\.[0-9a-f]{32}\.native\.json'
                )
                if re.fullmatch(pattern, row.name) is None:
                    raise ControllerRecordError('GUARD_STATE_FILENAME_INVALID')
                identity = self._journal._package.verify_member(row.name, directory=False)
                snapshot = self._snapshot(self._journal.root / row.name, MAX_STATE_BYTES, identity)
                value = strict_json_object(snapshot.raw)
                scope = decode_launch_scope(value.get('scope'))
                if launch:
                    _decode(snapshot.raw, scope)
                elif _bytes(value) != snapshot.raw:
                    raise ControllerRecordError('GUARD_STATE_NOT_CANONICAL')
                if not row.name.startswith(scope.key + '.'):
                    raise ControllerRecordError('GUARD_STATE_FILENAME_DIFFERS')
                if scope.controller_ref == controller_ref:
                    raise ControllerRecordError('CONTROLLER_RECORD_CANNOT_ATTEST_PRIOR_LAUNCH')

    def record_peer_facts(self, binding, *, peer, backend_program_ref, backend_package_sha256):
        # Diagnostic provenance only. This immutable unadmitted record cannot
        # later be upgraded into an authorization by supplying a new claim.
        return self._register(
            binding,
            peer=peer,
            backend_program_ref=backend_program_ref,
            backend_package_sha256=backend_package_sha256,
            admission=None,
        )

    def register_admitted(self, binding, *, peer, program, timeout_ms, cancelled):
        if type(program) is not ProtectedBackendProgram or program.peer is not peer:
            raise ControllerRecordError('ACTUAL_PROTECTED_BACKEND_PROGRAM_REQUIRED')
        with program.admission(timeout_ms=timeout_ms, cancelled=cancelled) as admission:
            result = self._register(
                binding,
                peer=peer,
                backend_program_ref=admission.program_ref,
                backend_package_sha256=admission.manifest_sha256,
                admission=admission,
            )
        return result

    def _register(self, binding, *, peer, backend_program_ref, backend_package_sha256, admission):
        if type(binding) is not GuardControllerBinding:
            raise TypeError('Original authenticated controller binding required')
        _resource(backend_program_ref)
        _hex(backend_package_sha256)
        with self._gate, self._journal._gate:
            if self._closing or self._pending:
                raise ControllerRecordError('CONTROLLER_REGISTRATION_REQUIRES_OBSERVATION')
            binding.assert_peer(peer)
            self._journal._verify()
            image = peer._program.verify()
            requested = GuardControllerRegistration(
                binding, backend_program_ref, backend_package_sha256, image, _now(), admission
            )
            raw = _bytes(requested.facts)
            decode_controller_registration(raw, binding.controller_ref, binding.owner_epoch)
            name = self._filename(binding.controller_ref)
            if (self._journal.root / name).exists():
                existing = self.read(binding.controller_ref, binding.owner_epoch)
                if replace(existing, registered_at=requested.registered_at) != requested:
                    raise ControllerRecordError('ORIGINAL_CONTROLLER_REGISTRATION_CONFLICT')
                binding.assert_peer(peer)
                return existing
            self._require_no_prior_history(binding.controller_ref)
            with os.scandir(self._journal.root) as rows:
                count = sum(row.name.endswith('.controller.json') for row in rows)
            if count >= MAX_CONTROLLER_RECORDS:
                raise ControllerRecordError('CONTROLLER_RECORD_CAPACITY_EXHAUSTED')
            writer = None
            try:
                writer = PrivateRecordAppend(
                    self._journal._package, name, raw, max_record_bytes=MAX_CONTROLLER_RECORD_BYTES
                )
                self._pending[binding.controller_ref] = (writer, binding.owner_epoch)
                reference = writer.publish()
                writer.close()
                if self._journal._package.verify_member(name, directory=False) != reference.file:
                    raise ControllerRecordError('ORIGINAL_CONTROLLER_RECORD_FILE_DIFFERS')
                actual = self.read(binding.controller_ref, binding.owner_epoch)
                if actual != requested:
                    raise ControllerRecordError('ORIGINAL_CONTROLLER_RECORD_BYTES_DIFFER')
                binding.assert_peer(peer)
                del self._pending[binding.controller_ref]
                return actual
            except BaseException as original:
                retained = getattr(original, 'retained_owner', None)
                if writer is None and type(retained) is PrivateRecordAppend:
                    self._pending[binding.controller_ref] = (retained, binding.owner_epoch)
                error = ControllerRecordError('CONTROLLER_RECORD_PUBLISH_UNVERIFIED')
                error.retained_owner = self
                raise error from original

    def read_seal(self, controller_ref, epoch):
        with self._gate, self._journal._gate:
            record = self.read(controller_ref, epoch)
            seal = self._journal.read_controller_seal(controller_ref)
            if (
                seal is None
                or seal.owner_epoch != epoch
                or seal.registration_sha256 != record.sha256
            ):
                raise ControllerRecordError('ORIGINAL_CONTROLLER_SEAL_UNVERIFIED')
            return seal

    def seal_controller(self, controller_ref, epoch):
        # Block every new nonce/Registry through the Journal, not just one
        # in-memory registry flag. No native stop/release is claimed here.
        with self._gate:
            if self._closing or self._pending:
                raise ControllerRecordError('CONTROLLER_REGISTRATION_REQUIRES_OBSERVATION')
            with self._journal._gate:
                record = self.read(controller_ref, epoch)
                self._journal._volatile_closed_controllers.add(controller_ref)
                existing = self._journal.read_controller_seal(controller_ref)
                if existing is not None:
                    seal = self.read_seal(controller_ref, epoch)
                else:
                    seal = ControllerSeal(1, controller_ref, epoch, record.sha256, _now())
                    raw = _bytes(asdict(seal))
                    decode_controller_seal(raw, controller_ref)
                    name = controller_ref + '.controller-seal.json'
                    writer = None
                    try:
                        writer = PrivateRecordAppend(
                            self._journal._package,
                            name,
                            raw,
                            max_record_bytes=MAX_CONTROLLER_RECORD_BYTES,
                        )
                        self._pending[controller_ref] = (writer, epoch)
                        reference = writer.publish()
                        writer.close()
                        actual = self._journal._package.verify_member(name, directory=False)
                        if (
                            actual != reference.file
                            or self.read_seal(controller_ref, epoch) != seal
                        ):
                            raise ControllerRecordError('ORIGINAL_CONTROLLER_SEAL_BYTES_DIFFER')
                        del self._pending[controller_ref]
                    except BaseException as original:
                        retained = getattr(original, 'retained_owner', None)
                        if writer is None and type(retained) is PrivateRecordAppend:
                            self._pending[controller_ref] = (retained, epoch)
                        error = ControllerRecordError('CONTROLLER_SEAL_PUBLISH_UNVERIFIED')
                        error.retained_owner = self
                        raise error from original
            self._journal.close_controller_scopes(controller_ref)
            return self.read_seal(controller_ref, epoch)

    def reconcile_pending(self):
        with self._gate, self._journal._gate:
            self._journal._verify()
            resolved = []
            for controller_ref, (writer, epoch) in tuple(self._pending.items()):
                try:
                    writer.close()
                    if not writer._rename_may:
                        del self._pending[controller_ref]
                        continue
                    if writer._identity is None:
                        raise ControllerRecordError('CONTROLLER_RECORD_CREATED_IDENTITY_UNKNOWN')
                    expected = replace(writer._identity, canonical_path=str(writer._target))
                    actual = self._journal._package.verify_member(writer._filename, directory=False)
                    if actual != expected:
                        raise ControllerRecordError('ORIGINAL_CONTROLLER_RECORD_FILE_DIFFERS')
                    record = (
                        self.read_seal(controller_ref, epoch)
                        if writer._filename == controller_ref + '.controller-seal.json'
                        else self.read(controller_ref, epoch)
                    )
                    if record.sha256 != writer._sha256:
                        raise ControllerRecordError('ORIGINAL_CONTROLLER_RECORD_BYTES_DIFFER')
                    del self._pending[controller_ref]
                    resolved.append(record)
                except BaseException as original:
                    error = ControllerRecordError('CONTROLLER_RECORD_STILL_UNVERIFIED')
                    error.retained_owner = self
                    raise error from original
            return tuple(resolved)

    def close(self):
        with self._gate:
            self._closing = True
            try:
                for source in tuple(self._retained_reads):
                    source.close()
                    self._retained_reads.remove(source)
                for writer, _ in self._pending.values():
                    writer.close()
            except BaseException as error:
                error.retained_owner = self
                raise

    def __enter__(self):
        if self._closing:
            raise ControllerRecordError('CONTROLLER_RECORD_STORE_CLOSED')
        return self

    def __exit__(self, kind, error, traceback):
        self.close()
