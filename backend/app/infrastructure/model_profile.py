"""D-007/D-014 immutable model profiles and exact historical restoration.

Environment startup defaults to DeepSeek v2. The one-argument constructor
retains its original v1 identity for existing private integrations/old audits;
new production requests use from_environment. Credentials are never snapshots.
"""
from dataclasses import dataclass, field
import os
from types import MappingProxyType
from urllib.parse import urlsplit

from .resources import ConfigInvalid
from backend.app.shared.validation import strict_json_object

MODEL_ID = 'doubao-seed-2-1-pro-260915'
MODEL_VERSION = '260915'
DEEPSEEK_MODEL_ID = 'deepseek-v4-1-flash-260910'
DEEPSEEK_MODEL_VERSION = '260910'
LEGACY_PROFILE = 'doubao-v1'
DEFAULT_PROFILE = 'deepseek-v2'
PROFILES = MappingProxyType({LEGACY_PROFILE: (MODEL_ID, MODEL_VERSION),
                            DEFAULT_PROFILE: (DEEPSEEK_MODEL_ID, DEEPSEEK_MODEL_VERSION)})
BASE_URL = 'https://ark.cn-beijing.volces.com/api/v3'
ENDPOINT = BASE_URL+'/chat/completions'


@dataclass(frozen=True)
class ModelProfile:
    api_key: str = field(repr=False)
    profile_id: str = LEGACY_PROFILE

    def __post_init__(self):
        if type(self.profile_id) is not str or self.profile_id not in PROFILES:
            raise ConfigInvalid('Only an approved immutable profile is permitted')
        if type(self.api_key) is not str or not self.api_key or len(self.api_key) > 8192 or self.api_key != self.api_key.strip() or any(ord(character) < 32 or ord(character) == 127 for character in self.api_key):
            raise ConfigInvalid('Model credential is missing or invalid')
        try: self.api_key.encode('ascii')
        except UnicodeEncodeError: raise ConfigInvalid('Model credential is invalid') from None

    @classmethod
    def from_environment(cls, environment=None):
        values = os.environ if environment is None else environment
        model = values.get('WALLE_MODEL_ID', DEEPSEEK_MODEL_ID)
        selected = next((name for name, pair in PROFILES.items() if type(model) is str and pair[0] == model), None)
        if selected is None or values.get('WALLE_MODEL_VERSION', PROFILES[selected][1]) != PROFILES[selected][1]:
            raise ConfigInvalid('Only an approved exact model/version pair is permitted')
        url = values.get('WALLE_MODEL_BASE_URL', BASE_URL)
        if type(url) is not str: raise ConfigInvalid('Model endpoint is invalid')
        try: parsed = urlsplit(url)
        except ValueError: raise ConfigInvalid('Model endpoint is invalid') from None
        if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or url.rstrip('/') != BASE_URL:
            raise ConfigInvalid('Only the approved credential-free Beijing endpoint is permitted')
        return cls(values.get('WALLE_MODEL_API_KEY'), selected)

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
        selected = next((name for name, pair in PROFILES.items()
                         if (snapshot.get('model_name'), snapshot.get('model_version')) == pair), None)
        if selected is None:
            raise ConfigInvalid('Persisted model/version pair is not approved')
        profile = cls(api_key, selected)
        from .idempotency import canonical_input
        try:
            exact = canonical_input(snapshot) == canonical_input(profile.snapshot)
        except (ValueError, TypeError, UnicodeError):
            exact = False
        if not exact:
            raise ConfigInvalid('Persisted model parameters differ from their frozen version')
        return profile

    @property
    def snapshot(self):
        return {'provider':'volcengine','model_name':self.model_name,'model_version':self.model_version,'endpoint':ENDPOINT,
            'temperature':0,'max_tokens':8192,'stream':False,'thinking':{'type':'disabled'},
            'timeouts':{'connect':10,'read':180,'write':10,'pool':10},'transport_retries':0}

    def request(self, context):
        if type(context.system) is not str or not context.system: raise ValueError('System protocol is required')
        strict_json_object(context.input_json)
        return {'model':self.model_name,'messages':[{'role':'system','content':context.system},{'role':'user','content':context.input_json}],
            'temperature':0,'max_tokens':8192,'stream':False,'thinking':{'type':'disabled'}}
