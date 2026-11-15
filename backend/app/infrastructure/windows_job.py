"""Guard-owned anonymous Windows Job, never a task completion decision.

Only this process holds the Job handle. Creation attributes associate a suspended
root atomically with the Job; no assign-after-create or breakaway fallback.
"""

import ctypes
import re
from contextlib import ExitStack, contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from threading import RLock
from uuid import uuid4

from .windows_lpac_capabilities import (
    hold_lpac_capability_sids,
    validate_lpac_capability_names,
)
from .windows_process import ObservedProcess, ProcessObservationError
from .windows_process import _api as _process_api

KILL_ON_JOB_CLOSE = 0x2000
ACTIVE_PROCESS_LIMIT = 0x8
JOB_MEMORY_LIMIT = 0x200
BREAKAWAY_FLAGS = 0x800 | 0x1000
JOB_LIST_ATTRIBUTE = 0x0002000D
HANDLE_LIST_ATTRIBUTE = 0x00020002
SECURITY_CAPABILITIES_ATTRIBUTE = 0x00020009
ALL_APPLICATION_PACKAGES_POLICY_ATTRIBUTE = 0x0002000F
ALL_APPLICATION_PACKAGES_OPT_OUT = 0x1
MAX_JOB_PROCESSES = 4096


class JobBoundaryError(RuntimeError):
    def __init__(self, code, native_error=None):
        self.code = code
        self.native_error = native_error
        super().__init__(code)


class SecurityCapabilities(ctypes.Structure):
    _fields_ = [
        ('appcontainer_sid', wintypes.LPVOID),
        ('capabilities', wintypes.LPVOID),
        ('capability_count', wintypes.DWORD),
        ('reserved', wintypes.DWORD),
    ]


def task_lpac_profile(directory_nonce):
    if type(directory_nonce) is not str or re.fullmatch('[0-9a-f]{32}', directory_nonce) is None:
        raise JobBoundaryError('JOB_PRIVATE_LPAC_PROFILE_NAME_REQUIRED')
    return 'walle-win20-' + directory_nonce


@contextmanager
def _lpac_security_capabilities(profile, capability_names=()):
    if type(profile) is not str or re.fullmatch(r'walle-win20-[a-f0-9]{32}', profile) is None:
        raise JobBoundaryError('JOB_PRIVATE_LPAC_PROFILE_NAME_REQUIRED')
    if ctypes.sizeof(SecurityCapabilities) != 24:
        raise JobBoundaryError('JOB_LPAC_CAPABILITIES_LAYOUT_UNSUPPORTED')
    userenv = ctypes.WinDLL('userenv', use_last_error=True)
    security = ctypes.WinDLL('advapi32', use_last_error=True)
    userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(wintypes.LPVOID),
    ]
    userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long
    security.IsValidSid.argtypes = [wintypes.LPVOID]
    security.IsValidSid.restype = wintypes.BOOL
    security.FreeSid.argtypes = [wintypes.LPVOID]
    security.FreeSid.restype = wintypes.LPVOID
    sid = wintypes.LPVOID()
    result = userenv.DeriveAppContainerSidFromAppContainerName(profile, ctypes.byref(sid))
    try:
        if result != 0 or not sid.value or not security.IsValidSid(sid):
            raise JobBoundaryError('JOB_PRIVATE_LPAC_SID_UNAVAILABLE', result)
        from .windows_private_package import SidAttributes

        # Empty by default. Names only come from an independently pinned CHECK_DRIVER resource.
        with hold_lpac_capability_sids(capability_names) as pointers:
            values = (SidAttributes * len(pointers))(
                *(SidAttributes(pointer, 4) for pointer in pointers)
            )
            address = ctypes.cast(values, wintypes.LPVOID) if pointers else None
            yield SecurityCapabilities(sid, address, len(pointers), 0)
    finally:
        if sid.value and security.FreeSid(sid):
            raise _error('JOB_PRIVATE_LPAC_SID_RELEASE_UNVERIFIED')


class IoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            'read_operations',
            'write_operations',
            'other_operations',
            'read_bytes',
            'write_bytes',
            'other_bytes',
        )
    ]


