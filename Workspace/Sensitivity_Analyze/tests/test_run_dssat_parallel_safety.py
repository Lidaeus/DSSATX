import os


def test_run_dssat_does_not_clean_shared_workspace_when_run_elsewhere():
    path = os.path.join(os.path.dirname(__file__), "..", "..", "run_dssat.py")
    with open(os.path.normpath(path), "r", encoding="utf-8", errors="ignore") as f:
        s = f.read()
    assert "if os.path.normcase(os.path.abspath(run_dir)) == os.path.normcase(os.path.abspath(cwd_script))" in s

