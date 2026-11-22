"""Observe the actual local HTTPS gateway while the selected rollout remains closed."""

from base64 import b64encode
from contextlib import closing
import fcntl
from http.client import HTTPConnection
import os
from pathlib import Path
import re
import socket
import ssl
import stat
from types import SimpleNamespace
from urllib.parse import urlsplit

from backend.app.management.attachment_observation import now
from backend.app.management.registry import is_timestamp
from backend.app.management.release_artifacts import snapshot_file

from .environment_backup_package import read_policy, validate_location
from .environment_files import (
    canonical,
    check_ext4,
    decode,
    digest,
    exact,
    identity,
    persisted_write,
    protected_directory,
    read_entry,
    read_protected,
    relative,
    require,
)
from .environment_installation import ACCESS_NAME
from .environment_lock import NativeEnvironmentFiles
from .environment_recovery_installation import checked_ref
from .environment_release_gateway import (
    RECEIPT as STAGE,
    load_site,
    same_previous_installation,
    static_entries,
)
from .environment_release_preflight import read_reference
from .environment_release_verify import selected_state

POLICY = 'release-gateway-verification-policy.v1.json'
VERIFIED = 'release-gateway-verified.v1.json'
INVALID = 'RELEASE_GATEWAY_VERIFICATION_INTENT_MISMATCH'
UNVERIFIED = 'RELEASE_GATEWAY_VERIFICATION_UNVERIFIED'
MAX_RESPONSE = 16 * 1024 * 1024
ASSET = re.compile(r'assets/[A-Za-z0-9._/-]{1,180}')


def small_proc(path):
    with path.open('rb') as stream:
        raw = stream.read(MAX_RESPONSE + 1)
    require(len(raw) <= MAX_RESPONSE, UNVERIFIED)
    return raw


def listener_inodes(pid, port):
    target = f'0100007F:{port:04X}'
    lines = small_proc(Path(f'/proc/{pid}/net/tcp')).decode('ascii').splitlines()[1:]
    interfaces = [row.split() for row in lines]
    return {row[9] for row in interfaces if row[1] == target and row[3] == '0A'}


def process_epoch(pid):
    parent = Path(f'/proc/{pid}')
    ticks = small_proc(parent / 'stat').rpartition(b') ')[2].split()[19].decode('ascii')
    boot = Path('/proc/sys/kernel/random/boot_id').read_text(encoding='ascii').strip()
    require(ticks.isascii() and ticks.isdigit() and bool(boot), UNVERIFIED)
    return ticks, boot


def gateway_process(pid, uid, executable, config, port):
    require(
        type(pid) is int and 1 < pid < 2**31 and type(uid) is int and 0 < uid < 2**31,
        INVALID,
    )
    parent = Path(f'/proc/{pid}')
    expected = [
        os.fsencode(executable),
        b'run',
        b'--config',
        os.fsencode(config),
        b'--adapter',
        b'caddyfile',
        b'',
    ]
    require(
        (parent / 'exe').resolve(strict=True) == executable
        and small_proc(parent / 'cmdline').split(b'\x00') == expected,
        UNVERIFIED,
    )
    actor = next(
        (
            row.split()[1:]
            for row in small_proc(parent / 'status').splitlines()
            if row.startswith(b'Uid:')
        ),
        None,
    )
    require(actor == [str(uid).encode('ascii')] * 4, UNVERIFIED)
    ticks, boot = process_epoch(pid)
    sockets = listener_inodes(pid, port)
    require(len(sockets) == 1, UNVERIFIED)
    match = f'socket:[{next(iter(sockets))}]'
    for descriptor in (parent / 'fd').iterdir():
        try:
            path = os.readlink(descriptor)
        except FileNotFoundError:
            continue
        if path == match:
            return {
                'pid': pid,
                'uid': uid,
                'start_ticks': ticks,
                'boot_id': boot,
                'listener_inode': next(iter(sockets)),
            }
    require(False, UNVERIFIED)


def https_get(host, port, context, route, credential=None):
    headers = {'Host': f'{host}:{port}', 'Accept-Encoding': 'identity', 'Connection': 'close'}
    if credential is not None:
        headers['Authorization'] = 'Basic ' + credential
    with closing(HTTPConnection(host, port, timeout=6)) as client:
        with socket.create_connection(('127.0.0.1', port), timeout=6) as transport:
            with context.wrap_socket(transport, server_hostname=host) as secured:
                client.sock = secured
                client.request('GET', route, headers=headers)
                with client.getresponse() as response:
                    body = response.read(MAX_RESPONSE + 1)
                    require(len(body) <= MAX_RESPONSE, UNVERIFIED)
                    return response.status, dict(response.getheaders()), body


