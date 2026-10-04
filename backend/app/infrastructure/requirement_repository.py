"""INF-REQ-REP read projections on the caller's real shared SQLite snapshot."""
import re
import sqlite3

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
