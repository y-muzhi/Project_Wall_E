"""Exercise the installed HTTPS identity used by the gateway and management."""

import json
import runpy
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from backend.app.infrastructure import environment_installation as installation
from backend.app.infrastructure.environment_files import EnvironmentFailure, canonical, digest

ENVIRONMENT = '673bc7cb-5050-4ce8-a9bc-b7733dde9180'
FOREIGN = '0f9bc28b-39ef-456c-8c38-18b8d623a35d'
DOMAIN = 'validation.example.test'


@pytest.mark.parametrize('port', (443, 9443))
def test_installed_business_origin_reaches_gateway_and_resource_claim(monkeypatch, tmp_path, port):
    pytest.importorskip('grp')
    gateway_path = (
        Path(__file__).resolve().parents[3] / 'tools/linux_runtime/environment_gateway.py'
    )
    gateway = runpy.run_path(str(gateway_path))['site_block']
    from backend.app.management.attachment_observation import public_origin_resource

    root = PurePosixPath('/srv/walle-test') / ENVIRONMENT
    anchor = tmp_path / installation.ANCHOR_NAME
    access_path = tmp_path / installation.ACCESS_NAME
    origin = installation.business_origin(ENVIRONMENT, DOMAIN, port)
    policy = {
        'format_version': 1,
        'environment_id': ENVIRONMENT,
        'public_origin': origin,
        'upstream_socket': str(root / 'runtime/walle.sock'),
        'principals': [
            {'principal_id': 'owned-test', 'client_kind': 'WEB', 'permission': 'DEVELOP'},
        ],
    }
    current = SimpleNamespace(
        anchor=anchor,
        environment_root=root,
        environment_id=ENVIRONMENT,
        data_generation=FOREIGN,
        configuration_sha256='a' * 64,
        description={'purpose': 'INTEGRATION'},
        ingress_group=1000,
        path=lambda kind: '/srv/walle-static/validation' if kind == 'frontend' else root / kind,
    )

    def install(record):
        raw = canonical(record)
        access_path.write_bytes(raw)
        current.description['access_policy_ref'] = {'name': access_path.name, 'sha256': digest(raw)}

    monkeypatch.setattr(installation, 'read_protected', Path.read_bytes)
    install(policy)
    result = installation.read_access_policy(current)
    assert result == policy
    claims = public_origin_resource(current)
    assert claims == {
        'kind': 'PUBLIC_ORIGIN',
        'scope': 'HTTPS',
        'locator': origin.removeprefix('https://'),
        'object_identity': None,
    }
    block = gateway(current, {'owned-test': '$2b$12$' + 'a' * 53})
    assert block.startswith(origin + ' {\n')
    assert 'bind 127.0.0.1' in block
    rendered = next(line for line in block.splitlines() if line.strip().startswith('respond "'))
    public = json.loads(rendered.strip().removeprefix('respond ').removesuffix(' 200'))
    assert json.loads(public)['public_origin'] == origin
    assert '/__walle_hmr' not in block
    assert 'rewrite * /index.html' in block

    dev_socket = PurePosixPath('/srv/walle-vite') / ENVIRONMENT / 'vite.sock'
    dev = gateway(current, {'owned-test': '$2b$12$' + 'a' * 53}, vite_socket=dev_socket)
    assert f'reverse_proxy unix/{policy["upstream_socket"]}' in dev
    assert dev.index('@api path /api/*') < dev.index('@development_hmr path /__walle_hmr')
    assert f'header Origin {origin}' in dev and 'header Upgrade websocket' in dev
    assert 'path /node_modules/vite/dist/client/env.mjs' in dev
    assert 'path /node_modules/*' not in dev
    assert dev.count(f'reverse_proxy unix/{dev_socket}') == 3
    assert dev.count('request_header -Authorization') == 4
    assert 'rewrite * /index.html' not in dev
    with pytest.raises(EnvironmentFailure, match='GATEWAY_POLICY_MISMATCH'):
        gateway(
            current,
            {'owned-test': '$2b$12$' + 'a' * 53},
            previous_frontend=PurePosixPath('/srv/previous'),
            vite_socket=dev_socket,
        )

    access_path.write_bytes(canonical({**policy, 'public_origin': 'https://other.example.test'}))
    with pytest.raises(EnvironmentFailure, match='INVALID_ENVIRONMENT_ACCESS'):
        public_origin_resource(current)


