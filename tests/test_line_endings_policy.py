import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = "data/parameter_registry/bounds_proposals/eggplant/eggplant_p1_xxql2501_v3_candidate_20260716.csv"
FILEX = "data/user/experiments/xxql2501_20260716/XXQL2501.TMX"
INPUT_MANIFEST = "data/user/experiments/xxql2501_20260716/input_manifest.json"


def _check_attr(attribute: str, path: str) -> str:
    result = subprocess.run(
        ["git", "check-attr", attribute, "--", path],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_scientific_csv_hashes_use_stable_windows_checkout():
    assert _check_attr("eol", PROPOSAL).endswith("eol: crlf")
    assert b"\r\n" in (ROOT / PROPOSAL).read_bytes()


def test_dssat_input_bytes_are_not_line_ending_filtered():
    assert _check_attr("text", FILEX).endswith("text: unset")


def test_input_manifest_uses_stable_windows_checkout():
    assert _check_attr("eol", INPUT_MANIFEST).endswith("eol: crlf")
    assert b"\r\n" in (ROOT / INPUT_MANIFEST).read_bytes()
