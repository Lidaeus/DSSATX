"""Run the 56-parameter ablation with XFPHT and XFINT removed from the ECO templates."""

import argparse
from dataclasses import replace
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
from tools.calibration import run_water_stress_expansion_40x3_20261107 as previous

trial, native, gradient = previous.trial, previous.native, previous.gradient
PARENT = ROOT / "workspace/runs/eggplant_final_springs_58_restored_bounds_final_200x4_8agents_20261107"
ID = "eggplant_final_springs_56_eco_columns_removed_200x4_8agents_20261107"
RUN = ROOT / "workspace/runs" / ID
MEMBERS, UPDATES, WORKERS = 200, 4, 8


EXCLUDED = ("XFPHT", "XFINT")
check_relations = trial.check_relations


def strip_eco_columns(payload):
    path = payload / "TMGRO048.ECO"
    rows = path.read_text(encoding="ascii").splitlines()
    header = next(i for i, line in enumerate(rows) if line.startswith("@ECO#"))
    assert tuple(rows[header].split()[-2:]) == EXCLUDED
    rows[header] = rows[header].rsplit(maxsplit=2)[0]
    assert rows[header + 1].split()[-2:] == ["18", "19"]
    rows[header + 1] = rows[header + 1].rsplit(maxsplit=2)[0]
    locations = native.field_map(rows, "ECO")
    _, last_offset = locations["XMAGE"]
    end = last_offset + 6
    records = [i for i in range(header + 1, len(rows)) if rows[i].strip() and not rows[i].startswith("!")]
    assert {rows[i][:6] for i in records} == {"TM0001", "DFAULT"}
    for i in records:
        assert len(rows[i]) == end + 12
        rows[i] = rows[i][:end]
    assert all(name not in line for line in rows for name in EXCLUDED)
    path.write_text("\n".join(rows) + "\n", encoding="ascii")


def contexts(run, design, bounds, seasons=("26SP",)):
    # Parse shared metadata and field offsets from the sealed parent layout.
    # The actual model input and injection template come from the trimmed copy.
    layout = pd.concat([bounds, pd.DataFrame({"name": EXCLUDED, "location": "ECO"})], ignore_index=True)
    result = {}
    for season in seasons:
        payload = run / f"{season}_inputs"
        original = PARENT / f"{season}_inputs"
        ctx = native.context(Path(design["datasets"][season]["path"]), original, season, layout)
        rows = (payload / "TMGRO048.ECO").read_text(encoding="ascii").splitlines()
        assert all(name not in line for line in rows for name in EXCLUDED)
        locations = native.field_map(rows, "ECO")
        fields = {name: pos for name, pos in ctx.fields.items() if name not in EXCLUDED}
        assert set(fields) == set(bounds.name)
        assert all(locations[name] == (i, j) for name, (ext, i, j) in fields.items() if ext == "ECO")
        result[season] = replace(ctx, payload=payload, fields=fields, templates=ctx.templates | {"ECO": rows})
    return result


def configure_runner():
    # The legacy validator has an unconditional XMAGE/XFPHT comparison.
    # There is no XFPHT threshold in this control, so bypass only that check.
    def check_remaining_relations(values):
        check_relations(values | {"XFPHT": float("inf")})

    trial.contexts = contexts
    trial.check_relations = check_remaining_relations


