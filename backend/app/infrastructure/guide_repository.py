"""INF-GUIDE-REP durable initialization acceptance, without Provider I/O."""
import sqlite3
from .identifiers import require_write_transaction
from .idempotency import canonical_input
from backend.app.documents.snapshot import _time
from backend.app.shared.pagination import PAGE_SIZE, page_offset

STATUS_COLUMNS = 'id,requirement_id,action_type,function_type,source_type,source_id,scope_type,scope_ref_json,status,current_step,error_code,error_message,cancel_reason,retry_of_guide_run_id,created_at,started_at,waiting_user_at,ended_at,updated_at'


class GuideRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def accept_initialization(self, identity: int, root: dict, message: sqlite3.Row, function, scope, manifest: dict, at: str) -> sqlite3.Row:
        require_write_transaction(self.connection)
        if message['requirement_id'] != root['id'] or message['guide_run_id'] != identity or message['role'] != 'USER' or message['message_type'] != 'TEXT' or function.action_type != 'INITIALIZE' or function.source_type != 'USER_INSTRUCTION':
            raise ValueError('Initial run must bind the real initial USER instruction and frozen Function')
        context_key, context_version = function.context_template.split('@')
        _, prompt_version = function.prompt_reference.split('@')
        self.connection.execute("INSERT INTO guide_runs(id,requirement_id,idempotency_key,trigger_message_id,trigger_type,source_type,source_id,function_type,context_template_key,context_template_version,prompt_version,action_type,mode_snapshot,instruction_summary,scope_type,scope_ref_json,read_scope_manifest_json,allowed_targets_json,status,current_step,final_result_json,created_at,started_at,waiting_user_at,ended_at,updated_at,error_code,error_message,cancel_reason,retry_of_guide_run_id) VALUES (?,?,?,?,'CREATE_REQUIREMENT','USER_INSTRUCTION',NULL,?,?,?,?,'INITIALIZE',?,?,'DOCUMENT',NULL,?,?,'RUNNING','PREPARING',NULL,?,NULL,NULL,NULL,?,NULL,NULL,NULL,NULL)",
            (identity, root['id'], message['idempotency_key'], message['id'], function.function_type, context_key, context_version, prompt_version,
             root['initialization_mode'], message['content'], canonical_input(manifest), scope.authority_json, at, at))
        row = self.connection.execute('SELECT * FROM guide_runs WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise ValueError('Accepted run is missing')
        return row

    def running(self) -> list[sqlite3.Row]:
        return self.connection.execute("SELECT id,requirement_id,status,created_at,updated_at FROM guide_runs WHERE status='RUNNING' ORDER BY id").fetchall()

    def get(self, identity: int):
        return self.connection.execute('SELECT * FROM guide_runs WHERE id=?', (identity,)).fetchone()

    def accept(self, identity, root, message, function, scope, manifest, at, *, trigger_type='CREATE_GUIDE_RUN'):
        require_write_transaction(self.connection)
        if message['requirement_id'] != root['id'] or message['guide_run_id'] != identity or message['role'] != 'USER' or message['message_type'] not in ('TEXT', 'CARD_RESPONSE'):
            raise ValueError('Accepted run must bind its real USER instruction')
        context_key, context_version = function.context_template.split('@')
        _, prompt_version = function.prompt_reference.split('@')
        values = {'id': identity, 'requirement_id': root['id'], 'idempotency_key': message['idempotency_key'], 'trigger_message_id': message['id'], 'trigger_type': trigger_type,
            'source_type': function.source_type, 'source_id': manifest['source']['source_id'], 'function_type': function.function_type, 'context_template_key': context_key,
            'context_template_version': context_version, 'prompt_version': prompt_version, 'action_type': function.action_type,
            'mode_snapshot': root['initialization_mode'] if function.action_type == 'INITIALIZE' else None, 'instruction_summary': message['content'],
            'scope_type': scope.scope_type, 'scope_ref_json': None if scope.input_ref is None else canonical_input(scope.input_ref),
            'read_scope_manifest_json': canonical_input(manifest), 'allowed_targets_json': scope.authority_json, 'status': 'RUNNING', 'current_step': 'PREPARING',
            'final_result_json': None, 'created_at': at, 'started_at': None, 'waiting_user_at': None, 'ended_at': None, 'updated_at': at,
            'error_code': None, 'error_message': None, 'cancel_reason': None, 'retry_of_guide_run_id': None}
        self.connection.execute('INSERT INTO guide_runs('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')', tuple(values.values()))
        return self.get(identity)

    def continue_run(self, identity, message, at, *, trigger_type='CONTINUE_GUIDE_RUN'):
        require_write_transaction(self.connection)
        run = self.get(identity)
        if run is None or message['requirement_id'] != run['requirement_id'] or message['guide_run_id'] != identity or message['role'] != 'USER' or message['message_type'] not in ('TEXT', 'CARD_RESPONSE'):
            raise ValueError('Continuation must bind its real USER instruction')
        result = self.connection.execute("UPDATE guide_runs SET trigger_message_id=?,trigger_type=?,instruction_summary=?,status='RUNNING',current_step='PREPARING',updated_at=? WHERE id=? AND status='WAITING_USER' AND action_type IN ('ASK','REVIEW','MODIFY')", (message['id'], trigger_type, message['content'], at, identity))
        if result.rowcount != 1: raise ValueError('Continuation lost its shared state gate')
        return self.get(identity)

    def get_status(self, identity: int) -> sqlite3.Row | None:
        return self.connection.execute('SELECT '+STATUS_COLUMNS+',final_result_json FROM guide_runs WHERE id=?', (identity,)).fetchone()

    def _count_history(self, where: str, values: tuple) -> int:
        return self.connection.execute('SELECT count(*) FROM guide_runs'+where, values).fetchone()[0]

    def list_history(self, request) -> tuple[int, list[sqlite3.Row]]:
        clauses, values = ['requirement_id=?'], [request.requirement_id]
        for field in ('status', 'action_type'):
            choices = getattr(request, field)
            if choices:
                clauses.append(field+' IN ('+','.join('?' for _ in choices)+')'); values.extend(choices)
        where, bindings = ' WHERE '+' AND '.join(clauses), tuple(values)
        total = self._count_history(where, bindings)
        rows = self.connection.execute('SELECT '+STATUS_COLUMNS+' FROM guide_runs'+where+' ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',
            (*bindings, PAGE_SIZE, page_offset(request.page))).fetchall()
        return total, rows

    def status_references(self, run: sqlite3.Row) -> tuple[sqlite3.Row | None, list[sqlite3.Row]]:
        message = self.connection.execute("SELECT id,requirement_id FROM conversation_messages WHERE guide_run_id=? AND role='ASSISTANT' ORDER BY sequence_no DESC,id DESC LIMIT 1", (run['id'],)).fetchone()
        batches = self.connection.execute('SELECT id,requirement_id FROM suggestion_batches WHERE guide_run_id=? LIMIT 2', (run['id'],)).fetchall()
        if message is not None and message['requirement_id'] != run['requirement_id'] or len(batches) > 1 or any(batch['requirement_id'] != run['requirement_id'] for batch in batches):
            raise ValueError('Run status references must belong to the same requirement')
        return message, batches

    def recover_failed(self, identity: int, code: str, message: str, at: str) -> None:
        require_write_transaction(self.connection)
        for row in self.connection.execute('SELECT started_at FROM llm_uses WHERE guide_run_id=? AND ended_at IS NULL', (identity,)):
            if _time(row['started_at']) > at:
                raise ValueError('Recovery cannot precede the unfinished attempt')
        result = self.connection.execute("UPDATE guide_runs SET status='FAILED',current_step='FINISHED',final_result_json=NULL,ended_at=?,updated_at=?,error_code=?,error_message=? WHERE id=? AND status='RUNNING'", (at, at, code, message, identity))
        if result.rowcount != 1:
            raise ValueError('Recovered run changed within its shared transaction')
        # Preserve all earlier transport/parse/validation facts and unknown usage.
        self.connection.execute("UPDATE llm_uses SET call_status='FAILED',ended_at=?,error_code=?,error_message=? WHERE guide_run_id=? AND ended_at IS NULL", (at, code, message, identity))

    def cancel(self, identity: int, at: str) -> sqlite3.Row:
        require_write_transaction(self.connection)
        for row in self.connection.execute('SELECT started_at FROM llm_uses WHERE guide_run_id=? AND ended_at IS NULL', (identity,)):
            if _time(row['started_at']) > at:
                raise ValueError('Cancellation cannot precede an unfinished attempt')
        result = self.connection.execute("UPDATE guide_runs SET status='CANCELLED',current_step='FINISHED',cancel_reason='USER_REQUESTED',final_result_json=NULL,error_code=NULL,error_message=NULL,ended_at=?,updated_at=? WHERE id=? AND status IN ('RUNNING','WAITING_USER') AND current_step<>'PERSISTING'", (at, at, identity))
        if result.rowcount != 1:
            raise ValueError('Cancellation lost its shared transaction state gate')
        # An unfinished request is logically cancelled, not a proven Provider
        # failure. Preserve transport/parse/validation facts and unknown usage.
        self.connection.execute("UPDATE llm_uses SET call_status='CANCELLED',ended_at=? WHERE guide_run_id=? AND ended_at IS NULL", (at, identity))
        return self.get_status(identity)
