import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "n_diagnostics"))
from data import native_table


class NativeTargetTests(unittest.TestCase):
    def test_readable_observation_survives_an_unselected_overflow(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "PlantGro.OUT"
            path.write_text(
                "*RUN 1 : T1 CRGRO\n TREATMENT 1\n"
                "@YEAR DOY LAID LWAD\n 2026 120 2.15 ******\n",
                encoding="ascii",
            )
            with self.assertRaises(ValueError):
                native_table(path)
            record = native_table(path, allow_numeric_overflow=True).iloc[0]
            self.assertEqual(record.yrdoy, 2026120)
            self.assertEqual(record.LAID, 2.15)
            self.assertTrue(math.isnan(record.LWAD))
