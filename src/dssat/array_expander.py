"""Expand dimensionality-reduced anchor parameters into full SPE arrays.

The extension plan (``docs/reference/参数拓展方案参考.MD`` §2.2) prescribes that
array-type SPE parameters (XVGROW-YVREF, XLEAF-YLEAF-YSTEM, etc.) be exposed
to calibration as a small number of *anchor* parameters rather than the full
node set.  This module reconstructs the full array from anchor values via
piecewise-linear interpolation, so the runner can inject complete arrays
into the SPE template at run time.

Anchor conventions (from the plan):

* **XVGROW-YVREF** (leaf area vs V-stage, 6 nodes) → 3 anchors:
  ``LAREA_EARLY``, ``LAREA_MID``, ``LAREA_LATE``.  The V-stage x-nodes
  remain fixed; the y-values at early/mid/late positions are free, and
  intermediate nodes interpolate linearly.
* **XLEAF-YLEAF** (leaf partition vs V-stage, 10 nodes) → 3 anchors:
  ``LEAF_PART_EARLY``, ``LEAF_PART_FLORAL``, ``LEAF_PART_LATE``.
* **XLEAF-YSTEM** (stem partition, shares XLEAF x-axis) → 2 anchors:
  ``STEM_PART_EARLY``, ``STEM_PART_LATE``.
* **XSTAGE-SENPOR** (senescence vs stage, 4 nodes) → 1 anchor:
  ``SENPOR_LATE`` (the late-stage senescence proportion).

Constraints enforced during expansion:
* ``0 <= YLEAF_i <= 1``
* ``0 <= YSTEM_i <= 1``
* ``YLEAF_i + YSTEM_i <= 1``  (root partition non-negative)
* ``0 <= SENPOR_i <= 1``
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class ArrayExpansion:
    """The result of expanding anchors into a full array."""

    array_name: str          # e.g. "YVREF"
    x_nodes: tuple[float, ...]   # the fixed x-axis (V-stages)
    y_values: tuple[float, ...]  # expanded y-values


def linear_interp(x: float, x0: float, y0: float, x1: float, y1: float) -> float:
    """Linear interpolation at point *x* between (x0,y0) and (x1,y1)."""
    if x1 == x0:
        return y0
    t = (x - x0) / (x1 - x0)
    return y0 + t * (y1 - y0)


def expand_anchor_series(
    x_nodes: Sequence[float],
    anchor_x: Sequence[float],
    anchor_y: Sequence[float],
) -> list[float]:
    """Expand anchor points into a full y-series at every x_node.

    Uses piecewise-linear interpolation between consecutive anchors.
    Anchor x-values must be sorted ascending and span the x_nodes range.
    """
    if len(anchor_x) != len(anchor_y):
        raise ValueError("anchor_x and anchor_y must have the same length")
    if len(anchor_x) < 2:
        raise ValueError("need at least 2 anchors for interpolation")

    result: list[float] = []
    for x in x_nodes:
        # Clamp to the anchor range (flat extrapolation at the ends).
        if x <= anchor_x[0]:
            result.append(anchor_y[0])
        elif x >= anchor_x[-1]:
            result.append(anchor_y[-1])
        else:
            for i in range(len(anchor_x) - 1):
                if anchor_x[i] <= x <= anchor_x[i + 1]:
                    result.append(linear_interp(
                        x, anchor_x[i], anchor_y[i], anchor_x[i + 1], anchor_y[i + 1]))
                    break
            else:
                result.append(anchor_y[-1])
    return result


# ---------------------------------------------------------------------------
# Specific array expansions
# ---------------------------------------------------------------------------

# XVGROW x-axis (V-stage nodes) — fixed, from SPE template line 63.
XVGROW_NODES = (0.0, 4.8, 7.4, 9.0, 10.0, 11.0)

# Anchor positions for the 3 leaf-area anchors (V-stage indices into XVGROW_NODES).
LAREA_ANCHOR_INDICES = (0, 3, 5)  # early (V0), mid (V9), late (V11)


def expand_leaf_area(larea_early: float, larea_mid: float, larea_late: float) -> ArrayExpansion:
    """Expand LAREA_EARLY/MID/LATE into the full YVREF array (6 nodes).

    The three anchors correspond to V-stage 0, 9, and 11 respectively.
    """
    anchor_x = tuple(XVGROW_NODES[i] for i in LAREA_ANCHOR_INDICES)
    anchor_y = (larea_early, larea_mid, larea_late)
    y_values = expand_anchor_series(XVGROW_NODES, anchor_x, anchor_y)
    return ArrayExpansion("YVREF", XVGROW_NODES, tuple(y_values))


# XLEAF x-axis (V-stage nodes) — fixed, from SPE template line 49.
XLEAF_NODES = (0.0, 6.1, 8.3, 10.3, 12.3, 14.6, 16.9, 18.4, 19.5, 22.1)

# Anchor positions for leaf/stem partition anchors.
LEAF_ANCHOR_INDICES = (0, 4, 9)   # early, flowering, late
STEM_ANCHOR_INDICES = (0, 9)      # early, late


def expand_leaf_partition(
    leaf_early: float, leaf_floral: float, leaf_late: float,
) -> ArrayExpansion:
    """Expand leaf-partition anchors into the full YLEAF array (10 nodes)."""
    anchor_x = tuple(XLEAF_NODES[i] for i in LEAF_ANCHOR_INDICES)
    anchor_y = (leaf_early, leaf_floral, leaf_late)
    y_values = expand_anchor_series(XLEAF_NODES, anchor_x, anchor_y)
    # Enforce 0 <= YLEAF_i <= 1.
    y_values = [max(0.0, min(1.0, v)) for v in y_values]
    return ArrayExpansion("YLEAF", XLEAF_NODES, tuple(y_values))


def expand_stem_partition(stem_early: float, stem_late: float) -> ArrayExpansion:
    """Expand stem-partition anchors into the full YSTEM array (10 nodes)."""
    anchor_x = tuple(XLEAF_NODES[i] for i in STEM_ANCHOR_INDICES)
    anchor_y = (stem_early, stem_late)
    y_values = expand_anchor_series(XLEAF_NODES, anchor_x, anchor_y)
    y_values = [max(0.0, min(1.0, v)) for v in y_values]
    return ArrayExpansion("YSTEM", XLEAF_NODES, tuple(y_values))


def validate_partition_sum(
    yleaf: Sequence[float], ystem: Sequence[float],
    tolerance: float = 0.001,
) -> list[int]:
    """Check YLEAF_i + YSTEM_i <= 1 at every node; return violating indices."""
    violations = []
    for i, (l, s) in enumerate(zip(yleaf, ystem)):
        if l + s > 1.0 + tolerance:
            violations.append(i)
    return violations


# XSTAGE x-axis (stage nodes) — fixed, from SPE template line 73.
XSTAGE_NODES = (0.0, 5.0, 14.0, 30.0)
SENPOR_DEFAULT = (0.0, 0.0, 0.12, 0.16)


def expand_senpor(senpor_late: float) -> ArrayExpansion:
    """Expand the SENPOR_LATE anchor into the full SENPOR array (4 nodes).

    Only the last node (late stage) is free; early nodes stay at template
    defaults (0.0, 0.0).  The third node interpolates.
    """
    anchor_x = (XSTAGE_NODES[1], XSTAGE_NODES[3])
    anchor_y = (SENPOR_DEFAULT[1], senpor_late)
    y_values = expand_anchor_series(XSTAGE_NODES, anchor_x, anchor_y)
    # Clamp to [0, 1].
    y_values = [max(0.0, min(1.0, v)) for v in y_values]
    return ArrayExpansion("SENPOR", XSTAGE_NODES, tuple(y_values))


def expand_water_stress_curves(
    swfac_recovery: float = 1.0,
    yswfac_mid: float = 1.0,
    swbar_recovery: float = 0.25,
    yswbar_mid: float = 1.0,
    trfac_xmid: float = 0.50,
    ytrfac_max: float = 0.0,
) -> dict[str, tuple[float, ...]]:
    """Expand six safe anchors into the three DSSAT water-response curves.

    The parameterization exactly reproduces the tomato template at its
    defaults and preserves ordered X nodes plus bounded Y responses.  It is
    deliberately lower-dimensional than exposing all 26 raw array cells.
    """
    swfac_recovery = float(swfac_recovery)
    yswfac_mid = float(yswfac_mid)
    swbar_recovery = float(swbar_recovery)
    yswbar_mid = float(yswbar_mid)
    trfac_xmid = float(trfac_xmid)
    ytrfac_max = float(ytrfac_max)
    if not 0.01 <= swfac_recovery <= 1.0:
        raise ValueError("SWFAC_REC must be within [0.01, 1.0]")
    if not 0.0 <= yswfac_mid <= 1.0:
        raise ValueError("YSWFAC_MID must be within [0, 1]")
    if not 0.01 <= swbar_recovery <= 1.0:
        raise ValueError("SWBAR_REC must be within [0.01, 1.0]")
    if not 0.0 <= yswbar_mid <= 1.0:
        raise ValueError("YSWBAR_MID must be within [0, 1]")
    if not 0.0 <= trfac_xmid <= 0.75:
        raise ValueError("TRFAC_XMID must be within [0, 0.75]")
    if not 0.0 <= ytrfac_max <= 1.0:
        raise ValueError("YTRFAC_MAX must be within [0, 1]")
    return {
        "XSWFAC": (0.0, 0.01, swfac_recovery, 1.0),
        "YSWFAC": (0.0, yswfac_mid, 1.0, 1.0),
        "XSWBAR": (0.0, 0.01, swbar_recovery, 1.0, 1.0),
        "YSWBAR": (0.0, 0.0, yswbar_mid, 1.0, 1.0),
        "XTRFAC": (0.0, trfac_xmid, 0.75, 1.0),
        "YTRFAC": (0.0, ytrfac_max, ytrfac_max, 0.0),
    }


__all__ = [
    "ArrayExpansion",
    "linear_interp", "expand_anchor_series",
    "expand_leaf_area", "expand_leaf_partition", "expand_stem_partition",
    "expand_senpor", "validate_partition_sum",
    "expand_water_stress_curves",
    "XVGROW_NODES", "XLEAF_NODES", "XSTAGE_NODES",
]
