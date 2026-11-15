"""Registered CHECK_DRIVER root. Chromium receives no result writer or sockets."""

import argparse
import os
import shutil
import sys
from base64 import b64encode
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit
from uuid import uuid4

from backend.app.shared.time import utc_milliseconds
from backend.app.shared.validation import strict_integer

from .check_case_evidence import CheckEvidenceUnknown, DriverFrameIdentity
from .check_case_pack import CaseBasis, CasePackLimits, decode_case_pack
from .check_case_values import byte_literal, relative_target
from .check_driver_bootstrap import (
    BROWSER_REQUEST_BODY_MAX_BYTES,
    BROWSER_RESPONSE_BODY_MAX_BYTES,
    original_result_writer,
    read_control_frame,
    write_frame,
    write_result_frame,
)
from .check_runner_bundle import exact_record, references, valid_sha256
from .owned_browser_relay import _REQUEST, _response_headers

_DRIVER_PROTOCOL = 'CHECK20-BROWSER-1'
_INPUT_LIMIT = BROWSER_REQUEST_BODY_MAX_BYTES


def _driver_input(row, digest):
    value = exact_record(
        row,
        ('protocol', 'identity', 'case_pack', 'basis_refs', 'limits', 'origin_refs'),
    )
    if value['protocol'] != _DRIVER_PROTOCOL or not valid_sha256(digest):
        raise CheckEvidenceUnknown('ORIGINAL_BROWSER_DRIVER_INPUT_REQUIRED')
    raw = byte_literal(value['case_pack'], _INPUT_LIMIT)
    if sha256(raw).hexdigest() != digest:
        raise CheckEvidenceUnknown('ORIGINAL_BROWSER_CASE_PACK_DIFFERS')
    origins = references(value['origin_refs'], nonempty=True)
    basis = tuple(
        CaseBasis(**exact_record(item, CaseBasis.__dataclass_fields__))
        for item in value['basis_refs']
    )
    pack = decode_case_pack(
        raw,
        limits=CasePackLimits(**exact_record(value['limits'], CasePackLimits.__dataclass_fields__)),
        basis_refs=basis,
        endpoint_refs=origins,
    )
    if pack.driver_kind != 'BROWSER':
        raise CheckEvidenceUnknown('ORIGINAL_BROWSER_CASE_PACK_REQUIRED')
    identity = DriverFrameIdentity(
        **exact_record(value['identity'], DriverFrameIdentity.__dataclass_fields__)
    )
    return (
        identity,
        pack,
        {alias: f'http://o{index}.localhost' for index, alias in enumerate(origins, 1)},
    )


def browser_input(identity, raw, basis, limits, origins):
    return {
        'protocol': _DRIVER_PROTOCOL,
        'identity': asdict(identity),
        'case_pack': b64encode(raw).decode('ascii'),
        'basis_refs': [asdict(value) for value in basis],
        'limits': asdict(limits),
        'origin_refs': list(origins),
    }


