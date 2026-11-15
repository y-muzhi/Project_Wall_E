"""Persist Testing asset loss for the exact fixed descendants in the revoke transaction."""

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.identifiers import increment


def invalidate_bound_tasks(connection, *, plan_version=None, pack_version=None):
    if (plan_version is None) == (pack_version is None):
        raise ValueError('An original Testing asset is required')
    field, identity = (
        ('plan_version_id', plan_version)
        if pack_version is None
        else ('test_pack_version_id', pack_version)
    )
    rows = connection.execute(
        f"""SELECT id,status,phase,state_version,control_generation,active_operation_id FROM testing_tasks
           WHERE {field}=? AND status NOT IN ('STOPPING','COMPLETED','TERMINATED') ORDER BY id""",
        (identity,),
    ).fetchall()
    for row in rows:
        active = row['active_operation_id'] is not None
        status = 'WAITING' if active else 'DRAFT' if row['status'] == 'READY' else row['status']
        phase = 'PLAN' if status == 'DRAFT' else row['phase']
        generation = increment(row['control_generation']) if active else row['control_generation']
        updated = connection.execute(
            """UPDATE testing_tasks SET status=?,phase=?,state_version=?,control_generation=?
               WHERE id=? AND state_version=? AND control_generation=? AND status=?""",
            (
                status,
                phase,
                increment(row['state_version']),
                generation,
                row['id'],
                row['state_version'],
                row['control_generation'],
                row['status'],
            ),
        )
        if updated.rowcount != 1:
            raise StorageUnavailable('Original Testing asset loss could not be recorded')
