"""Scientific validation tests for immutable frozen parameter bounds."""

from pathlib import Path

import pytest

from collections import Counter

from src.common.param_registry import PHYSICAL_BOUNDS, assert_valid_frozen_bounds, validate_frozen_bounds


def _write_bounds(path: Path, rows: list[str]) -> Path:
    path.write_text(
        "name,init,lower,upper,status,pargp,location,file,cultivar,ecotype,mode\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )
    return path


def test_valid_minimal_frozen_bounds(tmp_path):
    path = _write_bounds(
        tmp_path / "valid.csv",
        [
            "EM-FL,25,20,30,active,CUL_PheHrv,CUL,TMGRO048.CUL.base,TM0008,TM0001,both",
            "FL-VS,100,100,100,fixed,ECO_Pheno,ECO,TMGRO048.ECO.base,TM0008,TM0001,both",
            "XFINT,0.3,0.2,0.4,active,ECO_Pheno,ECO,TMGRO048.ECO.base,TM0008,TM0001,both",
        ],
    )
    assert not [issue for issue in validate_frozen_bounds(str(path)) if issue.severity == "error"]
    assert_valid_frozen_bounds(str(path))


def test_invalid_ranges_are_rejected_not_repaired(tmp_path):
    path = _write_bounds(
        tmp_path / "invalid.csv",
        ["SDPDV,5,8,2,active,CUL_PheHrv,CUL,TMGRO048.CUL.base,TM0008,TM0001,both"],
    )
    codes = {issue.code for issue in validate_frozen_bounds(str(path))}
    assert {"REVERSED_BOUNDS", "INIT_OUTSIDE_BOUNDS"}.issubset(codes)
    with pytest.raises(ValueError, match="validation failed"):
        assert_valid_frozen_bounds(str(path))


def test_temperature_ranges_must_guarantee_order(tmp_path):
    path = _write_bounds(
        tmp_path / "temperature.csv",
        [
            "TB1,10,8,12,active,SPE_Temp,SPE,TMGRO048.SPE.base,TM0008,TM0001,both",
            "TO11,24,11,28,active,SPE_Temp,SPE,TMGRO048.SPE.base,TM0008,TM0001,both",
            "TO21,30,27,33,active,SPE_Temp,SPE,TMGRO048.SPE.base,TM0008,TM0001,both",
            "TM1,38,34,40,active,SPE_Temp,SPE,TMGRO048.SPE.base,TM0008,TM0001,both",
        ],
    )
    assert "TEMP_RANGE_ORDER" in {issue.code for issue in validate_frozen_bounds(str(path))}


def test_current_v14_is_a_preserved_failure_fixture():
    path = Path("data/parameter_registry/bounds_frozen/eggplant/eggplant_v14_20260405.csv")
    issues = validate_frozen_bounds(str(path))
    errors = [issue for issue in issues if issue.severity == "error"]
    warnings = [issue for issue in issues if issue.severity == "warning"]
    assert Counter(issue.code for issue in errors) == Counter(
        {
            "REVERSED_BOUNDS": 5,
            "INIT_OUTSIDE_BOUNDS": 8,
            "FIXED_NOT_CONSTANT": 2,
            "TEMP_RANGE_ORDER": 3,
            "SOIL_WATER_RANGE_ORDER": 2,
        }
    )
    assert Counter(issue.code for issue in warnings) == Counter({"NUISANCE_PARAMETER_ACTIVE": 44})


def test_physical_safety_envelopes_include_shipped_dssat_baselines():
    shipped_baselines = {
        "WTPSD": 0.004,
        "SD-PM": 400.0,
        "FL-LF": 400.0,
        "SDPDV": 111.4,
        "PARMAX": 41.0,
        "PHTMAX": 61.0,
        "FINREF": 220.0,
        "EVMODC": 0.0,
    }
    for name, value in shipped_baselines.items():
        lower, upper = PHYSICAL_BOUNDS[name]
        assert lower <= value <= upper, f"{name} baseline must remain inside its safety envelope"


def test_empty_active_zero_width_and_blank_group_are_rejected(tmp_path):
    empty = _write_bounds(tmp_path / "empty.csv", [])
    assert {issue.code for issue in validate_frozen_bounds(str(empty))} == {"EMPTY_REGISTRY"}

    invalid = _write_bounds(
        tmp_path / "invalid_contract.csv",
        ["EM-FL,25,25,25,active,,CUL,TMGRO048.CUL.base,TM0008,TM0001,both"],
    )
    codes = {issue.code for issue in validate_frozen_bounds(str(invalid))}
    assert {"ACTIVE_ZERO_WIDTH", "EMPTY_PARAMETER_GROUP"}.issubset(codes)
