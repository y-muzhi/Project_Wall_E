"""Read the actual token of a held, suspended task root before any resume."""

import ctypes
import ntpath
from ctypes import wintypes
from dataclasses import dataclass

from .runtime_launch_journal import LaunchOutcomeUnknown
from .windows_access_check import GenericMapping
from .windows_access_check import _api as access_api
from .windows_check_logon import CheckLogonSession
from .windows_controller_token import TokenStatistics, _dword, _luid, _non_inheritable
from .windows_executable_pin import ExecutablePin
from .windows_job import OwnedJob
from .windows_lpac_capabilities import lpac_capability_sid_texts, validate_lpac_capability_names
from .windows_lpac_profile import TaskLpacProfile, _under_token
from .windows_native_process import ProcessInfo, _api
from .windows_private_package import _sid_text
from .windows_process import NativeProcessIdentity, _identity, _token_buffer, _token_flag


class LpacTokenError(LaunchOutcomeUnknown):
    def __init__(self, code, native_error=None):
        self.native_error = native_error
        super().__init__(code)


@dataclass(frozen=True)
class LpacTokenEvidence:
    process: NativeProcessIdentity
    authentication_id_hex: str
    session_id: int
    token_id_hex: str
    modified_id_hex: str
    integrity_sid: str
    lpac_evidence: str


def _first_sid(kernel, security, token, kind):
    buffer, size = _token_buffer(security, token, kind)
    if size < ctypes.sizeof(wintypes.LPVOID):
        raise LpacTokenError('ORIGINAL_LPAC_TOKEN_SID_UNAVAILABLE')
    pointer = ctypes.cast(buffer, ctypes.POINTER(wintypes.LPVOID)).contents
    return _sid_text(kernel, security, pointer)


def _verify_capability_sids(kernel, security, token, expected):
    from .windows_private_package import SidAttributes

    class CapabilityGroups(ctypes.Structure):
        _fields_ = [('count', wintypes.DWORD), ('groups', SidAttributes * 1)]

    buffer, size = _token_buffer(security, token, 30)
    if size < 4 or wintypes.DWORD.from_buffer(buffer).value != len(expected):
        raise LpacTokenError('ORIGINAL_LPAC_TOKEN_CAPABILITIES_DIFFERS')
    count = len(expected)
    offset = CapabilityGroups.groups.offset
    if count and size < offset + count * ctypes.sizeof(SidAttributes):
        raise LpacTokenError('ORIGINAL_LPAC_TOKEN_CAPABILITIES_DIFFERS')
    start = ctypes.addressof(buffer)
    observed = []
    for index in range(count):
        row = SidAttributes.from_buffer(buffer, offset + index * ctypes.sizeof(SidAttributes))
        pointer = row.sid
        if (
            not pointer
            or not start + offset + count * ctypes.sizeof(SidAttributes)
            <= pointer
            <= start + size - 8
        ):
            raise LpacTokenError('ORIGINAL_LPAC_TOKEN_CAPABILITIES_DIFFERS')
        header = ctypes.string_at(pointer, 8)
        sid_size = 8 + 4 * header[1]
        if header[0] != 1 or not 8 <= sid_size <= 68 or pointer + sid_size > start + size:
            raise LpacTokenError('ORIGINAL_LPAC_TOKEN_CAPABILITIES_DIFFERS')
        if row.attributes != 4:
            raise LpacTokenError('ORIGINAL_LPAC_TOKEN_CAPABILITIES_DIFFERS')
        observed.append(_sid_text(kernel, security, wintypes.LPVOID(pointer)))
    if tuple(observed) != expected:
        raise LpacTokenError('ORIGINAL_LPAC_TOKEN_CAPABILITIES_DIFFERS')


