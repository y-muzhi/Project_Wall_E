"""Guard-owned WFP namespace creation remains transactional and exact."""

from contextlib import contextmanager
from uuid import uuid4

import pytest

from backend.app.infrastructure import windows_wfp_namespace as ns


@pytest.mark.parametrize('case', ['create', 'existing', 'conflict', 'no-persistence'])
def test_admitted_namespace_uses_only_exact_pair_and_observes_commit(monkeypatch, case):
    events = []
    provider, sublayer = uuid4(), uuid4()
    marker = ns._marker('a' * 64, provider, sublayer)

    class Session:
        def __init__(self, *, read_only=True):
            self.read_only = read_only

        def __enter__(self):
            events.append('read-only' if self.read_only else 'write')
            return self

        def __exit__(self, *_):
            events.append('close')

        def read_layer(self, key, fields):
            assert (key, fields) in ns._REQUIRED_LAYERS
            return key.int

        def commit(self):
            assert not self.read_only
            events.append('commit')

    def observe(session, actual_provider, actual_sublayer, actual_marker, *, verify_security):
        assert (actual_provider, actual_sublayer, actual_marker) == (provider, sublayer, marker)
        assert verify_security
        events.append('observe')
        if case == 'conflict':
            raise ns.WfpObservationError('WFP_NAMESPACE_BINDING_DIFFERS')
        if case == 'no-persistence' and session.read_only:
            return False
        return case == 'existing' or 'add' in events

    @contextmanager
    def descriptor(*_):
        yield 'SYSTEM descriptor'

    def add(session, actual_provider, actual_sublayer, actual_marker, actual_descriptor):
        assert not session.read_only and actual_descriptor == 'SYSTEM descriptor'
        assert (actual_provider, actual_sublayer, actual_marker) == (provider, sublayer, marker)
        events.append('add')

    monkeypatch.setattr(ns, '_WfpSession', Session)
    monkeypatch.setattr(ns, '_observe', observe)
    monkeypatch.setattr(ns, '_add', add)
    monkeypatch.setattr(ns, '_guard_filter_descriptor', descriptor)
    monkeypatch.setattr(ns, 'current_operator_sid', lambda: ns._SYSTEM)
    monkeypatch.setattr(ns, 'security_api', lambda: (None, None))
    invoke = lambda: ns.ensure_admitted_task_wfp_namespace(
        'a' * 64, provider, sublayer, lambda: None
    )
    if case == 'conflict':
        with pytest.raises(ns.WfpObservationError, match='BINDING_DIFFERS'):
            invoke()
        assert events == ['write', 'observe', 'close']
    elif case == 'no-persistence':
        with pytest.raises(ns.WfpObservationError, match='PERSISTENCE_UNVERIFIED'):
            invoke()
        assert events == [
            'write',
            'observe',
            'add',
            'observe',
            'commit',
            'close',
            'read-only',
            'observe',
            'close',
        ]
    else:
        invoke()
        expected_write = ['write', 'observe']
        if case == 'create':
            expected_write.extend(('add', 'observe', 'commit'))
        assert events == expected_write + ['close', 'read-only', 'observe', 'close']


def test_namespace_refuses_without_system_before_opening_wfp(monkeypatch):
    monkeypatch.setattr(ns, 'current_operator_sid', lambda: 'S-1-5-32-544')
    monkeypatch.setattr(ns, '_WfpSession', lambda **_: pytest.fail('must not open WFP'))
    provider, sublayer = uuid4(), uuid4()
    with pytest.raises(ns.WfpObservationError, match='SYSTEM_REQUIRED'):
        ns.ensure_admitted_task_wfp_namespace('a' * 64, provider, sublayer, lambda: None)
