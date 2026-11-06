import pandas as pd

from src.reporting.analyze_results import _yyddd_day_difference
from tools.calibration.plot_dynamics import _observation_dap, _yyddd_to_dap_lookup


def test_cross_year_day_difference_is_calendar_safe() -> None:
    assert _yyddd_day_difference(25342, 26010) == 33
    assert _yyddd_day_difference(26006, 26010) == 4


def test_observation_dap_extends_beyond_terminal_output_across_year() -> None:
    daily = pd.DataFrame(
        {
            "YEAR": [2025, 2026, 2026],
            "DOY": [365, 5, 6],
            "DAP": [140, 145, 146],
        }
    )
    lookup = _yyddd_to_dap_lookup(daily)
    assert lookup[26006] == 146
    assert _observation_dap(26010, lookup) == 150