def _lpac_facts(kernel, security, token, original, expected_sid, *, primary, capability_sids=()):
    if (
        not _token_flag(security, token, 29)
        or _token_flag(security, token, 46, allow_unsupported=True) is False
        or _token_flag(security, token, 20)
        or _first_sid(kernel, security, token, 31) != expected_sid
        or _first_sid(kernel, security, token, 1) != original.user_sid
    ):
        raise LpacTokenError('ORIGINAL_LPAC_TOKEN_IDENTITY_DIFFERS')
    _verify_capability_sids(kernel, security, token, capability_sids)
    integrity = _first_sid(kernel, security, token, 25)
    if integrity != 'S-1-16-4096':
        raise LpacTokenError('ORIGINAL_LPAC_TOKEN_INTEGRITY_DIFFERS')
    statistics = TokenStatistics()
    returned = wintypes.DWORD()
    if not security.GetTokenInformation(
        token, 10, ctypes.byref(statistics), ctypes.sizeof(statistics), ctypes.byref(returned)
    ) or returned.value != ctypes.sizeof(statistics):
        raise LpacTokenError('ORIGINAL_LPAC_TOKEN_STATISTICS_UNVERIFIED', ctypes.get_last_error())
    logon = _luid(statistics.authentication_id)
    session = _dword(security, token, 12)
    if (
        logon != original.authentication_id_hex
        or session != original.session_id
        or statistics.token_type != (1 if primary else 2)
        or (not primary and statistics.impersonation_level != 2)
    ):
        raise LpacTokenError('ORIGINAL_LPAC_TOKEN_LOGON_DIFFERS')
    return logon, session, _luid(statistics.token_id), _luid(statistics.modified_id), integrity


def _package_read_allowed(kernel, security, token, user, principal):
    text = f'O:{user}G:{user}D:P(A;;0x1;;;{user})(A;;0x1;;;{principal})'
    descriptor = wintypes.LPVOID()
    size = wintypes.DWORD()
    if (
        not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            text, 1, ctypes.byref(descriptor), ctypes.byref(size)
        )
        or not descriptor.value
    ):
        raise LpacTokenError('ORIGINAL_LPAC_OPT_OUT_DESCRIPTOR_UNVERIFIED', ctypes.get_last_error())
    try:
        mapping = GenericMapping(0x120089, 0x120116, 0x1200A0, 0x1F01FF)
        privileges = ctypes.create_string_buffer(4096)
        privilege_size = wintypes.DWORD(len(privileges))
        granted, allowed = wintypes.DWORD(), wintypes.BOOL()
        if not security.AccessCheck(
            descriptor,
            token,
            1,
            ctypes.byref(mapping),
            privileges,
            ctypes.byref(privilege_size),
            ctypes.byref(granted),
            ctypes.byref(allowed),
        ):
            raise LpacTokenError('ORIGINAL_LPAC_OPT_OUT_ACCESS_UNVERIFIED', ctypes.get_last_error())
        if (allowed.value, granted.value) not in ((0, 0), (1, 1)):
            raise LpacTokenError('ORIGINAL_LPAC_OPT_OUT_ACCESS_DIFFERS')
        return bool(allowed.value)
    finally:
        if kernel.LocalFree(descriptor):
            raise LpacTokenError(
                'ORIGINAL_LPAC_OPT_OUT_DESCRIPTOR_CLOSE_UNVERIFIED', ctypes.get_last_error()
            )


def prove_lpac_opt_out(kernel, security, token, user, package):
    """Effective access checks on a held impersonation token; no files are created."""

    def allows(principal):
        return _package_read_allowed(kernel, security, token, user, principal)

    if not allows(package) or not allows('S-1-15-2-2') or allows('S-1-15-2-1'):
        raise LpacTokenError('ORIGINAL_LPAC_TOKEN_OPT_OUT_UNVERIFIED')
    return 'EFFECTIVE_OPT_OUT'


