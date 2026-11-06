from pathlib import Path

import pandas as pd
import pytest

from src.calibration.build_pest import _parse_filex_seedling_params
from src.dssat.run_dssat import update_initial_soil_n_file


def _write_filex(path: Path) -> None:
    path.write_text(
        "*INITIAL CONDITIONS\n"
        "@C   PCR ICDAT  ICRT  ICND  ICRN  ICRE  ICWD ICRES ICREN ICREP ICRIP ICRID ICNAME\n"
        " 12   -99 26069     1     0     1     1   -99   -99   -99   -99   -99   -99 12\n"
        "@C  ICBL  SH2O  SNH4  SNO3\n"
        " 12    20   .21   3.9  38.3\n"
        " 12    40  .298   1.6  31.8\n"
        " 12    60   .30    .5     1\n"
        "  6    TM 26069     1     0     1     1   -99   -99   -99   -99   -99   -99 6\n"
        "@C  ICBL  SH2O  SNH4  SNO3\n"
        "  6    20   .21   3.7  39.1\n"
        "*PLANTING DETAILS\n",
        encoding="utf-8",
    )


def _values(path: Path) -> list[list[float]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) == 5 and fields[0] == "12" and fields[1] in {"20", "40", "60"}:
            rows.append([float(value) for value in fields])
            assert len(line) == 26  # DSSAT 2/6/6/6/6 fixed-width contract
            assert line.startswith("12")  # no extra leading blank for a two-digit treatment
            assert all(line[index] == " " for index in (2, 8, 14, 20))
    return rows


def test_season_initial_n_scale_changes_both_species_and_preserves_layout(tmp_path: Path):
    params = tmp_path / "pest_params.csv"
    pd.DataFrame({"name": ["ICNS_25SP", "ICNS_26SP"], "value": [0.5, 1.2]}).to_csv(params, index=False)

    filex25 = tmp_path / "XXQL2501.TMX"
    _write_filex(filex25)
    update_initial_soil_n_file(str(params), str(filex25))
    rows25 = _values(filex25)
    assert rows25[0][3:] == pytest.approx([1.95, 19.15])
    assert rows25[1][3:] == pytest.approx([0.8, 15.9])
    assert rows25[2][3:] == pytest.approx([0.25, 0.5])
    assert any(line.startswith(" 6") for line in filex25.read_text(encoding="utf-8").splitlines())

    filex26 = tmp_path / "XXQL2601.TMX"
    _write_filex(filex26)
    update_initial_soil_n_file(str(params), str(filex26))
    rows26 = _values(filex26)
    assert rows26[0][3:] == pytest.approx([4.68, 45.96])
    assert rows26[1][3:] == pytest.approx([1.92, 38.16])
    assert rows26[2][3:] == pytest.approx([0.6, 1.2])


def test_initial_n_scale_rejects_mixed_absolute_parameterization(tmp_path: Path):
    params = tmp_path / "pest_params.csv"
    pd.DataFrame(
        {"name": ["ICNS_25SP", "IC_SNH4_XXQL2501_TN12_L01"], "value": [0.5, 2.0]}
    ).to_csv(params, index=False)
    filex = tmp_path / "XXQL2501.TMX"
    _write_filex(filex)
    with pytest.raises(ValueError, match="cannot be combined"):
        update_initial_soil_n_file(str(params), str(filex))


def test_frozen_filex_parser_materializes_initial_n_scales(tmp_path: Path):
    bounds = tmp_path / "bounds.csv"
    pd.DataFrame(
        [
            {"name": "ICNS_25SP", "init": 1.0, "lower": 0.15, "upper": 1.2, "status": "active", "location": "IC"},
            {"name": "ICNS_26SP", "init": 1.0, "lower": 0.15, "upper": 1.2, "status": "active", "location": "IC"},
        ]
    ).to_csv(bounds, index=False)
    params = _parse_filex_seedling_params(bounds)
    assert [row["name"] for row in params] == ["ICNS_25SP", "ICNS_26SP"]
    assert all(row["filex_initial_n_scale"] for row in params)
