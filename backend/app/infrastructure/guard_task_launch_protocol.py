"""Original TASK launch intent, stdio binding and returned native facts."""

from uuid import UUID

from .guard_action_records import MUTATIONS
from .guard_task_basis_protocol import _hex, _object
from .opencode_task_launch import TaskExecutionError
from .runtime_launch_journal import TestingLaunchScope, _bytes, _decode, decode_launch_scope
from .windows_check_driver_pipe import DriverPipeBinding
from .windows_process import NativeProcessIdentity
from .windows_stdio import ChildStdioDescriptor, GuardStdioBinding, _descriptor

CONFIRM_LAUNCH = 'CONFIRM_LAUNCH_INPUT'
LAUNCH_ACTIONS = ('CREATE_SUSPENDED', 'RESUME')
STDIO_FIELDS = ('io_nonce', 'stdin_handle', 'stdout_handle', 'stderr_handle')


def launch_stdio_descriptor(request, binding):
    value = _object(request.input['stdio'], STDIO_FIELDS)
    descriptor = ChildStdioDescriptor(binding.controller, request.scope, **value)
    _descriptor(descriptor)
    return descriptor


def stdio_binding(value, scope):
    _object(value, ('owner', 'scope', 'io_nonce', 'guard_io_ref'))
    wire_scope = decode_launch_scope(value['scope'])
    owner = NativeProcessIdentity(
        **_object(value['owner'], NativeProcessIdentity.__dataclass_fields__)
    )
    nonce = value['io_nonce']
    try:
        parsed = UUID(nonce)
    except (TypeError, AttributeError, ValueError) as error:
        raise TaskExecutionError('ORIGINAL_TASK_STDIO_BINDING_DIFFERS') from error
    if (
        wire_scope != scope
        or not _hex(value['guard_io_ref'], 32)
        or parsed.version != 4
        or str(parsed) != nonce
    ):
        raise TaskExecutionError('ORIGINAL_TASK_STDIO_BINDING_DIFFERS')
    return GuardStdioBinding(owner, scope, value['io_nonce'], value['guard_io_ref'])


def decode_task_launch_action(request, *, project_check=False):
    if request.target_scope.step_no not in ((3, 4) if project_check else (4,)):
        raise TaskExecutionError('ORIGINAL_TASK_LAUNCH_SCOPE_DIFFERS')
    value = request.input
    if request.recovery is not None:
        if request.action not in ('OBSERVE', 'STOP', 'RELEASE'):
            raise TaskExecutionError('ORIGINAL_TASK_LAUNCH_SCOPE_DIFFERS')
        value.pop('recovery')
    if request.action in LAUNCH_ACTIONS:
        field = 'launch_input_sha256' if request.action == 'CREATE_SUSPENDED' else 'receipt_sha256'
        _object(value, (field,))
        if not _hex(value[field], 64) or not _hex(request.binding_ref, 32):
            raise TaskExecutionError('ORIGINAL_TASK_LAUNCH_ACTION_DIFFERS')
        return value[field]
    if request.action == 'OBSERVE' and value.get('observed_action') in MUTATIONS:
        return value['observed_action']
    if request.action in ('STOP', 'RELEASE') and not value:
        return None
    raise TaskExecutionError('ORIGINAL_TASK_LAUNCH_ACTION_DIFFERS')


def check_driver_pipe_binding(value, scope):
    _object(value, ('owner', 'scope', 'nonce', 'guard_io_ref'))
    original_scope = decode_launch_scope(value['scope'])
    owner = NativeProcessIdentity(
        **_object(value['owner'], NativeProcessIdentity.__dataclass_fields__)
    )
    if original_scope != scope or type(scope) is not TestingLaunchScope:
        raise TaskExecutionError('ORIGINAL_DRIVER_RESULT_ACK_DIFFERS')
    return DriverPipeBinding(scope, owner, value['nonce'], value['guard_io_ref'])


def check_task_prepare_ack(scope, reference, value, *, run_kind='TASK'):
    fields = ('binding_ref', 'run_kind', 'launch_input_sha256', 'stdio_binding')
    if run_kind == 'CHECK_DRIVER':
        fields += ('result_pipe_binding',)
    _object(value, fields)
    if (
        value['binding_ref'] != reference
        or value['run_kind'] != run_kind
        or run_kind not in ('TASK', 'CHECK_DRIVER')
        or not _hex(value['launch_input_sha256'], 64)
    ):
        raise TaskExecutionError('ORIGINAL_TASK_PREPARE_ACK_DIFFERS')
    stdio = stdio_binding(value['stdio_binding'], scope)
    if run_kind == 'CHECK_DRIVER':
        result = check_driver_pipe_binding(value['result_pipe_binding'], scope)
        if result.owner != stdio.owner:
            raise TaskExecutionError('ORIGINAL_DRIVER_RESULT_OWNER_DIFFERS')
    return stdio


def task_launch_fence(value, scope):
    return _decode(_bytes(value), scope)


def check_task_native_result(scope, reference, value, *, run_kind='TASK'):
    _object(
        value,
        (
            'run_kind',
            'job_ref',
            'resource_ref',
            'receipt_sha256',
            'process_state',
            'fence',
            'process_identity',
        ),
    )
    if (
        value['run_kind'] != run_kind
        or run_kind not in ('TASK', 'CHECK_DRIVER')
        or run_kind == 'CHECK_DRIVER'
        and type(scope) is not TestingLaunchScope
        or value['job_ref'] != reference
        or (value['resource_ref'] is not None and not _hex(value['resource_ref'], 32))
        or (
            value['receipt_sha256'] is not None
            and (value['resource_ref'] is None or not _hex(value['receipt_sha256'], 64))
        )
        or value['process_state']
        not in ('NOT_CREATED', 'SUSPENDED', 'RUNNING', 'EXITED', 'UNKNOWN')
    ):
        raise TaskExecutionError('ORIGINAL_TASK_NATIVE_RESULT_DIFFERS')
    identity = value['process_identity']
    if identity is not None:
        process = NativeProcessIdentity(
            **_object(identity, NativeProcessIdentity.__dataclass_fields__)
        )
        if (
            type(process.pid) is not int
            or not 1 <= process.pid <= 0xFFFFFFFF
            or not _hex(process.creation_time_hex, 16)
            or process.is_appcontainer is not True
            or process.is_elevated is not False
            or process.is_lpac is False
            or type(process.appcontainer_sid) is not str
        ):
            raise TaskExecutionError('ORIGINAL_TASK_NATIVE_IDENTITY_DIFFERS')
    if value['receipt_sha256'] is not None and identity is None:
        raise TaskExecutionError('ORIGINAL_TASK_NATIVE_IDENTITY_REQUIRED')
    fence = task_launch_fence(value['fence'], scope)
    if fence.create_state == 'RESOURCE_RECORDED' and value['resource_ref'] not in (
        None,
        fence.resource_ref,
    ):
        raise TaskExecutionError('ORIGINAL_TASK_NATIVE_RESULT_DIFFERS')
    return fence
