"""Read the immutable grant pinned by the original successful START session step."""

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.shared.validation import strict_integer, strict_json_object

from .authorizations import project_grant


def original_start_authorization(connection, task_id):
    from .task_start import original_start_steps

    strict_integer(task_id, 'task_id')
    starts = connection.execute(
        """SELECT * FROM code_operations WHERE task_id=? AND operation_type='START'
           AND status='SUCCEEDED' ORDER BY id LIMIT 2""",
        (task_id,),
    ).fetchall()
    if len(starts) != 1:
        raise StorageUnavailable('Original authorization launch is missing')
    start = starts[0]
    _, steps = original_start_steps(connection, start)
    native = steps[4]
    if native['status'] != 'SUCCEEDED' or native['external_identity'] is None:
        raise StorageUnavailable('Original authorization session scope is missing')
    source = strict_json_object(native['external_identity'])
    row = connection.execute(
        'SELECT * FROM code_authorizations WHERE id=? AND task_id=?',
        (strict_integer(source['authorization_id'], 'authorization_id'), task_id),
    ).fetchone()
    if row is None:
        raise StorageUnavailable('Original launch authorization is missing')
    grant = project_grant(row)
    observed_owner = {key: source[key] for key in ('task_id', 'operation_id', 'profile_id')}
    original_owner = {
        'task_id': task_id,
        'operation_id': start['id'],
        'profile_id': grant['profile_version_id'],
    }
    if canonical_input(observed_owner) != canonical_input(original_owner) or grant[
        'status'
    ] not in ('EFFECTIVE', 'RETIRED'):
        raise StorageUnavailable('Original launch authorization owner differs')
    return grant
