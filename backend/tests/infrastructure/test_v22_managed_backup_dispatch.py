"""A managed backup claims its original grant only after the source is admitted."""

from contextlib import contextmanager, nullcontext
from subprocess import TimeoutExpired
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    decode,
    digest,
)
from backend.app.infrastructure.environment_host_hold import HOLD


@pytest.fixture
def capture(tmp_path, monkeypatch):
    pytest.importorskip('fcntl')
    from backend.app.management import backup_capture as backup

    control = {'control_revision': 3, 'admission': 'CLOSED', 'closed_reason': 'NORMAL_STOP'}
    scope = {key: str(uuid4()) for key in ('manager_id', 'host_id', 'registry_generation')}
    source = SimpleNamespace(
        environment_id=str(uuid4()),
        data_generation=str(uuid4()),
        deployment_id=str(uuid4()),
        project=tmp_path / 'program',
        configuration_sha256='a' * 64,
        anchor_sha256='b' * 64,
        description={'program_source': {'sha256': 'c' * 64}},
        maintenance_uid=12002,
        group=12001,
    )
    limits = {'max_database_bytes': 1000, 'max_audit_files': 5, 'max_audit_bytes': 1000}
    original = {
        **{
            key: getattr(source, key)
            for key in ('data_generation', 'deployment_id', 'configuration_sha256')
        },
        'installation_sha256': source.anchor_sha256,
        'program_sha256': source.description['program_source']['sha256'],
        'control_revision': control['control_revision'],
        'control_sha256': digest(canonical(control)),
    }
    grant = {
        **scope,
        'operation_id': str(uuid4()),
        'backup_id': str(uuid4()),
        'environment_id': source.environment_id,
        'source': original,
        'source_attachment': {'candidate_ref': str(uuid4()), 'sha256': 'd' * 64},
        'limits': limits,
    }
    policy = {
        **{key: source_value for key, source_value in original.items() if key != 'control_sha256'},
        **limits,
        'format_version': 2,
        'operation_id': grant['backup_id'],
        'environment_id': source.environment_id,
        'source_program': str(source.project),
        'source_program_sha256': original['program_sha256'],
    }
    args = SimpleNamespace(
        root=tmp_path,
        sha256='e' * 64,
        backup_operation_id=grant['operation_id'],
        capture_policy=tmp_path / 'capture.v1.json',
        capture_sha256=digest(canonical(policy)),
    )
    state = SimpleNamespace(
        events=[],
        facts={},
        operation='ACCEPTED',
        locked=False,
        admitted=False,
        frozen=False,
        wrong_policy=False,
        lost_capture_reply=False,
    )

    @contextmanager
    def locked(_):
        assert not state.locked
        state.locked = True
        try:
            yield SimpleNamespace(assert_owned=lambda: require_lock())
        finally:
            state.locked = False

    def require_lock():
        assert state.locked and state.admitted

    @contextmanager
    def admission():
        if state.frozen:
            raise EnvironmentFailure(HOLD)
        assert state.locked
        state.admitted = True
        try:
            yield
        finally:
            state.admitted = False

    def policy_input(*_):
        if state.wrong_policy:
            raise EnvironmentFailure(backup.CHANGED)
        return policy

    def invoke(_uid, _gid, command, _area, *, input_bytes=None, timeout=None):
        state.events.append(command)
        if command == '_observe-managed-backup':
            request = decode(input_bytes, backup.INVALID)
            assert request['operation_id'] == grant['operation_id']
            assert request['allow_pending'] or state.operation == 'RUNNING'
            return grant
        if command == '_claim-managed-backup':
            require_lock()
            request = decode(input_bytes, backup.INVALID)
            assert request['grant_sha256'] == digest(canonical(grant))
            state.operation = 'RUNNING'
            return grant
        assert command == 'capture-database' and timeout == 150
        assert not state.locked and not state.admitted
        if state.lost_capture_reply:
            raise TimeoutExpired(command, timeout)
        return {
            'format_version': 2,
            'status': backup.capture_status(2),
            'intent_sha256': args.capture_sha256,
            **{key: policy[key] for key in backup.CAPTURE_FIELDS},
            'cutoff_at': '2026-11-25T03:20:28.000Z',
            'asset_index': {},
            'database_artifact': {'identity': {}, 'bytes': 100, 'sha256': 'f' * 64},
        }

    def write_fact(_fd, name, fact):
        if name == backup.CAPTURE_ISSUED:
            require_lock()
        state.facts[name] = fact

    source.lock = locked
    source.host_admission = admission
    catalog = SimpleNamespace(directory=tmp_path, scope=scope, candidate=lambda *_: {})
    registry = SimpleNamespace(uid=11000, gid=11001)
    monkeypatch.setattr(backup, 'os', SimpleNamespace(geteuid=lambda: 0, fsync=lambda _: None))
    monkeypatch.setattr(backup, 'NativeEnvironmentFiles', lambda _: object())
    monkeypatch.setattr(backup, 'execution_directory', lambda *_, **__: nullcontext((tmp_path, 1)))
    monkeypatch.setattr(backup, 'manager_command', lambda action, *_: action)
    monkeypatch.setattr(backup, 'environment_command', lambda action, *_: action)
    monkeypatch.setattr(backup, 'candidate_environment', lambda *_: source)
    monkeypatch.setattr(backup, 'confirmed_control', lambda _: control)
    monkeypatch.setattr(backup, 'invoke_observer', invoke)
    monkeypatch.setattr(backup, 'capture_policy', policy_input)
    monkeypatch.setattr(backup, 'optional_fact', lambda _, name: state.facts.get(name))
    monkeypatch.setattr(backup, 'write_fact', write_fact)
    state.capture = lambda: backup.capture_managed_backup(catalog, registry, args, None)
    return state


@pytest.mark.parametrize('problem', ['wrong_policy', 'frozen'])
def test_rejection_preserves_accepted_operation_and_writes_no_dispatch(capture, problem):
    setattr(capture, problem, True)
    with pytest.raises(EnvironmentFailure):
        capture.capture()
    assert capture.operation == 'ACCEPTED'
    assert capture.events == ['_observe-managed-backup']
    assert not capture.facts


def test_original_capture_reads_while_frozen_without_claiming_or_copying_again(capture):
    receipt = capture.capture()
    assert capture.operation == 'RUNNING'
    capture.frozen = True
    assert capture.capture() == receipt
    assert capture.events == [
        '_observe-managed-backup',
        '_claim-managed-backup',
        'capture-database',
        '_observe-managed-backup',
    ]


def test_lost_capture_reply_is_uncertain_and_only_reuses_original_dispatch(capture):
    capture.lost_capture_reply = True
    with pytest.raises(EnvironmentFailure) as raised:
        capture.capture()
    assert raised.value.uncertain
    assert set(capture.facts) == {'capture-issued.v1.json'}
    capture.lost_capture_reply = False
    assert capture.capture()['status'] == 'MANAGED_BACKUP_CAPTURED'
    assert capture.events.count('_claim-managed-backup') == 1
    assert capture.events.count('capture-database') == 2
