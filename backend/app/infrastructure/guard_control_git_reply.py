"""Wire binding for replies to one original Control Git request."""

import hashlib
import re
from dataclasses import asdict, dataclass, field

from .git_delivery_objects import DeliveryObjectIntent
from .git_ref_protocol import baseline_create
from .guard_action_records import MUTATIONS, GuardActionRecord, mutation_input_sha256
from .guard_control_git_input import decode_delivery_ancestry, decode_delivery_ref
from .guard_pipe_frames import decode_guard_payload, encode_guard_frame
from .guard_project_check_protocol import check_project_release, is_project_check_prepare
from .guard_request_header import GuardRequestHeader
from .guard_task_basis_protocol import (
    BASIS_STAGE_STATUS,
    BasisStageResult,
    check_basis_stage_result,
    is_task_basis_request,
)
from .guard_task_execution_protocol import (
    EXECUTION_PREPARATION_STATUS,
    ExecutionPreparationResult,
    check_task_execution_result,
    is_task_execution_request,
)
from .guard_task_launch_protocol import (
    check_driver_pipe_binding,
    check_task_native_result,
    check_task_prepare_ack,
)
from .guard_task_model_source import (
    MODEL_SOURCE_STATUS,
    VERIFY_MODEL_SOURCE,
    ModelSourceResult,
    check_model_source_result,
)
from .guard_task_runtime_protocol import (
    RUNTIME_FILES_STATUS,
    RuntimeFilesStageResult,
    check_runtime_files_result,
    is_task_runtime_request,
)
from .guard_task_workspace_protocol import (
    WORKSPACE_STAGE_STATUS,
    WorkspaceStageResult,
    check_workspace_stage_result,
    is_task_workspace_request,
)
from .runtime_launch_journal import LaunchOutcomeUnknown

REPLY_FIELDS = frozenset(('protocol_version', 'request_sha256', 'status', 'result'))
OBSERVATION_FIELDS = frozenset(
    (
        'observed_action',
        'action_phase',
        'binding_ref',
        'fence',
        'preparation',
        'resource',
        'acknowledgement',
        'job_activity',
        'input_sha256',
    )
)


class GuardReplyError(LaunchOutcomeUnknown):
    pass


@dataclass(frozen=True)
class GuardReply:
    status: str
    result_json: str | None = field(repr=False)

    @property
    def result(self):
        if self.result_json is None:
            return None
        return decode_guard_payload(self.result_json.encode('utf-8'))


def _request_sha256(request):
    if type(request) is not GuardRequestHeader or request.action not in (
        *MUTATIONS,
        'OBSERVE',
        VERIFY_MODEL_SOURCE,
    ):
        raise GuardReplyError('ORIGINAL_CONTROL_GIT_REQUEST_REQUIRED')
    return hashlib.sha256(encode_guard_frame(request.wire)[4:]).hexdigest()


def _binding(request, result):
    reference = result.get('binding_ref')
    if reference is not None and (
        type(reference) is not str or re.fullmatch('[a-zA-Z0-9_-]{16,128}', reference) is None
    ):
        raise GuardReplyError('ORIGINAL_GUARD_REPLY_BINDING_INVALID')
    if request.binding_ref is not None and reference != request.binding_ref:
        raise GuardReplyError('ORIGINAL_GUARD_REPLY_BINDING_DIFFERS')
    return reference


def _check_scope(request, facts):
    if type(facts) is not dict or facts.get('scope') != asdict(request.target_scope):
        raise GuardReplyError('ORIGINAL_GUARD_REPLY_SCOPE_DIFFERS')


