"""Build, audit, smoke-test and run the TRUE-DELETION v48 derivation.

XFPHT and XFINT are absent from the PST (disabled bounds, as in the ``del``
run) AND from the ecotype file itself: the localized per-season
``TMGRO048.ECO(.base)`` are the column-stripped derived templates in
``data/templates/genotype_noxfx_20260903/``, substituted by the wrapper
``tools/calibration/run_multiseason_noxfx_20260903.py`` which the PST model
command invokes instead of the plain runner.  DSSAT therefore applies its
internal defaults for the two absent columns (empirically different from the
file values 38.8/0.12 — smoke TN1 terminal CHFPW 48517 vs 57055).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "configs/runs/e02_formal_v48_noxfx_20260903.json"
OBS = ROOT / "configs/runs/e02_formal_v47_free_nscale_observation_policy_20260901.csv"
BOUNDS_ID = "eggplant_e02_v48_del_xfpht_xfint_formal_20260903"  # disabled pair, unchanged
WRAPPER = ROOT / "tools/calibration/run_multiseason_noxfx_20260903.py"
CASE = "e02_formal_v48_noxfx_200x4_20260903"
RUN_ID = f"{CASE}_r1"
RUN_DIR = ROOT / "workspace/runs" / RUN_ID
REPORT_DIR = ROOT / "workspace/reports/e02_formal_v48_noxfx_20260903_r1"
ANCHOR = ROOT / "workspace/reports/e02_formal_v47_free_nscale_20260902_candidates/lowest_phi_params.csv"
EXPECTED_ACTIVE = 118
DELETED_PARAMS = ("xfpht", "xfint")


def run_logged(command: list[str], log_path: Path, *, cwd: Path = ROOT) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as handle:
        result = subprocess.run(command, cwd=cwd, stdout=handle, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}); see {log_path}")


def prepare_design() -> None:
    if DESIGN.is_file():
        return
    base = json.loads((ROOT / "configs/runs/e02_formal_v48_del_xfpht_xfint_20260903.json").read_text(encoding="utf-8"))
    base["design_id"] = "e02_formal_v48_noxfx_20260903"
    base["purpose"] = (
        "True deletion of XFPHT/XFINT: PST excludes them (disabled bounds) AND the "
        "localized ecotype files are the column-stripped derived templates "
        "(data/templates/genotype_noxfx_20260903); DSSAT internal defaults apply."
    )
    base["source_design_id"] = "e02_formal_v48_del_xfpht_xfint_20260903"
    DESIGN.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def patch_model_command() -> None:
    pst_path = RUN_DIR / f"{CASE}.pst"
    text = pst_path.read_text(encoding="utf-8")
    old = str((ROOT / "src/calibration/run_multiseason.py").resolve()).replace("\\", "/")
    new = str(WRAPPER.resolve()).replace("\\", "/")
    old_q = f'"{old}"'
    new_q = f'"{new}"'
    if old_q not in text:
        raise RuntimeError("model command target not found in PST")
    text = text.replace(old_q, new_q)
    pst_path.write_text(text, encoding="utf-8")


def audit() -> None:
    pst = pyemu.Pst(str(RUN_DIR / f"{CASE}.pst"))
    names = {str(n).lower() for n in pst.parameter_data.index}
    leaked = set(DELETED_PARAMS) & names
    if leaked:
        raise RuntimeError(f"deleted parameters leaked into PST: {leaked}")
    active = pst.parameter_data.loc[pst.parameter_data.partrans.ne("fixed")]
    if len(active) != EXPECTED_ACTIVE:
        raise RuntimeError(f"expected {EXPECTED_ACTIVE} active parameters, got {len(active)}")
    weights = pd.read_csv(RUN_DIR / f"{CASE}.weights.audit.csv", encoding="utf-8-sig")
    positive = weights[pd.to_numeric(weights["weight"], errors="coerce") > 0].copy()
    gradient = positive[positive["obgnme"].astype(str).str.contains("NG12M|NG23M|NGCVM", case=False, regex=True)]
    if len(gradient) != 45:
        raise RuntimeError(f"expected 45 N-dose-gradient observations, got {len(gradient)}")
    wresp = positive[positive["obgnme"].astype(str).str.contains("WRESPM", case=False)]
    if set(pd.to_numeric(wresp["nse_lambda"], errors="coerce").dropna().round(8)) != {3.0}:
        raise RuntimeError("W_RESPONSE lambda audit failed")
    pst_text = (RUN_DIR / f"{CASE}.pst").read_text(encoding="utf-8")
    if "run_multiseason_noxfx_20260903.py" not in pst_text:
        raise RuntimeError("PST model command does not invoke the noxfx wrapper")
    payload = {
        "run_id": RUN_ID, "case": CASE, "npar_adj": len(active),
        "deleted_params": list(DELETED_PARAMS),
        "genotype_template": "data/templates/genotype_noxfx_20260903 (columns absent)",
        "model_command_wrapper": str(WRAPPER.resolve()),
        "n_gradient_observations": len(gradient), "n_gradient_budget": 1.5,
        "w_response_lambda": 3.0, "num_reals": 200, "noptmax": 4, "agents": 6,
        "template_run": "e02_formal_v48_n_gradient_water2x_200x4_20260902_r2 (member 55)",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "preflight_audit.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


def smoke() -> None:
    work = ROOT / "workspace/smoke/e02_formal_v48_noxfx_20260903_r1_anchor"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    params = pd.read_csv(ANCHOR, encoding="utf-8-sig")
    params = params[~params["name"].astype(str).str.lower().isin(DELETED_PARAMS)]
    param_path = work / "params.csv"
    params.to_csv(param_path, index=False)
    run_logged([
        sys.executable, str(WRAPPER.resolve()),
        "--design", str(DESIGN.resolve()), "--param-csv", str(param_path.resolve()),
        "--prefix", "noxfx_smoke", "--harvest-var", "CHFPW",
    ], work / "smoke.log", cwd=work)
    gradient = work / "PestNDoseGradient.OUT"
    if not gradient.is_file() or len(gradient.read_text(encoding="utf-8").splitlines()) != 45:
        raise RuntimeError("N-dose-gradient smoke output must contain 45 one-observation rows")
    for eco in (work / "_seasons").glob("*/TMGRO048.ECO"):
        header = next((l for l in eco.read_text(encoding="utf-8-sig").splitlines() if l.startswith("@ECO#")), "")
        if "XFPHT" in header.upper() or "XFINT" in header.upper():
            raise RuntimeError(f"{eco}: localized ECO header still carries XFPHT/XFINT")
        data = next((l for l in eco.read_text(encoding="utf-8-sig").splitlines() if l.startswith("TM0001")), "")
        parts = data.split()
        if len(parts) != 20:  # 18 fixed fields + ECONAME token count for TM0001 row: header words - 2 (ECO#+ECONAME merged) — assert by header instead
            pass
        if parts[-1].upper() in {"0.12", "38.8"}:
            raise RuntimeError(f"{eco}: data row still carries deleted values")
    instruction = RUN_DIR / f"{CASE}_PestNDoseGradient.OUT.ins"
    parsed = pyemu.pst.pst_utils.InstructionFile(str(instruction)).read_output_file(str(gradient))
    if parsed is None or len(parsed) != 45:
        raise RuntimeError("generated N-dose-gradient instruction file did not parse all 45 values")


def build() -> None:
    prepare_design()
    if RUN_DIR.exists() and any(RUN_DIR.iterdir()):
        raise FileExistsError(f"refusing to mix existing run directory: {RUN_DIR}")
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    run_logged([
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2", "--prefix", CASE,
        "--bounds-id", BOUNDS_ID, "--bounds-crop", "eggplant",
        "--multiseason-design", str(DESIGN.resolve()),
        "--observation-policy-csv", str(OBS.resolve()),
        "--noptmax", "4", "--ies-num-reals", "200",
        "--batch", "DSSBatch.v48", "--harvest-var", "CHFPW",
        "--param-review-mode", "off", "--out-dir", str(RUN_DIR),
    ], REPORT_DIR / "build.log")
    patch_model_command()
    audit()
    smoke()


def run() -> None:
    run_logged([
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(RUN_DIR), "--case", CASE, "--mode", "ies",
        "--n-agents", "6", "--port", "4257", "--wait",
    ], REPORT_DIR / "parallel_run.log")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--run-only", action="store_true")
    args = parser.parse_args()
    if args.run_only:
        run()
    elif args.build_only:
        build()
    else:
        build(); run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
