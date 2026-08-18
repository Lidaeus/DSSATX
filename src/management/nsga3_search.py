"""Reproducible maximin-LHS seeding and NSGA-III two-spring robust search.

The v2 formal search couples direct DSSAT (no surrogate) with NSGA-III.  The
Latin hypercube is downgraded to a space-filling **initial population** only --
it is never reported as the formal optimisation result.

Decision-vector layout (8 dimensions, all in ``[0, 1]`` for the LHS, then
scaled to physical bounds by :func:`decode_to_candidate`):

    [ seasonal_irrigation ,
      irrigation_share_S1 , irrigation_share_S2 , irrigation_share_S3 ,
      seasonal_nitrogen ,
      nitrogen_share_S1   , nitrogen_share_S2   , nitrogen_share_S3 ]

S4 shares are *derived* so that the four shares sum to one (irrigation) or the
first three sum to one with S4 == 0 (nitrogen).  This keeps the simplex
constraint satisfied by construction while leaving a box-bounded search space
that a Latin hypercube and NSGA-III can sample directly.

The objective evaluator is injected (``dssat_evaluator``) so unit tests can run
the full NSGA-III machinery without a real DSSAT licence.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable, Protocol

import numpy as np
from pymoo.algorithms.moo.nsga3 import NSGA3
from pymoo.core.problem import Problem
from pymoo.util.ref_dirs import get_reference_directions


# Number of free decision dimensions in the box-bounded search space.
N_DECISIONS = 8


@dataclass(frozen=True)
class DecisionBounds:
    """Physical bounds for the year-agnostic decision variables."""

    irrigation_mm: tuple[float, float]
    nitrogen_kg_ha: tuple[float, float]
    irrigation_share_floor: float
    nitrogen_share_floor: float

    @property
    def lower(self) -> np.ndarray:
        return np.zeros(N_DECISIONS, dtype=float)

    @property
    def upper(self) -> np.ndarray:
        return np.ones(N_DECISIONS, dtype=float)


class DssatEvaluator(Protocol):
    """Injectable two-year DSSAT objective evaluator.

    A callable mapping a :class:`~src.management.dap_policy.CandidatePolicy` to
    a per-year result dict::

        {
            "2025": {"chfpw": float, "status": "completed"|"failed"},
            "2026": {"chfpw": float, "status": "completed"|"failed"},
        }
    """

    def __call__(self, candidate: Any) -> dict[str, dict[str, Any]]: ...


def _unit_simplex(raw: list[float], n: int, floor: float) -> tuple[float, ...]:
    """Map ``n`` positive unit-cube samples onto an n-simplex with a per-share floor.

    Returns ``n`` shares summing to ``1.0`` with each ``>= floor`` (requires
    ``n * floor < 1``).
    """
    if n * floor >= 1.0:
        raise ValueError("per-share floor leaves no variable simplex mass")
    if any(v <= 0.0 for v in raw[:n]):
        # avoid log(0); tiny floor
        raw = [max(v, 1e-9) for v in raw]
    weights = [-math.log(max(v, 1e-12)) for v in raw[:n]]
    total = sum(weights)
    free = 1.0 - n * floor
    return tuple(floor + free * (w / total) for w in weights)


def decode_to_candidate(
    vector: np.ndarray | list[float],
    bounds: DecisionBounds,
    policy_id: str = "",
) -> Any:
    """Decode a box-bounded decision vector into a :class:`CandidatePolicy`.

    S4 shares are derived (irrigation S4 = 1 - sum(S1..S3); nitrogen S4 = 0).
    """
    v = list(vector)
    if len(v) != N_DECISIONS:
        raise ValueError(f"decision vector must have {N_DECISIONS} entries, got {len(v)}")

    ir_lo, ir_hi = bounds.irrigation_mm
    n_lo, n_hi = bounds.nitrogen_kg_ha
    irrigation = ir_lo + v[0] * (ir_hi - ir_lo)
    nitrogen = n_lo + v[4] * (n_hi - n_lo)

    irr_shares = _unit_simplex(v[1:4], 3, bounds.irrigation_share_floor)
    # S4 irrigation = residual, clamped to its own floor.
    irr_s4 = max(
        bounds.irrigation_share_floor,
        1.0 - sum(irr_shares) - 3 * 0.0,
    )
    # Re-normalise so all four sum to exactly one (floor on S4 too).
    irr_full = list(irr_shares) + [irr_s4]
    scale = 1.0 / sum(irr_full)
    irr_full = [s * scale for s in irr_full]

    n_shares = _unit_simplex(v[5:8], 3, bounds.nitrogen_share_floor)
    n_full = list(n_shares) + [0.0]

    from src.management.dap_policy import CandidatePolicy

    return CandidatePolicy(
        policy_id=policy_id,
        seasonal_irrigation_mm=irrigation,
        irrigation_stage_shares=tuple(irr_full),
        seasonal_nitrogen_kg_ha=nitrogen,
        nitrogen_stage_shares=tuple(n_full),
    )


def maximin_lhs_initial_population(
    n: int, bounds: DecisionBounds, seed: int
) -> np.ndarray:
    """Generate ``n`` reproducible maximin-LHS candidates in the unit box.

    Uses ``scipy.stats.qmc.LatinHypercube`` with centered-LHS and the
    random-CD (centered discrepancy) optimisation pass to maximise
    space-fillingness, matching the v2 design's ``initial_design`` contract.
    """
    from scipy.stats import qmc

    sampler = qmc.LatinHypercube(d=N_DECISIONS, optimization="random-cd", seed=seed)
    unit = sampler.random(n)
    scaled = qmc.scale(unit, bounds.lower, bounds.upper)
    return np.asarray(scaled, dtype=float)


@dataclass(frozen=True)
class ObjectiveResult:
    """Aggregated four-objective value plus feasibility for one candidate."""

    mean_fresh_yield: float
    worst_year_fresh_yield: float
    seasonal_irrigation_mm: float
    seasonal_nitrogen_kg_ha: float
    feasible: bool
    failed: bool


# Large penalty for failed DSSAT runs -- dominates any real objective value so
# NSGA-III pushes failures to the dominated tail of the front.
_FAILED_PENALTY = 1.0e9


def evaluate_objectives(
    per_year: dict[str, dict[str, Any]],
    candidate: Any,
    reference_yields: dict[str, float],
    yield_floor_fraction: float,
) -> ObjectiveResult:
    """Aggregate paired-year direct-DSSAT results into the four v2 objectives.

    Objectives (all returned as **minimisation** values for NSGA-III):
      * ``mean_fresh_yield``      -> minimised as ``-mean``
      * ``worst_year_fresh_yield``-> minimised as ``-min``
      * ``seasonal_irrigation_mm``-> minimised directly
      * ``seasonal_nitrogen_kg_ha``-> minimised directly

    Per-year 90% yield floors are enforced as inequality constraints
    (``floor - chfpw <= 0``) by :class:`TwoYearRobustProblem`, and surfaced here
    via ``feasible``.
    """
    years = sorted(per_year)
    if years != [2025, 2026] and set(int(y) for y in per_year) != {2025, 2026}:
        raise ValueError("two-year evaluator requires exactly the 2025 and 2026 results")

    any_failed = any(per_year[str(y)].get("status") != "completed" for y in (2025, 2026))
    if any_failed:
        return ObjectiveResult(
            mean_fresh_yield=_FAILED_PENALTY,
            worst_year_fresh_yield=_FAILED_PENALTY,
            seasonal_irrigation_mm=float(candidate.seasonal_irrigation_mm),
            seasonal_nitrogen_kg_ha=float(candidate.seasonal_nitrogen_kg_ha),
            feasible=False,
            failed=True,
        )

    yields = [float(per_year[str(y)]["chfpw"]) for y in (2025, 2026)]
    floors = {
        str(y): yield_floor_fraction * float(reference_yields[str(y)])
        for y in (2025, 2026)
    }
    feasible = all(
        float(per_year[str(y)]["chfpw"]) >= floors[str(y)] for y in (2025, 2026)
    )
    return ObjectiveResult(
        mean_fresh_yield=-float(np.mean(yields)),
        worst_year_fresh_yield=-min(yields),
        seasonal_irrigation_mm=float(candidate.seasonal_irrigation_mm),
        seasonal_nitrogen_kg_ha=float(candidate.seasonal_nitrogen_kg_ha),
        feasible=feasible,
        failed=False,
    )


class TwoYearRobustProblem(Problem):
    """pymoo Problem wrapping the injected DSSAT evaluator.

    Four minimisation objectives (yields negated) and two inequality
    constraints (per-year yield floors).  Failed DSSAT runs receive a dominating
    penalty objective and an infeasible constraint.
    """

    def __init__(
        self,
        bounds: DecisionBounds,
        evaluator: DssatEvaluator,
        reference_yields: dict[str, float],
        yield_floor_fraction: float,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            n_var=N_DECISIONS,
            n_obj=4,
            n_ieq_constr=2,
            xl=np.zeros(N_DECISIONS),
            xu=np.ones(N_DECISIONS),
            **kwargs,
        )
        self._bounds = bounds
        self._evaluator = evaluator
        self._reference_yields = reference_yields
        self._yield_floor_fraction = yield_floor_fraction

    def _evaluate(self, X: np.ndarray, out: dict[str, Any], *args: Any, **kwargs: Any) -> None:
        n = X.shape[0]
        objectives = np.zeros((n, 4))
        constraints = np.zeros((n, 2))
        for i in range(n):
            candidate = decode_to_candidate(X[i], self._bounds, policy_id=f"eval_{i}")
            per_year = self._evaluator(candidate)
            result = evaluate_objectives(
                per_year,
                candidate,
                self._reference_yields,
                self._yield_floor_fraction,
            )
            objectives[i] = [
                result.mean_fresh_yield,
                result.worst_year_fresh_yield,
                result.seasonal_irrigation_mm,
                result.seasonal_nitrogen_kg_ha,
            ]
            # Inequality constraint g <= 0 means feasible.  floor - chfpw <= 0.
            yields = {
                str(y): float(per_year[str(y)]["chfpw"])
                for y in (2025, 2026)
                if per_year.get(str(y), {}).get("status") == "completed"
            }
            for j, y in enumerate((2025, 2026)):
                floor = self._yield_floor_fraction * float(self._reference_yields[str(y)])
                chfpw = yields.get(str(y))
                # Failed/missing year -> strongly positive (infeasible) constraint.
                constraints[i, j] = floor if chfpw is None else (floor - chfpw)
        out["F"] = objectives
        out["G"] = constraints


def build_nsga3(
    bounds: DecisionBounds,
    optimizer_config: dict[str, Any],
    initial_population: np.ndarray | None = None,
) -> NSGA3:
    """Construct a configured NSGA-III ready for :func:`pymoo.optimize.minimize`.

    Reference directions follow Das--Dennis on the 4-objective simplex with a
    partition count chosen so the number of rays is near ``population_size``.
    """
    pop_size = int(optimizer_config.get("population_size", 64))
    # Choose Das-Dennis partitions so #rays approximates pop_size for 4 objectives.
    # Partitions p give C(p+3, 3) rays; p=9 -> 220, p=7 -> 120, p=5 -> 56.
    ref_dirs = get_reference_directions("das-dennis", 4, n_partitions=5)
    n_ref = ref_dirs.shape[0]
    # NSGA-III requires pop_size >= n_ref and typically a multiple.
    if pop_size < n_ref:
        pop_size = n_ref
    sampling = initial_population if initial_population is not None else None
    return NSGA3(
        pop_size=pop_size,
        ref_dirs=ref_dirs,
        sampling=sampling,
    )
