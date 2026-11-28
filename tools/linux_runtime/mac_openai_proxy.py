"""Relay only the development VM's OpenAI CONNECT requests to the Mac loopback proxy."""

import argparse
import ipaddress
import select
import socket
import socketserver
import time

CONNECT = b'CONNECT api.openai.com:443 HTTP/1.1'
DESTINATION = b'Host: api.openai.com:443'
HEADER_LIMIT = 8192
TIMEOUT = 10
# Allow the document provider's 30-minute response timeout to take effect.
IDLE_TIMEOUT = 1860


def read_headers(stream, connection):
    block = bytearray()
    deadline = time.monotonic() + TIMEOUT
    while len(block) < HEADER_LIMIT:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        connection.settimeout(remaining)
        fragment = stream.read(1)
        if not fragment:
            break
        block.extend(fragment)
        if block.endswith(b'\r\n\r\n'):
            return bytes(block[:-4]).split(b'\r\n')
    raise ValueError('Malformed proxy headers')


def relay(client, upstream):
    client.settimeout(TIMEOUT)
    upstream.settimeout(TIMEOUT)
    peers = {client: upstream, upstream: client}
    while readable := select.select([client, upstream], [], [], IDLE_TIMEOUT)[0]:
        for source in readable:
            data = source.recv(65536)
            if not data:
                return
            peers[source].sendall(data)


class OpenAIConnect(socketserver.StreamRequestHandler):
    rbufsize = 0

    def handle(self):
        try:
            headers = read_headers(self.rfile, self.request)
            if not headers or headers[0] not in (CONNECT, b'CONNECT api.openai.com:443 HTTP/1.0'):
                self.request.sendall(b'HTTP/1.1 403 Forbidden\r\n\r\n')
                return
            with socket.create_connection(
                ('127.0.0.1', self.server.upstream_port), TIMEOUT
            ) as upstream:
                upstream.sendall(CONNECT + b'\r\n' + DESTINATION + b'\r\n\r\n')
                with upstream.makefile('rb', buffering=0) as response:
                    proxy_headers = read_headers(response, upstream)
                if not proxy_headers or proxy_headers[0].split()[1:2] != [b'200']:
                    self.request.sendall(b'HTTP/1.1 502 Bad Gateway\r\n\r\n')
                    return
                self.request.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                relay(self.request, upstream)
        except (OSError, ValueError):
            return


class DevelopmentProxy(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def verify_request(self, request, client_address):
        return client_address[0] == self.guest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', required=True, type=ipaddress.IPv4Address)
    parser.add_argument('--guest', required=True, type=ipaddress.IPv4Address)
    parser.add_argument('--port', type=int, default=17890)
    parser.add_argument('--upstream-port', type=int, default=7890)
    parser.add_argument('--duration', type=float)
    args = parser.parse_args()
    private_networks = (
        ipaddress.IPv4Network('10.0.0.0/8'),
        ipaddress.IPv4Network('172.16.0.0/12'),
        ipaddress.IPv4Network('192.168.0.0/16'),
    )
    if args.bind == args.guest or not any(
        args.bind in network and args.guest in network for network in private_networks
    ):
        parser.error('Provide distinct private IPv4 addresses for the VM bridge and guest')
    with DevelopmentProxy((str(args.bind), args.port), OpenAIConnect) as server:
        server.guest = str(args.guest)
        server.upstream_port = args.upstream_port
        print('Development OpenAI proxy ready', flush=True)
        if args.duration is None:
            server.serve_forever()
        else:
            deadline = time.monotonic() + args.duration
            server.timeout = 0.5
            while time.monotonic() < deadline:
                server.handle_request()


if __name__ == '__main__':
    main()
