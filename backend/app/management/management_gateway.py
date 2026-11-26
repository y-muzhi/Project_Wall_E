"""Generate the management-only route for the already installed Caddy runtime."""

import os
import re
import stat

from backend.app.infrastructure.environment_files import (
    digest,
    exact,
    persisted_write,
    protected_directory,
    require,
)

from .operation_contract import RESOURCE, installed_record

BCRYPT = re.compile(r'\$2[aby]\$[0-9]{2}\$[A-Za-z0-9./]{53}')
SAFE_PATH = re.compile(r'/[A-Za-z0-9._/-]{1,106}')


def render_gateway(web, installation, accounts):
    exact(accounts, web.identities, RESOURCE)
    require(
        all(type(item) is str and BCRYPT.fullmatch(item) for item in accounts.values()), RESOURCE
    )
    socket, frontend = str(web.socket_path), str(web.frontend)
    require(SAFE_PATH.fullmatch(socket) and SAFE_PATH.fullmatch(frontend), RESOURCE)
    records = ''.join(
        '            ' + name + ' ' + accounts[name] + '\n' for name in sorted(accounts)
    )
    return f"""{{
    admin off
    auto_https disable_redirects
    skip_install_trust
    servers {{
        strict_sni_host on
    }}
}}
{web.origin} {{
    bind 127.0.0.1
    tls internal
    route {{
        basicauth bcrypt "walle-manager:{installation.manager_id}" {{
{records}        }}
        header {{
            Referrer-Policy "no-referrer"
            X-Content-Type-Options "nosniff"
            Content-Security-Policy "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'"
        }}
        @controls path /.well-known/walle-management.json /management/api/v1 /management/api/v1/*
        handle @controls {{
            request_header -Authorization
            request_header -Proxy-Authorization
            request_header -Cookie
            request_header -Forwarded
            request_header -X-WALL-E-Auth-*
            reverse_proxy unix/{socket} {{
                header_up X-WALL-E-Auth-Principal {{http.auth.user.id}}
            }}
        }}
        @assets path /assets/*
        handle @assets {{
            root * {frontend}
            file_server
        }}
        @entry path /
        handle @entry {{
            header Cache-Control "no-store"
            root * {frontend}
            rewrite * /index.html
            file_server
        }}
        handle {{
            respond 404
        }}
    }}
}}
""".encode('utf-8')


def install_gateway(web, installation, args):
    config = render_gateway(web, installation, installed_record(args.web_hashes))
    require(
        args.web_output.name == 'Caddyfile'
        and type(args.gateway_group) is int
        and args.gateway_group > 0
        and args.gateway_group not in (installation.gid, web.ingress_group),
        RESOURCE,
    )
    with protected_directory(args.web_output.parent) as fd:
        info = os.fstat(fd)
        require(
            info.st_gid == args.gateway_group and stat.S_IMODE(info.st_mode) == 0o2750, RESOURCE
        )
        persisted_write(fd, args.web_output.name, config, mode=0o440)
    return {'status': 'MANAGEMENT_GATEWAY_PREPARED', 'sha256': digest(config)}
