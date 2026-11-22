"""Bind a closed ordinary source and a fixed same-schema release without changing either."""

from dataclasses import dataclass
import fcntl
from types import SimpleNamespace

from backend.app.management.recovery_evidence import parse_local_recovery
from backend.app.management.registry import is_timestamp
from backend.app.management.release_artifacts import (
    MANIFEST as RELEASE_MANIFEST,
    snapshot_file,
    verify_release_details,
)
from backend.app.management.release_checks import KINDS, verification_readiness

from .environment_backup import capture_inputs
from .environment_backup_coverage import check_coverage
from .environment_backup_package import (
    VERIFY_POLICY,
    principal_for_process,
    private_root,
    read_evidence,
    read_policy,
    verification_inputs,
    verify_contents,
)
from .environment_files import (
    absolute,
    canonical,
    decode,
    digest,
    exact,
    protected_directory,
    read_protected,
    require,
)
from .environment_installation import (
    ANCHOR_NAME,
    DEPLOYMENTS,
    RESTORE_MODE,
    load_installation,
    sha_value,
    uuid_value,
    version_record,
)
from .environment_recovery_installation import checked_ref
from .environment_release_compatibility import COMPATIBILITY, compatibility_record
from .schema_v22_release import load_release

POLICY = 'release-source-preflight.v1.json'
ROLLBACK_POLICY = 'rollback-source-preflight.v1.json'
CAPTURE_POLICY = 'database-capture.v1.json'
CANDIDATE_PROOF = 'release-candidate-check.v1.json'
INVALID = 'RELEASE_PREFLIGHT_INTENT_MISMATCH'
UNVERIFIED = 'RELEASE_PREFLIGHT_UNVERIFIED'


def read_reference(value, *, name=None):
    ref = exact(value, ('path', 'sha256'), INVALID)
    path = absolute(ref['path'], INVALID)
    require((name is None or path.name == name) and sha_value(ref['sha256']), INVALID)
    raw = read_protected(path)
    require(digest(raw) == ref['sha256'], UNVERIFIED)
    return decode(raw, UNVERIFIED)


def check_candidate_receipt(proof, actual, manifest):
    required = (
        'manifest_sha256',
        'release_id',
        'source_commit',
        'target_os',
        'target_arch',
        'runtime_manifest_sha256',
        'schema_manifest_sha256',
    )
    require(
        proof['status'] == 'RELEASE_CANDIDATE_PACKAGED'
        and all(proof[key] == actual[key] for key in required)
        and sha_value(proof['candidate_sha256'])
        and proof['verification_state'] == 'EVIDENCE_RECORDED',
        UNVERIFIED,
    )
    checks = proof['verification_checks']
    require(type(checks) is list and 1 <= len(checks) <= 256, UNVERIFIED)
    refs = set()
    for item in checks:
        exact(item, ('ref', 'kind', 'result', 'checked_at', 'artifact_sha256'), UNVERIFIED)
        key = item['ref']
        require(
            uuid_value(key)
            and key not in refs
            and item['kind'] in KINDS
            and item['result'] == 'PASSED'
            and is_timestamp(item['checked_at'])
            and sha_value(item['artifact_sha256']),
            UNVERIFIED,
        )
        refs.add(key)
    computed = verification_readiness(checks)
    require(
        refs == {item['ref'] for item in manifest['verification_refs']}
        and computed == proof['verification_readiness']
        and computed['state'] == 'REQUIRED_EVIDENCE_RECORDED',
        UNVERIFIED,
    )


def candidate_target(plan, active):
    manifest_path, manifest_sha = checked_ref(plan['target_manifest'], RELEASE_MANIFEST)
    actual, manifest = verify_release_details(
        manifest_path, manifest_sha, active.runtime_manifest_sha256
    )
    candidate = read_reference(plan['candidate_proof'], name=CANDIDATE_PROOF)
    check_candidate_receipt(candidate, actual, manifest)
    target_schema = absolute(plan['target_schema_directory'], INVALID)
    with protected_directory(target_schema):
        schema = load_release(
            target_schema, manifest['schema_manifest_sha256'], active.runtime_manifest_sha256
        )
    require(schema.schema_contract_sha256 == candidate['schema_contract_sha256'], UNVERIFIED)
    target_program, _ = snapshot_file(
        manifest_path.parent / 'application/program-snapshot.v1.json', 0o444
    )
    return candidate, manifest, schema, target_program


