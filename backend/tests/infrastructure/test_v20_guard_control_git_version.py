"""Fixed Guard command inputs and the original native version probe."""

from dataclasses import replace
from uuid import uuid4

import pytest

from backend.app.infrastructure.guard_action_journal import GuardActionJournal
from backend.app.infrastructure.guard_action_records import GuardActionError
from backend.app.infrastructure.guard_control_git_actions import _run_control_git_action
from backend.app.infrastructure.guard_control_git_input import (
    ControlGitInputError,
    ObserveControlGit,
    PrepareControlGit,
    decode_control_git_action,
    version_prepare_input,
)
from backend.app.infrastructure.guard_control_git_prepare import prepare_control_git
from backend.app.infrastructure.guard_controller_binding import GuardControllerBinding
from backend.app.infrastructure.guard_request_header import GuardRequestHeader, _parse
from backend.app.infrastructure.runtime_control_git import ControlGitRegistry
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal, LaunchOutcomeUnknown
from backend.app.infrastructure.windows_controller_token import ControllerPrimaryToken
from backend.app.infrastructure.windows_private_package import create_private_package
from backend.app.infrastructure.windows_stdio import ChildStdioDescriptor, StdioBoundaryError
from backend.tests.infrastructure.test_v20_git_config_command import (
    read_peer_output,
    start_peer_capture,
)
from backend.tests.infrastructure.test_v20_guard_recovery import facts
from backend.tests.infrastructure.test_v20_windows_stdio import owned_stdio_peer, publish, wait_file
from backend.tests.requirements.test_v15_foundation import tmp_path


def wire(binding, action, data, resource=None):
    scope = binding.scope(1, 1, 'stdio-original-nonce-0001')
    return {
        **GuardRequestHeader(action, binding.owner_epoch, scope, resource, '{}').wire,
        'input': data,
    }


@pytest.fixture
def sample():
    binding = facts()[0].binding
    descriptor = ChildStdioDescriptor(
        binding.controller,
        binding.scope(1, 1, 'stdio-original-nonce-0001'),
        str(uuid4()),
        '0000000000000010',
        '0000000000000014',
        '0000000000000018',
    )
    return binding, descriptor, version_prepare_input(descriptor)


def test_version_wire_reconstructs_current_original_identity_and_scope(sample):
    binding, descriptor, data = sample
    request = _parse(wire(binding, 'PREPARE', data), binding)
    assert decode_control_git_action(request, binding) == PrepareControlGit(descriptor)
    with pytest.raises(ControlGitInputError, match='CALLER_DIFFERS'):
        decode_control_git_action(request, replace(binding, owner_epoch=str(uuid4())))


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('run_kind', 'MODEL'),
        ('command_ref', 'GIT20-CONFIG-1'),
        ('runtime_bundle_ref', 'other'),
        ('argv', ['--version']),
        ('path', 'cmd/git.exe'),
        ('pid', 9),
    ],
)
def test_unregistered_command_or_extra_caller_inputs_rejected(sample, field, value):
    binding, _, data = sample
    request = _parse(wire(binding, 'PREPARE', {**data, field: value}), binding)
    with pytest.raises(ControlGitInputError, match='COMMAND_REQUIRED'):
        decode_control_git_action(request, binding)


@pytest.mark.parametrize(
    ('change', 'error'),
    [
        ({'owner': {}}, ControlGitInputError),
        ({'io_nonce': 'arbitrary'}, StdioBoundaryError),
        ({'stdin_handle': '0000000000000014'}, StdioBoundaryError),
        ({'stderr_handle': 32}, StdioBoundaryError),
    ],
)
def test_stdio_needs_exact_fields_and_canonical_distinct_handles(sample, change, error):
    binding, _, data = sample
    data['stdio'].update(change)
    request = _parse(wire(binding, 'PREPARE', data), binding)
    with pytest.raises(error):
        decode_control_git_action(request, binding)


def test_only_original_git_mutation_observation_and_empty_mutation_input(sample):
    binding, _, _ = sample
    selector = {'controller_ref': 'b' * 64, 'owner_epoch': str(uuid4())}
    request = _parse(
        wire(binding, 'OBSERVE', {'observed_action': 'RELEASE', 'recovery': selector}), binding
    )
    assert decode_control_git_action(request, binding) == ObserveControlGit('RELEASE')
    assert request.input['recovery'] == selector
    assert request.target_scope.controller_ref == selector['controller_ref']
    for action, data in (
        ('OBSERVE', {'observed_action': 'VERIFY_MODEL_SOURCE'}),
        ('STOP', {'pid': 9}),
        ('VERIFY_MODEL_SOURCE', {}),
    ):
        request = _parse(wire(binding, action, data, 'resource-binding1'), binding)
        with pytest.raises(ControlGitInputError):
            decode_control_git_action(request, binding)


@pytest.fixture
def version_peer(tmp_path):
    yield from owned_stdio_peer(tmp_path, bound_version=True)


