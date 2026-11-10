"""Archive the completed joint case and rebuild a fresh one from clean_restart.

Run from the run directory (workspace/runs/eggplant_final_springs_58_restored_bounds_40x3_8agents_20261107).
Idempotent-ish: refuses to proceed if 'joint' is missing or already looks fresh.
"""
from datetime import datetime
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent            # <run>/clean_restart
RUN = HERE.parent                                  # <run>
JOINT = RUN / "joint"
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")


def main() -> None:
    if not JOINT.exists():
        sys.exit("No existing 'joint' directory to archive.")
    if not (JOINT / "joint.pst").exists():
        sys.exit("'joint' exists but has no joint.pst; refusing to touch it.")
    archive = RUN / f"joint_completed_reference_{STAMP}"
    shutil.move(str(JOINT), str(archive))
    JOINT.mkdir()
    for name in ("joint.pst", "parameters.tpl", "objectives.ins", "initial_ensemble.csv",
                 "parameters.csv", "FormalObjectives.OUT", "run_manifest.yaml"):
        shutil.copy2(HERE / name, JOINT / name)
    print(f"archived previous case -> {archive.name}")
    print("fresh case ready at 'joint'. Start the calibration with:")
    print(r'  cd D:\Tomato_Cal')
    print(r"  python -X utf8 tools\parallel\run_parallel.py"
          r" --run-dir workspace\runs\eggplant_final_springs_58_restored_bounds_40x3_8agents_20261107\joint"
          r" --case joint --mode ies --n-agents 8 --wait")


if __name__ == "__main__":
    main()
