"""Compile only gateway permissions inside the original unchanged model bindings."""

import hashlib

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.shared.validation import strict_json_object

from .task_start_authorization import original_start_authorization


class ModelAuthorizationError(ValueError):
    pass


def compile_model_authorization(connection, task_id, models, scope):
    origin = original_start_authorization(connection, task_id)
    profile = connection.execute(
        'SELECT models FROM code_execution_profile_versions WHERE id=?',
        (origin['profile_version_id'],),
    ).fetchone()
    references = scope['model_profile_refs']
    if profile is None:
        raise StorageUnavailable('Original model authorization profile is missing')
    if canonical_input(strict_json_object(profile['models'])) != canonical_input(models) or not set(
        references
    ).issubset(origin['scope']['model_profile_refs']):
        raise ModelAuthorizationError('Model authorization exceeds original launch bindings')
    return {
        'launch_authorization_id': origin['id'],
        'models_sha256': hashlib.sha256(canonical_input(models).encode()).hexdigest(),
        'model_profile_refs': sorted(references),
        'aliases': [
            {
                'native_model_id': binding['native_model_id'],
                'model_profile_ref': binding['model_profile_ref'],
                'allowed': binding['model_profile_ref'] in references,
            }
            for binding in sorted(models['bindings'], key=lambda row: row['native_model_id'])
        ],
    }
