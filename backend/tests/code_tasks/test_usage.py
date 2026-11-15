import unittest

from backend.app.code_tasks.usage import (
    UsageContract,
    UsageState,
    confirm_final_usage,
    observe_usage,
)


class CumulativeUsageTests(unittest.TestCase):
    def setUp(self):
        self.contract = UsageContract(
            'test-parser-v1',
            'USAGE_TRAILER',
            ('input_tokens', 'output_tokens', 'cached_tokens'),
            ('cached_tokens',),
        )
        self.initial = UsageState('original-response')

    def observe(self, state, values):
        return observe_usage(
            state, values, response_ref='original-response', contract=self.contract
        )

    def final(self, state, values, **kwargs):
        return confirm_final_usage(
            state,
            values,
            response_ref='original-response',
            contract=self.contract,
            source=kwargs.pop('source', 'USAGE_TRAILER'),
            complete=kwargs.pop('complete', True),
            audit_complete=kwargs.pop('audit_complete', True),
            **kwargs,
        )

    def test_partial_growth_final_total_and_duplicate(self):
        state = self.observe(self.initial, {'input_tokens': 100})
        state = self.observe(state, {'input_tokens': 150, 'output_tokens': 10})
        self.assertEqual(state.status, 'PARTIAL')
        self.assertIsNone(state.settlement_usage)
        final = {'input_tokens': 200, 'output_tokens': 20, 'cached_tokens': 50}
        state = self.final(state, final)
        self.assertEqual(state.status, 'FINAL')
        self.assertEqual(state.settlement_usage, final)
        self.assertEqual(self.final(state, final), state)
        self.assertEqual(dict(state.latest)['input_tokens'], 200)
        copy = state.settlement_usage
        copy['input_tokens'] = 999
        self.assertEqual(state.settlement_usage, final)

    def test_missing_and_incomplete_never_freeze_or_fill_zero(self):
        for values in ({}, {'input_tokens': None}, {'input_tokens': 0, 'output_tokens': 0}):
            state = self.final(self.initial, values)
            self.assertIsNone(state.settlement_usage)
            self.assertNotEqual(state.status, 'FINAL')
        full = {'input_tokens': 0, 'output_tokens': 0, 'cached_tokens': 0}
        for flags in ({'complete': False}, {'audit_complete': False}):
            self.assertEqual(self.final(self.initial, full, **flags).status, 'PARTIAL')
        self.assertEqual(self.final(self.initial, full).status, 'FINAL')

    def test_old_optional_values_do_not_fill_final_required_fields(self):
        state = self.observe(self.initial, {'input_tokens': 100, 'cached_tokens': 40})
        state = self.final(state, {'input_tokens': 200, 'output_tokens': 10})
        self.assertEqual(state.status, 'PARTIAL')
        self.assertEqual(dict(state.latest)['cached_tokens'], 40)
        self.assertIsNone(state.settlement_usage)

    def test_regression_illegal_and_cross_response_hold(self):
        state = self.observe(self.initial, {'input_tokens': 100})
        for values in (
            {'input_tokens': 99},
            {'output_tokens': True},
            {'output_tokens': -1},
            {'output_tokens': 1.5},
            {'output_tokens': 9007199254740992},
        ):
            disputed = self.observe(state, values)
            self.assertEqual(disputed.status, 'DISPUTED')
            self.assertEqual(disputed.latest, state.latest)
            self.assertIsNone(disputed.settlement_usage)
        wrong = observe_usage(state, {}, response_ref='other', contract=self.contract)
        self.assertEqual(wrong.dispute_reason, 'RESPONSE_MISMATCH')
        self.assertEqual(self.observe(wrong, {'input_tokens': 1000}), wrong)

    def test_subsets_only_compare_same_observation(self):
        state = self.observe(self.initial, {'input_tokens': 100, 'output_tokens': 10})
        state = self.observe(state, {'cached_tokens': 120, 'reasoning_tokens': 20})
        self.assertEqual(state.status, 'PARTIAL')
        state = self.final(
            state,
            {
                'input_tokens': 200,
                'output_tokens': 30,
                'cached_tokens': 120,
                'reasoning_tokens': 20,
            },
        )
        self.assertEqual(state.status, 'FINAL')
        for values in (
            {'input_tokens': 100, 'cached_tokens': 101},
            {'output_tokens': 1, 'reasoning_tokens': 2},
        ):
            self.assertEqual(self.observe(self.initial, values).status, 'DISPUTED')

    def test_late_conflict_preserves_final_and_blocks_settlement(self):
        vector = {'input_tokens': 200, 'output_tokens': 20, 'cached_tokens': 0}
        state = self.final(self.initial, vector)
        disputed = self.final(state, {**vector, 'input_tokens': 201})
        self.assertEqual(disputed.status, 'DISPUTED')
        self.assertEqual(disputed.frozen_final, state.frozen_final)
        self.assertIsNone(disputed.settlement_usage)
        self.assertEqual(self.observe(state, {'output_tokens': 20}), state)

    def test_final_source_must_match_admitted_contract(self):
        vector = {'input_tokens': 1, 'output_tokens': 1, 'cached_tokens': 0}
        state = self.final(self.initial, vector, source='COMPLETE_BODY')
        self.assertEqual(state.dispute_reason, 'FINAL_SOURCE_MISMATCH')

    def test_contract_requires_all_price_dimensions(self):
        for args in (
            ('GUESSED', ('input_tokens', 'output_tokens')),
            ('USAGE_TRAILER', ('input_tokens',)),
            ('USAGE_TRAILER', ('input_tokens', 'output_tokens'), ('cached_tokens',)),
            ('USAGE_TRAILER', ('input_tokens', 'output_tokens'), ('input_tokens',)),
        ):
            with self.assertRaises(ValueError):
                UsageContract('test-parser-v1', *args)
