"""EV60 evidence boundaries: no paid call, no synthetic semantic pass evidence."""

import sys
import unittest
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import formation_evaluation as prepare
import formation_evaluation_review as review
from formation_evaluation_spec import TASKS, samples


def fake_manifest():
    # Explicit unit input only; never write these synthetic verdicts as EV evidence.
    rows = tuple(
        (sample.sample_id, 'full', '4', '401', *('a' * 64 for _ in range(6)), '100', 'b' * 64)
        for sample in samples()
    )
    lines = [
        '状态：INPUTS_FROZEN',
        'Samples: 60',
        'Candidates: 60',
        'Cohort-SHA256: ' + prepare.digest(prepare.stable(rows)),
        'Profile: synthetic-unit-only',
        'Release-SHA256: ' + 'e' * 64,
        'Input-limit: 120000',
        'Output-limit: 8192',
        'Total-limit: 131072',
    ]
    return '\n'.join([*lines, *('| ' + ' | '.join(row) + ' |' for row in rows)]) + '\n'


def replace_cell(content, identity, column, value, columns):
    lines = content.splitlines()
    for index, line in enumerate(lines):
        if line.startswith('| ' + identity + ' |'):
            cells = [cell.strip() for cell in line.strip('|').split('|')]
            cells[columns.index(column)] = value
            lines[index] = '| ' + ' | '.join(cells) + ' |'
    return '\n'.join(lines) + '\n'


def completed_documents(manifest):
    attempts = review.template(manifest, 'attempts')
    left = review.template(manifest, 'review').replace(
        'Reviewer-ID: UNASSIGNED', 'Reviewer-ID: person-a'
    )
    right = review.template(manifest, 'review').replace(
        'Reviewer-ID: UNASSIGNED', 'Reviewer-ID: person-b'
    )
    for sample in samples():
        identity = sample.sample_id
        values = {
            'Status': 'LIVE_RETURNED',
            'Chat attempts': '1',
            'Count batches': '1',
            'Counted input': '1000',
            'Usage input': 'UNKNOWN',
            'Usage output': 'UNKNOWN',
            'Request SHA256': 'a' * 64,
            'Evidence': 'synthetic-unit-only.md',
        }
        for column, value in values.items():
            attempts = replace_cell(attempts, identity, column, value, review.ATTEMPT_COLUMNS)
        for column in ('Rights', 'Protocol', 'Critical', 'Usable'):
            left = replace_cell(left, identity, column, 'PASS', review.REVIEW_COLUMNS)
            right = replace_cell(right, identity, column, 'PASS', review.REVIEW_COLUMNS)
        for column, value in (
            ('Reason', 'explicit synthetic unit verdict'),
            ('Evidence', 'synthetic-unit-only.md'),
            ('Decision', 'REUSE' if sample.related_branch else 'DISCUSS'),
        ):
            if column == 'Decision' and sample.task != 'discuss':
                continue
            left = replace_cell(left, identity, column, value, review.REVIEW_COLUMNS)
            right = replace_cell(right, identity, column, value, review.REVIEW_COLUMNS)
    return attempts, left, right


class EvaluationReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = fake_manifest()
        cls.documents = completed_documents(cls.manifest)

    def changed(self, document, index, column, value):
        docs = list(self.documents)
        columns = review.ATTEMPT_COLUMNS if document == 0 else review.REVIEW_COLUMNS
        docs[document] = replace_cell(
            docs[document], samples()[index].sample_id, column, value, columns
        )
        return docs

    def test_inventory_is_twelve_inputs_by_five_complete_tasks(self):
        fixed = samples()
        self.assertEqual(len(fixed), 60)
        self.assertEqual(len({sample.sample_id for sample in fixed}), 60)
        self.assertEqual(
            Counter(sample.task for sample in fixed), Counter({task: 12 for task, _, _ in TASKS})
        )
        self.assertEqual(sum(sample.edited for sample in fixed), 20)
        self.assertEqual(sum(sample.related_branch for sample in fixed), 10)

    def test_unassigned_or_same_person_cannot_supply_independent_evaluation(self):
        template = review.template(self.manifest, 'review')
        with self.assertRaisesRegex(ValueError, 'independent'):
            review.aggregate(self.manifest, self.documents[0], template, template)
        with self.assertRaisesRegex(ValueError, 'independent'):
            review.aggregate(self.manifest, *self.documents[:2], self.documents[1])

    def test_all_not_run_remains_zero_of_sixty_even_with_distinct_reviewers(self):
        attempts = review.template(self.manifest, 'attempts')
        left = review.template(self.manifest, 'review').replace('UNASSIGNED', 'person-a')
        right = review.template(self.manifest, 'review').replace('UNASSIGNED', 'person-b')
        result = review.aggregate(self.manifest, attempts, left, right)
        self.assertFalse(result['passed'])
        self.assertEqual(result['denominator'], 60)
        self.assertEqual(len(result['not_run']), 60)
        self.assertEqual(sum(result['usable'].values()), 0)

    def test_recorded_failures_cannot_shrink_denominator(self):
        docs = self.changed(0, 0, 'Status', 'STRUCTURED_REJECTED')
        result = review.aggregate(self.manifest, *docs)
        self.assertFalse(result['passed'])
        self.assertEqual(result['denominator'], 60)
        self.assertEqual(result['critical_failures'], (samples()[0].sample_id,))

    def test_one_critical_violation_blocks_otherwise_usable_cohort(self):
        docs = self.changed(1, 5, 'Rights', 'FAIL')
        result = review.aggregate(self.manifest, *docs)
        self.assertFalse(result['passed'])
        self.assertEqual(len(result['critical_failures']), 1)

    def test_ten_of_twelve_threshold_and_human_disagreement_are_exact(self):
        docs = list(self.documents)
        write_samples = [sample for sample in samples() if sample.task == 'write']
        for count, sample in enumerate(write_samples[:3], 1):
            docs[1] = replace_cell(
                docs[1], sample.sample_id, 'Usable', 'FAIL', review.REVIEW_COLUMNS
            )
            result = review.aggregate(self.manifest, *docs)
            self.assertEqual(result['usable']['write'], 12 - count)
            self.assertEqual(result['passed'], count <= 2)

    def test_wrong_reused_branch_is_critical_even_when_both_people_call_it_usable(self):
        index = next(
            i
            for i, sample in enumerate(samples())
            if sample.related_branch and sample.task == 'discuss'
        )
        docs = self.changed(1, index, 'Decision', 'NEW')
        docs[2] = replace_cell(
            docs[2], samples()[index].sample_id, 'Decision', 'NEW', review.REVIEW_COLUMNS
        )
        result = review.aggregate(self.manifest, *docs)
        self.assertFalse(result['passed'])
        self.assertIn(samples()[index].sample_id, result['critical_failures'])

    def test_pending_branch_decisions_and_conflicting_profile_cannot_count_as_evidence(self):
        docs = self.changed(1, 5, 'Decision', 'PENDING')
        docs[2] = replace_cell(
            docs[2], samples()[5].sample_id, 'Decision', 'PENDING', review.REVIEW_COLUMNS
        )
        result = review.aggregate(self.manifest, *docs)
        self.assertEqual(result['usable']['discuss'], 11)
        changed = self.documents[1].replace(
            'Profile: synthetic-unit-only', 'Profile: wrong-profile'
        )
        with self.assertRaisesRegex(ValueError, 'Profile'):
            review.aggregate(self.manifest, self.documents[0], changed, self.documents[2])

    def test_retry_unfrozen_request_and_sent_without_count_are_rejected(self):
        for column, value in (
            ('Chat attempts', '2'),
            ('Request SHA256', 'f' * 64),
            ('Chat attempts', '0'),
            ('Count batches', '0'),
            ('Count batches', '2'),
        ):
            with self.subTest(column=column, value=value), self.assertRaises(ValueError):
                review.aggregate(self.manifest, *self.changed(0, 0, column, value))

    def test_measured_budget_mismatch_blocks_even_two_positive_reviews(self):
        for column, value in (
            ('Counted input', '120001'),
            ('Usage input', '1001'),
            ('Usage output', '8193'),
        ):
            with self.subTest(column=column):
                result = review.aggregate(self.manifest, *self.changed(0, 0, column, value))
                self.assertFalse(result['passed'])
                self.assertEqual(result['denominator'], 60)
                self.assertIn(samples()[0].sample_id, result['critical_failures'])

    def test_unknown_provider_usage_stays_unknown_and_does_not_grant_admission(self):
        result = review.aggregate(self.manifest, *self.documents)
        self.assertTrue(result['passed'])  # Only the synthetic unit record meets criteria.
        rendered = review.summary(result, self.manifest, *self.documents)
        self.assertIn('不修改OFFLINE_READY/LIVE准入', rendered)
        self.assertIn('UNKNOWN', self.documents[0])

    def test_missing_duplicate_tampered_or_unbound_documents_are_rejected(self):
        identity = samples()[0].sample_id
        row = next(
            line
            for line in self.documents[1].splitlines()
            if line.startswith('| ' + identity + ' |')
        )
        for text in (
            self.documents[1].replace(row + '\n', ''),
            self.documents[1] + row + '\n',
            self.documents[1].replace('Manifest-SHA256: ', 'Manifest-SHA256: f'),
        ):
            with self.subTest(text=text[:50]), self.assertRaises(ValueError):
                review.aggregate(self.manifest, self.documents[0], text, self.documents[2])
        with self.assertRaises(ValueError):
            review.frozen_manifest(self.manifest.replace('Samples: 60', 'Samples: 59'))

    def test_markdown_output_never_overwrites_and_is_clean_after_failure(self):
        with TemporaryDirectory() as directory, patch.object(prepare, 'ROOT', Path(directory)):
            folder = Path(directory) / 'docs/verification/v2.1'
            folder.mkdir(parents=True)
            target = folder / 'test.md'
            prepare.new_markdown(target, 'original\n')
            with self.assertRaises(ValueError):
                prepare.new_markdown(target, 'replacement\n')
            self.assertEqual(target.read_text(), 'original\n')
            with patch.object(prepare.os, 'replace', side_effect=OSError('injected')):
                with self.assertRaises(OSError):
                    prepare.new_markdown(folder / 'failed.md', 'new\n')
            self.assertEqual([path.name for path in folder.iterdir()], ['test.md'])


if __name__ == '__main__':
    unittest.main()
