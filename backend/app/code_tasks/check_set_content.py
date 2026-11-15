"""OBJ-CODE-POLICY CheckSet content structure before resource/DB admission.

Both Coding settings and the Testing package compiler use this same validator.
Structural validity is not resource registration, readiness, coverage approval or
a Verification result; those checks require the actual original task/resources.
"""

import hashlib
import json
from dataclasses import dataclass, field

from backend.app.infrastructure.idempotency import canonical_input
from backend.app.shared.validation import (
    MAX_SAFE_INTEGER,
    object_fields,
    ordinary_text,
    raw_text,
    reject,
    strict_boolean,
    strict_enum,
    strict_integer,
)

PROTOCOL = 'CHECK20-CONTROL-1'
STAGES = ('BACKEND', 'FRONTEND', 'INTEGRATION', 'ACCEPTANCE')
CHECK_FIELDS = (
    'check_id',
    'name',
    'stages',
    'required',
    'check_kind',
    'command_id',
    'runner_ref',
    'case_pack_ref',
    'expected_exit_codes',
    'environment_refs',
    'protected_input_refs',
    'target',
    'timeout_seconds',
    'evidence_rule',
)
COVERAGE_FIELDS = ('coverage_id', 'basis_refs', 'stages', 'mode', 'check_ids', 'explanation')


def _record(value, field, fields):
    return object_fields(value, field, fields, fields)


def _items(value, field, minimum=0):
    if type(value) is not list:
        reject(field, 'INVALID_TYPE', '必须是数组')
    if len(value) < minimum:
        reject(field, 'TOO_SHORT', '至少需要一项')
    return value


def _text(value, field, maximum, *, quote=False):
    text = raw_text(value, field, 1, maximum)
    try:
        text.encode('utf-8', errors='strict')
    except UnicodeError:
        reject(field, 'INVALID_FORMAT', '必须是有效UTF-8文本')
    if '\0' in text or not text.strip():
        reject(field, 'INVALID_FORMAT', '文本不能为空白或包含空字符')
    if not quote and any(ord(char) < 32 or ord(char) == 127 for char in text):
        reject(field, 'INVALID_FORMAT', '引用不能包含控制字符')
    return text


def _ordinary(value, field, minimum, maximum):
    text = ordinary_text(value, field, minimum, maximum)
    if '\0' in text:
        reject(field, 'INVALID_FORMAT', '文本不能包含空字符')
    return text


def _references(value, field, maximum, *, minimum=0):
    values = [
        _text(item, f'{field}[{i}]', maximum)
        for i, item in enumerate(_items(value, field, minimum))
    ]
    if len(set(values)) != len(values):
        reject(field, 'DUPLICATE_PARAMETER', '引用不得重复')
    return values


def _stages(value, field, owner):
    stages = _references(value, field, 32, minimum=1)
    allowed = STAGES if owner == 'TESTING' else STAGES[:3]
    for stage in stages:
        strict_enum(stage, field, allowed)
    return stages


def _null(value, field):
    if value is not None:
        reject(field, 'INVALID_FORMAT', '此检查类型要求null')


def _target(value, field, maximum):
    fields = ('application_mode', 'external_dependency_mode', 'command_ids', 'fixture_ref')
    source = _record(value, field, fields)
    fixture = source['fixture_ref']
    return {
        'application_mode': strict_enum(
            source['application_mode'],
            field + '.application_mode',
            ('REAL_CANDIDATE', 'CONTROLLED_STUB'),
        ),
        'external_dependency_mode': strict_enum(
            source['external_dependency_mode'],
            field + '.external_dependency_mode',
            ('NONE', 'OFFLINE_STUB'),
        ),
        'command_ids': _references(
            source['command_ids'], field + '.command_ids', maximum, minimum=1
        ),
        'fixture_ref': None if fixture is None else _text(fixture, field + '.fixture_ref', maximum),
    }


def _check(value, field, owner, maximum):
    source = _record(value, field, CHECK_FIELDS)
    rule = _record(source['evidence_rule'], field + '.evidence_rule', ('kind',))
    kind = strict_enum(
        source['check_kind'], field + '.check_kind', ('PROJECT_COMMAND', 'CONTROLLED_ASSERTION')
    )
    evidence = strict_enum(
        rule['kind'],
        field + '.evidence_rule.kind',
        ('PROCESS_EXIT', 'CONTENT_INTEGRITY', 'CONTROLLED_CASES'),
    )
    result = {
        'check_id': _text(source['check_id'], field + '.check_id', maximum),
        'name': _ordinary(source['name'], field + '.name', 1, maximum),
        'stages': _stages(source['stages'], field + '.stages', owner),
        'required': strict_boolean(source['required'], field + '.required'),
        'check_kind': kind,
        'runner_ref': _text(source['runner_ref'], field + '.runner_ref', maximum),
        'environment_refs': _references(
            source['environment_refs'], field + '.environment_refs', maximum
        ),
        'protected_input_refs': _references(
            source['protected_input_refs'], field + '.protected_input_refs', maximum
        ),
        'timeout_seconds': strict_integer(source['timeout_seconds'], field + '.timeout_seconds'),
        'evidence_rule': {'kind': evidence},
    }
    if kind == 'PROJECT_COMMAND':
        result['command_id'] = _text(source['command_id'], field + '.command_id', maximum)
        exits = _items(source['expected_exit_codes'], field + '.expected_exit_codes')
        if len(exits) != 1 or type(exits[0]) is not int or exits[0] != 0:
            reject(field + '.expected_exit_codes', 'INVALID_FORMAT', '项目命令只允许[0]')
        if evidence != 'PROCESS_EXIT':
            reject(field + '.evidence_rule', 'INVALID_FORMAT', '项目命令只能证明进程退出')
        result['expected_exit_codes'] = [0]
        result['case_pack_ref'] = _null(source['case_pack_ref'], field + '.case_pack_ref')
        result['target'] = _null(source['target'], field + '.target')
    else:
        result['command_id'] = _null(source['command_id'], field + '.command_id')
        result['expected_exit_codes'] = _null(
            source['expected_exit_codes'], field + '.expected_exit_codes'
        )
        if evidence == 'CONTENT_INTEGRITY':
            result['case_pack_ref'] = _null(source['case_pack_ref'], field + '.case_pack_ref')
            result['target'] = _null(source['target'], field + '.target')
        elif evidence == 'CONTROLLED_CASES':
            result['case_pack_ref'] = _text(
                source['case_pack_ref'], field + '.case_pack_ref', maximum
            )
            result['target'] = _target(source['target'], field + '.target', maximum)
        else:
            reject(field + '.evidence_rule', 'INVALID_FORMAT', '受控断言不能采用项目退出码结论')
    return result


