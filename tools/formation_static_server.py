"""Serve an owned temporary browser build and proxy only the fixed isolated local API."""

import argparse
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HOP_HEADERS = {
    'connection',
    'keep-alive',
    'proxy-authenticate',
    'proxy-authorization',
    'te',
    'trailer',
    'transfer-encoding',
    'upgrade',
    'host',
    'content-length',
}


def serve(directory):
    from tools.quality_python import install_guards

    temporary = Path(os.environ['WALLE_CHECK_TEMP']).resolve(strict=True)
    output = directory.resolve(strict=True)
    if not output.is_relative_to(temporary):
        raise ValueError('Static test build must stay within its owned temporary directory')
    if not (output / 'tests/browser/formation-product.html').is_file():
        raise ValueError('Owned production fixture entry required')
    install_guards(ROOT, temporary)

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(output), **kwargs)

        def log_message(self, format, *args):
            return

        def proxy(self):
            if not self.path.startswith('/api/'):
                self.send_error(405, 'Only the isolated API accepts writes')
                return
            length = int(self.headers.get('Content-Length', '0'))
            body = self.rfile.read(length) if length else None
            headers = {
                name: value
                for name, value in self.headers.items()
                if name.lower() not in HOP_HEADERS
            }
            request = Request(
                'http://127.0.0.1:8217' + self.path,
                data=body,
                headers=headers,
                method=self.command,
            )
            try:
                response = urlopen(request, timeout=60)
            except HTTPError as error:
                response = error
            except URLError:
                self.send_error(502, 'Isolated API unavailable')
                return
            with response:
                data = response.read()
                self.send_response(response.status)
                for name, value in response.headers.items():
                    if name.lower() not in HOP_HEADERS:
                        self.send_header(name, value)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    # The browser may cancel a read when its panel is hidden.
                    return

        def do_GET(self):
            if self.path.startswith('/api/'):
                self.proxy()
            else:
                super().do_GET()

        do_POST = proxy
        do_PATCH = proxy
        do_PUT = proxy
        do_DELETE = proxy

    with ThreadingHTTPServer(('127.0.0.1', 5187), Handler) as server:
        print('OWNED_PYTHON_BROWSER_SERVER_READY', flush=True)
        server.serve_forever(poll_interval=0.2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    serve(args.directory)
