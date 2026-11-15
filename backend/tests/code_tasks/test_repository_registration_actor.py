"""The registration actor selects durable accepted work in its owner thread."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from backend.app.code_tasks.repository_acceptance import accept_repository_operation
from backend.app.code_tasks.repository_git_dispatch import (
    ObservationGitDispatch,
    RegistrationGitDispatch,
)
from backend.app.code_tasks.repository_git_runner import (
    RegistrationReadLimits,
    RepositoryRegistrationRun,
)
from backend.app.code_tasks.repository_observation_publish import start_repository_observation
from backend.app.code_tasks.repository_registration import start_repository_registration
from backend.app.code_tasks.repository_registration_actor import RepositoryRegistrationActor
from backend.app.infrastructure.guard_controller_binding import bind_backend_controller
from backend.app.infrastructure.idempotency import Idempotency
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal, LaunchOutcomeUnknown
from backend.app.infrastructure.windows_private_package import create_private_package
from backend.app.shared.command_execution import operation_time
from backend.tests.code_tasks.test_repository_acceptance import request, runtime
from backend.tests.infrastructure.test_v20_command_http import package


def test_actor_selects_oldest_pending_and_does_not_restart_started_operations(runtime):
    binding = bind_backend_controller(runtime.commands().process_lock, 'a' * 64)
    private_root = create_private_package(runtime.database.path.parent / 'registration-actor')
    with LaunchJournal(private_root) as journal:
        actor = RepositoryRegistrationActor(
            runtime,
            binding,
            journal,
            private_roots=(private_root,),
            limits=RegistrationReadLimits(4096, 4096, 256, 32768, 4096, 5),
        )
        assert actor.run_next(None, cancelled=lambda: False) is None
        original, later = [
            accept_repository_operation(runtime, request())['data']['operation_id']
            for _ in range(2)
        ]
        assert actor._next_operation() == (original, RepositoryRegistrationRun)
        assert actor.run_next(None, cancelled=lambda: True) is None
        assert actor._next_operation() == (original, RepositoryRegistrationRun)
        start_repository_registration(runtime, original)
        assert actor._next_operation() == (later, RepositoryRegistrationRun)
        with ThreadPoolExecutor(max_workers=1) as other:
            result = other.submit(actor.run_next, None, cancelled=lambda: True)
            with pytest.raises(LaunchOutcomeUnknown, match='ACTOR_THREAD_DIFFERS'):
                result.result(timeout=5)
        actor.close()
        with pytest.raises(LaunchOutcomeUnknown, match='ACTOR_CLOSED'):
            actor.run_next(None, cancelled=lambda: True)


@pytest.mark.parametrize('refresh', [False, True])
@pytest.mark.parametrize('reserved', [False, True])
def test_startup_without_original_dispatch_preserves_receipt_and_needs_no_guard(
    runtime, refresh, reserved
):
    if refresh:
        with runtime.database.transaction(write=True) as connection:
            connection.execute(
                'INSERT INTO code_repositories VALUES(1,?,?,?,?,?)',
                ('owned fixture', r'C:\fixture', r'C:\fixture\.git', 'sha1', operation_time(None)),
            )
    original = request(1 if refresh else None)
    receipt = accept_repository_operation(runtime, original)
    operation_id = receipt['data']['operation_id']
    start = start_repository_observation if refresh else start_repository_registration
    start(runtime, operation_id)
    lock = runtime.commands().process_lock
    private_root = create_private_package(runtime.database.path.with_suffix('.restart'))
    with LaunchJournal(private_root) as journal:
        previous = bind_backend_controller(lock, 'a' * 64)
        if reserved:
            dispatch_type = ObservationGitDispatch if refresh else RegistrationGitDispatch
            dispatch = dispatch_type(runtime, None, previous, journal)
            dispatch.reserve(operation_id)
            dispatch.close()
        with runtime.database.transaction() as connection:
            external_identity = connection.execute(
                'SELECT external_identity FROM code_operation_steps WHERE operation_id=? AND step_no=1',
                (operation_id,),
            ).fetchone()[0]
        assert (external_identity is not None) == reserved
        lock.release()
        lock.acquire()
        executor = Idempotency(runtime.database, lock)
        runtime = SimpleNamespace(database=runtime.database, commands=lambda: executor)
        binding = bind_backend_controller(lock, 'a' * 64)
        assert previous.owner_epoch != binding.owner_epoch
        actor = RepositoryRegistrationActor(
            runtime,
            binding,
            journal,
            private_roots=(private_root,),
            limits=RegistrationReadLimits(4096, 4096, 256, 32768, 4096, 5),
        )
        assert not actor.has_work()
        assert actor.run_next(None, cancelled=lambda: False) is None
        actor.close()

    with runtime.database.transaction() as connection:
        saved = connection.execute(
            'SELECT status,failure_code FROM code_operations WHERE id=?', (operation_id,)
        ).fetchone()
        assert tuple(saved) == ('UNKNOWN', 'EXTERNAL_RESULT_UNKNOWN')
        steps = connection.execute(
            'SELECT status,external_identity,result_ref FROM code_operation_steps '
            'WHERE operation_id=? ORDER BY step_no',
            (operation_id,),
        )
        assert [tuple(step) for step in steps] == [
            ('UNKNOWN', external_identity, None),
            ('PENDING', None, None),
        ]
    assert accept_repository_operation(runtime, original) == receipt


def test_worker_reopens_connection_and_cleans_original_before_next_take(monkeypatch, tmp_path):
    from contextlib import contextmanager

    from backend.app.code_tasks import repository_registration_worker as service

    opened, closed, calls = [], [], []
    installation = service.RegistrationInstallation(
        'a' * 64,
        'test-sid',
        tmp_path / 'guard.exe',
        1,
        'b' * 64,
        tmp_path,
        (),
        RegistrationReadLimits(4096, 4096, 256, 32768, 4096, 5),
    )
    worker = service.RepositoryRegistrationWorker(None, installation)

    @contextmanager
    def connection(given, program):
        assert given is installation
        token = len(opened) + 1
        opened.append(token)
        try:
            yield token
        finally:
            closed.append(token)

    class Actor:
        cleanup_required = False

        def has_work(self):
            return True

        def run_next(self, frames, *, cancelled):
            calls.append(('take', frames))
            assert not self.cleanup_required and not cancelled()
            if frames == 1:
                self.cleanup_required = True
                error = LaunchOutcomeUnknown('CREATE_REPLY_UNKNOWN')
                error.retained_owner = self
                raise error
            assert frames == 3
            worker._stop.set()

        def reconcile_cleanup(self, frames, *, timeout_ms, cancelled):
            assert frames == 2 and closed == [1] and not cancelled()
            calls.append(('cleanup', frames))
            self.cleanup_required = False

    monkeypatch.setattr(service, '_frames', connection)
    monkeypatch.setattr(service, 'QUEUE_RECHECK_SECONDS', 0)
    worker._serve(Actor(), None)
    assert opened == closed == [1, 2, 3]
    assert calls == [('take', 1), ('cleanup', 2), ('take', 3)]