def _check_observation(request, result):
    if (
        set(result) != OBSERVATION_FIELDS
        or result['observed_action'] != request.input.get('observed_action')
        or result['action_phase'] not in ('UNKNOWN', 'MAY_HAVE_BEEN_SENT', 'ACKNOWLEDGED')
    ):
        raise GuardReplyError('ORIGINAL_GUARD_OBSERVATION_DIFFERS')
    reference = _binding(request, result)
    digest = result['input_sha256']
    if result['action_phase'] == 'UNKNOWN':
        if digest is not None:
            raise GuardReplyError('ORIGINAL_GUARD_OBSERVED_INPUT_DIFFERS')
    elif type(digest) is not str or re.fullmatch('[0-9a-f]{64}', digest) is None:
        raise GuardReplyError('ORIGINAL_GUARD_OBSERVED_INPUT_DIFFERS')
    acknowledgement = result['acknowledgement']
    if (
        result['action_phase'] == 'ACKNOWLEDGED'
        and type(acknowledgement) is not dict
        or result['action_phase'] != 'ACKNOWLEDGED'
        and acknowledgement is not None
    ):
        raise GuardReplyError('ORIGINAL_GUARD_OBSERVED_ACK_DIFFERS')
    if acknowledgement is not None:
        _binding(request, acknowledgement)
    activity = result['job_activity']
    if activity is not None and (
        type(activity) is not dict
        or set(activity) != {'process_ids', 'assigned_count', 'complete'}
        or type(activity['complete']) is not bool
        or type(activity['assigned_count']) is not int
        or activity['assigned_count'] < 0
        or type(activity['process_ids']) is not list
        or any(
            type(pid) is not int or not 1 <= pid <= 0xFFFFFFFF for pid in activity['process_ids']
        )
        or len(set(activity['process_ids'])) != len(activity['process_ids'])
    ):
        raise GuardReplyError('ORIGINAL_GUARD_JOB_OBSERVATION_REQUIRED')
    if result['fence'] is not None:
        _check_scope(request, result['fence'])
    preparation = result['preparation']
    resource = result['resource']
    if preparation is not None and (
        type(preparation) is not dict or preparation.get('binding_ref') != reference
    ):
        raise GuardReplyError('ORIGINAL_GUARD_REPLY_PREPARATION_DIFFERS')
    if type(preparation) is dict and preparation.get('run_kind') in ('TASK', 'CHECK_DRIVER'):
        run_kind = preparation['run_kind']
        if preparation.get('launch_state') in ('PREPARING', 'CONFIRMED'):
            if (
                set(preparation) != {'binding_ref', 'run_kind', 'launch_state', 'cleanup_state'}
                or preparation['cleanup_state']
                not in ('UNKNOWN', 'NETWORK_PROFILE_RELEASED', 'COMPLETE')
                or (
                    preparation['cleanup_state'] != 'UNKNOWN'
                    and result['observed_action'] != 'RELEASE'
                )
                or reference is None
                or (resource is None) != (activity is None)
            ):
                raise GuardReplyError('ORIGINAL_TASK_LAUNCH_OBSERVATION_DIFFERS')
            if resource is not None:
                check_task_native_result(
                    request.target_scope, reference, resource, run_kind=run_kind
                )
                if result['fence'] != resource['fence']:
                    raise GuardReplyError('ORIGINAL_TASK_LAUNCH_OBSERVATION_DIFFERS')
            if acknowledgement is not None:
                if result['observed_action'] == 'PREPARE':
                    check_task_prepare_ack(
                        request.target_scope, reference, acknowledgement, run_kind=run_kind
                    )
                else:
                    _check_task_mutation(
                        request.target_scope,
                        reference,
                        result['observed_action'],
                        acknowledgement,
                        run_kind=run_kind,
                    )
            return
        if (
            run_kind != 'TASK'
            or reference is None
            or resource is not None
            or activity is not None
            or (acknowledgement is not None and acknowledgement != {'binding_ref': reference})
        ):
            raise GuardReplyError('ORIGINAL_TASK_OBSERVATION_DIFFERS')
        if set(preparation) == {'binding_ref', 'run_kind', 'network_state'}:
            if preparation['network_state'] not in ('PRESENT', 'ABSENT', 'UNKNOWN'):
                raise GuardReplyError('ORIGINAL_TASK_NETWORK_OBSERVATION_DIFFERS')
        elif (
            set(preparation) != {'binding_ref', 'run_kind', 'directory_state', 'basis_plan_sha256'}
            or preparation['directory_state'] not in ('HELD', 'UNKNOWN')
            or type(preparation['basis_plan_sha256']) is not str
            or re.fullmatch('[0-9a-f]{64}', preparation['basis_plan_sha256']) is None
        ):
            raise GuardReplyError('ORIGINAL_TASK_FILE_OBSERVATION_DIFFERS')
    if resource is not None:
        _check_scope(request, resource)
        if reference is None or resource.get('job_ref') != reference:
            raise GuardReplyError('ORIGINAL_GUARD_REPLY_BINDING_DIFFERS')


