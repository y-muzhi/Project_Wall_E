"""Reviewed Schema200 sources and read-only prerequisites for a new Schema210 copy."""

import json
from dataclasses import dataclass, replace

from .data_retention import RetentionManifest, capture_retained_data, original_projections
from .database import SchemaMismatch
from .formation_schema_release import RUNTIME_FACT
from .resources import ResourceCatalog
from .schema_inspection import quote_identifier, verify_integrity
from .schema_v20_release import RELEASE_PARENT, RESOURCE_NAMES, _read, canonical_bytes, digest
from .schema_v20_state import check_v20

# Historical code is evidence, never imported or executed. These immutable packages
# have identical complete DDL/resources, checked again against the current target core.
SOURCE_MANIFESTS = {
    'bf188e05df22f548ebb2e6dfab10132ba198ecea7240d4a312d14ca1579e5a39': 'db20-r48',
    '3d48be65e3ad6e549c3b73b831456459537adb1e03c765ef6f28ad9ce6eeedc7': 'db20-r54',
}


def reviewed_source(manifest_sha256, target_release):
    name = SOURCE_MANIFESTS.get(manifest_sha256)
    if name is None:
        raise SchemaMismatch('Unreviewed Schema200 source manifest')
    directory = RELEASE_PARENT / name
    raw = _read(directory / 'manifest.json')
    if digest(raw) != manifest_sha256:
        raise SchemaMismatch('Historical source manifest bytes differ')
    manifest = json.loads(raw)
    core = target_release.core
    expected = {
        'objects.v1.json': canonical_bytes(json.loads(_read(directory / 'objects.v1.json'))),
        'fresh.v1.sql': core.fresh.encode('utf-8'),
        'upgrade-151.v1.sql': core.upgrade.encode('utf-8'),
    }
    if (
        manifest['sqlite_runtime'] != RUNTIME_FACT
        or manifest['release_id'] != name
        or manifest['schema_version'] != 200
        or manifest['schema_contract_sha256'] != core.schema_contract_sha256
        or set(manifest['resources']) != set(RESOURCE_NAMES)
    ):
        raise SchemaMismatch('Historical source and target core contracts differ')
    for filename in RESOURCE_NAMES:
        data = _read(directory / filename)
        if data != expected[filename] or manifest['resources'][filename] != {
            'bytes': len(data),
            'sha256': digest(data),
        }:
            raise SchemaMismatch('Historical source resources differ')
    if digest(expected['objects.v1.json']) != core.schema_contract_sha256:
        raise SchemaMismatch('Historical source object contract differs')
    return replace(core, release_id=name, manifest_sha256=manifest_sha256)


# Actual execution/unknown states only. Published resources and dormant drafts in
# unrelated code configuration remain retained data; they are not cancelled here.
BLOCKING_STATES = {
    'guide_runs': ('RUNNING',),
    'manual_edit_sessions': ('EDITING',),
    'suggestion_batches': ('PENDING',),
    'idempotency_records': ('PROCESSING',),
    'code_tasks': (
        'RUNNING',
        'WAITING',
        'VERIFYING',
        'AWAITING_TESTING',
        'AWAITING_ACCEPTANCE',
        'STOPPING',
    ),
    'testing_tasks': ('PLANNING', 'RUNNING', 'WAITING', 'STOPPING'),
    'code_operations': ('PENDING', 'RUNNING', 'UNKNOWN'),
    'code_operation_steps': ('RUNNING', 'UNKNOWN'),
    'code_commands': ('PENDING', 'RUNNING', 'UNKNOWN'),
    'code_instances': ('STARTING', 'READY', 'STOPPING', 'UNKNOWN'),
    'code_sessions': ('PREPARING', 'ACTIVE', 'QUIESCING', 'UNKNOWN'),
    'code_workspaces': ('PREPARING', 'UNKNOWN'),
    'code_repairs': ('PENDING', 'RUNNING', 'UNKNOWN'),
    'code_deliveries': ('PENDING', 'PREPARING', 'WRITING', 'UNKNOWN'),
    'code_verifications': ('PENDING', 'RUNNING', 'UNKNOWN'),
    'code_configuration_applications': ('PENDING', 'APPLYING', 'UNKNOWN'),
    'code_task_reservations': ('RESERVED', 'UNKNOWN', 'DISPUTED'),
    'code_questions': ('ANSWERING', 'UNKNOWN'),
    'code_permissions': ('ANSWERING', 'UNKNOWN'),
    'code_authorizations': ('APPLY_UNKNOWN',),
}
EXTRA_BLOCKS = (
    ('requirements', "document_work_state<>'IDLE'"),
    ('code_deliveries', "git_write_status IN ('PREPARED','MAY_HAVE_BEEN_SENT','UNKNOWN')"),
    (
        'code_verifications',
        "stop_status IN ('ACTIVE','UNKNOWN') OR cleanup_status IN ('CLEANING','UNKNOWN')",
    ),
    ('testing_tasks', 'active_operation_id IS NOT NULL'),
)


