"""Conservative mapping from measured soil intervals to DSSAT soil layers.

Water content is integrated by depth. Concentrations and percentages are
integrated by dry soil mass, using bulk density for each source interval.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DepthInterval:
    top: float
    bottom: float
    value: float
    bulk_density: float = 1.0
    source: str = "measured"

    def __post_init__(self) -> None:
        if not 0 <= self.top < self.bottom:
            raise ValueError(f"Invalid depth interval: {self.top}-{self.bottom}")
        if self.bulk_density <= 0:
            raise ValueError("Bulk density must be positive")


def map_interval(
    intervals: list[DepthInterval],
    top: float,
    bottom: float,
    *,
    mass_weighted: bool,
) -> tuple[float, list[dict[str, float | str]]]:
    """Map intervals onto one target layer; require complete, unique coverage.

    The returned contributions are suitable for a source-to-target audit.
    For a mass-weighted value, source bulk density is used in both numerator
    and denominator so the measured-layer inventory is conserved exactly.
    """
    if not 0 <= top < bottom:
        raise ValueError(f"Invalid target interval: {top}-{bottom}")
    numerator = denominator = covered = 0.0
    contributions: list[dict[str, float | str]] = []
    for interval in intervals:
        overlap = max(0.0, min(bottom, interval.bottom) - max(top, interval.top))
        if overlap == 0:
            continue
        weight = overlap * (interval.bulk_density if mass_weighted else 1.0)
        numerator += interval.value * weight
        denominator += weight
        covered += overlap
        contributions.append({
            "source_top_cm": interval.top,
            "source_bottom_cm": interval.bottom,
            "source": interval.source,
            "overlap_cm": overlap,
            "weight": weight,
            "value": interval.value,
        })
    if abs(covered - (bottom - top)) > 1e-9:
        raise ValueError(f"Measured intervals cover {covered:g} cm of target {top:g}-{bottom:g} cm")
    return numerator / denominator, contributions


def integrated_inventory(intervals: list[DepthInterval], *, mass_weighted: bool) -> float:
    """Return thickness or dry-soil-mass weighted integral of the intervals."""
    return sum(
        interval.value * (interval.bottom - interval.top)
        * (interval.bulk_density if mass_weighted else 1.0)
        for interval in intervals
    )
