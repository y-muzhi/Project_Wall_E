"""Retrieve a single fixed Restic snapshot from an admitted local repository."""

import fcntl
import json
import os
import stat
import subprocess
from contextlib import ExitStack, contextmanager
from pathlib import Path
from shutil import disk_usage
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic

from backend.app.management.attachment_observation import now
from backend.app.management.release_artifacts import snapshot_file

from .environment_backup_assets import audit_directory
from .environment_backup_package import (
    principal_for_process,
    private_root,
    read_policy,
    validate_location,
    verify_contents,
)
from .environment_files import (
    EnvironmentFailure,
    absolute,
    exact,
    identity,
    no_acl,
    protected_directory,
    relative,
    require,
)
from .environment_installation import identity_record, sha_value, uuid_value
from .environment_restic_contract import RETRIEVED, VERSION

POLICY = 'restic-retrieval-policy.v1.json'
INVALID = 'RESTIC_RETRIEVAL_INTENT_MISMATCH'
UNVERIFIED = 'RESTIC_SNAPSHOT_UNVERIFIED'
LIMIT = 'RESTIC_RESTORE_LIMIT'
MAX_RESTIC_OUTPUT = 128 * 1024


def retrieval_inputs(args):
    plan = read_policy(
        args.anchor,
        args.anchor_sha256,
        POLICY,
        (
            'operation_id',
            'backup_id',
            'backup_manifest_sha256',
            'restic',
            'repository_directory',
            'repository_identity',
            'repository_id',
            'password_file',
            'receive_directory',
            'receive_identity',
            'snapshot_id',
            'snapshot_subdirectory',
            'max_restore_seconds',
            'max_restore_bytes',
            'max_files',
        ),
    )
    require(
        uuid_value(plan['operation_id'])
        and uuid_value(plan['backup_id'])
        and plan['operation_id'] != plan['backup_id']
        and all(
            sha_value(plan[field])
            for field in ('backup_manifest_sha256', 'repository_id', 'snapshot_id')
        )
        and type(plan['max_restore_seconds']) is int
        and 1 <= plan['max_restore_seconds'] <= 3600
        and type(plan['max_restore_bytes']) is int
        and 1 <= plan['max_restore_bytes'] <= 1024**4
        and type(plan['max_files']) is int
        and 1 <= plan['max_files'] <= 8192,
        INVALID,
    )
    program = exact(plan['restic'], ('path', 'sha256', 'version'), INVALID)
    binary = absolute(program['path'], INVALID)
    require(program['version'] == VERSION and sha_value(program['sha256']), INVALID)
    credentials = exact(plan['password_file'], ('path', 'identity'), INVALID)
    password = absolute(credentials['path'], INVALID)
    identity_record(credentials['identity'], INVALID)
    subdirectory = plan['snapshot_subdirectory']
    require(type(subdirectory) is str and subdirectory.startswith('/'), INVALID)
    relative(subdirectory[1:], INVALID)
    boundaries = (
        args.root,
        args.project,
        args.home,
        args.temporary,
        args.anchor.parent,
        binary.parent,
        password.parent,
    )
    repository = validate_location(plan, 'repository_directory', 'repository_identity', boundaries)
    receive = validate_location(
        plan, 'receive_directory', 'receive_identity', (*boundaries, repository)
    )
    return plan, binary, password, repository, receive


@contextmanager
def fixed_password(path, expected, principal):
    with protected_directory(path.parent) as directory:
        flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC
        descriptor = os.open(path.name, flags, dir_fd=directory)
        try:
            props = os.fstat(descriptor)
            require(
                stat.S_ISREG(props.st_mode)
                and (props.st_uid, props.st_gid, props.st_nlink, stat.S_IMODE(props.st_mode))
                == (principal.maintenance_uid, principal.group, 1, 0o400)
                and identity(props) == expected
                and 0 < props.st_size <= 4096,
                INVALID,
            )
            no_acl(descriptor)
            yield descriptor
            current = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
            require(
                identity(current) == expected
                and (current.st_ctime_ns, current.st_mtime_ns, current.st_size)
                == (props.st_ctime_ns, props.st_mtime_ns, props.st_size),
                UNVERIFIED,
            )
        finally:
            os.close(descriptor)


def restic_call(command, deadline, cwd, code, *, environment=None):
    finish_by = monotonic() + deadline
    with subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as child:
        finished = Event()
        reply = []

        def capture_output():
            try:
                reply.append(child.stdout.read(MAX_RESTIC_OUTPUT + 1))
            except OSError:
                pass
            finally:
                finished.set()

        reader = Thread(target=capture_output, name='restic-output')
        try:
            reader.start()
            require(finished.wait(max(0, finish_by - monotonic())), code)
            require(len(reply) == 1 and len(reply[0]) <= MAX_RESTIC_OUTPUT, code)
            try:
                status = child.wait(timeout=max(0, finish_by - monotonic()))
            except subprocess.TimeoutExpired as error:
                raise EnvironmentFailure(code) from error
            require(status == 0, code)
            return reply[0]
        finally:
            if child.poll() is None:
                child.kill()
            if reader.ident is not None:
                reader.join()


