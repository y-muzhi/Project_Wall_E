"""Privileged creation of a new P1 host installation, without opening SQLite."""

import argparse
import fcntl
import json
import os
import stat
from contextlib import ExitStack, contextmanager
from pathlib import Path
from uuid import uuid4

from .environment_files import (
    EnvironmentFailure,
    canonical,
    check_ext4,
    decode,
    digest,
    identity,
    no_acl,
    persisted_write,
    protected_directory,
    read_protected,
    require,
)
from .environment_installation import (
    ACCESS_NAME,
    ANCHOR_NAME,
    CANDIDATE_PURPOSE,
    CAPABILITIES,
    CONFIG_NAME,
    DEFAULT_BUSINESS_DOMAIN,
    DEFAULT_BUSINESS_PORT,
    DIRECTORIES,
    HOLD_NAME,
    WORKSPACE_PURPOSES,
    Installation,
    business_origin,
    check_business_listener,
    sha_value,
    validate_business_origin,
)
from .environment_lock import LOCK_NAME, PROTOCOL


def provision(
    args,
    *,
    validation=None,
    business_domain=DEFAULT_BUSINESS_DOMAIN,
    business_port=DEFAULT_BUSINESS_PORT,
    with_gateway_verifier=False,
):
    require(os.geteuid() == 0, 'INSTALLER_IDENTITY_NOT_ADMITTED')
    require(
        (
            args.purpose in WORKSPACE_PURPOSES
            if validation is None
            else args.purpose == CANDIDATE_PURPOSE
        )
        and args.application_uid != args.maintenance_uid
        and all(
            1 <= value < 2**31 for value in (args.application_uid, args.maintenance_uid, args.group)
        ),
        'INSTALLER_IDENTITIES_INVALID',
    )
    require(
        args.ingress_group is None
        or (1 <= args.ingress_group < 2**31 and args.ingress_group != args.group),
        'INSTALLER_IDENTITIES_INVALID',
    )
    require(
        not with_gateway_verifier or (validation is None and args.ingress_group is not None),
        'GATEWAY_VERIFIER_NOT_ADMITTED',
    )
    check_business_listener(business_domain, business_port)
    require(sha_value(args.runtime_sha256), 'RUNTIME_MANIFEST_MISMATCH')
    with ExitStack() as resources:
        for path in (args.host_root, args.project, args.schema, args.frontend_input):
            directory = resources.enter_context(protected_directory(path))
            check_ext4(directory)
        host_fd = resources.enter_context(installer_lock(args.host_root))
        if validation is not None:
            require(
                identity(os.fstat(host_fd)) == validation.host_identity,
                'CANDIDATE_VALIDATION_UNVERIFIED',
            )
        _initialize_host(host_fd, args.host_root)
        if validation is not None:
            from backend.app.management.release_validation import existing_candidate_installation

            existing = existing_candidate_installation(args, validation)
            if existing is not None:
                return existing
        _reserve_identities(args)
        return create_installation_files(
            args,
            host_fd,
            validation,
            business_domain=business_domain,
            business_port=business_port,
            with_gateway_verifier=with_gateway_verifier,
        )


@contextmanager
def installer_lock(host_root, *, expected_identity=None):
    with ExitStack() as resources:
        host_fd = resources.enter_context(protected_directory(host_root))
        if expected_identity is not None:
            require(identity(os.fstat(host_fd)) == expected_identity, 'INSTALLER_LOCK_NOT_ADMITTED')
            check_ext4(host_fd)
        flags = os.O_NOFOLLOW | os.O_CLOEXEC | os.O_RDWR
        try:
            serial_fd = os.open(
                '.install.lock', flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=host_fd
            )
        except FileExistsError:
            serial_fd = os.open('.install.lock', flags, dir_fd=host_fd)
        resources.callback(os.close, serial_fd)
        meta = os.fstat(serial_fd)
        require(
            stat.S_ISREG(meta.st_mode)
            and meta.st_uid == 0
            and meta.st_nlink == 1
            and stat.S_IMODE(meta.st_mode) == 0o600,
            'INSTALLER_LOCK_NOT_ADMITTED',
        )
        no_acl(serial_fd)
        fcntl.flock(serial_fd, fcntl.LOCK_EX)
        yield host_fd


def _initialize_host(host_fd, host_root):
    if (host_root / HOLD_NAME).exists():
        # Preserve the existing trusted hold through later installations.
        from .environment_host_hold import host_hold_record

        raw = read_protected(host_root / HOLD_NAME)
        host_hold_record(raw, identity(os.fstat(host_fd)))
        return
    require(not any(item.is_dir() for item in host_root.iterdir()), 'HOST_RECOVERY_HOLD')
    hold = {'format_version': 1, 'recovery_hold': False, 'allowed_deployments': []}
    persisted_write(host_fd, HOLD_NAME, canonical(hold), mode=0o444)


