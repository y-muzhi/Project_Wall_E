"""Create and verify the original TASK directory permissions on local NTFS."""

import ctypes
import re
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass

from backend.app.shared.validation import strict_integer

from .content_manifest import git_oid, object_format
from .guard_action_journal import GuardActionJournal
from .guard_action_records import GuardActionStart, mutation_input_sha256
from .guard_controller_binding import GuardControllerBinding
from .guard_request_header import GuardRequestHeader
from .runtime_launch_journal import LaunchScope, TestingLaunchScope
from .windows_access_check import ControllerAccessQuery, require_controller_read_only
from .windows_controller_token import ControllerPrimaryToken
from .windows_empty_directory import OWNER_RIGHTS, READ_EXECUTE
from .windows_job import _lpac_security_capabilities, task_lpac_profile
from .windows_local_paths import (
    FileIdentity,
    LocalDirectoryPin,
    LocalPathGuard,
    local_absolute_path,
)
from .windows_private_package import (
    OPERATOR_ACCESS,
    AclHeader,
    AllowedAce,
    PackageSecurityError,
    SecurityAttributes,
    _api,
    _sid_text,
    current_operator_sid,
)

MUTABLE_ROLES = ('workspace', 'scratch')
READ_ONLY_ROLES = ('basis', 'config', 'runtime')
TASK_ROLES = ('root', *MUTABLE_ROLES, *READ_ONLY_ROLES)
PROJECT_CHECK_PURPOSE = 'CHECK'
CHECK_DRIVER_KIND = 'CHECK_DRIVER'
_TRAVERSE = 0x001200A0
_DEPLOYMENT_TRAVERSE = 0x001000A0
_ANCESTOR_TRAVERSE = 0xA0
_WRITE_DIRECTORY = 0x001201FF
_WRITE_CHILD = 0x001301FF
_FILE_READ = 0x00120089
_DIRECTORY_INHERIT = 2
_FILE_INHERIT_ONLY = 9
_INHERIT = 3
_INHERIT_ONLY = 11
_LABEL_TYPE = 0x11
_LOW = 'S-1-16-4096'
_MEDIUM = 'S-1-16-8192'


@dataclass(frozen=True)
class TaskDirectoryFacts:
    role: str
    file: FileIdentity
    integrity_sid: str


@dataclass(frozen=True)
class ProjectCheckInput:
    owner_kind: str
    owner_id: int
    control_generation: int
    verification_id: int
    item_id: int
    candidate_id: int
    manifest_sha256: str

    def __post_init__(self):
        if (
            self.owner_kind not in ('CODING', 'TESTING')
            or type(self.manifest_sha256) is not str
            or re.fullmatch('[a-f0-9]{64}', self.manifest_sha256) is None
        ):
            raise PackageSecurityError('ORIGINAL_PROJECT_CHECK_SCOPE_REQUIRED')
        for field in (
            'owner_id',
            'control_generation',
            'verification_id',
            'item_id',
            'candidate_id',
        ):
            strict_integer(getattr(self, field), field)

    def require_scope(self, scope):
        if type(scope) is TestingLaunchScope:
            matches = (self.owner_kind, self.owner_id, self.control_generation) == (
                scope.owner_kind,
                scope.owner_id,
                scope.control_generation,
            )
        else:
            matches = type(scope) is LaunchScope and self.owner_kind == 'CODING'
        if not matches:
            raise PackageSecurityError('ORIGINAL_PROJECT_CHECK_SCOPE_REQUIRED')


