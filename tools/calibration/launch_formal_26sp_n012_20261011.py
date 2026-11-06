"""Freeze, preflight and launch the user-approved refreshed-data calibration.

The persistent controller runs S1/S2/S3/joint in sequence. Selection always
uses the same complete 423-row calibration objective, never validation.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.calibration import single_season_n as model

REVIEW = ROOT / "configs/calibration_proposals/eggplant_26sp_n012_review_20261011"
ID = "eggplant_26sp_n012_formal_20261011"
CONFIG = ROOT / "configs/runs" / ID
DESIGN = CONFIG / "design.json"
RUN = ROOT / "workspace/runs" / ID
BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant" / (ID + ".csv")


def use_run(run_id):
    """Select a new isolated execution without replacing its frozen bounds."""
    global ID, CONFIG, DESIGN, RUN, BOUNDS
    import re
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", run_id):
        raise ValueError("Invalid run identifier")
    ID = run_id
    CONFIG, RUN = ROOT / "configs/runs" / ID, ROOT / "workspace/runs" / ID
    DESIGN = CONFIG / "design.json"
    if DESIGN.is_file():
        bounds_id = json.loads(DESIGN.read_text(encoding="utf-8"))["bounds_id"]
        BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant" / (bounds_id + ".csv")


def prepare_repair(source_id):
    """Freeze an operational repair; preserve the approved scientific contract."""
    if CONFIG.exists() or RUN.exists():
        raise FileExistsError("A repair must use a new configuration and run directory")
    source_config = ROOT / "configs/runs" / source_id
    source_run = ROOT / "workspace/runs" / source_id
    source = json.loads((source_config / "design.json").read_text(encoding="utf-8"))
    receipt = json.loads((source_config / "frozen_configuration_receipt.json").read_text(encoding="utf-8"))
    if model.sha(source_config / "design.json") != receipt["design_sha256"]:
        raise ValueError("Previous frozen design changed")
    for name, expected in receipt["files"].items():
        if model.sha(source_config / name) != expected:
            raise ValueError(f"Previous frozen configuration changed: {name}")
    state = json.loads((source_run / "pipeline_status.json").read_text(encoding="utf-8"))
    if state["status"] != "failed":
        raise ValueError("Only a failed, stopped pipeline can be repaired this way")
    shutil.copytree(source_config, CONFIG)
    RUN.mkdir(parents=True)
    design = {**source, "design_id": ID, "configuration_revision": source.get("configuration_revision", 1) + 1,
        "runtime_preflight_passed": False, "status": "repair_preflight_pending",
        "repair_of": source_id, "repair_authorization": "若未成功执行，修复bug并重新进行参数率定。",
        "execution_policy": {
            "initial_sigma_width_divisor": 8.0,
            "feasibility_screen_all_initial_members": True,
            "feasibility_screen_uses_observed_values": False,
            "ies_bad_phi_sigma": 1e300, "ies_initial_lambda": 10.0,
            "lambda_scale_fac": [.25, .5], "ies_lambda_mults": [.1, 1., 10.],
            "maximum_stage_attempts": 3,
            "retry_sigma_divisors": [8., 12., 16.],
            "retry_initial_lambdas": [10., 100., 1000.],
            "retry_scale_factors": [[.25,.5],[.1,.25],[.05,.1]],
            "retry_condition": "engineering retention/Phi-finiteness failure only; same anchor, bounds, targets, weights and seed",
            "ensemble_interpretation": "feasibility-conditioned local optimization ensemble; not a posterior uncertainty sample"}}
    paths = list(design["runtime_hashes"]) + ["src/reporting/quality_gate.py", "src/common/quality.py",
        "src/calibration/engineering_gate.py", "tools/parallel/run_parallel.py"]
    design["runtime_hashes"] = {p: model.sha(ROOT / p) for p in paths}
    model.write_json(DESIGN, design)
    use_run(ID)
    model.write_json(CONFIG / "repair_receipt.json", {
        "prepared_at": stamp(), "source_run": source_id, "source_design_sha256": receipt["design_sha256"],
        "source_status_sha256": model.sha(source_run / "pipeline_status.json"),
        "bounds_unchanged": True, "targets_weights_roles_unchanged": True,
        "source_initial_prior_width_divisor": source.get('execution_policy', {}).get('initial_sigma_width_divisor', 4.),
        "windows_copy_policy": "reuse SHA-256-identical DSSAT executable; bounded retry of WinError32/33 only",
        "operational_changes": design["execution_policy"]})
    # Re-run all targets with the original anchor. The original 53-field OAT
    # audit remains evidence: scientific operators, inputs and bounds are unchanged.
    _, bounds, obs = model.load_design(DESIGN, require_preflight=False)
    initial = model.validate_parameters(dict(zip(bounds.name, bounds.init)), bounds)
    audit = RUN / "preflight"
    audit.mkdir()
    params = audit / "initial_parameters.csv"
    pd.DataFrame(list(initial.items()), columns=["name", "value"]).to_csv(params, index=False)
    result = model.evaluate(DESIGN, params, audit / "baseline", preflight=True)
    result.to_csv(audit / "baseline_comparison.csv", index=False)
    old = pd.read_csv(source_run / "preflight/baseline_comparison.csv")
    difference = float(np.max(np.abs(result.simulated.to_numpy() - old.simulated.to_numpy())))
    if not result.obsnme.equals(old.obsnme) or difference > 1e-10:
        raise ValueError("Repair changed the original baseline objective")
    model.audit_injection(audit / "baseline/_model", initial, bounds[bounds.status.eq("active")].name)
    model.write_json(audit / "preflight_report.json", {"passed": True, "checked_at": stamp(),
        "all_423_exact_date_rows_valid": True, "original_baseline_max_difference": difference,
        "inherited_parameter_activation_audit": str(source_run / "preflight/preflight_report.json"),
        "inherited_parameter_activation_audit_sha256": model.sha(source_run / "preflight/preflight_report.json"),
        "active_parameter_fields_independently_read_back": 53, "validation_used": False})
    design.update(runtime_preflight_passed=True, status="approved_ready",
        preflight_report_sha256=model.sha(audit / "preflight_report.json"))
    model.write_json(DESIGN, design)
    model.write_json(CONFIG / "frozen_configuration_receipt.json", {"frozen_at": stamp(),
        "design_sha256": model.sha(DESIGN), "files": {p.name: model.sha(p) for p in CONFIG.iterdir()
        if p.is_file() and p.name != "frozen_configuration_receipt.json"}})
    model.load_design(DESIGN)
    print(f"Repair prepared with unchanged 423-row baseline: {ID}", flush=True)


def feasible_ensemble(target, ensemble, bounds, rng, divisor):
    """Reject undefined model states before IES; never compare fit to observations."""
    audit = target / "initial_feasibility"
    audit.mkdir()
    records = []
    columns = list(ensemble.columns)
    initial = ensemble.loc["base"].copy()
    active = set(pyemu.Pst(str(target / (target.name + ".pst"))).adj_par_names)

    def run_member(name, seed):
        return _screen_member(name, ensemble.loc[name], initial, columns, active,
                              bounds, np.random.default_rng(seed), divisor, audit)

    seeds = rng.integers(0, 2**63-1, size=len(ensemble))
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        pending = [pool.submit(run_member, name, int(seed)) for name, seed in zip(ensemble.index, seeds)]
        for i, future in enumerate(concurrent.futures.as_completed(pending), 1):
            name, values, record = future.result()
            ensemble.loc[name] = values
            records.append(record)
            if i % 20 == 0:
                print(f"{target.name}: exact-date feasibility {i}/{len(ensemble)}", flush=True)
    model.write_json(audit / "report.json", {"passed": True, "members": len(ensemble),
        "rejected_candidates": sum(len(r["rejections"]) for r in records),
        "selection_by_fit": False, "validation_used": False, "members_audit": sorted(records, key=lambda r: r["realization"])})
    return ensemble


def _screen_member(name, values, initial, columns, active, bounds, rng, divisor, audit):
    rejected = []
    values = values.copy()
    for attempt in range(30):
        work = audit / name
        work.mkdir(exist_ok=True)
        params = work / "parameters.csv"
        pd.DataFrame({"name": [c.upper() for c in columns], "value": values.to_numpy()}).to_csv(params, index=False)
        try:
            compared = model.evaluate(DESIGN, params, work)
            return name, values, {"realization": name, "attempts": attempt+1, "passed": True,
                "objective_count": len(compared), "rejections": rejected}
        except ValueError as error:
            if "No mature fruit at the exact N sampling date" not in str(error) or name == "base":
                raise
            rejected.append({"attempt": attempt+1, "reason": str(error), "parameters": values.to_dict()})
            values = initial.copy()
            for row in bounds.itertuples():
                key = row.name.lower()
                if key not in active:
                    continue
                while True:
                    value = rng.normal(initial[key], (row.upper-row.lower)/divisor)
                    if row.lower <= value <= row.upper:
                        values[key] = value
                        break
    raise RuntimeError(f"Could not construct a feasible member: {name}")


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def logged(command, log, *, cwd=ROOT):
    Path(log).parent.mkdir(parents=True, exist_ok=True)
    with Path(log).open("w", encoding="utf-8") as handle:
        result = subprocess.run(command, cwd=cwd, stdout=handle, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"Command exited {result.returncode}: {log}")


def prepare():
    if DESIGN.exists():
        raise FileExistsError("Approved design already exists; never overwrite it")
    receipt = json.loads((REVIEW / "proposal_receipt.json").read_text(encoding="utf-8"))
    for item in receipt["files"]:
        if model.sha(REVIEW / item["name"]) != item["sha256"]:
            raise ValueError("Review artifact hash changed")
    for item in receipt["source_files"]:
        if model.sha(ROOT / item["path"]) != item["sha256"]:
            raise ValueError(f"Review source hash changed: {item['path']}")
    proposal = json.loads((REVIEW / "proposal.json").read_text(encoding="utf-8"))
    CONFIG.mkdir(parents=True, exist_ok=True)
    RUN.mkdir(parents=True, exist_ok=True)
    # Keep the review artifact immutable and record approval separately.
    for name in ["proposal.json", "proposal_receipt.json", "objective_policy.csv", "observation_catalog.csv",
                 "parameter_review.csv", "fruit_sampling_definition.json", "recent_parameter_comparison.csv"]:
        shutil.copy2(REVIEW / name, CONFIG / ("review_" + name))
    obs = pd.read_csv(REVIEW / "observation_catalog.csv").fillna("")
    cal = obs[obs.final_weight.gt(0)].copy().reset_index(drop=True)
    cal["obsnme"] = [f"n26_{i:04d}" for i in range(len(cal))]
    cal["runtime_operator_preflight_passed"] = False
    cal.to_csv(CONFIG / "calibration_observations.csv", index=False)
    obs[~obs.dataset_role.eq("calibration")].to_csv(CONFIG / "locked_evaluation_observations.csv", index=False)
    if not BOUNDS.is_file():
        logged([sys.executable, str(ROOT / "tools/freeze_bounds.py"), "--proposal", str(ROOT / proposal["parameter_proposal"]),
                "--crop", "eggplant", "--bounds-id", ID, "--notes", "User authorized formal launch 2026-10-11"], RUN / "freeze_bounds.log")
    runtime_paths = ["src/calibration/single_season_n.py", "src/dssat/run_dssat.py", "src/dssat/array_expander.py",
                     "src/calibration/observation_policy.py", "src/common/param_registry.py",
                     "src/common/input_manifest.py", "src/common/project.py",
                     "tools/calibration/launch_formal_26sp_n012_20261011.py"]
    runtime_paths += [f"data/templates/genotype/TMGRO048.{kind}.base" for kind in ["CUL", "ECO", "SPE"]]
    runtime_paths += ["data/templates/" + name for name in ["DSSATPRO.v48", "DSSAT48.INH", "DSSAT48.INP"]]
    executable = ROOT / "workspace/DSCSM048.EXE"
    if not executable.exists():
        executable = Path(r"C:\DSSAT48\DSCSM048.EXE")
    design = {**proposal, "schema": "formal_single_season_n_v1", "design_id": ID,
              "approved": True, "approval": {"user_statement": "启动正式参数率定", "recorded_at": stamp()},
              "status": "approved_preflight_pending", "executable": True, "diagnostic_single_season": False,
              "bounds_id": ID, "bounds_sha256": model.sha(BOUNDS), "runtime_preflight_passed": False,
              "runtime_hashes": {p: model.sha(ROOT / p) for p in runtime_paths},
              "dssat_executable": str(executable), "dssat_executable_sha256": model.sha(executable),
              "calibration_observations": "calibration_observations.csv",
              "calibration_observations_sha256": model.sha(CONFIG / "calibration_observations.csv"),
              "evaluation_catalog_sha256": model.sha(CONFIG / "locked_evaluation_observations.csv"),
              "selection_rule": "minimum complete 423-row fixed-weight calibration Phi among evaluated members, retain anchor on deterioration",
              "stage_target_families": {
                  "S1_canopy": ["CANOPY_LAI", "LEAF_DRY_MASS", "STEM_DRY_MASS", "HEIGHT"],
                  "S2_nitrogen": ["LEAF_N_CONCENTRATION", "STEM_N_CONCENTRATION", "LEAF_DRY_MASS", "STEM_DRY_MASS"],
                  "S3_water_fruit": ["FRUIT_N_CONCENTRATION", "HARVEST_DRY_EVENT", "SOIL_WATER"],
              }, "runtime_entrypoint": "src/calibration/single_season_n.py"}
    design["fruit_sampling_definition"]["calibration_design_approved"] = True
    design["uncertainty_model"]["floor_and_cv_status"] = "user_approved_assumptions"
    model.write_json(DESIGN, design)
    model.load_design(DESIGN, require_preflight=False)
    model.write_json(CONFIG / "approval_receipt.json", {"recorded_at": stamp(), "user_statement": "启动正式参数率定",
        "proposal_sha256": model.sha(REVIEW / "proposal.json"), "bounds_sha256": model.sha(BOUNDS),
        "review_doc_sha256": model.sha(ROOT / "docs/reports/正式率定方案_2026N012_20261011.md"),
        "calibration_count": 423, "active_candidates": 53, "validation_not_used_for_fit": True})
    print(f"Approved configuration prepared: {DESIGN}", flush=True)


def preflight():
    design, bounds, obs = model.load_design(DESIGN, require_preflight=False)
    audit = RUN / "preflight"
    audit.mkdir(parents=True, exist_ok=True)
    initial = model.validate_parameters(dict(zip(bounds.name, bounds.init)), bounds)
    baseline_params = audit / "initial_parameters.csv"
    pd.DataFrame(list(initial.items()), columns=["name", "value"]).to_csv(baseline_params, index=False)
    base = model.evaluate(DESIGN, baseline_params, audit / "baseline", preflight=True)
    base.to_csv(audit / "baseline_comparison.csv", index=False)
    fruits = base[base.variable.eq("FRUIT_N_PCT")]
    if len(fruits) != 27 or not fruits.bulk_harvest_dry.eq(0).all():
        raise ValueError("Fruit sampling phases require 27 exact-date non-bulk-harvest mature pools")
    effects_path = audit / "perturbation_effects.csv"
    records = pd.read_csv(effects_path).fillna("").to_dict("records") if effects_path.exists() else []
    dataset = next(d for d in design["datasets"] if d["roles"].get("calibration"))
    # One-at-a-time broad local perturbations. These are an output/injection
    # gate, not claims of scientific identifiability or a sensitivity ranking.
    for i, row in enumerate(bounds[bounds.status.eq("active")].itertuples(), 1):
        effects = []
        for sign in [1, -1]:
            values = dict(initial)
            values[row.name] = row.init + sign * .2 * (row.upper - row.lower)
            model.validate_parameters(values, bounds)
            cached = next((r for r in records if r['name'] == row.name and r['sign'] == sign), None)
            if cached:
                effects.append(float(cached['weighted_max_effect']) if cached['weighted_max_effect'] != '' else None)
                continue
            record = dict(name=row.name, sign=sign, requested_value=values[row.name])
            try:
                work = model.simulate(audit / "perturbation_work", dataset, dataset["roles"]["calibration"], values)
                model.audit_injection(work, values, bounds[bounds.status.eq("active")].name)
                result = model.extract_observations(work, obs)
                delta = (result.simulated.to_numpy() - base.simulated.to_numpy()) * obs.final_weight.to_numpy()
                record.update(weighted_max_effect=float(np.max(np.abs(delta))),
                              changed_objectives=int(np.count_nonzero(np.abs(delta) > 1e-10)), all_423_finite=True, error="")
            except ValueError as error:
                if 'No mature fruit at the exact N sampling date' not in str(error):
                    raise
                record.update(weighted_max_effect=None, changed_objectives=0, all_423_finite=False, error=str(error))
            effects.append(record['weighted_max_effect'])
            records.append(record)
        pd.DataFrame(records).to_csv(effects_path, index=False)
        print(f"preflight {i}/53 {row.name}: effects={effects}", flush=True)
    effect_table = pd.DataFrame(records)
    zero = [name for name, part in effect_table.groupby("name")
            if pd.to_numeric(part.weighted_max_effect, errors='coerce').max() <= 1e-10]
    # Verify zero local responses at both domain endpoints and in a distinct
    # valid high-demand/early-fruit context before applying the approved gate.
    contexts = [dict(initial), {**initial,
        "PROLFI": float(bounds.set_index('name').loc['PROLFI', 'upper']),
        "PROSTI": float(bounds.set_index('name').loc['PROSTI', 'upper']),
        "PROSHI": .19, "RTNO3": .01, "RTNH4": .01}]
    endpoint_path = audit/'zero_response_endpoint_checks.csv'
    endpoint_records = pd.read_csv(endpoint_path).to_dict('records') if endpoint_path.exists() else []
    for context_id, context in enumerate(contexts):
        model.validate_parameters(context, bounds)
        context_work = model.simulate(audit / 'context_work', dataset, dataset['roles']['calibration'], context)
        context_result = model.extract_observations(context_work, obs)
        for name in zero:
            row = bounds.set_index('name').loc[name]
            for endpoint in ['lower', 'upper']:
                if any(r['name']==name and r['context']==context_id and r['endpoint']==endpoint for r in endpoint_records):
                    continue
                values = {**context, name: float(row[endpoint])}
                work = model.simulate(audit / 'endpoint_work', dataset, dataset['roles']['calibration'], values)
                injection = model.audit_injection(work, values, [name])[0]
                result = model.extract_observations(work, obs)
                delta = (result.simulated.to_numpy()-context_result.simulated.to_numpy())*obs.final_weight.to_numpy()
                endpoint_records.append(dict(name=name, context=context_id, endpoint=endpoint,
                    requested_value=values[name], injected_value=injection['injected'],
                    weighted_max_effect=float(np.max(np.abs(delta)))))
                pd.DataFrame(endpoint_records).to_csv(endpoint_path, index=False)
            print(f'endpoint context={context_id} {name}', flush=True)
    still_zero = [name for name in zero if max(r['weighted_max_effect'] for r in endpoint_records if r['name']==name) <= 1e-10]
    # Check the unused shell G parameter against the installed executable.
    control = dict(initial)
    control["PROSHG"] = .18
    work = model.simulate(audit / "proshg_control", dataset, dataset["roles"]["calibration"], control)
    ignored = model.extract_observations(work, obs)
    ignored_effect = float(np.max(np.abs(ignored.simulated.to_numpy() - base.simulated.to_numpy())))
    model.audit_injection(audit/'baseline/_model', initial, bounds[bounds.status.eq('active')].name)
    report = {"checked_at": stamp(), "candidate_count": 53, "zero_local_effect_parameters": zero,
              "zero_effect_parameters": still_zero, "eligible_active_parameters": 53-len(still_zero),
              "passed": True, "all_423_exact_date_rows_valid": True,
              "mature_fruit_rows": 27, "fruit_sampling_days_bulk_harvest_zero": True,
              "fruit_operator": "same-day mature-seed/shell dry-mass weighted organ-average N",
              "phase_semantics": "FreshWt INTEGR stores mature pool before removal; PlantN OUTPUT after GROW; all N sample dates have no bulk removal, so use same-day states",
              "native_precision": "N organ concentrations printed to 0.01 percentage points; dry components to 0.1 kg/ha; no subtraction of rounded N masses",
              "maturity_semantics": "XMAGE is the model multi-harvest maturity threshold; proxy approximation explicitly approved, no claimed independent physiological maturity measurement",
              "proshg_control_effect": ignored_effect,
              "active_parameter_fields_independently_read_back": 53,
              "dssat_executable_sha256": design["dssat_executable_sha256"],
              "validation_simulated_during_preflight": False,
              "candidate_failures": [r for r in records if r['all_423_finite'] is False],
              "zero_response_action": "freeze at approved midpoint under reviewed non-degenerate-response activation rule; domains/targets unchanged",
              "zero_response_is_global_identifiability_claim": False}
    model.write_json(audit / "preflight_report.json", report)
    design['stages'] = json.loads((CONFIG/'review_proposal.json').read_text(encoding='utf-8'))['stages']
    for stage in design['stages']:
        stage['active_parameters'] = [name for name in stage['active_parameters'] if name not in still_zero]
    design['eligible_active_parameters'] = [name for name in bounds[bounds.status.eq('active')].name if name not in still_zero]
    design['conditional_fixed_parameters'] = {name: initial[name] for name in still_zero}
    obs['runtime_operator_preflight_passed'] = True
    obs.to_csv(CONFIG / 'calibration_observations.csv', index=False)
    design['calibration_observations_sha256'] = model.sha(CONFIG / 'calibration_observations.csv')
    design.pop('formal_calibration_started', None)  # Execution state lives in the run directory.
    design['runtime_hashes'] = {p: model.sha(ROOT/p) for p in design['runtime_hashes']}
    design["runtime_preflight_passed"] = True
    design["status"] = "approved_ready"
    design["preflight_report_sha256"] = model.sha(audit / "preflight_report.json")
    design["output_evidence"]["fruit_operator_runtime_phase_preflight_passed"] = True
    design["output_evidence"]["new_native_reader_is_not_integrated_into_pest"] = False
    design["pending"] = []
    model.write_json(DESIGN, design)
    model.write_json(CONFIG / "frozen_configuration_receipt.json", {"frozen_at": stamp(),
        "design_sha256": model.sha(DESIGN), "files": {p.name: model.sha(p) for p in CONFIG.iterdir()
        if p.is_file() and p.name != "frozen_configuration_receipt.json"}})
    print("Formal preflight passed", flush=True)


def build_stage(stage, values):
    design, bounds, obs = model.load_design(DESIGN)
    name = stage["stage_id"]
    target = RUN / name
    if target.exists():
        raise FileExistsError(f"Never overwrite a calibration stage: {target}")
    target.mkdir()
    active = set(stage["active_parameters"])
    if len(active) != len(stage["active_parameters"]):
        raise ValueError("Duplicate stage parameters")
    (target / "parameters.tpl").write_text("ptf ~\nname,value\n" + "".join(
        f"{row.name},~ {row.name.lower():<20} ~\n" for row in bounds.itertuples()), encoding="ascii")
    pd.DataFrame(list(values.items()), columns=["name", "value"]).to_csv(target / "parameters.csv", index=False)
    (target / "objectives.ins").write_text("pif ~\n" + "".join(f"l1 w !{r.obsnme}!\n" for r in obs.itertuples()), encoding="ascii")
    pst = pyemu.Pst.from_io_files([str(target / "parameters.tpl")], [str(target / "parameters.csv")],
                                 [str(target / "objectives.ins")], [str(target / "FormalObjectives.OUT")], pst_path=".")
    par = pst.parameter_data
    for row in bounds.itertuples():
        key = row.name.lower()
        par.loc[key, ["partrans", "parval1", "parlbnd", "parubnd", "pargp"]] = [
            "none" if row.name in active else "fixed", values[row.name], row.lower, row.upper, row.pargp.lower()]
    selected = set(design["stage_target_families"].get(stage.get('logical_stage_id', name), obs.family.unique()))
    for row in obs.itertuples():
        pst.observation_data.loc[row.obsnme, ["obsval", "weight", "obgnme"]] = [
            row.observed, row.final_weight if row.family in selected else 0., row.family.lower()]
    pst.model_command = [f'"{sys.executable}" -X utf8 "{ROOT / "src/calibration/single_season_n.py"}" --design "{DESIGN}" --param-csv parameters.csv']
    pst.control_data.noptmax = stage["noptmax"]
    policy = design.get("execution_policy", {})
    pst.pestpp_options = {"ies_num_reals": 200, "ies_include_base": True,
                          "ies_no_noise": True, "ies_save_binary": False,
                          "ies_bad_phi_sigma": policy.get("ies_bad_phi_sigma", 3.0),
                          "ies_initial_lambda": stage.get("initial_lambda", policy.get("ies_initial_lambda", 1.0)),
                          "ies_lambda_mults": policy.get("ies_lambda_mults", [0.1, 1.0, 10.0]),
                          "ies_par_en": "initial_ensemble.csv", "rand_seed": stage["seed"],
                          "panther_agent_no_ping_timeout_secs": 600}
    if policy:
        pst.pestpp_options["lambda_scale_fac"] = stage.get("scale_factors", policy["lambda_scale_fac"])
    # Sample a bounded Gaussian prior around the inherited anchor; rejection
    # avoids point masses from clipping. Fixed parameters remain exact.
    rng = np.random.default_rng(stage["seed"])
    divisor = stage.get("sigma_width_divisor", policy.get("initial_sigma_width_divisor", 4.0))
    ensemble = pd.DataFrame([dict((k.lower(), v) for k, v in values.items()) for _ in range(199)],
                            index=[f"real_{i:03d}" for i in range(199)])
    for row in bounds.itertuples():
        if row.name not in active:
            continue
        drawn = []
        while len(drawn) < 199:
            batch = rng.normal(values[row.name], (row.upper - row.lower) / divisor, 300)
            drawn.extend(batch[(batch >= row.lower) & (batch <= row.upper)].tolist())
        ensemble[row.name.lower()] = drawn[:199]
    ensemble.loc["base"] = {k.lower(): v for k, v in values.items()}
    for _, member in ensemble.iterrows():
        model.validate_parameters(member.to_dict(), bounds)
    ensemble.to_csv(target / "initial_ensemble.csv")
    pst.write(str(target / (name + ".pst")), version=1)
    reloaded = pyemu.Pst(str(target / (name + ".pst")))
    if reloaded.npar_adj != len(active) or len(reloaded.observation_data) != 423:
        raise ValueError("PEST case differs from approved stage")
    obs.assign(stage_weight=pst.observation_data.weight.reindex(obs.obsnme).to_numpy()).to_csv(target / "observation_weights.csv", index=False)
    manifest = {"run_id": ID + "_" + name, "created_at": stamp(), "mode": "eggplant_stage2",
        "design_schema": "formal_single_season_n_v1", "bounds_id": design['bounds_id'], "bounds_sha256": model.sha(BOUNDS),
        "design_sha256": model.sha(DESIGN), "observation_policy_sha256": design["calibration_observations_sha256"],
        "input_manifest_sha256": next(d["bundle_manifest_sha256"] for d in design["datasets"] if d["season_id"] == "26SP"),
        "n_params": len(bounds), "n_params_active": len(active), "n_obs": 423,
        "n_obs_positive": int(pst.observation_data.weight.gt(0).sum()), "noptmax": stage["noptmax"],
        "ies_num_reals": 200, "seed": stage["seed"], "agents": 6, "scientific_status": "science_pending",
        "batch_file": "DSSBatch.v48", "harvest_var": "HPODW", "scenario_type": "actual_trial_calibration"}
    (target / "run_manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    model.write_json(target / "stage_design.json", {**stage, "families": sorted(selected), "initial_ensemble_sha256": model.sha(target / "initial_ensemble.csv")})
    if policy.get("feasibility_screen_all_initial_members") and stage.get("noptmax", 0) > 0:
        ensemble = feasible_ensemble(target, ensemble, bounds, rng, divisor)
        ensemble.to_csv(target / "initial_ensemble.csv")
        model.write_json(target / "stage_design.json", {**stage, "families": sorted(selected),
            "sigma_width_divisor": divisor, "initial_ensemble_sha256": model.sha(target / "initial_ensemble.csv"),
            "initial_feasibility_report_sha256": model.sha(target / "initial_feasibility/report.json")})
    return target


def select_stage(target, stage, anchor_phi):
    design, bounds, obs = model.load_design(DESIGN)
    candidates = []
    for file in sorted(target.glob(stage["stage_id"] + ".*.obs.csv")):
        number = file.name.removeprefix(stage["stage_id"] + ".").removesuffix(".obs.csv")
        if not number.isdigit():
            continue
        parameters = target / f"{stage['stage_id']}.{number}.par.csv"
        if not parameters.exists():
            continue
        outputs, pars = pd.read_csv(file, index_col=0), pd.read_csv(parameters, index_col=0)
        outputs.index = outputs.index.astype(str)
        pars.index = pars.index.astype(str)
        outputs.columns = outputs.columns.str.lower()
        pars.columns = pars.columns.str.lower()
        for realization in outputs.index.intersection(pars.index):
            simulated = outputs.loc[realization, obs.obsnme].to_numpy(dtype=float)
            if not np.isfinite(simulated).all() or np.any(simulated < 0):
                continue
            phi = float(np.sum(((simulated - obs.observed.to_numpy()) * obs.final_weight.to_numpy()) ** 2))
            candidates.append((phi, int(number), realization, parameters.name))
    if not candidates:
        raise RuntimeError("No complete evaluated ensemble member available")
    candidates.sort(key=lambda row: (row[0], row[1], row[2]))
    best = candidates[0]
    pd.DataFrame(candidates, columns=["complete_calibration_phi", "iteration", "realization", "parameter_file"]).to_csv(target / "complete_objective_selection.csv", index=False)
    chosen = pd.read_csv(target / best[3], index_col=0)
    chosen.index = chosen.index.astype(str)
    chosen.columns = chosen.columns.str.lower()
    values = {row.name: float(chosen.loc[best[2], row.name.lower()]) for row in bounds.itertuples()}
    model.validate_parameters(values, bounds)
    report = {"selected_phi": best[0], "anchor_phi": anchor_phi, "iteration": best[1], "realization": best[2],
              "criterion": "complete fixed 423-row calibration objective", "validation_used": False,
              "retain_anchor": best[0] >= anchor_phi}
    model.write_json(target / "selection.json", report)
    return values, report


def pipeline():
    design, bounds, obs = model.load_design(DESIGN)
    if model.sha(Path(design["dssat_executable"])) != design["dssat_executable_sha256"]:
        raise ValueError("DSSAT executable changed")
    values = model.validate_parameters(dict(zip(bounds.name, bounds.init)), bounds)
    baseline = pd.read_csv(RUN / "preflight/baseline_comparison.csv")
    anchor_phi = float(np.sum(((baseline.simulated - baseline.observed) * baseline.final_weight) ** 2))
    stages = design["stages"] + [{**design["final_joint"], "stage_id": "S4_joint",
        "active_parameters": design['eligible_active_parameters']}]
    state = {"run_id": ID, "started_at": stamp(), "controller_pid": os.getpid(), "status": "running",
             "scientific_status": "science_pending", "completed_stages": [], "validation_used_for_selection": False}
    model.write_json(RUN / "pipeline_status.json", state)
    try:
        for stage in stages:
            policy = design.get('execution_policy', {})
            logical_stage = stage['stage_id']
            for attempt in range(policy.get('maximum_stage_attempts', 1)):
                actual_stage = dict(stage)
                if policy:
                    actual_stage.update(sigma_width_divisor=policy['retry_sigma_divisors'][attempt],
                        initial_lambda=policy['retry_initial_lambdas'][attempt],
                        scale_factors=policy['retry_scale_factors'][attempt])
                if attempt:
                    actual_stage['stage_id'] = logical_stage + f'_retry{attempt+1}'
                actual_stage['logical_stage_id'] = logical_stage
                state.update(current_stage=logical_stage, attempt=attempt+1, phase='initial_feasibility_screen',
                    last_updated_at=stamp())
                model.write_json(RUN / 'pipeline_status.json', state)
                target = build_stage(actual_stage, values)
                state.update(stage_dir=str(target), phase='ies', last_updated_at=stamp())
                model.write_json(RUN / 'pipeline_status.json', state)
                logged([sys.executable, '-X', 'utf8', str(ROOT / 'tools/parallel/run_parallel.py'), '--run-dir', str(target),
                        '--case', actual_stage['stage_id'], '--mode', 'ies', '--n-agents', '6', '--wait'], target / 'parallel_controller.log')
                outcome = json.loads((target/'run_status.json').read_text(encoding='utf-8'))
                if outcome.get('status') == 'completed' and outcome.get('engineering_status') == 'engineering_validated':
                    stage = actual_stage
                    break
                quality = json.loads((target/'ies_quality/ies_run_quality.json').read_text(encoding='utf-8'))
                failures = {c['check_id'] for c in quality['checks'] if c['status'] == 'fail'}
                retryable = {'ies_realization_alignment','ies_final_realization_alignment','ies_phi_finite'}
                state.setdefault('failed_stage_attempts', []).append({'stage': actual_stage['stage_id'],
                    'failures': sorted(failures), 'quality_path': str(target/'ies_quality/ies_run_quality.json')})
                model.write_json(RUN / 'pipeline_status.json', state)
                if outcome.get('status') != 'completed' or not failures or not failures.issubset(retryable) or attempt+1 == policy.get('maximum_stage_attempts',1):
                    raise RuntimeError(f"Stage engineering gate failed; downstream stages blocked: {target/'run_status.json'}")
            rec = (target / (stage["stage_id"] + ".rec")).read_text(errors="replace").lower()
            if "analysis complete" not in rec:
                raise RuntimeError("PEST++ completion marker missing")
            chosen, selection = select_stage(target, stage, anchor_phi)
            if not selection["retain_anchor"]:
                values = chosen
            params = target / "selected_parameters.csv"
            pd.DataFrame(list(values.items()), columns=["name", "value"]).to_csv(params, index=False)
            comparison = model.evaluate(DESIGN, params, target / "selected_deterministic")
            checked_phi = float(np.sum(((comparison.simulated - comparison.observed) * comparison.final_weight) ** 2))
            expected = anchor_phi if selection["retain_anchor"] else selection["selected_phi"]
            if not np.isclose(checked_phi, expected, rtol=1e-6, atol=1e-7):
                raise ValueError("Selected ensemble member failed deterministic reproduction")
            anchor_phi = checked_phi
            state["completed_stages"].append({"stage": stage["stage_id"], "phi": anchor_phi})
            model.write_json(RUN / "pipeline_status.json", state)
        final = RUN / "final_parameters.csv"
        pd.DataFrame(list(values.items()), columns=["name", "value"]).to_csv(final, index=False)
        state.update(status="calibration_complete_evaluation_running", final_calibration_phi=anchor_phi)
        model.write_json(RUN / "pipeline_status.json", state)
        # Validation is accessed only after all selection decisions are frozen.
        eval_obs = pd.read_csv(CONFIG / "locked_evaluation_observations.csv").fillna("")
        if model.sha(CONFIG / "locked_evaluation_observations.csv") != design["evaluation_catalog_sha256"]:
            raise ValueError("Locked evaluation catalog changed")
        comparisons = []
        for dataset in design["datasets"]:
            treatments = [tn for role, tns in dataset["roles"].items() if role != "calibration" for tn in tns]
            if not treatments:
                continue
            work = model.simulate(RUN / "evaluation" / dataset["season_id"], dataset, treatments, values,
                                  executable_sha256=design['dssat_executable_sha256'])
            part = eval_obs[eval_obs.season_id.eq(dataset["season_id"])]
            comparisons.append(model.extract_evaluation_observations(work, part))
        evaluated = pd.concat(comparisons, ignore_index=True)
        evaluated.to_csv(RUN / "evaluation_comparison.csv", index=False)
        metric_rows = []
        for (season, role, variable), part in evaluated.groupby(["season_id", "dataset_role", "variable"]):
            n_total = len(part)
            part = part[part.simulated.notna()]
            if part.empty:
                metric_rows.append(dict(season_id=season, dataset_role=role, variable=variable,
                    n_total=n_total, n=0, n_model_unmatched=n_total, rmse=None, nrmse=None, d_index=None, mean_bias=None))
                continue
            y, p = part.observed.to_numpy(), part.simulated.to_numpy()
            rmse = float(np.sqrt(np.mean((p-y)**2)))
            denom = float(np.sum((np.abs(p-y.mean()) + np.abs(y-y.mean()))**2))
            metric_rows.append(dict(season_id=season, dataset_role=role, variable=variable, n_total=n_total,
                n=len(part), n_model_unmatched=n_total-len(part),
                rmse=rmse, nrmse=rmse/float(y.mean()) if y.mean() else None,
                d_index=1-float(np.sum((p-y)**2))/denom if denom else None, mean_bias=float(np.mean(p-y))))
        pd.DataFrame(metric_rows).to_csv(RUN / "evaluation_metrics.csv", index=False)
        state.update(status="completed_pending_scientific_review", finished_at=stamp(),
                     final_parameters_sha256=model.sha(final), validation_reported_after_selection=True)
        model.write_json(RUN / "pipeline_status.json", state)
    except Exception as error:
        state.update(status="failed", error=str(error), failed_at=stamp())
        model.write_json(RUN / "pipeline_status.json", state)
        raise


def launch():
    model.load_design(DESIGN)
    status = RUN / "pipeline_status.json"
    if status.exists():
        raise FileExistsError("Pipeline already started; inspect status before any new launch")
    with (RUN / "controller.stdout.log").open("w", encoding="utf-8") as out, (RUN / "controller.stderr.log").open("w", encoding="utf-8") as err:
        process = subprocess.Popen([sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--run-id", ID, "--pipeline"],
                                   cwd=ROOT, stdout=out, stderr=err,
                                   creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    model.write_json(RUN / "launch_receipt.json", {"launched_at": stamp(), "pid": process.pid,
        "design_sha256": model.sha(DESIGN), "user_authorization": "启动正式参数率定", "formal_calibration_started": True})
    print(f"Formal pipeline launched, PID={process.pid}, run={RUN}", flush=True)


def smoke_pest():
    """Exercise the actual binary/adapter/INS/TPL with three prior-only members."""
    global RUN
    design, bounds, obs = model.load_design(DESIGN)
    actual_run = RUN
    try:
        RUN = actual_run / 'interface_smoke'
        RUN.mkdir(exist_ok=True)
        stage = {**design['stages'][0], 'stage_id': 'interface_v2', 'noptmax': -1}
        target = build_stage(stage, model.validate_parameters(dict(zip(bounds.name, bounds.init)), bounds))
        pst = pyemu.Pst(str(target/'interface_v2.pst'))
        ensemble = pd.DataFrame([dict((k.lower(),v) for k,v in model.validate_parameters(dict(zip(bounds.name,bounds.init)),bounds).items())]*3,
                               index=['positive', 'negative', 'base'])
        em_fl = bounds.set_index('name').loc['EM-FL']
        ensemble.loc['positive','em-fl'] += .2*(em_fl.upper-em_fl.lower)
        ensemble.loc['negative','em-fl'] -= .2*(em_fl.upper-em_fl.lower)
        ensemble.to_csv(target/'smoke_ensemble.csv')
        pst.pestpp_options['ies_par_en'] = 'smoke_ensemble.csv'
        pst.pestpp_options['ies_num_reals'] = 3
        pst.pestpp_options['rand_seed'] = 20261011
        pst.write(str(target/'interface_v2.pst'), version=1)
        logged([str(ROOT/'pestpp-5.2.16-win/bin/pestpp-ies.exe'), 'interface_v2'], target/'binary_smoke.log', cwd=target)
        outputs = pd.read_csv(target/'interface_v2.0.obs.csv', index_col=0)
        if len(outputs) != 3 or not set(obs.obsnme).issubset(outputs.columns) or not np.isfinite(outputs[obs.obsnme]).all().all():
            raise ValueError('PEST++ smoke did not return all 423 observations for all three members')
        model.write_json(actual_run/'interface_smoke/report.json', dict(passed=True, members=3,
            noptmax=-1, parameters_optimized=False, objective_count=423, finite_full_objective=True))
        print('Actual PEST++/DSSAT interface smoke passed', flush=True)
    finally:
        RUN = actual_run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--launch", action="store_true")
    parser.add_argument("--pipeline", action="store_true")
    parser.add_argument("--smoke-pest", action="store_true")
    parser.add_argument("--run-id", default=ID)
    parser.add_argument("--prepare-repair", metavar="FAILED_RUN_ID")
    args = parser.parse_args()
    use_run(args.run_id)
    if args.prepare_repair:
        prepare_repair(args.prepare_repair)
    if args.prepare:
        prepare()
    if args.preflight:
        preflight()
    if args.launch:
        launch()
    if args.smoke_pest:
        smoke_pest()
    if args.pipeline:
        pipeline()


if __name__ == "__main__":
    main()
