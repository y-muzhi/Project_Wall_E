"""A held CHECK_DRIVER-only logon session derived from its original controller."""

import ctypes
from contextlib import contextmanager
from ctypes import wintypes
from threading import RLock
from uuid import uuid4

from .runtime_launch_journal import LaunchOutcomeUnknown
from .windows_controller_token import (
    ControllerPrimaryToken,
    Luid,
    _luid,
    _non_inheritable,
    _read_token,
)
from .windows_lpac_profile import _under_token
from .windows_private_package import SidAttributes, _sid_text
from .windows_process import _token_buffer


def _security_state(kernel, security, token):
    class Groups(ctypes.Structure):
        _fields_ = [('count', wintypes.DWORD), ('members', SidAttributes * 1)]

    class Privilege(ctypes.Structure):
        _fields_ = [('luid', Luid), ('attributes', wintypes.DWORD)]

    class Privileges(ctypes.Structure):
        _fields_ = [('count', wintypes.DWORD), ('members', Privilege * 1)]

    result = []
    for kind, shape, member in ((2, Groups, SidAttributes), (3, Privileges, Privilege)):
        raw, size = _token_buffer(security, token, kind)
        count = wintypes.DWORD.from_buffer(raw).value
        offset = shape.members.offset
        if count > 256 or size < offset + count * ctypes.sizeof(member):
            raise LaunchOutcomeUnknown('CHECK_LOGON_SOURCE_SECURITY_UNVERIFIED')
        rows = (member * count).from_buffer(raw, offset)
        if kind == 2:
            result.append(
                tuple(
                    sorted(
                        (_sid_text(kernel, security, wintypes.LPVOID(row.sid)), row.attributes)
                        for row in rows
                        if row.attributes & 0xC0000000 != 0xC0000000
                    )
                )
            )
        else:
            result.append(tuple(sorted((_luid(row.luid), row.attributes) for row in rows)))
    return tuple(result)


class CheckLogonSession:
    """The source handle stays private to Guard and is never given to the driver."""

    def __init__(self, controller):
        if type(controller) is not ControllerPrimaryToken:
            raise LaunchOutcomeUnknown('ORIGINAL_CHECK_LOGON_CONTROLLER_REQUIRED')
        self._controller = controller
        self._kernel, self._security = controller._kernel, controller._security
        self._gate = RLock()
        self._handle = None
        self._identity = None
        self._state = None
        security = self._security
        security.LogonUserW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        security.LogonUserW.restype = wintypes.BOOL
        try:
            with controller.creation_handle() as source:
                self._original = controller.identity
                source_state = _security_state(self._kernel, security, source)

                def derive():
                    handle = wintypes.HANDLE()
                    password = ctypes.create_unicode_buffer(uuid4().hex + uuid4().hex)
                    try:
                        if not security.LogonUserW(
                            'wallecheck-' + uuid4().hex[:12],
                            '.',
                            password,
                            9,
                            3,
                            ctypes.byref(handle),
                        ):
                            raise LaunchOutcomeUnknown('PRIVATE_CHECK_LOGON_UNAVAILABLE')
                        self._handle = handle.value
                    finally:
                        ctypes.memset(ctypes.addressof(password), 0, ctypes.sizeof(password))

                _under_token(self._kernel, security, source, derive)
                if not self._kernel.SetHandleInformation(self._handle, 1, 0):
                    raise LaunchOutcomeUnknown('CHECK_LOGON_INHERITANCE_UNVERIFIED')
                self._identity = _read_token(self._kernel, security, self._handle)
                self._state = _security_state(self._kernel, security, self._handle)
                if (
                    self._identity.user_sid != self._original.user_sid
                    or self._identity.session_id != self._original.session_id
                    or self._identity.authentication_id_hex == self._original.authentication_id_hex
                    or set(self._state[0]) - set(source_state[0])
                    or not set(source_state[0]) - set(self._state[0])
                    <= {
                        ('S-1-2-0', 7),
                        ('S-1-5-64-10', 7),
                    }
                    or self._state[1] != source_state[1]
                ):
                    raise LaunchOutcomeUnknown('CHECK_LOGON_SOURCE_IDENTITY_DIFFERS')
                self._verify()
        except BaseException as original:
            try:
                self.close()
            except LaunchOutcomeUnknown as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    @property
    def identity(self):
        return self.verify()

    def _verify(self):
        if self._handle is None:
            raise LaunchOutcomeUnknown('CHECK_LOGON_SOURCE_CLOSED')
        _non_inheritable(self._kernel, self._handle)
        if (
            self._controller.identity != self._original
            or _read_token(self._kernel, self._security, self._handle) != self._identity
            or _security_state(self._kernel, self._security, self._handle) != self._state
        ):
            raise LaunchOutcomeUnknown('CHECK_LOGON_SOURCE_CHANGED')
        return self._identity

    def verify(self):
        with self._gate, self._controller.creation_handle():
            return self._verify()

    @contextmanager
    def creation_handle(self):
        with self._gate, self._controller.creation_handle():
            self._verify()
            try:
                yield self._handle
            finally:
                self._verify()

    def close(self):
        with self._gate:
            if self._handle is not None:
                if not self._kernel.CloseHandle(self._handle):
                    error = LaunchOutcomeUnknown('CHECK_LOGON_SOURCE_CLOSE_UNKNOWN')
                    error.retained_owner = self
                    raise error
                self._handle = None
