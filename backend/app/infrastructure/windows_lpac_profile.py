"""Create-only ownership of a task's per-user Windows AppContainer profile."""

import ctypes
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from dataclasses import asdict

from .guard_task_files import _publish_original, _read_original
from .guard_task_network import task_network_unlaunched_after_stop
from .runtime_launch_journal import LaunchOutcomeUnknown, _bytes
from .windows_controller_token import _no_thread_impersonation
from .windows_job import JobMembers, OwnedJob
from .windows_local_paths import LocalPathGuard, local_absolute_path
from .windows_private_package import _sid_text
from .windows_task_directories import TaskLpacDirectories

_LIMIT = 8192


class TaskLpacProfileError(LaunchOutcomeUnknown):
    def __init__(self, code, native_error=None):
        self.native_error = native_error
        super().__init__(code)


def _under_token(kernel, security, token, action):
    """Run one narrowly scoped operation on a thread that cannot leak impersonation."""
    security.ImpersonateLoggedOnUser.argtypes = [wintypes.HANDLE]
    security.ImpersonateLoggedOnUser.restype = wintypes.BOOL
    security.RevertToSelf.argtypes = []
    security.RevertToSelf.restype = wintypes.BOOL

    def invoke():
        _no_thread_impersonation(kernel, security)
        if not security.ImpersonateLoggedOnUser(token):
            raise TaskLpacProfileError(
                'ORIGINAL_LPAC_IMPERSONATION_UNVERIFIED', ctypes.get_last_error()
            )
        try:
            return action()
        finally:
            if not security.RevertToSelf():
                raise TaskLpacProfileError(
                    'ORIGINAL_LPAC_IMPERSONATION_REVERT_UNVERIFIED', ctypes.get_last_error()
                )
            _no_thread_impersonation(kernel, security)

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='walle-owned-lpac-native') as worker:
        return worker.submit(invoke).result()


def _profile_api():
    userenv = ctypes.WinDLL('userenv', use_last_error=True)
    userenv.CreateAppContainerProfile.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
    ]
    userenv.CreateAppContainerProfile.restype = ctypes.c_long
    userenv.DeleteAppContainerProfile.argtypes = [wintypes.LPCWSTR]
    userenv.DeleteAppContainerProfile.restype = ctypes.c_long
    userenv.GetAppContainerFolderPath.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPWSTR)]
    userenv.GetAppContainerFolderPath.restype = ctypes.c_long
    memory = ctypes.WinDLL('ole32', use_last_error=True)
    memory.CoTaskMemFree.argtypes = [wintypes.LPVOID]
    memory.CoTaskMemFree.restype = None
    return userenv, memory


