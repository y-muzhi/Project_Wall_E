"""The existing bounded inspection gate never delays cancellation or the deadline."""

import pytest
from backend.app.infrastructure import windows_check_driver_program as driver


def test_inspection_checks_cancellation_and_deadline_between_durable_reads(monkeypatch):
    now = [10.0]
    stopped = [False]
    durable = []
    monkeypatch.setattr(driver, 'monotonic', lambda: now[0])
    check = driver.browser_inspection_checkpoint(
        lambda: durable.append(now[0]), deadline=11, cancelled=lambda: stopped[0]
    )
    check()
    now[0] = 10.05
    check()
    assert durable == [10.0]
    stopped[0] = True
    with pytest.raises(driver.CheckResourceError, match='INTERRUPTED'):
        check()
    stopped[0] = False
    now[0] = 11
    with pytest.raises(driver.CheckResourceError, match='INTERRUPTED'):
        check()


def test_persisted_stop_is_not_reused_as_an_old_success(monkeypatch):
    now = [10.0]
    stopped = [False]
    monkeypatch.setattr(driver, 'monotonic', lambda: now[0])

    def durable():
        if stopped[0]:
            raise RuntimeError('original persisted STOP')

    check = driver.browser_inspection_checkpoint(durable, deadline=12, cancelled=lambda: False)
    check()
    stopped[0] = True
    now[0] = 10.2
    with pytest.raises(RuntimeError, match='persisted STOP'):
        check()


def test_expensive_durable_read_still_has_a_bounded_cooldown(monkeypatch):
    now = [10.0]
    calls = []
    monkeypatch.setattr(driver, 'monotonic', lambda: now[0])

    def durable():
        calls.append(now[0])
        now[0] += 0.4

    check = driver.browser_inspection_checkpoint(durable, deadline=12, cancelled=lambda: False)
    check()
    check()
    assert calls == [10.0]
    now[0] += 0.2
    check()
    assert len(calls) == 2
