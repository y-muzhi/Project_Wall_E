"""Separate instance-local model credential derived from the original launch seed."""

import hmac
from dataclasses import dataclass, field

from .opencode_task_launch import TaskExecutionError
from .runtime_launch_journal import _bytes

MODEL_BASE_URL_ENV = 'WALLE_CODE_MODEL_BASE_URL'
MODEL_BEARER_ENV = 'WALLE_CODE_MODEL_BEARER'


@dataclass(frozen=True)
class OpenCodeModelCredential:
    reference: str
    endpoint: tuple[str, int]
    _secret: str = field(repr=False)

    @classmethod
    def derive(cls, scope, endpoint, seed):
        original = _bytes([scope.key, endpoint])
        key = bytes.fromhex(seed)
        reference = hmac.digest(key, b'walle-model-route-v1\0' + original, 'sha256').hex()[:32]
        secret = hmac.digest(key, b'walle-model-bearer-v1\0' + original, 'sha256').hex()
        return cls(reference, endpoint, secret)

    @property
    def base_url(self):
        address, port = self.endpoint
        return f'http://{address}:{port}/internal/code-model/{self.reference}/v1'

    @property
    def route(self):
        return f'/internal/code-model/{self.reference}/v1/chat/completions'

    def verify(self, authorization):
        if (
            type(authorization) is not str
            or not authorization.isascii()
            or not hmac.compare_digest(authorization, 'Bearer ' + self._secret)
        ):
            raise TaskExecutionError('ORIGINAL_MODEL_CREDENTIAL_UNVERIFIED')

    def environment(self):
        return {MODEL_BASE_URL_ENV: self.base_url, MODEL_BEARER_ENV: self._secret}
