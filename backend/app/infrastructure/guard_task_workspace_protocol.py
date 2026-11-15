"""Strict workspace publication stages within the original TASK PREPARE."""

from dataclasses import dataclass

from .guard_task_basis_protocol import _hex, _object
from .windows_local_paths import FileIdentity, local_absolute_path
from .windows_stdio import _handle
from .windows_task_directories import TaskWorkspaceDestination
from .windows_task_workspace_lease import WorkspaceWriteError

WORKSPACE_STAGE_STATUS = 'WORKSPACE_STAGE'


@dataclass(frozen=True)
class WorkspaceStageResult:
    data: dict


def is_task_workspace_request(request):
    if request.action != 'PREPARE':
        return False
    value = request.input
    return value.get('run_kind') == 'TASK' and 'workspace_stage' in value


def decode_workspace_stage(request):
    if not is_task_workspace_request(request) or request.target_scope.step_no != 4:
        raise WorkspaceWriteError('ORIGINAL_WORKSPACE_STAGE_SCOPE_DIFFERS')
    value = _object(
        request.input,
        (
            'run_kind',
            'workspace_stage',
            'workspace_binding_ref',
            'prepare_input_sha256',
            'manifest_sha256',
            'payload',
        ),
    )
    stage = value['workspace_stage']
    reference, original, manifest = (
        value['workspace_binding_ref'],
        value['prepare_input_sha256'],
        value['manifest_sha256'],
    )
    if (
        stage not in ('BEGIN', 'FINISH', 'VERIFY')
        or not _hex(reference, 32)
        or not _hex(original, 64)
        or not _hex(manifest, 64)
    ):
        raise WorkspaceWriteError('ORIGINAL_WORKSPACE_STAGE_BINDING_DIFFERS')
    payload = _object(value['payload'], ('tree_identity_sha256',) if stage == 'FINISH' else ())
    tree = payload.get('tree_identity_sha256')
    if stage == 'FINISH' and not _hex(tree, 64):
        raise WorkspaceWriteError('ORIGINAL_WORKSPACE_STAGE_TREE_DIFFERS')
    return stage, reference, original, manifest, tree


def workspace_stage_destination(scope, value):
    file = FileIdentity(**_object(value['directory'], FileIdentity.__dataclass_fields__))
    nonce = value['directory_nonce']
    if (
        file.is_directory is not True
        or file.filesystem != 'NTFS'
        or not _hex(file.volume_serial, 16)
        or not _hex(file.file_id, 32)
        or not _hex(nonce, 32)
        or type(file.canonical_path) is not str
    ):
        raise WorkspaceWriteError('ORIGINAL_WORKSPACE_STAGE_DIRECTORY_DIFFERS')
    path = local_absolute_path(file.canonical_path)
    if path.name != 'workspace' or path.parent.name != 'task-' + nonce:
        raise WorkspaceWriteError('ORIGINAL_WORKSPACE_STAGE_DIRECTORY_DIFFERS')
    return TaskWorkspaceDestination(scope, value['binding_ref'], nonce, file)


def check_workspace_stage_result(request, value):
    stage, reference, _, manifest, tree = decode_workspace_stage(request)
    fields = ('binding_ref', 'manifest_sha256', 'directory_nonce', 'directory')
    fields += ('writer',) if stage == 'BEGIN' else ('tree_identity_sha256',)
    _object(value, fields)
    if value['binding_ref'] != reference or value['manifest_sha256'] != manifest:
        raise WorkspaceWriteError('ORIGINAL_WORKSPACE_STAGE_REPLY_DIFFERS')
    workspace_stage_destination(request.target_scope, value)
    if stage == 'BEGIN':
        _handle(value['writer'])
    elif not _hex(value['tree_identity_sha256'], 64) or (
        stage == 'FINISH' and value['tree_identity_sha256'] != tree
    ):
        raise WorkspaceWriteError('ORIGINAL_WORKSPACE_STAGE_TREE_DIFFERS')
