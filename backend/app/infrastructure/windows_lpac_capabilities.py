"""Strict named OS read capabilities for fixed, admitted Windows runtime resources."""

import ctypes
from contextlib import contextmanager
from ctypes import wintypes

OPENCODE_LPAC_CAPABILITY_NAMES = ('registryRead',)


class LpacCapabilityError(RuntimeError):
    def __init__(self, code, native_error=None):
        self.native_error = native_error
        super().__init__(code)


def validate_lpac_capability_names(names):
    if type(names) is not tuple or names not in (
        (),
        ('registryRead',),
        ('registryRead', 'lpacCom'),
    ):
        raise LpacCapabilityError('LPAC_SYSTEM_CAPABILITY_POLICY_INVALID')
    return names


class _NamedCapabilitySids:
    def __init__(self):
        self.kernel = ctypes.WinDLL('kernelbase', use_last_error=True)
        self.kernel.DeriveCapabilitySidsFromName.argtypes = [
            wintypes.LPCWSTR,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.kernel.DeriveCapabilitySidsFromName.restype = wintypes.BOOL
        self.kernel.LocalFree.argtypes = [ctypes.c_void_p]
        self.kernel.LocalFree.restype = ctypes.c_void_p
        self.arrays = []
        self.members = []
        self.capabilities = ()
        self.failed_close = False

    def derive(self, name):
        groups = ctypes.POINTER(ctypes.c_void_p)()
        capabilities = ctypes.POINTER(ctypes.c_void_p)()
        group_count = wintypes.DWORD()
        capability_count = wintypes.DWORD()
        success = self.kernel.DeriveCapabilitySidsFromName(
            name,
            ctypes.byref(groups),
            ctypes.byref(group_count),
            ctypes.byref(capabilities),
            ctypes.byref(capability_count),
        )
        error = ctypes.get_last_error()
        for array, count in ((groups, group_count.value), (capabilities, capability_count.value)):
            if array:
                self.arrays.append(ctypes.cast(array, ctypes.c_void_p).value)
                # Returned native arrays are owned even when later validation fails.
                self.members.extend(array[index] for index in range(count))
        if not success or capability_count.value != 1 or group_count.value != 1:
            raise LpacCapabilityError('LPAC_SYSTEM_CAPABILITY_SID_UNVERIFIED', error)
        self.capabilities = (capabilities[0],)
        if len(set(self.members)) != len(self.members) or not all(self.members):
            raise LpacCapabilityError('LPAC_SYSTEM_CAPABILITY_SID_UNVERIFIED')
        return self.capabilities

    def close(self):
        if self.failed_close:
            error = LpacCapabilityError('LPAC_SYSTEM_CAPABILITY_RELEASE_UNKNOWN')
            error.retained_owner = self
            raise error
        for pointers in (self.members, self.arrays):
            for pointer in tuple(pointers):
                if self.kernel.LocalFree(pointer):
                    self.failed_close = True
                    error = LpacCapabilityError(
                        'LPAC_SYSTEM_CAPABILITY_RELEASE_UNKNOWN', ctypes.get_last_error()
                    )
                    error.retained_owner = self
                    raise error
                pointers.remove(pointer)


@contextmanager
def hold_lpac_capability_sids(names):
    validate_lpac_capability_names(names)
    if not names:
        yield ()
        return
    owned = _NamedCapabilitySids()
    try:
        pointers = []
        for name in names:
            pointers.extend(owned.derive(name))
        yield tuple(pointers)
    finally:
        owned.close()


def lpac_capability_sid_texts(names):
    from .windows_private_package import _api, _sid_text

    validate_lpac_capability_names(names)
    if not names:
        return ()
    kernel, security = _api()
    with hold_lpac_capability_sids(names) as sids:
        return tuple(_sid_text(kernel, security, ctypes.c_void_p(sid)) for sid in sids)