class TaskLpacProfile:
    def __init__(self, directories, job):
        if (
            type(directories) is not TaskLpacDirectories
            or directories.scope.step_no not in ((3, 4) if directories.is_project_check else (4,))
            or type(job) is not OwnedJob
        ):
            raise TaskLpacProfileError('ORIGINAL_LPAC_PROFILE_SCOPE_REQUIRED')
        self._dirs, self._job = directories, job
        self._journal = directories._actions._journal
        self._kernel, self._security = (
            directories._controller._kernel,
            directories._controller._security,
        )
        self._security.FreeSid.argtypes = [wintypes.LPVOID]
        self._security.FreeSid.restype = wintypes.LPVOID
        self._api, self._memory = _profile_api()
        self._started = self._created = self._release_may = self._released = False
        self._folder = None
        self._intent = {
            'schema_version': 1,
            'scope': directories.scope.key,
            'prepare_input_sha256': directories._original.input_sha256,
            'owner_epoch': directories._original.owner_epoch,
            'binding_ref': directories.binding_ref,
            'user_sid': directories._controller.identity.user_sid,
            'logon': directories._controller.identity.authentication_id_hex,
            'name': directories.profile,
            'sid': directories.package_sid,
        }

    def _name(self, suffix):
        return self._dirs.scope.key + '.task-lpac-profile-' + suffix + '.json'

    def _read(self, suffix):
        return _read_original(self._journal._package, self._name(suffix), _LIMIT)

    def _write(self, suffix, facts):
        raw = _bytes(facts)
        _publish_original(self._journal._package, self._name(suffix), raw, _LIMIT)
        if self._read(suffix) != raw:
            raise TaskLpacProfileError('ORIGINAL_LPAC_PROFILE_RECORD_UNVERIFIED')

    def _call(self, action, recovery_controller=None):
        controller = self._dirs._controller if recovery_controller is None else recovery_controller
        with controller.creation_handle() as token:
            return _under_token(self._kernel, self._security, token, action)

    def _native_create(self):
        sid = wintypes.LPVOID()
        status = self._api.CreateAppContainerProfile(
            self._dirs.profile,
            'WALL-E task',
            'Private original task profile',
            None,
            0,
            ctypes.byref(sid),
        )
        try:
            if status != 0:
                raise TaskLpacProfileError('ORIGINAL_LPAC_PROFILE_CREATE_UNVERIFIED', status)
            self._created = True
            if (
                not sid.value
                or _sid_text(self._kernel, self._security, sid) != self._dirs.package_sid
            ):
                raise TaskLpacProfileError('ORIGINAL_LPAC_PROFILE_SID_DIFFERS')
        finally:
            if sid.value and self._security.FreeSid(sid):
                raise TaskLpacProfileError('ORIGINAL_LPAC_PROFILE_SID_FREE_UNVERIFIED')

    def _native_folder(self):
        path = wintypes.LPWSTR()
        status = self._api.GetAppContainerFolderPath(self._dirs.package_sid, ctypes.byref(path))
        try:
            if status != 0 or not path:
                raise TaskLpacProfileError('ORIGINAL_LPAC_PROFILE_PATH_UNVERIFIED', status)
            return path.value
        finally:
            if path:
                self._memory.CoTaskMemFree(ctypes.cast(path, wintypes.LPVOID))

    def _observe_folder(self, recovery_controller=None):
        path = local_absolute_path(self._call(self._native_folder, recovery_controller))
        if self._dirs.root.is_relative_to(path) or path.is_relative_to(self._dirs.root):
            raise TaskLpacProfileError('ORIGINAL_LPAC_PROFILE_PATH_DIFFERS')
        with LocalPathGuard(path, directory=True) as folder:
            return folder.verify()

    def prepare(self, cancelled):
        with self._journal._scope(self._dirs.scope):
            if self._started or self._read('intent') is not None:
                raise TaskLpacProfileError('ORIGINAL_LPAC_PROFILE_ALREADY_DISPATCHED')
            self._started = True
            self._dirs._require_open(cancelled)
            if self._job.observe_members() != JobMembers((), 0, True):
                raise TaskLpacProfileError('ORIGINAL_LPAC_PROFILE_JOB_NOT_EMPTY')
            with self._journal._gate:
                self._dirs._require_open(cancelled)
                self._write('intent', self._intent)
            self._dirs._require_open(cancelled)
            self._call(self._native_create)
            self._folder = self._observe_folder()
            self._dirs._require_open(cancelled)
            self._write('created', {'intent': self._intent, 'folder': asdict(self._folder)})
            return self.verify(cancelled)

    def verify_identity(self):
        with self._journal._scope(self._dirs.scope):
            if (
                not self._created
                or self._released
                or self._release_may
                or self._folder is None
                or self._read('intent') != _bytes(self._intent)
                or self._read('created')
                != _bytes({'intent': self._intent, 'folder': asdict(self._folder)})
                or self._observe_folder() != self._folder
            ):
                raise TaskLpacProfileError('ORIGINAL_LPAC_PROFILE_EVIDENCE_UNVERIFIED')
            return self._folder

    def verify(self, cancelled):
        with self._journal._scope(self._dirs.scope):
            self._dirs._require_open(cancelled)
            identity = self.verify_identity()
            self._dirs._require_open(cancelled)
            return identity

    def release(self):
        scope = self._dirs.scope
        with self._journal._scope(scope):
            if self._released:
                return
            if not task_network_unlaunched_after_stop(
                self._dirs._actions, scope, self._journal.inspect(scope)
            ):
                raise TaskLpacProfileError('ORIGINAL_LPAC_PROFILE_RELEASE_UNVERIFIED')
            self._release_stopped()

    def release_after_native_stop(self, native, *, recovery_controller=None):
        from .windows_controller_token import ControllerPrimaryToken
        from .windows_task_native_launch import TaskNativeLaunch

        if (
            type(native) is not TaskNativeLaunch
            or native._profile is not self
            or (
                recovery_controller is not None
                and (
                    type(recovery_controller) is not ControllerPrimaryToken
                    or recovery_controller.identity.user_sid != self._intent['user_sid']
                )
            )
        ):
            raise TaskLpacProfileError('ORIGINAL_LPAC_PROFILE_RELEASE_UNVERIFIED')
        with self._journal._scope(self._dirs.scope):
            native.stopped_evidence()
            self._release_stopped(recovery_controller)

    def release_evidence(self):
        with self._journal._scope(self._dirs.scope):
            if not self._released or self._read('released') != _bytes(self._intent):
                return False
            try:
                local_absolute_path(self._folder.canonical_path).lstat()
            except FileNotFoundError:
                return True
            raise TaskLpacProfileError('ORIGINAL_LPAC_PROFILE_STORAGE_STILL_PRESENT')

    def _release_stopped(self, recovery_controller=None):
        scope = self._dirs.scope
        with self._journal._scope(scope):
            if self._released:
                return
            if (
                not self._created
                or self._folder is None
                or self._release_may
                or self._read('intent') != _bytes(self._intent)
                or self._job.observe_members() != JobMembers((), 0, True)
            ):
                raise TaskLpacProfileError('ORIGINAL_LPAC_PROFILE_RELEASE_UNVERIFIED')
            folder = self._observe_folder(recovery_controller)
            if folder != self._folder:
                raise TaskLpacProfileError('ORIGINAL_LPAC_PROFILE_PATH_DIFFERS')
            self._write('release', {'intent': self._intent, 'folder': asdict(folder)})
            self._release_may = True
            status = self._call(
                lambda: self._api.DeleteAppContainerProfile(self._dirs.profile), recovery_controller
            )
            if status != 0:
                raise TaskLpacProfileError('ORIGINAL_LPAC_PROFILE_DELETE_UNVERIFIED', status)
            try:
                local_absolute_path(folder.canonical_path).lstat()
            except FileNotFoundError:
                self._write('released', self._intent)
                self._released = True
                return
            raise TaskLpacProfileError('ORIGINAL_LPAC_PROFILE_STORAGE_STILL_PRESENT')
