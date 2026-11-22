"""Verify fixed Git worktree and selected commit facts for external integration."""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import selectors
import stat
import subprocess
from time import monotonic

from backend.app.infrastructure.content_manifest import git_oid
from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    absolute,
    canonical,
    decode,
    digest,
    exact,
    identity,
    protected_directory,
    read_protected,
    require,
)
from backend.app.infrastructure.environment_installation import (
    identity_record,
    sha_value,
    uuid_value,
)
from backend.app.infrastructure.git_local_config import infer_local_config_output
from backend.app.infrastructure.git_ref_protocol import branch_ref
from backend.app.infrastructure.git_worktrees import (
    decode_local_branches,
    decode_worktrees,
    validate_worktree_links,
)
from backend.app.shared.time import utc_milliseconds

INPUT_ERROR = 'MANAGEMENT_WORKSPACE_INPUT_INVALID'
REPOSITORY_ERROR = 'MANAGEMENT_REPOSITORY_UNVERIFIED'
CHECKOUT_ERROR = 'MANAGEMENT_WORKTREE_UNVERIFIED'
INPUT_CHANGED = 'MANAGEMENT_WORKSPACE_INPUT_CHANGED'
FILE_LIMIT = 128 * 1024
OUTPUT_LIMIT = 1024 * 1024
TIMEOUT = 6


@dataclass(frozen=True)
class Workspace:
    environment_id: str
    purpose: str
    path: Path
    identity: dict
    branch: str
    expected_head: str
    commit: str


@dataclass(frozen=True)
class RegisteredRepository:
    reference: str
    uid: int
    git: Path
    git_sha: str
    git_version: str
    common: Path
    identity: dict
    config_sha: str
    bare: bool
    worktrees: tuple[Workspace, ...]


def load_repository(path, expected):
    raw = read_protected(path)
    require(sha_value(expected) and digest(raw) == expected, INPUT_ERROR)
    data = exact(
        decode(raw, INPUT_ERROR),
        (
            'format_version',
            'repository_ref',
            'uid',
            'git',
            'git_sha256',
            'git_version',
            'common',
            'common_identity',
            'config_sha256',
            'bare',
            'worktrees',
        ),
        INPUT_ERROR,
    )
    require(
        type(data['format_version']) is int
        and data['format_version'] == 1
        and uuid_value(data['repository_ref'])
        and type(data['uid']) is int
        and data['uid'] > 0
        and data['uid'] == os.geteuid()
        and sha_value(data['git_sha256'])
        and sha_value(data['config_sha256'])
        and type(data['git_version']) is str
        and data['git_version'].startswith('git version ')
        and type(data['bare']) is bool
        and type(data['worktrees']) is list
        and 2 <= len(data['worktrees']) <= 32,
        INPUT_ERROR,
    )
    git = absolute(data['git'], INPUT_ERROR)
    common = absolute(data['common'], INPUT_ERROR)
    identity_record(data['common_identity'], INPUT_ERROR)
    entries = []
    for row in data['worktrees']:
        exact(
            row,
            ('environment_id', 'purpose', 'path', 'identity', 'branch', 'expected_head', 'commit'),
            INPUT_ERROR,
        )
        directory = absolute(row['path'], INPUT_ERROR)
        require(
            uuid_value(row['environment_id'])
            and row['purpose'] in ('DEVELOPMENT', 'INTEGRATION')
            and not common.is_relative_to(directory)
            and not directory.is_relative_to(common),
            INPUT_ERROR,
        )
        identity_record(row['identity'], INPUT_ERROR)
        try:
            ref = branch_ref(row['branch'])
            oid = git_oid(row['commit'], 'sha1' if len(row['commit']) == 40 else 'sha256')
            head = git_oid(
                row['expected_head'], 'sha1' if len(row['expected_head']) == 40 else 'sha256'
            )
        except (TypeError, ValueError) as error:
            raise EnvironmentFailure(INPUT_ERROR) from error
        entries.append(
            Workspace(
                row['environment_id'], row['purpose'], directory, row['identity'], ref, head, oid
            )
        )
    require(
        sum(item.purpose == 'INTEGRATION' for item in entries) == 1
        and all(
            len({getattr(item, key) for item in entries}) == len(entries)
            for key in ('environment_id', 'path', 'branch')
        )
        and len({(item.identity['device'], item.identity['inode']) for item in entries})
        == len(entries),
        INPUT_ERROR,
    )
    return RegisteredRepository(
        data['repository_ref'],
        data['uid'],
        git,
        data['git_sha256'],
        data['git_version'],
        common,
        data['common_identity'],
        data['config_sha256'],
        data['bare'],
        tuple(entries),
    )