def prove_current_lpac_opt_out(user, package):
    """Use the same native fallback on kernels lacking the LPAC flag query."""
    kernel, security = _api()
    security.AccessCheck.argtypes = [
        wintypes.LPVOID,
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(GenericMapping),
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.BOOL),
    ]
    security.AccessCheck.restype = wintypes.BOOL
    security.DuplicateTokenEx.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    security.DuplicateTokenEx.restype = wintypes.BOOL
    primary, impersonation = wintypes.HANDLE(), wintypes.HANDLE()
    try:
        if not security.OpenProcessToken(kernel.GetCurrentProcess(), 0xA, ctypes.byref(primary)):
            raise LpacTokenError('ORIGINAL_LPAC_SELF_TOKEN_UNVERIFIED')
        if (
            not _token_flag(security, primary, 29)
            or _token_flag(security, primary, 20)
            or _first_sid(kernel, security, primary, 1) != user
            or _first_sid(kernel, security, primary, 31) != package
            or _first_sid(kernel, security, primary, 25) != 'S-1-16-4096'
        ):
            raise LpacTokenError('ORIGINAL_LPAC_SELF_IDENTITY_DIFFERS')
        if not security.DuplicateTokenEx(primary, 0xC, None, 2, 2, ctypes.byref(impersonation)):
            raise LpacTokenError('ORIGINAL_LPAC_SELF_COPY_UNVERIFIED')
        _non_inheritable(kernel, primary)
        _non_inheritable(kernel, impersonation)
        return prove_lpac_opt_out(kernel, security, impersonation, user, package)
    finally:
        errors = []
        for handle in (impersonation, primary):
            if handle and not kernel.CloseHandle(handle):
                errors.append(ctypes.get_last_error())
        if errors:
            raise LpacTokenError('ORIGINAL_LPAC_SELF_TOKEN_CLOSE_UNVERIFIED', errors[0])


