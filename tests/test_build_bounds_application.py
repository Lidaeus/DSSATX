from pathlib import Path

from src.calibration.build_pest import apply_bounds_review_csv


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