class BasicLimits(ctypes.Structure):
    _fields_ = [
        ('process_time', ctypes.c_int64),
        ('job_time', ctypes.c_int64),
        ('flags', wintypes.DWORD),
        ('minimum_working_set', ctypes.c_size_t),
        ('maximum_working_set', ctypes.c_size_t),
        ('active_process_limit', wintypes.DWORD),
        ('affinity', ctypes.c_size_t),
        ('priority_class', wintypes.DWORD),
        ('scheduling_class', wintypes.DWORD),
    ]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ('basic', BasicLimits),
        ('io', IoCounters),
        ('process_memory', ctypes.c_size_t),
        ('job_memory', ctypes.c_size_t),
        ('peak_process_memory', ctypes.c_size_t),
        ('peak_job_memory', ctypes.c_size_t),
    ]


@dataclass(frozen=True)
class JobMembers:
    process_ids: tuple[int, ...]
    assigned_count: int
    complete: bool


def _error(code):
    return JobBoundaryError(code, ctypes.get_last_error())


def _api():
    kernel, _ = _process_api()
    if ctypes.sizeof(BasicLimits) != 64 or ctypes.sizeof(ExtendedLimits) != 144:
        raise JobBoundaryError('JOB_NATIVE_LAYOUT_UNSUPPORTED')
    kernel.IsProcessInJob.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.BOOL),
    ]
    kernel.IsProcessInJob.restype = wintypes.BOOL
    kernel.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.QueryInformationJobObject.restype = wintypes.BOOL
    kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateJobObject.restype = wintypes.BOOL
    kernel.GetHandleInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.GetHandleInformation.restype = wintypes.BOOL
    kernel.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    kernel.SetHandleInformation.restype = wintypes.BOOL
    kernel.InitializeProcThreadAttributeList.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    kernel.UpdateProcThreadAttribute.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.c_size_t,
        wintypes.LPVOID,
        ctypes.c_size_t,
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    kernel.UpdateProcThreadAttribute.restype = wintypes.BOOL
    kernel.DeleteProcThreadAttributeList.argtypes = [wintypes.LPVOID]
    kernel.DeleteProcThreadAttributeList.restype = None
    return kernel


