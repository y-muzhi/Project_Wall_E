"""Protect recovery generation fencing and physical resource observations."""

import sqlite3
from contextlib import closing, contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    decode,
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
        restore_generation_sha256=None,
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
        'reason_code': 'MANAGED_APPLICATION_READY',
        'candidate_ref': candidate,
        'proof_id': proof_id,
        'run_id': run,
        'policy_sha256': '9' * 64,
        'data_generation': environment.data_generation,
        'deployment_id': environment.deployment_id,
        'configuration_sha256': environment.configuration_sha256,
        'program_sha256': environment.description['program_source']['sha256'],
    }
    if disturbance == 'unready':
        proof['reason_code'] = 'MANAGED_APPLICATION_UNVERIFIED'
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
        'unready',
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
    row['identity_json'] = None
    assert resource_observation(row, result)['state'] == 'BOUND'
    row['locator'] += '.other'
    assert resource_observation(row, result)['state'] == 'CHANGED'


@pytest.mark.parametrize('disturbance', ('none', 'missing', 'aliased', 'unattached', 'replaced'))
def test_retained_data_follows_original_receipt_chain(
    runtime_observation_module, tmp_path, monkeypatch, disturbance
):
    from backend.app.management import registry_recovery_retained_data as retained
    from backend.app.management.attachment_observation import PATH_SCOPE, path_resource
    from backend.app.management.registry_recovery_effects import resource_observation

    legacy = tmp_path / 'data'
    older = tmp_path / 'generations' / identifier() / 'data'
    current = tmp_path / 'generations' / identifier() / 'data'
    other = tmp_path / 'generations' / identifier() / 'data'
    paths = (legacy, older, current, other)
    database_name = 'fixture.sqlite3'
    for folder in paths:
        folder.mkdir(parents=True)
        with closing(sqlite3.connect(folder / database_name)) as database:
            database.execute('CREATE TABLE business_record (value TEXT)')
    entries = {
        item: (identity(item.stat()), identity((item / database_name).stat())) for item in paths
    }
    environment = SimpleNamespace(
        restore_generation_sha256='c' * 64,
        environment_root=tmp_path,
        environment_id=identifier(),
        data_generation=current.parent.name,
        roots={'data': entries[current][0]},
        database_relative=database_name,
    )
    source = entries[older][1]
    ancestry = {
        older.parent.name: (older, entries[legacy][1]),
        current.parent.name: (current, source),
        other.parent.name: (other, entries[legacy][1]),
    }

    def read_generation(root, subject, generation, *, expected=None):
        assert root == tmp_path and subject == environment.environment_id
        assert expected == (
            environment.restore_generation_sha256
            if generation == environment.data_generation
            else None
        )
        if generation == older.parent.name and disturbance == 'missing':
            raise FileNotFoundError('missing protected receipt')
        path, previous = ancestry[generation]
        root_identity, database_identity = entries[path]
        return {
            'source_database_identity': previous,
            'data_identity': root_identity,
            'database_identity': database_identity,
        }, 'd' * 64

    def sample(unused_native, unused_environment, path):
        root, database = entries[path]
        if path == other and disturbance == 'aliased':
            database = source
        if path == older and disturbance == 'replaced':
            database = entries[other][1]
        return root, database

    if disturbance == 'aliased':
        entries[other] = (entries[other][0], source)
    found = (legacy, older, other)
    if disturbance == 'unattached':
        found = (legacy, other)
    monkeypatch.setattr(retained, 'retained_sample', sample)
    monkeypatch.setattr(retained, 'read_restore_generation', read_generation)
    monkeypatch.setattr(retained, 'retained_data_paths', lambda _: found)
    observed = retained.retained_data_observation(object(), environment, entries[current][1])
    assert [item['kind'] for item in observed] == (
        ['DATA_ROOT', 'BUSINESS_DATABASE'] * 2 if disturbance == 'none' else []
    )
    current_path = path_resource('BUSINESS_DATABASE', current / database_name, entries[current][1])
    legacy_path = path_resource('BUSINESS_DATABASE', legacy / database_name, entries[legacy][1])
    row = {
        'resource_id': identifier(),
        'environment_id': environment.environment_id,
        'operation_id': identifier(),
        'kind': 'BUSINESS_DATABASE',
        'scope_ref': PATH_SCOPE,
        'locator': legacy_path['locator'],
        'identity_json': canonical(legacy_path['object_identity']).decode('utf-8'),
    }
    measured = {'paths': {'BUSINESS_DATABASE': current_path}, 'retained_paths': observed}
    result = resource_observation(row, measured)
    if disturbance == 'none':
        assert result['state'] == 'PRESERVED' and result['reason_code'] == retained.PRESERVED
    else:
        assert result['state'] == 'CHANGED'
    row['identity_json'] = canonical(entries[other][1]).decode('utf-8')
    assert resource_observation(row, measured)['state'] == 'CHANGED'


