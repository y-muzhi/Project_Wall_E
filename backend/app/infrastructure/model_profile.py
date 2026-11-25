"""D-007/D-014 immutable model profiles and exact historical restoration.

Environment startup defaults to DeepSeek v2. The one-argument constructor
retains its original v1 identity for existing private integrations/old audits;
new production requests use from_environment. Credentials are never snapshots.
"""

import os
from dataclasses import dataclass, field
from types import MappingProxyType
from urllib.parse import urlsplit

from backend.app.shared.validation import strict_json_object

from .resources import ConfigInvalid

MODEL_ID = 'doubao-seed-2-1-pro-260915'
MODEL_VERSION = '260915'
DEEPSEEK_MODEL_ID = 'deepseek-v4-1-flash-260910'
DEEPSEEK_MODEL_VERSION = '260910'
LEGACY_PROFILE = 'doubao-v1'
DEFAULT_PROFILE = 'deepseek-v2'
LONG_OUTPUT_PROFILE = 'deepseek-long-v3'
OPENAI_PROFILE = 'openai-sol-v1'
OPENAI_DOCUMENT_PROFILE = 'openai-sol-document-v1'
OPENAI_PROFILES = (OPENAI_PROFILE, OPENAI_DOCUMENT_PROFILE)
OPENAI_DOCUMENT_OUTPUT_LIMIT = 100_000
OPENAI_MODEL_ID = 'gpt-6.2-sol'
PROFILES = MappingProxyType(
    {
        LEGACY_PROFILE: (MODEL_ID, MODEL_VERSION),
        DEFAULT_PROFILE: (DEEPSEEK_MODEL_ID, DEEPSEEK_MODEL_VERSION),
        LONG_OUTPUT_PROFILE: (DEEPSEEK_MODEL_ID, DEEPSEEK_MODEL_VERSION),
        OPENAI_PROFILE: (OPENAI_MODEL_ID, OPENAI_MODEL_ID),
        OPENAI_DOCUMENT_PROFILE: (OPENAI_MODEL_ID, OPENAI_MODEL_ID),
    }
)
BASE_URL = 'https://ark.cn-beijing.volces.com/api/v3'
ENDPOINT = BASE_URL + '/chat/completions'


