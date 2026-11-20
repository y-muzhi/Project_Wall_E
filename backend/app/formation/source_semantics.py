"""One semantic capture for proposal/recommendation sources, without mutable display metadata."""

import hashlib

from backend.app.guide.accepted_context import capture_source
from backend.app.requirements.source_refs import verify_source_refs
from backend.app.shared.json_canonical import canonical_input


def captured_source(connection, requirement_id, source, resources):
    verify_source_refs(connection, requirement_id, [source], resources=resources)
    captured = capture_source(connection, requirement_id, source, resources)
    if source['kind'] == 'REVISION':
        captured['value'] = {
            key: value
            for key, value in captured['value'].items()
            if key not in ('name', 'document_kind', 'template_ref')
        }
    return captured


def source_digest(connection, requirement_id, source, resources):
    return hashlib.sha256(
        canonical_input(captured_source(connection, requirement_id, source, resources)).encode(
            'utf-8'
        )
    ).hexdigest()
