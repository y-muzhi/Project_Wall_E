"""Prepare the pinned document-review layout without switching the application service."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.infrastructure.sqlite_runtime import activate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--layout', action='store_true', help='Inspect the pinned local layout')
    action.add_argument('--initialize', type=Path, metavar='TARGET')
    action.add_argument('--copy', nargs=2, type=Path, metavar=('SOURCE', 'TARGET'))
    parser.add_argument('--offline-confirmed', action='store_true')
    args = parser.parse_args()
    if args.copy is not None and not args.offline_confirmed:
        parser.error('--copy requires an owned offline database and --offline-confirmed')
    activate()

    from backend.app.infrastructure.formation_database import FormationDatabase
    from backend.app.infrastructure.review_schema import load_review_release
    from backend.app.infrastructure.review_schema_copy import copy_review_database

    release = load_review_release()
    if args.initialize is not None:
        database = FormationDatabase(args.initialize.resolve(), formation_release=release)
        facts = database.initialize()
        print('initialized=' + str(facts['initialized']).lower())
    if args.copy is not None:
        print('retained_rows_sha256=' + copy_review_database(*args.copy))
    print(release.release_id, release.schema_contract_sha256, release.manifest_sha256)


if __name__ == '__main__':
    main()