@pytest.mark.parametrize('disturbance', ('none', 'branch', 'purpose', 'repository', 'absent'))
def test_assignment_resources_require_the_registered_checkout(
    runtime_observation_module, tmp_path, monkeypatch, disturbance
):
    from backend.app.infrastructure import environment_installation as installation
    from backend.app.management.registry_recovery_effects import resource_observation

    observation = runtime_observation_module
    env_id, repository, operation = (identifier() for _ in range(3))
    path = tmp_path / 'isolated'
    path.mkdir()
    scope = {'environment_id': env_id, 'purpose': 'DEVELOPMENT', 'branch': 'refs/heads/task'}
    specification = {
        'repository_ref': repository,
        'worktrees': [{**scope, 'path': str(path), 'identity': identity(path.stat())}],
    }
    head = 'b' * 40
    worktree = {**scope, 'head': head}
    live = {'repository_ref': repository, 'worktrees': [worktree]}
    if disturbance == 'branch':
        worktree['branch'] += '-another'
    if disturbance == 'purpose':
        worktree['purpose'] = 'INTEGRATION'
    if disturbance == 'repository':
        live['repository_ref'] = identifier()
    if disturbance == 'absent':
        live['worktrees'] = []
    origin = installation.business_origin(env_id, 'validation.example.test', 443)
    policy = canonical(
        {
            'format_version': 1,
            'environment_id': env_id,
            'public_origin': origin,
            'upstream_socket': str(tmp_path / 'runtime/walle.sock'),
            'principals': [
                {'principal_id': 'browser', 'client_kind': 'WEB', 'permission': 'DEVELOP'}
            ],
        }
    )
    (tmp_path / installation.ACCESS_NAME).write_bytes(policy)
    environment = SimpleNamespace(
        anchor=tmp_path / installation.ANCHOR_NAME,
        environment_root=tmp_path,
        environment_id=env_id,
        description={
            'purpose': 'DEVELOPMENT',
            'access_policy_ref': {'name': installation.ACCESS_NAME, 'sha256': digest(policy)},
        },
    )
    monkeypatch.setattr(installation, 'read_protected', Path.read_bytes)
    monkeypatch.setattr(
        observation, 'path_reference', lambda value: (Path(value['path']), value['sha256'])
    )
    monkeypatch.setattr(observation, 'absolute', lambda value, _: Path(value))
    candidate = {'workspace': {'path': str(path / 'policy.json'), 'sha256': 'c' * 64}}

    def probe(reference, pin):
        assert reference == path / 'policy.json' and pin == 'c' * 64
        return specification, live

    claims, actual_head = observation.observed_assignment(environment, candidate, probe)
    assert actual_head == (head if disturbance == 'none' else None)
    assert claims['PUBLIC_ORIGIN']['locator'] == origin.removeprefix('https://')
    assert set(claims) == (
        {'WORKTREE', 'GIT_BRANCH', 'PUBLIC_ORIGIN'} if disturbance == 'none' else {'PUBLIC_ORIGIN'}
    )
    for kind, resource in claims.items():
        pinned = resource['object_identity']
        row = {
            'kind': kind,
            'resource_id': identifier(),
            'operation_id': operation,
            'environment_id': env_id,
            'scope_ref': resource['scope'],
            'locator': resource['locator'],
            'identity_json': None if pinned is None else canonical(pinned).decode('utf-8'),
        }
        measured = {'assignment_claims': claims, 'state': 'CLOSED'}
        assert resource_observation(row, measured)['state'] == 'BOUND'
        row['scope_ref'] += '-changed'
        assert resource_observation(row, measured)['state'] == 'CHANGED'


