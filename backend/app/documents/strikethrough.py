"""D-004/GFM 6.5: match exactly one or two tildes of the same width.

The pinned parser accepts single tildes but pairs different widths before its
postprocessor rejects them, losing possible valid matches. Separate widths
only during its real delimiter pairing, then restore the installed rule's
marker before postprocessing. No text rewriting or rendered-HTML reparsing.
"""
from markdown_it import MarkdownIt

DOUBLE_TILDE = 0x1007E  # Private pairing key; never enters source or tokens.


def _delimiter_lists(state):
    yield state.delimiters
    for meta in state.tokens_meta:
        if meta and 'delimiters' in meta:
            yield meta['delimiters']


def _separate_widths(state):
    for delimiters in _delimiter_lists(state):
        for delimiter in delimiters:
            if delimiter.marker == 0x7E and state.tokens[delimiter.token].content == '~~':
                delimiter.marker = DOUBLE_TILDE


def _restore_marker(state):
    for delimiters in _delimiter_lists(state):
        for delimiter in delimiters:
            if delimiter.marker == DOUBLE_TILDE:
                delimiter.marker = 0x7E


def install_strikethrough(parser: MarkdownIt):
    parser.options['strikethrough_single_tilde'] = True
    parser.inline.ruler2.before('balance_pairs', 'walle_strike_widths', _separate_widths)
    parser.inline.ruler2.before('strikethrough', 'walle_strike_marker', _restore_marker)