@pytest.mark.parametrize(
    'description',
    (
        {'purpose': 'CANDIDATE'},
        {'purpose': 'DEVELOPMENT', 'deployment_slot': {}},
        {'purpose': 'INTEGRATION', 'recovery_replica': {}},
    ),
)
def test_gateway_refuses_vite_for_fixed_or_recovery_environments(description):
    gateway_path = (
        Path(__file__).resolve().parents[3] / 'tools/linux_runtime/environment_gateway.py'
    )
    development_sockets = runpy.run_path(str(gateway_path))['development_sockets']
    installed = SimpleNamespace(environment_id=ENVIRONMENT, description=description)
    with pytest.raises(EnvironmentFailure, match='DEVELOPMENT_FRONTEND_NOT_ADMITTED'):
        development_sockets(
            [(ENVIRONMENT, f'/srv/walle-vite/{ENVIRONMENT}/vite.sock')], [installed]
        )


@pytest.mark.parametrize('port', (443, 9443))
def test_reopening_rechecks_the_protected_origin_listener(monkeypatch, tmp_path, port):
    from backend.app.infrastructure import environment_release_open as opening
    from backend.app.management.attachment_observation import now

    anchor = tmp_path / installation.ANCHOR_NAME
    access_file = tmp_path / installation.ACCESS_NAME
    origin = installation.business_origin(ENVIRONMENT, DOMAIN, port)
    access = {
        'format_version': 1,
        'environment_id': ENVIRONMENT,
        'public_origin': origin,
        'upstream_socket': str(tmp_path / 'runtime' / 'walle.sock'),
        'principals': [
            {'principal_id': 'owned-test', 'client_kind': 'WEB', 'permission': 'DEVELOP'},
        ],
    }
    raw = canonical(access)
    access_file.write_bytes(raw)
    target = SimpleNamespace(
        anchor=anchor,
        environment_root=tmp_path,
        anchor_sha256='1' * 64,
        environment_id=ENVIRONMENT,
        data_generation=FOREIGN,
        deployment_id=FOREIGN,
        configuration_sha256='2' * 64,
        description={
            'access_policy_ref': {'name': access_file.name, 'sha256': digest(raw)},
            'deployment_slot': {'frontend_index_sha256': '3' * 64},
        },
    )
    plan = {
        'operation_id': ENVIRONMENT,
        'run_id': FOREIGN,
        'control_sha256': '4' * 64,
        'transition_sha256': '5' * 64,
        'release_verification': {'sha256': '6' * 64},
        'gateway_verification': {'sha256': '7' * 64},
    }
    verified_at = now()
    proof = {
        'format_version': 1,
        'status': 'RELEASE_GATEWAY_VERIFIED_CLOSED',
        'operation_id': ENVIRONMENT,
        'target_installation_sha256': target.anchor_sha256,
        'target_environment_id': ENVIRONMENT,
        'target_data_generation': FOREIGN,
        'target_deployment_id': FOREIGN,
        'target_configuration_sha256': target.configuration_sha256,
        'target_frontend_index_sha256': '3' * 64,
        'target_verification_sha256': plan['release_verification']['sha256'],
        'transition_sha256': plan['transition_sha256'],
        'control_sha256': plan['control_sha256'],
        'origin': origin,
        'gateway_process': {
            'pid': 301,
            'uid': 500,
            'start_ticks': '10',
            'boot_id': 'this-boot',
            'listener_inode': '30',
        },
        'verified_at': verified_at,
        **dict.fromkeys(
            (
                'policy_sha256',
                'gateway_stage_sha256',
                'gateway_configuration_sha256',
                'current_asset_sha256',
                'previous_asset_sha256',
            ),
            'e' * 64,
        ),
    }
    monkeypatch.setattr(installation, 'read_protected', Path.read_bytes)
    monkeypatch.setattr(opening, 'read_reference', lambda *args, **options: proof)
    monkeypatch.setattr(
        opening,
        'verified_release_receipt',
        lambda *args: {'run_id': ENVIRONMENT, 'verified_at': verified_at},
    )
    monkeypatch.setattr(opening, 'process_epoch', lambda pid: ('10', 'this-boot'))
    observed = []
    listeners = {port: {'30'}}

    def measure(pid, requested_port):
        assert pid == opening.os.getpid()
        observed.append(requested_port)
        return listeners.get(requested_port, set())

    monkeypatch.setattr(opening, 'listener_inodes', measure)
    opening.opening_evidence(plan, target, {})
    assert observed == [port]

    other_port = 9443 if port == 443 else 443
    proof['origin'] = installation.business_origin(ENVIRONMENT, DOMAIN, other_port)
    with pytest.raises(EnvironmentFailure, match=opening.UNVERIFIED):
        opening.opening_evidence(plan, target, {})
    assert observed == [port]
    proof['origin'] = origin
    listeners.clear()
    listeners[other_port] = {'30'}
    with pytest.raises(EnvironmentFailure, match=opening.UNVERIFIED):
        opening.opening_evidence(plan, target, {})
    assert observed == [port, port]

    access_file.write_bytes(
        canonical({**access, 'public_origin': proof['origin'], 'principals': []})
    )
    with pytest.raises(EnvironmentFailure, match='INVALID_ENVIRONMENT_ACCESS'):
        opening.opening_evidence(plan, target, {})
    assert observed == [port, port]


