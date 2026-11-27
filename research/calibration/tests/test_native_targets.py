import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "n_diagnostics"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data import native_table
from forward import evaluate


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

    def test_shared_parameters_route_overlapping_treatments_by_year(self):
        targets = pd.DataFrame({"name": ["spring25first", "spring26", "spring25last"],
                                "dataset": ["s25", "s26", "s25"], "treatment": [2, 2, 2]})
        inputs, executable = Path("inputs"), Path("engine")
        overrides = {Path("shared/NIntegration.nml"): "NIntegration.nml"}

        with patch("forward.evaluate_batch", side_effect=([10, 30], [20])) as run:
            self.assertEqual(evaluate(inputs, executable, targets, overrides, Path("dssat.log")), [10, 20, 30])
        calls = [call.args for call in run.call_args_list]
        self.assertEqual([args[0] for args in calls], [inputs / "s25", inputs / "s26"])
        self.assertEqual([args[2].name.tolist() for args in calls], [["spring25first", "spring25last"], ["spring26"]])
        self.assertTrue(all(args[3] is overrides for args in calls))
