"""Actual immutable SQL binding and private records around a transport port."""

from dataclasses import asdict
from uuid import uuid4

import pytest

from backend.app.code_tasks import repository_git_dispatch as module
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.guard_control_git_input import config_prepare_input
from backend.app.infrastructure.guard_control_git_reply import GuardReply
from backend.app.infrastructure.guard_controller_binding import bind_backend_controller
from backend.app.infrastructure.guard_git_config_source import ConfigReadDescriptor
from backend.app.infrastructure.guard_pipe_frames import encode_guard_frame
from backend.app.infrastructure.guard_request_header import _parse
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal
from backend.app.infrastructure.windows_local_paths import FileIdentity
from backend.app.infrastructure.windows_private_package import create_private_package
from backend.app.infrastructure.windows_stdio import ChildStdioDescriptor
from backend.tests.code_tasks.test_repository_registration import prepared, runtime
from backend.tests.infrastructure.test_v20_command_http import package

RUN_REF = 'a' * 32
JOB_REF = 'b' * 32
PROCESS_REF = 'c' * 32


@pytest.fixture
def launch(runtime, monkeypatch):
    _, operation_id = prepared(runtime)
    binding = bind_backend_controller(runtime.commands().process_lock, 'a' * 64)
    path = create_private_package(runtime.database.path.parent / ('dispatch-' + uuid4().hex))
    with LaunchJournal(path) as journal:
        dispatcher = module.RegistrationGitDispatch(runtime, object(), binding, journal)
        original = dispatcher.reserve(operation_id)
        scope = original.scope
        stdio = ChildStdioDescriptor(
            binding.controller,
            scope,
            str(uuid4()),
            '0000000000000010',
            '0000000000000014',
            '0000000000000018',
        )
        export = ConfigReadDescriptor(
            binding.controller,
            scope,
            FileIdentity(r'C:\fixture\.git\config', 'a' * 16, 'b' * 32, False, 'NTFS'),
            'c' * 64,
            64,
            '0000000000000020',
        )

        def request(action):
            return _parse(
                {
                    'protocol_version': 'WIN20-ISOLATION-1',
                    'action': action,
                    'controller_ref': binding.controller_ref,
                    'owner_epoch': binding.owner_epoch,
                    'operation_id': operation_id,
                    'step_no': 1,
                    'nonce': scope.nonce,
                    'binding_ref': None if action == 'PREPARE' else JOB_REF,
                    'input': config_prepare_input(stdio, export) if action == 'PREPARE' else {},
                },
                binding,
            )

        sent = []

        def transport(frames, actual_binding, lock, actual, **boundary):
            assert actual_binding == binding and lock is runtime.commands().process_lock
            assert dispatcher.original(operation_id) == original
            record = dispatcher.read_action(original, actual.action, 'MAY_HAVE_BEEN_SENT')
            assert record is not None and record['result'] is None
            sent.append(actual.action)
            if actual.action == 'PREPARE':
                result = {'binding_ref': JOB_REF, 'guard_run_ref': RUN_REF}
            else:
                result = {
                    'binding_ref': JOB_REF,
                    'native': {
                        'guard_run_ref': RUN_REF,
                        'job_ref': JOB_REF,
                        'resource_ref': PROCESS_REF,
                        'original_process_identity': asdict(binding.controller),
                        'fence': {
                            'create_state': 'RESOURCE_RECORDED',
                            'resume_state': 'NONE'
                            if actual.action == 'CREATE_SUSPENDED'
                            else 'ACKNOWLEDGED',
                            'stop_closed': actual.action in ('STOP', 'RELEASE'),
                        },
                        'cleanup_verified': actual.action == 'RELEASE',
                    },
                }
            return GuardReply('ACKNOWLEDGED', encode_guard_frame(result)[4:].decode('utf-8'))

        monkeypatch.setattr(module, 'exchange_guard_control_git', transport)

        def dispatch(action):
            return dispatcher.dispatch(request(action), timeout_ms=1000, cancelled=lambda: False)

        try:
            yield operation_id, binding, original, dispatcher, sent, dispatch
        finally:
            dispatcher.close()


def test_original_scope_and_each_intent_commit_before_send_and_resume_after_saved_process(
    runtime, launch
):
    operation_id, binding, original, dispatcher, sent, dispatch = launch
    assert original.scope.operation_id == operation_id and original.scope.step_no == 1
    with runtime.database.transaction() as connection:
        identity = connection.execute(
            'SELECT external_identity FROM code_operation_steps WHERE operation_id=? AND step_no=1',
            (operation_id,),
        ).fetchone()[0]
    with pytest.raises(StorageUnavailable, match='requires observation'):
        dispatcher.reserve(operation_id)
    with pytest.raises(StorageUnavailable, match='prerequisite'):
        dispatch('CREATE_SUSPENDED')
    assert not sent
    for action in ('PREPARE', 'CREATE_SUSPENDED', 'RESUME', 'STOP', 'RELEASE'):
        dispatch(action)
    assert sent == ['PREPARE', 'CREATE_SUSPENDED', 'RESUME', 'STOP', 'RELEASE']
    created = dispatcher.read_action(original, 'CREATE_SUSPENDED', 'ACKNOWLEDGED')['result'][
        'native'
    ]
    assert created['original_process_identity']['pid'] == binding.controller.pid
    assert created['resource_ref'] == PROCESS_REF
    prepared_record = dispatcher.read_action(original, 'PREPARE', 'ACKNOWLEDGED')
    assert prepared_record['result']['guard_run_ref'] == RUN_REF
    assert prepared_record['result']['binding_ref'] == JOB_REF
    assert all(
        dispatcher.read_action(original, action, 'ACKNOWLEDGED') is not None for action in sent
    )
    with runtime.database.transaction() as connection:
        assert (
            connection.execute(
                'SELECT external_identity FROM code_operation_steps WHERE operation_id=? AND step_no=1',
                (operation_id,),
            ).fetchone()[0]
            == identity
        )
        assert connection.execute('SELECT count(*) FROM code_repositories').fetchone()[0] == 0
    with pytest.raises(StorageUnavailable, match='requires observation'):
        dispatch('RESUME')
    assert len(sent) == 5


