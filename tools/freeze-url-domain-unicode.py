"""Generate once from the selected backend's actual Unicode profile.

No network, no overwrite, no automatic regeneration during application use.
The compatibility tests compare all codepoints to the actual backend profile.
"""
import json
from pathlib import Path
import platform
import unicodedata

if unicodedata.unidata_version != '15.1.0':
    raise RuntimeError('Requires selected Python 3.13 backend Unicode 15.1.0')

ranges = []
start = None
for point in range(0x110001):
    accepted = point < 0x110000 and chr(point).isalnum()
    if accepted and start is None:
        start = point
    elif not accepted and start is not None:
        ranges.append([start, point - 1])
        start = None

target = Path(__file__).resolve().parents[1] / 'shared/markdown/url-domain-unicode-v1.json'
target.parent.mkdir(parents=True, exist_ok=True)
record = {'schema_version': 1, 'unicode_version': unicodedata.unidata_version,
          'producer': f'Python {platform.python_version()} str.isalnum; selected backend compatibility profile',
          'ranges': ranges}
with target.open('x', encoding='utf-8', newline='\n') as stream:
    stream.write(json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n')
print(json.dumps({'path': str(target), 'unicode_version': unicodedata.unidata_version, 'ranges': len(ranges)}))
