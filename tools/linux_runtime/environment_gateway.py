"""Render a fixed local HTTPS gateway for the ordinary pair or one independent candidate."""

import argparse
import json
import os
import re
import runpy
import stat
import sys
from pathlib import Path

BCRYPT = re.compile(r'\$2[aby]\$[0-9]{2}\$[A-Za-z0-9./]{53}')
SAFE_SOCKET_PATH = re.compile(r'/[A-Za-z0-9._/-]{1,100}')
SAFE_STATIC_PATH = re.compile(r'/[A-Za-z0-9._/-]{1,240}')
PURPOSE_LABELS = {'DEVELOPMENT': '开发环境', 'INTEGRATION': '集成环境', 'CANDIDATE': '候选验证环境'}


def site_block(installation, accounts, *, previous_frontend=None, vite_socket=None):
    from backend.app.infrastructure.environment_files import exact, require
    from backend.app.infrastructure.environment_installation import read_access_policy

    code = 'GATEWAY_POLICY_MISMATCH'
    policy = read_access_policy(installation)
    origin = policy['public_origin']
    socket = policy['upstream_socket']
    frontend = str(installation.path('frontend'))
    require(
        installation.ingress_group is not None
        and len(socket.encode('utf-8')) < 108
        and SAFE_SOCKET_PATH.fullmatch(socket)
        and SAFE_STATIC_PATH.fullmatch(frontend)
        and (previous_frontend is None or SAFE_STATIC_PATH.fullmatch(str(previous_frontend)))
        and (vite_socket is None or previous_frontend is None),
        code,
    )
    names = [principal['principal_id'] for principal in policy['principals']]
    exact(accounts, names, code)
    require(
        all(type(value) is str and BCRYPT.fullmatch(value) for value in accounts.values()), code
    )
    credentials = ''.join(f'            {name} {accounts[name]}\n' for name in names)
    public = json.dumps(
        {
            'format_version': 1,
            'binding_protocol': 1,
            'environment_id': installation.environment_id,
            'data_generation': installation.data_generation,
            'display_name': PURPOSE_LABELS[installation.description['purpose']],
            'purpose': installation.description['purpose'],
            'public_origin': origin,
            'api_base': '/api/v1',
            'configuration_sha256': installation.configuration_sha256,
            'management_url': None,
        },
        separators=(',', ':'),
        ensure_ascii=False,
    )
    body = json.dumps(public, ensure_ascii=False)
    assets = asset_handlers(frontend, previous_frontend)
    routes = frontend_handlers(frontend, assets, origin, vite_socket)
    return f"""{origin} {{
    bind 127.0.0.1
    tls internal
    route {{
        basicauth bcrypt "walle-env:{installation.environment_id}" {{
{credentials}        }}
        header {{
            Referrer-Policy "no-referrer"
            X-Content-Type-Options "nosniff"
        }}
        @configuration path /.well-known/walle-environment.json
        handle @configuration {{
            header Cache-Control "no-store"
            header Content-Type "application/json; charset=utf-8"
            respond {body} 200
        }}
        @api path /api/*
        handle @api {{
{private_headers('            ')}            reverse_proxy unix/{socket} {{
                header_up X-WALL-E-Auth-Principal {{http.auth.user.id}}
            }}
        }}
{routes}        handle {{
            respond 404
        }}
    }}
}}
"""


def private_headers(indent):
    names = (
        'Authorization',
        'Proxy-Authorization',
        'Cookie',
        'Forwarded',
        'X-WALL-E-Auth-*',
    )
    return ''.join(f'{indent}request_header -{name}\n' for name in names)


def frontend_handlers(frontend, assets, origin, vite_socket):
    if vite_socket is None:
        pages = f"""            header Cache-Control "no-store"
            header Content-Security-Policy "frame-ancestors 'none'"
            root * {frontend}
            rewrite * /index.html
            file_server
"""
        development = ''
    else:
        proxy = f"""{private_headers('            ')}            reverse_proxy unix/{vite_socket}
"""
        pages = f"""            header Cache-Control "no-store"
            header Content-Security-Policy "frame-ancestors 'none'"
{proxy}"""
        development = f"""        @development_hmr path /__walle_hmr
        handle @development_hmr {{
            @development_origin {{
                method GET
                header Origin {origin}
                header Upgrade websocket
            }}
            handle @development_origin {{
{private_headers('                ')}                reverse_proxy unix/{vite_socket}
            }}
            respond 403
        }}
        @development_module {{
            path /@vite/* /@react-refresh /@id/* /@fs/* /src/* /node_modules/.vite/*
            path /node_modules/vite/dist/client/env.mjs
        }}
        handle @development_module {{
            header Cache-Control "no-store"
            header Cross-Origin-Resource-Policy "same-origin"
{proxy}        }}
"""
    return f"""{development}        @asset path /assets/*
        handle @asset {{
{assets}        }}
        @page path_regexp wallepage ^(/|/requirements(/[1-9][0-9]*(/documents/[1-9][0-9]*/code-tasks)?)?|/code-tasks/[1-9][0-9]*|/testing(/plans|/tasks/[1-9][0-9]*)?|/settings/(code|testing))$
        handle @page {{
{pages}        }}
"""


