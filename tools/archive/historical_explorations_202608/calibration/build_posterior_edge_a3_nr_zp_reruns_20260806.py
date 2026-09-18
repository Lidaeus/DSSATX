"""Build the two posterior-edge A3 NR-ZP rerun PSTs without touching originals."""

from __future__ import annotations

from pathlib import Path

from tools.calibration import build_saactive_a3_nr_zp_200x4_20260806 as b33
from tools.calibration import build_saall_a3_nr_zp_200x4_20260806 as b83


ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    b33.CASE = "e02_v2_rawdiff_terminal_nresp01_soil02_saactive_postedge_a3_nr_zp_200x4_20260806"
    b33.OUT = ROOT / "workspace/runs" / b33.CASE
    b33.SA_BOUNDS = "eggplant_two_spring_morris_top95_genetic_postedge_20260806"
    b33.SA_BOUNDS_CSV = ROOT / "data/parameter_registry/bounds_frozen/eggplant" / f"{b33.SA_BOUNDS}.csv"
    b33.main()

    b83.CASE = "e02_v2_rawdiff_terminal_nresp01_soil02_saall_postedge_a3_nr_zp_200x4_20260806"
    b83.OUT = ROOT / "workspace/runs" / b83.CASE
    b83.BOUNDS_ID = "eggplant_two_spring_organ_n_postedge_20260806"
    b83.BOUNDS_CSV = ROOT / "data/parameter_registry/bounds_frozen/eggplant" / f"{b83.BOUNDS_ID}.csv"
    b83.main()


if __name__ == "__main__":
    main()
