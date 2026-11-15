"""Pinned scope compiler boundaries on real NTFS; no executor or OS admission claim."""

import re
from copy import deepcopy
from dataclasses import replace

import pytest

from backend.app.code_tasks.task_native_policy import (
    NativePolicyCompilationError,
    compile_managed_native_policy,
)
from backend.app.infrastructure.managed_read_scopes import BASIS, WORKSPACE
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.windows_local_paths import LocalPathGuard
from backend.tests.code_tasks.test_execution_profile_content import body


def checkpoint():
    pass


@pytest.fixture
def inputs(tmp_path):
    root = tmp_path / 'instance'
    root.mkdir()
    identities = {}
    for name in ('workspace', 'basis'):
        path = root / name
        path.mkdir()
        with LocalPathGuard(path, directory=True) as guard:
            identities[name] = guard.verify()
    profile = body()
    profile['capture_rules']['secret_policy_ref'] = 'CONTENT20-SECRETS-1'
    scope = {
        'read_roots': [WORKSPACE, BASIS],
        'write_workspace_only': True,
        'allowed_command_ids': [],
        'network_targets': [],
        'model_profile_refs': ['deepseek-v2'],
        'allow_local_delivery': False,
        'limits': deepcopy(profile['limits']),
    }
    return profile, scope, identities


def compile_inputs(inputs, **overrides):
    profile, scope, identities = inputs
    return compile_managed_native_policy(
        profile,
        scope,
        agent='walle-code',
        workspace=identities['workspace'],
        basis=identities['basis'],
        checkpoint=overrides.get('checkpoint', checkpoint),
    )


def matches(value, pattern):
    # Source-derived offline evaluator for the emitted subset. Fixed native
    # runtime compatibility still needs separate evidence, not this Python port.
    pattern = re.escape(pattern.replace('\\', '/')).replace(r'\*', '.*').replace(r'\?', '.')
    return re.fullmatch(pattern, value.replace('\\', '/'), re.IGNORECASE | re.DOTALL) is not None


def action(policy, permission, path, previous=()):
    for row in reversed([*previous, *policy.permission()]):
        if matches(permission, row['permission']) and matches(path, row['pattern']):
            return row['action']
    return 'ask'


@pytest.mark.parametrize('permission', ['read', 'edit'])
@pytest.mark.parametrize(
    'path',
    [
        'src/main.py',
        'src/deep/file.tsx',
        '空 格/说明.md',
        '',
        '.',
    ],
)
def test_managed_product_paths_are_available(inputs, permission, path):
    result = compile_inputs(inputs)
    assert action(result.policy, permission, path) == 'allow'


@pytest.mark.parametrize('permission', ['read', 'edit'])
@pytest.mark.parametrize(
    'path',
    [
        '..',
        '../private/key',
        '../basis-old/design.md',
        '/private/key',
        'C:/private/key',
        r'D:\private\key',
        '//server/share/key',
        '.git',
        '.git/config',
        'src/.git/config',
        'src/.git',
        '../basis/../private/key',
        'src/../private/key',
        'src/..',
    ],
)
def test_parent_absolute_drive_git_and_noncanonical_paths_remain_denied(inputs, permission, path):
    assert action(compile_inputs(inputs).policy, permission, path) == 'deny'


@pytest.mark.parametrize('path', ['../basis', '../basis/main.md', r'..\basis\deep\design.md'])
def test_fixed_basis_is_read_only_and_has_a_separate_external_directory_gate(inputs, path):
    result = compile_inputs(inputs)
    assert action(result.policy, 'read', path) == 'allow'
    assert action(result.policy, 'edit', path) == 'deny'
    basis = inputs[2]['basis'].canonical_path.replace('\\', '/')
    assert action(result.policy, 'external_directory', basis + '/*') == 'allow'
    assert action(result.policy, 'external_directory', basis + '/deep/*') == 'allow'
    assert action(result.policy, 'external_directory', basis + '-other/*') == 'deny'


@pytest.mark.parametrize('permission', ['bash', 'webfetch', 'websearch', 'glob', 'grep', 'task'])
def test_uncompiled_tool_command_and_network_authority_is_never_implied(inputs, permission):
    assert action(compile_inputs(inputs).policy, permission, '*') == 'deny'


def test_removing_basis_covers_all_previous_wildcards_without_empty_patch(inputs):
    inputs[1]['read_roots'] = [WORKSPACE]
    result = compile_inputs(inputs)
    previous = [{'permission': '*', 'pattern': '*', 'action': 'allow'}]
    assert action(result.policy, 'read', '../basis/main.md', previous) == 'deny'
    assert action(result.policy, 'read', 'main.py', previous) == 'allow'
    assert action(result.policy, 'external_directory', '*', previous) == 'deny'
    assert action(result.policy, 'bash', '*', previous) == 'deny'
    assert result.policy.permission()[0] == {
        'permission': '*',
        'pattern': '*',
        'action': 'deny',
    }


def test_compilation_is_deterministic_detached_and_evidence_contains_no_host_paths(inputs):
    first = compile_inputs(inputs)
    inputs[1]['read_roots'].reverse()
    second = compile_inputs(inputs)
    assert first.policy == second.policy
    assert first.read_roots == second.read_roots
    # Approval array order is retained in the exact scope digest.
    assert first.scope_sha256 != second.scope_sha256
    exposed = first.evidence()
    assert all('canonical_path' not in key for key in exposed)
    assert inputs[2]['workspace'].canonical_path not in str(exposed)
    assert inputs[2]['basis'].canonical_path not in str(exposed)
    exposed['read_roots'].clear()
    assert len(first.evidence()['read_roots']) == 2
    detached = first.policy.permission()
    detached[0]['action'] = 'allow'
    assert first.policy.permission()[0]['action'] == 'deny'


