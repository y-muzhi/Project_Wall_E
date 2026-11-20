"""Formation native command's parsed business identity and complete success receipt."""

from dataclasses import dataclass

from backend.app.infrastructure.idempotency import request_key
from backend.app.shared.json_canonical import canonical_input
from backend.app.shared.validation import object_fields, strict_integer

from .native_contracts import native_command


@dataclass(frozen=True)
class FormationCommandInput:
    requirement_id: int
    document_id: int
    expected_discussion_version: int
    discussion_command: dict
    idempotency_key: str

    def business_input(self):
        return {
            'requirement_id': self.requirement_id,
            'document_id': self.document_id,
            'expected_discussion_version': self.expected_discussion_version,
            'discussion_command': self.discussion_command,
        }


def command_input(payload):
    fields = (
        'requirement_id',
        'document_id',
        'expected_discussion_version',
        'discussion_command',
        'idempotency_key',
    )
    data = object_fields(payload, 'body', fields, fields)
    result = FormationCommandInput(
        strict_integer(data['requirement_id'], 'requirement_id'),
        strict_integer(data['document_id'], 'document_id'),
        strict_integer(data['expected_discussion_version'], 'expected_discussion_version'),
        native_command(data['discussion_command']),
        request_key(data['idempotency_key']),
    )
    canonical_input(result.business_input())
    return result