def _reserve_identities(args):
    requested = {args.application_uid, args.maintenance_uid}
    groups = {args.group, args.ingress_group} - {None}
    for entry in args.host_root.iterdir():
        if not entry.is_dir():
            continue
        record = decode(read_protected(entry / ANCHOR_NAME), 'INSTALLATION_ANCHOR_MISMATCH')
        used = {record['application_uid'], record['maintenance_uid']}
        existing_groups = {record['shared_gid'], record.get('ingress_gid')} - {None}
        require(
            not requested & used and not groups & existing_groups,
            'ENVIRONMENT_IDENTITIES_ALREADY_RESERVED',
        )


def _frontend_copy(source, target, *, fixed=False):
    for item in sorted(source.iterdir()):
        meta = item.lstat()
        require(
            meta.st_uid == 0 and not stat.S_IMODE(meta.st_mode) & 0o022,
            'FRONTEND_INPUT_NOT_ADMITTED',
        )
        output = target / item.name
        if stat.S_ISDIR(meta.st_mode):
            output.mkdir(mode=0o755)
            output.chmod(0o755)
            _frontend_copy(item, output, fixed=fixed)
        else:
            require(
                stat.S_ISREG(meta.st_mode) and meta.st_nlink == 1, 'FRONTEND_INPUT_NOT_ADMITTED'
            )
            mode = stat.S_IMODE(meta.st_mode) if fixed else 0o444
            require(not fixed or mode in (0o444, 0o555), 'FRONTEND_INPUT_NOT_ADMITTED')
            with item.open('rb') as origin, output.open('xb') as sink:
                while block := origin.read(1024 * 1024):
                    sink.write(block)
                sink.flush()
                os.fchmod(sink.fileno(), mode)
                os.fsync(sink.fileno())
    with protected_directory(target) as fd:
        os.fsync(fd)