def test_gateway_uses_each_measured_program_from_its_original_installation(tmp_path, monkeypatch):
    from backend.app.infrastructure import environment_files

    gateway_path = (
        Path(__file__).resolve().parents[3] / 'tools/linux_runtime/environment_gateway.py'
    )
    load_site = runpy.run_path(str(gateway_path))['installed_site']
    monkeypatch.setattr(installation, 'read_protected', Path.read_bytes)
    monkeypatch.setattr(environment_files, 'absolute', lambda value, _code: Path(value))

    def fixture(name):
        root = tmp_path / name
        root.mkdir()
        program = root / 'sealed-program'
        program.mkdir()
        (program / 'program-snapshot.v1.json').write_bytes(name.encode())
        anchor = root / installation.ANCHOR_NAME
        anchor.write_bytes(canonical({'project': str(program)}))
        return SimpleNamespace(
            anchor=anchor,
            expected=digest(anchor.read_bytes()),
            project=program,
            description={'program_source': {'sha256': digest(name.encode())}},
        )

    developer, integration = (fixture(name) for name in ('developer', 'integration'))
    runtime = 'a' * 64
    indexed = {item.anchor: item for item in (developer, integration)}
    observed = []

    def original(anchor, expected, runtime_sha, project):
        item = indexed[anchor]
        assert item.project == project and expected == item.expected and runtime_sha == runtime
        return item

    def measure(project):
        observed.append(project)
        return digest((project / 'program-snapshot.v1.json').read_bytes())

    monkeypatch.setattr(installation, 'load_installation', original)
    assert load_site(developer.anchor, developer.expected, runtime, measure) is developer
    assert load_site(integration.anchor, integration.expected, runtime, measure) is integration
    assert observed == [developer.project, integration.project]
    assert developer.description != integration.description

    developer.anchor.write_bytes(canonical({'project': str(integration.project)}))
    with pytest.raises(EnvironmentFailure, match='INSTALLATION_ANCHOR_MISMATCH'):
        load_site(developer.anchor, developer.expected, runtime, measure)
    assert observed == [developer.project, integration.project]

    (integration.project / 'program-snapshot.v1.json').write_bytes(b'different snapshot')
    with pytest.raises(EnvironmentFailure, match='GATEWAY_POLICY_MISMATCH'):
        load_site(integration.anchor, integration.expected, runtime, measure)


