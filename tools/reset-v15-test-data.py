"""Explicitly discard the configured V1.5 test DB after the service is stopped.

No provider calls, credential reads, legacy migration or service termination.
The process lock is mandatory; frozen admission sources/configuration survive.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.infrastructure.database import Database
from backend.app.infrastructure.process_lock import ProcessLock


def reset_test_data(path):
    target = Path(path).resolve(strict=True)
    allowed = (ROOT / 'data' / 'wall-e-v1.5.sqlite').resolve()
    if target != allowed or target.is_symlink():
        raise ValueError('Only the explicitly named V1.5 test database may be reset')
    audit_root = target.with_name(target.name + '.count-audit')
    pending = []
    if audit_root.exists():
        if audit_root.is_symlink() or audit_root.resolve().parent != target.parent:
            raise ValueError('Counting audit directory cannot be redirected')
        for item in audit_root.iterdir():
            if item.is_symlink() or not item.is_file() or item.resolve().parent != audit_root:
                raise ValueError('Unexpected counting audit entry; preserve for review')
            if item.name.endswith('.admission.json'):
                source = Path(json.loads(item.read_text(encoding='utf-8'))['source_database']).resolve()
                if source == target or not source.is_file():
                    raise ValueError('Preserve a separate frozen admission source before resetting')
                continue
            if re.fullmatch(r'[0-9a-f]{32}\.(prepared|finished)\.json', item.name) is None:
                raise ValueError('Unrecognized audit file; preserve for review')
            pending.append(item)
    with ProcessLock.for_database(target):
        connection = sqlite3.connect(target.as_uri() + '?mode=ro', uri=True)
        try:
            before = {name: connection.execute('SELECT count(*) FROM ' + name).fetchone()[0]
                      for name in ('requirements','requirement_documents','conversation_messages','guide_runs','llm_uses')}
        finally:
            connection.close()
        sidecars = [target.with_name(target.name + suffix) for suffix in ('-wal','-shm')]
        for item in sidecars:
            if item.is_symlink() or item.parent != target.parent:
                raise ValueError('Unexpected SQLite sidecar target')
        with TemporaryDirectory(dir=target.parent, prefix='.doc-ai-reset-') as directory:
            replacement = Path(directory) / target.name
            fresh = Database(replacement)
            fresh.initialize()
            with fresh.transaction() as connection:
                assert connection.execute('SELECT count(*) FROM requirements').fetchone()[0] == 0
            os.replace(replacement, target)
            for item in sidecars:
                item.unlink(missing_ok=True)
            for item in pending:
                item.unlink()
        with Database(target).transaction() as connection:
            version = connection.execute('SELECT version FROM schema_migrations').fetchone()[0]
        return {'schema_version': version, 'deleted_test_records': before,
                'deleted_count_audits': len(pending), 'admission_configuration_preserved': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--delete-test-data', action='store_true', required=True)
    args = parser.parse_args()
    if not args.database.is_absolute():
        parser.error('--database must be absolute')
    print(json.dumps(reset_test_data(args.database), ensure_ascii=False))


if __name__ == '__main__':
    main()
