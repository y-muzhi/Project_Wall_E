"""Non-mutating effective path probes under the actual original LPAC token."""

import ctypes
import hashlib
from contextlib import ExitStack
from dataclasses import asdict, dataclass

from .runtime_launch_journal import _bytes
from .windows_local_paths import FileIdentity, LocalPathGuard, _identity, local_absolute_path
from .windows_local_paths import _api as file_api
from .windows_lpac_token import LpacProcessToken, LpacTokenError
from .windows_task_directories import MUTABLE_ROLES, READ_ONLY_ROLES, TaskLpacDirectories

_LIST_OR_READ = 0x1
_ADD_OR_WRITE = 0x2
_APPEND_OR_SUBDIRECTORY = 0x4
_WRITE_EA = 0x10
_EXECUTE_OR_TRAVERSE = 0x20
_DELETE_CHILD = 0x40
_READ_ATTRIBUTES = 0x80
_WRITE_ATTRIBUTES = 0x100
_DELETE = 0x10000
_WRITE_DAC = 0x40000
_WRITE_OWNER = 0x80000
_FILE_MUTATIONS = (
    _ADD_OR_WRITE,
    _APPEND_OR_SUBDIRECTORY,
    _WRITE_EA,
    _WRITE_ATTRIBUTES,
    _DELETE,
    _WRITE_DAC,
    _WRITE_OWNER,
)
_READ = _LIST_OR_READ | _READ_ATTRIBUTES
_TRAVERSE = _EXECUTE_OR_TRAVERSE | _READ_ATTRIBUTES
_CHECK_BATCH = 32


@dataclass(frozen=True)
class LpacAccessEvidence:
    checks_sha256: str
    object_count: int


class _OriginalAccessProbe:
    def __init__(self, token):
        self._token = token
        self._kernel = file_api()
        self._handles = []

    def _check(self, identity, path, mask, *, allowed):
        handle = self._kernel.CreateFileW(
            str(path), mask, 0x1 | 0x2 | 0x4, None, 3, 0x00200000 | 0x02000000, None
        )
        if not handle or handle == ctypes.c_void_p(-1).value:
            error = ctypes.get_last_error()
            if not allowed and error == 5:
                return
            raise LpacTokenError('ORIGINAL_LPAC_PATH_ACCESS_UNVERIFIED', error)
        self._handles.append(handle)
        try:
            if not allowed:
                raise LpacTokenError('ORIGINAL_LPAC_PATH_UNEXPECTED_ACCESS')
            if _identity(self._kernel, handle, path) != identity:
                raise LpacTokenError('ORIGINAL_LPAC_PATH_IDENTITY_DIFFERS')
        finally:
            if not self._kernel.CloseHandle(handle):
                error = LpacTokenError(
                    'ORIGINAL_LPAC_PATH_CLOSE_UNVERIFIED', ctypes.get_last_error()
                )
                error.retained_owner = self
                raise error
            self._handles.remove(handle)

    def probe(self, checks):
        with ExitStack() as opened:
            held = []
            for _, identity, allowed, denied in checks:
                path = local_absolute_path(identity.canonical_path)
                guard = opened.enter_context(LocalPathGuard(path, directory=identity.is_directory))
                if guard.verify() != identity:
                    raise LpacTokenError('ORIGINAL_LPAC_PATH_IDENTITY_DIFFERS')
                held.append((guard, identity, allowed, denied))

            def inspect():
                for guard, identity, allowed, denied in held:
                    if allowed:
                        self._check(identity, guard.path, allowed, allowed=True)
                    for mask in denied:
                        self._check(identity, guard.path, mask, allowed=False)

            self._token.with_restricted_token(inspect)
            if any(guard.verify() != identity for guard, identity, _, _ in held):
                raise LpacTokenError('ORIGINAL_LPAC_PATH_IDENTITY_DIFFERS')

    def close(self):
        for handle in tuple(self._handles):
            if not self._kernel.CloseHandle(handle):
                error = LpacTokenError(
                    'ORIGINAL_LPAC_PATH_CLOSE_UNVERIFIED', ctypes.get_last_error()
                )
                error.retained_owner = self
                raise error
            self._handles.remove(handle)


