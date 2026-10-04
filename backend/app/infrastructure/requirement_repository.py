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

    def activate_initialization(self, identity: int, at: str) -> dict:
        require_write_transaction(self.connection)
        result = self.connection.execute("UPDATE requirements SET status='ACTIVE',updated_at=? WHERE id=? AND status='INITIALIZING'", (at, identity))
        if result.rowcount != 1:
            raise ValueError('Initialization state changed inside shared write transaction')
        row = self.get(identity)
        if row is None:
            raise ValueError('Activated requirement is missing')
        return row

    def change_lifecycle(self, identity: int, previous: str, status: str, at: str) -> dict:
        require_write_transaction(self.connection)
        if (previous, status) not in (('ACTIVE', 'COMPLETED'), ('COMPLETED', 'ACTIVE')):
            raise ValueError('Unregistered lifecycle transition')
        completed_at = at if status == 'COMPLETED' else None
        result = self.connection.execute('UPDATE requirements SET status=?,completed_at=?,updated_at=? WHERE id=? AND status=?',
                                         (status, completed_at, at, identity, previous))
        if result.rowcount != 1:
            raise ValueError('Lifecycle changed inside shared write transaction')
        row = self.get(identity)
        if row is None:
            raise ValueError('Requirement vanished inside shared write transaction')
        return row

    def occupy_manual_draft(self, identity: int, draft_id: int, at: str) -> dict:
        require_write_transaction(self.connection)
        result = self.connection.execute("UPDATE requirements SET document_work_state='MANUAL_EDITING',active_operation_type='MANUAL_DRAFT',active_operation_id=?,state_started_at=?,updated_at=? WHERE id=? AND status IN ('INITIALIZING','ACTIVE') AND document_work_state='IDLE'", (draft_id, at, at, identity))
        if result.rowcount != 1:
            raise ValueError('Manual occupancy changed inside shared transaction')
        row = self.get(identity)
        if row is None:
            raise ValueError('Occupied requirement is missing')
        return row

    def release_manual_draft(self, identity: int, draft_id: int, at: str) -> dict:
        require_write_transaction(self.connection)
        result = self.connection.execute("UPDATE requirements SET document_work_state='IDLE',active_operation_type=NULL,active_operation_id=NULL,state_started_at=NULL,updated_at=? WHERE id=? AND document_work_state='MANUAL_EDITING' AND active_operation_type='MANUAL_DRAFT' AND active_operation_id=?", (at, identity, draft_id))
        if result.rowcount != 1:
            raise ValueError('Manual occupancy changed inside shared transaction')
        row = self.get(identity)
        if row is None:
            raise ValueError('Released requirement is missing')
        return row
