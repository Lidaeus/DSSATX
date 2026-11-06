"""Calibrate the archived 2026 spring bundle and evaluate archived 2025 spring."""
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd
import pyemu
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.common.input_manifest import verify_manifest_integrity
from tools.calibration import restart_dual_morris98_trial_c31_initial_20261106 as c31

trial = c31.trial
native = trial.native
ID = "eggplant_26sp_cal25sp_val_cold_c31pst_noadat_80x4_20261106"
RUN = ROOT / "workspace/runs" / ID
ARCHIVE = Path("D:/Tomato_Cal_Cold_Storage/bundle_retirement_20261105/calibration")
SOURCE = ROOT / "workspace/runs/eggplant_26sp_cal25sp_val_dual_morris98_80x4_20261105"
POLICY = ROOT / "workspace/runs/eggplant_26sp_cal25sp_val_dual_morris98_80x4_c31initial_noadat_20261106"
HISTORY = ROOT / "workspace/runs/eggplant_26sp_cal25sp_val_sa98_joint40_100x5_20261031"


def representable_edge(value, rounding):
    """Round into the interval on the native six-column input grid."""
    for places in range(5, -1, -1):
        candidate = float(Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=rounding))
        field = trial.genotype_field(candidate)
        if field.startswith(" ") and float(field) == candidate:
            return candidate
    raise ValueError(f"Cannot represent {value}")


def freeze(parent):
    pst_path = c31.C31 / f"{c31.C31.name}.pst"
    history = pyemu.Pst(str(pst_path)).parameter_data
    base = pd.read_csv(parent["frozen_bounds"])
    original = trial.read(SOURCE / "design.json")
    assert set(base.loc[base.status.eq("active"), "native_name"]) == set(original["active_parameters"])
    audit = []
    for i, row in base[base.status.eq("active")].iterrows():
        lo, hi = row.lower, row.upper
        c = history.loc[row.pest_name] if row.pest_name in history.index else None
        basis = "previous_interval_missing_or_fixed_in_C31"
        if c is not None and c.partrans not in {"fixed", "tied"} and c.parlbnd < c.parubnd:
            lower = representable_edge(max(lo, c.parlbnd), ROUND_CEILING)
            upper = representable_edge(min(hi, c.parubnd), ROUND_FLOOR)
            if lower < upper:
                lo, hi, basis = lower, upper, "C31_actual_control_interval"
            else:
                basis = "previous_interval_incompatible_C31_interval"
        init = row.init if lo <= row.init <= hi else (lo + hi) / 2
        base.loc[i, ["init", "lower", "upper", "basis"]] = [init, lo, hi, basis]
        audit.append(dict(parameter=row.native_name, previous_lower=row.lower, previous_upper=row.upper,
            c31_status=c.partrans if c is not None else "missing",
            c31_lower=c.parlbnd if c is not None else None, c31_upper=c.parubnd if c is not None else None,
            lower=lo, upper=hi, init=init, basis=basis))
    pd.DataFrame(audit).to_csv(RUN / "range_source_audit.csv", index=False)
    proposal = RUN / "approved_trial_bounds.csv"
    base.to_csv(proposal, index=False)
    subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tools/freeze_bounds.py"),
        "--proposal", str(proposal), "--crop", "eggplant", "--bounds-id", ID,
        "--notes", "Archived spring inputs; overlap with C31 control-file ranges and native precision."],
        cwd=ROOT, check=True)
    frozen = Path(parent["frozen_bounds"]).with_name(ID + ".csv")
    return frozen, pst_path


