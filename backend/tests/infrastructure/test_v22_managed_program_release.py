"""Exercise fixed deployment changes through management on owned SQLite databases."""

import json
import os
import sqlite3
from contextlib import closing, contextmanager, nullcontext
from dataclasses import replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import SimpleNamespace
from uuid import uuid4

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    digest,
    identity,
)


def identifier():
    return str(uuid4())


def store(path, value):
    raw = canonical(value)
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_bytes(raw)
    return {'path': str(path), 'sha256': digest(raw)}


@pytest.fixture(params=('RELEASE', 'ROLLBACK_CODE', 'RECONFIGURE'))
def deployment(request, tmp_path, monkeypatch):
    pytest.importorskip('fcntl')
    from backend.app.infrastructure import (
        environment_installation,
        environment_recovery_installation,
    )
    from backend.app.infrastructure import environment_release_preflight as preflight
    from backend.app.infrastructure.environment_installation import ANCHOR_NAME
    from backend.app.management import (
        management_web,
        operation_contract,
        operation_store,
        release_catalog_view,
        release_configuration,
        release_observation,
        release_operations,
    )
    from backend.app.management.attachment_observation import now
    from backend.app.management.operation_contract import Catalog, Principal
    from backend.app.management.registry_schema import STATEMENTS
    from backend.app.management.release_artifacts import MANIFEST

    action = request.param
    rollback = action == 'ROLLBACK_CODE'
    configure = action == 'RECONFIGURE'
    scope = {key: identifier() for key in ('manager_id', 'host_id', 'registry_generation')}
    manager = Principal('manager', 'MANAGER', ())
    environment, generation, current, previous, target = (identifier() for _ in range(5))
    developer = Principal('developer', 'DEVELOPER', (environment,))
    configuration, candidate, owner, profile, task = (identifier() for _ in range(5))
    runtime = 'b' * 64
    schema_pin = 'c' * 64
    schema_contract = 'd' * 64
    business_root = tmp_path / 'environment'
    input_db = business_root / 'data' / 'business.sqlite'
    input_db.parent.mkdir(parents=True)
    with closing(sqlite3.connect(input_db)) as business:
        business.execute('CREATE TABLE document (id INTEGER PRIMARY KEY, body TEXT)')
        business.execute(
            'INSERT INTO document(body) VALUES (?)', ('current content after original release',)
        )
        business.commit()
    control_path = business_root / 'control'
    control_path.mkdir()
    runtime_path = business_root / 'runtime'
    runtime_path.mkdir()
    package = tmp_path / 'fixed'
    target_program = package / 'application'
    source_program = target_program if configure else tmp_path / 'current-program'
    source_digest = '6' * 64 if configure else '5' * 64
    business = environment_installation.business_origin(environment, 'program.test')
    control = {
        'admission': 'CLOSED',
        'closed_reason': 'NORMAL_STOP',
        'control_revision': 9,
        'environment_id': environment,
        'deployment_id': current,
        'data_generation': generation,
    }
    manifest = {
        'release_id': candidate,
        'runtime_manifest_sha256': runtime,
        'schema_manifest_sha256': schema_pin,
        'application_index_ref': {'sha256': '1' * 64},
        'frontend_index_ref': {'sha256': '2' * 64},
        'compatibility_refs': [],
    }
    compatibility_id, recovery_id = identifier(), identifier()
    same_schema = SimpleNamespace(schema_contract_sha256=schema_contract)
    owned = SimpleNamespace(assert_owned=lambda: None)
    stable = {'device': '1', 'inode': '2'}
    schema_dir = tmp_path / 'schema'

    def installation(deployment_id, config_sha, program, program_sha, slot):
        anchor = business_root / 'deployments' / deployment_id / ANCHOR_NAME
        anchor_ref = store(anchor, {'deployment': deployment_id, 'program': program_sha})
        principal = 'new-browser' if configure and deployment_id == target else 'old-browser'
        access = store(
            anchor.parent / environment_installation.ACCESS_NAME,
            {
                'format_version': 1,
                'environment_id': environment,
                'public_origin': business,
                'upstream_socket': str(runtime_path / 'walle.sock'),
                'principals': [
                    {'principal_id': principal, 'client_kind': 'WEB', 'permission': 'DEVELOP'}
                ],
            },
        )
        result = SimpleNamespace(
            anchor=anchor,
            anchor_sha256=anchor_ref['sha256'],
            environment_root=business_root,
            environment_id=environment,
            deployment_id=deployment_id,
            data_generation=generation,
            configuration_sha256=config_sha,
            ingress_group=None,
            schema=schema_dir,
            project=program,
            lock_identity=stable,
            database=input_db,
            description={
                'purpose': 'INTEGRATION',
                'deployment_slot': slot,
                'program_source': {'kind': 'FIXED_RELEASE', 'sha256': program_sha},
                'schema_manifest_sha256': schema_pin,
                'runtime_manifest_sha256': runtime,
                'access_policy_ref': {
                    'name': environment_installation.ACCESS_NAME,
                    'sha256': access['sha256'],
                },
                'required_capabilities': ['DOCUMENT_READ', 'DOCUMENT_WRITE'],
            },
            check_hold=lambda: None,
            host_admission=nullcontext,
            lock=lambda native: nullcontext(owned),
            directory=lambda native, kind: nullcontext(
                control_path if kind == 'control' else input_db.parent
            ),
            path=lambda kind: runtime_path if kind == 'runtime' else input_db.parent,
        )
        return result, anchor_ref

    current_slot = {
        'source_deployment_id': previous,
        'source_configuration_sha256': '3' * 64,
        'authorization_mode': 'SAME_SCHEMA',
    }
    origin, origin_ref = installation(
        current, '4' * 64, source_program, source_digest, current_slot
    )
    compatibility = preflight.compatibility_record(
        compatibility_id, origin, same_schema, manifest, same_schema, '6' * 64
    )
    compatibility_ref = store(tmp_path / preflight.COMPATIBILITY, compatibility)
    if action == 'RELEASE':
        manifest['compatibility_refs'].append(
            {'ref': compatibility_id, 'sha256': compatibility_ref['sha256']}
        )
    manifest_ref = store(package / MANIFEST, manifest)
    previous_slot = {
        'release_id': candidate,
        'manifest_sha256': manifest_ref['sha256'],
        'frontend_index_sha256': manifest['frontend_index_ref']['sha256'],
    }
    if configure:
        current_slot.update(previous_slot)
    former, former_ref = installation(previous, '3' * 64, target_program, '6' * 64, previous_slot)
    target_slot = {
        'source_deployment_id': current,
        'source_configuration_sha256': origin.configuration_sha256,
        'authorization_mode': action if action != 'RELEASE' else 'SAME_SCHEMA',
        'release_id': candidate,
        'manifest_sha256': manifest_ref['sha256'],
    }
    next_run, target_ref = installation(target, '7' * 64, target_program, '6' * 64, target_slot)

    def load_installation(anchor, pin, runtime_pin, project):
        for item in (origin, former, next_run):
            if (anchor, pin, runtime_pin, project) == (
                item.anchor,
                item.anchor_sha256,
                runtime,
                item.project,
            ):
                return item
        raise EnvironmentFailure(preflight.UNVERIFIED)

    app_root = tmp_path / 'manager'
    source_attachment, target_attachment = identifier(), identifier()

    def attachment(key, reference):
        return store(
            app_root / 'candidates' / (key + '.json'),
            {
                'format_version': 1,
                'candidate_ref': key,
                'installation': reference,
                'workspace': {'path': str(tmp_path / 'workspace'), 'sha256': '8' * 64},
                'profile_ref': profile,
                'task_id': task,
                'display_name': 'Environment',
                'owner_principal': owner,
                'owner_label': 'Owner',
                'goal': 'Goal',
                'scope': 'Scope',
                'baseline_commit': '9' * 40,
                'checks': 'Checks',
            },
        )

    old_pin = attachment(source_attachment, origin_ref)['sha256']
    new_pin = attachment(target_attachment, target_ref)['sha256']
    old_ref = {'candidate_ref': source_attachment, 'sha256': old_pin}
    new_ref = {'candidate_ref': target_attachment, 'sha256': new_pin}
    retained_ref = store(
        app_root / 'release-candidates' / (candidate + '.json'),
        {
            'format_version': 1,
            **scope,
            'release_id': candidate,
            'delivery_operation_id': identifier(),
            'manifest_ref': manifest_ref,
            'schema_ref': {'path': str(schema_dir), 'sha256': schema_pin},
            'build_record_ref': {'path': str(tmp_path / 'build'), 'sha256': 'a' * 64},
        },
    )
    recovery_ref = store(
        app_root / 'release-recovery-policies' / (recovery_id + '.json'),
        {
            'format_version': 1,
            **scope,
            'ref': recovery_id,
            'minimum_verification': 'LOCAL_VERIFIED',
            'preserve_source': True,
        },
    )
    reference = {
        'format_version': 1,
        **scope,
        'configuration_ref': configuration,
        'environment_id': environment,
        'release_ref': candidate,
        'candidate_sha256': retained_ref['sha256'],
        'source_attachment': old_ref,
        'target_attachment': new_ref,
        'compatibility': {'ref': compatibility_id, **compatibility_ref},
        'recovery_policy': {'ref': recovery_id, 'sha256': recovery_ref['sha256']},
    }
    if rollback:
        reference['rollback_source'] = {
            'previous_installation': former_ref,
            'previous_project': str(former.project),
        }
    if configure:
        reference['target_access_sha256'] = next_run.description['access_policy_ref']['sha256']
    configuration_path = app_root / 'release-configurations' / (configuration + '.json')
    reference_pin = store(configuration_path, reference)['sha256']
    catalog = Catalog(
        directory=app_root,
        scope=scope,
        principals={manager.id: manager, developer.id: developer},
        candidates={source_attachment: old_pin, target_attachment: new_pin},
        resources={},
        checks={},
        registry_anchor_sha256='e' * 64,
        capacity_policy_sha256='f' * 64,
        release_candidates={candidate: retained_ref['sha256']},
        release_configurations={configuration: reference_pin},
        business_entries={
            environment: {
                'data_generation': generation,
                'deployment_id': current,
                'configuration_sha256': origin.configuration_sha256,
                'origin': business,
            }
        },
    )
    manager_db = tmp_path / 'manager.sqlite'

    @contextmanager
    def registry(*args, writable=True):
        with closing(sqlite3.connect(manager_db, isolation_level=None)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
            if not writable:
                connection.execute('PRAGMA query_only=ON')
            yield connection, owned

    @contextmanager
    def read_registry(*args, **kwargs):
        with registry(writable=False) as (connection, _):
            yield connection

    with registry() as (connection, _):
        for ddl in STATEMENTS:
            connection.execute(ddl)
        connection.execute('PRAGMA user_version=1')
        connection.execute(
            'INSERT INTO manager_state VALUES (1,1,?,?,?,?)', (*scope.values(), now())
        )
        connection.execute(
            'INSERT INTO managed_environments VALUES '
            "(?,?,?,?,?,?,'ACTIVE','PREPARED',?,?,?,?,?,?,?,'OPEN',NULL)",
            (
                environment,
                'INTEGRATION',
                'Original environment',
                scope['host_id'],
                7,
                4,
                origin.configuration_sha256,
                operation_store.stored(old_ref),
                source_digest,
                profile,
                task,
                operation_store.stored(
                    {
                        'data_generation': generation,
                        'deployment_id': current,
                        'owner_label': 'Owner',
                        'baseline_commit': '9' * 40,
                        'goal': 'Current goal',
                        'scope': 'Scope',
                        'checks': 'Checks',
                        'branch': 'refs/heads/codex/fixture',
                    }
                ),
                owner,
            ),
        )

    monkeypatch.setattr(operation_contract, 'absolute', lambda value, code: Path(value))
    monkeypatch.setattr(operation_contract, 'read_protected', Path.read_bytes)
    monkeypatch.setattr(environment_installation, 'read_protected', Path.read_bytes)
    monkeypatch.setattr(release_configuration, 'absolute', lambda value, code: Path(value))
    monkeypatch.setattr(preflight, 'absolute', lambda value, code: Path(value))
    monkeypatch.setattr(
        environment_recovery_installation, 'absolute', lambda value, code: Path(value)
    )
    monkeypatch.setattr(preflight, 'load_installation', load_installation)
    monkeypatch.setattr(preflight, 'read_protected', Path.read_bytes)
    monkeypatch.setattr(
        release_observation,
        'candidate_environment',
        lambda data, pin: origin if data['installation'] == origin_ref else next_run,
    )
    monkeypatch.setattr(
        release_observation,
        'admission_inputs',
        lambda args, _, program: (
            load_installation(args.anchor, args.anchor_sha256, runtime, args.project),
            same_schema,
        ),
    )
    monkeypatch.setattr(
        release_observation, 'verify_release_details', lambda path, pin, runtime_pin: ({}, manifest)
    )
    monkeypatch.setattr(release_observation, 'read_control', lambda fd, install: dict(control))
    monkeypatch.setattr(
        release_observation, 'database_identity', lambda inst, fd: identity(input_db.stat())
    )
    monkeypatch.setattr(release_observation, 'check_stable_resources', lambda *_: None)
    monkeypatch.setattr(release_observation, 'NativeEnvironmentFiles', lambda _: None)
    monkeypatch.setattr(
        release_observation, 'os', SimpleNamespace(geteuid=lambda: 0, path=__import__('os').path)
    )
    boot = identifier()
    monkeypatch.setattr(release_observation, 'machine_clock', lambda: (boot, 1))
    monkeypatch.setattr(release_observation, 'require_fresh', lambda proof: None)
    monkeypatch.setattr(
        release_observation,
        'publish_observation',
        lambda cat, ref, proof: store(cat.directory / 'observations' / (ref + '.json'), proof),
    )
    fixed_candidate = {
        'candidate_sha256': retained_ref['sha256'],
        'manifest_sha256': manifest_ref['sha256'],
        'schema_manifest_sha256': schema_pin,
        'runtime_manifest_sha256': runtime,
        'schema_contract_sha256': schema_contract,
        'source_commit': '1' * 40,
        'target_os': 'linux',
        'target_arch': 'arm64',
        'verification_readiness': {'state': 'REQUIRED_EVIDENCE_RECORDED'},
    }
    for module in (release_operations, release_catalog_view):
        monkeypatch.setattr(module, 'candidate_inputs', lambda *args: ())
        monkeypatch.setattr(module, 'verify_candidate', lambda *args: fixed_candidate)
    monkeypatch.setattr(operation_store, 'verified_registry', registry)
    monkeypatch.setattr(release_operations, 'verified_registry', registry)
    monkeypatch.setattr(management_web, 'read_registry', read_registry)
    monkeypatch.setattr(management_web, 'verify_registered_data', lambda *args: None)
    monkeypatch.setattr(management_web, 'require_dispatch_open', lambda *args: None)
    server = management_web.ManagementScope(
        SimpleNamespace(
            origin='https://manager.walle-dev.test:9443',
            display_name='Test management',
            identities={manager.id: 'WEB', developer.id: 'WEB'},
        ),
        catalog,
        identifier(),
        now(),
        None,
        SimpleNamespace(registry_generation=scope['registry_generation']),
        runtime,
    )
    web = Starlette(routes=[Route('/{path:path}', server.respond, methods=['GET', 'POST'])])
    headers = {
        'x-wall-e-auth-principal': manager.id,
        'origin': server.web.origin,
        'x-wall-e-client': 'web-v1',
        'sec-fetch-site': 'same-origin',
        'x-wall-e-manager-id': scope['manager_id'],
        'x-wall-e-registry-generation': scope['registry_generation'],
        'x-wall-e-management-protocol': '1',
    }
    variables = {
        'environment_id': environment,
        'expected_record_version': 7,
        'expected_assignment_generation': 4,
        'configuration_ref': configuration,
        'compatibility_ref': compatibility_id,
    }
    if rollback:
        variables.update(retained_release_ref=candidate, repair_of_operation_id=None)
    elif configure:
        variables.pop('compatibility_ref')
        variables['recovery_policy_ref'] = recovery_id
    else:
        variables.update(release_ref=candidate, recovery_policy_ref=recovery_id)
    args = SimpleNamespace(release_configuration_ref=configuration, sha256=runtime, root=tmp_path)
    verify = {'verify_program': lambda path: source_digest if path == source_program else '6' * 64}
    return SimpleNamespace(
        web=web,
        server=server,
        origin=server.web.origin,
        headers=headers,
        registry=registry,
        catalog=catalog,
        action=action,
        rollback=rollback,
        configure=configure,
        business=business,
        variables=variables,
        boot=boot,
        original=origin,
        earlier=former,
        target=next_run,
        entry=verify,
        source_args=args,
        input_db=input_db,
        manager_db=manager_db,
        installations=(origin_ref, former_ref, target_ref),
        config_path=configuration_path,
        config=reference,
        fixed=manifest_ref,
        compatibility_ref=compatibility_ref,
        capacity_pin=catalog.capacity_policy_sha256,
        attachment=new_ref,
        profile=profile,
        deployment_dir=app_root / 'release-executions',
    )


def inspect_source(case):
    from backend.app.management.release_observation import capture_release_source

    observed = capture_release_source(case.catalog, case.source_args, case.entry)
    assert observed['environment_id'] == case.variables['environment_id']
    return observed


def accept(client, case):
    plan_response = client.post(
        '/management/api/v1/plans', json={'kind': case.action, **case.variables}
    )
    assert plan_response.status_code == 201, plan_response.text
    plan = plan_response.json()['data']
    wire = canonical(plan)
    assert b'previous_installation' not in wire and b'previous_project' not in wire
    request = {
        'action': case.action,
        **case.variables,
        **{key: plan[key] for key in ('plan_id', 'plan_sha256')},
    }
    key = identifier()
    response = client.post(
        '/management/api/v1/operations', json=request, headers={'Idempotency-Key': key}
    )
    assert response.status_code == 202, response.text
    return plan, request, key, response.json()['data']['operation']


def selection_for(case, grant, monkeypatch):
    """Commit the original selection to an owned control directory."""
    from backend.app.infrastructure import environment_release_preflight as preflight
    from backend.app.management import release_configuration, release_execution, release_selection
    from backend.app.management.release_observation import ReleasePair

    configuration = release_configuration.read_configuration(
        case.catalog, case.variables['configuration_ref']
    )
    admitted = release_execution.AdmittedRelease(
        grant, configuration, ReleasePair(case.original, case.target)
    )
    operation = grant['operation_id']
    folder = case.deployment_dir / operation
    hold = {
        'control_revision': grant['source']['control_revision'] + 1,
        'maintenance_policy_sha256': '1' * 64,
    }
    proof = store(
        folder / preflight.CANDIDATE_PROOF,
        {
            'candidate_sha256': grant['release_candidate_sha256'],
            'manifest_sha256': grant['release_manifest_sha256'],
        },
    )
    offhost = grant['recovery_requirement'] == 'OFFHOST_VERIFIED'
    policy = {
        'format_version': 2 if offhost else 1,
        'operation_id': operation,
        'installation_sha256': case.original.anchor_sha256,
        'target_manifest': case.fixed,
        'compatibility_ref': case.compatibility_ref,
        'candidate_proof': proof,
    }
    if case.rollback:
        policy.update(case.config['rollback_source'])
    if case.configure:
        policy['target_access_sha256'] = case.config['target_access_sha256']
    offhost_pin = None
    names = preflight.LOCAL_PREFLIGHT
    if offhost:
        names = preflight.OFFHOST_PREFLIGHT
        policy['offhost_authority'] = configuration.recovery['offhost_authority']
        report = {'path': str(folder / 'verified-offhost.v1.json'), 'sha256': '4' * 64}
        policy['offhost_verification'] = report
        offhost_pin = report['sha256']
        missing = store(folder / preflight.LOCAL_PREFLIGHT[configuration.deployment_mode], policy)
        with pytest.raises(EnvironmentFailure):
            release_selection.check_preflight_request(
                SimpleNamespace(
                    release_preflight_policy=Path(missing['path']),
                    release_preflight_policy_sha256=missing['sha256'],
                ),
                admitted,
            )
    name = names[configuration.deployment_mode]
    low_level = folder / name
    reference = store(low_level, policy)
    args = SimpleNamespace(
        release_preflight_policy=low_level, release_preflight_policy_sha256=reference['sha256']
    )
    assert release_selection.check_preflight_request(args, admitted) == reference
    if offhost:
        changed = {
            **policy,
            'offhost_authority': {**policy['offhost_authority'], 'repository_id': '9' * 64},
        }
        wrong = store(folder / 'foreign' / name, changed)
        with pytest.raises(EnvironmentFailure, match=release_configuration.CHANGED):
            release_selection.check_preflight_request(
                SimpleNamespace(
                    release_preflight_policy=Path(wrong['path']),
                    release_preflight_policy_sha256=wrong['sha256'],
                ),
                admitted,
            )
    receipt = {
        'format_version': 1,
        'status': 'CLOSED_RELEASE_PRECONDITIONS_VERIFIED',
        'mode': configuration.deployment_mode,
        'preflight_policy_sha256': reference['sha256'],
        'operation_id': operation,
        'maintenance_plan_sha256': hold['maintenance_policy_sha256'],
        'source_environment_id': grant['environment_id'],
        'source_data_generation': case.original.data_generation,
        'source_deployment_id': case.original.deployment_id,
        'source_control_revision': hold['control_revision'],
        'source_configuration_sha256': case.original.configuration_sha256,
        'target_release_id': grant['release_ref'],
        'target_release_manifest_sha256': grant['release_manifest_sha256'],
        'target_program_snapshot_sha256': grant['target']['program_sha256'],
        'schema_contract_sha256': grant['schema_contract_sha256'],
        'compatibility_id': configuration.compatibility_reference['ref'],
        'backup_id': identifier(),
        'backup_manifest_sha256': '2' * 64,
        'backup_local_verification_sha256': '3' * 64,
    }
    if offhost:
        receipt['backup_offhost_verification_sha256'] = offhost_pin
        wrong = {**receipt, 'backup_offhost_verification_sha256': '8' * 64}
        with pytest.raises(EnvironmentFailure):
            release_selection.check_preflight_receipt(
                {**wrong, 'release_preflight_sha256': digest(canonical(wrong))},
                admitted,
                hold,
                reference['sha256'],
                offhost_pin,
            )
    if case.rollback:
        receipt.update(
            previous_fixed_deployment_id=case.earlier.deployment_id,
            previous_installation_sha256=case.earlier.anchor_sha256,
        )
        wrong = {**receipt, 'previous_fixed_deployment_id': identifier()}
        with pytest.raises(EnvironmentFailure):
            release_selection.check_preflight_receipt(
                {**wrong, 'release_preflight_sha256': digest(canonical(wrong))},
                admitted,
                hold,
                reference['sha256'],
                offhost_pin,
            )
    if case.configure:
        receipt['target_access_sha256'] = case.config['target_access_sha256']
    receipt['release_preflight_sha256'] = digest(canonical(receipt))
    release_selection.check_preflight_receipt(
        receipt, admitted, hold, reference['sha256'], offhost_pin
    )
    measured, policy_pin = switch_deployment(case, admitted, hold, receipt, reference, monkeypatch)
    selected = release_selection.selection_result(measured, admitted, hold, receipt, policy_pin)
    pin = store(folder / release_selection.SELECTED, selected)['sha256']
    return selected, pin


@pytest.mark.parametrize('conflict', ('host-hold', 'changed-control', None))
def test_deployment_selection_guards_both_persistent_writes(monkeypatch, conflict):
    pytest.importorskip('fcntl')
    from backend.app.infrastructure import environment_release_switch as switch

    events = []

    @contextmanager
    def guard_host():
        events.append('host-enter')
        if conflict == 'host-hold':
            raise EnvironmentFailure('HOST_RECOVERY_HOLD')
        try:
            yield
        finally:
            events.append('host-exit')

    def verify_owner():
        assert events[0] == 'host-enter' and events[-1] != 'host-exit'
        events.append('owner')

    before = {'admission': 'CLOSED', 'control_revision': 9}
    after = {**before, 'control_revision': 10}
    visible = before if conflict != 'changed-control' else {**before, 'control_revision': 8}
    saved_transition = None
    source = SimpleNamespace(anchor_sha256='1' * 64)
    target = SimpleNamespace(
        anchor_sha256='2' * 64, check_hold=lambda: None, host_admission=guard_host
    )
    selection = switch.ReleaseSelection(
        '3' * 64,
        identifier(),
        source,
        target,
        SimpleNamespace(release_preflight_policy_sha256='4' * 64),
        '5' * 64,
    )
    lock = SimpleNamespace(assert_owned=verify_owner)

    def write_transition(fd, installation, name, transition, *, create):
        nonlocal saved_transition
        assert installation is source and create
        assert events[0] == 'host-enter' and events[-1] != 'host-exit'
        assert name == switch.release_transition_name(selection.operation_id)
        saved_transition = transition
        events.append('transition')

    def write_control(fd, name, raw, *, mode, replace):
        nonlocal visible
        assert events[0] == 'host-enter' and events[-1] != 'host-exit'
        assert name == switch.CONTROL_NAME and replace and mode == 0o640
        visible = json.loads(raw)
        events.append('control')

    monkeypatch.setattr(switch, 'read_control', lambda fd, installation: visible)
    monkeypatch.setattr(switch, 'selected_release_control', lambda current, target: after)
    monkeypatch.setattr(switch, 'write_fact', write_transition)
    monkeypatch.setattr(switch, 'original_transition', lambda fd, selection: saved_transition)
    monkeypatch.setattr(switch, 'persisted_write', write_control)
    monkeypatch.setattr(switch, 'selected_receipt', lambda fd, selection, transition: transition)
    errors = {'host-hold': 'HOST_RECOVERY_HOLD', 'changed-control': switch.DIFFERENT}
    if conflict is not None:
        with pytest.raises(EnvironmentFailure, match=errors[conflict]):
            switch.commit_selection(selection, before, 0, lock)
        assert 'transition' not in events and 'control' not in events
        assert saved_transition is None
        assert visible['control_revision'] == (9 if conflict == 'host-hold' else 8)
    else:
        result = switch.commit_selection(selection, before, 0, lock)
        assert result == saved_transition and result['before'] == before
        assert visible == after
        assert events == ['host-enter', 'owner', 'transition', 'owner', 'control', 'host-exit']


@contextmanager
def switch_control_directory(path, patches):
    from backend.app.infrastructure import environment_control, environment_maintenance
    from backend.app.infrastructure import environment_release_switch as switch

    if os.name != 'nt':
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            yield descriptor
        finally:
            os.close(descriptor)
        return

    def publish(directory, name, raw, *, mode, replace=False):
        with NamedTemporaryFile(dir=directory, delete=False) as pending:
            temporary = Path(pending.name)
            pending.write(raw)
            pending.flush()
            os.fsync(pending.fileno())
        try:
            target = directory / name
            if replace:
                os.replace(temporary, target)
            else:
                os.link(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def stat(name, *, dir_fd, follow_symlinks):
        return (dir_fd / name).stat(follow_symlinks=follow_symlinks)

    for module in (environment_control, environment_maintenance):
        patches.setattr(
            module, 'read_entry', lambda directory, name, **_: (directory / name).read_bytes()
        )
    patches.setattr(environment_control, 'os', SimpleNamespace(stat=stat))
    patches.setattr(environment_maintenance, 'persisted_write', publish)
    patches.setattr(switch, 'persisted_write', publish)
    patches.setattr(switch, 'os', SimpleNamespace(fsync=lambda directory: None))
    yield path


def switch_deployment(case, admitted, hold, receipt, reference, monkeypatch):
    from backend.app.infrastructure import environment_backup_package as backup
    from backend.app.infrastructure import environment_control as control
    from backend.app.infrastructure import environment_maintenance as maintenance_stage
    from backend.app.infrastructure import environment_recovery_installation as recovery
    from backend.app.infrastructure import environment_release_switch as switch
    from backend.app.infrastructure.environment_maintenance import write_fact
    from backend.app.management.release_selection import switch_policy

    source, target = admitted.pair.source, admitted.pair.target
    directory = source.environment_root / 'control'
    operation = admitted.grant['operation_id']
    policy = switch_policy(admitted, reference, receipt)
    path = case.deployment_dir / operation / switch.POLICY
    policy_ref = store(path, policy)
    arguments = SimpleNamespace(
        release_switch_policy=path,
        release_switch_policy_sha256=policy_ref['sha256'],
        anchor=source.anchor,
        anchor_sha256=source.anchor_sha256,
        root=path.parent,
        home=path.parent,
        temporary=path.parent,
        project=source.project,
        program_sha256=source.description['program_source']['sha256'],
    )
    stopped = control.initial_control(source, identifier())
    stopped['control_revision'] = hold['control_revision'] - 1
    maintenance = {
        'format_version': 1,
        'operation_id': operation,
        'plan_sha256': hold['maintenance_policy_sha256'],
        'before_sha256': digest(canonical(stopped)),
        'before': stopped,
    }
    before = control.maintained_control(stopped, operation, maintenance['plan_sha256'])
    original_digest = digest(case.input_db.read_bytes())
    database_identity = identity(case.input_db.stat())
    coverage = {'logical_content_sha256': original_digest}
    measured = SimpleNamespace(receipt=receipt, coverage=coverage, capture_arguments=object())
    installations = {source.anchor: source, target.anchor: target}
    lock = SimpleNamespace(assert_owned=lambda: None)

    def load_installation(args, active, program_pin, *, offline):
        assert offline
        installation = installations[args.anchor]
        assert installation.anchor_sha256 == args.anchor_sha256
        assert installation.description['program_source']['sha256'] == program_pin
        return installation, None

    def load_preflight(active, args, entry):
        assert args.release_preflight_policy == Path(reference['path'])
        assert args.release_preflight_policy_sha256 == reference['sha256']
        return measured

    with monkeypatch.context() as patches, switch_control_directory(directory, patches) as fd:

        @contextmanager
        def verified_coverage(native, active, args, entry, *, require_clean_database):
            assert require_clean_database
            assert args is measured.capture_arguments
            assert digest(case.input_db.read_bytes()) == original_digest
            with source.lock(native):
                yield SimpleNamespace(
                    installation=source,
                    facts=coverage,
                    control=control.read_control(fd, source),
                    control_fd=fd,
                    lock=lock,
                    database_identity=database_identity,
                )

        patches.setattr(backup, 'read_protected', Path.read_bytes)
        for module in (switch, recovery):
            patches.setattr(module, 'absolute', lambda value, _: Path(value))
        patches.setattr(switch, 'admission_inputs', load_installation)
        patches.setattr(switch, 'preflight_inputs', load_preflight)
        patches.setattr(switch, 'locked_coverage', verified_coverage)
        for installation in (source, target):
            patches.setattr(
                installation,
                'roots',
                {'data': case.input_db.parent, 'control': directory},
                raising=False,
            )
            patches.setattr(installation, 'restore_generation_sha256', None, raising=False)
            patches.setattr(
                installation,
                'maintenance_uid',
                os.getuid() if os.name != 'nt' else 0,
                raising=False,
            )
            patches.setattr(
                installation, 'application_uid', installation.maintenance_uid, raising=False
            )
            patches.setattr(
                installation, 'group', os.getgid() if os.name != 'nt' else 0, raising=False
            )
            patches.setattr(installation, 'directory', lambda native, kind: nullcontext(fd))
        patches.setattr(source, 'check_identity', lambda *, maintenance: None, raising=False)
        write_fact(fd, source, control.maintenance_name(operation), maintenance, create=True)
        switch.persisted_write(fd, control.CONTROL_NAME, canonical(before), mode=0o640)
        assert control.read_control(fd, source) == before
        patches.setattr(target, 'ingress_group', 4004, raising=False)
        verifier = {'principal_id': 'probe', 'client_kind': 'AUTOMATION', 'permission': 'DEVELOP'}
        access = {
            'environment_id': target.environment_id,
            'public_origin': 'https://scope.example.test',
            'upstream_socket': str(directory / 'walle.sock'),
            'principals': [verifier],
        }
        patches.setattr(switch, 'read_access_policy', lambda installation: access)
        transition_path = directory / control.release_transition_name(operation)
        with pytest.raises(EnvironmentFailure, match='RELEASE_GATEWAY_VERIFIER_REQUIRED'):
            switch.select_release_deployment(None, None, arguments, case.entry)
        assert not transition_path.exists()
        assert control.read_control(fd, source) == before
        assert digest(case.input_db.read_bytes()) == original_digest
        verifier['permission'] = 'READ_ONLY'

        # The final reply is lost even though both facts have reached disk.
        with monkeypatch.context() as interruption:

            def lost_reply(*args):
                raise EnvironmentFailure('TEST_REPLY_LOST', uncertain=True)

            interruption.setattr(switch, 'selected_receipt', lost_reply)
            with pytest.raises(EnvironmentFailure, match='TEST_REPLY_LOST'):
                switch.select_release_deployment(None, None, arguments, case.entry)
        transition_raw = transition_path.read_bytes()
        if os.name == 'nt':
            patches.setattr(maintenance_stage, 'os', SimpleNamespace(stat=control.os.stat))
        with pytest.raises(EnvironmentFailure, match=maintenance_stage.UNKNOWN):
            maintenance_stage.require_before_selection(fd, operation)
        selected_raw = (directory / control.CONTROL_NAME).read_bytes()
        selected = control.read_control(fd, target)
        assert selected['deployment_id'] == target.deployment_id
        assert selected['data_generation'] == stopped['data_generation']
        assert selected['data_root_ref'] == stopped['data_root_ref']
        assert selected['outbound_hold'] and selected['admission'] == 'CLOSED'
        assert selected['closed_reason'] == 'RECOVERY_REQUIRED'

        def unexpected_preflight(*args):
            pytest.fail('The original selection must replay without preflight.')

        patches.setattr(switch, 'preflight_inputs', unexpected_preflight)
        patches.setattr(switch, 'gateway_verifier_names', unexpected_preflight)

        @contextmanager
        def frozen_host():
            pytest.fail('A persisted selection must remain readable when the host is frozen.')
            yield

        patches.setattr(target, 'host_admission', frozen_host)

        def reject_host_hold():
            raise EnvironmentFailure('HOST_RECOVERY_HOLD')

        patches.setattr(source, 'check_hold', reject_host_hold)
        result = switch.select_release_deployment(None, None, arguments, case.entry)
        assert result['transition_sha256'] == digest(transition_raw)
        assert result['control_sha256'] == digest(selected_raw)
        foreign = {**policy, 'release_preflight_sha256': '8' * 64}
        other = store(path.parent / 'other' / switch.POLICY, foreign)
        altered = SimpleNamespace(
            **{
                **vars(arguments),
                'release_switch_policy': Path(other['path']),
                'release_switch_policy_sha256': other['sha256'],
            }
        )
        with pytest.raises(EnvironmentFailure, match='RELEASE_SWITCH_REPLAN_REQUIRED'):
            switch.select_release_deployment(None, None, altered, case.entry)
        assert transition_path.read_bytes() == transition_raw
        assert (directory / control.CONTROL_NAME).read_bytes() == selected_raw
    assert digest(case.input_db.read_bytes()) == original_digest
    return result, policy_ref['sha256']


def record_open(case, grant, selected, selection_pin, monkeypatch):
    from backend.app.infrastructure import environment_release_open
    from backend.app.management import (
        release_open_admission,
        release_runtime,
        runtime_capacity,
        runtime_observation,
    )
    from backend.app.management.attachment_observation import now

    operation = grant['operation_id']
    folder = case.deployment_dir / operation
    capacities = runtime_capacity.MINIMUM.copy()
    capacity = runtime_capacity.CapacityPolicy(
        case.capacity_pin,
        folder,
        folder.parent,
        dict(capacities),
        {'INTEGRATION': {'profile_ref': case.profile, 'limits': dict(capacities)}},
    )
    monkeypatch.setattr(release_open_admission, 'machine_clock', lambda: (case.boot, 1))
    monkeypatch.setattr(release_open_admission, 'load_capacity', lambda _: capacity)
    monkeypatch.setattr(
        runtime_capacity, 'available_memory_bytes', lambda: capacities['memory_bytes']
    )
    monkeypatch.setattr(runtime_observation, 'absolute', lambda value, code: Path(value))
    request = {
        'operation_id': operation,
        'run_id': identifier(),
        'boot_id': case.boot,
        'limits': capacities,
        **{key: selected[key] for key in release_open_admission.TARGET},
        'selection_receipt_sha256': selection_pin,
        'open_policy_sha256': '7' * 64,
        'launch_policy_sha256': '8' * 64,
        'capacity_sha256': capacity.sha256,
    }
    with case.registry() as (connection, lock):
        authorized = release_open_admission.admit_release_open(
            connection, lock, case.catalog, request
        )
        assert authorized['status'] == release_open_admission.OPEN_AUTHORIZED
        assert (
            release_open_admission.admit_release_open(connection, lock, case.catalog, request)
            == authorized
        )
        assert len(runtime_capacity.reservations_for(connection, operation)) == 4
    observe = {
        'proof_id': identifier(),
        'environment_id': grant['environment_id'],
        'observed_at': now(),
        'state': 'RUNNING',
        'reason_code': 'MANAGED_APPLICATION_READY',
    }
    runtime = store(
        case.catalog.directory
        / 'observations'
        / ('start-runtime-' + operation)
        / release_runtime.RUNTIME_POLICY,
        {
            'format_version': 1,
            **case.catalog.scope,
            'candidate_ref': case.attachment['candidate_ref'],
            'candidate_sha256': case.attachment['sha256'],
            **{key: request[key] for key in ('operation_id', 'run_id', 'boot_id')},
            'invocation_id': '9' * 32,
            'start_sha256': request['open_policy_sha256'],
            'systemctl_sha256': 'a' * 64,
            'launcher': {'path': str(folder / 'launcher.py'), 'sha256': 'b' * 64},
            'home': str(folder),
            'temporary': str(folder.parent),
            'memory_bytes': capacities['memory_bytes'],
            'tasks': capacities['tasks'],
            'cpu_quota_usec': capacities['cpu_percent'] * 1000,
            'cpu_period_usec': 100_000,
            'release_open_policy': {
                'path': str(folder / environment_release_open.POLICY),
                'sha256': request['open_policy_sha256'],
            },
        },
    )
    opened = {
        'status': 'RELEASE_OPEN_CONFIRMED',
        'admission': 'OPEN',
        **{key: request[key] for key in ('operation_id', 'run_id', *release_open_admission.TARGET)},
        'control_revision': selected['control_revision'] + 1,
        'open_receipt_sha256': 'c' * 64,
        'opened_at': now(),
    }
    store(
        folder / release_runtime.DISPATCH,
        {
            'format_version': 1,
            'request': request,
            'unit': f'walle-env-{grant["environment_id"]}-{operation}.service',
        },
    )
    receipt = release_runtime.confirmed_opening(opened, runtime, observe, request, selected)
    store(folder / release_runtime.OPENED, receipt)
    return request


def verify_recovered_registry(case, grant, request, monkeypatch):
    from backend.app.management import (
        registry_recovery,
        runtime_capacity,
    )
    from backend.app.management import (
        registry_recovery_deployment_settlement as settlement,
    )
    from backend.app.management import (
        registry_recovery_disposition_receipts as receipts,
    )
    from backend.app.management import (
        registry_recovery_opened as opening,
    )
    from backend.app.management import (
        registry_recovery_outcome as outcome,
    )
    from backend.app.management import (
        registry_schema as schema,
    )
    from backend.app.management.attachment_observation import now
    from backend.app.management.operation_store import decoded, environment_row

    original = grant['operation_id']
    selected = identifier()
    recovery = identifier()
    readback = case.manager_db.parent / ('selected-' + selected + '.sqlite')
    initialized = now()
    basis = case.manager_db.read_bytes()
    pin = digest(basis)
    current = SimpleNamespace(
        **{key: case.catalog.scope[key] for key in ('manager_id', 'host_id')},
        registry_generation=selected,
        sha256='5' * 64,
    )
    with (
        case.registry(writable=False) as (archived, _),
        closing(sqlite3.connect(readback, isolation_level=None)) as connection,
    ):
        historic = archived.execute(
            'SELECT * FROM management_operations WHERE operation_id=?', (original,)
        ).fetchone()
        policy = {
            **case.catalog.scope,
            'registry_generation': selected,
            'registry_anchor_sha256': current.sha256,
            'source_registry_generation': historic['registry_generation'],
            'source_revision': historic['revision'],
            'source_intent_sha256': historic['intent_sha256'],
            'operation_id': original,
            'recovery_operation_id': recovery,
            'selection_receipt_sha256': '3' * 64,
            'authorization_sha256': '4' * 64,
        }
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('ATTACH DATABASE ? AS original', (str(case.manager_db),))
        registry_recovery.populate_database(
            connection,
            {
                **case.catalog.scope,
                'target_registry_generation': selected,
                'schema_version': (
                    schema.RECONFIGURATION_RECOVERY_SCHEMA_VERSION
                    if case.configure
                    else schema.ROLLBACK_RECOVERY_SCHEMA_VERSION
                ),
            },
            1,
            initialized,
        )
        connection.row_factory = sqlite3.Row
        expected_schema = {'RECONFIGURE': 7, 'ROLLBACK_CODE': 6, 'RELEASE': 5}[case.action]
        assert (
            outcome.disposition_schema(outcome.OPENED_DEPLOYMENT, action=case.action)
            == expected_schema
        )
        monkeypatch.setattr(opening, 'candidate_environment', lambda *_: case.target)
        source, projected, evidence = opening.opened_registration_projection(
            archived,
            case.catalog,
            policy,
            case.source_args.sha256,
        )
        assert evidence['action'] == case.action and projected['record_version'] == 8
        assert (
            decoded(projected['work_package_json'])['data_generation'] == request['data_generation']
        )
        proposal = opening.assessment_result(current, policy, pin, evidence)
        authorization = {
            'assessment_sha256': proposal['assessment_sha256'],
            'verification': {
                'recovery_operation_id': recovery,
                'source_registry_generation': policy['source_registry_generation'],
                'selection_receipt_sha256': policy['selection_receipt_sha256'],
                'environment_id': request['environment_id'],
                'opened_receipt_sha256': evidence['opened_receipt_sha256'],
                'target': {
                    **{
                        key: request[key]
                        for key in (
                            'environment_id',
                            'data_generation',
                            'deployment_id',
                            'configuration_sha256',
                            'run_id',
                        )
                    },
                    'program_sha256': projected['program_source'],
                },
                'management_entry': {'candidate_sha256': case.attachment['sha256']},
                'stop_operation_id': identifier(),
                'stop_receipt_sha256': '6' * 64,
            },
        }
        confirmed_receipt = case.manager_db.parent / 'local-proof'
        confirmed_receipt.mkdir()
        available = []

        def received(folder, operation, installation):
            assert folder == confirmed_receipt and operation == original and installation == current
            return available[0] if available else None

        def published(folder, file, raw, *, mode):
            assert folder == confirmed_receipt and file == original + '.json' and mode == 0o400
            assert not available
            available.append(raw)
            (folder / file).write_bytes(raw)

        def verify_scope():
            assert case.manager_db.read_bytes() == basis

        monkeypatch.setattr(settlement, 'authorized_deployment', lambda *args: authorization)
        monkeypatch.setattr(settlement, 'receipt_bytes', received)
        monkeypatch.setattr(settlement, 'persisted_write', published)
        args = SimpleNamespace(
            sha256=case.source_args.sha256, registry_disposition_policy_sha256='7' * 64
        )
        lock = SimpleNamespace(assert_owned=lambda: None)
        before = dict(environment_row(connection, grant['environment_id']))
        assert before == dict(source)
        outcome_record = settlement.settle_in_registry(
            connection,
            lock,
            confirmed_receipt,
            current,
            case.catalog,
            args,
            policy,
            archived,
            pin,
            verify_scope,
        )
        audit = receipts.read_permitted_receipt(
            available[0],
            original,
            current,
            {
                'operation_id': recovery,
                'selection_receipt_sha256': policy['selection_receipt_sha256'],
                'source_registry_generation': policy['source_registry_generation'],
            },
            pin,
        )
        assert audit == outcome_record and audit['evidence']['action'] == case.action
        assert not runtime_capacity.reservations_for(connection, original)
        preserved = connection.execute(
            'SELECT status,revision FROM management_operations WHERE operation_id=?', (original,)
        ).fetchone()
        assert tuple(preserved) == ('RUNNING', 3)
        assert dict(environment_row(connection, grant['environment_id'])) == projected
        assert (
            settlement.settle_in_registry(
                connection,
                lock,
                confirmed_receipt,
                current,
                case.catalog,
                args,
                policy,
                archived,
                pin,
                verify_scope,
            )
            == outcome_record
        )
        assert len(available) == 1
    assert case.manager_db.read_bytes() == basis


def prepare_strict_restore(case, patches, stopped, manifest, package, local, remote, authority):
    from backend.app.infrastructure import environment_restore_preflight
    from backend.app.infrastructure.environment_backup_package import VERIFY_POLICY
    from backend.app.infrastructure.environment_release_deployment import RESTORE_POLICY
    from backend.app.management import restore_catalog_view, restore_operations

    root = case.catalog.directory
    environment = case.variables['environment_id']
    release = case.config['release_ref']
    candidate = case.catalog.release_candidates[release]
    configuration, recovery, operation, preserved = (identifier() for _ in range(4))
    target_generation, target_deployment, attachment = (identifier() for _ in range(3))
    policy = store(
        root / 'release-recovery-policies' / (recovery + '.json'),
        {
            'format_version': 2,
            **case.catalog.scope,
            'ref': recovery,
            'preserve_source': True,
            'minimum_verification': 'OFFHOST_VERIFIED',
            'offhost_authority': authority,
        },
    )
    verification = store(
        root / operation / VERIFY_POLICY,
        {
            'format_version': 1,
            'backup_id': manifest['backup_id'],
            'package_directory': package['path'],
            'package_identity': package['identity'],
            'backup_manifest_sha256': package['sha256'],
        },
    )
    deployment = {
        'installation_sha256': case.original.anchor_sha256,
        'source_deployment_id': stopped['deployment_id'],
        'operation_id': operation,
        'target_data_generation': target_generation,
        'target_deployment_id': target_deployment,
        'target_manifest': case.fixed,
        'target_schema_directory': str(case.original.schema),
        'candidate_proof': {'path': str(root / operation / 'proof.json'), 'sha256': 'a' * 64},
    }
    preflight = {
        'format_version': 2,
        **deployment,
        'source_data_generation': stopped['data_generation'],
        'source_control_revision': stopped['control_revision'] + 1,
        'source_configuration_sha256': stopped['configuration_sha256'],
        'target_configuration_sha256': 'b' * 64,
        'preserved': {'backup_id': preserved, 'capture_policy': None, 'verification': None},
        'selected': {
            'backup_id': manifest['backup_id'],
            'verification': verification,
            'local_verification': local,
        },
        'accepted_backup_cutoff_at': manifest['cutoff_at'],
        'data_handling': 'PRESERVE_CURRENT_SOURCE',
        'data_preparation': {
            'path': str(root / operation / 'backup-package-rehearsal.v1.json'),
            'sha256': 'c' * 64,
        },
        'offhost_authority': authority,
        'offhost_verification': remote,
    }
    template = store(root / operation / environment_restore_preflight.OFFHOST_POLICY, preflight)
    configuration_record = {
        'format_version': 1,
        **case.catalog.scope,
        'configuration_ref': configuration,
        'environment_id': environment,
        'release_ref': release,
        'release_candidate_sha256': candidate,
        'source_attachment': case.config['source_attachment'],
        'target_attachment_ref': attachment,
        'source_control_sha256': digest(canonical(stopped)),
        'source_database_identity_sha256': digest(canonical(identity(case.input_db.stat()))),
        'deployment_policy': store(root / operation / RESTORE_POLICY, deployment),
        'preflight_template': template,
        'recovery_policy': {'ref': recovery, 'sha256': policy['sha256']},
    }
    path = root / 'restore-configurations' / (configuration + '.json')
    case.catalog.restore_configurations[configuration] = store(path, configuration_record)['sha256']
    patches.setattr(environment_restore_preflight, 'read_protected', Path.read_bytes)
    patches.setattr(restore_operations, 'verified_registry', case.registry)
    for module in (restore_operations, restore_catalog_view):
        patches.setattr(module, 'confirmed_current_control', lambda *_: stopped)

    def candidate_target(actual_template, active):
        assert actual_template == preflight
        assert active.runtime_manifest_sha256 == case.source_args.sha256
        schema = SimpleNamespace(schema_contract_sha256='d' * 64)
        return (
            {
                'candidate_sha256': candidate,
                'schema_contract_sha256': schema.schema_contract_sha256,
            },
            {'release_id': release},
            schema,
            'e' * 64,
        )

    patches.setattr(restore_operations, 'candidate_target', candidate_target)
    return {
        'environment_id': environment,
        'expected_record_version': 7,
        'expected_assignment_generation': 4,
        'backup_id': manifest['backup_id'],
        'target_release_ref': release,
        'target_configuration_ref': configuration,
        'recovery_policy_ref': recovery,
        'source_data_generation': stopped['data_generation'],
    }, operation


def test_strict_managed_backup_keeps_the_local_point_until_independent_retrieval(
    deployment, monkeypatch
):
    from backend.app.infrastructure.environment_restic_contract import BACKUP_POINT_FIELDS, VERSION
    from backend.app.management import backup_capture, backup_completion, backup_operations
    from backend.app.management.attachment_observation import now

    case = deployment
    reference = identifier()
    environment = case.variables['environment_id']
    authority = {
        'source_host_id': case.catalog.scope['host_id'],
        'verification_host_id': identifier(),
        'verification_anchor_sha256': 'a' * 64,
        'storage_profile_sha256': 'b' * 64,
        'repository_id': 'c' * 64,
        'observation_max_age_seconds': 3600,
    }
    policy = {
        'format_version': 2,
        **case.catalog.scope,
        'backup_policy_ref': reference,
        'environment_id': environment,
        'minimum_verification': 'OFFHOST_VERIFIED',
        'offhost_authority': authority,
        'assets': list(backup_operations.ASSETS),
        'max_database_bytes': 1024**2,
        'max_audit_files': 10,
        'max_audit_bytes': 1024**2,
    }
    proof = store(case.catalog.directory / 'backup-policies' / (reference + '.json'), policy)
    case.catalog.backup_policies[reference] = proof['sha256']
    source = case.original
    monkeypatch.setattr(backup_operations, 'verified_registry', case.registry)
    stopped = {
        'admission': 'CLOSED',
        'closed_reason': 'NORMAL_STOP',
        'control_revision': 9,
        'environment_id': environment,
        'configuration_sha256': source.configuration_sha256,
        'program_sha256': source.description['program_source']['sha256'],
        'deployment_id': source.deployment_id,
        'data_generation': source.data_generation,
        'operation_id': identifier(),
    }
    monkeypatch.setattr(backup_operations, 'confirmed_current_control', lambda *_: stopped)
    with TestClient(case.web, base_url=case.origin, headers=case.headers) as client:
        options = client.get(
            '/management/api/v1/catalog', params={'environment_id': environment, 'kind': 'BACKUP'}
        )
        assert options.status_code == 200
        assert options.json()['data']['backup_options'][0]['state'] == 'READY'
        preview = {
            'kind': 'BACKUP',
            'environment_id': environment,
            'expected_record_version': 7,
            'expected_assignment_generation': 4,
            'backup_policy_ref': reference,
            'after_completion': 'KEEP_STOPPED',
        }
        proposed = client.post('/management/api/v1/plans', json=preview)
        assert proposed.status_code == 201, proposed.text
        plan = proposed.json()['data']
        assert plan['preview']['minimum_verification'] == 'OFFHOST_VERIFIED'
        request = {
            **{key: preview[key] for key in preview if key != 'kind'},
            'action': 'BACKUP',
            'plan_id': plan['plan_id'],
            'plan_sha256': plan['plan_sha256'],
        }
        response = client.post(
            '/management/api/v1/operations', json=request, headers={'Idempotency-Key': identifier()}
        )
        assert response.status_code == 202, response.text
        operation = response.json()['data']['operation']['operation_id']
        with case.registry() as (connection, lock):
            request = {'operation_id': operation, 'allow_pending': False}
            with pytest.raises(EnvironmentFailure):
                backup_capture.observe_backup(connection, case.catalog, request)
            original_grant = backup_capture.observe_backup(
                connection, case.catalog, {**request, 'allow_pending': True}
            )
            claim = {'operation_id': operation, 'grant_sha256': digest(canonical(original_grant))}
            with pytest.raises(EnvironmentFailure, match=backup_capture.CHANGED):
                backup_capture.claim_backup(
                    connection, lock, case.catalog, {**claim, 'grant_sha256': '0' * 64}
                )
            accepted, step = backup_capture.backup_record(connection, case.catalog, operation)
            assert (accepted['status'], step['status'], step['external_identity_json']) == (
                'ACCEPTED',
                'PLANNED',
                None,
            )
            grant = backup_capture.claim_backup(connection, lock, case.catalog, claim)
            assert grant == original_grant
            assert backup_capture.observe_backup(connection, case.catalog, request) == grant
            running, step = backup_capture.backup_record(connection, case.catalog, operation)
            assert (running['status'], running['revision'], step['status']) == (
                'RUNNING',
                accepted['revision'] + 1,
                'DISPATCHING',
            )
        assert grant['offhost_authority'] == authority
        folder = case.catalog.directory / backup_capture.EXECUTIONS / operation
        folder.mkdir(parents=True)
        package = folder / 'sealed'
        package.mkdir()
        database = package / 'database.sqlite'
        original = case.input_db.read_bytes()
        with (
            closing(sqlite3.connect(case.input_db)) as active,
            closing(sqlite3.connect(database)) as copy,
        ):
            active.backup(copy)
            assert copy.execute('SELECT body FROM document').fetchone()[0]
        stored_db = database.read_bytes()
        cutoff = now()
        captured = {
            'format_version': 1,
            'status': 'MANAGED_BACKUP_CAPTURED',
            'operation_id': operation,
            'environment_id': environment,
            'backup_id': grant['backup_id'],
            'data_generation': source.data_generation,
            'deployment_id': source.deployment_id,
            'control_revision': stopped['control_revision'],
            'cutoff_at': cutoff,
            'grant_sha256': digest(canonical(grant)),
            'capture_policy_sha256': '1' * 64,
            'capture_receipt_sha256': '2' * 64,
            'database_sha256': digest(stored_db),
            'database_bytes': len(stored_db),
        }
        store(folder / backup_capture.CAPTURED, captured)
        manifest = {
            'backup_id': grant['backup_id'],
            'source_environment_id': environment,
            'source_data_generation': captured['data_generation'],
            'source_deployment_id': captured['deployment_id'],
            'source_control_revision': captured['control_revision'],
            'cutoff_at': cutoff,
            'logical_content_sha256': '3' * 64,
            'capture_receipt_ref': {'sha256': captured['capture_receipt_sha256']},
            'database_artifact': {'sha256': captured['database_sha256'], 'bytes': len(stored_db)},
            'program_and_configuration_refs': {
                'program_sha256': grant['source']['program_sha256'],
                'configuration_sha256': grant['source']['configuration_sha256'],
            },
        }
        manifest_ref = store(package / 'backup-manifest.v1.json', manifest)
        verify_id = identifier()
        witness = {
            'format_version': 1,
            'status': 'LOCAL_VERIFIED',
            'verification_id': verify_id,
            'verification_policy_sha256': '4' * 64,
            'backup_id': grant['backup_id'],
            'backup_manifest_sha256': manifest_ref['sha256'],
            'runtime_manifest_sha256': '5' * 64,
            'schema_manifest_sha256': '6' * 64,
            'program_snapshot_sha256': '7' * 64,
            'frontend_index_sha256': '8' * 64,
            'rehearsal_receipt_sha256': '9' * 64,
            'recovery_read_policy_sha256': '0' * 64,
            'environment_id': environment,
            'data_generation': identifier(),
            'deployment_id': identifier(),
            'configuration_sha256': 'a' * 64,
            'control_revision': 1,
            'run_id': identifier(),
            'verified_at': cutoff,
            'verified_scopes': ['DOCUMENT_CONTENT', 'DOCUMENT_HISTORY'],
            'database_sha256': captured['database_sha256'],
            'logical_content_sha256': manifest['logical_content_sha256'],
            'document_lookup': {'requirement_id': 1, 'document_id': 1, 'markdown_sha256': 'b' * 64},
            'outbound_hold_required': True,
        }
        local = store(folder / ('local-verified-' + verify_id + '.v1.json'), witness)
        command = {
            'format_version': 2,
            **case.catalog.scope,
            'operation_id': operation,
            'package': {
                'path': str(package),
                'sha256': manifest_ref['sha256'],
                'identity': identity(package.stat()),
            },
            'local_verification': local,
            'offhost_verification': None,
        }

        @contextmanager
        def execution(catalog, area, identifier):
            assert area == backup_capture.EXECUTIONS and identifier == operation
            yield folder, folder

        @contextmanager
        def protected_package(path, expected, installation):
            assert (
                path == package and expected == identity(package.stat()) and installation == source
            )
            yield path

        def verify_package(path, installation, backup, *, expected_manifest):
            assert path == package and installation == source and backup == grant['backup_id']
            assert digest(database.read_bytes()) == captured['database_sha256']
            assert expected_manifest == digest((package / 'backup-manifest.v1.json').read_bytes())
            return manifest, expected_manifest

        monkeypatch.setattr(backup_completion, 'execution_directory', execution)
        monkeypatch.setattr(backup_completion, 'admitted_backup', lambda *_: (grant, source))

        def read_fact(path, name):
            target = path / name
            return json.loads(target.read_bytes()) if target.exists() else None

        monkeypatch.setattr(backup_completion, 'optional_fact', read_fact)
        monkeypatch.setattr(
            backup_completion, 'write_fact', lambda path, name, record: store(path / name, record)
        )
        monkeypatch.setattr(backup_completion, 'private_root', protected_package)
        monkeypatch.setattr(backup_completion, 'verify_contents', verify_package)
        monkeypatch.setattr(
            backup_completion,
            'read_evidence',
            lambda *_: {'coverage_ref': {'audit_state': 'EMPTY'}},
        )
        monkeypatch.setattr(
            backup_completion, 'os', SimpleNamespace(geteuid=lambda: 0, fsync=lambda _: None)
        )
        monkeypatch.setattr(
            backup_completion, 'fcntl', SimpleNamespace(LOCK_SH=1, LOCK_NB=2, flock=lambda *_: None)
        )

        def arguments(record, variant):
            raw = store(folder / variant / backup_completion.OFFHOST_POLICY, record)
            return SimpleNamespace(
                backup_operation_id=operation,
                managed_backup_result_policy=Path(raw['path']),
                managed_backup_result_policy_sha256=raw['sha256'],
            )

        first = arguments(command, 'local')
        staged = backup_completion.complete_managed_backup(case.catalog, None, first, None)
        assert staged['status'] == backup_completion.LOCAL_STATUS
        assert staged == backup_completion.complete_managed_backup(case.catalog, None, first, None)
        history = '/management/api/v1/environments/' + environment + '/backups'
        read = client.get(history)
        assert read.status_code == 200, read.text
        local_point = read.json()['data']
        assert local_point['backups'][0]['verification_status'] == 'LOCAL_VERIFIED'
        assert (
            local_point['backup_status']['latest_attempt']['reason_code']
            == 'OFFHOST_VERIFICATION_REQUIRED'
        )
        assert local_point['backup_status']['latest_offhost'] is None
        control = '/management/api/v1/operations/' + operation + '/commands'
        pending = client.post(
            control,
            json={'command': 'RECONCILE', 'expected_revision': 2},
            headers={'Idempotency-Key': identifier()},
        )
        assert pending.status_code == 202, pending.text
        assert pending.json()['data']['operation']['status'] == 'RUNNING'
        assert not (folder / backup_completion.COMPLETE).exists()

        report = {
            'format_version': 1,
            'status': 'OFFHOST_SNAPSHOT_RETRIEVED',
            'verification_id': identifier(),
            'verification_policy_sha256': 'a' * 64,
            'publication_operation_id': identifier(),
            **{
                key: value
                for key, value in authority.items()
                if key != 'observation_max_age_seconds'
            },
            'source_environment_id': environment,
            **{key: staged['point'][key] for key in BACKUP_POINT_FIELDS},
            'snapshot_id': 'b' * 64,
            'restic_sha256': 'c' * 64,
            'restic_version': VERSION,
            'snapshot_bytes': len(stored_db) + 100,
            'snapshot_entries': 5,
            'retrieved_at': cutoff,
        }
        invalid = store(
            folder / 'unrelated-verification.json', {**report, 'backup_id': identifier()}
        )
        with pytest.raises(EnvironmentFailure, match=backup_completion.UNVERIFIED):
            backup_completion.complete_managed_backup(
                case.catalog,
                None,
                arguments({**command, 'offhost_verification': invalid}, 'wrong'),
                None,
            )
        assert not (folder / backup_completion.COMPLETE).exists()
        restored = store(folder / 'independent-verification.json', report)
        final_args = arguments({**command, 'offhost_verification': restored}, 'remote')
        result = backup_completion.complete_managed_backup(case.catalog, None, final_args, None)
        assert result['status'] == backup_completion.OFFHOST_COMPLETE
        assert result == backup_completion.complete_managed_backup(
            case.catalog, None, final_args, None
        )
        assert staged == backup_completion.complete_managed_backup(case.catalog, None, first, None)
        key = identifier()
        request = {'command': 'RECONCILE', 'expected_revision': 2}
        complete = client.post(control, json=request, headers={'Idempotency-Key': key})
        assert complete.status_code == 202, complete.text
        assert complete.json()['data']['operation']['status'] == 'SUCCEEDED'
        assert (
            complete.json()['data']['steps'][0]['result']['point']['offhost_verification'][
                'snapshot_id'
            ]
            == report['snapshot_id']
        )
        replay = client.post(control, json=request, headers={'Idempotency-Key': key})
        assert replay.status_code == 200 and replay.json()['data'] == complete.json()['data']
        visible = client.get(history).json()['data']
        assert visible['backups'][0]['cutoff_at'] == cutoff
        assert visible['backup_status']['latest_offhost']['backup_id'] == grant['backup_id']
        assert visible['backup_status']['rpo_status'] == 'UNVERIFIED'
        assert visible['backup_status']['latest_attempt']['status'] == 'SUCCEEDED'
        assert case.input_db.read_bytes() == original
        if case.action == 'RELEASE':
            restore, restore_operation = prepare_strict_restore(
                case, monkeypatch, stopped, manifest, command['package'], local, restored, authority
            )
            path = '/management/api/v1/catalog'
            query = {'environment_id': environment, 'kind': 'RESTORE'}
            answer = client.get(path, params=query)
            assert answer.status_code == 200, answer.text
            assert answer.json()['data']['state'] == 'READY'
            assert answer.json()['data']['restore_options'][0]['backup_id'] == grant['backup_id']
            proposed_restore = client.post(
                '/management/api/v1/plans', json={'kind': 'RESTORE', **restore}
            )
            assert proposed_restore.status_code == 201, proposed_restore.text
            restore_plan = proposed_restore.json()['data']
            assert restore_plan['preview']['recovery_requirement'] == 'OFFHOST_VERIFIED'
            assert restore_plan['preview']['offhost_recovery'] == {
                'verification_id': report['verification_id'],
                'verification_sha256': restored['sha256'],
                'snapshot_id': report['snapshot_id'],
                'retrieved_at': cutoff,
            }
            assert b'package_directory' not in canonical(restore_plan)
            confirm = {
                'action': 'RESTORE',
                **restore,
                **{key: restore_plan[key] for key in ('plan_id', 'plan_sha256')},
            }
            key = identifier()
            report_path = Path(restored['path'])
            store(report_path, {**report, 'snapshot_id': 'f' * 64})
            refused = client.post(
                '/management/api/v1/operations', json=confirm, headers={'Idempotency-Key': key}
            )
            assert refused.status_code == 409, refused.text
            assert refused.json()['error']['code'] == 'RELEASE_PLAN_CHANGED'
            with case.registry(writable=False) as (connection, _):
                assert (
                    connection.execute(
                        'SELECT operation_id FROM management_operations WHERE operation_id=?',
                        (restore_operation,),
                    ).fetchone()
                    is None
                )
            assert store(report_path, report) == restored
            accepted = client.post(
                '/management/api/v1/operations', json=confirm, headers={'Idempotency-Key': key}
            )
            assert accepted.status_code == 202, accepted.text
            assert accepted.json()['data']['operation']['operation_id'] == restore_operation
            replayed = client.post(
                '/management/api/v1/operations', json=confirm, headers={'Idempotency-Key': key}
            )
            assert replayed.status_code == 200
            assert replayed.json()['data'] == accepted.json()['data']
            assert case.input_db.read_bytes() == original


def test_unverifiable_https_target_has_no_management_release_observation(deployment):
    from backend.app.management import release_observation

    case = deployment
    case.target.ingress_group = 4004
    reference = release_observation.SOURCE + case.variables['configuration_ref']
    observation = release_observation.observation_path(case.catalog, reference)
    before = case.input_db.read_bytes()
    with pytest.raises(EnvironmentFailure, match='RELEASE_GATEWAY_VERIFIER_REQUIRED'):
        inspect_source(case)
    assert not observation.exists()
    assert case.input_db.read_bytes() == before

    with TestClient(case.web, base_url=case.origin, headers=case.headers) as client:
        request = {'environment_id': case.variables['environment_id'], 'kind': case.action}
        catalog = client.get('/management/api/v1/catalog', params=request)
        assert catalog.status_code == 200
        option = catalog.json()['data']['release_options'][0]
        assert option['state'] == 'SOURCE_UNVERIFIED'


def test_managed_deployment_carries_the_registered_offhost_requirement(deployment, monkeypatch):
    from backend.app.management import release_configuration, release_execution

    case = deployment
    policy = case.config['recovery_policy']
    source = case.catalog.directory / 'release-recovery-policies' / (policy['ref'] + '.json')
    original = release_configuration.installed_record(source, policy['sha256'])
    unsupported = {**original, 'minimum_verification': 'OFFHOST_VERIFIED'}
    policy.update(sha256=store(source, unsupported)['sha256'])
    case.catalog.release_configurations[case.variables['configuration_ref']] = store(
        case.config_path, case.config
    )['sha256']
    with TestClient(case.web, base_url=case.origin, headers=case.headers) as client:
        options = {'environment_id': case.variables['environment_id'], 'kind': case.action}
        assert (
            client.get('/management/api/v1/catalog', params=options).json()['data'][
                'release_options'
            ][0]['state']
            == 'RECOVERY_NOT_ADMITTED'
        )
        admitted = {
            **unsupported,
            'format_version': 2,
            'offhost_authority': {
                'source_host_id': case.catalog.scope['host_id'],
                'verification_host_id': identifier(),
                'verification_anchor_sha256': '5' * 64,
                'storage_profile_sha256': '6' * 64,
                'repository_id': '7' * 64,
                'observation_max_age_seconds': 3600,
            },
        }
        policy.update(sha256=store(source, admitted)['sha256'])
        case.catalog.release_configurations[case.variables['configuration_ref']] = store(
            case.config_path, case.config
        )['sha256']
        inspect_source(case)
        assert (
            client.get('/management/api/v1/catalog', params=options).json()['data'][
                'release_options'
            ][0]['state']
            == 'READY'
        )
        before = case.input_db.read_bytes()
        plan, _, _, operation = accept(client, case)
        assert plan['preview']['recovery_requirement'] == 'OFFHOST_VERIFIED'
        with case.registry() as (connection, lock):
            grant = release_execution.claim_release_maintenance(
                connection, lock, case.catalog, {'operation_id': operation['operation_id']}
            )
        assert grant['recovery_policy_sha256'] == policy['sha256']
        assert grant['recovery_requirement'] == 'OFFHOST_VERIFIED'
        selected, _ = selection_for(case, grant, monkeypatch)
        assert selected['status'] == 'MANAGED_RELEASE_SELECTION_RECORDED'
        assert case.input_db.read_bytes() == before


def test_management_makes_and_reconciles_distinct_release_intents(deployment, monkeypatch):
    from backend.app.management import (
        management_query,
        operation_store,
        release_execution,
        runtime_capacity,
    )
    from backend.app.management.attachment_observation import now

    case = deployment
    if case.rollback:
        from backend.app.management.release_observation import capture_release_source

        target = case.target.description
        with monkeypatch.context() as changes:
            changes.setitem(
                target, 'access_policy_ref', {'name': 'access-policy.v1.json', 'sha256': 'e' * 64}
            )
            with pytest.raises(EnvironmentFailure, match='MANAGEMENT_RESOURCE_UNVERIFIED'):
                capture_release_source(case.catalog, case.source_args, case.entry)
    inspect_source(case)
    before = case.input_db.read_bytes()
    with TestClient(case.web, base_url=case.origin, headers=case.headers) as client:
        url = '/management/api/v1/catalog'
        source = {'environment_id': case.variables['environment_id']}
        choices = {
            action: client.get(
                url, params=source if action == 'RELEASE' else {**source, 'kind': action}
            ).json()['data']['release_options']
            for action in ('RELEASE', 'ROLLBACK_CODE', 'RECONFIGURE')
        }
        options = choices.pop(case.action)
        assert not any(choices.values())
        assert len(options) == 1 and options[0]['state'] == 'READY'
        plan, request, original_key, operation = accept(client, case)
        assert plan['preview']['kind'] == operation['action'] == case.action
        assert (
            plan['preview']['source']['data_generation']
            == plan['preview']['target']['data_generation']
        )
        assert operation['status'] == 'ACCEPTED'
        denied = client.post(
            '/management/api/v1/plans',
            json={'kind': case.action, **case.variables},
            headers={'x-wall-e-auth-principal': 'developer'},
        )
        assert denied.status_code == 403
        with case.registry() as (connection, lock):
            grant = release_execution.claim_release_maintenance(
                connection, lock, case.catalog, {'operation_id': operation['operation_id']}
            )
            assert (
                release_execution.claim_release_maintenance(
                    connection, lock, case.catalog, {'operation_id': operation['operation_id']}
                )
                == grant
            )
        if case.rollback:
            assert grant['rollback_source_sha256'] == digest(
                canonical(case.config['rollback_source'])
            )
        else:
            assert 'rollback_source_sha256' not in grant
        if case.configure:
            assert grant['target_access_sha256'] == case.config['target_access_sha256']
            assert grant['source']['program_sha256'] == grant['target']['program_sha256']
        selected, pin = selection_for(case, grant, monkeypatch)
        original_run = record_open(case, grant, selected, pin, monkeypatch)
        verify_recovered_registry(case, grant, original_run, monkeypatch)
        endpoint = '/management/api/v1/operations/' + operation['operation_id'] + '/commands'
        control_request = {'command': 'RECONCILE', 'expected_revision': 3}
        control_key = identifier()
        confirmed = client.post(
            endpoint, json=control_request, headers={'Idempotency-Key': control_key}
        )
        assert confirmed.status_code == 202, confirmed.text
        assert confirmed.json()['data']['operation']['status'] == 'SUCCEEDED'
        repeated = client.post(
            endpoint, json=control_request, headers={'Idempotency-Key': control_key}
        )
        assert repeated.status_code == 200
        assert repeated.json()['data'] == confirmed.json()['data']
        initial_replay = client.post(
            '/management/api/v1/operations', json=request, headers={'Idempotency-Key': original_key}
        )
        assert initial_replay.status_code == 200
        assert (
            initial_replay.json()['data']['steps'][0]['result']['run_id'] == original_run['run_id']
        )
        with case.registry() as (connection, _):
            row = operation_store.environment_row(connection, grant['environment_id'])
            assert row['record_version'] == 8 and row['assignment_generation'] == 4
            current = operation_store.decoded(row['work_package_json'])
            assert current['deployment_id'] == case.target.deployment_id
            assert current['data_generation'] == case.original.data_generation
            if case.rollback or case.configure:
                assert management_query.business_entry(case.catalog, row, current) == case.business
                assert (
                    management_query.business_entry(
                        replace(case.catalog, business_entries={}), row, current
                    )
                    is None
                )
            runtime_capacity.release_capacity(
                connection,
                operation['operation_id'],
                identifier(),
                grant['environment_id'],
                {'run_id': original_run['run_id'], 'observed_at': now()},
                operation_store.stored,
                operation_store.decoded,
            )
            assert not runtime_capacity.reservations_for(connection, operation['operation_id'])
    assert case.input_db.read_bytes() == before


def verify_retirement_registry(case, operation_id, monkeypatch):
    from backend.app.management import (
        registry_recovery,
        registry_recovery_effects,
        release_execution,
        release_runtime,
    )
    from backend.app.management import (
        registry_recovery_dispatch_review as review,
    )
    from backend.app.management import (
        registry_recovery_disposition as disposition,
    )
    from backend.app.management import (
        registry_recovery_disposition_receipts as receipts,
    )
    from backend.app.management import (
        registry_recovery_outcome as outcome,
    )
    from backend.app.management import (
        registry_schema as schema,
    )
    from backend.app.management.attachment_observation import now

    generation, recovery = identifier(), identifier()
    selected = SimpleNamespace(
        manager_id=case.catalog.scope['manager_id'],
        host_id=case.catalog.scope['host_id'],
        registry_generation=generation,
        sha256='b' * 64,
    )
    archived = case.manager_db.read_bytes()
    target = case.manager_db.parent / 'retired-registry.sqlite'
    proof = case.manager_db.parent / 'retirement-proof'
    proof.mkdir()
    published = proof / (operation_id + '.json')

    def recorded(folder, operation, installation):
        assert folder == proof and operation == operation_id and installation == selected
        return published.read_bytes() if published.is_file() else None

    def publish(folder, name, raw, *, mode):
        assert folder == proof and name == published.name and mode == 0o400
        assert not published.exists()
        published.write_bytes(raw)

    with closing(sqlite3.connect(target, isolation_level=None)) as connection:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('ATTACH DATABASE ? AS original', (str(case.manager_db),))
        registry_recovery.populate_database(
            connection,
            {
                **case.catalog.scope,
                'target_registry_generation': generation,
                'schema_version': schema.RELEASE_RETIREMENT_SCHEMA_VERSION,
            },
            1,
            now(),
        )
        connection.row_factory = sqlite3.Row
        original = connection.execute(
            'SELECT * FROM management_operations WHERE operation_id=?', (operation_id,)
        ).fetchone()
        policy = {
            **case.catalog.scope,
            'registry_generation': generation,
            'registry_anchor_sha256': selected.sha256,
            'source_registry_generation': case.catalog.scope['registry_generation'],
            'source_revision': original['revision'],
            'source_intent_sha256': original['intent_sha256'],
            'operation_id': operation_id,
            'recovery_operation_id': recovery,
            'selection_receipt_sha256': 'c' * 64,
            'disposition': outcome.RELEASE_RETIRED,
        }
        pinned = 'd' * 64
        execution = case.catalog.directory / release_execution.EXECUTIONS / operation_id
        for fact in (release_runtime.DISPATCH, release_runtime.OPENED):
            source_fact = execution / fact
            store(source_fact, {'state': 'issued'})
            try:
                with pytest.raises(EnvironmentFailure, match=outcome.UNVERIFIED):
                    disposition.disposition_evidence(connection, case.catalog, policy)
            finally:
                source_fact.unlink()
        evidence = disposition.disposition_evidence(connection, case.catalog, policy)
        expected = disposition.disposition_outcome(selected, pinned, 'e' * 64, policy, evidence)
        assert evidence['original_status'] == 'RUNNING' and evidence['action'] == case.action
        scope = {
            'operation_id': recovery,
            'selection_receipt_sha256': policy['selection_receipt_sha256'],
            'source_registry_generation': case.catalog.scope['registry_generation'],
        }
        with monkeypatch.context() as changes:
            changes.setattr(disposition, 'receipt_bytes', recorded)
            changes.setattr(disposition, 'persisted_write', publish)
            lock = SimpleNamespace(assert_owned=lambda: None)
            settled = disposition.record_disposition(
                connection, lock, proof, selected, case.catalog, policy, expected, evidence
            )
            assert (
                disposition.record_disposition(
                    connection, lock, proof, selected, case.catalog, policy, expected, evidence
                )
                == settled
            )
        assert (
            receipts.read_permitted_receipt(
                published.read_bytes(), operation_id, selected, scope, pinned
            )
            == settled
        )
        receipts.confirms_original_operation(settled, original)
        source_step = connection.execute(
            'SELECT * FROM management_steps WHERE operation_id=?', (operation_id,)
        ).fetchone()
        observed = registry_recovery_effects.helper_observation(
            {**dict(source_step), 'environment_id': original['environment_id']}, case.catalog
        )
        assert (observed['state'], observed['units']) == ('UNKNOWN', [])
        assert (
            list(review.blocked_subjects([observed], [dict(original)], 1, {operation_id: settled}))
            == []
        )
        unproven = list(review.blocked_subjects([observed], [dict(original)], 1))
        assert {item['reason_code'] for item in unproven} == {review.STEP, review.OPERATION}
        observed['original_status'] = 'SKIPPED'
        with pytest.raises(EnvironmentFailure, match=review.UNVERIFIED):
            list(review.blocked_subjects([observed], [dict(original)], 1, {operation_id: settled}))
        wrong = {
            **settled,
            'evidence': {
                **evidence,
                'action': 'ROLLBACK_CODE' if case.action != 'ROLLBACK_CODE' else 'RECONFIGURE',
            },
        }
        with pytest.raises(EnvironmentFailure, match=outcome.UNVERIFIED):
            receipts.confirms_original_operation(wrong, original)
        assert (
            outcome.outcome_for_operation(connection, operation_id)['disposition']
            == outcome.RELEASE_RETIRED
        )
        stored = connection.execute(
            'SELECT status,revision FROM management_operations WHERE operation_id=?',
            (operation_id,),
        ).fetchone()
        assert tuple(stored) == ('RUNNING', original['revision'])
    assert case.manager_db.read_bytes() == archived


def test_original_held_release_retires_only_before_selection(deployment, monkeypatch):
    from backend.app.infrastructure import environment_maintenance as maintenance
    from backend.app.management import (
        environment_archive,
        release_configuration,
        release_execution,
        release_retirement,
        release_selection,
    )
    from backend.app.management.release_observation import ReleasePair

    case = deployment
    inspect_source(case)
    basis = case.input_db.read_bytes()
    with TestClient(case.web, base_url=case.origin, headers=case.headers) as client:
        _, request, first_key, operation = accept(client, case)
        identifier = operation['operation_id']
        with case.registry() as (connection, lock):
            grant = release_execution.claim_release_maintenance(
                connection, lock, case.catalog, {'operation_id': identifier}
            )
        folder = case.deployment_dir / identifier
        policy = release_execution.maintenance_policy(grant, case.original)
        policy_pin = store(folder / maintenance.POLICY, policy)['sha256']
        facts = {
            'status': maintenance.ACTIVE,
            'operation_id': identifier,
            **{key: policy[key] for key in release_execution.SOURCE_KEYS},
            'control_revision': grant['source']['control_revision'] + 1,
            'plan_sha256': policy_pin,
        }
        hold = release_execution.maintenance_result(facts, grant, policy, policy_pin)
        store(folder / release_execution.HOLD_RECEIPT, hold)
        config = release_configuration.read_configuration(
            case.catalog, case.variables['configuration_ref']
        )
        root = SimpleNamespace(
            release_operation_id=identifier,
            root=folder,
            sha256='a' * 64,
            runtime_entry=folder / 'runtime.py',
        )

        def reobserve(catalog, registry, args, entry, launcher, *, read_retired):
            assert read_retired
            with case.registry() as (connection, lock):
                current = release_execution.claim_release_maintenance(
                    connection,
                    lock,
                    catalog,
                    {'operation_id': args.release_operation_id, 'read_retired': True},
                )
            return release_execution.AdmittedRelease(
                current, config, ReleasePair(case.original, case.target)
            )

        def current_fact(directory, name):
            try:
                return release_execution.decode(
                    (directory / name).read_bytes(), 'INVALID_TEST_RECORD'
                )
            except FileNotFoundError:
                return None

        def write_fact(directory, name, value):
            known = current_fact(directory, name)
            assert known is None or known == value
            if known is None:
                return store(directory / name, value)['sha256']
            return digest(canonical(known))

        @contextmanager
        def execution(catalog, operation_id, **unused):
            assert catalog == case.catalog and operation_id == identifier
            yield folder, folder

        cancelled = False
        attempts = []

        def cancel_original(owner, group, argv, observations):
            nonlocal cancelled
            assert argv[-2:] == ['--maintenance-action', 'cancel']
            assert current_fact(folder, release_execution.RETIREMENT_INTENT) is not None
            attempts.append(argv)
            if not cancelled:
                cancelled = True
                raise EnvironmentFailure('TEST_CANCELLATION_REPLY_MISSING', uncertain=True)
            return {
                **facts,
                'status': maintenance.CANCELLED,
                'control_revision': hold['control_revision'] + 1,
            }

        for module in (release_execution, release_selection, release_retirement):
            monkeypatch.setattr(module, 'optional_fact', current_fact)
        for module in (release_selection, release_retirement):
            monkeypatch.setattr(module, 'release_execution', execution)
            monkeypatch.setattr(
                module, 'os', SimpleNamespace(geteuid=lambda: 0, fsync=lambda fd: None)
            )
        monkeypatch.setattr(release_retirement, 'write_fact', write_fact)
        monkeypatch.setattr(release_retirement, 'admitted_release', reobserve)
        monkeypatch.setattr(release_retirement, 'invoke_observer', cancel_original)
        monkeypatch.setattr(case.original, 'maintenance_uid', 1000, raising=False)
        monkeypatch.setattr(case.original, 'group', 1001, raising=False)

        selected_policy = folder / release_selection.SWITCH_POLICY
        store(selected_policy, {'write_attempt_already_bound': True})
        with pytest.raises(EnvironmentFailure, match=release_retirement.UNAVAILABLE):
            release_retirement.retire_managed_release(case.catalog, None, root, None, 'owned-tool')
        selected_policy.unlink()
        assert not attempts

        with pytest.raises(EnvironmentFailure, match='TEST_CANCELLATION_REPLY_MISSING'):
            release_retirement.retire_managed_release(case.catalog, None, root, None, 'owned-tool')
        with pytest.raises(EnvironmentFailure, match=release_selection.UNAVAILABLE):
            release_selection.select_managed_release(case.catalog, None, root, None, 'owned-tool')
        pending = client.get('/management/api/v1/operations/' + identifier)
        assert pending.json()['data']['operation']['status'] == 'RUNNING'

        resolved = release_retirement.retire_managed_release(
            case.catalog, None, root, None, 'owned-tool'
        )
        assert resolved['status'] == release_retirement.RETIRED and len(attempts) == 2
        verify_retirement_registry(case, identifier, monkeypatch)
        endpoint = '/management/api/v1/operations/' + identifier + '/commands'
        key = str(uuid4())
        command = {'command': 'RECONCILE', 'expected_revision': 2}
        result = client.post(endpoint, json=command, headers={'Idempotency-Key': str(key)})
        assert result.status_code == 202, result.text
        assert result.json()['data']['operation']['status'] == 'CANCELLED'
        replay = client.post(endpoint, json=command, headers={'Idempotency-Key': str(key)})
        assert replay.status_code == 200 and replay.json()['data'] == result.json()['data']
        assert (
            release_retirement.retire_managed_release(case.catalog, None, root, None, 'owned-tool')
            == resolved
        )
        assert len(attempts) == 2
        with case.registry() as (connection, lock):
            with pytest.raises(EnvironmentFailure):
                release_execution.claim_release_maintenance(
                    connection, lock, case.catalog, {'operation_id': identifier}
                )
            env = connection.execute(
                'SELECT configuration_sha256,record_version FROM managed_environments'
            ).fetchone()
            assert tuple(env) == (case.original.configuration_sha256, 7)
            helpers = environment_archive.scoped_projection(
                connection,
                'steps.jsonl',
                operation['environment_id'],
                pending_step=environment_archive.pending_step_clause(connection),
            )
            helper = next(row for row in helpers if row['operation_id'] == identifier)
            settled = environment_archive.terminal_helper(connection, case.catalog, helper)
            assert settled['original_status'] == 'CANCELLED'
            assert settled['action'] == case.action
        original = client.post(
            '/management/api/v1/operations', json=request, headers={'Idempotency-Key': first_key}
        )
        assert (
            original.status_code == 200
            and original.json()['data']['operation']['status'] == 'CANCELLED'
        )
    assert case.input_db.read_bytes() == basis


@pytest.mark.parametrize('deployment', ['RELEASE'], indirect=True)
def test_recovered_registry_rejects_historical_operation_and_control_keys(deployment, monkeypatch):
    from backend.app.management import (
        lifecycle_operations,
        management_web,
        operation_store,
        registry_recovery,
        registry_schema,
        runtime_capacity,
    )
    from backend.app.management.attachment_observation import now

    case = deployment
    old_scope = case.catalog.scope
    old_key, old_control = identifier(), identifier()
    new_scope = {**old_scope, 'registry_generation': identifier()}
    actor = case.catalog.access(case.headers['x-wall-e-auth-principal'])
    intent = {
        'action': 'START',
        **{
            key: case.variables[key]
            for key in (
                'environment_id',
                'expected_record_version',
                'expected_assignment_generation',
            )
        },
        'expected_configuration_sha256': case.original.configuration_sha256,
    }
    with case.registry() as (connection, _):
        original = operation_store.insert_operation(
            connection,
            old_scope['registry_generation'],
            old_key,
            actor,
            intent,
            intent['environment_id'],
            now(),
        )
        operation_store.insert_step(connection, original, 'RUNTIME_STARTED', None)
        connection.execute(
            'INSERT INTO management_controls VALUES (?,?,?,?,?,?,?)',
            (
                old_scope['registry_generation'],
                old_control,
                original,
                actor.id,
                'RECONCILE',
                '2' * 64,
                operation_store.stored({'control_key': old_control}),
            ),
        )
    archived = case.manager_db.read_bytes()
    restored = case.manager_db.with_name('historical-keys.sqlite')
    with closing(sqlite3.connect(restored, isolation_level=None)) as connection:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('ATTACH DATABASE ? AS original', (str(case.manager_db),))
        registry_recovery.populate_database(
            connection,
            {
                **old_scope,
                'target_registry_generation': new_scope['registry_generation'],
                'schema_version': registry_schema.RELEASE_RETIREMENT_SCHEMA_VERSION,
            },
            registry_schema.SCHEMA_VERSION,
            now(),
        )

    @contextmanager
    def live_registry(*_args, writable=True):
        with closing(sqlite3.connect(restored, isolation_level=None)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
            if not writable:
                connection.execute('PRAGMA query_only=ON')
            yield connection, SimpleNamespace(assert_owned=lambda: None)

    allocation = {
        'memory_bytes': 256 * 1024**2,
        'cpu_percent': 50,
        'tasks': 48,
        'run_slots': 1,
    }
    capacity = runtime_capacity.CapacityPolicy(
        case.capacity_pin,
        restored.parent,
        restored.parent,
        allocation,
        {'INTEGRATION': {'profile_ref': case.profile, 'limits': allocation}},
    )
    monkeypatch.setattr(operation_store, 'verified_registry', live_registry)
    monkeypatch.setattr(lifecycle_operations, 'startup_capacity', lambda *_: (capacity, None))
    server = management_web.ManagementScope(
        case.server.web,
        replace(case.catalog, scope=new_scope),
        identifier(),
        now(),
        None,
        SimpleNamespace(registry_generation=new_scope['registry_generation']),
        case.source_args.sha256,
    )
    web = Starlette(routes=[Route('/{path:path}', server.respond, methods=['POST'])])
    headers = {**case.headers, 'x-wall-e-registry-generation': new_scope['registry_generation']}
    path = '/management/api/v1/operations'
    with TestClient(web, base_url=case.origin) as client:
        stale_scope = client.post(
            path, json=intent, headers={**case.headers, 'Idempotency-Key': old_key}
        )
        assert stale_scope.status_code == 409
        forbidden = client.post(path, json=intent, headers={**headers, 'Idempotency-Key': old_key})
        assert forbidden.status_code == 409
        assert forbidden.json()['error']['code'] == operation_store.KEY_CONFLICT

        fresh = {**headers, 'Idempotency-Key': identifier()}
        accepted = client.post(path, json=intent, headers=fresh)
        assert accepted.status_code == 202, accepted.json()
        operation = accepted.json()['data']['operation']
        assert operation['status'] == 'ACCEPTED'
        assert client.post(path, json=intent, headers=fresh).status_code == 200

        control_path = path + '/' + operation['operation_id'] + '/commands'
        body = {'command': 'RECONCILE', 'expected_revision': operation['revision']}
        rejected = client.post(
            control_path, json=body, headers={**headers, 'Idempotency-Key': old_control}
        )
        assert rejected.status_code == 409
        assert rejected.json()['error']['code'] == operation_store.KEY_CONFLICT

        new_control = {**headers, 'Idempotency-Key': old_key}
        receipt = client.post(control_path, json=body, headers=new_control)
        assert receipt.status_code == 202, receipt.json()
        replay = client.post(control_path, json=body, headers=new_control)
        assert replay.status_code == 200 and replay.json()['data'] == receipt.json()['data']

    with live_registry(writable=False) as (connection, _):
        for table in ('management_operations', 'management_controls'):
            assert (
                connection.execute(
                    f'SELECT COUNT(*) FROM {table} WHERE registry_generation=?',
                    (new_scope['registry_generation'],),
                ).fetchone()[0]
                == 1
            )
    assert case.manager_db.read_bytes() == archived