class BrowserRelayClient:
    """Private ordered controller RPC. Results always use a different pipe."""

    def __init__(self, incoming, outgoing, origins):
        self._incoming, self._outgoing = incoming, outgoing
        self._origins = {origin: alias for alias, origin in origins.items()}
        self._sequence = 1
        self.failed = False

    def forward(self, route):
        try:
            if self.failed:
                raise CheckEvidenceUnknown('ORIGINAL_BROWSER_RELAY_CLOSED')
            request = route.request
            address = urlsplit(request.url)
            origin = f'{address.scheme}://{address.netloc}'
            if origin not in self._origins or address.fragment:
                raise CheckEvidenceUnknown('ORIGINAL_BROWSER_ORIGIN_UNAVAILABLE')
            path = address.path or '/'
            if address.query:
                path += '?' + address.query
            headers = request.all_headers()
            if {'authorization', 'proxy-authorization', 'cookie', 'upgrade'} & headers.keys():
                raise CheckEvidenceUnknown('ORIGINAL_BROWSER_REQUEST_HEADERS_UNSUPPORTED')
            sequence = self._sequence
            body = request.post_data_buffer or b''
            if len(body) > _INPUT_LIMIT:
                raise CheckEvidenceUnknown('ORIGINAL_BROWSER_BODY_LIMIT')
            write_frame(
                self._outgoing,
                {
                    'seq': sequence,
                    'origin_ref': self._origins[origin],
                    'path': relative_target(path),
                    'method': request.method,
                    'headers': {key: headers[key] for key in headers.keys() & _REQUEST},
                    'body': b64encode(body).decode('ascii'),
                },
            )
            self._outgoing.flush()
            response = exact_record(
                read_control_frame(self._incoming), ('seq', 'status', 'headers', 'body')
            )
            if strict_integer(response['seq'], 'seq') != sequence:
                raise CheckEvidenceUnknown('ORIGINAL_BROWSER_RELAY_REPLY_DIFFERS')
            status = strict_integer(response['status'], 'status', minimum=200, maximum=599)
            checked = _response_headers(status, list(response['headers'].items()))
            received = byte_literal(response['body'], BROWSER_RESPONSE_BODY_MAX_BYTES)
            self._sequence += 1
            route.fulfill(status=status, headers=dict(checked), body=received)
        except Exception:  # noqa: BLE001 - fail closed at the browser boundary
            self.failed = True
            route.abort('blockedbyclient')

    def close_websocket(self, route):
        self.failed = True
        route.close(code=1008)


def _locator(page, value):
    kind, name, accessible_name = value
    if kind == 'TEST_ID':
        return page.get_by_test_id(name)
    if kind != 'ROLE':
        raise CheckEvidenceUnknown('ORIGINAL_BROWSER_LOCATOR_REQUIRED')
    return page.get_by_role(name, name=accessible_name, exact=True)


def _remaining(deadline):
    time = int((deadline - monotonic()) * 1000)
    if time <= 0:
        raise CheckEvidenceUnknown('ORIGINAL_BROWSER_CASE_DEADLINE')
    return time


def _step(page, value, origins, deadline):
    op = value.op
    if op == 'NAVIGATE':
        alias, path = value.operands
        page.goto(
            origins[alias] + path, wait_until='domcontentloaded', timeout=_remaining(deadline)
        )
        return
    locator = _locator(page, value.operands[0])
    if op == 'CLICK':
        locator.click(timeout=_remaining(deadline))
        return
    item = value.operands[1]
    if op == 'FILL':
        locator.fill(item, timeout=_remaining(deadline))
    elif op == 'SELECT':
        locator.select_option(value=item, timeout=_remaining(deadline))
    elif op == 'PRESS':
        locator.press(item, timeout=_remaining(deadline))
    else:
        raise CheckEvidenceUnknown('ORIGINAL_BROWSER_STEP_REQUIRED')


def _assertion(page, assertion, deadline):
    _remaining(deadline)
    target, expected = assertion.operands
    locator = _locator(page, target)
    if assertion.op == 'VISIBLE':
        actual = locator.is_visible()
    elif assertion.op == 'TEXT':
        actual = locator.inner_text(timeout=_remaining(deadline))
        if len(actual.encode('utf-8')) > 4096:
            raise CheckEvidenceUnknown('ORIGINAL_BROWSER_ASSERTION_TEXT_LIMIT')
    elif assertion.op == 'COUNT':
        actual = locator.count()
    else:
        raise CheckEvidenceUnknown('ORIGINAL_BROWSER_ASSERTION_REQUIRED')
    _remaining(deadline)
    return {
        'assertion_id': assertion.assertion_id,
        'result': 'PASSED' if type(actual) is type(expected) and actual == expected else 'FAILED',
        'actual_value': actual,
    }


