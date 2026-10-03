"""Capture inert flow source while the actual container offsets are active."""
import re

from markdown_it import MarkdownIt
from markdown_it.rules_block import html_block, reference


def install_raw_source(parser: MarkdownIt) -> None:
    def remember(state):
        # Before normalize changes CRLF/CR and NULL. Line-local character
        # offsets remain compatible with the block parser's normalized source.
        state.env['_walle_original_lines'] = re.findall(r'[^\r\n]*(?:\r\n|\r|\n|$)', state.src)
        state.env['_walle_normalized_starts'] = [0] + [match.end() for match in re.finditer(r'\r\n|\r|\n', state.src.replace('\r\n', '\n').replace('\r', '\n'))]

    parser.core.ruler.before('normalize', 'walle-original-flow-source', remember)

    def capture(rule):
        def wrapped(state, start_line, end_line, silent):
            before = len(state.tokens)
            accepted = rule(state, start_line, end_line, silent)
            if not accepted or silent:
                return accepted
            for token in state.tokens[before:]:
                if token.type not in ('html_block', 'definition') or token.map is None:
                    continue
                lines = []
                for line in range(*token.map):
                    first = line_start = state.bMarks[line]
                    indent = 0
                    # Same indentation consumption as pinned StateBlock.getLines,
                    # including virtual spaces when a tab crosses the boundary.
                    while first < state.eMarks[line] and indent < state.blkIndent:
                        char = state.src[first]
                        if char == '\t':
                            indent += 4 - (indent + state.bsCount[line]) % 4
                        elif char == ' ' or first - line_start < state.tShift[line]:
                            indent += 1
                        else:
                            break
                        first += 1
                    prefix = ' ' * max(0, indent - state.blkIndent)
                    if token.type == 'definition' and line == token.map[0]:
                        first = state.bMarks[line] + state.tShift[line]
                        prefix = ''
                    original = state.env['_walle_original_lines'][line]
                    offset = first - state.env['_walle_normalized_starts'][line]
                    lines.append(prefix + original[offset:])
                token.meta['walle_raw_source'] = ''.join(lines)
            return accepted
        return wrapped

    parser.block.ruler.at('html_block', capture(html_block))
    parser.block.ruler.at('reference', capture(reference))
