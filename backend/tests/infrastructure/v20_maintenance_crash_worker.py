"""Owned test helper: pause at a precise real original-database commit boundary."""

import argparse
from pathlib import Path
import sys

from backend.app.infrastructure import schema_v20_upgrade as engine
from backend.app.infrastructure.schema_v20_maintenance import apply_plan
from backend.app.infrastructure.schema_v20_release import _load_verified_release


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', required=True)
    parser.add_argument('--package', required=True)
    parser.add_argument('--upgrade-id', required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--release', required=True)
    parser.add_argument('--release-sha256', required=True)
    parser.add_argument('--phase', choices=('BEFORE_MARKER', 'AFTER_COMMIT'), required=True)
    args = parser.parse_args()
    release = _load_verified_release(Path(args.release), args.release_sha256)

    def wait_for_owned_termination():
        print('OWNED_MAINTENANCE_BOUNDARY_READY', flush=True)
        sys.stdin.read()
        raise RuntimeError('The crash fixture requires parent-owned process termination')

    if args.phase == 'BEFORE_MARKER':

        def before_marker(*_args):
            wait_for_owned_termination()

        engine._save_marker = before_marker
    else:
        real_commit = engine._commit_once

        def after_commit(connection):
            real_commit(connection)
            wait_for_owned_termination()

        engine._commit_once = after_commit
    with engine.MaintenanceSession(
        args.database, args.package, release, maintenance_window_confirmed=True
    ) as session:
        apply_plan(session, upgrade_id=args.upgrade_id, plan_sha256=args.plan_sha256)


if __name__ == '__main__':
    main()
