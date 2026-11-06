"""Tests for the Morris interaction-summary aggregator (task 3a)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from tools.sa.aggregate_morris_interaction import (
    OUTPUT_COLUMNS,
    aggregate_interaction_summary,
)


def _write_effects(path: Path, rows: list[dict[str, str]]) -> Path:
    cols = ["parameter", "ranking_domain", "response_group", "mu_star", "sigma",
            "season", "seed", "mu_star_share_within_observation"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    return path


def test_one_row_per_parameter(tmp_path: Path) -> None:
    eff = _write_effects(tmp_path / "eff.csv", [
        {"parameter": "P1", "ranking_domain": "general_genetic", "response_group": "biomass",
         "mu_star": "10", "sigma": "5", "season": "S1", "seed": "1", "mu_star_share_within_observation": "0.5"},
        {"parameter": "P1", "ranking_domain": "general_genetic", "response_group": "biomass",
         "mu_star": "20", "sigma": "8", "season": "S1", "seed": "1", "mu_star_share_within_observation": "0.6"},
        {"parameter": "P2", "ranking_domain": "general_genetic", "response_group": "canopy",
         "mu_star": "1", "sigma": "0.5", "season": "S1", "seed": "1", "mu_star_share_within_observation": "0.3"},
    ])
    out = aggregate_interaction_summary(eff)
    params = {r["parameter"] for r in out}
    assert params == {"P1", "P2"}


def test_median_aggregation(tmp_path: Path) -> None:
    eff = _write_effects(tmp_path / "eff.csv", [
        {"parameter": "P1", "ranking_domain": "general_genetic", "response_group": "biomass",
         "mu_star": "10", "sigma": "5", "season": "S1", "seed": "1", "mu_star_share_within_observation": "0.5"},
        {"parameter": "P1", "ranking_domain": "general_genetic", "response_group": "biomass",
         "mu_star": "20", "sigma": "8", "season": "S1", "seed": "1", "mu_star_share_within_observation": "0.5"},
        {"parameter": "P1", "ranking_domain": "general_genetic", "response_group": "biomass",
         "mu_star": "30", "sigma": "11", "season": "S1", "seed": "1", "mu_star_share_within_observation": "0.5"},
    ])
    out = aggregate_interaction_summary(eff)
    p1 = next(r for r in out if r["parameter"] == "P1")
    assert float(p1["mu_star_median"]) == 20.0  # median of (10,20,30)
    assert float(p1["sigma_median"]) == 8.0     # median of (5,8,11)


def test_sigma_ratio_non_negative(tmp_path: Path) -> None:
    eff = _write_effects(tmp_path / "eff.csv", [
        {"parameter": "P1", "ranking_domain": "general_genetic", "response_group": "biomass",
         "mu_star": "10", "sigma": "5", "season": "S1", "seed": "1", "mu_star_share_within_observation": "0.5"},
    ])
    out = aggregate_interaction_summary(eff)
    ratio = float(out[0]["sigma_ratio"])
    assert ratio >= 0.0


def test_dominant_group_uses_share_not_raw_mustar(tmp_path: Path) -> None:
    """Dominant group is the highest dimensionless share, NOT raw mu*.

    Without this, every parameter would be 'biomass' because biomass mu*
    (kg/ha) dwarfs canopy LAI in absolute magnitude."""
    eff = _write_effects(tmp_path / "eff.csv", [
        # P1 has high raw mu* in biomass (100) but higher SHARE in canopy (0.8 vs 0.3)
        {"parameter": "P1", "ranking_domain": "general_genetic", "response_group": "biomass",
         "mu_star": "100", "sigma": "5", "season": "S1", "seed": "1", "mu_star_share_within_observation": "0.3"},
        {"parameter": "P1", "ranking_domain": "general_genetic", "response_group": "canopy",
         "mu_star": "1", "sigma": "0.5", "season": "S1", "seed": "1", "mu_star_share_within_observation": "0.8"},
    ])
    out = aggregate_interaction_summary(eff)
    assert out[0]["response_group"] == "canopy"  # share-based, not raw


def test_domain_filtering(tmp_path: Path) -> None:
    eff = _write_effects(tmp_path / "eff.csv", [
        {"parameter": "P1", "ranking_domain": "general_genetic", "response_group": "biomass",
         "mu_star": "10", "sigma": "5", "season": "S1", "seed": "1", "mu_star_share_within_observation": "0.5"},
        {"parameter": "P2", "ranking_domain": "water_nitrogen_response", "response_group": "water_response",
         "mu_star": "10", "sigma": "5", "season": "S1", "seed": "1", "mu_star_share_within_observation": "0.5"},
    ])
    out = aggregate_interaction_summary(eff, ranking_domain="general_genetic")
    assert {r["parameter"] for r in out} == {"P1"}


def test_sorted_by_descending_mu_star(tmp_path: Path) -> None:
    eff = _write_effects(tmp_path / "eff.csv", [
        {"parameter": "LOW", "ranking_domain": "general_genetic", "response_group": "biomass",
         "mu_star": "1", "sigma": "1", "season": "S1", "seed": "1", "mu_star_share_within_observation": "0.1"},
        {"parameter": "HIGH", "ranking_domain": "general_genetic", "response_group": "biomass",
         "mu_star": "100", "sigma": "1", "season": "S1", "seed": "1", "mu_star_share_within_observation": "0.9"},
    ])
    out = aggregate_interaction_summary(eff)
    assert out[0]["parameter"] == "HIGH"


def test_output_columns_match(tmp_path: Path) -> None:
    eff = _write_effects(tmp_path / "eff.csv", [
        {"parameter": "P1", "ranking_domain": "general_genetic", "response_group": "biomass",
         "mu_star": "10", "sigma": "5", "season": "S1", "seed": "1", "mu_star_share_within_observation": "0.5"},
    ])
    out = aggregate_interaction_summary(eff)
    assert set(out[0].keys()) == set(OUTPUT_COLUMNS)
