from pathlib import Path

import pandas as pd

from src.calibration.nitrogen_response import (
    build_observed_water_response_rows,
    write_simulated_water_response,
)


def test_water_response_supports_different_contrast_per_season(tmp_path: Path) -> None:
    mapping = pd.DataFrame(
        [
            ("25SP", 2, "W3", "N3", 1), ("25SP", 5, "W3", "N0", 2),
            ("25SP", 10, "W1", "N3", 3), ("25SP", 13, "W1", "N0", 4),
            ("26SP", 2, "W2", "N3", 5), ("26SP", 11, "W2", "N0", 6),
            ("26SP", 3, "W1", "N3", 7), ("26SP", 12, "W1", "N0", 8),
        ],
        columns=["season_id", "treatment", "water_level", "nitrogen_level", "global_run"],
    )
    values = {1: 150.0, 2: 120.0, 3: 100.0, 4: 90.0, 5: 140.0, 6: 105.0, 7: 110.0, 8: 95.0}
    harvest = pd.DataFrame(
        [
            {"@RUN": run, "TN": int(row.treatment), "HNO": 1,
             "DATE": 25140 if row.season_id == "25SP" else 26140,
             "CHPDTM": values[run], "CHPDTM_SIGMA": 10.0, "season": row.season_id}
            for run, row in enumerate(mapping.itertuples(index=False), start=1)
        ]
    )
    contrasts = {
        "25SP": {"high_water": "W3", "low_water": "W1"},
        "26SP": {"high_water": "W2", "low_water": "W1"},
    }
    observed = build_observed_water_response_rows(
        harvest, mapping, contrast_scale="raw_difference", season_contrasts=contrasts,
        nitrogen_levels=["N0", "N3"],
    )
    assert observed.groupby("season")["water_level"].first().to_dict() == {
        "25SP": "W3", "26SP": "W2"
    }
    assert sorted(observed["WRESPM"].tolist()) == [10.0, 30.0, 30.0, 50.0]

    source = tmp_path / "PestHarvest.OUT"
    source.write_text(
        "\n".join(
            f"RUN {run} TN {row.treatment} @HNO@ 1 DATE "
            f"{25140 if row.season_id == '25SP' else 26140} @CHPDTS@ {values[run]}"
            for run, row in enumerate(mapping.itertuples(index=False), start=1)
        ) + "\n",
        encoding="utf-8",
    )
    target = tmp_path / "PestWResponse.OUT"
    write_simulated_water_response(
        source, target, mapping, contrast_scale="raw_difference", season_contrasts=contrasts,
        nitrogen_levels=["N0", "N3"],
    )
    text = target.read_text(encoding="utf-8")
    assert "RUN 1 TN 2" in text and "RUN 2 TN 5" in text
    assert "RUN 5 TN 2" in text and "RUN 6 TN 11" in text


def test_water_response_can_filter_nitrogen_strata(tmp_path: Path) -> None:
    mapping = pd.DataFrame(
        [
            ("25SP", 2, "W3", "N3", 1), ("25SP", 5, "W3", "N0", 2),
            ("25SP", 10, "W1", "N3", 3), ("25SP", 13, "W1", "N0", 4),
        ],
        columns=["season_id", "treatment", "water_level", "nitrogen_level", "global_run"],
    )
    harvest = pd.DataFrame(
        [
            {"@RUN": run, "TN": row.treatment, "HNO": 1, "DATE": 25140,
             "CHPDTM": value, "CHPDTM_SIGMA": 10.0, "season": "25SP"}
            for run, row, value in zip(
                range(1, 5), mapping.itertuples(index=False), [150.0, 120.0, 100.0, 90.0]
            )
        ]
    )
    observed = build_observed_water_response_rows(
        harvest, mapping, nitrogen_levels=["N0"], contrast_scale="raw_difference"
    )
    assert observed["nitrogen_level"].tolist() == ["N0"]
    assert observed["WRESPM"].tolist() == [30.0]
