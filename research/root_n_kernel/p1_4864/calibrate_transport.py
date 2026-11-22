"""Stage, audit, and calibrate the steady 26SP transport."""

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import traceback

import numpy as np
import pandas as pd
import pyemu
from scipy.stats import qmc

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "research/n_diagnostics"))
from data import native_table
from portable_dssat import prepare_case, run
from verify_p1 import audit

CONFIG = HERE / "p1_smoke.nml"
TEMPLATE = HERE.parent / "source/RootNUptake.nml.template"
SEED = 20261107
PHYSICAL_DATA = ("DSSBatch.v48", "XXQL2601.TMX", "XXQL2601.TMA", "XXQL2601.TMT",
                 "SOIL.SOL", "XXTW2403.WTH")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def normalized_bounds(path):
    bounds = pd.read_csv(path, dtype={"name": str}).set_index("name", verify_integrity=True)
    if len(bounds) != 18 or not bounds.init.between(bounds.lower, bounds.upper, inclusive="neither").all():
        raise ValueError("Expected 18 bounded shared parameters with interior starting values")
    return bounds


def full_date(date):
    return int(date.strftime("%Y%j"))


def make_targets(source):
    file_a = pd.read_csv(source / "FileA_values.csv").rename(columns={"TRNO": "treatment"})
    file_t = pd.read_csv(source / "FileT_values.csv").rename(columns={"TRNO": "treatment", "DATE": "date_code"})
    file_t["date"] = pd.to_datetime(file_t.date_code.astype(int).astype(str), format="%y%j")
    uncertainty = pd.read_csv(source / "observation_uncertainty.csv")
    uncertainty["date"] = pd.to_datetime(uncertainty.date)
    uncertainty = uncertainty.rename(columns={"trno": "treatment"})
    uncertainty["se"] = uncertainty.raw_sd / uncertainty.n_rep.pow(.5)
    rows = []

    def add(name, source_variable, series, fraction, filename, column, interval=False):
        data = series.copy()
        if name == "anthesis":
            data["sigma"] = 1.0
        else:
            se = uncertainty.loc[uncertainty.variable.eq(source_variable), ["treatment", "date", "se"]]
            data = data.merge(se, on=["treatment", "date"], how="left", validate="one_to_one")
            if not (data.se.notna() & data.se.ge(0)).all():
                raise ValueError(f"Missing or invalid uncertainty for {name}")
            data["sigma"] = data.se.clip(lower=data.loc[data.se.gt(0), "se"].median())
        if not (data.observed.ge(0) & data.sigma.gt(0)).all():
            raise ValueError(f"Invalid observations for {name}")
        data["weight"] = (fraction / len(data)) ** .5 / data.sigma
        for record in data.itertuples(index=False):
            day = full_date(record.date)
            rows.append(dict(name=f"{name}_{int(record.treatment):02}_{day%1000:03}",
                             group=name, treatment=int(record.treatment), yrdoy=day, file=filename,
                             column=column, observed=record.observed, sigma=record.sigma,
                             weight=record.weight,
                             interval_start=record.interval_start if interval else 0))

    harvest = file_t.loc[file_t.CHFPW.ge(0)].sort_values(["treatment", "date"]).copy()
    if not harvest.groupby("treatment").size().eq(5).all():
        raise ValueError("Expected five observed harvests per treatment")
    harvest["ordinal"] = harvest.groupby("treatment").cumcount() + 1
    harvest["interval_start"] = harvest.date.map(full_date).groupby(harvest.treatment).shift().fillna(0).astype(int)
    terminal = harvest.loc[harvest.ordinal.eq(5), ["treatment", "date", "CHFPW"]].merge(
        file_a[["treatment", "HWAHF"]], on="treatment", validate="one_to_one")
    if not terminal.CHFPW.eq(terminal.HWAHF).all():
        raise ValueError("FileA and terminal FileT fresh yield differ")
    add("fresh_end", "CHFPW", terminal.rename(columns={"HWAHF": "observed"}), .35, "FreshWt.OUT", "CHFPW")
    add("fresh_inc", "HFPOW", harvest.loc[harvest.ordinal.lt(5)].rename(columns={"HFPOW": "observed"}),
        .20, "FreshWt.OUT", "CHFPW", True)
    for variable in ("LAID", "CHTD", "LWAD", "SWAD"):
        observed = file_t.loc[file_t[variable].ge(0), ["treatment", "date", variable]]
        add(variable.lower(), variable, observed.rename(columns={variable: "observed"}),
            .25 / 4, "PlantGro.OUT", variable)
    for raw, variable in (("LNAM", "LNAD"), ("SNAM", "SNAD")):
        observed = file_t.loc[file_t[raw].ge(0) & file_t.date.lt("2026-07-17"), ["treatment", "date", raw]]
        add(variable.lower(), raw, observed.rename(columns={raw: "observed"}), .15 / 2, "PlantN.OUT", variable)
    anthesis = file_a[["treatment", "ADAT", "PDAT"]].copy()
    anthesis["date"] = pd.to_datetime(anthesis.ADAT.astype(int).astype(str), format="%y%j")
    planted = pd.to_datetime(anthesis.PDAT.astype(int).astype(str), format="%y%j")
    anthesis["observed"] = (anthesis.date - planted).dt.days
    add("anthesis", "", anthesis, .05, "Evaluate.OUT", "ADAPS")
    targets = pd.DataFrame(rows)
    if targets.name.duplicated().any() or len(targets) != 336:
        raise ValueError(f"Expected 336 unique physical targets, found {len(targets)}")
    return targets


