"""Regression test: DSSAT must read the bundle-local FileX, not TOMATO copy.

The test copies one completed season sandbox, replaces ID_SOIL with an invalid
identifier, and runs the inner DSSAT runner.  A successful run would indicate
that the FileX was not read; the expected result is a non-zero DSSAT failure.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "workspace/runs/e02_wnstress_fourcorner_layermeanic_smoke_20260801/_agents/agent_01/_seasons/25SP"


def main() -> int:
    if not SOURCE.is_dir():
        raise FileNotFoundError(SOURCE)
    with tempfile.TemporaryDirectory(prefix="filex_localization_", dir=ROOT / "workspace" / "runs") as td:
        run = Path(td)
        for name in ("XXQL2501.TMX", "XXQL2501.TMA", "XXQL2501.TMT", "DSSBatch.selected.v48",
                     "SOIL.SOL", "DSSATPRO.v48", "DSSAT48.INH", "DSSAT48.INP", "TMGRO048.CUL.base",
                     "TMGRO048.ECO.base", "TMGRO048.SPE.base", "pest_params.csv"):
            shutil.copy2(SOURCE / name, run / name)
        filex = run / "XXQL2501.TMX"
        text = filex.read_text(encoding="utf-8")
        if "IBTM910017" not in text:
            raise AssertionError("sentinel soil id not found in FileX")
        filex.write_text(text.replace("IBTM910017", "ZZZZZZZZZ", 1), encoding="utf-8")
        result = subprocess.run(
            ["python", str(ROOT / "src/dssat/run_dssat.py"), "--param-csv", "pest_params.csv",
             "--batch", "DSSBatch.selected.v48", "--model", "CRGRO048"],
            cwd=run, capture_output=True, text=True, check=False,
        )
        if result.returncode == 0:
            raise AssertionError("DSSAT succeeded with invalid local FileX ID_SOIL; stale FileX fallback remains")
        print("PASS: invalid local FileX ID_SOIL caused DSSAT failure")
        print((result.stdout + "\n" + result.stderr)[-1000:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