@dataclass(frozen=True)
class ModelProfile:
    api_key: str = field(repr=False)
    profile_id: str = LEGACY_PROFILE

    def __post_init__(self):
        if type(self.profile_id) is not str or self.profile_id not in PROFILES:
            raise ConfigInvalid('Only an approved immutable profile is permitted')
        if (
            type(self.api_key) is not str
            or not self.api_key
            or len(self.api_key) > 8192
            or self.api_key != self.api_key.strip()
            or any(ord(character) < 32 or ord(character) == 127 for character in self.api_key)
        ):
            raise ConfigInvalid('Model credential is missing or invalid')
        try:
            self.api_key.encode('ascii')
        except UnicodeEncodeError:
            raise ConfigInvalid('Model credential is invalid') from None

    @classmethod
    def selected_profile(cls, environment=None):
        values = os.environ if environment is None else environment
        hint = values.get('WALLE_MODEL_PROFILE')
        default_model = (
            PROFILES[hint][0] if type(hint) is str and hint in PROFILES else DEEPSEEK_MODEL_ID
        )
        model = values.get('WALLE_MODEL_ID', default_model)
        selected = values.get(
            'WALLE_MODEL_PROFILE',
            next(
                (
                    name
                    for name, pair in PROFILES.items()
                    if type(model) is str and pair[0] == model
                ),
                None,
            ),
        )
        if (
            type(selected) is not str
            or selected not in PROFILES
            or model != PROFILES[selected][0]
            or values.get('WALLE_MODEL_VERSION', PROFILES[selected][1]) != PROFILES[selected][1]
        ):
            raise ConfigInvalid('Only an approved exact model/version pair is permitted')
        return selected

    @classmethod
    def from_environment(cls, environment=None):
        values = os.environ if environment is None else environment
        selected = cls.selected_profile(values)
        if selected in OPENAI_PROFILES:
            from .openai_protocol import BASE_URL as OPENAI_URL

            url = values.get('WALLE_MODEL_BASE_URL', OPENAI_URL)
            if type(url) is not str or url.rstrip('/') != OPENAI_URL:
                raise ConfigInvalid('Only the official OpenAI endpoint is permitted')
            return cls(values.get('OPENAI_API_KEY'), selected)
        url = values.get('WALLE_MODEL_BASE_URL', BASE_URL)
        if type(url) is not str:
            raise ConfigInvalid('Model endpoint is invalid')
        try:
            parsed = urlsplit(url)
        except ValueError:
            raise ConfigInvalid('Model endpoint is invalid') from None
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or url.rstrip('/') != BASE_URL
        ):
            raise ConfigInvalid('Only the approved credential-free Beijing endpoint is permitted')
        return cls(values.get('WALLE_MODEL_API_KEY'), selected)

    @property
    def provider(self):
        return 'openai' if self.profile_id in OPENAI_PROFILES else 'volcengine'

    @property
    def model_name(self):
        return PROFILES[self.profile_id][0]

    @property
    def model_version(self):
        return PROFILES[self.profile_id][1]

    @classmethod
    def from_snapshot(cls, snapshot, *, api_key='private-audit-profile-validation'):
        """Restore the complete exact historic profile, never the new default."""
        if type(snapshot) is not dict:
            raise ConfigInvalid('Persisted model profile must be an object')
        from backend.app.shared.json_canonical import canonical_input

        try:
            for name in PROFILES:
                profile = cls(api_key, name)
                if canonical_input(snapshot) == canonical_input(profile.snapshot):
                    return profile
        except (ValueError, TypeError, UnicodeError):
            pass
        raise ConfigInvalid('Persisted model parameters differ from their frozen version')

    @property
    def output_limit(self):
        if self.profile_id == OPENAI_DOCUMENT_PROFILE:
            return OPENAI_DOCUMENT_OUTPUT_LIMIT
        return 32768 if self.profile_id == LONG_OUTPUT_PROFILE else 8192

    @property
    def snapshot(self):
        if self.provider == 'openai':
            from .openai_protocol import snapshot

            return snapshot(self.output_limit)
        return {
            'provider': 'volcengine',
            'model_name': self.model_name,
            'model_version': self.model_version,
            'endpoint': ENDPOINT,
            'temperature': 0,
            'max_tokens': self.output_limit,
            'stream': False,
            'thinking': {'type': 'disabled'},
            'timeouts': {'connect': 10, 'read': 180, 'write': 10, 'pool': 10},
            'transport_retries': 0,
        }

    def request(self, context):
        if self.provider == 'openai':
            from .openai_protocol import request

            return request(context, self.output_limit)
        if type(context.system) is not str or not context.system:
            raise ValueError('System protocol is required')
        strict_json_object(context.input_json)
        body = {
            'model': self.model_name,
            'messages': [
                {'role': 'system', 'content': context.system},
                {'role': 'user', 'content': context.input_json},
            ],
            'temperature': 0,
            'max_tokens': self.output_limit,
            'stream': False,
            'thinking': {'type': 'disabled'},
        }
        output_format = getattr(context, 'response_format', None)
        if output_format is not None:
            body['response_format'] = output_format
        return body

    def testing_request(self, context, *, output_cap):
        if self.provider == 'openai':
            raise ConfigInvalid('OpenAI currently supports document collaboration only')
        if type(output_cap) is not int or not 1 <= output_cap <= self.output_limit:
            raise ConfigInvalid('Original Testing output bound differs')
        body = self.request(context)
        body['max_tokens'] = output_cap
        body['response_format'] = {'type': 'json_object'}
        return body
