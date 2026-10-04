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
            snapshot = create_snapshot('甲乙\n\n尾\n', Provenance('SYSTEM', 'TEMPLATE', None), now, DocumentSources(connection, 101, catalog))
            connection.execute("INSERT INTO requirement_documents VALUES (201,101,'CURRENT',?,?,7,?,?)", (snapshot.parsed.markdown, snapshot.state_json, now, now))
            connection.execute("INSERT INTO sequences VALUES ('RequirementDocument',201)")
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