def test_unknown_create_retains_original_intent_and_blocks_repeat_or_resume(launch, monkeypatch):
    operation_id, _, scope, dispatcher, sent, dispatch = launch
    dispatch('PREPARE')
    original = module.exchange_guard_control_git

    def lost_ack(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError('test-owned lost reply')

    monkeypatch.setattr(module, 'exchange_guard_control_git', lost_ack)
    with pytest.raises(OSError, match='lost reply'):
        dispatch('CREATE_SUSPENDED')
    with pytest.raises(StorageUnavailable, match='requires observation'):
        dispatch('CREATE_SUSPENDED')
    with pytest.raises(StorageUnavailable, match='prerequisite'):
        dispatch('RESUME')
    assert sent == ['PREPARE', 'CREATE_SUSPENDED']
    assert dispatcher.original(operation_id) == scope
    assert dispatcher.read_action(scope, 'CREATE_SUSPENDED', 'MAY_HAVE_BEEN_SENT') is not None
    assert dispatcher.read_action(scope, 'CREATE_SUSPENDED', 'ACKNOWLEDGED') is None


@pytest.mark.parametrize('matches', [True, False])
def test_original_observation_recovers_ack_without_repeating_mutation(launch, monkeypatch, matches):
    _, binding, original_scope, dispatcher, sent, dispatch = launch
    dispatch('PREPARE')
    original_transport = module.exchange_guard_control_git
    created = []

    def lose_create_reply(*args, **kwargs):
        created.append(original_transport(*args, **kwargs))
        raise OSError('test-owned lost create acknowledgement')

    monkeypatch.setattr(module, 'exchange_guard_control_git', lose_create_reply)
    with pytest.raises(OSError):
        dispatch('CREATE_SUSPENDED')
    intent = dispatcher.read_action(original_scope, 'CREATE_SUSPENDED', 'MAY_HAVE_BEEN_SENT')
    scope = original_scope.scope
    request = _parse(
        {
            'protocol_version': 'WIN20-ISOLATION-1',
            'action': 'OBSERVE',
            'controller_ref': binding.controller_ref,
            'owner_epoch': binding.owner_epoch,
            'operation_id': scope.operation_id,
            'step_no': scope.step_no,
            'nonce': scope.nonce,
            'binding_ref': JOB_REF,
            'input': {'observed_action': 'CREATE_SUSPENDED'},
        },
        binding,
    )
    observed = {
        'input_sha256': intent['input_sha256'] if matches else 'f' * 64,
        'action_phase': 'ACKNOWLEDGED',
        'acknowledgement': created[0].result,
    }
    monkeypatch.setattr(
        module,
        'exchange_guard_control_git',
        lambda *args, **kwargs: GuardReply(
            'OBSERVED', encode_guard_frame(observed)[4:].decode('utf-8')
        ),
    )
    if matches:
        dispatcher.observe(request, timeout_ms=1000, cancelled=lambda: False)
        assert (
            dispatcher.read_action(original_scope, 'CREATE_SUSPENDED', 'ACKNOWLEDGED')['result']
            == created[0].result
        )
        monkeypatch.setattr(module, 'exchange_guard_control_git', original_transport)
        dispatch('RESUME')
        assert sent == ['PREPARE', 'CREATE_SUSPENDED', 'RESUME']
    else:
        with pytest.raises(StorageUnavailable, match='observed input differs'):
            dispatcher.observe(request, timeout_ms=1000, cancelled=lambda: False)
        assert dispatcher.read_action(original_scope, 'CREATE_SUSPENDED', 'ACKNOWLEDGED') is None


@pytest.mark.parametrize('released', [False, True])
def test_validation_failure_after_prepare_requires_original_release(runtime, launch, released):
    operation_id, _, _, dispatcher, sent, dispatch = launch
    dispatch('PREPARE')
    if released:
        dispatch('STOP')
        dispatch('RELEASE')
        dispatcher.fail_validation(operation_id, 'SOURCE_CHANGED')
        assert sent == ['PREPARE', 'STOP', 'RELEASE']
    else:
        with pytest.raises(StorageUnavailable, match='cleanup remains unverified'):
            dispatcher.fail_validation(operation_id, 'SOURCE_CHANGED')
    with runtime.database.transaction() as connection:
        row = connection.execute(
            'SELECT status,failure_code FROM code_operations WHERE id=?', (operation_id,)
        ).fetchone()
        assert tuple(row) == (('FAILED', 'SOURCE_CHANGED') if released else ('RUNNING', None))
    if released:
        with pytest.raises(StorageUnavailable, match='not active'):
            dispatch('CREATE_SUSPENDED')