def prepare():
    parent = trial.read(POLICY / "design.json")
    assert trial.read(POLICY / "sealed_design.json")["sha256"] == native.sha(POLICY / "design.json")
    assert trial.read(POLICY / "pipeline_status.json")["status"] == "completed"
    assert native.sha(Path(parent["frozen_bounds"])) == parent["source_hashes"][parent["frozen_bounds"]]
    for filename in ("calibration_observations.csv", "objective_policy.csv"):
        p = POLICY / filename
        assert native.sha(p) == parent["source_hashes"][str(p)]
    old_design_path = HISTORY / "source_snapshot/configs/runs" / HISTORY.name / "design.json"
    old_design = trial.read(old_design_path)
    assert native.sha(trial.EXE) == old_design["dssat_executable_sha256"] == parent["source_hashes"][str(trial.EXE)]
    datasets, catalogs = {}, {}
    trial.DATES = parent["anthesis_dates"]
    for entry in old_design["datasets"]:
        season = entry["season_id"]
        bundle = ARCHIVE / Path(entry["bundle_path"]).name
        verified = verify_manifest_integrity(bundle)
        assert verified.manifest_sha256 == entry["bundle_manifest_sha256"]
        assert entry["roles"] == {parent["datasets"][season]["role"]: parent["datasets"][season]["treatments"]}
        native.model_payload(bundle, RUN / f"{season}_inputs", parent["SLPF"][season])
        catalogs[season] = trial.observation_catalog(bundle, season)
        assert catalogs[season].loc[catalogs[season].variable.eq("ADAP"), "observed"].eq(37).all()
        datasets[season] = parent["datasets"][season] | dict(
            path=str(bundle), bundle_id=bundle.name, manifest_sha256=verified.manifest_sha256)

    full_policy = pd.read_csv(SOURCE / "objective_policy.csv")
    assert native.sha(SOURCE / "objective_policy.csv") == trial.read(SOURCE/"design.json")["source_hashes"][str(SOURCE/"objective_policy.csv")]
    full = trial.objectives(catalogs["26SP"], Path(datasets["26SP"]["path"]), full_policy)
    obs = full[~full.variable.eq("ADAP")].copy()
    assert len(obs) == 617 and np.isclose(obs.final_weight.pow(2).sum(), 97)
    assert obs.role.eq("calibration").all() and obs.season_id.eq("26SP").all()
    assert np.isfinite(obs.observed).all() and obs.obsnme.is_unique
    obs.to_csv(RUN / "calibration_observations.csv", index=False)
    catalogs["25SP"].to_csv(RUN / "locked_validation_observations.csv", index=False)
    full[full.variable.eq("ADAP")].assign(final_weight=0., budget_multiplier=0.).to_csv(
        RUN / "anthesis_diagnostic_observations.csv", index=False)
    shutil.copy2(POLICY / "objective_policy.csv", RUN / "objective_policy.csv")

    frozen, pst = freeze(parent)
    source_paths = [frozen, pst, Path(__file__), Path(trial.__file__), Path(native.__file__),
        trial.EXE, old_design_path, SOURCE / "design.json", SOURCE / "objective_policy.csv",
        POLICY / "joint/joint.pst", RUN / "range_source_audit.csv",
        *(RUN / name for name in ("calibration_observations.csv", "locked_validation_observations.csv",
                                  "anthesis_diagnostic_observations.csv", "objective_policy.csv"))]
    for season in datasets:
        source_paths.extend((RUN / f"{season}_inputs").iterdir())
    hashes = {str(p): native.sha(p) for p in source_paths}
    for p, digest in parent["source_hashes"].items():
        if Path(p).is_relative_to(ROOT / "src"):
            assert native.sha(Path(p)) == digest
            hashes[p] = digest
    design = {k: parent[k] for k in ("stage", "members", "updates", "seed", "workers", "active_parameters",
        "anthesis_dates", "anthesis_dap", "SLPF", "SASC", "ICNS")} | dict(
        run_id=ID, parent_trial=POLICY.name, activation_source=SOURCE.name, bounds_id=ID,
        frozen_bounds=str(frozen), c31_actual_control_file=str(pst), datasets=datasets,
        target_count=len(obs), anthesis_in_objective=False, objective_budget=97,
        ensemble_output_precision=17, source_hashes=hashes)
    native.write(RUN / "design.json", design)
    b = pd.read_csv(frozen).rename(columns={"name":"registry_name","native_name":"name"})
    return design, b, obs.fillna("")


