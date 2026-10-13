"""Unit tests for PestCNC.OUT exporter and rigid layout invariants."""

from pathlib import Path
import pytest

from subprojects.critical_n.adapters.pest_cnc_exporter import (
    HEADER_COLUMNS,
    HEADER_TITLE,
    export_cnc_dataframe,
    export_pest_cnc,
    format_pest_cnc_line,
)


def test_format_pest_cnc_line_exact_widths():
    """Verify exact 64-character fixed-width string layout."""
    line = format_pest_cnc_line(
        run_id=1,
        trt_id=2,
        year=2025,
        doy=120,
        das=45,
        w_t=1.234,
        n_act=4.567,
        nc_crit=3.890,
        nni_val=1.174,
    )
    assert len(HEADER_COLUMNS.strip()) == 64
    assert len(line) == 65  # 64 chars + newline
    assert line[0:5] == "    1"
    assert line[5:9] == "   2"
    assert line[9:14] == " 2025"
    assert line[14:19] == "  120"
    assert line[19:24] == "   45"
    assert line[24:34] == "     1.234"
    assert line[34:44] == "     4.567"
    assert line[44:54] == "     3.890"
    assert line[54:64] == "     1.174"

    # NaN input produces rigid sentinel -99.000 instead of crashing or writing 'nan'
    nan_line = format_pest_cnc_line(1, 1, 2025, 100, 30, float("nan"), float("nan"), float("nan"), float("nan"))
    assert len(nan_line) == 65
    assert nan_line[54:64] == "   -99.000"

    # Line with explicit r_tol: exactly 74 chars + newline = 75 chars
    rtol_line = format_pest_cnc_line(1, 2, 2025, 120, 45, 1.234, 4.567, 3.890, 1.174, r_tol=0.0)
    assert len(rtol_line) == 75
    assert rtol_line[64:74] == "     0.000"


def test_export_pest_cnc_line_count_invariance(tmp_path):
    """Verify rigid line count preservation: emergence steps retain sentinel rows."""
    # Write synthetic inputs
    gro = tmp_path / "PlantGro.OUT"
    gro.write_text(
        "*RUN 1\n TREATMENT 1\n@YEAR DOY DAS CWAD\n"
        " 2025 075  8  10.0\n"   # pre-emergence W < 0.05
        " 2025 076  9  20.0\n"   # pre-emergence W < 0.05
        " 2025 100 33 500.0\n",  # post-emergence
        encoding="utf-8",
    )
    n = tmp_path / "PlantN.OUT"
    n.write_text(
        "*RUN 1\n@YEAR DOY DAS CNAD\n"
        " 2025 075  8  0.4\n"
        " 2025 076  9  0.8\n"
        " 2025 100 33 20.0\n",
        encoding="utf-8",
    )

    out_file = export_pest_cnc(tmp_path)
    lines = out_file.read_text(encoding="utf-8").splitlines()

    # 2 header lines + 3 data lines = 5 lines exactly
    assert len(lines) == 5
    assert lines[0] == HEADER_TITLE.strip()
    assert lines[1] == HEADER_COLUMNS.strip()

    # Line 3 (DAS 8): Sentinel values -99.000 preserved, not dropped!
    row1 = lines[2]
    assert "-99.000" in row1
    assert row1[54:64].strip() == "-99.000"

    # Line 5 (DAS 33): Valid NNI calculated
    row3 = lines[4]
    nni_val = float(row3[54:64])
    assert nni_val > 0.0

    # Also test include_r_tol=True
    out_rtol_file = export_pest_cnc(tmp_path, out_file=tmp_path / "PestCNC_rtol.OUT", include_r_tol=True, treatment_n_levels={1: "N3"})
    rtol_lines = out_rtol_file.read_text(encoding="utf-8").splitlines()
    assert len(rtol_lines) == 5
    assert "R_TOL" in rtol_lines[1]
    # Post-emergence line length is 74 chars
    assert len(rtol_lines[4]) == 74


def test_export_cnc_dataframe_columns(tmp_path):
    """Verify DataFrame export schema and data types."""
    gro = tmp_path / "PlantGro.OUT"
    gro.write_text(
        "*RUN 1\n TREATMENT 2\n@YEAR DOY DAS CWAD\n 2025 100 33 1000.0\n",
        encoding="utf-8",
    )
    n = tmp_path / "PlantN.OUT"
    n.write_text(
        "*RUN 1\n@YEAR DOY DAS CNAD\n 2025 100 33 40.0\n",
        encoding="utf-8",
    )
    df = export_cnc_dataframe(tmp_path)
    assert len(df) == 1
    assert set(df.columns).issuperset({
        "run_id", "treatment_id", "das", "cwad", "chpdtn", "w_eff", "n_act_cum", "nc_crit", "nni", "is_valid"
    })
    assert df["w_eff"].iloc[0] == 1.0
    assert df["chpdtn"].iloc[0] == 0.0
    assert bool(df["is_valid"].iloc[0]) is True
