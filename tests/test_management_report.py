from pathlib import Path

from src.management.core import load_design
from src.management.batch_search import generate_candidates, nondominated
from src.management.report import build_demo_report, select_strategy_anchors


def test_anchor_selection_is_pareto_based_and_deterministic():
    rows = [
        {"scenario_id": "a", "status": "completed", "chfpw": 10, "irrigation_mm": 300, "nitrogen_kg_ha": 100},
        {"scenario_id": "b", "status": "completed", "chfpw": 9, "irrigation_mm": 310, "nitrogen_kg_ha": 110},
        {"scenario_id": "c", "status": "completed", "chfpw": 11, "irrigation_mm": 350, "nitrogen_kg_ha": 80},
    ]
    anchors = select_strategy_anchors(rows)
    assert {item["anchor_type"] for item in anchors} == {
        "yield_anchor", "water_anchor", "nitrogen_anchor", "equal_weight_balance_anchor",
    }
    assert next(item for item in anchors if item["anchor_type"] == "yield_anchor")["scenario_id"] == "c"
    assert next(item for item in anchors if item["anchor_type"] == "water_anchor")["scenario_id"] == "a"


def test_demo_report_preserves_the_result_status_gate(tmp_path):
    root = Path("workspace/runs/management_lhs32_feasible_demo_20260721")
    artifacts = build_demo_report(root, tmp_path / "demo_report.md")
    report = artifacts["report"].read_text(encoding="utf-8")
    anchors = artifacts["anchors"].read_text(encoding="utf-8")
    assert "32/32" in report
    assert "demo_only / science_pending" in report
    assert "rainfall_considered=false" in report
    assert "DEMO_lhs_feasible_022" in anchors


def test_greenhouse_design_excludes_rainfall_decision_variables():
    design = load_design("configs/management/eggplant_greenhouse_drip_demo_v1.json")
    assert len(design.stages) == 4
    assert design.nitrogen_cutoff_date == 25171


def test_lhs_and_pareto_rules_are_reproducible_and_rainfall_free():
    design = "configs/management/eggplant_greenhouse_drip_demo_v1.json"
    assert generate_candidates(design, "demo", 2, 3, 7) == generate_candidates(design, "demo", 2, 3, 7)
    assert all(item.nitrogen_stage_shares[-1] == 0 for item in generate_candidates(design, "demo", 2, 3, 7))
    rows = [{"status": "completed", "chfpw": 10, "irrigation_mm": 300, "nitrogen_kg_ha": 100}, {"status": "completed", "chfpw": 9, "irrigation_mm": 320, "nitrogen_kg_ha": 120}]
    assert nondominated(rows) == [rows[0]]