@pytest.fixture
def original_ordinary_start(runtime_observation_module, tmp_path, monkeypatch):
    from backend.app.management import registry_recovery_effects as effects
    from backend.app.management.runtime_capacity import MINIMUM

    env, operation, deployment, data, run, boot, candidate = (identifier() for _ in range(7))
    scope = {
        'manager_id': identifier(),
        'host_id': identifier(),
        'registry_generation': identifier(),
    }
    catalog = SimpleNamespace(directory=tmp_path, scope=scope)
    observations = tmp_path / 'observations'
    policy_path = observations / f'start-runtime-{operation}' / effects.RUNTIME_POLICY
    policy_path.parent.mkdir(parents=True)
    binding = {
        'environment_id': env,
        'deployment_id': deployment,
        'data_generation': data,
        'configuration_sha256': '1' * 64,
    }
    dispatch = {
        **binding,
        'operation_id': operation,
        'boot_id': boot,
        'capacity_sha256': '2' * 64,
        'start_policy_sha256': '3' * 64,
        'limits': MINIMUM,
    }
    outcome = {
        'environment_id': env,
        'run_id': run,
        'runtime_state': 'RUNNING',
        'observed_at': '2026-11-22T10:20:00.000Z',
        'proof_id': identifier(),
    }
    ordinary = {
        'dispatch': dispatch,
        'run_id': run,
        'policy_sha256': dispatch['start_policy_sha256'],
    }
    row = {
        'operation_id': operation,
        'environment_id': env,
        'registry_generation': scope['registry_generation'],
        'ordinal': 1,
        'status': 'SUCCEEDED',
        'step_kind': effects.START_STEP,
        'original_action': 'START',
        'original_operation_status': 'SUCCEEDED',
        'executor_ref': effects.ORDINARY_EXECUTOR,
        'external_identity_json': canonical(ordinary).decode('utf-8'),
        'result_json': canonical(outcome).decode('utf-8'),
    }
    anchor = observations / f'start-{operation}.v1.json'
    policy = {
        'candidate_ref': candidate,
        'candidate_sha256': '4' * 64,
        'operation_id': operation,
        'run_id': run,
        'boot_id': boot,
        'invocation_id': '5' * 32,
        'start_sha256': '6' * 64,
        'memory_bytes': MINIMUM['memory_bytes'],
        'tasks': MINIMUM['tasks'],
        'cpu_quota_usec': MINIMUM['cpu_percent'] * 1000,
        'cpu_period_usec': 100_000,
    }
    policy_raw = canonical(policy)
    policy_path.write_bytes(policy_raw)
    policy_pin = digest(policy_raw)
    original_start = {
        **effects.start_common(catalog, operation, env, dispatch['start_policy_sha256']),
        'state': 'READY',
        'recorded_at': outcome['observed_at'],
        'boot_id': boot,
        'prepared': {
            **binding,
            'run_id': run,
            'operation_id': operation,
            'start_sha256': policy['start_sha256'],
        },
        'runtime': {'path': str(policy_path), 'sha256': policy_pin},
        'observation': {
            **{field: outcome[field] for field in ('proof_id', 'environment_id', 'observed_at')},
            'state': 'RUNNING',
            'reason_code': 'MANAGED_APPLICATION_READY',
        },
    }
    anchor.write_bytes(canonical(original_start))

    def local_policy(path, pin, source_catalog):
        assert path == policy_path and source_catalog is catalog
        raw = path.read_bytes()
        assert digest(raw) == pin
        return decode(raw, 'TEST')

    def captured(directory, name, **unused):
        return (directory / name).read_bytes()

    def observe(unit):
        if unit == f'walle-prep-{env}-{operation}.service':
            return {'unit': unit, 'state': 'ABSENT_OBSERVED'}
        assert unit == f'walle-env-{env}-{operation}.service'
        return {
            'unit': unit,
            'state': 'PRESENT_OBSERVED',
            'main_pid': 1001,
            'active_state': 'active',
            'cgroup_empty': False,
            'invocation_id': policy['invocation_id'],
        }

    monkeypatch.setattr(effects, 'protected_directory', nullcontext)
    monkeypatch.setattr(effects, 'path_reference', lambda ref: (Path(ref['path']), ref['sha256']))
    monkeypatch.setattr(effects, 'load_policy', local_policy)
    monkeypatch.setattr(effects, 'unit_observation', observe)
    from backend.app.management import runtime_start

    monkeypatch.setattr(runtime_start, 'read_entry', captured)
    current = {
        'kind': 'ENVIRONMENT',
        'environment_id': env,
        'state': 'RUNNING_OBSERVED',
        'binding': binding,
        'run_id': run,
        'policy_sha256': policy_pin,
        'lock_pid': 1009,
        'configuration_attachment': {
            'candidate_ref': candidate,
            'sha256': policy['candidate_sha256'],
        },
    }
    return effects, catalog, row, current, anchor, original_start


@pytest.mark.parametrize(
    'disturbance', ('none', 'source-run', 'proof', 'attachment', 'missing', 'cancelled', 'stop')
)
def test_original_start_observation_uses_original_dispatch_and_runtime(
    runtime_observation_module, original_ordinary_start, disturbance
):
    from backend.app.management import registry_recovery_dispatch_review as review

    effects, catalog, row, current, anchor, original = original_ordinary_start
    if disturbance == 'source-run':
        original['prepared']['run_id'] = identifier()
        anchor.write_bytes(canonical(original))
    if disturbance == 'proof':
        original['observation']['proof_id'] = identifier()
        anchor.write_bytes(canonical(original))
    if disturbance == 'attachment':
        current['configuration_attachment']['sha256'] = '0' * 64
    if disturbance == 'missing':
        anchor.unlink()
    if disturbance == 'cancelled':
        row['original_operation_status'] = 'CANCELLED'
    measured = effects.helper_observation(row, catalog)
    assert measured['state'] == 'OBSERVED' and len(measured['units']) == 2
    if disturbance == 'stop':
        measured['step_kind'] = effects.STOP_STEP
    blockers = review.review_host_rows(iter((current, measured)), iter(()), 2)
    assert blockers == ({} if disturbance == 'none' else {review.RUNTIME: 1})


