"""Freeze and replay the unmodified 4.8.6.4 baseline; no calibration or model patch.

All outputs go to a NEW preparation directory. Existing runs/executables are read only.
Requires Python standard library only. Re-running with the same output path is rejected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

BASE_SHA = "25c93b9a2f73f8ec45bf441b198dac5fb7b22849"
COMPARE_FILES = (
    "Summary.OUT", "PlantGro.OUT", "PlantN.OUT", "FreshWt.OUT", "ET.OUT",
    "SoilWat.OUT", "SoilNiBal.OUT", "PlantNBal.OUT",
)
INPUT_SUFFIXES = {".TMX", ".TMA", ".TMT", ".WTH", ".SOL", ".CUL", ".ECO", ".SPE", ".CDE"}
SOURCE_FILES = (
    "CSM_Main/CSM.for", "CSM_Main/LAND.for", "SPAM/SPAM.for", "SPAM/SPSUBS.for",
    "Utilities/ModuleDefs.for", "Soil/Inorganic_N/SoilNi.for", "CMakeLists.txt",
    *[f"Plant/CROPGRO/{name}.for" for name in
      ("CROPGRO", "DEMAND", "NUPTAK", "MOBIL", "VEGGR", "GROW", "PHOTO", "PlantNBal", "FreshWt")],
)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest(folder: Path) -> dict[str, str]:
    return {str(p.relative_to(folder)).replace("\\", "/"): digest(p)
            for p in sorted(folder.rglob("*")) if p.is_file()}


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def numeric_records(path: Path) -> list[list[float | str]]:
    """Compare native numeric records, excluding headers/version/date banners.

    Retain nonnumeric tokens within a data row (e.g. cultivar identifiers).
    This is a baseline replay check, not a general DSSAT observation parser.
    """
    rows = []
    for line in path.read_text(errors="replace").splitlines():
        tokens = line.split()
        if not tokens:
            continue
        if path.name == "PlantNBal.OUT":
            if not re.match(r"^\s*(?:Leaf N|Stem N|Shell N|Seed N|Root N|Nodule N|Total N|N leakage|TOTAL N|N2 Fixed|N Uptake)", line):
                continue
        else:
            try:
                float(tokens[0])
            except ValueError:
                continue
        row = []
        for token in tokens:
            try:
                value = float(token.replace("D", "E"))
            except ValueError:
                row.append(token)
            else:
                if not math.isfinite(value):
                    raise ValueError(f"Non-finite output in {path}")
                row.append(value)
        rows.append(row)
    if not rows:
        raise ValueError(f"No comparable native data rows: {path}")
    return rows


def redirect_profile(path: Path, run: Path) -> None:
    codes = {"SLD", "CRD", "TMD", "WED"}
    seen = set()
    result = []
    for line in path.read_text(errors="strict").splitlines():
        match = re.match(r"^([A-Z]{3})\s+[A-Z]:\s*(.*)$", line)
        if match and match[1] in codes:
            line = f"{match[1]} {str(run)[:2]} {str(run)[2:]}"
            seen.add(match[1])
        result.append(line)
    if seen != codes:
        raise ValueError(f"Incomplete path isolation: {seen}")
    path.write_text("\n".join(result) + "\n", encoding="ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(r"D:\Tomato_Cal"))
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--candidate-exe", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    cn = args.project_root.resolve() / "subprojects/critical_n"
    original = cn / "dssat_csm_os_4864"
    source_run = cn / "runs/official_4864_compat_20261101/o4864/26SP"
    plan = args.project_root / "subprojects/DSSAT_4.8.6.4_根系吸收_氮同化与分配一体化改进方案_v2.md"
    protected = [Path(r"C:\DSSAT48\DSCSM048.EXE"), original / "build/bin/dscsm048.exe",
                 cn / "bin/dscsm048_cnc.exe", cn / "n_buffer_v15/bin/v15_s1_interface.exe"]
    protected_before = {str(p): digest(p) for p in protected}
    official_code_before = git(original, "status", "--porcelain", "--untracked-files=no")
    if official_code_before:
        raise ValueError("The protected official source has tracked changes")
    if git(repo, "merge-base", "HEAD", BASE_SHA) != BASE_SHA:
        raise ValueError("Development branch does not descend from official v4.8.6.4")
    source_hashes = {p: digest(repo / p) for p in SOURCE_FILES}
    for name in SOURCE_FILES:
        if digest(original / name) != source_hashes[name]:
            raise ValueError(f"Baseline source already modified: {name}")
    root = args.output_root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    receipt: dict = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "unmodified official baseline readiness, not mechanism validation",
        "plan": {"path": str(plan), "sha256": digest(plan)},
        "official_base_sha": BASE_SHA, "development_worktree": str(repo),
        "development_branch": git(repo, "branch", "--show-current"),
        "development_head_at_run": git(repo, "rev-parse", "HEAD"),
        "source_hashes": source_hashes, "source_input_run": str(source_run),
        "input_parameter_role": "frozen historical preflight BASE vector, NOT V15 best",
        "scope": "26SP 12 treatments; no 25FA; no calibration",
        "protected_executables_before": protected_before,
        "unmodified_source_status_before": official_code_before,
        "diagnostic_status": "not_instrumented_pending_P0_trace",
    }
    receipt_path = root / "readiness_receipt.json"
    try:
        bins = root / "bin"
        inputs = root / "inputs_26SP"
        reference = root / "reference_26SP"
        for folder in (bins, inputs, reference):
            folder.mkdir()
        for name, exe in (("official4864.exe", protected[1]),
                          ("development4864_unmodified.exe", args.candidate_exe.resolve())):
            shutil.copy2(exe, bins / name)
        for path in source_run.iterdir():
            if path.is_file() and (path.suffix.upper() in INPUT_SUFFIXES or
                                   path.name in {"DSSATPRO.v48", "DSSBatch.v48"}):
                shutil.copy2(path, inputs / path.name)
        for name in COMPARE_FILES:
            shutil.copy2(source_run / name, reference / name)
        receipt["frozen_input_hashes"] = manifest(inputs)
        receipt["frozen_reference_hashes"] = manifest(reference)
        receipt["copied_binary_hashes"] = manifest(bins)
        receipt["runs"] = {}
        for label, exe in (("official", bins / "official4864.exe"),
                           ("development", bins / "development4864_unmodified.exe")):
            run = root / f"replay_{label}_26SP"
            shutil.copytree(inputs, run)
            redirect_profile(run / "DSSATPRO.v48", run)
            input_before = {p.name: digest(p) for p in run.iterdir() if p.is_file()}
            command = [str(exe), "B", "DSSBatch.v48"]
            result = subprocess.run(command, cwd=run, capture_output=True, timeout=900)
            (run / "engine_stdout.txt").write_bytes(result.stdout)
            (run / "engine_stderr.txt").write_bytes(result.stderr)
            info = (run / "INFO.OUT").read_text(errors="replace") if (run / "INFO.OUT").exists() else ""
            if result.returncode or not re.search(r"Normal end of run\s+12\b", info) or (run / "MODEL.ERR").exists():
                raise RuntimeError(f"{label} replay failed; see native output")
            changed = [name for name, sha in input_before.items() if digest(run / name) != sha]
            if changed:
                raise RuntimeError(f"Engine altered frozen run inputs: {changed}")
            comparison = {}
            for name in COMPARE_FILES:
                expected, actual = numeric_records(reference / name), numeric_records(run / name)
                comparison[name] = {"reference_numeric_rows": len(expected),
                                    "replayed_numeric_rows": len(actual),
                                    "numeric_rows_exactly_equal": expected == actual,
                                    "output_sha256": digest(run / name)}
            receipt["runs"][label] = {"command": command, "returncode": result.returncode,
                                       "normal_end_12": True, "input_hashes": input_before,
                                       "comparison": comparison}
        receipt["protected_executables_after"] = {str(p): digest(p) for p in protected}
        receipt["protected_executables_unchanged"] = (
            receipt["protected_executables_after"] == protected_before)
        receipt["unmodified_source_status_after"] = git(original, "status", "--porcelain", "--untracked-files=no")
        receipt["all_selected_numeric_records_exact"] = all(
            data["numeric_rows_exactly_equal"] for run in receipt["runs"].values()
            for data in run["comparison"].values())
        receipt["passed"] = (receipt["protected_executables_unchanged"] and
                              not receipt["unmodified_source_status_after"] and
                              receipt["all_selected_numeric_records_exact"])
        if not receipt["passed"]:
            raise RuntimeError("Readiness comparison failed; inspect receipt")
    except Exception as exc:
        receipt["passed"] = False
        receipt["error"] = repr(exc)
        raise
    finally:
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": receipt["passed"], "receipt": str(receipt_path),
                      "runs": 2, "treatments_per_run": 12, "compared_files_per_run": len(COMPARE_FILES)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
