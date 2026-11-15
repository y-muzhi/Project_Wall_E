"""Reconstruct the exact case definitions from a persisted Testing seal."""

from contextlib import contextmanager
from time import monotonic

from backend.app.infrastructure.check_runner_bundle import CheckResourceError
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.shared.validation import strict_json_loads

from .asset_installation import hold_compiler_sources
from .assets import sealed_pack_facts
from .pack_compile import CompileError, CompilerTarget, basis_fingerprint, compile_pack
from .pack_seal import SealRejected, original_targets
from .pack_storage import hold_sealed_pack, pack_content_ref
from .plans import _version


def compiled_definition(connection, pack):
    operation, facts = sealed_pack_facts(connection, pack)
    plan = _version(connection, pack['plan_version_id'])
    if plan is None or pack['content_ref'] != pack_content_ref(pack['id'], operation):
        raise StorageUnavailable('Original sealed pack provenance differs')
    try:
        targets = tuple(
            CompilerTarget(
                **{
                    key: tuple(value) if isinstance(value, list) else value
                    for key, value in row['target'].items()
                }
            )
            for row in facts['targets']
        )
        compiled = compile_pack(
            plan,
            targets,
            pack_id=pack['id'],
            version=pack['version'],
            basis_sha256=facts['basis_fingerprint'],
        )
    except (CompileError, RuntimeError, ValueError, TypeError, KeyError) as error:
        raise StorageUnavailable(
            'Original sealed pack definition cannot be reconstructed'
        ) from error
    check_set = connection.execute(
        'SELECT owner_module,protocol_version,items,coverage_plan FROM code_check_set_versions WHERE id=?',
        (pack['check_set_version_id'],),
    ).fetchone()
    expected = compiled.check_set.value()
    if (
        compiled.sha256 != pack['sha256']
        or compiled.plan_sha256 != facts['plan_sha256']
        or check_set is None
        or check_set['owner_module'] != 'TESTING'
        or check_set['protocol_version'] != expected['protocol_version']
        or strict_json_loads(check_set['items'], 'items') != expected['items']
        or strict_json_loads(check_set['coverage_plan'], 'coverage_plan')
        != expected['coverage_plan']
    ):
        raise StorageUnavailable('Original sealed definition differs from its fixed CheckSet')
    return operation, compiled


@contextmanager
def hold_compiled_pack_assets(connection, installation, pack, *, deadline):
    identity, compiled = compiled_definition(connection, pack)
    _, seal = sealed_pack_facts(connection, pack)
    plan = _version(connection, pack['plan_version_id'])
    try:
        targets = original_targets(installation, seal)
    except SealRejected as error:
        raise CheckResourceError('TESTING_ORIGINAL_SEALED_TARGET_UNAVAILABLE') from error
    if (
        plan is None
        or plan['status'] != 'PUBLISHED'
        or basis_fingerprint(connection, plan) != compiled.basis_sha256
        or targets != compiled.targets
    ):
        raise CheckResourceError('TESTING_ORIGINAL_SEALED_BASIS_CHANGED')

    def checkpoint():
        if monotonic() >= deadline:
            raise CheckResourceError('TESTING_PACK_INSPECTION_INTERRUPTED')

    with (
        hold_compiler_sources(
            installation, compiled.targets, deadline=deadline, cancelled=lambda: False
        ),
        hold_sealed_pack(installation, compiled, identity, checkpoint),
    ):
        checkpoint()
        yield compiled
