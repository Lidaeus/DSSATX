import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "SA_Project_Code" / "sa_generate_param_review_csv.py"
spec = importlib.util.spec_from_file_location("sa_generate_param_review_csv", MODULE_PATH)
assert spec is not None and spec.loader is not None
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)


def test_default_bounds_soil_special_cases():
    lb, ub, status = gen._default_bounds("SOIL_SALB", 0.2, "SOIL")
    assert (lb, ub, status) == (0.05, 0.35, "active")
    lb, ub, status = gen._default_bounds("SOIL_SLRO", 80.0, "SOIL")
    assert (lb, ub, status) == (40.0, 95.0, "active")


def test_default_bounds_general_active():
    lb, ub, status = gen._default_bounds("RWDTH", 1.0, "ECO")
    assert lb < ub
    assert status == "active"
