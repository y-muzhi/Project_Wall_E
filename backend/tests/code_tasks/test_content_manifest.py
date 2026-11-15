"""Canonical content metadata and streaming bytes, not Git/capture admission."""

from dataclasses import replace
import hashlib
import json

import pytest

from backend.app.infrastructure import content_manifest as content
from backend.app.infrastructure.content_paths import ContentPathError

LIMITS = content.ContentLimits(1024, 4096, 10, 16384)
HELLO_OID = 'ce013625030ba8dba906f756967f9e9ca394464a'


def entry(path='hello.txt', body=b'hello\n', mode='100644'):
    # Independent public Git hello-blob vector; arbitrary fixture paths do not
    # affect a blob identity. Other vectors are rejected or supplied by real Git.
    assert body == b'hello\n'
    return content.ContentEntry(path, mode, HELLO_OID, len(body), hashlib.sha256(body).hexdigest())


def manifest(entries=(), *, format='sha1', limits=LIMITS):
    return content.build_manifest(
        entries,
        content_profile_version_id=7,
        format=format,
        content_tree_oid='1' * (40 if format == 'sha1' else 64),
        limits=limits,
    )


def encoded_row(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n'
    ).encode()


def test_canonical_bytes_roundtrip_sort_unicode_lf_and_original_identity():
    value = manifest([entry('😀.txt'), entry('é/a.txt'), entry('Z.txt'), entry('a.txt')])
    raw = content.encode_manifest(value, LIMITS)
    assert [e.path for e in value.entries] == ['Z.txt', 'a.txt', 'é/a.txt', '😀.txt']
    assert raw.endswith(b'\n') and not raw.endswith(b'\n\n') and not raw.startswith(b'\xef\xbb\xbf')
    assert 'é'.encode() in raw and b'\\ud83d' not in raw
    assert raw == encoded_row(value.as_dict())
    assert (
        content.decode_manifest(
            raw,
            limits=LIMITS,
            expected_sha256=hashlib.sha256(raw).hexdigest(),
            expected_format='sha1',
            expected_profile_version_id=7,
        )
        == value
    )
    assert content.manifest_sha256(raw) != content.manifest_sha256(raw[:-1])


@pytest.mark.parametrize(
    'raw_change',
    [
        lambda raw: b'\xef\xbb\xbf' + raw,
        lambda raw: raw.replace(b'\n', b'\r\n'),
        lambda raw: raw + b'\n',
        lambda raw: raw[:-1],
        lambda raw: b' ' + raw,
        lambda raw: raw.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1'),
        lambda raw: raw.replace(b'"byte_count":6', b'"byte_count":6.0'),
        lambda raw: raw.replace(b'"file_count":1', b'"file_count":true'),
        lambda raw: raw.replace(b'"schema_version":1', b'"schema_version":NaN'),
    ],
)
def test_malformed_or_noncanonical_serializations_are_never_repaired(raw_change):
    raw = content.encode_manifest(manifest([entry()]), LIMITS)
    with pytest.raises(content.ContentManifestError):
        content.decode_manifest(raw_change(raw), limits=LIMITS)


def test_full_fields_order_mode_oid_policy_counts_and_profile_are_checked():
    original = manifest([entry('a'), entry('b')]).as_dict()
    changes = [
        {'entries': list(reversed(original['entries']))},
        {'unknown': None},
        {'schema_version': True},
        {'content_policy_version': 'GIT20-BASELINE-1'},
        {'content_profile_version_id': True},
        {'file_count': 1},
        {'byte_count': 0},
        {'content_tree_oid': 'HEAD'},
        {'object_format': 'SHA1'},
    ]
    for change in changes:
        with pytest.raises(content.ContentManifestError):
            content.decode_manifest(encoded_row({**original, **change}), limits=LIMITS)
    for change in [
        {'blob_oid': 'f' * 64},
        {'blob_oid': HELLO_OID.upper()},
        {'byte_count': True},
        {'byte_count': -1},
        {'sha256': '0' * 63},
        {'extra': 1},
    ]:
        row = {
            **original,
            'entries': [{**original['entries'][0], **change}, original['entries'][1]],
        }
        with pytest.raises(content.ContentManifestError):
            content.decode_manifest(encoded_row(row), limits=LIMITS)
    with pytest.raises(ContentPathError):
        manifest([replace(entry(), mode='120000')])
    raw = content.encode_manifest(manifest(), LIMITS)
    for expected in [
        {'expected_sha256': 'a' * 64},
        {'expected_format': 'sha256'},
        {'expected_profile_version_id': 8},
    ]:
        with pytest.raises(content.ContentManifestError):
            content.decode_manifest(raw, limits=LIMITS, **expected)


