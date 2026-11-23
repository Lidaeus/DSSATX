"""Prepare and optionally run a standalone PEST++ IES mechanism case."""

import argparse
import json
import re
from pathlib import Path
import shutil
import os
import subprocess
import sys

import numpy as np
import pandas as pd
import pyemu

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "n_diagnostics"))
from data import sha
from forward import evaluate


def input_table(path, columns):
    frame = pd.read_csv(path, dtype={"name": str}, float_precision="round_trip")
    missing = set(columns) - set(frame.columns)
    if frame.empty or missing:
        raise ValueError(f"{path}: expected nonempty table with {columns}")
    if frame.name.isna().any() or not frame.name.str.fullmatch(r"[a-z][a-z0-9_]{0,19}").all():
        raise ValueError(f"{path}: invalid PEST names")
    return frame.set_index("name", verify_integrity=True)


def require_fixed_sln_reference(template):
    with template.open(encoding="utf-8-sig") as stream:
        header = stream.readline().split()
        if len(header) != 2 or header[0].lower() not in {"ptf", "jtf"}:
            return
        delimiter = re.escape(header[1])
        assignment = rf"^[^!\n]*\bphoto_sln_ref\s*=\s*(?:![^\n]*\n\s*)*{delimiter}"
        if re.search(assignment, stream.read(), flags=re.IGNORECASE | re.MULTILINE):
            raise ValueError(f"{template}: set photo_sln_ref to a fixed value before the IES run")


