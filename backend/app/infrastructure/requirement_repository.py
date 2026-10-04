"""INF-REQ-REP read projections on the caller's real shared SQLite snapshot."""
import re
import sqlite3

from backend.app.infrastructure.identifiers import require_write_transaction
from backend.app.requirements.contracts import ListRequirementsInput, READ_FIELDS, list_requirements_result, requirement_read_model
from backend.app.shared.pagination import PAGE_SIZE, page_offset

COLUMNS = ','.join(READ_FIELDS)


class RequirementRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def _count(self, where: str, bindings: tuple) -> int:
        return self.connection.execute('SELECT count(*) FROM requirements' + where, bindings).fetchone()[0]

    def list_page(self, request: ListRequirementsInput) -> dict:
        clauses, values = [], []
        if request.keyword is not None:
            if re.fullmatch(r'REQ[0-9]{6}', request.keyword, re.IGNORECASE | re.ASCII):
                clauses.append('requirement_no = ?')
                values.append(request.keyword.upper())
            else:
                clauses.append('instr(title, ?) > 0')
                values.append(request.keyword)
        for field, choices in (('status', request.status), ('requirement_type', request.requirement_type)):
            if choices:
                clauses.append(field + ' IN (' + ','.join('?' for _ in choices) + ')')
                values.extend(choices)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        bindings = tuple(values)
        total = self._count(where, bindings)
        rows = self.connection.execute(
            'SELECT ' + COLUMNS + ' FROM requirements' + where + ' ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?',
            (*bindings, PAGE_SIZE, page_offset(request.page)),
        ).fetchall()
        return list_requirements_result(rows, request.page, total)

    def get(self, identity: int) -> dict | None:
        row = self.connection.execute('SELECT ' + COLUMNS + ' FROM requirements WHERE id=?', (identity,)).fetchone()
        return None if row is None else requirement_read_model(row)

    def update_attributes(self, identity: int, changes: dict[str, str], at: str) -> dict:
        require_write_transaction(self.connection)
        if not changes or not set(changes) <= {'title', 'initialization_mode'}:
            raise ValueError('Only submitted mutable attributes may be written')
        fields = tuple(changes)
        result = self.connection.execute(
            'UPDATE requirements SET ' + ','.join(field + '=?' for field in fields) + ',updated_at=? WHERE id=?',
            (*[changes[field] for field in fields], at, identity),
        )
        if result.rowcount != 1:
            raise ValueError('Requirement disappeared from shared write transaction')
        row = self.get(identity)
        if row is None:
            raise ValueError('Updated requirement is missing')
        return row
