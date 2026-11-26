"""Bind a sealed release's actual files to one registered integration delivery."""

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    exact,
    protected_directory,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value
from backend.app.infrastructure.schema_v22_release import load_release

from .delivery_evidence import admitted_reference
from .operation_contract import INVALID, MISSING, commit, installed_record, path_reference
from .operation_store import decoded
from .registry import is_timestamp
from .release_artifacts import MANIFEST, verify_release_details
from .release_checks import verification_evidence, verification_readiness

UNVERIFIED = 'RELEASE_CANDIDATE_UNVERIFIED'


def installed_candidate(catalog, release_id, expected):
    require(uuid_value(release_id) and sha_value(expected), INVALID)
    require(catalog.release_candidates.get(release_id) == expected, MISSING)
    record = exact(
        installed_record(
            catalog.directory / 'release-candidates' / (release_id + '.json'), expected
        ),
        (
            'format_version',
            *catalog.scope,
            'release_id',
            'delivery_operation_id',
            'manifest_ref',
            'schema_ref',
            'build_record_ref',
        ),
        INVALID,
    )
    require(
        type(record['format_version']) is int
        and record['format_version'] == 1
        and all(record[key] == value for key, value in catalog.scope.items())
        and record['release_id'] == release_id
        and uuid_value(record['delivery_operation_id']),
        INVALID,
    )
    return record


def original_delivery(connection, generation, delivery_id, purpose):
    row = connection.execute(
        'SELECT d.commit_oid,d.evidence_json,d.environment_id,d.assignment_generation,'
        'op.status,op.action,env.purpose,op.registry_generation '
        'FROM delivery_snapshots AS d '
        'JOIN management_operations AS op ON op.operation_id=d.operation_id AND op.environment_id=d.environment_id '
        'JOIN managed_environments AS env ON env.environment_id=d.environment_id '
        'WHERE d.operation_id=? AND op.registry_generation=?',
        (delivery_id, generation),
    ).fetchone()
    require(
        row is not None
        and row['action'] == 'REGISTER_DELIVERY'
        and row['status'] == 'SUCCEEDED'
        and row['purpose'] == purpose,
        UNVERIFIED,
    )
    evidence = decoded(row['evidence_json'])
    require(
        evidence.get('commit') == row['commit_oid']
        and evidence.get('environment_id') == row['environment_id']
        and evidence.get('assignment_generation') == row['assignment_generation']
        and uuid_value(evidence.get('repository_ref'))
        and uuid_value(evidence.get('proof_id'))
        and is_timestamp(evidence.get('verified_at')),
        UNVERIFIED,
    )
    commit(evidence['commit'])
    commit(evidence.get('tree'))
    require(len(evidence['tree']) == len(evidence['commit']), UNVERIFIED)
    return evidence


def resolve_sources(connection, generation, integration):
    sources = integration.get('source_deliveries')
    require(type(sources) is list and 0 < len(sources) <= 64, UNVERIFIED)
    seen = set()
    for raw in sources:
        exact(raw, ('environment_id', 'commit', 'delivery_operation_id'), UNVERIFIED)
        environment_id = raw['environment_id']
        reference = raw['delivery_operation_id']
        require(
            uuid_value(environment_id) and uuid_value(reference) and environment_id not in seen,
            UNVERIFIED,
        )
        source = original_delivery(connection, generation, reference, 'DEVELOPMENT')
        require(
            source['environment_id'] == environment_id
            and source['commit'] == raw['commit']
            and source['repository_ref'] == integration['repository_ref'],
            UNVERIFIED,
        )
        seen.add(environment_id)
    return sources


def admitted_resources(catalog, delivery):
    accepted = delivery.get('resource_refs')
    require(type(accepted) is list, UNVERIFIED)
    expected = {}
    for item in accepted:
        exact(item, ('ref', 'sha256', 'bytes'), UNVERIFIED)
        reference = item['ref']
        require(uuid_value(reference) and reference not in expected, UNVERIFIED)
        actual = admitted_reference(catalog, reference, delivery, delivery, check=False)
        require(actual == item, UNVERIFIED)
        expected[reference] = actual['sha256']
    return expected


