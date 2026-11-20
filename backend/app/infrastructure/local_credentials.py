"""Explicit local CLI credential import; never evaluate shell/dotenv code."""

from pathlib import Path


def read_local_credential(path, *, name='WALLE_MODEL_API_KEY'):
    if name not in ('WALLE_MODEL_API_KEY', 'OPENAI_API_KEY'):
        raise ValueError('Unsupported local credential name')
    candidate = Path(path)
    if candidate.is_symlink() or candidate.stat().st_size > 65536:
        raise ValueError('Invalid local credential file')
    values = []
    for line in candidate.read_text(encoding='utf-8-sig').splitlines():
        left, separator, right = line.partition('=')
        if separator and left.strip() == name:
            value = right.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
                value = value[1:-1]
            values.append(value)
    if len(values) != 1:
        raise ValueError('Exactly one local credential assignment is required')
    value = values[0]
    if not value or len(value) > 8192 or any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise ValueError('Invalid local credential')
    return value
