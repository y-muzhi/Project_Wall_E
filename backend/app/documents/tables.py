"""GFM row selection and plain-cell replacement; never replaces a whole table."""
from dataclasses import dataclass
import html
import re

from .markdown import ParsedBlock, _inline_text, _parser, parse_markdown
from .patch_errors import PatchInvalid, TargetStale


@dataclass(frozen=True)
class TableRow:
    cells: tuple[str, ...]
    markdown: str
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class Table:
    markdown: str
    headers: tuple[str, ...]
    rows: tuple[TableRow, ...]


@dataclass(frozen=True)
class RowReplacement:
    selector: dict
    original_content: str
    cells: tuple[str, ...]


def table_model(block: ParsedBlock) -> Table:
    if block.block_type != 'table':
        raise PatchInvalid('行补丁只能应用于表格')
    offsets = [0] + [match.end() for match in re.finditer(r'\r\n|\r|\n', block.markdown)]
    if offsets[-1] != len(block.markdown):
        offsets.append(len(block.markdown))
    tokens = _parser().parse(block.markdown, {})
    header = None
    rows = []
    position = None
    cells = []
    for token in tokens:
        if token.type == 'tr_open':
            position = token.map
            cells = []
        elif token.type == 'inline' and position is not None:
            cells.append(_inline_text(token))
        elif token.type == 'tr_close':
            if position is None:
                raise PatchInvalid('表格行位置不完整')
            if header is None:
                header = tuple(cells)
            else:
                start, end = offsets[position[0]], offsets[position[1]]
                rows.append(TableRow(tuple(cells), block.markdown[start:end], start, end))
            position = None
    if not header or any(len(row.cells) != len(header) for row in rows):
        raise PatchInvalid('表头与数据列不完整')
    return Table(block.markdown, header, tuple(rows))


def select_row(table: Table, selector: dict) -> int:
    if type(selector) is not dict or set(selector) != {'key_column_index', 'key_value'} or type(selector['key_column_index']) is not int or selector['key_column_index'] != 0 or type(selector['key_value']) is not str:
        raise PatchInvalid('行选择条件必须使用第0列的精确文本键')
    matches = [index for index, row in enumerate(table.rows) if row.cells[0] == selector['key_value']]
    if len(matches) != 1:
        raise TargetStale('表格键不能唯一定位原行')
    return matches[0]


def validate_cells(value: dict, columns: int) -> tuple[str, ...]:
    if type(value) is not dict or set(value) != {'cells'} or type(value['cells']) is not list or len(value['cells']) != columns or any(type(cell) is not str for cell in value['cells']):
        raise PatchInvalid('行内容必须只含与表头等长的文本cells数组')
    cells = tuple(value['cells'])
    if sum(len(cell) for cell in cells) > 100_000 or any('\r' in cell or '\n' in cell for cell in cells):
        raise PatchInvalid('GFM纯文本单元格不能含换行或超过容量')
    try:
        for cell in cells:
            cell.encode('utf-8', errors='strict')
    except UnicodeError:
        raise PatchInvalid('单元格包含非法Unicode') from None
    return cells


def _escape_cell(cell: str) -> str:
    # Escape literal entities/HTML before Markdown punctuation. Whitespace is
    # encoded so GFM's padding trim cannot silently alter the supplied value.
    escaped = html.escape(cell, quote=False)
    escaped = re.sub(r'([\\`*{}\[\]()#+.!_>|~\-])', r'\\\1', escaped)
    return escaped.replace(' ', '&#32;').replace('\t', '&#9;')


def replace_rows(table: Table, replacements: tuple[RowReplacement, ...]) -> str:
    by_index = {}
    for replacement in replacements:
        index = select_row(table, replacement.selector)
        if index in by_index:
            raise PatchInvalid('同一基线行不能重复修改')
        row = table.rows[index]
        if type(replacement.original_content) is not str or replacement.original_content != row.markdown:
            raise TargetStale('表格行原文已变化')
        cells = validate_cells({'cells': list(replacement.cells)}, len(table.headers))
        ending = '\r\n' if row.markdown.endswith('\r\n') else '\n' if row.markdown.endswith('\n') else '\r' if row.markdown.endswith('\r') else ''
        by_index[index] = '| ' + ' | '.join(_escape_cell(cell) for cell in cells) + ' |' + ending
    result = table.markdown
    for index in sorted(by_index, reverse=True):
        row = table.rows[index]
        result = result[:row.start_offset] + by_index[index] + result[row.end_offset:]
    # Independently reparse: exact requested plain cells must survive escaping,
    # and the table must not split or gain/drop rows. No silent data correction.
    parsed = parse_markdown(result)
    if len(parsed.blocks) != 1 or parsed.blocks[0].block_type != 'table':
        raise PatchInvalid('替换行不能改变表格结构')
    after = table_model(parsed.blocks[0])
    if after.headers != table.headers or len(after.rows) != len(table.rows):
        raise PatchInvalid('替换行不能改变表头或行数')
    for replacement in replacements:
        index = select_row(table, replacement.selector)
        if after.rows[index].cells != replacement.cells:
            raise PatchInvalid('单元格文本不能无损表示为GFM行')
    return result