def check_digest(reply, expected):
    status, _, body = reply
    _, length, fingerprint = expected
    require(status == 200 and len(body) == length and digest(body) == fingerprint, UNVERIFIED)


def check_gateway_wire(fetch, target, origin, current, previous, current_asset, previous_asset):
    expected = {
        'format_version': 1,
        'binding_protocol': 1,
        'environment_id': target.environment_id,
        'data_generation': target.data_generation,
        'configuration_sha256': target.configuration_sha256,
        'purpose': target.description['purpose'],
        'api_base': '/api/v1',
        'public_origin': origin,
        'management_url': None,
    }
    location = '/.well-known/walle-environment.json'
    require(fetch(location, authenticated=False)[0] == 401, UNVERIFIED)
    status, headers, raw = fetch(location)
    binding = decode(raw, UNVERIFIED, require_canonical=False)
    require(
        status == 200
        and {name.lower(): value for name, value in headers.items()}.get('cache-control')
        == 'no-store'
        and set(binding) == {*expected, 'display_name'}
        and all(canonical(binding[key]) == canonical(value) for key, value in expected.items())
        and type(binding['display_name']) is str
        and bool(binding['display_name'].strip()),
        UNVERIFIED,
    )
    check_digest(fetch('/'), current['index.html'])
    check_digest(fetch('/' + current_asset), current[current_asset])
    check_digest(fetch('/' + previous_asset), previous[previous_asset])
    require(fetch('/api/v1/environment')[0] == 502, UNVERIFIED)


def credentials_pair(reference, access):
    path, expected = checked_ref(reference, 'gateway-verification-credential.v1.json')
    actual, contents = snapshot_file(path, 0o400, capture=True)
    require(actual == expected, INVALID)
    info = exact(decode(contents, INVALID), ('name', 'password'), INVALID)
    permitted = {
        principal['principal_id']
        for principal in access['principals']
        if principal['permission'] == 'READ_ONLY' and principal['client_kind'] == 'AUTOMATION'
    }
    require(
        info['name'] in permitted
        and type(info['password']) is str
        and 8 <= len(info['password']) <= 160
        and info['password'].isascii()
        and all(33 <= ord(char) <= 126 for char in info['password']),
        INVALID,
    )
    return b64encode((info['name'] + ':' + info['password']).encode('ascii')).decode('ascii')


def exact_file(reference, *, modes, name):
    path, expected = checked_ref(reference, name)
    permissions = stat.S_IMODE(path.lstat().st_mode)
    require(permissions in modes, INVALID)
    actual, _ = snapshot_file(path, permissions)
    require(actual == expected, UNVERIFIED)
    return path