@contextmanager
def fresh_browser_profile(scratch, *, can_remove=None):
    # Windows CPython 3.13 mode 0700 replaces the inherited LPAC package ACE.
    # The original scratch already has the exact private low-integrity policy.
    profile = Path(scratch) / ('browser-' + uuid4().hex)
    try:
        os.mkdir(profile, 0o777)
    except OSError as error:
        raise CheckEvidenceUnknown('ORIGINAL_BROWSER_PROFILE_CREATE_FAILED') from error
    try:
        yield str(profile)
    finally:
        if can_remove is not None and not can_remove():
            raise CheckEvidenceUnknown('ORIGINAL_BROWSER_PROFILE_STOP_REQUIRED')
        try:
            shutil.rmtree(profile)
        except OSError as error:
            raise CheckEvidenceUnknown('ORIGINAL_BROWSER_PROFILE_CLEANUP_REQUIRED') from error


def _run_case(chromium, executable, scratch, case, origins, relay):
    deadline = monotonic() + case.timeout_seconds
    with fresh_browser_profile(scratch, can_remove=chromium.profile_can_remove) as profile:
        context = chromium.launch_persistent_context(
            profile,
            executable_path=executable,
            chromium_sandbox=True,
            headless=True,
            service_workers='block',
            accept_downloads=False,
            args=[
                '--disable-background-networking',
                '--disable-component-update',
                '--disable-sync',
            ],
            timeout=_remaining(deadline),
        )
        try:
            context.route('**/*', relay.forward)
            context.route_web_socket('**/*', relay.close_websocket)
            if len(context.pages) > 1:
                raise CheckEvidenceUnknown('ORIGINAL_BROWSER_CONTEXT_NOT_FRESH')
            page = context.pages[0] if context.pages else context.new_page()
            for step in case.steps:
                _step(page, step, origins, deadline)
                if relay.failed:
                    raise CheckEvidenceUnknown('ORIGINAL_BROWSER_RELAY_RESULT_UNVERIFIED')
            facts = [_assertion(page, item, deadline) for item in case.assertions]
        finally:
            context.close()
        if relay.failed:
            raise CheckEvidenceUnknown('ORIGINAL_BROWSER_RELAY_RESULT_UNVERIFIED')
    return facts


def execute_browser(chromium, executable, scratch, identity, pack, origins, relay, writer):
    def record(seq, kind, case_id=None, assertions=()):
        write_result_frame(
            writer,
            {
                'schema_version': 1,
                **asdict(identity),
                'seq': seq,
                'type': kind,
                'case_id': case_id,
                'assertion_results': list(assertions),
                'observed_at': utc_milliseconds(datetime.now(UTC)),
            },
        )

    record(1, 'BEGIN')
    for seq, case in enumerate(pack.cases, 2):
        facts = _run_case(chromium, executable, scratch, case, origins, relay)
        record(seq, 'CASE_RESULT', case.case_id, facts)
    record(len(pack.cases) + 2, 'END')


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--browser', required=True)
    parser.add_argument('--case-pack-sha256', required=True)
    parser.add_argument('--result-handle', required=True)
    args = parser.parse_args(argv)
    with original_result_writer(args.result_handle) as writer:
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            os.set_inheritable(stream.fileno(), False)
        incoming, outgoing = sys.stdin.buffer, sys.stdout.buffer
        identity, pack, origins = _driver_input(read_control_frame(incoming), args.case_pack_sha256)
        relay = BrowserRelayClient(incoming, outgoing, origins)
        runtime = Path(sys.executable).parent
        scratch = runtime.parent / 'scratch' / 'temp'
        if runtime.name != 'runtime' or not scratch.is_dir():
            raise CheckEvidenceUnknown('ORIGINAL_DRIVER_SCRATCH_REQUIRED')
        from .check_driver_pipe_sdk import PipeChromium
        from .check_driver_private_desktop import PrivateBrowserDesktop

        with PrivateBrowserDesktop(), PipeChromium(runtime, private_temp=scratch) as chromium:
            execute_browser(chromium, args.browser, scratch, identity, pack, origins, relay, writer)


if __name__ == '__main__':
    main()
