"""Rainfall-free FileX materialisation and direct DSSAT staging utilities."""
from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from src.calibration.run_dssat import prepare_run_directory
from src.common.experiment_inputs import parse_filex

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAIN_KEYS = {"rain", "rainfall", "precipitation", "effective_rainfall"}


@dataclass(frozen=True)
class ManagementDesign:
    management_design_id: str
    stages: tuple[tuple[str, int, int], ...]
    irrigation_event_max_mm: float
    irrigation_min_interval_days: int
    nitrogen_cutoff_date: int


@dataclass(frozen=True)
class ManagementScenario:
    scenario_id: str
    parameter_set_id: str
    management_design_id: str
    total_irrigation_mm: float
    total_nitrogen_kg_ha: float
    irrigation_stage_shares: tuple[float, ...]
    nitrogen_stage_shares: tuple[float, ...]
    target_treatment: int


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_design(path: str | Path) -> ManagementDesign:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if set(map(str.lower, payload)) & RAIN_KEYS:
        raise ValueError("greenhouse management design cannot define rainfall variables")
    if payload.get("production_system") != "greenhouse_drip_eggplant" or payload.get("rainfall_considered") is not False:
        raise ValueError("design must declare greenhouse_drip_eggplant and rainfall_considered=false")
    stages, previous = [], -1
    for row in payload.get("stages", []):
        start, end = int(row["start_date"]), int(row["end_date"])
        if start > end or start <= previous:
            raise ValueError("stage calendar must be ordered and non-overlapping")
        stages.append((str(row["name"]), start, end)); previous = end
    if len(stages) != 4:
        raise ValueError("exactly four management stages are required")
    c = payload["constraints"]
    return ManagementDesign(str(payload["management_design_id"]), tuple(stages), float(c["irrigation_event_max_mm"]), int(c["irrigation_min_interval_days"]), int(c["nitrogen_cutoff_date"]))


def _shares(values: tuple[float, ...], name: str) -> tuple[float, ...]:
    result = tuple(map(float, values))
    if len(result) != 4 or any(v < 0 for v in result) or abs(sum(result) - 1) > 1e-8:
        raise ValueError(f"{name} must have four non-negative shares summing to one")
    return result


def _section(lines: list[str], title: str) -> tuple[int, int]:
    start = next((i for i, line in enumerate(lines) if line.strip().upper().startswith(title)), None)
    if start is None:
        raise ValueError(f"FileX lacks section {title}")
    return start, next((i for i in range(start + 1, len(lines)) if lines[i].startswith("*")), len(lines))


def _events(lines: list[str], title: str, level: int, date_field: str, amount_field: str) -> list[dict[str, Any]]:
    start, end = _section(lines, title); header: list[str] = []; result = []
    for index in range(start + 1, end):
        if lines[index].strip().startswith("@"):
            header = lines[index].strip()[1:].upper().split(); continue
        values = lines[index].split()
        if not header or len(values) < len(header):
            continue
        try:
            if int(values[0]) == level:
                result.append({"line": index, "date": int(values[header.index(date_field)]), "amount": float(values[header.index(amount_field)]), "field": header.index(amount_field)})
        except (ValueError, IndexError):
            continue
    if not result:
        raise ValueError(f"no {title} events for factor level {level}")
    return result


def _stage(date: int, design: ManagementDesign) -> int:
    for index, (_, start, end) in enumerate(design.stages):
        if start <= date <= end:
            return index
    raise ValueError(f"management event {date} is outside the stage calendar")


def _allocate(total: float, shares: tuple[float, ...], events: list[dict[str, Any]], design: ManagementDesign) -> dict[int, float]:
    groups = [[] for _ in range(4)]
    for event in events: groups[_stage(event["date"], design)].append(event)
    if any(shares[i] > 0 and not groups[i] for i in range(4)):
        raise ValueError("management shares allocate mass to a stage without template events")
    output: dict[int, float] = {}
    for index, group in enumerate(groups):
        if group:
            weights = [max(0.0, event["amount"]) for event in group]; denom = sum(weights)
            weights = [v / denom for v in weights] if denom else [1 / len(group)] * len(group)
            for event, weight in zip(group, weights): output[event["line"]] = round(total * shares[index] * weight, 3)
    residual = round(total, 3) - round(sum(output.values()), 3)
    if output: output[sorted(output)[-1]] = round(output[sorted(output)[-1]] + residual, 3)
    if round(sum(output.values()), 3) != round(total, 3) or any(v < 0 for v in output.values()):
        raise ValueError("FileX rounding cannot preserve the seasonal total")
    return output


