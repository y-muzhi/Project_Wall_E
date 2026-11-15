"""Fixed cat-file response framing before any body allocation."""

import pytest

from backend.app.infrastructure.git_commit_closure import ObjectReadRequest
from backend.app.infrastructure.git_object_batch import _batch_size
from backend.app.infrastructure.git_object_read import GitObjectReadError

OID = 'a' * 40
REQUEST = ObjectReadRequest('sha1', 'blob', OID, 4, 10)


def test_batch_header_accepts_zero_and_exact_limit():
    assert _batch_size(OID.encode() + b' blob 0', REQUEST) == 0
    assert _batch_size(OID.encode() + b' blob 4', REQUEST) == 4


@pytest.mark.parametrize(
    ('header', 'reason'),
    [
        (OID.encode() + b' missing', 'OBJECT_MISSING'),
        (OID.encode() + b' tree 1', 'HEADER_DIFFERS'),
        (b'b' * 40 + b' blob 1', 'HEADER_DIFFERS'),
        (OID.encode() + b' blob 00', 'HEADER_DIFFERS'),
        (OID.encode() + b' blob -1', 'HEADER_DIFFERS'),
        (OID.encode() + b' blob 10000000000000000', 'HEADER_DIFFERS'),
        (OID.encode() + b' blob 4 extra', 'HEADER_DIFFERS'),
        (OID.encode() + b' blob 5', 'OBJECT_TOO_LARGE'),
    ],
)
def test_wrong_original_object_or_unbounded_length_is_rejected_before_body(header, reason):
    with pytest.raises(GitObjectReadError, match=reason):
        _batch_size(header, REQUEST)
