"""Safe deterministic patch failures; no raw model/input text in messages."""

PATCH_MESSAGES = {'PATCH_INVALID': '修改建议结构不合法或不能组合应用', 'TARGET_STALE': '修改目标或原内容已变化'}


class PatchInvalid(ValueError):
    code = 'PATCH_INVALID'


class TargetStale(ValueError):
    code = 'TARGET_STALE'