def verified_backup(args, item, backup_id):
    policy_path, policy_sha = checked_ref(item, VERIFY_POLICY)
    verification, root = verification_inputs(
        SimpleNamespace(
            anchor=policy_path,
            anchor_sha256=policy_sha,
            root=args.root,
            project=args.project,
            home=args.home,
            temporary=args.temporary,
        ),
    )
    require(backup_id == verification['backup_id'], INVALID)
    principal = principal_for_process()
    with private_root(root, verification['package_identity'], principal) as directory:
        fcntl.flock(directory, fcntl.LOCK_SH | fcntl.LOCK_NB)
        manifest, measured = verify_contents(
            directory,
            principal,
            backup_id,
            expected_manifest=verification['backup_manifest_sha256'],
        )
        evidence = read_evidence(directory, principal, manifest)
    return manifest, measured, evidence['coverage_ref']


def rollback_subject(plan, source, manifest, target_program, entry):
    binding = source.description.get('deployment_slot')
    require(binding is not None and 'recovery_replica' not in source.description, INVALID)
    anchor, pin = checked_ref(plan['previous_installation'], ANCHOR_NAME)
    project = absolute(plan['previous_project'], INVALID)
    require(
        anchor
        == source.environment_root / DEPLOYMENTS / binding['source_deployment_id'] / ANCHOR_NAME
        and project == absolute(plan['target_manifest']['path'], INVALID).parent / 'application'
        and entry['verify_program'](project) == target_program,
        UNVERIFIED,
    )
    previous = load_installation(anchor, pin, manifest['runtime_manifest_sha256'], project)
    original = previous.description.get('deployment_slot')
    require(
        original is not None
        and previous.configuration_sha256 == binding['source_configuration_sha256']
        and previous.environment_id == source.environment_id
        and (
            previous.data_generation == source.data_generation
            or binding['authorization_mode'] == RESTORE_MODE
        )
        and previous.lock_identity == source.lock_identity
        and previous.description['program_source']
        == {'kind': 'FIXED_RELEASE', 'sha256': target_program}
        and previous.description['schema_manifest_sha256'] == manifest['schema_manifest_sha256']
        and previous.schema == absolute(plan['target_schema_directory'], INVALID)
        and original['release_id'] == manifest['release_id']
        and original['manifest_sha256'] == plan['target_manifest']['sha256']
        and original['frontend_index_sha256'] == manifest['frontend_index_ref']['sha256'],
        UNVERIFIED,
    )
    return previous


def compatibility(plan, source, current, manifest, target, target_program, *, rollback=False):
    proof = read_reference(plan['compatibility_ref'], name=COMPATIBILITY)
    require(uuid_value(proof.get('compatibility_id')), INVALID)
    if not rollback:
        require(
            {'ref': proof['compatibility_id'], 'sha256': plan['compatibility_ref']['sha256']}
            in manifest['compatibility_refs'],
            UNVERIFIED,
        )
    expected = compatibility_record(
        proof['compatibility_id'],
        source,
        current,
        manifest,
        target,
        target_program,
        code=UNVERIFIED,
    )
    version_record(proof, tuple(key for key in expected if key != 'format_version'), UNVERIFIED)
    require(proof == expected, UNVERIFIED)
    return proof['compatibility_id']


@dataclass(frozen=True)
class ReleasePreflight:
    receipt: dict
    coverage: dict
    capture_arguments: SimpleNamespace


