"""INF-MSG-REP accepted initial USER TEXT, immutable with actual run binding."""
import sqlite3
from .identifiers import message_sequence, require_write_transaction


class MessageRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def create_user_text(self, identity: int, requirement_id: int, guide_run_id: int, content: str, key: str, at: str) -> sqlite3.Row:
        require_write_transaction(self.connection)
        self.connection.execute("INSERT INTO conversation_messages VALUES (?,?,?,?,'USER',?,'TEXT',NULL,NULL,?,?)",
            (identity, requirement_id, guide_run_id, message_sequence(self.connection, requirement_id), content, key, at))
        row = self.connection.execute('SELECT * FROM conversation_messages WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise ValueError('Accepted user message is missing')
        return row
