"""Metadata-only stages of the original authenticated TASK PREPARE."""

import re
from dataclasses import dataclass

from backend.app.shared.validation import MAX_SAFE_INTEGER

from .windows_local_paths import FileIdentity, local_absolute_path
from .windows_stdio import _handle
from .windows_task_basis import TaskBasisTransferError

BASIS_STAGE_STATUS = 'BASIS_STAGE'
BASIS_PLAN_PART_MEMBERS = 256
# A member needs more than 128 bytes in the original 8 MiB source seal.
_MAX_PLAN_MEMBERS = 65536
_PLAN_HEADER_FIELDS = (
    'operation_id',
    'task_id',
    'workspace_id',
    'generation',
    'source_sha256',
    'document_count',
)
_STAGE_INPUTS = {
    'BEGIN': {'plan'},
    'PLAN': {'members'},
    'OFFER': {'number'},
    'PIN': {'number'},
    'CONFIRM': {'number', 'file'},
    'FINISH': set(),
    'VERIFY': set(),
}


@dataclass(frozen=True)
class BasisStageResult:
    data: dict


def basis_plan_header(plan):
    return {
        'operation_id': plan.operation_id,
        'task_id': plan.task_id,
        'workspace_id': plan.workspace_id,
        'generation': plan.generation,
        'source_sha256': plan.source_sha256,
        'document_count': len(plan.members),
    }


def basis_plan_members(members):
    return [
        {'number': spec.number, 'byte_count': spec.byte_count, 'sha256': spec.sha256}
        for spec in members
    ]


def _hex(value, length):
    return type(value) is str and re.fullmatch(f'[0-9a-f]{{{length}}}', value) is not None


def _integer(value, *, minimum=1):
    return type(value) is int and minimum <= value <= MAX_SAFE_INTEGER


def is_task_basis_request(request):
    if request.action != 'PREPARE':
        return False
    value = request.input
    return value.get('run_kind') == 'TASK' and 'basis_stage' in value


def _object(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_FIELDS_DIFFER')
    return value


def basis_file_identity(value):
    file = FileIdentity(**_object(value, FileIdentity.__dataclass_fields__))
    if (
        file.is_directory is not False
        or file.filesystem != 'NTFS'
        or not _hex(file.volume_serial, 16)
        or not _hex(file.file_id, 32)
        or type(file.canonical_path) is not str
    ):
        raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_FILE_DIFFERS')
    local_absolute_path(file.canonical_path)
    return file


def _plan_header(value):
    value = _object(value, _PLAN_HEADER_FIELDS)
    if (
        any(not _integer(value[field]) for field in _PLAN_HEADER_FIELDS[:4])
        or not _hex(value['source_sha256'], 64)
        or not _integer(value['document_count'])
        or value['document_count'] > _MAX_PLAN_MEMBERS
    ):
        raise TaskBasisTransferError('ORIGINAL_BASIS_GROUP_PLAN_REQUIRED')
    return value


def _plan_part(value):
    if type(value) is not list or not 1 <= len(value) <= BASIS_PLAN_PART_MEMBERS:
        raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_PLAN_PART_REQUIRED')
    previous = None
    for item in value:
        _object(item, ('number', 'byte_count', 'sha256'))
        number = item['number']
        if (
            not _integer(number)
            or not _integer(item['byte_count'], minimum=0)
            or not _hex(item['sha256'], 64)
            or (previous is not None and number != previous + 1)
        ):
            raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_PLAN_PART_DIFFERS')
        previous = number
    return value


def decode_basis_stage(request):
    if not is_task_basis_request(request) or request.target_scope.step_no != 4:
        raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_SCOPE_DIFFERS')
    value = _object(
        request.input,
        ('run_kind', 'basis_stage', 'basis_binding_ref', 'prepare_input_sha256', 'payload'),
    )
    stage = value['basis_stage']
    binding, original = value['basis_binding_ref'], value['prepare_input_sha256']
    if (
        type(stage) is not str
        or stage not in _STAGE_INPUTS
        or not _hex(binding, 32)
        or not _hex(original, 64)
    ):
        raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_BINDING_DIFFERS')
    payload = _object(value['payload'], _STAGE_INPUTS[stage])
    if stage == 'BEGIN':
        data = _plan_header(payload['plan'])
        if data['operation_id'] != request.target_scope.operation_id:
            raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_PLAN_DIFFERS')
    elif stage == 'PLAN':
        data = _plan_part(payload['members'])
    elif stage in ('OFFER', 'PIN', 'CONFIRM'):
        number = payload['number']
        if not _integer(number):
            raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_MEMBER_DIFFERS')
        data = (number, basis_file_identity(payload['file'])) if stage == 'CONFIRM' else number
    else:
        data = None
    return stage, binding, original, data


def check_basis_stage_result(request, value):
    stage, binding, _, data = decode_basis_stage(request)
    if type(value) is not dict or value.get('binding_ref') != binding:
        raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_REPLY_BINDING_DIFFERS')
    if stage == 'BEGIN':
        _object(value, ('binding_ref', 'plan_sha256'))
        if not _hex(value['plan_sha256'], 64):
            raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_PLAN_DIFFERS')
    elif stage == 'PLAN':
        _object(value, ('binding_ref', 'last_number'))
        if not _integer(value['last_number']) or value['last_number'] != data[-1]['number']:
            raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_PLAN_PART_DIFFERS')
    elif stage in ('OFFER', 'PIN', 'CONFIRM'):
        fields = (
            ('binding_ref', 'number', 'writer', 'file')
            if stage == 'OFFER'
            else ('binding_ref', 'number')
        )
        _object(value, fields)
        number = data[0] if stage == 'CONFIRM' else data
        if not _integer(value['number']) or value['number'] != number:
            raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_MEMBER_DIFFERS')
        if stage == 'OFFER':
            _handle(value['writer'])
            basis_file_identity(value['file'])
    else:
        _object(
            value, ('binding_ref', 'plan_sha256', 'receipts_sha256', 'document_count', 'byte_count')
        )
        if (
            not _hex(value['plan_sha256'], 64)
            or not _hex(value['receipts_sha256'], 64)
            or not _integer(value['document_count'])
            or not _integer(value['byte_count'], minimum=0)
        ):
            raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_EVIDENCE_DIFFERS')
