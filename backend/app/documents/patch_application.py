"""Pure whole-bundle adoption. No database writes, versions or batch transitions.

Every effective patch is checked against the same original snapshot. Identities
are explicit; a final reparse proves that composition has not merged, swallowed
or reinterpreted a neighboring block. The application owns the transaction and
must bind source verification to that transaction's actual related objects.
"""
from dataclasses import dataclass, replace
import re

from backend.app.infrastructure.identifiers import block_id
from backend.app.shared.validation import MAX_SAFE_INTEGER
from .markdown import DocumentInvalid, ParsedBlock, parse_markdown
from .patch_errors import PatchInvalid
from .patch_validation import validate_combination, validate_patch, validate_bundle
from .scopes import WriteAuthority
from .snapshot import Provenance, Snapshot, SourceVerifier, _time, validate_snapshot
from .tables import RowReplacement, replace_rows, table_model


@dataclass(frozen=True)
class Adoption:
    order_no: int
    patch: dict
    decision: str
    edited_content: str | None = None


@dataclass(frozen=True)
class PatchPreview:
    """Structural composition only; no manufactured author/source metadata."""
    markdown: str
    block_ids: tuple[int, ...]
    next_block_id: int


@dataclass
class _Unit:
    identity: int
    markdown: str
    gap: str
    created: Provenance | None
    cause: Provenance | None = None
    path: tuple[str, ...] = ()
    parsed: ParsedBlock | None = None

    def __post_init__(self):
        if self.parsed is None:
            self.parsed = parse_markdown(self.markdown).blocks[0]

    def update_markdown(self, markdown: str, cause: Provenance) -> None:
        self.markdown, self.cause = markdown, cause
        self.parsed = parse_markdown(markdown).blocks[0]


def _paths(units: list[_Unit], cause: Provenance | None) -> None:
    stack = []
    for unit in units:
        block = unit.parsed
        if block.heading_level is not None:
            while stack and stack[-1][0] >= block.heading_level:
                stack.pop()
            stack.append((block.heading_level, block.plain_text))
        path = tuple(text for _, text in stack)
        if unit.path != path:
            unit.cause = cause
            unit.path = path


def _compose(units: list[_Unit], trailer: str, prior: Snapshot) -> tuple[str, tuple[int, ...]]:
    result = ''
    expected = []
    prior_ids = tuple(prior.by_id)
    adjacent = set(zip(prior_ids, prior_ids[1:]))
    original = prior.by_id
    for index, unit in enumerate(units):
        gap = unit.gap
        local = unit.parsed
        previous = units[index - 1] if index else None
        unchanged_boundary = previous is not None and (previous.identity, unit.identity) in adjacent and previous.markdown == original[previous.identity][0].markdown and unit.markdown == original[unit.identity][0].markdown
        if expected and not unchanged_boundary:
            # Retain every authored byte. Only add a boundary separator where
            # necessary; the reparse below rejects syntax that still merges.
            boundary_start = len(result)
            while boundary_start and result[boundary_start - 1] in ' \t\r\n':
                boundary_start -= 1
            boundary = result[boundary_start:] + gap + unit.markdown[:local.start_offset]
            if len(re.findall(r'\r\n|\r|\n', boundary)) < 2:
                ending = '\r\n' if result.endswith('\r\n') else '\r' if result.endswith('\r') else '\n'
                gap = ending * (2 - len(re.findall(r'\r\n|\r|\n', boundary))) + gap
        result += gap
        expected.append((len(result) + local.start_offset, local, unit.identity))
        result += unit.markdown
    result += trailer
    parsed = parse_markdown(result)
    if len(parsed.blocks) != len(expected):
        raise PatchInvalid('补丁组合不能合并或吞掉其他区块')
    for actual, (start, local, _) in zip(parsed.blocks, expected):
        # A previously unterminated last line acquires one line ending when a
        # new block follows. All its existing bytes remain exact.
        suffix = actual.markdown[len(local.markdown):] if actual.markdown.startswith(local.markdown) else None
        appended_ending = not local.markdown.endswith(('\r', '\n')) and suffix in ('\r\n', '\r', '\n')
        if actual.start_offset != start or actual.block_type != local.block_type or not (suffix == '' or appended_ending):
            raise PatchInvalid('补丁组合改变了区块边界或未授权源码')
        if actual.plain_text != local.plain_text and not (appended_ending and local.block_type in ('html_block', 'link_definition') and actual.plain_text == local.plain_text + suffix):
            raise PatchInvalid('补丁组合改变了区块解释')
    return result, tuple(identity for _, _, identity in expected)


