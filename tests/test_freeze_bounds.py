from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_freeze_bounds_rejects_instead_of_repairing(tmp_path):
    proposal = tmp_path / "invalid.csv"
    proposal.write_text(
        "name,init,lower,upper,status,pargp,location,file,cultivar,ecotype,mode\n"
        "SD-PM,90,80,40,active,CUL_Phenology,CUL,TMGRO048.CUL.base,TM0008,TM0001,both\n",
        encoding="utf-8",
    )
    output = tmp_path / "frozen"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "freeze_bounds.py"),
            "--proposal",
            str(proposal),
            "--crop",
            "eggplant",
            "--bounds-id",
            "must_not_exist",
            "--out-dir",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert not (output / "must_not_exist.csv").exists()