@dataclass(frozen=True)
class SnapshotCheckInput:
    owner_kind: str
    owner_id: int
    control_generation: int
    verification_id: int
    item_id: int
    snapshot_id: int
    commit_oid: str
    tree_oid: str
    object_format: str
    content_profile_version_id: int
    content_sha256: str

    def __post_init__(self):
        if (
            self.owner_kind != 'TESTING'
            or type(self.content_sha256) is not str
            or re.fullmatch('[a-f0-9]{64}', self.content_sha256) is None
        ):
            raise PackageSecurityError('ORIGINAL_SNAPSHOT_CHECK_SCOPE_REQUIRED')
        object_format(self.object_format)
        git_oid(self.commit_oid, self.object_format)
        git_oid(self.tree_oid, self.object_format)
        for field in (
            'owner_id',
            'control_generation',
            'verification_id',
            'item_id',
            'snapshot_id',
            'content_profile_version_id',
        ):
            strict_integer(getattr(self, field), field)

    def require_scope(self, scope):
        if type(scope) is not TestingLaunchScope or (
            self.owner_kind,
            self.owner_id,
            self.control_generation,
        ) != (scope.owner_kind, scope.owner_id, scope.control_generation):
            raise PackageSecurityError('ORIGINAL_SNAPSHOT_CHECK_SCOPE_REQUIRED')


def decode_project_check_input(value, scope):
    if type(value) is dict:
        for input_type in (ProjectCheckInput, SnapshotCheckInput):
            if set(value) == set(input_type.__dataclass_fields__):
                check = input_type(**value)
                check.require_scope(scope)
                return check
    raise PackageSecurityError('ORIGINAL_PROJECT_CHECK_SCOPE_REQUIRED')


@dataclass(frozen=True)
class TaskWorkspaceDestination:
    scope: LaunchScope
    binding_ref: str
    directory_nonce: str
    directory: FileIdentity


def _failure(code):
    return PackageSecurityError(code, ctypes.get_last_error())


def _policy(role, operator, user, package):
    inheritance = 0 if role == 'root' else _INHERIT
    aces = [(0, inheritance, OPERATOR_ACCESS, operator)]
    for reader in sorted({user, package, OWNER_RIGHTS} - {operator}):
        if role == 'root':
            aces.append((0, 0, _TRAVERSE, reader))
        elif role in MUTABLE_ROLES:
            aces.extend(
                ((0, 0, _WRITE_DIRECTORY, reader), (0, _INHERIT_ONLY, _WRITE_CHILD, reader))
            )
        elif role == 'runtime':
            aces.append((0, _INHERIT, READ_EXECUTE, reader))
        else:
            aces.extend(
                (
                    (0, _DIRECTORY_INHERIT, READ_EXECUTE, reader),
                    (0, _FILE_INHERIT_ONLY, _FILE_READ, reader),
                )
            )
    label = (_LABEL_TYPE, inheritance, 1, _LOW if role in MUTABLE_ROLES else _MEDIUM)
    return tuple(aces), label


def _sddl(operator, aces, label):
    flags = {
        0: '',
        _DIRECTORY_INHERIT: 'CI',
        _FILE_INHERIT_ONLY: 'OIIO',
        _INHERIT: 'OICI',
        _INHERIT_ONLY: 'OICIIO',
    }
    dacl = ''.join(f'(A;{flags[inherit]};0x{mask:08x};;;{sid})' for _, inherit, mask, sid in aces)
    _, inherit, _, sid = label
    return f'O:{operator}D:P{dacl}S:(ML;{flags[inherit]};NW;;;{sid})'


def _read_aces(kernel, security, acl):
    if not acl:
        raise PackageSecurityError('TASK_DIRECTORY_ACL_UNAVAILABLE')
    header = ctypes.cast(acl, ctypes.POINTER(AclHeader)).contents
    if not 1 <= header.count <= 16 or header.size < ctypes.sizeof(AclHeader):
        raise PackageSecurityError('TASK_DIRECTORY_ACL_INVALID')
    entries = []
    for index in range(header.count):
        pointer = wintypes.LPVOID()
        if not security.GetAce(acl, index, ctypes.byref(pointer)) or not pointer.value:
            raise _failure('TASK_DIRECTORY_ACE_UNAVAILABLE')
        ace = ctypes.cast(pointer, ctypes.POINTER(AllowedAce)).contents
        offset = pointer.value - acl.value
        if ace.size < 16 or offset < ctypes.sizeof(AclHeader) or offset + ace.size > header.size:
            raise PackageSecurityError('TASK_DIRECTORY_ACE_INVALID')
        sid = _sid_text(
            kernel, security, wintypes.LPVOID(pointer.value + ctypes.sizeof(AllowedAce))
        )
        entries.append((ace.kind, ace.flags, ace.mask, sid))
    return tuple(entries)


