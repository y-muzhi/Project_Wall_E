"""Exact frozen protocol identity and required endpoint contracts."""

import hashlib
import json
from time import monotonic

import pytest

from backend.app.infrastructure import opencode_protocol_source as protocol


def _fixture(path, monkeypatch, *, missing=False):
    routes = {}
    for route, method, status in protocol.REQUIRED_OPERATIONS:
        routes.setdefault(route, {}).setdefault(method, {'responses': {}})['responses'][status] = {}
    if missing:
        routes['/session/{sessionID}/prompt_async']['post']['responses'] = {'200': {}}
    payload = json.dumps({'info': {'version': '1.0.0'}, 'paths': routes}).encode()
    path.write_bytes(payload)
    digest = hashlib.sha1(f'blob {len(payload)}\0'.encode() + payload).hexdigest()
    monkeypatch.setattr(protocol, 'OPENAPI_BYTES', len(payload))
    monkeypatch.setattr(protocol, 'OPENAPI_BLOB', digest)
    return path


@pytest.fixture
def protocol_document(tmp_path, monkeypatch):
    return _fixture(tmp_path / 'openapi.json', monkeypatch)


def test_original_bytes_prove_static_source_and_reject_same_size_change(protocol_document):
    fact = protocol.verify_opencode_protocol_source(
        protocol_document, deadline=monotonic() + 10, cancelled=lambda: False
    )
    assert fact.commit == protocol.SOURCE_COMMIT
    assert fact.blob == protocol.OPENAPI_BLOB
    payload = protocol_document.read_bytes()
    protocol_document.write_bytes(payload.replace(b'1.0.0', b'1.0.1'))
    with pytest.raises(protocol.OpenCodeProtocolSourceError, match='BLOB_DIFFERS'):
        protocol.verify_opencode_protocol_source(
            protocol_document, deadline=monotonic() + 10, cancelled=lambda: False
        )


def test_source_with_an_incompatible_prompt_contract_is_rejected(tmp_path, monkeypatch):
    source = _fixture(tmp_path / 'openapi.json', monkeypatch, missing=True)
    with pytest.raises(protocol.OpenCodeProtocolSourceError, match='OPERATION_DIFFERS'):
        protocol.verify_opencode_protocol_source(
            source, deadline=monotonic() + 10, cancelled=lambda: False
        )
