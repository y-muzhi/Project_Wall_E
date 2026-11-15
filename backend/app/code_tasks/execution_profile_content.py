"""Strict execution-version content. Registration and admission remain separate."""

import hashlib
import json
from dataclasses import dataclass, field

from backend.app.infrastructure.content_paths import ContentPathError, relative_content_path
from backend.app.infrastructure.content_selection import ContentSelection
from backend.app.infrastructure.git_bundle import SOURCE_COMMIT, VERSION
from backend.app.infrastructure.git_commit_input import (
    CommitIdentity,
    DeliveryCommitError,
    _identity,
    render_delivery_message,
)
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.model_profile import PROFILES
from backend.app.shared.validation import reject, strict_enum, strict_integer

from .check_set_content import _items, _record, _references, _text

FIELDS = (
    'executor',
    'git',
    'models',
    'environment',
    'commands',
    'capture_rules',
    'delivery',
    'check_set_version_id',
    'limits',
    'capability_evidence_refs',
)
LIMITS = (
    'max_model_requests',
    'max_output_tokens',
    'max_consecutive_failures',
    'max_active_seconds',
    'max_file_bytes',
    'max_snapshot_bytes',
    'max_snapshot_files',
    'max_capture_entries',
    'max_capture_seconds',
    'max_manifest_bytes',
    'max_git_seconds',
    'max_git_output_bytes',
    'max_delivery_window_seconds',
    'max_check_output_bytes',
    'max_check_cases',
    'max_case_steps',
    'max_case_payload_bytes',
    'query_timeout_seconds',
    'send_timeout_seconds',
    'queue_wait_seconds',
    'graceful_stop_seconds',
    'force_stop_wait_seconds',
)
EXECUTOR_FIELDS = (
    'version',
    'binary_ref',
    'adapter_contract_version',
    'runtime_bundle_ref',
    'configuration_policy_version',
    'runtime_policy_version',
)
GIT_FIELDS = ('version', 'binary_ref', 'runtime_bundle_ref', 'source_commit', 'protocol_version')
BINDING_FIELDS = (
    'native_model_id',
    'purpose',
    'model_profile_ref',
    'model_snapshot_ref',
    'price_version_id',
    'input_cap_tokens',
    'context_cap_tokens',
    'output_cap_tokens',
    'admission_ref',
)
COMMAND_FIELDS = (
    'command_id',
    'executable_ref',
    'argument_template',
    'working_directory',
    'purpose',
    'timeout_seconds',
    'network_scope_ref',
)


def fixed(value, name, expected):
    return strict_enum(value, name, (expected,))


def text_record(value, name, fields, maximum):
    source = _record(value, name, fields)
    return {key: _text(source[key], name + '.' + key, maximum) for key in fields}


