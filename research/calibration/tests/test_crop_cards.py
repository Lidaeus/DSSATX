import csv
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

CALIBRATION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CALIBRATION))
from crop_cards import card_number, materialize, number, read_map

FIXTURE = CALIBRATION.parent / "fixtures/v7-26sp"


class CropCardTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.inputs = self.work / "inputs"
        shutil.copytree(FIXTURE, self.inputs)

    def plan(self, entries):
        map_path = self.work / "map.csv"
        with map_path.open("w", newline="", encoding="ascii") as stream:
            writer = csv.writer(stream)
            writer.writerow(("name", "file", "record", "field"))
            writer.writerows((name, f"TMGRO048.{ext}", record, field)
                             for name, ext, record, field, _, _ in entries)
        bounds = pd.DataFrame([(name, lower, upper) for name, _, _, _, lower, upper in entries],
                              columns=["name", "lower", "upper"]).set_index("name")
        return read_map(map_path, self.inputs, bounds)

    def test_three_cards_preserve_other_columns_records_and_line_endings(self):
        entries = [
            ("lfmax", "CUL", "TM0008", "LFMAX", 1.2, 2.8),
            ("pm06", "ECO", "TM0001", "PM06", .1, .2),
            ("lngsh", "ECO", "TM0001", "LNGSH", 18, 21),
            ("vssink", "SPE", "", "VSSINK", 4, 15),
            ("xswbar3", "SPE", "", "XSWBAR(3)", .25, .6),
            ("senpor4", "SPE", "", "SENPOR(4)", .16, .27),
        ]
        values = dict(lfmax=2.23456789, pm06=.13245, lngsh=19.85, vssink=10.85378,
                      xswbar3=.35246, senpor4=.24713)
        plan = self.plan(entries)
        overrides, readback = materialize(plan, self.inputs, values, self.work)
        self.assertEqual(readback["pm06"]["columns"], [61, 66])
        self.assertEqual(readback["lngsh"]["columns"], [73, 78])
        self.assertEqual(readback["lfmax"]["columns"], [79, 84])
        for path, filename in overrides.items():
            before = (self.inputs / filename).read_bytes().splitlines(keepends=True)
            after = path.read_bytes().splitlines(keepends=True)
            self.assertEqual(list(map(len, before)), list(map(len, after)))
            for field in plan[filename]["fields"]:
                row, start, alias = field["row"], field["col"], field["name"]
                self.assertAlmostEqual(number(after[row][start:start + 6]), values[alias], delta=abs(values[alias]) * .001)
                after[row] = after[row][:start] + before[row][start:start + 6] + after[row][start + 6:]
            self.assertEqual(before, after)
        self.assertEqual((self.inputs / "TMGRO048.SPE").read_bytes(), (FIXTURE / "TMGRO048.SPE").read_bytes())

    def test_rejects_inactive_records_duplicate_destinations_and_changed_source(self):
        with self.assertRaisesRegex(ValueError, "inactive"):
            self.plan([("lfmax", "CUL", "DFAULT", "LFMAX", 1, 3)])
        a = ("lfmax", "CUL", "TM0008", "LFMAX", 1, 3)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.plan([a, ("second", *a[1:])])
        plan = self.plan([a])
        path = self.inputs / "TMGRO048.CUL"
        path.write_bytes(path.read_bytes() + b"! comment\r\n")
        with self.assertRaisesRegex(ValueError, "Frozen crop card changed"):
            materialize(plan, self.inputs, {"lfmax": 2}, self.work)

    def test_checks_rounded_candidate_bounds_and_native_array_order(self):
        plan = self.plan([("xswbar3", "SPE", "", "XSWBAR(3)", 0, 1)])
        with self.assertRaisesRegex(ValueError, "require[d] order"):
            materialize(plan, self.inputs, {"xswbar3": .005}, self.work)
        with self.assertRaisesRegex(ValueError, "outside"):
            materialize(plan, self.inputs, {"xswbar3": 1.01}, self.work)
        with self.assertRaisesRegex(ValueError, "bounds must be representable"):
            self.plan([("lfmax", "CUL", "TM0008", "LFMAX", 1.0012345, 3)])

    def test_checks_leaf_stem_partition_when_only_the_stem_changes(self):
        plan = self.plan([("ystem3", "SPE", "", "YSTEM(3)", 0, 1)])
        with self.assertRaisesRegex(ValueError, "negative root partition"):
            materialize(plan, self.inputs, {"ystem3": .46}, self.work)
        _, receipt = materialize(plan, self.inputs, {"ystem3": .45}, self.work)
        self.assertEqual(receipt["ystem3"]["readback"], .45)

    def test_ordered_species_row_can_start_with_full_width_number(self):
        plan = self.plan([("prolfi", "SPE", "", "PROLFI", .27, .325)])
        overrides, receipt = materialize(plan, self.inputs, {"prolfi": .29014}, self.work)
        self.assertEqual(receipt["prolfi"]["readback"], .29014)
        row = receipt["prolfi"]["row"] - 1
        path = next(iter(overrides))
        self.assertEqual(path.read_bytes().splitlines()[row][:6], b".29014")

    def test_formats_fortran_notation_and_rejects_overflow_or_nonfinite(self):
        self.assertEqual(number(b"2.5D-3"), .0025)
        self.assertEqual(number(b"2.5-03"), .0025)
        self.assertEqual(len(card_number(1e-6)), 6)
        self.assertEqual(number(card_number(.00037)), .00037)
        with self.assertRaises(ValueError):
            card_number(float("nan"))
        with self.assertRaises(ValueError):
            card_number(123456789.0)


if __name__ == "__main__":
    unittest.main()
