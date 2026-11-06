"""Three-season deterministic baseline smoke (T1) for the formal SA handoff.

This is the T1 gate of docs/reports/三季正式敏感性分析实施交接_20260720.md:
build a clean 8-treatment DSSAT baseline for each of the three controlled SA
bundles, with NO parameter injection, NO FileA/FileT, and the bundle's own
authoritative SOIL.SOL and weather files.

Critical DSSAT path facts (resolved via the parallel-run design in
C:\\DSSAT48_bak\\Tomato_Cal):

1. DSCSM048.EXE reads DSSATPRO.v48 from its OWN EXE directory. So we copy the
   EXE into run_dir and write a run-local DSSATPRO with CRD=run_dir.

2. Even with CRD=run_dir, when a FileX of the SAME name exists in the shared
   TMD (C:\\DSSAT48\\TOMATO), DSSAT prefers TMD and silently reads the stale
   file — defeating the bundle's counterfactual IC. The shared TMD currently
   holds stale XXQL2501/2502/2601.TMX (+.TMA/.TMT/.TMX.bak) from prior runs.

User-authorized remedy (fully reversible): for each season, move the
conflicting stale TMD XXQL* files into a timestamped backup dir, run DSSAT
(which then resolves the FileX from CRD=run_dir, i.e. the bundle), then move
the stale files back. A before/after SHA-256 snapshot of every touched TMD
file verifies the install is byte-identical afterwards. The bundle's own
SOIL.SOL and weather are supplied via run_dir + CRD; they do not require TMD
mutation because the bundle weather matches the install (verified at T0) and
SOIL.SOL is read from run_dir.

The run uses src/dssat/run_dssat.py as the DSSAT entry point so the same
output-pipeline (Evaluate.OUT / PlantGro.OUT / FreshWt.OUT / Pest*) exercised
by calibration is exercised here. No parameter injection (empty param CSV) so
the pristine CUL/ECO/SPE templates are used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SEASONS = [
    {"exp": "XXQL2501", "bundle": "xxql2501_sa_controlled_candidate_20260720", "weather": "XXLI2502.WTH"},
    {"exp": "XXQL2502", "bundle": "xxql2502_sa_controlled_candidate_20260720", "weather": "XXLI2502.WTH"},
    {"exp": "XXQL2601", "bundle": "xxql2601_sa_controlled_tn12_w1_candidate_20260721", "weather": "XXQL2601.WTH"},
]

DSSAT_ROOT = Path(r"C:\DSSAT48")
TMD_DIR = DSSAT_ROOT / "TOMATO"
RUN_DSSAT = PROJECT_ROOT / "src" / "dssat" / "run_dssat.py"
TEMPLATE_DSSATPRO = PROJECT_ROOT / "data" / "templates" / "DSSATPRO.v48"
# Stale XXQL* files in the shared TMD that would shadow the bundle FileX.
TMD_CONFLICT_STEMS = ["XXQL2501", "XXQL2502", "XXQL2601"]
TMD_CONFLICT_SUFFIXES = [".TMX", ".TMA", ".TMT", ".TMX.bak"]


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _snapshot_tmd() -> dict:
    """SHA-256 of every TMD conflict file, for before/after restore audit."""
    snap = {}
    for stem in TMD_CONFLICT_STEMS:
        for suf in TMD_CONFLICT_SUFFIXES:
            p = TMD_DIR / f"{stem}{suf}"
            snap[str(p)] = _sha256(p)
    return snap


def _stage_tmd_conflicts(backup_dir: Path) -> list[dict]:
    """Move stale TMD XXQL* files into backup_dir so DSSAT resolves FileX from CRD.

    Returns records [{tmd_path, backup_path, sha256}] for _restore_tmd_conflicts.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for stem in TMD_CONFLICT_STEMS:
        for suf in TMD_CONFLICT_SUFFIXES:
            p = TMD_DIR / f"{stem}{suf}"
            if not p.exists():
                continue
            sha = _sha256(p)
            backup_path = backup_dir / f"{stem}{suf}.staged_{int(time.time() * 1000)}"
            shutil.move(str(p), str(backup_path))
            records.append({
                "tmd_path": str(p),
                "backup_path": str(backup_path),
                "sha256": sha,
            })
    return records


