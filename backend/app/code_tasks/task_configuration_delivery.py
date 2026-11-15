"""Compile explicitly approved local delivery permission for the fixed launch profile."""

import hashlib

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.shared.validation import strict_json_object

from .task_start_authorization import original_start_authorization


class DeliveryAuthorizationError(ValueError):
    pass


def compile_delivery_authorization(connection, task_id, delivery, scope):
    origin = original_start_authorization(connection, task_id)
    row = connection.execute(
        'SELECT delivery FROM code_execution_profile_versions WHERE id=?',
        (origin['profile_version_id'],),
    ).fetchone()
    if row is None:
        raise StorageUnavailable('Original delivery authorization profile is missing')
    original = None if row['delivery'] is None else strict_json_object(row['delivery'])
    if (
        original is None
        or type(delivery) is not dict
        or canonical_input(original) != canonical_input(delivery)
    ):
        raise DeliveryAuthorizationError('Delivery authorization exceeds original launch bindings')
    return {
        'launch_authorization_id': origin['id'],
        'delivery_sha256': hashlib.sha256(canonical_input(delivery).encode()).hexdigest(),
        'allow_local_delivery': scope['allow_local_delivery'],
    }
