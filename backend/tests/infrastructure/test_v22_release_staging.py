"""Regression cases for the initial fixed release build and its source binding."""

import os
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.infrastructure.environment_files import EnvironmentFailure, canonical, digest
from backend.app.management import release_source as source
from backend.app.management import release_staging as staging


@pytest.fixture
def staged_build(tmp_path, monkeypatch):
    stage = tmp_path / 'staging'
    stage.mkdir()
    inputs = {
        'release_id': str(uuid4()),
        'delivery_operation_id': str(uuid4()),
        'schema_ref': {'path': '/schema', 'sha256': 'c' * 64},
        'staging_root': {'path': str(stage), 'identity': {}},
        'publication_root': {'path': str(tmp_path / 'publication'), 'identity': {}},
    }
    args = SimpleNamespace(release_build_policy_sha256='a' * 64)
    scope = SimpleNamespace(scope={'registry_generation': str(uuid4())})
    seen = SimpleNamespace(staged=0, published=0, fail_sync=False, fail_stage=False)

    def write_stage(_catalog, target, _roots, _plan, _resources, request, _entry, _source):
        seen.staged += 1
        target.mkdir()
        (target / 'test-build').write_text(request.release_build_policy_sha256)
        if seen.fail_stage:
            raise EnvironmentFailure(staging.UNVERIFIED)

    def validate_stage(_catalog, path, _plan, _resources, request, _entry, _source):
        marker = path / 'test-build'
        if marker.read_text() != request.release_build_policy_sha256:
            raise EnvironmentFailure(staging.CONFLICT)
        package = stage / inputs['release_id'] / 'release'
        return 'b' * 64, 'd' * 64, {'path': str(package), 'identity': {}}

    def publish(source, target):
        seen.published += 1
        source.rename(target)

    def sync(_directory):
        if seen.fail_sync:
            seen.fail_sync = False
            raise OSError('directory sync interrupted after publication')

    operations = SimpleNamespace(
        geteuid=lambda: 0,
        path=os.path,
        fsync=sync,
    )
    roots = {
        'staging_root': stage,
        'publication_root': tmp_path / 'publication',
    }
    monkeypatch.setattr(staging, 'os', operations)
    monkeypatch.setattr(staging, 'load_build_plan', lambda *_: inputs)
    monkeypatch.setattr(staging, 'check_disjoint_roots', lambda *_: roots)
    monkeypatch.setattr(staging, 'observe', lambda *_: [])
    monkeypatch.setattr(staging, 'application_sources', lambda *_: {})
    monkeypatch.setattr(staging, 'checked_root', lambda directory, _: nullcontext(directory))
    monkeypatch.setattr(staging, 'protected_directory', nullcontext)
    monkeypatch.setattr(staging, 'publish_directory', publish)
    monkeypatch.setattr(staging, 'write_stage', write_stage)
    monkeypatch.setattr(staging, 'validate_stage', validate_stage)

    def prepare():
        return staging.prepare_release_build(scope, None, args, None, None)

    return SimpleNamespace(
        prepare=prepare,
        args=args,
        seen=seen,
        container=stage,
        target=stage / inputs['release_id'],
    )


def test_original_build_returns_the_same_candidate_and_policy(staged_build):
    first = staged_build.prepare()
    assert staged_build.prepare() == first
    assert first['candidate_sha256'] == digest(canonical(first['candidate']))
    assert first['publication_policy_sha256'] == digest(canonical(first['publication_policy']))
    assert first['publication_policy']['candidate_sha256'] == first['candidate_sha256']
    assert Path(first['candidate']['manifest_ref']['path']).name == 'release-manifest.v1.json'
    assert staged_build.seen.staged == staged_build.seen.published == 1
    assert list(staged_build.container.iterdir()) == [staged_build.target]


def test_prepublication_error_clears_private_assembly(staged_build):
    staged_build.seen.fail_stage = True
    with pytest.raises(EnvironmentFailure, match=staging.UNVERIFIED) as caught:
        staged_build.prepare()
    assert not caught.value.uncertain
    assert not list(staged_build.container.iterdir())
    assert staged_build.seen.published == 0


def test_postpublication_sync_failure_keeps_original_for_readback(staged_build):
    staged_build.seen.fail_sync = True
    with pytest.raises(EnvironmentFailure, match=staging.UNVERIFIED) as caught:
        staged_build.prepare()
    assert caught.value.uncertain
    inode = staged_build.target.stat().st_ino
    assert staged_build.prepare()['status'] == 'RELEASE_BUILD_PREPARED'
    assert staged_build.target.stat().st_ino == inode
    assert staged_build.seen.published == 1


def test_another_plan_cannot_adopt_or_replace_the_same_release_id(staged_build):
    staged_build.prepare()
    staged_build.args.release_build_policy_sha256 = 'e' * 64
    with pytest.raises(EnvironmentFailure, match=staging.CONFLICT) as caught:
        staged_build.prepare()
    assert not caught.value.uncertain
    assert (staged_build.target / 'test-build').read_text() == 'a' * 64
    assert staged_build.seen.published == 1


@pytest.mark.parametrize('field', ('repository_ref', 'source_commit', 'source_tree'))
def test_build_source_rejects_a_different_original_delivery(field, monkeypatch):
    plan = {
        'delivery_operation_id': str(uuid4()),
        'repository_ref': str(uuid4()),
        'source_commit': 'a' * 40,
        'source_tree': 'b' * 40,
    }
    stored = {
        'repository_ref': plan['repository_ref'],
        'commit': plan['source_commit'],
        'tree': plan['source_tree'],
    }
    monkeypatch.setattr(staging, 'integration_delivery', lambda *_: (stored, []))
    monkeypatch.setattr(staging, 'admitted_resources', lambda *_: {})
    assert staging.observe_build_source(None, None, plan, 'c' * 64)['source_tree'] == 'b' * 40
    with pytest.raises(EnvironmentFailure, match=staging.INVALID):
        staging.observe_build_source(None, None, {**plan, field: 'wrong'}, 'c' * 64)


@pytest.mark.parametrize('field', ('source_commit', 'source_tree', 'program_sha256', 'pin'))
def test_application_inputs_must_match_the_original_source_manifest(field, tmp_path, monkeypatch):
    name = 'shared/release.txt'
    monkeypatch.setattr(source, 'REQUIRED', {name})
    row = {'path': name, 'mode': '100755', 'bytes': 1, 'sha256': '3' * 64, 'oid': '4' * 40}
    source_record = {
        'format_version': 1,
        'object_format': 'sha1',
        'commit': '1' * 40,
        'tree': '2' * 40,
        'files': [row],
    }
    raw = canonical(source_record)
    pin = digest(raw)
    plan = {
        'source_manifest_ref': {'path': str(tmp_path / source.MANIFEST), 'sha256': pin},
        'source_commit': source_record['commit'],
        'source_tree': source_record['tree'],
        'program_sha256': source.program_sha256([row]),
    }
    monkeypatch.setattr(staging, 'path_reference', lambda ref: (Path(ref['path']), ref['sha256']))
    monkeypatch.setattr(staging, 'snapshot_file', lambda *_args, **_kwargs: (pin, raw))
    assert staging.application_sources(plan) == {name: (0o555, 1, '3' * 64)}
    if field == 'pin':
        plan['source_manifest_ref']['sha256'] = '5' * 64
    else:
        plan[field] = '5' * len(plan[field])
    with pytest.raises(EnvironmentFailure, match=staging.UNVERIFIED):
        staging.application_sources(plan)
