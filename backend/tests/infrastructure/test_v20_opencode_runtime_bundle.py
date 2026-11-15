"""Frozen OpenCode bundle references against a temporary NTFS directory."""

import hashlib
import json
from time import monotonic

import pytest

from backend.app.infrastructure import opencode_runtime_bundle as bundle
from backend.app.infrastructure.windows_config_source import ConfigReadError
from backend.app.infrastructure.windows_private_package import PackageSecurityError
from backend.app.infrastructure.windows_task_runtime_bundle import (
    TaskRuntimeBundlePublication,
    TaskRuntimeFilesError,
)
from backend.tests.infrastructure.test_v20_windows_controller_token import (
    controller,
    ordinary_controller,
)
from backend.tests.infrastructure.test_v20_windows_task_directories import original_paths
from backend.tests.requirements.test_v15_foundation import tmp_path


@pytest.fixture
def runtime_bundle(tmp_path):
    def prepare(damage=None):
        root = tmp_path / 'kit'
        dependency = {bundle.PLUGIN_NAME: bundle.PLUGIN_VERSION}
        package = {'dependencies': dependency}
        installed = {'name': bundle.PLUGIN_NAME, 'version': bundle.PLUGIN_VERSION}
        packages = {'': package, bundle.PLUGIN_ROOT: {'version': bundle.PLUGIN_VERSION}}
        config = dict(bundle.ISOLATION_SETTINGS)
        if damage == 'lsp':
            config['lsp'] = {}
        elif damage == 'plugin':
            installed['version'] = '1.19.4'
        elif damage == 'lock':
            packages[''] = {}
        elif damage == 'missing-dependency':
            packages['node_modules/dependency'] = {'version': '1.0.0'}
        elif damage == 'optional-dependency':
            packages['node_modules/dependency'] = {'version': '1.0.0', 'optional': True}

        content = {
            '.gitignore': b'node_modules\n',
            'opencode.json': json.dumps(config).encode(),
            'package.json': json.dumps(package).encode(),
            'package-lock.json': json.dumps({'packages': packages}).encode(),
            bundle.PLUGIN_MANIFEST: json.dumps(installed).encode(),
            bundle.PLUGIN_ROOT + '/index.js': b'export {}\n',
        }
        manifest = tmp_path / 'bundle.json'
        members = []
        for name, raw in content.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            members.append(
                {'path': name, 'byte_count': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
            )
        if damage == 'alias':
            members.append({**members[-1], 'path': members[-1]['path'].upper()})
        raw = json.dumps(
            {'schema_version': 1, 'configuration_policy': 'OC20-CONFIG-1', 'members': members}
        ).encode()
        manifest.write_bytes(raw)
        return (
            bundle.OpenCodeRuntimeBundle(manifest, root),
            bundle.REF_PREFIX + hashlib.sha256(raw).hexdigest(),
        )

    return prepare


def check(source, reference, cancelled=lambda: False):
    return bundle.verify_opencode_runtime_bundle(
        source, reference, deadline=monotonic() + 10, cancelled=cancelled
    )


def test_verify_only_original_file_inventory(runtime_bundle):
    source, reference = runtime_bundle('optional-dependency')
    assert check(source, reference) == 6
    with pytest.raises(bundle.OpenCodeRuntimeBundleError, match='DIGEST_DIFFERS'):
        check(source, reference[:-1])
    with pytest.raises(bundle.OpenCodeRuntimeBundleError, match='INTERRUPTED'):
        check(source, reference, cancelled=lambda: True)
    extra = source.root / 'unexpected'
    extra.mkdir()
    with pytest.raises(bundle.OpenCodeRuntimeBundleError, match='TREE_DIFFERS'):
        check(source, reference)
    extra.rmdir()
    (source.root / '.gitignore').write_bytes(b'node_modulex\n')
    with pytest.raises(bundle.OpenCodeRuntimeBundleError, match='MEMBER_DIFFERS'):
        check(source, reference)


@pytest.mark.parametrize(
    ('damage', 'failure'),
    [
        ('lsp', 'CONFIGURATION_DIFFERS'),
        ('plugin', 'REQUIRED_PLUGIN_DIFFERS'),
        ('lock', 'DEPENDENCY_LOCK_DIFFERS'),
        ('missing-dependency', 'LOCKED_PACKAGE_MISSING'),
        ('alias', 'CONTENT_PATH_CASE_ALIAS'),
    ],
)
def test_reject_invalid_manifest_or_bound_configuration(runtime_bundle, damage, failure):
    with pytest.raises((bundle.OpenCodeRuntimeBundleError, ValueError), match=failure):
        check(*runtime_bundle(damage))


def test_runtime_bundle_keeps_original_file_ids_across_copy_pass(runtime_bundle):
    source, reference = runtime_bundle()
    with bundle.hold_opencode_runtime_bundle(
        source, reference, deadline=monotonic() + 10, cancelled=lambda: False
    ) as held:
        file = source.root / 'opencode.json'
        saved = source.root / 'original'
        file.rename(saved)
        file.write_bytes(saved.read_bytes())
        saved.unlink()
        with pytest.raises(ConfigReadError, match='ORIGINAL_FILE_DIFFERS'):
            held.visit(lambda *_: None)


def test_original_runtime_role_rechecks_native_acl_and_exact_identity(
    runtime_bundle, original_paths
):
    owner, _ = original_paths
    owner.allocate(cancelled=lambda: False)
    source, reference = runtime_bundle()
    publication = TaskRuntimeBundlePublication(owner, source, reference)
    try:
        evidence = publication.publish(deadline=monotonic() + 15, cancelled=lambda: False)
        assert evidence == publication.verify(lambda: None)
        assert evidence.member_count == 6
        assert (
            publication.configuration_path.read_bytes()
            == (source.root / 'opencode.json').read_bytes()
        )
        with pytest.raises(TaskRuntimeFilesError, match='ALREADY_DISPATCHED'):
            publication.publish(deadline=monotonic() + 15, cancelled=lambda: False)
        path = publication.configuration_path
        replaced = path.with_suffix('.original')
        path.rename(replaced)
        path.write_bytes(replaced.read_bytes())
        replaced.unlink()
        with pytest.raises(ConfigReadError, match='ORIGINAL_FILE_DIFFERS'):
            publication.verify(lambda: None)
    finally:
        publication.close()


def test_interrupted_runtime_publication_leaves_partial_role(runtime_bundle, original_paths):
    owner, _ = original_paths
    owner.allocate(cancelled=lambda: False)
    source, reference = runtime_bundle()
    publication = TaskRuntimeBundlePublication(owner, source, reference)
    try:
        with pytest.raises(
            (bundle.OpenCodeRuntimeBundleError, PackageSecurityError), match='INTERRUPTED'
        ):
            publication.publish(
                deadline=monotonic() + 15, cancelled=lambda: any((owner.root / 'runtime').iterdir())
            )
        assert any((owner.root / 'runtime').iterdir())
        with pytest.raises(TaskRuntimeFilesError, match='UNVERIFIED'):
            publication.verify(lambda: None)
        with pytest.raises(TaskRuntimeFilesError, match='ALREADY_DISPATCHED'):
            publication.publish(deadline=monotonic() + 15, cancelled=lambda: False)
    finally:
        publication.close()


def test_instance_runtime_environment_reuses_private_roles(
    runtime_bundle, original_paths, monkeypatch
):
    from backend.app.infrastructure import windows_task_runtime_environment as env
    from backend.app.infrastructure.opencode_managed_config import _source_is_absent

    owner, _ = original_paths
    owner.allocate(cancelled=lambda: False)
    source, reference = runtime_bundle()
    managed = source.root.parent / 'managed'
    managed.mkdir()
    monkeypatch.setattr(env, 'opencode_managed_source_clear', lambda: _source_is_absent(managed))
    monkeypatch.setenv('OPENCODE_CONFIG', 'outside-profile')
    monkeypatch.setenv('OPENCODE_CONFIG_CONTENT', 'untrusted')
    monkeypatch.setenv('OPENCODE_TEST_HOME', 'outside-home')
    monkeypatch.setenv('ARK_API_KEY', 'fixture')
    runtime = TaskRuntimeBundlePublication(owner, source, reference)
    environment = env.TaskRuntimeEnvironment(owner, runtime)

    def checkpoint():
        owner._require_open(lambda: False)

    try:
        runtime.publish(deadline=monotonic() + 15, cancelled=lambda: False)
        evidence = environment.prepare(checkpoint)
        values = environment.values(checkpoint)
        assert evidence == environment.verify(checkpoint)
        assert values['OPENCODE_CONFIG'] == str(runtime.configuration_path)
        assert values['XDG_CONFIG_HOME'] == str(owner.root / 'config')
        assert values['USERPROFILE'] == str(owner.root / 'scratch' / 'home')
        assert values['OPENCODE_DISABLE_PROJECT_CONFIG'] == 'true'
        assert values['OPENCODE_ENABLE_QUESTION_TOOL'] == 'true'
        assert not {'OPENCODE_CONFIG_CONTENT', 'OPENCODE_TEST_HOME', 'ARK_API_KEY'} & values.keys()
        values['OPENCODE_CONFIG'] = 'changed locally'
        assert environment.values(checkpoint)['OPENCODE_CONFIG'] == str(runtime.configuration_path)
        (managed / 'opencode').mkdir()
        with pytest.raises(TaskRuntimeFilesError, match='SYSTEM_CONFIG_UNVERIFIED'):
            environment.verify(checkpoint)
        (managed / 'opencode').rmdir()
        (owner.root / 'scratch' / 'home' / '.opencode').mkdir()
        with pytest.raises(TaskRuntimeFilesError, match='ENVIRONMENT_TREE_DIFFERS'):
            environment.verify(checkpoint)
        with pytest.raises(TaskRuntimeFilesError, match='ALREADY_DISPATCHED'):
            environment.prepare(checkpoint)
    finally:
        environment.close()
        runtime.close()


def test_runtime_environment_never_adopts_config_role(runtime_bundle, original_paths, monkeypatch):
    from backend.app.infrastructure import windows_task_runtime_environment as env

    owner, _ = original_paths
    owner.allocate(cancelled=lambda: False)
    source, reference = runtime_bundle()
    monkeypatch.setattr(env, 'opencode_managed_source_clear', lambda: True)
    runtime = TaskRuntimeBundlePublication(owner, source, reference)
    environment = env.TaskRuntimeEnvironment(owner, runtime)
    try:
        runtime.publish(deadline=monotonic() + 15, cancelled=lambda: False)
        existing = owner.root / 'config' / 'opencode'
        existing.mkdir()
        with pytest.raises(TaskRuntimeFilesError, match='ENVIRONMENT_NOT_EMPTY'):
            environment.prepare(lambda: None)
        assert list((owner.root / 'config').iterdir()) == [existing]
        assert not list((owner.root / 'scratch').iterdir())
    finally:
        environment.close()
        runtime.close()
