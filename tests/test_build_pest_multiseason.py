"""Multi-season TMT resolution tests for ``src.calibration.build_pest``.

The historical stage2/harvest/v13/process observation builders resolved only
``entries[0]['filex']`` to a single ``.TMT`` and keyed harvest/process events
by treatment number.  That silently mixed seasons when a joint batch
contained more than one FileX (e.g. XXQL2501 + XXQL2502), because the same TN
number can refer to different treatments across seasons.

These tests exercise ``_collect_tmt_events_per_run`` directly and verify that
the events/points are re-keyed by the globally-unique ``@RUN`` so downstream
observation tables cannot cross seasons.
"""

from __future__ import annotations

import os

import pytest

from src.calibration import build_pest


def _stem(tmt_path) -> str:
    """Extract the FileX stem from either a str or Path-like ``tmt_path``."""
    if tmt_path is None:
        return ""
    if hasattr(tmt_path, "stem"):
        return tmt_path.stem
    base = os.path.basename(str(tmt_path))
    return base.rsplit(".", 1)[0] if "." in base else base


@pytest.fixture
def patch_tmt_readers(monkeypatch):
    """Replace the TMT readers with deterministic in-memory fixtures.

    Two synthetic FileX stems (``XXQL2501`` and ``XXQL2502``) each get their
    own harvest/process table.  Critically, both seasons define a treatment
    ``TN=3`` so a TN-keyed lookup would collide; the run-keyed lookup must
    keep them apart.
    """

    season_a_harvest = {
        2: [{"hno": 1, "date": 2025010, "dry_cum": 10.0, "dry_inc": 10.0,
              "fresh_cum": 50.0, "fresh_inc": 50.0}],
        3: [{"hno": 1, "date": 2025012, "dry_cum": 12.0, "dry_inc": 12.0,
              "fresh_cum": 60.0, "fresh_inc": 60.0}],
    }
    season_b_harvest = {
        # Same TN=3 as season A, but different content -> collisions would
        # corrupt the harvest table if we keyed on TN alone.
        3: [{"hno": 1, "date": 2025210, "dry_cum": 99.0, "dry_inc": 99.0,
              "fresh_cum": 999.0, "fresh_inc": 999.0}],
        4: [{"hno": 1, "date": 2025212, "dry_cum": 20.0, "dry_inc": 20.0,
              "fresh_cum": 80.0, "fresh_inc": 80.0}],
    }
    season_a_points = {
        2: [{"date": 2025045, "laid": 0.5, "lwad": 100.0, "swad": 50.0, "lnsd": 10.0}],
        3: [{"date": 2025045, "laid": 0.7, "lwad": 120.0, "swad": 60.0, "lnsd": 12.0}],
    }
    season_b_points = {
        3: [{"date": 2025245, "laid": 1.1, "lwad": 200.0, "swad": 110.0, "lnsd": 20.0}],
        4: [{"date": 2025245, "laid": 1.3, "lwad": 220.0, "swad": 130.0, "lnsd": 22.0}],
    }

    harvest_tables = {"XXQL2501": season_a_harvest, "XXQL2502": season_b_harvest}
    points_tables = {"XXQL2501": season_a_points, "XXQL2502": season_b_points}

    def fake_harvest_reader(tmt_path):
        return harvest_tables.get(_stem(tmt_path), {})

    def fake_points_reader(tmt_path):
        return points_tables.get(_stem(tmt_path), {})

    monkeypatch.setattr(build_pest, "_read_tmt_harvest_events", fake_harvest_reader)
    monkeypatch.setattr(build_pest, "_read_tmt_process_points", fake_points_reader)
    return harvest_tables, points_tables


def _entry(run, filex, tn):
    return {"run": run, "filex": filex, "tn": tn}


def test_collect_events_keys_by_run_not_treatment(patch_tmt_readers, monkeypatch):
    """A joint XXQL2501+XXQL2502 batch with overlapping TN=3 must not collide."""

    # build_pest._resolve_filex_path probes real files; stub it so the helper
    # accepts our synthetic stems verbatim.
    monkeypatch.setattr(
        build_pest,
        "_resolve_filex_path",
        lambda filex: f"/tmp/joint/{filex}" if filex else None,
    )

    entries = [
        _entry(1, "XXQL2501.TMX", 2),
        _entry(2, "XXQL2501.TMX", 3),
        _entry(3, "XXQL2502.TMX", 3),  # colliding TN, different season
        _entry(4, "XXQL2502.TMX", 4),
    ]

    events_by_run, points_by_run = build_pest._collect_tmt_events_per_run(entries)
    assert set(events_by_run.keys()) == {1, 2, 3, 4}
    assert set(points_by_run.keys()) == {1, 2, 3, 4}

    # Run 2 = XXQL2501 TN3, Run 3 = XXQL2502 TN3.  Same TN, different content.
    assert events_by_run[2][0]["dry_cum"] == 12.0
    assert events_by_run[3][0]["dry_cum"] == 99.0
    assert points_by_run[2][0]["lwad"] == 120.0
    assert points_by_run[3][0]["lwad"] == 200.0


def test_collect_events_caches_per_stem(patch_tmt_readers, monkeypatch):
    """Repeated FileX stems must share one TMT read, not re-read per entry."""

    monkeypatch.setattr(
        build_pest,
        "_resolve_filex_path",
        lambda filex: f"/tmp/joint/{filex}" if filex else None,
    )

    call_count = {"harvest": 0, "points": 0}
    harvest_tables, points_tables = patch_tmt_readers

    def counting_harvest(tmt_path):
        call_count["harvest"] += 1
        return harvest_tables.get(_stem(tmt_path), {})

    def counting_points(tmt_path):
        call_count["points"] += 1
        return points_tables.get(_stem(tmt_path), {})

    build_pest._read_tmt_harvest_events = counting_harvest  # type: ignore[assignment]
    build_pest._read_tmt_process_points = counting_points  # type: ignore[assignment]

    entries = [
        _entry(1, "XXQL2501.TMX", 2),
        _entry(2, "XXQL2501.TMX", 3),
        _entry(3, "XXQL2501.TMX", 2),  # same stem, third call
        _entry(4, "XXQL2502.TMX", 4),
    ]
    build_pest._collect_tmt_events_per_run(entries)
    # One read per (stem, reader), regardless of how many entries share the stem.
    assert call_count["harvest"] == 2
    assert call_count["points"] == 2


def test_collect_events_raises_on_unresolvable_filex(monkeypatch):
    """An entry whose FileX cannot be resolved must fail loudly, not silently."""

    monkeypatch.setattr(build_pest, "_resolve_filex_path", lambda filex: None)
    entries = [_entry(1, "missing.TMX", 1)]
    with pytest.raises(FileNotFoundError, match="cannot resolve FileX"):
        build_pest._collect_tmt_events_per_run(entries)
