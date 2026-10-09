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

    def create(self, identity: int, number: str, request, guide_run_id: int, at: str) -> dict:
        require_write_transaction(self.connection)
        self.connection.execute("INSERT INTO requirements(id,requirement_no,requirement_type,initialization_mode,title,template_key,template_version,status,document_work_state,active_operation_type,active_operation_id,created_at,updated_at,completed_at,state_started_at) VALUES (?,?,?,?,?,?,?,'INITIALIZING','GUIDE_ACTIVE','GUIDE_RUN',?,?,?,NULL,?)",
            (identity, number, request.requirement_type, request.initialization_mode, request.title, request.template_key, request.template_version, guide_run_id, at, at, at))
        return self.get(identity)

    def all_roots(self) -> list[dict]:
        return [requirement_read_model(row) for row in self.connection.execute('SELECT ' + COLUMNS + ' FROM requirements ORDER BY id')]

    def recover_occupancy(self, root: dict, batch_id: int | None, started_at: str | None, at: str) -> None:
        require_write_transaction(self.connection)
        state, kind = ('IDLE', None) if batch_id is None else ('SUGGESTION_REVIEWING', 'SUGGESTION_BATCH')
        result = self.connection.execute('UPDATE requirements SET document_work_state=?,active_operation_type=?,active_operation_id=?,state_started_at=?,updated_at=? WHERE id=? AND document_work_state=? AND active_operation_type IS ? AND active_operation_id IS ?',
            (state, kind, batch_id, started_at, at, root['id'], root['document_work_state'], root['active_operation_type'], root['active_operation_id']))
        if result.rowcount != 1:
            raise ValueError('Recovery occupancy changed within the shared transaction')

    def update_attributes(self, identity: int, changes: dict[str, str], at: str) -> dict:
        require_write_transaction(self.connection)
        if not changes or not set(changes) <= {'title'}:
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

    def occupy_guide(self, identity: int, guide_id: int, at: str) -> dict:
        require_write_transaction(self.connection)
        result = self.connection.execute("UPDATE requirements SET document_work_state='GUIDE_ACTIVE',active_operation_type='GUIDE_RUN',active_operation_id=?,state_started_at=?,updated_at=? WHERE id=? AND document_work_state='IDLE'", (guide_id, at, at, identity))
        if result.rowcount != 1:
            raise ValueError('Guide occupancy changed inside shared transaction')
        row = self.get(identity)
        if row is None: raise ValueError('Occupied requirement is missing')
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
