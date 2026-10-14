"""Unit and regression tests for Phase 1 format alignment and safety safeguards.

Verifies:
[1.1] SPE Format Alignment: TMGRO048.SPE.base lines strictly align to 6-column fixed width 4F6.0.
      DEMAND_CNC.FOR contains numerical range validation and fallback warnings.
[1.2] Optimization Penalty Safeguard: stage_r4_setup assigns heavy penalty (999.0) when simulated CNC is missing.
[1.3] Phenology Extraction: cross_season_evaluator extracts ADAP from Evaluate.OUT, returning np.nan / missing if absent.
[1.4] Seed Nitrogen Accumulation: GROW_CNC accumulates NHSDWT using PCNSD (seed N concentration), not PCNSH.
[1.5] Instantaneous Harvest Flux Synchronization: GROW and CROPGRO share HPODN_FLUX.
[1.6] Treatment Number Mapping: run_cross_season_comparison enforces explicit RUN -> TRNO for 25SP (1..8 -> 2,3,4,5,10,11,12,13).
"""

from __future__ import annotations

import math
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CRITICAL_N_DIR = PROJECT_ROOT / "subprojects" / "critical_n"


def test_1_1_spe_format_strictly_6col_fixed_width():
    """Verify that SPE.base critical nitrogen lines strictly conform to Fortran 4F6.0."""
    template_spe = PROJECT_ROOT / "data" / "templates" / "genotype" / "TMGRO048.SPE.base"
    greenhouse_spe = CRITICAL_N_DIR / "verification_runs" / "greenhouse" / "cnc" / "TMGRO048.SPE.base"

    for spe_path in [template_spe, greenhouse_spe]:
        assert spe_path.is_file(), f"SPE file missing: {spe_path}"
        lines = spe_path.read_text(encoding="latin-1").splitlines()

        crit_idx = None
        for i, line in enumerate(lines):
            if "!*CRITICAL NITROGEN DILUTION PARAMETERS" in line:
                crit_idx = i
                break
        assert crit_idx is not None, f"!*CRITICAL section missing in {spe_path}"

        header_line = lines[crit_idx + 1]
        data_line = lines[crit_idx + 2]

        assert "@ CNC_A  CNC_B CNC_W0 CNC_NC_INF" in header_line

        # Exact 4F6.0 Fortran slice check
        field1 = data_line[0:6]
        field2 = data_line[6:12]
        field3 = data_line[12:18]
        field4 = data_line[18:24]

        assert float(field1) == pytest.approx(4.85, abs=1e-4), f"field1 '{field1}' != 4.85"
        assert float(field2) == pytest.approx(0.38, abs=1e-4), f"field2 '{field2}' != 0.38"
        assert float(field3) == pytest.approx(1.00, abs=1e-4), f"field3 '{field3}' != 1.00"
        assert float(field4) == pytest.approx(1.70, abs=1e-4), f"field4 '{field4}' != 1.70"


def test_1_1_demand_fortran_reading_assertions():
    """Verify DEMAND_CNC.FOR includes numerical range assertions and fallback warnings."""
    demand_src = CRITICAL_N_DIR / "fortran_patch" / "src_scheme_b" / "DEMAND_CNC.FOR"
    text = demand_src.read_text(encoding="latin-1")

    assert "CNC_A_IN .GE. 2.0 .AND. CNC_A_IN .LE. 8.0" in text
    assert "CNC_B_IN .GE. 0.05 .AND. CNC_B_IN .LE. 1.50" in text
    assert "CNC_W0_IN .GE. 0.05 .AND. CNC_W0_IN .LE. 5.00" in text
    assert "CNC_NC_INF_IN .GE. 0.50 .AND. CNC_NC_INF_IN .LE. 3.50" in text
    assert "CNC_A .LE. CNC_NC_INF" in text
    assert "CALL WARNING(1, ERRKEY, MSG)" in text


def test_1_2_optimization_penalty_safeguard():
    """Verify that stage_r4_setup assigns heavy penalty (999.0) when simulated CNC output is missing."""
    setup_file = CRITICAL_N_DIR / "calibration" / "stage_r4_setup.py"
    text = setup_file.read_text(encoding="utf-8")

    assert "sim_val = 999.0" in text
    assert "sim_val = 0.0" not in text.split("if sim_nni > 0.0:")[1].split("cnc_results.append")[0]


