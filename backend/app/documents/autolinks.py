"""D-004/GFM literal autolinks, before emphasis/entity parsing.

Candidate indexing is linear in the original inline source. URL paths are
matched lazily at actual parser positions, so nested-looking URLs in a long
path are not repeatedly scanned. No fuzzy bare-domain recognition occurs.
"""
from bisect import bisect_right
from dataclasses import dataclass
import re

from markdown_it import MarkdownIt
from markdown_it.rules_inline import image

ATEXT = frozenset('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.+_-')
DOMAIN = ATEXT - {'+'}
RESOURCE = frozenset('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.@')
SPACE = frozenset(' \t\r\n\v\f')
PREFIX = re.compile(r'https?://|www\.|mailto:|xmpp:', re.IGNORECASE | re.ASCII)
PUNCTUATION = frozenset('?!.,:*_~')


@dataclass(frozen=True)
class LiteralLink:
    start: int
    end: int
    text: str
    href: str


def _email_end(source: str, at: int) -> int | None:
    end = at + 1
    dot = False
    segment = False
    while end < len(source):
        char = source[end]
        if char in DOMAIN and char != '.':
            segment = True
            end += 1
        elif char == '.' and segment and end + 1 < len(source) and source[end + 1] in DOMAIN - {'.'}:
            dot = True
            segment = False
            end += 1
        else:
            break
    if not dot or not segment or source[end - 1] in '-_':
        return None
    return end


class AutolinkIndex:
    def __init__(self, source: str):
        self.source = source
        self.emails = {}
        starts = {match.start() for match in PREFIX.finditer(source)}
        for at in (match.start() for match in re.finditer('@', source)):
            start = at
            while start and source[start - 1] in ATEXT:
                start -= 1
            if start == at:
                continue
            end = _email_end(source, at)
            if end is not None:
                self.emails[start] = end
                starts.add(start)
        self.starts = sorted(starts)

    def match(self, start: int, maximum: int, previous: str | None) -> LiteralLink | None:
        source = self.source
        prefix = PREFIX.match(source, start, maximum)
        if prefix:
            protocol = prefix[0].lower()
            if protocol.startswith(('http', 'www')):
                if previous is not None and previous not in SPACE and previous not in '*_~(':
                    return None
                domain_start = start if protocol == 'www.' else prefix.end()
                domain_end = domain_start
                while domain_end < maximum and source[domain_end] in DOMAIN:
                    domain_end += 1
                domain = source[domain_start:domain_end].rstrip('.')
                labels = domain.split('.')
                if len(labels) < 2 or any(not label for label in labels) or any('_' in label for label in labels[-2:]):
                    return None
                end = domain_end
                while end < maximum and source[end] not in SPACE and source[end] != '<':
                    end += 1
                excess = source[start:end].count(')') - source[start:end].count('(')
                while end > domain_start:
                    if source[end - 1] in PUNCTUATION:
                        end -= 1
                    elif source[end - 1] == ')' and excess > 0:
                        end -= 1
                        excess -= 1
                    elif source[end - 1] == ';':
                        amp = end - 1
                        while amp > start and source[amp - 1] in RESOURCE - {'.', '@'}:
                            amp -= 1
                        if amp < end - 1 and amp > start and source[amp - 1] == '&':
                            end = amp - 1
                        else:
                            break
                    else:
                        break
                text = source[start:end].replace('\0', '\ufffd')
                if end < domain_start + len(domain):
                    return None
                return LiteralLink(start, end, text, ('http://' if protocol == 'www.' else '') + text)
            if previous is not None and (previous in ATEXT or previous == '/'):
                return None
            email_start = prefix.end()
            end = self.emails.get(email_start)
            if end is None or end > maximum:
                return None
            if protocol == 'xmpp:' and end < maximum and source[end] == '/':
                resource_end = end + 1
                while resource_end < maximum and source[resource_end] in RESOURCE:
                    resource_end += 1
                if resource_end > end + 1:
                    end = resource_end
            text = source[start:end]
            return LiteralLink(start, end, text, text)
        end = self.emails.get(start)
        if end is None or end > maximum or previous is not None and (previous in ATEXT or previous == '/'):
            return None
        text = source[start:end]
        return LiteralLink(start, end, text, 'mailto:' + text)


def _index(state) -> AutolinkIndex:
    index = getattr(state, '_walle_autolinks', None)
    if index is None:
        index = AutolinkIndex(state.src)
        state._walle_autolinks = index
    return index


def _literal(state, silent: bool) -> bool:
    if state.linkLevel or state.env.get('_walle_image_label', 0):
        return False
    link = _index(state).match(state.pos, state.posMax, state.src[state.pos - 1] if state.pos else None)
    if link is None or not state.md.validateLink(link.href):
        return False
    if not silent:
        token = state.push('link_open', 'a', 1)
        token.attrs = {'href': link.href}
        token.info = 'auto'
        token.markup = 'walle_literal_autolink'
        state.push('text', '', 0).content = link.text
        token = state.push('link_close', 'a', -1)
        token.info = 'auto'
        token.markup = 'walle_literal_autolink'
    state.pos = link.end
    return True


def _text(state, silent: bool) -> bool:
    index = _index(state)
    next_index = bisect_right(index.starts, state.pos)
    candidate = index.starts[next_index] if next_index < len(index.starts) else state.posMax
    terminator = state.md.inline.terminator_re.search(state.src, state.pos, min(candidate, state.posMax))
    end = min(candidate, terminator.start() if terminator else state.posMax, state.posMax)
    if end == state.pos:
        return False
    if not silent:
        state.pending += state.src[state.pos:end]
    state.pos = end
    return True


def _image(state, silent: bool) -> bool:
    previous = state.env.get('_walle_image_label', 0)
    state.env['_walle_image_label'] = previous + 1
    try:
        return image(state, silent)
    finally:
        if previous:
            state.env['_walle_image_label'] = previous
        else:
            state.env.pop('_walle_image_label', None)


def install_autolinks(parser: MarkdownIt) -> None:
    parser.inline.ruler.before('text', 'walle_literal_autolink', _literal)
    parser.inline.ruler.at('text', _text)
    parser.inline.ruler.at('image', _image)
