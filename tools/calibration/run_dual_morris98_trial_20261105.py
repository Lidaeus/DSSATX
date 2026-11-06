"""Build and execute the approved 80-member dual-Morris calibration trial."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.calibration.all12_joint import check_relations
from src.calibration.sa98_joint40 import encode, extract
from src.common.input_manifest import verify_calibrated_input_bundle
from tools.sa import run_dual_spring_morris_20261105 as native

ID = "eggplant_26sp_cal25sp_val_dual_morris98_80x4_20261105"
BOUNDS_ID = ID + "_spaced"
REVIEW = ROOT / "configs/calibration_proposals/eggplant_26sp_cal25sp_val_dual_morris98_20261105"
INDEX = ROOT / "configs/experiments/current_bundles.json"
EXE = Path("C:/DSSAT48/DSCSM048.EXE")
MEMBERS, UPDATES, WORKERS, SEED = 80, 4, 6, 20261105
DATES = {"25SP": "2025-05-01", "26SP": "2026-05-02"}
PREVIOUS = {"25SP": 25112, "26SP": 26110}
SLPF = {"25SP": .90, "26SP": .89}
LATE_ANTHESIS = {"EM-FL": (24, 35), "TO12": (23, 27.5),
                  "TB2": (9.5, 12.5), "TM2": (34, 44)}
C31_DOMAIN = ("PGEFF", "TO11", "TRIFL", "SLAVR", "FL-SD", "VSSINK", "PODUR",
              "SFDUR", "TB1", "EM-V1", "LFMAX", "LNGSH", "XMAGE", "XSWBAR(3)",
              "XFRT", "YSWBAR(3)", "PM06", "PROLFI", "TM1", "FL-SH", "NMOBMX",
              "DSWBAR", "SIZLF", "NSTFAC", "RHGHT", "FNPGN(1)", "CMOBMX",
              "RTNO3", "ATOP")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def revise_bundle(source, season):
    parent = verify_calibrated_input_bundle(source)
    manifest = parent.raw
    target = source.with_name(source.name.removesuffix("_20261105") + "_adat_20261105")
    if target.exists():
        revised = verify_calibrated_input_bundle(target)
        if revised.raw["anthesis_revision"]["parent_manifest_sha256"] != parent.manifest_sha256:
            raise ValueError(f"Unexpected parent of {target}")
        return target
    with TemporaryDirectory(dir=source.parent) as tmp:
        stage = Path(tmp) / target.name
        shutil.copytree(source, stage)
        date = pd.Timestamp(DATES[season])
        code = int(date.strftime("%y%j"))
        old = PREVIOUS[season]
        tma = next(stage.glob("*.TMA"))
        lines = tma.read_bytes().splitlines(keepends=True)
        updated = 0
        for i, line in enumerate(lines):
            cells = line.split()
            if cells and cells[0].isdigit():
                assert int(line[12:18]) == old == int(cells[2])
                lines[i] = line[:12] + f"{code:6d}".encode("ascii") + line[18:]
                updated += 1
        tma.write_bytes(b"".join(lines))
        a_path = stage / "FileA_values.csv"
        a = pd.read_csv(a_path)
        assert len(a) == updated and a.ADAT.eq(old).all()
        a["ADAT"] = float(code)
        a.to_csv(a_path, index=False)
        assert [int(line.split()[2]) for line in lines if line.split() and line.split()[0].isdigit()] == [code] * len(a)
        revision = dict(parent_bundle=source.name, parent_manifest_sha256=parent.manifest_sha256,
                        source="User supplied revised observed anthesis date",
                        old_adat=old, new_adat=code, date=DATES[season], treatments=updated,
                        inherited_input_audits="Historical audit snapshots from the parent bundle")
        decision = read(stage / "decision_record.json")
        decision["spring_anthesis"] = "user_confirmed_ADAT;25SP_2025-05-01;26SP_2026-05-02"
        decision["anthesis_revision"] = revision
        native.write(stage / "decision_record.json", decision)
        provenance = read(stage / "source_provenance.json")
        provenance["anthesis_revision"] = revision
        native.write(stage / "source_provenance.json", provenance)
        manifest.update(bundle_id=target.name, decision_record=decision, anthesis_revision=revision,
                        source_provenance_sha256=native.sha(stage / "source_provenance.json"),
                        generator_sha256=native.sha(Path(__file__)))
        for entry in manifest["files"]:
            p = stage / entry["name"]
            entry.update(sha256=native.sha(p), bytes=p.stat().st_size)
        native.write(stage / "input_manifest.json", manifest)
        verify_calibrated_input_bundle(stage)
        stage.rename(target)
    return target


def observation_catalog(bundle, season):
    role = "calibration" if season == "26SP" else "validation"
    u = pd.read_csv(bundle / "observation_uncertainty.csv")
    u = u[u.variable.isin(("LAID", "LWAD", "SWAD", "CHTD", "HFPOW", "CHFPW", "HPODW", "CHPDT"))]
    u = u.rename(columns={"unrounded_source_mean": "observed"})
    common = ["trno", "date", "variable", "observed", "raw_sd", "n_rep"]
    organs = {"\u53f6": "LEAF_N_PCT", "\u830e": "STEM_N_PCT", "\u679c": "FRUIT_N_PCT"}
    n = pd.read_csv(bundle / "plant_npk_source_values.csv")
    n["variable"] = n.organ.map(organs)
    n["N"] /= 10
    n = n.groupby(["trno", "date", "variable"], as_index=False).N.agg(
        observed="mean", raw_sd="std", n_rep="count")
    water = pd.read_csv(bundle / "soil_water_observations.csv")
    water = water[water.phi_role.eq("soil_water_phi")].rename(columns={"vwc_mean": "observed", "vwc_sd": "raw_sd"})
    water = water.assign(variable="VWC")[common + ["depth_label", "depth_top_cm",
                                                   "depth_bottom_cm", "dssat_layer_weights"]]
    a = pd.read_csv(bundle / "FileA_values.csv")
    dates = pd.to_datetime(a.ADAT.astype(int).astype(str), format="%y%j")
    pdats = pd.to_datetime(a.PDAT.astype(int).astype(str), format="%y%j")
    assert dates.dt.strftime("%Y-%m-%d").eq(DATES[season]).all()
    phenology = pd.DataFrame(dict(trno=a.TRNO.astype(int), date=dates.dt.strftime("%Y-%m-%d"),
                                  variable="ADAP", observed=(dates-pdats).dt.days, raw_sd=0, n_rep=1))
    out = pd.concat([u[common], n, water, phenology], ignore_index=True)
    return out.assign(season_id=season, role=role)


def objectives(catalog, bundle, policy):
    metadata = pd.read_csv(bundle / "treatment_metadata.csv")
    trt = {(r.water_level, r.nitrogen_level): int(r.treatment) for r in metadata.itertuples()}
    fresh = catalog[catalog.variable.eq("CHFPW")].sort_values("date").groupby("trno").tail(1).set_index("trno")
    pairs = {
        "W_SIGNED_CONTRAST": [(trt[w, f"N{i}"], trt["W1", f"N{i}"]) for i in range(4) for w in ("W2", "W3")],
        "N_ADJACENT_SIGNED_CONTRAST": [(trt[w, f"N{i+1}"], trt[w, f"N{i}"]) for w in ("W1", "W2", "W3") for i in range(3)],
    }
    groups = []
    for p in policy[policy.budget.gt(0)].itertuples():
        if p.family in pairs:
            rows = []
            for hi, lo in pairs[p.family]:
                a, b = fresh.loc[hi], fresh.loc[lo]
                assert a.date == b.date
                rows.append(a.to_dict() | dict(trno=hi, paired_trno=lo, variable=p.variable,
                                              observed=a.observed-b.observed, raw_sd=np.hypot(a.raw_sd,b.raw_sd)))
            group = pd.DataFrame(rows)
            strata = ["trno", "paired_trno"]
        else:
            group = catalog[catalog.variable.eq(p.variable)].copy()
            last = group.date.eq(group.groupby("trno").date.transform("max"))
            if p.family.startswith("FINAL_"):
                group = group[last].copy()
            if p.family == "HARVEST_DRY_CUMULATIVE_EARLY":
                group = group[~last].copy()
            strata = ["trno", "depth_label"] if p.variable == "VWC" else ["trno"]
        blocks = group.groupby(strata)
        group["sigma_eff"] = np.sqrt(group.raw_sd**2/p.n_eff + p.floor**2 + (p.cv*group.observed.abs())**2)
        group["budget_multiplier"] = np.sqrt(p.budget / (blocks.ngroups * blocks["observed"].transform("size")))
        group["final_weight"] = group.budget_multiplier
        assert len(group) == p.n_targets and np.isclose((group.final_weight**2).sum(), p.budget)
        groups.append(group.assign(family=p.family, loss=p.loss, huber_delta=p.huber_delta))
    obs = pd.concat(groups, ignore_index=True)
    assert len(obs) == 629 and np.isfinite(obs.sigma_eff).all() and obs.sigma_eff.gt(0).all()
    return obs.assign(obsnme=[f"obs_{i:04d}" for i in range(len(obs))])


def freeze_bounds(run, review):
    source = pd.read_csv(REVIEW / "parameter_selection_and_bounds.csv")
    rows = []
    for p in source.itertuples():
        field = p.morris_parameter
        lo, hi, center = p.proposal_lower, p.proposal_upper, p.proposal_init_or_fixed
        basis = "Morris range or reviewed fixed value"
        if field in C31_DOMAIN:
            lo, hi = p.c31_lower, p.c31_upper
            center = (lo+hi)/2
            basis = "C31 and joint67 historical active working domain"
        if field in LATE_ANTHESIS:
            lo, hi = LATE_ANTHESIS[field]
            center = (lo+hi)/2
            basis = "Late anthesis target; late-date Morris vector evidence and historical temperature limits"
        if field == "LNREF":
            lo, hi, center = 3.6, 6.5, 5.05
            basis = "Envelope of reviewed Morris lower edge and C31 upper edge"
        if field == "SHLAG":
            lo = hi = center = .0022
            basis = "Morris center rounded to fit the native field with a separator"
        pest = p.historical_name.replace("(", "_").replace(")", "").lower()
        rows.append(dict(name=p.historical_name, native_name=field, pest_name=pest,
                         init=float(native.format_field(center)), lower=lo, upper=hi,
                         status=p.proposed_status, pargp=p.location.lower(), location=p.location,
                         file=f"TMGRO048.{p.location}", cultivar="TM0008", ecotype="TM0001",
                         mode="eggplant_stage2", basis=basis))
    b = pd.DataFrame(rows)
    assert set(b.loc[b.status.eq("active"), "native_name"]) == set(review["active_parameters"])
    assert b.pest_name.is_unique
    proposal = run / "approved_trial_bounds.csv"
    b.to_csv(proposal, index=False)
    frozen = ROOT / "data/parameter_registry/bounds_frozen/eggplant" / f"{BOUNDS_ID}.csv"
    if frozen.exists():
        from src.common.param_registry import assert_valid_frozen_bounds
        assert_valid_frozen_bounds(frozen)
        pd.testing.assert_frame_equal(pd.read_csv(frozen), pd.read_csv(proposal))
        return frozen
    subprocess.run([sys.executable, str(ROOT / "tools/freeze_bounds.py"), "--proposal", str(proposal),
                    "--crop", "eggplant", "--bounds-id", BOUNDS_ID, "--notes",
                    "User authorized 80x4 trial; historical working bounds and updated observed anthesis dates"],
                   check=True, cwd=ROOT)
    return frozen


def prepare(run):
    review = read(REVIEW / "proposal.json")
    for name, digest in review["proposal_sha256"].items():
        assert native.sha(REVIEW / name) == digest, name
    assert native.sha(EXE) == native.EXE_HASH
    index = read(INDEX)
    datasets = {}
    catalog = {}
    for season, p in review["bundles"].items():
        original = ROOT / p["path"]
        assert verify_calibrated_input_bundle(original).manifest_sha256 == p["manifest_sha256"]
        revised = revise_bundle(original, season)
        m = verify_calibrated_input_bundle(revised)
        datasets[season] = dict(path=str(revised), bundle_id=revised.name,
                                manifest_sha256=m.manifest_sha256, role=p["role"], treatments=p["treatments"])
        index["bundles"][season] = dict(bundle_id=revised.name, manifest_sha256=m.manifest_sha256)
        catalog[season] = observation_catalog(revised, season)
        payload = run / f"{season}_inputs"
        with TemporaryDirectory(dir=run) as tmp:
            staged = Path(tmp) / payload.name
            native.model_payload(revised, staged, SLPF[season])
            if payload.exists():
                assert {p.name: native.sha(p) for p in payload.iterdir()} == {
                    p.name: native.sha(p) for p in staged.iterdir()}
            else:
                staged.rename(payload)
    index["notes"] = "Current spring inputs with revised soil carbon/N and user-confirmed spring ADAT."
    policy = pd.read_csv(REVIEW / "proposed_objective_policy.csv")
    obs = objectives(catalog["26SP"], Path(datasets["26SP"]["path"]), policy)
    assert obs.loc[obs.variable.eq("ADAP"), "observed"].eq(49).all()
    assert catalog["25SP"].loc[catalog["25SP"].variable.eq("ADAP"), "observed"].eq(46).all()
    obs.to_csv(run / "calibration_observations.csv", index=False)
    catalog["25SP"].to_csv(run / "locked_validation_observations.csv", index=False)
    policy.assign(approved=True).to_csv(run / "objective_policy.csv", index=False)
    frozen = freeze_bounds(run, review)
    fields = pd.read_csv(frozen).rename(columns={"name": "registry_name", "native_name": "name"})
    for season, ds in datasets.items():
        native.context(Path(ds["path"]), run / f"{season}_inputs", season, fields)
    source_files = [Path(__file__), Path(native.__file__), ROOT / "src/calibration/sa98_joint40.py",
                    ROOT / "src/calibration/all12_joint.py", ROOT / "src/calibration/single_season_n.py",
                    ROOT / "src/common/param_registry.py", ROOT / "src/common/input_manifest.py"]
    sealed_files = [frozen, run / "calibration_observations.csv", run / "locked_validation_observations.csv",
                    run / "objective_policy.csv", REVIEW / "proposal.json", EXE, *source_files]
    for season in datasets:
        sealed_files.extend(sorted((run / f"{season}_inputs").iterdir()))
    design = dict(approved=True, stage="trial", bounds_id=BOUNDS_ID, frozen_bounds=str(frozen),
                  source_review=str(REVIEW / "proposal.json"), datasets=datasets,
                  members=MEMBERS, updates=UPDATES, seed=SEED, workers=WORKERS,
                  active_parameters=review["active_parameters"], target_count=len(obs),
                  anthesis_dates=DATES, anthesis_dap={"25SP": 46, "26SP": 49}, SLPF=SLPF,
                  SASC=-99, ICNS=1, source_hashes={str(p):native.sha(p) for p in sealed_files})
    native.write(run / "design.json", design)
    native.write(INDEX, index)
    return fields, obs, design


def genotype_field(value):
    field = native.format_field(value)
    if value == 10000:
        return "  1.E4"
    return field


def values_for(b, values):
    assert set(values) == set(b.name)
    actual = {}
    for r in b.itertuples():
        value = values[r.name]
        if r.status == "fixed" and not np.isclose(value, r.init, rtol=0, atol=1e-10):
            raise ValueError(f"Fixed parameter changed: {r.name}")
        # DSSAT genotype input reserves a leading blank in each six-column
        # field. A full-width continuous Sobol value can lose its leading
        # digit or decimal point in the native reader.
        for decimals in range(5, -1, -1):
            field = genotype_field(round(value, decimals))
            if field.startswith(" "):
                rounded = float(field)
                break
        else:
            raise ValueError(f"Cannot serialize with a leading blank: {r.name}={value}")
        if not r.lower <= rounded <= r.upper:
            raise ValueError(f"Out of bounds after serializing {r.name}: {rounded}")
        actual[r.name] = rounded
    relations = actual | {f"FNPGN{i}": actual[f"FNPGN({i})"] for i in (1, 2, 3)}
    check_relations(relations)
    if actual["LNREF"] <= actual["FNPGN(1)"] or actual["PROSHG"] > actual["PROSHI"]:
        raise ValueError("Invalid leaf-N or shell protein curve")
    if actual["YLEAF(4)"] + actual["YSTEM(4)"] > 1:
        raise ValueError("Invalid fourth partition node")
    return actual


def simulate(run, work, ctx, values):
    for p in ctx.payload.iterdir():
        shutil.copy2(p, work / p.name)
    lines = {ext: rows.copy() for ext, rows in ctx.templates.items()}
    for name, value in values.items():
        ext, row, offset = ctx.fields[name]
        field = genotype_field(value)
        assert len(field) == 6 and field.startswith(" ")
        text = lines[ext][row]
        lines[ext][row] = text[:offset] + field + text[offset+6:]
    for ext, rows in lines.items():
        path = work / f"TMGRO048.{ext}"
        path.write_text("\n".join(rows) + "\n", encoding="ascii")
        actual = path.read_text(encoding="ascii").splitlines()
        for name, (location, row, offset) in ctx.fields.items():
            if location == ext and native.read_field(actual[row], offset) != values[name]:
                raise ValueError(f"Genotype readback mismatch: {name}")
    with (work / "model.log").open("wb") as log:
        proc = subprocess.run([str(EXE), "CRGRO048", "B", "DSSBatch.v48"], cwd=work,
                              stdout=log, stderr=subprocess.STDOUT, timeout=150)
    err = work / "ERROR.OUT"
    if proc.returncode or (err.exists() and err.read_text(errors="replace").strip()):
        msg = err.read_text(errors="replace").strip() if err.exists() else ""
        raise native.NativeRunError(f"Native code {proc.returncode}: {msg[:1600]}")
    required, _ = native.response_values(work, ctx)
    plant = native.read_daily_output(work / "PlantGro.OUT", ctx.season)
    if not (plant.LAID >= 0).all():
        row = plant[plant.LAID < 0].iloc[0]
        raise native.NativeOutputError(f"{ctx.season} negative daily LAID {row.LAID:g} at {row.name}")
    return required


def evaluate(run, work, ctx, values, obs):
    simulate(run, work, ctx, values)
    return encode(extract(work, obs))


def contexts(run, design, b, seasons=("26SP",)):
    return {s: native.context(Path(design["datasets"][s]["path"]), run / f"{s}_inputs", s, b) for s in seasons}


def status(run, state, **fields):
    from datetime import datetime, timezone
    native.write(run / "pipeline_status.json", dict(status=state, updated_utc=datetime.now(timezone.utc).isoformat(),
                                                    members=MEMBERS, updates=UPDATES, **fields))


def initial_ensemble(run, b, obs, ctx):
    from scipy.stats import qmc
    active = b[b.status.eq("active")]
    center = dict(zip(b.name, b.init))
    samples = qmc.Sobol(len(active), scramble=True, seed=SEED).random_base2(9)
    candidates = [("center", center)] + [
        (f"global_{i:04d}", center | dict(zip(active.name, active.lower + p * (active.upper-active.lower))))
        for i, p in enumerate(samples)
    ]
    screening = run / "initial_feasibility"
    screening.mkdir()

    def evaluate_candidate(task):
        name, vector = task
        try:
            values = values_for(b, vector)
            with TemporaryDirectory(prefix=f"{name}_", dir=screening) as folder:
                work = Path(folder)
                try:
                    result = evaluate(run, work, ctx, values, obs)
                except (native.NativeOutputError, native.NativeRunError, ValueError, KeyError, AssertionError):
                    shutil.copytree(work, screening / name)
                    raise
            return dict(candidate=name, accepted=True, values=values, output=result.pest_output.to_numpy(),
                        phi=float(result.phi_contribution.sum()),
                        anthesis_min=float(result[result.variable.eq("ADAP")].simulated.min()),
                        anthesis_max=float(result[result.variable.eq("ADAP")].simulated.max()))
        except (ValueError, KeyError, AssertionError, native.NativeRunError) as exc:
            return dict(candidate=name, accepted=False, reason=f"{type(exc).__name__}: {exc}")

    accepted, audits, unique = [], [], set()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for start in range(0, len(candidates), WORKERS):
            for row in pool.map(evaluate_candidate, candidates[start:start+WORKERS]):
                if row["accepted"]:
                    key = tuple(row["values"].values())
                    if key in unique:
                        row.update(accepted=False, reason="Duplicate serialized vector")
                    elif len(accepted) < MEMBERS:
                        unique.add(key)
                        accepted.append(row)
                    else:
                        row.update(accepted=False, reason="Eligible after ensemble filled")
                audits.append({k:v for k,v in row.items() if k not in {"output", "values"}})
            pd.DataFrame(audits).to_csv(run / "initial_feasibility_audit.csv", index=False)
            status(run, "preflight", accepted=len(accepted), attempted=len(audits))
            if len(accepted) == MEMBERS:
                break
            if len(audits) >= 18 and not accepted and len({a["reason"] for a in audits}) == 1:
                raise RuntimeError(audits[0]["reason"])
    if len(accepted) != MEMBERS:
        raise RuntimeError(f"Initial feasible ensemble incomplete: {len(accepted)}/{MEMBERS}")
    names = ["base"] + [row["candidate"] for row in accepted[1:]]
    params = pd.DataFrame([row["values"] for row in accepted], index=names).rename(
        columns=dict(zip(b.name, b.pest_name)))
    outputs = pd.DataFrame([row["output"] for row in accepted], index=names, columns=obs.obsnme)
    return params, outputs, accepted[0]["candidate"]


def make_case(run, b, obs, params, outputs):
    import pyemu
    import yaml
    work = run / "joint"
    work.mkdir()
    params.to_csv(work / "initial_ensemble.csv")
    params.loc["base"].rename("value").to_csv(work / "parameters.csv", index_label="name")
    (work / "parameters.tpl").write_text(
        "ptf ~\nname,value\n" + "".join(f"{p},~ {p:<22} ~\n" for p in b.pest_name), encoding="ascii")
    (work / "objectives.ins").write_text(
        "pif ~\n" + "".join(f"l1 w !{name}!\n" for name in obs.obsnme), encoding="ascii")
    write_outputs(work / "FormalObjectives.OUT", obs.obsnme, outputs.loc["base"])
    pst = pyemu.Pst.from_io_files([str(work / "parameters.tpl")], [str(work / "parameters.csv")],
                                 [str(work / "objectives.ins")], [str(work / "FormalObjectives.OUT")], pst_path=".")
    for r in b.itertuples():
        pst.parameter_data.loc[r.pest_name, ["partrans", "parval1", "parlbnd", "parubnd", "pargp"]] = [
            "none" if r.status == "active" else "fixed", params.loc["base", r.pest_name], r.lower, r.upper, r.pargp]
    for r in obs.itertuples():
        pst.observation_data.loc[r.obsnme, ["obsval", "weight", "obgnme"]] = [0., r.final_weight, r.family.lower()]
    pst.model_command = [f'"{sys.executable}" -X utf8 "{Path(__file__)}" --forward "{run}"']
    pst.control_data.noptmax = UPDATES
    pst.pestpp_options = dict(ies_num_reals=MEMBERS, ies_include_base=True, ies_no_noise=True,
                              ies_bad_phi_sigma=1e300, ies_initial_lambda=100., ies_lambda_mults=[.1,1.,10.],
                              lambda_scale_fac=[.05,.1,.25], ies_par_en="initial_ensemble.csv", rand_seed=SEED,
                              ies_drop_conflicts=False, ies_pdc_sigma_distance=0., ies_subset_size=30,
                              panther_agent_no_ping_timeout_secs=600)
    pst.write(str(work / "joint.pst"), version=1)
    check = pyemu.Pst(str(work / "joint.pst"))
    assert check.npar_adj == 58 and check.nnz_obs == 629 and check.control_data.noptmax == 4
    (work / "run_manifest.yaml").write_text(yaml.safe_dump(dict(run_id=ID, n_params_active=58, n_obs=629,
        ies_num_reals=MEMBERS, noptmax=UPDATES, agents=WORKERS, mode="eggplant_stage2", bounds_id=BOUNDS_ID,
        batch_file="DSSBatch.v48", harvest_var="CHPDT", scientific_status="science_pending",
        minimum_member_retention=.98, design=str(run / "design.json")), sort_keys=False), encoding="utf-8")


def write_outputs(path, names, values):
    temp = path.with_suffix(".tmp")
    temp.write_text("".join(f"{n} {v:.12g}\n" for n,v in zip(names, values)), encoding="ascii")
    temp.replace(path)


def forward(run):
    work = Path.cwd()
    output = work / "FormalObjectives.OUT"
    output.unlink(missing_ok=True)
    design = read(run / "design.json")
    assert read(run / "sealed_design.json")["sha256"] == native.sha(run / "design.json")
    for p, h in design["source_hashes"].items():
        assert native.sha(Path(p)) == h, p
    b = pd.read_csv(design["frozen_bounds"]).rename(columns={"name": "registry_name", "native_name": "name"})
    values = pd.read_csv(work / "parameters.csv").set_index("name").value
    try:
        values = values_for(b, dict(zip(b.name, values.loc[b.pest_name])))
        obs = pd.read_csv(run / "calibration_observations.csv").fillna("")
        ctx = contexts(run, design, b)["26SP"]
        with TemporaryDirectory(prefix="model_", dir=work) as temp:
            result = evaluate(run, Path(temp), ctx, values, obs)
        write_outputs(output, obs.obsnme, result.pest_output)
    except Exception as exc:
        with (work / "forward_failures.jsonl").open("a", encoding="utf-8") as log:
            print(json.dumps(dict(error=f"{type(exc).__name__}: {exc}", vector=values if isinstance(values, dict) else values.to_dict())), file=log)
        raise


def finalize(run, b, obs, design, params):
    work = run / "joint"
    selections, rounds, boundaries = [], [], []
    active = b[b.status.eq("active")].set_index("pest_name")
    for iteration in range(UPDATES+1):
        par_path, obs_path = (work / f"joint.{iteration}.{suffix}.csv" for suffix in ("par", "obs"))
        if not par_path.is_file() or not obs_path.is_file():
            rounds.append(dict(iteration=iteration, retained=0, passed=False))
            continue
        p = pd.read_csv(par_path, index_col=0)
        o = pd.read_csv(obs_path, index_col=0)
        pairs = params.index.intersection(p.index).intersection(o.index)
        y = o.loc[pairs, obs.obsnme].to_numpy()
        valid = np.isfinite(y).all(axis=1) & np.isfinite(p.loc[pairs, b.pest_name]).all(axis=1)
        pairs = pairs[valid]
        phi = pd.Series(np.square(y[valid] * obs.final_weight.to_numpy()).sum(axis=1), index=pairs)
        passed = len(pairs)/MEMBERS >= .98
        rounds.append(dict(iteration=iteration, retained=len(pairs), passed=passed,
                           min_phi=phi.min(), median_phi=phi.median()))
        if passed:
            for name, score in phi.items():
                v = p.loc[name, b.pest_name]
                selections.append((float(score), iteration, str(name), v))
        if iteration >= UPDATES-1 and len(pairs):
            positions = (p.loc[pairs, active.index]-active.lower)/(active.upper-active.lower)
            for name in active.index:
                x = positions[name]
                boundaries.append(dict(iteration=iteration, parameter=active.loc[name, "name"],
                    members=len(x), near_lower=float(x.le(.02).mean()), near_upper=float(x.ge(.98).mean()),
                    severe_lower=float(x.le(.005).mean()), severe_upper=float(x.ge(.995).mean())))
    pd.DataFrame(rounds).to_csv(run / "round_quality.csv", index=False)
    pd.DataFrame(boundaries).to_csv(run / "parameter_boundary_round3_4.csv", index=False)
    if not selections:
        raise RuntimeError("No completed round met the retention gate")
    score, iteration, member, v = min(selections, key=lambda row: row[:3])
    values = values_for(b, dict(zip(b.name, v)))
    ctx = contexts(run, design, b, ("26SP", "25SP"))
    out = run / "selected_deterministic"
    out.mkdir()
    compared = evaluate(run, out, ctx["26SP"], values, obs)
    phi = float(compared.phi_contribution.sum())
    if not np.isclose(phi, score, rtol=1e-6, atol=1e-8):
        raise ValueError(f"Deterministic Phi differs: {score} vs {phi}")
    compared.to_csv(run / "calibration_comparison.csv", index=False)
    best = run / "best_calibration_parameters.csv"
    pd.Series(values, name="value").to_csv(best, index_label="name")
    native.write(run / "selection.json", dict(iteration=iteration, member=member, phi=phi,
                 validation_used=False, parameters_sha256=native.sha(best)))
    validation = run / "validation"
    validation.mkdir()
    simulate(run, validation, ctx["25SP"], values)
    catalog = pd.read_csv(run / "locked_validation_observations.csv").fillna("")
    extract(validation, catalog, strict=False).to_csv(run / "validation_comparison.csv", index=False)
    fruit = observation_catalog(Path(design["datasets"]["26SP"]["path"]), "26SP")
    extract(out, fruit[fruit.variable.eq("FRUIT_N_PCT")], strict=False).to_csv(
        run / "calibration_fruit_n_diagnostic.csv", index=False)
    engineering = read(work / "run_status.json").get("engineering_status")
    status(run, "completed", selected_phi=phi, selected_iteration=iteration, selected_member=member,
           retained=rounds[-1]["retained"], all_rounds_passed=all(row["passed"] for row in rounds),
           engineering_status=engineering, scientific_status="science_pending_trial")


def controller(run):
    run.mkdir(exist_ok=True)
    if (run / "design.json").exists() or (run / "joint").exists():
        raise FileExistsError(f"Existing trial {run}")
    try:
        status(run, "preparing")
        b, obs, design = prepare(run)
        obs = obs.fillna("")
        params, outputs, base = initial_ensemble(run, b, obs, contexts(run, design, b)["26SP"])
        design.update(initial_ensemble_base=base, initial_members=len(params))
        native.write(run / "design.json", design)
        native.write(run / "sealed_design.json", dict(sha256=native.sha(run / "design.json")))
        make_case(run, b, obs, params, outputs)
        status(run, "running", phase="pest_ies", initial_members=len(params))
        with (run / "parallel_controller.log").open("wb") as log:
            subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tools/parallel/run_parallel.py"),
                            "--run-dir", str(run / "joint"), "--case", "joint", "--mode", "ies",
                            "--n-agents", str(WORKERS), "--wait"], cwd=ROOT, stdout=log,
                           stderr=subprocess.STDOUT, check=True)
        if read(run / "joint/run_status.json")["status"] != "completed":
            raise RuntimeError("PEST++ did not complete")
        status(run, "postprocessing")
        finalize(run, b, obs, design, params)
    except Exception as exc:
        previous = read(run / "pipeline_status.json")
        status(run, "failed", phase=previous["status"], error=f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    mode = cli.add_mutually_exclusive_group(required=True)
    mode.add_argument("--start", action="store_true")
    mode.add_argument("--forward", type=Path)
    args = cli.parse_args()
    if args.start:
        controller(ROOT / "workspace/runs" / ID)
    else:
        forward(args.forward)
