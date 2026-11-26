"""Publish a protected authorization for the selected registry's stopped deployment."""

import os

from backend.app.infrastructure.environment_backup_package import read_policy
from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    decode,
    digest,
    exact,
    protected_directory,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value

from .registry_installation import require_registry_root
from .registry_recovery_deployment_entry import VERIFIED, verified_deployment_entry
from .registry_recovery_reobserve import selected_observation_inputs
from .registry_recovery_selection import preserve_fact, protected_fact

POLICY = 'registry-recovery-adopt-policy.v1.json'
POLICY_FIELDS = (
    'operation_id',
    'registry_anchor_sha256',
    'assessment_sha256',
    'verification_sha256',
)
UNVERIFIED = 'MANAGEMENT_REGISTRY_RECOVERY_DEPLOYMENT_ADOPTION_UNVERIFIED'
AUTHORIZED = 'MANAGEMENT_REGISTRY_RECOVERY_DEPLOYMENT_ADOPTION_AUTHORIZED'
RECEIPT_FIELDS = (
    'format_version',
    'status',
    'operation_id',
    'registry_generation',
    'registry_anchor_sha256',
    'assessment_sha256',
    'authorization_policy_sha256',
    'verification',
)


def authorization_name(operation_id):
    require(uuid_value(operation_id), UNVERIFIED)
    return f'deployment-adoption-{operation_id}.v1.json'


def authorize_deployment_adoption(native, installation, args, entry):
    try:
        policy_pin = args.registry_disposition_policy_sha256
        policy = read_policy(args.registry_disposition_policy, policy_pin, POLICY, POLICY_FIELDS)
        name = authorization_name(policy['operation_id'])
        require(
            policy['registry_anchor_sha256'] == installation.sha256
            and sha_value(policy['assessment_sha256'])
            and sha_value(policy['verification_sha256']),
            UNVERIFIED,
        )
        with selected_observation_inputs(native, installation, args) as inputs:
            current, _, _, _, verify_source = inputs
            verification = verified_deployment_entry(native, args, entry, inputs)
            require(
                verification['verification_sha256'] == policy['verification_sha256']
                and verification['deployment_operation_id'] == policy['operation_id']
                and verification['registry_generation'] == current.registry_generation,
                UNVERIFIED,
            )
            receipt = {
                'format_version': 1,
                'status': AUTHORIZED,
                'operation_id': policy['operation_id'],
                'registry_generation': current.registry_generation,
                'registry_anchor_sha256': current.sha256,
                'assessment_sha256': policy['assessment_sha256'],
                'authorization_policy_sha256': policy_pin,
                'verification': verification,
            }
            raw = canonical(receipt)
            pin = digest(raw)
            verify_source()
            with protected_directory(current.directory_root) as directory:
                require_registry_root(
                    os.fstat(directory), current.generation_root_facts, current.gid
                )
                previous = protected_fact(directory, name, current.gid)
                require(previous is None or previous == raw, UNVERIFIED)
                try:
                    if previous is None:
                        preserve_fact(directory, name, current.gid, raw)
                    os.fsync(directory)
                    verify_source()
                    require(
                        authorized_deployment(current, policy['operation_id'], pin) == receipt,
                        UNVERIFIED,
                    )
                except (EnvironmentFailure, OSError, KeyError, TypeError, ValueError) as error:
                    raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
            return {**receipt, 'authorization_sha256': pin}
    except EnvironmentFailure:
        raise
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise EnvironmentFailure(UNVERIFIED) from error


def authorized_deployment(installation, operation_id, pin):
    name = authorization_name(operation_id)
    require(sha_value(pin) and installation.generation_root_facts is not None, UNVERIFIED)
    with protected_directory(installation.directory_root) as directory:
        require_registry_root(
            os.fstat(directory), installation.generation_root_facts, installation.gid
        )
        raw = protected_fact(directory, name, installation.gid)
        require(raw is not None and digest(raw) == pin, UNVERIFIED)
    record = exact(decode(raw, UNVERIFIED), RECEIPT_FIELDS, UNVERIFIED)
    verification = record['verification']
    require(
        type(record['format_version']) is int
        and record['format_version'] == 1
        and record['status'] == AUTHORIZED
        and record['operation_id'] == operation_id
        and record['registry_anchor_sha256'] == installation.sha256
        and record['registry_generation'] == installation.registry_generation
        and all(
            sha_value(record[key]) for key in ('assessment_sha256', 'authorization_policy_sha256')
        )
        and type(verification) is dict
        and verification['status'] == VERIFIED
        and verification['deployment_operation_id'] == operation_id
        and verification['registry_generation'] == installation.registry_generation
        and verification['verification_sha256']
        == digest(
            canonical(
                {key: value for key, value in verification.items() if key != 'verification_sha256'}
            )
        ),
        UNVERIFIED,
    )
    return record