def create_installation_files(
    args,
    host_fd,
    validation=None,
    *,
    replica=None,
    staging=None,
    business_domain=DEFAULT_BUSINESS_DOMAIN,
    business_port=DEFAULT_BUSINESS_PORT,
    with_gateway_verifier=False,
):
    if replica is not None:
        environment_id, data_generation, deployment_id = replica.identities
    elif validation is not None:
        environment_id, data_generation, deployment_id = validation.identities
    else:
        environment_id, data_generation, deployment_id = (str(uuid4()) for _ in range(3))
    origin = (
        business_origin(environment_id, business_domain, business_port)
        if validation is None
        else validate_business_origin(validation.public_origin, environment_id)
    )
    destination = args.host_root / environment_id
    root = destination if staging is None else staging
    anchor = destination / ANCHOR_NAME
    replica_configuration = {} if replica is None else {'recovery_replica': replica.binding}
    permission = 'DEVELOP' if replica is None else 'READ_ONLY'
    schema_raw = read_protected(args.schema / 'manifest.v2.json')
    schema_record = decode(schema_raw, 'SCHEMA_RELEASE_MISMATCH')
    require(
        schema_record.get('runtime_manifest_sha256') == args.runtime_sha256
        and schema_record.get('release_id') == args.schema.name
        and schema_record.get('format_version') == 2,
        'SCHEMA_RELEASE_MISMATCH',
    )
    schema_sha = digest(schema_raw)
    source_raw = read_protected(args.project / 'program-snapshot.v1.json')
    source = decode(source_raw, 'PROGRAM_SNAPSHOT_MISMATCH')
    require(source.get('format_version') == 1, 'PROGRAM_SNAPSHOT_MISMATCH')
    program_sha = digest(source_raw)
    if validation is not None:
        from backend.app.management.release_validation import UNVERIFIED

        require(
            program_sha == validation.program_sha and schema_sha == validation.schema_sha,
            UNVERIFIED,
        )

    root.mkdir(mode=0o755)
    root.chmod(0o755)
    layout = Installation(
        anchor,
        '',
        '',
        replica_configuration,
        {},
        environment_id,
        data_generation,
        deployment_id,
        args.application_uid,
        args.maintenance_uid,
        args.group,
        {},
        args.project,
        args.schema,
        args.ingress_group,
    )
    directories = {}
    for kind in DIRECTORIES:
        path = root / kind
        owner, group, mode = layout.expected_directory(kind)
        path.mkdir(mode=0o700)
        os.chown(path, owner, group)
        os.chmod(path, mode)
        directories[kind] = identity(path.stat())
    require((args.frontend_input / 'index.html').is_file(), 'FRONTEND_INPUT_NOT_ADMITTED')
    _frontend_copy(
        args.frontend_input, root / 'frontend', fixed=validation is not None or replica is not None
    )
    if validation is not None:
        from backend.app.management.release_validation import verify_validation_frontend

        verify_validation_frontend(root / 'frontend', args.project, validation.binding)

    lock_file = root / 'lock' / LOCK_NAME
    with lock_file.open('xb') as handle:
        os.fchown(handle.fileno(), 0, args.group)
        os.fchmod(handle.fileno(), 0o660)
        os.fsync(handle.fileno())
        lock_identity = identity(os.fstat(handle.fileno()))
    with protected_directory(lock_file.parent) as lock_fd:
        os.fsync(lock_fd)

    principals = [
        {'principal_id': f'web-{environment_id}', 'client_kind': 'WEB', 'permission': permission},
        {
            'principal_id': f'automation-{environment_id}',
            'client_kind': 'AUTOMATION',
            'permission': permission,
        },
    ]
    if with_gateway_verifier:
        principals.append(
            {
                'principal_id': f'gateway-check-{environment_id}',
                'client_kind': 'AUTOMATION',
                'permission': 'READ_ONLY',
            }
        )
    access = canonical(
        {
            'format_version': 1,
            'environment_id': environment_id,
            'public_origin': origin,
            'upstream_socket': str(destination / 'runtime' / 'walle.sock'),
            'principals': principals,
        }
    )
    config = canonical(
        {
            'format_version': 1,
            'environment_id': environment_id,
            'data_generation': data_generation,
            'purpose': args.purpose,
            'required_capabilities': sorted(CAPABILITIES),
            'enabled_capabilities': sorted(CAPABILITIES),
            'database_relative_path': 'wall-e.sqlite',
            'program_source': {
                'kind': 'WORKSPACE_SNAPSHOT' if validation is None else 'FIXED_RELEASE',
                'sha256': program_sha,
            },
            **({'release_validation': validation.binding} if validation is not None else {}),
            **replica_configuration,
            'runtime_manifest_sha256': args.runtime_sha256,
            'schema_manifest_sha256': schema_sha,
            'access_policy_ref': {'name': ACCESS_NAME, 'sha256': digest(access)},
            'model_permission_ref': None,
            **{f'{kind}_root': str(destination / kind) for kind in DIRECTORIES[:-1]},
        }
    )
    record = canonical(
        {
            'format_version': 1,
            'environment_id': environment_id,
            'data_generation': data_generation,
            'deployment_id': deployment_id,
            'runtime_manifest_sha256': args.runtime_sha256,
            'schema_manifest_sha256': schema_sha,
            'configuration_sha256': digest(config),
            'program_sha256': program_sha,
            'lock_protocol': PROTOCOL,
            'lock_identity': lock_identity,
            'root_identities': directories,
            'application_uid': args.application_uid,
            'maintenance_uid': args.maintenance_uid,
            'shared_gid': args.group,
            'ingress_gid': args.ingress_group,
            'project': str(args.project),
            'schema': str(args.schema),
        }
    )
    with protected_directory(root) as directory:
        persisted_write(directory, ACCESS_NAME, access, mode=0o444)
        persisted_write(directory, CONFIG_NAME, config, mode=0o444)
        persisted_write(directory, ANCHOR_NAME, record, mode=0o444)
    os.fsync(host_fd)
    return {
        'anchor': str(anchor),
        'anchor_sha256': digest(record),
        'environment_id': environment_id,
        'data_generation': data_generation,
        'deployment_id': deployment_id,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ('host-root', 'project', 'schema', 'frontend-input'):
        parser.add_argument(f'--{argument}', type=Path, required=True)
    for argument in ('application-uid', 'maintenance-uid', 'group'):
        parser.add_argument(f'--{argument}', type=int, required=True)
    parser.add_argument('--runtime-sha256', required=True)
    parser.add_argument('--ingress-group', type=int)
    parser.add_argument('--with-gateway-verifier', action='store_true')
    parser.add_argument('--business-domain', default=DEFAULT_BUSINESS_DOMAIN)
    parser.add_argument('--business-port', type=int, default=DEFAULT_BUSINESS_PORT)
    parser.add_argument('--purpose', choices=sorted(WORKSPACE_PURPOSES), required=True)
    args = parser.parse_args(argv)
    try:
        result = provision(
            args,
            business_domain=args.business_domain,
            business_port=args.business_port,
            with_gateway_verifier=args.with_gateway_verifier,
        )
    except EnvironmentFailure as error:
        print(json.dumps({'status': 'BLOCKED', 'reason_code': error.code}))
        return 3 if error.uncertain else 2
    except (OSError, ValueError, KeyError):
        print(json.dumps({'status': 'BLOCKED', 'reason_code': 'INSTALLATION_UNVERIFIED'}))
        return 3
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