def prepare():
    parent_path = PARENT / "design.json"
    parent = trial.read(parent_path)
    assert trial.read(PARENT / "sealed_design.json")["sha256"] == native.sha(parent_path)
    assert trial.read(PARENT / "pipeline_status.json")["status"] == "completed"
    for path, digest in parent["source_hashes"].items():
        assert native.sha(Path(path)) == digest, path
    for season, dataset in parent["datasets"].items():
        assert verify_manifest_integrity(dataset["path"]).manifest_sha256 == dataset["manifest_sha256"]
        shutil.copytree(PARENT / f"{season}_inputs", RUN / f"{season}_inputs")
        strip_eco_columns(RUN / f"{season}_inputs")

    source_bounds = Path(parent["frozen_bounds"])
    original = pd.read_csv(source_bounds)
    excluded = original.native_name.isin(EXCLUDED)
    assert set(original.loc[excluded & original.status.eq("active"), "native_name"]) == set(EXCLUDED)
    proposal = RUN / "approved_trial_bounds.csv"
    original.loc[~excluded].to_csv(proposal, index=False)
    subprocess.run([
        sys.executable, "-X", "utf8", str(ROOT / "tools/freeze_bounds.py"),
        "--proposal", str(proposal), "--crop", "eggplant", "--bounds-id", ID,
        "--notes", "Remove XFPHT and XFINT from the ECO template and from calibration.",
    ], cwd=ROOT, check=True)
    frozen = source_bounds.with_name(ID + ".csv")
    bounds = pd.read_csv(frozen).rename(columns={"name": "registry_name", "native_name": "name"})
    active = bounds.loc[bounds.status.eq("active"), "name"].tolist()
    assert len(active) == 56 and set(active) == set(parent["active_parameters"]) - set(EXCLUDED)
    files = ["calibration_observations.csv", "objective_policy.csv", "locked_validation_observations.csv",
             "calibration_diagnostic_observations.csv", "fixed_input_audit.csv"]
    for name in files:
        shutil.copy2(PARENT / name, RUN / name)
    obs = pd.read_csv(RUN / "calibration_observations.csv").fillna("")
    assert len(obs) == 511 and np.isclose(obs.final_weight.pow(2).sum(), 97)

    sealed = [Path(__file__), parent_path, frozen, proposal, source_bounds, PARENT / "joint/joint.pst",
              *(RUN / name for name in files)]
    for season in parent["datasets"]:
        sealed.extend((RUN / f"{season}_inputs").iterdir())
        sealed.extend((PARENT / f"{season}_inputs").iterdir())
    hashes = {p: h for p, h in parent["source_hashes"].items() if not Path(p).is_relative_to(PARENT)}
    hashes.update({str(path): native.sha(path) for path in sealed})
    design = parent | dict(
        run_id=ID, parent_trial=PARENT.name, parent_design_sha256=native.sha(parent_path),
        members=MEMBERS, updates=UPDATES, workers=WORKERS, source_hashes=hashes,
        final_calibration_requested=False, comparison_group=True,
        active_parameters=active, frozen_bounds=str(frozen), bounds_id=ID, bounds_proposal=str(proposal),
        excluded_parameters=list(EXCLUDED), eco_columns_removed=list(EXCLUDED),
        initial_parameter_source=str(source_bounds),
    )
    for key in ("initial_members", "initial_ensemble_base", "initial_base_phi"):
        design.pop(key, None)
    native.write(RUN / "design.json", design)
    return design, bounds, obs


