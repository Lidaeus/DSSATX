import argparse
import json
import os
import shutil
import sys

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import pyemu

from src.common.param_registry import assert_valid_frozen_bounds
from src.common.project import git_metadata, sha256_file
from src.common.experiment_inputs import validate_input_bundle
from src.common.input_manifest import InputManifestError, verify_manifest_integrity
from src.sensitivity.output_contract import DEFAULT_PROFILE, load_output_contract, observation_names


def _workspace_dir_from_this_file():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", ".."))


def _write_params_csv_and_tpl(param_df, params_csv_path, tpl_path):
    df = param_df.copy()
    df = df[df["status"].astype(str).str.lower().isin(["active", "adjustable", "free", "log", "none", "both"]) | (df["status"].astype(str).str.lower() == "active")]
    rows = []
    for _, r in df.iterrows():
        name = str(r["name"]).strip().upper()
        init = float(r["init"]) if pd.notna(r["init"]) else 0.0
        rows.append({"name": name, "value": init})
    out_df = pd.DataFrame(rows)
    out_df.to_csv(params_csv_path, index=False)

    with open(tpl_path, "w", encoding="utf-8") as f:
        f.write("ptf ~\n")
        f.write("name,value\n")
        for _, r in out_df.iterrows():
            name = str(r["name"]).strip().upper()
            f.write(f"{name},~ {name} ~\n")

    return out_df


def _write_indicators_ins(observation_names, ins_path):
    with open(ins_path, "w", encoding="utf-8") as f:
        f.write("pif ~\n")
        for n in observation_names:
            # pyemu lowercases observation names internally; the .ins markers
            # must match the .pst observation section case-convention.
            f.write(f"l1 w !{n.lower()}!\n")


def _default_observation_names():
    return observation_names(load_output_contract())


