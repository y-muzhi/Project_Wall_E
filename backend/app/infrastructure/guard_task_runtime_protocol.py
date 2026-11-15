"""File readiness evidence within the original TASK PREPARE."""

from dataclasses import dataclass

from .guard_task_basis_protocol import _hex, _integer, _object
from .opencode_runtime_bundle import is_opencode_runtime_bundle_ref
from .windows_task_runtime_bundle import TaskRuntimeFilesError

RUNTIME_FILES_STATUS = 'RUNTIME_FILES'
_DIGESTS = (
    'basis_receipts_sha256',
    'workspace_tree_identity_sha256',
    'runtime_tree_identity_sha256',
    'environment_sha256',
)


@dataclass(frozen=True)
class RuntimeFilesStageResult:
    data: dict


def is_task_runtime_request(request):
    if request.action != 'PREPARE':
        return False
    value = request.input
    return value.get('run_kind') == 'TASK' and 'runtime_files_stage' in value


def decode_runtime_files_stage(request):
    if not is_task_runtime_request(request) or request.target_scope.step_no != 4:
        raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_STAGE_SCOPE_DIFFERS')
    value = _object(
        request.input,
        (
            'run_kind',
            'runtime_files_stage',
            'runtime_binding_ref',
            'prepare_input_sha256',
            'runtime_bundle_ref',
        ),
    )
    stage, reference, original, bundle = (
        value['runtime_files_stage'],
        value['runtime_binding_ref'],
        value['prepare_input_sha256'],
        value['runtime_bundle_ref'],
    )
    if (
        stage not in ('PREPARE_FILES', 'VERIFY_FILES')
        or not _hex(reference, 32)
        or not _hex(original, 64)
        or not is_opencode_runtime_bundle_ref(bundle)
    ):
        raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_STAGE_BINDING_DIFFERS')
    return stage, reference, original, bundle


def check_runtime_files_result(request, value):
    _, reference, _, bundle = decode_runtime_files_stage(request)
    _object(value, ('binding_ref', 'runtime_bundle_ref', 'runtime_member_count', *_DIGESTS))
    if (
        value['binding_ref'] != reference
        or value['runtime_bundle_ref'] != bundle
        or not _integer(value['runtime_member_count'])
        or any(not _hex(value[name], 64) for name in _DIGESTS)
    ):
        raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_STAGE_REPLY_DIFFERS')
