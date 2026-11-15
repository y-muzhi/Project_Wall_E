"""Read one stopped original child thread; no PID attach, debug privilege or injected code."""

import ctypes
import struct
from ctypes import wintypes


class ModuleInfo(ctypes.Structure):
    _fields_ = [('base', ctypes.c_void_p), ('size', wintypes.DWORD), ('entry', ctypes.c_void_p)]


def sample_owned_thread(info, *, stopped_by_original_debug_event=False):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    signatures = {
        'SuspendThread': ([wintypes.HANDLE], wintypes.DWORD),
        'ResumeThread': ([wintypes.HANDLE], wintypes.DWORD),
        'GetProcessId': ([wintypes.HANDLE], wintypes.DWORD),
        'GetThreadContext': ([wintypes.HANDLE, ctypes.c_void_p], wintypes.BOOL),
        'ReadProcessMemory': (
            [
                wintypes.HANDLE,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_size_t),
            ],
            wintypes.BOOL,
        ),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes = arguments
        function.restype = result
    psapi.EnumProcessModulesEx.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.HMODULE),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.DWORD,
    ]
    psapi.EnumProcessModulesEx.restype = wintypes.BOOL
    psapi.GetModuleInformation.argtypes = [
        wintypes.HANDLE,
        wintypes.HMODULE,
        ctypes.POINTER(ModuleInfo),
        wintypes.DWORD,
    ]
    psapi.GetModuleInformation.restype = wintypes.BOOL
    psapi.GetModuleBaseNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.HMODULE,
        wintypes.LPWSTR,
        wintypes.DWORD,
    ]
    psapi.GetModuleBaseNameW.restype = wintypes.DWORD
    assert kernel.GetProcessId(info.process) == info.pid
    modules = (wintypes.HMODULE * 128)()
    size = wintypes.DWORD()
    assert psapi.EnumProcessModulesEx(
        info.process, modules, ctypes.sizeof(modules), ctypes.byref(size), 3
    ), ctypes.get_last_error()
    assert size.value <= ctypes.sizeof(modules)
    images = []
    for module in modules[: size.value // ctypes.sizeof(wintypes.HMODULE)]:
        facts = ModuleInfo()
        name = ctypes.create_unicode_buffer(260)
        assert psapi.GetModuleInformation(
            info.process, module, ctypes.byref(facts), ctypes.sizeof(facts)
        )
        assert psapi.GetModuleBaseNameW(info.process, module, name, len(name))
        images.append((facts.base, facts.size, name.value))
    ntdll = ctypes.WinDLL('ntdll')
    known = {}
    for name in (
        'NtRaiseHardError',
        'NtWaitForSingleObject',
        'NtWaitForMultipleObjects',
        'NtDelayExecution',
        'NtAlpcSendWaitReceivePort',
        'NtReadFile',
        'NtCreateNamedPipeFile',
        'NtDeviceIoControlFile',
        'NtWaitForWorkViaWorkerFactory',
    ):
        known[name] = ctypes.cast(getattr(ntdll, name), ctypes.c_void_p).value - ntdll._handle

    def image_for(address):
        for base, size, name in images:
            if base <= address < base + size:
                offset = address - base
                if name.casefold() == 'ntdll.dll':
                    for symbol, start in known.items():
                        if start <= offset < start + 32:
                            return name + '!' + symbol + '+' + hex(offset - start)
                return name + '+' + hex(offset)
        return None

    storage = ctypes.create_string_buffer(1248)
    address = (ctypes.addressof(storage) + 15) & ~15
    context = (ctypes.c_ubyte * 1232).from_address(address)
    struct.pack_into('<I', context, 48, 0x100003)
    previous = 0 if stopped_by_original_debug_event else kernel.SuspendThread(info.thread)
    assert previous == 0, ('Original thread was not running', previous, ctypes.get_last_error())
    try:
        assert kernel.GetThreadContext(info.thread, address), ctypes.get_last_error()
        raw = bytes(context)
        rip = struct.unpack_from('<Q', raw, 248)[0]
        rsp = struct.unpack_from('<Q', raw, 152)[0]
        stack = ctypes.create_string_buffer(min(2048, 4096 - (rsp & 4095)))
        read = ctypes.c_size_t()
        assert kernel.ReadProcessMemory(info.process, rsp, stack, len(stack), ctypes.byref(read)), (
            ctypes.get_last_error()
        )
        frames = []
        for (value,) in struct.iter_unpack('<Q', stack.raw[: read.value // 8 * 8]):
            mapped = image_for(value)
            if mapped is not None and (not frames or frames[-1] != mapped):
                frames.append(mapped)
        literals = []
        readonly = []
        for base, size, name in images:
            if name.casefold() == 'chrome-headless-shell.exe':
                header = ctypes.create_string_buffer(4096)
                count = ctypes.c_size_t()
                if kernel.ReadProcessMemory(
                    info.process, base, header, len(header), ctypes.byref(count)
                ):
                    pe = struct.unpack_from('<I', header.raw, 60)[0]
                    sections = struct.unpack_from('<H', header.raw, pe + 6)[0]
                    optional = struct.unpack_from('<H', header.raw, pe + 20)[0]
                    first = pe + 24 + optional
                    for index in range(min(sections, 32)):
                        offset = first + 40 * index
                        virtual_size, rva = struct.unpack_from('<II', header.raw, offset + 8)
                        flags = struct.unpack_from('<I', header.raw, offset + 36)[0]
                        if flags & 0x40000000 and not flags & 0xA0000000:
                            readonly.append((base + rva, base + rva + virtual_size))
        pointers = [struct.unpack_from('<Q', raw, offset)[0] for offset in (128, 136, 184, 192)]
        pointers.extend(
            value for (value,) in struct.iter_unpack('<Q', stack.raw[: read.value // 8 * 8])
        )
        for pointer in pointers:
            if any(start <= pointer < end for start, end in readonly):
                text = ctypes.create_string_buffer(192)
                count = ctypes.c_size_t()
                if kernel.ReadProcessMemory(
                    info.process, pointer, text, len(text), ctypes.byref(count)
                ):
                    value = text.raw.split(b'\0')[0]
                    if 5 <= len(value) < 192 and all(32 <= byte < 127 for byte in value):
                        value = value.decode('ascii')
                        if value not in literals:
                            literals.append(value)
            if len(literals) >= 16:
                break
        result = {
            'readonly_literals': literals,
            'instruction': image_for(rip),
            'stack_modules': frames[:40],
            'module_count': len(images),
        }
        result['return_rax_sample'] = hex(struct.unpack_from('<Q', raw, 120)[0])
        objects = {}
        for register, offset in (('rbx', 144), ('rbp', 160), ('rsi', 168), ('rdi', 176)):
            pointer = struct.unpack_from('<Q', raw, offset)[0]
            slot = ctypes.c_uint64()
            count = ctypes.c_size_t()
            if kernel.ReadProcessMemory(
                info.process, pointer, ctypes.byref(slot), 8, ctypes.byref(count)
            ) and any(start <= slot.value < end for start, end in readonly):
                functions = (ctypes.c_uint64 * 8)()
                if kernel.ReadProcessMemory(
                    info.process,
                    slot.value,
                    functions,
                    ctypes.sizeof(functions),
                    ctypes.byref(count),
                ):
                    mapped = [image_for(value) for value in functions]
                    if sum(value is not None for value in mapped) >= 3:
                        objects[register] = mapped
        result['readonly_vtable_targets'] = objects
        types = {}
        for register, offset in (('rbx', 144), ('rbp', 160), ('rsi', 168), ('rdi', 176)):
            pointer = struct.unpack_from('<Q', raw, offset)[0]
            slot = ctypes.c_uint64()
            count = ctypes.c_size_t()
            if not kernel.ReadProcessMemory(
                info.process, pointer, ctypes.byref(slot), 8, ctypes.byref(count)
            ):
                continue
            if not any(start <= slot.value < end for start, end in readonly):
                continue
            locator = ctypes.c_uint64()
            if not kernel.ReadProcessMemory(
                info.process, slot.value - 8, ctypes.byref(locator), 8, ctypes.byref(count)
            ):
                continue
            descriptor = ctypes.create_string_buffer(24)
            if not kernel.ReadProcessMemory(
                info.process, locator.value, descriptor, 24, ctypes.byref(count)
            ):
                continue
            signature, _, _, type_rva, _, self_rva = struct.unpack('<6I', descriptor.raw)
            if signature != 1:
                continue
            base = locator.value - self_rva
            label = ctypes.create_string_buffer(192)
            if kernel.ReadProcessMemory(
                info.process, base + type_rva + 16, label, len(label), ctypes.byref(count)
            ):
                text = label.raw.split(b'\0')[0]
                if text.startswith(b'.?A') and all(32 <= byte < 127 for byte in text):
                    types[register] = text.decode('ascii')
        result['readonly_object_types'] = types
        if 'NtRaiseHardError' in str(result['instruction']):
            result['volatile_r10_sample'] = hex(struct.unpack_from('<Q', raw, 200)[0] & 0xFFFFFFFF)
            result['parameter_count'] = struct.unpack_from('<Q', raw, 136)[0]
        return result
    finally:
        if not stopped_by_original_debug_event:
            assert kernel.ResumeThread(info.thread) == 1, ctypes.get_last_error()
