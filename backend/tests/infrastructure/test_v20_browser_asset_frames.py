"""Root response framing accepts real assets while keeping distinct bounds."""

import base64
import io
from types import SimpleNamespace
import pytest
from backend.app.infrastructure.check_driver_browser import BrowserRelayClient
from backend.app.infrastructure.check_driver_bootstrap import write_frame, write_result_frame
from backend.app.infrastructure.check_case_evidence import CheckEvidenceUnknown


@pytest.mark.parametrize('size,allowed', [(3 * 1024 * 1024, True), (4 * 1024 * 1024 + 1, False)])
def test_root_asset_response_uses_bounded_control_frame(size, allowed):
    body = b'x' * size
    incoming, outgoing = io.BytesIO(), io.BytesIO()
    write_frame(
        incoming,
        {
            'seq': 1,
            'status': 200,
            'headers': {'content-type': 'application/javascript'},
            'body': base64.b64encode(body).decode('ascii'),
        },
    )
    incoming.seek(0)
    fulfilled, aborted = [], []
    route = SimpleNamespace(
        request=SimpleNamespace(
            url='http://o1.localhost/asset.js',
            method='GET',
            all_headers=lambda: {},
            post_data_buffer=b'',
        ),
        fulfill=lambda **value: fulfilled.append(value),
        abort=aborted.append,
    )
    client = BrowserRelayClient(incoming, outgoing, {'app': 'http://o1.localhost'})
    client.forward(route)
    assert client.failed is not allowed
    if allowed:
        assert len(fulfilled) == 1 and fulfilled[0]['body'] == body and not aborted
    else:
        assert not fulfilled and aborted == ['blockedbyclient']


def test_large_response_capacity_does_not_expand_request_body_or_result_frames():
    incoming, outgoing = io.BytesIO(), io.BytesIO()
    route = SimpleNamespace(
        request=SimpleNamespace(
            url='http://o1.localhost/',
            method='POST',
            all_headers=lambda: {},
            post_data_buffer=b'x' * (1024 * 1024 + 1),
        ),
        fulfill=lambda **_: pytest.fail('Oversized request was forwarded'),
        abort=lambda _: None,
    )
    client = BrowserRelayClient(incoming, outgoing, {'app': 'http://o1.localhost'})
    client.forward(route)
    assert client.failed and not outgoing.getvalue()
    writer = io.BytesIO()
    with pytest.raises(CheckEvidenceUnknown, match='CAPACITY_EXCEEDED'):
        write_result_frame(writer, {'untrusted_text': 'x' * (128 * 1024)})
    assert writer.getvalue() == b''
