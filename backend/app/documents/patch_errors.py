"""Safe deterministic patch failures; no raw model/input text in messages."""


class PatchInvalid(ValueError):
    code = 'PATCH_INVALID'


class TargetStale(ValueError):
    code = 'TARGET_STALE'
