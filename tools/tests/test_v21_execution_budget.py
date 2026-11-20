"""Paid-attempt limits and frozen requests, using only local fake delegates."""

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from formation_evaluation import row_for
from formation_evaluation_execution import TOTAL_LIMIT, Allowance
from formation_evaluation_spec import samples

from backend.app.infrastructure.model_profile import ModelProfile


class AllowanceTests(unittest.TestCase):
    def setUp(self):
        self.profile = ModelProfile('offline-only-placeholder', 'deepseek-v2')
        self.events = []
        self.owner = Allowance(self.profile, lambda *value: self.events.append(value), lambda: None)
        self.sample = samples()[0]
        self.facts = {'content_version': 1, 'revision_id': 101}
        texts = ('system', '{}', '', '', '', '', '', '')
        self.context = SimpleNamespace(
            system=texts[0],
            input_json=texts[1],
            texts=texts,
            basis={'canonical_sha256': 'a' * 64, 'output_schema_sha256': 'b' * 64},
            input={'project_position': {'formation': {'coverage': {}}}},
        )
        expected = row_for(self.sample, 'full', self.context, self.facts, self.profile)
        self.case = self.owner.case(self.sample, [expected], self.facts)
        self.case.catalog = object()

    def counted(self):
        delegate = SimpleNamespace(count=AsyncMock(return_value=object()))
        asyncio.run(self.case.counter(delegate).count(self.profile, self.context.texts))
        return delegate

    def response(self):
        return SimpleNamespace(succeeded=True, raw_response={}, input_tokens=100, output_tokens=20)

    def test_first_definitive_rejection_stops_subsequent_paid_io(self):
        for status in ('STRUCTURED_REJECTED', 'TRANSPORT_ERROR', 'PREFLIGHT_REJECTED'):
            with self.subTest(status=status):
                self.setUp()
                self.owner.observe_outcome('AI_FINISHED', {'status': status, 'protected': True})
                self.assertTrue(self.owner.stopped)
                delegate = SimpleNamespace(count=AsyncMock())
                with self.assertRaises(ValueError):
                    asyncio.run(self.case.counter(delegate).count(self.profile, self.context.texts))
                delegate.count.assert_not_awaited()
        self.setUp()
        self.owner.observe_outcome('AI_FINISHED', {'status': 'LIVE_RETURNED', 'protected': True})
        self.assertFalse(self.owner.stopped)
        self.owner.observe_outcome('AI_FINISHED', {'status': 'LIVE_RETURNED', 'protected': False})
        self.assertTrue(self.owner.stopped)

    def test_single_compatibility_observation_has_own_limits(self):
        owner = Allowance(
            self.profile,
            lambda *value: self.events.append(value),
            lambda: None,
            chat_limit=1,
            count_limit=2,
            token_limit=139264,
        )
        self.owner = owner
        self.case = owner.case(self.sample, self.case.expected, self.facts)
        self.case.catalog = object()
        self.counted()
        gateway = SimpleNamespace(send=AsyncMock(return_value=self.response()))
        with patch('backend.app.infrastructure.practical_usage.validate_collaboration_usage'):
            asyncio.run(self.case.gateway(gateway).send(self.profile, self.context))
        self.assertEqual((owner.chats, owner.reserved_tokens), (1, 139264))
        another = owner.case(self.sample, self.case.expected, self.facts)
        another.last_texts = self.context.texts
        another.count_calls = 1
        with self.assertRaises(ValueError):
            asyncio.run(another.gateway(gateway).send(self.profile, self.context))
        self.assertEqual(gateway.send.await_count, 1)
        with self.assertRaises(ValueError):
            Allowance(
                self.profile,
                lambda *value: None,
                lambda: None,
                chat_limit=2,
                count_limit=4,
                token_limit=278528,
            )

    def test_count_intent_is_claimed_before_delegate(self):
        def observed(profile, texts):
            self.assertEqual(self.owner.counts, 1)
            self.assertEqual(self.events[0][1], 'COUNT_INTENT')
            return object()

        delegate = SimpleNamespace(count=AsyncMock(side_effect=observed))
        asyncio.run(self.case.counter(delegate).count(self.profile, self.context.texts))
        self.assertEqual(self.owner.counts, 1)
        self.assertEqual(self.events[-1][1], 'COUNT_RETURNED')
        with self.assertRaises(ValueError):
            asyncio.run(self.case.counter(delegate).count(self.profile, self.context.texts))
        self.assertEqual(delegate.count.await_count, 1)

    def test_durable_claim_failure_prevents_io(self):
        self.owner.event = lambda *value: (_ for _ in ()).throw(OSError('offline injected'))
        delegate = SimpleNamespace(count=AsyncMock())
        with self.assertRaises(OSError):
            asyncio.run(self.case.counter(delegate).count(self.profile, self.context.texts))
        delegate.count.assert_not_awaited()
        self.assertEqual(self.owner.counts, 0)

    def test_failed_count_is_not_refunded_or_retried(self):
        delegate = SimpleNamespace(count=AsyncMock(side_effect=TimeoutError))
        with self.assertRaises(TimeoutError):
            asyncio.run(self.case.counter(delegate).count(self.profile, self.context.texts))
        self.assertTrue(self.owner.stopped)
        self.assertEqual(self.owner.counts, 1)
        with self.assertRaises(ValueError):
            asyncio.run(self.case.counter(delegate).count(self.profile, self.context.texts))
        self.assertEqual(delegate.count.await_count, 1)

    def test_candidate_tamper_and_unmeasured_chat_never_send(self):
        counter = SimpleNamespace(count=AsyncMock())
        with self.assertRaises(ValueError):
            asyncio.run(
                self.case.counter(counter).count(
                    self.profile, ('other-system', *self.context.texts[1:])
                )
            )
        counter.count.assert_not_awaited()
        gateway = SimpleNamespace(send=AsyncMock())
        with self.assertRaises(ValueError):
            asyncio.run(self.case.gateway(gateway).send(self.profile, self.context))
        gateway.send.assert_not_awaited()

    def test_global_count_and_token_limits_prevent_extra_io(self):
        self.owner.counts = 120
        delegate = SimpleNamespace(count=AsyncMock())
        with self.assertRaises(ValueError):
            asyncio.run(self.case.counter(delegate).count(self.profile, self.context.texts))
        delegate.count.assert_not_awaited()
        self.owner.counts = 0
        self.counted()
        self.owner.chats = 60
        gateway = SimpleNamespace(send=AsyncMock())
        with self.assertRaises(ValueError):
            asyncio.run(self.case.gateway(gateway).send(self.profile, self.context))
        gateway.send.assert_not_awaited()
        self.owner.chats = 0
        self.owner.reserved_tokens = TOTAL_LIMIT
        gateway = SimpleNamespace(send=AsyncMock())
        with self.assertRaises(ValueError):
            asyncio.run(self.case.gateway(gateway).send(self.profile, self.context))
        gateway.send.assert_not_awaited()

    def test_one_chat_claim_before_io_and_no_second_attempt(self):
        self.counted()

        async def observed(profile, context):
            self.assertEqual(self.owner.chats, 1)
            self.assertEqual(self.owner.reserved_tokens, 139264)
            self.assertEqual(self.events[-1][1], 'CHAT_INTENT')
            return self.response()

        gateway = SimpleNamespace(send=AsyncMock(side_effect=observed))
        with patch('backend.app.infrastructure.practical_usage.validate_collaboration_usage'):
            asyncio.run(self.case.gateway(gateway).send(self.profile, self.context))
            with self.assertRaises(ValueError):
                asyncio.run(self.case.gateway(gateway).send(self.profile, self.context))
        self.assertEqual(gateway.send.await_count, 1)
        self.assertFalse(self.owner.stopped)

    def test_transport_exception_claims_budget_and_stops(self):
        self.counted()
        gateway = SimpleNamespace(send=AsyncMock(side_effect=TimeoutError))
        with self.assertRaises(TimeoutError):
            asyncio.run(self.case.gateway(gateway).send(self.profile, self.context))
        self.assertEqual(self.owner.chats, 1)
        self.assertEqual(self.owner.reserved_tokens, 139264)
        self.assertTrue(self.owner.stopped)
        self.assertEqual(self.events[-1][1], 'CHAT_UNCERTAIN')

    def test_bad_actual_usage_returns_to_audit_and_stops_following_calls(self):
        self.counted()
        response = self.response()
        gateway = SimpleNamespace(send=AsyncMock(return_value=response))
        with patch(
            'backend.app.infrastructure.practical_usage.validate_collaboration_usage',
            side_effect=ValueError('UNKNOWN'),
        ):
            returned = asyncio.run(self.case.gateway(gateway).send(self.profile, self.context))
        self.assertIs(returned, response)
        self.assertTrue(self.owner.stopped)
        self.assertEqual(self.events[-1][1], 'CHAT_RETURNED_STOPPED')

    def test_source_change_prevents_network(self):
        self.owner.guard = lambda: (_ for _ in ()).throw(ValueError('changed'))
        counter = SimpleNamespace(count=AsyncMock())
        with self.assertRaises(ValueError):
            asyncio.run(self.case.counter(counter).count(self.profile, self.context.texts))
        self.assertTrue(self.owner.stopped)
        counter.count.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