@pytest.fixture(params=('RELEASE', 'RESTORE'))
def opened_deployment_step(runtime_observation_module, request):
    from backend.app.management import registry_recovery_effects as effects
    from backend.app.management.runtime_capacity import MINIMUM

    action = request.param
    operation, environment, generation, manager, host, release = (identifier() for _ in range(6))
    target = {
        'data_generation': identifier(),
        'deployment_id': identifier(),
        'configuration_sha256': '4' * 64,
        'program_sha256': '5' * 64,
    }
    opening = {
        'environment_id': environment,
        'operation_id': operation,
        'run_id': identifier(),
        'boot_id': identifier(),
        'limits': MINIMUM.copy(),
        **{
            key: target[key] for key in ('data_generation', 'deployment_id', 'configuration_sha256')
        },
        'open_policy_sha256': '6' * 64,
        'selection_receipt_sha256': '7' * 64,
        'launch_policy_sha256': '8' * 64,
        'capacity_sha256': '9' * 64,
    }
    scope = {'manager_id': manager, 'host_id': host, 'registry_generation': generation}
    catalog = SimpleNamespace(scope={**scope, 'registry_generation': identifier()})
    authorization = {
        'operation_id': operation,
        'environment_id': environment,
        'target': target,
        'release_manifest_sha256': 'b' * 64,
    }
    step_kind = 'RELEASE_DEPLOYMENT' if action == 'RELEASE' else 'RESTORE_ENVIRONMENT'
    authority = (
        {**authorization, 'release_ref': release}
        if action == 'RELEASE'
        else {'confirmation': {**authorization, 'target_release_ref': release}}
    )
    external = {'maintenance': {'format_version': 1, **scope, **authority}, 'opening': opening}
    result = {
        **{key: opening[key] for key in (*effects.TARGET, 'run_id')},
        'release_ref': release,
        'release_manifest_sha256': authorization['release_manifest_sha256'],
        'proof_id': identifier(),
        'opened_at': '2026-11-22T08:00:00.000Z',
        'control_revision': 9,
        'record_version': 2,
        'assignment_generation': 1,
    }
    row = {
        'operation_id': operation,
        'environment_id': environment,
        'registry_generation': generation,
        'original_action': action,
        'original_operation_status': 'SUCCEEDED',
        'status': 'SUCCEEDED',
        'ordinal': 1,
        'step_kind': step_kind,
        'executor_ref': effects.DEPLOYMENT_STEPS[step_kind][1],
        'external_identity_json': canonical(external).decode(),
        'result_json': canonical(result).decode(),
    }
    return effects, catalog, row, external, result


@pytest.mark.parametrize(
    ('change', 'expected'),
    (
        ('none', 'OPENED_RUNNING'),
        ('no-opening', 'MAINTENANCE_WITHOUT_OPENING'),
        ('no-proof', 'OPENING_UNCONFIRMED'),
        ('source-drift', 'OPENING_UNVERIFIED'),
        ('root-drift', 'OPENED_RUNTIME_UNVERIFIED'),
        ('run-drift', 'OPENED_RUNTIME_UNVERIFIED'),
    ),
)
def test_pending_deployment_retains_original_dispatch_blocker(
    runtime_observation_module, opened_deployment_step, monkeypatch, change, expected
):
    from backend.app.management import registry_recovery_dispatch_review as review

    obs = runtime_observation_module
    _, catalog, original, payload, result = opened_deployment_step
    action = original['original_action']
    catalog.scope['registry_generation'] = original['registry_generation']
    request = payload['opening']
    grant = payload['maintenance']
    plan = grant if action == 'RELEASE' else grant['confirmation']
    target = plan['target']
    source_attachment = {'candidate_ref': identifier(), 'sha256': 'a' * 64}
    target_attachment = {'candidate_ref': identifier(), 'sha256': 'b' * 64}
    source = {
        'environment_id': original['environment_id'],
        'configuration_sha256': '1' * 64,
        'program_sha256': '2' * 64,
        'data_generation': target['data_generation'] if action == 'RELEASE' else identifier(),
        'deployment_id': identifier(),
    }
    plan.update(source=source, source_attachment=source_attachment)
    registered = {
        **source,
        'program_source': source['program_sha256'],
        'purpose': 'DEVELOPMENT',
        'configuration_ref': canonical(source_attachment).decode(),
        'host_id': catalog.scope['host_id'],
        'registration_state': 'ACTIVE',
        'preparation_state': 'PREPARED',
        'assignment_control_state': 'OPEN',
    }
    if change == 'source-drift':
        registered['program_source'] = '0' * 64
    if change == 'no-opening':
        payload.pop('opening')
    step = {
        **original,
        'status': 'DISPATCHING',
        'original_operation_status': 'RUNNING',
        'cancel_requested': 0,
        'external_identity_json': canonical(payload).decode(),
        'result_json': None,
    }
    observed = {
        'opening': {'opened_at': result['opened_at'], 'operation_id': original['operation_id']},
        'runtime': {'sha256': '3' * 64},
    }
    installed = dict(
        zip(
            (source_attachment['candidate_ref'], target_attachment['candidate_ref']),
            (
                {**source, 'purpose': 'DEVELOPMENT'},
                {'environment_id': source['environment_id'], **target, 'purpose': 'DEVELOPMENT'},
            ),
            strict=True,
        )
    )
    catalog.candidate = lambda ref, pin: installed[ref]

    def installation(candidate, runtime):
        target_installation = candidate['deployment_id'] == target['deployment_id']
        return SimpleNamespace(
            facts=candidate,
            environment_root='different'
            if target_installation and change == 'root-drift'
            else 'stable',
            roots={'control': 'same-control'},
            lock_identity='same-lock',
            project=candidate['program_sha256'],
            check_hold=lambda *, offline: None,
        )

    def state(native, active_catalog, environment, attachment, binding, receipt, policy):
        assert attachment == target_attachment and binding['run_id'] == request['run_id']
        if change == 'run-drift':
            raise EnvironmentFailure(obs.UNVERIFIED)
        return {'state': 'OPENED_RUNNING'}

    monkeypatch.setattr(obs, 'candidate_environment', installation)
    monkeypatch.setattr(obs, 'public_facts', lambda environment: environment.facts)
    monkeypatch.setattr(obs, 'opened_target_state', state)
    monkeypatch.setattr(
        obs,
        'checked_deployment_opening',
        lambda *args: None if change == 'no-proof' else (observed, target_attachment, {}),
    )
    evidence = obs.pending_deployment_observation(
        object(), catalog, registered, step, '4' * 64, {'verify_program': lambda path: path}
    )
    assert evidence['state'] == expected
    if expected == 'OPENED_RUNNING':
        assert evidence['source']['deployment_id'] == source['deployment_id']
        assert evidence['target']['deployment_id'] == target['deployment_id']
        assert evidence['opened_receipt_sha256'] == digest(canonical(observed))

    helper = {
        **step,
        'kind': 'ORIGINAL_HELPER_STEP',
        'state': 'UNKNOWN',
        'original_status': step['status'],
        'external_deployment': evidence,
        'units': [],
    }
    operation = {
        **step,
        'status': 'RUNNING',
        'revision': 3,
        'intent_sha256': 'c' * 64,
        'action': action,
    }
    blockers = list(review.blocked_subjects(iter((helper,)), iter((operation,)), 1))
    assert [item['reason_code'] for item in blockers] == [review.STEP, review.OPERATION]
    assert blockers[0]['external_deployment'] == evidence


