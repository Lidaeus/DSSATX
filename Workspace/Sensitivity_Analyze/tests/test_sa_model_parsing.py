import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "SA_Project_Code" / "sa_model.py"
spec = importlib.util.spec_from_file_location("sa_model", MODULE_PATH)
assert spec is not None and spec.loader is not None
sa_model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sa_model)


def test_parse_evaluate_out_fills_missing(tmp_path):
    content = "@RUN TN HWAMS HIAMS\n1 2 100 0.5\n2 3 200\n"
    p = tmp_path / "Evaluate.OUT"
    p.write_text(content, encoding="utf-8")
    rows = sa_model._parse_evaluate_out(str(p))
    assert len(rows) == 2
    assert rows[1]["HIAMS"] == "-99"


def test_series_value_on_or_before():
    series = [
        {"DAP": 10, "LAID": 0.5},
        {"DAP": 20, "LAID": 1.2},
        {"DAP": 30, "LAID": 2.0},
    ]
    assert sa_model._series_value_on_or_before(series, 25, "LAID") == 1.2
    assert sa_model._series_value_on_or_before(series, 5, "LAID") == 0.5
