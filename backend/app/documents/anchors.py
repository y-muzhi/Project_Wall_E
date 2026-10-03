"""SHR-ANCHOR/D-004 pure reads. Never changes a persisted comment's status."""
from dataclasses import dataclass

from backend.app.shared.validation import InvalidInput, MAX_SAFE_INTEGER, prefix_text, selected_text, suffix_text
from .snapshot import Snapshot


class AnchorInvalid(ValueError):
    code = 'ANCHOR_INVALID'


@dataclass(frozen=True)
class Location:
    block_id: int | None
    start_offset: int | None
    end_offset: int | None

    @property
    def attached(self) -> bool:
        return self.block_id is not None

    def as_dict(self) -> dict:
        return {'block_id': self.block_id, 'start_offset': self.start_offset, 'end_offset': self.end_offset}


ORPHANED = Location(None, None, None)


def validate_anchor(anchor_type: str, block_id: int, anchor_ref: dict) -> None:
    if type(block_id) is not int or not 1 <= block_id <= MAX_SAFE_INTEGER or type(anchor_ref) is not dict:
        raise AnchorInvalid('锚点结构不合法')
    if anchor_type == 'BLOCK':
        if set(anchor_ref) != {'block_markdown_snapshot'} or type(anchor_ref['block_markdown_snapshot']) is not str:
            raise AnchorInvalid('完整区块锚点必须保留创建原文')
    elif anchor_type == 'SELECTION':
        if set(anchor_ref) != {'selected_text', 'prefix_text', 'suffix_text'}:
            raise AnchorInvalid('选区锚点必须保留原文与紧邻上下文')
        try:
            selected_text(anchor_ref['selected_text'])
            prefix_text(anchor_ref['prefix_text'])
            suffix_text(anchor_ref['suffix_text'])
        except InvalidInput:
            raise AnchorInvalid('选区锚点文本不合法') from None
    else:
        raise AnchorInvalid('锚点类型未登记')


def locate(snapshot: Snapshot, anchor_type: str, block_id: int, anchor_ref: dict) -> Location:
    validate_anchor(anchor_type, block_id, anchor_ref)
    current = snapshot.by_id.get(block_id)
    if current is None:
        return ORPHANED
    if anchor_type == 'BLOCK':
        return Location(block_id, None, None)
    text = current[0].plain_text
    selection, prefix, suffix = (anchor_ref[key] for key in ('selected_text', 'prefix_text', 'suffix_text'))
    candidates = []
    position = 0
    while True:
        start = text.find(selection, position)
        if start == -1:
            break
        end = start + len(selection)
        if start >= len(prefix) and text[start - len(prefix):start] == prefix and text[end:end + len(suffix)] == suffix:
            candidates.append((start, end))
            if len(candidates) > 1:
                return ORPHANED
        # Overlapping occurrences are real alternatives too (e.g. aa in aaa).
        position = start + 1
    return Location(block_id, *candidates[0]) if candidates else ORPHANED


def create_block_anchor(snapshot: Snapshot, block_id: int) -> dict:
    current = snapshot.by_id.get(block_id)
    if current is None:
        raise AnchorInvalid('区块不存在')
    return {'block_markdown_snapshot': current[0].markdown}


def create_selection_anchor(snapshot: Snapshot, block_id: int, anchor_ref: dict) -> dict:
    if not locate(snapshot, 'SELECTION', block_id, anchor_ref).attached:
        raise AnchorInvalid('选区不能在原区块内唯一定位')
    return dict(anchor_ref)
