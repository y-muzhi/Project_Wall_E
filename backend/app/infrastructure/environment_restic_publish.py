"""Publish and verify one sealed backup without replaying an uncertain Restic write."""

import fcntl
import json
import os
import stat
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from backend.app.management.release_artifacts import snapshot_file

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
    canonical,
    decode,
    digest,
    exact,
    identity,
    persisted_write,
    read_entry,
    require,
)
from .environment_initialize import is_timestamp
from .environment_installation import identity_record, sha_value, uuid_value
from .environment_restic_contract import (
    INTENT_FIELDS,
    PUBLISHED,
    RETRIEVED,
    VERSION,
    publication_intent,
)
from .environment_restic_restore import (
    fixed_password,
    restic_arguments,
    restic_call,
    retrieve_into,
)

POLICY = 'restic-publication-policy.v1.json'
INVALID = 'RESTIC_PUBLICATION_INTENT_MISMATCH'
UNVERIFIED = 'RESTIC_PUBLICATION_UNVERIFIED'
RECEIPT_FIELDS = ('snapshot_id', 'retrieved_at', 'snapshot_bytes', 'snapshot_entries')


@dataclass(frozen=True)
class PublicationInputs:
    plan: dict
    policy_sha256: str
    binary: Path
    password: Path
    repository: Path
    package: Path
    work: Path


def publication_inputs(args):
    plan = read_policy(
        args.anchor,
        args.anchor_sha256,
        POLICY,
        (
            *INTENT_FIELDS,
            'restic',
            'password_file',
            'repository_directory',
            'repository_identity',
            'package_directory',
            'package_identity',
            'work_directory',
            'work_identity',
            'max_publish_seconds',
            'max_restore_seconds',
            'max_restore_bytes',
            'max_files',
        ),
    )
    require(
        uuid_value(plan['operation_id'])
        and uuid_value(plan['backup_id'])
        and plan['operation_id'] != plan['backup_id']
        and sha_value(plan['backup_manifest_sha256'])
        and sha_value(plan['repository_id'])
        and all(
            type(plan[key]) is int and 1 <= plan[key] <= maximum
            for key, maximum in (
                ('max_publish_seconds', 3600),
                ('max_restore_seconds', 3600),
                ('max_restore_bytes', 1024**4),
                ('max_files', 8192),
            )
        ),
        INVALID,
    )
    program = exact(plan['restic'], ('path', 'sha256', 'version'), INVALID)
    require(program['version'] == VERSION and sha_value(program['sha256']), INVALID)
    binary = absolute(program['path'], INVALID)
    reference = exact(plan['password_file'], ('path', 'identity'), INVALID)
    password = absolute(reference['path'], INVALID)
    identity_record(reference['identity'], INVALID)
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
    package = validate_location(
        plan, 'package_directory', 'package_identity', (*boundaries, repository)
    )
    work = validate_location(
        plan, 'work_directory', 'work_identity', (*boundaries, repository, package)
    )
    require(package.name == plan['backup_id'], INVALID)
    return PublicationInputs(plan, args.anchor_sha256, binary, password, repository, package, work)


def tags_for(plan):
    return (
        f'wall-e-backup-{plan["backup_id"]}',
        f'wall-e-manifest-{plan["backup_manifest_sha256"]}',
        f'wall-e-publication-{plan["operation_id"]}',
    )


def find_snapshot(command, plan, package, work, call=None):
    call = restic_call if call is None else call
    repository = json.loads(call([*command, 'cat', 'config'], 30, work, UNVERIFIED))
    require(type(repository) is dict and repository.get('id') == plan['repository_id'], UNVERIFIED)
    tags = tags_for(plan)
    rows = json.loads(
        call([*command, 'snapshots', '--json', '--tag', tags[-1]], 30, work, UNVERIFIED)
    )
    require(type(rows) is list and len(rows) <= 1, UNVERIFIED)
    if not rows:
        return None
    found = rows[0]
    require(
        type(found) is dict
        and sha_value(found.get('id'))
        and found.get('paths') == [str(package)]
        and type(found.get('tags')) is list
        and all(type(tag) is str for tag in found['tags'])
        and sorted(found['tags']) == sorted(tags),
        UNVERIFIED,
    )
    return found['id']


def backup_snapshot(command, plan, package, work, call):
    call(
        [
            *command,
            'backup',
            '--json',
            '--force',
            '--one-file-system',
            *[item for tag in tags_for(plan) for item in ('--tag', tag)],
            str(package),
        ],
        plan['max_publish_seconds'],
        work,
        UNVERIFIED,
    )


def package_coverage(package, plan):
    used, count = 0, 0
    device = package.stat(follow_symlinks=False).st_dev
    for folder, directories, files in os.walk(package, followlinks=False):
        for name in (*directories, *files):
            info = (Path(folder) / name).stat(follow_symlinks=False)
            require(
                info.st_dev == device
                and (
                    stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                ),
                UNVERIFIED,
            )
            count += 1
            if stat.S_ISREG(info.st_mode):
                used += info.st_size
            require(count <= plan['max_files'] and used <= plan['max_restore_bytes'], UNVERIFIED)
    require(used > 0 and count > 0, UNVERIFIED)


