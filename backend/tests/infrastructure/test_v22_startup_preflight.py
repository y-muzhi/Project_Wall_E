"""Ordinary startup must own the stable environment lock before inspecting SQLite."""

import asyncio
from types import SimpleNamespace

import pytest

from backend.app.guide import worker as workers
from backend.app.infrastructure import environment_ordinary as ordinary
from backend.app.infrastructure.environment_files import EnvironmentFailure


class StartupLock:
    def __init__(self, events, busy=False):
        self.events = events
        self.busy = busy
        self.owner_epoch = None

    def acquire(self):
        self.events.append('acquire')
        if self.busy:
            raise EnvironmentFailure('ENVIRONMENT_ALREADY_RUNNING')
        self.owner_epoch = 'worker'

    def assert_owned(self):
        if self.owner_epoch is None:
            raise EnvironmentFailure('ENVIRONMENT_LOCK_NOT_OWNED')

    def release(self):
        self.assert_owned()
        self.events.append('release')
        self.owner_epoch = None


@pytest.fixture
def startup(monkeypatch):
    def make(*, busy=False, failed=False, recover=True, local=False):
        events = []
        lock = StartupLock(events, busy)

        def checked(event):
            events.append(event)
            lock.assert_owned()

        def preflight():
            checked('preflight')
            if failed:
                raise EnvironmentFailure('ENVIRONMENT_BINDING_MISMATCH')

        def previous():
            checked('recover-commands')
            return 0

        def runs(*args, **options):
            checked('recover-runs')
            return {'code': 'RECOVERY_NO_CHANGE'}

        monkeypatch.setattr(
            workers,
            'Idempotency',
            lambda *args, **options: SimpleNamespace(recover_previous_process=previous),
        )
        monkeypatch.setattr(workers, 'recover_runs', runs)
        database = SimpleNamespace(preflight=preflight)
        scope = SimpleNamespace(
            database=database,
            lock=lock,
            preflight=database.preflight,
            before_recovery=lambda: checked('before-recovery'),
            recover_on_start=recover,
            recover_local_commands=local,
        )
        worker = workers.GuideWorker(
            database, ordinary=scope, catalog=SimpleNamespace(collaboration=None)
        )
        return worker, lock, events

    return make


@pytest.mark.parametrize(
    'recover,local,steps',
    (
        (True, False, ['preflight', 'before-recovery', 'recover-commands', 'recover-runs']),
        (False, True, ['preflight', 'before-recovery', 'recover-commands']),
        (False, False, ['before-recovery']),
    ),
)
def test_startup_holds_a_single_owner_through_preflight_and_recovery(
    startup, recover, local, steps
):
    worker, lock, events = startup(recover=recover, local=local)
    result = asyncio.run(worker.start())
    assert events == ['acquire', *steps]
    assert worker.started
    assert lock.owner_epoch == 'worker'
    assert result['code'] == ('RECOVERY_NO_CHANGE' if recover else 'RECOVERY_DEFERRED')
    lock.release()


def test_busy_ordinary_start_never_reads_sqlite(startup):
    worker, lock, events = startup(busy=True)
    with pytest.raises(EnvironmentFailure, match='ENVIRONMENT_ALREADY_RUNNING'):
        asyncio.run(worker.start())
    assert events == ['acquire']
    assert lock.owner_epoch is None
    assert not worker.started


def test_preflight_rejection_releases_owner_without_recovering_commands(startup):
    worker, lock, events = startup(failed=True)
    with pytest.raises(EnvironmentFailure, match='ENVIRONMENT_BINDING_MISMATCH'):
        asyncio.run(worker.start())
    assert events == ['acquire', 'preflight', 'release']
    assert lock.owner_epoch is None
    assert worker.executor is None
    assert not worker.started


def test_ordinary_preflight_entry_checks_ownership_before_inspecting_database(monkeypatch):
    observed = []
    database = object.__new__(ordinary.OrdinaryDatabase)
    database.installation = SimpleNamespace(check_hold=lambda: None)
    database.environment_lock = StartupLock(observed)
    database.data_fd = 0
    database.identity = None
    database.schema_release = None
    database.binding = None
    monkeypatch.setattr(
        ordinary, 'inspect_database', lambda *args: observed.append('read') or 'initialized'
    )
    with pytest.raises(EnvironmentFailure, match='ENVIRONMENT_LOCK_NOT_OWNED'):
        database.preflight()
    assert observed == []
