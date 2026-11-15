"""Original partial-preparation lifecycle ports, no Native execution claim."""

from contextlib import contextmanager
from threading import RLock
from types import SimpleNamespace

import pytest

from backend.app.infrastructure import runtime_control_git_preparation as prep
from backend.tests.infrastructure.test_v20_guard_action_journal import context, journal, tmp_path


@pytest.fixture
def prepared(context, monkeypatch):
    actions, journal, binding, request = context
    events = []

    class JobPort:
        def __init__(self):
            self.closed = False
            self.process_ids = ()

        def terminate_owned(self, code):
            events.append('terminate-job')
            self.process_ids = ()

        def observe_members(self):
            return SimpleNamespace(
                complete=True,
                process_ids=self.process_ids,
                assigned_count=len(self.process_ids),
            )

        def close(self):
            events.append('close-job')
            self.closed = True

    class ProgramPort:
        def close(self):
            events.append('close-program')

    class TokenPort:
        live = True
        identity = SimpleNamespace(user_sid=binding.controller.user_sid)
        _expected = binding.controller

        @contextmanager
        def creation_handle(self):
            if not self.live:
                raise RuntimeError('Original controller exited')
            try:
                yield 1
            finally:
                if not self.live:
                    raise RuntimeError('Original controller exited after allocation')

    registry = SimpleNamespace(
        _gate=RLock(), _admission_closed=False, _journal=journal, _controller=TokenPort()
    )
    start = actions.begin(request)
    owner = prep.ControlGitPreparation(registry, start)
    monkeypatch.setattr(prep, 'RESOURCE_TYPES', {'JOB': (JobPort,), 'PROGRAM': (ProgramPort,)})
    # The real class constructed its fixed slots before narrowing the port role map.
    return SimpleNamespace(
        owner=owner,
        registry=registry,
        journal=journal,
        token=registry._controller,
        start=start,
        events=events,
        Job=JobPort,
        Program=ProgramPort,
    )


def test_partial_owner_exists_before_factory_and_repeated_role_returns_original_without_reallocating(
    prepared,
):
    port = prepared
    calls = []

    def create():
        calls.append('new')
        assert port.owner.describe()['allocation_in_flight']
        return port.Job()

    job = port.owner.allocate('JOB', create)
    assert port.owner.allocate('JOB', lambda: pytest.fail('No replacement allocation')) is job
    assert calls == ['new']
    port.owner.request_stop()
    assert port.owner.verify_no_activity()
    port.owner.close_stopped_handles()
    assert job.closed and port.owner.describe()['handles_released']
    assert 'cleanup_verified' not in port.owner.describe()


def test_stop_before_first_allocation_closes_original_nonce_and_never_calls_factory(prepared):
    port = prepared
    assert port.owner.request_stop()
    with pytest.raises(prep.PreparationOwnerError, match='CLOSED'):
        port.owner.allocate('JOB', lambda: pytest.fail('No late factory'))
    assert port.journal.inspect(port.owner.scope).stop_closed
    assert port.owner.verify_no_activity()


def test_stop_during_factory_keeps_late_job_and_terminates_original_object(prepared):
    port = prepared
    job = port.Job()

    def late():
        assert not port.owner.request_stop()
        job.process_ids = (71,)
        return job

    with pytest.raises(prep.PreparationOwnerError, match='CLOSED_AFTER_ALLOCATION') as caught:
        port.owner.allocate('JOB', late)
    assert caught.value.retained_owner is port.owner
    assert port.owner._slots['JOB'].value is job
    assert port.events.count('terminate-job') >= 1
    assert port.owner.verify_no_activity()
    port.owner.close_stopped_handles()
    assert job.closed


def test_source_exit_after_constructor_return_cannot_drop_new_native_owner(prepared):
    port = prepared
    job = port.Job()

    def late_exit():
        port.token.live = False
        return job

    with pytest.raises(prep.PreparationOwnerError, match='ALLOCATION_UNVERIFIED') as caught:
        port.owner.allocate('JOB', late_exit)
    assert caught.value.retained_owner is port.owner
    assert port.owner._slots['JOB'].value is job
    port.owner.request_stop()
    port.owner.close_stopped_handles()
    assert job.closed


def test_constructor_retained_owner_is_closed_only_after_original_stop(prepared):
    port = prepared
    job = port.Job()

    def fail():
        error = RuntimeError('Original constructor cleanup unverified')
        error.retained_owner = job
        raise error

    with pytest.raises(prep.PreparationOwnerError, match='ALLOCATION_UNVERIFIED'):
        port.owner.allocate('JOB', fail)
    assert port.owner._slots['JOB'].value is job
    with pytest.raises(prep.PreparationOwnerError, match='STOP_UNVERIFIED'):
        port.owner.close_stopped_handles()
    port.owner.request_stop()
    port.owner.close_stopped_handles()
    assert job.closed


def test_unknown_constructor_outcome_is_not_no_resource_and_never_retries_factory(prepared):
    port = prepared

    def unknown():
        raise OSError('No trustworthy resource receipt')

    with pytest.raises(prep.PreparationOwnerError, match='ALLOCATION_UNVERIFIED'):
        port.owner.allocate('PROGRAM', unknown)
    assert port.owner.describe()['resource_states']['PROGRAM'] == 'UNKNOWN'
    with pytest.raises(prep.PreparationOwnerError, match='REQUIRES_OBSERVATION'):
        port.owner.allocate('PROGRAM', lambda: pytest.fail('No unknown redispatch'))
    port.owner.request_stop()
    with pytest.raises(prep.PreparationOwnerError, match='STOP_UNVERIFIED'):
        port.owner.verify_no_activity()


def test_handle_close_failure_keeps_exact_resource_for_retry(prepared):
    port = prepared
    job = port.owner.allocate('JOB', port.Job)
    port.owner.request_stop()
    calls = []
    actual = job.close

    def fail_once():
        if not calls:
            calls.append('failed')
            raise OSError('Original close failed')
        actual()

    job.close = fail_once
    with pytest.raises(OSError) as caught:
        port.owner.close_stopped_handles()
    assert caught.value.retained_owner is port.owner
    assert port.owner._slots['JOB'].value is job and not job.closed
    port.owner.close_stopped_handles()
    assert job.closed


def test_unknown_returned_type_cannot_be_treated_as_stopped_or_cleanup_success(prepared):
    port = prepared
    claimed = {'owned': True}
    with pytest.raises(prep.PreparationOwnerError, match='ALLOCATION_UNVERIFIED'):
        port.owner.allocate('PROGRAM', lambda: claimed)
    assert port.owner._slots['PROGRAM'].value is claimed
    port.owner.request_stop()
    with pytest.raises(prep.PreparationOwnerError, match='STOP_UNVERIFIED'):
        port.owner.verify_no_activity()


def test_known_objects_close_in_reverse_allocation_order_and_do_not_reopen_nonce(prepared):
    port = prepared
    port.owner.allocate('PROGRAM', port.Program)
    port.owner.allocate('JOB', port.Job)
    port.owner.request_stop()
    port.owner.close_stopped_handles()
    assert port.events[-2:] == ['close-job', 'close-program']
    assert port.journal.inspect(port.owner.scope).stop_closed