def _basis(value, field, maximum):
    result = []
    seen = set()
    for i, item in enumerate(_items(value, field, 1)):
        here = f'{field}[{i}]'
        item = _record(item, here, ('document_id', 'revision_id', 'quote'))
        document = strict_integer(item['document_id'], here + '.document_id')
        revision = strict_integer(item['revision_id'], here + '.revision_id')
        quote = _text(item['quote'], here + '.quote', maximum, quote=True)
        key = (document, revision, quote)
        if key in seen:
            reject(field, 'DUPLICATE_PARAMETER', '同一依据引用不得重复')
        seen.add(key)
        result.append({'document_id': document, 'revision_id': revision, 'quote': quote})
    return result


def _coverage(value, field, owner, maximum, checks):
    source = _record(value, field, COVERAGE_FIELDS)
    mode = strict_enum(source['mode'], field + '.mode', ('AUTO', 'MANUAL', 'NOT_APPLICABLE'))
    ids = _references(source['check_ids'], field + '.check_ids', maximum)
    stages = _stages(source['stages'], field + '.stages', owner)
    explanation = _ordinary(
        source['explanation'], field + '.explanation', 0 if mode == 'AUTO' else 1, maximum
    )
    if mode == 'AUTO':
        if not ids:
            reject(field + '.check_ids', 'TOO_SHORT', '自动覆盖必须关联受控功能检查')
        for identity in ids:
            if (
                identity not in checks
                or checks[identity]['evidence_rule']['kind'] != 'CONTROLLED_CASES'
            ):
                reject(field + '.check_ids', 'INVALID_FORMAT', '必须引用本版本受控功能检查')
    elif ids:
        reject(field + '.check_ids', 'INVALID_FORMAT', '人工或不适用范围不能关联自动检查')
    return {
        'coverage_id': _text(source['coverage_id'], field + '.coverage_id', maximum),
        'basis_refs': _basis(source['basis_refs'], field + '.basis_refs', maximum),
        'stages': stages,
        'mode': mode,
        'check_ids': ids,
        'explanation': explanation,
    }


@dataclass(frozen=True)
class CheckSetContent:
    owner_module: str
    _encoded: bytes = field(repr=False)

    @property
    def sha256(self):
        return hashlib.sha256(self._encoded).hexdigest()

    def value(self):
        # Return a fresh value; mutable caller changes cannot modify fixed input.
        return json.loads(self._encoded)


def parse_check_set_content(value, *, owner_module, max_input_bytes):
    owner = strict_enum(owner_module, 'owner_module', ('CODING', 'TESTING'))
    strict_integer(max_input_bytes, 'max_input_bytes', 1, MAX_SAFE_INTEGER)
    source = _record(value, 'version_content', ('protocol_version', 'items', 'coverage_plan'))
    try:
        original_size = len(canonical_input(value).encode('utf-8', errors='strict'))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        reject('version_content', 'INVALID_FORMAT', '必须是有界有效JSON')
    if original_size > max_input_bytes:
        reject('version_content', 'TOO_LONG', '检查标准超过输入限制')
    strict_enum(source['protocol_version'], 'protocol_version', (PROTOCOL,))
    items = [
        _check(item, f'items[{i}]', owner, max_input_bytes)
        for i, item in enumerate(_items(source['items'], 'items'))
    ]
    checks = {item['check_id']: item for item in items}
    if len(checks) != len(items):
        reject('items', 'DUPLICATE_PARAMETER', '检查身份不得重复')
    coverage = [
        _coverage(item, f'coverage_plan[{i}]', owner, max_input_bytes, checks)
        for i, item in enumerate(_items(source['coverage_plan'], 'coverage_plan'))
    ]
    if len({item['coverage_id'] for item in coverage}) != len(coverage):
        reject('coverage_plan', 'DUPLICATE_PARAMETER', '覆盖身份不得重复')
    result = {'protocol_version': PROTOCOL, 'items': items, 'coverage_plan': coverage}
    raw = canonical_input(result).encode('utf-8')
    if len(raw) > max_input_bytes:
        reject('version_content', 'TOO_LONG', '检查标准超过输入限制')
    return CheckSetContent(owner, raw)
