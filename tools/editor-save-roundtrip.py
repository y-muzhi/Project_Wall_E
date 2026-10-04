"""Isolated real-SQLite diagnostic bridge, not a product HTTP endpoint."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.documents.commands import start_manual_draft, save_manual_draft
from backend.app.documents.queries import get_manual_draft
from backend.app.documents.snapshot import Provenance, create_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.database import Database
from backend.app.infrastructure.idempotency import Idempotency
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.shared.time import utc_milliseconds
from backend.app.shared.validation import strict_json_object
from backend.tests.infrastructure.test_database import insert_requirement


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('init', 'save', 'read'))
    parser.add_argument('--database', required=True, type=Path)
    args = parser.parse_args()
    database = Database(args.database)
    catalog = ResourceCatalog()
    if args.operation == 'init':
        if database.path.exists():
            raise ValueError('Diagnostic fixture must use a new file')
        database.initialize()
        now = utc_milliseconds(datetime.now(timezone.utc))
        with database.transaction(write=True) as connection:
            insert_requirement(connection)
            # Explicit existing ACTIVE/history fixture; this diagnostic does not
            # claim to test requirement creation or initialization transitions.
            connection.execute("UPDATE requirements SET status='ACTIVE'")
            sources = DocumentSources(connection, 101, catalog)
            snapshot = create_snapshot('甲乙\n\n尾\n', Provenance('SYSTEM', 'TEMPLATE', None), now, sources)
            connection.execute("INSERT INTO requirement_documents VALUES (201,101,'CURRENT',?,?,7,?,?)", (snapshot.parsed.markdown, snapshot.state_json, now, now))
            connection.execute("INSERT INTO manual_edit_sessions VALUES (999,101,201,'COMPLETED',?,?)", (now, now))
            state = snapshot.state
            for block in state['blocks']:
                block.update(last_modified_by_type='USER', last_modified_source_type='MANUAL_EDIT', last_modified_source_id=999)
            connection.execute('UPDATE requirement_documents SET block_state_json=? WHERE id=201', (json.dumps(state),))
            template = catalog.template('NEW', 'new-requirement', 'v1')
            baseline = create_snapshot(template.markdown, Provenance('SYSTEM', 'TEMPLATE', None), now, sources)
            connection.execute("INSERT INTO revisions VALUES (301,101,1,'BASELINE',?,?,'初始化基线',1,?)", (baseline.parsed.markdown, baseline.state_json, now))
            connection.execute("INSERT INTO sequences VALUES ('RequirementDocument',999)")
        with ProcessLock.for_database(database.path) as lock:
            result = start_manual_draft(Idempotency(database, lock), {'requirement_id': 101, 'expected_content_version': 7, 'idempotency_key': '00000000-0000-4000-8000-000000000001'}, catalog=catalog)
    elif args.operation == 'save':
        with ProcessLock.for_database(database.path):
            result = save_manual_draft(database, strict_json_object(sys.stdin.buffer.read()), catalog=catalog)
    else:
        result = get_manual_draft(database, 101, catalog=catalog)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