def preflight_inputs(active, args, entry):
    policy_name = args.release_preflight_policy.name
    require(policy_name in (POLICY, ROLLBACK_POLICY), INVALID)
    rollback = policy_name == ROLLBACK_POLICY
    plan = read_policy(
        args.release_preflight_policy,
        args.release_preflight_policy_sha256,
        policy_name,
        (
            'operation_id',
            'installation_sha256',
            'capture_policy',
            'backup_id',
            'backup_verification',
            'local_verification',
            'candidate_proof',
            'target_manifest',
            'target_schema_directory',
            'compatibility_ref',
            *(('previous_installation', 'previous_project') if rollback else ()),
        ),
    )
    require(
        uuid_value(plan['operation_id'])
        and uuid_value(plan['backup_id'])
        and plan['installation_sha256'] == args.anchor_sha256
        and sha_value(plan['installation_sha256']),
        INVALID,
    )
    policy, policy_sha = checked_ref(plan['capture_policy'], CAPTURE_POLICY)
    operations = SimpleNamespace(
        anchor=args.anchor,
        anchor_sha256=args.anchor_sha256,
        capture_policy=policy,
        capture_sha256=policy_sha,
    )
    capture, source, current = capture_inputs(active, operations, entry)
    maintenance = capture.get('maintenance')
    require(
        capture['format_version'] == 2
        and capture['operation_id'] == plan['backup_id']
        and maintenance is not None
        and maintenance['operation_id'] == plan['operation_id'],
        INVALID,
    )
    candidate, release, target, target_program = candidate_target(plan, active)
    package, measured, coverage = verified_backup(
        args, plan['backup_verification'], plan['backup_id']
    )
    local = parse_local_recovery(read_reference(plan['local_verification']), UNVERIFIED)
    require(
        local['backup_id'] == package['backup_id']
        and local['backup_manifest_sha256'] == measured
        and local['environment_id'] == source.environment_id
        and local['data_generation'] != source.data_generation
        and local['deployment_id'] != source.deployment_id
        and local['logical_content_sha256'] == package['logical_content_sha256']
        and local['verified_at'] >= package['cutoff_at']
        and coverage['capture_policy_sha256'] == policy_sha
        and current.schema_contract_sha256
        == target.schema_contract_sha256
        == coverage['schema_contract_sha256'],
        UNVERIFIED,
    )
    previous = rollback_subject(plan, source, release, target_program, entry) if rollback else None
    accepted = compatibility(
        plan, source, current, release, target, target_program, rollback=rollback
    )
    observed = {
        'format_version': 1,
        'status': 'CLOSED_RELEASE_PRECONDITIONS_VERIFIED',
        'mode': 'ROLLBACK_CODE' if rollback else 'SAME_SCHEMA',
        'preflight_policy_sha256': args.release_preflight_policy_sha256,
        'operation_id': plan['operation_id'],
        'maintenance_plan_sha256': maintenance['plan_sha256'],
        'source_environment_id': source.environment_id,
        'source_data_generation': source.data_generation,
        'source_deployment_id': source.deployment_id,
        'source_control_revision': coverage['control_revision'],
        'source_configuration_sha256': source.configuration_sha256,
        'backup_id': package['backup_id'],
        'backup_manifest_sha256': measured,
        'backup_local_verification_sha256': plan['local_verification']['sha256'],
        'target_release_id': release['release_id'],
        'target_release_manifest_sha256': candidate['manifest_sha256'],
        'target_program_snapshot_sha256': target_program,
        'schema_contract_sha256': target.schema_contract_sha256,
        'compatibility_id': accepted,
    }
    if previous is not None:
        observed['previous_fixed_deployment_id'] = previous.deployment_id
        observed['previous_installation_sha256'] = previous.anchor_sha256
    receipt = {**observed, 'release_preflight_sha256': digest(canonical(observed))}
    return ReleasePreflight(receipt, coverage, operations)


def preflight_release_source(native, active, args, entry):
    planned = preflight_inputs(active, args, entry)
    require(
        check_coverage(native, active, planned.capture_arguments, entry) == planned.coverage,
        UNVERIFIED,
    )
    return planned.receipt
