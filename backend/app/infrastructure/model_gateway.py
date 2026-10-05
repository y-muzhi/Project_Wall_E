"""One fixed D-007 HTTP attempt; task retries and business adoption belong upstream.

The caller must pass the Builder gate and commit its actual AuditRepository
preparation before invoking this private adapter. No public endpoint calls it.
"""
from dataclasses import dataclass, field
import asyncio
import json
from time import monotonic

import httpx

from .audit_data import audit_json, AuditCapacityExceeded, MAX_AUDIT_BYTES
from .model_profile import ModelProfile, ENDPOINT
from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_json_object

# Exact inference codes from the official Ark error table. Unknown codes are
# not matched by prefix or by a provider's free-text error message.
RETRY_CODES = frozenset({'RateLimitExceeded.EndpointRPMExceeded', 'RateLimitExceeded.EndpointTPMExceeded',
    'RateLimitExceeded.EndpointFlexTPMExceeded', 'ModelAccountRpmRateLimitExceeded',
    'ModelAccountTpmRateLimitExceeded', 'ModelAccountFlexTpmRateLimitExceeded',
    'APIAccountRpmRateLimitExceeded', 'AccountRateLimitExceeded', 'InflightBatchsizeExceeded',
    'RequestBurstTooFast', 'ServerOverloaded', 'InternalServiceError'})
NO_RETRY_CODES = {
    'AuthenticationError':'AUTHENTICATION', 'AccessDenied':'PERMISSION',
    'OperationDenied.PermissionDenied':'PERMISSION', 'OperationDenied.ServiceNotOpen':'PERMISSION',
    'InvalidAccountStatus':'ACCOUNT', 'OperationDenied.ServiceOverdue':'BALANCE', 'AccountOverdueError':'BALANCE',
    'SetLimitExceeded':'QUOTA', 'QuotaExceeded':'QUOTA', 'QuotaExceeded.AgentPlanQuotaExceeded':'QUOTA',
    'MissingParameter':'PARAMETER', 'InvalidParameter':'PARAMETER',
    'InvalidParameter.UnsupportedParameter':'PARAMETER', 'InvalidEndpointOrModel.NotFound':'MODEL_CONFIGURATION',
    'InvalidEndpointOrModel.ModelIDAccessDisabled':'MODEL_CONFIGURATION', 'ModelNotOpen':'MODEL_CONFIGURATION',
    'InputTextSensitiveContentDetected.PolicyViolation':'CONTENT_FILTER',
    'OutputTextSensitiveContentDetected':'CONTENT_FILTER',
    'InputTextRiskDetection':'CONTENT_FILTER', 'OutputTextRiskDetection':'CONTENT_FILTER',
    'OutofContextError':'CONTEXT_LIMIT',
}
RETRY_HTTP = frozenset({408,429,500,502,503,504})


def classify_error(status, code):
    """Internal category/retry hint, never a new public task error enum."""
    if code in NO_RETRY_CODES: return NO_RETRY_CODES[code],False
    if code in RETRY_CODES:
        return ('TEMPORARY_SERVICE' if code=='InternalServiceError' else 'RATE_LIMIT'), status in RETRY_HTTP
    if code is not None: return 'UNKNOWN_PROVIDER_ERROR',False
    if status==401: return 'AUTHENTICATION',False
    if status==403: return 'PERMISSION',False
    if status==402: return 'BALANCE',False
    if status==413: return 'CONTEXT_LIMIT',False
    return ('TEMPORARY_HTTP' if status in RETRY_HTTP else 'HTTP_ERROR'),status in RETRY_HTTP


def _count(value):
    return value if type(value) is int and 0 <= value <= MAX_SAFE_INTEGER else None


@dataclass(frozen=True)
class TransportResult:
    succeeded: bool
    category: str | None
    retryable: bool
    http_status: int | None
    provider_error_code: str | None
    duration_ms: int
    raw_response_json: str | None = field(repr=False)
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_info_json: str | None = field(default=None,repr=False)
    provider_request_id: str | None = None
    finish_reason: str | None = None

    @property
    def raw_response(self):
        return None if self.raw_response_json is None else strict_json_object(self.raw_response_json)

    @property
    def cache_info(self):
        return None if self.cache_info_json is None else strict_json_object(self.cache_info_json)


