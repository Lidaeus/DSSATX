"""port_spring58_joint.py -- rebuild a fresh spring58 joint case on macOS
from the run directory's clean_restart assets (equivalent to the shipped
make_fresh_joint.py, with a POSIX model command)."""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ("joint.pst", "parameters.tpl", "objectives.ins",
          "initial_ensemble.csv", "parameters.csv", "FormalObjectives.OUT",
          "run_manifest.yaml")
FORWARD = ROOT / "tools/calibration/run_water_stress_expansion_40x3_20261107.py"


def rebuild_joint(run: Path, engine: Path):
    joint = run / "joint"
    if joint.exists():
        stamp = "joint_completed_reference_windows"
        dest = run / stamp
        i = 1
        while dest.exists():
            i += 1
            dest = run / f"{stamp}_{i}"
        joint.rename(dest)
        print(f"  archived existing joint -> {dest.name}")
    joint.mkdir()
    for name in ASSETS:
        shutil.copy2(run / "clean_restart" / name, joint / name)
    # macOS-port: pestpp-ies 5.2.27 (apple build) strips the leading "/"
    # of the model command's first token before execv(), so an absolute
    # interpreter path can never launch (V15's bare "python" works). The
    # run_parallel launch env puts the project venv first on PATH, so a
    # bare "python" resolves to .venv/bin/python (V15-proven form).
    command = f"python -X utf8 {FORWARD} --forward {run}"
    pst = joint / "joint.pst"
    text = pst.read_text(encoding="utf-8")
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().startswith('"') and "python" in ln.lower() \
                and "--forward" in ln:
            lines[i] = command
            break
    else:
        raise SystemExit("model command line not found in clean_restart "
                         "joint.pst")
    pst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  joint.pst model command -> {command}")
