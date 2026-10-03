"""D-004 raw-source Markdown block parser and codepoint text projection.

Never renders HTML. The full document is kept separately from block spans, so
blank separators, CRLF, definitions and inert HTML cannot silently disappear.
Frontend editor parity must be proved separately with the shared fixtures.
"""
from dataclasses import dataclass
import re

from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.tasklists import tasklists_plugin
from .autolinks import install_autolinks
from .strikethrough import install_strikethrough
from .raw_source import install_raw_source

MAX_MARKDOWN_CODEPOINTS = 1_000_000
MAX_BLOCKS = 10_000
BLOCK_TYPES = frozenset({'heading', 'paragraph', 'blockquote', 'bullet_list', 'ordered_list', 'task_list', 'code_block', 'thematic_break', 'table', 'html_block', 'link_definition'})


class DocumentInvalid(ValueError):
    code = 'DOCUMENT_INVALID'


@dataclass(frozen=True)
class ParsedBlock:
    block_type: str
    markdown: str
    plain_text: str
    section_path: tuple[str, ...]
    heading_level: int | None
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class ParsedMarkdown:
    markdown: str
    blocks: tuple[ParsedBlock, ...]

    def source_parts(self) -> tuple[str, ...]:
        """All blocks and untouched gaps in order, including leading/trailing gaps."""
        parts = []
        offset = 0
        for block in self.blocks:
            parts.extend((self.markdown[offset:block.start_offset], block.markdown))
            offset = block.end_offset
        parts.append(self.markdown[offset:])
        return tuple(parts)


def _mark_task_items(state):
    # Mark before the official tasklist plugin inserts a generated checkbox.
    # Authored HTML that happens to resemble a checkbox remains inert raw text.
    for index, token in enumerate(state.tokens):
        if index >= 2 and token.type == 'inline' and state.tokens[index - 1].type == 'paragraph_open' and state.tokens[index - 2].type == 'list_item_open':
            match = re.match(r'^\[[ xX]\]([ \t\n\r]+)', token.content)
            if match:
                token.meta['walle_task_whitespace'] = len(match[1])


def _parser() -> MarkdownIt:
    parser = MarkdownIt('commonmark', {'html': True, 'inline_definitions': True, 'typographer': False})
    parser.enable(['table', 'strikethrough'])
    install_strikethrough(parser)
    install_autolinks(parser)
    install_raw_source(parser)
    parser.use(tasklists_plugin, enabled=False, label=False)
    parser.core.ruler.before('github-tasklists', 'walle-task-source', _mark_task_items)
    return parser


def _inline_text(token: Token) -> str:
    children = token.children or []
    if 'walle_task_whitespace' in token.meta:
        # Exactly the generated checkbox, then the recognized syntax whitespace.
        children = children[1:]
        pending_whitespace = token.meta['walle_task_whitespace']
    else:
        pending_whitespace = 0
    result = []
    for child in children:
        if child.type in ('text', 'code_inline', 'html_inline'):
            content = child.content
        elif child.type in ('softbreak', 'hardbreak'):
            content = '\n'
        elif child.type == 'image':
            content = _inline_text(child) if child.children else child.content
        else:
            # emphasis/link/strikethrough open/close tokens are display syntax.
            content = ''
        if pending_whitespace and content:
            count = min(pending_whitespace, len(content) - len(content.lstrip(' \t\r\n')))
            content = content[count:]
            pending_whitespace -= count
        result.append(content)
    return ''.join(result)


