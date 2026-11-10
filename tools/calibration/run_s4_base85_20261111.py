#!/usr/bin/env python3
"""run_s4_base85_20261111.py -- S4 formal calibration on the spring58
objective machinery (approved 2026-11-11).

Design decisions (user-approved):
- Objective budget fully inherits spring58 EXCEPT the two signed
  fresh-yield contrast families (W2_W1 x4, N2_N0 x3), whose budgets are
  CANCELLED (moved to diagnostic; total budget 85, 504 active objectives).
- Parameter ranges must COVER the S4 diagnostic figure's parameter point
  (best_params_s4.csv from the s4 50x4 IES, good N-response curve):
  active params widen to contain it; fixed params that differ are
  re-fixed at the S4 value (all changes recorded in range_changes.csv).
- Two soil-baseline arms: A = xxql2601_final_20261105 (measured SASC),
  B = xxql2601_final_sasc70_20261106; both validate on LWAD 20261108.

Subcommands: bounds | catalog | build | screen | joint | finalize | compare
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.calibration import run_dual_morris98_trial_20261105 as trial
from tools.sa import run_dual_spring_morris_20261105 as native

SPRING58 = ROOT / "workspace/runs/eggplant_final_springs_58_restored_bounds_40x3_8agents_20261107"
S4_DIAG = ROOT / "workspace/runs/s4_diag_20261108"
BOUNDS_ID = "eggplant_s4_base85_s4point_40x3_20261111"
ARM_A = "eggplant_s4_base85_sascdefault_40x3_8agents_20261111"
ARM_B = "eggplant_s4_base85_sasc70_40x3_8agents_20261111"
ENGINE = ROOT / ".local/build-v15-s4-nstate/bin/dscsm048"
ENGINE_SHA = "cf9464ba88581325e0dfed0a4ecda918e7a306c1ba6cd108aedc7d222d0da2a8"
STD_DIR = ROOT / ".local/s4-std"
NML_RU = ROOT / "subprojects/critical_n/n_buffer_v15/source/v15_s3_v4root/RootUptake.nml.template"
NML_NS = ROOT / "subprojects/critical_n/n_buffer_v15/source/v15_s4_nstate/NState.nml.template"
NBUF_CARD = ("!*ORGAN NITROGEN RESERVES AND BUFFER DILUTION\n"
             " 1.000 0.030 0.370 0.020 0.078 0.100 0.100 0.000"
             " 0.028 1.000 0.500 0.091 1.770 4.524 2.400  40.0\n")
CONTRAST_FAMILIES = {"W2_W1_SIGNED_CONTRAST", "N2_N0_SIGNED_CONTRAST"}
BUNDLES = {
    "A": ROOT / "data/user/experiments/xxql2601_final_20261105",
    "B": ROOT / "data/user/experiments/xxql2601_final_sasc70_20261106",
}
VALIDATION_BUNDLE = ROOT / "data/user/experiments/xxql2501_refreshed_lwad_20261108"


def sha256(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ---------------------------------------------------------------- bounds
def s4_cover_points() -> dict[str, float]:
    """Both S4-lineage calibration points that the new bounds must cover:
    1) best_params_s3.csv -- the parameter point behind the
       diagnostic_s4_fresh_2x2.png S4 panel (S3-calibrated kernel-2 point
       replayed on the S4 engine; the user-cited good N-response curve).
    2) the S4 own 50x4 IES best member (v15s4_k2s2 run, phi 124.5)."""
    pts: dict[str, list[float]] = {}
    fig = pd.read_csv(ROOT / "workspace/runs/v4root_ab_diag_20261108"
                      "/best_params_s3.csv")
    for _, r in fig.iterrows():
        pts.setdefault(str(r.iloc[0]).strip(), []).append(float(r.iloc[1]))
    run = ROOT / "workspace/runs/v15s4_k2s2_smoke_50x4_20261108"
    phi = pd.read_csv(run / "s4k2psi50x4.phi.actual.csv")
    last = phi.iloc[-1]
    fixed = {"iteration", "total_runs", "mean", "standard_deviation",
             "min", "max"}
    best, bv = None, float("inf")
    for m in last.index:
        if m in fixed or last[m] in ("", None):
            continue
        v = float(last[m])
        if v < bv:
            best, bv = m, v
    par = pd.read_csv(run / "s4k2psi50x4.4.par.csv")
    row = par[par.real_name.astype(str) == best].iloc[0]
    for col in par.columns[1:]:
        pts.setdefault(col.strip(), []).append(float(row[col]))
    flat = {k: (vs[0] if len(vs) == 1 else sum(vs) / len(vs))
            for k, vs in pts.items()}
    # Six spring58 params absent from the S4-lineage 126-param sets had
    # their in-effect values fixed by the c31 bounds (the machinery behind
    # the S4 figure runs) -- carry those over as cover points too.
    c31 = pd.read_csv(ROOT / "data/parameter_registry/bounds_frozen/eggplant"
                      "/eggplant_26sp_cal25sp_val_cold_c31pst_noadat_80x4_20261106.csv")
    for _, r in c31.iterrows():
        if str(r["name"]) not in flat and str(r["native_name"]) in flat:
            continue
        for key in (r["name"], r["native_name"]):
            if key not in flat and r["name"] in {
                    "YLEAF(4)", "YSTEM(4)", "YRTFAC(2)", "YTRFAC(2)",
                    "XSWFAC(3)", "YSWFAC(2)"}:
                flat[str(key)] = float(r["init"])
    print(f"cover points: figure={len(fig)} params, s4_ies member={best} "
          f"(phi {bv:.3f}); union={len(flat)} params")
    return flat


def step_bounds():
    """Derive bounds covering the S4 points; freeze via the project
    freeze_bounds discipline; print the change list."""
    b = pd.read_csv(ROOT / "data/parameter_registry/bounds_frozen/eggplant/"
                    "eggplant_final_springs_58_restored_bounds_40x3_8agents_20261107.csv")
    s4 = s4_cover_points()
    fmt = lambda v: native.format_field(v)
    changes = []
    rows = []
    for r in b.itertuples():
        name, pest = r.name, r.pest_name
        s4v = s4.get(pest) or s4.get(name)
        if s4v is None:
            print(f"WARN no S4 value for {name}")
            rows.append(r._asdict())
            continue
        if r.status == "active":
            lo, hi = float(r.lower), float(r.upper)
            nlo, nhi = min(lo, s4v), max(hi, s4v)
            if (nlo, nhi) != (lo, hi):
                changes.append(dict(name=name, kind="active_widen",
                                    lower=lo, upper=hi, new_lower=nlo,
                                    new_upper=nhi, s4_value=s4v))
            d = r._asdict()
            d["lower"], d["upper"] = nlo, nhi
            d["init"] = float(r.init) if nlo <= float(r.init) <= nhi else s4v
            rows.append(d)
        else:
            if fmt(float(r.init)) != fmt(s4v):
                changes.append(dict(name=name, kind="refix_at_s4",
                                    fixed=r.init, s4_value=s4v))
                d = r._asdict()
                # frozen-bounds contract: fixed rows need lower=init=upper
                d["init"] = d["lower"] = d["upper"] = s4v
                rows.append(d)
            else:
                rows.append(r._asdict())
    out = pd.DataFrame(rows)
    assert (out.lower <= out.upper).all()
    proposal = ROOT / "data/parameter_registry/bounds_proposals/eggplant" / \
        (BOUNDS_ID + ".csv")
    out.to_csv(proposal, index=False)
    chg = pd.DataFrame(changes)
    chg.to_csv(ROOT / "workspace/runs/s4_bounds_range_changes_20261111.csv",
               index=False)
    print(f"active widen: {sum(c['kind']=='active_widen' for c in changes)}, "
          f"refix: {sum(c['kind']=='refix_at_s4' for c in changes)}")
    print(chg.to_string(index=False) if len(chg) else "(no changes needed)")
    res = subprocess.run(
        [sys.executable, str(ROOT / "tools/freeze_bounds.py"),
         "--proposal", str(proposal), "--crop", "eggplant",
         "--bounds-id", BOUNDS_ID,
         "--notes", "spring58 restored bounds widened/refixed to cover the "
                    "S4-lineage calibration points (s4 fresh-2x2 figure "
                    "point = S3-calibrated kernel-2 replay; S4 own IES best "
                    "member); contrast budgets cancelled (85)"],
        cwd=ROOT, capture_output=True, text=True)
    print(res.stdout[-800:], res.stderr[-800:])
    return res.returncode


# ---------------------------------------------------------------- catalog
def step_catalog():
    """Filter the frozen 511 catalog to 504 active (contrasts -> diagnostic)
    and patch the policy; write into a shared catalog dir."""
    obs = pd.read_csv(SPRING58 / "calibration_observations.csv").fillna("")
    is_contrast = obs.family.isin(CONTRAST_FAMILIES)
    active = obs[~is_contrast].copy()
    diag_new = obs[is_contrast].copy()
    # zero the weights of the moved rows (kept for traceability only)
    diag_new["budget_multiplier"] = 0.0
    diag_new["final_weight"] = 0.0
    existing_diag = SPRING58 / "calibration_diagnostic_observations.csv"
    frames = [active]
    if existing_diag.is_file():
        frames.append(pd.read_csv(existing_diag).fillna(""))
    frames.append(diag_new)
    cat_dir = ROOT / "workspace/runs/s4_base85_catalog_20261111"
    cat_dir.mkdir(parents=True, exist_ok=True)
    active.to_csv(cat_dir / "calibration_observations.csv", index=False)
    pd.concat(frames, ignore_index=True).to_csv(
        cat_dir / "calibration_diagnostic_observations.csv", index=False)
    pol = pd.read_csv(SPRING58 / "objective_policy.csv")
    pol.loc[pol.family.isin(CONTRAST_FAMILIES),
            ["budget", "diagnostic_only"]] = 0, True
    pol.to_csv(cat_dir / "objective_policy.csv", index=False)
    w = active.groupby("family").final_weight.first() ** 2
    w = w * active.groupby("family").size() / \
        active.groupby("family").size()          # budget per family = n*w^2
    fam_budget = (active.groupby("family").size() *
                  active.groupby("family").final_weight.first() ** 2)
    print(f"active objectives: {len(active)} (contrast moved: {len(diag_new)})")
    print("family budgets:", fam_budget.round(3).to_dict())
    print("TOTAL BUDGET:", round(fam_budget.sum(), 6))
    shutil.copy2(SPRING58 / "locked_validation_observations.csv",
                 cat_dir / "locked_validation_observations.csv")
    return 0


# ---------------------------------------------------------------- build
SEALED_CODE = [
    ROOT / "tools/calibration/run_dual_morris98_trial_20261105.py",
    ROOT / "tools/sa/run_dual_spring_morris_20261105.py",
    ROOT / "src/calibration/sa98_joint40.py",
    ROOT / "src/calibration/all12_joint.py",
    ROOT / "src/calibration/single_season_n.py",
    ROOT / "src/common/param_registry.py",
    ROOT / "src/common/input_manifest.py",
    ROOT / "tools/calibration/run_s4_objectives_20261111.py",
    ROOT / "tools/calibration/run_s4_base85_20261111.py",
]
CAT_DIR = ROOT / "workspace/runs/s4_base85_catalog_20261111"
FORWARD = ROOT / "tools/calibration/run_s4_objectives_20261111.py"


def build_payload(bundle: Path, dest: Path, slpf: float):
    native.model_payload(bundle, dest, slpf)
    spe = dest / "TMGRO048.SPE"
    text = spe.read_text(encoding="utf-8")
    if "ORGAN NITROGEN RESERVES" not in text:
        if not text.endswith("\n"):
            text += "\n"
        spe.write_text(text + "\n" + NBUF_CARD, encoding="utf-8")
    shutil.copy2(NML_RU, dest / "RootUptake.nml")
    shutil.copy2(NML_NS, dest / "NState.nml")


def step_build(arm: str):
    run = ROOT / "workspace/runs" / (ARM_A if arm == "A" else ARM_B)
    if run.exists():
        shutil.rmtree(run)
    run.mkdir(parents=True)
    bundle = BUNDLES[arm]
    for name in ("calibration_observations.csv", "objective_policy.csv",
                 "locked_validation_observations.csv",
                 "calibration_diagnostic_observations.csv"):
        shutil.copy2(CAT_DIR / name, run / name)
    build_payload(bundle, run / "26SP_inputs", 0.89)
    build_payload(VALIDATION_BUNDLE, run / "25SP_inputs", 0.92)
    design = json.loads((SPRING58 / "design.json").read_text(encoding="utf-8"))
    design.update(
        run_id=ARM_A if arm == "A" else ARM_B,
        bounds_id=BOUNDS_ID,
        frozen_bounds=str(ROOT / "data/parameter_registry/bounds_frozen"
                          "/eggplant" / (BOUNDS_ID + ".csv")),
        target_count=504, objective_budget=85.0,
        datasets={
            "25SP": {"path": str(VALIDATION_BUNDLE), "role": "validation",
                     "manifest_sha256": sha256(
                         VALIDATION_BUNDLE / "input_manifest.json")},
            "26SP": {"path": str(bundle), "role": "calibration",
                     "manifest_sha256": sha256(bundle / "input_manifest.json")},
        })
    hashes: dict[str, str] = {}
    for p in SEALED_CODE + [ENGINE,
                            Path(design["frozen_bounds"])]:
        hashes[str(p)] = sha256(p)
    for name in ("calibration_observations.csv", "objective_policy.csv",
                 "locked_validation_observations.csv",
                 "calibration_diagnostic_observations.csv"):
        f = run / name
        hashes[str(f)] = sha256(f)
    for season in ("26SP_inputs", "25SP_inputs"):
        for f in sorted((run / season).iterdir()):
            hashes[str(f)] = sha256(f)
    design["source_hashes"] = hashes
    design["port_s4"] = {
        "derived_from": str(SPRING58),
        "engine": str(ENGINE), "engine_sha256": ENGINE_SHA,
        "objective_changes": ("spring58 budgets inherited; W2_W1 and N2_N0 "
                              "signed-contrast budgets CANCELLED to 0 "
                              "(diagnostic only); total budget 85; 504 "
                              "active objectives (user decision 2026-11-11)"),
        "bounds_derivation": ("spring58 restored bounds; active ranges "
                              "already covered both S4 points (0 widened); "
                              "PORPT/ALPHS/PROSTF re-fixed at S4 values; "
                              "c31 fixed values carried for 6 params"),
        "arm": arm, "arm_bundle_26sp": str(bundle),
        "validation_bundle": str(VALIDATION_BUNDLE),
        "nml_root_kernel": 2, "nml_nstate_mode": 2, "nml_state_tau": 0.0,
        "std_data": str(STD_DIR),
        "std_data_note": "v15 family CDE/SDA/WDA + 485mix CO2048.WDA "
                         "(2026 coverage, cross-engine identical CO2)",
    }
    (run / "design.json").write_text(
        json.dumps(design, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (run / "sealed_design.json").write_text(
        json.dumps({"sha256": sha256(run / "design.json")}, indent=2) + "\n",
        encoding="utf-8")
    bad = [k for k, v in hashes.items() if sha256(Path(k)) != v]
    print(f"arm {arm}: {run.name}; hash gate {len(hashes)-len(bad)}/"
          f"{len(hashes)} pass")
    for k in bad:
        print("  FAIL", k)
    return 1 if bad else 0


# ---------------------------------------------------------------- screen
def step_screen():
    import os
    os.environ.setdefault("DSSAT_CUSTOM_EXE", str(ENGINE))
    os.environ.setdefault("DSSAT_STD_DATA_DIR", str(STD_DIR))
    run = ROOT / "workspace/runs" / ARM_A
    design = trial.read(run / "design.json")
    b = pd.read_csv(design["frozen_bounds"]).rename(
        columns={"name": "registry_name", "native_name": "name"})
    obs = pd.read_csv(run / "calibration_observations.csv").fillna("")
    ctx = trial.contexts(run, design, b, ("26SP", "25SP"))
    params, outputs, base = trial.initial_ensemble(run, b, obs, ctx)
    params.to_csv(run / "initial_ensemble.csv")
    outputs.to_csv(run / "initial_outputs.csv")
    (run / "initial_base.txt").write_text(base + "\n", encoding="utf-8")
    print(f"ensemble: {params.shape}; base candidate {base}")
    return 0


# ---------------------------------------------------------------- joint
def step_joint():
    import pyemu
    import yaml
    run = ROOT / "workspace/runs" / ARM_A
    design = trial.read(run / "design.json")
    b0 = pd.read_csv(design["frozen_bounds"])
    b = b0.rename(columns={"name": "registry_name", "native_name": "name"})
    obs = pd.read_csv(run / "calibration_observations.csv").fillna("")
    params = pd.read_csv(run / "initial_ensemble.csv", index_col=0)
    outputs = pd.read_csv(run / "initial_outputs.csv", index_col=0)
    work = run / "joint"
    work.mkdir(exist_ok=True)
    params.to_csv(work / "initial_ensemble.csv")
    params.loc["base"].rename("value").to_csv(work / "parameters.csv",
                                              index_label="name")
    (work / "parameters.tpl").write_text(
        "ptf ~\nname,value\n" +
        "".join(f"{p},~ {p:<22} ~\n" for p in b.pest_name),
        encoding="ascii")
    (work / "objectives.ins").write_text(
        "pif ~\n" + "".join(f"l1 w !{n}!\n" for n in obs.obsnme),
        encoding="ascii")
    trial.write_outputs(work / "FormalObjectives.OUT", obs.obsnme,
                        outputs.loc["base"])
    pst = pyemu.Pst.from_io_files(
        [str(work / "parameters.tpl")], [str(work / "parameters.csv")],
        [str(work / "objectives.ins")], [str(work / "FormalObjectives.OUT")],
        pst_path=".")
    for r in b.itertuples():
        pst.parameter_data.loc[r.pest_name,
                               ["partrans", "parval1", "parlbnd",
                                "parubnd", "pargp"]] = [
            "none" if r.status == "active" else "fixed",
            params.loc["base", r.pest_name], r.lower, r.upper, r.pargp]
    for r in obs.itertuples():
        pst.observation_data.loc[r.obsnme,
                                 ["obsval", "weight", "obgnme"]] = [
            0.0, r.final_weight, r.family.lower()]
    pst.model_command = [f"python -X utf8 {FORWARD} --forward {run}"]
    pst.control_data.noptmax = 3
    ref = pyemu.Pst(str(SPRING58 / "joint/joint.pst"))
    pst.pestpp_options = dict(ref.pestpp_options)
    pst.pestpp_options["ies_par_en"] = "initial_ensemble.csv"
    pst.write(str(work / "joint.pst"), version=1)
    chk = pyemu.Pst(str(work / "joint.pst"))
    assert chk.npar_adj == 58, chk.npar_adj
    assert chk.nnz_obs == 504, chk.nnz_obs
    assert chk.control_data.noptmax == 3
    (work / "run_manifest.yaml").write_text(yaml.safe_dump(dict(
        run_id=ARM_A, n_params_active=58, n_obs=504,
        ies_num_reals=40, noptmax=3, agents=8, mode="s4_base85",
        bounds_id=BOUNDS_ID, batch_file="DSSBatch.v48",
        harvest_var="CHFPDT", scientific_status="science_pending",
        minimum_member_retention=.98,
        engine=str(ENGINE), engine_sha256=ENGINE_SHA,
        objective_changes="contrast budgets cancelled; total 85",
        design=str(run / "design.json")), sort_keys=False),
        encoding="utf-8")
    print(f"joint: npar_adj={chk.npar_adj} nnz_obs={chk.nnz_obs}")
    # arm B shares the identical ensemble/joint (only the 26SP payload and
    # design differ); copy and re-point the model command.
    runb = ROOT / "workspace/runs" / ARM_B
    jb = runb / "joint"
    if jb.exists():
        shutil.rmtree(jb)
    shutil.copytree(work, jb)
    pstb = pyemu.Pst(str(jb / "joint.pst"))
    pstb.model_command = [f"python -X utf8 {FORWARD} --forward {runb}"]
    pstb.write(str(jb / "joint.pst"), version=1)
    print("arm B joint copied + re-pointed")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["bounds", "catalog", "build", "screen",
                                     "joint", "finalize", "compare"])
    ap.add_argument("--arm", default="A", choices=["A", "B"])
    a = ap.parse_args()
    if a.step == "build":
        return step_build(a.arm)
    return {"bounds": step_bounds, "catalog": step_catalog,
            "screen": step_screen, "joint": step_joint}[a.step]()


if __name__ == "__main__":
    raise SystemExit(main())


if __name__ == "__main__":
    raise SystemExit(main())
