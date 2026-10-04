"""Reproduce a pending identity design gap in an isolated real v3 database.

Uses the implemented draft start and actual source verifier. The candidate save
steps below exercise pure identity algorithms, not an unimplemented save API.
Proposed tables are compiled and rolled back; this does not adopt a migration.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.documents.commands import start_manual_draft
from backend.app.documents.markdown import DocumentInvalid
from backend.app.documents.snapshot import Provenance, assign_identities, create_snapshot, validate_creation_inheritance, validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.database import Database, _statements
from backend.app.infrastructure.idempotency import Idempotency
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ResourceCatalog
from backend.tests.infrastructure.test_database import insert_requirement

T0, T1, T2, T3 = [f'2026-10-04T00:00:0{second}.000Z' for second in range(4)]


class RollbackProposal(Exception):
    pass


def rejected(operation):
    try:
        operation()
    except DocumentInvalid:
        return 'DOCUMENT_INVALID'
    return 'ACCEPTED'


def audit():
    proposal = ROOT / 'docs/proposals/manual-identity-receipts-v1.sql'
    catalog = ResourceCatalog()
    probes = {}
    with tempfile.TemporaryDirectory(prefix='walle-identity-design-audit-') as directory:
        database = Database(Path(directory) / 'isolated-v3.sqlite')
        database.initialize()
        with database.transaction(write=True) as connection:
            insert_requirement(connection)
            template = catalog.template('NEW', 'new-requirement', 'v1')
            initial = create_snapshot(template.markdown, Provenance('SYSTEM', 'TEMPLATE', None), T0, DocumentSources(connection, 101, catalog))
            connection.execute("INSERT INTO requirement_documents VALUES (201,101,'CURRENT',?,?,7,?,?)", (initial.parsed.markdown, initial.state_json, T0, T0))
            connection.execute("INSERT INTO sequences VALUES ('RequirementDocument',201)")
        with ProcessLock.for_database(database.path) as process_lock:
            executor = Idempotency(database, process_lock, clock=lambda: datetime.fromisoformat(T1[:-1] + '+00:00'))
            accepted = start_manual_draft(executor, {'requirement_id': 101, 'expected_content_version': 7, 'idempotency_key': '00000000-0000-4000-8000-000000000001'}, catalog=catalog, clock=lambda: datetime.fromisoformat(T1[:-1] + '+00:00'))
            if accepted['code'] != 'DRAFT_STARTED':
                raise RuntimeError('Implemented real draft start failed')
            draft_id = accepted['data']['manual_draft']['id']
            with database.transaction() as connection:
                sources = DocumentSources(connection, 101, catalog)
                model = accepted['data']['manual_draft']
                baseline = validate_snapshot(model['markdown_content'], model['block_state_json'], sources)
                ids = [item['block_id'] for item in baseline.state['blocks']]
                born_id = baseline.next_block_id
                new_markdown = baseline.parsed.markdown + '\n\n新增区块\n'
                origin = Provenance('USER', 'MANUAL_EDIT', draft_id)
                provisional = assign_identities(new_markdown, [*ids, born_id], born_id + 1, baseline, origin, T1, sources)
                assigned = assign_identities(new_markdown, [*ids, born_id], born_id + 1, baseline, origin, T2, sources)
                removed = assign_identities(baseline.parsed.markdown, ids, born_id + 1, assigned, origin, T3, sources)
                probes['saved_new_then_deleted_restore_with_initial_baseline'] = rejected(lambda: assign_identities(new_markdown, [*ids, born_id], born_id + 1, removed, origin, T3, sources, restoration_baseline=baseline))
                skipped = assign_identities(baseline.parsed.markdown, ids, born_id + 1, baseline, origin, T2, sources)
                probes['never_visible_allocation_then_restore_with_initial_baseline'] = rejected(lambda: assign_identities(new_markdown, [*ids, born_id], born_id + 1, skipped, origin, T3, sources, restoration_baseline=baseline))
                probes['provisional_birth_against_server_assigned_birth_without_receipt_rebind'] = rejected(lambda: validate_creation_inheritance(provisional, assigned))
                probes['identity'] = {'draft_id': draft_id, 'new_block_id': born_id, 'high_water_after_delete': removed.next_block_id}
            try:
                with database.transaction(write=True) as connection:
                    for statement in _statements(proposal.read_text(encoding='utf-8')):
                        connection.execute(statement)
                    connection.execute('INSERT INTO manual_block_allocation_ranges VALUES (?,?,?,?)', (draft_id, born_id, born_id + 1, T2))
                    connection.execute("INSERT INTO manual_block_origins VALUES (?,?,'USER','MANUAL_EDIT',?,?)", (draft_id, born_id, draft_id, T2))
                    try:
                        connection.execute('INSERT INTO manual_block_allocation_ranges VALUES (?,?,?,?)', (draft_id, born_id, born_id + 2, T3))
                    except sqlite3.IntegrityError:
                        probes['proposal_sql_overlap'] = 'REJECTED'
                    else:
                        raise RuntimeError('Proposed overlap guard failed')
                    probes['proposal_sql_compiled'] = True
                    raise RollbackProposal()
            except RollbackProposal:
                pass
            with database.transaction() as connection:
                probes['proposal_tables_rolled_back'] = connection.execute("SELECT count(*) FROM sqlite_master WHERE name IN ('manual_block_allocation_ranges','manual_block_origins')").fetchone()[0] == 0
    record = {'scope': 'Observed current algorithm gaps and isolated proposed SQL syntax/guards only; no save API, migration adoption or product acceptance',
              'recorded_at': datetime.now(timezone.utc).isoformat(), 'sqlite': sqlite3.sqlite_version,
              'proposal_sha256': hashlib.sha256(proposal.read_bytes()).hexdigest(), 'probes': probes,
              'gap_observed': all(probes[name] == 'DOCUMENT_INVALID' for name in (
                  'saved_new_then_deleted_restore_with_initial_baseline', 'never_visible_allocation_then_restore_with_initial_baseline',
                  'provisional_birth_against_server_assigned_birth_without_receipt_rebind'))}
    path = ROOT / 'docs/verification' / ('manual-identity-gap-' + record['recorded_at'].replace(':', '-').replace('.', '-') + '.json')
    path.write_bytes((json.dumps(record, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    print(json.dumps({'gap_observed': record['gap_observed'], 'proposal_sql_compiled_and_rolled_back': probes['proposal_sql_compiled'] and probes['proposal_tables_rolled_back'], 'evidence': str(path)}))


if __name__ == '__main__':
    audit()
