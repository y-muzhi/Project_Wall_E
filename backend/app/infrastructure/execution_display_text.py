"""Bounded user-visible text from observed execution, with credential filtering."""

import re
from unicodedata import category

_CREDENTIAL_SHAPE = re.compile(
    r'-----BEGIN [^-\n]{0,48}PRIVATE KEY-----'
    r'|\b(?:authorization|proxy-authorization|cookie|set-cookie)\s*["\x27]?\s*[:=]'
    r'|\b(?:[a-z0-9]{1,32}[_-]){0,8}(?:password|passphrase|credential|secret|api[_ -]?key|token)'
    r'(?:[_-][a-z0-9]{1,32}){0,8}\s*["\x27]?\s*[:=]'
    r'|\b(?:bearer|basic)\s+[a-z0-9+/_=-]{8,}'
    r'|\b(?:sk[-_]|ghp_|github_pat_|xox[bp]-)[a-z0-9_-]{8,}'
    r'|https?://[^\s/@:]+:[^\s/@]+@'
    r'|\b[A-Za-z]:[\\/]|\\\\[^\s\\]+\\'
    r'|/(?:home|Users|root|tmp|var/tmp|private/var|run/user)/',
    re.IGNORECASE,
)
UNAVAILABLE_EXECUTION_TEXT = '此原生记录的内容不可安全显示。'


def execution_display_text(value, *, max_bytes):
    try:
        if (
            type(value) is str
            and bool(value.strip())
            and len(value.encode('utf-8')) <= max_bytes
            and not any(category(char) in ('Cc', 'Cf') and char not in '\n\r\t' for char in value)
            and _CREDENTIAL_SHAPE.search(value) is None
        ):
            return value
    except UnicodeError:
        pass
    return UNAVAILABLE_EXECUTION_TEXT
