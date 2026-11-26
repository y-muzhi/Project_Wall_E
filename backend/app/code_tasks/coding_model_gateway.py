"""Execute one original audited Coding model call through its fixed supplier route."""

from base64 import b64encode
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from urllib.parse import quote

import httpx

from backend.app.infrastructure.openai_transport import configured_proxy
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import MAX_SAFE_INTEGER

from .coding_model_admission import CodingModelAdmission, effective_coding_binding
from .coding_model_ledger import (
    append_frame,
    finish_call,
    mark_sending,
    mark_sent,
    prepare_audit_request,
    release_unsent,
    reserve_call,
)
from .coding_model_listener import CodingGatewayError
from .coding_model_request import CodingModelProtocolError, parse_request, prepare_request
from .coding_model_sse import CodingSseError, CodingSseReader, CodingSseResponse
from .task_model_ingress import read_original_open_window


@dataclass(frozen=True)
class CodingModelDeployment:
    admissions: tuple[CodingModelAdmission, ...]

    def __post_init__(self):
        if (
            type(self.admissions) is not tuple
            or not self.admissions
            or any(type(row) is not CodingModelAdmission for row in self.admissions)
            or len({row.evidence_ref for row in self.admissions}) != len(self.admissions)
        ):
            raise ValueError('Exact Coding model deployment admissions required')


def _check_credentials(value, credentials):
    variants = {
        item
        for secret in credentials
        for item in (secret, quote(secret, safe=''), b64encode(secret.encode()).decode('ascii'))
    }
    pending = [value]
    while pending:
        current = pending.pop()
        if type(current) is str and any(secret in current for secret in variants):
            raise CodingModelProtocolError('CODING_MODEL_REQUEST_CREDENTIAL_REJECTED')
        if type(current) is dict:
            pending.extend(current.keys())
            pending.extend(current.values())
        elif type(current) is list:
            pending.extend(current)


class CodingModelGateway:
    def __init__(self, runtime, deployment, *, transport_factory: Callable | None = None):
        if type(deployment) is not CodingModelDeployment:
            raise ValueError('Trusted Coding model deployment required')
        self._runtime = runtime
        self._admissions = {value.evidence_ref: value for value in deployment.admissions}
        self._transport_factory = transport_factory

    def __call__(self, credential_ref, proof, raw, verify, stream, cancelled, *, instance_secret):
        native = parse_request(raw)
        alias = native['model']
        db = self._runtime.database
        catalog = self._runtime.catalog
        with db.transaction() as connection:
            binding = effective_coding_binding(
                connection, catalog, self._admissions, proof.window, alias, operation_time(None)
            )
        request = prepare_request(native, binding.contract)
        credentials = (binding.admission.model.api_key, instance_secret)
        _check_credentials(native, credentials)
        audit = prepare_audit_request(proof, request, binding, credentials)
        with db.transaction(write=True) as connection:
            call = reserve_call(
                connection,
                catalog,
                self._admissions,
                credential_ref,
                proof,
                request,
                binding,
                audit,
            )
        if call is None:
            raise CodingGatewayError('budget')
        self._dispatch(call, request, verify, stream, cancelled, credentials)

    def _open(self, call):
        with self._runtime.database.transaction() as connection:
            return (
                read_original_open_window(connection, call.window, call.credential_ref)
                == call.window
            )

    def _dispatch(self, call, request, verify, stream, cancelled, credentials):
        db = self._runtime.database
        started = monotonic()
        deadline = started + call.binding.admission.max_duration_seconds
        state = CodingSseResponse(
            call.gateway_request_id,
            call.binding.admission.usage,
            model_name=call.binding.admission.model.model_name,
        )
        entered = completed = False

        def duration():
            return min(MAX_SAFE_INTEGER, max(0, round((monotonic() - started) * 1000)))

        def active():
            if cancelled() or monotonic() >= deadline or not self._open(call):
                raise CodingGatewayError('hold')

        def complete():
            with db.transaction(write=True) as connection:
                return finish_call(
                    connection,
                    call,
                    state.finalize(),
                    complete=True,
                    finish_reason=state.finish_reason,
                    duration_ms=duration(),
                    cancelled=cancelled(),
                )

        try:
            active()
            verified = verify()
            with db.transaction(write=True) as connection:
                mark_sending(connection, call, verified)
            active()
            contract = call.binding.contract
            with self._client(deadline - monotonic(), contract.provider) as client:
                active()
                entered = True
                with client.stream(
                    'POST',
                    contract.supplier_endpoint,
                    content=request.supplier_body,
                    headers={
                        'Authorization': 'Bearer ' + credentials[0],
                        'Content-Type': 'application/json',
                        'Accept': 'text/event-stream',
                        'Accept-Encoding': 'identity',
                    },
                ) as response:
                    self._accept_response(call, response, credentials)
                    done = self._relay(call, state, response, stream, active, credentials)
                    if done is None:
                        raise CodingGatewayError('hold')
                    relay_end = complete()
                    completed = True
                    if relay_end:
                        stream(done)
                    else:
                        raise CodingGatewayError('hold')
        except Exception as error:
            if not completed:
                stopped = cancelled() or not self._open(call)
                with db.transaction(write=True) as connection:
                    if entered:
                        finish_call(
                            connection,
                            call,
                            state.usage,
                            complete=False,
                            finish_reason=state.finish_reason,
                            duration_ms=duration(),
                            cancelled=stopped,
                        )
                    else:
                        release_unsent(connection, call)
            if isinstance(error, CodingGatewayError):
                raise
            raise CodingGatewayError('hold') from None

    def _client(self, remaining, provider):
        if remaining <= 0:
            raise CodingGatewayError('hold')
        transport = (
            httpx.HTTPTransport(
                proxy=configured_proxy() if provider == 'openai' else None,
                retries=0,
                trust_env=False,
                http2=False,
            )
            if self._transport_factory is None
            else self._transport_factory()
        )
        return httpx.Client(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(
                connect=min(10, remaining),
                read=min(15, remaining),
                write=min(10, remaining),
                pool=min(10, remaining),
            ),
        )

    def _accept_response(self, call, response, credentials):
        trace = response.headers.get('x-request-id')
        if trace is not None:
            try:
                if not 1 <= len(trace) <= 1024:
                    trace = None
                else:
                    _check_credentials(trace, credentials)
            except CodingModelProtocolError:
                trace = None
        with self._runtime.database.transaction(write=True) as connection:
            mark_sent(connection, call, trace)
        media = response.headers.get('content-type', '').partition(';')[0].strip().lower()
        if (
            response.status_code != 200
            or media != 'text/event-stream'
            or response.headers.get('content-encoding', 'identity').lower() != 'identity'
        ):
            raise CodingGatewayError('hold')

    def _relay(self, call, state, response, stream, active, credentials):
        reader = CodingSseReader()
        number = 0
        for chunk in response.iter_raw():
            active()
            frames = reader.feed(chunk)
            for frame in frames:
                active()
                number += 1
                invalid = False
                try:
                    state.observe(frame)
                    _check_credentials(frame.audit, credentials)
                except (CodingSseError, CodingModelProtocolError):
                    invalid = True
                with self._runtime.database.transaction(write=True) as connection:
                    append_frame(connection, call, number, frame.audit, credentials, state.usage)
                if invalid or state.usage.status == 'DISPUTED':
                    raise CodingGatewayError('hold')
                if frame.kind == 'DONE':
                    if next(frames, None) is not None or reader.has_pending:
                        raise CodingGatewayError('hold')
                    return frame.wire
                active()
                stream(frame.wire)
        return None
