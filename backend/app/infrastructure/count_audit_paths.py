"""Private paths shared by counting and stopped recovery."""

from pathlib import Path
import re

COUNT_AUDIT_ENTRY = re.compile(r'[0-9a-f]{32}\.(?:prepared|finished)\.json')


def count_audit_root(database_path):
    base = Path(database_path).resolve()
    return base.with_name(base.name + '.count-audit')


def count_audit_name(identity, phase):
    if type(identity) is not str or type(phase) is not str:
        raise ValueError('Private count record identity')
    name = f'{identity}.{phase}.json'
    if COUNT_AUDIT_ENTRY.fullmatch(name) is None:
        raise ValueError('Private count record identity')
    return name