class _TaskDirectory:
    def __init__(self, path, role, operator, aces, label):
        self.path, self.role = path, role
        self._operator, self._aces, self._label = operator, aces, label
        self._kernel, self._security = _api()
        self._pin = None
        self._descriptor = None
        self.created = False
        self.original = None

    @property
    def _native_path(self):
        return '\\\\?\\' + str(self.path)

    def _free_descriptor(self):
        if self._descriptor and self._kernel.LocalFree(self._descriptor):
            raise _failure('TASK_DIRECTORY_DESCRIPTOR_RELEASE_UNVERIFIED')
        self._descriptor = None

    def create(self):
        descriptor = wintypes.LPVOID()
        size = wintypes.DWORD()
        if (
            not self._security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                _sddl(self._operator, self._aces, self._label),
                1,
                ctypes.byref(descriptor),
                ctypes.byref(size),
            )
            or not descriptor.value
        ):
            raise _failure('TASK_DIRECTORY_DESCRIPTOR_UNAVAILABLE')
        self._descriptor = descriptor
        try:
            attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
            if not self._kernel.CreateDirectoryW(self._native_path, ctypes.byref(attributes)):
                raise _failure('TASK_NEW_DIRECTORY_REQUIRED')
            self.created = True
        finally:
            self._free_descriptor()
        self.pin()

    def pin(self, expected=None):
        self._pin = LocalDirectoryPin(self.path, expected=expected)
        self._pin.__enter__()
        self.original = self._pin.verify()
        self.verify()

    def _verify_security(self):
        owner, dacl, sacl, descriptor = (wintypes.LPVOID() for _ in range(4))
        code = self._security.GetNamedSecurityInfoW(
            self._native_path,
            1,
            0x15,
            ctypes.byref(owner),
            None,
            ctypes.byref(dacl),
            ctypes.byref(sacl),
            ctypes.byref(descriptor),
        )
        if code:
            raise PackageSecurityError('TASK_DIRECTORY_SECURITY_UNAVAILABLE', code)
        self._descriptor = descriptor
        try:
            control, revision = wintypes.WORD(), wintypes.DWORD()
            if (
                not descriptor.value
                or not owner.value
                or _sid_text(self._kernel, self._security, owner) != self._operator
                or not self._security.GetSecurityDescriptorControl(
                    descriptor, ctypes.byref(control), ctypes.byref(revision)
                )
                or not control.value & 0x1000
                or _read_aces(self._kernel, self._security, dacl) != self._aces
                or _read_aces(self._kernel, self._security, sacl) != (self._label,)
            ):
                raise PackageSecurityError('TASK_DIRECTORY_SECURITY_DIFFERS')
        finally:
            self._free_descriptor()

    def verify(self):
        if self._descriptor is not None or self._pin is None or self._pin.verify() != self.original:
            raise PackageSecurityError('TASK_DIRECTORY_PIN_DIFFERS')
        self._verify_security()
        return TaskDirectoryFacts(self.role, self.original, self._label[-1])

    def close(self):
        self._free_descriptor()
        if self._pin is not None:
            self._pin.close()
            self._pin = None