def observe_gateway(args, entry):
    require(os.geteuid() == 0, INVALID)
    plan = read_policy(
        args.anchor,
        args.anchor_sha256,
        POLICY,
        (
            'target_installation',
            'previous_installation',
            'previous_frontend_index',
            'gateway_stage',
            'gateway_executable',
            'gateway_pid',
            'gateway_uid',
            'tls_ca',
            'credential',
            'current_asset',
            'previous_asset',
            'evidence',
            'evidence_identity',
        ),
    )
    active = SimpleNamespace(runtime_manifest_sha256=args.sha256)
    target = load_site(plan['target_installation'], active, entry)
    previous = load_site(plan['previous_installation'], active, entry)
    stage = read_reference(plan['gateway_stage'], name=STAGE)
    binding = target.description.get('deployment_slot')
    require(
        binding is not None
        and stage['status'] == 'RELEASE_GATEWAY_STAGED'
        and stage['target_installation_sha256'] == target.anchor_sha256
        and stage['target_environment_id'] == target.environment_id
        and stage['target_data_generation'] == target.data_generation
        and stage['target_deployment_id'] == target.deployment_id
        and stage['target_configuration_sha256'] == target.configuration_sha256
        and stage['target_frontend_index_sha256'] == binding['frontend_index_sha256']
        and previous.environment_root == target.environment_root,
        INVALID,
    )
    stage_path = Path(plan['gateway_stage']['path'])
    config = exact_file(
        {
            'path': str(stage_path.parent / 'Caddyfile'),
            'sha256': stage['gateway_configuration_sha256'],
        },
        modes=(0o400, 0o440),
        name='Caddyfile',
    )
    executable = exact_file(plan['gateway_executable'], modes=(0o555, 0o755), name='caddy')
    old_index, old_pin = checked_ref(plan['previous_frontend_index'], 'frontend-index.v1.json')
    require(old_pin == stage['previous_frontend_index_sha256'], INVALID)
    original = static_entries(previous.path('frontend'), old_index, old_pin)
    current = static_entries(
        target.path('frontend'),
        target.project.parent / 'frontend-index.v1.json',
        binding['frontend_index_sha256'],
    )
    new_asset, previous_asset = (plan['current_asset'], plan['previous_asset'])
    for asset in (new_asset, previous_asset):
        require(type(asset) is str and ASSET.fullmatch(asset), INVALID)
        relative(asset, INVALID)
    require(
        new_asset in current
        and previous_asset in original
        and (
            previous_asset not in current
            or current[previous_asset][1:] == original[previous_asset][1:]
        ),
        INVALID,
    )
    access = decode(read_protected(target.anchor.parent / ACCESS_NAME), UNVERIFIED)
    credential = credentials_pair(plan['credential'], access)
    origin = access['public_origin']
    server = urlsplit(origin)
    require(server.scheme == 'https' and server.port == 9443, INVALID)
    ca_path = exact_file(plan['tls_ca'], modes=(0o444,), name='root.crt')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cadata=read_protected(ca_path).decode('ascii'))
    native = NativeEnvironmentFiles(args.root)
    before = selected_state(target, native, stage)
    _, transition, _ = before
    require(same_previous_installation(previous, transition), INVALID)
    process = gateway_process(
        plan['gateway_pid'], plan['gateway_uid'], executable, config, server.port
    )

    def fetch(route, *, authenticated=True):
        return https_get(
            server.hostname, server.port, context, route, credential if authenticated else None
        )

    check_gateway_wire(fetch, target, origin, current, original, new_asset, previous_asset)
    require(
        gateway_process(plan['gateway_pid'], plan['gateway_uid'], executable, config, server.port)
        == process
        and digest(read_protected(config)) == stage['gateway_configuration_sha256']
        and selected_state(target, native, stage) == before,
        UNVERIFIED,
    )
    output = validate_location(
        plan,
        'evidence',
        'evidence_identity',
        (target.environment_root, target.project, stage_path.parent, args.anchor.parent, args.root),
    )
    result = {
        'format_version': 1,
        'status': 'RELEASE_GATEWAY_VERIFIED_CLOSED',
        'policy_sha256': args.anchor_sha256,
        'gateway_stage_sha256': plan['gateway_stage']['sha256'],
        'gateway_configuration_sha256': stage['gateway_configuration_sha256'],
        'operation_id': stage['operation_id'],
        'target_installation_sha256': target.anchor_sha256,
        'target_environment_id': target.environment_id,
        'target_data_generation': target.data_generation,
        'target_deployment_id': target.deployment_id,
        'target_configuration_sha256': target.configuration_sha256,
        'target_frontend_index_sha256': binding['frontend_index_sha256'],
        'target_verification_sha256': stage['target_verification_sha256'],
        'transition_sha256': stage['transition_sha256'],
        'control_sha256': stage['control_sha256'],
        'origin': origin,
        'gateway_process': process,
        'current_asset_sha256': current[new_asset][2],
        'previous_asset_sha256': original[previous_asset][2],
    }
    with protected_directory(output) as fd:
        require(identity(os.fstat(fd)) == plan['evidence_identity'], INVALID)
        check_ext4(fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            existed = read_entry(fd, VERIFIED, owner=0, reject_writers=0o222)
        except FileNotFoundError:
            result['verified_at'] = now()
            payload = canonical(result)
            persisted_write(fd, VERIFIED, payload, mode=0o444)
            existed = read_entry(fd, VERIFIED, owner=0, reject_writers=0o222)
        timestamp = decode(existed, UNVERIFIED).get('verified_at')
        require(
            is_timestamp(timestamp) and existed == canonical({**result, 'verified_at': timestamp}),
            UNVERIFIED,
        )
        os.fsync(fd)
        return {**result, 'verified_at': timestamp}
