"""Regression tests for the legacy-mode NameError fixes (CodeReview_BuildPest C1/C2).

The ``eggplant_harvest`` and ``eggplant_process`` legacy mode branches referenced
``events_by_run`` / ``points_by_run`` (run-number-keyed dicts produced only by
``_collect_tmt_events_per_run``) while actually calling ``_read_tmt_harvest_events``
/ ``_read_tmt_process_points``, which return ``events_by_tn`` / ``points_by_tn``
(treatment-number-keyed).  Executing either mode raised ``NameError``.

These modes are deprecated (P0-E), but the bug is severe and must not regress.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
from src.calibration import build_pest as bp_mod


# ---------------------------------------------------------------------------
# Source-level guards: the buggy variable references must be gone from the
# legacy mode bodies, while the correct (joint/stage2) branches keep them.
# ---------------------------------------------------------------------------

def _mode_body(source: str, mode: str, stop_mode: str) -> str:
    """Extract the source between `mode == "<mode>"` and the next elif/else."""
    start = source.find(f'mode == "{mode}"')
    assert start >= 0, f"mode {mode!r} not found"
    # find the next top-level elif/else after this branch
    rest = source[start:]
    # the branch ends at the next "    elif mode ==" or "    elif " at col 4
    m = re.search(r"\n    elif mode ==|\n    elif |\Z", rest[1:])
    end = (1 + m.start()) if m else len(rest)
    return rest[:end]


def test_harvest_mode_uses_events_by_tn_not_events_by_run():
    """eggplant_harvest must index events by treatment number (tn), not run_no."""
    source = (PROJECT_ROOT / "src" / "calibration" / "build_pest.py").read_text(encoding="utf-8")
    body = _mode_body(source, "eggplant_harvest", "eggplant_v13")
    # The buggy reference must be gone:
    assert "events_by_run.get(run_no" not in body, (
        "eggplant_harvest must not reference the undefined events_by_run "
        "(CodeReview C1 regression)"
    )
    # The correct reference must be present:
    assert "events_by_tn.get(tn" in body


def test_process_mode_uses_points_by_tn_not_points_by_run():
    """eggplant_process must index points by treatment number (tn), not run_no."""
    source = (PROJECT_ROOT / "src" / "calibration" / "build_pest.py").read_text(encoding="utf-8")
    body = _mode_body(source, "eggplant_process", "eggplant_spe_temp")
    assert "points_by_run.get(run_no" not in body, (
        "eggplant_process must not reference the undefined points_by_run "
        "(CodeReview C2 regression)"
    )
    assert "points_by_tn.get(tn" in body


# ---------------------------------------------------------------------------
# Helper-function correctness: the readers are tn-keyed (the fix relies on this)
# ---------------------------------------------------------------------------

HARVEST_TMT = """*EXP.DATA (T): XXQL2501 Eggplant
@TRNO   DATE  HFPOW CHFPW HPODW CHPDT PDMCD
     2 25140  4710  4710   235   235 0.050
     2 25146  9807 14517   490   725 0.050
     3 25140  4000  4000   200   200 0.050
"""

PROCESS_TMT = """*EXP.DATA (T): XXQL2501 Eggplant
@TRNO   DATE  L#SD  LAID  LWAD  SWAD
     2 25120   -99 0.295   115   148
     2 25142   -99 1.209   516   606
     3 25120   -99 0.300   120   150
"""


def test_read_tmt_harvest_events_is_tn_keyed(tmp_path):
    """The harvest reader returns a dict keyed by treatment number."""
    tmt = tmp_path / "XXQL2501.TMT"
    tmt.write_text(HARVEST_TMT, encoding="utf-8")
    events_by_tn = bp_mod._read_tmt_harvest_events(str(tmt))
    # TN 2 has two harvest events, TN 3 has one
    assert set(events_by_tn.keys()) == {2, 3}
    assert len(events_by_tn[2]) == 2
    assert len(events_by_tn[3]) == 1
    # the dry-cumulative field is read as CHPDT
    assert events_by_tn[2][0]["dry_cum"] == pytest.approx(235.0)


def test_read_tmt_process_points_is_tn_keyed(tmp_path):
    """The process reader returns a dict keyed by treatment number."""
    tmt = tmp_path / "XXQL2501.TMT"
    tmt.write_text(PROCESS_TMT, encoding="utf-8")
    points_by_tn = bp_mod._read_tmt_process_points(str(tmt))
    assert set(points_by_tn.keys()) == {2, 3}
    assert len(points_by_tn[2]) == 2
    assert points_by_tn[2][0]["laid"] == pytest.approx(0.295)


def test_harvest_lookup_by_tn_matches_reader_output(tmp_path):
    """The fixed legacy lookup `events_by_tn.get(tn, [])` returns the right events."""
    tmt = tmp_path / "XXQL2501.TMT"
    tmt.write_text(HARVEST_TMT, encoding="utf-8")
    events_by_tn = bp_mod._read_tmt_harvest_events(str(tmt))
    # simulate the legacy-mode loop with tn (not run_no)
    tn = 2
    matched = events_by_tn.get(tn, [])
    assert len(matched) == 2  # would be 0 (NameError) before the fix
    tn_missing = 99
    assert events_by_tn.get(tn_missing, []) == []
