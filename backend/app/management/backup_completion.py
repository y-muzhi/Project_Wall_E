"""Verify the sealed original backup, read-only rehearsal and publish a bound receipt."""

import fcntl
import os

from backend.app.infrastructure.environment_backup_package import (
    private_root,
    read_evidence,
    verify_contents,
)
from backend.app.infrastructure.environment_files import canonical, digest, exact, require
from backend.app.infrastructure.environment_installation import (
    identity_record,
    sha_value,
    uuid_value,
    version_record,
)

from .attachment_observation import now
from .backup_capture import CAPTURED, EXECUTIONS, admitted_backup, checked_capture_receipt
from .operation_contract import DENIED, INVALID, RESOURCE, installed_record, path_reference
from .recovery_catalog import local_metadata
from .recovery_evidence import backup_cutoff
from .recovery_offhost import offhost_metadata
from .release_configuration import CHANGED
from .release_execution import execution_directory, optional_fact, write_fact

POLICY = 'managed-backup-result.v1.json'
OFFHOST_POLICY = 'managed-backup-result.v2.json'
LOCAL_STAGE = 'local-verified.v1.json'
LOCAL_STATUS = 'MANAGED_BACKUP_WAITING_OFFHOST'
COMPLETE = 'verified.v1.json'
COMPLETE_STATUS = 'MANAGED_BACKUP_LOCAL_VERIFIED'
OFFHOST_COMPLETE = 'MANAGED_BACKUP_OFFHOST_VERIFIED'
UNVERIFIED = 'MANAGED_BACKUP_RESULT_UNVERIFIED'


def load_result(catalog, args, *, offhost=False):
    path = args.managed_backup_result_policy
    require(path.is_absolute() and path.name == (OFFHOST_POLICY if offhost else POLICY), INVALID)
    raw = installed_record(path, args.managed_backup_result_policy_sha256)
    fields = (*catalog.scope, 'operation_id', 'package', 'local_verification')
    if offhost:
        exact(raw, ('format_version', *fields, 'offhost_verification'), INVALID)
        require(type(raw['format_version']) is int and raw['format_version'] == 2, INVALID)
    else:
        version_record(raw, fields, INVALID)
    require(
        raw['operation_id'] == args.backup_operation_id
        and all(raw[key] == value for key, value in catalog.scope.items()),
        INVALID,
    )
    package = exact(raw['package'], ('path', 'sha256', 'identity'), INVALID)
    folder, pin = path_reference({'path': package['path'], 'sha256': package['sha256']})
    identity_record(package['identity'], INVALID)
    proof, witness = path_reference(raw['local_verification'])
    reference = raw.get('offhost_verification')
    return (folder, pin, package['identity'], proof, witness), (
        None if reference is None else path_reference(reference)
    )


def point_from_package(source, grant, captured, inputs, observed_at):
    folder, pin, expected_identity, verification, proof_pin = inputs
    with private_root(folder, expected_identity, source) as fd:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        manifest, measured = verify_contents(fd, source, grant['backup_id'], expected_manifest=pin)
        evidence = read_evidence(fd, source, manifest)
    program = manifest['program_and_configuration_refs']
    require(
        manifest['backup_id'] == grant['backup_id']
        and manifest['source_environment_id'] == grant['environment_id']
        and manifest['source_data_generation'] == captured['data_generation']
        and manifest['source_deployment_id'] == captured['deployment_id']
        and manifest['source_control_revision'] == captured['control_revision']
        and backup_cutoff(manifest['cutoff_at'], UNVERIFIED) == captured['cutoff_at']
        and manifest['capture_receipt_ref']['sha256'] == captured['capture_receipt_sha256']
        and manifest['database_artifact']['sha256'] == captured['database_sha256']
        and manifest['database_artifact']['bytes'] == captured['database_bytes']
        and program['program_sha256'] == grant['source']['program_sha256']
        and program['configuration_sha256'] == grant['source']['configuration_sha256'],
        CHANGED,
    )
    point = {
        'backup_id': grant['backup_id'],
        'source_environment_id': grant['environment_id'],
        'source_data_generation': captured['data_generation'],
        'source_deployment_id': captured['deployment_id'],
        'source_control_revision': captured['control_revision'],
        'cutoff_at': captured['cutoff_at'],
        'backup_manifest_sha256': measured,
        'database_bytes': captured['database_bytes'],
        'logical_content_sha256': manifest['logical_content_sha256'],
        'count_audit_state': evidence['coverage_ref']['audit_state'],
        'program_sha256': program['program_sha256'],
        'configuration_sha256': program['configuration_sha256'],
    }
    proof = installed_record(verification, proof_pin)
    require(
        verification.name == 'local-verified-' + proof['verification_id'] + '.v1.json'
        and point['count_audit_state'] in ('ABSENT', 'EMPTY', 'FILES'),
        UNVERIFIED,
    )
    return {
        **point,
        'verification_status': 'LOCAL_VERIFIED',
        'local_verification': local_metadata(proof, point, grant['environment_id'], observed_at),
        'local_snapshot_retrieval': None,
    }


