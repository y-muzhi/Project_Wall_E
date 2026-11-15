"""APP-CODE-SETUP configuration identities; no versions or runtime preparation."""

from dataclasses import dataclass

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success
from backend.app.infrastructure.identifiers import EntityKind, entity_id, require_write_transaction
from backend.app.shared.command_execution import execute_idempotent, operation_time


@dataclass(frozen=True)
class IdentityCollection:
    path: str
    resource_kind: str
    entity_kind: EntityKind
    table: str
    version_table: str
    parent_column: str


EXECUTION_PROFILES = IdentityCollection(
    '/api/v1/code-execution-profiles',
    'EXECUTION_PROFILE',
    EntityKind.EXECUTION_PROFILE,
    'code_execution_profiles',
    'code_execution_profile_versions',
    'profile_id',
)
CHECK_SETS = IdentityCollection(
    '/api/v1/code-check-sets',
    'CHECK_SET',
    EntityKind.CHECK_SET,
    'code_check_sets',
    'code_check_set_versions',
    'check_set_id',
)
COLLECTIONS = (EXECUTION_PROFILES, CHECK_SETS)


def require_collection(value):
    if not any(value is collection for collection in COLLECTIONS):
        raise ValueError('A program-registered configuration identity collection is required')
    return value


def require_schema(runtime):
    if runtime.database.schema_release is None:
        raise StorageUnavailable('Explicit Schema200 initialization or maintenance is required')


def create_identity(runtime, request):
    require_schema(runtime)
    collection = require_collection(request.collection)

    def save(connection):
        require_write_transaction(connection)
        identity = entity_id(connection, collection.entity_kind)
        at = operation_time(None)
        connection.execute(
            f'INSERT INTO {collection.table}(id,name,created_at) VALUES(?,?,?)',
            (identity, request.name, at),
        )
        return Success(
            {
                'code': 'CREATED',
                'data': {'resource_kind': collection.resource_kind, 'resource_id': identity},
                'details': None,
            },
            201,
        )

    return execute_idempotent(
        runtime.commands(),
        request.command.route.capability_id,
        request,
        save,
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset(),
    )


def list_identities(runtime, request):
    require_schema(runtime)
    collection = require_collection(request.collection)
    # Both identifiers below are program constants, never SQL from a request.
    coding = " AND v.owner_module='CODING'" if collection is CHECK_SETS else ''
    with runtime.database.transaction() as connection:
        total = connection.execute(f'SELECT COUNT(*) FROM {collection.table}').fetchone()[0]
        rows = connection.execute(
            f'SELECT p.id,p.name,'
            f'(SELECT v.id FROM {collection.version_table} AS v '
            f'WHERE v.{collection.parent_column}=p.id{coding} '
            f'ORDER BY v.version DESC,v.id DESC LIMIT 1) AS latest_version_id '
            f'FROM {collection.table} AS p ORDER BY p.created_at DESC,p.id DESC LIMIT 20 OFFSET ?',
            ((request.page - 1) * 20,),
        ).fetchall()
        items = [dict(row) for row in rows]
    return {
        'code': 'READ_OK',
        'data': {
            'items': items,
            'page': request.page,
            'page_size': 20,
            'total': total,
            'total_pages': (total + 19) // 20,
        },
        'details': None,
    }