@pytest.mark.parametrize(
    'paths',
    [
        ['src/a', 'Src/b'],
        ['Straße/a', 'STRASSE/b'],
        ['a', 'a/b'],
        ['a', 'a'],
        ['a/.GIT/config'],
        ['../outside'],
        ['é/a', 'e\u0301/b'],
    ],
)
def test_all_parent_aliases_conflicts_and_disallowed_paths_reuse_the_shared_policy(paths):
    with pytest.raises(ContentPathError):
        manifest([entry(path) for path in paths])


def test_empty_manifest_is_valid_metadata_but_not_proof_of_a_readable_tree():
    value = manifest()
    assert value.entries == () and value.file_count == 0 and value.byte_count == 0
    assert content.decode_manifest(content.encode_manifest(value, LIMITS), limits=LIMITS) == value
    # No native/Git callback occurs anywhere in the codec.


def test_limits_use_actual_utf8_manifest_bytes_and_declared_raw_file_counts():
    value = manifest([entry('😀')])
    raw = content.encode_manifest(value, LIMITS)
    exact = replace(LIMITS, max_manifest_bytes=len(raw))
    assert content.encode_manifest(value, exact) == raw
    with pytest.raises(content.ContentManifestError, match='MANIFEST_BYTES_EXCEEDED'):
        content.encode_manifest(value, replace(exact, max_manifest_bytes=len(raw) - 1))
    with pytest.raises(content.ContentManifestError, match='FILE_LIMIT_EXCEEDED'):
        manifest([entry()], limits=replace(LIMITS, max_file_bytes=5))
    with pytest.raises(content.ContentManifestError, match='FILE_COUNT_EXCEEDED'):
        manifest([entry('a'), entry('b')], limits=replace(LIMITS, max_snapshot_files=1))
    with pytest.raises(content.ContentManifestError, match='TOTAL_BYTES_EXCEEDED'):
        manifest([entry('a'), entry('b')], limits=replace(LIMITS, max_snapshot_bytes=11))
    for bad in [0, -1, True, 1.0, '1', 9007199254740992]:
        with pytest.raises(content.ContentManifestError):
            replace(LIMITS, max_manifest_bytes=bad)
    with pytest.raises(ContentPathError, match='FULL_PATH_TOO_LONG'):
        content.build_manifest(
            [entry('x' * 239)],
            content_profile_version_id=7,
            format='sha1',
            content_tree_oid='1' * 40,
            limits=LIMITS,
            materialization_root='C:/x',
        )


def test_streaming_known_git_blob_vector_keeps_exact_bytes_and_never_reuses_finished_state():
    expected = entry()
    verifier = content.BlobVerifier(expected, format='sha1', limits=LIMITS)
    verifier.feed(b'he')
    verifier.feed(b'llo\n')
    assert verifier.finish() == expected
    with pytest.raises(content.ContentManifestError, match='VERIFIER_CLOSED'):
        verifier.feed(b'hello\n')
    with pytest.raises(content.ContentManifestError, match='VERIFIER_CLOSED'):
        verifier.finish()
    empty = content.ContentEntry(
        'empty',
        '100755',
        'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391',
        0,
        hashlib.sha256(b'').hexdigest(),
    )
    assert content.BlobVerifier(empty, format='sha1', limits=LIMITS).finish() == empty


@pytest.mark.parametrize('kind', ['short', 'long', 'sha256', 'oid', 'empty_chunk', 'text_chunk'])
def test_incomplete_changed_overlong_or_invalid_blob_bytes_fail_the_whole_verifier(kind):
    value = entry()
    if kind == 'sha256':
        value = replace(value, sha256='0' * 64)
    if kind == 'oid':
        value = replace(value, blob_oid='0' * 40)
    verifier = content.BlobVerifier(value, format='sha1', limits=LIMITS)
    with pytest.raises(content.ContentManifestError):
        if kind == 'short':
            verifier.feed(b'hello')
        elif kind == 'long':
            verifier.feed(b'hello\r\n')
        elif kind == 'empty_chunk':
            verifier.feed(b'')
        elif kind == 'text_chunk':
            verifier.feed('hello\n')
        else:
            verifier.feed(b'hello\n')
        verifier.finish()
    with pytest.raises(content.ContentManifestError, match='VERIFIER_CLOSED'):
        verifier.finish()


def test_exact_path_comparison_preserves_missing_vs_empty_modes_and_has_no_rename_inference():
    old = [entry('gone'), entry('mode'), entry('same'), entry('改动')]
    new = [
        entry('added'),
        entry('mode', mode='100755'),
        entry('same'),
        replace(entry('改动'), sha256='0' * 64),
    ]
    changes = content.compare_content(old, new, format='sha1', limits=LIMITS)
    assert [c.path for c in changes] == ['added', 'gone', 'mode', '改动']
    assert changes[0].before is None and changes[0].after == new[0]
    assert changes[1].before == old[0] and changes[1].after is None
    assert changes[2].before.mode == '100644' and changes[2].after.mode == '100755'
    assert content.compare_content(old, old, format='sha1', limits=LIMITS) == ()
