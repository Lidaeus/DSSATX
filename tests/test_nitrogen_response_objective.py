from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from src.calibration.nitrogen_response import (
    build_observed_n_response_rows,
    load_n_response_mapping,
    write_simulated_n_response,
)


def _mapping(tmp_path: Path) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    rows = []
    run_rows = []
    for run, (water, nitrogen) in enumerate(
        [
            ("W1", "N0"), ("W1", "N1"), ("W1", "N2"), ("W1", "N3"),
            ("W3", "N0"), ("W3", "N1"), ("W3", "N2"), ("W3", "N3"),
        ],
        1,
    ):
        rows.append(
            {
                "season_id": "S1", "treatment": run,
                "water_level": water, "nitrogen_level": nitrogen,
            }
        )
        run_rows.append(
            {
                "season_id": "S1", "treatment": run,
                "global_run": run, "local_run": run,
            }
        )
    path = tmp_path / "mapping.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return load_n_response_mapping(path, run_rows), run_rows


def test_observed_response_is_log_contrast_with_propagated_sigma(tmp_path: Path) -> None:
    mapping, _ = _mapping(tmp_path)
    harvest = pd.DataFrame(
        [
            {
                "@RUN": run, "TN": run, "HNO": 1, "DATE": 25150,
                "CHPDTM": value, "CHPDTM_SIGMA": 10.0, "season": "S1",
            }
            for run, value in enumerate(
                [100, 120, 150, 130, 200, 240, 260, 250], 1
            )
        ]
    )
    result = build_observed_n_response_rows(
        harvest, mapping, sigma_floor=0.10
    )
    assert len(result) == 6
    row = result.loc[
        (result["water_level"] == "W1")
        & (result["nitrogen_level"] == "N2")
    ].iloc[0]
    assert math.isclose(
        float(row["NRESPM"]), math.log1p(150) - math.log1p(100)
    )
    expected_sigma = math.sqrt(
        (10 / 151) ** 2 + (10 / 101) ** 2 + 0.10**2
    )
    assert math.isclose(float(row["NRESPM_SIGMA"]), expected_sigma)


def test_simulated_response_uses_explicit_raw_to_log_contrast(tmp_path: Path) -> None:
    mapping, _ = _mapping(tmp_path)
    source = tmp_path / "PestHarvest.OUT"
    lines = []
    raw = [100, 120, 150, 130, 200, 240, 260, 250]
    for run, value in enumerate(raw, 1):
        lines.append(
            f"RUN {run} TN {run} HNO 1 DATE 25150 @CHPDTS@ {value:.12g}"
        )
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")
    target = tmp_path / "PestNResponse.OUT"
    write_simulated_n_response(
        source, target, mapping, source_scale="raw", contrast_scale="log_ratio"
    )
    text = target.read_text(encoding="utf-8")
    assert text.count("@NRESPS@") == 6
    n2 = next(line for line in text.splitlines() if line.startswith("RUN 3 "))
    actual = float(n2.split("@NRESPS@")[1])
    assert math.isclose(
        actual, math.log1p(150) - math.log1p(100), abs_tol=1e-10
    )


def test_raw_n2_minus_n0_terminal_is_strictly_keyed_and_ordered(tmp_path: Path) -> None:
    mapping, _ = _mapping(tmp_path)
    harvest_rows = []
    output_lines = []
    for hno, date, offset in [(1, 25150, 0), (2, 25160, 100)]:
        values = [100, 120, 150, 130, 200, 240, 260, 250]
        for run, value in enumerate(values, 1):
            value += offset
            harvest_rows.append(
                {
                    "@RUN": run, "TN": run, "HNO": hno, "DATE": date,
                    "CHPDTM": value, "CHPDTM_SIGMA": 10.0, "season": "S1",
                }
            )
            output_lines.append(
                f"RUN {run} TN {run} HNO {hno} DATE {date} @CHPDTS@ {value}"
            )
    observed = build_observed_n_response_rows(
        pd.DataFrame(harvest_rows), mapping, response_levels=["N2"],
        contrast_scale="raw_difference", harvest_scope="terminal",
        sigma_floor=50.0,
    )
    assert list(zip(observed["@RUN"], observed["HNO"])) == [(3, 2), (7, 2)]
    assert observed["NRESPM"].tolist() == [50.0, 60.0]

    source = tmp_path / "PestHarvest.OUT"
    source.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
    target = tmp_path / "PestNResponse.OUT"
    write_simulated_n_response(
        source, target, mapping, response_levels=["N2"], source_scale="raw",
        contrast_scale="raw_difference", harvest_scope="terminal",
    )
    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("RUN 3 TN 3 @HNO@ 2 DATE 25160")
    assert lines[1].startswith("RUN 7 TN 7 @HNO@ 2 DATE 25160")
    assert [float(line.split("@NRESPS@")[1]) for line in lines] == [50.0, 60.0]


def test_no_excess_n_target_uses_monotone_plateau(tmp_path: Path) -> None:
    mapping, _ = _mapping(tmp_path)
    harvest = pd.DataFrame(
        [
            {
                "@RUN": run, "TN": run, "HNO": 1, "DATE": 25150,
                "CHPDTM": value, "CHPDTM_SIGMA": 10.0, "season": "S1",
            }
            for run, value in enumerate(
                [100, 140, 130, 120, 200, 250, 230, 240], 1
            )
        ]
    )
    result = build_observed_n_response_rows(
        harvest, mapping, response_target="monotone_plateau"
    )
    w1 = result.loc[result["water_level"].eq("W1")].set_index(
        "nitrogen_level"
    )
    expected = math.log1p(140) - math.log1p(100)
    assert math.isclose(float(w1.loc["N1", "NRESPM"]), expected)
    assert math.isclose(float(w1.loc["N2", "NRESPM"]), expected)
    assert math.isclose(float(w1.loc["N3", "NRESPM"]), expected)
    assert w1.loc["N3", "target_source_level"] == "N1"