def models(value, maximum, output_limit):
    source = _record(
        value,
        'models',
        ('primary_profile_ref', 'auxiliary_profile_refs', 'protocol_version', 'bindings'),
    )
    primary = strict_enum(source['primary_profile_ref'], 'models.primary_profile_ref', PROFILES)
    auxiliary = _references(
        source['auxiliary_profile_refs'], 'models.auxiliary_profile_refs', maximum
    )
    for ref in auxiliary:
        strict_enum(ref, 'models.auxiliary_profile_refs', PROFILES)
    if primary in auxiliary:
        reject('models.auxiliary_profile_refs', 'DUPLICATE_PARAMETER', '主模型不能重复列为辅助模型')
    seen = set()
    bindings = []
    for i, binding in enumerate(_items(source['bindings'], 'models.bindings')):
        here = f'models.bindings[{i}]'
        row = _record(binding, here, BINDING_FIELDS)
        alias = strict_enum(
            row['native_model_id'], here + '.native_model_id', ('walle-code', 'walle-compaction')
        )
        purpose = fixed(
            row['purpose'], here + '.purpose', 'CODE' if alias == 'walle-code' else 'COMPACTION'
        )
        profile = strict_enum(
            row['model_profile_ref'], here + '.model_profile_ref', (primary, *auxiliary)
        )
        if alias in seen or (alias == 'walle-code' and profile != primary):
            reject(here, 'INVALID_FORMAT', '模型别名必须唯一并关联原主模型')
        seen.add(alias)
        result = {'native_model_id': alias, 'purpose': purpose, 'model_profile_ref': profile}
        for key in ('model_snapshot_ref', 'admission_ref'):
            result[key] = _text(row[key], here + '.' + key, maximum)
        for key in (
            'price_version_id',
            'input_cap_tokens',
            'context_cap_tokens',
            'output_cap_tokens',
        ):
            result[key] = strict_integer(row[key], here + '.' + key)
        if result['output_cap_tokens'] > output_limit:
            reject(here + '.output_cap_tokens', 'OUT_OF_RANGE', '模型输出不能扩大配置上限')
        bindings.append(result)
    if seen != {'walle-code', 'walle-compaction'}:
        reject('models.bindings', 'INVALID_FORMAT', '必须明确代码与压缩两项绑定')
    return {
        'primary_profile_ref': primary,
        'auxiliary_profile_refs': auxiliary,
        'protocol_version': fixed(
            source['protocol_version'], 'models.protocol_version', 'OC20-MODEL-1'
        ),
        'bindings': bindings,
    }


def commands(value, maximum):
    result = []
    seen = set()
    for i, definition in enumerate(_items(value, 'commands')):
        here = f'commands[{i}]'
        row = _record(definition, here, COMMAND_FIELDS)
        command = {
            key: _text(row[key], here + '.' + key, maximum)
            for key in ('command_id', 'executable_ref', 'working_directory')
        }
        if command['command_id'] in seen:
            reject(here + '.command_id', 'DUPLICATE_PARAMETER', '命令身份不得重复')
        seen.add(command['command_id'])
        if command['working_directory'] != '.':
            try:
                relative_content_path(command['working_directory'])
            except ContentPathError:
                reject(here + '.working_directory', 'INVALID_FORMAT', '工作目录必须在受管根内')
        command['purpose'] = strict_enum(
            row['purpose'], here + '.purpose', ('EXECUTION', 'CHECK', 'SERVICE')
        )
        command['timeout_seconds'] = strict_integer(
            row['timeout_seconds'], here + '.timeout_seconds'
        )
        command['network_scope_ref'] = (
            None
            if row['network_scope_ref'] is None
            else _text(row['network_scope_ref'], here + '.network_scope_ref', maximum)
        )
        # Resource-specific template grammar is not a user programming API.
        # Publication must compare the entire immutable COMMAND definition.
        if type(row['argument_template']) not in (list, dict):
            reject(here + '.argument_template', 'INVALID_TYPE', '必须使用已登记参数模板')
        command['argument_template'] = json.loads(
            canonical_input({'value': row['argument_template']})
        )['value']
        result.append(command)
    return result


def git_profile(value, maximum):
    git = text_record(value, 'git', GIT_FIELDS, maximum)
    for key, expected in (
        ('version', VERSION),
        ('source_commit', SOURCE_COMMIT),
        ('protocol_version', 'GIT20-LOCAL-1'),
    ):
        fixed(git[key], 'git.' + key, expected)
    return git


def capture(value, maximum):
    source = _record(
        value,
        'capture_rules',
        (
            'content_policy_version',
            'product_include_paths',
            'nonproduct_exclude_paths',
            'new_file_mode',
            'secret_policy_ref',
        ),
    )
    fixed(
        source['content_policy_version'],
        'capture_rules.content_policy_version',
        'CONTENT20-STORE-1',
    )
    try:
        ContentSelection(
            product_include_paths=source['product_include_paths'],
            nonproduct_exclude_paths=source['nonproduct_exclude_paths'],
            new_file_mode=source['new_file_mode'],
            baseline_entries=[],
        )
    except ContentPathError:
        reject('capture_rules', 'INVALID_FORMAT', '选择规则不符合内容路径规则')
    return {
        **source,
        'secret_policy_ref': _text(
            source['secret_policy_ref'], 'capture_rules.secret_policy_ref', maximum
        ),
    }


