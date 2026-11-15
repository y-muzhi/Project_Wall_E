"""Strict EXECUTION_PREPARATION facts within the original TASK PREPARE."""

from dataclasses import dataclass

from .guard_task_basis_protocol import _hex, _object
from .guard_task_launch_protocol import CONFIRM_LAUNCH, check_task_prepare_ack
from .opencode_task_launch import TaskExecutionError

EXECUTION_PREPARATION_STATUS = 'EXECUTION_PREPARATION'
_DIGESTS = ('program_sha256', 'endpoints_sha256', 'file_evidence_sha256', 'network_plan_ref')
_LAUNCH_STAGE = 'VERIFY_LAUNCH_INPUT'
_POLICY_STAGES = ('VERIFY_NETWORK_POLICY', _LAUNCH_STAGE)
_NETWORK_STAGES = ('INSTALL_NETWORK', 'VERIFY_PROFILE_NETWORK', *_POLICY_STAGES)
_PROFILE_STAGES = ('PREPARE_PROFILE', 'VERIFY_PROFILE', *_NETWORK_STAGES)
_CONTROL_STAGES = ('BIND_CONTROL_CREDENTIAL', 'VERIFY_CONTROL_CREDENTIAL')


@dataclass(frozen=True)
class ExecutionPreparationResult:
    data: dict


def is_task_execution_request(request):
    if request.action != 'PREPARE':
        return False
    value = request.input
    return value.get('run_kind') == 'TASK' and 'execution_stage' in value


def decode_task_execution_stage(request):
    if not is_task_execution_request(request) or request.target_scope.step_no != 4:
        raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_STAGE_DIFFERS')
    value = request.input
    stage = value.get('execution_stage')
    fields = ()
    if stage == 'BIND_CONTROL_CREDENTIAL':
        fields = ('control_credential',)
    if stage == CONFIRM_LAUNCH:
        fields = ('launch_input_sha256', 'stdio')
        if not _hex(value.get('launch_input_sha256'), 64):
            raise TaskExecutionError('ORIGINAL_TASK_CONFIRMATION_DIGEST_REQUIRED')
    _object(
        value,
        (
            'run_kind',
            'execution_stage',
            'execution_binding_ref',
            'prepare_input_sha256',
            *fields,
        ),
    )
    binding, digest = (
        value['execution_binding_ref'],
        value['prepare_input_sha256'],
    )
    if (
        stage
        not in (
            'PREPARE_EXECUTION',
            'VERIFY_EXECUTION',
            *_PROFILE_STAGES,
            *_CONTROL_STAGES,
            CONFIRM_LAUNCH,
        )
        or not _hex(binding, 32)
        or not _hex(digest, 64)
    ):
        raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_STAGE_DIFFERS')
    return stage, binding, digest


def check_task_execution_result(request, value):
    stage, binding, _ = decode_task_execution_stage(request)
    if stage == CONFIRM_LAUNCH:
        stdio = check_task_prepare_ack(request.scope, binding, value)
        if (
            value['launch_input_sha256'] != request.input['launch_input_sha256']
            or stdio.io_nonce != request.input['stdio']['io_nonce']
        ):
            raise TaskExecutionError('ORIGINAL_TASK_CONFIRMATION_ACK_DIFFERS')
        return
    digests = (*_DIGESTS, 'profile_sha256') if stage in _PROFILE_STAGES else _DIGESTS
    fields = ()
    if stage in _POLICY_STAGES:
        fields = ('policy_state',)
    if stage == _LAUNCH_STAGE:
        fields += ('credential_ref',)
        digests += ('credential_sha256', 'deployment_sha256', 'launch_input_sha256')
    if stage in _CONTROL_STAGES:
        fields = ('credential_ref',)
        digests = (*digests, 'credential_sha256')
    _object(value, ('binding_ref', 'job_ref', 'network_state', *digests, *fields))
    if (
        value['binding_ref'] != binding
        or not _hex(value['job_ref'], 32)
        or value['network_state'] not in ('RULES_VERIFIED', 'UNKNOWN')
        or (stage in _NETWORK_STAGES and value['network_state'] != 'RULES_VERIFIED')
        or (stage in _POLICY_STAGES and value['policy_state'] != 'NO_EXTERNAL_BYPASS_SEEN')
        or (stage in (*_CONTROL_STAGES, _LAUNCH_STAGE) and not _hex(value['credential_ref'], 32))
        or any(not _hex(value[name], 64) for name in digests)
    ):
        raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_EVIDENCE_DIFFERS')