class LpacProcessToken:
    def __init__(self, process_info, job, profile, pin, *, capability_names=(), launch_source=None):
        if (
            type(process_info) is not ProcessInfo
            or not process_info.process
            or not process_info.thread
            or type(profile) is not TaskLpacProfile
            or type(job) is not OwnedJob
            or job is not profile._job
            or type(pin) is not ExecutablePin
        ):
            raise LpacTokenError('ORIGINAL_LPAC_PROCESS_RESOURCES_REQUIRED')
        validate_lpac_capability_names(capability_names)
        self._capability_sids = lpac_capability_sid_texts(capability_names)
        self._process = process_info
        self._job, self.profile, self._pin = job, profile, pin
        profile.verify_identity()
        self._controller = profile._dirs._controller
        if (
            launch_source is not None
            and launch_source is not self._controller
            and (
                type(launch_source) is not CheckLogonSession
                or launch_source._controller is not self._controller
                or not profile._dirs.is_browser_driver
            )
        ):
            raise LpacTokenError('ORIGINAL_LPAC_LAUNCH_SOURCE_DIFFERS')
        self._launch_source = self._controller if launch_source is None else launch_source

        self._kernel, self._security = _api()
        self._access_kernel, self._access_security = access_api(self._controller)
        self._security.DuplicateTokenEx = self._controller._security.DuplicateTokenEx
        self._program = pin.verify().file
        self._token = self._impersonation = None
        self._evidence = None
        try:
            token = wintypes.HANDLE()
            if not self._security.OpenProcessToken(process_info.process, 0xA, ctypes.byref(token)):
                raise LpacTokenError('ORIGINAL_LPAC_TOKEN_OPEN_UNVERIFIED', ctypes.get_last_error())
            self._token = token.value
            self._evidence = self._inspect()
        except BaseException as original:
            try:
                self.close()
            except LpacTokenError as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    def _inspect(self, *, require_suspended_thread=True):
        process, kernel, security = self._process, self._kernel, self._security
        _non_inheritable(kernel, process.process)
        _non_inheritable(kernel, process.thread)
        _non_inheritable(kernel, self._token)
        if (
            kernel.GetThreadId(process.thread) != process.tid
            or kernel.GetProcessIdOfThread(process.thread) != process.pid
            or (require_suspended_thread and kernel.WaitForSingleObject(process.thread, 0) != 258)
            or kernel.WaitForSingleObject(process.process, 0) != 258
        ):
            raise LpacTokenError('ORIGINAL_LPAC_THREAD_IDENTITY_DIFFERS')
        actual = _identity(kernel, security, process.process, process.pid)
        with self._pin._gate:
            if self._pin._closing or self._pin._handle is None:
                raise LpacTokenError('ORIGINAL_LPAC_PROCESS_IMAGE_UNVERIFIED')
            expected = self._pin._attributes()
        if expected != self._program:
            raise LpacTokenError('ORIGINAL_LPAC_PROCESS_IMAGE_DIFFERS')
        if ntpath.normcase(actual.image_path) != ntpath.normcase(expected.canonical_path):
            raise LpacTokenError('ORIGINAL_LPAC_PROCESS_IMAGE_DIFFERS')
        if (
            not actual.is_appcontainer
            or actual.is_elevated
            or actual.appcontainer_sid != self.profile._dirs.package_sid
        ):
            raise LpacTokenError('ORIGINAL_LPAC_PROCESS_IDENTITY_DIFFERS')
        if actual.is_lpac is False:
            raise LpacTokenError('ORIGINAL_LPAC_TOKEN_FLAG_FALSE')
        method = 'TOKEN_FLAG' if actual.is_lpac is True else self._prove_opt_out()
        with self._job._gate:
            self._job.verify_limits()
            inside = wintypes.BOOL()
            if (
                not self._job._kernel.IsProcessInJob(
                    process.process, self._job._require_handle(), ctypes.byref(inside)
                )
                or inside.value != 1
            ):
                raise LpacTokenError('ORIGINAL_LPAC_JOB_MEMBERSHIP_UNVERIFIED')
        facts = _lpac_facts(
            kernel,
            security,
            self._token,
            self._launch_source.identity,
            self.profile._dirs.package_sid,
            primary=True,
            capability_sids=self._capability_sids,
        )
        return LpacTokenEvidence(actual, *facts, method)

    def verify(self):
        if self._token is None or self._inspect() != self._evidence:
            raise LpacTokenError('ORIGINAL_LPAC_TOKEN_EVIDENCE_UNVERIFIED')
        return self._evidence

    def verify_running(self):
        if (
            self._evidence is None
            or self._inspect(require_suspended_thread=False) != self._evidence
        ):
            raise LpacTokenError('ORIGINAL_LPAC_TOKEN_CHANGED')
        return self._evidence

    def _query_token(self):
        if self._impersonation is None:
            token = wintypes.HANDLE()
            if not self._security.DuplicateTokenEx(
                self._token, 0xC, None, 2, 2, ctypes.byref(token)
            ):
                raise LpacTokenError(
                    'ORIGINAL_LPAC_ACCESS_TOKEN_UNVERIFIED', ctypes.get_last_error()
                )
            self._impersonation = token.value
        _non_inheritable(self._kernel, self._impersonation)
        _lpac_facts(
            self._kernel,
            self._security,
            self._impersonation,
            self._launch_source.identity,
            self.profile._dirs.package_sid,
            primary=False,
            capability_sids=self._capability_sids,
        )
        return self._impersonation

    def _prove_opt_out(self):
        token = self._query_token()
        user, package = self._controller.identity.user_sid, self.profile._dirs.package_sid

        return prove_lpac_opt_out(self._access_kernel, self._access_security, token, user, package)

    def with_restricted_token(self, action):
        self.verify()
        self._query_token()
        result = _under_token(self._kernel, self._security, self._impersonation, action)
        self.verify()
        return result

    def close(self):
        for name in ('_impersonation', '_token'):
            handle = getattr(self, name)
            if handle is not None:
                if not self._kernel.CloseHandle(handle):
                    error = LpacTokenError(
                        'ORIGINAL_LPAC_TOKEN_CLOSE_UNVERIFIED', ctypes.get_last_error()
                    )
                    error.retained_owner = self
                    raise error
                setattr(self, name, None)