def safe_file(path, uid, maximum):
    require(path.resolve(strict=True) == path, REPOSITORY_ERROR)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as file:
        meta = os.fstat(fd)
        require(
            stat.S_ISREG(meta.st_mode)
            and meta.st_uid == uid
            and meta.st_nlink == 1
            and not stat.S_IMODE(meta.st_mode) & 0o022,
            REPOSITORY_ERROR,
        )
        original = file.read(maximum + 1)
        require(len(original) <= maximum, REPOSITORY_ERROR)
        return original


def check_directory(path, uid, expected, error):
    require(path.resolve(strict=True) == path, error)
    meta = path.stat(follow_symlinks=False)
    require(
        stat.S_ISDIR(meta.st_mode)
        and meta.st_uid == uid
        and not stat.S_IMODE(meta.st_mode) & 0o022
        and identity(meta) == expected,
        error,
    )


def bounded_git(git, arguments):
    env = {
        'PATH': '/usr/bin:/bin',
        'LC_ALL': 'C',
        'GIT_CONFIG_NOSYSTEM': '1',
        'GIT_CONFIG_GLOBAL': '/dev/null',
        'GIT_CONFIG_SYSTEM': '/dev/null',
        'GIT_ATTR_NOSYSTEM': '1',
        'GIT_NO_LAZY_FETCH': '1',
        'GIT_NO_REPLACE_OBJECTS': '1',
        'GIT_OPTIONAL_LOCKS': '0',
        'GIT_TERMINAL_PROMPT': '0',
    }
    deadline = monotonic() + TIMEOUT
    argv = [str(git), '--no-pager', *arguments]
    with subprocess.Popen(
        argv,
        cwd='/',
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as process:
        result = bytearray()
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - monotonic()
                    require(remaining > 0 and selector.select(remaining), REPOSITORY_ERROR)
                    chunk = os.read(
                        process.stdout.fileno(), min(65536, OUTPUT_LIMIT + 1 - len(result))
                    )
                    if not chunk:
                        break
                    result.extend(chunk)
                    require(len(result) <= OUTPUT_LIMIT, REPOSITORY_ERROR)
            require(process.wait(timeout=max(0, deadline - monotonic())) == 0, REPOSITORY_ERROR)
            return bytes(result)
        except (OSError, subprocess.TimeoutExpired, EnvironmentFailure) as error:
            if process.poll() is None:
                process.kill()
            raise EnvironmentFailure(REPOSITORY_ERROR) from error


def worktree_link(repo, workspace):
    check_directory(workspace.path, repo.uid, workspace.identity, CHECKOUT_ERROR)
    pointer = workspace.path / '.git'
    try:
        raw = safe_file(pointer, repo.uid, 4096)
        require(
            raw.startswith(b'gitdir: ') and raw.count(b'\n') == 1 and raw.endswith(b'\n'),
            CHECKOUT_ERROR,
        )
        linked = absolute(raw[8:-1].decode('utf-8'), CHECKOUT_ERROR)
        require(
            linked.parent == repo.common / 'worktrees' and linked.resolve(strict=True) == linked,
            CHECKOUT_ERROR,
        )
        require(
            safe_file(linked / 'gitdir', repo.uid, 4096) == os.fsencode(pointer) + b'\n',
            CHECKOUT_ERROR,
        )
        require(safe_file(linked / 'commondir', repo.uid, 4096) == b'../..\n', CHECKOUT_ERROR)
        require(
            not (linked / 'config.worktree').exists()
            and not (linked / 'config.worktree').is_symlink(),
            CHECKOUT_ERROR,
        )
        return identity(linked.stat(follow_symlinks=False))
    except (OSError, UnicodeError) as error:
        raise EnvironmentFailure(CHECKOUT_ERROR) from error


def source_evidence(repo):
    require(os.geteuid() == repo.uid and repo.uid != 0, INPUT_ERROR)
    with protected_directory(repo.git.parent):
        git_meta = repo.git.stat(follow_symlinks=False)
        require(
            git_meta.st_uid == 0
            and stat.S_ISREG(git_meta.st_mode)
            and not stat.S_IMODE(git_meta.st_mode) & 0o022
            and repo.git.resolve(strict=True) == repo.git
            and sha256(repo.git.read_bytes()).hexdigest() == repo.git_sha,
            REPOSITORY_ERROR,
        )
    require(
        bounded_git(repo.git, ('--version',)) == repo.git_version.encode('ascii') + b'\n',
        REPOSITORY_ERROR,
    )
    check_directory(repo.common, repo.uid, repo.identity, REPOSITORY_ERROR)
    config = repo.common / 'config'
    require(digest(safe_file(config, repo.uid, FILE_LIMIT)) == repo.config_sha, REPOSITORY_ERROR)
    options = (
        '-c',
        'core.hooksPath=/dev/null',
        '-c',
        'core.fsmonitor=false',
        '-c',
        'gc.auto=0',
        '-c',
        'maintenance.auto=false',
        '-c',
        'protocol.allow=never',
    )
    parsed = bounded_git(
        repo.git, ('config', '--file', str(config), '--no-includes', '--null', '--list')
    )
    config_facts = infer_local_config_output(
        parsed, expected_bare=repo.bare, max_output_bytes=FILE_LIMIT, max_entries=256
    )

    def git(*command):
        return bounded_git(repo.git, (*options, '--git-dir=' + str(repo.common), *command))

    def observations():
        views = decode_worktrees(
            git('worktree', 'list', '--porcelain', '-z'),
            format=config_facts.object_format,
            query_exit_code=0,
            max_output_bytes=OUTPUT_LIMIT,
            platform='linux',
        )
        branches = decode_local_branches(
            git(
                'for-each-ref',
                '--format=%(refname)%00%(objectname)%00%(objecttype)%00%(symref)%00',
                'refs/heads/',
            ),
            format=config_facts.object_format,
            query_exit_code=0,
            max_output_bytes=OUTPUT_LIMIT,
        )
        return views, validate_worktree_links(views, branches)

    original_links = [worktree_link(repo, item) for item in repo.worktrees]
    listing, branches = observations()
    registered_paths = {Path(row.path): row for row in listing.entries}
    records = []
    for item in repo.worktrees:
        row = registered_paths.get(item.path)
        require(
            row is not None
            and not (row.bare or row.detached or row.prunable)
            and row.branch_ref == item.branch
            and branches.get(item.branch) == item.expected_head
            and row.head_oid == item.expected_head,
            CHECKOUT_ERROR,
        )
        git_oid(item.commit, config_facts.object_format)
        require(git('cat-file', '-t', item.commit) == b'commit\n', CHECKOUT_ERROR)
        tree = git('rev-parse', '--verify', item.commit + '^{tree}').strip().decode('ascii')
        tree = git_oid(tree, config_facts.object_format)
        require(git('cat-file', '-t', tree) == b'tree\n', CHECKOUT_ERROR)
        records.append(
            {
                'environment_id': item.environment_id,
                'purpose': item.purpose,
                'branch': item.branch,
                'head': item.expected_head,
                'commit': item.commit,
                'tree': tree,
            }
        )
    check_directory(repo.common, repo.uid, repo.identity, INPUT_CHANGED)
    require(
        original_links == [worktree_link(repo, item) for item in repo.worktrees]
        and digest(safe_file(config, repo.uid, FILE_LIMIT)) == repo.config_sha
        and observations() == (listing, branches),
        INPUT_CHANGED,
    )
    captured = {
        'format_version': 1,
        'repository_ref': repo.reference,
        'object_format': config_facts.object_format,
        'git_sha256': repo.git_sha,
        'worktrees': records,
        'worktree_listing_sha256': listing.listing_sha256,
        'uncommitted_contents': 'NOT_INSPECTED',
    }
    return {
        **captured,
        'evidence_sha256': digest(canonical(captured)),
        'observed_at': utc_milliseconds(datetime.now(timezone.utc)),
    }
