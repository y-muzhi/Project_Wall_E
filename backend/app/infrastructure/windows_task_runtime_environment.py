"""Prepare a private instance environment from the original TASK directories."""

import ctypes
import hashlib
from ctypes import wintypes
from dataclasses import dataclass

from .opencode_control import OpenCodeControlCredential
from .opencode_managed_config import opencode_managed_source_clear
from .runtime_launch_journal import _bytes
from .windows_local_paths import LocalPathGuard, local_absolute_path
from .windows_task_directories import _policy, _TaskDirectory
from .windows_task_runtime_bundle import TaskRuntimeFilesError

_SCRATCH = ('home', 'data', 'cache', 'state', 'temp', 'appdata', 'localappdata')
_OPENCODE_FLAGS = (
    'DISABLE_PROJECT_CONFIG',
    'PURE',
    'DISABLE_DEFAULT_PLUGINS',
    'DISABLE_EXTERNAL_SKILLS',
    'DISABLE_CLAUDE_CODE',
    'DISABLE_LSP_DOWNLOAD',
    'DISABLE_MODELS_FETCH',
    'DISABLE_AUTOUPDATE',
    'ENABLE_QUESTION_TOOL',
)


@dataclass(frozen=True)
class TaskRuntimeEnvironmentEvidence:
    environment_sha256: str


def _windows_system_paths():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    get_directory = kernel.GetWindowsDirectoryW
    get_directory.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    get_directory.restype = wintypes.UINT
    path = ctypes.create_unicode_buffer(32768)
    count = get_directory(path, len(path))
    if not 1 <= count < len(path):
        raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_WINDOWS_DIRECTORY_UNAVAILABLE')
    windows = local_absolute_path(path.value)
    with (
        LocalPathGuard(windows, directory=True) as root,
        LocalPathGuard(windows / 'System32', directory=True) as system,
    ):
        return root.verify(), system.verify()


class TaskRuntimeEnvironment:
    def __init__(self, directories, bundle):
        self._dirs, self._bundle = directories, bundle
        if directories.is_project_check != (bundle is None):
            raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_ENVIRONMENT_PURPOSE_DIFFERS')
        self._scratch_names = (*_SCRATCH, 'output') if directories.is_project_check else _SCRATCH
        self._config_names = () if directories.is_project_check else ('opencode',)
        self._children = {}
        self._system = self._values = self._evidence = None
        self._started = False

    def _create(self, role, name):
        dirs = self._dirs
        aces, label = _policy(role, dirs._operator, dirs._user, dirs.package_sid)
        path = dirs._directories[role].path / name
        child = _TaskDirectory(path, role, dirs._operator, aces, label)
        self._children[(role, name)] = child
        child.create()

    def prepare(self, checkpoint):
        if self._started:
            raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_ENVIRONMENT_ALREADY_DISPATCHED')
        self._started = True
        checkpoint()
        if not self._dirs.is_project_check and not opencode_managed_source_clear():
            raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_SYSTEM_CONFIG_UNVERIFIED')
        self._system = _windows_system_paths()
        config = self._dirs._directories['config'].path
        scratch = self._dirs._directories['scratch'].path
        if any(config.iterdir()) or any(scratch.iterdir()):
            raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_ENVIRONMENT_NOT_EMPTY')
        for name in self._config_names:
            self._create('config', name)
        for name in self._scratch_names:
            checkpoint()
            self._create('scratch', name)
        windows, system = self._system
        self._values = {
            'SystemRoot': windows.canonical_path,
            'SystemDrive': local_absolute_path(windows.canonical_path).drive,
            'WINDIR': windows.canonical_path,
            'PATH': system.canonical_path,
            'HOME': str(scratch / 'home'),
            'USERPROFILE': str(scratch / 'home'),
            'APPDATA': str(scratch / 'appdata'),
            'LOCALAPPDATA': str(scratch / 'localappdata'),
            'TEMP': str(scratch / 'temp'),
            'TMP': str(scratch / 'temp'),
            'XDG_CONFIG_HOME': str(config),
            'XDG_DATA_HOME': str(scratch / 'data'),
            'XDG_CACHE_HOME': str(scratch / 'cache'),
            'XDG_STATE_HOME': str(scratch / 'state'),
        }
        if self._dirs.is_project_check:
            self._values['WALLE_CHECK_OUTPUT'] = str(scratch / 'output')
        else:
            self._values.update(
                OPENCODE_CONFIG=str(self._bundle.configuration_path),
                **{'OPENCODE_' + name: 'true' for name in _OPENCODE_FLAGS},
            )
        self._evidence = self._inspect(checkpoint)
        return self._evidence

    def _inspect(self, checkpoint):
        checkpoint()
        if (
            not self._dirs.is_project_check and not opencode_managed_source_clear()
        ) or _windows_system_paths() != self._system:
            raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_SYSTEM_CONFIG_UNVERIFIED')
        for role, names in (('config', self._config_names), ('scratch', self._scratch_names)):
            directory = self._dirs._directories[role]
            directory.verify()
            if {entry.name for entry in directory.path.iterdir()} != set(names):
                raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_ENVIRONMENT_TREE_DIFFERS')
        facts = {}
        for (role, name), child in self._children.items():
            checkpoint()
            facts[role + '/' + name] = child.verify().file.file_id
            if any(child.path.iterdir()):
                raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_ENVIRONMENT_TREE_DIFFERS')
        checkpoint()
        return TaskRuntimeEnvironmentEvidence(
            hashlib.sha256(_bytes({'environment': self._values, 'directories': facts})).hexdigest()
        )

    def verify(self, checkpoint):
        if self._evidence is None:
            raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_ENVIRONMENT_UNVERIFIED')
        if self._inspect(checkpoint) != self._evidence:
            raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_ENVIRONMENT_DIFFERS')
        return self._evidence

    def values(self, checkpoint):
        self.verify(checkpoint)
        return self._values.copy()

    def launch_values(self, credential, plan, checkpoint):
        if self._dirs.is_project_check or type(credential) is not OpenCodeControlCredential:
            raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_CONTROL_CREDENTIAL_REQUIRED')
        return {**self.values(checkpoint), **credential.launch_variables(self._dirs.scope, plan)}

    def close(self):
        for key, child in tuple(self._children.items()):
            try:
                child.close()
            except BaseException as error:
                error.retained_owner = self
                raise
            del self._children[key]
