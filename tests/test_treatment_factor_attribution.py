import subprocess
import sys

from src.common.experiment_inputs import parse_filex
from src.sensitivity.treatment_factor_attribution import (
    fertilizer_n_dates,
    normalize_fertilizer_level_rows,
    replace_fertilizer_n,
    replace_initial_components,
    replace_treatment_factors,
)


FILEX = """*TREATMENTS
@N R O C TNAME CU FL SA IC MP MI MF MR MC MT ME MH SM
 2 1 0 0 target  1  5  2  2  2  1  1  0  0  2  0  5  2
 3 1 0 0 ref     1  5  2  3  2  1  2  0  0  2  0  5  2
*INITIAL CONDITIONS
@C   PCR ICDAT ICRT
 2   -99 25069 1
@C  ICBL  SH2O  SNH4  SNO3
 2    20  .216   1.5  33.7
 2    40  .224     1  13.8
@C   PCR ICDAT ICRT
 3   -99 25069 1
@C  ICBL  SH2O  SNH4  SNO3
 3    20  .189   1.7  26.8
 3    40  .269     1  13.3
*PLANTING DETAILS
"""

FERTILIZER = """*FERTILIZERS (INORGANIC)
@F FDATE FMCD FACD FDEP FAMN FAMP FAMK FAMC FAMO FOCD FERNAME
 1 25069 FE005 AP002 25 108 0 0 0 0 0 N3
 1 25121 FE005 AP005 20 25 0 0 0 0 0 N3
 1 25188 FE005 AP005 20 25 0 0 0 0 0 N3
 2 25069 FE005 AP002 25 72 0 0 0 0 0 N2
 2 25121 FE005 AP005 20 17 0 0 0 0 0 N2
 2 25188 FE005 AP005 20 17 0 0 0 0 0 N2
*RESIDUES
"""


def _parse(tmp_path, text):
    path = tmp_path / "case.TMX"
    path.write_text(text, encoding="utf-8")
    return parse_filex(path)


def test_treatment_factor_replacement_is_scoped(tmp_path):
    updated = replace_treatment_factors(FILEX, 2, {"IC": 3, "MF": 2})
    parsed = _parse(tmp_path, updated)
    assert parsed["treatments"][2]["IC"] == 3
    assert parsed["treatments"][2]["MF"] == 2
    assert parsed["treatments"][3]["IC"] == 3


def test_initial_water_and_nitrogen_can_be_attributed_separately(tmp_path):
    water = replace_initial_components(FILEX, 2, 3, ("sh2o",))
    parsed_water = _parse(tmp_path, water)["initial_conditions"][2]
    assert parsed_water[0] == {"depth": 20.0, "sh2o": 0.189, "snh4": 1.5, "sno3": 33.7}

    nitrogen = replace_initial_components(FILEX, 2, 3, ("snh4", "sno3"))
    parsed_n = _parse(tmp_path, nitrogen)["initial_conditions"][2]
    assert parsed_n[0] == {"depth": 20.0, "sh2o": 0.216, "snh4": 1.7, "sno3": 26.8}


def test_direct_cli_entrypoint_loads_repo_package():
    completed = subprocess.run(
        [sys.executable, "src/sensitivity/treatment_factor_attribution.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_fertilizer_n_can_be_replaced_by_date():
    assert fertilizer_n_dates(FERTILIZER, 1) == [25069, 25121, 25188]
    updated = replace_fertilizer_n(FERTILIZER, 1, 2, {25188})
    rows = [line.split() for line in updated.splitlines() if line.strip().startswith("1 ")]
    assert [row[5] for row in rows] == ["108", "25", "17"]


def test_fertilizer_level_rows_can_be_made_contiguous_and_chronological():
    split = FERTILIZER.replace(
        " 2 25188 FE005 AP005 20 17 0 0 0 0 0 N2\n",
        "",
    ).replace(
        "@F FDATE FMCD FACD FDEP FAMN FAMP FAMK FAMC FAMO FOCD FERNAME\n",
        "@F FDATE FMCD FACD FDEP FAMN FAMP FAMK FAMC FAMO FOCD FERNAME\n"
        " 2 25188 FE005 AP005 20 17 0 0 0 0 0 N2\n",
    )
    normalized = normalize_fertilizer_level_rows(split, 2, "last")
    data = [line.split() for line in normalized.splitlines() if line.strip() and line.split()[0] in {"1", "2"}]
    level2_positions = [i for i, row in enumerate(data) if row[0] == "2"]
    assert level2_positions == list(range(level2_positions[0], level2_positions[-1] + 1))
    assert [int(data[i][1]) for i in level2_positions] == [25069, 25121, 25188]
