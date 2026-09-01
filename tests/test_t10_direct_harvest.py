from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.calibration.run_multiseason import _prepare_t10_input_bundle
from src.common.experiment_inputs import filex_harvest_dates, filex_observed_harvest_dates
from src.dssat import run_dssat
from src.reporting import analyze_results


def test_bounded_nearest_handles_yyddd_year_boundary_and_later_tie() -> None:
    value, selected = run_dssat._bounded_nearest_within_window(
        {25364: 1.0, 26001: 2.0}, 25365
    )
    assert (value, selected) == (2.0, 26001)


def test_t10_writer_keeps_raw_values_until_shared_transform(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(run_dssat, "_parse_batch_entries", lambda _: [{"run": 1, "tn": 2, "filex": "X.TMX"}])
    monkeypatch.setattr(run_dssat, "_read_tmt_harvest_events", lambda _: {2: [{"hno": 1, "date": 25140}]})
    monkeypatch.setattr(run_dssat, "_read_freshwt_var_by_run", lambda _, variable: {1: {25140: 100.0 if variable == "CHFPW" else 10.0}})
    target = tmp_path / "PestHarvest.OUT"
    run_dssat._write_pest_harvest_from_tmt_and_freshwt("batch", "fresh", str(target), tmt_path="events")
    text = target.read_text(encoding="utf-8")
    assert "@CHFPWS@ 100.000" in text
    assert "@HFPOWS@ 100.000" in text
    assert "@CHPDTS@ 10.000" in text
    assert "@HPODWS@ 10.000" in text
    assert (tmp_path / "PestHarvest.audit.csv").is_file()


def test_t10_writer_reads_cumulative_harvest_on_observation_date(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(run_dssat, "_parse_batch_entries", lambda _: [{"run": 1, "tn": 2, "filex": "X.TMX"}])
    monkeypatch.setattr(run_dssat, "_read_tmt_harvest_events", lambda _: {2: [{"hno": 1, "date": 25325}]})

    def fake_freshwt(_, variable: str):
        return {1: {25325: 100.0 if variable == "CHFPW" else 10.0}}

    monkeypatch.setattr(run_dssat, "_read_freshwt_var_by_run", fake_freshwt)
    target = tmp_path / "PestHarvest.OUT"
    run_dssat._write_pest_harvest_from_tmt_and_freshwt("batch", "fresh", str(target), tmt_path="events")
    text = target.read_text(encoding="utf-8")
    assert "@CHFPWS@ 100.000" in text
    assert "@CHPDTS@ 10.000" in text
    assert "@HPODWS@ 10.000" in text
    audit = (tmp_path / "PestHarvest.audit.csv").read_text(encoding="utf-8")
    assert "read_reference_date" in audit
    assert "25325,25325,25325,25325" in audit


def test_t10_writer_derives_fresh_event_increments(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(run_dssat, "_parse_batch_entries", lambda _: [{"run": 1, "tn": 2, "filex": "X.TMX"}])
    monkeypatch.setattr(run_dssat, "_read_tmt_harvest_events", lambda _: {2: [
        {"hno": 1, "date": 25140}, {"hno": 2, "date": 25146}
    ]})

    def fake_freshwt(_, variable: str):
        if variable == "CHFPW":
            return {1: {25140: 100.0, 25146: 260.0}}
        return {1: {25140: 10.0, 25146: 25.0}}

    monkeypatch.setattr(run_dssat, "_read_freshwt_var_by_run", fake_freshwt)
    target = tmp_path / "PestHarvest.OUT"
    run_dssat._write_pest_harvest_from_tmt_and_freshwt(
        "batch", "fresh", str(target), tmt_path="events"
    )
    text = target.read_text(encoding="utf-8")
    assert "DATE 25140 @CHFPWS@ 100.000 @HFPOWS@ 100.000" in text
    assert "DATE 25146 @CHFPWS@ 260.000 @HFPOWS@ 160.000" in text


def test_virtual_filex_harvest_does_not_replace_last_observed_yield(tmp_path: Path, monkeypatch) -> None:
    """A 25194 virtual event may extend state output but is not a yield target."""
    monkeypatch.setattr(
        analyze_results,
        "_parse_batch_entries",
        lambda _: [{"run": 1, "tn": 2, "filex": str(tmp_path / "XXQL2501.TMX")}],
    )
    monkeypatch.setattr(
        analyze_results,
        "_read_tmt_harvest_obs",
        lambda _: {2: [
            {"HNO": 1, "DATE": 25140, "OBS_DRY_INC": 10.0, "OBS_DRY_CUM": 10.0,
             "OBS_FRESH_INC": 100.0, "OBS_FRESH_CUM": 100.0},
            {"HNO": 2, "DATE": 25192, "OBS_DRY_INC": 20.0, "OBS_DRY_CUM": 30.0,
             "OBS_FRESH_INC": 200.0, "OBS_FRESH_CUM": 300.0},
        ]},
    )

    def fake_freshwt(_, variable: str):
        if variable == "CHFPW":
            return {1: {25140: 100.0, 25192: 300.0, 25194: 999.0}}
        return {1: {25140: 10.0, 25192: 30.0, 25194: 99.0}}

    monkeypatch.setattr(analyze_results, "_read_freshwt_var_by_run", fake_freshwt)
    monkeypatch.setattr(analyze_results, "_pick_latest_by_mtime", lambda paths: str(tmp_path / "FreshWt.OUT"))
    out = analyze_results.deterministic_harvest_compare(
        "virtual_contract", "batch", run_dir=str(tmp_path)
    )
    frame = pd.read_csv(out)
    last = frame.iloc[-1]
    assert int(last["DATE"]) == 25192
    assert float(last["SIM_FRESH_CUM"]) == 300.0
    assert float(last["SIM_DRY_CUM"]) == 30.0


def test_virtual_harvest_extends_filex_but_not_observation_cutoff(tmp_path: Path) -> None:
    filex = tmp_path / "XXQL2501.TMX"
    filex.write_text(
        "*HARVEST DETAILS\n"
        "@H HDATE HSTG HCOM HSIZE HPC HBPC HNAME\n"
        " 5 25192 GS000 -99 -99 -99 -99 byproduct\n"
        " 5 25194 GS000 -99 -99 -99 -99 virtual-state-output\n"
        "*SIMULATION CONTROLS\n",
        encoding="utf-8",
    )
    assert filex_harvest_dates(filex) == [25192, 25194]
    assert filex_observed_harvest_dates(filex) == [25192]


def test_t10_virtual_harvest_is_local_and_preserves_authoritative_filex(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    original = """*EXP.DETAILS\n*HARVEST DETAILS\n@H HDATE HSTG HCOM HSIZE HPC HBPC HNAME\n 2 25140 GS000 H A -99 -99 old\n*SIMULATION CONTROLS\n"""
    (source / "X.TMX").write_text(original, encoding="utf-8")
    (source / "X.TMT").write_text(
        "*EXP.DATA (T)\n@TRNO DATE CHFPW CHPDT\n 2 25140 100 10\n 2 25146 200 20\n",
        encoding="utf-8",
    )
    target = _prepare_t10_input_bundle(source, tmp_path / "local", (2,), "25SP")
    local = (target / "X.TMX").read_text(encoding="utf-8")
    # FileX is user-maintained authority: the scheduler must not shift or
    # replace its harvest events.  Date reconciliation belongs to the output
    # reader's exact-date audit.
    assert " 2 25140" in local
    assert " 2 25146" not in local
    audit = (target / "harvest_observation_audit.csv").read_text(encoding="utf-8")
    assert "observed_date" in audit
    assert (source / "X.TMX").read_text(encoding="utf-8") == original


def test_process_terminal_tokens_follow_each_variables_last_observation(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        run_dssat, "_parse_batch_entries",
        lambda _: [{"run": 1, "tn": 2, "filex": "X.TMX"}],
    )
    monkeypatch.setattr(
        run_dssat, "_read_tmt_process_points",
        lambda _: {2: [
            {"date": 25100, "laid": 1.0, "lwad": 10.0, "swad": 20.0},
            {"date": 25110, "laid": 2.0, "lwad": 15.0, "swad": 25.0},
            {"date": 25120, "laid": -99.0, "lwad": 18.0, "swad": 28.0},
        ]},
    )
    monkeypatch.setattr(
        run_dssat, "_read_plantgro_vars_by_run",
        lambda *_: {1: {
            25100: {"L#SD": 1, "LAID": 1.1, "LWAD": 11, "SWAD": 21, "CHTD": 1},
            25110: {"L#SD": 2, "LAID": 2.2, "LWAD": 16, "SWAD": 26, "CHTD": 2},
            25120: {"L#SD": 3, "LAID": 3.3, "LWAD": 19, "SWAD": 29, "CHTD": 3},
        }},
    )
    target = tmp_path / "PestTmtGrow.OUT"
    run_dssat._write_pest_tmtgrow_from_tmt_and_plantgro(
        "batch", "PlantGro.OUT", str(target), tmt_path="X.TMT"
    )
    lines = target.read_text(encoding="utf-8").splitlines()
    assert "DATE 25110" in lines[1] and "@LAIETS@ 2.200" in lines[1]
    assert "DATE 25120" in lines[2] and "@LAIETS@ -99.000" in lines[2]
    assert "DATE 25120" in lines[2] and "@LWETS@ 19.000" in lines[2]


def test_terminal_lai_never_falls_back_to_previous_simulation_date(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        run_dssat, "_parse_batch_entries",
        lambda _: [{"run": 1, "tn": 2, "filex": "X.TMX"}],
    )
    monkeypatch.setattr(
        run_dssat, "_read_tmt_process_points",
        lambda _: {2: [{"date": 25110, "laid": 2.0, "lwad": 15.0, "swad": 25.0}]},
    )
    monkeypatch.setattr(
        run_dssat, "_read_plantgro_vars_by_run",
        lambda *_: {1: {
            25109: {"L#SD": 2, "LAID": 9.9, "LWAD": 16, "SWAD": 26, "CHTD": 2},
        }},
    )
    target = tmp_path / "PestTmtGrow.OUT"
    run_dssat._write_pest_tmtgrow_from_tmt_and_plantgro(
        "batch", "PlantGro.OUT", str(target), tmt_path="X.TMT"
    )
    text = target.read_text(encoding="utf-8")
    assert "DATE 25110" in text
    assert "@LAIETS@ -99.000" in text
    assert "@LAIETS@ 9.900" not in text