def snapshot_facts(command, policy, work, call):
    def observe(*parameters):
        return json.loads(call([*command, *parameters], 30, work, UNVERIFIED))

    config = observe('cat', 'config')
    require(type(config) is dict and config.get('id') == policy['repository_id'], UNVERIFIED)
    snapshot = policy['snapshot_id']
    rows = observe('snapshots', '--json', snapshot)
    require(
        type(rows) is list
        and len(rows) == 1
        and type(rows[0]) is dict
        and rows[0].get('id') == snapshot,
        UNVERIFIED,
    )
    tags = rows[0].get('tags')
    expected_tags = (
        f'wall-e-backup-{policy["backup_id"]}',
        f'wall-e-manifest-{policy["backup_manifest_sha256"]}',
    )
    require(type(tags) is list and all(tags.count(tag) == 1 for tag in expected_tags), UNVERIFIED)
    publication = policy.get('publication_operation_id')
    if publication is not None:
        all_tags = {*expected_tags, f'wall-e-publication-{publication}'}
        require(
            all(type(tag) is str for tag in tags)
            and len(tags) == len(all_tags)
            and set(tags) == all_tags
            and rows[0].get('paths') == [policy['snapshot_subdirectory']],
            UNVERIFIED,
        )
    stats = observe('stats', '--json', '--mode', 'restore-size', snapshot)
    size, count = stats['total_size'], stats['total_file_count']
    require(
        stats['snapshots_count'] == 1
        and type(size) is int
        and 0 < size <= policy['max_restore_bytes']
        and type(count) is int
        and 0 < count <= policy['max_files']
        and size < disk_usage(work).free,
        LIMIT,
    )
    return size, count


def restic_arguments(binary, password, repository):
    return [
        str(binary),
        '--repo',
        str(repository),
        '--password-file',
        str(password),
        '--no-cache',
        '--quiet',
    ]


@contextmanager
def verified_snapshot_directory(receive, receiver, principal, plan, command, call):
    size, count = snapshot_facts(command, plan, receive, call)
    with TemporaryDirectory(prefix='.restic-restore-', dir=receive) as scratch:
        fresh = Path(scratch)
        selector = plan['snapshot_id'] + ':' + plan['snapshot_subdirectory']
        call(
            [
                *command,
                'restore',
                selector,
                '--target',
                str(fresh),
                '--overwrite',
                'never',
                '--verify',
            ],
            plan['max_restore_seconds'],
            receive,
            'RESTIC_RESTORE_FAILED',
        )
        with audit_directory(
            receiver, fresh.name, principal.maintenance_uid, principal.group, source=False
        ) as restored:
            manifest, measured = verify_contents(
                restored,
                principal,
                plan['backup_id'],
                expected_manifest=plan['backup_manifest_sha256'],
            )
        require(snapshot_facts(command, plan, receive, call) == (size, count), UNVERIFIED)
        yield fresh, manifest, measured, size, count


def restore_verified_package(receive, receiver, principal, plan, command, call):
    with verified_snapshot_directory(receive, receiver, principal, plan, command, call) as restored:
        _, manifest, measured, size, count = restored
        return manifest, measured, size, count


def retrieve_into(receive, receiver, principal, plan, binary, password, repository):
    command = restic_arguments(binary, password, repository)
    version = restic_call([str(binary), 'version'], 12, receive, INVALID)
    require(version.startswith(f'restic {VERSION} '.encode('ascii')), INVALID)
    manifest, measured, size, count = restore_verified_package(
        receive, receiver, principal, plan, command, restic_call
    )
    return {
        'format_version': 1,
        'status': RETRIEVED,
        'operation_id': plan['operation_id'],
        'retrieved_at': now(),
        'backup_id': manifest['backup_id'],
        'backup_manifest_sha256': measured,
        'snapshot_id': plan['snapshot_id'],
        'repository_id': plan['repository_id'],
        'restic_sha256': plan['restic']['sha256'],
        'restic_version': VERSION,
        'snapshot_bytes': size,
        'snapshot_entries': count,
    }


def retrieve_backup_snapshot(args):
    plan, binary, password, repository, receive = retrieval_inputs(args)
    principal = principal_for_process()
    program_sha, _ = snapshot_file(binary, 0o555)
    require(program_sha == plan['restic']['sha256'], INVALID)
    with ExitStack() as opened:
        opened.enter_context(fixed_password(password, plan['password_file']['identity'], principal))
        source = opened.enter_context(
            private_root(repository, plan['repository_identity'], principal)
        )
        target = opened.enter_context(private_root(receive, plan['receive_identity'], principal))
        fcntl.flock(source, fcntl.LOCK_SH | fcntl.LOCK_NB)
        fcntl.flock(target, fcntl.LOCK_EX | fcntl.LOCK_NB)
        output = retrieve_into(receive, target, principal, plan, binary, password, repository)
        for folder, directory in ((repository, source), (receive, target)):
            require(
                identity(folder.stat(follow_symlinks=False)) == identity(os.fstat(directory)),
                UNVERIFIED,
            )
        require(snapshot_file(binary, 0o555)[0] == program_sha, UNVERIFIED)
    return output
