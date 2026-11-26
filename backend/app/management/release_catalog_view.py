"""List only installed fixed release configurations for an authorized target environment."""

from backend.app.infrastructure.environment_files import EnvironmentFailure, require
from backend.app.infrastructure.environment_installation import uuid_value

from .operation_contract import DENIED, INVALID, MISSING, RELEASE, installed_record
from .operation_store import conflicting_action, decoded, environment_row
from .release_configuration import CHANGED, configuration_action, read_configuration
from .release_operations import (
    binding_for_release,
    candidate_inputs,
    no_live_reservation,
    verify_candidate,
)


def installed_choices(catalog, identifier, source_attachment, action):
    for reference, pin in sorted(catalog.release_configurations.items()):
        raw = installed_record(
            catalog.directory / 'release-configurations' / (reference + '.json'), pin
        )
        if (
            raw.get('environment_id') == identifier
            and raw.get('source_attachment') == source_attachment
            and configuration_action(raw) == action
        ):
            yield read_configuration(catalog, reference, supported=False)


def checked_candidate(connection, catalog, configuration, runtime_sha):
    try:
        found = verify_candidate(
            catalog,
            configuration.release_ref,
            configuration.candidate_sha256,
            runtime_sha,
            candidate_inputs(
                connection, catalog, configuration.release_ref, configuration.candidate_sha256
            ),
        )
        require(
            found['candidate_sha256'] == configuration.candidate_sha256
            and found['manifest_sha256'] == configuration.manifest_reference['sha256'],
            CHANGED,
        )
    except (EnvironmentFailure, OSError):
        return None
    return found


def option_state(connection, catalog, row, config, candidate):
    if (
        config.recovery['minimum_verification'] == 'OFFHOST_VERIFIED'
        and 'offhost_authority' not in config.recovery
    ):
        return 'RECOVERY_NOT_ADMITTED'
    if (
        candidate is None
        or candidate['verification_readiness']['state'] != 'REQUIRED_EVIDENCE_RECORDED'
    ):
        return 'CANDIDATE_UNVERIFIED'
    if conflicting_action(connection, row['environment_id']):
        return 'ENVIRONMENT_BUSY'
    try:
        no_live_reservation(connection, row['environment_id'])
        binding_for_release(
            catalog, row, config.public_references(), fresh=True, action=config.action
        )
    except (EnvironmentFailure, OSError):
        return 'SOURCE_UNVERIFIED'
    return 'READY'


def release_choices(connection, catalog, principal, identifier, runtime_sha, *, action=RELEASE):
    require(principal.role == 'MANAGER', DENIED)
    require(uuid_value(identifier), INVALID)
    row = environment_row(connection, identifier)
    require(row is not None, MISSING)
    version = row['record_version']
    assignment = row['assignment_generation']
    options = []
    if (
        row['purpose'] in ('DEVELOPMENT', 'INTEGRATION')
        and row['registration_state'] == 'ACTIVE'
        and row['preparation_state'] == 'PREPARED'
        and row['assignment_control_state'] == 'OPEN'
        and row['configuration_ref'] is not None
    ):
        measured = {}
        source = decoded(row['configuration_ref'])
        for config in installed_choices(catalog, identifier, source, action):
            key = (config.release_ref, config.candidate_sha256)
            if key not in measured:
                measured[key] = checked_candidate(connection, catalog, config, runtime_sha)
            candidate = measured[key]
            options.append(
                {
                    **config.public_references(),
                    'state': option_state(connection, catalog, row, config, candidate),
                    'manifest_sha256': config.manifest_reference['sha256'],
                    'commit': candidate['source_commit'] if candidate is not None else None,
                    'target_os': candidate['target_os'] if candidate is not None else None,
                    'target_arch': candidate['target_arch'] if candidate is not None else None,
                }
            )
    return {
        'environment_id': identifier,
        'record_version': version,
        'assignment_generation': assignment,
        'release_options': options,
    }
