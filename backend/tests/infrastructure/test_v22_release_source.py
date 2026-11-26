"""Check exact Git bytes and safe materialization of a release build source."""

import os
import tarfile
from hashlib import sha1, sha256
from io import BytesIO

import pytest

from backend.app.infrastructure.content_paths import ContentPathError
from backend.app.infrastructure.environment_files import canonical
from backend.app.infrastructure.git_commit_closure import GitClosureError
from backend.app.management import release_source as source

PATH = 'shared/fixtures/build.json'
RAW = b'original git bytes\n'


def blob(raw):
    oid = sha1(f'blob {len(raw)}\0'.encode() + raw, usedforsecurity=False).hexdigest()
    return source.Blob('100644', oid, len(raw))


def archive(path, data, *, member_type=tarfile.REGTYPE):
    with tarfile.open(path, mode='w') as tar:
        item = tarfile.TarInfo(PATH)
        item.type = member_type
        item.mode = 0o644
        if member_type == tarfile.SYMTYPE:
            item.linkname = 'outside'
        else:
            item.size = len(data)
        tar.addfile(item, BytesIO(data) if item.isreg() else None)


def test_exact_shared_blob_is_materialized_twice_without_links(tmp_path):
    tar = tmp_path / 'input.tar'
    archive(tar, RAW)
    expected = blob(RAW)
    result = source.extract_inputs(tar, tmp_path / 'output', {PATH: expected}, 'sha1')
    paths = [tmp_path / 'output' / role / PATH for role in ('application', 'build')]
    assert result[0]['oid'] == expected.oid
    assert paths[0].read_bytes() == paths[1].read_bytes() == RAW
    assert paths[0].stat().st_ino != paths[1].stat().st_ino


@pytest.mark.parametrize(
    ('data', 'kind', 'reason'),
    (
        (RAW[:-2] + b'x\n', tarfile.REGTYPE, 'pinned blob'),
        (RAW, tarfile.SYMTYPE, 'Unexpected Git archive member'),
        (RAW + b'extra', tarfile.REGTYPE, 'mode or length'),
    ),
)
def test_archive_cannot_change_or_redirect_a_git_input(tmp_path, data, kind, reason):
    tar = tmp_path / 'input.tar'
    archive(tar, data, member_type=kind)
    with pytest.raises(source.SourceError, match=reason):
        source.extract_inputs(tar, tmp_path / 'output', {PATH: blob(RAW)}, 'sha1')
    assert not (tmp_path / 'output').exists()


def test_source_rejects_lfs_placeholders(tmp_path):
    tar = tmp_path / 'input.tar'
    pointer = (
        b'version https://git-lfs.github.com/spec/v1\noid sha256:' + b'1' * 64 + b'\nsize 51\n'
    )
    archive(tar, pointer)
    with pytest.raises(GitClosureError, match='CONTENT_LFS_POINTER_UNSUPPORTED'):
        source.extract_inputs(tar, tmp_path / 'output', {PATH: blob(pointer)}, 'sha1')
    assert not (tmp_path / 'output').exists()


def test_tree_case_aliases_and_missing_required_inputs_are_rejected(monkeypatch):
    item = blob(RAW)
    row = f'{item.mode} blob {item.oid} {item.size}\t'.encode()
    listing = row + PATH.encode() + b'\x00'
    with pytest.raises(source.SourceError, match='missing required'):
        source.blobs_from_tree(listing, 'sha1')
    monkeypatch.setattr(source, 'REQUIRED', {PATH})
    assert source.blobs_from_tree(listing, 'sha1') == {PATH: item}
    with pytest.raises(ContentPathError, match='CONTENT_PATH_CASE_ALIAS'):
        source.blobs_from_tree(
            listing + row + PATH.replace('build', 'Build').encode() + b'\x00', 'sha1'
        )


@pytest.fixture
def prepared_sources(tmp_path, monkeypatch):
    frontend = 'frontend/package.json'
    values = {frontend: b'{}\n', PATH: RAW}
    files = []
    for name, data in values.items():
        entry = blob(data)
        files.append(
            {
                'path': name,
                'oid': entry.oid,
                'mode': entry.mode,
                'bytes': entry.size,
                'sha256': sha256(data).hexdigest(),
            }
        )
        source.write_new(tmp_path / 'build' / name, data, 0o644)
    source.write_new(tmp_path / 'application' / PATH, RAW, 0o444)
    raw = canonical(
        {
            'format_version': 1,
            'object_format': 'sha1',
            'commit': 'a' * 40,
            'tree': 'b' * 40,
            'files': files,
        }
    )
    source.write_new(tmp_path / source.MANIFEST, raw, 0o444)
    monkeypatch.setattr(source, 'REQUIRED', set(values))
    return tmp_path, sha256(raw).hexdigest()


def test_verify_counts_fixed_inputs_when_build_outputs_are_present(prepared_sources):
    root, expected = prepared_sources
    for output in source.BUILD_OUTPUTS:
        source.write_new(root / 'build' / output / 'output.txt', b'build output', 0o644)
    found = source.verify(root, expected)
    assert found['application_files'] == 1
    assert found['build_files'] == 2
    with pytest.raises(source.SourceError, match='manifest differs'):
        source.verify(root, 'c' * 64)


def test_verify_rejects_new_inputs_even_when_original_bytes_match(prepared_sources):
    root, expected = prepared_sources
    source.write_new(root / 'build/frontend/extra.ts', b'export {}', 0o644)
    with pytest.raises(source.SourceError, match='unexpected input file'):
        source.verify(root, expected)


def test_verify_rejects_unexpected_content_at_the_export_root(prepared_sources):
    root, expected = prepared_sources
    source.write_new(root / 'unexpected.json', b'{}', 0o444)
    with pytest.raises(source.SourceError, match='unexpected entries'):
        source.verify(root, expected)


def test_verify_rejects_shared_blob_even_when_bytes_match(prepared_sources):
    root, expected = prepared_sources
    extra = root / 'build/frontend/dist'
    extra.mkdir()
    unrelated = extra / 'extra-copy'
    try:
        os.link(root / 'application' / PATH, unrelated)
    except PermissionError:
        if os.name != 'nt':
            raise
        pytest.skip('The Windows test sandbox disallows hard links in this fixture')
    with pytest.raises(source.SourceError, match='redirected or shared'):
        source.verify(root, expected)
