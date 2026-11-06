"""Tests for the Morris response-effects exporter (W2 + P0 fix, plan §10).

After the P0 review fix, the exporter reports **observation-level** Morris
statistics (exact, from .mio) and only aggregates the *dimensionless*
within-observation shares across treatments — it never claims treatment-mean
mu/mu_star/sigma (which require per-run responses not persisted by PESTPP-SEN).

Covers the W2 scientific rules (plan §5.2) plus the P0 correctness invariant:

1. raw ``mu*``/``sigma`` are never averaged across observations of different
   treatments into a fake treatment-mean statistic;
2. the two ranking domains are never merged;
3. zero/low-effect parameters are retained (no Top-K filtering);
4. ``mu`` is carried as a directional hint;
5. the within-observation share sums to 1 per observation (dimensionless);
6. the within-family share is a mean of dimensionless shares only;
7. re-running on identical inputs yields identical bytes;
8. the schema honestly documents the aggregation level and that a true
   trajectory failure rate is unavailable from .mio.
"""

from __future__ import annotations

import csv
import hashlib
import io
from collections import defaultdict
from pathlib import Path

import pytest

from tools.sa.export_morris_response_effects import (
    OUTPUT_COLUMNS,
    _parse_observation,
    export_morris_response_effects,
)


# ---------------------------------------------------------------------------
# Synthetic .mio fixture
# ---------------------------------------------------------------------------

MIO_COLUMNS = ["observation_name", "parameter_name", "n_samples", "sen_mean",
               "sen_mean_abs", "sen_std_dev"]


def _write_mio(path: Path, rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=MIO_COLUMNS)
        w.writeheader()
        for r in rows:
            full = {c: r.get(c, "0") for c in MIO_COLUMNS}
            w.writerow(full)
    return path


def _ee(obs: str, par: str, mu: float, mu_star: float, sigma: float, n: int = 10) -> dict[str, str]:
    return {"observation_name": obs, "parameter_name": par, "n_samples": str(n),
            "sen_mean": str(mu), "sen_mean_abs": str(mu_star), "sen_std_dev": str(sigma)}


@pytest.fixture
def synthetic_case(tmp_path: Path) -> tuple[str, Path]:
    """A one-season, one-seed synthetic Morris case with known effects.

    Two treatments of fruitd_end (tn1, tn2) with *different* mu_star so the
    P0 test can confirm they are NOT collapsed into a fake mean.
    """
    rows = [
        # MEAN_FRUITD_END family: P1 dominant, P2 small, P3 zero — two treatments
        _ee("tn1_fruitd_end", "P1", 10.0, 10.0, 1.0),
        _ee("tn2_fruitd_end", "P1", 8.0, 8.0, 0.9),   # different value per treatment
        _ee("tn1_fruitd_end", "P2", 1.0, 1.0, 0.5),
        _ee("tn2_fruitd_end", "P2", 2.0, 2.0, 0.4),
        _ee("tn1_fruitd_end", "P3", 0.0, 0.0, 0.0),
        _ee("tn2_fruitd_end", "P3", 0.0, 0.0, 0.0),
        # WN_WATER_FRUITD_END (two water levels)
        _ee("wn_water_n0_fruitd_end", "P1", 5.0, 5.0, 0.5),
        _ee("wn_water_n1_fruitd_end", "P1", 3.0, 3.0, 0.3),
    ]
    case_dir = tmp_path / "SEASON_A" / "seed_20260729"
    _write_mio(case_dir / "sa_sen_morris.mio", rows)
    return "SEASON_A", case_dir


# ===========================================================================
# observation-name parsing
# ===========================================================================

def test_parse_per_treatment_observation() -> None:
    tn, key = _parse_observation("tn13_fruitd_end")
    assert tn == 13
    assert key == "FRUITD_END"


def test_parse_wn_water_folds_level() -> None:
    tn, key = _parse_observation("wn_water_n0_fruitd_end")
    assert tn is None
    assert key == "WN_WATER_FRUITD_END"
    tn2, key2 = _parse_observation("wn_water_n3_fruitd_end")
    assert key2 == "WN_WATER_FRUITD_END"


def test_parse_wn_nslope_folds_water_level() -> None:
    tn, key = _parse_observation("wn_nslope_w3_agb_end_cwad")
    assert tn is None
    assert key == "WN_NSLOPE_AGB_END_CWAD"


def test_parse_wn_interaction() -> None:
    tn, key = _parse_observation("wn_interaction_lai_auc")
    assert tn is None
    assert key == "WN_INTERACTION_LAI_AUC"


# ===========================================================================
# P0 correctness: observation-level, no fake treatment-mean
# ===========================================================================

def test_one_row_per_observation_not_collapsed(synthetic_case) -> None:
    """Each observation appears as its own row; treatments are not averaged."""
    rows, _ = export_morris_response_effects("t", [synthetic_case])
    fruitd_p1 = [r for r in rows
                 if r["response_id"] == "MEAN_FRUITD_END" and r["parameter"] == "P1"]
    # two treatment observations -> two rows, each with its own exact mu_star
    assert len(fruitd_p1) == 2
    mu_stars = sorted(float(r["mu_star"]) for r in fruitd_p1)
    assert mu_stars == [8.0, 10.0]  # NOT collapsed to mean(8,10)=9
    assert {r["observation_id"] for r in fruitd_p1} == {
        "tn1_fruitd_end", "tn2_fruitd_end",
    }
    assert {r["treatment"] for r in fruitd_p1} == {"1", "2"}
    assert all(r["aggregation_level"] == "observation" for r in fruitd_p1)