def require_quiescent(connection):
    for table, states in BLOCKING_STATES.items():
        placeholders = ','.join('?' for _ in states)
        if connection.execute(
            f'SELECT 1 FROM {quote_identifier(table)} WHERE status IN ({placeholders}) LIMIT 1',
            states,
        ).fetchone():
            raise SchemaMismatch('Source has active or unreconciled work: ' + table)
    for table, predicate in EXTRA_BLOCKS:
        if connection.execute(
            f'SELECT 1 FROM {quote_identifier(table)} WHERE {predicate} LIMIT 1'
        ).fetchone():
            raise SchemaMismatch('Source has active or unreconciled work: ' + table)


@dataclass(frozen=True)
class SourceFacts:
    retained: RetentionManifest
    history: tuple[tuple[int, str, str], ...]
    sha256: str


def source_facts(connection, release):
    check_v20(connection, release)
    verify_integrity(connection)
    require_quiescent(connection)
    projections = tuple(
        p for p in original_projections(connection) if p.table != 'schema_migrations'
    )
    retained = capture_retained_data(connection, projections)
    history = tuple(
        tuple(row)
        for row in connection.execute(
            'SELECT version,checksum,applied_at FROM schema_migrations ORDER BY version'
        )
    )
    sha256 = digest(canonical_bytes({'retained': retained.sha256, 'history': history}))
    return SourceFacts(retained, history, sha256)


def verify_source_resources(connection):
    catalog = ResourceCatalog()
    for row in connection.execute(
        'SELECT DISTINCT function_type,context_template_version,prompt_version,context_template_key,execution_basis_json FROM guide_runs'
    ):
        if row[0] == 'collaboration_v1':
            accepted = json.loads(row[4])
            resources = catalog.for_collaboration_release(
                accepted['resources']['release']
            ).collaboration
            expected_context = (
                'formation_context_v21_1'
                if resources.formation_driven
                else 'collaboration_context_v1'
            )
            expected_version = 'v21_1' if resources.formation_driven else 'v1'
            expected_prompt = (
                resources.release['prompt']['version'] if resources.formation_driven else 'v1'
            )
            if (
                row[3] != expected_context
                or row[1] != expected_version
                or row[2] != expected_prompt
            ):
                raise SchemaMismatch('Original collaboration run resource references differ')
            for reference in accepted['resources'].values():
                if type(reference) is dict and set(reference) >= {'key', 'version', 'digest'}:
                    resources.content(reference)
        else:
            catalog.restore(
                row[0], row[2], prompt_version=row[2], context_template=row[3] + '@' + row[1]
            )
    for row in connection.execute(
        'SELECT DISTINCT template_ref FROM requirement_documents WHERE template_ref IS NOT NULL'
    ):
        reference = json.loads(row[0])
        catalog.template('NEW', reference['key'], reference['version'])
