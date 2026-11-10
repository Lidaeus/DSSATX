from pathlib import Path

from src.calibration.audit_observations import (
    audit_observation_bundle,
    derive_cumulative_harvest_increments,
    read_dssat_observation_table,
)
from src.reporting.analyze_results import _read_tmt_harvest_obs


ROOT = Path(__file__).resolve().parents[1]


def test_new_observation_files_have_monotone_cumulative_harvest():
    for experiment in ("XXQL2502", "XXQL2601"):
        filet = ROOT / "data" / "user" / "experiments" / experiment / f"{experiment}.TMT"
        frame = read_dssat_observation_table(filet)
        events = derive_cumulative_harvest_increments(frame)
        assert len(events) == (36 if experiment == "XXQL2502" else 48)
        assert (events["derived_hpodw"] >= 0).all()
        assert (events["derived_hfpow"] >= 0).all()


def test_reporting_derives_incremental_harvest_when_only_cumulative_is_recorded():
    filet = ROOT / "data" / "user" / "experiments" / "XXQL2502" / "XXQL2502.TMT"
    observations = _read_tmt_harvest_obs(filet)
    first = observations[1]
    assert [row["OBS_DRY_INC"] for row in first] == [463.0, 415.0, 583.0]
    assert [row["OBS_FRESH_INC"] for row in first] == [6059.0, 5436.0, 6720.0]


def test_xxql2502_observation_values_match_filea_and_repaired_raw_bundle_is_safe():
    report, _ = audit_observation_bundle(
        ROOT / "data" / "user" / "experiments" / "XXQL2502"
    )
    codes = {item["code"] for item in report["findings"]}
    assert "FILEA_FILET_VALUE_MISMATCH" not in codes
    assert "CUMULATIVE_HARVEST_DECREASES" not in codes
    assert "FILEA_DERIVED_DUPLICATES" in codes
    assert "ORGAN_N_WITHOUT_TOTAL_PLANT_N" in codes
    assert "NONLEGUME_SYMBIOSIS_ENABLED" not in codes
    assert "SOIL_PROFILE_MISSING" not in codes
    assert "TRNO_DECLARED_AS_PLOT_NUMBER" not in codes
    assert report["safe_for_direct_formal_use"] is True


def test_xxql2601_flags_no_plant_n_and_filex_event_order_problem():
    report, _ = audit_observation_bundle(
        ROOT / "data" / "user" / "experiments" / "XXQL2601"
    )
    codes = {item["code"] for item in report["findings"]}
    assert "FILEA_FILET_VALUE_MISMATCH" not in codes
    assert "PLANT_N_OBSERVATIONS_UNAVAILABLE" in codes
    assert "WATER_NITROGEN_CELL_DUPLICATED" not in codes
    assert "WATER_NITROGEN_GRID_INCOMPLETE" not in codes
    assert "FILEX_FACTOR_ROWS_NONCONTIGUOUS" in codes
