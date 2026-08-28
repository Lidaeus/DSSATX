"""Tests for the modular parameter system and array expander."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from src.common.parameter_modules import (
    ParameterModuleError,
    compose_bounds,
    load_all_modules,
    load_module,
)
from src.dssat.array_expander import (
    expand_anchor_series,
    expand_leaf_area,
    expand_water_stress_curves,
    expand_leaf_partition,
    expand_senpor,
    expand_stem_partition,
    linear_interp,
    validate_partition_sum,
)


# ===========================================================================
# Array expander
# ===========================================================================

def test_linear_interp_midpoint() -> None:
    assert linear_interp(5, 0, 0, 10, 100) == pytest.approx(50)


def test_linear_interp_endpoints() -> None:
    assert linear_interp(0, 0, 10, 10, 20) == pytest.approx(10)
    assert linear_interp(10, 0, 10, 10, 20) == pytest.approx(20)


def test_expand_anchor_series_basic() -> None:
    x = [0, 1, 2, 3, 4]
    ax = [0, 4]
    ay = [10, 50]
    result = expand_anchor_series(x, ax, ay)
    assert result == pytest.approx([10, 20, 30, 40, 50])


def test_expand_anchor_series_clamps() -> None:
    """Values outside the anchor range are clamped (flat extrapolation)."""
    x = [-1, 0, 5, 10, 11]
    ax = [0, 10]
    ay = [100, 200]
    result = expand_anchor_series(x, ax, ay)
    assert result[0] == 100  # clamped below
    assert result[-1] == 200  # clamped above


def test_expand_leaf_area_3_anchors() -> None:
    """LAREA anchors expand to 6 YVREF nodes via interpolation."""
    exp = expand_leaf_area(15.0, 200.0, 550.0)
    assert len(exp.y_values) == 6
    assert exp.y_values[0] == pytest.approx(15.0)   # early anchor
    assert exp.y_values[5] == pytest.approx(550.0)  # late anchor
    # mid anchor is at index 3 (V=9.0)
    assert exp.y_values[3] == pytest.approx(200.0)


def test_expand_leaf_partition_clamps_0_1() -> None:
    """YLEAF values are clamped to [0, 1]."""
    exp = expand_leaf_partition(0.5, 1.5, 0.3)  # 1.5 > 1, should clamp
    assert all(0 <= v <= 1 for v in exp.y_values)


def test_expand_stem_partition_clamps_0_1() -> None:
    exp = expand_stem_partition(0.3, -0.5)  # negative, should clamp to 0
    assert all(v >= 0 for v in exp.y_values)


def test_validate_partition_sum_no_violation() -> None:
    assert validate_partition_sum([0.3, 0.4], [0.2, 0.3]) == []


def test_validate_partition_sum_finds_violation() -> None:
    violations = validate_partition_sum([0.7, 0.4], [0.5, 0.3])
    assert 0 in violations  # 0.7 + 0.5 = 1.2 > 1
    assert 1 not in violations  # 0.4 + 0.3 = 0.7 ok


def test_expand_senpor_single_anchor() -> None:
    """SENPOR_LATE expands to 4 nodes, early nodes stay near 0."""
    exp = expand_senpor(0.25)
    assert len(exp.y_values) == 4
    assert 0 <= exp.y_values[-1] <= 1


def test_water_stress_curve_defaults_reproduce_template() -> None:
    curves = expand_water_stress_curves()
    assert curves["XSWFAC"] == (0.0, 0.01, 1.0, 1.0)
    assert curves["YSWFAC"] == (0.0, 1.0, 1.0, 1.0)
    assert curves["XSWBAR"] == (0.0, 0.01, 0.25, 1.0, 1.0)
    assert curves["YSWBAR"] == (0.0, 0.0, 1.0, 1.0, 1.0)
    assert curves["XTRFAC"] == (0.0, 0.5, 0.75, 1.0)
    assert curves["YTRFAC"] == (0.0, 0.0, 0.0, 0.0)


def test_water_stress_curve_anchors_preserve_constraints() -> None:
    curves = expand_water_stress_curves(0.6, 0.5, 0.4, 0.7, 0.3, 0.2)
    assert all(a <= b for a, b in zip(curves["XSWFAC"], curves["XSWFAC"][1:]))
    assert all(a <= b for a, b in zip(curves["XSWBAR"], curves["XSWBAR"][1:]))
    assert all(a <= b for a, b in zip(curves["XTRFAC"], curves["XTRFAC"][1:]))
    assert all(0.0 <= value <= 1.0 for name in ("YSWFAC", "YSWBAR", "YTRFAC") for value in curves[name])


# ===========================================================================
# Module loading (uses fixture modules created below)
# ===========================================================================

@pytest.fixture
def temp_module_dir(tmp_path: Path, monkeypatch) -> Path:
    """Create a temporary module directory with a sample module."""
    mod_dir = tmp_path / "parameter_modules"
    mod_dir.mkdir()
    # Sample module
    (mod_dir / "01_test_module.json").write_text(json.dumps({
        "module_id": "test_module",
        "display_name_en": "Test module",
        "display_name_zh": "测试模块",
        "priority": "batch_1",
        "required_observations": ["obs1"],
        "parameters": [
            {"name": "TESTP1", "location": "SPE", "physical_bounds": [0.0, 10.0],
             "default_bounds": [1.0, 5.0], "role": "scalar",
             "scientific_note": "test parameter 1"},
            {"name": "TESTP2", "location": "ECO", "physical_bounds": [0.0, 1.0],
             "default_bounds": [0.1, 0.9], "role": "scalar",
             "scientific_note": "test parameter 2"},
        ],
        "constraints": [
            {"constraint_id": "test_ordering", "constraint_type": "ordering",
             "parameters": ["TESTP1", "TESTP2"],
             "expression": "TESTP1.init < TESTP2.init",
             "relation": "<", "field": "init"},
        ],
    }), encoding="utf-8")
    # Cross-module constraints
    (mod_dir / "_constraints.json").write_text(json.dumps({
        "constraints": []
    }), encoding="utf-8")
    # Patch MODULES_DIR
    import src.common.parameter_modules as pm
    monkeypatch.setattr(pm, "MODULES_DIR", mod_dir)
    return mod_dir


def test_load_module(temp_module_dir) -> None:
    mod = load_module("test_module")
    assert mod.module_id == "test_module"
    assert len(mod.parameters) == 2
    assert mod.parameters[0].name == "TESTP1"
    assert mod.parameters[0].location == "SPE"
    assert mod.parameters[0].default_bounds == (1.0, 5.0)
    assert mod.priority == "batch_1"


def test_load_module_missing(temp_module_dir) -> None:
    with pytest.raises(ParameterModuleError, match="not found"):
        load_module("nonexistent_module")


def test_load_module_duplicate_params(temp_module_dir) -> None:
    """Duplicate parameter names within a module are rejected."""
    bad = temp_module_dir / "02_bad.json"
    bad.write_text(json.dumps({
        "module_id": "bad", "display_name_en": "B", "display_name_zh": "坏",
        "priority": "batch_1", "required_observations": [],
        "parameters": [
            {"name": "DUP", "location": "SPE", "physical_bounds": [0, 1], "default_bounds": [0, 1]},
            {"name": "DUP", "location": "SPE", "physical_bounds": [0, 1], "default_bounds": [0, 1]},
        ],
    }), encoding="utf-8")
    with pytest.raises(ParameterModuleError, match="duplicate"):
        load_module(temp_module_dir / "02_bad.json")


def test_compose_bounds_adds_new_params(temp_module_dir) -> None:
    """Composing a module adds its parameters to the bounds."""
    rows, issues = compose_bounds(["test_module"], include_existing_v4=False)
    names = {r["name"] for r in rows}
    assert "TESTP1" in names
    assert "TESTP2" in names
    # new params should have the requested status
    p1 = next(r for r in rows if r["name"] == "TESTP1")
    assert p1["status"] == "active"
    assert p1["location"] == "SPE"


def test_compose_bounds_constraint_violation(temp_module_dir) -> None:
    """An ordering constraint violation is detected."""
    # TESTP1 default_bounds = [1,5], TESTP2 = [0.1,0.9]
    # init TESTP1 = 3.0, init TESTP2 = 0.5 → 3.0 < 0.5 is False → violation
    rows, issues = compose_bounds(["test_module"], include_existing_v4=False)
    errors = [i for i in issues if i.severity == "error"]
    assert any("TESTP1" in i.message for i in errors)


def test_compose_bounds_no_v4(temp_module_dir) -> None:
    """include_existing_v4=False skips the v4 baseline."""
    rows, issues = compose_bounds(["test_module"], include_existing_v4=False)
    # Should NOT contain v4 parameters like TRIFL, XFRT etc.
    names = {r["name"] for r in rows}
    assert "TRIFL" not in names
    assert "XFRT" not in names


def test_compose_bounds_requires_explicit_baseline_path(temp_module_dir) -> None:
    with pytest.raises(ParameterModuleError, match="explicit baseline bounds CSV"):
        compose_bounds(["test_module"], include_existing_v4=True)


def test_real_leaf_area_module_auto_resolves_mutual_exclusive_pairs() -> None:
    rows, issues = compose_bounds(["leaf_area_expansion"], include_existing_v4=False)
    errors = [i for i in issues if i.severity == "error"]
    assert not any(
        i.constraint_id in {"mutual_exclusive_slavr_slaref", "mutual_exclusive_sizlf_sizref"}
        for i in errors
    )
    by_name = {row["name"]: row for row in rows}
    assert by_name["SLAVR"]["status"] == "active"
    assert by_name["SLAREF"]["status"] == "fixed"
    assert by_name["SIZLF"]["status"] == "active"
    assert by_name["SIZREF"]["status"] == "fixed"


def test_compose_bounds_applies_status_overrides(temp_module_dir) -> None:
    rows, issues = compose_bounds(
        ["test_module"],
        include_existing_v4=False,
        status_for_new="fixed",
        activate_parameters=["TESTP2"],
    )
    by_name = {row["name"]: row for row in rows}
    assert by_name["TESTP1"]["status"] == "fixed"
    assert by_name["TESTP2"]["status"] == "active"


def test_param_name_uppercased(temp_module_dir) -> None:
    """Parameter names are always stored uppercase."""
    mod = load_module("test_module")
    for p in mod.parameters:
        assert p.name == p.name.upper()