def stage(args):
    root = args.root.resolve()
    root.mkdir(parents=True)
    source = args.bundle.resolve()
    manifest = json.loads((source / "input_manifest.json").read_text())
    if digest(source / "input_manifest.json") != "2333a67f5c92f6217564eb49062147610e6a11316361e65e599951163b3fab6c":
        raise ValueError("Unexpected frozen 26SP input manifest")
    if not all(digest(source / row["name"]) == row["sha256"] for row in manifest["files"]):
        raise ValueError("Frozen source file hash mismatch")
    args.bounds = args.bounds.resolve()
    normalized_bounds(args.bounds)
    shutil.copyfile(args.bounds, root / "bounds.csv")
    case = prepare_case(argparse.Namespace(config=CONFIG, out=root / "inputs"))
    for name in PHYSICAL_DATA:
        shutil.copyfile(source / name, case / name)
    shutil.copyfile(TEMPLATE, root / "root_template.nml")
    shutil.copyfile(source / "treatment_metadata.csv", root / "treatment_metadata.csv")
    shutil.copyfile(source / "soil_water_observations.csv", root / "soil_water_observations.csv")
    targets = make_targets(source)
    targets.to_csv(root / "targets.csv", index=False)
    engine = args.engine.resolve(strict=True)
    shutil.copy2(engine, root / "dscsm048")
    write_json(root / "input_manifest.json", {
        "commit": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
        "engine_sha256": digest(root / "dscsm048"), "bounds_sha256": digest(root / "bounds.csv"),
        "source_manifest_sha256": digest(source / "input_manifest.json"), "source_files_verified": len(manifest["files"]),
        "sha256": {str(path.relative_to(root)): digest(path) for path in sorted(root.rglob("*")) if path.is_file()},
    })


def exact_edit(text, pattern, replacement):
    text, count = re.subn(pattern, replacement, text)
    if count != 1:
        raise ValueError(f"Expected exactly one {pattern!r} card, found {count}")
    return text


def scalar_fields(path, marker, fields):
    lines = path.read_text(encoding="ascii", errors="strict").splitlines(keepends=True)
    matching = [i for i, line in enumerate(lines) if marker(line)]
    if len(matching) != 1:
        raise ValueError(f"{path} has {len(matching)} matching rows")
    index = matching[0]
    line = lines[index]
    for (start, end), (name, value) in fields.items():
        width = end - start
        for digits in range(8, -1, -1):
            raw = f"{value:.{digits}f}"
            if "." in raw:
                raw = raw.rstrip("0").rstrip(".")
            if len(raw) > width and raw.startswith("0."):
                raw = raw[1:]
            if len(raw) <= width:
                break
        else:
            raise ValueError(f"{name}={value} overflows a fixed-width field")
        line = line[:start] + raw.rjust(end - start) + line[end:]
        if not math.isclose(float(line[start:end]), value, rel_tol=.002, abs_tol=.00001):
            raise ValueError(f"{name} was rounded too far to {float(line[start:end])}")
    lines[index] = line
    path.write_text("".join(lines), encoding="ascii")
    return {name: float(line[start:end]) for (start, end), (name, _) in fields.items()}


