import unittest
from datetime import datetime, timedelta, timezone

from backend.app.shared import validation as v
from backend.app.shared.pagination import page_metadata, page_number, page_offset
from backend.app.shared.time import utc_milliseconds


class ContractTests(unittest.TestCase):
    def assert_invalid(self, function, value, reason, *args, **kwargs):
        with self.assertRaises(v.InvalidInput) as result:
            function(value, *args, **kwargs)
        self.assertEqual(result.exception.errors[0].reason, reason)
        self.assertTrue(result.exception.details["field_errors"])
        return result.exception

    def test_id_and_version_integer_boundaries(self):
        for value in (1, 9_007_199_254_740_991):
            self.assertEqual(v.strict_integer(value, "id"), value)
        for value in (0, -1, 9_007_199_254_740_992):
            with self.subTest(value=value):
                self.assert_invalid(v.strict_integer, value, "OUT_OF_RANGE", "id")
        for value in (True, False, 1.0, "1", None, [], {}):
            with self.subTest(value=value):
                self.assert_invalid(v.strict_integer, value, "INVALID_TYPE", "id")
        self.assert_invalid(v.strict_integer, v.MISSING, "REQUIRED", "id")

    def test_canonical_path_query_integer(self):
        self.assertEqual(v.decimal_integer("9007199254740991", "id"), 9_007_199_254_740_991)
        for value in ("0", "01", "+1", "1.0", "1e2", "", " 1", "1 ", "１", "١"):
            with self.subTest(value=value):
                self.assert_invalid(v.decimal_integer, value, "INVALID_FORMAT", "id")
        for value in ("9007199254740992", "9" * 10_000):
            self.assert_invalid(v.decimal_integer, value, "OUT_OF_RANGE", "id")

    def test_enum_and_boolean_have_no_coercion(self):
        self.assertEqual(v.strict_enum("NEW", "type", ("NEW", "CHANGE")), "NEW")
        for value in ("new", " NEW", "NEW ", "", "ALL"):
            self.assert_invalid(v.strict_enum, value, "INVALID_ENUM", "type", ("NEW", "CHANGE"))
        self.assertIs(v.strict_boolean(False, "skipped"), False)
        for value in (0, 1, "false", None):
            self.assert_invalid(v.strict_boolean, value, "INVALID_TYPE", "skipped")

    def test_ordinary_text_normalization_order_and_unicode(self):
        self.assertEqual(v.instruction("\u3000\r\n甲\r\n乙\r丙\u00a0"), "甲\n乙\n丙")
        self.assertEqual(v.title("  Ａe\u0301  "), "Ａe\u0301")
        self.assertEqual(v.title("\ufeff甲\u200b"), "\ufeff甲\u200b")
        self.assertEqual(v.title("\u001c甲\u001f"), "\u001c甲\u001f")
        self.assert_invalid(v.title, "甲\r\n乙", "INVALID_FORMAT")
        self.assert_invalid(v.keyword, "甲\r乙", "INVALID_FORMAT")
        self.assertEqual(v.keyword(" \t\r\n\u3000"), "")
        self.assert_invalid(v.title, " \t\u3000", "TOO_SHORT")

    def test_each_text_field_codepoint_limit(self):
        for function, limit, minimum in ((v.title, 20, 1), (v.initial_idea, 10_000, 1), (v.instruction, 10_000, 1), (v.comment_content, 2_000, 1), (v.keyword, 100, 0)):
            with self.subTest(field=function.__name__):
                value = "😀" * limit
                self.assertEqual(function(value), value)
                self.assert_invalid(function, value + "😀", "TOO_LONG")
                if minimum:
                    self.assert_invalid(function, "", "TOO_SHORT")
                self.assert_invalid(function, None, "INVALID_TYPE")
        self.assertEqual(v.title("e\u0301" * 10), "e\u0301" * 10)
        self.assert_invalid(v.title, "e\u0301" * 11, "TOO_LONG")

    def test_optional_revision_description(self):
        for value in (v.MISSING, None, "", " \r\n\u3000"):
            self.assertIsNone(v.revision_description(value))
        self.assertEqual(v.revision_description(" \r\n甲\r乙 "), "甲\n乙")
        self.assertEqual(v.revision_description("😀" * 1_000), "😀" * 1_000)
        self.assert_invalid(v.revision_description, "😀" * 1_001, "TOO_LONG")
        self.assert_invalid(v.revision_description, False, "INVALID_TYPE")

    def test_raw_markdown_and_anchor_fragments_remain_exact(self):
        text = " \r\n**Ａe\u0301**\r\n "
        self.assertEqual(v.raw_text(text, "markdown_content", 0), text)
        self.assertEqual(v.selected_text(text), text)
        self.assertEqual(v.prefix_text(text), text)
        self.assertEqual(v.suffix_text(""), "")
        self.assertEqual(v.selected_text(" " * 2_000), " " * 2_000)
        self.assert_invalid(v.selected_text, "", "TOO_SHORT")
        self.assert_invalid(v.selected_text, "😀" * 2_001, "TOO_LONG")
        for function in (v.prefix_text, v.suffix_text):
            self.assertEqual(function("😀" * 100), "😀" * 100)
            self.assert_invalid(function, "😀" * 101, "TOO_LONG")
        # No idea-size limit is applied to full documents.
        self.assertEqual(len(v.raw_text("甲" * 100_001, "markdown_content", 0)), 100_001)

    def test_single_json_object_and_preserved_types(self):
        value = v.strict_json_object(b'{"integer":1,"decimal":1.0,"bool":true,"null":null,"nested":{"array":[1,2]}}')
        self.assertIs(type(value["integer"]), int)
        self.assertIs(type(value["decimal"]), float)
        self.assertIs(type(value["bool"]), bool)
        self.assertEqual(value["nested"], {"array": [1, 2]})
        self.assertEqual(v.strict_json_object(' {"甲":"😀"} \n'), {"甲": "😀"})
        for payload in ('{"a":1,"a":2}', '{"nested":{"a":1,"a":2}}', '{"array":[{"a":1,"a":2}]}', '{"a":1,"\\u0061":2}'):
            self.assert_invalid(v.strict_json_object, payload, "DUPLICATE_PARAMETER")
        for payload in ('```json\n{}\n```', '{} {}', '', '{', '{"a":NaN}', '{"a":Infinity}', '{"a":-Infinity}', '{"a":1e309}', b'\xff'):
            self.assert_invalid(v.strict_json_object, payload, "INVALID_FORMAT")
        for payload in ('[]', 'null', 'true', '1', '"{}"'):
            self.assert_invalid(v.strict_json_object, payload, "INVALID_TYPE")

    def test_unknown_and_required_object_fields_without_default_repair(self):
        value = {"title": None}
        self.assertIs(v.object_fields(value, "body", ("title", "mode"), ("title",)), value)
        failure = self.assert_invalid(v.object_fields, {"unknown": "secret-marker"}, "UNKNOWN_FIELD", "body", ("title",), ("title",))
        self.assertEqual([error.reason for error in failure.errors], ["UNKNOWN_FIELD", "REQUIRED"])
        self.assertNotIn("secret-marker", str(failure.details))
        self.assert_invalid(v.object_fields, "{}", "INVALID_TYPE", "body", ())
        self.assert_invalid(v.object_fields, [], "INVALID_TYPE", "body", ())

    def test_query_repeat_rules_and_original_occurrence_index(self):
        config = {"status": ("ACTIVE", "COMPLETED")}
        self.assertEqual(v.query_fields([("status", "ACTIVE"), ("status", "ACTIVE"), ("status", "COMPLETED"), ("page", "1")], ("page",), config), {"status": ["ACTIVE", "COMPLETED"], "page": "1"})
        self.assertEqual(v.query_fields([], ("page",), config), {})
        self.assert_invalid(v.query_fields, [("page", "1"), ("page", "1")], "DUPLICATE_PARAMETER", ("page",), config)
        self.assert_invalid(v.query_fields, [("unknown", "value")], "UNKNOWN_FIELD", ("page",), config)
        for value in ("", "active", "ACTIVE,COMPLETED", '["ACTIVE"]'):
            self.assert_invalid(v.query_fields, [("status", value)], "INVALID_ENUM", ("page",), config)
        failure = self.assert_invalid(v.query_fields, [("status", "ACTIVE"), ("status", "ACTIVE"), ("status", "bad")], "INVALID_ENUM", ("page",), config)
        self.assertEqual(failure.errors[0].field, "status[2]")

    def test_pagination_empty_and_valid_out_of_actual_range(self):
        self.assertEqual(page_metadata(1, 0), {"page": 1, "page_size": 20, "total": 0, "total_pages": 0})
        self.assertEqual(page_metadata(4, 41), {"page": 4, "page_size": 20, "total": 41, "total_pages": 3})
        self.assertEqual(page_offset(100_000), 1_999_980)
        self.assertEqual(page_number(), 1)
        for value in (0, 100_001):
            self.assert_invalid(page_number, value, "OUT_OF_RANGE")
        self.assert_invalid(page_number, True, "INVALID_TYPE")

    def test_utc_millisecond_projection(self):
        self.assertEqual(utc_milliseconds(datetime(2026, 9, 21, 16, 30, 0, 123_999, timezone(timedelta(hours=8)))), "2026-09-21T08:30:00.123Z")
        self.assertEqual(utc_milliseconds(datetime(2026, 9, 21, 8, 30, tzinfo=timezone.utc)), "2026-09-21T08:30:00.000Z")
        self.assertIsNone(utc_milliseconds(None))
        with self.assertRaises(ValueError):
            utc_milliseconds(datetime(2026, 9, 21))
        with self.assertRaises(ValueError):
            utc_milliseconds("2026-09-21T08:30:00.000Z")


if __name__ == "__main__":
    unittest.main()
