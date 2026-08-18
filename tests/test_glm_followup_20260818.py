"""Unit tests for the PEST-GLM follow-up pipeline (plan 20260818, section 11).

Covers: approved pool ordering, name normalization, posterior-bound rules,
member-126 containment, soil/IC fixation, objective-arm weights, the
``phi = lambda * (1 - NSE)`` identity, the W2-W1 response contract, and the
10/12 treatment contract.

Integration tests require the formal IES run directory and are skipped when
it is absent.
"""

from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.calibration.prepare_ies_to_glm_20260818 import (
    APPROVED_TOPK_CSV,
    ARM_RESPONSE_LAMBDAS,
    DEFAULT_SELECTED_SET_CSV,
    IES_CASE,
    IES_DIR,
    apply_response_nse_weights,
    build_glm_case,
    compute_posterior_bounds,
    load_approved_pool,
    load_selected_pool,
    nse_uniform_weight,
)

PLAN_TOP15 = [
    "rtno3", "trifl", "xfrt", "lfmax", "xfint", "frlff", "pm06", "rtnh4",
    "nmobmx", "em-v1", "em-fl", "tb2", "to11", "frstmf", "nvsmob",
]
PLAN_TOP23_EXTRA = [
    "fl-sd", "porpt", "to12", "atop", "nstfac", "tb1", "to22", "tm2",
]


# ── approved pool ───────────────────────────────────────────────────

def test_top15_order_matches_approved_csv():
    assert load_approved_pool(APPROVED_TOPK_CSV, 15) == PLAN_TOP15


def test_top23_order_matches_approved_csv():
    assert load_approved_pool(APPROVED_TOPK_CSV, 23) == PLAN_TOP15 + PLAN_TOP23_EXTRA


def test_pool_names_are_lowercase_normalized():
    pool = load_approved_pool(APPROVED_TOPK_CSV, 23)
    assert all(n == n.lower() for n in pool)


def test_pool_rejects_oversized_k():
    with pytest.raises(ValueError):
        load_approved_pool(APPROVED_TOPK_CSV, 24)


# ── selected pool (WP3 recommendation) ──────────────────────────────

def test_selected_pool_reads_recommendation_csv(tmp_path):
    csv = tmp_path / "sel.csv"
    csv.write_text("rank,parameter,css_scaled\n1,pm06,10\n2,xfint,9\n", encoding="utf-8")
    assert load_selected_pool(csv) == ["pm06", "xfint"]


def test_selected_pool_rejects_over_cap(tmp_path):
    csv = tmp_path / "sel.csv"
    names = ",".join(f"p{i}" for i in range(19))
    csv.write_text("rank,parameter\n1," + "\n1,".join([]) + "\n" +
                   "".join(f"{i},p{i}\n" for i in range(19)), encoding="utf-8")
    with pytest.raises(ValueError, match="caps formal"):
        load_selected_pool(csv)


