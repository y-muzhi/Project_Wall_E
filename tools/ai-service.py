"""V2.0/V2.1 offline readiness, or explicit credential import and server startup.

Never initializes a database, imports admission, calls a provider or selects a
legacy model. --start uses the existing ordinary single-process entry point.
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.infrastructure.sqlite_runtime import activate

activate()

from backend.app.infrastructure.database import SchemaMismatch, StorageUnavailable
from backend.app.infrastructure.local_credentials import read_local_credential
from backend.app.infrastructure.model_profile import DEFAULT_PROFILE, ModelProfile
from backend.app.infrastructure.resources import ConfigInvalid, ResourceCatalog
from backend.app.infrastructure.schema_v20_release import load_release


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', action='store_true')
    parser.add_argument('--schema-version', type=int, choices=(200, 210), default=200)
    parser.add_argument('--credential-file', type=Path)
    args = parser.parse_args(argv)
    if args.credential_file and not args.start:
        parser.error('credential import requires explicit startup')
    schema_release = load_release()
    catalog = ResourceCatalog()
    if args.schema_version == 210:
        from backend.app.infrastructure.formation_schema_release import (
            load_release as load_formation_release,
        )

        schema_release = load_formation_release()
        catalog = catalog.for_formation_profile(DEFAULT_PROFILE)
    resources = catalog.collaboration
    profile = ModelProfile('offline-readiness-no-credential', DEFAULT_PROFILE)
    budget = resources.counting
    print(
        'WALL-E '
        + ('V2.1' if args.schema_version == 210 else 'V2.0')
        + '; model='
        + profile.model_name
        + '; release='
        + resources.release_sha256
    )
    print(
        'context='
        + resources.layout
        + '; input='
        + str(budget['input_limit'])
        + '; output='
        + str(budget['output_limit'])
        + '; total='
        + str(budget['total_limit'])
    )
    print('schema=' + str(args.schema_version) + '; schema_release=' + schema_release.release_id)
    if not args.start:
        print(
            'mode=OFFLINE_READINESS; frozen_state='
            + resources.release['admission']['state']
            + '; credentials_read=0; database_opened=0; provider_calls=0; service_started=0'
        )
        return 0
    selected = os.environ.get('WALLE_DATABASE_PATH')
    if not selected or not Path(selected).is_absolute() or not Path(selected).is_file():
        raise ConfigInvalid('Explicit existing absolute selected-schema database required')
    from backend.app.infrastructure.collaboration_admission import CollaborationAdmission
    from backend.app.infrastructure.database import Database
    from backend.app.infrastructure.process_lock import ProcessLock

    if args.schema_version == 210:
        from backend.app.infrastructure.formation_database import FormationDatabase

        database = FormationDatabase(Path(selected), formation_release=schema_release)
    else:
        database = Database(Path(selected), schema_release=schema_release)
    # Schema200 is independently required even when no admission file exists.
    with database.transaction():
        pass
    lock = ProcessLock.for_database(database.path)
    proof = CollaborationAdmission(database, lock, catalog).current(profile.snapshot)
    resources.require_live(profile.snapshot, admission=proof)
    # Only explicit startup reads a key, after schema/admission checks. Never
    # export it to a parent shell, persist it, print it or evaluate local text.
    if args.credential_file is not None:
        if not args.credential_file.is_absolute():
            raise ValueError('Absolute credential file required')
        key = read_local_credential(args.credential_file)
    else:
        key = os.environ.get('WALLE_MODEL_API_KEY') or read_local_credential(ROOT / '.env.local')
    ModelProfile(key, DEFAULT_PROFILE)
    os.environ['WALLE_MODEL_API_KEY'] = key
    os.environ['WALLE_MODEL_ID'] = profile.model_name
    os.environ['WALLE_MODEL_VERSION'] = profile.model_version
    from backend.app.__main__ import main as serve

    serve(schema_version=args.schema_version)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, ConfigInvalid, SchemaMismatch, StorageUnavailable):
        print(
            'AI service not started: check the selected-schema database, admission and local credentials.',
            file=sys.stderr,
        )
        raise SystemExit(1)