def existing_fact(fd, principal, name):
    try:
        raw = read_entry(
            fd, name, owner=principal.maintenance_uid, group=principal.group, reject_writers=0o277
        )
    except FileNotFoundError:
        return None
    record = decode(raw, UNVERIFIED)
    require(raw == canonical(record), UNVERIFIED)
    return record


def confirmed_publication(record, intent, snapshot, plan):
    exact(record, (*intent, 'publication_intent_sha256', *RECEIPT_FIELDS), UNVERIFIED)
    require(
        all(record[key] == value for key, value in intent.items() if key != 'status')
        and record['status'] == PUBLISHED
        and record['publication_intent_sha256'] == digest(canonical(intent))
        and sha_value(snapshot)
        and record['snapshot_id'] == snapshot
        and is_timestamp(record['retrieved_at'])
        and type(record['snapshot_bytes']) is int
        and 1 <= record['snapshot_bytes'] <= plan['max_restore_bytes']
        and type(record['snapshot_entries']) is int
        and 1 <= record['snapshot_entries'] <= plan['max_files'],
        UNVERIFIED,
    )
    return record


def publish_once(inputs, source, fd, principal, check_current):
    plan = inputs.plan
    intent = publication_intent(
        {
            **{key: plan[key] for key in INTENT_FIELDS},
            'policy_sha256': inputs.policy_sha256,
            'restic_sha256': plan['restic']['sha256'],
            'restic_version': VERSION,
        }
    )
    prefix = f'publish-{plan["operation_id"]}'
    intent_name = f'{prefix}-intent.v1.json'
    result_name = f'{prefix}-result.v1.json'
    original = existing_fact(fd, principal, intent_name)
    result = existing_fact(fd, principal, result_name)
    require(original in (None, intent) and (result is None or original == intent), INVALID)
    verify_contents(
        source, principal, plan['backup_id'], expected_manifest=plan['backup_manifest_sha256']
    )
    package_coverage(inputs.package, plan)
    version = restic_call([str(inputs.binary), 'version'], 12, inputs.work, INVALID)
    require(version.startswith(f'restic {VERSION} '.encode('ascii')), INVALID)
    command = restic_arguments(inputs.binary, inputs.password, inputs.repository)
    snapshot = find_snapshot(command, plan, inputs.package, inputs.work)
    check_current()
    if result is not None:
        previous = confirmed_publication(result, intent, snapshot, plan)
        os.fsync(fd)
        return previous
    if original is None:
        require(snapshot is None, INVALID)
        persisted_write(fd, intent_name, canonical(intent), mode=0o400)
        try:
            backup_snapshot(command, plan, inputs.package, inputs.work, restic_call)
        except EnvironmentFailure:
            # Restic can leave a snapshot after reporting incomplete or interrupted backup.
            pass
    try:
        if original is None:
            snapshot = find_snapshot(command, plan, inputs.package, inputs.work)
        require(snapshot is not None, UNVERIFIED)
        verified = retrieve_into(
            inputs.work,
            fd,
            principal,
            {**plan, 'snapshot_id': snapshot, 'snapshot_subdirectory': inputs.package.as_posix()},
            inputs.binary,
            inputs.password,
            inputs.repository,
        )
        require(
            verified['status'] == RETRIEVED
            and verified['operation_id'] == plan['operation_id']
            and verified['restic_sha256'] == plan['restic']['sha256']
            and verified['restic_version'] == VERSION
            and verified['backup_id'] == plan['backup_id']
            and verified['backup_manifest_sha256'] == plan['backup_manifest_sha256']
            and verified['repository_id'] == plan['repository_id']
            and find_snapshot(command, plan, inputs.package, inputs.work) == snapshot,
            UNVERIFIED,
        )
        check_current()
    except (EnvironmentFailure, OSError, ValueError, KeyError, TypeError) as error:
        raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
    result = confirmed_publication(
        {
            **intent,
            'status': PUBLISHED,
            'publication_intent_sha256': digest(canonical(intent)),
            **{key: verified[key] for key in RECEIPT_FIELDS},
        },
        intent,
        snapshot,
        plan,
    )
    persisted_write(fd, result_name, canonical(result), mode=0o400)
    return result


def publish_backup_snapshot(args):
    inputs = publication_inputs(args)
    plan = inputs.plan
    principal = principal_for_process()
    program = plan['restic']['sha256']
    require(snapshot_file(inputs.binary, 0o555)[0] == program, INVALID)
    with ExitStack() as resources:
        resources.enter_context(
            fixed_password(inputs.password, plan['password_file']['identity'], principal)
        )
        roots = []
        for path, field, access in (
            (inputs.repository, 'repository_identity', fcntl.LOCK_EX),
            (inputs.work, 'work_identity', fcntl.LOCK_EX),
            (inputs.package, 'package_identity', fcntl.LOCK_SH),
        ):
            fd = resources.enter_context(private_root(path, plan[field], principal))
            fcntl.flock(fd, access | fcntl.LOCK_NB)
            roots.append((path, fd, plan[field]))

        def check_current():
            for path, fd, expected in roots:
                require(
                    identity(path.stat(follow_symlinks=False))
                    == identity(os.fstat(fd))
                    == expected,
                    UNVERIFIED,
                )
            require(snapshot_file(inputs.binary, 0o555)[0] == program, UNVERIFIED)

        return publish_once(inputs, roots[2][1], roots[1][1], principal, check_current)
