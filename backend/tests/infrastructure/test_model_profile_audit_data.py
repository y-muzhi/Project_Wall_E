"""Frozen profile/scrubbing unit checks; no Provider request or AI adoption."""
from copy import deepcopy
import base64
import json
import unittest
from urllib.parse import quote

from backend.app.guide.context_builder import BuiltContext
from backend.app.infrastructure.model_profile import ModelProfile, MODEL_ID, MODEL_VERSION, BASE_URL, ENDPOINT
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.infrastructure.audit_data import sanitize_audit, audit_json, AuditCapacityExceeded, MAX_AUDIT_BYTES

KEY = 'diagnostic-credential-only+/=='


class ModelProfileTests(unittest.TestCase):
    def test_fixed_request_and_snapshot_have_exact_approved_fields_no_key_or_arbitrary_parameters(self):
        profile = ModelProfile.from_environment({'WALLE_MODEL_API_KEY':KEY,'WALLE_MODEL_BASE_URL':BASE_URL+'/',
            'WALLE_MODEL_ID':MODEL_ID,'WALLE_MODEL_VERSION':MODEL_VERSION,'temperature':'0.8','top_p':'0.9'})
        context = BuiltContext('diagnostic system protocol','{"diagnostic_wire_fixture":true}','{}',0,(),())
        body = profile.request(context)
        self.assertEqual(body, {'model':MODEL_ID,'messages':[{'role':'system','content':'diagnostic system protocol'},
            {'role':'user','content':'{"diagnostic_wire_fixture":true}'}],'temperature':0,'max_tokens':8192,'stream':False,'thinking':{'type':'disabled'}})
        self.assertEqual(profile.snapshot['endpoint'],ENDPOINT)
        self.assertEqual(profile.snapshot['timeouts'],{'connect':10,'read':180,'write':10,'pool':10})
        self.assertEqual(profile.snapshot['transport_retries'],0)
        self.assertNotIn(KEY,repr(profile));self.assertNotIn(KEY,json.dumps(profile.snapshot));self.assertNotIn(KEY,json.dumps(body))
        detached = profile.snapshot;detached['thinking']['type']='enabled';self.assertEqual(profile.snapshot['thinking'],{'type':'disabled'})

    def test_missing_invalid_credentials_and_model_override_refuse_with_safe_config_errors(self):
        for key in (None,'',' abc','abc\n','abc\tdef','abc\0def','abc\x7fdef','密钥',True,'a'*8193):
            with self.subTest(key_type=type(key).__name__),self.assertRaises(ConfigInvalid):ModelProfile.from_environment({'WALLE_MODEL_API_KEY':key})
        for changes in ({'WALLE_MODEL_ID':'another-model'},{'WALLE_MODEL_VERSION':'latest'},
            {'WALLE_MODEL_BASE_URL':'http://ark.cn-beijing.volces.com/api/v3'},
            {'WALLE_MODEL_BASE_URL':'https://credential:secret@ark.cn-beijing.volces.com/api/v3'},
            {'WALLE_MODEL_BASE_URL':BASE_URL+'?api_key=secret'},{'WALLE_MODEL_BASE_URL':BASE_URL+'#fragment'},
            {'WALLE_MODEL_BASE_URL':'https://example.invalid/api/v3'},{'WALLE_MODEL_BASE_URL':'https://['}):
            with self.assertRaises(ConfigInvalid) as error: ModelProfile.from_environment({'WALLE_MODEL_API_KEY':KEY,**changes})
            self.assertNotIn(KEY,str(error.exception));self.assertNotIn('credential:secret',str(error.exception))

    def test_model_input_must_be_one_json_object_and_protocol_nonempty_no_fence_repair(self):
        profile = ModelProfile(KEY)
        for system,input_json in (('', '{}'),('system','[]'),('system','{} {}'),('system','```json\n{}\n```'),('system','{"a":1,"a":2}')):
            with self.assertRaises(ValueError):profile.request(BuiltContext(system,input_json,'{}',0,(),()))


class AuditDataTests(unittest.TestCase):
    def test_recursive_auth_reasoning_and_encrypted_fields_removed_without_dropping_visible_content_or_usage(self):
        value = {'Authorization':'Bearer '+KEY,'headers':{'x-api-key':KEY,'safe':'kept'},'choices':[{'message':{'role':'assistant',
            'content':'{"visible":"actual invalid JSON retained for diagnosis"','reasoning':'private','reasoning_content':'private','encrypted_content':'private'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':0,'completion_tokens':12,'nested':[{'API_KEY':KEY,'object':'usage'}]},'id':'provider-id'}
        before = deepcopy(value);sanitized = sanitize_audit(value,credentials=(KEY,))
        self.assertEqual(value,before);self.assertNotIn(KEY,str(sanitized))
        self.assertEqual(sanitized['choices'][0]['message'],{'role':'assistant','content':value['choices'][0]['message']['content']})
        self.assertEqual(sanitized['usage']['prompt_tokens'],0);self.assertEqual(sanitized['id'],'provider-id')
        self.assertEqual(sanitized['headers'],{'safe':'kept'})
        self.assertEqual(sanitized['usage']['nested'],[{'object':'usage'}])

    def test_known_credentials_redacted_in_text_url_base64_and_object_keys_no_shared_mutation(self):
        encoded = base64.b64encode(KEY.encode()).decode();url = quote(KEY,safe='')
        value = {'text':f'Bearer {KEY} {encoded} {url}',KEY:'private keyed field','visible':'keep'}
        output = audit_json(value,credentials=(KEY,))
        for secret in (KEY,encoded,url):self.assertNotIn(secret,output)
        self.assertEqual(json.loads(output)['text'].count('[REDACTED_CREDENTIAL]'),3)
        self.assertEqual(json.loads(output)['visible'],'keep')

    def test_capacity_exact_utf8_after_authorized_scrubbing_no_visible_truncation(self):
        overhead = len('{"content":""}'.encode())
        accepted = {'content':'x'*(MAX_AUDIT_BYTES-overhead)}
        self.assertEqual(len(audit_json(accepted).encode()),MAX_AUDIT_BYTES)
        with self.assertRaises(AuditCapacityExceeded):audit_json({'content':accepted['content']+'x'})
        with self.assertRaises(AuditCapacityExceeded):audit_json({'content':'😀'*(MAX_AUDIT_BYTES//4)})
        self.assertEqual(json.loads(audit_json({'reasoning_content':'x'*(MAX_AUDIT_BYTES+1),'content':'visible'})),{'content':'visible'})

    def test_nonfinite_unknown_types_invalid_unicode_and_nonobject_snapshots_refuse(self):
        for value in ({'x':float('inf')},{'x':object()},{'x':'\ud800'},[],'{}'):
            with self.assertRaises((ValueError,TypeError,UnicodeError)):audit_json(value)
        with self.assertRaises(ValueError):sanitize_audit({'content':'visible'},credentials=('',))
