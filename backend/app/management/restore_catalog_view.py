"""Project only registered, scoped restore choices to the management page."""

from backend.app.infrastructure.environment_control import normal_stop
from backend.app.infrastructure.environment_files import EnvironmentFailure, require
from backend.app.infrastructure.environment_installation import uuid_value
from backend.app.infrastructure.environment_restore_preflight import restore_plan

from .attachment_observation import now
from .backup_reconciliation import managed_backup_history
from .lifecycle_operations import authorized
from .operation_contract import DENIED, INVALID, path_reference
from .operation_store import conflicting_action, decoded
from .release_maintenance_view import confirmed_current_control
from .release_operations import no_live_reservation
from .restore_operations import (
    checked_restore_point,
    operation_exists,
    registered_restore,
    restore_recovery_policy,
)


def eligible_options(connection, catalog, row, current):
    attachment = decoded(row['configuration_ref'])
    ceiling = now()
    _, points = managed_backup_history(connection, catalog, row['environment_id'], ceiling)
    backups = {item['backup_id']: item for item in points}
    options = []
    for reference in catalog.restore_configurations:
        try:
            record, _ = registered_restore(catalog, reference)
            if (
                record['environment_id'] != row['environment_id']
                or record['source_attachment'] != attachment
                or record['target_attachment_ref'] in catalog.candidates
            ):
                continue
            template_path, pin = path_reference(record['preflight_template'])
            template = restore_plan(template_path, pin)
            restore_recovery_policy(catalog, record['recovery_policy'], template)
            point = backups.get(template['selected']['backup_id'])
            checked_restore_point(point, row['environment_id'], template, ceiling)
            if (
                template['source_data_generation'] != current['data_generation']
                or template['source_deployment_id'] != current['deployment_id']
                or template['source_configuration_sha256'] != current['configuration_sha256']
                or template['source_control_revision'] != current['control_revision'] + 1
                or operation_exists(connection, template['operation_id'])
            ):
                continue
            options.append(
                {
                    'backup_id': point['backup_id'],
                    'cutoff_at': point['cutoff_at'],
                    'backup_source_data_generation': point['source_data_generation'],
                    'backup_manifest_sha256': point['backup_manifest_sha256'],
                    'target_release_ref': record['release_ref'],
                    'target_configuration_ref': reference,
                    'recovery_policy_ref': record['recovery_policy']['ref'],
                    'source_data_generation': current['data_generation'],
                }
            )
        except (OSError, EnvironmentFailure, KeyError, TypeError, ValueError):
            continue
    return sorted(
        options,
        key=lambda item: (item['cutoff_at'], item['target_configuration_ref']),
        reverse=True,
    )


def restore_choices(connection, catalog, principal, identifier):
    require(uuid_value(identifier), INVALID)
    require(principal.role == 'MANAGER', DENIED)
    row = authorized(connection, principal, identifier)
    status = 'SOURCE_NOT_STOPPED'
    options = []
    if conflicting_action(connection, identifier):
        status = 'OPERATION_ACTIVE'
    elif row['configuration_ref'] is not None:
        current = confirmed_current_control(catalog, row)
        if current is not None and normal_stop(current):
            try:
                no_live_reservation(connection, identifier)
            except EnvironmentFailure:
                status = 'CAPACITY_RESERVED'
            else:
                options = eligible_options(connection, catalog, row, current)
                status = 'READY' if options else 'NO_VERIFIED_CONFIGURATION'
    return {
        'environment_id': identifier,
        'record_version': row['record_version'],
        'assignment_generation': row['assignment_generation'],
        'state': status,
        'restore_options': options,
    }
