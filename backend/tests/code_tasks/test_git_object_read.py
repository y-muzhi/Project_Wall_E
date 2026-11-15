"""Raw Git object integrity, independently generated SHA-1/SHA-256 vectors."""

import hashlib
import pytest

from backend.app.infrastructure.git_object_read import (
    GitObjectReadError,
    verify_git_object,
)


def digest(kind, raw, format):
    return hashlib.new(
        format, kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw
    ).hexdigest()


@pytest.mark.parametrize('format', ['sha1', 'sha256'])
@pytest.mark.parametrize('kind', ['commit', 'tree', 'blob'])
@pytest.mark.parametrize('raw', [b'', b'\0\xff\r\nraw bytes\n', bytes(range(256))])
def test_exact_object_bytes_type_and_format_are_required(format, kind, raw):
    oid = digest(kind, raw, format)
    result = verify_git_object(
        raw, format=format, object_type=kind, oid=oid, max_output_bytes=max(1, len(raw))
    )
    assert result.raw is raw and result.object_oid == oid
    assert result.byte_count == len(raw) and result.sha256 == hashlib.sha256(raw).hexdigest()
    assert 'raw=' not in repr(result)
    with pytest.raises(GitObjectReadError, match='TYPE_OR_OID'):
        verify_git_object(
            raw + b'x', format=format, object_type=kind, oid=oid, max_output_bytes=1000
        )
    other = 'commit' if kind != 'commit' else 'tree'
    with pytest.raises(GitObjectReadError, match='TYPE_OR_OID'):
        verify_git_object(raw, format=format, object_type=other, oid=oid, max_output_bytes=1000)


@pytest.mark.parametrize(
    'changes',
    [
        {'oid': 'HEAD'},
        {'oid': 'a' * 7},
        {'oid': '0' * 40},
        {'oid': 'A' * 40},
        {'object_type': 'tag'},
        {'object_type': '--filters'},
        {'object_type': True},
        {'raw': bytearray(b'raw')},
        {'max_output_bytes': True},
        {'max_output_bytes': 0},
        {'max_output_bytes': 2},
        {'max_output_bytes': 9007199254740992},
        {'format': 'md5'},
        {'oid': 'a' * 64},
    ],
)
def test_unbounded_unsupported_and_expression_inputs_fail(changes):
    raw = b'raw'
    values = dict(
        raw=raw,
        format='sha1',
        object_type='blob',
        oid=digest('blob', raw, 'sha1'),
        max_output_bytes=3,
    )
    values.update(changes)
    with pytest.raises(ValueError):
        verify_git_object(**values)