def verify_resources(catalog, delivery, manifest):
    expected = admitted_resources(catalog, delivery)
    require(
        {item['ref']: item['sha256'] for item in manifest['resource_refs']} == expected, UNVERIFIED
    )
    return expected


def check_build(catalog, descriptor, release, manifest, delivery):
    path, pin = path_reference(descriptor['build_record_ref'])
    build = exact(
        installed_record(path, pin),
        (
            'format_version',
            *catalog.scope,
            'release_id',
            'delivery_operation_id',
            'repository_ref',
            'source_commit',
            'source_tree',
            'target_os',
            'target_arch',
            'application_index_sha256',
            'frontend_index_sha256',
            'runtime_manifest_sha256',
            'schema_manifest_sha256',
            'built_at',
        ),
        UNVERIFIED,
    )
    expected = {
        'format_version': 1,
        **catalog.scope,
        'release_id': release['release_id'],
        'delivery_operation_id': descriptor['delivery_operation_id'],
        'repository_ref': delivery['repository_ref'],
        'source_commit': delivery['commit'],
        'source_tree': delivery['tree'],
        **{
            key: release[key]
            for key in (
                'target_os',
                'target_arch',
                'runtime_manifest_sha256',
                'schema_manifest_sha256',
            )
        },
        **{
            role + '_index_sha256': manifest[role + '_index_ref']['sha256']
            for role in ('application', 'frontend')
        },
    }
    require(
        type(build['format_version']) is int
        and all(build[key] == value for key, value in expected.items())
        and is_timestamp(build['built_at']),
        UNVERIFIED,
    )
    return pin


def integration_delivery(connection, catalog, operation_id):
    generation = catalog.scope['registry_generation']
    delivery = original_delivery(connection, generation, operation_id, 'INTEGRATION')
    return delivery, resolve_sources(connection, generation, delivery)


def candidate_inputs(connection, catalog, release_id, expected):
    descriptor = installed_candidate(catalog, release_id, expected)
    delivery, sources = integration_delivery(
        connection, catalog, descriptor['delivery_operation_id']
    )
    return descriptor, delivery, sources


def verify_candidate(catalog, release_id, expected, runtime_sha, inputs, *, staged_root=None):
    descriptor, delivery, sources = inputs
    anchor, manifest_sha = path_reference(descriptor['manifest_ref'])
    if staged_root is not None:
        anchor = staged_root / MANIFEST
    checked, manifest = verify_release_details(anchor, manifest_sha, runtime_sha)
    require(
        checked['release_id'] == release_id and checked['source_commit'] == delivery['commit'],
        UNVERIFIED,
    )
    schema, schema_sha = path_reference(descriptor['schema_ref'])
    require(schema_sha == checked['schema_manifest_sha256'], UNVERIFIED)
    application = anchor.parent / 'application'
    try:
        with protected_directory(schema):
            explicit_schema = load_release(schema, schema_sha, runtime_sha, source_root=application)
    except (ValueError, OSError, RuntimeError) as error:
        raise EnvironmentFailure(UNVERIFIED) from error
    resources = verify_resources(catalog, delivery, manifest)
    build_sha = check_build(catalog, descriptor, checked, manifest, delivery)
    state, checks = verification_evidence(catalog, manifest, delivery, application)
    return {
        **checked,
        'status': 'RELEASE_CANDIDATE_PACKAGED',
        'candidate_sha256': expected,
        'delivery_operation_id': descriptor['delivery_operation_id'],
        'source_tree': delivery['tree'],
        'source_deliveries': sources,
        'schema_contract_sha256': explicit_schema.schema_contract_sha256,
        'resource_count': len(resources),
        'build_record_sha256': build_sha,
        'verification_state': state,
        'verification_checks': checks,
        'verification_readiness': verification_readiness(checks),
    }