def _restore_tmd_conflicts(records: list[dict]) -> list[dict]:
    """Move staged TMD files back; verify byte-identity by SHA-256."""
    restored = []
    for rec in reversed(records):
        tmd_path = Path(rec["tmd_path"])
        backup_path = Path(rec["backup_path"])
        if not backup_path.exists():
            restored.append({**rec, "restored_ok": False, "reason": "backup missing"})
            continue
        # If DSSAT re-created the file at tmd_path, remove it before moving back.
        if tmd_path.exists():
            tmd_path.unlink()
        shutil.move(str(backup_path), str(tmd_path))
        after = _sha256(tmd_path)
        restored.append({
            "tmd_path": str(tmd_path),
            "backup_path": str(backup_path),
            "before_sha256": rec.get("sha256"),
            "after_restore_sha256": after,
            "restored_ok": after == rec.get("sha256"),
        })
    return restored


def _to_dssatpro_path(p: Path) -> str:
    """Format a path the way DSSAT's DSSATPRO expects: 'D: \\path\\rest'."""
    s = os.path.abspath(str(p))
    drive, rest = os.path.splitdrive(s)
    rest = rest.replace("/", "\\")
    if not rest.startswith("\\"):
        rest = "\\" + rest
    return f"{drive} {rest}"


def _write_local_dssatpro(run_dir: Path) -> Path:
    """Write DSSATPRO.v48 into run_dir with CRD = run_dir.

    TMD/SLD/WED stay at the shared install (DSSAT resolves FileX/genotype/soil
    from CRD first, then CWD, then TMD/SLD/WED as fallback). Placing the EXE +
    this DSSATPRO in run_dir makes DSSAT read it instead of the shared one.
    """
    lines = TEMPLATE_DSSATPRO.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    crd_line = f"CRD {_to_dssatpro_path(run_dir)}\n"
    out = []
    wrote_crd = False
    for ln in lines:
        if ln.strip().startswith("CRD "):
            out.append(crd_line)
            wrote_crd = True
        else:
            out.append(ln)
    if not wrote_crd:
        # Insert after the first blank line if no CRD present.
        for i, ln in enumerate(out):
            if ln.strip() == "":
                out.insert(i + 1, crd_line)
                break
    dst = run_dir / "DSSATPRO.v48"
    dst.write_text("".join(out), encoding="utf-8")
    return dst


def _setup_run_dir(season: dict, run_root: Path) -> Path:
    """Set up an isolated, self-contained run_dir.

    Places: DSCSM048.EXE + DSSAT48.INH/INP + local DSSATPRO (CRD=run_dir) +
    bundle FileX/batch/SOIL/weather + genotype (.base + rendered).
    """
    exp = season["exp"]
    bundle_dir = PROJECT_ROOT / "data" / "user" / "experiments" / season["bundle"]
    run_dir = run_root / f"{exp.lower()}_baseline_smoke_20260720"
    if run_dir.exists():
        # Retry removal: Windows holds file handles briefly after DSSAT exits.
        last_err = None
        for _ in range(10):
            try:
                shutil.rmtree(run_dir)
                last_err = None
                break
            except PermissionError as exc:
                last_err = exc
                time.sleep(0.3)
        if last_err is not None:
            shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir(parents=True)

    # 1. DSSAT EXE + startup files into run_dir (so DSSAT reads local DSSATPRO)
    exe_src = DSSAT_ROOT / "DSCSM048.EXE"
    if not exe_src.exists():
        raise FileNotFoundError(f"DSCSM048.EXE not found at {exe_src}")
    shutil.copy2(exe_src, run_dir / "DSCSM048.EXE")
    for aux in ("DSSAT48.INH", "DSSAT48.INP"):
        src = DSSAT_ROOT / aux
        if src.exists():
            shutil.copy2(src, run_dir / aux)

    # 2. Local DSSATPRO with CRD=run_dir
    _write_local_dssatpro(run_dir)

    # 3. Bundle FileX, batch, soil, weather (authoritative). Rewrite the batch
    #    FileX tokens to a BARE name with correct fixed-width column alignment
    #    (TRTNO/RP/SQ/OP/CO must stay at their original @FILEX header columns).
    #    A bare name lets run_dssat._resolve_filex_from_batch find the run_dir
    #    FileX via CWD, and with the stale TMD FileX staged aside DSSAT then
    #    resolves the bare-named FileX from CWD=run_dir (per the GLUEP guide's
    #    "FileX copied to worker, batch writes bare name" option, which is
    #    deterministic as long as no same-named file shadows it).
    filex_name = f"{exp}.TMX"
    shutil.copy(bundle_dir / filex_name, run_dir / filex_name)
    batch_text = (bundle_dir / "DSSBatch.v48").read_text(encoding="utf-8", errors="ignore")
    # Find the @FILEX header to learn the FileX field width (column of TRTNO).
    lines = batch_text.splitlines()
    filex_field_width = None
    for ln in lines:
        if ln.lstrip().startswith("@FILEX"):
            filex_field_width = ln.find("TRTNO")
            break
    if filex_field_width is None:
        filex_field_width = 95
    new_lines = []
    for raw in lines:
        stripped = raw.strip()
        if stripped and not stripped.startswith(("$", "!", "@", "*")) and filex_name in raw:
            # Replace the FileX token (absolute TMD path or bare name) with a
            # bare name, left-justified to the original FileX field width.
            tmd_ref = f"C:\\DSSAT48\\TOMATO\\{filex_name}"
            rest = raw
            if tmd_ref in rest:
                rest = rest.replace(tmd_ref, filex_name)
            # Preserve the trailing columns (TRTNO onward) by splitting at the
            # first run of 2+ spaces after the FileX token.
            import re as _re
            m = _re.match(r"^(\s*)(\S+\.TMX)(\s{2,}.*)$", raw)
            if m:
                prefix, _old, tail = m.group(1), m.group(2), m.group(3)
                new_token = filex_name
                # Pad to filex_field_width so TRTNO stays aligned.
                padded = new_token.ljust(filex_field_width - len(prefix))
                raw = prefix + padded + tail.lstrip()
        new_lines.append(raw)
    (run_dir / "DSSBatch.v48").write_text("\r\n".join(new_lines) + "\r\n", encoding="utf-8")
    shutil.copy(bundle_dir / "SOIL.SOL", run_dir / "SOIL.SOL")
    shutil.copy(bundle_dir / season["weather"], run_dir / season["weather"])

    # 4. Genotype: .base templates + rendered copies (run_dssat's update_*_file
    #    with empty params writes only CUL; pre-render ECO/SPE to avoid IPVE).
    geno_dir = PROJECT_ROOT / "data" / "templates" / "genotype"
    for stem in ("TMGRO048.CUL", "TMGRO048.ECO", "TMGRO048.SPE"):
        base_src = geno_dir / f"{stem}.base"
        if base_src.exists():
            shutil.copy(base_src, run_dir / f"{stem}.base")
            shutil.copy(base_src, run_dir / stem)

    # 5. Empty param CSV => no injection; DSSAT runs against pristine templates.
    (run_dir / "baseline_params.csv").write_text("name,value\n", encoding="utf-8")
    return run_dir


