"""Conformance with the actual Gateway request bytes; MockTransport, never a provider."""

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import httpx
from formation_evaluation import digest, transport_json

from backend.app.infrastructure.model_gateway import ModelGateway
from backend.app.infrastructure.model_profile import (
    DEFAULT_PROFILE,
    LONG_OUTPUT_PROFILE,
    ModelProfile,
)
from backend.app.infrastructure.resources import ResourceCatalog


class ActualTransportTests(unittest.TestCase):
    def test_exact_gateway_http_content_matches_frozen_request_hash(self):
        profile = ModelProfile('explicit-offline-placeholder', DEFAULT_PROFILE)
        context = SimpleNamespace(
            system='严格保留中文与原顺序。\n本测试没有真实调用。',
            input_json='{"schema_version":1,"最后字段":"保留中文","首字段":"特殊\\n换行"}',
        )
        seen = []

        def response(request):
            seen.append(request.content)
            return httpx.Response(
                200,
                json={
                    'id': 'offline-mock-only',
                    'model': profile.model_name,
                    'choices': [
                        {
                            'index': 0,
                            'finish_reason': 'stop',
                            'message': {'role': 'assistant', 'content': 'offline mock only'},
                        }
                    ],
                    'usage': {'prompt_tokens': 20, 'completion_tokens': 4, 'total_tokens': 24},
                },
            )

        with patch(
            'backend.app.infrastructure.model_gateway.httpx.AsyncHTTPTransport',
            side_effect=AssertionError('No real transport may be constructed'),
        ):
            returned = asyncio.run(
                ModelGateway(transport_factory=lambda: httpx.MockTransport(response)).send(
                    profile, context
                )
            )
        self.assertTrue(returned.succeeded)
        self.assertEqual(len(seen), 1)
        exact = transport_json(profile.request(context)).encode('utf-8')
        self.assertEqual(seen[0], exact)
        self.assertEqual(digest(seen[0]), digest(transport_json(profile.request(context))))
        self.assertIn('严格保留中文'.encode(), seen[0])

    def test_profile_hash_is_the_release_identity_not_an_alternate_key_sorting(self):
        for identity in (DEFAULT_PROFILE, LONG_OUTPUT_PROFILE):
            with self.subTest(profile=identity):
                profile = ModelProfile('explicit-offline-placeholder', identity)
                catalog = ResourceCatalog().for_formation_profile(profile.profile_id)
                self.assertEqual(
                    digest(transport_json(profile.snapshot)),
                    catalog.collaboration.release['model_profile_sha256'],
                )
                self.assertNotIn('api_key', transport_json(profile.snapshot))
                self.assertNotIn(profile.api_key, transport_json(profile.snapshot))


if __name__ == '__main__':
    unittest.main()
