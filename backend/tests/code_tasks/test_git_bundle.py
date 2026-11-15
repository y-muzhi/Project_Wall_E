"""Archive preparation faults use synthetic data, never execute downloaded code."""

from dataclasses import asdict
import hashlib
from io import BytesIO
import json
from pathlib import Path
import stat
import struct
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo

import pytest

from backend.app.infrastructure import git_bundle as bundle
from backend.app.infrastructure.content_paths import ContentPathError
from backend.tests.requirements.test_v15_foundation import tmp_path


def archive_bytes(entries):
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        for name, body in entries:
            archive.writestr(name, body)
    return output.getvalue()


def pe():
    data = bytearray(134)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3C, 128)
    data[128:] = b'PE\0\0\x64\x86'
    return bytes(data)


def test_archive_namespace_and_regular_files_preflight_before_any_writes(tmp_path):
    source = archive_bytes(
        [('cmd/', b''), ('cmd/git.exe', pe()), ('empty/', b''), ('data/x.txt', b'\0\r\n')]
    )
    target = tmp_path / 'bundle'
    with ZipFile(BytesIO(source)) as archive:
        inventory, total = bundle._inventory(archive, target)
    assert total == len(pe()) + 3
    assert not target.exists()


@pytest.mark.parametrize(
    'paths',
    [
        ['../outside'],
        ['/absolute'],
        [r'C:\outside'],
        ['.git/config'],
        ['aux.txt'],
        ['Src/a', 'src/b'],
        ['a', 'a/b'],
        ['a/', 'a'],
        ['source.zip'],
        ['manifest.json'],
    ],
)
def test_zip_slip_alias_conflict_or_reserved_metadata_is_rejected_before_outputs(tmp_path, paths):
    source = archive_bytes([(path, b'' if path.endswith('/') else b'x') for path in paths])
    target = tmp_path / 'never-created'
    with ZipFile(BytesIO(source)) as archive:
        with pytest.raises((bundle.GitBundleError, ContentPathError)):
            bundle._inventory(archive, target)
    assert not target.exists()


def test_zip_symbolic_link_and_capacity_are_not_extracted(tmp_path):
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        link = ZipInfo('link')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, 'outside')
    with ZipFile(BytesIO(output.getvalue())) as archive:
        with pytest.raises(bundle.GitBundleError, match='TYPE_UNSUPPORTED'):
            bundle._inventory(archive, tmp_path / 'not-written')
    source = archive_bytes([('data', b'123')])
    with ZipFile(BytesIO(source)) as archive, patch.object(bundle, 'MAX_EXPANDED_BYTES', 2):
        with pytest.raises(bundle.GitBundleError, match='EXPANSION_LIMIT'):
            bundle._inventory(archive, tmp_path / 'not-written')


def test_extraction_keeps_raw_bytes_and_no_overwrite_and_pe_requires_x64(tmp_path):
    root = tmp_path / 'new'
    root.mkdir()
    source = archive_bytes(
        [('cmd/git.exe', pe()), ('data/empty', b''), ('data/raw', b'\x00\r\n\xff')]
    )
    with ZipFile(BytesIO(source)) as archive:
        inventory, total = bundle._inventory(archive, root)
        members = bundle._extract(archive, root, inventory)
        assert [entry.path for entry in members] == ['cmd/git.exe', 'data/empty', 'data/raw']
        assert (root / 'data/raw').read_bytes() == b'\x00\r\n\xff'
        bundle._verify_pe_x64(root / 'cmd/git.exe')
        with pytest.raises(FileExistsError):
            bundle._extract(archive, root, inventory)
    with (root / 'bad.exe').open('xb') as stream:
        stream.write(b'not a Windows executable')
    with pytest.raises(bundle.GitBundleError, match='NOT_PE'):
        bundle._verify_pe_x64(root / 'bad.exe')


def test_byte_verifier_reconstructs_from_archive_and_rejects_extra_empty_dir_or_tamper(tmp_path):
    root = tmp_path / 'win-x64'
    root.mkdir()
    source = archive_bytes([('cmd/git.exe', pe()), ('empty/', b''), ('data/raw', b'raw\r\n')])
    with (root / 'source.zip').open('xb') as stream:
        stream.write(source)
    with ZipFile(BytesIO(source)) as archive:
        inventory, total = bundle._inventory(archive, root)
        members = bundle._extract(archive, root, inventory)
    with (
        patch.object(bundle, 'BUNDLE_PARENT', tmp_path),
        patch.object(bundle, 'ARCHIVE_BYTES', len(source)),
        patch.object(bundle, 'ARCHIVE_SHA256', hashlib.sha256(source).hexdigest()),
    ):
        expected = bundle._manifest(members)
        encoded = (
            json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n'
        ).encode()
        with (root / 'manifest.json').open('xb') as stream:
            stream.write(encoded)
        assert bundle.verify_bundle_bytes() == (
            len(members),
            total,
            hashlib.sha256(encoded).hexdigest(),
        )
        assert expected['runtime_admitted'] is False
        (root / 'extra-empty').mkdir()
        with pytest.raises(bundle.GitBundleError, match='OBJECTS_DIFFER'):
            bundle.verify_bundle_bytes()
        (root / 'extra-empty').rmdir()
        with (root / 'data/raw').open('ab') as stream:
            stream.write(b'tampered')
        with pytest.raises(bundle.GitBundleError, match='BYTES_DIFFER'):
            bundle.verify_bundle_bytes()


def test_download_rejects_wrong_size_and_digest_and_performs_no_implicit_retry(tmp_path):
    class Response(BytesIO):
        pass

    for body, expected_size, expected_sha in (
        (b'abcd', 3, hashlib.sha256(b'abc').hexdigest()),
        (b'abc', 3, '0' * 64),
        (b'ab', 3, hashlib.sha256(b'abc').hexdigest()),
    ):
        with (
            patch.object(bundle, 'ARCHIVE_BYTES', expected_size),
            patch.object(bundle, 'ARCHIVE_SHA256', expected_sha),
            patch.object(bundle, 'urlopen', return_value=Response(body)) as read,
        ):
            with pytest.raises(bundle.GitBundleError):
                bundle._download(
                    tmp_path / ('rejected-' + str(expected_size) + '-' + str(len(body)))
                )
            assert read.call_count == 1