def delivery(value):
    if value is None:
        return None
    source = _record(
        value,
        'delivery',
        ('author_name', 'author_email', 'committer_name', 'committer_email', 'message_template'),
    )
    try:
        _identity(CommitIdentity(source['author_name'], source['author_email']))
        _identity(CommitIdentity(source['committer_name'], source['committer_email']))
        render_delivery_message(source['message_template'], task_id=1, candidate_id=1)
    except (DeliveryCommitError, TypeError):
        reject('delivery', 'INVALID_FORMAT', '提交标识或消息模板不合法')
    return {
        **source,
        'message_template': source['message_template'].replace('\r\n', '\n').replace('\r', '\n'),
    }


@dataclass(frozen=True)
class ExecutionProfileContent:
    _encoded: bytes = field(repr=False)

    def value(self):
        return json.loads(self._encoded)

    @property
    def sha256(self):
        return hashlib.sha256(self._encoded).hexdigest()


def parse_execution_profile_content(value, *, max_input_bytes):
    strict_integer(max_input_bytes, 'max_input_bytes')
    source = _record(value, 'version_content', FIELDS)
    try:
        original = canonical_input(source).encode('utf-8', errors='strict')
    except (ValueError, TypeError, UnicodeError, RecursionError):
        reject('version_content', 'INVALID_FORMAT', '必须是有界有效JSON')
    if len(original) > max_input_bytes:
        reject('version_content', 'TOO_LONG', '执行配置超过容量')
    limits = _record(source['limits'], 'limits', LIMITS)
    limits = {key: strict_integer(value, 'limits.' + key) for key, value in limits.items()}
    if limits['max_delivery_window_seconds'] > 300:
        reject('limits.max_delivery_window_seconds', 'OUT_OF_RANGE', '交付窗口不能超过300秒')
    executor = text_record(source['executor'], 'executor', EXECUTOR_FIELDS, max_input_bytes)
    for key, expected in (
        ('version', '1.19.5'),
        ('configuration_policy_version', 'OC20-CONFIG-1'),
        ('runtime_policy_version', 'WIN20-ISOLATION-1'),
    ):
        fixed(executor[key], 'executor.' + key, expected)
    git = git_profile(source['git'], max_input_bytes)
    environment = _record(
        source['environment'],
        'environment',
        ('python_ref', 'node_ref', 'package_manager_refs', 'secret_refs'),
    )
    result = {
        'executor': executor,
        'git': git,
        'limits': limits,
        'models': models(source['models'], max_input_bytes, limits['max_output_tokens']),
        'environment': {
            key: None
            if environment[key] is None
            else _text(environment[key], 'environment.' + key, max_input_bytes)
            for key in ('python_ref', 'node_ref')
        },
        'commands': commands(source['commands'], max_input_bytes),
        'capture_rules': capture(source['capture_rules'], max_input_bytes),
        'delivery': delivery(source['delivery']),
        'check_set_version_id': strict_integer(
            source['check_set_version_id'], 'check_set_version_id'
        ),
        'capability_evidence_refs': _references(
            source['capability_evidence_refs'], 'capability_evidence_refs', max_input_bytes
        ),
    }
    for key in ('package_manager_refs', 'secret_refs'):
        result['environment'][key] = _references(
            environment[key], 'environment.' + key, max_input_bytes
        )
    encoded = canonical_input(result).encode('utf-8')
    if len(encoded) > max_input_bytes:
        reject('version_content', 'TOO_LONG', '执行配置超过容量')
    return ExecutionProfileContent(encoded)