def fixed_row(path, identity, start, values):
    header = next(line for line in path.read_text().splitlines() if line.startswith("@"))
    # Fixed-width numeric cards end immediately after each header token.
    fields = {}
    for name, value in values.items():
        token = re.search(rf"(?<!\S){re.escape(name)}(?!\S)", header)
        if token is None or token.end() < start:
            raise ValueError(f"Missing numeric field {name} in {path}")
        fields[(token.end()-5, token.end())] = (name.lower().replace("-", "_"), value)
    return scalar_fields(path, lambda line: line.startswith(identity + " "), fields)


def materialize(root, dest, p):
    shutil.copytree(root / "inputs", dest, dirs_exist_ok=True)
    readback = {}
    readback.update(fixed_row(dest / "TMGRO048.CUL", "TM0008", 32, {
        k: p[k.lower().replace("-", "_")] for k in ("EM-FL", "FL-SH", "SLAVR", "XFRT")}))
    readback.update(fixed_row(dest / "TMGRO048.ECO", "TM0001", 30, {"RHGHT": p["rhght"]}))
    for name, qualifier, start in (("rwumx", "RTDEPI,RFAC1", 36),
                                    ("dswbar", "DSWBAR,XFRMAX", 0),
                                    ("cmobmx", "CMOBMX,CADSTF,CADPR1", 0)):
        readback.update(scalar_fields(dest / "TMGRO048.SPE", lambda line: qualifier in line, {
            (start, start+6): (name, p[name])}))
    # XXSL2601 is the only profile in the frozen soil file.
    readback.update(scalar_fields(dest / "SOIL.SOL", lambda line: bool(re.match(r"^\s+-99\s+0\.13\s+5\.5\s+0\.65\s+", line)), {
        (19, 24): ("sldr", p["sldr"])}))
    nml = (dest / "NIntegration.nml").read_text()
    root_nml = (root / "root_template.nml").read_text()
    scales = [p["vmax_no3_scale"], p["vmax_nh4_scale"]]
    for field, values in (("rnk_vmax_high", (.0003, .0004)), ("rnk_vmax_low", (.0015, .002))):
        numbers = [x * scale for x, scale in zip(values, scales)]
        root_nml = exact_edit(root_nml, rf"(\b{field}\s*=)[^,]+,[^,]+",
                              lambda match: match[1] + ",".join(f"{x:.17g}" for x in numbers))
    for name in ("q_no3_max", "assim_no3_v", "leaf_a", "stem_a", "remob_tau", "protect_beta", "slow_ratio"):
        nml = exact_edit(nml, rf"(\b{name}\s*=)[^,\n]+", lambda match: f"{match[1]}{p[name]:.17g}")
        readback[name] = float(re.search(rf"\b{name}\s*=([^,\n]+)", nml)[1])
    readback.update(dict(vmax_no3_scale=scales[0], vmax_nh4_scale=scales[1]))
    (dest / "NIntegration.nml").write_text(nml + "\n" + root_nml)
    return readback


def extract(dest, targets):
    lookup = {}
    vals = pd.read_csv(io.StringIO(next(line for line in (dest / "Evaluate.OUT").read_text().splitlines()
                                        if line.startswith("@RUN"))[1:] + "\n" + "\n".join(
        line for line in (dest / "Evaluate.OUT").read_text().splitlines() if re.match(r"^\s+\d+\s+XXQL2601", line))),
                       sep=r"\s+").set_index("TN", verify_integrity=True)
    if len(vals) != 12:
        raise ValueError("Evaluate.OUT does not contain 12 treatments")
    lookup["Evaluate.OUT"] = {t: x for t, x in vals.ADAPS.items()}
    for name in targets.file.unique():
        if name == "Evaluate.OUT":
            continue
        frame = native_table(dest / name)
        lookup[name] = frame.set_index(["treatment", "yrdoy"], verify_integrity=True)
    out = {}
    for row in targets.itertuples(index=False):
        if row.file == "Evaluate.OUT":
            value = lookup[row.file][row.treatment]
        else:
            table = lookup[row.file][row.column]
            value = table.loc[(row.treatment, row.yrdoy)]
            if row.interval_start:
                value -= table.loc[(row.treatment, row.interval_start)]
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{row.name} invalid simulated value: {value}")
        out[row.name] = float(value)
    return pd.Series(out)


