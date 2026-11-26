"""Protected management entry, socket identity and fixed static output."""

from contextlib import contextmanager
from dataclasses import dataclass, field
import os
from pathlib import Path
import socket
import stat

from backend.app.infrastructure.environment_files import (
    absolute,
    decode,
    exact,
    identity,
    no_acl,
    protected_directory,
    require,
)
from backend.app.infrastructure.environment_installation import identity_record, sha_value

from .operation_contract import INVALID, RESOURCE, SCOPE, https_origin, installed_record, text
from .release_artifacts import indexed_files, snapshot_file

WEB_POLICY = 'management-web.v1.json'


@dataclass(frozen=True)
class ManagementWeb:
    display_name: str
    origin: str
    socket_directory: Path = field(repr=False)
    socket_identity: dict = field(repr=False)
    ingress_group: int
    frontend: Path = field(repr=False)
    identities: dict[str, str] = field(repr=False)

    @property
    def socket_path(self):
        return self.socket_directory / 'manager.sock'


def load_web(path, expected, catalog, installation):
    require(path.is_absolute() and path.name == WEB_POLICY and sha_value(expected), INVALID)
    raw = exact(
        installed_record(path, expected),
        (
            'format_version',
            *catalog.scope,
            'display_name',
            'public_origin',
            'socket_directory',
            'socket_identity',
            'ingress_group',
            'frontend_root',
            'frontend_index',
            'identities',
        ),
        INVALID,
    )
    require(type(raw['format_version']) is int and raw['format_version'] == 1, INVALID)
    require(all(raw[key] == value for key, value in catalog.scope.items()), SCOPE)
    title = text(raw['display_name'], maximum=120)
    origin = https_origin(raw['public_origin'])
    require(
        all(
            entry['origin'] != origin.removesuffix(':443')
            for entry in catalog.business_entries.values()
        ),
        INVALID,
    )
    group = raw['ingress_group']
    require(type(group) is int and 1 <= group < 2**31 and group != installation.gid, INVALID)
    socket_dir = absolute(raw['socket_directory'], INVALID)
    require(len(os.fsencode(socket_dir / 'manager.sock')) < 108, INVALID)
    identity_record(raw['socket_identity'], INVALID)
    require(type(raw['identities']) is dict and raw['identities'], INVALID)
    require(
        all(
            name in catalog.principals and kind in ('WEB', 'AUTOMATION')
            for name, kind in raw['identities'].items()
        ),
        INVALID,
    )
    frontend = absolute(raw['frontend_root'], INVALID)
    spec = exact(raw['frontend_index'], ('path', 'sha256', 'bytes'), INVALID)
    require(sha_value(spec['sha256']) and type(spec['bytes']) is int and spec['bytes'] > 0, INVALID)
    observed, contents = snapshot_file(
        absolute(spec['path'], INVALID), 0o444, spec['bytes'], capture=True
    )
    require(observed == spec['sha256'], RESOURCE)
    indexed_files(decode(contents, INVALID), frontend, 'frontend')
    require((frontend / 'index.html').is_file(), RESOURCE)
    web = ManagementWeb(
        title, origin, socket_dir, raw['socket_identity'], group, frontend, raw['identities']
    )
    verify_socket_directory(web, installation)
    return web


def verify_socket_directory(web, installation):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_DIRECTORY
    with protected_directory(web.socket_directory.parent) as parent:
        fd = os.open(web.socket_directory.name, flags, dir_fd=parent)
        try:
            info = os.fstat(fd)
            require(
                stat.S_IMODE(info.st_mode) == 0o2710
                and info.st_uid == installation.uid
                and info.st_gid == web.ingress_group
                and identity(info) == web.socket_identity,
                RESOURCE,
            )
            no_acl(fd)
        finally:
            os.close(fd)


@contextmanager
def listening_socket(web, installation):
    verify_socket_directory(web, installation)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        target = web.socket_path
        listener.bind(str(target))
        original = identity(target.lstat())
        try:
            require(target.lstat().st_gid == web.ingress_group, RESOURCE)
            os.chmod(target, 0o660)
            yield listener
        finally:
            try:
                status = target.lstat()
            except FileNotFoundError:
                status = None
            if (
                status is not None
                and stat.S_ISSOCK(status.st_mode)
                and identity(status) == original
            ):
                target.unlink()