def _check_task_mutation(scope, reference, action, result, *, run_kind='TASK'):
    fields = {'binding_ref', 'native'}
    if action == 'RELEASE':
        fields.add('cleanup_ref')
        if 'check' in result:
            check_project_release(result['check'], scope, reference)
            fields.add('check')
    if (
        set(result) != fields
        or result['binding_ref'] != reference
        or (
            action == 'RELEASE'
            and (
                type(result['cleanup_ref']) is not str
                or re.fullmatch('[0-9a-f]{64}', result['cleanup_ref']) is None
            )
        )
    ):
        raise GuardReplyError('ORIGINAL_TASK_MUTATION_REPLY_DIFFERS')
    native = result['native']
    fence = check_task_native_result(scope, reference, native, run_kind=run_kind)
    state = native['process_state']
    if (
        action == 'CREATE_SUSPENDED'
        and (
            state != 'SUSPENDED'
            or fence.create_state != 'RESOURCE_RECORDED'
            or native['receipt_sha256'] is None
            or fence.stop_closed
        )
        or action == 'RESUME'
        and (
            state not in ('RUNNING', 'EXITED')
            or fence.resume_state != 'ACKNOWLEDGED'
            or native['receipt_sha256'] is None
            or fence.stop_closed
        )
        or action in ('STOP', 'RELEASE')
        and (state not in ('NOT_CREATED', 'EXITED') or not fence.stop_closed)
    ):
        raise GuardReplyError('ORIGINAL_TASK_MUTATION_REPLY_DIFFERS')


def _check_acknowledgement(request, result):
    reference = _binding(request, result)
    if request.action == 'PREPARE':
        if is_project_check_prepare(request):
            run_kind = request.input['run_kind']
            stdio = check_task_prepare_ack(request.scope, reference, result, run_kind=run_kind)
            if run_kind == 'CHECK_DRIVER':
                driver = check_driver_pipe_binding(result['result_pipe_binding'], request.scope)
                if driver.nonce != request.input['result_pipe']['nonce']:
                    raise GuardReplyError('ORIGINAL_DRIVER_RESULT_REPLY_DIFFERS')
            if stdio.io_nonce != request.input['stdio']['io_nonce']:
                raise GuardReplyError('ORIGINAL_GUARD_REPLY_IO_DIFFERS')
            return
        fields = {'binding_ref', 'guard_run_ref', 'stdio_binding', 'native_receipt'}
        export = request.input.get('config_export')
        if export is not None:
            fields.add('config_export')
            expected = {name: export[name] for name in ('file', 'sha256', 'byte_count')}
            if result.get('config_export') != expected:
                raise GuardReplyError('ORIGINAL_GUARD_REPLY_CONFIG_EXPORT_DIFFERS')
        metadata = request.input.get('metadata')
        if metadata is not None:
            fields.add('metadata_source')
            expected = {
                'command_ref': request.input['command_ref'],
                'config_output_sha256': metadata['config_facts']['output_sha256'],
                **{
                    name: metadata[name]
                    for name in ('location_sha256', 'metadata_sha256', 'config_nonce')
                },
            }
            baseline = request.input.get('baseline')
            if baseline is not None:
                intent = baseline_create(
                    baseline['snapshot_id'],
                    baseline['commit_oid'],
                    format=metadata['config_facts']['object_format'],
                )
                expected['ref_intent_sha256'] = intent.input_sha256
            delivery = request.input.get('delivery_ref')
            if delivery is not None:
                intent, reflog = decode_delivery_ref(
                    delivery, metadata['config_facts']['object_format']
                )
                expected['ref_intent_sha256'] = intent.input_sha256
                expected['reflog_sha256'] = reflog.digest
            target = request.input.get('delivery_object')
            if target is not None:
                expected['object_intent_sha256'] = DeliveryObjectIntent(**target).digest
            ancestry = request.input.get('ancestry')
            if ancestry is not None:
                query = decode_delivery_ancestry(
                    ancestry, metadata['config_facts']['object_format']
                )
                expected['ancestry_sha256'] = query.digest
            target_ref = request.input.get('target_ref')
            if target_ref is not None:
                expected['target_ref'] = target_ref
            if result.get('metadata_source') != expected:
                raise GuardReplyError('ORIGINAL_GUARD_REPLY_METADATA_SOURCE_DIFFERS')
        content = request.input.get('content_source')
        if content is not None:
            fields.add('content_source')
            if result.get('content_source') != content['intent']:
                raise GuardReplyError('ORIGINAL_GUARD_REPLY_CONTENT_SOURCE_DIFFERS')
        if (
            set(result) != fields
            or reference is None
            or type(result['native_receipt']) is not dict
            or type(result['guard_run_ref']) is not str
        ):
            raise GuardReplyError('ORIGINAL_GUARD_PREPARE_REPLY_REQUIRED')
        stdio = result['stdio_binding']
        _check_scope(request, stdio)
        if stdio.get('io_nonce') != request.input['stdio']['io_nonce']:
            raise GuardReplyError('ORIGINAL_GUARD_REPLY_IO_DIFFERS')
        return
    native = result.get('native')
    if type(native) is not dict:
        raise GuardReplyError('ORIGINAL_GUARD_MUTATION_REPLY_REQUIRED')
    if native.get('run_kind') in ('TASK', 'CHECK_DRIVER'):
        _check_task_mutation(
            request.target_scope, reference, request.action, result, run_kind=native['run_kind']
        )
        return
    if set(result) != {'binding_ref', 'native'}:
        raise GuardReplyError('ORIGINAL_GUARD_MUTATION_REPLY_REQUIRED')
    if 'scope' in native:
        _check_scope(request, native)
    if 'fence' in native:
        _check_scope(request, native['fence'])
    if 'job_ref' in native and native['job_ref'] != reference:
        raise GuardReplyError('ORIGINAL_GUARD_REPLY_BINDING_DIFFERS')