def _parse_evaluate(path: Path) -> list[dict]:
    if not path.exists():
        return []
    header = None
    rows = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("@RUN"):
            header = line.split()
            continue
        if not header or not line.strip() or line.startswith(("*", "!", "@")):
            continue
        parts = line.split()
        if len(parts) < len(header):
            parts += ["-99"] * (len(header) - len(parts))
        rows.append(dict(zip(header, parts)))
    return rows


def _count_runs(path: Path) -> int:
    if not path.exists():
        return 0
    n = 0
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("*RUN"):
            n += 1
    return n


def _safe_float(v):
    try:
        f = float(v)
    except Exception:
        return None
    return None if f == -99.0 else f


def _finite_eval_metrics(eval_rows: list[dict]) -> dict:
    keys = ["HWAMS", "CWAMS", "LAIXS", "ADAPS", "PDFPS", "MDAPS", "HIAMS"]
    out = {}
    for r in eval_rows:
        try:
            tn = int(float(r.get("TN", -99)))
        except Exception:
            continue
        out[tn] = {k: _safe_float(r.get(k)) for k in keys}
    return out


def _plantgro_coverage(path: Path) -> dict:
    if not path.exists():
        return {}
    by_run = {}
    cur = None
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("*RUN"):
            try:
                cur = int(line.split()[1])
            except Exception:
                cur = None
            by_run.setdefault(cur, [])
            continue
        if line.startswith("@"):
            continue
        if cur is None or not line.strip() or line.startswith(("*", "!")):
            continue
        parts = line.split()
        try:
            dap = int(float(parts[2])) if len(parts) > 2 else None
        except Exception:
            dap = None
        if dap is not None:
            by_run[cur].append(dap)
    return {k: (min(v), max(v), len(v)) for k, v in by_run.items() if v}


