"""Finite, non-secret SCM diagnostics; never execution or cleanup evidence."""

from dataclasses import dataclass
from enum import IntEnum

from .process_lock import ProcessAlreadyRunning

SERVICE_SPECIFIC_ERROR = 1066
_DIAGNOSTIC_PREFIX = 0xD0000000
_LEGACY_STAGE_PREFIX = 0x57000000


class GuardFailureStage(IntEnum):
    SERVICE_START = 1
    SYSTEM_IDENTITY = 2
    DEPLOYMENT_SOURCE = 3
    DEPLOYMENT_CONTRACT = 4
    BACKEND_SOURCE = 5
    BACKEND_CONTRACT = 6
    TASK_PROGRAM = 7
    RUNTIME_ROOT = 8
    TASK_NETWORK = 9
    CHECK_PROGRAMS = 10
    PRIVATE_JOURNAL = 11
    CONTROLLER_RECORDS = 12
    CONTROL_HOST = 13
    SERVICE_LOOP = 14
    SHUTDOWN = 15
    SERVICE_STATUS = 16
    SERVICE_CONTROL = 17
    SERVICE_HEARTBEAT = 18
    SERVICE_CALLBACK = 19
    STOP_STATUS = 20
    JOURNAL_DIRECTORY_SECURITY = 21
    JOURNAL_LOCK_CREATION = 22
    JOURNAL_LOCK_SECURITY = 23
    JOURNAL_LOCK_ACQUISITION = 24
    JOURNAL_OWNERSHIP_CHECK = 25
    JOURNAL_PRIOR_NONCES = 26


class GuardFailureReason(IntEnum):
    UNSPECIFIED = 0
    PACKAGE_OWNER_OR_DACL_DIFFERS = 1
    PACKAGE_DACL_MUST_BE_PROTECTED = 2
    PACKAGE_DACL_MUST_ONLY_ALLOW_OPERATOR = 3
    PACKAGE_OPERATOR_ACCESS_DIFFERS = 4
    PACKAGE_DACL_INHERITANCE_DIFFERS = 5
    PACKAGE_OPERATOR_CHANGED = 6
    PACKAGE_SECURITY_UNAVAILABLE = 7
    PACKAGE_ACE_UNAVAILABLE = 8
    OPERATOR_THREAD_TOKEN_UNVERIFIED = 9
    OPERATOR_TOKEN_UNAVAILABLE = 10
    OPERATOR_TOKEN_UNVERIFIED = 11
    OPERATOR_IDENTITY_UNAVAILABLE = 12
    GUARD_JOURNAL_NOT_OPEN = 13
    GUARD_JOURNAL_ALREADY_OPEN = 14
    ORIGINAL_LOCK_OCCUPIED = 15
    NATIVE_FILE_ERROR = 16
    INTERNAL_ATTRIBUTE_ERROR = 17
    INTERNAL_TYPE_ERROR = 18
    INTERNAL_IMPORT_ERROR = 19
    INTERNAL_VALUE_ERROR = 20
    UNKNOWN_INTERNAL_FAILURE = 21
    GUARD_STATE_CAPACITY_EXHAUSTED = 22
    GUARD_STATE_FILENAME_INVALID = 23
    GUARD_STATE_TOO_LARGE = 24
    GUARD_STATE_SCOPE_INVALID = 25
    GUARD_STATE_FILENAME_DIFFERS = 26
    PATH_HANDLE_UNAVAILABLE = 27
    FILE_IDENTITY_CHANGED = 28
    PATH_TYPE_DIFFERS = 29


def _error_chain(error):
    seen = set()
    current = error
    for _ in range(4):
        if current is None or id(current) in seen:
            return
        seen.add(id(current))
        yield current
        current = getattr(current, '__cause__', None)


def _native_error(error):
    for current in _error_chain(error):
        value = getattr(current, 'native_error', None)
        if value is None and isinstance(current, OSError):
            value = getattr(current, 'winerror', None)
        if type(value) is int and 1 <= value <= 65535:
            return value
    return None


def _failure_reason(error):
    if error is None:
        return GuardFailureReason.UNSPECIFIED
    for current in _error_chain(error):
        arguments = getattr(current, 'args', ())
        message = arguments[0] if type(arguments) is tuple and len(arguments) == 1 else None
        for value in (getattr(current, 'code', None), getattr(current, 'reason', None), message):
            if type(value) is str and len(value) <= 128:
                matched = GuardFailureReason.__members__.get(value)
                if matched is not None:
                    return matched
        if isinstance(current, ProcessAlreadyRunning):
            return GuardFailureReason.ORIGINAL_LOCK_OCCUPIED
    known = (
        (AttributeError, GuardFailureReason.INTERNAL_ATTRIBUTE_ERROR),
        (TypeError, GuardFailureReason.INTERNAL_TYPE_ERROR),
        (ImportError, GuardFailureReason.INTERNAL_IMPORT_ERROR),
        (ValueError, GuardFailureReason.INTERNAL_VALUE_ERROR),
        (OSError, GuardFailureReason.NATIVE_FILE_ERROR),
    )
    for error_type, reason in known:
        if isinstance(error, error_type):
            return reason
    return GuardFailureReason.UNKNOWN_INTERNAL_FAILURE


@dataclass(frozen=True)
class GuardServiceDiagnostic:
    stage: GuardFailureStage
    native_error: int | None = None
    reason: GuardFailureReason = GuardFailureReason.UNSPECIFIED

    def __post_init__(self):
        if type(self.stage) is not GuardFailureStage:
            raise ValueError('GUARD_DIAGNOSTIC_STAGE_INVALID')
        if type(self.reason) is not GuardFailureReason:
            raise ValueError('GUARD_DIAGNOSTIC_REASON_INVALID')
        if self.native_error is not None and (
            type(self.native_error) is not int or not 1 <= self.native_error <= 65535
        ):
            raise ValueError('GUARD_DIAGNOSTIC_NATIVE_ERROR_INVALID')

    @property
    def service_exit_code(self):
        return (
            _DIAGNOSTIC_PREFIX
            | (self.stage.value << 23)
            | (self.reason.value << 16)
            | (self.native_error or 0)
        )


def diagnostic_for_failure(error, stage):
    retained = getattr(error, 'guard_diagnostic', None)
    if type(retained) is GuardServiceDiagnostic:
        return retained
    return GuardServiceDiagnostic(stage, _native_error(error), _failure_reason(error))


def decode_service_diagnostic(win32_exit_code, service_exit_code):
    if (
        type(win32_exit_code) is not int
        or win32_exit_code != SERVICE_SPECIFIC_ERROR
        or type(service_exit_code) is not int
        or not 0 <= service_exit_code <= 0xFFFFFFFF
    ):
        return None
    if service_exit_code & 0xF0000000 == _DIAGNOSTIC_PREFIX:
        stage_value = (service_exit_code >> 23) & 0x1F
        reason_value = (service_exit_code >> 16) & 0x7F
    elif service_exit_code & 0xFF000000 == _LEGACY_STAGE_PREFIX:
        stage_value = (service_exit_code >> 16) & 0xFF
        if stage_value > 20:
            return None
        reason_value = 0
    else:
        return None
    try:
        stage = GuardFailureStage(stage_value)
        reason = GuardFailureReason(reason_value)
    except ValueError:
        return None
    return GuardServiceDiagnostic(stage, (service_exit_code & 0xFFFF) or None, reason)
