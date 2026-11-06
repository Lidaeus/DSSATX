import pandas as pd

from src.reporting.constraint_review import propose_constraint_reviews


def test_constraint_review_prefers_weaker_evidence_and_never_changes_bounds():
    evidence = pd.DataFrame(
        {
            "parameter": ["STRONG", "WEAK"],
            "current_lower": [0.0, 0.0],
            "current_upper": [10.0, 10.0],
            "constraint_priority": [3, 1],
            "evidence_tier": ["A", "C"],
        }
    )
    diagnostics = pd.DataFrame(
        {
            "parameter": ["STRONG", "WEAK"],
            "collapsed": [False, False],
            "iqr_shrinkage": [0.2, 0.3],
            "frac_near_lower": [0.0, 0.25],
            "frac_near_upper": [0.0, 0.0],
        }
    )
    spearman = pd.DataFrame(
        {"parameter_a": ["STRONG"], "parameter_b": ["WEAK"], "spearman": [0.91]}
    )
    pairs = pd.DataFrame(
        {
            "real_a": [1],
            "real_b": [2],
            "classification": ["prediction_similar"],
        }
    )
    candidates = pd.DataFrame(
        {
            "realization": [1, 1, 2, 2],
            "name": ["STRONG", "WEAK", "STRONG", "WEAK"],
            "value": [5.0, 1.0, 5.5, 9.0],
        }
    )
    result = propose_constraint_reviews(
        diagnostics, spearman, pairs, candidates, evidence
    )
    compensation = result.loc[
        result["finding_type"].eq("strong_posterior_compensation")
    ].iloc[0]
    assert compensation["parameters"] == "WEAK"
    assert result["automatic_bounds_change"].eq(False).all()
    assert "functional_equifinality_driver" in set(result["finding_type"])


def test_constraint_review_requires_seed_confirmation_for_collapse():
    evidence = pd.DataFrame(
        {
            "parameter": ["P"],
            "current_lower": [0.0],
            "current_upper": [1.0],
            "constraint_priority": [1],
            "evidence_tier": ["C"],
        }
    )
    diagnostics = pd.DataFrame(
        {
            "parameter": ["P"],
            "collapsed": [True],
            "iqr_shrinkage": [1.0],
            "frac_near_lower": [0.0],
            "frac_near_upper": [0.0],
        }
    )
    result = propose_constraint_reviews(
        diagnostics,
        pd.DataFrame(columns=["parameter_a", "parameter_b", "spearman"]),
        pd.DataFrame(),
        pd.DataFrame(),
        evidence,
    )
    assert len(result) == 1
    assert "independent_seed" in result.iloc[0]["recommended_action"]
