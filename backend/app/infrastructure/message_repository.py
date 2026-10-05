"""INF-MSG-REP accepted initial USER TEXT, immutable with actual run binding."""
import sqlite3
from .identifiers import message_sequence, require_write_transaction


class MessageRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def get(self, identity: int):
        return self.connection.execute('SELECT * FROM conversation_messages WHERE id=?', (identity,)).fetchone()

    def window(self, requirement_id: int, cursor: int | None):
        condition = '' if cursor is None else ' AND sequence_no<?'
        parameters = (requirement_id,) if cursor is None else (requirement_id, cursor)
        rows = self.connection.execute('SELECT * FROM conversation_messages WHERE requirement_id=?'+condition+' ORDER BY sequence_no DESC LIMIT 20', parameters).fetchall()
        return list(reversed(rows))

    def older_exists(self, requirement_id: int, sequence: int):
        return self.connection.execute('SELECT 1 FROM conversation_messages WHERE requirement_id=? AND sequence_no<? LIMIT 1', (requirement_id, sequence)).fetchone() is not None

    def guide(self, identity: int):
        return self.connection.execute('SELECT id,requirement_id,action_type,source_type,source_id,function_type,status,created_at,read_scope_manifest_json,final_result_json FROM guide_runs WHERE id=?', (identity,)).fetchone()

    def guide_binding(self, identity: int):
        return self.connection.execute('SELECT id,requirement_id FROM guide_runs WHERE id=?', (identity,)).fetchone()

    def activities(self, requirement_id: int):
        return {
            'MANUAL_DRAFT': [row['id'] for row in self.connection.execute("SELECT id FROM requirement_documents WHERE requirement_id=? AND document_type='MANUAL_DRAFT' LIMIT 2", (requirement_id,))],
            'GUIDE_RUN': [row['id'] for row in self.connection.execute("SELECT id FROM guide_runs WHERE requirement_id=? AND status IN ('RUNNING','WAITING_USER') LIMIT 2", (requirement_id,))],
            'SUGGESTION_BATCH': [row['id'] for row in self.connection.execute("SELECT id FROM suggestion_batches WHERE requirement_id=? AND status='PENDING' LIMIT 2", (requirement_id,))],
        }

    def formal_responses(self, message_id: int):
        return self.connection.execute("SELECT id,requirement_id,guide_run_id,sequence_no,created_at FROM conversation_messages WHERE message_type='CARD_RESPONSE' AND reply_to_message_id=? LIMIT 2", (message_id,)).fetchall()

    def latest_card_id(self, requirement_id: int):
        row = self.connection.execute("SELECT id FROM conversation_messages WHERE requirement_id=? AND role='ASSISTANT' AND message_type='INTERACTION_CARDS' ORDER BY sequence_no DESC LIMIT 1", (requirement_id,)).fetchone()
        return None if row is None else row['id']

    def newer_input_exists(self, message):
        return self.connection.execute("SELECT 1 FROM conversation_messages WHERE requirement_id=? AND role='USER' AND sequence_no>? AND (message_type<>'CARD_RESPONSE' OR reply_to_message_id<>?) LIMIT 1", (message['requirement_id'], message['sequence_no'], message['id'])).fetchone() is not None

    def newer_run_exists(self, requirement_id: int, run_id: int):
        return self.connection.execute('SELECT 1 FROM guide_runs WHERE requirement_id=? AND id>? LIMIT 1', (requirement_id, run_id)).fetchone() is not None

    def current_identity(self, requirement_id: int):
        return self.connection.execute("SELECT id,content_version FROM requirement_documents WHERE requirement_id=? AND document_type='CURRENT' LIMIT 2", (requirement_id,)).fetchall()

    def create_user_text(self, identity: int, requirement_id: int, guide_run_id: int, content: str, key: str, at: str) -> sqlite3.Row:
        require_write_transaction(self.connection)
        self.connection.execute("INSERT INTO conversation_messages VALUES (?,?,?,?,'USER',?,'TEXT',NULL,NULL,?,?)",
            (identity, requirement_id, guide_run_id, message_sequence(self.connection, requirement_id), content, key, at))
        row = self.connection.execute('SELECT * FROM conversation_messages WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise ValueError('Accepted user message is missing')
        return row
