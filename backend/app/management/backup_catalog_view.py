"""Display installed backup strategies within one authorized environment."""

from backend.app.infrastructure.environment_files import EnvironmentFailure, require
from backend.app.infrastructure.environment_installation import uuid_value

from .backup_operations import LIMITS, backup_policy, stopped_source
from .operation_contract import DENIED, INVALID, MISSING, installed_record
from .operation_store import conflicting_action, environment_row


def backup_choices(connection, catalog, principal, identifier):
    require(principal.role == 'MANAGER', DENIED)
    require(uuid_value(identifier), INVALID)
    row = environment_row(connection, identifier)
    require(row is not None, MISSING)
    versions = {
        'expected_record_version': row['record_version'],
        'expected_assignment_generation': row['assignment_generation'],
    }
    choices = []
    busy = conflicting_action(connection, identifier)
    for reference, pin in sorted(catalog.backup_policies.items()):
        raw = installed_record(catalog.directory / 'backup-policies' / (reference + '.json'), pin)
        if raw.get('environment_id') != identifier:
            continue
        policy, _ = backup_policy(catalog, reference, identifier, supported=False)
        state = 'READY'
        if policy['minimum_verification'] == 'OFFHOST_VERIFIED':
            state = 'OFFHOST_REQUIRED'
        elif busy:
            state = 'ENVIRONMENT_BUSY'
        else:
            try:
                stopped_source(
                    connection,
                    catalog,
                    principal,
                    {
                        'environment_id': identifier,
                        'backup_policy_ref': reference,
                        **versions,
                    },
                )
            except (EnvironmentFailure, OSError):
                state = 'SOURCE_UNVERIFIED'
        choices.append(
            {
                'backup_policy_ref': reference,
                'state': state,
                **{key: policy[key] for key in ('minimum_verification', 'assets', *LIMITS)},
            }
        )
    return {
        'environment_id': identifier,
        'record_version': row['record_version'],
        'assignment_generation': row['assignment_generation'],
        'backup_options': choices,
    }
