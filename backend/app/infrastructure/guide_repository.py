"""INF-GUIDE-REP durable initialization acceptance, without Provider I/O."""
import sqlite3
from .identifiers import require_write_transaction
from .idempotency import canonical_input
from backend.app.documents.snapshot import _time


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