class OwnedJob:
    def __init__(self, *, active_process_limit, job_memory_limit_bytes):
        if (
            type(active_process_limit) is not int
            or not 1 <= active_process_limit <= MAX_JOB_PROCESSES
        ):
            raise JobBoundaryError('JOB_PROCESS_LIMIT_INVALID')
        if (
            type(job_memory_limit_bytes) is not int
            or not 1 <= job_memory_limit_bytes <= 0x7FFFFFFFFFFFFFFF
        ):
            raise JobBoundaryError('JOB_MEMORY_LIMIT_INVALID')
        self._kernel = _api()
        self._gate = RLock()
        self._process_limit = active_process_limit
        self._memory_limit = job_memory_limit_bytes
        self._handle = self._kernel.CreateJobObjectW(None, None)
        if not self._handle:
            raise _error('JOB_CREATE_FAILED')
        try:
            if not self._kernel.SetHandleInformation(self._handle, 1, 0):
                raise _error('JOB_HANDLE_INHERITANCE_UNVERIFIED')
            limits = ExtendedLimits()
            limits.basic.flags = KILL_ON_JOB_CLOSE | ACTIVE_PROCESS_LIMIT | JOB_MEMORY_LIMIT
            limits.basic.active_process_limit = active_process_limit
            limits.job_memory = job_memory_limit_bytes
            if not self._kernel.SetInformationJobObject(
                self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            ):
                raise _error('JOB_LIMITS_NOT_APPLIED')
            self.verify_limits()
        except BaseException:
            self.close()
            raise

    def _require_handle(self):
        if not self._handle:
            raise JobBoundaryError('JOB_HANDLE_CLOSED')
        return self._handle

    def verify_limits(self):
        with self._gate:
            actual = ExtendedLimits()
            returned = wintypes.DWORD()
            if not self._kernel.QueryInformationJobObject(
                self._require_handle(),
                9,
                ctypes.byref(actual),
                ctypes.sizeof(actual),
                ctypes.byref(returned),
            ):
                raise _error('JOB_LIMITS_UNVERIFIED')
            required = KILL_ON_JOB_CLOSE | ACTIVE_PROCESS_LIMIT | JOB_MEMORY_LIMIT
            if (
                actual.basic.flags & required != required
                or actual.basic.flags & BREAKAWAY_FLAGS
                or actual.basic.active_process_limit != self._process_limit
                or actual.job_memory != self._memory_limit
            ):
                raise JobBoundaryError('JOB_LIMITS_DIFFER')
            return True

    def contains_process(self, process):
        if type(process) is not ObservedProcess:
            raise JobBoundaryError('HELD_PROCESS_REQUIRED')
        # Process-before-Job order matches native creation's controller lease.
        with process._gate, self._gate:
            process.observe()
            inside = wintypes.BOOL()
            if not self._kernel.IsProcessInJob(
                process._handle, self._require_handle(), ctypes.byref(inside)
            ):
                raise _error('JOB_PROCESS_MEMBERSHIP_UNVERIFIED')
            if inside.value not in (0, 1):
                raise JobBoundaryError('JOB_PROCESS_MEMBERSHIP_INVALID')
            return bool(inside.value)

    def observe_members(self):
        with self._gate:
            handle = self._require_handle()
            capacity = min(32, self._process_limit)
            for _ in range(4):
                size = 8 + capacity * ctypes.sizeof(ctypes.c_size_t)
                buffer = ctypes.create_string_buffer(size)
                returned = wintypes.DWORD()
                success = self._kernel.QueryInformationJobObject(
                    handle, 3, buffer, size, ctypes.byref(returned)
                )
                error = ctypes.get_last_error() if not success else None
                if not success and error != 234:
                    raise JobBoundaryError('JOB_MEMBERS_UNVERIFIED', error)
                counts = ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD))
                assigned, count = counts[0], counts[1]
                if count > capacity or assigned > self._process_limit:
                    raise JobBoundaryError('JOB_MEMBER_LIMIT_CONFLICT')
                array = (ctypes.c_size_t * count).from_buffer(buffer, 8)
                pids = tuple(int(pid) for pid in array)
                if any(not 1 <= pid <= 0xFFFFFFFF for pid in pids) or len(set(pids)) != len(pids):
                    raise JobBoundaryError('JOB_MEMBER_IDENTITIES_INVALID')
                complete = bool(success and count == assigned)
                if complete:
                    return JobMembers(pids, assigned, True)
                if capacity >= self._process_limit:
                    return JobMembers(pids, assigned, False)
                capacity = min(self._process_limit, max(capacity * 2, assigned))
            return JobMembers(pids, assigned, False)

    @contextmanager
    def process_creation_attributes(
        self,
        *,
        stdio_handles=(),
        lpac_profile=None,
        driver_result_handle=None,
        lpac_capability_names=(),
    ):
        validate_lpac_capability_names(lpac_capability_names)
        if lpac_profile is None and lpac_capability_names:
            raise JobBoundaryError('JOB_LPAC_PROFILE_REQUIRED')
        if type(stdio_handles) is not tuple or (stdio_handles and len(stdio_handles) != 3):
            raise JobBoundaryError('JOB_STDIO_HANDLE_LIST_INVALID')
        inherited = stdio_handles
        if driver_result_handle is not None:
            inherited += (driver_result_handle,)
        if any(
            type(value) is not int or not 1 <= value <= 0x7FFFFFFFFFFFFFFF for value in inherited
        ):
            raise JobBoundaryError('JOB_STDIO_HANDLE_LIST_INVALID')
        if len(set(inherited)) != len(inherited):
            raise JobBoundaryError('JOB_STDIO_HANDLE_LIST_INVALID')
        # Keep Job and exact handle-list storage alive across native creation.
        with self._gate, ExitStack() as resources:
            self.verify_limits()
            handle = self._require_handle()
            capabilities = None
            if lpac_profile is not None:
                capabilities = resources.enter_context(
                    _lpac_security_capabilities(lpac_profile, lpac_capability_names)
                    if lpac_capability_names
                    else _lpac_security_capabilities(lpac_profile)
                )
            for value in inherited:
                if value == handle:
                    raise JobBoundaryError('JOB_HANDLE_MUST_NOT_BE_INHERITED')
                flags = wintypes.DWORD()
                if (
                    not self._kernel.GetHandleInformation(value, ctypes.byref(flags))
                    or not flags.value & 1
                ):
                    raise _error('JOB_STDIO_INHERITANCE_UNVERIFIED')
            attribute_count = 1 + bool(inherited) + 2 * (capabilities is not None)
            size = ctypes.c_size_t()
            result = self._kernel.InitializeProcThreadAttributeList(
                None, attribute_count, 0, ctypes.byref(size)
            )
            if result or ctypes.get_last_error() != 122 or not 1 <= size.value <= 65536:
                raise _error('JOB_ATTRIBUTE_LAYOUT_UNVERIFIED')
            attributes = ctypes.create_string_buffer(size.value)
            initialized = self._kernel.InitializeProcThreadAttributeList(
                attributes, attribute_count, 0, ctypes.byref(size)
            )
            if not initialized:
                raise _error('JOB_ATTRIBUTES_NOT_INITIALIZED')
            jobs = (wintypes.HANDLE * 1)(handle)
            handles = (wintypes.HANDLE * len(inherited))(*inherited)
            try:
                if not self._kernel.UpdateProcThreadAttribute(
                    attributes, 0, JOB_LIST_ATTRIBUTE, jobs, ctypes.sizeof(jobs), None, None
                ):
                    raise _error('JOB_CREATION_ASSOCIATION_UNSUPPORTED')
                if inherited and not self._kernel.UpdateProcThreadAttribute(
                    attributes,
                    0,
                    HANDLE_LIST_ATTRIBUTE,
                    handles,
                    ctypes.sizeof(handles),
                    None,
                    None,
                ):
                    raise _error('JOB_STDIO_WHITELIST_UNSUPPORTED')
                if capabilities is not None:
                    if not self._kernel.UpdateProcThreadAttribute(
                        attributes,
                        0,
                        SECURITY_CAPABILITIES_ATTRIBUTE,
                        ctypes.byref(capabilities),
                        ctypes.sizeof(capabilities),
                        None,
                        None,
                    ):
                        raise _error('JOB_SECURITY_CAPABILITIES_UNSUPPORTED')
                    policy = wintypes.DWORD(ALL_APPLICATION_PACKAGES_OPT_OUT)
                    if not self._kernel.UpdateProcThreadAttribute(
                        attributes,
                        0,
                        ALL_APPLICATION_PACKAGES_POLICY_ATTRIBUTE,
                        ctypes.byref(policy),
                        ctypes.sizeof(policy),
                        None,
                        None,
                    ):
                        raise _error('JOB_LPAC_POLICY_OPT_OUT_UNSUPPORTED')
                yield ctypes.cast(attributes, wintypes.LPVOID)
            finally:
                self._kernel.DeleteProcThreadAttributeList(attributes)

    def terminate_owned(self, exit_code):
        if type(exit_code) is not int or not 0 <= exit_code <= 0xFFFFFFFF:
            raise JobBoundaryError('JOB_EXIT_CODE_INVALID')
        with self._gate:
            if not self._kernel.TerminateJobObject(self._require_handle(), exit_code):
                raise _error('JOB_TERMINATION_UNVERIFIED')
        # Caller must separately observe all original steps, resources and exits.

    def close(self):
        with self._gate:
            if self._handle:
                if not self._kernel.CloseHandle(self._handle):
                    error = _error('JOB_HANDLE_CLOSE_UNVERIFIED')
                    error.retained_owner = self
                    raise error
                self._handle = None

    def __enter__(self):
        self._require_handle()
        return self

    def __exit__(self, kind, error, traceback):
        self.close()


def probe_lpac_creation_attributes():
    """Check kernel attribute support without creating a profile or child."""
    try:
        with OwnedJob(active_process_limit=1, job_memory_limit_bytes=16 * 1024 * 1024) as job:
            profile = 'walle-win20-' + uuid4().hex
            with job.process_creation_attributes(lpac_profile=profile):
                return job.observe_members() == JobMembers((), 0, True)
    except (JobBoundaryError, ProcessObservationError, OSError, AttributeError) as error:
        if getattr(error, 'retained_owner', None) is not None:
            raise
        return False