@pytest.mark.parametrize('defect', ['no-workspace', 'unknown-root', 'command', 'network', 'limits'])
def test_unsupported_grants_fail_before_directory_io(inputs, monkeypatch, defect):
    scope = inputs[1]
    if defect == 'no-workspace':
        scope['read_roots'] = [BASIS]
    elif defect == 'unknown-root':
        scope['read_roots'].append('arbitrary-host-root')
    elif defect == 'command':
        # Also absent from profile; no command substitution or silent removal.
        scope['allowed_command_ids'] = ['arbitrary-command']
    elif defect == 'network':
        scope['network_targets'] = ['arbitrary-network']
    elif defect == 'limits':
        scope['limits']['max_model_requests'] += 1

    def forbidden(*args, **kwargs):
        raise AssertionError('Unsupported scope must fail before native path IO')

    monkeypatch.setattr('backend.app.code_tasks.task_native_policy.LocalPathGuard', forbidden)
    with pytest.raises(NativePolicyCompilationError):
        compile_inputs(inputs)


@pytest.mark.parametrize('role', ['workspace', 'basis'])
def test_wrong_physical_identity_is_never_rebound_from_the_current_path(inputs, role):
    identities = inputs[2]
    identities[role] = replace(identities[role], file_id='0' * 32)
    with pytest.raises(NativePolicyCompilationError, match='IDENTITIES_DIFFER'):
        compile_inputs(inputs)


@pytest.mark.parametrize(
    'defect', ['role', 'parent', 'volume', 'same-object', 'not-directory', 'filesystem']
)
def test_only_current_instance_sibling_directory_roles_can_be_compiled(inputs, defect):
    identities = inputs[2]
    basis = identities['basis']
    if defect == 'role':
        basis = replace(basis, canonical_path=basis.canonical_path + '-other')
    elif defect == 'parent':
        basis = replace(
            basis, canonical_path=basis.canonical_path.replace('instance', 'other-instance')
        )
    elif defect == 'volume':
        basis = replace(basis, volume_serial='0' * 16)
    elif defect == 'same-object':
        basis = replace(basis, file_id=identities['workspace'].file_id)
    elif defect == 'not-directory':
        basis = replace(basis, is_directory=False)
    elif defect == 'filesystem':
        basis = replace(basis, filesystem='FAT32')
    identities['basis'] = basis
    with pytest.raises(NativePolicyCompilationError):
        compile_inputs(inputs)


@pytest.mark.parametrize('stop_at', [1, 2, 3, 4])
def test_stop_is_checked_before_and_during_physical_binding(inputs, stop_at):
    calls = 0

    def stopped():
        nonlocal calls
        calls += 1
        if calls == stop_at:
            raise TaskExecutionError('STOP_REQUESTED')

    with pytest.raises(TaskExecutionError, match='STOP_REQUESTED'):
        compile_inputs(inputs, checkpoint=stopped)
    assert calls == stop_at


@pytest.mark.parametrize(
    'field',
    [
        'protocol_version',
        'resource_sha256',
        'profile_sha256',
        'authorization_scope_sha256',
        'read_roots',
        'workspace_sha256',
        'basis_sha256',
        'agent',
        'permission_sha256',
    ],
)
def test_retained_target_evidence_cannot_change_its_bound_fields(inputs, field):
    from dataclasses import asdict

    from backend.app.code_tasks.execution_profile_content import parse_execution_profile_content
    from backend.app.code_tasks.task_native_policy import validate_managed_policy_evidence
    from backend.app.shared.http_boundary import HTTP_REQUEST_BYTES

    compiled = compile_inputs(inputs)
    proof = compiled.evidence()
    proof[field] = [] if field == 'read_roots' else 'changed'
    profile = parse_execution_profile_content(inputs[0], max_input_bytes=HTTP_REQUEST_BYTES).value()
    with pytest.raises(NativePolicyCompilationError):
        validate_managed_policy_evidence(
            proof, profile, inputs[1], asdict(inputs[2]['workspace']), 'walle-code'
        )


@pytest.mark.parametrize('agent', [None, True, 1, [], {}, '', ' walle-code', 'walle-code '])
def test_retained_agent_cannot_validate_itself_with_a_malformed_expected_value(inputs, agent):
    from dataclasses import asdict

    from backend.app.code_tasks.task_native_policy import validate_managed_policy_evidence

    proof = compile_inputs(inputs).evidence()
    proof['agent'] = agent
    with pytest.raises(NativePolicyCompilationError, match='EVIDENCE_AGENT_REQUIRED'):
        validate_managed_policy_evidence(
            proof, inputs[0], inputs[1], asdict(inputs[2]['workspace']), agent
        )


@pytest.mark.parametrize('basis', [True, False])
def test_complete_retained_evidence_has_the_exact_compiled_origin(inputs, basis):
    from dataclasses import asdict

    from backend.app.code_tasks.execution_profile_content import parse_execution_profile_content
    from backend.app.code_tasks.task_native_policy import validate_managed_policy_evidence
    from backend.app.shared.http_boundary import HTTP_REQUEST_BYTES

    if not basis:
        inputs[1]['read_roots'] = [WORKSPACE]
    proof = compile_inputs(inputs).evidence()
    profile = parse_execution_profile_content(inputs[0], max_input_bytes=HTTP_REQUEST_BYTES).value()
    assert (
        validate_managed_policy_evidence(
            proof, profile, inputs[1], asdict(inputs[2]['workspace']), 'walle-code'
        )
        == proof
    )
