"""End-to-end staged-inheritance smoke test (Finding 3, T2.2 task 8).

Exercises the full S1 finalize → auto representative → S2 build --fixed-from
chain through the real ``build_pest.py`` CLI without ever starting DSSAT/IES.

The S1 run directory is mocked (no DSSAT runs, no IES iterations): a
prior-only PST (NOPTMAX=0) plus a final-round ``.par.csv``/``.obs.csv``/
``.phi.actual.csv`` is enough for ``finalize_calibration`` to produce an
``engineering_validated`` finalize artifact and the median representative CSV.
The S2 step then runs the real ``build_pest.py`` via subprocess, reusing the
project's frozen bounds and the real ``xxql2501_20260716`` input bundle (the
build path enforces ``verify_calibrated_input_bundle``, which cannot be mocked
away without weakening the smoke). The test is skipped when those real inputs
are absent so it can run on the dev machine and degrade gracefully elsewhere.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pyemu
import pytest

from src.calibration.finalize_calibration import finalize_calibration

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DESIGN = PROJECT_ROOT / "configs" / "runs" / "eggplant_p1_v4_design_20260717.json"
BOUNDS_ID = "eggplant_p1_xxql2501_v4_sobol20_20260717"
INPUT_BUNDLE = PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2501_20260716"
POLICY_CSV = PROJECT_ROOT / "configs" / "runs" / "assumption_based_sigma_v2.csv"
BATCH = PROJECT_ROOT / "workspace" / "DSSBatch.v48"
BUILD_PEST = PROJECT_ROOT / "src" / "calibration" / "build_pest.py"

REQUIRED_INPUTS = (DESIGN, INPUT_BUNDLE, POLICY_CSV, BATCH)
skip_if_inputs_missing = pytest.mark.skipif(
    not all(path.exists() for path in REQUIRED_INPUTS),
    reason="S1→S2 smoke requires the real xxql2501_20260716 input bundle, "
           "frozen v4-sobol20 bounds, observation policy, batch and design config",
)


def _build_mocked_s1_run(run_dir: Path, *, case: str = "smoke") -> Path:
    """Construct a minimal prior-only S1 run dir that finalize_calibration accepts.

    Mirrors the fixtures in ``test_p2_n1_n3.py::test_prior_only_profile_*``:
    three realizations with distinct priors, an observation ensemble, a single
    iteration Phi table, a NOPTMAX=0 PST, and the staged manifest fields that
    ``_fixed_from_provenance`` cross-checks. No DSSAT is invoked.
    """
    pd.DataFrame({
        "real_name": ["r0", "r1", "r2"],
        "EM-FL": [20.0, 22.0, 24.0],
        "TRIFL": [0.6, 0.7, 0.8],
    }).to_csv(run_dir / f"{case}.2.par.csv", index=False)
    pd.DataFrame({
        "real_name": ["r0", "r1", "r2"],
        "o1": [1.0, 1.1, 1.2],
    }).to_csv(run_dir / f"{case}.2.obs.csv", index=False)
    pd.DataFrame({
        "iteration": [0], "0": [3.0], "1": [2.5], "2": [2.0],
    }).to_csv(run_dir / f"{case}.phi.actual.csv", index=False)
    pst = pyemu.Pst.from_par_obs_names(["EM-FL", "TRIFL"], ["o1"])
    pst.control_data.noptmax = 0
    pst.write(str(run_dir / f"{case}.pst"))
    (run_dir / "run_status.json").write_text(
        json.dumps({"run_id": case, "state": "completed"}), encoding="utf-8"
    )
    # Manifest scalars use the legacy double-quoted form; the project reader
    # accepts both quote styles and the S1 manifest is not the unit under test
    # here (the S2 build's consumption of it is).
    (run_dir / "run_manifest.yaml").write_text(
        f'run_id: "{case}"\n'
        f'design_stage: "S1"\n'
        f'design_table_id: "eggplant_p2_tooling_design_20260718"\n'
        f'approval_scope: "tooling_development"\n',
        encoding="utf-8",
    )
    return run_dir


@skip_if_inputs_missing
def test_s1_finalize_to_s2_build_inheritance_smoke(tmp_path):
    """S1 finalize → auto representative → S2 build --fixed-from, no DSSAT.

    Asserts the real ``build_pest.py`` CLI (a) accepts the auto-generated
    representative CSV at its actual ``calibration_finalize/`` location
    (Finding 1), (b) writes a PST whose S1-inherited parameters are fixed at
    the representative median and whose S2 active parameters remain free, and
    (c) the representative manifest field carries a Windows-path-safe scalar
    (Finding 2).
    """
    s1_run = tmp_path / "s1_run"
    s1_run.mkdir()
    _build_mocked_s1_run(s1_run, case="smoke")

    finalize_payload = finalize_calibration(s1_run, "smoke")
    assert finalize_payload["engineering_status"] == "engineering_validated", \
        finalize_payload["engineering_failures"]
    representative = finalize_payload["stage_representative"]
    assert representative and representative["sha256"]
    rep_csv = s1_run / "calibration_finalize" / "stage_representative_params.csv"
    assert rep_csv.is_file()
    # The representative median is what S2 must later pin EM-FL/TRIFL to.
    rep_table = pd.read_csv(rep_csv).set_index("name")["value"]
    assert rep_table["EM-FL"] == pytest.approx(22.0)
    assert rep_table["TRIFL"] == pytest.approx(0.7)
    # Finding 2: the upserted manifest path must be valid YAML.
    yaml = pytest.importorskip("yaml")
    manifest_payload = yaml.safe_load((s1_run / "run_manifest.yaml").read_text(encoding="utf-8"))
    assert manifest_payload["stage_representative_params"].endswith(
        "stage_representative_params.csv"
    )
    assert manifest_payload["stage_representative_params_sha256"] == representative["sha256"]

    s2_run = tmp_path / "s2_run"
    s2_run.mkdir()
    cmd = [
        sys.executable, str(BUILD_PEST),
        "--mode", "eggplant_stage2",
        "--design-config", str(DESIGN), "--stage", "S2",
        "--bounds-id", BOUNDS_ID, "--bounds-crop", "eggplant",
        "--input-dir", str(INPUT_BUNDLE),
        "--observation-policy-csv", str(POLICY_CSV),
        "--fixed-from", str(rep_csv),
        "--prefix", "smoke_s2", "--out-dir", str(s2_run),
        "--noptmax", "0", "--ies-num-reals", "4",
        "--random-seed", "20260731",
        "--harvest-var", "CHPDT", "--batch", str(BATCH),
        "--param-review-mode", "off",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, (
        f"S2 build failed (exit {result.returncode})\n"
        f"stdout:\n{result.stdout[-1500:]}\nstderr:\n{result.stderr[-1500:]}"
    )

    pst_path = s2_run / "smoke_s2.pst"
    assert pst_path.is_file(), f"S2 PST was not written: {pst_path}"
    pst = pyemu.Pst(str(pst_path))
    params = pst.parameter_data
    # S2 design: active = {NSTFAC, RTNO3, NMOBMX, NVSMOB}, fixed = {EM-FL, TRIFL}
    param_names = {str(n).lower() for n in params.index}
    assert {"em-fl", "trifl", "nstfac", "rtno3", "nmobmx", "nvsmob"} == param_names, param_names
    for name in ("em-fl", "trifl"):
        row = params.loc[name]
        assert str(row.partrans).lower() == "fixed", f"{name} not fixed: {row.partrans}"
        assert float(row.parlbnd) == float(row.parubnd) == float(row.parval1), \
            f"{name} not pinned: lbnd={row.parlbnd} ubnd={row.parubnd} val={row.parval1}"
        key = "EM-FL" if name == "em-fl" else "TRIFL"
        assert float(row.parval1) == pytest.approx(float(rep_table[key])), \
            f"{name} parval1 {row.parval1} != representative {rep_table[key]}"
    for name in ("nstfac", "rtno3", "nmobmx", "nvsmob"):
        row = params.loc[name]
        assert str(row.partrans).lower() in {"none", "log"}, \
            f"{name} not active: {row.partrans}"
        assert float(row.parlbnd) < float(row.parubnd), \
            f"{name} bounds collapsed: lbnd={row.parlbnd} ubnd={row.parubnd}"