def simulate(root, p, targets, destination, trace=False):
    destination.mkdir()
    env = dict(os.environ, DSSAT_HOME="./")
    for key in ("DSSAT_N_CONFIG", "DSSAT_ROOT_UPTAKE_NML", "DSSAT_NSTATE_NML", "DSSAT_P0_TRACE"):
        env.pop(key, None)
    if trace:
        env["DSSAT_P0_TRACE"] = "1"
    dest = destination / "A"
    effective = materialize(root, dest, p)
    run([str(root / "dscsm048"), "CRGRO048", "B", "DSSBatch.v48"], dest, "dssat", env)
    write_json(destination / "effective_parameters.json", effective)
    return extract(dest, targets).rename("A").to_frame()


def verify_budgets(dest):
    result = {}
    for file, column, limit in (("PlantNIntegration.csv", "Q_residual", 1e-9),
                                ("PlantABudget.csv", "organic_residual", 1e-5),
                                ("PlantCCash.csv", "CH2O_residual", 1e-4)):
        f = pd.read_csv(dest / file, skipinitialspace=True)
        result[column] = float(f[column].abs().max())
        assert len(f) == 1512 and not f.duplicated(["run", "yrdoy"]).any() and f[column].abs().le(limit).all()
    result["layer_audit"] = audit(dest, 12)
    return result


def prepare_pest(root, directory, members, updates, baseline):
    directory.mkdir()
    names = normalized_bounds(root / "bounds.csv")
    targets = pd.read_csv(root / "targets.csv").set_index("name")
    (directory / "params.tpl").write_text("ptf ~\n" + "".join(f"{name},~ {name:19s} ~\n" for name in names.index))
    (directory / "params.csv").write_text("".join(f"{name},{x:.17g}\n" for name, x in names.init.items()))
    obs = targets.copy()
    obs["simulated"] = baseline["A"]
    (directory / "simulated.ins").write_text("pif ~\n" + "".join(f"l1 !{name}!\n" for name in obs.index))
    (directory / "simulated.txt").write_text("".join(f"{v:.17g}\n" for v in obs.simulated))
    (directory / "root.txt").write_text(str(root) + "\n")
    launcher = directory / "forward.sh"
    launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{Path(__file__).resolve()}" forward\n')
    launcher.chmod(0o755)
    pst = pyemu.Pst.from_io_files([str(directory/"params.tpl")], [str(directory/"params.csv")],
                                  [str(directory/"simulated.ins")], [str(directory/"simulated.txt")], pst_path=".")
    pst.model_command = ["./forward.sh"]
    pst.parameter_data["partrans"] = "none"
    for key, col in (("parval1", "init"), ("parlbnd", "lower"), ("parubnd", "upper")):
        pst.parameter_data[key] = names[col]
    pst.observation_data["obsval"] = obs.observed
    pst.observation_data["weight"] = obs.weight
    pst.observation_data["obgnme"] = obs.group
    pst.control_data.noptmax = updates
    pst.control_data.nphistp = 10
    pst.control_data.nphinored = 10
    lhs = qmc.LatinHypercube(d=len(names), seed=SEED).random(members-1)
    prior = pd.DataFrame(qmc.scale(lhs, names.lower.to_numpy(), names.upper.to_numpy()), columns=names.index)
    prior.index = prior.index.map(str)
    prior.loc["base"] = names.init
    prior.rename_axis("real_name").to_csv(directory / "prior.csv")
    pst.pestpp_options.update(ies_num_reals=members, ies_no_noise=True, ies_include_base=True,
                               rand_seed=SEED, ies_parameter_ensemble="prior.csv",
                               ies_bad_phi_sigma=1e30, ies_drop_conflicts=False, par_sigma_range=6)
    pst.write(str(directory / "transport.pst"), version=1)


def forward():
    directory = Path.cwd()
    root = Path((directory / "root.txt").read_text().strip())
    targets = pd.read_csv(root / "targets.csv")
    p = pd.read_csv(directory / "params.csv", header=None, names=["name", "value"], float_precision="round_trip").set_index("name").value
    dest = directory / "simulated.txt"
    dest.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="dssatx-steady-") as scratch:
        location = Path(scratch) / "run"
        try:
            sims = simulate(root, p, targets, location)
        except Exception:
            with (directory / "forward_errors.log").open("a") as log:
                log.write(f"\n{p.to_dict()}\n{traceback.format_exc()}\n")
            for path in location.glob("*/dssat.log"):
                with (directory / "forward_errors.log").open("a") as log:
                    log.write(f"\n{path.parent.name}\n{p.to_dict()}\n{path.read_text(errors='replace')}\n")
            raise
    tmp = dest.with_suffix(".tmp")
    tmp.write_text("".join(f"{x:.17g}\n" for x in sims["A"]))
    tmp.replace(dest)