class ModelGateway:
    """Closes a real HTTP connection on cancellation; cannot stop remote compute.

    A supplied transport is private diagnostic injection, not an environment
    endpoint override. The application uses the default, retries=0 transport.
    Each send owns a client, so cancelling one task cannot close another run.
    """
    def __init__(self, *, transport_factory=None):
        self._transport_factory = transport_factory

    async def send(self, profile, context):
        if type(profile) is not ModelProfile: raise ValueError('A frozen model profile is required')
        body = profile.request(context)
        started = monotonic();status=None;raw=None;code=None
        input_tokens=output_tokens=cache=trace=finish=None
        def result(succeeded,category,retryable):
            return TransportResult(succeeded,category,retryable,status,code,
                min(MAX_SAFE_INTEGER,max(0,round((monotonic()-started)*1000))),raw,
                input_tokens,output_tokens,cache,trace,finish)
        transport = httpx.AsyncHTTPTransport(retries=0,trust_env=False) if self._transport_factory is None else self._transport_factory()
        try:
            async with httpx.AsyncClient(transport=transport,trust_env=False,follow_redirects=False,
                timeout=httpx.Timeout(connect=10,read=180,write=10,pool=10)) as client:
                async with client.stream('POST',ENDPOINT,headers={'Authorization':'Bearer '+profile.api_key,
                    'Content-Type':'application/json'},content=json.dumps(body,ensure_ascii=False,separators=(',',':')).encode('utf-8')) as response:
                    status=response.status_code;parts=[];size=0
                    async for part in response.aiter_bytes():
                        size+=len(part)
                        if size > MAX_AUDIT_BYTES: return result(False,'RESPONSE_CAPACITY',False)
                        parts.append(part)
                    encoded=b''.join(parts)
                    try: original=strict_json_object(encoded.decode('utf-8'))
                    except (ValueError,UnicodeError,RecursionError):
                        # Non-object/non-JSON wire data is not repaired into a
                        # valid provider envelope. Store complete safe text only.
                        try: raw=audit_json({'http_status':status,'unparsed_body':encoded.decode('utf-8')},credentials=(profile.api_key,))
                        except (ValueError,UnicodeError,RecursionError): raw=None
                        if 200 <= status < 300: return result(False,'RESPONSE_PROTOCOL',True)
                        category,retryable=classify_error(status,None)
                        return result(False,category,retryable)
                    try: raw=audit_json(original,credentials=(profile.api_key,))
                    except AuditCapacityExceeded: return result(False,'RESPONSE_CAPACITY',False)
                    except (ValueError,UnicodeError,RecursionError): return result(False,'RESPONSE_PROTOCOL',False)
                    sanitized=strict_json_object(raw)
                    usage=original.get('usage')
                    if type(usage) is dict:
                        input_tokens=_count(usage.get('prompt_tokens'));output_tokens=_count(usage.get('completion_tokens'))
                        if type(usage.get('prompt_tokens_details')) is dict:
                            # Only actual supplied fields; do not estimate a
                            # cache hit rate, total usage, currency or charge.
                            details=sanitized.get('usage',{}).get('prompt_tokens_details')
                            if type(details) is dict: cache=audit_json(details)
                    candidate=sanitized.get('id')
                    if type(candidate) is str and candidate and len(candidate)<=1024 and candidate==original.get('id'):
                        trace=candidate
                    choices=original.get('choices')
                    if type(choices) is list and len(choices)==1 and type(choices[0]) is dict:
                        candidate=choices[0].get('finish_reason')
                        if type(candidate) is str:
                            finish=json.loads(audit_json({'value':candidate},credentials=(profile.api_key,)))['value']
                        message=choices[0].get('message')
                        safe_choices=sanitized.get('choices')
                        if type(message) is dict and type(safe_choices) is list and len(safe_choices)==1:
                            if message.get('content') != safe_choices[0].get('message',{}).get('content'):
                                # Credential redaction is for the private audit,
                                # not permission to adopt a rewritten answer.
                                return result(False,'CREDENTIAL_ECHO',False)
                    error=original.get('error')
                    if type(error) is dict:
                        candidate=error.get('code')
                        if type(candidate) is str and candidate and len(candidate)<=256:
                            safe_code=sanitized.get('error',{}).get('code')
                            if safe_code==candidate: code=candidate
                        if 'code' in error and code is None: return result(False,'UNKNOWN_PROVIDER_ERROR',False)
                        category,retryable=classify_error(status,code)
                        return result(False,category,retryable)
                    if error is not None: return result(False,'UNKNOWN_PROVIDER_ERROR',False)
                    if not 200 <= status < 300:
                        category,retryable=classify_error(status,None)
                        return result(False,category,retryable)
                    if type(choices) is list and len(choices)==1 and type(choices[0]) is dict:
                        message=choices[0].get('message')
                        if finish=='content_filter' or type(message) is dict and message.get('refusal'):
                            return result(True,'CONTENT_FILTER',False)
                        if finish=='length': return result(True,'OUTPUT_TRUNCATED',True)
                    # Only transport succeeded. Audit parse/Schema/business
                    # gates still reject wrong model/finish/role/tool/content.
                    return result(True,None,False)
        except asyncio.CancelledError:
            raise
        except httpx.TimeoutException:
            return result(False,'TIMEOUT',True)
        except (httpx.NetworkError,httpx.RemoteProtocolError):
            return result(False,'NETWORK',True)
        except httpx.HTTPError:
            return result(False,'HTTP_CLIENT',False)
