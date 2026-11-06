from pathlib import Path

import pandas as pd
import pytest
from pyemu.pst.pst_utils import InstructionFile

from src.calibration.build_pest import PEST_N_DOSE_GRADIENT_FILE, _build_ins_and_obs
from src.calibration.nitrogen_response import (
    build_observed_n_dose_gradient_rows,
    write_simulated_n_dose_gradient,
)


def _mapping() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "season_id": ["26SP"] * 4,
            "treatment": [1, 2, 3, 4],
            "water_level": ["W2"] * 4,
            "nitrogen_level": ["N0", "N1", "N2", "N3"],
            "global_run": [1, 2, 3, 4],
        }
    )


def test_observed_gradient_clamps_target_but_preserves_cv_contract() -> None:
    harvest = pd.DataFrame(
        {
            "@RUN": [1, 2, 3, 4],
            "TN": [1, 2, 3, 4],
            "HNO": [1] * 4,
            "DATE": [26146] * 4,
            "CHFPWM": [80.0, 100.0, 90.0, 140.0],
            "season": ["26SP"] * 4,
        }
    )
    result = build_observed_n_dose_gradient_rows(
        harvest, _mapping(), sigma_floor=0.05, response_target="monotone_plateau"
    )
    assert len(result) == 3
    rows = result.set_index("gradient_metric")
    assert rows.loc["NG12", "NG12M"] == pytest.approx(0.0)
    assert rows.loc["NG23", "NG23M"] > 0.0
    assert rows.loc["NGCV", "NGCVM"] > 0.0
    assert rows.loc["NG12", "NG12M_SIGMA"] == pytest.approx(0.05)
    assert rows.loc["NG12", "NG23M"] == pytest.approx(-99.0)
    assert rows.loc["NG23", "NGCVM"] == pytest.approx(-99.0)


def test_simulated_gradient_keeps_negative_inversion(tmp_path: Path) -> None:
    harvest = tmp_path / "PestHarvest.OUT"
    harvest.write_text(
        "RUN 2 TN 2 @HNO@ 1 DATE 26146 @CHFPWS@ 100\n"
        "RUN 3 TN 3 @HNO@ 1 DATE 26146 @CHFPWS@ 90\n"
        "RUN 4 TN 4 @HNO@ 1 DATE 26146 @CHFPWS@ 140\n",
        encoding="utf-8",
    )
    output = tmp_path / "PestNDoseGradient.OUT"
    write_simulated_n_dose_gradient(harvest, output, _mapping())
    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    value = float(lines[0].split("@NG12S@", 1)[1].split()[0])
    assert value < 0.0
    assert "@NG23S@" in lines[1] and "@NGCVS@" in lines[2]
    assert sum("@NG12S@" in line for line in lines) == 1
    assert sum("@NG23S@" in line for line in lines) == 1
    assert sum("@NGCVS@" in line for line in lines) == 1


def test_generated_instruction_contract_parses_each_gradient_value(tmp_path: Path) -> None:
    harvest_obs = pd.DataFrame(
        {
            "@RUN": [1, 2, 3, 4], "TN": [1, 2, 3, 4],
            "HNO": [1] * 4, "DATE": [26146] * 4,
            "CHFPWM": [80.0, 100.0, 90.0, 140.0],
            "season": ["26SP"] * 4,
        }
    )
    observed = build_observed_n_dose_gradient_rows(harvest_obs, _mapping())
    obs_data, ins_lines = _build_ins_and_obs(
        observed, {"NG12", "NG23", "NGCV"}, set(),
        PEST_N_DOSE_GRADIENT_FILE, {},
    )
    assert len(obs_data) == 3
    assert ins_lines[0] == "pif @"
    assert ins_lines[1].startswith("l1 @NG12S@ w !")
    assert ins_lines[2].startswith("l1 @NG23S@ w !")
    assert ins_lines[3].startswith("l1 @NGCVS@ w !")

    simulated_harvest = tmp_path / "PestHarvest.OUT"
    simulated_harvest.write_text(
        "RUN 2 TN 2 @HNO@ 1 DATE 26146 @CHFPWS@ 100\n"
        "RUN 3 TN 3 @HNO@ 1 DATE 26146 @CHFPWS@ 90\n"
        "RUN 4 TN 4 @HNO@ 1 DATE 26146 @CHFPWS@ 140\n",
        encoding="utf-8",
    )
    simulated = tmp_path / "PestNDoseGradient.OUT"
    write_simulated_n_dose_gradient(simulated_harvest, simulated, _mapping())
    instruction = tmp_path / "PestNDoseGradient.OUT.ins"
    instruction.write_text("\n".join(ins_lines) + "\n", encoding="utf-8")
    parsed = InstructionFile(str(instruction)).read_output_file(str(simulated))
    assert parsed is not None
    assert len(parsed) == 3
    assert parsed["obsval"].notna().all()