def prepare(args, executable):
    bounds = input_table(args.bounds, ("name", "init", "lower", "upper"))
    targets = input_table(
        args.observations, ("name", "file", "column", "treatment", "yrdoy", "observed", "weight"),
    )
    if "preflight_only" in targets and targets.preflight_only.ne(0).any() and args.updates > 0:
        raise ValueError("This observation table is restricted to zero-update preflight")
    if not np.isfinite(bounds[["init", "lower", "upper"]]).all().all() or not (
        bounds.lower.lt(bounds.upper) & bounds.init.between(bounds.lower, bounds.upper)
    ).all():
        raise ValueError("Parameters need finite bounds and an initial value within each range")
    if not np.isfinite(targets[["observed", "weight", "treatment"]]).all().all() or not (
        targets.weight.ge(0).all() and targets.weight.gt(0).any()
    ):
        raise ValueError("Targets need finite values and nonnegative weights with at least one positive weight")
    if not targets.file.str.fullmatch(r"[\w-]+\.OUT", case=False, na=False).all():
        raise ValueError("Targets must name native DSSAT OUT files")

    templates = {}
    for path in args.templates:
        if path.suffix.lower() != ".tpl" or Path(path.stem).suffix.lower() != ".nml":
            raise ValueError("Templates must use the engine's <name>.nml.tpl naming")
        if path.stem.lower() in (name.lower() for name in templates):
            raise ValueError(f"Duplicate template destination {path.stem}")
        template = path.resolve(strict=True)
        require_fixed_sln_reference(template)
        templates[path.stem] = template

    inputs = args.inputs.resolve(strict=True)
    profile = "DSSATPRO.v48" if sys.platform == "win32" else "DSSATPRO.L48"
    for required in (profile, "DSSBatch.v48"):
        if not (inputs / required).is_file():
            raise ValueError(f"Prepared case needs {required}")
    if any(not path.is_file() or path.suffix.lower() in {".out", ".exe", ".log"} for path in inputs.iterdir()):
        raise ValueError("The input case must be a flat directory of model inputs")

    work = args.out.resolve()
    work.mkdir(parents=True, exist_ok=False)
    shutil.copytree(inputs, work / "inputs")
    here = Path(__file__).resolve().parent
    shutil.copyfile(here / "forward.py", work / "forward.py")
    shutil.copyfile(here.parent / "n_diagnostics/data.py", work / "data.py")
    for source in templates.values():
        shutil.copyfile(source, work / source.name)
    shutil.copyfile(args.bounds, work / "bounds.csv")
    shutil.copyfile(args.observations, work / "observations.csv")
    (work / "simulated.ins").write_text(
        "pif ~\n" + "".join(f"l1 !{name}!\n" for name in targets.index), encoding="ascii",
    )
    (work / "forward.json").write_text(
        json.dumps({"engine": str(executable), "templates": list(templates)}), encoding="utf-8",
    )
    baseline = evaluate(
        work / "inputs", executable, targets.reset_index(), {}, work / "baseline.log",
    )
    (work / "simulated.txt").write_text("".join(f"{value:.17g}\n" for value in baseline), encoding="ascii")
    pst = pyemu.Pst.from_io_files(
        [str(work / source.name) for source in templates.values()],
        [str(work / name) for name in templates],
        [str(work / "simulated.ins")], [str(work / "simulated.txt")], pst_path=".",
    )
    if set(pst.par_names) != set(bounds.index) or set(pst.obs_names) != set(targets.index):
        raise ValueError("Template parameter names and observation keys must match their tables")
    for key, column in (("parval1", "init"), ("parlbnd", "lower"), ("parubnd", "upper")):
        pst.parameter_data[key] = bounds.loc[pst.par_names, column]
    pst.parameter_data["partrans"] = "none"
    pst.observation_data["obsval"] = targets.loc[pst.obs_names, "observed"]
    pst.observation_data["weight"] = targets.loc[pst.obs_names, "weight"]
    if "group" in targets:
        if not targets.group.str.fullmatch(r"[a-z][a-z0-9_]{0,19}", na=False).all():
            raise ValueError("Invalid observation group names")
        pst.observation_data["obgnme"] = targets.loc[pst.obs_names, "group"]
    if sys.platform == "win32":
        launcher = work / "forward.cmd"
        launcher.write_text("@python -X utf8 forward.py\n", encoding="utf-8")
        pst.model_command = ["cmd /c forward.cmd"]
    else:
        launcher = work / "forward.sh"
        launcher.write_text("#!/bin/sh\nexec python3 -X utf8 forward.py\n")
        launcher.chmod(0o755)
        pst.model_command = ["./forward.sh"]
    pst.control_data.noptmax = args.updates
    pst.pestpp_options.update(
        ies_num_reals=args.members, ies_no_noise=True, ies_include_base=True, random_seed=args.seed,
    )
    pst.write(str(work / "mechanism.pst"), version=2)
    manifest = {str(path.relative_to(work)): sha(path) for path in work.rglob("*") if path.is_file() and path.name not in {"baseline.log", "simulated.txt"}}
    (work / "run_manifest.json").write_text(json.dumps({
        "engine": str(executable), "engine_sha256": sha(executable),
        "members": args.members, "updates": args.updates, "seed": args.seed,
        "inputs_sha256": manifest,
    }, indent=2) + "\n", encoding="utf-8")
    return work


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("engine", "inputs", "bounds", "observations", "out"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--template", dest="templates", action="append", type=Path, required=True)
    parser.add_argument("--pestpp-ies", help="Run the prepared case using this executable")
    parser.add_argument("--members", type=int, default=8)
    parser.add_argument("--updates", type=int, default=1)
    parser.add_argument("--seed", type=int, default=12345)
    args = parser.parse_args()
    if args.members < 3 or args.updates < 0:
        parser.error("Require at least three members and zero or more updates")
    engine = args.engine.resolve(strict=True)
    pest = shutil.which(args.pestpp_ies) if args.pestpp_ies else None
    if args.pestpp_ies and pest is None:
        parser.error(f"PEST++ executable not found: {args.pestpp_ies}")
    work = prepare(args, engine)
    if pest:
        # Resolve Python from the selected environment without sealing its path in the case.
        env = dict(os.environ, PATH=os.pathsep.join(
            (str(Path(sys.executable).parent), os.environ.get("PATH", "")),
        ))
        with (work / "pestpp-ies.log").open("wb") as log:
            subprocess.run([str(Path(pest).resolve()), "mechanism.pst"], cwd=work, stdout=log,
                           stderr=subprocess.STDOUT, env=env, check=True)
        objectives = pd.read_csv(work / "mechanism.phi.actual.csv")
        if objectives.empty or objectives["iteration"].max() < args.updates:
            raise RuntimeError("PEST++ stopped before the requested IES update; see pestpp-ies.log")
    print(work)


if __name__ == "__main__":
    main()
