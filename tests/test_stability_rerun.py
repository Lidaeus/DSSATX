from __future__ import annotations

from tools.sa import rerun_unstable_sa as rerun


def test_stability_rerun_plan_is_narrow_and_uses_fresh_case_roots() -> None:
    plan = rerun.load_plan(rerun.DEFAULT_PLAN)
    assert plan["morris"]["season"] == "XXQL2502"
    assert plan["morris"]["morris_r"] == 40
    assert plan["morris"]["seeds"] == [20260729, 20260812, 20260826]
    assert plan["sobol"]["samples"] == [128, 256]
    assert plan["sobol"]["new_sample"] == 256
    assert "stability_rerun" in plan["morris"]["case_root"]
    assert "stability_rerun" in plan["sobol"]["case_root"]


def test_stability_rerun_dry_plan_does_not_require_clean_worktree(capsys) -> None:
    assert rerun.main(["--all", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "morris-r 40" in output
    assert "N=256" in output
    assert "planned N=128 -> N=256 convergence assessment" in output
