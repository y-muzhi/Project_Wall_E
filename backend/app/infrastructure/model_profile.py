"""D-007 fixed Volcengine profile; credentials never form a snapshot field."""
from dataclasses import dataclass, field
import os
from urllib.parse import urlsplit

from .resources import ConfigInvalid
from backend.app.shared.validation import strict_json_object

MODEL_ID = 'doubao-seed-2-1-pro-260915'
MODEL_VERSION = '260915'
BASE_URL = 'https://ark.cn-beijing.volces.com/api/v3'
ENDPOINT = BASE_URL+'/chat/completions'


@dataclass(frozen=True)
class ModelProfile:
    api_key: str = field(repr=False)

    def __post_init__(self):
        if type(self.api_key) is not str or not self.api_key or len(self.api_key) > 8192 or self.api_key != self.api_key.strip() or any(ord(character) < 32 or ord(character) == 127 for character in self.api_key):
            raise ConfigInvalid('Model credential is missing or invalid')
        try: self.api_key.encode('ascii')
        except UnicodeEncodeError: raise ConfigInvalid('Model credential is invalid') from None

    @classmethod
    def from_environment(cls, environment=None):
        values = os.environ if environment is None else environment
        if values.get('WALLE_MODEL_ID', MODEL_ID) != MODEL_ID or values.get('WALLE_MODEL_VERSION', MODEL_VERSION) != MODEL_VERSION:
            raise ConfigInvalid('Only the approved frozen model and version are permitted')
        url = values.get('WALLE_MODEL_BASE_URL', BASE_URL)
        if type(url) is not str: raise ConfigInvalid('Model endpoint is invalid')
        try: parsed = urlsplit(url)
        except ValueError: raise ConfigInvalid('Model endpoint is invalid') from None
        if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or url.rstrip('/') != BASE_URL:
            raise ConfigInvalid('Only the approved credential-free Beijing endpoint is permitted')
        return cls(values.get('WALLE_MODEL_API_KEY'))

    @property
    def snapshot(self):
        return {'provider':'volcengine','model_name':MODEL_ID,'model_version':MODEL_VERSION,'endpoint':ENDPOINT,
            'temperature':0,'max_tokens':8192,'stream':False,'thinking':{'type':'disabled'},
            'timeouts':{'connect':10,'read':180,'write':10,'pool':10},'transport_retries':0}

    def request(self, context):
        if type(context.system) is not str or not context.system: raise ValueError('System protocol is required')
        strict_json_object(context.input_json)
        return {'model':MODEL_ID,'messages':[{'role':'system','content':context.system},{'role':'user','content':context.input_json}],
            'temperature':0,'max_tokens':8192,'stream':False,'thinking':{'type':'disabled'}}
