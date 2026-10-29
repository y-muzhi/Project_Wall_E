"""Offline child: install guards before importing any test or product module."""
import ipaddress
import os
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit, parse_qs


def install_guards(root, temporary):
    root, temporary = Path(root).resolve(), Path(temporary).resolve()
    def local(host):
        if host in ('localhost', None): return True
        try: return ipaddress.ip_address(host).is_loopback
        except ValueError: return False
    def audit(event, args):
        if event == 'socket.getaddrinfo' and not local(args[0]):
            raise PermissionError('Offline checks forbid external DNS')
        if event == 'socket.connect' and isinstance(args[1], tuple) and not local(args[1][0]):
            raise PermissionError('Offline checks forbid external network connections')
        if event == 'sqlite3.connect':
            name = os.fspath(args[0])
            if name == ':memory:': return
            if name.startswith('file:'):
                parsed = urlsplit(name)
                if parse_qs(parsed.query).get('mode') == ['memory']: return
                name = unquote(parsed.path)
                if os.name == 'nt' and len(name)>2 and name[0]=='/' and name[2]==':': name=name[1:]
            if not Path(name).resolve().is_relative_to(temporary):
                raise PermissionError('Offline SQLite must stay inside the owned temporary directory')
        if event == 'open' and not isinstance(args[0], int):
            path = Path(os.fsdecode(args[0])).resolve()
            if path.is_relative_to(root/'data') or path.parent == root and path.name.startswith('.env') and path.name != '.env.example':
                raise PermissionError('Offline checks cannot access user data or local credentials')
    sys.addaudithook(audit)


def main():
    root = Path(__file__).resolve().parents[1]
    install_guards(root, Path(os.environ['WALLE_CHECK_TEMP']).resolve(strict=True))
    sys.path.insert(0, str(root))
    import pytest
    return pytest.main(sys.argv[1:])


if __name__ == '__main__': raise SystemExit(main())
