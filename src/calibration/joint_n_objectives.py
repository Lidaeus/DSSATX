"""Approved joint calibration operators; legacy sealed single-season runs stay unchanged."""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import subprocess
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration import single_season_n as legacy
from src.common.input_manifest import verify_manifest_integrity
from src.common.param_registry import assert_valid_frozen_bounds
from src.dssat import run_dssat as runner

ROOT = legacy.ROOT
SIGNED = {"N_FRESH_CONTRAST", "W_FRESH_CONTRAST"}
DERIVED = SIGNED | {"N2_SIGN_PENALTY", "ADAP"}


def load_design(path, *, require_preflight=True):
    path = Path(path).resolve()
    design = json.loads(path.read_text(encoding="utf-8"))
    if design.get("schema") != "formal_joint_n_v1" or not design.get("approved"):
        raise ValueError("Explicitly approved joint design required")
    if require_preflight:
        if not design.get("runtime_preflight_passed"):
            raise ValueError("Joint forward preflight must pass")
        receipt = json.loads((path.parent / "frozen_configuration_receipt.json").read_text(encoding="utf-8"))
        if legacy.sha(path) != receipt["design_sha256"]:
            raise ValueError("Frozen design changed")
    for rel, digest in design["runtime_hashes"].items():
        if legacy.sha(ROOT / rel) != digest:
            raise ValueError(f"Frozen runtime changed: {rel}")
    if legacy.sha(design["dssat_executable"]) != design["dssat_executable_sha256"]:
        raise ValueError("DSSAT binary changed")
    bounds_path = ROOT / "data/parameter_registry/bounds_frozen/eggplant" / (design["bounds_id"] + ".csv")
    if legacy.sha(bounds_path) != design["bounds_sha256"]:
        raise ValueError("Bounds changed")
    assert_valid_frozen_bounds(bounds_path)
    bounds = pd.read_csv(bounds_path).fillna("")
    if set(bounds[bounds.status.eq("active")].name) != set(design["active_parameters"]):
        raise ValueError("Active parameter identities differ")
    for dataset in design["datasets"]:
        manifest = verify_manifest_integrity(ROOT / dataset["bundle_path"])
        if manifest.manifest_sha256 != dataset["bundle_manifest_sha256"]:
            raise ValueError("Bundle changed")
        roles = [int(t) for group in dataset["roles"].values() for t in group]
        if len(roles) != len(set(roles)):
            raise ValueError("Dataset roles overlap")
    calibration = [x for x in design["datasets"] if x["roles"].get("calibration")]
    if len(calibration) != 1 or calibration[0]["season_id"] != "26SP" or sorted(calibration[0]["roles"]["calibration"]) != list(range(4, 13)):
        raise ValueError("Only approved 2026 nine treatments may calibrate")
    obs_path = path.parent / "calibration_observations.csv"
    if legacy.sha(obs_path) != design["calibration_observations_sha256"]:
        raise ValueError("Objective catalog changed")
    obs = pd.read_csv(obs_path).fillna("")
    if len(obs) != 492 or not obs.dataset_role.eq("calibration").all() or set(obs.trno) != set(range(4, 13)):
        raise ValueError("Expected exactly 492 calibration-only objectives")
    if obs.obsnme.duplicated().any() or not obs.final_weight.gt(0).all():
        raise ValueError("Invalid objective identities/weights")
    return design, bounds, obs


def validate_parameters(values, bounds):
    values = legacy.validate_parameters(values, bounds)
    if not values["PRORTF"] <= values["PRORTG"] <= values["PRORTI"]:
        raise ValueError("Invalid root protein order")
    return values


def audit_extended_injection(work, values, active):
    actual = legacy.read_injected_parameters(work)
    # Extend the independent numeric readback for C31's additional SPE fields.
    markers = {
        "ICMP,TCMP": ["ICMP", "TCMP"],
        "OPTLFP-EM,": [None, None, "OPTLFP_FS"],
        "OPTSTP-EM,": [None, None, "OPTSTP_FS"],
        "OPTSDP-EM,": [None, None, "OPTSDP_FS"],
    }
    number = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[Ee][-+]?\d+)?")
    lines = (Path(work) / "TMGRO048.SPE").read_text().splitlines()
    for marker, names in markers.items():
        line = next(x for x in lines if marker in x)
        # Phosphorus rows have descriptive text between values and identifiers.
        tokens = number.findall(line[:line.index(marker)].split("Optimum")[0])
        for name, token in zip(names, tokens):
            if name is None:
                continue
            mantissa, _, exponent = token.lower().partition("e")
            decimals = len(mantissa.split(".")[1]) if "." in mantissa else 0
            resolution = 10.**((int(exponent) if exponent else 0)-decimals)
            actual[name] = (float(token), resolution)
    rows = []
    for name in active:
        if name not in actual:
            raise ValueError(f"No independent injection field: {name}")
        injected, resolution = actual[name]
        if abs(injected-values[name]) > resolution/2+1e-9:
            raise ValueError(f"Injection mismatch: {name}: {values[name]} -> {injected}")
        rows.append(dict(name=name, requested=values[name], injected=injected, printed_resolution=resolution))
    pd.DataFrame(rows).to_csv(Path(work)/"joint_parameter_injection_audit.csv", index=False)
    return rows


