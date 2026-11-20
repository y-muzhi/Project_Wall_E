"""Explicit copy/inspect CLI. It never starts, stops or selects a user service."""

import argparse
import sys

from .database import CommitOutcomeUnknown
from .formation_upgrade import copy_upgrade, inspect_target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('copy', 'inspect'))
    parser.add_argument('--source', required=True)
    parser.add_argument(
        '--target',
        required=True,
        help='copy requires a file inside a brand-new private parent directory',
    )
    parser.add_argument('--source-manifest', required=True)
    parser.add_argument('--target-manifest', required=True)
    parser.add_argument('--upgrade-id')
    parser.add_argument('--maintenance-window-confirmed', action='store_true', required=True)
    args = parser.parse_args(argv)
    if args.command == 'inspect' and args.upgrade_id is None:
        parser.error('inspect requires the original --upgrade-id')
    try:
        result = (copy_upgrade if args.command == 'copy' else inspect_target)(
            args.source,
            args.target,
            source_manifest=args.source_manifest,
            target_manifest=args.target_manifest,
            upgrade_id=args.upgrade_id,
            maintenance_window_confirmed=args.maintenance_window_confirmed,
        )
    except (CommitOutcomeUnknown, KeyboardInterrupt):
        print(
            'PENDING_RECONCILIATION; retain both paths and inspect the original upgrade intent.',
            file=sys.stderr,
        )
        return 3
    except (RuntimeError, ValueError, OSError) as error:
        print(
            'FAILED: '
            + type(error).__name__
            + '; retain both paths and inspect the original intent.',
            file=sys.stderr,
        )
        return 2
    print(result.status)
    print('upgrade_id=' + result.upgrade_id)
    print('source_data_sha256=' + result.source_data_sha256)
    print('report=' + result.report_path)
    return 0
