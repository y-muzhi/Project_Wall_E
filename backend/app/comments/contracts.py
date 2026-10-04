"""Approved C06 internal input and complete result contract."""
from backend.app.shared.validation import object_fields, strict_integer
from backend.app.infrastructure.idempotency import canonical_input


def revalidate_anchors_input(payload: object) -> tuple[int, dict]:
    data = object_fields(payload, 'body', ('requirement_id', 'new_document'), ('requirement_id', 'new_document'))
    document = object_fields(data['new_document'], 'new_document', ('markdown_content', 'block_state_json'), ('markdown_content', 'block_state_json'))
    return strict_integer(data['requirement_id'], 'requirement_id'), document


def revalidate_anchors_result(requirement_id: int, document_id: int, version: int,
                              attached: list[int], orphaned: list[int]) -> dict:
    for field, value in (('requirement_id', requirement_id), ('document_id', document_id), ('content_version', version)):
        strict_integer(value, field)
    identities = attached + orphaned
    if len(set(identities)) != len(identities):
        raise ValueError('Every nondeleted comment must appear exactly once')
    for identity in identities:
        strict_integer(identity, 'comment_id')
    data = {'requirement_id': requirement_id, 'document_id': document_id, 'content_version': version,
            'attached_comment_ids': list(attached), 'orphaned_comment_ids': list(orphaned)}
    canonical_input(data)
    return {'code': 'ANCHORS_UPDATED', 'data': data, 'details': None}