def read_anthesis(path):
    header, result = None, {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("@RUN"):
            header = line.lstrip("@").split()
        elif header and line.split() and line.split()[0].isdigit():
            parts = line.split()
            if len(parts) != len(header):
                raise ValueError("Malformed Evaluate.OUT")
            row = dict(zip(header, parts))
            if not row["EXCODE"].startswith("XXQL2601"):
                continue
            tn = int(row["TN"])
            if tn in result:
                raise ValueError("Ambiguous treatment anthesis")
            value = float(row["ADAPS"])
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"Missing simulated anthesis: T{tn}")
            result[tn] = value
    return result


def extract_observations(work, obs, *, native_frames=None, anthesis=None):
    frames = native_frames if native_frames is not None else {
        name: legacy.read_native(Path(work)/f"{name}.OUT") for name in ["PlantGro", "PlantN", "FreshWt", "SoilWat"]}
    raw = obs[~obs.variable.isin(DERIVED)]
    normal = (legacy.extract_observations(work, raw, native_frames=frames).set_index("obsnme")
              if len(raw) else pd.DataFrame())
    anthesis = read_anthesis(Path(work)/"Evaluate.OUT") if anthesis is None else anthesis
    result = []
    for item in obs.to_dict("records"):
        variable = item["variable"]
        if variable not in DERIVED:
            result.append(normal.loc[item["obsnme"]].to_dict() | {"obsnme": item["obsnme"]})
            continue
        if variable == "ADAP":
            value = anthesis[int(item["trno"])]
        else:
            date = item["date"]
            high = float(frames["FreshWt"].loc[(int(item["trno"]), date), "CHFPW"])
            low = float(frames["FreshWt"].loc[(int(item["paired_trno"]), date), "CHFPW"])
            if not all(math.isfinite(v) and v >= 0 for v in (high, low)):
                raise ValueError("Missing/invalid fresh-yield contrast parent")
            value = high-low
            if variable == "N2_SIGN_PENALTY":
                value = max(0., -value)
        if not math.isfinite(value) or (variable not in SIGNED and value < 0):
            raise ValueError(f"Invalid joint objective: {variable}")
        result.append({**item, "simulated": value})
    return pd.DataFrame(result)


def evaluate(design_path, param_csv, output_dir, *, preflight=False):
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir/"FormalObjectives.OUT"
    output.unlink(missing_ok=True)
    (output_dir/"model_failure.json").unlink(missing_ok=True)
    design, bounds, obs = load_design(design_path, require_preflight=not preflight)
    values = validate_parameters(runner._read_param_dict(param_csv), bounds)
    dataset = next(d for d in design["datasets"] if d["roles"].get("calibration"))
    work = simulate(output_dir/"_model", dataset, dataset["roles"]["calibration"], values,
                           executable_sha256=design["dssat_executable_sha256"])
    audit_extended_injection(work, values, design["active_parameters"])
    compared = extract_observations(work, obs)
    compared.to_csv(output_dir/"last_comparison.csv", index=False)
    temp = output.with_suffix(".tmp")
    temp.write_text("\n".join(f"{r.obsnme} {r.simulated:.12g}" for r in compared.itertuples())+"\n", encoding="ascii")
    temp.replace(output)
    return compared


def simulate(work, dataset, treatments, values, *, executable_sha256=None):
    values={str(k).upper():float(f'{float(v):.12g}') for k,v in values.items()}
    work=legacy.prepare_inputs(work,dataset,treatments)
    if executable_sha256 and legacy.sha(work/"DSCSM048.EXE")!=executable_sha256:
        raise ValueError("Prepared binary changed")
    pd.DataFrame(values.items(),columns=["name","value"]).to_csv(work/"parameters.csv",index=False)
    before={name:legacy.sha(work/name) for name in [dataset["experiment_code"]+".TMX","SOIL.SOL"]}
    command=[sys.executable,"-X","utf8",str(ROOT/"src/dssat/forward_joint.py"),"--param-csv","parameters.csv","--batch","DSSBatch.v48"]
    with (work/"model.log").open("w",encoding="utf-8") as log:
        completed=subprocess.run(command,cwd=work,stdout=log,stderr=subprocess.STDOUT,timeout=120)
    if completed.returncode:raise RuntimeError(f"DSSAT forward failed ({completed.returncode}): {work/'model.log'}")
    for name,digest in before.items():
        if legacy.sha(work/name)!=digest:raise ValueError("Fixed measured inputs changed during injection")
    return work


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--design", required=True)
    parser.add_argument("--param-csv", default="parameters.csv")
    parser.add_argument("--output-dir", default=".")
    args = parser.parse_args()
    try:
        evaluate(args.design, args.param_csv, args.output_dir)
    except Exception as error:
        legacy.write_json(Path(args.output_dir)/"model_failure.json", {"error": str(error)})
        raise


if __name__ == "__main__":
    main()
