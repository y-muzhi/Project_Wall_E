"""Read an original result only from the two archives fixed by a restore plan."""

from types import SimpleNamespace

from .environment_backup_package import VERIFY_POLICY, lookup_backup_result
from .environment_files import require
from .environment_installation import uuid_value
from .environment_recovery_installation import checked_ref
from .environment_restore_preflight import locked_restore_preflight
from .environment_result_archive import scope_key

INVALID = 'RESTORE_RESULT_SCOPE_MISMATCH'
UNVERIFIED = 'RESTORE_RESULT_UNVERIFIED'


def lookup_restore_result(native, active, args, entry):
    require(
        uuid_value(args.source_environment_id) and uuid_value(args.source_data_generation), INVALID
    )
    scope_key(args.original_capability, args.original_target, args.original_request_key, INVALID)
    with locked_restore_preflight(native, active, args, entry) as verified:
        proof = verified.receipt
        require(args.source_environment_id == proof['environment_id'], INVALID)
        result = {
            'format_version': 1,
            'restore_operation_id': proof['operation_id'],
            'environment_id': args.source_environment_id,
            'data_generation': args.source_data_generation,
            'status': 'UNVERIFIABLE',
            'result_summary': None,
            'archive_role': None,
            'evidence': None,
        }
        if args.source_data_generation == proof['source_data_generation']:
            archive = 'preserved'
        elif args.source_data_generation == proof['selected_source_data_generation']:
            archive = 'selected'
        else:
            return result
        path, pin = checked_ref(verified.plan[archive]['verification'], VERIFY_POLICY)
        original = lookup_backup_result(
            SimpleNamespace(
                anchor=path,
                anchor_sha256=pin,
                **{
                    key: getattr(args, key)
                    for key in (
                        'root',
                        'project',
                        'home',
                        'temporary',
                        'source_environment_id',
                        'source_data_generation',
                        'original_capability',
                        'original_target',
                        'original_request_key',
                    )
                },
            )
        )
        expected_index = proof[f'{archive}_result_index_sha256']
        expected_manifest = proof[f'{archive}_backup_manifest_sha256']
        require(
            original['evidence']['index_sha256'] == expected_index
            and original['evidence']['backup_manifest_sha256'] == expected_manifest,
            UNVERIFIED,
        )
        verified.source.lock.assert_owned()
        return {**result, **original, 'archive_role': archive.upper()}
