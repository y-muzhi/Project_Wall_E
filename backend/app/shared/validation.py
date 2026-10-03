"""Strict, framework-independent input validation (SHR-ID/TEXT/SERIALIZE).

Field errors describe requirements without echoing user input or credentials.
Markdown and anchor fragments must use raw_text, never ordinary_text.
"""

from dataclasses import dataclass
import json
import math
import re
from typing import Any, Iterable

MAX_SAFE_INTEGER = 9_007_199_254_740_991
MISSING = object()
# Unicode White_Space property; excludes BOM, zero-width space and C0 separators.
UNICODE_WHITESPACE = "\u0009\u000a\u000b\u000c\u000d\u0020\u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
REASONS = frozenset({"REQUIRED", "INVALID_TYPE", "INVALID_FORMAT", "INVALID_ENUM", "TOO_SHORT", "TOO_LONG", "OUT_OF_RANGE", "UNKNOWN_FIELD", "DUPLICATE_PARAMETER"})


@dataclass(frozen=True)
class FieldError:
    field: str
    reason: str
    message: str

    def __post_init__(self) -> None:
        if self.reason not in REASONS or not self.field or not self.message:
            raise ValueError("Invalid field-error contract")

    def as_dict(self) -> dict[str, str]:
        return {"field": self.field, "reason": self.reason, "message": self.message}


class InvalidInput(ValueError):
    """Application INVALID_INPUT, mapped to HTTP VALIDATION_FAILED by the boundary."""

    def __init__(self, errors: Iterable[FieldError]):
        self.errors = tuple(errors)
        if not self.errors:
            raise ValueError("At least one field error is required")
        super().__init__("请求参数不合法")

    @property
    def details(self) -> dict[str, list[dict[str, str]]]:
        return {"field_errors": [error.as_dict() for error in self.errors]}


def reject(field: str, reason: str, message: str) -> None:
    raise InvalidInput([FieldError(field, reason, message)])


def required(value: Any, field: str) -> Any:
    if value is MISSING:
        reject(field, "REQUIRED", "必须提供此参数")
    return value


def strict_integer(value: Any, field: str, minimum: int = 1, maximum: int = MAX_SAFE_INTEGER) -> int:
    required(value, field)
    if type(value) is not int:
        reject(field, "INVALID_TYPE", "必须是整数，不能使用布尔值、小数或字符串")
    if not minimum <= value <= maximum:
        reject(field, "OUT_OF_RANGE", f"必须在 {minimum}～{maximum} 范围内")
    return value


def decimal_integer(value: Any, field: str, maximum: int = MAX_SAFE_INTEGER) -> int:
    """Canonical path/query integer, with no coercion of whitespace or leading zeros."""
    required(value, field)
    if type(value) is not str:
        reject(field, "INVALID_TYPE", "必须是十进制整数文本")
    if re.fullmatch(r"[1-9][0-9]*", value) is None:
        reject(field, "INVALID_FORMAT", "必须是不带前导零的十进制正整数")
    # Compare before conversion to avoid Python's arbitrary-length int conversion limit.
    bound = str(maximum)
    if len(value) > len(bound) or (len(value) == len(bound) and value > bound):
        reject(field, "OUT_OF_RANGE", f"必须在 1～{maximum} 范围内")
    return int(value)


def strict_enum(value: Any, field: str, allowed: Iterable[str]) -> str:
    required(value, field)
    if type(value) is not str:
        reject(field, "INVALID_TYPE", "必须是枚举字符串")
    if value not in allowed:
        reject(field, "INVALID_ENUM", "必须使用此字段已登记的枚举值")
    return value


def strict_boolean(value: Any, field: str) -> bool:
    required(value, field)
    if type(value) is not bool:
        reject(field, "INVALID_TYPE", "必须是布尔值")
    return value


def normalize_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip(UNICODE_WHITESPACE)


def text_value(value: Any, field: str) -> str:
    required(value, field)
    if type(value) is not str:
        reject(field, "INVALID_TYPE", "必须是文本字符串")
    return value


def bounded_text(value: str, field: str, minimum: int, maximum: int) -> str:
    if len(value) < minimum:
        reject(field, "TOO_SHORT", f"至少需要 {minimum} 个 Unicode 码点")
    if len(value) > maximum:
        reject(field, "TOO_LONG", f"最多允许 {maximum} 个 Unicode 码点")
    return value