def verify_lpac_task_access(token, directories, read_only_members, protected, checkpoint):
    """Check held original roles, their admitted members, and protected original roots."""
    if type(directories) is not TaskLpacDirectories:
        raise LpacTokenError('ORIGINAL_LPAC_ACCESS_SCOPE_DIFFERS')
    writable = ('scratch',) if directories.is_project_check else MUTABLE_ROLES
    read_only = (*READ_ONLY_ROLES, 'workspace') if directories.is_project_check else READ_ONLY_ROLES
    if (
        type(token) is not LpacProcessToken
        or token.profile._dirs is not directories
        or type(read_only_members) is not dict
        or set(read_only_members) != set(read_only)
        or type(protected) is not tuple
        or not protected
    ):
        raise LpacTokenError('ORIGINAL_LPAC_ACCESS_SCOPE_DIFFERS')
    checkpoint()
    scope = directories.scope
    journal = directories._actions._journal

    def require_open():
        checkpoint()
        journal._require_controller_open(scope)
        fence = journal.inspect(scope)
        if (
            scope.key in journal._volatile_closed
            or (fence is not None and (fence.stop_closed or fence.resume_state != 'NONE'))
            or directories._actions.find(scope, 'STOP') is not None
        ):
            raise LpacTokenError('ORIGINAL_LPAC_ACCESS_SCOPE_FENCED')

    with journal._scope(scope):
        require_open()
        token.profile.verify_identity()
        roles = {fact.role: fact.file for fact in directories.verify()}
        checks = [
            ('root', roles['root'], _TRAVERSE, (_LIST_OR_READ, *_FILE_MUTATIONS, _DELETE_CHILD))
        ]
        for role in writable:
            checks.append(
                (
                    role,
                    roles[role],
                    _READ | _TRAVERSE | _ADD_OR_WRITE | _APPEND_OR_SUBDIRECTORY,
                    (_DELETE, _WRITE_DAC, _WRITE_OWNER),
                )
            )
        for role in read_only:
            original = roles[role]
            root = local_absolute_path(original.canonical_path)
            members = read_only_members[role]
            if type(members) is not tuple or any(
                type(file) is not FileIdentity for file in members
            ):
                raise LpacTokenError('ORIGINAL_LPAC_MEMBER_SCOPE_DIFFERS')
            ordered = sorted(members, key=lambda file: file.canonical_path)
            for file in (original, *ordered):
                path = local_absolute_path(file.canonical_path)
                if not path.is_relative_to(root) or (file is not original and path == root):
                    raise LpacTokenError('ORIGINAL_LPAC_MEMBER_SCOPE_DIFFERS')
                can_execute = file.is_directory or role == 'runtime'
                allowed = _READ | (_EXECUTE_OR_TRAVERSE if can_execute else 0)
                denied = _FILE_MUTATIONS + ((_DELETE_CHILD,) if file.is_directory else ())
                if not can_execute:
                    denied += (_EXECUTE_OR_TRAVERSE,)
                checks.append((role, file, allowed, denied))
        if not any(identity == token._program for _, identity, _, _ in checks):
            checks.append(
                ('program', token._program, _READ | _EXECUTE_OR_TRAVERSE, _FILE_MUTATIONS)
            )
        for file in (journal._package.verify(), *protected):
            if type(file) is not FileIdentity:
                raise LpacTokenError('ORIGINAL_LPAC_PROTECTED_SCOPE_DIFFERS')
            target = local_absolute_path(file.canonical_path)
            if target.is_relative_to(directories.root) or directories.root.is_relative_to(target):
                raise LpacTokenError('ORIGINAL_LPAC_PROTECTED_SCOPE_DIFFERS')
            denied = (
                _LIST_OR_READ,
                *_FILE_MUTATIONS,
                *((_DELETE_CHILD,) if file.is_directory else ()),
            )
            checks.append(('protected', file, 0, denied))
        probe = _OriginalAccessProbe(token)
        digest = hashlib.sha256()
        try:
            for offset in range(0, len(checks), _CHECK_BATCH):
                require_open()
                batch = checks[offset : offset + _CHECK_BATCH]
                probe.probe(batch)
                for role, identity, allowed, denied in batch:
                    digest.update(
                        _bytes(
                            {
                                'role': role,
                                'identity': asdict(identity),
                                'allowed': allowed,
                                'denied': denied,
                            }
                        )
                    )
            require_open()
            return LpacAccessEvidence(digest.hexdigest(), len(checks))
        finally:
            probe.close()
