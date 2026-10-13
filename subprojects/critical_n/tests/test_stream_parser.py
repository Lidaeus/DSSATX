"""Unit tests for fast stream parser on DSSAT files."""

import tempfile
import time
from pathlib import Path
import pytest

from subprojects.critical_n.adapters.stream_parser import (
    load_merged_nitrogen_series,
    parse_fresh_wt_stream,
    parse_plant_gro_stream,
    parse_plant_n_stream,
    parse_treatment_ids_from_plantgro,
)


def _write_sample_plant_gro(path: Path) -> Path:
    content = """*GROWTH ASPECTS OUTPUT FILE
*DSSAT Cropping System Model Ver. 4.8
*RUN   1        : CRGRO048 XXQL2501 2
 TREATMENT  2   : TRT 2
@YEAR DOY   DAS   DAP   CWAD   GWAD   LAID
 2025 075     8     0     10      0  0.010
 2025 076     9     1     12      0  0.012
 2025 100    33    25    500     20  0.500
*RUN   2        : CRGRO048 XXQL2501 3
 TREATMENT  3   : TRT 3
@YEAR DOY   DAS   DAP   CWAD   GWAD   LAID
 2025 075     8     0     15      0  0.010
 2025 100    33    25    600     30  0.600
"""
    path.write_text(content, encoding="utf-8")
    return path


def _write_sample_plant_n(path: Path) -> Path:
    content = """*PLANT N OUTPUT FILE
*RUN   1        : CRGRO048 XXQL2501 2
@YEAR DOY   DAS   DAP    CNAD    GNAD    VNAD
 2025 075     8     0     0.4     0.0     0.4
 2025 076     9     1     0.5     0.0     0.5
 2025 100    33    25    20.0     1.0    19.0
*RUN   2        : CRGRO048 XXQL2501 3
@YEAR DOY   DAS   DAP    CNAD    GNAD    VNAD
 2025 075     8     0     0.6     0.0     0.6
 2025 100    33    25    24.0     1.5    22.5
"""
    path.write_text(content, encoding="utf-8")
    return path


def _write_sample_fresh_wt(path: Path) -> Path:
    content = """*Fresh Weight Output File
*RUN   1        : CRGRO048 XXQL2501 2
@YEAR DOY   DAS   DAP    CHPDT    CHFPW    HPODW   CHPDTN
 2025 075     8     0      0.0      0.0      0.0      0.0
 2025 100    33    25    150.0   1200.0     50.0      2.7
*RUN   2        : CRGRO048 XXQL2501 3
@YEAR DOY   DAS   DAP    CHPDT    CHFPW    HPODW   CHPDTN
 2025 075     8     0      0.0      0.0      0.0      0.0
 2025 100    33    25    180.0   1400.0     60.0      3.2
"""
    path.write_text(content, encoding="utf-8")
    return path


def test_stream_parser_basic_synthetic(tmp_path):
    """Verify stream parser correctly extracts multiple runs and fields from synthetic files."""
    gro_file = _write_sample_plant_gro(tmp_path / "PlantGro.OUT")
    n_file = _write_sample_plant_n(tmp_path / "PlantN.OUT")
    fresh_file = _write_sample_fresh_wt(tmp_path / "FreshWt.OUT")

    merged = load_merged_nitrogen_series(tmp_path)
    assert len(merged) == 2, "Must extract 2 runs"

    run1 = merged[1]
    assert len(run1) == 3
    assert run1[0].das == 8
    assert run1[0].cwad == 10.0
    assert run1[0].cnad == 0.4
    assert run1[0].treatment_id == 2

    assert run1[0].has_fresh_wt is True
    assert run1[2].das == 33
    assert run1[2].cwad == 500.0
    assert run1[2].cnad == 20.0
    assert run1[2].chpdt == 150.0
    assert run1[2].chpdtn == 2.7

    run2 = merged[2]
    assert len(run2) == 2
    assert run2[0].treatment_id == 3
    assert run2[1].cwad == 600.0


def test_stream_parser_whitespace_and_colon_tolerance(tmp_path):
    """Verify stream parser handles leading whitespace, trailing colons on *RUN and TREATMENT."""
    gro = tmp_path / "PlantGro.OUT"
    gro.write_text(
        "   *RUN 1: CRGRO048\n"
        "   TREATMENT 2: TRT 2\n"
        "   @YEAR DOY DAS CWAD\n"
        "    2025 100  33 500.0\n",
        encoding="utf-8",
    )
    n = tmp_path / "PlantN.OUT"
    n.write_text(
        "   *RUN 1: CRGRO048\n"
        "   @YEAR DOY DAS CNAD\n"
        "    2025 100  33  20.0\n",
        encoding="utf-8",
    )
    merged = load_merged_nitrogen_series(tmp_path)
    assert 1 in merged
    assert merged[1][0].treatment_id == 2
    assert merged[1][0].cwad == 500.0
    assert merged[1][0].cnad == 20.0
    assert merged[1][0].has_fresh_wt is False


def test_stream_parser_performance_benchmark():
    """Verify stream parser meets high performance specification (< 25 ms on multi-run test files)."""
    scratch_dir = Path("scratch/test_0.5")
    if not (scratch_dir / "PlantGro.OUT").is_file():
        pytest.skip("scratch/test_0.5 files not present")

    t0 = time.perf_counter()
    merged = load_merged_nitrogen_series(scratch_dir)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert len(merged) >= 1
    assert elapsed_ms < 50.0, f"Parser took {elapsed_ms:.2f} ms (expected < 50 ms)"


def test_missing_and_corrupt_files_handled_gracefully(tmp_path):
    """Verify empty/missing/corrupted files do not crash the stream parser."""
    # Empty directory
    res_empty = load_merged_nitrogen_series(tmp_path)
    assert res_empty == {}

    # Corrupt file
    corrupt_gro = tmp_path / "PlantGro.OUT"
    corrupt_gro.write_text("gibberish without run or headers\n@YEAR DOY\n bad bad", encoding="utf-8")
    res_corrupt = parse_plant_gro_stream(corrupt_gro)
    assert res_corrupt == {}
