"""Protect recovery generation fencing and physical resource observations."""

from contextlib import closing, nullcontext
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    digest,
    identity,
)
from backend.app.management import registry_dispatch as dispatch


def identifier():
    return str(uuid4())


def test_current_dispatch_requires_active_anchor_and_original_hold_archive(tmp_path, monkeypatch):
    root = tmp_path / 'host'
    root.mkdir()
    generation = root / 'generation'
    generation.mkdir()
    anchor = root / dispatch.ANCHOR_NAME
    anchor.write_bytes(b'current registry anchor')
    manager, host, operation = identifier(), identifier(), identifier()
    source = SimpleNamespace(
        manager_id=manager,
        host_id=host,
        registry_generation=identifier(),
        sha256=digest(b'previous registry anchor'),
        gid=19,
        generation_root_facts=None,
    )
    current = SimpleNamespace(
        manager_id=manager,
        host_id=host,
        registry_generation=identifier(),
        sha256=digest(anchor.read_bytes()),
        gid=19,
        generation_root_facts=identity(generation.stat()),
    )
    monkeypatch.setattr(
        dispatch, 'read_entry', lambda directory, name, **_: (directory / name).read_bytes()
    )
    monkeypatch.setattr(dispatch, 'dispatch_generation', lambda _: nullcontext(generation))
    prefix = dispatch.hold_scope(source, operation)
    prior_hold = canonical({**prefix, 'paused_at': '2026-11-22T08:00:00.000Z'})
    active = root / dispatch.HOLD_NAME
    active.write_bytes(prior_hold)
    with pytest.raises(EnvironmentFailure, match=dispatch.PAUSED):
        dispatch.require_dispatch_open_locked(root, current)

    intent = {
        **dispatch.hold_scope(current, operation),
        **dict.fromkeys(dispatch.OPEN_PINS, 'a' * 64),
        'status': dispatch.OPEN_INTENT_STATUS,
        'source_registry_generation': source.registry_generation,
        'source_registry_anchor_sha256': source.sha256,
        'dispatch_hold_sha256': digest(prior_hold),
    }
    (generation / dispatch.OPEN_INTENT).write_bytes(canonical(intent))
    with pytest.raises(EnvironmentFailure, match=dispatch.PAUSED):
        dispatch.require_dispatch_open_locked(root, current)
    archived = generation / dispatch.RETIRED_HOLD
    active.rename(archived)
    dispatch.require_dispatch_open_locked(root, current)
    with pytest.raises(EnvironmentFailure, match=dispatch.PAUSED):
        dispatch.require_dispatch_open_locked(root, source)
    archived.write_bytes(b'archive identity changed')
    with pytest.raises(EnvironmentFailure, match=dispatch.PAUSED):
        dispatch.require_dispatch_open_locked(root, current)


@pytest.fixture
def runtime_observation_module():
    pytest.importorskip('fcntl')
    from backend.app.management import registry_recovery_observation

    return registry_recovery_observation


def live_environment(observation, tmp_path, monkeypatch, disturbance):
    names = ('data', 'control', 'runtime', 'lock')
    folders = {name: tmp_path / name for name in names}
    for path in folders.values():
        path.mkdir()
    database = folders['data'] / 'fixture.sqlite3'
    with closing(sqlite3.connect(database)) as connection:
        connection.execute('CREATE TABLE business_record (value TEXT)')
    environment = SimpleNamespace(
        environment_root=tmp_path,
        environment_id=identifier(),
        data_generation=identifier(),
        deployment_id=identifier(),
        configuration_sha256='2' * 64,
        description={'program_source': {'sha256': '5' * 64}},
        database=database,
        lock_identity={'device': '4', 'inode': '5'},
        path=folders.__getitem__,
        directory=lambda unused_native, name: nullcontext(folders[name]),
        lock=lambda unused_native: SimpleNamespace(observer_pid=lambda: 739),
    )
    candidate, proof_id, run = identifier(), identifier(), identifier()
    proof = {
        'state': 'RUNNING',
        'candidate_ref': candidate,
        'proof_id': proof_id,
        'run_id': run,
        'data_generation': environment.data_generation,
        'deployment_id': environment.deployment_id,
        'configuration_sha256': environment.configuration_sha256,
        'program_sha256': environment.description['program_source']['sha256'],
    }
    pinned_control = {'admission': 'OPEN', 'open_receipt_ref': f'open-{run}.v1.json'}
    system_socket = {'device': '1', 'inode': '9'}
    metadata = (
        identity(tmp_path.stat()),
        {name: identity(path.stat()) for name, path in folders.items()},
    )
    samples = {
        'runtime_observation': (proof, {**proof, 'run_id': identifier()}),
        'private_control': (pinned_control, {**pinned_control, 'admission': 'CLOSED'}),
        'observed_socket': (system_socket, {**system_socket, 'inode': '2'}),
        'directory_facts': (metadata, ({'device': '7', 'inode': '9'}, metadata[1])),
        'database_identity': (identity(database.stat()), {'device': '7', 'inode': '4'}),
    }
    for name, (first, second) in samples.items():
        values = iter((first, second if name == disturbance else first))
        monkeypatch.setattr(observation, name, lambda *args, values=values: next(values))
    monkeypatch.setattr(observation, 'require_fresh', lambda _: None)
    return environment, candidate, system_socket


@pytest.mark.parametrize(
    'disturbance',
    (
        'runtime_observation',
        'private_control',
        'observed_socket',
        'directory_facts',
        'database_identity',
    ),
)
def test_live_recovery_observation_rejects_inconsistent_physical_facts(
    runtime_observation_module, tmp_path, monkeypatch, disturbance
):
    observation = runtime_observation_module
    environment, candidate, _ = live_environment(observation, tmp_path, monkeypatch, disturbance)
    with pytest.raises(EnvironmentFailure, match=observation.UNVERIFIED):
        observation.observed_running(object(), object(), environment, candidate)


def test_live_recovery_observation_can_bind_ordinary_paths_without_stopping(
    runtime_observation_module, tmp_path, monkeypatch
):
    from backend.app.management.attachment_observation import PATH_SCOPE
    from backend.app.management.registry_recovery_effects import resource_observation

    observation = runtime_observation_module
    environment, candidate, socket_identity = live_environment(
        observation, tmp_path, monkeypatch, None
    )
    result = observation.observed_running(object(), object(), environment, candidate)
    assert result['state'] == 'RUNNING_OBSERVED'
    assert result['database_identity'] == identity(environment.database.stat())
    assert result['paths']['UPSTREAM_SOCKET']['object_identity'] == socket_identity
    assert set(result['paths']) == {
        'INSTALLATION_ROOT',
        'DATA_ROOT',
        'CONTROL_ROOT',
        'BUSINESS_DATABASE',
        'STABLE_LOCK',
        'UPSTREAM_SOCKET',
    }
    row = {
        'resource_id': identifier(),
        'kind': 'UPSTREAM_SOCKET',
        'environment_id': environment.environment_id,
        'operation_id': identifier(),
        'scope_ref': PATH_SCOPE,
        'locator': result['paths']['UPSTREAM_SOCKET']['locator'],
        'identity_json': canonical(socket_identity).decode('utf-8'),
    }
    assert resource_observation(row, result)['state'] == 'BOUND'
    row['identity_json'] = canonical({**socket_identity, 'inode': '0'}).decode('utf-8')
    assert resource_observation(row, result)['state'] == 'CHANGED'