def test_no_fake_treatment_mean_claim(synthetic_case) -> None:
    """The note must state raw mu/mu_star/sigma are NOT treatment-mean."""
    rows, _ = export_morris_response_effects("t", [synthetic_case])
    note = rows[0]["aggregation_note"].lower()
    assert "not" in note and "treatment-mean" in note


def test_zero_effect_parameter_retained(synthetic_case) -> None:
    """Zero-effect parameters must be retained (no Top-K filtering)."""
    rows, _ = export_morris_response_effects("t", [synthetic_case])
    p3 = [r for r in rows if r["response_id"] == "MEAN_FRUITD_END" and r["parameter"] == "P3"]
    assert p3, "zero-effect P3 must be retained"
    assert all(float(r["mu_star"]) == 0.0 for r in p3)


def test_water_levels_keep_separate_observations(synthetic_case) -> None:
    """wn_water_<level> observations are kept as separate observation rows,
    folded only in the dimensionless within-family share."""
    rows, _ = export_morris_response_effects("t", [synthetic_case])
    wn = [r for r in rows if r["response_id"] == "WN_WATER_FRUITD_END"
          and r["parameter"] == "P1"]
    assert len(wn) == 2  # two level observations, not collapsed
    assert all(r["ranking_domain"] == "water_nitrogen_response" for r in wn)


def test_ranking_domains_never_merge(synthetic_case) -> None:
    """No response_id may appear in both ranking domains."""
    rows, _ = export_morris_response_effects("t", [synthetic_case])
    domains: dict[str, set[str]] = {}
    for r in rows:
        domains.setdefault(r["response_id"], set()).add(r["ranking_domain"])
    mixed = {k: v for k, v in domains.items() if len(v) > 1}
    assert not mixed, f"responses with mixed domains: {mixed}"


def test_within_observation_share_sums_to_one(synthetic_case) -> None:
    """Within one observation, mu_star shares across parameters sum to ~1."""
    rows, _ = export_morris_response_effects("t", [synthetic_case])
    by_obs: dict[tuple, list[float]] = defaultdict(list)
    for r in rows:
        if r["mu_star_share_within_observation"]:
            by_obs[(r["season"], r["seed"], r["observation_id"],
                    r["ranking_domain"])].append(
                float(r["mu_star_share_within_observation"]))
    assert by_obs
    for shares in by_obs.values():
        assert sum(shares) == pytest.approx(1.0)


def test_within_family_share_is_mean_of_shares(synthetic_case) -> None:
    """mu_star_share_within_family is a mean of dimensionless shares, in (0,1]."""
    rows, _ = export_morris_response_effects("t", [synthetic_case])
    for r in rows:
        s = r["mu_star_share_within_family"]
        if s:
            assert 0.0 <= float(s) <= 1.0 + 1e-9


def test_mu_carries_direction(synthetic_case) -> None:
    """mu is the signed observation-level mean (directional hint)."""
    rows, _ = export_morris_response_effects("t", [synthetic_case])
    p1 = [r for r in rows
          if r["response_id"] == "MEAN_FRUITD_END" and r["parameter"] == "P1"]
    assert all(float(r["mu"]) > 0 for r in p1)


def test_n_samples_and_component_count_recorded(synthetic_case) -> None:
    """n_samples (per-observation) and component_count (family size) recorded."""
    rows, _ = export_morris_response_effects("t", [synthetic_case])
    for r in rows:
        assert r["n_samples"], "n_samples must be present"
        assert r["component_count"], "component_count must be present"
    # MEAN_FRUITD_END family has 2 treatments here
    fruitd = [r for r in rows if r["response_id"] == "MEAN_FRUITD_END"]
    assert all(r["component_count"] == "2" for r in fruitd)


def test_trajectory_failure_rate_honestly_unavailable(synthetic_case) -> None:
    """The true trajectory failure rate is unavailable from .mio."""
    rows, _ = export_morris_response_effects("t", [synthetic_case])
    assert all(r["trajectory_failure_rate_available"] == "no" for r in rows)


def test_output_columns_match_contract(synthetic_case) -> None:
    """Output rows carry exactly the corrected columns."""
    rows, _ = export_morris_response_effects("t", [synthetic_case])
    assert rows
    assert set(rows[0].keys()) == set(OUTPUT_COLUMNS)


def test_duplicate_case_rejected(tmp_path: Path) -> None:
    case_dir = tmp_path / "S" / "seed_1"
    _write_mio(case_dir / "sa_sen_morris.mio", [_ee("tn1_adaps", "P1", 1.0, 1.0, 0.1)])
    with pytest.raises(ValueError, match="duplicate case"):
        export_morris_response_effects("t", [("S", case_dir), ("S", case_dir)])


def test_missing_mio_rejected(tmp_path: Path) -> None:
    case_dir = tmp_path / "S" / "seed_1"
    case_dir.mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="sa_sen_morris.mio"):
        export_morris_response_effects("t", [("S", case_dir)])


def test_identical_inputs_yield_identical_hash(synthetic_case) -> None:
    """Determinism: re-running on identical inputs yields identical bytes."""
    rows1, manifest1 = export_morris_response_effects("t", [synthetic_case])
    rows2, manifest2 = export_morris_response_effects("t", [synthetic_case])

    def _h(rows):
        s = io.StringIO()
        w = csv.DictWriter(s, fieldnames=OUTPUT_COLUMNS)
        w.writeheader()
        w.writerows(rows)
        return hashlib.sha256(s.getvalue().encode("utf-8")).hexdigest()

    assert _h(rows1) == _h(rows2)
    assert (manifest1["source_artifacts"][0]["mio_sha256"]
            == manifest2["source_artifacts"][0]["mio_sha256"])
