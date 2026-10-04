import unittest
from uuid import UUID

from backend.app.shared.http_errors import error_response, new_request_id

REQUEST_ID = '00000000-0000-4000-8000-000000000001'


class ErrorContractTests(unittest.TestCase):
    def test_registered_http_status_and_safe_envelopes(self):
        groups = {
            404: ['NOT_FOUND', 'MANUAL_DRAFT_NOT_FOUND'],
            409: ['STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'CONTENT_VERSION_CONFLICT', 'TARGET_STALE', 'COMMENT_ORPHANED', 'CARD_EXPIRED', 'IDEMPOTENCY_CONFLICT', 'REQUEST_IN_PROGRESS'],
            422: ['TEMPLATE_INVALID', 'DOCUMENT_INVALID', 'ANCHOR_INVALID', 'SCOPE_INVALID', 'SOURCE_INVALID', 'PATCH_INVALID', 'BATCH_PENDING'],
            503: ['CONFIG_INVALID', 'STORAGE_UNAVAILABLE', 'CAPACITY_EXHAUSTED'],
            500: ['INTERNAL_ERROR'],
        }
        for status, codes in groups.items():
            for code in codes:
                with self.subTest(code=code):
                    response = error_response(code, None, allowed_errors=[code], request_id=REQUEST_ID)
                    self.assertEqual(response.status, status)
                    self.assertEqual(set(response.body), {'success', 'data', 'error', 'meta'})
                    self.assertIs(response.body['success'], False)
                    self.assertIsNone(response.body['data'])
                    self.assertEqual(response.body['error']['code'], code)
                    self.assertTrue(response.body['error']['message'])
                    self.assertIsNone(response.body['error']['details'])
                    self.assertEqual(response.body['meta'], {'request_id': REQUEST_ID})

    def test_validation_code_and_nested_field_error(self):
        details = {'field_errors': [{'field': 'responses[0].card_key', 'reason': 'REQUIRED', 'message': '必须提供此参数'}]}
        response = error_response('INVALID_INPUT', details, allowed_errors=['INVALID_INPUT'], request_id=REQUEST_ID)
        self.assertEqual(response.status, 422)
        self.assertEqual(response.body['error'], {'code': 'VALIDATION_FAILED', 'message': '请求参数不合法', 'details': details})
        details['field_errors'][0]['reason'] = 'CHANGED_AFTER_PROJECTION'
        self.assertEqual(response.body['error']['details']['field_errors'][0]['reason'], 'REQUIRED')
        unknown = {'field_errors': [{'field': 'body.未登记字段', 'reason': 'UNKNOWN_FIELD', 'message': '此字段未登记'}]}
        self.assertEqual(error_response('INVALID_INPUT', unknown, allowed_errors=['INVALID_INPUT'], request_id=REQUEST_ID).body['error']['details'], unknown)

    def test_already_answered_reference(self):
        response = error_response('CARD_ALREADY_ANSWERED', {'response_message_id': 601}, allowed_errors=['CARD_ALREADY_ANSWERED'], request_id=REQUEST_ID)
        self.assertEqual(response.status, 409)
        self.assertEqual(response.body['error'], {'code': 'CARD_ALREADY_ANSWERED', 'message': '该组卡片已提交回答', 'details': {'response_message_id': 601}})
        for value in (True, 0, 9_007_199_254_740_992, '601', None):
            response = error_response('CARD_ALREADY_ANSWERED', {'response_message_id': value}, allowed_errors=['CARD_ALREADY_ANSWERED'], request_id=REQUEST_ID)
            self.assertEqual(response.status, 500)

    def test_approved_suggestion_error_details_are_exact_detached_safe_and_bounded(self):
        details={'suggestion_errors':[{'suggestion_id':11,'code':'TARGET_STALE','message':'修改目标或原内容已变化'}]}
        value=error_response('TARGET_STALE',details,allowed_errors=['TARGET_STALE'],request_id=REQUEST_ID)
        self.assertEqual(value.status,409);self.assertEqual(value.body['error']['details'],details)
        details['suggestion_errors'][0]['message']='secret-marker';self.assertNotIn('secret-marker',str(value.body))
        for malformed in (details,{'suggestion_errors':[]},{'suggestion_errors':[{'suggestion_id':True,'code':'TARGET_STALE','message':'修改目标或原内容已变化'}]}, {'suggestion_errors':[{'suggestion_id':1,'code':'NEW','message':'secret-marker'}]}):
            value=error_response('TARGET_STALE',malformed,allowed_errors=['TARGET_STALE'],request_id=REQUEST_ID)
            self.assertEqual(value.status,500);self.assertNotIn('secret-marker',str(value.body))

    def test_unknown_unreachable_and_malformed_results_are_safe_500(self):
        for code, details, allowed in (
            ('UNREGISTERED', {'raw': 'secret-marker'}, ['UNREGISTERED']),
            ([], None, []),
            ('CONFIG_INVALID', None, ['NOT_FOUND']),
            ('NOT_FOUND', {'stack': 'secret-marker'}, ['NOT_FOUND']),
            ('INVALID_INPUT', None, ['INVALID_INPUT']),
            ('INVALID_INPUT', {'field_errors': []}, ['INVALID_INPUT']),
            ('INVALID_INPUT', {'field_errors': [{'field': 'title', 'reason': 'NEW_REASON', 'message': 'secret-marker'}]}, ['INVALID_INPUT']),
            ('INVALID_INPUT', {'field_errors': [{'field': 'title', 'reason': 'REQUIRED', 'message': '必须提供', 'extra': 'secret-marker'}]}, ['INVALID_INPUT']),
            ('CARD_ALREADY_ANSWERED', {'response_message_id': 601, 'raw': 'secret-marker'}, ['CARD_ALREADY_ANSWERED']),
        ):
            response = error_response(code, details, allowed_errors=allowed, request_id=REQUEST_ID)
            self.assertEqual(response.status, 500)
            self.assertEqual(response.body['error'], {'code': 'INTERNAL_ERROR', 'message': '系统处理失败，请稍后重试', 'details': None})
            self.assertNotIn('secret-marker', str(response.body))
            self.assertNotIn('pagination', response.body['meta'])

    def test_request_ids_are_new_canonical_v4_contexts(self):
        first, second = new_request_id(), new_request_id()
        self.assertNotEqual(first, second)
        for identity in (first, second):
            self.assertEqual(UUID(identity).version, 4)
            self.assertEqual(str(UUID(identity)), identity)
            self.assertEqual(error_response('NOT_FOUND', None, allowed_errors=['NOT_FOUND'], request_id=identity).body['meta']['request_id'], identity)
        for identity in ('bad', '00000000-0000-1000-8000-000000000001', first.replace('-', ''), 'ABCDEFAB-CDEF-4ABC-8ABC-ABCDEFABCDEF', None):
            with self.assertRaises(ValueError):
                error_response('NOT_FOUND', None, allowed_errors=['NOT_FOUND'], request_id=identity)


if __name__ == '__main__':
    unittest.main()
