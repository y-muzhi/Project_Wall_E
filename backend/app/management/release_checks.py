"""Read independently recorded evidence for exactly one sealed candidate."""

from backend.app.infrastructure.environment_files import (
    MAX_RECORD_SIZE,
    absolute,
    canonical,
    decode,
    digest,
    exact,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value

from .delivery_evidence import artifact
from .operation_contract import installed_record
from .registry import is_timestamp
from .recovery_evidence import parse_local_recovery
from .release_artifacts import snapshot_file

UNVERIFIED = 'RELEASE_CHECK_EVIDENCE_UNVERIFIED'
KINDS = ('BUILD_OFFLINE', 'ISOLATED_APPLICATION', 'BROWSER_FLOW', 'RECOVERY')


def binding(manifest, delivery):
    subject = {
        key: manifest[key]
        for key in (
            'release_id',
            'source_commit',
            'target_os',
            'target_arch',
            'runtime_manifest_sha256',
            'schema_manifest_sha256',
            'binding_protocol',
            'management_protocol',
            'maintenance_contract',
        )
    }
    subject.update(
        source_tree=delivery['tree'],
        application_index_sha256=manifest['application_index_ref']['sha256'],
        frontend_index_sha256=manifest['frontend_index_ref']['sha256'],
        resource_refs=sorted(manifest['resource_refs'], key=lambda item: item['ref']),
    )
    return digest(canonical(subject))


def verification_readiness(checks):
    recorded = {item['kind'] for item in checks}
    blocking = {item['kind'] for item in checks if item['result'] != 'PASSED'}
    missing = [kind for kind in KINDS if kind not in recorded]
    if blocking:
        state = 'CHECKS_BLOCKED'
    elif missing:
        state = 'CHECKS_REQUIRED'
    else:
        state = 'REQUIRED_EVIDENCE_RECORDED'
    return {
        'state': state,
        'required_kinds': list(KINDS),
        'missing_kinds': missing,
        'blocking_kinds': [kind for kind in KINDS if kind in blocking],
    }


def verify_recovery_artifact(reference, manifest, application_root, checked_at):
    exact(reference, ('path', 'sha256', 'bytes'), UNVERIFIED)
    require(
        sha_value(reference['sha256'])
        and type(reference['bytes']) is int
        and 0 < reference['bytes'] <= MAX_RECORD_SIZE,
        UNVERIFIED,
    )
    actual, raw = snapshot_file(
        absolute(reference['path'], UNVERIFIED), 0o444, reference['bytes'], capture=True
    )
    require(actual == reference['sha256'], UNVERIFIED)
    program_sha, _ = snapshot_file(application_root / 'program-snapshot.v1.json', 0o444)
    proof = parse_local_recovery(decode(raw, UNVERIFIED), UNVERIFIED)
    require(
        proof['runtime_manifest_sha256'] == manifest['runtime_manifest_sha256']
        and proof['schema_manifest_sha256'] == manifest['schema_manifest_sha256']
        and proof['program_snapshot_sha256'] == program_sha
        and proof['frontend_index_sha256'] == manifest['frontend_index_ref']['sha256']
        and proof['verified_at'] <= checked_at,
        UNVERIFIED,
    )
    return {'sha256': actual, 'bytes': reference['bytes']}


def verification_evidence(catalog, manifest, delivery, application_root):
    if not manifest['verification_refs']:
        return 'NOT_EVALUATED', []
    subject = binding(manifest, delivery)
    checks = []
    for reference in manifest['verification_refs']:
        identifier = reference['ref']
        require(uuid_value(identifier), UNVERIFIED)
        location = catalog.directory / 'release-checks' / (identifier + '.json')
        record = exact(
            installed_record(location, reference['sha256'], code=UNVERIFIED),
            (
                'format_version',
                *catalog.scope,
                'reference',
                'kind',
                'runner_ref',
                'checked_at',
                'result',
                'binding_sha256',
                'artifact',
            ),
            UNVERIFIED,
        )
        require(
            type(record['format_version']) is int
            and record['format_version'] == 1
            and all(record[key] == value for key, value in catalog.scope.items())
            and record['reference'] == identifier
            and uuid_value(record['runner_ref'])
            and record['binding_sha256'] == subject
            and record['kind'] in KINDS
            and record['result'] in ('PASSED', 'FAILED', 'INCONCLUSIVE')
            and is_timestamp(record['checked_at']),
            UNVERIFIED,
        )
        if record['kind'] == 'RECOVERY' and record['result'] == 'PASSED':
            output = verify_recovery_artifact(
                record['artifact'], manifest, application_root, record['checked_at']
            )
        else:
            output = artifact(record['artifact'])
        checks.append(
            {
                'ref': identifier,
                'kind': record['kind'],
                'result': record['result'],
                'checked_at': record['checked_at'],
                'artifact_sha256': output['sha256'],
            }
        )
    state = (
        'EVIDENCE_RECORDED'
        if all(check['result'] == 'PASSED' for check in checks)
        else 'CHECKS_BLOCKED'
    )
    return state, checks
