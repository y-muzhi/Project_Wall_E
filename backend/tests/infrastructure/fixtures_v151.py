"""Current 151 requirement fixture for schema-independent transaction tests."""

from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.requirements.contracts import create_requirement_input
from backend.app.requirements.discussion import empty_discussion

AT = '2026-09-21T08:30:00.000Z'
KEY = '00000000-0000-4000-8000-000000000099'


def insert_requirement(connection, identity=101, number='REQ000001'):
    request = create_requirement_input(
        {
            'title': '需求甲',
            'requirement_type': 'NEW',
            'initial_idea': '事务边界专项',
            'idempotency_key': KEY,
        }
    )
    RequirementRepository(connection).create(
        identity,
        number,
        request,
        identity,
        empty_discussion(),
        AT,
    )
    MessageRepository(connection).create_user_text(
        identity,
        identity,
        None,
        request.initial_idea,
        KEY,
        AT,
    )