def test_completed_deployment_observes_its_original_unit(opened_deployment_step, monkeypatch):
    effects, catalog, row, external, _ = opened_deployment_step
    expected = f'walle-env-{row["environment_id"]}-{row["operation_id"]}.service'
    units = []

    def observe(unit):
        units.append(unit)
        return {'unit': unit, 'state': 'ABSENT_OBSERVED'}

    monkeypatch.setattr(effects, 'unit_observation', observe)
    result = effects.helper_observation(row, catalog)
    assert units == [expected]
    assert result['state'] == 'OBSERVED'
    assert result['opening_binding']['run_id'] == external['opening']['run_id']
    assert result['opening_binding']['environment_id'] == row['environment_id']


@pytest.mark.parametrize('mismatch', ('generation', 'host', 'configuration', 'run', 'executor'))
def test_completed_deployment_requires_all_preserved_bindings(
    opened_deployment_step, monkeypatch, mismatch
):
    effects, catalog, row, external, result = opened_deployment_step
    if mismatch == 'generation':
        external['maintenance']['registry_generation'] = identifier()
    elif mismatch == 'host':
        external['maintenance']['host_id'] = identifier()
    elif mismatch == 'configuration':
        external['opening']['configuration_sha256'] = '1' * 64
    elif mismatch == 'run':
        result['run_id'] = identifier()
    else:
        row['executor_ref'] = 'WRONG_EXECUTOR'
    row['external_identity_json'] = canonical(external).decode()
    row['result_json'] = canonical(result).decode()

    def unexpected(unit):
        pytest.fail(f'Unbound unit was queried: {unit}')

    monkeypatch.setattr(effects, 'unit_observation', unexpected)
    observed = effects.helper_observation(row, catalog)
    assert observed['state'] == 'UNKNOWN'
    assert observed['units'] == []
    assert 'opening_binding' not in observed


