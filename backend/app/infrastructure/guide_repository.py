"""INF-GUIDE-REP durable initialization acceptance, without Provider I/O."""
import sqlite3
from .identifiers import require_write_transaction
from .idempotency import canonical_input


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