class TaskRuntimeRoot:
    """Trusted installation's original runtime-only parent, independent of its journal."""

    def __init__(self, base, backend_sid):
        if type(base) is not LocalDirectoryPin:
            raise PackageSecurityError('ORIGINAL_TASK_RUNTIME_BASE_REQUIRED')
        if (
            type(backend_sid) is not str
            or re.fullmatch(r'S-1-(?:5-21(?:-[0-9]+){4}|12-1(?:-[0-9]+){4})', backend_sid) is None
        ):
            raise PackageSecurityError('REGISTERED_TASK_BACKEND_USER_REQUIRED')
        self._base = base
        self._base_identity = base.verify()
        self.backend_sid = backend_sid
        self.operator_sid = current_operator_sid()
        self.path = local_absolute_path(self._base_identity.canonical_path) / 'task-runtime'
        aces = [(0, 0, OPERATOR_ACCESS, self.operator_sid)]
        if backend_sid != self.operator_sid:
            aces.append((0, 0, _DEPLOYMENT_TRAVERSE, backend_sid))
        self._directory = _TaskDirectory(
            self.path, 'deployment', self.operator_sid, tuple(aces), (_LABEL_TYPE, 0, 1, _MEDIUM)
        )

    @classmethod
    def create(cls, base, backend_sid):
        owner = cls(base, backend_sid)
        try:
            owner._directory.create()
            owner.verify()
            return owner
        except BaseException as error:
            error.retained_owner = owner
            raise

    @classmethod
    def open(cls, base, backend_sid, expected):
        owner = cls(base, backend_sid)
        if (
            type(expected) is not FileIdentity
            or not expected.is_directory
            or expected.filesystem != 'NTFS'
            or local_absolute_path(expected.canonical_path) != owner.path
        ):
            raise PackageSecurityError('REGISTERED_TASK_RUNTIME_IDENTITY_REQUIRED')
        try:
            owner._directory.pin(expected)
            owner.verify()
            return owner
        except BaseException as original:
            try:
                owner.close()
            except BaseException as cleanup:
                raise cleanup from original
            raise

    def require_disjoint(self, other):
        if type(other) is not FileIdentity or not other.is_directory or other.filesystem != 'NTFS':
            raise PackageSecurityError('ORIGINAL_TASK_PROTECTED_DIRECTORY_REQUIRED')
        path = local_absolute_path(other.canonical_path)
        original = self.verify()
        same_file = (original.volume_serial, original.file_id) == (
            other.volume_serial,
            other.file_id,
        )
        if same_file or self.path.is_relative_to(path) or path.is_relative_to(self.path):
            raise PackageSecurityError('TASK_RUNTIME_ROOT_MUST_BE_SEPARATE')

    def verify(self):
        if (
            self._base.verify() != self._base_identity
            or current_operator_sid() != self.operator_sid
        ):
            raise PackageSecurityError('ORIGINAL_TASK_RUNTIME_BASE_DIFFERS')
        return self._directory.verify().file

    def verify_controller(self, controller, *, checkpoint):
        if (
            type(controller) is not ControllerPrimaryToken
            or controller.identity.user_sid != self.backend_sid
        ):
            raise PackageSecurityError('ORIGINAL_TASK_RUNTIME_CONTROLLER_DIFFERS')
        checkpoint()
        original = self.verify()
        with ControllerAccessQuery(controller) as access:
            facts = access.query(self._directory._pin._path)
            if facts.file != original or facts.owner_sid != self.operator_sid:
                raise PackageSecurityError('ORIGINAL_TASK_RUNTIME_ACCESS_IDENTITY_DIFFERS')
            if self.backend_sid == self.operator_sid:
                # Same-account isolated execution cannot prove a separate principal's access.
                if facts.granted_access & _DEPLOYMENT_TRAVERSE != _DEPLOYMENT_TRAVERSE:
                    raise PackageSecurityError('TASK_RUNTIME_CONTROLLER_ACCESS_REQUIRED')
            else:
                if facts.granted_access != _DEPLOYMENT_TRAVERSE:
                    raise PackageSecurityError('TASK_RUNTIME_CONTROLLER_ACCESS_DIFFERS')
                for path in self.path.parents:
                    checkpoint()
                    with LocalPathGuard(path, directory=True) as ancestor:
                        granted = require_controller_read_only(
                            access.query(ancestor), role='ANCESTOR'
                        )
                        if granted.granted_access & _ANCESTOR_TRAVERSE != _ANCESTOR_TRAVERSE:
                            raise PackageSecurityError('TASK_RUNTIME_ANCESTOR_ACCESS_REQUIRED')
        checkpoint()
        if self.verify() != original:
            raise PackageSecurityError('ORIGINAL_TASK_RUNTIME_ACCESS_IDENTITY_DIFFERS')
        return original

    def close(self):
        try:
            self._directory.close()
        except BaseException as error:
            error.retained_owner = self
            raise

    def __enter__(self):
        self.verify()
        return self

    def __exit__(self, kind, error, traceback):
        self.close()