@pytest.mark.parametrize('mismatch', (None, 'run', 'deployment', 'policy', 'invocation', 'process'))
def test_recovery_review_binds_live_deployment_to_current_environment(
    opened_deployment_step, monkeypatch, mismatch
):
    from backend.app.management import registry_recovery_dispatch_review as review

    effects, catalog, row, external, _ = opened_deployment_step
    unit = {
        'unit': f'walle-env-{row["environment_id"]}-{row["operation_id"]}.service',
        'state': 'PRESENT_OBSERVED',
        'active_state': 'active',
        'main_pid': 799,
        'cgroup_empty': False,
        'invocation_id': '2' * 32,
    }
    authority = {'policy_sha256': 'c' * 64, 'invocation_id': unit['invocation_id']}
    monkeypatch.setattr(effects, 'unit_observation', lambda _: unit)
    monkeypatch.setattr(effects, 'observed_deployment_authority', lambda *args: authority)
    observed = effects.helper_observation(row, catalog)
    opening = external['opening']
    current = {
        'kind': 'ENVIRONMENT',
        'environment_id': row['environment_id'],
        'state': 'RUNNING_OBSERVED',
        'binding': {
            **{key: opening[key] for key in effects.TARGET},
            'program_sha256': '5' * 64,
        },
        'run_id': opening['run_id'],
        'lock_pid': 801,
        'policy_sha256': authority['policy_sha256'],
    }
    if mismatch == 'run':
        current['run_id'] = identifier()
    elif mismatch == 'deployment':
        current['binding']['deployment_id'] = identifier()
    elif mismatch == 'policy':
        current['policy_sha256'] = '5' * 64
    elif mismatch == 'invocation':
        unit['invocation_id'] = '4' * 32
    elif mismatch == 'process':
        unit['main_pid'] = current['lock_pid']
    expected = {} if mismatch is None else {review.RUNTIME: 1}
    assert review.review_host_rows(iter((current, observed)), iter(()), 2) == expected


def test_present_deployment_with_missing_opening_receipt_stays_unverified(
    opened_deployment_step, monkeypatch
):
    effects, catalog, row, _, _ = opened_deployment_step
    name = f'walle-env-{row["environment_id"]}-{row["operation_id"]}.service'
    monkeypatch.setattr(
        effects,
        'unit_observation',
        lambda _: {
            'unit': name,
            'state': 'PRESENT_OBSERVED',
        },
    )

    def absent(*args):
        raise FileNotFoundError

    monkeypatch.setattr(effects, 'observed_deployment_authority', absent)
    observed = effects.helper_observation(row, catalog)
    assert observed['units'][0]['state'] == 'PRESENT_OBSERVED'
    assert 'runtime_authority' not in observed


@pytest.mark.parametrize('case', ('exact', 'receipt_drift', 'unit_occupied', 'other_environment'))
def test_adopted_deployment_only_settles_its_exact_original_step(opened_deployment_step, case):
    from backend.app.management import registry_recovery_dispatch_review as review
    from backend.app.management.registry_recovery_outcome import OPENED_DEPLOYMENT

    _, _, source, _, _ = opened_deployment_step
    operation = {
        'operation_id': source['operation_id'],
        'environment_id': source['environment_id'],
        'registry_generation': source['registry_generation'],
        'status': 'RUNNING',
        'action': source['original_action'],
        'revision': 3,
        'intent_sha256': 'a' * 64,
    }
    identifier = operation['operation_id']
    evidence = {'state': 'OPENED_STOPPED', 'opened_receipt_sha256': 'b' * 64}
    unit = {
        'unit': f'walle-env-{operation["environment_id"]}-{identifier}.service',
        'state': 'QUIET_OBSERVED',
        'cgroup_empty': True,
        'main_pid': 0,
    }
    step = {
        'kind': 'ORIGINAL_HELPER_STEP',
        'ordinal': 1,
        'step_kind': source['step_kind'],
        'original_status': 'DISPATCHING',
        'state': 'OBSERVED',
        'environment_id': operation['environment_id'],
        'operation_id': identifier,
        'external_deployment': dict(evidence),
        'units': [unit],
    }
    receipt = {
        'outcome': {
            'operation_id': identifier,
            'source_registry_generation': operation['registry_generation'],
            'source_revision': operation['revision'],
            'source_intent_sha256': operation['intent_sha256'],
            'disposition': OPENED_DEPLOYMENT,
        },
        'evidence': {
            'environment_id': operation['environment_id'],
            'original_status': operation['status'],
            'action': operation['action'],
        },
    }
    rows = [step]
    expected = {}
    if case == 'receipt_drift':
        step['external_deployment']['opened_receipt_sha256'] = 'c' * 64
        expected = {review.STEP: 1}
    if case == 'other_environment':
        rows.append({'kind': 'ENVIRONMENT', 'environment_id': str(uuid4()), 'state': 'UNKNOWN'})
        expected = {review.ENVIRONMENT: 1}
    if case == 'unit_occupied':
        unit['cgroup_empty'] = False
        with pytest.raises(EnvironmentFailure, match=review.UNVERIFIED):
            review.review_host_rows(
                iter(rows),
                iter((operation,)),
                len(rows),
                {identifier: receipt},
                adopted_steps={identifier: evidence},
            )
        return
    assert (
        review.review_host_rows(
            iter(rows),
            iter((operation,)),
            len(rows),
            {identifier: receipt},
            adopted_steps={identifier: evidence},
        )
        == expected
    )