def _copy_runtime_file(source, runtime_root, relative_path):
    source = Path(source)
    destination = Path(runtime_root) / relative_path
    if not source.is_file():
        raise FileNotFoundError(f"Required sensitivity runtime file is missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def _prepare_runtime_bundle(case_dir, workspace_dir, input_dir, output_profile):
    """Freeze the forward-model runtime inside a sensitivity case.

    PEST++ copies the whole case to each worker.  Keeping every Python module,
    model template, user input and output contract below ``runtime/`` makes the
    model command independent from subsequent edits to the repository.
    """
    case_root = Path(case_dir)
    project_root = Path(workspace_dir)
    runtime_root = case_root / "runtime"
    if runtime_root.exists():
        shutil.rmtree(runtime_root)

    required = (
        (project_root / "src" / "__init__.py", Path("src/__init__.py")),
        (project_root / "src" / "sensitivity" / "__init__.py", Path("src/sensitivity/__init__.py")),
        (project_root / "src" / "sensitivity" / "sa_model.py", Path("src/sensitivity/sa_model.py")),
        (project_root / "src" / "sensitivity" / "output_contract.py", Path("src/sensitivity/output_contract.py")),
        (project_root / "src" / "common" / "__init__.py", Path("src/common/__init__.py")),
        (project_root / "src" / "common" / "param_registry.py", Path("src/common/param_registry.py")),
        (project_root / "src" / "calibration" / "__init__.py", Path("src/calibration/__init__.py")),
        (project_root / "src" / "calibration" / "run_dssat.py", Path("src/calibration/run_dssat.py")),
        (
            project_root / "src" / "calibration" / "observation_policy.py",
            Path("src/calibration/observation_policy.py"),
        ),
        (project_root / "src" / "dssat" / "__init__.py", Path("src/dssat/__init__.py")),
        (project_root / "src" / "dssat" / "run_dssat.py", Path("src/dssat/run_dssat.py")),
        (project_root / "data" / "templates" / "DSSAT48.INH", Path("data/templates/DSSAT48.INH")),
        (project_root / "data" / "templates" / "DSSAT48.INP", Path("data/templates/DSSAT48.INP")),
        (project_root / "data" / "templates" / "DSSATPRO.v48", Path("data/templates/DSSATPRO.v48")),
    )
    copied = [_copy_runtime_file(source, runtime_root, relative) for source, relative in required]
    for filename in ("TMGRO048.CUL.base", "TMGRO048.ECO.base", "TMGRO048.SPE.base"):
        copied.append(
            _copy_runtime_file(
                project_root / "data" / "templates" / "genotype" / filename,
                runtime_root,
                Path("data/templates/genotype") / filename,
            )
        )

    executable_candidates = (
        Path(os.environ.get("DSSAT48_HOME", r"C:\DSSAT48")) / "DSCSM048.EXE",
        project_root / "workspace" / "DSCSM048.EXE",
    )
    executable = next((path for path in executable_candidates if path.is_file()), None)
    if executable is None:
        raise FileNotFoundError("DSCSM048.EXE is required to freeze a sensitivity runtime")
    copied.append(
        _copy_runtime_file(executable, runtime_root, Path("workspace/DSCSM048.EXE"))
    )

    runtime_input = runtime_root / "input"
    shutil.copytree(input_dir, runtime_input)
    copied.extend(path for path in runtime_input.rglob("*") if path.is_file())
    runtime_profile = _copy_runtime_file(
        output_profile,
        runtime_root,
        Path("config/output_profile.json"),
    )
    copied.append(runtime_profile)

    files = [
        {
            "path": path.relative_to(runtime_root).as_posix(),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(set(copied))
    ]
    manifest_path = runtime_root / "runtime_manifest.json"
    manifest_path.write_text(
        json.dumps({"schema_version": 1, "files": files}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return runtime_root, manifest_path


def build_case(
    param_review_csv,
    case_dir,
    workspace_dir,
    cultivar="TM0008",
    morris_r=100,
    morris_p=None,
    morris_delta=None,
    random_seed=20260715,
    output_profile=DEFAULT_PROFILE,
    input_dir=None,
    run_type="sensitivity_formal_case",
):
    allowed_run_types = {
        "sensitivity_formal_case",
        "sensitivity_preflight_case",
        "sensitivity_sobol_preflight_case",
        "sensitivity_sobol_formal_case",
    }
    if run_type not in allowed_run_types:
        raise ValueError(f"Unsupported sensitivity run type: {run_type}")
    assert_valid_frozen_bounds(param_review_csv)
    os.makedirs(case_dir, exist_ok=True)
    case_dir = os.path.abspath(case_dir)
    workspace_dir = os.path.abspath(workspace_dir)
    contract = load_output_contract(output_profile)
    if input_dir:
        input_dir = os.path.abspath(input_dir)
        # Unified manifest integrity gate: directory/bundle_id match + per-file
        # SHA-256 verification (not just hashing the manifest file). Runs before
        # the FileX/soil coherence check so a tampered or mis-identified bundle
        # fails fast, before any case artifact is written.
        try:
            verify_manifest_integrity(input_dir)
        except InputManifestError as exc:
            raise ValueError(f"Input bundle manifest verification failed: {exc}") from exc
        input_summary, input_findings = validate_input_bundle(
            input_dir,
            require_observations=False,
        )
        errors = [item for item in input_findings if item.severity == "error"]
        if errors:
            raise ValueError("Input bundle validation failed: " + "; ".join(item.message for item in errors))
        if set(contract["treatments"]) != set(input_summary["treatments"]):
            raise ValueError("Output contract treatments do not match the selected input bundle")
        runtime_root, runtime_manifest = _prepare_runtime_bundle(
            case_dir,
            workspace_dir,
            input_dir,
            contract["path"],
        )
    else:
        runtime_root = None
        runtime_manifest = None

    review_df = pd.read_csv(param_review_csv)
    review_df["name"] = review_df["name"].astype(str).str.strip().str.upper()
    review_df["status"] = review_df["status"].fillna("active")

    params_csv_name = "sa_params.csv"
    tpl_name = "sa_params.csv.tpl"
    params_csv = os.path.join(case_dir, params_csv_name)
    tpl_path = os.path.join(case_dir, tpl_name)
    _write_params_csv_and_tpl(review_df[review_df["status"].str.lower() == "active"], params_csv, tpl_path)

    out_name = "SA_Indicators.OUT"
    ins_name = "SA_Indicators.OUT.ins"
    ins_path = os.path.join(case_dir, ins_name)
    obs_names = observation_names(contract)
    _write_indicators_ins(obs_names, ins_path)
    obs_order_path = os.path.join(case_dir, "sa_obs_order.txt")
    with open(obs_order_path, "w", encoding="utf-8") as f:
        for n in obs_names:
            f.write(str(n) + "\n")

    # PyEMU validates instruction files while building the PST. Supply a
    # temporary one-value-per-line output with the same contract, then remove
    # it so a future model run cannot mistake the fixture for fresh data.
    placeholder_output = os.path.join(case_dir, out_name)
    placeholder_created = not os.path.exists(placeholder_output)
    if placeholder_created:
        with open(placeholder_output, "w", encoding="utf-8") as handle:
            for _ in obs_names:
                handle.write(" 0\n")

    pst_path = os.path.join(case_dir, "sa_sen_morris.pst")

    cwd0 = os.getcwd()
    try:
        os.chdir(case_dir)
        pst = pyemu.Pst.from_io_files(
            tpl_files=[tpl_name],
            in_files=[params_csv_name],
            ins_files=[ins_name],
            out_files=[out_name],
        )
    finally:
        os.chdir(cwd0)
        if placeholder_created and os.path.exists(placeholder_output):
            os.remove(placeholder_output)
    pst.control_data.noptmax = 0

    for p in pst.parameter_data.parnme:
        m = review_df[review_df["name"] == p.upper()]
        if m.empty:
            continue
        r = m.iloc[0]
        try:
            if pd.notna(r.get("init")):
                pst.parameter_data.loc[p, "parval1"] = float(r["init"])
        except Exception:
            pass
        try:
            pst.parameter_data.loc[p, "parlbnd"] = float(r["lower"]) if pd.notna(r["lower"]) else pst.parameter_data.loc[p, "parlbnd"]
            pst.parameter_data.loc[p, "parubnd"] = float(r["upper"]) if pd.notna(r["upper"]) else pst.parameter_data.loc[p, "parubnd"]
        except Exception:
            pass
        pst.parameter_data.loc[p, "pargp"] = str(r.get("pargp", ""))[:12] if pd.notna(r.get("pargp", "")) else ""

    pst.parameter_data.loc[:, "partrans"] = "none"

    pst.observation_data.loc[:, "weight"] = 1.0

    if runtime_root is not None:
        model_script = "runtime/src/sensitivity/sa_model.py"
        batch_path = "runtime/input/DSSBatch.v48"
        command_input_dir = "runtime/input"
        command_output_profile = "runtime/config/output_profile.json"
    else:
        model_script = os.path.normpath(os.path.join(workspace_dir, "src", "sensitivity", "sa_model.py"))
        batch_path = os.path.join(workspace_dir, "data", "templates", "batch", "DSSBatch.v48")
        command_input_dir = None
        command_output_profile = contract["path"]
    model_cmd = (
        f"python \"{model_script}\" --workspace . --batch \"{batch_path}\" "
        f"--cultivar {cultivar} --param-csv {params_csv_name} --out {out_name} --obs-order sa_obs_order.txt"
    )
    if command_input_dir:
        model_cmd += f' --input-dir "{command_input_dir}"'
    model_cmd += f' --output-profile "{command_output_profile}"'
    pst.model_command = [model_cmd]

    pst.pestpp_options["gsa_morris_r"] = int(morris_r)
    if morris_p is not None:
        pst.pestpp_options["gsa_morris_p"] = int(morris_p)
    if morris_delta is not None:
        pst.pestpp_options["gsa_morris_delta"] = float(morris_delta)
    pst.pestpp_options["gsa_morris_obs_sen"] = True
    pst.pestpp_options["rand_seed"] = int(random_seed)

    pst.write(pst_path)

    pst_sobol_path = os.path.join(case_dir, "sa_sen_sobol.pst")
    pst_sobol = pyemu.Pst(pst_path)
    pst_sobol.pestpp_options["gsa_method"] = "sobol"
    pst_sobol.pestpp_options["gsa_sobol_samples"] = 1000
    pst_sobol.write(pst_sobol_path)

    git_info = git_metadata()
    manifest = os.path.join(case_dir, "run_manifest.yaml")
    with open(manifest, "w", encoding="utf-8") as handle:
        handle.write(f"run_id: {os.path.basename(case_dir)}\n")
        handle.write(f"run_type: {run_type}\n")
        handle.write(f"git_commit: {git_info.get('git_commit', '')}\n")
        handle.write(f"git_branch: {git_info.get('git_branch', '')}\n")
        handle.write(f"git_dirty: {str(git_info.get('git_dirty', False)).lower()}\n")
        handle.write(f"bounds_csv: {os.path.abspath(param_review_csv)}\n")
        handle.write(f"bounds_sha256: {sha256_file(param_review_csv)}\n")
        handle.write(f"random_seed: {int(random_seed)}\n")
        handle.write(f"morris_r: {int(morris_r)}\n")
        handle.write(f"morris_p: {'' if morris_p is None else int(morris_p)}\n")
        handle.write(f"cultivar: {cultivar}\n")
        handle.write(f"observation_count: {len(obs_names)}\n")
        handle.write(f"output_profile: {contract['path']}\n")
        handle.write(f"output_profile_sha256: {sha256_file(contract['path'])}\n")
        handle.write(f"input_dir: {input_dir or ''}\n")
        manifest_path = os.path.join(input_dir, "input_manifest.json") if input_dir else ""
        handle.write(f"input_manifest_sha256: {sha256_file(manifest_path) if manifest_path and os.path.isfile(manifest_path) else ''}\n")
        handle.write("runtime_bundle: runtime\n" if runtime_root is not None else "runtime_bundle: \n")
        handle.write(
            f"runtime_manifest_sha256: {sha256_file(runtime_manifest) if runtime_manifest is not None else ''}\n"
        )

    return pst_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--param-review",
        default=None,
    )
    parser.add_argument("--case-dir", default=None)
    parser.add_argument("--cultivar", default="TM0008")
    parser.add_argument("--morris-r", type=int, default=30)
    parser.add_argument("--morris-p", type=int, default=None)
    parser.add_argument("--morris-delta", type=float, default=None)
    parser.add_argument("--random-seed", type=int, default=20260715)
    parser.add_argument("--output-profile", default=str(DEFAULT_PROFILE))
    parser.add_argument("--input-dir", default=None)
    parser.add_argument(
        "--run-type",
        choices=(
            "sensitivity_formal_case",
            "sensitivity_preflight_case",
            "sensitivity_sobol_preflight_case",
            "sensitivity_sobol_formal_case",
        ),
        default="sensitivity_formal_case",
    )
    args = parser.parse_args()

    workspace_dir = _workspace_dir_from_this_file()
    param_review = (
        os.path.normpath(args.param_review)
        if args.param_review
        else os.path.join(workspace_dir, "workspace", "runs", "sa_output", "sensitivity_param_review.csv")
    )
    case_dir = (
        os.path.normpath(args.case_dir)
        if args.case_dir
        else os.path.join(workspace_dir, "workspace", "runs", "sa_output", "sen_case")
    )

    pst_path = build_case(
        param_review,
        case_dir=case_dir,
        workspace_dir=workspace_dir,
        cultivar=args.cultivar,
        morris_r=args.morris_r,
        morris_p=args.morris_p,
        morris_delta=args.morris_delta,
        random_seed=args.random_seed,
        output_profile=args.output_profile,
        input_dir=args.input_dir,
        run_type=args.run_type,
    )
    print(f"Wrote: {pst_path}")


if __name__ == "__main__":
    main()
