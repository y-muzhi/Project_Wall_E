"""Explicit local maintenance commands; never imported by normal service startup."""

import argparse
import json
import os

from .database import Database, CommitOutcomeUnknown
from .schema_inspection import verify_integrity
from .schema_v20_maintenance import (
    rehearse_plan,
    apply_plan,
    recover_plan,
    _historical_evidence,
)
from .schema_v20_plan import prepare_plan, load_plan, _intent
from .schema_v20_release import load_release
from .schema_v20_upgrade import MaintenanceSession, recover_locked
from .sqlite_runtime import require_active
from .windows_local_paths import LocalPathGuard, local_absolute_path
from .windows_private_package import create_private_package

BOUND_COMMANDS = ('rehearse', 'apply', 'recover', 'check')


def parser():
    result = argparse.ArgumentParser(description='Explicit offline WALL-E Schema200 maintenance')
    result.add_argument('command', choices=('plan', *BOUND_COMMANDS, 'init-v20', 'check-v20'))
    result.add_argument('--database', required=True)
    result.add_argument('--package')
    result.add_argument('--upgrade-id')
    result.add_argument('--plan-sha256')
    result.add_argument(
        '--maintenance-window-confirmed',
        action='store_true',
        help='Confirm separately authorized maintenance, stopped application writers and closed external SQLite editors; this tool does not stop them',
    )
    group = result.add_mutually_exclusive_group()
    group.add_argument('--config-reference', action='append')
    group.add_argument('--no-config-references', action='store_true')
    return result


def _arguments(arguments, command_parser):
    if arguments.command != 'check-v20':
        if arguments.package is None:
            command_parser.error('This command requires an explicit --package')
        if not arguments.maintenance_window_confirmed:
            command_parser.error(
                'Confirm the authorized offline window with --maintenance-window-confirmed'
            )
    elif arguments.package is not None or arguments.maintenance_window_confirmed:
        command_parser.error('check-v20 only takes an explicit database path')
    if arguments.command in BOUND_COMMANDS:
        if arguments.upgrade_id is None or arguments.plan_sha256 is None:
            command_parser.error('Both original --upgrade-id and --plan-sha256 are required')
    elif arguments.upgrade_id is not None or arguments.plan_sha256 is not None:
        command_parser.error('Original plan identity only applies to plan-bound commands')
    if arguments.command == 'plan':
        if arguments.config_reference is None and not arguments.no_config_references:
            command_parser.error('Explicitly declare --config-reference or --no-config-references')
    elif arguments.config_reference is not None or arguments.no_config_references:
        command_parser.error('Configuration reference declarations only apply to plan')


def _initialize(arguments, release):
    source = local_absolute_path(arguments.database)
    # Check the original parent before creating the explicitly requested empty file.
    with LocalPathGuard(source.parent, directory=True):
        try:
            source.lstat()
        except FileNotFoundError:
            with source.open('xb') as stream:
                stream.flush()
                os.fsync(stream.fileno())
        with MaintenanceSession(
            source, arguments.package, release, maintenance_window_confirmed=True
        ) as session:
            result = Database(session.database.path, schema_release=release)._initialize_locked()
            return {
                'status': 'INITIALIZED' if result['initialized'] else 'ALREADY_INITIALIZED',
                'schema_version': 200,
            }


def _execute(arguments, release):
    source = local_absolute_path(arguments.database)
    if arguments.command == 'check-v20':
        with LocalPathGuard(source, directory=False) as guard:
            with Database(
                source, schema_release=release, read_only=True
            ).transaction() as connection:
                verify_integrity(connection)
            guard.verify()
        return {'status': 'CHECKED', 'schema_version': 200}
    local_absolute_path(arguments.package)
    if arguments.command in ('plan', 'init-v20'):
        # A new package is mandatory; no merging or ACL repair of previous assets.
        create_private_package(arguments.package)
    if arguments.command == 'init-v20':
        return _initialize(arguments, release)
    with MaintenanceSession(
        source, arguments.package, release, maintenance_window_confirmed=True
    ) as session:
        if arguments.command == 'plan':
            plan, sha256 = prepare_plan(
                session, configuration_paths=tuple(arguments.config_reference or ())
            )
            return {'status': 'PLAN_READY', 'upgrade_id': plan.upgrade_id, 'plan_sha256': sha256}
        original = {'upgrade_id': arguments.upgrade_id, 'plan_sha256': arguments.plan_sha256}
        if arguments.command == 'rehearse':
            value, sha256 = rehearse_plan(session, **original)
            return {
                'status': value['status'],
                'upgrade_id': arguments.upgrade_id,
                'rehearsal_sha256': sha256,
            }
        if arguments.command == 'check':
            plan, sha256 = load_plan(session, **original)
            _historical_evidence(session, plan, sha256)
            observed = recover_locked(session, _intent(plan))
        else:
            action = apply_plan if arguments.command == 'apply' else recover_plan
            observed = action(session, **original)
        return {
            'status': observed.status,
            'upgrade_id': observed.upgrade_id,
            'committed_at': observed.committed_at,
            'retained_data_matches': observed.retained_data_matches,
            'reason_code': observed.reason_code,
        }


def main(argv=None):
    command_parser = parser()
    arguments = command_parser.parse_args(argv)
    _arguments(arguments, command_parser)
    try:
        require_active()
        value = _execute(arguments, load_release())
        code = 4 if value['status'] == 'UNKNOWN' else 0
    except CommitOutcomeUnknown:
        value = {
            'status': 'PENDING_RECONCILIATION',
            'reason_code': 'ORIGINAL_DATABASE_AND_RECEIPT_UNVERIFIED',
        }
        code = 3
    except KeyboardInterrupt:
        value = {
            'status': 'PENDING_RECONCILIATION',
            'reason_code': 'INTERRUPTED_REQUIRES_ORIGINAL_INTENT_CHECK',
        }
        code = 3
    except Exception as error:
        # Native/API exception messages can include private paths or credentials.
        # Only registered short machine codes leave the maintenance boundary.
        reason = getattr(error, 'code', None)
        import re

        if type(reason) is not str or re.fullmatch('[A-Z][A-Z0-9_]{0,95}', reason) is None:
            reason = 'MAINTENANCE_UNVERIFIED'
        value = {'status': 'BLOCKED', 'reason_code': reason}
        code = 2
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
