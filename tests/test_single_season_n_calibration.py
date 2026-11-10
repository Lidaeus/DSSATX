"""Contracts for the formal concentration adapter and staged PEST interface."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu
import pytest

from src.calibration import single_season_n as model
from tools.calibration import launch_formal_26sp_n012_20261011 as launch

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/runs/eggplant_26sp_n012_formal_20261011"
WORK = ROOT / "workspace/runs/eggplant_26sp_n012_formal_20261011/preflight/baseline/_model"


def data():
    design = json.loads((CONFIG / "design.json").read_text(encoding="utf-8"))
    bounds = pd.read_csv(launch.BOUNDS).fillna("")
    obs = pd.read_csv(CONFIG / "calibration_observations.csv").fillna("")
    return design, bounds, obs


def test_native_treatment_identity_does_not_use_batch_position():
    native = model.read_native(WORK / "PlantN.OUT")
    assert set(native.index.get_level_values("trno")) == set(range(4, 13))
    assert native.loc[(4, "2026-06-03"), "run"] == 1
    assert native.loc[(12, "2026-06-03"), "run"] == 9


def test_all_objectives_exact_date_units_and_mature_fruit_phase():
    _, _, obs = data()
    result = model.extract_observations(WORK, obs)
    assert len(result) == 423 and np.isfinite(result.simulated).all()
    native_n = model.read_native(WORK / "PlantN.OUT")
    native_f = model.read_native(WORK / "FreshWt.OUT")
    native_s = model.read_native(WORK / "SoilWat.OUT")
    for r in result.itertuples():
        key = (r.trno, r.date)
        if r.variable == "LEAF_N_PCT":
            assert r.simulated == native_n.loc[key, "LN%D"]
        elif r.variable == "STEM_N_PCT":
            assert r.simulated == native_n.loc[key, "SN%D"]
        elif r.variable == "FRUIT_N_PCT":
            assert r.date_shift == 0 and r.bulk_harvest_dry == 0
            assert r.mature_seed_dm + r.mature_shell_dm > 0
            assert r.simulated == pytest.approx((r.seed_n_pct*r.mature_seed_dm + r.shell_n_pct*r.mature_shell_dm)/
                                               (r.mature_seed_dm+r.mature_shell_dm))
        elif r.variable == "HPODW":
            assert r.simulated == native_f.loc[key, "HPODW"]
            previous = (pd.Timestamp(r.date) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            assert r.simulated == pytest.approx(native_f.loc[key, "CHPDT"] - native_f.loc[(r.trno, previous), "CHPDT"], abs=.11)
        elif r.variable == "VWC":
            weights = [part.split(":") for part in r.dssat_layer_weights.split(";")]
            expected = sum(native_s.loc[key, f"SW{int(i)+1}D"] * float(w) for i, w in weights)
            assert r.simulated == pytest.approx(expected)


def test_missing_actual_date_fails_without_date_substitution():
    _, _, obs = data()
    wrong = obs.iloc[:1].copy()
    wrong["date"] = "2026-01-01"
    with pytest.raises(KeyError):
        model.extract_observations(WORK, wrong)


@pytest.mark.parametrize("values", [(4, 2, 0, 0), (4, -99, 10, 30), (4, 2, np.nan, 30)])
def test_invalid_fruit_pool_cannot_drop_or_fallback(values):
    with pytest.raises(ValueError):
        model.mature_fruit_n_percent(*values)


def test_fixed_and_domain_parameters_are_enforced():
    _, bounds, _ = data()
    values = dict(zip(bounds.name, bounds.init))
    assert all(v == pytest.approx(values[k]) for k,v in model.validate_parameters(values,bounds).items())
    for name, invalid in [("FL-VS", 101), ("PROSHI", .1), ("LNREF", np.nan)]:
        altered = {**values, name: invalid}
        with pytest.raises(ValueError):
            model.validate_parameters(altered, bounds)
    with pytest.raises(ValueError):
        model.validate_parameters({**values, "ICNS_26SP": 1}, bounds)


def test_csv_pst_rounding_ties_canonicalize_to_identical_values():
    _, bounds, _ = data()
    values = dict(zip(bounds.name,bounds.init))
    first = model.validate_parameters({**values,'PROSHI': .17049999999999998},bounds)
    second = model.validate_parameters({**values,'PROSHI': .1705},bounds)
    assert first == second


def test_actual_fields_independently_match_all_candidate_parameters():
    _, bounds, _ = data()
    records = model.audit_injection(WORK, dict(zip(bounds.name,bounds.init)), bounds[bounds.status.eq('active')].name)
    assert len(records) == 53
    assert all(abs(r['injected']-r['requested']) <= r['printed_resolution']/2+1e-9 for r in records)


def test_validation_missing_date_is_reported_without_repair():
    _, _, obs = data()
    wrong = obs.iloc[:1].copy()
    wrong['date'] = '2026-01-01'
    result = model.extract_evaluation_observations(WORK, wrong)
    assert result.comparison_status.tolist() == ['model_unmatched']
    assert result.simulated.isna().all()
    assert result.date.iloc[0] == '2026-01-01'


def test_pe_template_instruction_and_no_validation_weights(tmp_path, monkeypatch):
    design, bounds, obs = data()
    monkeypatch.setattr(launch, "RUN", tmp_path)
    monkeypatch.setattr(launch.model, "load_design", lambda *a, **k: (design, bounds, obs))
    stage = design["stages"][0]
    values = dict(zip(bounds.name, bounds.init))
    work = launch.build_stage(stage, values)
    pst = pyemu.Pst(str(work / (stage["stage_id"] + ".pst")))
    assert pst.npar_adj == len(stage["active_parameters"])
    assert pst.nobs == 423 and pst.nnz_obs == 144
    assert len(pd.read_csv(work / "initial_ensemble.csv", index_col=0)) == 200
    pyemu.pst_utils.write_input_files(pst, pst_path=str(work))
    injected = model.runner._read_param_dict(work / "parameters.csv")
    assert set(injected) == set(values)
    assert all(injected[k] == pytest.approx(v) for k, v in values.items())
    expected = model.extract_observations(WORK, obs)
    (work / "FormalObjectives.OUT").write_text("".join(f"{r.obsnme} {r.simulated:.12g}\n" for r in expected.itertuples()))
    instruction = pyemu.pst_utils.InstructionFile(str(work / "objectives.ins"), pst=pst)
    parsed = instruction.read_output_file(str(work / "FormalObjectives.OUT"))
    assert np.allclose(parsed.reindex(obs.obsnme).obsval, expected.simulated)
    assert pst.pestpp_options.get("ies_no_noise") in (True, "True", "true")


def test_stage_selection_uses_complete_objective_not_stage_phi(tmp_path, monkeypatch):
    design, bounds, obs = data()
    monkeypatch.setattr(launch.model, "load_design", lambda *a, **k: (design, bounds, obs))
    output = pd.DataFrame([obs.observed.to_numpy(), obs.observed.to_numpy()+1], index=["better", "worse"], columns=obs.obsnme)
    output.to_csv(tmp_path / "S1_canopy.0.obs.csv")
    parameters = pd.DataFrame([dict(zip(bounds.name.str.lower(), bounds.init))]*2, index=output.index)
    parameters.to_csv(tmp_path / "S1_canopy.0.par.csv")
    chosen, report = launch.select_stage(tmp_path, {"stage_id": "S1_canopy"}, 1.)
    assert report["realization"] == "better" and report["selected_phi"] == 0
    assert report["validation_used"] is False and not report["retain_anchor"]
    assert chosen == dict(zip(bounds.name, bounds.init))


def test_feasibility_rejects_undefined_pool_without_using_fit_or_changing_fixed_values(tmp_path, monkeypatch):
    _, bounds, _ = data()
    initial = pd.Series(dict(zip(bounds.name.str.lower(), bounds.init)))
    candidate = initial.copy()
    candidate['em-fl'] = bounds.set_index('name').loc['EM-FL','upper']
    calls = []

    def evaluation(design, params, work):
        values = pd.read_csv(params).set_index('name').value
        calls.append(values)
        if len(calls) == 1:
            raise ValueError('No mature fruit at the exact N sampling date; treatment=9, date=2026-06-03')
        return pd.DataFrame({'simulated': np.full(423, 1000000.)})  # Poor fit is still feasible.

    monkeypatch.setattr(model, 'evaluate', evaluation)
    name, values, report = launch._screen_member('real_018', candidate, initial, list(initial.index),
        {'em-fl'}, bounds, np.random.default_rng(20261011), 8., tmp_path)
    assert name == 'real_018' and report['passed'] and report['attempts'] == 2
    assert len(report['rejections']) == 1 and report['objective_count'] == 423
    assert values.drop('em-fl').equals(initial.drop('em-fl'))
    row = bounds.set_index('name').loc['EM-FL']
    assert row.lower <= values['em-fl'] <= row.upper

    def broken(*args):
        raise ValueError('Parameter injection mismatch')

    monkeypatch.setattr(model, 'evaluate', broken)
    with pytest.raises(ValueError, match='injection mismatch'):
        launch._screen_member('real_018', candidate, initial, list(initial.index), {'em-fl'},
            bounds, np.random.default_rng(20261011), 8., tmp_path)


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows sharing-violation regression')
def test_dssat_binary_copy_with_real_windows_write_lock(tmp_path):
    import ctypes
    import threading
    from ctypes import wintypes
    source, destination = tmp_path/'binary_source.exe', tmp_path/'DSCSM048.EXE'
    source.write_bytes(b'current DSSAT binary')
    destination.write_bytes(source.read_bytes())
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(destination), 0x80000000, 1, None, 3, 0, None)
    assert handle != ctypes.c_void_p(-1).value
    try:
        with pytest.raises(PermissionError):
            model.runner.shutil.copy2(source, destination)
        model.runner._copy(source, destination)  # Identical content needs no overwrite.
        source.write_bytes(b'new DSSAT binary')
        timer = threading.Timer(.25, lambda: kernel.CloseHandle(handle))
        timer.start()
        model.runner._copy(source, destination)  # A changed binary waits, then copies.
        timer.join()
        handle = None
        assert destination.read_bytes() == source.read_bytes()
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)


def test_input_copy_does_not_hide_permanent_permission_error(tmp_path, monkeypatch):
    source = tmp_path/'SOIL.SOL'
    source.write_text('soil')
    calls = []
    def denied(*args):
        calls.append(1)
        error = PermissionError('Access denied')
        error.winerror = 5
        raise error
    monkeypatch.setattr(model.runner.shutil, 'copy2', denied)
    with pytest.raises(PermissionError):
        model.runner._copy(source, tmp_path/'copy.SOL')
    assert len(calls) == 1
