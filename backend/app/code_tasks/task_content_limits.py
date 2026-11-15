"""Content capacity remains bounded by the task's original approved launch scope."""

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.shared.validation import strict_integer, strict_json_object

from .task_configuration_effective import FIXED_CONTENT_LIMITS, fixed_content_changed
from .task_start_authorization import original_start_authorization


def authorized_content_settings(connection, profile_id, task_id):
    strict_integer(task_id, 'task_id')
    profile = connection.execute(
        'SELECT capture_rules,limits FROM code_execution_profile_versions WHERE id=?',
        (profile_id,),
    ).fetchone()
    if profile is None:
        raise StorageUnavailable('Original content profile is missing')
    grant = original_start_authorization(connection, task_id)
    original = connection.execute(
        'SELECT capture_rules,limits FROM code_execution_profile_versions WHERE id=?',
        (grant['profile_version_id'],),
    ).fetchone()
    if original is None:
        raise StorageUnavailable('Original content profile is missing')

    def policy(row):
        return {
            'capture_rules': strict_json_object(row['capture_rules']),
            'limits': strict_json_object(row['limits']),
        }

    selected = policy(profile)
    if fixed_content_changed(policy(original), selected):
        raise StorageUnavailable('Original fixed content capacity changed')
    settings = selected['limits']
    authorized = grant['scope']['limits']
    return {
        key: min(
            strict_integer(settings[key], key),
            strict_integer(authorized[key], key),
        )
        for key in FIXED_CONTENT_LIMITS
    }