def test_selected_pool_rejects_duplicates(tmp_path):
    csv = tmp_path / "sel.csv"
    csv.write_text("rank,parameter\n1,pm06\n2,pm06\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_selected_pool(csv)


# ── posterior bounds (plan section 4.2) ─────────────────────────────

def test_bounds_basic_padding_and_clip():
    ens = np.linspace(10.0, 20.0, 200)
    out = compute_posterior_bounds(ens, member_value=15.0, frozen_lo=0.0, frozen_hi=40.0)
    width = out["q975"] - out["q025"]
    assert out["glm_lo"] == pytest.approx(max(0.0, out["q025"] - 0.10 * width))
    assert out["glm_hi"] == pytest.approx(min(40.0, out["q975"] + 0.10 * width))


def test_bounds_member_outside_posterior_is_included():
    ens = np.linspace(10.0, 12.0, 200)          # posterior far below member
    out = compute_posterior_bounds(ens, member_value=30.0, frozen_lo=0.0, frozen_hi=40.0)
    assert out["glm_lo"] <= 30.0 <= out["glm_hi"]
    assert any("include member 126" in r for r in out["reasons"])


def test_bounds_narrow_posterior_widened_to_ten_percent():
    ens = np.full(200, 10.0) + np.linspace(0, 0.01, 200)   # width ~0.01 << 5% of 40
    out = compute_posterior_bounds(ens, member_value=10.0, frozen_lo=0.0, frozen_hi=40.0)
    assert out["glm_hi"] - out["glm_lo"] >= 0.10 * 40.0 - 1e-6
    assert any("5% of frozen width" in r for r in out["reasons"])


def test_bounds_member_at_frozen_edge_uses_full_bound():
    ens = np.linspace(30.0, 39.0, 200)
    out = compute_posterior_bounds(ens, member_value=40.0, frozen_lo=0.0, frozen_hi=40.0)
    assert out["glm_hi"] == 40.0
    assert any("full frozen upper bound" in r for r in out["reasons"])


def test_bounds_respect_physical_bounds():
    ens = np.linspace(0.0, 50.0, 200)
    out = compute_posterior_bounds(ens, member_value=25.0, frozen_lo=0.0, frozen_hi=50.0,
                                   physical_lo=2.0, physical_hi=48.0)
    assert out["glm_lo"] >= 2.0 and out["glm_hi"] <= 48.0
    assert "lower clipped to PHYSICAL_BOUNDS" in out["reasons"]
    assert "upper clipped to PHYSICAL_BOUNDS" in out["reasons"]


# ── NSE weight identity ─────────────────────────────────────────────

def test_nse_uniform_weight_identity():
    obs = np.array([100.0, 250.0, 400.0, 900.0])
    lam = 75.0
    w, sst = nse_uniform_weight(obs, lam)
    # phi = sum(w^2 r^2) == lam * SSE / SST == lam * (1 - NSE)
    sse = 12345.0
    phi = 4 * (w ** 2) * (sse / 4)  # equal per-obs residuals -> SSE total
    assert phi == pytest.approx(lam * sse / sst, rel=1e-12)


def test_nse_weight_rejects_constant_observations():
    with pytest.raises(ValueError):
        nse_uniform_weight(np.full(5, 7.0), 1.0)


def _synthetic_registry() -> pd.DataFrame:
    names, groups, seasons, values = [], [], [], []
    for season, vals in (("25SP", [10.0, 20.0, 40.0, 80.0]), ("26SP", [5.0, 15.0, 30.0])):
        for i, v in enumerate(vals):
            names.append(f"nresp_{season.lower()}_{i}")
            groups.append(f"{season}_NRESPM_H1")
            seasons.append(season)
            values.append(v)
    return pd.DataFrame({
        "obsnme": names, "obgnme": groups, "season_id": seasons,
        "raw_obsval": values, "transform": "raw",
    })


def test_apply_response_nse_weights_sets_uniform_sqrt_lambda_over_sst():
    reg = _synthetic_registry()
    obs_data = pd.DataFrame({"weight": np.full(len(reg), 1e-3)}, index=reg["obsnme"])
    obs_data, audit = apply_response_nse_weights(reg, obs_data, {"N_RESPONSE": 1.0})
    for row in audit:
        rows = reg[reg["season_id"] == row["season"]]
        sst = float(np.square(rows["raw_obsval"] - rows["raw_obsval"].mean()).sum())
        expected = math.sqrt(row["lambda"] / sst)
        got = obs_data.loc[rows["obsnme"], "weight"].to_numpy()
        assert np.allclose(got, expected)


def test_apply_response_weights_rejects_non_raw_transform():
    reg = _synthetic_registry()
    reg.loc[0, "transform"] = "log"
    obs_data = pd.DataFrame({"weight": np.full(len(reg), 1e-3)}, index=reg["obsnme"])
    with pytest.raises(ValueError, match="raw-scale"):
        apply_response_nse_weights(reg, obs_data, {"N_RESPONSE": 1.0})


def test_arm_lambda_table_matches_plan():
    assert ARM_RESPONSE_LAMBDAS["A"] is None
    assert ARM_RESPONSE_LAMBDAS["B"] == {"N_RESPONSE": 1.0, "W_RESPONSE": 0.5}
    assert ARM_RESPONSE_LAMBDAS["C"] == {"N_RESPONSE": 0.5, "W_RESPONSE": 0.25}


# ── code-review 20260818 regressions ───────────────────────────────

def test_step_stability_detects_direction_flip():
    from tools.calibration.analyze_glm_jacobian_20260818 import step_stability
    import pandas as pd
    a = pd.DataFrame({"p": [1.0, 2.0, -1.0], "q": [0.5, 0.5, 0.5]})
    flipped = pd.DataFrame({"p": [-1.0, -2.2, 1.1], "q": [0.6, 0.4, 0.5]})
    weights = pd.Series([1.0, 1.0, 1.0], index=list(range(3)))
    a.index = weights.index
    flipped.index = weights.index
    out = step_stability({"s1": a, "s2": flipped}, weights)
    p = out[out["parameter"] == "p"].iloc[0]
    q = out[out["parameter"] == "q"].iloc[0]
    assert p["stable"] is False or bool(p["stable"]) is False
    assert bool(q["stable"]) is True
    assert float(p["min_cosine"]) < 0


def test_step_stability_single_step_is_unverified():
    from tools.calibration.analyze_glm_jacobian_20260818 import step_stability
    import pandas as pd
    a = pd.DataFrame({"p": [1.0, 2.0]}, index=[0, 1])
    weights = pd.Series([1.0, 1.0], index=[0, 1])
    out = step_stability({"only": a}, weights)
    assert out.iloc[0]["stable"] is None


def test_singular_values_are_unit_invariant():
    from tools.calibration.analyze_glm_jacobian_20260818 import singular_values
    import pandas as pd
    jac = pd.DataFrame({"p": [1.0, 2.0], "q": [0.5, -1.0]}, index=["o1", "o2"])
    weights = pd.Series([1.0, 1.0], index=["o1", "o2"])
    ranges = pd.Series({"p": 2.0, "q": 4.0})
    _, base = singular_values(jac, weights, ranges)
    # Express p in units 10x larger: numeric values shrink 10x (range /10) and
    # the derivative column grows 10x, leaving every range-scaled entry — and
    # therefore the spectrum — unchanged.
    jac2 = jac.copy()
    jac2["p"] = jac2["p"] * 10.0
    ranges2 = ranges.copy()
    ranges2["p"] = ranges2["p"] / 10.0
    _, rescaled = singular_values(jac2, weights, ranges2)
    assert base["effective_rank"] == rescaled["effective_rank"]
    assert base["condition_number"] == pytest.approx(rescaled["condition_number"], rel=1e-9)


def test_not_assessed_gate_blocks_engineering_pass():
    from tools.calibration.evaluate_glm_followup_20260818 import engineering_gates
    baseline = {
        "DRY_CUM": {"nse": {"25SP": 0.9, "26SP": 0.8}, "pbias_pct": {}},
        "N_RESPONSE": {"nse": {"25SP": -1.0, "26SP": -3.0}},
        "W_RESPONSE": {"nse": {"25SP": -1.5, "26SP": -1.4}},
        "ORGAN": {"LAID": {"nse": {"25SP": 0.8, "26SP": 0.2}}},
    }
    candidate = {"DRY_CUM": {"25SP": {"nse": 0.91, "pbias_pct": 1.0},
                             "26SP": {"nse": 0.81, "pbias_pct": 2.0}},
                 "N_RESPONSE": {"25SP": {"nse": -0.9}, "26SP": {"nse": -2.9}},
                 "W_RESPONSE": {"25SP": {"nse": -1.4}, "26SP": {"nse": -1.3}}}
    passed, checks = engineering_gates(candidate, baseline, source="unit")
    assert passed is False
    assert any(c["status"] == "not_assessed" for c in checks)


def test_replacement_decision_requires_all_hard_criteria():
    from tools.calibration.evaluate_glm_followup_20260818 import replacement_decision
    baseline = {
        "DRY_CUM": {"nse": {"25SP": 0.905, "26SP": 0.877}},
        "N_RESPONSE": {"nse": {"25SP": -0.9, "26SP": -3.5}},
        "W_RESPONSE": {"nse": {"25SP": -1.6, "26SP": -1.4}},
        "ORGAN": {"LAID": {"nse": {"25SP": 0.8, "26SP": 0.2}},
                  "LWAD": {"nse": {"25SP": 0.8, "26SP": 0.6}},
                  "SWAD": {"nse": {"25SP": 0.9, "26SP": 0.8}}},
    }
    strong = {"DRY_CUM": {"25SP": {"nse": 0.91}, "26SP": {"nse": 0.88}},
              "N_RESPONSE": {"25SP": {"nse": -0.5}, "26SP": {"nse": -3.0}},
              "W_RESPONSE": {"25SP": {"nse": -1.0}, "26SP": {"nse": -1.0}},
              "ORGAN": {"LAID": {"25SP": 0.85, "26SP": 0.3},
                        "LWAD": {"25SP": 0.82, "26SP": 0.62},
                        "SWAD": {"25SP": 0.91, "26SP": 0.81}}}
    decision = replacement_decision(strong, baseline, at_bound_params=[])
    assert decision["replaces_member126"] is True
    weak = {"DRY_CUM": {"25SP": {"nse": 0.90}, "26SP": {"nse": 0.86}},
            "N_RESPONSE": {"25SP": {"nse": -1.2}, "26SP": {"nse": -3.4}},
            "W_RESPONSE": {"25SP": {"nse": -1.0}, "26SP": {"nse": -1.0}},
            "ORGAN": {"LAID": {"25SP": 0.85, "26SP": 0.3},
                      "LWAD": {"25SP": 0.82, "26SP": 0.62},
                      "SWAD": {"25SP": 0.91, "26SP": 0.81}}}
    decision2 = replacement_decision(weak, baseline, at_bound_params=[])
    assert decision2["replaces_member126"] is False
    decision3 = replacement_decision(strong, baseline, at_bound_params=["porpt"])
    assert decision3["criteria"]["no_new_bound_pressure"] == "manual_review"
    assert decision3["replaces_member126"] is False


# ── integration against the formal IES baseline ─────────────────────

pytestmark_integration = pytest.mark.skipif(
    not (IES_DIR / f"{IES_CASE}.pst").is_file(), reason="formal IES baseline not present"
)


@pytestmark_integration
def test_default_selected_set_exists_and_valid():
    assert DEFAULT_SELECTED_SET_CSV.is_file()
    pool = load_selected_pool(DEFAULT_SELECTED_SET_CSV)
    assert 1 <= len(pool) <= 18
    assert pool == ["pm06", "xfint", "trifl", "frlff", "rtno3", "nmobmx",
                    "nvsmob", "frstmf", "rtnh4"]


@pytest.fixture(scope="module")
def glm_case_dir(tmp_path_factory):
    out = build_glm_case("top15", "A", "pilot", 1, date_tag="unittest")
    yield out
    shutil.rmtree(out, ignore_errors=True)


@pytestmark_integration
def test_build_pool_and_fixation(glm_case_dir):
    import pyemu
    case = glm_case_dir.name
    pst = pyemu.Pst(str(glm_case_dir / f"{case}.pst"))
    par = pst.parameter_data
    selected = load_approved_pool(APPROVED_TOPK_CSV, 15)
    adjustable = par[par.partrans.astype(str).str.lower() != "fixed"]
    assert sorted(adjustable.index) == sorted(selected)
    soil_fixed = par[par.pargp.astype(str).str.startswith(("soil", "initial_conditions"))]
    assert (soil_fixed.partrans.astype(str).str.lower() == "fixed").all()


@pytestmark_integration
def test_member126_inside_bounds_and_used_as_init(glm_case_dir):
    import pyemu
    case = glm_case_dir.name
    pst = pyemu.Pst(str(glm_case_dir / f"{case}.pst"))
    par = pst.parameter_data
    member = pd.read_csv(IES_DIR / f"{IES_CASE}.6.par.csv")
    row = member[member["real_name"].astype(str).str.replace(r"\.0$", "", regex=True).eq("126")].iloc[0]
    for name in par.index:
        value = float(row[name])
        assert value == pytest.approx(float(par.loc[name, "parval1"]), rel=1e-9)
        if par.loc[name, "partrans"] != "fixed":
            assert par.loc[name, "parlbnd"] <= value <= par.loc[name, "parubnd"], name


@pytestmark_integration
def test_arm_a_weights_identical_to_ies(glm_case_dir):
    import pyemu
    case = glm_case_dir.name
    glm = pyemu.Pst(str(glm_case_dir / f"{case}.pst"))
    ies = pyemu.Pst(str(IES_DIR / f"{IES_CASE}.pst"))
    a = glm.observation_data["weight"].astype(float)
    b = ies.observation_data["weight"].astype(float)
    assert np.allclose(a.to_numpy(), b.to_numpy())


@pytestmark_integration
def test_dry_cumulative_nse_identity_inherited(glm_case_dir):
    case = glm_case_dir.name
    reg = pd.read_csv(glm_case_dir / f"{case}_observation_registry.csv", encoding="utf-8-sig")
    import pyemu
    pst = pyemu.Pst(str(glm_case_dir / f"{case}.pst"))
    dry = reg[reg["sim_token"].astype(str).isin(["CHPDTS", "CHPDTS_T"])]
    for season, rows in dry.groupby("season_id"):
        obs = rows["raw_obsval"].to_numpy(float)
        sst = float(np.square(obs - obs.mean()).sum())
        w = pst.observation_data.loc[rows["obsnme"].str.lower(), "weight"].astype(float).to_numpy()
        assert np.allclose(w, math.sqrt(75.0 / sst)), season


@pytestmark_integration
def test_design_contracts_w2_minus_w1_and_treatments():
    design = json.loads((IES_DIR / "joint_design.json").read_text(encoding="utf-8"))
    water = design["water_response_objective"]
    assert water["contrast"] == "W2_minus_W1_within_same_nitrogen"
    assert water["high_water"] == "W2" and water["low_water"] == "W1"
    counts = {s["season_id"]: len(s["treatments"]) for s in design["seasons"]}
    assert counts == {"25SP": 10, "26SP": 12}


@pytestmark_integration
def test_glm_pst_strips_ies_options_and_sets_estimation(glm_case_dir):
    import pyemu
    case = glm_case_dir.name
    pst = pyemu.Pst(str(glm_case_dir / f"{case}.pst"))
    assert pst.control_data.pestmode == "estimation"
    assert pst.control_data.noptmax == 1
    assert not [k for k in pst.pestpp_options if k.startswith("ies_")]
    assert "pest.stp" not in pst.pestpp_options
    command = pst.model_command
    joined = " ".join(command) if isinstance(command, list) else str(command)
    assert glm_case_dir.as_posix() in joined and IES_CASE not in joined


@pytestmark_integration
def test_derinc_one_percent_of_glm_range(glm_case_dir):
    import pyemu
    case = glm_case_dir.name
    pst = pyemu.Pst(str(glm_case_dir / f"{case}.pst"))
    par = pst.parameter_data
    for name in [g for g in pst.parameter_groups.index if str(g).startswith("glm_")]:
        row = pst.parameter_groups.loc[name]
        derinc = float(row["derinc"])
        assert row["inctyp"] == "absolute"
        members = par[par.pargp == name]
        assert len(members) == 1
        m = members.index[0]
        expected = 0.01 * (float(par.loc[m, "parubnd"]) - float(par.loc[m, "parlbnd"]))
        assert derinc == pytest.approx(expected, rel=1e-9)