def _replace_field(line: str, field: int, value: float) -> str:
    spans, active = [], False
    for index, char in enumerate(line + " "):
        if not char.isspace() and not active: start, active = index, True
        elif char.isspace() and active: spans.append((start, index)); active = False
    left = spans[field - 1][1] if field else spans[field][0]; right = spans[field][1]
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    if len(text) > right - left: raise ValueError("management amount does not fit FileX fixed-width field")
    return line[:left] + text.rjust(right - left) + line[right:]


def materialize_management_scenario(source_filex: str | Path, output_dir: str | Path, design: ManagementDesign, scenario: ManagementScenario) -> dict[str, Any]:
    if scenario.management_design_id != design.management_design_id or not scenario.parameter_set_id: raise ValueError("scenario provenance is incomplete")
    water_shares, n_shares = _shares(scenario.irrigation_stage_shares, "irrigation shares"), _shares(scenario.nitrogen_stage_shares, "nitrogen shares")
    source, out = Path(source_filex), Path(output_dir); out.mkdir(parents=True, exist_ok=True); lines = source.read_text(encoding="utf-8", errors="ignore").splitlines()
    factors = parse_filex(source)["treatments"].get(scenario.target_treatment)
    if not factors: raise KeyError(f"TN{scenario.target_treatment} is absent from FileX")
    irrigation = _events(lines, "*IRRIGATION AND WATER MANAGEMENT", int(factors["MI"]), "IDATE", "IRVAL")
    nitrogen = _events(lines, "*FERTILIZERS (INORGANIC)", int(factors["MF"]), "FDATE", "FAMN")
    water, n_values = _allocate(scenario.total_irrigation_mm, water_shares, irrigation, design), _allocate(scenario.total_nitrogen_kg_ha, n_shares, nitrogen, design)
    if any(value > design.irrigation_event_max_mm + 1e-9 for value in water.values()): raise ValueError("irrigation event exceeds drip-system capacity")
    if any(event["date"] > design.nitrogen_cutoff_date and n_values[event["line"]] > 0 for event in nitrogen): raise ValueError("nitrogen event after cutoff date")
    for events, values in ((irrigation, water), (nitrogen, n_values)):
        for event in events: lines[event["line"]] = _replace_field(lines[event["line"]], event["field"], values[event["line"]])
    filex = out / source.name; filex.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    ledger = out / "MgmtEvent.OUT"
    with ledger.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["scenario_id", "parameter_set_id", "event_type", "date_code", "stage", "amount", "unit", "rainfall_considered"]); writer.writeheader()
        for kind, events, values, unit in (("irrigation", irrigation, water, "mm"), ("nitrogen", nitrogen, n_values, "kg N/ha")):
            for event in events: writer.writerow({"scenario_id": scenario.scenario_id, "parameter_set_id": scenario.parameter_set_id, "event_type": kind, "date_code": event["date"], "stage": design.stages[_stage(event["date"], design)][0], "amount": values[event["line"]], "unit": unit, "rainfall_considered": "false"})
    manifest = {"scenario_id": scenario.scenario_id, "parameter_set_id": scenario.parameter_set_id, "management_design_id": design.management_design_id, "production_system": "greenhouse_drip_eggplant", "rainfall_considered": False, "source_filex": str(source.resolve()), "scenario_filex": str(filex.resolve()), "management_event_ledger": str(ledger.resolve()), "irrigation_total_mm": sum(water.values()), "nitrogen_total_kg_ha": sum(n_values.values()), "target_treatment": scenario.target_treatment}
    (out / "management_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def freeze_historical_parameter_set(run_dir: str | Path, realization: str | int, output_dir: str | Path, parameter_set_id: str) -> dict[str, Any]:
    run, out = Path(run_dir), Path(output_dir); ensemble = run / f"{run.name}.2.par.csv"; final = run / "calibration_finalize" / "calibration_finalize.json"
    with ensemble.open(encoding="utf-8", newline="") as handle: row = next((r for r in csv.DictReader(handle) if r.get("real_name") == str(realization)), None)
    if row is None or not final.is_file(): raise FileNotFoundError("historical final parameter realization is unavailable")
    out.mkdir(parents=True, exist_ok=True); values = {k: v for k, v in row.items() if k != "real_name" and v not in (None, "")}; parameters = out / "parameters.csv"
    with parameters.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle); writer.writerow(["name", "value"]); writer.writerows(sorted(values.items()))
    status = json.loads(final.read_text(encoding="utf-8")); manifest = {"parameter_set_id": parameter_set_id, "approval_scope": "demo_only", "science_validated": False, "source_run_id": run.name, "source_realization": str(realization), "source_engineering_status": status.get("engineering_status"), "source_science_status": status.get("science_status"), "parameters_csv": str(parameters.resolve()), "parameters_sha256": _sha(parameters), "parameter_count": len(values)}
    (out / "parameter_set_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8"); return manifest


