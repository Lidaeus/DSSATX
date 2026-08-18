"""Create review-only constraint proposals from posterior/equifinality evidence.

The output is deliberately advisory.  It never edits a bounds proposal or a
frozen bounds file; doing so automatically would reuse calibration evidence as
an unrecorded prior and could hide equifinality instead of resolving it.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _validate_evidence(evidence: pd.DataFrame) -> pd.DataFrame:
    required = {
        "parameter",
        "current_lower",
        "current_upper",
        "constraint_priority",
        "evidence_tier",
    }
    missing = required - set(evidence.columns)
    if missing:
        raise ValueError(f"parameter evidence is missing columns: {sorted(missing)}")
    out = evidence.copy()
    out["parameter"] = out["parameter"].astype(str).str.strip().str.upper()
    for column in ("current_lower", "current_upper", "constraint_priority"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    if out[list(required - {"parameter", "evidence_tier"})].isna().any().any():
        raise ValueError("parameter evidence contains non-numeric bounds/priority")
    if (out["current_upper"] <= out["current_lower"]).any():
        raise ValueError("parameter evidence contains invalid bounds")
    if out["parameter"].duplicated().any():
        raise ValueError("parameter evidence contains duplicate parameters")
    return out.set_index("parameter", drop=False)


def propose_constraint_reviews(
    diagnostics: pd.DataFrame,
    spearman: pd.DataFrame,
    pair_predictions: pd.DataFrame,
    candidate_parameters: pd.DataFrame,
    evidence: pd.DataFrame,
    *,
    boundary_fraction: float = 0.20,
    strong_correlation: float = 0.80,
    collapse_shrinkage: float = 0.95,
) -> pd.DataFrame:
    """Build deterministic, non-mutating review recommendations."""
    ev = _validate_evidence(evidence)
    rows: list[dict[str, Any]] = []

    def emit(kind: str, parameters: str, action: str, reason: str, priority: str) -> None:
        rows.append(
            {
                "finding_type": kind,
                "parameters": parameters,
                "review_priority": priority,
                "recommended_action": action,
                "reason": reason,
                "automatic_bounds_change": False,
            }
        )

    for _, row in diagnostics.iterrows():
        parameter = str(row.get("parameter", "")).strip().upper()
        if parameter not in ev.index:
            continue
        lower = float(pd.to_numeric(row.get("frac_near_lower"), errors="coerce"))
        upper = float(pd.to_numeric(row.get("frac_near_upper"), errors="coerce"))
        if max(lower, upper) >= boundary_fraction:
            side = "lower" if lower >= upper else "upper"
            emit(
                "boundary_accumulation",
                parameter,
                "review_external_bound_or_model_bias; do_not_narrow_automatically",
                f"{max(lower, upper):.3f} of posterior is near the {side} bound",
                "high",
            )
        shrinkage = float(pd.to_numeric(row.get("iqr_shrinkage"), errors="coerce"))
        if _bool(row.get("collapsed")) or shrinkage >= collapse_shrinkage:
            emit(
                "posterior_collapse",
                parameter,
                "repeat_with_independent_seed_then_fix_or_narrow_using_external_evidence",
                f"collapsed={_bool(row.get('collapsed'))}; iqr_shrinkage={shrinkage:.3f}",
                "high",
            )

    for _, row in spearman.iterrows():
        a = str(row.get("parameter_a", "")).strip().upper()
        b = str(row.get("parameter_b", "")).strip().upper()
        rho = float(pd.to_numeric(row.get("spearman"), errors="coerce"))
        if a not in ev.index or b not in ev.index or abs(rho) < strong_correlation:
            continue
        priority_a = float(ev.loc[a, "constraint_priority"])
        priority_b = float(ev.loc[b, "constraint_priority"])
        if priority_a == priority_b:
            target = f"{a};{b}"
            action = "seek_discriminating_observation_or_review_pairwise_constraint"
        else:
            # Lower priority means weaker direct/external support and is the
            # first parameter to constrain, never the better-supported member.
            target = a if priority_a < priority_b else b
            action = "fix_or_tighten_weaker_parameter_using_external_evidence"
        emit(
            "strong_posterior_compensation",
            target,
            action,
            f"Spearman rho={rho:.3f} for {a} and {b}",
            "high",
        )

    if not pair_predictions.empty and not candidate_parameters.empty:
        params = candidate_parameters.copy()
        params["name"] = params["name"].astype(str).str.strip().str.upper()
        params["realization"] = pd.to_numeric(params["realization"], errors="coerce")
        params["value"] = pd.to_numeric(params["value"], errors="coerce")
        for _, pair in pair_predictions.iterrows():
            classification = str(pair.get("classification", ""))
            if classification != "prediction_similar":
                continue
            real_a = int(pair["real_a"])
            real_b = int(pair["real_b"])
            a_values = params.loc[params["realization"].eq(real_a)].set_index("name")["value"]
            b_values = params.loc[params["realization"].eq(real_b)].set_index("name")["value"]
            distances: list[tuple[float, str]] = []
            for parameter in sorted(set(a_values.index) & set(b_values.index) & set(ev.index)):
                span = float(ev.loc[parameter, "current_upper"] - ev.loc[parameter, "current_lower"])
                distances.append((abs(float(a_values[parameter]) - float(b_values[parameter])) / span, parameter))
            for distance, parameter in sorted(distances, reverse=True)[:3]:
                emit(
                    "functional_equifinality_driver",
                    parameter,
                    "review_fix_or_tighten_with_external_evidence_or_add_discriminating_observation",
                    f"pair {real_a}/{real_b} is prediction_similar; normalized parameter distance={distance:.3f}",
                    "high" if distance >= 0.5 else "medium",
                )

    columns = [
        "finding_type",
        "parameters",
        "review_priority",
        "recommended_action",
        "reason",
        "automatic_bounds_change",
    ]
    result = pd.DataFrame(rows, columns=columns).drop_duplicates()
    if result.empty:
        return result
    order = {"high": 0, "medium": 1, "low": 2}
    result["_order"] = result["review_priority"].map(order).fillna(9)
    return result.sort_values(
        ["_order", "finding_type", "parameters"], kind="stable"
    ).drop(columns="_order").reset_index(drop=True)


def _require_science_validated(frames: list[pd.DataFrame], allow_provisional: bool) -> None:
    statuses: set[str] = set()
    for frame in frames:
        if "data_status" in frame:
            statuses.update(frame["data_status"].dropna().astype(str).str.strip())
    if statuses != {"science_validated"} and not allow_provisional:
        raise ValueError(
            f"equifinality evidence is not uniformly science_validated ({sorted(statuses)}); "
            "pass --allow-provisional only for interface QA"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a review-only constraint proposal")
    parser.add_argument("--posterior-diagnostics", required=True)
    parser.add_argument("--spearman", required=True)
    parser.add_argument("--pair-predictions", required=True)
    parser.add_argument("--candidate-parameters", required=True)
    parser.add_argument("--parameter-evidence", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--allow-provisional", action="store_true")
    args = parser.parse_args(argv)
    diagnostics = pd.read_csv(args.posterior_diagnostics)
    spearman = pd.read_csv(args.spearman)
    pairs = pd.read_csv(args.pair_predictions)
    candidates = pd.read_csv(args.candidate_parameters)
    _require_science_validated([diagnostics, spearman, pairs], args.allow_provisional)
    proposal = propose_constraint_reviews(
        diagnostics,
        spearman,
        pairs,
        candidates,
        pd.read_csv(args.parameter_evidence),
    )
    output = Path(args.out).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    proposal.to_csv(output, index=False, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
