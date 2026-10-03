"""Server-derived focus/read ranges and write authority (SHR-SCOPE/D-004)."""
from dataclasses import dataclass
import json

from backend.app.shared.validation import MAX_SAFE_INTEGER
from .anchors import AnchorInvalid, locate
from .snapshot import Snapshot

OPERATIONS = ('REPLACE_BLOCK', 'INSERT_BEFORE', 'INSERT_AFTER', 'DELETE_BLOCK', 'REPLACE_TABLE_ROW')


class ScopeInvalid(ValueError):
    code = 'SCOPE_INVALID'


@dataclass(frozen=True)
class AllowedTarget:
    block_id: int
    operations: tuple[str, ...]
    selection_range: tuple[int, int] | None

    def as_dict(self) -> dict:
        return {'block_id': self.block_id, 'operations': list(self.operations), 'selection_range': None if self.selection_range is None else {'start_offset': self.selection_range[0], 'end_offset': self.selection_range[1]}, 'row_selectors': None}


@dataclass(frozen=True)
class ResolvedScope:
    scope_type: str
    input_ref_json: str
    context_scope_json: str
    focus_ids: tuple[int, ...]
    required_read_ids: tuple[int, ...]
    read_ids: tuple[int, ...]
    allowed_targets: tuple[AllowedTarget, ...]

    @property
    def input_ref(self) -> dict | None:
        return json.loads(self.input_ref_json)

    @property
    def context_scope(self) -> dict:
        return json.loads(self.context_scope_json)

    @property
    def targets_json(self) -> list[dict]:
        return [target.as_dict() for target in self.allowed_targets]


def resolve_scope(snapshot: Snapshot, action_type: str, scope_type: str, scope_ref: dict | None = None) -> ResolvedScope:
    if type(action_type) is not str or action_type not in ('INITIALIZE', 'ASK', 'REVIEW', 'MODIFY'):
        raise ScopeInvalid('动作未登记')
    if type(scope_type) is not str or scope_type not in ('DOCUMENT', 'SECTION', 'BLOCK', 'SELECTION'):
        raise ScopeInvalid('范围未登记')
    pairs = list(snapshot.by_id.items())
    selection = None
    if scope_type == 'DOCUMENT':
        if scope_ref is not None:
            raise ScopeInvalid('全文范围不能带区块引用')
        start, end = 0, len(pairs)
        context_ref = None
    else:
        fields = {'block_id', 'selected_text', 'prefix_text', 'suffix_text'} if scope_type == 'SELECTION' else {'block_id'}
        if type(scope_ref) is not dict or set(scope_ref) != fields:
            raise ScopeInvalid('范围引用字段不完整或含未知字段')
        identity = scope_ref['block_id']
        if type(identity) is not int or not 1 <= identity <= MAX_SAFE_INTEGER:
            raise ScopeInvalid('范围区块身份不合法')
        start = next((index for index, (block_id, _) in enumerate(pairs) if block_id == identity), None)
        if start is None:
            raise ScopeInvalid('范围区块不存在')
        end = start + 1
        if scope_type == 'SECTION':
            heading = pairs[start][1][0]
            if heading.block_type != 'heading':
                raise ScopeInvalid('章节范围必须引用标题身份')
            while end < len(pairs):
                following = pairs[end][1][0]
                if following.heading_level is not None and following.heading_level <= heading.heading_level:
                    break
                end += 1
            context_ref = {'heading_block_id': identity}
        else:
            context_ref = dict(scope_ref)
        if scope_type == 'SELECTION':
            try:
                location = locate(snapshot, 'SELECTION', identity, {key: scope_ref[key] for key in fields if key != 'block_id'})
            except AnchorInvalid:
                raise ScopeInvalid('选区结构不合法') from None
            if not location.attached:
                raise ScopeInvalid('选区不能在原区块唯一定位')
            selection = location.start_offset, location.end_offset
    focus = {identity for identity, _ in pairs[start:end]}
    required = set(focus)
    # Heading identities follow actual nesting positions, never title text
    # matching; duplicate heading names cannot select another section.
    ancestors = []
    for index, (identity, (block, _)) in enumerate(pairs):
        if block.heading_level is not None:
            while ancestors and ancestors[-1][0] >= block.heading_level:
                ancestors.pop()
            ancestors.append((block.heading_level, identity))
        if start <= index < end:
            required.update(identity for _, identity in ancestors)
    read = set(required)
    if scope_type != 'DOCUMENT':
        read.update(identity for identity, _ in pairs[max(0, start - 2):min(len(pairs), end + 2)])
    targets = []
    if action_type in ('INITIALIZE', 'MODIFY'):
        for index in range(start, end):
            identity, (block, _) = pairs[index]
            if scope_type == 'SELECTION':
                operations = ('REPLACE_BLOCK',)
            else:
                operations = tuple(operation for operation in OPERATIONS if operation != 'REPLACE_TABLE_ROW' or block.block_type == 'table')
                if scope_type == 'SECTION' and index == start:
                    # Inserting before this heading is outside the section.
                    operations = tuple(operation for operation in operations if operation != 'INSERT_BEFORE')
            targets.append(AllowedTarget(identity, operations, selection))
    in_order = lambda identities: tuple(identity for identity, _ in pairs if identity in identities)
    return ResolvedScope(scope_type, json.dumps(scope_ref, ensure_ascii=False), json.dumps({'scope_type': scope_type, 'scope_ref': context_ref}, ensure_ascii=False), in_order(focus), in_order(required), in_order(read), tuple(targets))
