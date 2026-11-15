"""Query one registered Guard's status; never install, start, stop or repair."""

import argparse
import ctypes
import sys
from ctypes import wintypes
from pathlib import Path


def main(arguments=None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from backend.app.infrastructure.guard_service_diagnostics import decode_service_diagnostic
    from backend.app.infrastructure.windows_guard_service import guard_service_name
    from tools.windows_guard_install_service import _ServiceStatusProcess, service_api

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installation-ref', required=True)
    values = parser.parse_args(arguments)
    try:
        name = guard_service_name(values.installation_ref)
    except (TypeError, ValueError, RuntimeError):
        parser.error('An exact Guard installation reference is required')
    api = service_api()
    manager, service = None, None
    try:
        manager = api.OpenSCManagerW(None, None, 1)
        if not manager:
            raise RuntimeError('GUARD_STATUS_MANAGER_UNAVAILABLE')
        service = api.OpenServiceW(manager, name, 4)
        if not service:
            raise RuntimeError('GUARD_STATUS_SERVICE_UNAVAILABLE')
        status, size = _ServiceStatusProcess(), wintypes.DWORD()
        if not api.QueryServiceStatusEx(
            service, 0, ctypes.byref(status), ctypes.sizeof(status), ctypes.byref(size)
        ):
            raise RuntimeError('GUARD_STATUS_QUERY_UNAVAILABLE')
        if status.service_type != 16 or status.flags != 0:
            raise RuntimeError('GUARD_STATUS_PROCESS_KIND_DIFFERS')
        failure = decode_service_diagnostic(status.win32_exit_code, status.service_exit_code)
        print(
            f'GUARD_READ_ONLY_STATUS state={status.state} pid={status.pid} '
            f'win32={status.win32_exit_code} specific={status.service_exit_code} '
            f'stage={failure.stage.name if failure else "UNCLASSIFIED"} '
            f'reason={failure.reason.name if failure else "UNCLASSIFIED"} '
            f'native={failure.native_error if failure and failure.native_error else "UNAVAILABLE"}'
        )
    finally:
        errors = []
        for handle in (service, manager):
            if handle and not api.CloseServiceHandle(handle):
                errors.append('GUARD_STATUS_HANDLE_CLOSE_UNVERIFIED')
        if errors:
            raise RuntimeError(errors[0])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
