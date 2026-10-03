"""D-008 persistent edit sources and real same-transaction provenance lookup.

These relationships never grant adoption permission. The application separately
checks lifecycle, occupancy, cancellation, base versions and frozen scope.
"""
import sqlite3

from backend.app.infrastructure.identifiers import require_write_transaction
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.shared.validation import MAX_SAFE_INTEGER
from .markdown import DocumentInvalid
from .snapshot import Provenance, _time


def _identity(value: int) -> None:
    if type(value) is not int or not 1 <= value <= MAX_SAFE_INTEGER:
        raise DocumentInvalid('来源身份必须为正整数')


def register_edit_session(connection: sqlite3.Connection, draft_id: int, operation_time: str) -> None:
    require_write_transaction(connection)
    _identity(draft_id)
    time = _time(operation_time)
    row = connection.execute("SELECT d.requirement_id,d.document_type,c.current_document_id,c.base_content_version,p.requirement_id AS current_requirement_id,p.document_type AS current_type,p.content_version FROM requirement_documents d JOIN manual_draft_context c ON c.draft_id=d.id JOIN requirement_documents p ON p.id=c.current_document_id WHERE d.id=?", (draft_id,)).fetchone()
    if row is None or row['document_type'] != 'MANUAL_DRAFT' or row['current_type'] != 'CURRENT' or row['requirement_id'] != row['current_requirement_id'] or row['base_content_version'] != row['content_version']:
        raise DocumentInvalid('编辑来源未绑定真实草稿与正文基线')
    connection.execute("INSERT INTO manual_edit_sessions(draft_id,requirement_id,current_document_id,status,started_at,closed_at) VALUES (?,?,?,'EDITING',?,NULL)", (draft_id, row['requirement_id'], row['current_document_id'], time))


def close_edit_session(connection: sqlite3.Connection, draft_id: int, outcome: str, operation_time: str) -> None:
    require_write_transaction(connection)
    _identity(draft_id)
    time = _time(operation_time)
    if type(outcome) is not str or outcome not in ('COMPLETED', 'CANCELLED'):
        raise DocumentInvalid('编辑来源关闭结果未登记')
    row = connection.execute('SELECT requirement_id,status,started_at FROM manual_edit_sessions WHERE draft_id=?', (draft_id,)).fetchone()
    if row is None or row['status'] != 'EDITING' or time < row['started_at']:
        raise DocumentInvalid('编辑来源缺失、已关闭或时间倒退')
    if connection.execute('SELECT 1 FROM requirement_documents WHERE id=?', (draft_id,)).fetchone() or connection.execute('SELECT 1 FROM manual_draft_context WHERE draft_id=?', (draft_id,)).fetchone():
        raise DocumentInvalid('关闭编辑来源必须与草稿及上下文删除同事务')
    requirement = connection.execute('SELECT document_work_state FROM requirements WHERE id=?', (row['requirement_id'],)).fetchone()
    if requirement is None or requirement['document_work_state'] != 'IDLE':
        raise DocumentInvalid('关闭编辑来源必须与占用释放同事务')
    connection.execute('UPDATE manual_edit_sessions SET status=?,closed_at=? WHERE draft_id=?', (outcome, time, draft_id))


class DocumentSources:
    """Callable verifier for Snapshot, bound to the caller's actual transaction."""
    def __init__(self, connection: sqlite3.Connection, requirement_id: int, catalog: ResourceCatalog):
        _identity(requirement_id)
        if not connection.in_transaction:
            raise RuntimeError('Source verification requires the shared transaction')
        self.connection, self.requirement_id, self.catalog = connection, requirement_id, catalog

    def __call__(self, origin: Provenance) -> bool:
        try:
            active = self.connection.in_transaction
        except sqlite3.ProgrammingError:
            raise RuntimeError('Source verifier cannot escape its transaction') from None
        if not active:
            raise RuntimeError('Source verifier cannot escape its transaction')
        if type(origin) is not Provenance:
            return False
        requirement = self.connection.execute('SELECT requirement_type,template_key,template_version FROM requirements WHERE id=?', (self.requirement_id,)).fetchone()
        if requirement is None:
            return False
        if origin.source_type == 'TEMPLATE':
            if origin.actor != 'SYSTEM' or origin.source_id is not None:
                return False
            self.catalog.template(requirement['requirement_type'], requirement['template_key'], requirement['template_version'])
            return True
        if origin.source_type == 'GUIDE_RUN':
            if origin.actor != 'AI':
                return False
            row = self.connection.execute('SELECT requirement_id,action_type FROM guide_runs WHERE id=?', (origin.source_id,)).fetchone()
            return row is not None and row['requirement_id'] == self.requirement_id and row['action_type'] == 'INITIALIZE'
        if origin.source_type == 'SUGGESTION_BATCH':
            if origin.actor not in ('AI', 'USER'):
                return False
            row = self.connection.execute('SELECT b.requirement_id,g.requirement_id AS run_requirement_id,g.action_type FROM suggestion_batches b JOIN guide_runs g ON g.id=b.guide_run_id WHERE b.id=?', (origin.source_id,)).fetchone()
            return row is not None and row['requirement_id'] == self.requirement_id == row['run_requirement_id'] and row['action_type'] == 'MODIFY'
        if origin.source_type != 'MANUAL_EDIT' or origin.actor != 'USER':
            return False
        row = self.connection.execute('SELECT s.requirement_id,s.current_document_id,s.status,p.requirement_id AS current_requirement_id,p.document_type FROM manual_edit_sessions s JOIN requirement_documents p ON p.id=s.current_document_id WHERE s.draft_id=?', (origin.source_id,)).fetchone()
        if row is None or row['requirement_id'] != self.requirement_id or row['current_requirement_id'] != self.requirement_id or row['document_type'] != 'CURRENT':
            return False
        if row['status'] != 'EDITING':
            return row['status'] in ('COMPLETED', 'CANCELLED')
        draft = self.connection.execute('SELECT d.requirement_id,d.document_type,c.current_document_id FROM requirement_documents d JOIN manual_draft_context c ON c.draft_id=d.id WHERE d.id=?', (origin.source_id,)).fetchone()
        return draft is not None and draft['requirement_id'] == self.requirement_id and draft['document_type'] == 'MANUAL_DRAFT' and draft['current_document_id'] == row['current_document_id']
