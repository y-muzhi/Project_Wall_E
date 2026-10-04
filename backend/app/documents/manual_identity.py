"""D-009 identity proofs from actual successful saves, bound to one live draft."""
import sqlite3

from backend.app.infrastructure.identifiers import require_write_transaction
from backend.app.shared.validation import strict_json_object, MAX_SAFE_INTEGER
from .markdown import DocumentInvalid, BLOCK_TYPES
from .snapshot import FIELDS, Provenance, Snapshot, SourceVerifier, _time, validate_snapshot

CREATION_FIELDS = tuple(field for field in FIELDS if field.startswith('created_'))


class ManualIdentityProofs:
    def __init__(self, connection: sqlite3.Connection, draft_id: int):
        require_write_transaction(connection)
        self.connection = connection
        self.draft_id = draft_id

    def baseline(self, source_verifier: SourceVerifier) -> dict[int, dict]:
        row = self.connection.execute('SELECT baseline_block_state_json FROM manual_draft_context WHERE draft_id=?', (self.draft_id,)).fetchone()
        if row is None:
            raise ValueError('Actual draft baseline is absent')
        state = strict_json_object(row[0], 'stored_baseline')
        if set(state) != {'schema_version', 'next_block_id', 'blocks'} or type(state['schema_version']) is not int or state['schema_version'] != 1 or type(state['next_block_id']) is not int or not 1 <= state['next_block_id'] <= MAX_SAFE_INTEGER or type(state['blocks']) is not list or len(state['blocks']) > 10000:
            raise ValueError('Stored baseline shape is invalid')
        result = {}
        self.baseline_next = state['next_block_id']
        for metadata in state['blocks']:
            if type(metadata) is not dict or set(metadata) != FIELDS or type(metadata['block_id']) is not int or not 1 <= metadata['block_id'] < state['next_block_id'] or metadata['block_id'] in result or metadata['block_type'] not in BLOCK_TYPES or type(metadata['section_path']) is not list or any(type(part) is not str for part in metadata['section_path']):
                raise ValueError('Stored baseline identities are invalid')
            for prefix in ('created', 'last_modified'):
                if source_verifier(Provenance(metadata[prefix+'_by_type'], metadata[prefix+'_source_type'], metadata[prefix+'_source_id'])) is not True:
                    raise ValueError('Stored baseline source is invalid')
            if _time(metadata['created_at']) > _time(metadata['last_modified_at']):
                raise ValueError('Stored baseline chronology is invalid')
            result[metadata['block_id']] = metadata
        return result

    def verify_persisted(self, prior: Snapshot, baseline: dict[int, dict], at: str) -> None:
        next_id = self.baseline_next
        for row in self.connection.execute('SELECT start_block_id,end_block_id,observed_at FROM manual_block_allocation_ranges WHERE draft_id=? ORDER BY start_block_id', (self.draft_id,)):
            if row['start_block_id'] != next_id or _time(row['observed_at']) > at:
                raise ValueError('Persisted allocation intervals do not prove the high water mark')
            next_id = row['end_block_id']
        if next_id != prior.next_block_id:
            raise ValueError('Persisted high water mark lacks allocation proof')
        for identity, (_, metadata) in prior.by_id.items():
            proof = baseline.get(identity)
            if proof is None:
                row = self.connection.execute('SELECT created_by_type,created_source_type,created_source_id,created_at FROM manual_block_origins WHERE draft_id=? AND block_id=?', (self.draft_id, identity)).fetchone()
                proof = dict(row) if row is not None else None
            if proof is None or any(metadata[field] != proof[field] for field in CREATION_FIELDS):
                raise ValueError('Persisted visible identity lacks its immutable creation proof')

    def derive(self, candidate: Snapshot, prior: Snapshot, baseline: dict[int, dict], at: str, source_verifier: SourceVerifier) -> Snapshot:
        if candidate.next_block_id < prior.next_block_id:
            raise DocumentInvalid('区块高水位不能回退')
        if candidate.next_block_id > prior.next_block_id:
            self.connection.execute('INSERT INTO manual_block_allocation_ranges VALUES (?,?,?,?)', (self.draft_id, prior.next_block_id, candidate.next_block_id, at))
        previous = prior.by_id
        provenance = Provenance('USER', 'MANUAL_EDIT', self.draft_id)
        output = []
        for block, incoming in zip(candidate.parsed.blocks, candidate.state['blocks']):
            identity = incoming['block_id']
            old = previous.get(identity)
            origin = self.connection.execute('SELECT created_by_type,created_source_type,created_source_id,created_at FROM manual_block_origins WHERE draft_id=? AND block_id=?', (self.draft_id, identity)).fetchone()
            creation = old[1] if old else baseline.get(identity) or (dict(origin) if origin is not None else None)
            if creation is not None:
                if any(incoming[field] != creation[field] for field in CREATION_FIELDS):
                    raise DocumentInvalid('已有区块创建信息不可修改')
            else:
                if any(incoming[field] != value for field, value in provenance.fields('created').items()):
                    raise DocumentInvalid('新身份必须属于本人工编辑会话')
                allocated = self.connection.execute('SELECT observed_at FROM manual_block_allocation_ranges WHERE draft_id=? AND start_block_id<=? AND ?<end_block_id', (self.draft_id, identity, identity)).fetchall()
                if len(allocated) != 1:
                    raise DocumentInvalid('身份没有本草稿的分配证明')
                born = _time(allocated[0]['observed_at'])
                creation = {**provenance.fields('created'), 'created_at': born}
                self.connection.execute('INSERT INTO manual_block_origins VALUES (?,?,?,?,?,?)', (self.draft_id, identity, creation['created_by_type'], creation['created_source_type'], creation['created_source_id'], born))
            unchanged = old is not None and old[0].markdown == block.markdown and old[0].section_path == block.section_path
            if unchanged:
                value = dict(old[1])
            else:
                if at < creation['created_at'] or old is not None and at < old[1]['last_modified_at']:
                    raise DocumentInvalid('事件时间不能倒退')
                value = {'block_id': identity, **{field: creation[field] for field in CREATION_FIELDS}, **provenance.fields('last_modified'), 'last_modified_at': at}
            value.update(block_type=block.block_type, section_path=list(block.section_path))
            output.append(value)
        return validate_snapshot(candidate.parsed.markdown, {'schema_version': 1, 'next_block_id': candidate.next_block_id, 'blocks': output}, source_verifier)
