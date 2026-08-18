"""Two-spring robust orchestration: DAP materialisation + direct DSSAT per year.

This is the v2 formal search entry point.  It enforces the science gate that
the upstream parameter set must be frozen and independently validated before
any NSGA-III run that produces citable results.  Without that gate, only an
explicit ``--allow-engineering-precheck`` engineering precheck is permitted,
and its outputs are flagged ``engineering_precheck`` (never ``formal``).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import shutil
from typing import Any

from src.management.core import (
    execute_direct_scenario,
    stage_direct_scenario_run,
)
from src.management.dap_policy import (
    CandidatePolicy,
    HardConstraints,
    build_calendar_stages,
    load_dap_stages,
    materialize_dap_scenario,
    read_final_chfpw,
)
from src.management.formal_design import (
    FormalManagementDesign,
    SpringSeason,
    load_formal_design,
)
from src.management.nsga3_search import (
    DecisionBounds,
    DssatEvaluator,
    TwoYearRobustProblem,
    build_nsga3,
    decode_to_candidate,
    maximin_lhs_initial_population,
)


def _bounds_from_design(payload: dict[str, Any]) -> DecisionBounds:
    dv = payload["decision_variables"]
    return DecisionBounds(
        irrigation_mm=tuple(float(x) for x in dv["seasonal_irrigation_mm"]),
        nitrogen_kg_ha=tuple(float(x) for x in dv["seasonal_nitrogen_kg_ha"]),
        irrigation_share_floor=float(dv["irrigation_stage_shares"]["minimum_each"]),
        nitrogen_share_floor=float(dv["nitrogen_stage_shares"]["minimum_first_three"]),
    )


def _hard_constraints(payload: dict[str, Any]) -> HardConstraints:
    """Read hard constraints, preferring the dedicated field, falling back to DAP cutoff."""
    hc = payload["hard_constraints"]
    dv = payload.get("decision_variables", {})
    nitrogen_after_dap = int(dv.get("nitrogen_after_dap", hc.get("nitrogen_after_dap", 96)))
    return HardConstraints(
        irrigation_event_max_mm=float(hc["irrigation_event_max_mm"]),
        nitrogen_after_dap=nitrogen_after_dap,
        yield_floor_fraction=float(hc["yield_floor_fraction_of_year_specific_reference"]),
    )


def evaluate_policy_two_years(
    candidate: CandidatePolicy,
    design: FormalManagementDesign,
    payload: dict[str, Any],
    parameter_set_dir: Path,
    work_root: Path,
    run_id_prefix: str,
) -> dict[str, dict[str, Any]]:
    """Run one candidate in both spring weather years and read back CHFPW.

    Returns ``{"2025": {...}, "2026": {...}}`` where each value has ``chfpw``,
    ``irrigation_mm``, ``nitrogen_kg_ha``, ``status`` and ``rainfall_considered``.
    """
    dap_stages = load_dap_stages(payload["stage_policy"]["stages"])
    hard = _hard_constraints(payload)
    work_root.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, Any]] = {}

    for season in design.seasons:
        year_key = str(season.year)
        calendar = build_calendar_stages(
            dap_stages, season.planting_date, season.last_harvest_date
        )
        # Source FileX: the trial's .TMX in the actual input bundle.
        source_filex = season.actual_input_bundle / _source_filex_name(season)
        scenario_dir = work_root / f"{run_id_prefix}_{season.season_id}"
        materialize_dap_scenario(
            source_filex=source_filex,
            output_dir=scenario_dir / "scenario",
            candidate=candidate,
            calendar_stages=calendar,
            hard=hard,
            target_treatment=season.template_treatment,
            parameter_set_id=run_id_prefix,
        )
        run_dir = scenario_dir / "dssat_run"
        batch_file = season.actual_input_bundle / "DSSBatch.v48"
        stage_direct_scenario_run(
            run_dir=run_dir,
            scenario_dir=scenario_dir / "scenario",
            parameter_set_dir=parameter_set_dir,
            input_dir=season.actual_input_bundle,
            batch_file=batch_file,
            target_treatment=season.template_treatment,
        )
        rc = execute_direct_scenario(run_dir, harvest_var="CHPDT")
        chfpw = read_final_chfpw(run_dir / "FreshWt.OUT")
        results[year_key] = {
            "chfpw": chfpw if chfpw is not None else float("nan"),
            "irrigation_mm": float(candidate.seasonal_irrigation_mm),
            "nitrogen_kg_ha": float(candidate.seasonal_nitrogen_kg_ha),
            "status": "completed" if (rc == 0 and chfpw is not None) else "failed",
            "rainfall_considered": False,
            "season_id": season.season_id,
            "run_dir": str(run_dir),
        }
    return results


def _source_filex_name(season: SpringSeason) -> str:
    """Locate the .TMX FileX inside the season's actual input bundle."""
    candidates = sorted(season.actual_input_bundle.glob("*.TMX"))
    if not candidates:
        raise FileNotFoundError(f"no .TMX FileX in {season.actual_input_bundle}")
    return candidates[0].name


