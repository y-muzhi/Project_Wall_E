"""Run current V1.5 offline suites; retain only a brief Markdown result.

Capture output in memory and save the final result before console printing, so
Windows console encoding or a lost terminal cannot discard a finished result.
"""
from datetime import datetime
import os
from pathlib import Path
import re
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    paths = sorted(str(p.relative_to(root)) for p in (root/'backend/tests').rglob('test_v15*.py'))
    paths.append('backend/tests/infrastructure/test_collaboration_resources.py')
    print('Running '+str(len(paths))+' offline suite files', flush=True)
    result = subprocess.run([sys.executable, '-m', 'pytest', *paths, '-q', '-p', 'no:cacheprovider'],
        cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace',
        env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    summary = next((line.strip() for line in reversed(result.stdout.splitlines())
        if re.search(r'\d+ (passed|failed)', line)), 'No pytest summary returned')
    date = datetime.now().strftime('%Y-%m-%d')
    record = root/'docs/verification/v1.5'/('offline-suite-'+date+'.md')
    record.write_text('# V1.5 complete offline suite\n\nDate: '+date+'; code: current saved workspace.\n\n'
        'Command: `.venv\\Scripts\\python.exe tools/check-v15-offline.py`; '+str(len(paths))+' files '
        '(all test_v15*.py and test_collaboration_resources.py), no cache provider.\n\n'
        'Exit code: '+str(result.returncode)+'; actual result: `'+summary+'`.\n\n'
        'Isolated temporary databases/private delegates only. No real provider or user service/data operations. '
        'Output captured in memory; no raw log/JSON/screenshots retained. '
        'This does not establish browser or real provider acceptance.\n', encoding='utf-8')
    output = summary if result.returncode == 0 else result.stdout+result.stderr
    print(output.encode('ascii', 'backslashreplace').decode(), flush=True)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