def ordinary_text(value: Any, field: str, minimum: int, maximum: int, *, multiline: bool = True) -> str:
    result = bounded_text(normalize_text(text_value(value, field)), field, minimum, maximum)
    if not multiline and "\n" in result:
        reject(field, "INVALID_FORMAT", "不允许内部换行")
    return result


def raw_text(value: Any, field: str, minimum: int, maximum: int | None = None) -> str:
    result = text_value(value, field)
    if len(result) < minimum:
        reject(field, "TOO_SHORT", f"至少需要 {minimum} 个 Unicode 码点")
    if maximum is not None and len(result) > maximum:
        reject(field, "TOO_LONG", f"最多允许 {maximum} 个 Unicode 码点")
    return result


def title(value: Any) -> str:
    return ordinary_text(value, "title", 1, 20, multiline=False)


def initial_idea(value: Any) -> str:
    return ordinary_text(value, "initial_idea", 1, 10_000)


def instruction(value: Any) -> str:
    return ordinary_text(value, "instruction", 1, 10_000)


def comment_content(value: Any) -> str:
    return ordinary_text(value, "content", 1, 2_000)


def keyword(value: Any = "") -> str:
    return ordinary_text(value, "keyword", 0, 100, multiline=False)


def revision_description(value: Any = MISSING) -> str | None:
    if value is MISSING or value is None:
        return None
    return ordinary_text(value, "description", 0, 1_000) or None


def selected_text(value: Any) -> str:
    return raw_text(value, "selected_text", 1, 2_000)


def prefix_text(value: Any) -> str:
    return raw_text(value, "prefix_text", 0, 100)


def suffix_text(value: Any) -> str:
    return raw_text(value, "suffix_text", 0, 100)


def object_fields(value: Any, field: str, allowed: Iterable[str], mandatory: Iterable[str] = ()) -> dict[str, Any]:
    required(value, field)
    if type(value) is not dict:
        reject(field, "INVALID_TYPE", "必须是 JSON 对象")
    allowed_set = frozenset(allowed)
    errors = [FieldError(f"{field}.{key}", "UNKNOWN_FIELD", "此字段未在契约中登记") for key in value if key not in allowed_set]
    errors.extend(FieldError(f"{field}.{key}", "REQUIRED", "必须提供此参数") for key in mandatory if key not in value)
    if errors:
        raise InvalidInput(errors)
    return value


def strict_json_object(payload: str | bytes, field: str = "body") -> dict[str, Any]:
    """Single JSON object, duplicate keys rejected at every depth; no fence repair."""
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                reject(field, "DUPLICATE_PARAMETER", "JSON 对象不得含有重复键")
            result[key] = value
        return result

    def nonfinite(_: str) -> None:
        reject(field, "INVALID_FORMAT", "JSON 数值必须是有限数")

    def finite_float(token: str) -> float:
        value = float(token)
        if not math.isfinite(value):
            nonfinite(token)
        return value

    if type(payload) not in (str, bytes):
        reject(field, "INVALID_TYPE", "必须提供 JSON 文本")
    try:
        text = payload.decode("utf-8") if type(payload) is bytes else payload
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=nonfinite, parse_float=finite_float)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as error:
        if isinstance(error, InvalidInput):
            raise
        reject(field, "INVALID_FORMAT", "必须是一份完整合法的 JSON 对象")
    if type(value) is not dict:
        reject(field, "INVALID_TYPE", "JSON 根必须是对象")
    return value


def query_fields(pairs: Iterable[tuple[str, str]], singles: Iterable[str], arrays: dict[str, Iterable[str]]) -> dict[str, Any]:
    """Preserve raw repeated query parameters; array values are enums, never CSV/JSON."""
    single_names = frozenset(singles)
    output: dict[str, Any] = {}
    occurrences: dict[str, int] = {}
    for key, value in pairs:
        if key in single_names:
            if key in output:
                reject(key, "DUPLICATE_PARAMETER", "单值参数不能重复提供")
            output[key] = value
        elif key in arrays:
            values = output.setdefault(key, [])
            index = occurrences.get(key, 0)
            occurrences[key] = index + 1
            parsed = strict_enum(value, f"{key}[{index}]", arrays[key])
            if parsed not in values:
                values.append(parsed)
        else:
            reject(key, "UNKNOWN_FIELD", "此查询参数未在契约中登记")
    return output
