"""Run fixed Linux management and maintenance commands."""

import argparse
import json
import os
import runpy
import stat
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path


def trusted_script(path):
    item = path.lstat()
    if (
        path.resolve(strict=True) != path
        or not stat.S_ISREG(item.st_mode)
        or item.st_uid != 0
        or item.st_nlink != 1
        or stat.S_IMODE(item.st_mode) & 0o222
        or any(
            part.is_symlink()
            or part.stat().st_uid != 0
            or stat.S_IMODE(part.stat().st_mode) & 0o022
            for part in path.parents
        )
    ):
        raise ValueError('Untrusted launcher')


def target(args, entry):
    expected_environment = entry['minimum_environment'](args.home, args.temporary)
    entry['demand'](dict(os.environ) == expected_environment, 'Untrusted target environment')
    manifest, libraries, bindings = entry['admit_target'](args.root, args.sha256, args.temporary)
    entry['verify_target_imports'](args.root, manifest)
    if args.action in ('_workspace', '_workspace-binding', '_release'):
        entry['validate_mappings'](args.root, bindings, libraries)
    if args.action in ('_workspace', '_workspace-binding'):
        from backend.app.management.workspace_evidence import load_repository, source_evidence

        repository = load_repository(args.anchor, args.anchor_sha256)
        return source_evidence(repository, ownership_only=args.action == '_workspace-binding')
    if args.action == '_release':
        from backend.app.management.release_artifacts import verify_release

        return verify_release(
            args.anchor, args.anchor_sha256, entry['require_active']().runtime_manifest_sha256
        )

    from backend.app.infrastructure.sqlite_runtime import bind_linux_runtime

    bind_linux_runtime(entry['require_active'])
    from sqlite3 import Error as SQLiteError

    from backend.app.infrastructure.environment_files import EnvironmentFailure
    from backend.app.infrastructure.environment_lock import NativeEnvironmentFiles
    from backend.app.management.registry import REGISTRY_ERROR, registry_command
    from backend.app.management.registry_installation import load_installation

    native = NativeEnvironmentFiles(args.root)
    entry['validate_mappings'](
        args.root, (*bindings, args.root / 'lib/walle_environment_lock.so'), libraries
    )
    os.umask(0o077)
    try:
        if args.action == '_seal-backup-package':
            from backend.app.infrastructure.environment_backup_package_seal import (
                seal_backup_package,
            )

            return seal_backup_package(native, entry['require_active'](), args, entry)
        if args.action == '_verify-backup-package':
            from backend.app.infrastructure.environment_backup_package import verify_backup_package

            return verify_backup_package(args)
        if args.action == '_lookup-backup-result':
            from backend.app.infrastructure.environment_backup_package import lookup_backup_result

            return lookup_backup_result(args)
        if args.action == '_publish-backup-snapshot':
            from backend.app.infrastructure.environment_restic_publish import (
                publish_backup_snapshot,
            )

            return publish_backup_snapshot(args)
        if args.action == '_retrieve-backup-snapshot':
            from backend.app.infrastructure.environment_restic_restore import (
                retrieve_backup_snapshot,
            )

            return retrieve_backup_snapshot(args)
        if args.action == '_publish-offhost-backup-snapshot':
            from backend.app.infrastructure.environment_restic_offhost_publish import (
                publish_offhost_backup_snapshot,
            )

            return publish_offhost_backup_snapshot(args)
        if args.action == '_verify-offhost-backup-snapshot':
            from backend.app.infrastructure.environment_restic_offhost_verify import (
                verify_offhost_backup_snapshot,
            )

            return verify_offhost_backup_snapshot(args)
        if args.action == '_materialize-offhost-backup-package':
            from backend.app.infrastructure.environment_restic_offhost_materialize import (
                materialize_offhost_backup_package,
            )

            return materialize_offhost_backup_package(args)
        if args.action == '_rehearse-backup-package':
            from backend.app.infrastructure.environment_backup_rehearsal import (
                rehearse_backup_package,
            )

            return rehearse_backup_package(entry['require_active'](), args)
        if args.action == '_observe-release-open':
            from backend.app.infrastructure.environment_command import admission_inputs
            from backend.app.infrastructure.environment_release_open import (
                observe_release_open,
                open_inputs,
            )

            installation, _ = admission_inputs(
                args, entry['require_active'](), args.program_sha256, offline=True
            )
            plan = open_inputs(
                installation,
                args.release_open_operation,
                args.release_open_policy,
                args.release_open_policy_sha256,
            )
            return observe_release_open(native, installation, plan, args.release_open_policy_sha256)
        if args.action == '_select-release-deployment':
            from backend.app.infrastructure.environment_release_switch import (
                select_release_deployment,
            )

            return select_release_deployment(native, entry['require_active'](), args, entry)
        if args.action == '_check-restore-readiness':
            from backend.app.infrastructure.environment_restore_readiness import (
                check_restore_readiness,
            )

            return check_restore_readiness(native, entry['require_active'](), args, entry)
        if args.action == '_lookup-restore-result':
            from backend.app.infrastructure.environment_restore_results import lookup_restore_result

            return lookup_restore_result(native, entry['require_active'](), args, entry)
        if args.action == '_prepare-restore-data':
            from backend.app.infrastructure.environment_restore_preparation import (
                prepare_restore_data,
            )

            return prepare_restore_data(native, entry['require_active'](), args, entry)
        if args.action == '_check-restore-preflight':
            from backend.app.infrastructure.environment_restore_preflight import preflight_restore

            return preflight_restore(native, entry['require_active'](), args, entry)
        if args.action == '_check-release-preflight':
            from backend.app.infrastructure.environment_release_preflight import (
                preflight_release_source,
            )

            return preflight_release_source(native, entry['require_active'](), args, entry)
        if args.action == '_check-recovery-chain':
            from backend.app.infrastructure.environment_recovery_chain import check_recovery_chain

            return check_recovery_chain(native, entry['require_active'](), args, entry)
        if args.action == '_check-backup-coverage':
            from backend.app.infrastructure.environment_backup_coverage import check_coverage

            return check_coverage(native, entry['require_active'](), args, entry)
        if args.action == '_capture-database':
            from backend.app.infrastructure.environment_backup import capture_database

            return capture_database(native, entry['require_active'](), args, entry)
        if args.action == '_environment-maintenance':
            from backend.app.infrastructure.environment_maintenance import run_maintenance

            return run_maintenance(native, entry['require_active'](), args, entry)
        if args.action in ('_seal-result-index', '_lookup-result-index'):
            from backend.app.infrastructure.environment_result_archive import (
                lookup_index,
                seal_index,
            )

            action = seal_index if args.action == '_seal-result-index' else lookup_index
            return action(entry['require_active'](), args, entry)
        if args.action == '_restore-database':
            from backend.app.infrastructure.environment_restore import restore_database

            return restore_database(native, entry['require_active'](), args, entry)
        installation = load_installation(args.anchor, args.anchor_sha256, args.sha256)
        if args.action == '_inspect-registry-recovery-deployment':
            from backend.app.management.registry_recovery_opened import inspect_recovered_deployment

            return inspect_recovered_deployment(native, installation, args)
        if args.action == '_settle-registry-recovery-deployment':
            from backend.app.management.registry_recovery_deployment_settlement import (
                settle_opened_deployment,
            )

            return settle_opened_deployment(native, installation, args)
        if args.action == '_settle-registry-recovery-disposition':
            from backend.app.management.registry_recovery_disposition import (
                settle_registry_recovery_disposition,
            )

            return settle_registry_recovery_disposition(native, installation, args)
        if args.action == '_inventory-registry-recovery':
            from backend.app.management.registry_recovery_inventory import (
                inventory_registry_recovery,
            )

            return inventory_registry_recovery(native, installation, args)
        if args.action == '_ready-registry-recovery':
            from backend.app.management.registry_recovery_readiness import ready_registry_recovery

            return ready_registry_recovery(native, installation, args)
        if args.action in ('_prepare-registry-recovery', '_verify-registry-recovery'):
            from backend.app.management.registry_recovery import (
                prepare_registry_recovery,
                verify_registry_recovery,
            )

            action = (
                prepare_registry_recovery
                if args.action == '_prepare-registry-recovery'
                else verify_registry_recovery
            )
            return action(native, installation, args)
        if args.action in ('_snapshot-registry', '_verify-registry-snapshot'):
            from backend.app.management.operation_contract import load_catalog
            from backend.app.management.registry_snapshot import (
                snapshot_registry,
                verify_registry_snapshot,
            )

            if args.catalog is not None:
                load_catalog(args.catalog, args.catalog_sha256, installation)
            action = (
                verify_registry_snapshot
                if args.action == '_verify-registry-snapshot'
                else snapshot_registry
            )
            return action(native, installation, args)
        if args.action == '_release-build-source':
            from backend.app.management.operation_contract import load_catalog
            from backend.app.management.registry import read_registry, verify_registered_data
            from backend.app.management.release_staging import load_build_plan, observe_build_source

            catalog = load_catalog(args.catalog, args.catalog_sha256, installation)
            plan = load_build_plan(catalog, args)
            with read_registry(native, installation, args.sha256) as connection:
                observation = observe_build_source(
                    connection, catalog, plan, args.release_build_policy_sha256
                )
            verify_registered_data(native, installation, args.sha256)
            return observation
        if args.action in ('_candidate', '_inspect-release-build'):
            from contextlib import nullcontext

            from backend.app.management.operation_contract import load_catalog
            from backend.app.management.registry import read_registry, verify_registered_data
            from backend.app.management.release_candidates import candidate_inputs, verify_candidate

            catalog = load_catalog(args.catalog, args.catalog_sha256, installation)
            staged = None
            stage_scope = nullcontext()
            if args.action == '_inspect-release-build':
                from backend.app.management.release_publication import (
                    checked_root,
                    publication_inputs,
                )

                plan, staged, _, _, _ = publication_inputs(catalog, args)
                release_id, candidate_sha = plan['release_id'], plan['candidate_sha256']
                stage_scope = checked_root(staged, plan['build_root']['identity'])
            else:
                release_id, candidate_sha = args.release_candidate, args.release_candidate_sha256
            with stage_scope:
                with read_registry(native, installation, args.sha256) as connection:
                    inputs = candidate_inputs(connection, catalog, release_id, candidate_sha)
                result = verify_candidate(
                    catalog, release_id, candidate_sha, args.sha256, inputs, staged_root=staged
                )
                verify_registered_data(native, installation, args.sha256)
                return result
        if args.action == '_serve':
            from backend.app.management.management_web import serve
            from backend.app.management.operation_contract import load_catalog
            from backend.app.management.registry_recovery_entry_admission import (
                verify_serving_entry,
            )
            from backend.app.management.web_installation import load_web

            catalog = load_catalog(args.catalog, args.catalog_sha256, installation)
            verify_serving_entry(installation, args)
            web = load_web(args.web, args.web_sha256, catalog, installation)
            return serve(native, installation, catalog, web, args.sha256)
        if args.action in (
            '_admit-runtime',
            '_authorize-cancel',
            '_claim-release-maintenance',
            '_claim-restore-maintenance',
            '_admit-release-open',
            '_admit-restore-open',
            '_observe-managed-backup',
            '_claim-managed-backup',
            '_archive-subject',
            '_complete-archive',
        ):
            from backend.app.infrastructure.environment_files import decode, require
            from backend.app.management.lifecycle_operations import dispatch_start
            from backend.app.management.operation_contract import INVALID, load_catalog
            from backend.app.management.registry import read_registry, verified_registry

            catalog = load_catalog(args.catalog, args.catalog_sha256, installation)
            raw = sys.stdin.buffer.read(16 * 1024 + 1)
            require(0 < len(raw) <= 16 * 1024, INVALID)
            request = decode(raw, INVALID)
            if args.action == '_authorize-cancel':
                from backend.app.management.runtime_controls import authorize_cancel

                with read_registry(native, installation, args.sha256) as connection:
                    return authorize_cancel(connection, catalog, request)
            if args.action == '_observe-managed-backup':
                from backend.app.management.backup_capture import observe_backup

                with read_registry(native, installation, args.sha256) as connection:
                    return observe_backup(connection, catalog, request)
            if args.action == '_archive-subject':
                from backend.app.management.environment_archive import read_archive_subject

                with read_registry(native, installation, args.sha256) as connection:
                    return read_archive_subject(connection, catalog, request)
            with verified_registry(native, installation, writable=True) as (connection, lock):
                if args.action == '_complete-archive':
                    from backend.app.management.environment_archive import complete_archive

                    return complete_archive(connection, lock, catalog, request)
                if args.action == '_claim-release-maintenance':
                    from backend.app.management.release_execution import claim_release_maintenance

                    return claim_release_maintenance(connection, lock, catalog, request)
                if args.action == '_claim-restore-maintenance':
                    from backend.app.management.restore_execution import claim_restore_maintenance

                    return claim_restore_maintenance(connection, lock, catalog, request)
                if args.action == '_admit-release-open':
                    from backend.app.management.release_open_admission import admit_release_open

                    return admit_release_open(connection, lock, catalog, request)
                if args.action == '_admit-restore-open':
                    from backend.app.management.restore_runtime import admit_restore_open

                    return admit_restore_open(connection, lock, catalog, request, args.sha256)
                if args.action == '_claim-managed-backup':
                    from backend.app.management.backup_capture import claim_backup

                    return claim_backup(connection, lock, catalog, request)
                return dispatch_start(connection, lock, catalog, request)
        if args.action == '_operation':
            from backend.app.management.operation_contract import (
                INVALID,
                installed_record,
                load_catalog,
            )
            from backend.app.management.operation_store import run_operation

            catalog = load_catalog(args.catalog, args.catalog_sha256, installation)
            request = installed_record(args.request, code=INVALID)
            return run_operation(native, installation, catalog, request, args.sha256)
        return registry_command(args.action[1:], native, installation)
    except SQLiteError as error:
        code = {
            '_check-backup-coverage': 'BACKUP_COVERAGE_UNVERIFIED',
            '_check-recovery-chain': 'RECOVERY_CHAIN_UNVERIFIED',
            '_check-release-preflight': 'RELEASE_PREFLIGHT_UNVERIFIED',
            '_check-restore-preflight': 'RESTORE_PREFLIGHT_UNVERIFIED',
            '_prepare-restore-data': 'RESTORE_DATA_PREPARATION_UNVERIFIED',
            '_lookup-restore-result': 'RESTORE_RESULT_UNVERIFIED',
            '_check-restore-readiness': 'RESTORE_READINESS_UNVERIFIED',
            '_seal-backup-package': 'BACKUP_PACKAGE_UNVERIFIED',
            '_publish-offhost-backup-snapshot': 'OFFHOST_BACKUP_UNVERIFIED',
            '_verify-offhost-backup-snapshot': 'OFFHOST_BACKUP_UNVERIFIED',
            '_materialize-offhost-backup-package': 'OFFHOST_BACKUP_UNVERIFIED',
            '_snapshot-registry': 'MANAGEMENT_REGISTRY_SNAPSHOT_UNVERIFIED',
            '_verify-registry-snapshot': 'MANAGEMENT_REGISTRY_SNAPSHOT_UNVERIFIED',
            '_prepare-registry-recovery': 'MANAGEMENT_REGISTRY_RECOVERY_UNVERIFIED',
            '_verify-registry-recovery': 'MANAGEMENT_REGISTRY_RECOVERY_UNVERIFIED',
            '_ready-registry-recovery': 'MANAGEMENT_REGISTRY_READINESS_UNVERIFIED',
            '_inventory-registry-recovery': 'MANAGEMENT_REGISTRY_RECOVERY_INVENTORY_UNVERIFIED',
            '_settle-registry-recovery-disposition': (
                'MANAGEMENT_REGISTRY_RECOVERY_DISPOSITION_UNVERIFIED'
            ),
            '_inspect-registry-recovery-deployment': (
                'MANAGEMENT_REGISTRY_RECOVERY_OPENING_UNVERIFIED'
            ),
            '_settle-registry-recovery-deployment': (
                'MANAGEMENT_REGISTRY_RECOVERY_DEPLOYMENT_SETTLEMENT_UNVERIFIED'
            ),
        }.get(args.action, REGISTRY_ERROR)
        raise EnvironmentFailure(code) from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = (
        'initialize',
        'reconcile',
        'diagnose',
        'snapshot-registry',
        'verify-registry-snapshot',
        'prepare-registry-recovery',
        'verify-registry-recovery',
        'ready-registry-recovery',
        'inventory-registry-recovery',
        'settle-registry-recovery-disposition',
        'inspect-registry-recovery-deployment',
        'settle-registry-recovery-deployment',
        'workspace',
        'workspace-binding',
        'release',
        'candidate',
        'inspect-release-build',
        'release-build-source',
        'operation',
        'serve',
        'capture-database',
        'check-backup-coverage',
        'check-recovery-chain',
        'check-release-preflight',
        'check-restore-preflight',
        'prepare-restore-data',
        'lookup-restore-result',
        'check-restore-readiness',
        'select-release-deployment',
        'observe-release-open',
        'seal-backup-package',
        'verify-backup-package',
        'lookup-backup-result',
        'publish-backup-snapshot',
        'retrieve-backup-snapshot',
        'publish-offhost-backup-snapshot',
        'verify-offhost-backup-snapshot',
        'materialize-offhost-backup-package',
        'rehearse-backup-package',
        'restore-database',
        'seal-result-index',
        'lookup-result-index',
        'environment-maintenance',
    )
    parser.add_argument(
        'action',
        choices=(
            'prepare',
            'pause-registry-dispatch',
            'observe-registry-dispatch',
            'place-registry-recovery',
            'observe-registry-recovery',
            'refresh-registry-recovery-observation',
            'stop-registry-recovery-deployment',
            'verify-registry-recovery-deployment-entry',
            'authorize-registry-recovery-deployment-adoption',
            'check-registry-recovery-dispatch',
            'inspect-registry-recovery-dispatch',
            'open-registry-recovery-dispatch',
            'select-registry-recovery',
            'prepare-registry-recovery-entry',
            'admit-registry-recovery-entry',
            'enter-host-recovery-hold',
            'observe-host-recovery-hold',
            'authorize-host-recovery-deployment',
            'observe-attach',
            'observe-delivery',
            'observe-runtime',
            'observe-release-source',
            'observe-restore-source',
            'observe-release-maintenance',
            'observe-environment-control',
            'enter-managed-release',
            'retire-managed-release',
            'enter-managed-restore',
            'retire-managed-restore',
            'select-managed-restore',
            'select-managed-release',
            'start-managed-release',
            'start-managed-restore',
            'capture-managed-backup',
            'complete-managed-backup',
            'stop-runtime',
            'start-runtime',
            'archive-environment',
            'prepare-candidate-validation',
            'prepare-recovery-replica',
            'prepare-restore-generation',
            'verify-recovery-replica',
            'export-management-backups',
            'export-prior-command-results',
            'record-release-compatibility',
            'prepare-release-deployment',
            'describe-restore-deployment',
            'verify-release-deployment',
            'verify-release-gateway',
            'seal-release',
            'prepare-release-build',
            'prepare-release-final-build',
            'cancel-runtime',
            'gateway',
            '_admit-runtime',
            '_authorize-cancel',
            '_claim-release-maintenance',
            '_claim-restore-maintenance',
            '_admit-release-open',
            '_admit-restore-open',
            '_observe-managed-backup',
            '_claim-managed-backup',
            '_archive-subject',
            '_complete-archive',
            *modes,
            *('_' + mode for mode in modes),
        ),
    )
    for path in ('root', 'project', 'runtime-entry', 'anchor'):
        parser.add_argument(f'--{path}', required=True, type=Path)
    for path in ('home', 'temporary'):
        parser.add_argument(f'--{path}', type=Path)
    for field in ('sha256', 'program-sha256'):
        parser.add_argument(f'--{field}', required=True)
    parser.add_argument('--anchor-sha256')
    parser.add_argument('--registry-recovery-id')
    parser.add_argument('--registry-recovery-policy', type=Path)
    parser.add_argument('--registry-recovery-policy-sha256')
    parser.add_argument('--registry-recovery-receipt-sha256')
    parser.add_argument('--registry-placement-receipt-sha256')
    parser.add_argument('--registry-readiness-receipt-sha256')
    parser.add_argument('--registry-inventory-receipt-sha256')
    parser.add_argument('--registry-observation-id')
    parser.add_argument('--registry-observation-receipt-sha256')
    parser.add_argument('--registry-systemctl-sha256')
    parser.add_argument('--registry-selection-policy', type=Path)
    parser.add_argument('--registry-selection-policy-sha256')
    parser.add_argument('--registry-selection-receipt-sha256')
    parser.add_argument('--registry-entry-policy', type=Path)
    parser.add_argument('--registry-entry-policy-sha256')
    parser.add_argument('--registry-entry-admission-policy', type=Path)
    parser.add_argument('--registry-entry-admission-policy-sha256')
    parser.add_argument('--registry-entry-admission-receipt-sha256')
    parser.add_argument('--registry-dispatch-open-policy', type=Path)
    parser.add_argument('--registry-dispatch-open-policy-sha256')
    parser.add_argument('--registry-disposition-policy', type=Path)
    parser.add_argument('--registry-disposition-policy-sha256')
    parser.add_argument('--registry-dispatch-blocker')
    parser.add_argument('--registry-dispatch-blocker-offset', type=int)
    parser.add_argument('--registry-snapshot-id')
    parser.add_argument('--registry-snapshot-receipt-sha256')
    parser.add_argument('--registry-snapshot-hold-id')
    parser.add_argument('--registry-snapshot-hold-sha256')
    parser.add_argument('--manager-uid', type=int)
    parser.add_argument('--manager-gid', type=int)
    parser.add_argument('--host-id')
    parser.add_argument('--catalog', type=Path)
    parser.add_argument('--catalog-sha256')
    parser.add_argument('--release-candidate')
    parser.add_argument('--release-candidate-sha256')
    parser.add_argument('--require-release-evidence', action='store_true')
    parser.add_argument('--release-build-policy', type=Path)
    parser.add_argument('--release-build-policy-sha256')
    parser.add_argument('--release-publication-policy', type=Path)
    parser.add_argument('--release-publication-policy-sha256')
    parser.add_argument('--release-finalization-policy', type=Path)
    parser.add_argument('--release-finalization-policy-sha256')
    parser.add_argument('--request', type=Path)
    parser.add_argument('--candidate-ref')
    parser.add_argument('--release-configuration-ref')
    parser.add_argument('--release-operation-id')
    parser.add_argument('--backup-operation-id')
    parser.add_argument('--managed-backup-result-policy', type=Path)
    parser.add_argument('--managed-backup-result-policy-sha256')
    parser.add_argument('--managed-release-open-policy', type=Path)
    parser.add_argument('--managed-release-open-policy-sha256')
    parser.add_argument('--workspace-ref')
    parser.add_argument('--workspace-sha256')
    parser.add_argument('--web', type=Path)
    parser.add_argument('--web-sha256')
    parser.add_argument('--web-hashes', type=Path)
    parser.add_argument('--web-output', type=Path)
    parser.add_argument('--gateway-group', type=int)
    parser.add_argument('--capture-policy', type=Path)
    parser.add_argument('--capture-sha256')
    parser.add_argument('--restore-policy', type=Path)
    parser.add_argument('--restore-sha256')
    parser.add_argument('--recovery-chain-policy', type=Path)
    parser.add_argument('--recovery-chain-policy-sha256')
    parser.add_argument('--release-preflight-policy', type=Path)
    parser.add_argument('--release-preflight-policy-sha256')
    parser.add_argument('--restore-preflight-policy', type=Path)
    parser.add_argument('--restore-preflight-policy-sha256')
    parser.add_argument('--restore-readiness-policy', type=Path)
    parser.add_argument('--restore-readiness-policy-sha256')
    parser.add_argument('--release-compatibility-policy', type=Path)
    parser.add_argument('--release-compatibility-policy-sha256')
    parser.add_argument('--release-deployment-policy', type=Path)
    parser.add_argument('--release-deployment-policy-sha256')
    parser.add_argument('--release-switch-policy', type=Path)
    parser.add_argument('--release-switch-policy-sha256')
    parser.add_argument('--release-open-policy', type=Path)
    parser.add_argument('--release-open-policy-sha256')
    parser.add_argument('--release-open-operation')
    parser.add_argument('--backup-package-policy', type=Path)
    parser.add_argument('--backup-package-policy-sha256')
    parser.add_argument('--maintenance-policy', type=Path)
    parser.add_argument('--maintenance-policy-sha256')
    parser.add_argument('--maintenance-action', choices=('enter', 'cancel', 'observe'))
    parser.add_argument('--result-index-policy', type=Path)
    parser.add_argument('--result-index-policy-sha256')
    for field in (
        'result-index-sha256',
        'source-environment-id',
        'source-data-generation',
        'original-capability',
        'original-target',
        'original-request-key',
    ):
        parser.add_argument('--' + field)
    parser.add_argument('--candidate-validation-policy', type=Path)
    parser.add_argument('--candidate-validation-policy-sha256')
    parser.add_argument('--runtime-policy', type=Path)
    parser.add_argument('--runtime-policy-sha256')
    parser.add_argument('--recovered-observation-id')
    parser.add_argument('--stop-policy', type=Path)
    parser.add_argument('--stop-policy-sha256')
    parser.add_argument('--archive-operation-id')
    parser.add_argument('--start-policy', type=Path)
    parser.add_argument('--start-policy-sha256')
    parser.add_argument('--cancel-policy', type=Path)
    parser.add_argument('--cancel-policy-sha256')
    args = parser.parse_args()
    prepare = args.action == 'prepare'
    registry_dispatch = args.action in ('pause-registry-dispatch', 'observe-registry-dispatch')
    host_recovery_control = args.action in (
        'enter-host-recovery-hold',
        'observe-host-recovery-hold',
    )
    host_recovery_authorization = args.action == 'authorize-host-recovery-deployment'
    registry_recovery_placement = args.action == 'place-registry-recovery'
    registry_recovery_open = args.action == 'open-registry-recovery-dispatch'
    registry_recovery_inspect = args.action == 'inspect-registry-recovery-dispatch'
    registry_recovery_stop = args.action == 'stop-registry-recovery-deployment'
    registry_deployment_adoption = args.action == 'authorize-registry-recovery-deployment-adoption'
    registry_deployment_entry = (
        args.action == 'verify-registry-recovery-deployment-entry' or registry_deployment_adoption
    )
    registry_recovery_review = (
        args.action == 'check-registry-recovery-dispatch'
        or registry_recovery_open
        or registry_recovery_inspect
    )
    registry_recovery_refresh = (
        args.action == 'refresh-registry-recovery-observation'
        or registry_recovery_review
        or registry_recovery_stop
        or registry_deployment_entry
    )
    registry_recovery_observer = (
        args.action == 'observe-registry-recovery' or registry_recovery_refresh
    )
    registry_recovery_select = args.action == 'select-registry-recovery'
    registry_recovery_entry = args.action in (
        'prepare-registry-recovery-entry',
        'admit-registry-recovery-entry',
    )
    admitting_entry = args.action == 'admit-registry-recovery-entry'
    registry_recovery_host = (
        registry_recovery_placement
        or registry_recovery_observer
        or registry_recovery_select
        or registry_recovery_entry
    )
    archive = args.action == 'archive-environment'
    attach_observer = args.action == 'observe-attach'
    delivery_observer = args.action == 'observe-delivery'
    runtime_observer = args.action == 'observe-runtime'
    release_source_observer = args.action == 'observe-release-source'
    restore_source_observer = args.action == 'observe-restore-source'
    release_maintenance_observer = args.action == 'observe-release-maintenance'
    environment_control_observer = args.action == 'observe-environment-control'
    release_maintenance = args.action == 'enter-managed-release'
    release_retirement = args.action == 'retire-managed-release'
    restore_maintenance = args.action == 'enter-managed-restore'
    restore_retirement = args.action == 'retire-managed-restore'
    managed_restore_selection = args.action == 'select-managed-restore'
    managed_release_selection = args.action == 'select-managed-release'
    managed_release_start = args.action == 'start-managed-release'
    managed_restore_start = args.action == 'start-managed-restore'
    managed_backup_capture = args.action == 'capture-managed-backup'
    managed_backup_completion = args.action == 'complete-managed-backup'
    normal_runtime_stop = args.action == 'stop-runtime'
    has_stop_policy = normal_runtime_stop or registry_recovery_stop or registry_deployment_entry
    normal_runtime_start = args.action == 'start-runtime'
    runtime_cancellation = args.action == 'cancel-runtime'
    gateway = args.action == 'gateway'
    candidate_validation = args.action == 'prepare-candidate-validation'
    recovery_preparation = args.action == 'prepare-recovery-replica'
    generation_preparation = args.action == 'prepare-restore-generation'
    recovery_verification = args.action == 'verify-recovery-replica'
    backup_export = args.action == 'export-management-backups'
    prior_result_export = args.action == 'export-prior-command-results'
    compatibility_recording = args.action == 'record-release-compatibility'
    deployment_preparation = args.action in (
        'prepare-release-deployment',
        'describe-restore-deployment',
    )
    deployment_verification = args.action == 'verify-release-deployment'
    release_gateway_verification = args.action == 'verify-release-gateway'
    standalone_host_action = (
        registry_dispatch
        or host_recovery_control
        or host_recovery_authorization
        or registry_recovery_host
        or recovery_preparation
        or generation_preparation
        or recovery_verification
        or backup_export
        or prior_result_export
        or compatibility_recording
        or deployment_preparation
        or deployment_verification
        or release_gateway_verification
    )
    serving = args.action in ('serve', '_serve')
    candidate = args.action in ('candidate', '_candidate')
    inspect_release = args.action in ('inspect-release-build', '_inspect-release-build')
    publication = args.action == 'seal-release'
    initial_build = args.action == 'prepare-release-build'
    build_observation = args.action in ('release-build-source', '_release-build-source')
    final_build = args.action == 'prepare-release-final-build'
    host_action = (
        attach_observer
        or delivery_observer
        or runtime_observer
        or release_source_observer
        or restore_source_observer
        or release_maintenance_observer
        or environment_control_observer
        or release_maintenance
        or release_retirement
        or restore_maintenance
        or restore_retirement
        or managed_restore_selection
        or managed_release_selection
        or managed_release_start
        or managed_restore_start
        or managed_backup_capture
        or managed_backup_completion
        or normal_runtime_stop
        or normal_runtime_start
        or archive
        or runtime_cancellation
        or gateway
        or candidate_validation
        or standalone_host_action
        or publication
        or initial_build
        or final_build
    )
    operation = args.action in ('operation', '_operation')
    registry_recovery_verify = args.action in (
        'verify-registry-recovery',
        '_verify-registry-recovery',
    )
    registry_recovery_ready = args.action in ('ready-registry-recovery', '_ready-registry-recovery')
    registry_inventory = args.action in (
        'inventory-registry-recovery',
        '_inventory-registry-recovery',
    )
    registry_recovery = (
        (registry_recovery_host and not registry_recovery_entry)
        or registry_inventory
        or registry_recovery_ready
        or registry_recovery_verify
        or args.action
        in (
            'prepare-registry-recovery',
            '_prepare-registry-recovery',
        )
    )
    registry_recovery_values = (args.registry_recovery_policy, args.registry_recovery_policy_sha256)
    registry_selection_values = (
        args.registry_selection_policy,
        args.registry_selection_policy_sha256,
    )
    registry_entry_values = (args.registry_entry_policy, args.registry_entry_policy_sha256)
    dispatch_open_values = (
        args.registry_dispatch_open_policy,
        args.registry_dispatch_open_policy_sha256,
    )
    entry_admission_values = (
        args.registry_entry_admission_policy,
        args.registry_entry_admission_policy_sha256,
    )
    registry_disposition = args.action in (
        'settle-registry-recovery-disposition',
        '_settle-registry-recovery-disposition',
        'inspect-registry-recovery-deployment',
        '_inspect-registry-recovery-deployment',
        'settle-registry-recovery-deployment',
        '_settle-registry-recovery-deployment',
    )
    disposition_values = (args.registry_disposition_policy, args.registry_disposition_policy_sha256)
    registry_snapshot = args.action in ('snapshot-registry', '_snapshot-registry')
    registry_snapshot_verify = args.action in (
        'verify-registry-snapshot',
        '_verify-registry-snapshot',
    )
    admission = args.action in (
        '_admit-runtime',
        '_authorize-cancel',
        '_claim-release-maintenance',
        '_claim-restore-maintenance',
        '_admit-release-open',
        '_admit-restore-open',
        '_observe-managed-backup',
        '_claim-managed-backup',
        '_archive-subject',
        '_complete-archive',
    )
    privileged = (args.manager_uid, args.manager_gid, args.host_id)
    ordinary = (args.anchor_sha256, args.temporary, args.home)
    installed = (args.catalog, args.catalog_sha256)
    workspace = (args.workspace_ref, args.workspace_sha256)
    candidate_values = (args.release_candidate, args.release_candidate_sha256)
    build_values = (args.release_build_policy, args.release_build_policy_sha256)
    publication_values = (args.release_publication_policy, args.release_publication_policy_sha256)
    use_publication_policy = (
        publication
        or final_build
        or inspect_release
        or (candidate_validation and any(publication_values))
    )
    finalization_values = (
        args.release_finalization_policy,
        args.release_finalization_policy_sha256,
    )
    validation_values = (args.candidate_validation_policy, args.candidate_validation_policy_sha256)
    web_values = (args.web, args.web_sha256)
    gateway_values = (args.web_hashes, args.web_output, args.gateway_group)
    capture = args.action in (
        'capture-database',
        '_capture-database',
        'check-backup-coverage',
        '_check-backup-coverage',
        'capture-managed-backup',
    )
    restoring = args.action in ('restore-database', '_restore-database')
    recovery_chain = args.action in ('check-recovery-chain', '_check-recovery-chain')
    chain_values = (args.recovery_chain_policy, args.recovery_chain_policy_sha256)
    release_preflight = args.action in (
        'check-release-preflight',
        '_check-release-preflight',
        'select-managed-release',
    )
    preflight_values = (args.release_preflight_policy, args.release_preflight_policy_sha256)
    restore_preflight = args.action in (
        'check-restore-preflight',
        '_check-restore-preflight',
        'prepare-restore-data',
        '_prepare-restore-data',
        'lookup-restore-result',
        '_lookup-restore-result',
        'check-restore-readiness',
        '_check-restore-readiness',
        'select-managed-restore',
    )
    restore_preflight_values = (args.restore_preflight_policy, args.restore_preflight_policy_sha256)
    restore_readiness = args.action in (
        'check-restore-readiness',
        '_check-restore-readiness',
        'select-managed-restore',
    )
    restore_readiness_values = (args.restore_readiness_policy, args.restore_readiness_policy_sha256)
    compatibility_values = (
        args.release_compatibility_policy,
        args.release_compatibility_policy_sha256,
    )
    deployment_values = (args.release_deployment_policy, args.release_deployment_policy_sha256)
    deployment_switch = args.action in ('select-release-deployment', '_select-release-deployment')
    switch_values = (args.release_switch_policy, args.release_switch_policy_sha256)
    observe_open = args.action in ('observe-release-open', '_observe-release-open')
    open_values = (
        args.release_open_policy,
        args.release_open_policy_sha256,
        args.release_open_operation,
    )
    sealing_backup = args.action in ('seal-backup-package', '_seal-backup-package')
    backup_values = (args.backup_package_policy, args.backup_package_policy_sha256)
    maintenance = args.action in ('environment-maintenance', '_environment-maintenance')
    maintenance_values = (
        args.maintenance_policy,
        args.maintenance_policy_sha256,
        args.maintenance_action,
    )
    capture_values = (args.capture_policy, args.capture_sha256)
    runtime_values = (args.runtime_policy, args.runtime_policy_sha256)
    restore_values = (args.restore_policy, args.restore_sha256)
    sealing_index = args.action in ('seal-result-index', '_seal-result-index')
    looking_up_index = args.action in ('lookup-result-index', '_lookup-result-index')
    looking_up_backup = args.action in ('lookup-backup-result', '_lookup-backup-result')
    looking_up_restore = args.action in ('lookup-restore-result', '_lookup-restore-result')
    index_values = (args.result_index_policy, args.result_index_policy_sha256)
    lookup_values = (
        args.source_environment_id,
        args.source_data_generation,
        args.original_capability,
        args.original_target,
        args.original_request_key,
    )
    managed_open_values = (
        args.managed_release_open_policy,
        args.managed_release_open_policy_sha256,
    )
    managed_backup_result = (
        args.managed_backup_result_policy,
        args.managed_backup_result_policy_sha256,
    )
    stop_values = (args.stop_policy, args.stop_policy_sha256)
    start_values = (args.start_policy, args.start_policy_sha256)
    cancel_values = (args.cancel_policy, args.cancel_policy_sha256)
    if (
        not (
            all(installed)
            if (host_action and not standalone_host_action)
            or registry_recovery_observer
            or registry_disposition
            or operation
            or registry_snapshot
            or serving
            or admission
            or candidate
            or inspect_release
            or build_observation
            else bool(args.catalog_sha256)
            if registry_snapshot_verify
            else not any(installed)
        )
        or not (
            all(disposition_values)
            if registry_disposition or registry_deployment_adoption
            else not any(disposition_values)
        )
        or not (all(candidate_values) if candidate else not any(candidate_values))
        or (args.require_release_evidence and not candidate)
        or not (all(publication_values) if use_publication_policy else not any(publication_values))
        or not (all(validation_values) if candidate_validation else not any(validation_values))
        or not (all(build_values) if initial_build or build_observation else not any(build_values))
        or not (all(finalization_values) if final_build else not any(finalization_values))
        or not (all(capture_values) if capture else not any(capture_values))
        or not (all(restore_values) if restoring else not any(restore_values))
        or not (all(chain_values) if recovery_chain else not any(chain_values))
        or not (all(preflight_values) if release_preflight else not any(preflight_values))
        or not (
            all(restore_preflight_values)
            if restore_preflight
            else not any(restore_preflight_values)
        )
        or not (
            all(restore_readiness_values)
            if restore_readiness
            else not any(restore_readiness_values)
        )
        or not (
            all(compatibility_values) if compatibility_recording else not any(compatibility_values)
        )
        or not (all(deployment_values) if deployment_preparation else not any(deployment_values))
        or not (all(switch_values) if deployment_switch else not any(switch_values))
        or not (all(open_values) if observe_open else not any(open_values))
        or not (
            all(managed_open_values)
            if managed_release_start or managed_restore_start
            else not any(managed_open_values)
        )
        or not (
            all(managed_backup_result)
            if managed_backup_completion
            else not any(managed_backup_result)
        )
        or not (all(backup_values) if sealing_backup else not any(backup_values))
        or not (all(maintenance_values) if maintenance else not any(maintenance_values))
        or not (all(index_values) if sealing_index or looking_up_index else not any(index_values))
        or not (
            all(lookup_values)
            if looking_up_index or looking_up_backup or looking_up_restore
            else not any(lookup_values)
        )
        or bool(args.result_index_sha256) != looking_up_index
        or not (all(runtime_values) if runtime_observer else not any(runtime_values))
        or (args.recovered_observation_id is not None and not runtime_observer)
        or not (all(stop_values) if has_stop_policy else not any(stop_values))
        or not (all(start_values) if normal_runtime_start else not any(start_values))
        or bool(args.archive_operation_id) != archive
        or not (all(cancel_values) if runtime_cancellation else not any(cancel_values))
        or bool(args.request) != (operation or delivery_observer)
        or bool(args.registry_recovery_id) != registry_dispatch
        or not (
            all(registry_recovery_values)
            if registry_recovery
            else not any(registry_recovery_values)
        )
        or bool(args.registry_recovery_receipt_sha256)
        != (
            registry_recovery_verify
            or registry_recovery_placement
            or registry_recovery_ready
            or registry_inventory
            or registry_recovery_observer
        )
        or bool(args.registry_placement_receipt_sha256)
        != (registry_recovery_ready or registry_inventory or registry_recovery_observer)
        or bool(args.registry_readiness_receipt_sha256)
        != (registry_inventory or registry_recovery_observer)
        or bool(args.registry_inventory_receipt_sha256) != registry_recovery_observer
        or bool(args.registry_observation_id) != registry_recovery_observer
        or bool(args.registry_observation_receipt_sha256) != registry_recovery_review
        or bool(args.registry_dispatch_blocker) != registry_recovery_inspect
        or (args.registry_dispatch_blocker_offset is not None and not registry_recovery_inspect)
        or not (
            all(dispatch_open_values) if registry_recovery_open else not any(dispatch_open_values)
        )
        or bool(args.registry_systemctl_sha256) != registry_recovery_observer
        or bool(args.registry_selection_receipt_sha256) != registry_recovery_refresh
        or not (
            all(registry_selection_values)
            if registry_recovery_select
            else not any(registry_selection_values)
        )
        or not (
            all(registry_entry_values)
            if registry_recovery_entry
            else not any(registry_entry_values)
        )
        or not (all(entry_admission_values) if admitting_entry else not any(entry_admission_values))
        or (
            (registry_recovery_review or registry_deployment_entry)
            and not args.registry_entry_admission_receipt_sha256
        )
        or (
            args.registry_entry_admission_receipt_sha256 is not None
            and not (serving or registry_recovery_review or registry_deployment_entry)
        )
        or bool(args.registry_snapshot_id) != (registry_snapshot or registry_snapshot_verify)
        or bool(args.registry_snapshot_receipt_sha256) != registry_snapshot_verify
        or (args.registry_snapshot_hold_id is None) != (args.registry_snapshot_hold_sha256 is None)
        or (args.registry_snapshot_hold_id is not None and not registry_snapshot)
        or bool(args.candidate_ref)
        != (attach_observer or environment_control_observer or restore_source_observer)
        or bool(args.backup_operation_id) != (managed_backup_capture or managed_backup_completion)
        or bool(args.release_configuration_ref)
        != (release_source_observer or release_maintenance_observer)
        or bool(args.release_operation_id)
        != (
            release_maintenance
            or release_retirement
            or restore_maintenance
            or restore_retirement
            or managed_restore_selection
            or managed_release_selection
            or managed_release_start
            or managed_restore_start
        )
        or not (all(workspace) if delivery_observer else not any(workspace))
        or not (all(web_values) if gateway or serving else not any(web_values))
        or not (
            all(gateway_values)
            if gateway
            else not any(value is not None for value in gateway_values)
        )
    ):
        parser.error('Unexpected management inputs')
    if (
        prepare
        and (not all(value is not None for value in privileged) or any(ordinary))
        or host_action
        and (
            not args.anchor_sha256
            or args.home
            or args.temporary
            or any(value is not None for value in privileged)
        )
        or not (prepare or host_action)
        and (not all(ordinary) or any(value is not None for value in privileged))
    ):
        parser.error('Use the explicit installation or existing registry arguments')
    try:
        if not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode):
            raise ValueError('Use -I -B -S')
        if (os.geteuid() == 0) != (prepare or host_action):
            raise ValueError('Unexpected process identity for management action')
        trusted_script(Path(__file__))
        trusted_script(args.runtime_entry)
        entry = runpy.run_path(str(args.runtime_entry))
        entry['demand'](
            all(
                not (name.startswith(('LD_', 'PYTHON', 'PIP_')) or name.lower().endswith('_proxy'))
                for name in os.environ
            ),
            'Untrusted loader or proxy variable',
        )
        entry['demand'](
            entry['verify_program'](args.project) == args.program_sha256,
            'PROGRAM_SNAPSHOT_MISMATCH',
        )
        sys.path.append(str(args.project))
        if prepare:
            entry['verify_runtime'](args.root, args.sha256)
            from backend.app.management.registry_installation import (
                ANCHOR_NAME,
                prepare_installation,
            )

            entry['demand'](args.anchor.name == ANCHOR_NAME, 'Unexpected installation anchor')
            result = prepare_installation(
                args.anchor.parent, args.manager_uid, args.manager_gid, args.sha256, args.host_id
            )
            print(json.dumps({'status': 'REGISTRY_PREPARED', **result}, sort_keys=True))
        elif registry_recovery_host:
            manifest, runtime_hosts = entry['verify_runtime'](args.root, args.sha256)
            executable = args.root / manifest['python']['executable_ref']
            if Path(sys.executable) != executable:
                os.execve(
                    executable,
                    [str(executable), *entry['FLAGS'], str(Path(__file__)), *sys.argv[1:]],
                    {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'TZ': 'UTC'},
                )
            from backend.app.infrastructure.environment_lock import (
                LIBRARY_REF,
                NativeEnvironmentFiles,
            )
            from backend.app.management.registry_installation import load_installation
            from backend.app.management.registry_recovery_dispatch_open import (
                open_registry_recovery_dispatch,
            )
            from backend.app.management.registry_recovery_dispatch_review import (
                BLOCKED as DISPATCH_REVIEW_BLOCKED,
            )
            from backend.app.management.registry_recovery_dispatch_review import (
                check_registry_recovery_dispatch,
                inspect_registry_recovery_dispatch,
            )
            from backend.app.management.registry_recovery_entry import (
                prepare_registry_recovery_entry,
            )
            from backend.app.management.registry_recovery_entry_admission import (
                admit_registry_recovery_entry,
            )
            from backend.app.management.registry_recovery_installation import (
                place_recovered_registry,
            )
            from backend.app.management.registry_recovery_observation import (
                observe_registry_recovery,
            )
            from backend.app.management.registry_recovery_reobserve import (
                refresh_registry_recovery_observation,
            )
            from backend.app.management.registry_recovery_selection import select_registry_recovery

            native = NativeEnvironmentFiles(args.root)
            entry['validate_mappings'](
                args.root, (executable, args.root / LIBRARY_REF), runtime_hosts
            )
            if registry_recovery_select:
                result = select_registry_recovery(native, args)
            else:
                registry = load_installation(
                    args.anchor, args.anchor_sha256, args.sha256, installer=True
                )
                if registry_recovery_open:
                    result = open_registry_recovery_dispatch(native, registry, args, entry)
                elif registry_recovery_inspect:
                    result = inspect_registry_recovery_dispatch(native, registry, args, entry)
                elif registry_recovery_review:
                    result = check_registry_recovery_dispatch(native, registry, args, entry)
                elif registry_deployment_adoption:
                    from backend.app.management.registry_recovery_deployment_authorization import (
                        authorize_deployment_adoption,
                    )

                    result = authorize_deployment_adoption(native, registry, args, entry)
                elif registry_deployment_entry:
                    from backend.app.management.registry_recovery_deployment_entry import (
                        verify_recovered_deployment_entry,
                    )

                    result = verify_recovered_deployment_entry(native, registry, args, entry)
                elif registry_recovery_stop:
                    from backend.app.management.registry_recovery_deployment_stop import (
                        stop_recovered_deployment,
                    )

                    result = stop_recovered_deployment(native, registry, args, entry)
                elif registry_recovery_refresh:
                    result = refresh_registry_recovery_observation(native, registry, args, entry)
                elif registry_recovery_observer:
                    result = observe_registry_recovery(native, registry, args, entry)
                elif admitting_entry:
                    result = admit_registry_recovery_entry(native, registry, args)
                elif registry_recovery_entry:
                    result = prepare_registry_recovery_entry(native, registry, args)
                else:
                    result = place_recovered_registry(native, registry, args)
            print(json.dumps(result, sort_keys=True))
            if registry_recovery_review and result['status'] == DISPATCH_REVIEW_BLOCKED:
                return 3
        elif host_recovery_authorization:
            _, runtime_hosts = entry['verify_runtime'](args.root, args.sha256)
            from backend.app.infrastructure.environment_host_release import authorize_host_recovery

            print(json.dumps(authorize_host_recovery(args, entry, runtime_hosts), sort_keys=True))
        elif host_recovery_control:
            entry['verify_runtime'](args.root, args.sha256)
            from backend.app.infrastructure.environment_host_hold import (
                enter_host_recovery,
                observe_host_recovery,
            )

            action = (
                enter_host_recovery
                if args.action == 'enter-host-recovery-hold'
                else observe_host_recovery
            )
            print(json.dumps(action(args), sort_keys=True))
        elif registry_dispatch:
            entry['verify_runtime'](args.root, args.sha256)
            from backend.app.infrastructure.environment_lock import NativeEnvironmentFiles
            from backend.app.management.registry_dispatch import pause_dispatch
            from backend.app.management.registry_installation import load_installation

            registry = load_installation(
                args.anchor, args.anchor_sha256, args.sha256, installer=True
            )
            if args.action == 'pause-registry-dispatch':
                result = pause_dispatch(
                    NativeEnvironmentFiles(args.root), registry, args.registry_recovery_id
                )
            else:
                from backend.app.management.registry_recovery_dispatch_open import (
                    observe_active_registry_dispatch,
                )

                result = observe_active_registry_dispatch(
                    registry, args.registry_recovery_id, args.sha256
                )
            print(json.dumps(result, sort_keys=True))
        elif recovery_preparation:
            _, runtime_hosts = entry['verify_runtime'](args.root, args.sha256)
            from backend.app.infrastructure.environment_recovery_installation import (
                prepare_recovery_replica,
            )

            print(json.dumps(prepare_recovery_replica(args, entry, runtime_hosts), sort_keys=True))
        elif generation_preparation:
            _, runtime_hosts = entry['verify_runtime'](args.root, args.sha256)
            from backend.app.infrastructure.environment_restore_generation import (
                prepare_restore_generation,
            )

            print(
                json.dumps(prepare_restore_generation(args, entry, runtime_hosts), sort_keys=True)
            )
        elif recovery_verification:
            from backend.app.infrastructure.environment_recovery_verify import (
                verify_recovery_replica,
            )

            entry['verify_runtime'](args.root, args.sha256)
            print(json.dumps(verify_recovery_replica(args, entry), sort_keys=True))
        elif compatibility_recording:
            from backend.app.infrastructure.environment_release_compatibility import (
                record_compatibility,
            )

            entry['verify_runtime'](args.root, args.sha256)
            print(json.dumps(record_compatibility(args, entry), sort_keys=True))
        elif deployment_preparation:
            from backend.app.infrastructure.environment_release_deployment import (
                describe_restore_deployment,
                prepare_deployment,
            )

            entry['verify_runtime'](args.root, args.sha256)
            action = (
                describe_restore_deployment
                if args.action == 'describe-restore-deployment'
                else prepare_deployment
            )
            print(json.dumps(action(args, entry), sort_keys=True))
        elif deployment_verification:
            from backend.app.infrastructure.environment_release_verify import (
                verify_release_deployment,
            )

            entry['verify_runtime'](args.root, args.sha256)
            print(json.dumps(verify_release_deployment(args, entry), sort_keys=True))
        elif release_gateway_verification:
            from backend.app.infrastructure.environment_release_gateway_check import observe_gateway

            entry['verify_runtime'](args.root, args.sha256)
            print(json.dumps(observe_gateway(args, entry), sort_keys=True))
        elif prior_result_export:
            from backend.app.management.prior_result_export import export_prior_results

            entry['verify_runtime'](args.root, args.sha256)
            print(json.dumps(export_prior_results(args, entry), sort_keys=True))
        elif backup_export:
            from backend.app.management.recovery_export import export_management_backups

            entry['verify_runtime'](args.root, args.sha256)
            print(json.dumps(export_management_backups(args), sort_keys=True))
        elif host_action:
            entry['verify_runtime'](args.root, args.sha256)
            from backend.app.management.operation_contract import (
                INVALID,
                installed_record,
                load_catalog,
            )
            from backend.app.management.registry_installation import load_installation

            registry = load_installation(
                args.anchor, args.anchor_sha256, args.sha256, installer=True
            )
            from backend.app.management.registry_dispatch import host_dispatch

            with ExitStack() as resources:
                if not args.action.startswith('observe-'):
                    resources.enter_context(host_dispatch(registry))
                catalog = load_catalog(args.catalog, args.catalog_sha256, registry)
                if attach_observer:
                    from backend.app.management.attachment_observation import capture

                    result = capture(catalog, args.candidate_ref, args, entry)
                elif candidate_validation:
                    from backend.app.management.release_validation import (
                        prepare_candidate_validation,
                    )

                    result = prepare_candidate_validation(
                        catalog, registry, args, entry, Path(__file__)
                    )
                elif archive:
                    from backend.app.management.environment_archive import archive_environment

                    result = archive_environment(catalog, registry, args, entry, Path(__file__))
                elif initial_build:
                    from backend.app.management.release_staging import prepare_release_build

                    result = prepare_release_build(catalog, registry, args, entry, Path(__file__))
                elif final_build:
                    from backend.app.management.release_finalization import prepare_final_build

                    result = prepare_final_build(catalog, registry, args, entry, Path(__file__))
                elif publication:
                    from backend.app.management.release_publication import seal_release

                    result = seal_release(catalog, registry, args, entry, Path(__file__))
                elif release_maintenance:
                    from backend.app.management.release_execution import enter_release_maintenance

                    result = enter_release_maintenance(
                        catalog, registry, args, entry, Path(__file__)
                    )
                elif release_retirement:
                    from backend.app.management.release_retirement import retire_managed_release

                    result = retire_managed_release(catalog, registry, args, entry, Path(__file__))
                elif restore_maintenance:
                    from backend.app.management.restore_execution import enter_managed_restore

                    result = enter_managed_restore(catalog, registry, args, Path(__file__))
                elif restore_retirement:
                    from backend.app.management.restore_retirement import retire_managed_restore

                    result = retire_managed_restore(catalog, registry, args, Path(__file__))
                elif managed_restore_selection:
                    from backend.app.management.restore_selection import select_managed_restore

                    result = select_managed_restore(catalog, registry, args, entry, Path(__file__))
                elif managed_release_selection:
                    from backend.app.management.release_selection import select_managed_release

                    result = select_managed_release(catalog, registry, args, entry, Path(__file__))
                elif managed_release_start:
                    from backend.app.management.release_runtime import start_managed_release

                    result = start_managed_release(catalog, registry, args, entry, Path(__file__))
                elif managed_restore_start:
                    from backend.app.management.restore_runtime import start_managed_restore

                    result = start_managed_restore(catalog, registry, args, entry, Path(__file__))
                elif managed_backup_capture:
                    from backend.app.management.backup_capture import capture_managed_backup

                    result = capture_managed_backup(catalog, registry, args, Path(__file__))
                elif managed_backup_completion:
                    from backend.app.management.backup_completion import (
                        LOCAL_STATUS,
                        complete_managed_backup,
                    )

                    result = complete_managed_backup(catalog, registry, args, Path(__file__))
                elif environment_control_observer:
                    from backend.app.management.release_maintenance_view import (
                        capture_environment_control,
                    )

                    result = capture_environment_control(catalog, args)
                elif release_maintenance_observer:
                    from backend.app.management.release_maintenance_view import capture_maintenance

                    result = capture_maintenance(catalog, args, entry)
                elif restore_source_observer:
                    from backend.app.management.restore_observation import capture_restore_source

                    result = capture_restore_source(catalog, args, entry)
                elif release_source_observer:
                    from backend.app.management.release_observation import capture_release_source

                    result = capture_release_source(catalog, args, entry)
                elif runtime_observer:
                    if args.recovered_observation_id is None:
                        from backend.app.management.runtime_observation import capture_runtime

                        result = capture_runtime(catalog, args, entry)
                    else:
                        from backend.app.management.registry_recovered_runtime import (
                            capture_recovered_runtime,
                        )

                        result = capture_recovered_runtime(catalog, registry, args, entry)
                elif normal_runtime_start:
                    from backend.app.management.runtime_start import start_runtime

                    result = start_runtime(catalog, args, entry, registry, Path(__file__))
                elif runtime_cancellation:
                    from backend.app.management.runtime_cancel import cancel_runtime

                    result = cancel_runtime(catalog, args, entry, registry, Path(__file__))
                elif normal_runtime_stop:
                    from backend.app.management.runtime_stop import stop_runtime

                    result = stop_runtime(catalog, args, entry)
                elif gateway:
                    from backend.app.management.management_gateway import install_gateway
                    from backend.app.management.web_installation import load_web

                    web = load_web(args.web, args.web_sha256, catalog, registry)
                    result = install_gateway(web, registry, args)
                else:
                    from backend.app.management.delivery_evidence import capture_delivery

                    result = capture_delivery(
                        catalog, installed_record(args.request, code=INVALID), args
                    )
                print(json.dumps(result, sort_keys=True))
                if managed_backup_completion and result['status'] == LOCAL_STATUS:
                    return 3
        elif admission:
            manifest, _ = entry['verify_runtime'](args.root, args.sha256)
            executable = args.root / manifest['python']['executable_ref']
            current = Path(sys.executable)
            if current != executable:
                entry['demand'](
                    current.resolve(strict=True) == Path('/usr/bin/python3').resolve(strict=True),
                    'Untrusted management callback bootstrap',
                )
                environment = entry['minimum_environment'](args.home, args.temporary)
                command = [str(executable), *entry['FLAGS'], str(Path(__file__)), *sys.argv[1:]]
                os.chdir(args.temporary)
                os.execve(str(executable), command, environment)
            result = target(args, entry)
            sys.stdout.buffer.write(entry['canonical'](result))
        elif args.action.startswith('_'):
            result = target(args, entry)
            if serving:
                return result
            print(json.dumps(result, sort_keys=True))
            if (maintenance or observe_open) and result['status'] == 'PENDING_RECONCILIATION':
                return 3
            if (
                args.require_release_evidence
                and result['verification_readiness']['state'] != 'REQUIRED_EVIDENCE_RECORDED'
            ):
                return 2
        else:
            manifest, _ = entry['verify_runtime'](args.root, args.sha256)
            executable = str(args.root / manifest['python']['executable_ref'])
            command = [
                executable,
                *entry['FLAGS'],
                str(Path(__file__)),
                '_' + args.action,
                *sys.argv[2:],
            ]
            environment = entry['minimum_environment'](args.home, args.temporary)
            if serving:
                os.chdir(args.temporary)
                os.execve(executable, command, environment)
            receipt = subprocess.run(command, cwd=args.temporary, env=environment, check=False)
            return receipt.returncode if receipt.returncode in (0, 2, 3) else 3
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        ImportError,
        TypeError,
        subprocess.SubprocessError,
    ) as error:
        failure = {
            'workspace': 'MANAGEMENT_WORKSPACE_UNVERIFIED',
            'workspace-binding': 'MANAGEMENT_WORKSPACE_UNVERIFIED',
            'archive-environment': 'MANAGEMENT_ARCHIVE_UNVERIFIED',
            'archive-subject': 'MANAGEMENT_ARCHIVE_UNVERIFIED',
            'complete-archive': 'MANAGEMENT_ARCHIVE_UNVERIFIED',
            'release': 'RELEASE_ARTIFACT_UNVERIFIED',
            'candidate': 'RELEASE_CANDIDATE_UNVERIFIED',
            'inspect-release-build': 'RELEASE_PUBLICATION_UNVERIFIED',
            'seal-release': 'RELEASE_PUBLICATION_UNVERIFIED',
            'prepare-release-build': 'RELEASE_BUILD_UNVERIFIED',
            'release-build-source': 'RELEASE_BUILD_UNVERIFIED',
            'prepare-release-final-build': 'RELEASE_FINALIZATION_UNVERIFIED',
            'prepare-candidate-validation': 'CANDIDATE_VALIDATION_UNVERIFIED',
            'prepare-recovery-replica': 'RECOVERY_REPLICA_UNVERIFIED',
            'prepare-restore-generation': 'RESTORE_GENERATION_UNVERIFIED',
            'verify-recovery-replica': 'RECOVERY_VERIFICATION_UNVERIFIED',
            'export-management-backups': 'MANAGEMENT_BACKUP_EXPORT_UNVERIFIED',
            'export-prior-command-results': 'PRIOR_COMMAND_EXPORT_UNVERIFIED',
            'observe-attach': 'MANAGEMENT_RESOURCE_UNVERIFIED',
            'observe-delivery': 'MANAGEMENT_RESOURCE_UNVERIFIED',
            'observe-runtime': 'MANAGEMENT_RESOURCE_UNVERIFIED',
            'observe-restore-source': 'MANAGEMENT_RESOURCE_UNVERIFIED',
            'enter-managed-restore': 'MANAGED_RESTORE_MAINTENANCE_UNVERIFIED',
            'retire-managed-restore': 'MANAGED_RESTORE_RETIREMENT_UNVERIFIED',
            'select-managed-restore': 'MANAGED_RESTORE_SELECTION_UNVERIFIED',
            'start-managed-restore': 'MANAGED_RESTORE_OPEN_UNVERIFIED',
            'snapshot-registry': 'MANAGEMENT_REGISTRY_SNAPSHOT_UNVERIFIED',
            'verify-registry-snapshot': 'MANAGEMENT_REGISTRY_SNAPSHOT_UNVERIFIED',
            'pause-registry-dispatch': 'MANAGEMENT_DISPATCH_HOLD_UNVERIFIED',
            'observe-registry-dispatch': 'MANAGEMENT_DISPATCH_HOLD_UNVERIFIED',
            'prepare-registry-recovery': 'MANAGEMENT_REGISTRY_RECOVERY_UNVERIFIED',
            'verify-registry-recovery': 'MANAGEMENT_REGISTRY_RECOVERY_UNVERIFIED',
            'place-registry-recovery': 'MANAGEMENT_REGISTRY_INSTALLATION_UNVERIFIED',
            'ready-registry-recovery': 'MANAGEMENT_REGISTRY_READINESS_UNVERIFIED',
            'inventory-registry-recovery': 'MANAGEMENT_REGISTRY_RECOVERY_INVENTORY_UNVERIFIED',
            'settle-registry-recovery-disposition': 'MANAGEMENT_REGISTRY_RECOVERY_DISPOSITION_UNVERIFIED',
            'inspect-registry-recovery-deployment': (
                'MANAGEMENT_REGISTRY_RECOVERY_OPENING_UNVERIFIED'
            ),
            'settle-registry-recovery-deployment': (
                'MANAGEMENT_REGISTRY_RECOVERY_DEPLOYMENT_SETTLEMENT_UNVERIFIED'
            ),
            'observe-registry-recovery': 'MANAGEMENT_REGISTRY_RECOVERY_HOST_UNVERIFIED',
            'refresh-registry-recovery-observation': 'MANAGEMENT_REGISTRY_RECOVERY_HOST_UNVERIFIED',
            'stop-registry-recovery-deployment': 'MANAGEMENT_REGISTRY_RECOVERY_DEPLOYMENT_STOP_UNVERIFIED',
            'verify-registry-recovery-deployment-entry': (
                'MANAGEMENT_REGISTRY_RECOVERY_DEPLOYMENT_ENTRY_UNVERIFIED'
            ),
            'authorize-registry-recovery-deployment-adoption': (
                'MANAGEMENT_REGISTRY_RECOVERY_DEPLOYMENT_ADOPTION_UNVERIFIED'
            ),
            'check-registry-recovery-dispatch': 'MANAGEMENT_REGISTRY_RECOVERY_DISPATCH_UNVERIFIED',
            'inspect-registry-recovery-dispatch': 'MANAGEMENT_REGISTRY_RECOVERY_DISPATCH_UNVERIFIED',
            'open-registry-recovery-dispatch': 'MANAGEMENT_REGISTRY_RECOVERY_DISPATCH_OPEN_UNVERIFIED',
            'select-registry-recovery': 'MANAGEMENT_REGISTRY_RECOVERY_SELECTION_UNVERIFIED',
            'prepare-registry-recovery-entry': 'MANAGEMENT_REGISTRY_RECOVERY_ENTRY_UNVERIFIED',
            'admit-registry-recovery-entry': 'MANAGEMENT_REGISTRY_RECOVERY_ENTRY_ADMISSION_UNVERIFIED',
            'enter-host-recovery-hold': 'HOST_RECOVERY_CONTROL_UNVERIFIED',
            'observe-host-recovery-hold': 'HOST_RECOVERY_CONTROL_UNVERIFIED',
            'authorize-host-recovery-deployment': 'HOST_RECOVERY_AUTHORIZATION_UNVERIFIED',
            'stop-runtime': 'MANAGEMENT_STOP_EFFECT_UNVERIFIED',
            'start-runtime': 'MANAGEMENT_START_EFFECT_UNVERIFIED',
            'cancel-runtime': 'MANAGEMENT_CANCEL_EFFECT_UNVERIFIED',
            'gateway': 'MANAGEMENT_GATEWAY_NOT_ADMITTED',
            'capture-database': 'DATABASE_CAPTURE_UNVERIFIED',
            'check-backup-coverage': 'BACKUP_COVERAGE_UNVERIFIED',
            'check-recovery-chain': 'RECOVERY_CHAIN_UNVERIFIED',
            'check-release-preflight': 'RELEASE_PREFLIGHT_UNVERIFIED',
            'check-restore-preflight': 'RESTORE_PREFLIGHT_UNVERIFIED',
            'prepare-restore-data': 'RESTORE_DATA_PREPARATION_UNVERIFIED',
            'lookup-restore-result': 'RESTORE_RESULT_UNVERIFIED',
            'check-restore-readiness': 'RESTORE_READINESS_UNVERIFIED',
            'select-release-deployment': 'RELEASE_SWITCH_UNVERIFIED',
            'observe-release-open': 'RELEASE_OPEN_UNVERIFIED',
            'record-release-compatibility': 'RELEASE_COMPATIBILITY_UNVERIFIED',
            'prepare-release-deployment': 'RELEASE_DEPLOYMENT_UNVERIFIED',
            'describe-restore-deployment': 'RELEASE_DEPLOYMENT_UNVERIFIED',
            'verify-release-deployment': 'RELEASE_VERIFICATION_UNVERIFIED',
            'verify-release-gateway': 'RELEASE_GATEWAY_VERIFICATION_UNVERIFIED',
            'seal-backup-package': 'BACKUP_PACKAGE_UNVERIFIED',
            'verify-backup-package': 'BACKUP_PACKAGE_UNVERIFIED',
            'lookup-backup-result': 'BACKUP_PACKAGE_UNVERIFIED',
            'publish-backup-snapshot': 'RESTIC_PUBLICATION_UNVERIFIED',
            'retrieve-backup-snapshot': 'RESTIC_SNAPSHOT_UNVERIFIED',
            'publish-offhost-backup-snapshot': 'OFFHOST_BACKUP_UNVERIFIED',
            'verify-offhost-backup-snapshot': 'OFFHOST_BACKUP_UNVERIFIED',
            'materialize-offhost-backup-package': 'OFFHOST_BACKUP_UNVERIFIED',
            'rehearse-backup-package': 'BACKUP_REHEARSAL_UNVERIFIED',
            'restore-database': 'DATABASE_RESTORE_UNVERIFIED',
            'seal-result-index': 'ORIGINAL_RESULT_INDEX_UNVERIFIED',
            'lookup-result-index': 'ORIGINAL_RESULT_INDEX_UNVERIFIED',
            'environment-maintenance': 'MAINTENANCE_CONTROL_UNVERIFIED',
        }.get(args.action.removeprefix('_'), 'MANAGEMENT_REGISTRY_NOT_ADMITTED')
        reason = getattr(error, 'code', failure)
        print(json.dumps({'status': 'BLOCKED', 'reason_code': reason}), file=sys.stderr)
        return 3 if getattr(error, 'uncertain', False) else 2


if __name__ == '__main__':
    raise SystemExit(main())
