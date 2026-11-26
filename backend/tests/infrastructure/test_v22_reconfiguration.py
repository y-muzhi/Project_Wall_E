"""Verify closed reconfiguration uses the current fixed program and access scope."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.infrastructure.environment_files import EnvironmentFailure, canonical, digest

ENVIRONMENT = '673bc7cb-5050-4ce8-a9bc-b7733dde9180'
GENERATION = '0f9bc28b-39ef-456c-8c38-18b8d623a35d'
SOURCE = '20001111-5050-4ccf-a123-111111111111'
TARGET = '20001111-5050-4ccf-a123-222222222222'
RELEASE = '20001111-5050-4ccf-a123-333333333333'
OPERATION = '20001111-5050-4ccf-a123-444444444444'
PROGRAM = 'a' * 64
RUNTIME = 'b' * 64
SCHEMA = 'c' * 64
ORIGINAL = 'd' * 64
TARGET_PIN = 'e' * 64


def fixed(path, record):
    data = canonical(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {'path': str(path), 'sha256': digest(data)}


@pytest.fixture
def reconfiguration(tmp_path, monkeypatch):
    pytest.importorskip('fcntl')
    from backend.app.infrastructure import (
        environment_backup_package,
        environment_installation,
        environment_recovery_installation,
    )
    from backend.app.infrastructure import (
        environment_release_deployment as deployment,
    )
    from backend.app.infrastructure import (
        environment_release_preflight as preflight,
    )
    from backend.app.infrastructure import (
        environment_release_switch as switch,
    )

    root = tmp_path / ENVIRONMENT
    original = root / 'deployments' / SOURCE
    candidate = root / 'deployments' / TARGET
    package = tmp_path / 'fixed'
    schema = tmp_path / 'schema'
    plan_folder = tmp_path / 'intent'
    origin = environment_installation.business_origin(ENVIRONMENT, 'check.example.test')
    access = {
        'format_version': 1,
        'environment_id': ENVIRONMENT,
        'public_origin': origin,
        'upstream_socket': str(root / 'runtime/walle.sock'),
        'principals': [{'principal_id': 'user-old', 'client_kind': 'WEB', 'permission': 'DEVELOP'}],
    }
    prior = fixed(original / environment_installation.ACCESS_NAME, access)
    approved = {
        **access,
        'principals': [{'principal_id': 'user-new', 'client_kind': 'WEB', 'permission': 'DEVELOP'}],
    }
    proposal = plan_folder / environment_installation.ACCESS_NAME
    proposed = fixed(proposal, approved)
    manifest = {
        'release_id': RELEASE,
        'runtime_manifest_sha256': RUNTIME,
        'schema_manifest_sha256': SCHEMA,
        'application_index_ref': {'sha256': '1' * 64},
        'frontend_index_ref': {'sha256': '2' * 64},
        'compatibility_refs': [],
    }
    manifest_ref = fixed(package / 'manifest.json', manifest)
    source = SimpleNamespace(
        anchor=original / environment_installation.ANCHOR_NAME,
        anchor_sha256=ORIGINAL,
        environment_id=ENVIRONMENT,
        data_generation=GENERATION,
        deployment_id=SOURCE,
        configuration_sha256='9' * 64,
        environment_root=root,
        database=root / 'data/walle.sqlite',
        lock_identity={'device': '1', 'inode': '2'},
        roots={'control': root / 'control', 'data': root / 'data'},
        project=package / 'application',
        schema=schema,
        ingress_group=None,
        restore_generation_sha256=None,
        check_hold=lambda: None,
        check_identity=lambda **_: None,
        description={
            'purpose': 'DEVELOPMENT',
            'program_source': {'kind': 'FIXED_RELEASE', 'sha256': PROGRAM},
            'runtime_manifest_sha256': RUNTIME,
            'schema_manifest_sha256': SCHEMA,
            'required_capabilities': ['DOCUMENT_READ', 'DOCUMENT_WRITE'],
            'access_policy_ref': {
                'name': environment_installation.ACCESS_NAME,
                'sha256': prior['sha256'],
            },
            'deployment_slot': {
                'base_installation_sha256': '3' * 64,
                'base_project': str(tmp_path / 'original-code'),
                'release_id': RELEASE,
                'manifest_sha256': manifest_ref['sha256'],
                'frontend_index_sha256': manifest['frontend_index_ref']['sha256'],
            },
        },
    )
    current_schema = SimpleNamespace(schema_contract_sha256='4' * 64)
    proof = preflight.compatibility_record(
        RELEASE,
        source,
        current_schema,
        manifest,
        current_schema,
        PROGRAM,
    )
    compatibility_ref = fixed(plan_folder / preflight.COMPATIBILITY, proof)
    deployment_plan = {
        'format_version': 1,
        'installation_sha256': ORIGINAL,
        'source_deployment_id': SOURCE,
        'target_deployment_id': TARGET,
        'target_manifest': manifest_ref,
        'target_schema_directory': str(schema),
        'candidate_proof': {},
        'compatibility_ref': compatibility_ref,
        'target_access_policy': proposed,
    }
    policy = plan_folder / deployment.RECONFIGURE_POLICY
    entry = {'verify_program': lambda path: PROGRAM}

    def args(plan=deployment_plan, name=policy):
        result = fixed(name, plan)
        return SimpleNamespace(
            release_deployment_policy=name,
            release_deployment_policy_sha256=result['sha256'],
            anchor=source.anchor,
            anchor_sha256=ORIGINAL,
            project=source.project,
            sha256=RUNTIME,
            root=tmp_path / 'runtime',
            home=tmp_path / 'home',
            temporary=tmp_path / 'tmp',
            program_sha256=PROGRAM,
        )

    for module in (environment_backup_package, environment_installation, deployment, preflight):
        monkeypatch.setattr(module, 'read_protected', Path.read_bytes)
    for module in (environment_recovery_installation, preflight, switch):
        monkeypatch.setattr(module, 'absolute', lambda value, _: Path(value))
    monkeypatch.setattr(deployment, 'load_installation', lambda *args: source)
    monkeypatch.setattr(deployment, 'checked_schema', lambda *args: current_schema)
    monkeypatch.setattr(
        deployment, 'candidate_target', lambda *args: ({}, manifest, current_schema, PROGRAM)
    )
    return SimpleNamespace(
        deployment=deployment,
        preflight=preflight,
        source=source,
        target=candidate,
        plan=deployment_plan,
        access=access,
        approved=approved,
        proposal=proposal,
        arguments=args,
        entry=entry,
        switch=switch,
    )


def test_prepared_configuration_keeps_current_fixed_program_and_data(reconfiguration):
    case = reconfiguration
    prepared = case.deployment.prepare_target(case.arguments(), case.entry)
    assert prepared.binding['authorization_mode'] == 'RECONFIGURE'
    assert prepared.binding['source_deployment_id'] == SOURCE
    assert prepared.deployment_id == TARGET
    assert prepared.project == case.source.project and prepared.schema == case.source.schema
    assert prepared.description['program_source'] == case.source.description['program_source']
    assert prepared.access == canonical(case.approved)
    assert prepared.description['access_policy_ref']['sha256'] == digest(prepared.access)
    assert (case.source.anchor.parent / case.proposal.name).read_bytes() == canonical(case.access)
    for changes in (
        {'public_origin': case.access['public_origin'].replace('check.', 'another.')},
        {'upstream_socket': '/srv/foreign/walle.sock'},
        {
            'principals': [
                {'principal_id': 'user-new', 'client_kind': 'WEB', 'permission': 'READ_ONLY'}
            ]
        },
    ):
        altered = fixed(case.proposal, {**case.approved, **changes})
        with pytest.raises(EnvironmentFailure):
            case.deployment.prepare_target(
                case.arguments({**case.plan, 'target_access_policy': altered}), case.entry
            )
    fixed(case.proposal, case.approved)
    with pytest.raises(EnvironmentFailure):
        case.deployment.prepare_target(
            case.arguments(
                {**case.plan, 'target_schema_directory': str(case.source.schema / 'other')}
            ),
            case.entry,
        )
    with pytest.raises(EnvironmentFailure):
        case.deployment.prepare_target(
            case.arguments(
                {key: value for key, value in case.plan.items() if key != 'target_access_policy'},
                case.proposal.parent / case.deployment.POLICY,
            ),
            case.entry,
        )


def test_https_reconfiguration_requires_read_only_automation_in_target_policy(reconfiguration):
    case = reconfiguration
    case.source.ingress_group = 4004
    for client_kind, permission in (('WEB', 'READ_ONLY'), ('AUTOMATION', 'DEVELOP')):
        wrong_role = {'principal_id': 'probe', 'client_kind': client_kind, 'permission': permission}
        policy = {**case.approved, 'principals': [*case.approved['principals'], wrong_role]}
        reference = fixed(case.proposal, policy)
        with pytest.raises(EnvironmentFailure, match='RELEASE_GATEWAY_VERIFIER_REQUIRED'):
            case.deployment.prepare_target(
                case.arguments({**case.plan, 'target_access_policy': reference}), case.entry
            )

    verifier = {'principal_id': 'probe', 'client_kind': 'AUTOMATION', 'permission': 'READ_ONLY'}
    policy = {**case.approved, 'principals': [*case.approved['principals'], verifier]}
    reference = fixed(case.proposal, policy)
    prepared = case.deployment.prepare_target(
        case.arguments({**case.plan, 'target_access_policy': reference}), case.entry
    )
    assert prepared.access == canonical(policy)
    assert prepared.description['access_policy_ref']['sha256'] == reference['sha256']
    assert (case.source.anchor.parent / case.proposal.name).read_bytes() == canonical(case.access)


def test_switch_validates_current_origin_and_separates_configuration_from_release(
    reconfiguration, monkeypatch
):
    case = reconfiguration
    source = case.source
    prepared = case.deployment.prepare_target(case.arguments(), case.entry)
    access_path = case.target / case.proposal.name
    fixed(access_path, case.approved)
    target = SimpleNamespace(
        **{
            **vars(source),
            'anchor': case.target / source.anchor.name,
            'anchor_sha256': TARGET_PIN,
            'deployment_id': TARGET,
            'configuration_sha256': '8' * 64,
            'description': prepared.description,
        }
    )
    anchor_ref = {'path': str(target.anchor), 'sha256': TARGET_PIN}

    def admission(args, active, program, *, offline):
        assert program == PROGRAM and offline
        return {source.anchor: source, target.anchor: target}[args.anchor], None

    monkeypatch.setattr(case.switch, 'admission_inputs', admission)

    def check(preflight_name):
        preflight = fixed(case.proposal.parent / preflight_name, {'operation_id': OPERATION})
        plan_ref = fixed(
            case.proposal.parent / case.switch.POLICY,
            {
                'format_version': 1,
                'operation_id': OPERATION,
                'source_installation_sha256': ORIGINAL,
                'target_installation': anchor_ref,
                'target_project': str(target.project),
                'preflight_policy': preflight,
                'release_preflight_sha256': '5' * 64,
            },
        )
        args = case.arguments()
        args.release_switch_policy = Path(plan_ref['path'])
        args.release_switch_policy_sha256 = plan_ref['sha256']
        return case.switch.selection_inputs(None, args, case.entry)

    candidate = check(case.preflight.RECONFIGURE_POLICY)
    assert candidate.target == target and candidate.source == source
    with pytest.raises(EnvironmentFailure, match=case.switch.INVALID):
        check(case.preflight.POLICY)
    target.description['deployment_slot']['authorization_mode'] = 'SAME_SCHEMA'
    with pytest.raises(EnvironmentFailure, match=case.switch.INVALID):
        check(case.preflight.POLICY)


def test_business_requests_require_the_actual_selected_access_pin(reconfiguration):
    from fastapi import FastAPI
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from backend.app.infrastructure.environment_http import api_admission

    case = reconfiguration
    prepared = case.deployment.prepare_target(case.arguments(), case.entry)
    target_path = case.target / case.proposal.name
    fixed(target_path, case.approved)
    target = SimpleNamespace(
        **{
            **vars(case.source),
            'anchor': case.target / case.source.anchor.name,
            'deployment_id': TARGET,
            'configuration_sha256': '8' * 64,
            'description': prepared.description,
        }
    )
    scope = SimpleNamespace(installation=case.source, active=True, run_id=OPERATION)

    async def get_document(request):
        return JSONResponse({'body': 'current data remains accessible'})

    app = FastAPI(routes=[Route('/api/v1/requirements', get_document)])
    app.state.walle_worker = SimpleNamespace(accepting=True)

    @app.middleware('http')
    async def entry(request, call_next):
        return await api_admission(request, call_next, scope)

    headers = {
        'X-WALL-E-Environment-ID': ENVIRONMENT,
        'X-WALL-E-Data-Generation': GENERATION,
        'X-WALL-E-Binding-Protocol': '1',
        'X-WALL-E-Client': 'web-v1',
        'Sec-Fetch-Site': 'same-origin',
    }

    with TestClient(app, base_url=case.access['public_origin'], headers=headers) as browser:
        url = '/api/v1/requirements'

        def view(principal):
            return browser.get(url, headers={'X-WALL-E-Auth-Principal': principal})

        assert view('user-old').status_code == 200
        assert view('user-new').status_code == 403
        scope.installation = target
        assert view('user-old').status_code == 403
        accepted = view('user-new')
        assert accepted.json()['body'] == 'current data remains accessible'
        assert accepted.headers['X-WALL-E-Data-Generation'] == GENERATION
        fixed(target_path, case.access)
        late = view('user-new')
        assert late.status_code == 503
        assert late.json()['error']['code'] == 'ENVIRONMENT_NOT_READY'
        assert view('user-old').status_code == 503