def make_case(design, bounds, obs, params, outputs):
    work = RUN / "joint"
    work.mkdir()
    shutil.copy2(PARENT / "joint/objectives.ins", work / "objectives.ins")
    old_tpl = (PARENT / "joint/parameters.tpl").read_text(encoding="ascii").splitlines()
    omitted = {name.lower() for name in EXCLUDED}
    tpl = [line for line in old_tpl if line.split(",", 1)[0] not in omitted]
    assert len(old_tpl) - len(tpl) == len(omitted)
    (work / "parameters.tpl").write_text("\n".join(tpl) + "\n", encoding="ascii")
    params.to_csv(work / "initial_ensemble.csv")
    params.loc["base"].rename("value").to_csv(work / "parameters.csv", index_label="name")
    trial.write_outputs(work / "FormalObjectives.OUT", obs.obsnme, outputs.loc["base"])
    pst = pyemu.Pst(str(PARENT / "joint/joint.pst"))
    pst.parameter_data = pst.parameter_data.drop(index=list(omitted))
    assert set(pst.par_names) == set(bounds.pest_name) == set(params.columns)
    assert pst.observation_data.obsnme.tolist() == obs.obsnme.tolist()
    np.testing.assert_allclose(pst.parameter_data.loc[bounds.pest_name, "parval1"],
                               params.loc["base", bounds.pest_name], rtol=1e-9, atol=1e-12)
    pst.control_data.noptmax = UPDATES
    pst.pestpp_options["ies_num_reals"] = str(MEMBERS)
    pst.model_command = [f'"{sys.executable}" -X utf8 "{Path(__file__)}" --forward "{RUN}"']
    pst.write(str(work / "joint.pst"), version=1)
    actual = pyemu.Pst(str(work / "joint.pst"))
    assert (actual.npar_adj, actual.nnz_obs, actual.control_data.noptmax) == (56, 511, UPDATES)
    assert int(actual.pestpp_options["ies_num_reals"]) == MEMBERS
    assert actual.pestpp_options == pst.pestpp_options
    np.testing.assert_allclose(actual.observation_data.weight, obs.final_weight, rtol=1e-8)
    np.testing.assert_allclose(
        actual.parameter_data.loc[bounds.pest_name, ["parlbnd", "parubnd"]], bounds[["lower", "upper"]], rtol=1e-9
    )
    manifest = yaml.safe_load((PARENT / "joint/run_manifest.yaml").read_text(encoding="utf8"))
    manifest.update(run_id=ID, parent_trial=PARENT.name, design=str(RUN / "design.json"), bounds_id=design["bounds_id"],
                    ies_num_reals=MEMBERS, noptmax=UPDATES, n_params_active=56, final_calibration_requested=False,
                    bounds_proposal=design["bounds_proposal"], excluded_parameters=list(EXCLUDED))
    (work / "run_manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf8")


def main():
    RUN.mkdir(exist_ok=True)
    if (RUN / "pipeline_status.json").exists():
        raise FileExistsError(f"Existing trial {RUN}")
    trial.MEMBERS, trial.UPDATES, trial.WORKERS = MEMBERS, UPDATES, WORKERS
    gradient.sa98_joint40.SIGNED.add(gradient.NITROGEN_OPERATOR)
    try:
        trial.status(RUN, "preparing")
        design, bounds, obs = prepare()
        configure_runner()
        trial.DATES = design["anthesis_dates"]
        ctx = trial.contexts(RUN, design, bounds)["26SP"]
        params, outputs, base = trial.initial_ensemble(RUN, bounds, obs, ctx)
        base_phi = float(np.square(outputs.loc["base"].to_numpy() * obs.final_weight.to_numpy()).sum())
        assert base == "center" and np.isfinite(base_phi), (base, base_phi)
        design.update(initial_members=len(params), initial_ensemble_base=base, initial_base_phi=base_phi)
        native.write(RUN / "design.json", design)
        native.write(RUN / "sealed_design.json", dict(sha256=native.sha(RUN / "design.json")))
        make_case(design, bounds, obs, params, outputs)
        trial.status(RUN, "running", phase="pest_ies", initial_members=len(params), n_targets=len(obs),
                     agents=WORKERS, initial_base_phi=base_phi)
        with (RUN / "parallel_controller.log").open("wb") as log:
            subprocess.run([
                sys.executable, "-X", "utf8", str(ROOT / "tools/parallel/run_parallel.py"),
                "--run-dir", str(RUN / "joint"), "--case", "joint", "--mode", "ies",
                "--n-agents", str(WORKERS), "--wait",
            ], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        if trial.read(RUN / "joint/run_status.json")["status"] != "completed":
            raise RuntimeError("PEST++ did not complete")
        for dataset in design["datasets"].values():
            assert verify_manifest_integrity(dataset["path"]).manifest_sha256 == dataset["manifest_sha256"]
        trial.status(RUN, "postprocessing")
        trial.finalize(RUN, bounds, obs, design, params)
        gradient.RUN = RUN
        gradient.save_gradient_diagnostics(design)
    except Exception as exc:
        state = trial.read(RUN / "pipeline_status.json")
        trial.status(RUN, "failed", phase=state["status"], error=f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--forward", type=Path)
    args = parser.parse_args()
    if args.forward is None:
        main()
    else:
        gradient.sa98_joint40.SIGNED.add(gradient.NITROGEN_OPERATOR)
        configure_runner()
        trial.forward(args.forward)