def _apply_checked_units(snapshot: Snapshot, checked):
    """Shared exact composition; origins are absent in structural previews."""
    units = []
    offset = 0
    for identity, (block, _) in snapshot.by_id.items():
        local = replace(block, start_offset=0, end_offset=len(block.markdown))
        units.append(_Unit(identity, block.markdown, snapshot.parsed.markdown[offset:block.start_offset], None, path=block.section_path, parsed=local))
        offset = block.end_offset
    trailer = snapshot.parsed.markdown[offset:]
    next_id = snapshot.next_block_id
    inserted_after = {}
    row_edits = {}
    for patch, origin in checked:
        index = next(index for index, unit in enumerate(units) if unit.identity == patch.target_id)
        target = units[index]
        if patch.operation in ('INSERT_BEFORE', 'INSERT_AFTER'):
            identity, next_id = block_id(next_id)
            inserted = _Unit(identity, patch.proposed_markdown, '', origin, origin)
            if patch.operation == 'INSERT_BEFORE':
                inserted.gap, target.gap = target.gap, ''
                units.insert(index, inserted)
            else:
                last_id = inserted_after.get(target.identity, target.identity)
                position = next(i for i, unit in enumerate(units) if unit.identity == last_id)
                units.insert(position + 1, inserted)
                inserted_after[target.identity] = identity
        elif patch.operation == 'DELETE_BLOCK':
            units.pop(index)
            if index < len(units):
                units[index].gap = target.gap + units[index].gap
            else:
                trailer = target.gap + trailer
        else:
            if patch.operation == 'REPLACE_TABLE_ROW':
                edits = row_edits.setdefault(target.identity, [])
                edits.append(RowReplacement(patch.patch['selector_json'], patch.patch['original_content'], patch.row_cells))
                proposed = replace_rows(table_model(snapshot.by_id[target.identity][0]), tuple(edits))
            else:
                proposed = patch.proposed_markdown
            if target.markdown != proposed:
                target.update_markdown(proposed, origin)
        _paths(units, origin)
    return units, trailer, next_id


def preview_patches(snapshot: Snapshot, patches: list[dict], authority: WriteAuthority) -> PatchPreview:
    """Prove an entire candidate bundle composes, without DB/SourceVerifier.

    Only a program-validated original Snapshot is accepted upstream. This
    preview does not fabricate a future batch, source relation or BlockState,
    allocate persistent IDs, change a version or authorize C07 by itself.
    """
    checked = validate_bundle(snapshot, patches, authority)
    units, trailer, next_id = _apply_checked_units(snapshot, [(patch, None) for patch in checked])
    markdown, identities = _compose(units, trailer, snapshot)
    return PatchPreview(markdown, identities, next_id)