@pytest.mark.parametrize('is_candidate', (False, True))
def test_explicit_gateway_verifier_requires_an_ordinary_https_installation(
    monkeypatch, is_candidate
):
    from backend.app.infrastructure import environment_provision as provisioner

    monkeypatch.setattr(provisioner, 'os', SimpleNamespace(geteuid=lambda: 0))
    args = SimpleNamespace(
        purpose='CANDIDATE' if is_candidate else 'DEVELOPMENT',
        application_uid=4001,
        maintenance_uid=4002,
        group=4003,
        ingress_group=4004 if is_candidate else None,
    )
    candidate = object() if is_candidate else None
    with pytest.raises(EnvironmentFailure, match='GATEWAY_VERIFIER_NOT_ADMITTED'):
        provisioner.provision(args, validation=candidate, with_gateway_verifier=True)


def test_business_origin_rejects_foreign_and_noncanonical_inputs():
    default = f'https://e-{ENVIRONMENT}.walle-dev.test:9443'
    assert installation.business_origin(ENVIRONMENT) == default
    assert installation.validate_business_origin(default, ENVIRONMENT) == default
    prefix = f'https://e-{ENVIRONMENT}.'
    for suffix in (
        'site.example.test:443',
        'site.example.test:8443',
        'site.example.test.',
        'site.example.test/p',
        'site.example.test@cross.example.test',
        '*.example.test',
        '127.0.0.1',
        'validation..example.test',
        'Domain.example.test',
        '-validation.example.test',
    ):
        with pytest.raises(EnvironmentFailure, match='INVALID_ENVIRONMENT_ACCESS'):
            installation.validate_business_origin(prefix + suffix, ENVIRONMENT)
    with pytest.raises(EnvironmentFailure, match='INVALID_ENVIRONMENT_ACCESS'):
        installation.validate_business_origin(default, FOREIGN)


def test_candidate_policy_pins_exact_endpoint(monkeypatch, tmp_path):
    pytest.importorskip('grp')
    from backend.app.infrastructure.environment_files import identity
    from backend.app.management import operation_contract, release_validation

    root = PurePosixPath('/srv/walle-validate')
    path = tmp_path / release_validation.POLICY
    scope = {'manager_id': ENVIRONMENT, 'host_id': FOREIGN, 'registry_generation': ENVIRONMENT}
    catalog = SimpleNamespace(scope=scope, directory=PurePosixPath('/srv/manager-catalog'))
    registry = SimpleNamespace(uid=100, gid=101)
    plan = {
        'format_version': 1,
        **scope,
        'operation_id': ENVIRONMENT,
        'release_id': FOREIGN,
        'candidate_sha256': 'a' * 64,
        'delivery_operation_id': ENVIRONMENT,
        'manifest_sha256': 'b' * 64,
        'host_root': {'path': str(root), 'identity': identity(tmp_path.stat())},
        'environment_id': ENVIRONMENT,
        'data_generation': FOREIGN,
        'deployment_id': '20001111-5050-4ccf-a123-111111111111',
        'application_uid': 1000,
        'maintenance_uid': 1001,
        'shared_gid': 1002,
        'ingress_gid': 1003,
    }

    @contextmanager
    def host_directory(directory):
        assert directory == root
        yield None

    monkeypatch.setattr(operation_contract, 'read_protected', Path.read_bytes)
    monkeypatch.setattr(
        release_validation, 'os', SimpleNamespace(fstat=lambda descriptor: tmp_path.stat())
    )
    monkeypatch.setattr(release_validation, 'absolute', lambda value, _code: PurePosixPath(value))
    monkeypatch.setattr(release_validation, 'protected_directory', host_directory)
    monkeypatch.setattr(release_validation, 'check_ext4', lambda descriptor: None)

    def load(record, *, expected=None):
        raw = canonical(record)
        path.write_bytes(raw)
        return release_validation.load_policy(path, expected or digest(raw), catalog, registry)

    assert load(plan) == (plan, root, installation.business_origin(ENVIRONMENT))
    custom = {**plan, 'business_endpoint': {'domain': DOMAIN, 'port': 443}}
    assert load(custom) == (custom, root, installation.business_origin(ENVIRONMENT, DOMAIN, 443))
    with pytest.raises(EnvironmentFailure, match=release_validation.UNVERIFIED):
        load({**plan, 'business_endpoint': {'domain': '*.example.test', 'port': 443}})
    with pytest.raises(EnvironmentFailure, match=release_validation.UNVERIFIED):
        load(custom, expected=digest(canonical(plan)))


