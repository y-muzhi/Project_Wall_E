"""Execution configuration invariants; fixtures are not registered runtime proof."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib

import pytest

from backend.app.code_tasks.execution_profile_content import LIMITS, parse_execution_profile_content
from backend.app.infrastructure.git_bundle import SOURCE_COMMIT, VERSION
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.shared.validation import InvalidInput, MAX_SAFE_INTEGER


def body():
    binding = {
        'native_model_id': 'walle-code',
        'purpose': 'CODE',
        'model_profile_ref': 'deepseek-v2',
        'model_snapshot_ref': 'test-only-snapshot',
        'price_version_id': 1,
        'input_cap_tokens': 1000,
        'context_cap_tokens': 2000,
        'output_cap_tokens': 100,
        'admission_ref': 'test-only-admission',
    }
    return {
        'executor': {
            'version': '1.19.5',
            'binary_ref': 'test-executor',
            'adapter_contract_version': 'test-adapter',
            'runtime_bundle_ref': 'test-runtime',
            'configuration_policy_version': 'OC20-CONFIG-1',
            'runtime_policy_version': 'WIN20-ISOLATION-1',
        },
        'git': {
            'version': VERSION,
            'binary_ref': 'test-git',
            'runtime_bundle_ref': 'test-git-runtime',
            'source_commit': SOURCE_COMMIT,
            'protocol_version': 'GIT20-LOCAL-1',
        },
        'models': {
            'primary_profile_ref': 'deepseek-v2',
            'auxiliary_profile_refs': [],
            'protocol_version': 'OC20-MODEL-1',
            'bindings': [
                binding,
                {**binding, 'native_model_id': 'walle-compaction', 'purpose': 'COMPACTION'},
            ],
        },
        'environment': {
            'python_ref': None,
            'node_ref': None,
            'package_manager_refs': [],
            'secret_refs': [],
        },
        'commands': [],
        'capture_rules': {
            'content_policy_version': 'CONTENT20-STORE-1',
            'product_include_paths': ['.'],
            'nonproduct_exclude_paths': [],
            'new_file_mode': '100644',
            'secret_policy_ref': 'test-secret-policy',
        },
        'delivery': None,
        'check_set_version_id': 1,
        'limits': {name: 100 for name in LIMITS},
        'capability_evidence_refs': [],
    }


def command():
    return {
        'command_id': 'test-command',
        'executable_ref': 'test-node',
        'argument_template': ['--test'],
        'working_directory': '.',
        'purpose': 'CHECK',
        'timeout_seconds': 30,
        'network_scope_ref': None,
    }


def delivery():
    return {
        'author_name': '作者',
        'author_email': 'author@example.test',
        'committer_name': '提交者',
        'committer_email': 'committer@example.test',
        'message_template': '任务 {task_id}\r\n候选 {candidate_id}\r\n',
    }


def parse(value):
    return parse_execution_profile_content(value, max_input_bytes=1024 * 1024)


def test_detached_immutable_content_and_original_labels_no_fallback():
    value = body()
    value['commands'] = [command()]
    value['delivery'] = delivery()
    original = deepcopy(value)
    content = parse(value)
    expected = deepcopy(original)
    expected['delivery']['message_template'] = '任务 {task_id}\n候选 {candidate_id}\n'
    assert content.value() == expected
    assert content.sha256 == hashlib.sha256(canonical_input(expected).encode()).hexdigest()
    value['models']['bindings'][0]['input_cap_tokens'] = 1
    result = content.value()
    result['commands'][0]['argument_template'].append('changed')
    assert content.value() == expected
    assert original['delivery']['message_template'].endswith('\r\n')
    with pytest.raises(FrozenInstanceError):
        content._encoded = b'{}'


@pytest.mark.parametrize('field', tuple(body()))
@pytest.mark.parametrize('mode', ['missing', 'null', 'unknown'])
def test_exact_required_fields(field, mode):
    value = body()
    if mode == 'missing':
        del value[field]
    elif mode == 'null':
        if field == 'delivery':
            return
        value[field] = None
    else:
        value[field + '_override'] = value[field]
    with pytest.raises(InvalidInput):
        parse(value)


@pytest.mark.parametrize('name', LIMITS)
@pytest.mark.parametrize('invalid', [0, -1, True, 1.5, '10', MAX_SAFE_INTEGER + 1])
def test_all_limits_are_positive_safe_integers(name, invalid):
    value = body()
    value['limits'][name] = invalid
    with pytest.raises(InvalidInput):
        parse(value)


def test_window_cap_and_independent_content_limits():
    value = body()
    value['limits']['max_delivery_window_seconds'] = 300
    value['limits']['max_file_bytes'] = 1000
    assert parse(value).value()['limits']['max_file_bytes'] == 1000
    value['limits']['max_delivery_window_seconds'] = 301
    with pytest.raises(InvalidInput):
        parse(value)


@pytest.mark.parametrize(
    ('field', 'name'),
    [
        ('executor', 'version'),
        ('executor', 'configuration_policy_version'),
        ('executor', 'runtime_policy_version'),
        ('git', 'version'),
        ('git', 'source_commit'),
        ('git', 'protocol_version'),
        ('models', 'protocol_version'),
        ('capture_rules', 'content_policy_version'),
    ],
)
def test_fixed_versions_no_latest(field, name):
    value = body()
    value[field][name] = 'latest'
    with pytest.raises(InvalidInput):
        parse(value)


@pytest.mark.parametrize(
    'change',
    [
        'missing',
        'duplicate',
        'purpose',
        'unknown-profile',
        'undeclared-aux',
        'output',
        'unsafe-price',
    ],
)
def test_model_bindings_are_explicit_and_cannot_expand_output(change):
    value = body()
    bindings = value['models']['bindings']
    if change == 'missing':
        bindings.pop()
    elif change == 'duplicate':
        bindings[1] = deepcopy(bindings[0])
    elif change == 'purpose':
        bindings[1]['purpose'] = 'CODE'
    elif change == 'unknown-profile':
        value['models']['primary_profile_ref'] = 'fallback'
    elif change == 'undeclared-aux':
        bindings[1]['model_profile_ref'] = 'doubao-v1'
    elif change == 'output':
        bindings[1]['output_cap_tokens'] = 101
    else:
        bindings[0]['price_version_id'] = True
    with pytest.raises(InvalidInput):
        parse(value)


def test_auxiliary_requires_explicit_existing_profile_and_code_keeps_primary():
    value = body()
    value['models']['auxiliary_profile_refs'] = ['doubao-v1']
    value['models']['bindings'][1]['model_profile_ref'] = 'doubao-v1'
    assert parse(value).value()['models'] == value['models']
    value['models']['bindings'][0]['model_profile_ref'] = 'doubao-v1'
    with pytest.raises(InvalidInput):
        parse(value)


@pytest.mark.parametrize(
    'path', ['../outside', '/tmp', 'C:/tmp', '.git/config', 'folder/../other', 'folder\\file']
)
def test_command_directory_must_be_managed_relative_path(path):
    value = body()
    value['commands'] = [{**command(), 'working_directory': path}]
    with pytest.raises(InvalidInput):
        parse(value)


@pytest.mark.parametrize('change', ['CONTROL_GIT', 'duplicate', 'shell', 'extra'])
def test_command_structure_cannot_be_replaced_by_free_shell(change):
    value = body()
    value['commands'] = [command()]
    if change == 'CONTROL_GIT':
        value['commands'][0]['purpose'] = change
    elif change == 'duplicate':
        value['commands'].append(command())
    elif change == 'shell':
        value['commands'][0]['argument_template'] = 'cmd /c arbitrary'
    else:
        value['commands'][0]['shell'] = True
    with pytest.raises(InvalidInput):
        parse(value)


@pytest.mark.parametrize(
    'template',
    ['{task_id.__class__}', '{candidate_id!r}', '{task_id:04}', '{HOME}', 'WALL-E-Delivery: 1'],
)
def test_delivery_template_accepts_only_literal_documented_ids(template):
    value = body()
    value['delivery'] = {**delivery(), 'message_template': template}
    with pytest.raises(InvalidInput):
        parse(value)


@pytest.mark.parametrize('path', ['../secret', '.git/', 'AUX.txt', 'folder\\item', '/absolute'])
def test_capture_uses_shared_path_policy(path):
    value = body()
    value['capture_rules']['product_include_paths'] = [path]
    with pytest.raises(InvalidInput):
        parse(value)


@pytest.mark.parametrize(
    'field',
    [
        'capability_evidence_refs',
        'environment.secret_refs',
        'environment.package_manager_refs',
        'models.auxiliary_profile_refs',
    ],
)
def test_reference_arrays_reject_duplicates(field):
    value = body()
    parent = value
    parts = field.split('.')
    for name in parts[:-1]:
        parent = parent[name]
    parent[parts[-1]] = ['doubao-v1', 'doubao-v1']
    with pytest.raises(InvalidInput):
        parse(value)


@pytest.mark.parametrize('invalid', [float('nan'), float('inf'), '\ud800', 9007199254740992])
def test_nested_template_invalid_json_cannot_escape_validation(invalid):
    value = body()
    value['commands'] = [{**command(), 'argument_template': [invalid]}]
    with pytest.raises(InvalidInput):
        parse(value)


def test_capacity_is_utf8_bytes_and_cyclic_data_is_rejected():
    value = body()
    with pytest.raises(InvalidInput):
        parse_execution_profile_content(value, max_input_bytes=50)
    value['commands'].append(value)
    with pytest.raises(InvalidInput):
        parse(value)
