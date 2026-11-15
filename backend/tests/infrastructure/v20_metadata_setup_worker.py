"""Create only this owned temporary Git fixture; no production command dispatch."""

import json
import os
import subprocess
import sys
from pathlib import Path

from backend.app.infrastructure.git_bundle import BUNDLE_PARENT
from backend.tests.code_tasks.v20_git_vector_worker import owned_git_environment


def main():
    root = Path(sys.argv[1]).resolve(strict=True)
    nonce, format, *options = sys.argv[2:]
    if root != Path.cwd().resolve() or (root / '.metadata-owner').read_text() != nonce:
        raise ValueError('Exact owned metadata setup required')
    environment = owned_git_environment(root)
    environment.update(
        GIT_AUTHOR_NAME='Metadata Fixture',
        GIT_AUTHOR_EMAIL='fixture@example.invalid',
        GIT_COMMITTER_NAME='Metadata Fixture',
        GIT_COMMITTER_EMAIL='fixture@example.invalid',
        GIT_AUTHOR_DATE='2000-01-01T00:00:00 +0000',
        GIT_COMMITTER_DATE='2000-01-01T00:00:00 +0000',
    )
    program = BUNDLE_PARENT / 'win-x64/cmd/git.exe'

    def invoke(args):
        result = subprocess.run(
            [str(program), *args], cwd=root, env=environment, capture_output=True, timeout=15
        )
        if result.returncode or len(result.stdout) > 65536 or len(result.stderr) > 65536:
            raise ValueError('Owned metadata setup command failed')
        return result.stdout

    repo = root / 'repository'
    invoke(['init', '--initial-branch=main', '--object-format=' + format, str(repo)])
    with (repo / 'fixture.txt').open('xb') as stream:
        stream.write(
            b'missing expected text\n' if 'negative' in options else b'owned fixed source\n'
        )
    prefix = ['-C', str(repo)]
    invoke(prefix + ['add', 'fixture.txt'])
    if 'workspace' in options:
        (repo / 'sub').mkdir()
        with (repo / 'sub/run.bin').open('xb') as stream:
            stream.write(b'\xef\xbb\xbfraw\r\n\x00\xff')
        (repo / 'empty').touch(exist_ok=False)
        invoke(prefix + ['add', 'sub/run.bin', 'empty'])
        invoke(prefix + ['update-index', '--chmod=+x', 'sub/run.bin'])
    invoke(prefix + ['commit', '-m', 'Owned fixture'])
    invoke(prefix + ['branch', 'idle'])
    invoke(prefix + ['tag', '-a', 'v1', '-m', 'Owned annotation'])
    invoke(prefix + ['pack-refs', '--all'])
    invoke(prefix + ['branch', 'loose'])
    invoke(prefix + ['update-ref', 'refs/remotes/origin/main', 'HEAD'])
    invoke(prefix + ['symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/main'])
    invoke(prefix + ['worktree', 'add', '--detach', str(root / 'linked'), 'HEAD'])
    with (root / 'setup-result.json').open('x', encoding='utf-8') as stream:
        json.dump(
            {
                'completed': True,
                'nonce': nonce,
                'oid': invoke(prefix + ['rev-parse', 'HEAD']).decode().strip(),
            },
            stream,
        )
        stream.flush()
        os.fsync(stream.fileno())


if __name__ == '__main__':
    main()
