"""Explicit local OpenAI proxy, independent from OS and generic proxy settings."""

import ipaddress
import logging
import os
from urllib.parse import urlsplit

import httpx

from .resources import ConfigInvalid

PROXY_ENV = 'OPENAI_HTTP_PROXY'


def validate_proxy(value):
    try:
        if type(value) is not str or not value or value != value.strip():
            raise ValueError('Invalid proxy')
        parsed = urlsplit(value)
        if (
            parsed.scheme != 'http'
            or parsed.hostname is None
            or not ipaddress.ip_address(parsed.hostname).is_loopback
            or parsed.port is None
            or not 1 <= parsed.port <= 65535
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ('', '/')
            or parsed.query
            or parsed.fragment
            or any(ord(character) < 33 or ord(character) > 126 for character in value)
        ):
            raise ValueError('Invalid proxy')
        host = parsed.hostname
        if ':' in host:
            host = '[' + host + ']'
        return 'http://' + host + ':' + str(parsed.port)
    except (TypeError, ValueError):
        raise ConfigInvalid(
            'OpenAI proxy must be a credential-free local HTTP IP and port'
        ) from None


def configured_proxy(environment=None):
    values = os.environ if environment is None else environment
    value = values.get(PROXY_ENV)
    return None if value is None else validate_proxy(value)


def create_transport():
    # A CONNECT tunnel to the fixed HTTPS API; certificate checking remains on.
    return httpx.AsyncHTTPTransport(
        proxy=configured_proxy(), retries=0, trust_env=False, verify=True
    )


def report_transport_error(operation, error):
    if operation not in ('input_count', 'responses'):
        raise ValueError('Unknown OpenAI transport operation')
    kinds = []
    current = error
    seen = set()
    while current is not None and id(current) not in seen and len(kinds) < 4:
        seen.add(id(current))
        kinds.append(type(current).__name__)
        current = current.__cause__
    logging.getLogger(__name__).warning(
        'openai_transport_error operation=%s types=%s', operation, ','.join(kinds)
    )
