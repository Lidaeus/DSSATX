"""Critical failure-isolation and native fixed-width checks for the new adapter."""
from pathlib import Path
import json
import tempfile
import unittest

from smoke_forward import evaluate, inject_cultivar


class AdapterChecks(unittest.TestCase):
    def test_fixed_width_preserves_identity_and_unselected_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            line = 'TM0008' + ' ' * 42 + '  28.0   3.7  25.5 400.0 203.5  1.66 220.0' + ' untouched'
            path = work / 'TMGRO048.CUL'
            path.write_text(line + '\n')
            actual = inject_cultivar(work, {'EM-FL': 27.125, 'SLAVR': 219.96}, {'EM-FL': 48, 'SLAVR': 84})
            after = path.read_text().splitlines()[0]
            self.assertEqual(len(after), len(line))
            self.assertEqual(after[:48], line[:48])
            self.assertEqual(after[54:84], line[54:84])
            self.assertEqual(after[90:], line[90:])
            self.assertEqual(actual, {'EM-FL': 27.12, 'SLAVR': 220.0})
            self.assertIn('.', after[84:90])
            self.assertTrue(after[84:90].startswith(' '))

    def test_overflow_is_rejected_before_native_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            path = work / 'TMGRO048.CUL'
            line = 'TM0008' + ' ' * 90 + '\n'
            path.write_text(line)
            with self.assertRaisesRegex(ValueError, 'overflow'):
                inject_cultivar(work, {'SLAVR': 999999.}, {'SLAVR': 84})
            self.assertEqual(path.read_text(), line)

    def test_bad_frozen_dependency_cannot_reuse_old_objective(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            dependency = work / 'dependency.txt'
            dependency.write_text('mutated')
            design = work / 'design.json'
            design.write_text(json.dumps({'frozen_hashes': {str(dependency): 'wrong'}}))
            (work / 'FormalObjectives.OUT').write_text('stale objective')
            with self.assertRaisesRegex(ValueError, 'Frozen dependency changed'):
                evaluate(design, work / 'irrelevant_parameters.csv', work)
            self.assertFalse((work / 'FormalObjectives.OUT').exists())
            failure = json.loads((work / 'last_failure.json').read_text())
            self.assertFalse(failure['success'])
            self.assertFalse(failure['imputed'])
            self.assertEqual(len(list((work / 'native_trials').glob('*/receipt.json'))), 1)


if __name__ == '__main__':
    unittest.main()