def _plain(tokens: list[Token], kind: str, raw: str) -> str:
    if kind in ('html_block', 'link_definition'):
        return raw
    if kind == 'thematic_break':
        return ''
    if kind == 'code_block':
        return tokens[0].content
    # Follow the actual block structure. A flat scan loses empty structural
    # children and changes tables nested inside quotes/lists into LF cells.
    def children(index: int) -> tuple[list[str], int]:
        parts = []
        while index < len(tokens):
            token = tokens[index]
            index += 1
            if token.nesting == -1:
                return parts, index
            if token.nesting == 1:
                nested, index = children(index)
                parts.append(('\t' if token.type == 'tr_open' else '\n').join(nested))
            elif token.type == 'inline':
                parts.append(_inline_text(token))
            elif token.type in ('fence', 'code_block'):
                parts.append(token.content)
            elif token.type in ('html_block', 'definition'):
                parts.append(token.meta['walle_raw_source'])
            elif token.type == 'hr':
                parts.append('')
        return parts, index

    parts, _ = children(0)
    return '\n'.join(parts)


def parse_markdown(markdown: str) -> ParsedMarkdown:
    if type(markdown) is not str:
        raise DocumentInvalid('Markdown必须为文本')
    if len(markdown) > MAX_MARKDOWN_CODEPOINTS:
        raise DocumentInvalid('完整Markdown超过容量')
    try:
        markdown.encode('utf-8', errors='strict')
    except UnicodeError:
        raise DocumentInvalid('Markdown包含非法Unicode') from None
    # Python splitlines() also splits Unicode paragraph separators; CommonMark
    # line maps use only CR/LF. These offsets preserve the original source.
    offsets = [0] + [match.end() for match in re.finditer(r'\r\n|\r|\n', markdown)]
    if offsets[-1] != len(markdown):
        offsets.append(len(markdown))
    tokens = _parser().parse(markdown, {})
    blocks = []
    headings = []
    index = 0
    previous_end = 0
    while index < len(tokens):
        first = tokens[index]
        if first.level != 0 or first.nesting < 0 or first.map is None:
            raise DocumentInvalid('解析器产生未识别的顶层区块')
        last_index = index
        if first.nesting == 1:
            while last_index + 1 < len(tokens):
                last_index += 1
                if tokens[last_index].level == 0 and tokens[last_index].nesting == -1:
                    break
            else:
                raise DocumentInvalid('解析器区块未完整闭合')
        grouped = tokens[index:last_index + 1]
        kind = {
            'heading_open': 'heading', 'paragraph_open': 'paragraph', 'blockquote_open': 'blockquote',
            'bullet_list_open': 'bullet_list', 'ordered_list_open': 'ordered_list',
            'code_block': 'code_block', 'fence': 'code_block', 'hr': 'thematic_break',
            'table_open': 'table', 'html_block': 'html_block', 'definition': 'link_definition',
        }.get(first.type)
        if first.type in ('bullet_list_open', 'ordered_list_open') and first.attrGet('class') == 'contains-task-list':
            kind = 'task_list'
        if kind is None:
            raise DocumentInvalid('解析器区块类型未注册')
        start_line, end_line = first.map
        if not 0 <= start_line < end_line < len(offsets):
            raise DocumentInvalid('解析器源位置不合法')
        if first.type in ('bullet_list_open', 'ordered_list_open'):
            # markdown-it includes following blank separator lines in a list's
            # map. Keep those outside the block, still intact in source_parts.
            while end_line > start_line + 1 and not markdown[offsets[end_line - 1]:offsets[end_line]].strip(' \t\r\n'):
                end_line -= 1
        start, end = offsets[start_line], offsets[end_line]
        if start < previous_end:
            raise DocumentInvalid('解析器顶层区块源位置重叠')
        raw = markdown[start:end]
        plain = _plain(grouped, kind, raw)
        level = int(first.tag[1:]) if kind == 'heading' else None
        if level is not None:
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, plain))
        blocks.append(ParsedBlock(kind, raw, plain, tuple(heading[1] for heading in headings), level, start, end))
        if len(blocks) > MAX_BLOCKS:
            raise DocumentInvalid('顶层区块超过容量')
        previous_end = end
        index = last_index + 1
    return ParsedMarkdown(markdown, tuple(blocks))