def parse_guard_control_git_reply(request, value):
    if type(value) is not dict or set(value) != REPLY_FIELDS:
        raise GuardReplyError('ORIGINAL_GUARD_REPLY_FIELDS_REQUIRED')
    value = decode_guard_payload(encode_guard_frame(value)[4:])
    if value['protocol_version'] != request.protocol or value['request_sha256'] != _request_sha256(
        request
    ):
        raise GuardReplyError('ORIGINAL_GUARD_REPLY_REQUEST_DIFFERS')
    status = value['status']
    result = value['result']
    if status == 'UNKNOWN' and result is None:
        return GuardReply(status, None)
    if type(result) is not dict:
        raise GuardReplyError('ORIGINAL_GUARD_REPLY_RESULT_REQUIRED')
    if is_task_basis_request(request):
        if status != BASIS_STAGE_STATUS:
            raise GuardReplyError('ORIGINAL_BASIS_STAGE_STATUS_DIFFERS')
        check_basis_stage_result(request, result)
    elif is_task_workspace_request(request):
        if status != WORKSPACE_STAGE_STATUS:
            raise GuardReplyError('ORIGINAL_WORKSPACE_STAGE_STATUS_DIFFERS')
        check_workspace_stage_result(request, result)
    elif is_task_runtime_request(request):
        if status != RUNTIME_FILES_STATUS:
            raise GuardReplyError('ORIGINAL_RUNTIME_STAGE_STATUS_DIFFERS')
        check_runtime_files_result(request, result)
    elif is_task_execution_request(request):
        if status != EXECUTION_PREPARATION_STATUS:
            raise GuardReplyError('ORIGINAL_TASK_EXECUTION_STATUS_DIFFERS')
        check_task_execution_result(request, result)
    elif request.action == VERIFY_MODEL_SOURCE and status == MODEL_SOURCE_STATUS:
        check_model_source_result(request, result)
    elif request.action == 'OBSERVE' and status == 'OBSERVED':
        _check_observation(request, result)
    elif request.action in MUTATIONS and status == 'ACKNOWLEDGED':
        _check_acknowledgement(request, result)
    else:
        raise GuardReplyError('ORIGINAL_GUARD_REPLY_STATUS_DIFFERS')
    return GuardReply(status, encode_guard_frame(result)[4:].decode('utf-8'))


def guard_control_git_reply(request, outcome):
    request_digest = _request_sha256(request)
    status, result = 'UNKNOWN', None
    if type(outcome) is GuardActionRecord:
        epoch = request.owner_epoch if request.recovery is None else request.recovery.owner_epoch
        if (
            outcome.action != request.action
            or outcome.scope != request.target_scope
            or outcome.owner_epoch != epoch
            or outcome.binding_ref != request.binding_ref
            or outcome.input_sha256 != mutation_input_sha256(request)
            or outcome.phase not in ('MAY_HAVE_BEEN_SENT', 'ACKNOWLEDGED')
        ):
            raise GuardReplyError('ORIGINAL_GUARD_REPLY_ACTION_DIFFERS')
        if outcome.phase == 'ACKNOWLEDGED':
            status, result = 'ACKNOWLEDGED', outcome.result
    elif type(outcome) is BasisStageResult:
        status, result = BASIS_STAGE_STATUS, outcome.data
    elif type(outcome) is WorkspaceStageResult:
        status, result = WORKSPACE_STAGE_STATUS, outcome.data
    elif type(outcome) is RuntimeFilesStageResult:
        status, result = RUNTIME_FILES_STATUS, outcome.data
    elif type(outcome) is ExecutionPreparationResult:
        status, result = EXECUTION_PREPARATION_STATUS, outcome.data
    elif type(outcome) is ModelSourceResult:
        status, result = MODEL_SOURCE_STATUS, outcome.data
    elif outcome is not None:
        status, result = 'OBSERVED', outcome
    reply = {
        'protocol_version': request.protocol,
        'request_sha256': request_digest,
        'status': status,
        'result': result,
    }
    parse_guard_control_git_reply(request, reply)
    return reply
