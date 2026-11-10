"""Approved single-season concentration calibration, using the existing injector.

This entry point has its own explicit formal schema. It does not relax the
multi-season design contract or read validation data during model evaluation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.input_manifest import verify_manifest_integrity
from src.common.param_registry import assert_valid_frozen_bounds
from src.dssat import run_dssat as runner


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2,
                                    allow_nan=False) + "\n", encoding="utf-8")


def read_native(path):
    """Strict daily output reader; actual treatment IDs, never batch positions."""
    records, header, run, treatment = [], None, None, None
    for line in Path(path).read_text(encoding="utf-8", errors="strict").splitlines():
        match = re.match(r"\*RUN\s+(\d+)", line)
        if match:
            run, treatment, header = int(match[1]), None, None
        match = re.match(r"\s*TREATMENT\s+(\d+)", line)
        if match:
            treatment = int(match[1])
        if line.lstrip().startswith("@YEAR"):
            header = line.strip().lstrip("@").split()
        elif header and re.match(r"\s*20\d{2}\s+\d+", line):
            values = line.split()
            if len(values) != len(header) or run is None or treatment is None:
                raise ValueError(f"Malformed native row in {path}")
            item = dict(zip(header, map(float, values)))
            item["trno"], item["run"] = treatment, run
            item["date"] = (pd.Timestamp(int(item["YEAR"]), 1, 1) +
                            pd.Timedelta(days=int(item["DOY"]) - 1)).strftime("%Y-%m-%d")
            records.append(item)
    frame = pd.DataFrame(records)
    if frame.empty or frame.duplicated(["trno", "date"]).any():
        raise ValueError(f"Empty or ambiguous native treatment/date output: {path}")
    return frame.set_index(["trno", "date"])


def mature_fruit_n_percent(seed_pct, shell_pct, seed_dm, shell_dm):
    values = [seed_pct, shell_pct, seed_dm, shell_dm]
    if not all(math.isfinite(float(v)) and float(v) >= 0 for v in values):
        raise ValueError("Invalid mature-fruit N concentration or dry mass")
    total = seed_dm + shell_dm
    if total <= 0:
        raise ValueError("No mature fruit at the exact N sampling date")
    return (seed_pct * seed_dm + shell_pct * shell_dm) / total


def read_injected_parameters(work):
    """Read actual numeric fields independently of injector formatting logic."""
    work = Path(work)
    number = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[Ee][-+]?\d+)?")
    result = {}

    def collect(names, tokens):
        for name, token in zip(names, tokens):
            if name is not None:
                mantissa, _, exponent = token.lower().partition("e")
                decimals = len(mantissa.split(".")[1]) if "." in mantissa else 0
                resolution = 10. ** ((int(exponent) if exponent else 0) - decimals)
                result[name] = (float(token), resolution)

    for kind, header, identity, skip in [("CUL", "@VAR#", "TM0008", 4), ("ECO", "@ECO#", "TM0001", 2)]:
        lines = (work / f"TMGRO048.{kind}").read_text().splitlines()
        names = next(line.split()[skip:] for line in lines if line.startswith(header))
        line = next(line for line in lines if line.startswith(identity))
        collect(names, number.findall(line)[-len(names):])
    mapping = {
        "PARMAX,PHTMAX": "PARMAX PHTMAX KCAN KC_SLOPE",
        "PGEFF SCV KDIF": "PGEFF SCV KDIF LFANGB",
        "FNPGN(4)": "FNPGN1 FNPGN2 FNPGN3 FNPGN4",
        "SLWREF,SLWSLO": "SLWREF SLWSLO NSLOPE LNREF PGREF",
        "PROLFI,PROLFG,PROLFF": "PROLFI PROLFG PROLFF PROSTI PROSTG PROSTF",
        "PRORTI,PRORTG,PRORTF": "PRORTI PRORTG PRORTF PROSHI PROSHG PROSHF",
        "CMOBMX,CADSTF": "CMOBMX CADSTF CADPR1 NMOBMX NVSMOB NRCVR",
        "XPODF,": "NSTFAC NREXP NRMIN",
        "WTFSD,PORPT": "WTFSD PORPT FRSTMF FRLFF ATOP FRCNOD",
        "FINREF,SLAREF": "FINREF SLAREF SIZREF VSSINK EVMODC",
        "SENRTE,SENRT2": "SENRTE SENRT2 SENDAY FREEZ1 FREEZ2",
        "RTDEPI,RFAC1": "RTDEPI RFAC1 RTSEN RLDSM RTSDF RWUEP1 RWUMX",
        "RTNO3,RTNH4": "RTNO3 RTNH4 PORMIN RTEXF",
        "DSWBAR,XFRMAX": "DSWBAR XFRMAX SHLAG",
        "XSWBAR(1-5)": "_X1 _X2 SWBAR_REC",
        "YSWBAR(1-5)": "_Y1 _Y2 YSWBAR_MID",
        "VEGETATIVE DEVELOPMENT": "TB1 TO11 TO21 TM1",
        "EARLY REPRODUCTIVE DEVELOPMENT": "TB2 TO12 TO22 TM2",
    }
    lines = (work / "TMGRO048.SPE").read_text().splitlines()
    for marker, names in mapping.items():
        line = next(line for line in lines if marker in line)
        collect(names.split(), number.findall(line[:line.index(marker)]))
    index = next(i for i, line in enumerate(lines) if "SENPOR........." in line)
    collect([None, None, None, "SENPOR_LATE", None, None, None, "SENMAX_LATE"], number.findall(lines[index + 1]))
    return result


def audit_injection(work, values, names):
    actual = read_injected_parameters(work)
    records = []
    for name in names:
        if name not in actual:
            raise ValueError(f"No actual DSSAT field for {name}")
        value, resolution = actual[name]
        if abs(values[name] - value) > resolution / 2 + 1e-9:
            raise ValueError(f"Parameter injection mismatch {name}: requested {values[name]}, actual {value}")
        records.append(dict(name=name, requested=values[name], injected=value, printed_resolution=resolution))
    pd.DataFrame(records).to_csv(Path(work) / "parameter_injection_audit.csv", index=False)
    return records


def load_design(path, *, require_preflight=True):
    path = Path(path).resolve()
    design = json.loads(path.read_text(encoding="utf-8"))
    if design.get("schema") != "formal_single_season_n_v1" or not design.get("approved"):
        raise ValueError("An explicitly approved formal single-season N design is required")
    if design.get("diagnostic_single_season", False):
        raise ValueError("Diagnostic designs cannot launch formal concentration calibration")
    if require_preflight and not design.get("runtime_preflight_passed"):
        raise ValueError("Runtime preflight must pass before formal model evaluation")
    if require_preflight:
        receipt = json.loads((path.parent / 'frozen_configuration_receipt.json').read_text(encoding='utf-8'))
        if sha(path) != receipt['design_sha256']:
            raise ValueError('Frozen formal design changed')
    if sha(design['dssat_executable']) != design['dssat_executable_sha256']:
        raise ValueError('Approved DSSAT executable changed')
    for rel, expected in design["runtime_hashes"].items():
        if sha(ROOT / rel) != expected:
            raise ValueError(f"Frozen runtime/input changed: {rel}")
    bounds = ROOT / "data/parameter_registry/bounds_frozen/eggplant" / (design["bounds_id"] + ".csv")
    if sha(bounds) != design["bounds_sha256"]:
        raise ValueError("Frozen bounds hash mismatch")
    assert_valid_frozen_bounds(bounds)
    for dataset in design["datasets"]:
        manifest = verify_manifest_integrity(ROOT / dataset["bundle_path"])
        if manifest.manifest_sha256 != dataset["bundle_manifest_sha256"]:
            raise ValueError("Input bundle differs from approved design")
        roles = dataset["roles"]
        flat = [int(tn) for group in roles.values() for tn in group]
        if len(flat) != len(set(flat)):
            raise ValueError("Treatment roles overlap")
    calibration = [d for d in design["datasets"] if d["roles"].get("calibration")]
    if len(calibration) != 1 or calibration[0]["season_id"] != "26SP":
        raise ValueError("This design requires exactly the approved 26SP calibration season")
    if sorted(calibration[0]["roles"]["calibration"]) != list(range(4, 13)):
        raise ValueError("Calibration treatments must be the approved nine N0/N1/N2 treatments")
    catalog = path.parent / design["calibration_observations"]
    if sha(catalog) != design["calibration_observations_sha256"]:
        raise ValueError("Frozen observation catalog changed")
    obs = pd.read_csv(catalog).fillna("")
    if len(obs) != 423 or not obs.dataset_role.eq("calibration").all() or not obs.season_id.eq("26SP").all():
        raise ValueError("Formal objective must contain exactly 423 calibration-only rows")
    if set(obs.trno) != set(range(4, 13)) or not obs.final_weight.gt(0).all() or obs.obsnme.duplicated().any():
        raise ValueError("Invalid calibration objective identity or weights")
    return design, pd.read_csv(bounds).fillna(""), obs


def validate_parameters(values, bounds):
    # Canonicalize decimal values before fixed-width formatting. Equivalent
    # CSV/PST values such as .17049999999999998 and .1705 otherwise land on
    # opposite sides of a rounding tie in the legacy DSSAT writer.
    values = {str(k).upper(): float(f'{float(v):.12g}') for k, v in values.items()}
    if set(values) != set(bounds.name.str.upper()):
        raise ValueError("Missing or unexpected parameter names")
    for item in bounds.itertuples():
        val = values[item.name.upper()]
        if not math.isfinite(val) or not item.lower - 1e-9 <= val <= item.upper + 1e-9:
            raise ValueError(f"Parameter outside frozen range: {item.name}={val}")
        if item.status != "active" and abs(val - item.init) > 1e-9:
            raise ValueError(f"Immutable fixed parameter changed: {item.name}")
    for names in [("TB1", "TO11", "TO21", "TM1"), ("TB2", "TO12", "TO22", "TM2"),
                  ("FNPGN1", "FNPGN2", "FNPGN3")]:
        if not all(values[a] < values[b] for a, b in zip(names, names[1:])):
            raise ValueError(f"Invalid parameter order: {names}")
    for names in [("PROLFF", "PROLFG", "PROLFI"), ("PROSTF", "PROSTG", "PROSTI"),
                  ("PROSHF", "PROSHI")]:
        if not all(values[a] <= values[b] for a, b in zip(names, names[1:])):
            raise ValueError(f"Invalid protein composition order: {names}")
    if values["XMAGE"] >= values["XFPHT"]:
        raise ValueError("Mature fruit age must precede complete harvest age")
    return values


def prepare_inputs(work, dataset, treatments):
    """Copy fresh inputs every member, then select batch only; FileX stays intact."""
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    bundle = ROOT / dataset["bundle_path"]
    runner.prepare_run_directory(work, ["--input-dir", str(bundle), "--batch", "DSSBatch.v48"])
    for kind in ['CUL','ECO','SPE']:
        if sha(work/f'TMGRO048.{kind}.base') != sha(ROOT/f'data/templates/genotype/TMGRO048.{kind}.base'):
            raise ValueError('Runtime genotype template differs from the frozen canonical template')
    # Existing DSSAT compatibility normalization removes only a blank separator
    # before PLANTING DETAILS. Apply it before auditing injection immutability.
    runner._normalize_filex_initial_conditions_boundary(str(work / (dataset["experiment_code"] + ".TMX")))
    lines, found = [], []
    for line in (bundle / "DSSBatch.v48").read_text().splitlines():
        fields = line.split()
        if fields and fields[0].upper().endswith(".TMX"):
            tn = int(fields[1])
            if tn not in treatments:
                continue
            found.append(tn)
        lines.append(line)
    if sorted(found) != sorted(treatments):
        raise ValueError("Batch selection does not match approved treatments")
    (work / "DSSBatch.v48").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return work


def simulate(work, dataset, treatments, values, *, executable_sha256=None):
    values = {str(k).upper(): float(f'{float(v):.12g}') for k,v in values.items()}
    work = prepare_inputs(work, dataset, treatments)
    if executable_sha256 and sha(work/'DSCSM048.EXE') != executable_sha256:
        raise ValueError('Prepared DSSAT executable differs from approved binary')
    pd.DataFrame(list(values.items()), columns=["name", "value"]).to_csv(work / "parameters.csv", index=False)
    before = {name: sha(work / name) for name in (dataset["experiment_code"] + ".TMX", "SOIL.SOL")}
    command = [sys.executable, "-X", "utf8", str(ROOT / "src/dssat/run_dssat.py"),
               "--param-csv", "parameters.csv", "--batch", "DSSBatch.v48", "--cultivar", "TM0008",
               "--model", "CRGRO048", "--harvest-var", "CHPDT", "--keep-soil-water", "--keep-nitrogen-outputs"]
    with (work / "model.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=work, stdout=log, stderr=subprocess.STDOUT, timeout=120)
    if result.returncode:
        raise RuntimeError(f"DSSAT failed ({result.returncode}); see {work / 'model.log'}")
    audited = set(values).intersection(read_injected_parameters(work))
    audit_injection(work, values, sorted(audited))
    for name, expected in before.items():
        if sha(work / name) != expected:
            raise ValueError(f"Fixed measured input changed during injection: {name}")
    return work


def extract_observations(work, obs, *, native_frames=None):
    work = Path(work)
    frames = native_frames if native_frames is not None else {
        name: read_native(work / f"{name}.OUT") for name in ["PlantGro", "PlantN", "FreshWt", "SoilWat"]}
    records = []
    for item in obs.to_dict("records"):
        key, variable = (int(item["trno"]), item["date"]), item["variable"]
        source = ("PlantGro" if variable in {"LAID", "CHTD", "LWAD", "SWAD"} else
                  "SoilWat" if variable == "VWC" else "FreshWt" if variable in {"HPODW", "HFPOW", "CHPDT", "CHFPW"} else "PlantN")
        row = frames[source].loc[key]
        detail = {}
        if variable == "VWC":
            parts = [part.split(":") for part in item["dssat_layer_weights"].split(";")]
            weights = [(int(index), float(weight)) for index, weight in parts]
            if not math.isclose(sum(w for _, w in weights), 1., abs_tol=1e-6):
                raise ValueError("Layer weights must sum to one")
            components = [float(row[f"SW{index + 1}D"]) for index, _ in weights]
            if not all(math.isfinite(v) and 0 <= v <= 1 for v in components):
                raise ValueError("Invalid soil water output")
            value = sum(v * w for v, (_, w) in zip(components, weights))
        elif variable == "FRUIT_N_PCT":
            fresh = frames["FreshWt"].loc[key]
            if row["DAS"] != fresh["DAS"] or row["DAP"] != fresh["DAP"]:
                raise ValueError("Fruit output files disagree on simulation date/state identity")
            try:
                value = mature_fruit_n_percent(row["GN%D"], row["SHND"], fresh["MTDSD"], fresh["MTDSH"])
            except ValueError as error:
                raise ValueError(f"{error}; treatment={key[0]}, date={key[1]}, variable={variable}") from error
            detail = dict(mature_seed_dm=float(fresh["MTDSD"]), mature_shell_dm=float(fresh["MTDSH"]),
                          seed_n_pct=float(row["GN%D"]), shell_n_pct=float(row["SHND"]),
                          bulk_harvest_dry=float(fresh["HPODW"]), model_date=item["date"], date_shift=0)
        else:
            column = {"LEAF_N_PCT": "LN%D", "STEM_N_PCT": "SN%D", "LNAM": "LNAD", "SNAM": "SNAD"}.get(variable, variable)
            value = float(row[column])
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"Invalid simulated objective: {key} {variable}={value}")
        records.append({**item, "simulated": float(value), **detail})
    return pd.DataFrame(records)


def evaluate(design_path, param_csv, output_dir, *, preflight=False):
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "FormalObjectives.OUT"
    output.unlink(missing_ok=True)  # Never leave a previous successful member's values.
    (output_dir / "model_failure.json").unlink(missing_ok=True)
    design, bounds, obs = load_design(design_path, require_preflight=not preflight)
    values = validate_parameters(runner._read_param_dict(param_csv), bounds)
    for name, fixed in design.get('conditional_fixed_parameters', {}).items():
        if abs(values[name]-fixed) > 1e-9:
            raise ValueError(f'Parameter failed response gate and must remain fixed: {name}')
    dataset = next(d for d in design["datasets"] if d["roles"].get("calibration"))
    work = simulate(output_dir / "_model", dataset, dataset["roles"]["calibration"], values,
                    executable_sha256=design['dssat_executable_sha256'])
    compared = extract_observations(work, obs)
    compared.to_csv(output_dir / "last_comparison.csv", index=False)
    temp = output.with_suffix(".tmp")
    temp.write_text("\n".join(f"{r.obsnme} {r.simulated:.12g}" for r in compared.itertuples()) + "\n", encoding="ascii")
    temp.replace(output)
    return compared


def extract_evaluation_observations(work, obs):
    """Report every locked evaluation row, including explicit model mismatches.

    Calibration uses the strict extractor. Evaluation coverage is reported,
    never repaired by moving dates or substituting another fruit compartment.
    """
    records = []
    work = Path(work)
    frames = {name: read_native(work / f'{name}.OUT') for name in ['PlantGro','PlantN','FreshWt','SoilWat']}
    for index in range(len(obs)):
        row = obs.iloc[[index]]
        try:
            result = extract_observations(work, row, native_frames=frames).iloc[0].to_dict()
            result.update(comparison_status='matched', model_error='')
        except (KeyError, ValueError) as error:
            result = {**row.iloc[0].to_dict(), 'simulated': None,
                      'comparison_status': 'model_unmatched', 'model_error': str(error)}
        records.append(result)
    return pd.DataFrame(records)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--design", required=True)
    parser.add_argument("--param-csv", default="parameters.csv")
    parser.add_argument("--output-dir", default=".")
    args = parser.parse_args()
    try:
        evaluate(args.design, args.param_csv, args.output_dir)
    except Exception as error:
        write_json(Path(args.output_dir) / "model_failure.json", {"error": str(error)})
        raise


if __name__ == "__main__":
    main()
