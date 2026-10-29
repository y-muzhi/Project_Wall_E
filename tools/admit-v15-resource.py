"""Inspect or explicitly import existing V1.5 admission evidence; no network.

The original database and its normal LLMUse/count audit must be retained. This
tool cannot create real observation evidence, grant a call budget or clear an
actual suspended release by substituting a later successful call.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from backend.app.infrastructure.collaboration_admission import CollaborationAdmission
    from backend.app.infrastructure.database import Database
    from backend.app.infrastructure.model_profile import ModelProfile, DEFAULT_PROFILE, PROFILES
    from backend.app.infrastructure.process_lock import ProcessLock
    from backend.app.infrastructure.resources import ResourceCatalog
    from backend.app.shared.command_execution import operation_time
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--profile', choices=list(PROFILES), default=DEFAULT_PROFILE)
    parser.add_argument('--approve-saved-call', action='store_true')
    parser.add_argument('--source-database', type=Path)
    parser.add_argument('--llm-use-id', type=int)
    args = parser.parse_args()
    if not args.database.is_absolute() or not args.database.is_file():
        parser.error('--database must name an existing absolute V1.5 database')
    if args.approve_saved_call != (args.source_database is not None and args.llm_use_id is not None):
        parser.error('Explicit approval requires both --source-database and --llm-use-id')
    if not args.approve_saved_call and (args.source_database is not None or args.llm_use_id is not None):
        parser.error('Evidence arguments require --approve-saved-call')
    database = Database(args.database);catalog = ResourceCatalog().for_collaboration_profile(args.profile)
    # A metadata-only dummy key; no environment credential read and no IO client.
    profile = ModelProfile('private-admission-metadata-validation', args.profile)
    lock = ProcessLock.for_database(database.path)
    store = CollaborationAdmission(database, lock, catalog)
    if args.approve_saved_call:
        with lock:
            store.approve_saved_call(args.source_database, args.llm_use_id, operation_time(None))
    value = store.current(profile.snapshot).value
    print('state='+value['state']+' release='+value['release_sha256']+' evidence='+(value['evidence_ref'] or 'none'))


if __name__ == '__main__':
    main()