def test_candidate_installation_retry_rejects_different_installed_origin(monkeypatch, tmp_path):
    pytest.importorskip('grp')
    from backend.app.management import release_validation

    root = tmp_path / ENVIRONMENT
    root.mkdir()
    environment, generation, deployment = (
        ENVIRONMENT,
        FOREIGN,
        '20001111-5050-4ccf-a123-111111111111',
    )
    binding = {'policy_sha256': 'd' * 64}
    args = SimpleNamespace(
        host_root=tmp_path,
        schema=tmp_path / 'schema',
        application_uid=1000,
        maintenance_uid=1001,
        group=1002,
        ingress_group=1003,
        runtime_sha256='b' * 64,
        project=tmp_path / 'application',
    )
    origin = installation.business_origin(environment, DOMAIN, 443)
    admitted = release_validation.CandidateInstallation(
        (environment, generation, deployment),
        'c' * 64,
        'e' * 64,
        {},
        binding,
        origin,
    )
    anchor = root / installation.ANCHOR_NAME
    current = SimpleNamespace(
        environment_id=environment,
        data_generation=generation,
        deployment_id=deployment,
        schema=args.schema,
        application_uid=1000,
        maintenance_uid=1001,
        group=1002,
        ingress_group=1003,
        anchor=anchor,
        environment_root=root,
        path=lambda kind: root / kind,
        description={
            'purpose': 'CANDIDATE',
            'release_validation': binding,
            'program_source': {'kind': 'FIXED_RELEASE', 'sha256': admitted.program_sha},
            'schema_manifest_sha256': admitted.schema_sha,
        },
    )

    def protect(endpoint):
        raw = canonical(
            {
                'format_version': 1,
                'environment_id': environment,
                'public_origin': endpoint,
                'upstream_socket': str(root / 'runtime/walle.sock'),
                'principals': [
                    {
                        'principal_id': 'candidate-user',
                        'client_kind': 'WEB',
                        'permission': 'DEVELOP',
                    }
                ],
            }
        )
        path = root / installation.ACCESS_NAME
        path.write_bytes(raw)
        current.description['access_policy_ref'] = {'name': path.name, 'sha256': digest(raw)}

    monkeypatch.setattr(installation, 'read_protected', Path.read_bytes)
    monkeypatch.setattr(
        release_validation, 'snapshot_file', lambda *args, **kwargs: ('a' * 64, b'')
    )
    monkeypatch.setattr(release_validation, 'load_installation', lambda *args: current)
    monkeypatch.setattr(release_validation, 'directory_facts', lambda loaded: None)
    monkeypatch.setattr(release_validation, 'verify_validation_frontend', lambda *args: None)
    protect(origin)
    confirmed = release_validation.existing_candidate_installation(args, admitted)
    assert confirmed['deployment_id'] == deployment
    assert release_validation.existing_candidate_installation(args, admitted) == confirmed
    protect(installation.business_origin(environment, 'different.example.test', 443))
    with pytest.raises(EnvironmentFailure, match=release_validation.CONFLICT):
        release_validation.existing_candidate_installation(args, admitted)