def _check_parameter_gate(
    parameter_set_dir: Path, allow_engineering_precheck: bool
) -> tuple[bool, dict[str, Any]]:
    """Return ``(science_validated, manifest)`` and gate the formal run.

    The v2 design's first science gate requires a frozen, independently
    validated parameter set.  Without it, only an engineering precheck is
    allowed and its outputs must be flagged as non-citable.
    """
    manifest_path = parameter_set_dir / "parameter_set_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"parameter set manifest not found: {manifest_path}"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    science_validated = bool(manifest.get("science_validated"))
    if not science_validated and not allow_engineering_precheck:
        raise PermissionError(
            "formal NSGA-III search blocked: the parameter set is not "
            "science_validated. Run with allow_engineering_precheck=True to "
            "perform a non-citable engineering precheck only."
        )
    return science_validated, manifest


def _make_evaluator(
    design: FormalManagementDesign,
    payload: dict[str, Any],
    parameter_set_dir: Path,
    work_root: Path,
    run_id_prefix: str,
) -> DssatEvaluator:
    """Bind a two-year DSSAT evaluator closure for the NSGA-III problem."""

    def evaluator(candidate: CandidatePolicy) -> dict[str, dict[str, Any]]:
        return evaluate_policy_two_years(
            candidate=candidate,
            design=design,
            payload=payload,
            parameter_set_dir=parameter_set_dir,
            work_root=work_root,
            run_id_prefix=run_id_prefix,
        )

    return evaluator


