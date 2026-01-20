import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "SA_Project_Code" / "sa_postprocess_sobol.py"
spec = importlib.util.spec_from_file_location("sa_postprocess_sobol", MODULE_PATH)
sobol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sobol)


def test_indicator_key_strips_prefixes_sobol():
    assert sobol._indicator_key("TN3_FRUITD_END") == "FRUITD_END"
    assert sobol._indicator_key("MEAN_FRUITD_AUC") == "FRUITD_AUC"


def test_time_group_key():
    assert sobol._time_group_key("lai_dap028") == "lai_dap"
    assert sobol._time_group_key("fruitd_dap112") == "fruitd_dap"
    assert sobol._time_group_key("yield_hwams") == "yield_hwams"


def test_df_to_markdown_table():
    df = sobol.pd.DataFrame([{"a": 1, "b": "x"}])
    text = sobol._df_to_markdown_table(df)
    assert "| a | b |" in text
