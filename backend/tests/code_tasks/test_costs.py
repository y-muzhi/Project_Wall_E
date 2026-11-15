import unittest

from backend.app.code_tasks.costs import (
    final_usage_cost,
    ApplicablePrices,
    CachePrice,
    IncompleteUsage,
    available_balance,
    format_balance,
    format_money,
    parse_balance,
    parse_money,
    reserve_cost,
    settle_cost,
)
from backend.app.shared.validation import InvalidInput
from backend.app.code_tasks.usage import (
    UsageContract,
    UsageState,
    observe_usage,
    confirm_final_usage,
)


class ExactCostTests(unittest.TestCase):
    def test_design_vectors_round_total_once(self):
        vectors = (
            (1000, 200, '1', '1', (), None, '0.001200'),
            (
                1000,
                200,
                '1',
                '2',
                (CachePrice('cached_tokens', 200000),),
                {'cached_tokens': 500},
                '0.001000',
            ),
            (1, 1, '0.5', '0.5', (), None, '0.000001'),
            (1, 0, '0.5', '0', (), None, '0.000001'),
            (1, 0, '0.499999', '0', (), None, '0.000000'),
            (0, 0, '1', '1', (), None, '0.000000'),
        )
        for i, o, ip, op, cache, counts, expected in vectors:
            with self.subTest(expected=expected, i=i, o=o, ip=ip):
                prices = ApplicablePrices(parse_money(ip), parse_money(op), cache)
                self.assertEqual(format_money(settle_cost(i, o, prices, counts)), expected)
        self.assertEqual(reserve_cost(1, 0, 499999, 0), 1)

    def test_arbitrary_integer_precision_and_negative_balance(self):
        huge = 10**60
        price = ApplicablePrices(huge, huge)
        self.assertEqual(settle_cost(1000000, 0, price), huge)
        self.assertEqual(reserve_cost(1000000, 0, huge, 0), huge)
        text = format_money(huge)
        self.assertEqual(parse_money(text), huge)
        remaining = available_balance(1000000, 1000000, 1)
        self.assertEqual(format_balance(remaining), '-0.000001')
        self.assertEqual(parse_balance('-0.000001'), remaining)
        self.assertEqual(format_balance(0), '0.000000')

    def test_missing_usage_never_becomes_free(self):
        prices = ApplicablePrices(1000000, 2000000, (CachePrice('cached_tokens', 200000),))
        for i, o, counts in ((None, 0, {}), (0, None, {}), (1000, 200, None)):
            with self.subTest(i=i, o=o):
                with self.assertRaises(IncompleteUsage):
                    settle_cost(i, o, prices, counts)
        self.assertEqual(settle_cost(1000, 200, prices, {'cached_tokens': 0}), 1400)

    def test_equal_cache_prices_can_use_complete_totals(self):
        prices = ApplicablePrices(1000000, 2000000, (CachePrice('cached_tokens', 1000000),))
        self.assertEqual(settle_cost(1000, 200, prices), 1400)

    def test_cache_categories_are_exclusive_and_priced(self):
        prices = ApplicablePrices(
            1000000,
            2000000,
            (
                CachePrice('short_cache', 100000),
                CachePrice('long_cache', 200000),
            ),
        )
        self.assertEqual(settle_cost(1000, 0, prices, {'short_cache': 400, 'long_cache': 500}), 240)
        for counts in (
            {'short_cache': 1001, 'long_cache': 0},
            {'unknown': 0},
            {'short_cache': True, 'long_cache': 0},
        ):
            with self.subTest(counts=counts):
                with self.assertRaises(ValueError):
                    settle_cost(1000, 0, prices, counts)
        with self.assertRaises(ValueError):
            ApplicablePrices(1, 1, (CachePrice('same', 1), CachePrice('same', 2)))

    def test_strict_amount_and_token_inputs(self):
        for value in (
            None,
            True,
            1,
            1.0,
            '',
            '-0',
            '-1',
            '+1',
            '1e2',
            ' 1',
            '1\n',
            '1.',
            '.1',
            '01',
            '1.0000001',
            '１',
        ):
            with self.subTest(value=value):
                with self.assertRaises(InvalidInput):
                    parse_money(value)
        for value in ('-0.000000', '+0.000001', '1', '01.000000', '1.000000\n'):
            with self.subTest(value=value):
                with self.assertRaises(InvalidInput):
                    parse_balance(value)
        for value in (True, -1, 1.5, '1', 9007199254740992):
            with self.subTest(value=value):
                with self.assertRaises(InvalidInput):
                    settle_cost(value, 0, ApplicablePrices(1, 1))
        for value in (-1, True, 0.5):
            with self.assertRaises(ValueError):
                format_money(value)

    def test_usage_to_cost_path_rejects_partial_and_disputed(self):
        contract = UsageContract(
            'test-parser-v1', 'COMPLETE_BODY', ('input_tokens', 'output_tokens')
        )
        initial = UsageState('response-1')
        prices = ApplicablePrices(1000000, 2000000)
        vector = {'input_tokens': 1000, 'output_tokens': 200}
        partial = observe_usage(initial, vector, response_ref='response-1', contract=contract)
        with self.assertRaises(IncompleteUsage):
            final_usage_cost(partial, prices)
        final = confirm_final_usage(
            partial,
            vector,
            response_ref='response-1',
            contract=contract,
            source='COMPLETE_BODY',
            complete=True,
            audit_complete=True,
        )
        self.assertEqual(final_usage_cost(final, prices), 1400)
        disputed = observe_usage(
            final, {**vector, 'output_tokens': 201}, response_ref='response-1', contract=contract
        )
        with self.assertRaises(IncompleteUsage):
            final_usage_cost(disputed, prices)


if __name__ == '__main__':
    unittest.main()