def test_candidate_validation_can_use_only_the_bound_staging_package(monkeypatch):
    pytest.importorskip('grp')
    from backend.app.management import release_publication, release_validation

    stage = PurePosixPath('/srv/fixed-input')
    archive = PurePosixPath('/srv/fixed-output')
    published = archive / FOREIGN / release_validation.MANIFEST
    schema = PurePosixPath('/srv/schema')
    receiver = PurePosixPath('/srv/validation')
    observed_roots = []
    observations = []
    inspected = []
    plan = {
        'release_id': FOREIGN,
        'candidate_sha256': 'a' * 64,
        'delivery_operation_id': ENVIRONMENT,
        'manifest_sha256': 'b' * 64,
    }
    descriptor = {
        'delivery_operation_id': ENVIRONMENT,
        'manifest_ref': (published, plan['manifest_sha256']),
        'schema_ref': (schema, 'c' * 64),
    }
    pin = plan['manifest_sha256']
    checked = {
        'source_commit': '4' * 40,
        'runtime_manifest_sha256': '5' * 64,
        'schema_manifest_sha256': 'c' * 64,
        'target_os': 'linux',
        'target_arch': 'x86_64',
        'application_files': 36,
        'frontend_files': 3,
    }
    manifest = dict(checked)
    catalog = SimpleNamespace(directory=PurePosixPath('/srv/management'))
    registry = SimpleNamespace(uid=1234, gid=4321)
    args = SimpleNamespace(
        sha256='5' * 64,
        release_publication_policy=None,
        release_publication_policy_sha256='d' * 64,
        root=PurePosixPath('/srv/runtime'),
        project=PurePosixPath('/srv/manager-program'),
        runtime_entry=PurePosixPath('/srv/runtime/metadata/runtime.py'),
        anchor=catalog.directory / 'installation.v1.json',
        anchor_sha256='6' * 64,
        program_sha256='7' * 64,
        catalog=catalog.directory / 'management-catalog.v1.json',
        catalog_sha256='8' * 64,
    )

    @contextmanager
    def permitted_root(path, token):
        observed_roots.append((path, token))
        yield

    def verify_inputs(anchor, accepted_pin, runtime):
        assert accepted_pin == pin and runtime == args.sha256
        inspected.append(anchor)
        return checked, manifest

    def observe(uid, gid, argv, area):
        assert (uid, gid) == (registry.uid, registry.gid)
        assert area == catalog.directory / 'observations'
        observations.append(argv)
        return {'status': 'RELEASE_CANDIDATE_PACKAGED', **plan, **checked}

    publication = {
        'release_id': plan['release_id'],
        'candidate_sha256': plan['candidate_sha256'],
        'build_root': {'identity': 'build identity'},
        'publication_root': {'identity': 'publication identity'},
    }
    monkeypatch.setattr(release_validation, 'installed_candidate', lambda *_: descriptor)
    monkeypatch.setattr(release_validation, 'path_reference', lambda reference: reference)
    monkeypatch.setattr(release_validation, 'verify_release_details', verify_inputs)
    monkeypatch.setattr(release_publication, 'checked_root', permitted_root)
    monkeypatch.setattr(release_publication, 'invoke_observer', observe)
    monkeypatch.setattr(
        release_publication,
        'publication_inputs',
        lambda *_: (publication, stage, archive, descriptor, pin),
    )

    def inspect(host=receiver):
        return release_validation.inspect_candidate(
            catalog, registry, args, plan, 'fixed-tool', host=host
        )

    assert inspect() == (published, schema, manifest)
    assert observations[-1][1] == 'candidate'
    assert observed_roots == []
    args.release_publication_policy = PurePosixPath(
        '/srv/trusted/release-publication-policy.v1.json'
    )
    assert inspect() == (stage / release_validation.MANIFEST, schema, manifest)
    assert inspected[-1] == stage / release_validation.MANIFEST
    assert observed_roots == [(stage, 'build identity'), (archive, 'publication identity')]
    assert observations[-1][1] == 'inspect-release-build'
    assert observations[-1][-4:] == [
        '--release-publication-policy',
        args.release_publication_policy,
        '--release-publication-policy-sha256',
        args.release_publication_policy_sha256,
    ]

    with pytest.raises(EnvironmentFailure, match=release_validation.UNVERIFIED):
        inspect(archive / 'candidate-run')
    publication['candidate_sha256'] = '9' * 64
    with pytest.raises(EnvironmentFailure, match=release_validation.UNVERIFIED):
        inspect()
    assert len(observations) == len(inspected) == 2
