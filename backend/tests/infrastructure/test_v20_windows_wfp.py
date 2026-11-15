"""WFP read-only Win32 layout, lifetime and failure paths."""

import ctypes

import pytest

from backend.app.infrastructure import windows_wfp as wfp


class Engine:
    def __init__(self, *, fail_at=None):
        self.fail_at = fail_at
        self.events = []
        self.layers = []
        self.layer_keys = []
        self.closed = False

    def FwpmEngineOpen0(self, server, auth, identity, session, target):
        assert server is None and auth == 10 and identity is None
        assert session._obj.flags == 0 and session._obj.transaction_wait_ms == 2000
        target._obj.value = 23
        self.events.append('OPEN')
        return 5 if self.fail_at == 'OPEN' else 0

    def FwpmTransactionBegin0(self, engine, flags):
        assert engine.value == 23 and flags == 1
        self.events.append('BEGIN')
        return 5 if self.fail_at == 'BEGIN' else 0

    def FwpmLayerGetByKey0(self, engine, requested, target):
        assert engine.value == 23
        index = len(self.layer_keys)
        key, fields = wfp._REQUIRED_LAYERS[index]
        assert bytes(requested._obj) == key.bytes_le
        self.layer_keys.append(key)
        self.events.append('READ')
        if self.fail_at == 'READ':
            return 5
        if self.fail_at == 'FIELD':
            fields = fields - {wfp._PACKAGE_SID}
        fields = sorted(fields)
        keys = [wfp._Guid.from_buffer_copy(field.bytes_le) for field in fields]
        observed = (wfp._Field * len(keys))(
            *(wfp._Field(ctypes.pointer(field), 0, 0) for field in keys)
        )
        row = wfp._Layer()
        row.key = requested._obj
        row.flags = 3
        row.field_count = len(keys)
        row.fields = observed
        row.id = 30 if self.fail_at == 'DUPLICATE' else 30 + index
        self.layers.append((row, observed, keys))
        ctypes.cast(target, ctypes.POINTER(ctypes.POINTER(wfp._Layer)))[0] = ctypes.pointer(row)
        return 0

    def FwpmFreeMemory0(self, allocation):
        assert allocation._obj.value
        allocation._obj.value = None
        self.events.append('FREE')

    def FwpmTransactionAbort0(self, engine):
        assert engine.value == 23
        self.events.append('ABORT')
        return 5 if self.fail_at == 'ABORT' else 0

    def FwpmEngineClose0(self, engine):
        assert engine.value == 23
        self.events.append('CLOSE')
        self.closed = self.fail_at != 'CLOSE'
        return 0 if self.closed else 5


def test_wfp_read_requires_all_six_fixed_layers(monkeypatch):
    engine = Engine()
    monkeypatch.setattr(wfp, '_api', lambda: engine)
    assert wfp.probe_wfp_ale_layers() is True
    assert len(engine.layer_keys) == len(set(engine.layer_keys)) == 6
    assert engine.events == ['OPEN', 'BEGIN'] + ['READ', 'FREE'] * 6 + ['ABORT', 'CLOSE']


@pytest.mark.parametrize(
    ('stage', 'events'),
    [
        ('OPEN', ['OPEN']),
        ('BEGIN', ['OPEN', 'BEGIN', 'CLOSE']),
        ('READ', ['OPEN', 'BEGIN', 'READ', 'ABORT', 'CLOSE']),
        ('FIELD', ['OPEN', 'BEGIN', 'READ', 'FREE', 'ABORT', 'CLOSE']),
        ('DUPLICATE', ['OPEN', 'BEGIN'] + ['READ', 'FREE'] * 6 + ['ABORT', 'CLOSE']),
        ('ABORT', ['OPEN', 'BEGIN'] + ['READ', 'FREE'] * 6 + ['ABORT', 'CLOSE']),
    ],
)
def test_wfp_refuses_incomplete_or_unverified_snapshot(monkeypatch, stage, events):
    engine = Engine(fail_at=stage)
    monkeypatch.setattr(wfp, '_api', lambda: engine)
    assert wfp.probe_wfp_ale_layers() is False
    assert engine.events == events


def test_failed_close_retains_only_original_engine_owner(monkeypatch):
    engine = Engine(fail_at='CLOSE')
    monkeypatch.setattr(wfp, '_api', lambda: engine)
    with pytest.raises(wfp.WfpObservationError, match='CLOSE_UNVERIFIED') as failure:
        wfp.probe_wfp_ale_layers()
    assert not engine.closed
    engine.fail_at = None
    failure.value.retained_owner.close()
    assert engine.closed and engine.events.count('OPEN') == 1


def test_actual_current_windows_wfp_read_only_api():
    try:
        with wfp._WfpSession() as session:
            ids = {session.read_layer(key, fields) for key, fields in wfp._REQUIRED_LAYERS}
            assert len(ids) == 6
    except wfp.WfpObservationError as error:
        # The ordinary account is intentionally not granted WFP read access.
        assert error.native_error == 5
        assert str(error) in {
            'WFP_LOCAL_ENGINE_UNAVAILABLE',
            'WFP_READ_TRANSACTION_UNAVAILABLE',
            'WFP_ALE_LAYER_UNAVAILABLE',
        }