def make_case(design, b, obs, params, outputs):
    work = RUN / "joint"
    work.mkdir()
    shutil.copy2(POLICY / "joint/parameters.tpl", work / "parameters.tpl")
    params.to_csv(work / "initial_ensemble.csv")
    params.loc["base"].rename("value").to_csv(work / "parameters.csv", index_label="name")
    (work / "objectives.ins").write_text(
        "pif ~\n" + "".join(f"l1 w !{name}!\n" for name in obs.obsnme), encoding="ascii")
    trial.write_outputs(work / "FormalObjectives.OUT", obs.obsnme, outputs.loc["base"])
    pst = pyemu.Pst(str(POLICY / "joint/joint.pst"))
    for row in b.itertuples():
        pst.parameter_data.loc[row.pest_name, ["parval1", "parlbnd", "parubnd"]] = [
            params.loc["base", row.pest_name], row.lower, row.upper]
    pst.observation_data = pst.observation_data.loc[obs.obsnme].copy()
    pst.observation_data["weight"] = obs.set_index("obsnme").final_weight
    pst.model_command = [f'"{sys.executable}" -X utf8 "{Path(trial.__file__)}" --forward "{RUN}"']
    pst.pestpp_options["ensemble_output_precision"] = design["ensemble_output_precision"]
    pst.write(str(work / "joint.pst"), version=1)
    actual = pyemu.Pst(str(work / "joint.pst"))
    assert (actual.npar_adj, actual.nnz_obs, actual.control_data.noptmax) == (58, 617, 4)
    assert int(actual.pestpp_options["ensemble_output_precision"]) == design["ensemble_output_precision"]
    np.testing.assert_allclose(actual.observation_data.weight, obs.final_weight, rtol=1e-8)
    np.testing.assert_allclose(actual.parameter_data.loc[b.pest_name, "parlbnd"], b.lower, rtol=1e-8)
    np.testing.assert_allclose(actual.parameter_data.loc[b.pest_name, "parubnd"], b.upper, rtol=1e-8)
    manifest = yaml.safe_load((POLICY / "joint/run_manifest.yaml").read_text(encoding="utf-8"))
    manifest.pop("c31_initial_bounds_source", None)
    manifest.update(run_id=ID, design=str(RUN / "design.json"), bounds_id=ID, parent_trial=POLICY.name,
                    c31_actual_control_file=design["c31_actual_control_file"],
                    ensemble_output_precision=design["ensemble_output_precision"])
    (work / "run_manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")


def main():
    RUN.mkdir(exist_ok=True)
    if (RUN / "design.json").exists() or (RUN / "joint").exists():
        raise FileExistsError(f"Existing trial {RUN}")
    try:
        trial.status(RUN, "preparing")
        design, b, obs = prepare()
        params, outputs, base = trial.initial_ensemble(RUN, b, obs, trial.contexts(RUN, design, b)["26SP"])
        design.update(initial_members=len(params), initial_ensemble_base=base)
        native.write(RUN / "design.json", design)
        native.write(RUN / "sealed_design.json", dict(sha256=native.sha(RUN / "design.json")))
        make_case(design, b, obs, params, outputs)
        trial.status(RUN, "running", phase="pest_ies", initial_members=len(params), n_targets=len(obs))
        with (RUN / "parallel_controller.log").open("wb") as log:
            subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tools/parallel/run_parallel.py"),
                "--run-dir", str(RUN / "joint"), "--case", "joint", "--mode", "ies",
                "--n-agents", str(design["workers"]), "--wait"], cwd=ROOT, stdout=log,
                stderr=subprocess.STDOUT, check=True)
        if trial.read(RUN / "joint/run_status.json")["status"] != "completed":
            raise RuntimeError("PEST++ did not complete")
        for dataset in design["datasets"].values():
            assert verify_manifest_integrity(dataset["path"]).manifest_sha256 == dataset["manifest_sha256"]
        trial.status(RUN, "postprocessing")
        trial.finalize(RUN, b, obs, design, params)
    except Exception as exc:
        previous = trial.read(RUN / "pipeline_status.json")
        trial.status(RUN, "failed", phase=previous["status"], error=f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    main()
