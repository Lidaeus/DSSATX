from __future__ import annotations

import hashlib
import json
from itertools import combinations
from pathlib import Path

import pandas as pd
import pytest

from src.reporting.export_sa_paper_data import export_sa_bundle


PARAMETERS = ["TRIFL", "RTNO3", "XFRT", "LFMAX"]
DOMAINS = ["general_genetic", "water_nitrogen_response"]
SEEDS = [101, 202, 303]


def _write_season(root: Path, season: str, *, wn_stable: bool = True) -> None:
    directory = root / season
    directory.mkdir(parents=True)
    consensus_rows = []
    rank_rows = []
    group_rows = []
    pair_rows = []
    for domain in DOMAINS:
        for index, parameter in enumerate(PARAMETERS, 1):
            consensus_rows.append({
                "ranking_domain": domain, "parameter": parameter,
                "mean_score": 0.5 / index, "mean_rank": float(index),
                "min_rank": float(index), "max_rank": float(index), "consensus_rank": index,
            })
            for seed in SEEDS:
                rank_rows.append({
                    "seed": seed, "ranking_domain": domain, "parameter": parameter,
                    "score": 0.5 / index, "rank": float(index),
                })
                response_group = "phenology" if domain == "general_genetic" else "nitrogen_response"
                group_rows.append({
                    "seed": seed, "response_group": response_group, "parameter": parameter,
                    "group_score": 0.5 / index, "ranking_domain": domain,
                })
        for pair_index, (left, right) in enumerate(combinations(SEEDS, 2)):
            fails = domain == "water_nitrogen_response" and not wn_stable and pair_index == 0
            spearman = 0.85 if fails else 0.96
            jaccard = 0.70 if fails else 0.90
            pair_rows.append({
                "ranking_domain": domain, "seed_a": left, "seed_b": right,
                "spearman": spearman, "top_k": 15, "top_k_jaccard": jaccard,
                "passes": not fails,
            })
    pd.DataFrame(consensus_rows).to_csv(directory / "morris_consensus_ranking.csv", index=False)
    pd.DataFrame(rank_rows).to_csv(directory / "morris_seed_rankings.csv", index=False)
    pd.DataFrame(group_rows).to_csv(directory / "morris_seed_group_scores.csv", index=False)
    pd.DataFrame(pair_rows).to_csv(directory / "morris_seed_pairwise_stability.csv", index=False)
    domain_stability = {
        "general_genetic": {"stable": True},
        "water_nitrogen_response": {"stable": wn_stable},
    }
    report = {
        "schema_version": 1,
        "run_type": "formal_morris_multiseed_stability",
        "science_validated": wn_stable,
        "case_quality_validated": True,
        "ranking_stable": wn_stable,
        "parameter_count": len(PARAMETERS),
        "seed_count": len(SEEDS),
        "seeds": SEEDS,
        "top_k": 15,
        "thresholds": {"spearman": 0.90, "top_k_jaccard": 0.80},
        "domain_stability": domain_stability,
    }
    (directory / "morris_multiseed_stability.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )


def _write_focus(path: Path) -> None:
    pd.DataFrame([
        {"display_order": 1, "parameter": "TRIFL", "primary_domain": "general_genetic",
         "process_label": "Main-stem leaf appearance"},
        {"display_order": 2, "parameter": "RTNO3", "primary_domain": "water_nitrogen_response",
         "process_label": "Root nitrate uptake"},
        {"display_order": 3, "parameter": "XFRT", "primary_domain": "general_genetic",
         "process_label": "Fruit partitioning"},
    ]).to_csv(path, index=False)


def test_sa_export_requires_demo_opt_in_and_freezes_hashes(tmp_path: Path) -> None:
    root = tmp_path / "results"
    _write_season(root, "S1", wn_stable=True)
    _write_season(root, "S2", wn_stable=False)
    focus = tmp_path / "focus.csv"
    _write_focus(focus)
    out = root / "paper_data"
    with pytest.raises(ValueError, match="allow-unvalidated-demo"):
        export_sa_bundle(run_id="demo", results_root=root, out_dir=out, focus_config=focus)
    manifest_path = export_sa_bundle(
        run_id="demo", results_root=root, out_dir=out, focus_config=focus,
        allow_unvalidated_demo=True,
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["bundle_type"] == "morris_sa_evidence"
    assert payload["data_status"] == "science_pending"
    assert payload["seasons"] == ["S1", "S2"]
    assert any(not item["stable"] for item in payload["domain_status"])
    for item in payload["artifacts"]:
        artifact = out / item["path"]
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == item["sha256"]
    ranking = pd.read_csv(out / "morris_cross_season_summary.csv")
    assert set(ranking["ranking_domain"]) == set(DOMAINS)
    assert set(ranking["data_status"]) == {"science_pending"}


def test_sa_export_recomputes_stability_instead_of_trusting_flags(tmp_path: Path) -> None:
    root = tmp_path / "results"
    _write_season(root, "S1", wn_stable=True)
    _write_season(root, "S2", wn_stable=True)
    pairs_path = root / "S2" / "morris_seed_pairwise_stability.csv"
    pairs = pd.read_csv(pairs_path)
    pairs.loc[0, "passes"] = False
    pairs.to_csv(pairs_path, index=False)
    focus = tmp_path / "focus.csv"
    _write_focus(focus)
    with pytest.raises(ValueError, match="pass flags disagree"):
        export_sa_bundle(
            run_id="bad", results_root=root, out_dir=tmp_path / "out", focus_config=focus,
            allow_unvalidated_demo=True,
        )


def test_sa_export_cannot_be_formal_without_raw_source_hash_chain(tmp_path: Path) -> None:
    root = tmp_path / "results"
    _write_season(root, "S1", wn_stable=True)
    _write_season(root, "S2", wn_stable=True)
    focus = tmp_path / "focus.csv"
    _write_focus(focus)
    with pytest.raises(ValueError, match="allow-unvalidated-demo"):
        export_sa_bundle(
            run_id="not_formal", results_root=root, out_dir=tmp_path / "out", focus_config=focus,
        )
    manifest = export_sa_bundle(
        run_id="not_formal", results_root=root, out_dir=tmp_path / "demo", focus_config=focus,
        allow_unvalidated_demo=True,
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["data_status"] == "science_pending"
    assert all(not item["complete"] for item in payload["source_chain_status"])


def test_sa_paper_figures_are_r_only_and_domain_separated() -> None:
    exporter = Path("src/reporting/export_sa_paper_data.py").read_text(encoding="utf-8")
    figure = Path("paper/R/fig_sa_morris.R").read_text(encoding="utf-8")
    entry = Path("paper/R/make_all.R").read_text(encoding="utf-8")
    common = Path("paper/R/common.R").read_text(encoding="utf-8")
    assert "matplotlib" not in exporter
    assert "morris_sa_evidence" in common
    assert "read_sa_bundle" in entry
    assert 'selected("fig1_sa")' in entry
    assert 'selected("figs1_sa_stability")' in entry
    assert "ranking_domain" in figure
    assert "Hierarchy-normalised Morris score" in figure
    assert "Spearman rho" in figure
    assert "Jaccard index" in figure
    assert "mu-star" not in figure.lower()
