"""SHR-BLOCK structure, provenance and explicit identity transitions.

The caller supplies actual source relationship validation inside its transaction.
No content similarity matching, clock guessing, or repository defaults occur here.
"""
from dataclasses import dataclass
from datetime import datetime
import json
import re
from typing import Callable

from backend.app.infrastructure.identifiers import block_id as allocate_block
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.resources import FixedTemplate
from backend.app.shared.time import utc_milliseconds
from backend.app.shared.validation import MAX_SAFE_INTEGER
from .markdown import BLOCK_TYPES, DocumentInvalid, ParsedBlock, ParsedMarkdown, parse_markdown

ACTORS = frozenset({'USER', 'AI', 'SYSTEM'})
SOURCES = frozenset({'TEMPLATE', 'GUIDE_RUN', 'SUGGESTION_BATCH', 'MANUAL_EDIT'})
FIELDS = frozenset({'block_id', 'block_type', 'section_path', 'created_by_type', 'created_source_type', 'created_source_id', 'created_at', 'last_modified_by_type', 'last_modified_source_type', 'last_modified_source_id', 'last_modified_at'})


def _integer(value) -> bool:
    return type(value) is int and 1 <= value <= MAX_SAFE_INTEGER


def _time(value: str) -> str:
    if type(value) is not str or re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z', value) is None:
        raise DocumentInvalid('区块时间必须为UTC毫秒格式')
    try:
        instant = datetime.fromisoformat(value[:-1] + '+00:00')
    except ValueError:
        raise DocumentInvalid('区块时间不合法') from None
    if utc_milliseconds(instant) != value:
        raise DocumentInvalid('区块时间不合法')
    return value


@dataclass(frozen=True)
class Provenance:
    actor: str
    source_type: str
    source_id: int | None

    def __post_init__(self):
        if type(self.actor) is not str or self.actor not in ACTORS or type(self.source_type) is not str or self.source_type not in SOURCES:
            raise DocumentInvalid('区块作者或来源未登记')
        if self.source_type == 'TEMPLATE':
            if self.source_id is not None:
                raise DocumentInvalid('模板来源ID必须为空')
        elif not _integer(self.source_id):
            raise DocumentInvalid('区块来源必须有正整数ID')

    def fields(self, prefix: str) -> dict:
        return {prefix + '_by_type': self.actor, prefix + '_source_type': self.source_type, prefix + '_source_id': self.source_id}


SourceVerifier = Callable[[Provenance], bool]


@dataclass(frozen=True)
class Snapshot:
    parsed: ParsedMarkdown
    state_json: str

    @property
    def state(self) -> dict:
        return json.loads(self.state_json)

    @property
    def next_block_id(self) -> int:
        return self.state['next_block_id']

    @property
    def by_id(self) -> dict[int, tuple[ParsedBlock, dict]]:
        return {metadata['block_id']: (block, metadata) for block, metadata in zip(self.parsed.blocks, self.state['blocks'])}


def validate_snapshot(markdown: str, state: dict, source_verifier: SourceVerifier) -> Snapshot:
    parsed = parse_markdown(markdown)
    if type(state) is not dict or set(state) != {'schema_version', 'next_block_id', 'blocks'} or type(state['schema_version']) is not int or state['schema_version'] != 1:
        raise DocumentInvalid('BlockState结构不合法')
    if not _integer(state['next_block_id']) or type(state['blocks']) is not list or len(state['blocks']) != len(parsed.blocks):
        raise DocumentInvalid('BlockState未对应完整Markdown')
    try:
        encoded = canonical_input(state)
    except (ValueError, UnicodeError, RecursionError):
        raise DocumentInvalid('BlockState未满足JSON契约') from None
    if len(encoded.encode('utf-8')) > 4 * 1024 * 1024:
        raise DocumentInvalid('BlockState超过容量')
    identities = set()
    for metadata, block in zip(state['blocks'], parsed.blocks):
        if type(metadata) is not dict or set(metadata) != FIELDS:
            raise DocumentInvalid('区块元数据字段不完整或含未知字段')
        identity = metadata['block_id']
        if not _integer(identity) or identity in identities or identity >= state['next_block_id']:
            raise DocumentInvalid('区块ID重复或超过高水位')
        identities.add(identity)
        if type(metadata['block_type']) is not str or metadata['block_type'] not in BLOCK_TYPES or metadata['block_type'] != block.block_type:
            raise DocumentInvalid('区块类型未对应Markdown')
        if type(metadata['section_path']) is not list or any(type(part) is not str for part in metadata['section_path']) or metadata['section_path'] != list(block.section_path):
            raise DocumentInvalid('区块章节路径未对应Markdown')
        for prefix in ('created', 'last_modified'):
            origin = Provenance(metadata[prefix + '_by_type'], metadata[prefix + '_source_type'], metadata[prefix + '_source_id'])
            if source_verifier(origin) is not True:
                raise DocumentInvalid('区块来源对象或关系不合法')
        if _time(metadata['created_at']) > _time(metadata['last_modified_at']):
            raise DocumentInvalid('创建时间不能晚于最近修改时间')
    return Snapshot(parsed, encoded)