def test_fixed_version_prepare_holds_original_io_and_runs_actual_mingit(version_peer):
    source, descriptor, _, directory = version_peer
    epoch = (directory / 'bound-controller-epoch').read_text(encoding='ascii')
    binding = GuardControllerBinding('a' * 64, epoch, source.identity)
    scope = descriptor.scope
    assert scope == binding.scope(1, 1, 'stdio-original-nonce-0001')
    data = version_prepare_input(descriptor)
    request = _parse(wire(binding, 'PREPARE', data), binding)
    package = create_private_package(directory / 'version-guard-journal')
    with (
        LaunchJournal(package) as journal,
        ControllerPrimaryToken(source, expected=source.identity) as token,
    ):
        actions = GuardActionJournal(journal)
        registry = ControlGitRegistry(journal, token, controller_ref=binding.controller_ref)
        try:
            record = prepare_control_git(request, binding, actions, registry)
            assert record.phase == 'ACKNOWLEDGED'
            assert record.result['binding_ref'] == record.allocated_binding_ref
            assert record.result['guard_run_ref'] == registry.guard_run_ref
            assert prepare_control_git(request, binding, actions, registry) == record
            changed = version_prepare_input(replace(descriptor, io_nonce=str(uuid4())))
            with pytest.raises(GuardActionError, match='INPUT_CONFLICT'):
                prepare_control_git(
                    _parse(wire(binding, 'PREPARE', changed), binding), binding, actions, registry
                )
            publish(directory / 'copy-ack.json', record.result['stdio_binding'])
            wait_file(directory / 'copy-released.json')
            start_peer_capture(directory)

            def action(name, data=None, resource=record.allocated_binding_ref):
                request = _parse(wire(binding, name, data or {}, resource), binding)
                return _run_control_git_action(request, binding, registry)

            with pytest.raises(LaunchOutcomeUnknown, match='STOP_UNVERIFIED'):
                action('RELEASE')
            assert actions.find(scope, 'RELEASE') is None
            created = action('CREATE_SUSPENDED')
            assert created.phase == 'ACKNOWLEDGED'
            assert created.result['native']['job_ref'] == record.allocated_binding_ref
            assert action('CREATE_SUSPENDED') == created
            root = registry._entry(scope).root
            observed = action('OBSERVE', {'observed_action': 'CREATE_SUSPENDED'})
            assert observed['action_phase'] == 'ACKNOWLEDGED'
            assert observed['resource']['observation']['state'] == 'RUNNING'
            assert observed['resource']['fence']['resume_state'] == 'NONE'
            resumed = action('RESUME')
            assert resumed.result['native']['fence']['resume_state'] == 'ACKNOWLEDGED'
            assert action('RESUME') == resumed
            assert root._kernel.WaitForSingleObject(root._info.process, 8000) == 0
            assert root.observe().exit_code == 0
            output = read_peer_output(directory)
            assert output['STDOUT'].strip() == b'git version 2.56.0.windows.4'
            assert output['STDERR'] == b''
            assert output['progress']['stdout_eof'] and output['progress']['stderr_eof']
            stopped = action('STOP')
            assert stopped.result['native']['phase'] == 'STOP_REQUESTED'
            assert stopped.result['native']['fence']['stop_closed']
            assert action('STOP') == stopped
            released = action('RELEASE')
            assert released.result['native']['cleanup_verified']
            assert released.result['native']['preparation']['handles_released']
            assert action('RELEASE') == released
            observed = action('OBSERVE', {'observed_action': 'RELEASE'})
            assert observed['preparation']['handles_released']
            assert observed['resource']['native_handles_released']
            assert observed['action_phase'] == 'ACKNOWLEDGED'
            assert registry._entry(scope).directory.path.is_dir()
        finally:
            owner = registry._preparations.get(scope.key)
            if owner is not None and not owner.handles_released:
                registry.stop(scope)
                entry = registry._entries.get(scope.key)
                if entry is not None:
                    if entry.root is not None:
                        assert (
                            entry.root._kernel.WaitForSingleObject(entry.root._info.process, 8000)
                            == 0
                        )
                    registry.release_native_handles(scope)
                owner.close_stopped_handles()
                assert owner.handles_released
            registry.close_watch()


def test_stop_before_prepare_fences_original_nonce_without_allocating_resources(version_peer):
    source, descriptor, _, directory = version_peer
    epoch = (directory / 'bound-controller-epoch').read_text(encoding='ascii')
    binding = GuardControllerBinding('a' * 64, epoch, source.identity)
    scope = descriptor.scope
    package = create_private_package(directory / 'version-stop-journal')
    with (
        LaunchJournal(package) as journal,
        ControllerPrimaryToken(source, expected=source.identity) as token,
    ):
        actions = GuardActionJournal(journal)
        registry = ControlGitRegistry(journal, token, controller_ref=binding.controller_ref)
        try:
            observe = _parse(wire(binding, 'OBSERVE', {'observed_action': 'STOP'}), binding)
            initial = _run_control_git_action(observe, binding, registry)
            assert initial['action_phase'] == 'UNKNOWN' and initial['fence'] is None
            stop = _parse(wire(binding, 'STOP', {}), binding)
            stopped = _run_control_git_action(stop, binding, registry)
            assert stopped.phase == 'ACKNOWLEDGED'
            assert stopped.result['native']['fence']['stop_closed']
            assert _run_control_git_action(stop, binding, registry) == stopped
            prepare = _parse(wire(binding, 'PREPARE', version_prepare_input(descriptor)), binding)
            with pytest.raises(GuardActionError, match='PREPARATION_INTENT_MISSING'):
                _run_control_git_action(prepare, binding, registry)
            assert actions.find(scope, 'PREPARE') is None
            assert not registry._entries and not registry._preparations
            observed = _run_control_git_action(observe, binding, registry)
            assert observed['action_phase'] == 'ACKNOWLEDGED'
            assert observed['resource'] is None and observed['fence']['stop_closed']
        finally:
            registry.close_watch()
