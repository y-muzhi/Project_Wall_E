"""Offline diagnostics preserve native causes and never replay a model request."""

import errno
import logging
import sqlite3

from backend.app.guide import collaboration_execution
from backend.app.guide.collaboration_execution import _storage_failure
from backend.app.infrastructure.collaboration_admission import CollaborationAdmission
from backend.app.infrastructure.database import Database, StorageUnavailable
from backend.tests.documents.test_v15_documents import workspace
from backend.tests.guide.test_v15_acceptance import accept
from backend.tests.guide.test_v15_counting import Counter, offline_gate
from backend.tests.guide.test_v15_execution import Gateway, execute
from backend.tests.requirements.test_v15_foundation import setup, tmp_path

__all__ = ['setup', 'tmp_path', 'workspace']


def diagnostics(caplog):
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == collaboration_execution.__name__
    ]


def test_real_writer_conflict_after_count_retains_code_and_prevents_chat(
    workspace, monkeypatch, caplog
):
    offline_gate(monkeypatch)
    assert accept(workspace)['code'] == 'GUIDE_ACCEPTED'
    contender = Database(workspace[0].path, busy_timeout_ms=0)

    def locked_preparation(*args, **kwargs):
        with workspace[0].transaction(write=True), contender.transaction(write=True):
            raise AssertionError('The second writer must not enter')

    monkeypatch.setattr(collaboration_execution, '_prepare', locked_preparation)
    gateway = Gateway()
    counter = Counter(['OK'])
    with caplog.at_level(logging.WARNING):
        result = execute(workspace, gateway, counter)
    assert result['code'] == 'AI_FAILED', result
    assert len(counter.calls) == 1
    assert gateway.calls == []
    entries = diagnostics(caplog)
    assert len(entries) == 1
    assert 'run=1 phase=PREPARE_MODEL_CALL' in entries[0]
    assert '"code":5,"name":"SQLITE_BUSY"' in entries[0]
    with workspace[0].transaction() as connection:
        run = connection.execute('SELECT status,error_code FROM guide_runs').fetchone()
        assert tuple(run) == ('FAILED', 'STORAGE_UNAVAILABLE')
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0


def test_admission_read_failure_after_count_retains_os_code_without_sensitive_text(
    workspace, monkeypatch, caplog
):
    offline_gate(monkeypatch)
    assert accept(workspace)['code'] == 'GUIDE_ACCEPTED'
    counter = Counter(['OK'])
    original = CollaborationAdmission.current
    secret = 'credential-and-user-body-must-never-reach-log'

    def failing_admission(self, snapshot):
        if counter.calls:
            try:
                raise PermissionError(errno.EACCES, secret, 'private-path')
            except OSError as error:
                raise StorageUnavailable(secret) from error
        return original(self, snapshot)

    monkeypatch.setattr(CollaborationAdmission, 'current', failing_admission)
    gateway = Gateway()
    with caplog.at_level(logging.WARNING):
        result = execute(workspace, gateway, counter)
    assert result['code'] == 'AI_FAILED', result
    assert len(counter.calls) == 1
    assert gateway.calls == []
    entry = diagnostics(caplog)[0]
    assert 'phase=CHECK_ADMISSION_AFTER_COUNT' in entry
    assert '"kind":"OS","errno":13' in entry
    assert secret not in caplog.text
    assert 'private-path' not in caplog.text


def test_native_code_attributes_are_bounded_and_exception_cycles_stop(caplog):
    error = sqlite3.OperationalError('secret SQL and credential')
    error.sqlite_errorcode = True
    error.sqlite_errorname = 'SQLITE_BUSY\nsecret'
    error.__cause__ = error
    with caplog.at_level(logging.WARNING):
        _storage_failure(1, 'READ_CONTEXT', error)
    entry = diagnostics(caplog)[0]
    assert 'errors=[{"kind":"SQLITE"}]' in entry
    assert 'secret' not in caplog.text


def test_failed_log_sink_does_not_replace_the_storage_failure(workspace, monkeypatch):
    offline_gate(monkeypatch)
    assert accept(workspace)['code'] == 'GUIDE_ACCEPTED'

    def fail_preparation(*args, **kwargs):
        raise StorageUnavailable('original failure')

    def fail_log(*args, **kwargs):
        raise OSError('diagnostic sink unavailable')

    monkeypatch.setattr(collaboration_execution, '_prepare', fail_preparation)
    monkeypatch.setattr(logging.getLogger(collaboration_execution.__name__), 'warning', fail_log)
    gateway = Gateway()
    result = execute(workspace, gateway, Counter(['OK']))
    assert result['code'] == 'AI_FAILED', result
    assert gateway.calls == []
    with workspace[0].transaction() as connection:
        run = connection.execute('SELECT error_code FROM guide_runs').fetchone()
        assert run[0] == 'STORAGE_UNAVAILABLE'