def run_one_season(season: dict, run_root: Path) -> dict:
    exp = season["exp"]
    bundle_dir = PROJECT_ROOT / "data" / "user" / "experiments" / season["bundle"]
    run_dir = _setup_run_dir(season, run_root)

    result: dict = {
        "exp": exp,
        "run_dir": str(run_dir),
        "inputs": {
            "filex_sha256": _sha256(run_dir / f"{exp}.TMX"),
            "soil_sha256": _sha256(run_dir / "SOIL.SOL"),
            "weather_sha256": _sha256(run_dir / season["weather"]),
            "batch_sha256": _sha256(run_dir / "DSSBatch.v48"),
            "bundle_manifest_sha256": _sha256(bundle_dir / "input_manifest.json"),
        },
    }

    # run_dssat.py from run_dir: it localizes FileX, rewrites the batch to a bare
    # FileX name, renders CUL from .base, and launches DSCSM048.EXE from run_dir
    # (so DSSAT reads run_dir/DSSATPRO.v48 and run_dir's bundle inputs).
    # Stage stale TMD XXQL* files aside so DSSAT resolves the FileX from CRD
    # (run_dir) instead of the shared TMD. Restore in a finally block.
    backup_dir = run_root / "_tmd_staged_backup"
    tmd_before = _snapshot_tmd()
    staged = _stage_tmd_conflicts(backup_dir)
    result["tmd_staged_count"] = len(staged)
    cmd = [
        sys.executable,
        str(RUN_DSSAT),
        "--param-csv", "baseline_params.csv",
        "--batch", "DSSBatch.v48",
        "--cultivar", "TM0008",
        "--model", "CRGRO048",
        "--harvest-var", "CHPDT",
    ]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(run_dir), capture_output=True, text=True)
        dt = time.time() - t0
        result["returncode"] = proc.returncode
        result["elapsed_s"] = round(dt, 2)
        result["stdout_tail"] = proc.stdout[-2500:]
        result["stderr_tail"] = proc.stderr[-2000:]
        result["status"] = "OK" if proc.returncode == 0 else "FAILED"
    finally:
        restored = _restore_tmd_conflicts(staged)
        tmd_after = _snapshot_tmd()
        result["tmd_restore_records"] = restored
        result["tmd_before_sha"] = tmd_before
        result["tmd_after_sha"] = tmd_after
        result["tmd_restored_byte_identical"] = tmd_before == tmd_after

    # FileX fidelity: should be unchanged from the bundle (no silent IC rewrite
    # now that DSSAT reads the bundle FileX via CRD).
    result["filex_preserved_after_run"] = (
        _sha256(run_dir / f"{exp}.TMX") == result["inputs"]["filex_sha256"]
    )

    if result["status"] != "OK":
        return result

    eval_rows = _parse_evaluate(run_dir / "Evaluate.OUT")
    result["evaluate_rows"] = len(eval_rows)
    result["evaluate_per_tn"] = _finite_eval_metrics(eval_rows)
    result["plantgro_runs"] = _count_runs(run_dir / "PlantGro.OUT")
    result["freshwt_runs"] = _count_runs(run_dir / "FreshWt.OUT")
    result["plantgro_coverage"] = _plantgro_coverage(run_dir / "PlantGro.OUT")
    result["outputs_present"] = {
        "Evaluate.OUT": (run_dir / "Evaluate.OUT").exists(),
        "PlantGro.OUT": (run_dir / "PlantGro.OUT").exists(),
        "FreshWt.OUT": (run_dir / "FreshWt.OUT").exists(),
    }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", default=str(PROJECT_ROOT / "workspace" / "runs" / "three_season_baseline_smoke_20260720"))
    parser.add_argument("--season", default=None, help="single exp id to run (e.g. XXQL2501)")
    args = parser.parse_args()
    run_root = Path(args.run_root)
    run_root.mkdir(parents=True, exist_ok=True)

    seasons = SEASONS if not args.season else [s for s in SEASONS if s["exp"] == args.season]
    all_results = []
    for season in seasons:
        print("=" * 72)
        print(f"T1 baseline smoke: {season['exp']}  (bundle={season['bundle']})")
        print("=" * 72)
        res = run_one_season(season, run_root)
        all_results.append(res)
        summary = {k: v for k, v in res.items() if k not in (
            "stdout_tail", "stderr_tail", "evaluate_per_tn", "plantgro_coverage",
            "tmd_restore_records", "tmd_before_sha", "tmd_after_sha",
        )}
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        if not res.get("tmd_restored_byte_identical", False):
            print("  *** WARNING: shared TMD NOT byte-identical after restore ***")
        if res["status"] != "OK":
            print("--- stdout tail ---")
            print(res["stdout_tail"])
            print("--- stderr tail ---")
            print(res["stderr_tail"])

    out = run_root / "baseline_smoke_results.json"
    out.write_text(json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote: {out}")
    restore_failures = [r["exp"] for r in all_results if not r.get("tmd_restored_byte_identical", False)]
    if restore_failures:
        print(f"TMD RESTORE INCOMPLETE for: {restore_failures} — manual repair needed")
        sys.exit(2)
    failures = [r["exp"] for r in all_results if r["status"] != "OK"]
    if failures:
        print(f"FAILED seasons: {failures}")
        sys.exit(1)
    print("All seasons returned OK from DSSAT; shared TMD restored byte-identical.")


if __name__ == "__main__":
    main()
