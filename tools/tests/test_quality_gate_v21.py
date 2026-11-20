"""Verify V2.1 test coverage partition and fail-closed reporting, without product execution."""

import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
gate = importlib.import_module('quality_gate_v21')


class V21QualityGateTests(unittest.TestCase):
    def test_every_actual_v21_test_is_selected_once_and_future_names_are_not_dropped(self):
        groups = gate.inventory()
        all_files = list((gate.ROOT / 'backend/tests/formation').glob('test_v21_*.py'))
        selected = [path for files in groups.values() for path in files]
        self.assertEqual(set(selected), set(all_files))
        self.assertEqual(len(selected), len(set(selected)))
        self.assertEqual(gate.group_for(Path('test_v21_future_capability.py')), 'programs')
        self.assertEqual(
            {path.stem for path in groups['load']},
            {'test_v21_load_continuation', 'test_v21_combined_growth_performance'},
        )

    def test_backend_uses_fixed_bootstrap_and_owned_basetemp(self):
        with TemporaryDirectory() as directory:
            temporary = Path(directory)
            definitions = gate.stage_commands(temporary, ('core',))
            self.assertEqual(len(definitions), 1)
            stage, command, cwd = definitions[0]
            self.assertEqual(stage, 'backend-core')
            self.assertEqual(cwd, gate.ROOT)
            self.assertEqual(Path(command[2]), gate.ROOT / 'tools/python-v20.py')
            self.assertEqual(Path(command[3]), gate.ROOT / 'tools/quality_python.py')
            self.assertTrue(Path(command[-1]).is_relative_to(temporary))
            self.assertNotIn('test_v15', ' '.join(command))

    def test_missing_result_source_change_and_cleanup_failure_cannot_pass(self):
        row = {'stage': 'backend-core', 'status': 'PASSED', 'seconds': 1, 'summary': '2 passed'}
        variants = [
            ([row], 'a', 'a', True, 0),
            ([], 'a', 'a', True, 1),
            ([row], 'a', 'b', True, 1),
            ([row], 'a', 'a', False, 1),
        ]
        with TemporaryDirectory() as directory:
            for results, before, after, cleanup, expected_code in variants:
                report, code = gate.save_report(
                    ('core',),
                    ('backend-core',),
                    results,
                    before,
                    after,
                    cleanup,
                    datetime.now(timezone.utc),
                    'test',
                    root=Path(directory),
                )
                self.assertEqual(code, expected_code)
                text = report.read_text(encoding='utf-8')
                self.assertIn('非整版验收', text)
                self.assertIn('未执行load', text)
                self.assertNotIn('V1.5离线检查结果', text)

    def test_version_entry_dispatches_its_own_gate(self):
        specification = importlib.util.spec_from_file_location(
            'v21_entry', TOOLS / 'check-v21-offline.py'
        )
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        self.assertIs(module.main, gate.main)


if __name__ == '__main__':
    unittest.main()
