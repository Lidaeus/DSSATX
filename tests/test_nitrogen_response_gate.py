import pandas as pd
import pytest

from src.reporting.nitrogen_response_gate import mean_n2_n1_minus_n0_gate


def test_gate_uses_mean_of_n2_and_n1_contrasts_and_last_row_per_treatment() -> None:
    harvest = pd.DataFrame(
        [
            # An earlier event must not enter the terminal treatment contrast.
            {"TN": 1, "HNO": 1, "DATE": 25140, "OBS_FRESH_CUM": 10, "SIM_FRESH_CUM": 20},
            {"TN": 1, "HNO": 2, "DATE": 25192, "OBS_FRESH_CUM": 100, "SIM_FRESH_CUM": 110},
            {"TN": 2, "HNO": 2, "DATE": 25192, "OBS_FRESH_CUM": 70, "SIM_FRESH_CUM": 80},
            {"TN": 3, "HNO": 2, "DATE": 25192, "OBS_FRESH_CUM": 40, "SIM_FRESH_CUM": 50},
        ]
    )
    mapping = pd.DataFrame(
        [
            {"season_id": "25SP", "treatment": 1, "water_level": "W1", "nitrogen_level": "N2"},
            {"season_id": "25SP", "treatment": 2, "water_level": "W1", "nitrogen_level": "N1"},
            {"season_id": "25SP", "treatment": 3, "water_level": "W1", "nitrogen_level": "N0"},
        ]
    )
    result = mean_n2_n1_minus_n0_gate(harvest, mapping, "25SP")
    assert result["n_contrasts"] == 2
    assert result["observed_mean"] == pytest.approx(((100 - 40) + (70 - 40)) / 2)
    assert result["simulated_mean"] == pytest.approx(((110 - 50) + (80 - 50)) / 2)
    assert result["direction_pass"] is True