def protect_local_stage(fd, binding, inputs, point, observed, policy_sha):
    folder, manifest, identity, note, proof = inputs
    subject = {
        **binding,
        'status': LOCAL_STATUS,
        'local_inputs_sha256': digest(
            canonical(
                {
                    'package_directory': str(folder),
                    'backup_manifest_sha256': manifest,
                    'package_identity': identity,
                    'local_verification': str(note),
                    'local_verification_sha256': proof,
                }
            )
        ),
        'point': point,
    }
    previous = optional_fact(fd, LOCAL_STAGE)
    if previous is not None:
        require(
            all(previous.get(key) == value for key, value in subject.items())
            and set(previous) == {*subject, 'observed_at', 'local_policy_sha256'}
            and sha_value(previous['local_policy_sha256']),
            CHANGED,
        )
        os.fsync(fd)
        return previous
    staged = {**subject, 'observed_at': observed, 'local_policy_sha256': policy_sha}
    write_fact(fd, LOCAL_STAGE, staged)
    return staged


def complete_managed_backup(catalog, registry, args, launcher):
    operation = args.backup_operation_id
    require(os.geteuid() == 0 and uuid_value(operation), DENIED)
    with execution_directory(catalog, EXECUTIONS, operation) as (_, fd):
        grant, source = admitted_backup(catalog, registry, args, launcher)
        captured = optional_fact(fd, CAPTURED)
        require(captured is not None, RESOURCE)
        checked_capture_receipt(captured, grant)
        authority = grant.get('offhost_authority')
        binding = {
            'format_version': 1,
            **catalog.scope,
            'operation_id': operation,
            'grant_sha256': digest(canonical(grant)),
            'capture_sha256': digest(canonical(captured)),
        }
        record = {
            **binding,
            'status': COMPLETE_STATUS if authority is None else OFFHOST_COMPLETE,
            'result_policy_sha256': args.managed_backup_result_policy_sha256,
        }
        require(sha_value(record['result_policy_sha256']), INVALID)
        known = optional_fact(fd, COMPLETE)
        if known is not None:
            if all(known[key] == value for key, value in record.items()):
                os.fsync(fd)
                return known
            staged = optional_fact(fd, LOCAL_STAGE) if authority is not None else None
            require(
                staged is not None
                and staged['local_policy_sha256'] == record['result_policy_sha256']
                and all(staged[key] == value for key, value in binding.items()),
                CHANGED,
            )
            os.fsync(fd)
            return staged
        inputs, reference = load_result(catalog, args, offhost=authority is not None)
        observed = now()
        point = point_from_package(source, grant, captured, inputs, observed)
        if authority is not None:
            local = protect_local_stage(
                fd, binding, inputs, point, observed, record['result_policy_sha256']
            )
            if reference is None:
                return local
            proof, pin = reference
            report = installed_record(proof, pin)
            verified = offhost_metadata(
                report, point, grant['environment_id'], observed, authority, UNVERIFIED
            )
            point = {
                **point,
                'verification_status': 'OFFHOST_VERIFIED',
                'offhost_verification': verified,
            }
            record['offhost_verification_sha256'] = pin
        result = {**record, 'observed_at': observed, 'point': point}
        write_fact(fd, COMPLETE, result)
        return result
