"""Independent fixed Git parser peer, confined to this fresh test's original copy."""

import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def main():
    if len(sys.argv) != 4:
        raise ValueError('Explicit owned root, nonce and private copy required')
    root = Path(sys.argv[1]).resolve(strict=True)
    nonce = sys.argv[2]
    config = Path(sys.argv[3]).resolve(strict=True)
    if (
        root != Path.cwd().resolve()
        or re.fullmatch('[0-9a-f]{32}', nonce) is None
        or (root / '.walle-config-owner').read_text(encoding='ascii') != nonce
        or config.parent != root.parent / 'private'
        or re.fullmatch('git-config-[0-9a-f]{32}', config.name) is None
    ):
        raise ValueError('Original test scope differs')
    helpers = runpy.run_path(str(ROOT / 'backend/tests/code_tasks/v20_git_vector_worker.py'))
    environment = helpers['owned_git_environment'](root)
    program = ROOT / 'backend/runtime/git/2.56.0.windows.4/win-x64/cmd/git.exe'

    def invoke(arguments):
        result = subprocess.run(
            [str(program), *arguments], cwd=root, env=environment, capture_output=True, timeout=15
        )
        if len(result.stdout) > 4096 or len(result.stderr) > 65536:
            raise ValueError('Owned parse output exceeded bound')
        return result

    result = {'completed': False, 'run_nonce': nonce}
    step = 'VERSION'
    try:
        version = invoke(['--version'])
        if version.returncode or version.stdout != b'git version 2.56.0.windows.4\n':
            raise ValueError('Actual fixed version differs')
        step = 'NONREPOSITORY'
        outside = invoke(['rev-parse', '--is-inside-work-tree'])
        if outside.returncode != 128 or outside.stdout:
            raise ValueError('Owned parser cwd must not discover a repository')
        step = 'PARSE'
        parsed = invoke(['config', '--file', str(config), '--no-includes', '--null', '--list'])
        if parsed.returncode:
            raise ValueError('Owned private config parse failed')
        result.update(completed=True, wire_hex=parsed.stdout.hex(), nonrepository=True)
    except Exception as error:
        result['failure_kind'] = type(error).__name__
        result['failed_step'] = step
        raise
    finally:
        with (root / 'config-result.json').open('x', encoding='utf-8') as stream:
            json.dump(result, stream)
            stream.flush()
            os.fsync(stream.fileno())


if __name__ == '__main__':
    main()