def create_snapshot(markdown: str, provenance: Provenance, operation_time: str, source_verifier: SourceVerifier) -> Snapshot:
    parsed = parse_markdown(markdown)
    time = _time(operation_time)
    next_id = 1
    metadata = []
    for block in parsed.blocks:
        identity, next_id = allocate_block(next_id)
        metadata.append({'block_id': identity, 'block_type': block.block_type, 'section_path': list(block.section_path), **provenance.fields('created'), 'created_at': time, **provenance.fields('last_modified'), 'last_modified_at': time})
    return validate_snapshot(markdown, {'schema_version': 1, 'next_block_id': next_id, 'blocks': metadata}, source_verifier)


def assign_identities(markdown: str, identities: list[int], next_block_id: int, prior: Snapshot, provenance: Provenance, operation_time: str, source_verifier: SourceVerifier, *, restoration_baseline: Snapshot | None = None) -> Snapshot:
    """Editor/patch mappings are explicit. Preserve creation; derive actual changes.

    Deleted IDs can return only with the same draft's retained baseline proof.
    The application must bind that baseline to the real draft context.
    """
    parsed = parse_markdown(markdown)
    if type(identities) is not list or len(identities) != len(parsed.blocks) or any(not _integer(identity) for identity in identities) or len(set(identities)) != len(identities):
        raise DocumentInvalid('身份映射必须完整且唯一')
    if not _integer(next_block_id) or next_block_id < prior.next_block_id or any(identity >= next_block_id for identity in identities):
        raise DocumentInvalid('区块高水位不能回退或覆盖已分配身份')
    time = _time(operation_time)
    previous = prior.by_id
    baseline = restoration_baseline.by_id if restoration_baseline is not None else {}
    metadata = []
    for identity, block in zip(identities, parsed.blocks):
        existing = previous.get(identity)
        restored = False
        if existing is None and identity < prior.next_block_id:
            existing = baseline.get(identity)
            restored = True
            if existing is None:
                raise DocumentInvalid('不能恢复未证明属于本草稿基线的身份')
        if existing is not None:
            old_block, old_metadata = existing
            value = dict(old_metadata)
            changed = restored or old_block.markdown != block.markdown or old_block.section_path != block.section_path
            if changed:
                if time < old_metadata['last_modified_at']:
                    raise DocumentInvalid('事件时间不能倒退')
                value.update(provenance.fields('last_modified'))
                value['last_modified_at'] = time
        else:
            value = {'block_id': identity, **provenance.fields('created'), 'created_at': time, **provenance.fields('last_modified'), 'last_modified_at': time}
        value.update(block_type=block.block_type, section_path=list(block.section_path))
        metadata.append(value)
    return validate_snapshot(markdown, {'schema_version': 1, 'next_block_id': next_block_id, 'blocks': metadata}, source_verifier)


def validate_template_lock(snapshot: Snapshot, template: FixedTemplate, locked_heading_ids: tuple[int, ...]) -> None:
    if len(locked_heading_ids) != len(template.locked_headings) or len(set(locked_heading_ids)) != len(locked_heading_ids):
        raise DocumentInvalid('初始化模板锁定身份不完整')
    locked = set(locked_heading_ids)
    actual = [(metadata['block_id'], block.heading_level, block.plain_text) for block, metadata in zip(snapshot.parsed.blocks, snapshot.state['blocks']) if metadata['block_id'] in locked]
    expected = [(identity, heading.level, heading.text) for identity, heading in zip(locked_heading_ids, template.locked_headings)]
    if actual != expected:
        raise DocumentInvalid('初始化不能删除、重排或改变模板标题及身份')


def validate_creation_inheritance(candidate: Snapshot, prior: Snapshot, *, restoration_baseline: Snapshot | None = None) -> None:
    """Call before deriving server metadata from a client's complete snapshot."""
    if candidate.next_block_id < prior.next_block_id:
        raise DocumentInvalid('区块高水位不能回退')
    known = prior.by_id
    baseline = restoration_baseline.by_id if restoration_baseline is not None else {}
    for identity, (_, metadata) in candidate.by_id.items():
        proof = known.get(identity) or baseline.get(identity)
        if proof is None:
            if identity < prior.next_block_id:
                raise DocumentInvalid('区块身份不属于本编辑基线')
            continue
        original = proof[1]
        if any(metadata[field] != original[field] for field in FIELDS if field.startswith('created_')):
            raise DocumentInvalid('已有区块创建信息不可修改')
