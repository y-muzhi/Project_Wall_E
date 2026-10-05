"""Actual loopback TCP server/HTTP transport, never paid provider/effect proof.

The private forwarding transport preserves the fixed external request URL and
headers as observed, then routes it to the controlled local diagnostic server.
"""
import asyncio
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import sys
from threading import Event, Thread
import unittest
from datetime import timedelta

import httpx

from backend.app.guide.context_builder import BuiltContext
from backend.app.infrastructure.audit_data import MAX_AUDIT_BYTES
from backend.app.infrastructure.model_gateway import ModelGateway, RETRY_CODES, NO_RETRY_CODES
from backend.app.infrastructure.model_profile import ModelProfile, MODEL_ID, ENDPOINT

KEY='loopback-diagnostic-credential-only+/=='
CONTEXT=BuiltContext('diagnostic protocol only','{"wire_diagnostic":true}','{}',0,(),())


def envelope(**changes):
    return {'model':MODEL_ID,'id':'actual-controlled-http-id','choices':[{'message':{
        'role':'assistant','content':'{"diagnostic_output":true}','reasoning_content':'excluded private thought'},
        'finish_reason':'stop'}],'usage':{'prompt_tokens':123,'completion_tokens':10,
        'prompt_tokens_details':{'cached_tokens':0}},**changes}


class ForwardTransport(httpx.AsyncBaseTransport):
    def __init__(self, port, observed, *, short_read=False):
        self.port=port;self.observed=observed;self.short_read=short_read;self.closed=False
        self.inner=httpx.AsyncHTTPTransport(retries=0,trust_env=False)

    async def handle_async_request(self, request):
        body=await request.aread()
        self.observed.append({'url':str(request.url),'method':request.method,'body':body,
            'headers':dict(request.headers),'extensions':deepcopy(request.extensions)})
        extensions=deepcopy(request.extensions)
        if self.short_read: extensions['timeout']['read']=0.05  # diagnostic only, original 180 is asserted
        routed=httpx.Request(request.method,f'http://127.0.0.1:{self.port}/controlled-chat',
            headers=request.headers,content=body,extensions=extensions)
        return await self.inner.handle_async_request(routed)

    async def aclose(self):
        await self.inner.aclose();self.closed=True


class ControlledServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self):
        super().__init__(('127.0.0.1',0),ControlledHandler)
        self.responses=[];self.receipts=[];self.entered=Event();self.peer_closed=Event();self.errors=[];self.inspect_request=None
    def handle_error(self, request, client_address):
        self.errors.append(type(sys.exception()).__name__)


class ControlledHandler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self, *args): pass
    def do_POST(self):
        self.server.receipts.append({'path':self.path,'body':self.rfile.read(int(self.headers['Content-Length'])),
            'authorization':self.headers.get('Authorization'),'content_type':self.headers.get('Content-Type')})
        if self.server.inspect_request is not None: self.server.inspect_request()
        status,body,headers,behavior=self.server.responses.pop(0)
        if behavior=='disconnect':
            self.close_connection=True
            self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
        self.send_response(status)
        for key,value in headers.items(): self.send_header(key,value)
        self.send_header('Content-Length',str(len(body)));self.end_headers()
        self.server.entered.set()
        if behavior=='hold':
            # The client is waiting for body bytes; after logical task cancel
            # its real TCP connection must close, independently of this server.
            self.connection.settimeout(2)
            try:
                if self.connection.recv(1)==b'': self.server.peer_closed.set()
            except (socket.timeout,OSError): pass
            self.close_connection=True;return
        try:self.wfile.write(body);self.wfile.flush()
        except (BrokenPipeError,ConnectionResetError):pass


class ModelGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server=ControlledServer();self.thread=Thread(target=self.server.serve_forever,kwargs={'poll_interval':0.01},daemon=True)
        self.thread.start();self.observed=[];self.transports=[];self.profile=ModelProfile(KEY)

    async def asyncTearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(2)
        self.assertFalse(self.thread.is_alive())
        self.assertEqual(self.server.errors,[])
        self.assertTrue(all(transport.closed for transport in self.transports))

    def gateway(self, *, short_read=False, port=None):
        def factory():
            transport=ForwardTransport(self.server.server_port if port is None else port,self.observed,short_read=short_read)
            self.transports.append(transport);return transport
        return ModelGateway(transport_factory=factory)

    def queue(self, status=200, value=None, *, raw=None, headers=None, behavior=None):
        body=json.dumps(envelope() if value is None else value,ensure_ascii=False,separators=(',',':')).encode() if raw is None else raw
        self.server.responses.append((status,body,headers or {},behavior))

    async def test_actual_wire_has_only_fixed_parameters_two_roles_and_exact_timeouts_one_attempt(self):
        self.queue();result=await self.gateway().send(self.profile,CONTEXT)
        self.assertTrue(result.succeeded);self.assertFalse(result.retryable);self.assertEqual(result.http_status,200)
        self.assertEqual(len(self.observed),1);self.assertEqual(len(self.server.receipts),1)
        wire=self.observed[0];receipt=self.server.receipts[0]
        self.assertEqual(wire['url'],ENDPOINT);self.assertEqual(wire['method'],'POST')
        self.assertEqual(json.loads(receipt['body']),self.profile.request(CONTEXT))
        self.assertEqual(receipt['authorization'],'Bearer '+KEY);self.assertEqual(receipt['content_type'],'application/json')
        self.assertEqual(wire['extensions']['timeout'],{'connect':10,'read':180,'write':10,'pool':10})
        self.assertEqual((result.input_tokens,result.output_tokens,result.cache_info,result.provider_request_id,result.finish_reason),
            (123,10,{'cached_tokens':0},'actual-controlled-http-id','stop'))
        self.assertIsInstance(result.duration_ms,int);self.assertGreaterEqual(result.duration_ms,0)
        self.assertNotIn('reasoning_content',result.raw_response['choices'][0]['message'])
        self.assertNotIn(KEY,repr(result));self.assertNotIn(KEY,result.raw_response_json)
        detached=result.raw_response;detached['usage']['prompt_tokens']=999;self.assertEqual(result.raw_response['usage']['prompt_tokens'],123)

    async def test_unknown_measurements_are_null_without_estimating_tokens_total_or_cost(self):
        for usage in (None,{},'malformed',{'prompt_tokens':True,'completion_tokens':-1},
            {'prompt_tokens':'123','completion_tokens':1.5},{'prompt_tokens':None,'completion_tokens':False}):
            self.queue(value=envelope(usage=usage,id=None))
            result=await self.gateway().send(self.profile,CONTEXT)
            self.assertTrue(result.succeeded);self.assertEqual((result.input_tokens,result.output_tokens,result.cache_info,result.provider_request_id),(None,None,None,None))
            self.assertFalse(hasattr(result,'cost'))
        self.queue(value=envelope(usage={'prompt_tokens':0,'completion_tokens':None,'total_tokens':987654}))
        result=await self.gateway().send(self.profile,CONTEXT)
        self.assertEqual((result.input_tokens,result.output_tokens),(0,None))
        self.assertEqual(len(self.server.receipts),7)
        self.queue(value=envelope(usage={'prompt_tokens':9_007_199_254_740_992}))
        result=await self.gateway().send(self.profile,CONTEXT)
        self.assertFalse(result.succeeded);self.assertEqual(result.category,'RESPONSE_PROTOCOL')
        self.assertIsNone(result.input_tokens);self.assertIsNone(result.raw_response)

    async def test_exact_official_error_codes_override_status_no_string_or_prefix_guessing(self):
        for code in sorted(NO_RETRY_CODES):
            self.queue(429,{'error':{'code':code,'message':'temporary rate limit retry '+KEY}})
            result=await self.gateway().send(self.profile,CONTEXT)
            self.assertFalse(result.succeeded);self.assertFalse(result.retryable);self.assertEqual(result.category,NO_RETRY_CODES[code])
            self.assertEqual(result.provider_error_code,code);self.assertNotIn(KEY,result.raw_response_json)
        for code in sorted(RETRY_CODES):
            self.queue(500 if code=='InternalServiceError' else 429,{'error':{'code':code,'message':'actual diagnostic error'}})
            result=await self.gateway().send(self.profile,CONTEXT)
            self.assertFalse(result.succeeded);self.assertTrue(result.retryable)
        for code in ('Unknown.ProviderCode','RateLimitExceeded','AccountOverdueError.extra','InsufficientBalance'):
            self.queue(429,{'error':{'code':code,'message':'account overdue or temporary, do not guess'}})
            result=await self.gateway().send(self.profile,CONTEXT)
            self.assertFalse(result.retryable);self.assertEqual(result.category,'UNKNOWN_PROVIDER_ERROR')
        self.assertEqual(len(self.observed),len(NO_RETRY_CODES)+len(RETRY_CODES)+4)
        self.assertEqual(len(self.server.receipts),len(self.observed))
        for error in ({'code':None},{'code':[]},{'code':KEY},'malformed error'):
            self.queue(429,{'error':error});result=await self.gateway().send(self.profile,CONTEXT)
            self.assertFalse(result.retryable);self.assertEqual(result.category,'UNKNOWN_PROVIDER_ERROR')

    async def test_http_status_fallback_is_bounded_and_redirect_is_not_followed(self):
        for status,retry in ((408,True),(429,True),(500,True),(502,True),(503,True),(504,True),
            (400,False),(401,False),(402,False),(403,False),(404,False),(413,False),(418,False),(501,False)):
            self.queue(status,{},headers={'Retry-After':'99999'})
            result=await self.gateway().send(self.profile,CONTEXT)
            self.assertFalse(result.succeeded);self.assertEqual(result.retryable,retry)
        self.queue(307,{},headers={'Location':'https://example.invalid/credential-theft'})
        result=await self.gateway().send(self.profile,CONTEXT)
        self.assertFalse(result.succeeded);self.assertFalse(result.retryable);self.assertEqual(len(self.observed),15)
        self.assertEqual(len(self.server.receipts),15)

    async def test_transport_success_does_not_claim_valid_output_model_schema_or_business(self):
        for value in (envelope(model='wrong-model'),envelope(choices=[]),
            envelope(choices=[{'message':{'role':'assistant','content':'not JSON'},'finish_reason':'length'}]),
            envelope(choices=[{'message':None,'finish_reason':'content_filter'}])):
            self.queue(value=value);result=await self.gateway().send(self.profile,CONTEXT)
            self.assertTrue(result.succeeded);self.assertEqual(result.raw_response,value if not value['choices'] or value['choices'][0].get('message') is None else {**value,'choices':[
                {**value['choices'][0],'message':{k:v for k,v in value['choices'][0]['message'].items() if k!='reasoning_content'}}]})
            self.assertFalse(hasattr(result,'trusted_output'))

    async def test_nonobject_duplicate_fenced_or_invalid_utf8_wire_not_repaired_into_envelope(self):
        for raw in (b'[]',b'{"a":1,"a":2}',b'{} {}',b'```json\n{}\n```',b'not JSON',b'\xff'):
            self.queue(raw=raw);result=await self.gateway().send(self.profile,CONTEXT)
            self.assertFalse(result.succeeded);self.assertEqual(result.category,'RESPONSE_PROTOCOL')
            self.assertNotEqual(result.raw_response,{})
        self.assertEqual(len(self.observed),6)

    async def test_capacity_closes_without_partial_raw_response_or_usage(self):
        self.queue(raw=b'{' + b' ' * MAX_AUDIT_BYTES + b'}')
        result=await self.gateway().send(self.profile,CONTEXT)
        self.assertFalse(result.succeeded);self.assertFalse(result.retryable)
        self.assertEqual(result.category,'RESPONSE_CAPACITY');self.assertIsNone(result.raw_response)
        self.assertIsNone(result.input_tokens);self.assertEqual(len(self.observed),1)

    async def test_actual_timeout_and_peer_disconnect_are_single_attempt_safe_results(self):
        self.queue(behavior='hold')
        result=await self.gateway(short_read=True).send(self.profile,CONTEXT)
        self.assertFalse(result.succeeded);self.assertEqual(result.category,'TIMEOUT');self.assertTrue(result.retryable)
        self.assertTrue(await asyncio.to_thread(self.server.peer_closed.wait,1))
        self.queue(behavior='disconnect')
        result=await self.gateway().send(self.profile,CONTEXT)
        self.assertEqual(result.category,'NETWORK');self.assertTrue(result.retryable)
        self.assertEqual(len(self.observed),2);self.assertEqual(len(self.server.receipts),2)

    async def test_actual_task_cancel_closes_its_connection_without_returning_success(self):
        self.queue(behavior='hold');gateway=self.gateway();task=asyncio.create_task(gateway.send(self.profile,CONTEXT))
        self.assertTrue(await asyncio.to_thread(self.server.entered.wait,1))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(await asyncio.to_thread(self.server.peer_closed.wait,1))
        self.assertTrue(self.transports[0].closed);self.assertEqual(len(self.server.receipts),1)

    async def test_cancelling_one_real_request_does_not_close_another_runs_transport(self):
        self.queue(behavior='hold');self.queue();gateway=self.gateway()
        first=asyncio.create_task(gateway.send(self.profile,CONTEXT))
        self.assertTrue(await asyncio.to_thread(self.server.entered.wait,1))
        second=asyncio.create_task(gateway.send(self.profile,CONTEXT));first.cancel()
        with self.assertRaises(asyncio.CancelledError):await first
        result=await second;self.assertTrue(result.succeeded)
        self.assertTrue(await asyncio.to_thread(self.server.peer_closed.wait,1))
        self.assertEqual(len(self.server.receipts),2);self.assertEqual(len(self.transports),2)
        self.assertTrue(all(transport.closed for transport in self.transports))

    async def test_content_filter_or_explicit_refusal_never_offer_safety_retry_but_length_is_regenerable(self):
        for finish,refusal,category,retry in (('content_filter',None,'CONTENT_FILTER',False),
            ('stop','actual provider refusal','CONTENT_FILTER',False),('length',None,'OUTPUT_TRUNCATED',True)):
            raw=envelope();raw['choices'][0]['finish_reason']=finish
            raw['choices'][0]['message']['refusal']=refusal
            self.queue(value=raw);result=await self.gateway().send(self.profile,CONTEXT)
            self.assertTrue(result.succeeded);self.assertEqual((result.category,result.retryable),(category,retry))
        self.assertEqual(len(self.observed),3)

    async def test_credential_echo_is_private_redacted_audit_and_never_a_rewritten_success(self):
        original=envelope(id=KEY)
        original['choices'][0]['message']['content']=json.dumps({'diagnostic_output':KEY})
        self.queue(value=original);result=await self.gateway().send(self.profile,CONTEXT)
        self.assertFalse(result.succeeded);self.assertFalse(result.retryable);self.assertEqual(result.category,'CREDENTIAL_ECHO')
        self.assertIsNone(result.provider_request_id);self.assertNotIn(KEY,result.raw_response_json);self.assertNotIn(KEY,repr(result))
        self.assertEqual(result.input_tokens,123)

    async def test_preflight_invalid_profile_or_input_never_opens_transport(self):
        gateway=self.gateway()
        for profile,context in ((object(),CONTEXT),(self.profile,BuiltContext('system','[]','{}',0,(),()))):
            with self.assertRaises(ValueError):await gateway.send(profile,context)
        self.assertEqual(self.transports,[]);self.assertEqual(self.server.receipts,[])

    def audit_fixture(self):
        from backend.tests.infrastructure.test_audit_repository import AuditRepositoryTests
        fixture=AuditRepositoryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.profile=self.profile
        return fixture

    def store_transport(self, fixture, identity, result, at='2026-10-04T08:00:02.000Z'):
        from backend.app.infrastructure.audit_repository import AuditRepository
        with fixture.database.transaction(write=True) as connection:
            return dict(AuditRepository(connection).record_transport(identity,result.raw_response,at,
                profile=self.profile,succeeded=result.succeeded,duration_ms=result.duration_ms,
                input_tokens=result.input_tokens,output_tokens=result.output_tokens,
                provider_request_id=result.provider_request_id,finish_reason=result.finish_reason,cache_info=result.cache_info))

    async def test_real_prepared_audit_before_tcp_request_no_database_write_lock_over_network(self):
        from backend.app.infrastructure.audit_repository import AuditRepository
        fixture=self.audit_fixture();identity=fixture.prepare()['id'];root=fixture.row('requirements',fixture.req)
        current=fixture.row('requirement_documents',fixture.created['current_document_id']);wire_rows=[]
        def inspect():
            # Real independent write BEGIN succeeds while the client is on the
            # network, and observes the committed preparation before response.
            with fixture.database.transaction(write=True) as connection:
                wire_rows.append(dict(AuditRepository(connection).get(identity)))
        self.server.inspect_request=inspect
        output={'schema_version':1,'response_type':'INITIALIZE_TEXT','message':'actual HTTP diagnostic, no trusted success',
            'confirmed_fact_patches':[],'unknown_output_field':True}
        raw=envelope();raw['choices'][0]['message']['content']=json.dumps(output)
        self.queue(value=raw);result=await self.gateway().send(self.profile,fixture.context)
        self.assertTrue(result.succeeded);self.assertEqual(len(wire_rows),1)
        self.assertEqual((wire_rows[0]['call_status'],wire_rows[0]['parse_status']),('RUNNING','NOT_STARTED'))
        self.assertEqual(json.loads(wire_rows[0]['request_snapshot_json'])['request'],json.loads(self.server.receipts[0]['body']))
        self.store_transport(fixture,identity,result);parsed=fixture.parse(identity)
        self.assertEqual(parsed,output)
        with self.assertRaises(ValueError):fixture.function.parse_output(json.dumps(parsed))
        with fixture.database.transaction(write=True) as connection:
            AuditRepository(connection).record_validation_failure(identity,'2026-10-04T08:00:03.000Z')
        audit=fixture.row('llm_uses',identity)
        self.assertEqual((audit['call_status'],audit['parse_status'],audit['validation_status'],audit['trusted_output_json']),
            ('SUCCEEDED','SUCCEEDED','FAILED',None))
        self.assertEqual(audit['input_tokens'],123);self.assertEqual(audit['provider_request_id'],'actual-controlled-http-id')
        self.assertEqual(fixture.row('requirements',fixture.req),root)
        self.assertEqual(fixture.row('requirement_documents',current['id']),current)

    async def test_real_transport_retry_facts_remain_distinct_and_fourth_attempt_cannot_be_prepared(self):
        from backend.app.shared.command_execution import Rejected
        fixture=self.audit_fixture();before_root=fixture.row('requirements',fixture.req);previous=[]
        for attempt in range(1,4):
            audit=fixture.prepare(at='2026-10-04T08:00:01.000Z' if attempt==1 else '2026-10-04T08:00:03.000Z',call_no=None if attempt==1 else 1)
            self.assertEqual((audit['call_no'],audit['attempt_no']),(1,attempt))
            self.queue(429,{'error':{'code':'RequestBurstTooFast','message':'actual controlled rate error'}})
            result=await self.gateway().send(self.profile,fixture.context)
            self.assertFalse(result.succeeded);self.assertTrue(result.retryable)
            self.store_transport(fixture,audit['id'],result,at='2026-10-04T08:00:03.000Z')
            for prior in previous:self.assertEqual(fixture.row('llm_uses',prior['id']),prior)
            previous.append(fixture.row('llm_uses',audit['id']))
        before=fixture.facts()
        with self.assertRaises(Rejected):fixture.prepare(at='2026-10-04T08:00:03.000Z',call_no=1)
        self.assertEqual(fixture.facts(),before);self.assertEqual(len(self.server.receipts),3)
        self.assertEqual(fixture.row('requirements',fixture.req),before_root)
        self.assertTrue(all(row['trusted_output_json'] is None and row['call_status']=='FAILED' for row in previous))

    async def test_actual_business_cancel_then_late_http_usage_never_reopens_or_adopts(self):
        from backend.app.guide.commands import cancel_guide_run
        from backend.app.shared.command_execution import Rejected
        from backend.tests.requirements import test_create_requirement as creation
        fixture=self.audit_fixture();identity=fixture.prepare()['id']
        self.queue();result=await self.gateway().send(self.profile,fixture.context)
        cancelled=cancel_guide_run(fixture.executor,{'guide_run_id':fixture.run,'idempotency_key':creation.OTHER},
            clock=lambda:creation.INSTANT+timedelta(seconds=2))
        self.assertEqual(cancelled['code'],'GUIDE_CANCELLED')
        root=fixture.row('requirements',fixture.req);run=fixture.row('guide_runs',fixture.run)
        stored=self.store_transport(fixture,identity,result,at='2026-10-04T08:00:03.000Z')
        self.assertEqual((stored['call_status'],stored['input_tokens'],stored['provider_request_id']),('CANCELLED',123,'actual-controlled-http-id'))
        self.assertEqual(stored['ended_at'],'2026-10-04T08:00:02.000Z')
        self.assertEqual(fixture.row('guide_runs',fixture.run),run);self.assertEqual(fixture.row('requirements',fixture.req),root)
        with self.assertRaises(Rejected):fixture.parse(identity)
        self.assertIsNone(fixture.row('llm_uses',identity)['trusted_output_json'])

    async def test_real_tcp_response_reaches_trusted_validation_and_atomic_business_submit(self):
        from backend.app.guide.trusted_output import produce_trusted_output
        from backend.app.guide.commands import persist_ai_result
        from backend.app.guide.queries import get_guide_run
        from backend.tests.requirements import test_create_requirement as creation
        fixture=self.audit_fixture();identity=fixture.prepare()['id']
        current=fixture.row('requirement_documents',fixture.created['current_document_id'])
        output={'schema_version':1,'response_type':'INITIALIZE_TEXT','message':'真实TCP传输的受控诊断正文','confirmed_fact_patches':[]}
        raw=envelope();raw['choices'][0]['message']['content']=json.dumps(output,ensure_ascii=False)
        self.queue(value=raw);result=await self.gateway().send(self.profile,fixture.context)
        self.assertTrue(result.succeeded);self.store_transport(fixture,identity,result)
        self.assertEqual(fixture.parse(identity),output)
        receipt=produce_trusted_output(fixture.database,identity,process_lock=fixture.lock,profile=self.profile,catalog=fixture.catalog,
            clock=lambda:creation.INSTANT+timedelta(seconds=4))
        self.assertIsNotNone(receipt)
        persisted=persist_ai_result(fixture.database,{'guide_run_id':fixture.run,'llm_use_id':identity,'trusted_output':receipt},
            process_lock=fixture.lock,profile=self.profile,catalog=fixture.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=5))
        self.assertEqual(persisted['code'],'AI_RESULT_PERSISTED',persisted)
        message=fixture.row('conversation_messages',persisted['data']['assistant_message_id'])
        self.assertEqual(message['content'],output['message']);self.assertEqual(message['role'],'ASSISTANT')
        self.assertEqual(get_guide_run(fixture.database,fixture.run,catalog=fixture.catalog)['data']['status'],'COMPLETED')
        audit=fixture.row('llm_uses',identity)
        self.assertEqual((audit['call_status'],audit['parse_status'],audit['validation_status']),('SUCCEEDED','SUCCEEDED','SUCCEEDED'))
        self.assertEqual((audit['input_tokens'],audit['output_tokens'],audit['cost']),(123,10,None))
        self.assertEqual(json.loads(audit['request_snapshot_json'])['request'],json.loads(self.server.receipts[0]['body']))
        self.assertEqual(fixture.row('requirement_documents',current['id']),current)
        self.assertEqual(len(self.server.receipts),1)