def test_recovered_entry_capacity_policy_preserves_original_authority(
    tmp_path, monkeypatch, runtime_observation_module
):
    from backend.app.management import operation_contract, runtime_capacity

    observation = runtime_observation_module
    shared_scope = {'manager_id': identifier(), 'host_id': identifier()}
    original, current = (
        SimpleNamespace(**shared_scope, registry_generation=identifier(), sha256=pin * 64)
        for pin in ('a', 'b')
    )
    legacy = tmp_path / 'original-capacity.v1.json'
    old_dir = tmp_path / 'original-directory'
    new_dir = tmp_path / 'recovered-entry'
    old_dir.mkdir()
    new_dir.mkdir()
    limits = {'memory_bytes': 256 * 1024**2, 'cpu_percent': 25, 'tasks': 16, 'run_slots': 1}
    profiles = {
        purpose: {'profile_ref': identifier(), 'limits': limits}
        for purpose in ('DEVELOPMENT', 'INTEGRATION')
    }
    monkeypatch.setattr(runtime_capacity, 'POLICY_PATH', legacy)
    monkeypatch.setattr(runtime_capacity, 'absolute', lambda value, _: Path(value))
    memory = {'SC_PHYS_PAGES': 524_288, 'SC_PAGE_SIZE': 4096}
    monkeypatch.setattr(
        runtime_capacity, 'os', SimpleNamespace(cpu_count=lambda: 4, sysconf=memory.__getitem__)
    )
    monkeypatch.setattr(operation_contract, 'read_protected', Path.read_bytes)
    monkeypatch.setattr(operation_contract, 'absolute', lambda value, _: Path(value))
    monkeypatch.setattr(observation, 'read_protected', Path.read_bytes)

    def catalog(installation, directory, path, *, location=None):
        scope = operation_contract.identity_scope(installation)
        record = {
            'format_version': 1,
            **scope,
            'registry_anchor_sha256': installation.sha256,
            'catalog_directory': str(directory),
            'manager_home': str(tmp_path / 'home'),
            'manager_temporary': str(tmp_path / 'temporary'),
            'limits': limits,
            'profiles': profiles,
        }
        raw = canonical(record)
        path.write_bytes(raw)
        description = {
            'format_version': 1,
            **scope,
            'principals': [{'id': 'operator', 'role': 'MANAGER', 'environment_ids': []}],
            'candidates': {},
            'resources': {},
            'checks': {},
            'capacity_policy_sha256': digest(raw),
        }
        if location is not None:
            description['capacity_policy_location'] = location
        return operation_contract.catalog_from_record(
            description, directory, installation
        ), description

    old_catalog, _ = catalog(original, old_dir, legacy)
    scoped = new_dir / 'ordinary-capacity.v1.json'
    new_catalog, description = catalog(current, new_dir, scoped, location='CATALOG')
    assert runtime_capacity.load_capacity(old_catalog).sha256 == digest(legacy.read_bytes())
    assert runtime_capacity.load_capacity(new_catalog).sha256 == digest(scoped.read_bytes())
    for registered in (old_catalog, new_catalog):
        assert [row['state'] for row in observation.asset_observations(registered)] == ['VERIFIED']

    bad = {**description, 'capacity_policy_location': '../old'}
    with pytest.raises(EnvironmentFailure, match=operation_contract.INVALID):
        operation_contract.catalog_from_record(bad, new_dir, current)
    unpinned = {key: value for key, value in description.items() if key != 'capacity_policy_sha256'}
    with pytest.raises(EnvironmentFailure, match=operation_contract.INVALID):
        operation_contract.catalog_from_record(unpinned, new_dir, current)

    scoped.rename(new_dir / 'unpublished.v1.json')
    with pytest.raises(EnvironmentFailure, match=runtime_capacity.NOT_READY):
        runtime_capacity.load_capacity(new_catalog)
    assert [row['state'] for row in observation.asset_observations(new_catalog)] == ['UNKNOWN']
    assert [row['state'] for row in observation.asset_observations(old_catalog)] == ['VERIFIED']