def development_sockets(entries, installations):
    from backend.app.infrastructure.environment_files import absolute, protected_directory, require
    from backend.app.infrastructure.environment_installation import WORKSPACE_PURPOSES

    code = 'DEVELOPMENT_FRONTEND_NOT_ADMITTED'
    installed = {item.environment_id: item for item in installations}
    paths = {}
    for environment_id, address in entries:
        item = installed.get(environment_id)
        require(
            item is not None
            and environment_id not in paths
            and item.description['purpose'] in WORKSPACE_PURPOSES
            and 'deployment_slot' not in item.description
            and 'recovery_replica' not in item.description
            and item.ingress_group is not None,
            code,
        )
        socket = absolute(address, code)
        require(
            socket.name == 'vite.sock'
            and socket.parent.name == environment_id
            and SAFE_SOCKET_PATH.fullmatch(address)
            and not any(
                socket.is_relative_to(root)
                for scope in installations
                for root in (scope.environment_root, scope.project, scope.schema)
            ),
            code,
        )
        with protected_directory(socket.parent) as fd:
            parent = os.fstat(fd)
            require(stat.S_IMODE(parent.st_mode) == 0o755, code)
            try:
                metadata = os.stat(socket.name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                # systemd may bind the configured path after this Caddyfile is rendered.
                pass
            else:
                require(
                    stat.S_ISSOCK(metadata.st_mode)
                    and metadata.st_nlink == 1
                    and metadata.st_uid == 0
                    and metadata.st_gid == item.ingress_group
                    and stat.S_IMODE(metadata.st_mode) == 0o660,
                    code,
                )
        paths[environment_id] = socket
    return paths


def asset_handlers(frontend, previous_frontend):
    if previous_frontend is None:
        return f'            root * {frontend}\n            file_server\n'
    return f"""            @currentAsset file {{
                root {frontend}
                try_files {{path}}
            }}
            handle @currentAsset {{
                root * {frontend}
                file_server
            }}
            handle {{
                root * {previous_frontend}
                file_server
            }}
"""


def installed_site(anchor, expected, runtime_sha256, verify_program):
    from backend.app.infrastructure.environment_files import absolute, require
    from backend.app.infrastructure.environment_installation import (
        load_installation,
        read_installation_anchor,
    )

    code = 'GATEWAY_POLICY_MISMATCH'
    record = read_installation_anchor(anchor, expected)
    project = absolute(record['project'], code)
    installation = load_installation(anchor, expected, runtime_sha256, project)
    require(verify_program(project) == installation.description['program_source']['sha256'], code)
    return installation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--project', required=True, type=Path, help='Trusted gateway renderer program'
    )
    parser.add_argument('--runtime-sha256', required=True)
    parser.add_argument('--runtime-entry', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--site', nargs=2, action='append', metavar=('ANCHOR', 'SHA256'))
    parser.add_argument('--vite-site', nargs=2, action='append', metavar=('ENVIRONMENT', 'SOCKET'))
    parser.add_argument('--hashes-file', type=Path, required=True)
    parser.add_argument('--gateway-group', type=int)
    parser.add_argument('--release-stage-policy', type=Path)
    parser.add_argument('--release-stage-policy-sha256')
    parser.add_argument('--runtime-root', type=Path)
    parser.add_argument('--companion-runtime-root', type=Path)
    parser.add_argument('--companion-runtime-sha256')
    args = parser.parse_args()
    companion_values = (args.companion_runtime_root, args.companion_runtime_sha256)
    stage_values = (args.release_stage_policy, args.release_stage_policy_sha256, args.runtime_root)
    release_stage = bool(args.release_stage_policy)
    if not (
        all(stage_values) and not (args.site or args.vite_site)
        if release_stage
        else not any(stage_values) and args.site
    ):
        parser.error('Use --site or the complete fixed release staging policy')
    if any(companion_values) and not (release_stage and all(companion_values)):
        parser.error('A separate companion runtime requires a root and digest for release staging')

    try:
        path = args.runtime_entry
        metadata = path.lstat()
        if (
            path.resolve(strict=True) != path
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) & 0o222
            or any(
                item.is_symlink()
                or item.stat().st_uid != 0
                or stat.S_IMODE(item.stat().st_mode) & 0o022
                for item in path.parents
            )
        ):
            raise ValueError('Runtime entry is not trusted')
        entry = runpy.run_path(str(path))
        entry['verify_program'](args.project)
    except (OSError, RuntimeError, ValueError, KeyError):
        print('GATEWAY_CONFIGURATION_NOT_ADMITTED', file=sys.stderr)
        return 2

    sys.path.append(str(args.project))
    from backend.app.infrastructure.environment_files import (
        EnvironmentFailure,
        canonical,
        decode,
        digest,
        exact,
        persisted_write,
        protected_directory,
        read_entry,
        read_protected,
        require,
    )

    try:
        stage = None
        previous = None
        if release_stage:
            from backend.app.infrastructure.environment_release_gateway import (
                RECEIPT,
                gateway_release,
            )

            installations, previous, stage = gateway_release(args, entry)
        else:
            installations = [
                installed_site(Path(anchor), expected, args.runtime_sha256, entry['verify_program'])
                for anchor, expected in args.site
            ]
        code = 'GATEWAY_POLICY_MISMATCH'
        purposes = {item.description['purpose'] for item in installations}
        isolated_candidate = len(installations) == 1 and purposes == {'CANDIDATE'}
        ordinary_pair = len(installations) == 2 and purposes == {'DEVELOPMENT', 'INTEGRATION'}
        require(
            (isolated_candidate or ordinary_pair)
            and len({item.environment_id for item in installations}) == len(installations)
            and len({item.ingress_group for item in installations}) == len(installations),
            code,
        )
        if isolated_candidate:
            from backend.app.management.release_validation import verify_validation_frontend

            candidate = installations[0]
            verify_validation_frontend(
                candidate.path('frontend'),
                candidate.project,
                candidate.description['release_validation'],
            )
        vite = development_sockets(args.vite_site or (), installations)
        all_credentials = decode(read_protected(args.hashes_file), code)
        exact(all_credentials, [item.environment_id for item in installations], code)
        output = ''.join(
            site_block(
                item,
                all_credentials[item.environment_id],
                previous_frontend=previous if release_stage and index == 0 else None,
                vite_socket=vite.get(item.environment_id),
            )
            for index, item in enumerate(installations)
        )
        contents = (
            '{\n    admin off\n    auto_https disable_redirects\n    skip_install_trust\n'
            '    servers {\n        strict_sni_host on\n    }\n}\n\n' + output
        ).encode('utf-8')
        require(args.output.name == 'Caddyfile', code)
        with protected_directory(args.output.parent) as fd:
            mode = 0o400
            if args.gateway_group is not None:
                directory = os.fstat(fd)
                require(
                    0 < args.gateway_group < 2**31
                    and directory.st_gid == args.gateway_group
                    and stat.S_IMODE(directory.st_mode) == 0o2750
                    and all(item.group != args.gateway_group for item in installations),
                    'GATEWAY_GROUP_NOT_ADMITTED',
                )
                mode = 0o440
            if release_stage:
                facts = canonical({**stage, 'gateway_configuration_sha256': digest(contents)})
                for name, raw, permissions in (
                    (args.output.name, contents, mode),
                    (RECEIPT, facts, 0o444),
                ):
                    try:
                        previous_raw = read_entry(fd, name, owner=0, reject_writers=0o222)
                    except FileNotFoundError:
                        persisted_write(fd, name, raw, mode=permissions)
                        previous_raw = read_entry(fd, name, owner=0, reject_writers=0o222)
                    found = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    require(
                        previous_raw == raw and stat.S_IMODE(found.st_mode) == permissions, code
                    )
                os.fsync(fd)
            else:
                persisted_write(fd, args.output.name, contents, mode=mode)
    except (EnvironmentFailure, OSError, TypeError, ValueError, KeyError):
        print('GATEWAY_CONFIGURATION_NOT_ADMITTED', file=sys.stderr)
        return 2
    print(f'GATEWAY_CONFIGURATION {digest(contents)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