def _write_pareto_csv(
    result: Any,
    bounds: DecisionBounds,
    destination: Path,
) -> None:
    """Write the final NSGA-III population as a decoded policy table."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    X = result.pop.get("X")
    F = result.pop.get("F")
    rows = []
    for i in range(len(X)):
        candidate = decode_to_candidate(X[i], bounds, policy_id=f"pop_{i:03d}")
        rows.append(
            {
                "policy_id": candidate.policy_id,
                "seasonal_irrigation_mm": round(candidate.seasonal_irrigation_mm, 4),
                "seasonal_nitrogen_kg_ha": round(candidate.seasonal_nitrogen_kg_ha, 4),
                "w_s1": candidate.irrigation_stage_shares[0],
                "w_s2": candidate.irrigation_stage_shares[1],
                "w_s3": candidate.irrigation_stage_shares[2],
                "w_s4": candidate.irrigation_stage_shares[3],
                "n_s1": candidate.nitrogen_stage_shares[0],
                "n_s2": candidate.nitrogen_stage_shares[1],
                "n_s3": candidate.nitrogen_stage_shares[2],
                "n_s4": candidate.nitrogen_stage_shares[3],
                "neg_mean_fresh_yield": float(F[i, 0]),
                "neg_worst_year_fresh_yield": float(F[i, 1]),
                "seasonal_irrigation_mm_obj": float(F[i, 2]),
                "seasonal_nitrogen_kg_ha_obj": float(F[i, 3]),
            }
        )
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def run_formal_nsga3(
    design_path: str | Path,
    parameter_set_dir: str | Path,
    work_root: str | Path,
    seeds: list[int] | None = None,
    allow_engineering_precheck: bool = False,
    generations: int | None = None,
    population_size: int | None = None,
    initial_candidates: int | None = None,
    reference_yields: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Top-level v2 formal NSGA-III entry.

    Loads the design (which audits both weather files for zero rainfall),
    checks the parameter-science gate, then runs NSGA-III for each independent
    seed with a maximin-LHS initial population.
    """
    from pymoo.optimize import minimize

    design = load_formal_design(design_path)
    payload = json.loads(Path(design_path).read_text(encoding="utf-8"))
    optimizer = payload["optimizer"]
    if optimizer.get("algorithm") != "NSGA-III":
        raise ValueError("design optimizer is not NSGA-III")
    if optimizer.get("direct_dssat_only") is not True:
        raise ValueError("design must require direct DSSAT (no surrogate)")

    science_validated, parameter_manifest = _check_parameter_gate(
        Path(parameter_set_dir), allow_engineering_precheck
    )
    is_precheck = not science_validated
    prefix = "engineering_precheck_" if is_precheck else "formal_"

    seeds = seeds or list(optimizer["independent_seeds"])
    gens = generations if generations is not None else int(optimizer["generations"])
    pop = population_size if population_size is not None else int(optimizer["population_size"])
    n_init = initial_candidates if initial_candidates is not None else int(optimizer["initial_candidates"])

    bounds = _bounds_from_design(payload)
    yield_floor_fraction = float(
        payload["hard_constraints"]["yield_floor_fraction_of_year_specific_reference"]
    )
    refs = reference_yields or {"2025": 1.0, "2026": 1.0}

    work_root = Path(work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    run_manifest: dict[str, Any] = {
        "design_id": design.design_id,
        "approval_scope": "engineering_precheck" if is_precheck else "formal",
        "science_validated": science_validated,
        "parameter_set_id": parameter_manifest.get("parameter_set_id"),
        "seeds": seeds,
        "generations": gens,
        "population_size": pop,
        "initial_candidates": n_init,
        "objectives": list(design.objectives),
        "yield_floor_fraction": yield_floor_fraction,
        "surrogate_model": False,
        "rainfall_as_management_input": False,
        "per_seed_outputs": [],
    }

    for seed in seeds:
        evaluator = _make_evaluator(
            design=design,
            payload=payload,
            parameter_set_dir=Path(parameter_set_dir),
            work_root=work_root / f"seed_{seed}",
            run_id_prefix=f"{prefix}seed{seed}",
        )
        problem = TwoYearRobustProblem(
            bounds=bounds,
            evaluator=evaluator,
            reference_yields=refs,
            yield_floor_fraction=yield_floor_fraction,
        )
        initial = maximin_lhs_initial_population(n_init, bounds, seed=seed)
        algo = build_nsga3(
            bounds=bounds,
            optimizer_config={"population_size": pop},
            initial_population=initial,
        )
        result = minimize(problem, algo, ("n_gen", gens), seed=seed, verbose=False)
        pareto_path = work_root / f"{prefix}seed{seed}_pareto.csv"
        _write_pareto_csv(result, bounds, pareto_path)
        run_manifest["per_seed_outputs"].append(
            {
                "seed": seed,
                "pareto_csv": str(pareto_path.resolve()),
                "population_size": int(len(result.pop)),
            }
        )

    manifest_path = work_root / f"{prefix}nsga3_manifest.json"
    manifest_path.write_text(
        json.dumps(run_manifest, indent=2) + "\n", encoding="utf-8"
    )
    return run_manifest
