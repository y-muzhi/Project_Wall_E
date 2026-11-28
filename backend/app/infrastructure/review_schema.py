"""Derive the opt-in document-review layout from the verified Schema210 release."""

from dataclasses import asdict, replace
from functools import lru_cache
import os
import sqlite3

from .database import SchemaMismatch, _statements
from .formation_schema_release import FormationRelease, load_release
from .schema_inspection import inspect_schema, verify_integrity
from .schema_v20_release import canonical_bytes, digest

LAYOUT_NAME = 'db21-document-review-r1'
REQUIREMENT_INDEX = 'manual_draft_requirement'
SCHEMA_SHA256 = 'd20230c0121b933c7f9700f64ace233c7198e7e41fb16248743b433a0180c9c3'
MANIFEST_SHA256 = '3454d765dca7c83fb7fc991ecc072e538a41b65940dad5690a5e096b9ccc6fd1'
LEGACY_DRAFT_LIMIT = (
    'CREATE UNIQUE INDEX manual_draft_requirement ON requirement_documents(requirement_id) '
    "WHERE document_type='MANUAL_DRAFT';"
)
LEGACY_BUDGET_CHECK = "  CHECK((budget_limit_cny<>'0.000000') IS TRUE),\n"


def _layout_sql(base: FormationRelease) -> str:
    if base.fresh.count(LEGACY_DRAFT_LIMIT) != 1 or base.fresh.count(LEGACY_BUDGET_CHECK) != 1:
        raise SchemaMismatch('Document review requires the reviewed Schema210 layout')
    return base.fresh.replace(LEGACY_DRAFT_LIMIT, '').replace(LEGACY_BUDGET_CHECK, '')


@lru_cache(maxsize=1)
def load_review_release() -> FormationRelease:
    base = load_release()
    fresh = _layout_sql(base)
    connection = sqlite3.connect(':memory:', isolation_level=None)
    try:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('BEGIN IMMEDIATE')
        for statement in _statements(fresh):
            connection.execute(statement)
        verify_integrity(connection)
        layout = inspect_schema(connection)
    finally:
        connection.close()
    original = {(item.kind, item.name): item for item in base.expected_schema.objects}
    actual = {(item.kind, item.name): item for item in layout.objects}
    if (
        original.keys() - actual.keys() != {('index', REQUIREMENT_INDEX)}
        or actual.keys() - original.keys()
        or {key for key, item in actual.items() if original[key] != item}
        != {('table', 'code_tasks')}
    ):
        raise SchemaMismatch('Document review layout changed unrelated database objects')
    contract = digest(canonical_bytes(asdict(layout)))
    manifest = digest(
        canonical_bytes(
            {
                'release_id': LAYOUT_NAME,
                'base_manifest_sha256': base.manifest_sha256,
                'schema_contract_sha256': contract,
                'fresh_checksum': digest(fresh.encode('utf-8')),
            }
        )
    )
    if contract != SCHEMA_SHA256 or manifest != MANIFEST_SHA256:
        raise SchemaMismatch('Document review layout differs from its reviewed manifest')
    return replace(
        base,
        release_id=LAYOUT_NAME,
        schema_contract_sha256=contract,
        manifest_sha256=manifest,
        expected_schema=layout,
        fresh=fresh,
    )


def load_configured_release() -> FormationRelease:
    layout = os.environ.get('WALLE_FORMATION_SCHEMA_LAYOUT')
    if layout is None:
        return load_release()
    if layout != LAYOUT_NAME:
        raise SchemaMismatch('Unknown Schema210 layout')
    return load_review_release()


def supports_review_layout(connection: sqlite3.Connection) -> bool:
    has_marker = connection.execute(
        "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='formation_schema_state'"
    ).fetchone()
    if has_marker is None:
        return False
    row = connection.execute(
        'SELECT schema_contract_sha256 FROM formation_schema_state WHERE singleton_id=1'
    ).fetchone()
    return row is not None and row[0] == SCHEMA_SHA256