def test_1_3_phenology_extraction_from_evaluate_out(tmp_path):
    """Verify cross_season_evaluator dynamically extracts ADAP from Evaluate.OUT and returns np.nan / missing if absent."""
    from subprojects.critical_n.scripts.cross_season_evaluator import CrossSeasonSandbox

    # Create mock sandbox
    sb = CrossSeasonSandbox(tmp_path, "26SP", CRITICAL_N_DIR / "bin" / "dscsm048_cnc.exe")

    catalog = pd.DataFrame([
        {
            "season_id": "26SP",
            "trno": 1,
            "run": 1,
            "variable": "ADAP",
            "unit": "day",
            "observed": 37.0,
            "obsnme": "ADAP_T1",
        },
        {
            "season_id": "26SP",
            "trno": 2,
            "run": 2,
            "variable": "ADAP",
            "unit": "day",
            "observed": 37.0,
            "obsnme": "ADAP_T2",
        },
    ])

    # Case 1: Evaluate.OUT missing -> should return np.nan and comparison_status 'missing'
    res_missing = sb.extract_observations(catalog)
    assert len(res_missing) == 2
    for r in res_missing.to_dict("records"):
        assert np.isnan(r["simulated"])
        assert r["comparison_status"] == "missing"

    # Case 2: Evaluate.OUT present with specific ADAP values
    eval_text = (
        "*EVALUATION\n"
        "@RUN EXCODE        TN RN CR   EDAPS   EDAPM   ADAPS   ADAPM\n"
        "   1 XXQL2601TM     1  1 TM     -99     -99      39      37\n"
        "   2 XXQL2601TM     2  1 TM     -99     -99      41      37\n"
    )
    (tmp_path / "Evaluate.OUT").write_text(eval_text, encoding="latin-1")

    res_found = sb.extract_observations(catalog)
    assert len(res_found) == 2
    r1 = res_found[res_found["trno"] == 1].iloc[0]
    r2 = res_found[res_found["trno"] == 2].iloc[0]

    assert r1["simulated"] == 39.0
    assert r1["comparison_status"] == "matched"
    assert r2["simulated"] == 41.0
    assert r2["comparison_status"] == "matched"


def test_1_4_seed_nitrogen_accumulation_typo_fixed():
    """Verify that GROW_CNC.FOR accumulates seed nitrogen using PCNSD, not PCNSH."""
    grow_src = CRITICAL_N_DIR / "fortran_patch" / "src_scheme_b" / "GROW_CNC.FOR"
    text = grow_src.read_text(encoding="latin-1")

    assert "NHSDWT = NHSDWT + HSDWT * PCNSD/100." in text
    assert "NHSDWT = NHSDWT + HSDWT * PCNSH/100." not in text


def test_1_5_instantaneous_harvest_flux_synchronization():
    """Verify GROW and CROPGRO share HPODN_FLUX for instantaneous harvest N synchronization."""
    grow_src = CRITICAL_N_DIR / "fortran_patch" / "src_scheme_b" / "GROW_CNC.FOR"
    cropgro_src = CRITICAL_N_DIR / "fortran_patch" / "src_scheme_b" / "CROPGRO_CNC.FOR"

    grow_text = grow_src.read_text(encoding="latin-1")
    cropgro_text = cropgro_src.read_text(encoding="latin-1")

    # In GROW
    assert "HPODN_FLUX = HSDWT * (PCNSD/100.) + HSHELWT * (PCNSH/100.)" in grow_text
    assert "HPODN_FLUX" in grow_text.split("SUBROUTINE GROW(")[1].split("USE ModuleDefs")[0]

    # In CROPGRO
    assert "HPODN = HPODN_FLUX" in cropgro_text
    assert "CHPDTN = CHPDTN + HPODN * 10.0" in cropgro_text
    assert cropgro_text.count("HPODN_FLUX)                                       !Output") == 4


def test_1_6_treatment_number_mapping_25sp():
    """Verify run_cross_season_comparison maps RUN 1..8 to treatments 2,3,4,5,10,11,12,13 for 25SP."""
    from subprojects.critical_n.scripts.run_cross_season_comparison import (
        map_run_to_trno,
        RUN_TO_TRNO_25SP,
    )

    expected_25sp = {
        1: 2,
        2: 3,
        3: 4,
        4: 5,
        5: 10,
        6: 11,
        7: 12,
        8: 13,
    }
    assert RUN_TO_TRNO_25SP == expected_25sp

    for run_idx, expected_trt in expected_25sp.items():
        assert map_run_to_trno("25SP", run_idx) == expected_trt

    # Identity for other seasons
    for run_idx in range(1, 13):
        assert map_run_to_trno("26SP", run_idx) == run_idx
        assert map_run_to_trno("25FA", run_idx) == run_idx