class TaskLpacDirectories:
    """One original allocation. Partial directories stay with their original owner."""

    def __init__(self, parent, actions, accepted, request, binding, controller):
        if (
            type(actions) is not GuardActionJournal
            or type(accepted) is not GuardActionStart
            or not accepted.first_accepted
        ):
            raise PackageSecurityError('ORIGINAL_TASK_DIRECTORY_FIRST_ACCEPTANCE_REQUIRED')
        original = accepted.record
        if (
            type(parent) is not TaskRuntimeRoot
            or original.action != 'PREPARE'
            or type(request) is not GuardRequestHeader
            or request.action != 'PREPARE'
            or request.recovery is not None
            or request.input.get('run_kind') not in ('TASK', CHECK_DRIVER_KIND)
            or original.scope != request.target_scope
            or original.owner_epoch != request.owner_epoch
            or original.input_sha256 != mutation_input_sha256(request)
            or original.phase != 'MAY_HAVE_BEEN_SENT'
            or original.allocated_binding_ref is None
            or type(binding) is not GuardControllerBinding
            or original.owner_epoch != binding.owner_epoch
            or original.scope.controller_ref != binding.controller_ref
            or type(controller) is not ControllerPrimaryToken
            or controller._expected != binding.controller
        ):
            raise PackageSecurityError('ORIGINAL_TASK_DIRECTORY_ALLOCATION_REQUIRED')
        parent.require_disjoint(actions._journal._package.verify())
        self.scope = original.scope
        self.run_kind = request.input['run_kind']
        self.binding_ref = original.allocated_binding_ref
        purpose = request.input.get('execution_purpose')
        check = request.input.get('check_input')
        self.check_input = None
        if purpose == PROJECT_CHECK_PURPOSE:
            if self.is_browser_driver and type(self.scope) is not TestingLaunchScope:
                raise PackageSecurityError('ORIGINAL_DRIVER_DIRECTORY_SCOPE_REQUIRED')
            self.check_input = decode_project_check_input(check, self.scope)
        elif (
            purpose is not None
            or self.is_browser_driver
            or 'check_input' in request.input
            or type(self.scope) is TestingLaunchScope
        ):
            raise PackageSecurityError('ORIGINAL_TASK_DIRECTORY_PURPOSE_INVALID')
        self._check_publication = self._check_fixture = None
        self.profile = task_lpac_profile(original.directory_nonce)
        self.root = parent.path / ('task-' + original.directory_nonce)
        self._parent, self._controller = parent, controller
        self._actions, self._original = actions, original
        self._parent_identity = parent.verify()
        self._operator = parent.operator_sid
        self._user = controller.identity.user_sid
        kernel, security = _api()
        with _lpac_security_capabilities(self.profile) as capabilities:
            self.package_sid = _sid_text(kernel, security, capabilities.appcontainer_sid)
        self._directories = {}
        self._basis_group = None
        self._basis_intake = None
        self._workspace_publication = None
        self._runtime_preparation = None
        self._execution_preparation = None
        self._launch_read_ack = None
        self._prepare_request = request
        self._runtime_bundle_ref = request.input.get('runtime_bundle_ref')
        self._workspace_manifest_sha256 = request.input.get('workspace_manifest_sha256')
        self._workspace_nonce = request.input.get('workspace_nonce')
        self._basis_plan_sha256 = request.input.get('basis_plan_sha256')
        self._started = False

    @property
    def is_browser_driver(self):
        return self.run_kind == CHECK_DRIVER_KIND

    @property
    def is_project_check(self):
        return self.check_input is not None

    def _require_open(self, cancelled):
        journal = self._actions._journal
        journal._require_controller_open(self.scope)
        fence = journal.inspect(self.scope)
        expected = self._original if self._launch_read_ack is None else self._launch_read_ack
        if (
            cancelled()
            or self._parent.verify() != self._parent_identity
            or self.scope.key in journal._volatile_closed
            or self._actions.find(self.scope, 'STOP') is not None
            or self._actions.find(self.scope, 'PREPARE') != expected
            or (self._launch_read_ack is None and fence is not None)
            or (
                self._launch_read_ack is not None
                and (
                    fence is None
                    or fence.stop_closed
                    or fence.resume_state != 'NONE'
                    or fence.input_sha256 != expected.result['launch_input_sha256']
                )
            )
        ):
            raise PackageSecurityError('ORIGINAL_TASK_DIRECTORY_ALLOCATION_INTERRUPTED')

    @contextmanager
    def launch_read(self, acknowledged, cancelled):
        journal = self._actions._journal
        with journal._scope(self.scope):
            if (
                self._launch_read_ack is not None
                or acknowledged.scope != self.scope
                or acknowledged.phase != 'ACKNOWLEDGED'
                or acknowledged.input_sha256 != self._original.input_sha256
                or acknowledged.allocated_binding_ref != self.binding_ref
            ):
                raise PackageSecurityError('ORIGINAL_TASK_LAUNCH_FILE_READ_UNVERIFIED')
            self._launch_read_ack = acknowledged
            try:
                self._require_open(cancelled)
                yield
            finally:
                self._launch_read_ack = None

    def allocate(self, *, cancelled):
        if self._started or not callable(cancelled):
            raise PackageSecurityError('ORIGINAL_TASK_DIRECTORY_ALLOCATION_NOT_NEW')
        self._started = True
        try:
            with self._actions._journal._scope(self.scope), self._controller.creation_handle():
                self._parent.verify_controller(
                    self._controller, checkpoint=lambda: self._require_open(cancelled)
                )
                for role in TASK_ROLES:
                    self._require_open(cancelled)
                    if role != 'root':
                        self._directories['root'].verify()
                    path = self.root if role == 'root' else self.root / role
                    policy_role = 'basis' if role == 'workspace' and self.is_project_check else role
                    aces, label = _policy(policy_role, self._operator, self._user, self.package_sid)
                    directory = _TaskDirectory(path, role, self._operator, aces, label)
                    self._directories[role] = directory
                    directory.create()
                self._require_open(cancelled)
                return self.verify()
        except BaseException as error:
            error.retained_owner = self
            raise

    def verify(self):
        if (
            set(self._directories) != set(TASK_ROLES)
            or self._parent.verify() != self._parent_identity
        ):
            raise PackageSecurityError('ORIGINAL_TASK_DIRECTORIES_UNVERIFIED')
        return tuple(self._directories[role].verify() for role in TASK_ROLES)

    def workspace_destination(self):
        if self.is_project_check:
            raise PackageSecurityError('CHECK_WORKSPACE_WRITER_NOT_ALLOWED')
        self.verify()
        return TaskWorkspaceDestination(
            self.scope,
            self.binding_ref,
            self._original.directory_nonce,
            self._directories['workspace'].original,
        )

    def close(self):
        try:
            if self._execution_preparation is not None:
                self._execution_preparation.close()
                self._execution_preparation = None
            self.close_content()
        except BaseException as error:
            error.retained_owner = self
            raise

    def close_content(self):
        try:
            for name in ('_check_publication', '_check_fixture'):
                publication = getattr(self, name)
                if publication is not None:
                    publication.close()
                    setattr(self, name, None)
            if self._basis_group is not None:
                self._basis_group.close()
                self._basis_group = None
            self._basis_intake = None
            if self._workspace_publication is not None:
                self._workspace_publication.close()
                self._workspace_publication = None
            if self._runtime_preparation is not None:
                self._runtime_preparation.close()
                self._runtime_preparation = None
        except BaseException as error:
            error.retained_owner = self
            raise
        error = None
        for role, directory in reversed(tuple(self._directories.items())):
            try:
                directory.close()
            except (OSError, RuntimeError) as failure:
                error = failure
            else:
                del self._directories[role]
        if error is not None:
            error.retained_owner = self
            raise error
