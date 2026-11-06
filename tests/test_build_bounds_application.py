from pathlib import Path

import pytest

from src.calibration.build_pest import apply_bounds_review_csv, apply_param_review_csv


def test_frozen_bounds_apply_reviewed_initial_value_and_status(tmp_path: Path):
    bounds = tmp_path / "bounds.csv"
    bounds.write_text(
        "name,init,lower,upper,status,location,cultivar,ecotype,mode\n"
        "SD-PM,60,45,75,active,CUL,TM0008,TM0001,eggplant_pheno\n"
        "CSDL,12.33,12.33,12.33,fixed,CUL,TM0008,TM0001,eggplant_pheno\n",
        encoding="utf-8",
    )
    params = [
        {"name": "SD-PM", "init": 400.0, "lower": 45.0, "upper": 400.0, "pargp": "cultivar"},
        {"name": "CSDL", "init": 12.0, "lower": 8.0, "upper": 16.0, "pargp": "cultivar"},
    ]

    applied, report = apply_bounds_review_csv(
        params,
        str(bounds),
        cultivar="TM0008",
        ecotype="TM0001",
        mode="eggplant_pheno",
    )

    assert report["applied"] == 2
    assert applied[0]["init"] == 60.0
    assert applied[0]["status"] == "none"
    assert applied[1]["init"] == 12.33
    assert applied[1]["status"] == "fixed"


@pytest.mark.parametrize(
    "row,match",
    [
        ("SD-PM,60,80,45,active,CUL,TM0008,TM0001,eggplant_pheno", "lower <= init <= upper"),
        ("SD-PM,60,45,75,fixed,CUL,TM0008,TM0001,eggplant_pheno", "Fixed bounds"),
        ("SD-PM,60,60,60,active,CUL,TM0008,TM0001,eggplant_pheno", "zero width"),
    ],
)
def test_bounds_application_rejects_instead_of_swapping_or_clamping(tmp_path: Path, row: str, match: str):
    bounds = tmp_path / "invalid.csv"
    bounds.write_text(
        "name,init,lower,upper,status,location,cultivar,ecotype,mode\n" + row + "\n",
        encoding="utf-8",
    )
    params = [{"name": "SD-PM", "init": 60.0, "lower": 45.0, "upper": 75.0, "pargp": "cultivar"}]
    with pytest.raises(ValueError, match=match):
        apply_bounds_review_csv(
            params,
            str(bounds),
            cultivar="TM0008",
            ecotype="TM0001",
            mode="eggplant_pheno",
        )


def test_parameter_review_cannot_silently_clamp_initial_value(tmp_path: Path):
    review = tmp_path / "review.csv"
    review.write_text(
        "name,init,lower,upper,status\nSD-PM,400,45,80,active\n",
        encoding="utf-8",
    )
    params = [{"name": "SD-PM", "init": 60.0, "lower": 45.0, "upper": 75.0, "pargp": "cultivar"}]
    with pytest.raises(ValueError, match="lower <= init <= upper"):
        apply_param_review_csv(params, str(review))
