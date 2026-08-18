"""Trajectory-aware audit of PESTPP-SEN Morris runs.

The audit deliberately separates successful model evaluations, genuine model
failures, runtime/interruption failures, and runs that were never finalized.
Partial runs remain useful diagnostics but are never promoted to formal Morris
results.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from src.common.run_state import canonical_status, normalize_exit_code


SUCCESS_RE = re.compile(r"->run\s+(\d+)\s+processed", re.IGNORECASE)
FAILURE_RE = re.compile(
    r"run_id:(?P<run_id>\d+)\s+failed on agent:(?P<agent>.*?)\s+group_id:.*?"
    r"par_name:(?P<par_name>.*?)\s+concurrent:",
    re.IGNORECASE,
)
AGENT_RE = re.compile(r"agent_\d+", re.IGNORECASE)
FINAL_ERROR_RE = re.compile(
    r"RuntimeError:\s+DSSAT sensitivity run failed with exit code\s+(\d+)",
    re.IGNORECASE,
)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _failure_events(stderr_text: str) -> list[dict[str, Any]]:
    """Extract one structured event for each top-level SA model failure."""
    events: list[dict[str, Any]] = []
    previous_end = 0
    for match in FINAL_ERROR_RE.finditer(stderr_text):
        segment = stderr_text[previous_end : match.end()]
        previous_end = match.end()
        code = int(match.group(1))
        normalized = normalize_exit_code(code)
        if code == 1:
            failure_class = "model_failed"
            if "floating divide by zero" in segment.lower():
                detail = "dssat_floating_divide_by_zero"
            elif "candidate parameter validation failed" in segment.lower():
                detail = "candidate_validation"
            else:
                detail = "dssat_or_model_command_failure"
        else:
            failure_class = "runtime_failed"
            detail = "windows_process_termination" if normalized and normalized >= 0xC0000000 else "model_command_runtime_failure"
        events.append(
            {
                "failure_class": failure_class,
                "failure_detail": detail,
                "outer_exit_code": code,
                "outer_exit_code_hex": f"0x{normalized:08X}" if normalized is not None else "",
            }
        )
    return events


def _read_parameter_rows(path: Path) -> tuple[list[str], dict[int, dict[str, str]]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "run_id" not in reader.fieldnames:
            raise ValueError(f"Morris parameter file lacks run_id: {path}")
        parameters = [name for name in reader.fieldnames if name != "run_id"]
        rows = {int(row["run_id"]): row for row in reader}
    if not rows or not parameters:
        raise ValueError(f"Morris parameter design is empty: {path}")
    expected_ids = set(range(len(rows)))
    if set(rows) != expected_ids:
        raise ValueError("Morris run_id values must be contiguous and zero-based")
    return parameters, rows


def _infer_changed_parameter(
    rows: dict[int, dict[str, str]], parameters: list[str], run_id: int, points_per_trajectory: int
) -> str:
    if run_id % points_per_trajectory == 0:
        return ""
    previous = rows[run_id - 1]
    current = rows[run_id]
    changed = [name for name in parameters if previous[name] != current[name]]
    return changed[0] if len(changed) == 1 else "|".join(changed)


def audit_morris_case(case_dir: str | Path, case: str = "sa_sen_morris") -> dict[str, Any]:
    root = Path(case_dir).resolve()
    parameter_path = root / f"{case}.sen.par.csv"
    rmr_path = root / f"{case}.rmr"
    parameters, rows = _read_parameter_rows(parameter_path)
    planned_runs = len(rows)
    points_per_trajectory = len(parameters) + 1
    if planned_runs % points_per_trajectory:
        raise ValueError(
            f"Design has {planned_runs} points, not divisible by {points_per_trajectory} points per trajectory"
        )
    expected_trajectories = planned_runs // points_per_trajectory
    if rmr_path.is_file():
        rmr_text = rmr_path.read_text(encoding="utf-8", errors="ignore")
        successful_ids = set(map(int, SUCCESS_RE.findall(rmr_text)))
    else:
        rmr_text = ""
        successful_ids = set()

    raw_failures: list[dict[str, Any]] = []
    failures_by_agent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if rmr_text:
        for match in FAILURE_RE.finditer(rmr_text):
            run_id = int(match.group("run_id"))
            agent_match = AGENT_RE.search(match.group("agent"))
            agent = agent_match.group(0).lower() if agent_match else "unknown_agent"
            record = {
                "run_id": run_id,
                "agent": agent,
                "par_name": match.group("par_name").strip().lower(),
            }
            raw_failures.append(record)
            failures_by_agent[agent].append(record)

    event_queues: dict[str, deque[dict[str, Any]]] = {}
    agents_root = root / "_agents"
    for agent in failures_by_agent:
        stderr_path = agents_root / agent / "panther_agent.stderr.log"
        text = stderr_path.read_text(encoding="utf-8", errors="ignore") if stderr_path.is_file() else ""
        event_queues[agent] = deque(_failure_events(text))

    failures: list[dict[str, Any]] = []
    for record in raw_failures:
        event = event_queues.get(record["agent"], deque()).popleft() if event_queues.get(record["agent"]) else {}
        run_id = int(record["run_id"])
        inferred = _infer_changed_parameter(rows, parameters, run_id, points_per_trajectory)
        candidate = {name: rows[run_id][name] for name in parameters}
        merged = {
            **record,
            **event,
            "failure_class": event.get("failure_class", "unknown_failed"),
            "failure_detail": event.get("failure_detail", "missing_agent_error_context"),
            "trajectory_id": run_id // points_per_trajectory,
            "trajectory_step": run_id % points_per_trajectory,
            "changed_parameter": inferred,
            "candidate_values": candidate,
        }
        failures.append(merged)

    model_failed_ids = {int(item["run_id"]) for item in failures if item["failure_class"] == "model_failed"}
    runtime_failed_ids = {int(item["run_id"]) for item in failures if item["failure_class"] == "runtime_failed"}
    unknown_failed_ids = {int(item["run_id"]) for item in failures if item["failure_class"] == "unknown_failed"}
    all_failed_ids = model_failed_ids | runtime_failed_ids | unknown_failed_ids
    terminal_ids = successful_ids | all_failed_ids
    not_finalized_ids = set(range(planned_runs)) - terminal_ids

    trajectory_rows: list[dict[str, Any]] = []
    valid_effects = defaultdict(int)
    invalid_effects = defaultdict(int)
    invalid_effect_reasons = defaultdict(lambda: defaultdict(int))
    design_warnings: list[str] = []

    for trajectory_id in range(expected_trajectories):
        first = trajectory_id * points_per_trajectory
        block = set(range(first, first + points_per_trajectory))
        process_complete = block.issubset(terminal_ids)
        fully_valid = block.issubset(successful_ids)
        trajectory_rows.append(
            {
                "trajectory_id": trajectory_id,
                "first_run_id": first,
                "last_run_id": first + points_per_trajectory - 1,
                "process_complete": process_complete,
                "fully_valid": fully_valid,
                "successful_points": len(block & successful_ids),
                "model_failed_points": len(block & model_failed_ids),
                "runtime_failed_points": len(block & runtime_failed_ids),
                "unknown_failed_points": len(block & unknown_failed_ids),
                "not_finalized_points": len(block & not_finalized_ids),
            }
        )
        for step in range(1, points_per_trajectory):
            left = first + step - 1
            right = first + step
            changed = [name for name in parameters if rows[left][name] != rows[right][name]]
            if len(changed) != 1:
                design_warnings.append(
                    f"trajectory {trajectory_id} step {step} changes {len(changed)} parameters: {changed}"
                )
                continue
            parameter = changed[0]
            if left in successful_ids and right in successful_ids:
                valid_effects[parameter] += 1
                continue
            invalid_effects[parameter] += 1
            if left in model_failed_ids or right in model_failed_ids:
                reason = "model_failed_endpoint"
            elif left in runtime_failed_ids or right in runtime_failed_ids:
                reason = "runtime_failed_endpoint"
            elif left in unknown_failed_ids or right in unknown_failed_ids:
                reason = "unknown_failed_endpoint"
            else:
                reason = "not_finalized_endpoint"
            invalid_effect_reasons[parameter][reason] += 1

    coverage = []
    for parameter in parameters:
        valid = int(valid_effects[parameter])
        invalid = int(invalid_effects[parameter])
        coverage.append(
            {
                "parameter": parameter,
                "expected_effects": expected_trajectories,
                "valid_effects": valid,
                "invalid_effects": invalid,
                "coverage_fraction": valid / expected_trajectories if expected_trajectories else 0.0,
                **dict(invalid_effect_reasons[parameter]),
            }
        )

    run_status = _read_json(root / "run_status.json")
    manager_exit_code = run_status.get("manager_exit_code")
    process_state = canonical_status(run_status.get("status"), exit_code=manager_exit_code)
    if not rmr_path.is_file() and (root / f"{case}.mio").is_file():
        process_state = "completed"
    complete_trajectories = sum(bool(row["process_complete"]) for row in trajectory_rows)
    fully_valid_trajectories = sum(bool(row["fully_valid"]) for row in trajectory_rows)
    min_effects = min((int(row["valid_effects"]) for row in coverage), default=0)

    summary = {
        "case": case,
        "case_dir": str(root),
        "process_state": process_state,
        "manager_exit_code": manager_exit_code,
        "planned_runs": planned_runs,
        "successful_runs": len(successful_ids),
        "model_failed_runs": len(model_failed_ids),
        "runtime_failed_runs": len(runtime_failed_ids),
        "unknown_failed_runs": len(unknown_failed_ids),
        "not_finalized_runs": len(not_finalized_ids),
        "expected_trajectories": expected_trajectories,
        "complete_trajectories": complete_trajectories,
        "fully_valid_trajectories": fully_valid_trajectories,
        "parameter_count": len(parameters),
        "points_per_trajectory": points_per_trajectory,
        "valid_elementary_effects": sum(valid_effects.values()),
        "invalid_elementary_effects": sum(invalid_effects.values()),
        "minimum_valid_effects_per_parameter": min_effects,
        "mio_exists": (root / f"{case}.mio").is_file(),
        "rmr_exists": rmr_path.is_file(),
    }
    if not rmr_path.is_file():
        summary["audit_mode"] = "mio_only_no_trajectory_log"
        summary["successful_runs"] = planned_runs if summary["mio_exists"] else 0
        summary["not_finalized_runs"] = 0 if summary["mio_exists"] else planned_runs
        summary["complete_trajectories"] = expected_trajectories if summary["mio_exists"] else 0
        summary["fully_valid_trajectories"] = expected_trajectories if summary["mio_exists"] else 0
        summary["valid_elementary_effects"] = len(parameters) * expected_trajectories if summary["mio_exists"] else 0
        summary["invalid_elementary_effects"] = 0
        summary["minimum_valid_effects_per_parameter"] = expected_trajectories if summary["mio_exists"] else 0
        coverage = []
        for parameter in parameters:
            coverage.append(
                {
                    "parameter": parameter,
                    "expected_effects": expected_trajectories,
                    "valid_effects": expected_trajectories if summary["mio_exists"] else 0,
                    "invalid_effects": 0,
                    "coverage_fraction": 1.0 if summary["mio_exists"] and expected_trajectories else 0.0,
                    "audit_note": "trajectory log missing; coverage inferred from final .mio presence",
                }
            )
        trajectory_rows = []
        for trajectory_id in range(expected_trajectories):
            first = trajectory_id * points_per_trajectory
            trajectory_rows.append(
                {
                    "trajectory_id": trajectory_id,
                    "first_run_id": first,
                    "last_run_id": first + points_per_trajectory - 1,
                    "process_complete": bool(summary["mio_exists"]),
                    "fully_valid": bool(summary["mio_exists"]),
                    "successful_points": points_per_trajectory if summary["mio_exists"] else 0,
                    "model_failed_points": 0,
                    "runtime_failed_points": 0,
                    "unknown_failed_points": 0,
                    "not_finalized_points": 0,
                }
            )
        design_warnings.append(
            "Trajectory audit downgraded: sa_sen_morris.rmr is absent; completeness inferred from final .mio only."
        )
        not_finalized_ids = []
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": summary,
        "failures": failures,
        "trajectories": trajectory_rows,
        "effect_coverage": coverage,
        "not_finalized_run_ids": sorted(not_finalized_ids),
        "design_warnings": design_warnings,
    }


def write_morris_audit(audit: dict[str, Any], out_dir: str | Path) -> dict[str, Path]:
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "morris_run_audit.json"
    md_path = destination / "morris_run_audit.md"
    failures_path = destination / "morris_failures.csv"
    coverage_path = destination / "morris_effect_coverage.csv"
    trajectories_path = destination / "morris_trajectory_status.csv"

    json_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    failures = audit["failures"]
    failure_columns = [
        "run_id", "trajectory_id", "trajectory_step", "agent", "failure_class", "failure_detail",
        "outer_exit_code", "outer_exit_code_hex", "par_name", "changed_parameter", "candidate_values",
    ]
    with failures_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=failure_columns, extrasaction="ignore")
        writer.writeheader()
        for item in failures:
            row = dict(item)
            row["candidate_values"] = json.dumps(item.get("candidate_values", {}), ensure_ascii=False, sort_keys=True)
            writer.writerow(row)

    def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
        columns = sorted({key for row in rows for key in row})
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)

    _write_rows(coverage_path, audit["effect_coverage"])
    _write_rows(trajectories_path, audit["trajectories"])

    summary = audit["summary"]
    lines = [
        f"# Morris run audit: {summary['case']}", "",
        f"- Process state: `{summary['process_state']}`",
        f"- Planned/successful runs: `{summary['planned_runs']}` / `{summary['successful_runs']}`",
        f"- Model/runtime/unknown failures: `{summary['model_failed_runs']}` / `{summary['runtime_failed_runs']}` / `{summary['unknown_failed_runs']}`",
        f"- Not finalized: `{summary['not_finalized_runs']}`",
        f"- Fully valid trajectories: `{summary['fully_valid_trajectories']}` / `{summary['expected_trajectories']}`",
        f"- Valid/invalid elementary effects: `{summary['valid_elementary_effects']}` / `{summary['invalid_elementary_effects']}`",
        f"- Minimum valid effects per parameter: `{summary['minimum_valid_effects_per_parameter']}`",
        f"- Final .mio exists: `{str(summary['mio_exists']).lower()}`", "",
        "Partial or failed runs are diagnostic only and must not be used for formal parameter ranking.",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "json": json_path,
        "markdown": md_path,
        "failures": failures_path,
        "coverage": coverage_path,
        "trajectories": trajectories_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit PESTPP-SEN Morris trajectory completeness and failures")
    parser.add_argument("--case-dir", required=True)
    parser.add_argument("--case", default="sa_sen_morris")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--require-formal", action="store_true")
    args = parser.parse_args()

    audit = audit_morris_case(args.case_dir, case=args.case)
    out_dir = args.out_dir or str(Path(args.case_dir) / "morris_audit")
    paths = write_morris_audit(audit, out_dir)
    from src.common.quality import assess_morris, assess_morris_audit, load_morris_summary

    report = assess_morris_audit(audit, run_id=Path(args.case_dir).name)
    report.write(out_dir, stem="morris_run_quality")
    result_report = assess_morris(
        load_morris_summary(Path(args.case_dir) / f"{args.case}.mio"),
        run_id=Path(args.case_dir).name,
    )
    result_report.write(out_dir, stem="morris_result_quality")
    print(json.dumps(audit["summary"], ensure_ascii=False, indent=2))
    print(f"audit={paths['json']}")
    if args.require_formal:
        report.require_pass()
        result_report.require_pass()
    return 0


if __name__ == "__main__":
    sys.exit(main())
