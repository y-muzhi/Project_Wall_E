"""Verify the actual closed application's narrow read contract through its Unix peer."""

from contextlib import closing
from http.client import HTTPConnection
import json
import socket
import struct

from .environment_files import digest, require

UNVERIFIED = 'RECOVERY_APPLICATION_UNVERIFIED'
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def unix_reply(path, peer, method, target, headers):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
        channel.settimeout(4)
        channel.connect(str(path))
        credentials = channel.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')
        )
        require(struct.unpack('3i', credentials) == peer, UNVERIFIED)
        with closing(HTTPConnection('local-recovery')) as http:
            http.sock = channel
            http.request(method, target, headers=headers)
            with http.getresponse() as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                require(
                    len(raw) <= MAX_RESPONSE_BYTES
                    and response.getheader('Content-Type') == 'application/json'
                    and response.getheader('Cache-Control') == 'no-store',
                    UNVERIFIED,
                )
                return response.status, dict(response.getheaders()), json.loads(raw)


def check_identity(headers, policy):
    expected = {
        'x-wall-e-environment-id': policy['environment_id'],
        'x-wall-e-data-generation': policy['data_generation'],
        'x-wall-e-run-id': policy['run_id'],
    }
    actual = {key.lower(): value for key, value in headers.items()}
    require(all(actual.get(key) == value for key, value in expected.items()), UNVERIFIED)


def checked_read(reply, policy):
    status, headers, envelope = reply
    check_identity(headers, policy)
    require(
        status == 200
        and envelope['success'] is True
        and envelope['error'] is None
        and envelope['data'] is not None,
        UNVERIFIED,
    )
    return envelope['data']


def checked_refusal(reply, policy, status, code):
    actual, headers, envelope = reply
    check_identity(headers, policy)
    require(
        actual == status
        and envelope['success'] is False
        and envelope['data'] is None
        and envelope['error']['code'] == code,
        UNVERIFIED,
    )


def check_handshake(reply, policy, reference):
    result = checked_read(reply, policy)
    maintenance = result['maintenance']
    current = maintenance['recovery_read']
    statuses = {item['code']: item['state'] for item in result['capabilities']}
    require(
        result['binding_protocol'] == 1
        and result['phase'] == 'READY'
        and result['environment_id'] == policy['environment_id']
        and result['data_generation'] == policy['data_generation']
        and result['run_id'] == policy['run_id']
        and result['configuration_sha256'] == policy['configuration_sha256']
        and result['access'] == {'client_kind': 'AUTOMATION', 'permission': 'READ_ONLY'}
        and {key for key, state in statuses.items() if state == 'READY'} == {'DOCUMENT_READ'},
        UNVERIFIED,
    )
    require(
        maintenance['contract_version'] == 1
        and maintenance['admission'] == 'CLOSED'
        and maintenance['maintenance_id'] == policy['operation_id']
        and maintenance['stage'] == 'BLOCKED'
        and maintenance['control_revision'] == policy['control_revision']
        and maintenance['allowed_drain_actions'] == []
        and current['status'] == 'AVAILABLE'
        and current['deployment_id'] == policy['deployment_id']
        and current['data_generation'] == policy['data_generation']
        and current['control_revision'] == policy['control_revision']
        and current['verification_ref'] == reference
        and current['verified_scopes'] == policy['verified_scopes'],
        UNVERIFIED,
    )


def check_application(reply, policy, read_sha, wrong_generation, plan):
    check_handshake(reply('GET', '/api/v1/environment'), policy, read_sha)
    route = '/api/v1/requirements'
    requirement = plan['requirement_id']
    document = plan['document_id']
    listing = checked_read(reply('GET', route), policy)
    detail = route + '/' + str(requirement)
    view = checked_read(reply('GET', detail), policy)
    current = checked_read(
        reply('GET', f'{detail}/current-document?document_id={document}'), policy
    )
    markdown = current['markdown_content']
    require(
        type(listing['items']) is list
        and view['requirement']['id'] == requirement
        and current['id'] == document
        and type(markdown) is str
        and bool(markdown.strip())
        and digest(markdown.encode('utf-8')) == plan['markdown_sha256'],
        UNVERIFIED,
    )
    checked_read(reply('GET', f'{detail}/comment-index?document_id={document}'), policy)
    checked_read(reply('GET', f'{detail}/revisions?document_id={document}'), policy)
    checked_refusal(reply('POST', route), policy, 403, 'RECOVERY_READ_ONLY')
    checked_refusal(reply('GET', detail + '/guide-runs'), policy, 403, 'RECOVERY_READ_ONLY')
    checked_refusal(
        reply('GET', route, data_generation=wrong_generation),
        policy,
        409,
        'DATA_GENERATION_MISMATCH',
    )
    return {
        'requirement_id': requirement,
        'document_id': document,
        'markdown_sha256': plan['markdown_sha256'],
    }