def calibrate(args):
    root = args.root.resolve()
    targets = pd.read_csv(root / "targets.csv")
    bounds = normalized_bounds(root / "bounds.csv")
    label = args.operation
    case = root / f"{label}_seed"
    if label == "preflight" and not (root / "baseline_conservation.json").is_file():
        base_output = root / "baseline"
        baseline = simulate(root, bounds.init, targets, base_output, trace=True)
        baseline.to_csv(root / "baseline_simulated.csv", index_label="name")
        write_json(root / "baseline_conservation.json", verify_budgets(base_output / "A"))
    else:
        baseline = pd.read_csv(root / "baseline_simulated.csv", index_col="name")
        if label == "formal" and not (root / "preflight_receipt.json").is_file():
            raise ValueError("A successful isolated preflight is required")
    master = root / label
    if not master.exists():
        prepare_pest(root, case, 6 if label == "preflight" else 50, 1 if label == "preflight" else 4, baseline)
        workers = root / f"{label}_workers"
        workers.mkdir()
        pyemu.os_utils.start_workers(str(case), args.pest, "transport.pst", num_workers=args.workers,
                                     master_dir=str(master), worker_root=str(workers), port=args.port, cleanup=False)
    if "pestpp-ies analysis complete" not in (master / "transport.rec").read_text(errors="replace").lower():
        raise ValueError(f"{master}: PEST did not finish normally")
    stats = pd.read_csv(master / "transport.phi.actual.csv").set_index("iteration")
    expected_updates = 1 if label == "preflight" else 4
    if stats.index.tolist() != list(range(expected_updates + 1)):
        raise ValueError("IES ended before all requested updates")
    entries = stats.iloc[-1, 5:].dropna()
    member = entries.idxmin()
    p = pd.read_csv(master / f"transport.{expected_updates}.par.csv", index_col=0,
                    dtype={"real_name": str}, float_precision="round_trip").loc[member]
    held = root / f"{label}_best"
    simulation = simulate(root, p, targets, held, trace=label == "formal")
    shutil.copyfile(master / f"transport.{expected_updates}.par.csv", held / "posterior.csv")
    p.to_csv(held / "best_params.csv", header=["value"])
    series_targets = targets.set_index("name")
    pairs = series_targets.join(simulation)
    score = float(((pairs.A - pairs.observed) * pairs.weight).pow(2).sum())
    pest_values = pd.read_csv(master / f"transport.{expected_updates}.obs.csv", index_col=0,
                              dtype={"real_name": str}, float_precision="round_trip").loc[member]
    deltas = (simulation.A - pest_values.reindex(simulation.index)).abs()
    replay_delta = float(deltas.max())
    # FreshWt reports 0.1 kg/ha. Intervals subtract two rounded records.
    allowed = series_targets.group.map({"fresh_end": .100000001, "fresh_inc": .200000001}).fillna(1e-7)
    if not math.isclose(score, entries[member], rel_tol=8e-6) or not deltas.le(allowed).all():
        raise ValueError(f"Steady objective replay mismatch: {score} vs {entries[member]}, delta {replay_delta}")
    pairs.to_csv(held / "observed_simulated.csv")
    receipt = {"member": member, "phi": score, "max_pest_output_delta": replay_delta,
               "terminal_members": len(entries), "total_evaluations": int(stats.iloc[-1].total_runs),
               "updates": expected_updates}
    if label == "formal":
        receipt["conservation"] = verify_budgets(held / "A")
    write_json(root / f"{label}_receipt.json", receipt)


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "forward":
        forward()
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("stage", "preflight", "formal"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--bounds", type=Path)
    parser.add_argument("--pest", default="/usr/local/bin/pestpp-ies")
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--port", type=int, default=40271)
    args = parser.parse_args()
    if args.operation == "stage":
        stage(args)
    else:
        calibrate(args)


if __name__ == "__main__":
    main()
