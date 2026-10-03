"""Baseline validation only; no suggestion/DB writes or partial adoption.

Application/bundle application is a separate unit. Passing this module alone
does not authorize C07 adoption or mark a suggestion batch completed.
"""
from dataclasses import dataclass
from functools import lru_cache
import json

from backend.app.infrastructure.resources import ProtocolInvalid, ResourceCatalog
from backend.app.shared.validation import InvalidInput, strict_json_object
from .markdown import DocumentInvalid, ParsedBlock, parse_markdown
from .patch_errors import PatchInvalid, TargetStale
from .scopes import WriteAuthority
from .snapshot import Snapshot
from .tables import select_row, table_model, validate_cells


@dataclass(frozen=True)
class CheckedPatch:
    patch_json: str
    target_id: int
    operation: str
    proposed_markdown: str | None
    row_cells: tuple[str, ...] | None
    row_index: int | None

    @property
    def patch(self) -> dict:
        return json.loads(self.patch_json)


@lru_cache(maxsize=1)
def _protocol():
    return ResourceCatalog().freeze('MODIFY', 'USER_INSTRUCTION')


def prove_selection(old: ParsedBlock, proposed: str, selection: tuple[int, int]) -> None:
    """Closed proof: replace the minimal raw difference with a visible sentinel.

    The probe must project exactly to unchanged prefix + sentinel + unchanged
    suffix, with the removed projected range wholly inside the authorized range.
    Hidden destinations/metadata and grammar changes that cannot be proved are
    rejected. Nothing outside the minimal raw difference is rewritten.
    """
    start, end = selection
    if not 0 <= start < end <= len(old.plain_text):
        raise TargetStale('冻结选区不再对应原文')
    after = parse_markdown(proposed)
    if len(after.blocks) != 1:
        raise PatchInvalid('选区补丁必须仍为一个完整区块')
    if proposed == old.markdown:
        return
    prefix_length = 0
    while prefix_length < min(len(old.markdown), len(proposed)) and old.markdown[prefix_length] == proposed[prefix_length]:
        prefix_length += 1
    suffix_length = 0
    while suffix_length < min(len(old.markdown) - prefix_length, len(proposed) - prefix_length) and old.markdown[-suffix_length - 1] == proposed[-suffix_length - 1]:
        suffix_length += 1
    marker = 'WALLESELECTIONBOUNDARYCHECK'
    while marker in old.markdown or marker in proposed or marker in old.plain_text:
        marker += 'Z'
    tail = old.markdown[len(old.markdown) - suffix_length:] if suffix_length else ''
    probe = parse_markdown(old.markdown[:prefix_length] + marker + tail)
    if len(probe.blocks) != 1 or probe.blocks[0].plain_text.count(marker) != 1:
        raise PatchInvalid('不能证明选区外标记保持不变')
    before, _, after_text = probe.blocks[0].plain_text.partition(marker)
    removed_start, removed_end = len(before), len(old.plain_text) - len(after_text)
    if old.plain_text[:removed_start] != before or old.plain_text[removed_end:] != after_text or not start <= removed_start <= removed_end <= end:
        raise PatchInvalid('补丁修改了选区外内容或标记')
    new_text = after.blocks[0].plain_text
    if not new_text.startswith(old.plain_text[:start]) or not new_text.endswith(old.plain_text[end:]):
        raise PatchInvalid('补丁修改了选区外文本')


def validate_patch(snapshot: Snapshot, patch: dict, authority: WriteAuthority, *, edited_content: str | None = None) -> CheckedPatch:
    try:
        value = _protocol().validate_patch(patch)
    except ProtocolInvalid:
        raise PatchInvalid('补丁未满足冻结结构') from None
    identity = value['target_ref']['block_id']
    target = snapshot.by_id.get(identity)
    allowed = next((entry for entry in authority.allowed_targets if entry.block_id == identity), None)
    operation = value['patch_operation']
    if target is None or allowed is None or operation not in allowed.operations:
        raise TargetStale('目标或冻结权限未匹配')
    if edited_content is not None and (type(edited_content) is not str or not 1 <= len(edited_content) <= 100_000 or operation == 'DELETE_BLOCK'):
        raise PatchInvalid('编辑内容不符合操作类型或容量')
    block = target[0]
    row_index, row_cells = None, None
    proposed = value['proposed_markdown']
    if operation == 'REPLACE_TABLE_ROW':
        selector = value['selector_json']
        if allowed.row_selectors is not None and (selector['key_column_index'], selector['key_value']) not in allowed.row_selectors:
            raise TargetStale('表格行不在冻结授权集合')
        table = table_model(block)
        row_index = select_row(table, value['selector_json'])
        if value['original_content'] != table.rows[row_index].markdown:
            raise TargetStale('表格行原文已变化')
        data = value['proposed_data_json']
        if edited_content is not None:
            try:
                data = strict_json_object(edited_content)
            except InvalidInput:
                raise PatchInvalid('编辑行必须为单一cells JSON对象') from None
        row_cells = validate_cells(data, len(table.headers))
    else:
        if value['original_content'] != block.markdown:
            raise TargetStale('目标区块原文已变化')
        if operation != 'DELETE_BLOCK':
            proposed = edited_content if edited_content is not None else proposed
            try:
                parsed = parse_markdown(proposed)
            except DocumentInvalid:
                raise PatchInvalid('建议Markdown不合法') from None
            if len(parsed.blocks) != 1:
                raise PatchInvalid('建议必须为恰好一个顶层区块')
            if allowed.selection_range is not None:
                prove_selection(block, proposed, allowed.selection_range)
    return CheckedPatch(json.dumps(value, ensure_ascii=False, sort_keys=True), identity, operation, proposed, row_cells, row_index)


def validate_combination(patches: tuple[CheckedPatch, ...]) -> None:
    by_target = {}
    for patch in patches:
        by_target.setdefault(patch.target_id, []).append(patch)
    for entries in by_target.values():
        mutations = [entry for entry in entries if entry.operation in ('REPLACE_BLOCK', 'DELETE_BLOCK')]
        rows = [entry for entry in entries if entry.operation == 'REPLACE_TABLE_ROW']
        inserts = [entry for entry in entries if entry.operation in ('INSERT_BEFORE', 'INSERT_AFTER')]
        if len(mutations) > 1 or mutations and rows or len({entry.row_index for entry in rows}) != len(rows) or any(entry.operation == 'DELETE_BLOCK' for entry in mutations) and inserts:
            raise PatchInvalid('补丁目标或操作组合冲突')


def validate_bundle(snapshot: Snapshot, patches: list[dict], authority: WriteAuthority) -> tuple[CheckedPatch, ...]:
    if type(patches) is not list or not 1 <= len(patches) <= 100:
        raise PatchInvalid('模型建议必须为非空且不超过100项')
    checked = tuple(validate_patch(snapshot, patch, authority) for patch in patches)
    validate_combination(checked)
    return checked
