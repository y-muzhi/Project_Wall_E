"""Owned fixed-Git location vectors; all repositories and output are temporary."""

import json
import os
from pathlib import Path
import subprocess
import sys

from backend.app.infrastructure.git_bundle import BUNDLE_PARENT
from backend.app.infrastructure.git_config_command import ConfigParseCommand
from backend.app.infrastructure.git_local_config import validate_local_config_output
from backend.app.infrastructure.git_repository_location import RepositoryLocationLease
from backend.app.infrastructure.windows_config_copy import PrivateConfigCopy
from backend.app.infrastructure.windows_config_source import LockedConfigSource
from backend.app.infrastructure.windows_private_package import (
    create_private_package,
    PrivatePackageGuard,
)
from backend.tests.code_tasks.v20_git_vector_worker import owned_git_environment


def main():
    root = Path(sys.argv[1]).resolve(strict=True)
    nonce = sys.argv[2]
    if (
        root != Path.cwd().resolve()
        or (root / '.location-owner').read_text(encoding='ascii') != nonce
    ):
        raise ValueError('Exact owned location test root required')
    environment = owned_git_environment(root)
    environment.update(
        GIT_AUTHOR_NAME='Location Fixture',
        GIT_AUTHOR_EMAIL='fixture@example.invalid',
        GIT_COMMITTER_NAME='Location Fixture',
        GIT_COMMITTER_EMAIL='fixture@example.invalid',
        GIT_AUTHOR_DATE='2000-01-01T00:00:00 +0000',
        GIT_COMMITTER_DATE='2000-01-01T00:00:00 +0000',
    )
    program = BUNDLE_PARENT / 'win-x64/cmd/git.exe'

    def invoke(arguments):
        result = subprocess.run(
            [str(program), *arguments], cwd=root, env=environment, capture_output=True, timeout=15
        )
        if result.returncode or len(result.stdout) > 65536 or len(result.stderr) > 65536:
            raise ValueError('Owned Git fixture command failed')
        return result.stdout

    result = {'completed': False, 'run_nonce': nonce, 'layouts': []}
    step = 'VERSION'
    try:
        if invoke(['--version']) != b'git version 2.56.0.windows.4\n':
            raise ValueError('Actual fixed version differs')
        private = create_private_package(root / 'private')
        empty = private / 'empty.config'
        empty.open('xb').close()
        for format in ('sha1', 'sha256'):
            step = format + '.INIT'
            main_root = root / (format + '-main')
            invoke(['init', '--initial-branch=main', '--object-format=' + format, str(main_root)])
            with (main_root / 'fixture.txt').open('xb') as stream:
                stream.write(b'fixed owned input\n')
            invoke(['-C', str(main_root), 'add', 'fixture.txt'])
            invoke(['-C', str(main_root), 'commit', '-m', 'Owned location fixture'])
            linked = root / (format + '-linked')
            invoke(['-C', str(main_root), 'worktree', 'add', '--detach', str(linked), 'HEAD'])
            bare = root / (format + '-bare.git')
            invoke(
                ['init', '--bare', '--initial-branch=main', '--object-format=' + format, str(bare)]
            )
            separate = root / (format + '-separate')
            external = root / (format + '-external.git')
            invoke(
                [
                    'init',
                    '--initial-branch=main',
                    '--object-format=' + format,
                    '--separate-git-dir=' + str(external),
                    str(separate),
                ]
            )
            for kind, path in [
                ('MAIN', main_root),
                ('LINKED', linked),
                ('BARE', bare),
                ('SEPARATE', separate),
            ]:
                step = format + '.' + kind
                with RepositoryLocationLease(
                    path,
                    private_roots=(private,),
                    max_file_bytes=65536,
                    max_open_handles=4096,
                    max_metadata_entries=4096,
                ) as location:
                    original = location.verify()
                    if original.expected_bare != (kind == 'BARE') or original.linked != (
                        kind == 'LINKED'
                    ):
                        raise ValueError('Actual repository location kind differs')
                    with (
                        location.hold(),
                        PrivatePackageGuard(private) as package,
                        LockedConfigSource(empty, max_file_bytes=4096) as global_config,
                    ):
                        with PrivateConfigCopy(location.config_source, package) as copied:
                            command = ConfigParseCommand(copied, global_config)
                            try:
                                wire = invoke(list(command.arguments()))
                                facts = validate_local_config_output(
                                    wire,
                                    expected_object_format=format,
                                    expected_bare=original.expected_bare,
                                    max_output_bytes=65536,
                                    max_entries=100,
                                )
                                if command.facts()['source']['sha256'] != original.config_sha256:
                                    raise ValueError('Original config copy binding differs')
                                if facts.object_format != format:
                                    raise ValueError('Actual config format differs')
                            finally:
                                command.close()
                    if location.verify() != original:
                        raise ValueError('Original repository location changed')
                result['layouts'].append({'format': format, 'kind': kind, 'config_verified': True})
        result['completed'] = True
    except Exception as error:
        result.update(failed_step=step, failure_kind=type(error).__name__)
        raise
    finally:
        with (root / 'location-result.json').open('x', encoding='utf-8') as stream:
            json.dump(result, stream)
            stream.flush()
            os.fsync(stream.fileno())


if __name__ == '__main__':
    main()