def test_recovered_runtime_authority_requires_the_prior_attestation_and_open_receipt(
    tmp_path, monkeypatch, runtime_observation_module
):
    from backend.app.management import registry_recovered_runtime as recovered

    generation = tmp_path / 'g'
    directory = generation / recovered.ENTRY_INPUTS / 'e'
    operation, environment, run = identifier(), identifier(), identifier()
    runtime = directory / 'observations' / (recovered.RUNTIME_DIRECTORY + operation)
    opened = generation / dispatch.OPEN_INTENT
    protected_records = {opened: b'original verified dispatch reopening'}

    catalog = SimpleNamespace(
        directory=directory,
        scope={
            'manager_id': identifier(),
            'host_id': identifier(),
            'registry_generation': identifier(),
        },
        registry_anchor_sha256='a' * 64,
    )
    pin = 'b' * 64
    attestation = {
        'format_version': 1,
        **catalog.scope,
        'registry_anchor_sha256': catalog.registry_anchor_sha256,
        'environment_id': environment,
        'operation_id': operation,
        'run_id': run,
        'runtime_policy_sha256': pin,
        'source_registry_generation': identifier(),
        'source_runtime_policy_sha256': 'c' * 64,
        'dispatch_open_sha256': digest(protected_records[opened]),
    }
    proof = runtime / recovered.ATTESTATION
    protected_records[proof] = canonical(attestation)
    policy = {
        'operation_id': operation,
        'run_id': run,
        'boot_id': identifier(),
        'invocation_id': 'd' * 32,
        'candidate_ref': identifier(),
        'candidate_sha256': 'e' * 64,
        'memory_bytes': 256 * 1024**2,
        'tasks': 32,
        'cpu_quota_usec': 45_000,
        'cpu_period_usec': 100_000,
    }
    row = {
        'status': 'SUCCEEDED',
        'original_operation_status': 'SUCCEEDED',
        'operation_id': operation,
        'environment_id': environment,
    }
    quota = {'memory_bytes': policy['memory_bytes'], 'tasks': 32, 'cpu_percent': 45}
    monkeypatch.setattr(recovered, 'read_protected', protected_records.__getitem__)
    monkeypatch.setattr(
        recovered,
        'runtime_observation',
        lambda _, candidate: (
            {'run_id': run, 'policy_sha256': pin} if candidate == environment else None
        ),
    )

    def pinned_policy(path, actual_pin, actual_catalog):
        assert (
            path == runtime / recovered.POLICY and actual_pin == pin and actual_catalog is catalog
        )
        return policy

    monkeypatch.setattr(recovered, 'load_policy', pinned_policy)
    result = recovered.recovered_authority(catalog, row, run, quota, boot_id=policy['boot_id'])
    assert result == {
        'policy_sha256': pin,
        'invocation_id': policy['invocation_id'],
        'configuration_attachment': {
            'candidate_ref': policy['candidate_ref'],
            'sha256': policy['candidate_sha256'],
        },
    }
    with pytest.raises(EnvironmentFailure, match=recovered.UNVERIFIED):
        recovered.recovered_authority(catalog, row, run, {**quota, 'tasks': 34})
    with pytest.raises(EnvironmentFailure, match=recovered.UNVERIFIED):
        recovered.recovered_authority(catalog, row, identifier(), quota)
    bad_source = {**attestation, 'source_registry_generation': catalog.scope['registry_generation']}
    protected_records[proof] = canonical(bad_source)
    with pytest.raises(EnvironmentFailure, match=recovered.UNVERIFIED):
        recovered.recovered_authority(catalog, row, run, quota)
    protected_records[proof] = canonical(attestation)
    protected_records[opened] = b'dispatch receipt changed'
    with pytest.raises(EnvironmentFailure, match=recovered.UNVERIFIED):
        recovered.recovered_authority(catalog, row, run, quota)


def test_runtime_adoption_cannot_overwrite_a_concurrent_observation(
    tmp_path, monkeypatch, runtime_observation_module
):
    from backend.app.management import attachment_observation as observation

    catalog = SimpleNamespace(directory=tmp_path)
    current = {'boot_id': identifier(), 'observed_monotonic_ms': 12}
    newer = {**current, 'observed_monotonic_ms': 15}
    published = []
    monkeypatch.setattr(observation, 'protected_directory', nullcontext)
    monkeypatch.setattr(observation, 'fcntl', SimpleNamespace(LOCK_EX=1, flock=lambda *_: None))
    monkeypatch.setattr(observation, 'read_entry', lambda *_, **__: canonical(current))
    monkeypatch.setattr(
        observation,
        'persisted_write',
        lambda _dir, _name, raw, **_options: published.append(raw),
    )

    with pytest.raises(EnvironmentFailure, match=observation.RESOURCE):
        observation.publish_observation(catalog, 'runtime-environment', newer, expected=None)
    with pytest.raises(EnvironmentFailure, match=observation.RESOURCE):
        observation.publish_observation(
            catalog,
            'runtime-environment',
            newer,
            expected=canonical({**current, 'observed_monotonic_ms': 11}),
        )
    assert published == []
    observation.publish_observation(
        catalog, 'runtime-environment', newer, expected=canonical(current)
    )
    assert published == [canonical(newer)]


def test_demoted_observer_scratch_keeps_private_catalog_ancestors_closed(
    monkeypatch, runtime_observation_module
):
    from backend.app.management import attachment_observation as observation

    @contextmanager
    def protection(area):
        if not area.protected:
            raise EnvironmentFailure(observation.RESOURCE)
        yield

    def root(mode):
        return SimpleNamespace(stat=lambda: SimpleNamespace(st_mode=mode))

    shared = SimpleNamespace(stat=root(0o755).stat, parents=(root(0o755),), protected=True)
    closed = SimpleNamespace(stat=root(0o755).stat, parents=(root(0o2750),), protected=True)
    unrelated = SimpleNamespace(stat=root(0o755).stat, parents=(), protected=False)
    monkeypatch.setattr(observation, 'protected_directory', protection)
    assert observation.observer_scratch(shared) is shared
    assert observation.observer_scratch(closed) == Path('/run')
    with pytest.raises(EnvironmentFailure, match=observation.RESOURCE):
        observation.observer_scratch(unrelated)