def apply_adoptions(snapshot: Snapshot, adoptions: list[Adoption], authority: WriteAuthority, batch_id: int, operation_time: str, source_verifier: SourceVerifier) -> Snapshot:
    """Apply accepted/edited decisions in order_no order, or return original.

    REJECTED decisions are supplied by the application as no effective patches;
    PENDING/batch status/version checks belong to that application's transaction.
    """
    if type(adoptions) is not list or len(adoptions) > 100 or any(type(item) is not Adoption for item in adoptions):
        raise PatchInvalid('采用列表结构或容量不合法')
    orders = [item.order_no for item in adoptions]
    if any(type(order) is not int or not 1 <= order <= MAX_SAFE_INTEGER for order in orders) or len(set(orders)) != len(orders):
        raise PatchInvalid('建议顺序必须为唯一正整数')
    time = _time(operation_time)
    checked = []
    for item in sorted(adoptions, key=lambda entry: entry.order_no):
        if item.decision not in ('ACCEPTED', 'EDITED') or item.decision == 'ACCEPTED' and item.edited_content is not None or item.decision == 'EDITED' and item.edited_content is None:
            raise PatchInvalid('采用决定或编辑内容不匹配')
        origin = Provenance('AI' if item.decision == 'ACCEPTED' else 'USER', 'SUGGESTION_BATCH', batch_id)
        if source_verifier(origin) is not True:
            raise DocumentInvalid('采用来源不属于当前文档')
        checked.append((validate_patch(snapshot, item.patch, authority, edited_content=item.edited_content), origin))
    validate_combination(tuple(patch for patch, _ in checked))
    if not checked:
        return snapshot
    units, trailer, next_id = _apply_checked_units(snapshot, checked)
    return _adopt_composition(snapshot, units, trailer, next_id, checked, time, source_verifier)


def apply_confirmed_facts(snapshot, patches, authority, guide_run_id, operation_time, source_verifier):
    """INITIALIZE only: caller already proves each actual user confirmation.

    No manufactured batch. The real initializer is the shared source relation.
    """
    if type(patches) is not list or len(patches) > 100:
        raise PatchInvalid('事实采用列表结构或容量不合法')
    if not patches:return snapshot
    time = _time(operation_time)
    origin = Provenance('AI', 'GUIDE_RUN', guide_run_id)
    if source_verifier(origin) is not True:
        raise DocumentInvalid('事实来源不是当前真实初始化运行')
    checked = [(patch, origin) for patch in validate_bundle(snapshot, patches, authority)]
    units, trailer, next_id = _apply_checked_units(snapshot, checked)
    return _adopt_composition(snapshot, units, trailer, next_id, checked, time, source_verifier)


def _adopt_composition(snapshot, units, trailer, next_id, checked, time, source_verifier):
    """Common metadata rules, exact bytes, identity and actual source proof."""
    markdown, identities = _compose(units, trailer, snapshot)
    if markdown == snapshot.parsed.markdown and identities == tuple(snapshot.by_id) and next_id == snapshot.next_block_id:
        return snapshot
    parsed = parse_markdown(markdown)
    metadata = []
    prior = snapshot.by_id
    for unit, block in zip(units, parsed.blocks):
        if unit.identity in prior:
            old, previous = prior[unit.identity]
            value = dict(previous)
            changed = old.markdown != block.markdown or old.section_path != block.section_path
            if changed:
                origin = unit.cause
                if origin is None:
                    # The separator may add a terminator to an insertion anchor
                    # at EOF. Attribute that boundary to its insertion operation.
                    origin = next((cause for patch, cause in reversed(checked) if patch.target_id == unit.identity and patch.operation in ('INSERT_AFTER', 'INSERT_BEFORE')), None)
                if origin is None:
                    raise PatchInvalid('未修改目标的源码或章节发生变化')
                if time < previous['last_modified_at']:
                    raise DocumentInvalid('采用事件时间不能倒退')
                value.update(origin.fields('last_modified'), last_modified_at=time)
        else:
            value = {'block_id': unit.identity, **unit.created.fields('created'), 'created_at': time, **(unit.cause or unit.created).fields('last_modified'), 'last_modified_at': time}
        value.update(block_type=block.block_type, section_path=list(block.section_path))
        metadata.append(value)
    return validate_snapshot(markdown, {'schema_version': 1, 'next_block_id': next_id, 'blocks': metadata}, source_verifier)