def _restrict_batch_to_treatment(batch: Path, treatment: int) -> None:
    """Avoid changing any other treatment sharing the edited FileX factors."""
    kept, selected = [], 0
    for raw in batch.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True):
        fields = raw.split()
        if fields and not raw.lstrip().startswith(("$", "!", "@", "*")) and Path(fields[0]).suffix.upper() == ".TMX":
            if len(fields) < 2 or int(float(fields[1])) != treatment:
                continue
            selected += 1
        kept.append(raw if raw.endswith("\n") else raw + "\n")
    if selected != 1:
        raise ValueError(f"expected one DSSBatch entry for TN{treatment}, found {selected}")
    batch.write_text("".join(kept), encoding="utf-8")


def stage_direct_scenario_run(run_dir: str | Path, scenario_dir: str | Path, parameter_set_dir: str | Path, input_dir: str | Path, batch_file: str | Path, target_treatment: int) -> dict[str, Any]:
    run, scenario_dir, parameters, inputs = map(Path, (run_dir, scenario_dir, parameter_set_dir, input_dir)); scenario = json.loads((scenario_dir / "management_manifest.json").read_text(encoding="utf-8")); parameter = json.loads((parameters / "parameter_set_manifest.json").read_text(encoding="utf-8"))
    if scenario["parameter_set_id"] != parameter["parameter_set_id"] or scenario["target_treatment"] != target_treatment or scenario["rainfall_considered"] is not False: raise ValueError("scenario and parameter provenance mismatch")
    batch = prepare_run_directory(run, ["--batch", str(Path(batch_file).resolve()), "--input-dir", str(inputs.resolve())]); _restrict_batch_to_treatment(batch, target_treatment); shutil.copy2(scenario_dir / Path(scenario["scenario_filex"]).name, run / Path(scenario["scenario_filex"]).name); shutil.copy2(parameters / "parameters.csv", run / "pest_params.csv")
    manifest = {"run_type": "management_direct_dssat_demo", "approval_scope": "demo_only", "science_validated": False, "status": "staged_not_run", "scenario_id": scenario["scenario_id"], "parameter_set_id": parameter["parameter_set_id"], "rainfall_considered": False, "target_treatment": target_treatment, "batch_file": str(batch.resolve())}; (run / "management_run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8"); return manifest


def execute_direct_scenario(run_dir: str | Path, harvest_var: str = "CHPDT") -> int:
    run = Path(run_dir); manifest_path = run / "management_run_manifest.json"; manifest = json.loads(manifest_path.read_text(encoding="utf-8")); env = os.environ.copy(); env["PYTHONPATH"] = str(PROJECT_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    result = subprocess.run([sys.executable, "-m", "src.dssat.run_dssat", "--param-csv", "pest_params.csv", "--batch", Path(manifest["batch_file"]).name, "--model", "CRGRO048", "--harvest-var", harvest_var], cwd=run, env=env, check=False)
    manifest.update(status="completed" if result.returncode == 0 else "failed", dssat_exit_code=result.returncode); manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8"); return result.returncode
