"""Multi-season DSSAT scheduler — PEST++ model command for T8 joint calibration.

Usage (invoked by PEST++ as the model command)::

    python -m src.calibration.run_multiseason \\
        --design configs/runs/eggplant_t8_joint_25sp_25fa_v1.json \\
        --param-csv pest_params.csv

For each realization the scheduler:

1. Reads the multi-season design JSON to discover seasons, bundles, and treatments.
2. Creates a ``_seasons/<season_id>/`` working directory per calibration season.
3. Copies the season's immutable bundle (FileX/FileA/FileT/SOIL/WTH/batch) into each.
4. Copies the shared PEST-written ``parameters.csv`` into each.
5. Runs the existing inner DSSAT runner (``src.dssat.run_dssat``) in each season
   directory **sequentially**, injecting the same genetic parameters.
6. On any calibration-season failure, marks the realization failed and exits
   non-zero, leaving no partial merged output for PEST++.
7. On success, reads the per-season tagged outputs (``PestEval.OUT``, etc.)
   and merges them into the root PEST directory using ``run_mapping`` order.

The scheduler does **not** generate INS/TPL/weights — those are built by
``build_pest.py`` before the PEST case is run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path so src.* imports work even when
# PEST++ invokes this script without PYTHONPATH.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.calibration.multiseason_design import MultiSeasonDesign
from src.common.project import PROJECT_ROOT

# ── constants ────────────────────────────────────────────────────────────────
_TAGGED_OUTPUTS = ("PestEval.OUT", "PestJoint.OUT", "PestHarvest.OUT", "PestTmtGrow.OUT")
_RUN_TAG = re.compile(r"^RUN\s+(\d+)\s", re.IGNORECASE)
_DEFAULT_HARVEST_VAR = "CHPDT"
_DEFAULT_MODEL = "CRGRO048"


def _write_selected_batch(source: Path, target: Path, treatments: tuple[int, ...]) -> None:
    """Write a season-local batch in exactly the design treatment order."""
    lines = source.read_text(encoding="utf-8-sig", errors="strict").splitlines()
    preamble: list[str] = []
    rows: dict[int, str] = {}
    filex_width: int | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("$", "!", "@")):
            preamble.append(line)
            if stripped.upper().startswith("@FILEX") and "TRTNO" in line.upper():
                filex_width = line.upper().index("TRTNO")
            continue
        parts = stripped.split()
        if len(parts) < 2:
            raise ValueError(f"unrecognized DSSAT batch row in {source}: {line!r}")
        try:
            tn = int(parts[1])
        except ValueError as exc:
            raise ValueError(f"invalid treatment number in {source}: {line!r}") from exc
        if tn in rows:
            raise ValueError(f"duplicate treatment TN{tn} in {source}")
        if filex_width is None:
            raise ValueError(f"DSSAT batch lacks @FILEX/TRTNO header: {source}")
        filex = Path(parts[0].replace("\\", "/")).name
        if len(filex) > filex_width:
            raise ValueError(f"FileX name exceeds DSSAT batch field width: {filex}")
        rows[tn] = f"{filex:<{filex_width}}{line[filex_width:]}"

    missing = [tn for tn in treatments if tn not in rows]
    if missing:
        raise ValueError(f"selected treatments absent from {source}: {missing}")
    target.write_text(
        "\n".join([*preamble, *(rows[tn] for tn in treatments)]) + "\n",
        encoding="utf-8",
    )


# ── helpers ──────────────────────────────────────────────────────────────────
def _copy_bundle(src: Path, dst: Path) -> None:
    """Copy non-hidden bundle files into *dst*, plus genotype templates."""
    dst.mkdir(parents=True, exist_ok=True)
    # Bundle files
    for item in src.iterdir():
        if item.name.startswith(".") or item.name.startswith("_"):
            continue
        if item.is_file():
            shutil.copy2(item, dst / item.name)
    # Genotype template files (needed by src.dssat.run_dssat)
    gen_dir = PROJECT_ROOT / "data" / "templates" / "genotype"
    if gen_dir.is_dir():
        for stem in ("TMGRO048.CUL", "TMGRO048.ECO", "TMGRO048.SPE"):
            for suffix in (".base", ""):
                f = gen_dir / f"{stem}{suffix}"
                if f.is_file():
                    shutil.copy2(f, dst / f.name)
    # DSSAT control files — rewrite CRD and TMD to point to the season dir
    for fn in ("DSSAT48.INH", "DSSAT48.INP"):
        ctrl = PROJECT_ROOT / "data" / "templates" / fn
        if ctrl.is_file():
            shutil.copy2(ctrl, dst / fn)
    dssatpro_src = PROJECT_ROOT / "data" / "templates" / "DSSATPRO.v48"
    if dssatpro_src.is_file():
        lines = dssatpro_src.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        out = []
        drive, rest = os.path.splitdrive(os.path.abspath(str(dst)))
        dssatpro_path = f"{drive} {rest.replace('/', '\\\\')}"
        if not rest.startswith("\\"):
            dssatpro_path = f"{drive} \\\\{rest.replace('/', '\\\\')}"
        for ln in lines:
            if ln.strip().startswith("CRD "):
                out.append(f"CRD {dssatpro_path}\n")
            elif ln.strip().startswith("TMD "):
                out.append(f"TMD {dssatpro_path}\n")
            else:
                out.append(ln)
        (dst / "DSSATPRO.v48").write_text("".join(out), encoding="utf-8")


def _merge_tagged_outputs(
    season_dirs: dict[str, Path],
    run_mapping_path: Path,
    root_dir: Path,
    prefix: str,
) -> None:
    """Read per-season tagged outputs, rename @RUN tags by global_run,
    and write merged ``Pest*.OUT`` in run-mapping order."""
    import csv

    # Load run mapping
    run_map: dict[tuple[str, int], int] = {}
    ordered_rows: list[dict] = []
    with run_mapping_path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            s_id = row["season_id"]
            lr = int(row["local_run"])
            gr = int(row["global_run"])
            run_map[(s_id, lr)] = gr
            ordered_rows.append(row)

    for filename in _TAGGED_OUTPUTS:
        combined: list[str] = []
        for row in ordered_rows:
            s_id = row["season_id"]
            lr = int(row["local_run"])
            gr = run_map.get((s_id, lr), lr)
            s_dir = season_dirs.get(s_id)
            if s_dir is None:
                raise FileNotFoundError(f"season dir missing for {s_id}")
            src_file = s_dir / filename
            if not src_file.is_file():
                raise FileNotFoundError(
                    f"{s_id}/{filename} missing — DSSAT may have failed silently"
                )
            text = src_file.read_text(encoding="utf-8", errors="strict")
            # Lines are tagged as "RUN <local_run> TN <tn> @TOKEN@ value"
            local_prefix = f"RUN {lr} "
            matches: list[str] = []
            for line in text.splitlines():
                if line.startswith(local_prefix):
                    match = re.match(r"^RUN\s+\d+\s+TN\s+(\d+)\s", line, re.IGNORECASE)
                    actual_tn = int(match.group(1)) if match else None
                    expected_tn = int(row["treatment"])
                    if actual_tn != expected_tn:
                        raise ValueError(
                            f"{s_id}/{filename} RUN {lr} maps to TN{actual_tn}, "
                            f"expected TN{expected_tn}"
                        )
                    matches.append(line.replace(local_prefix, f"RUN {gr} ", 1))
            if not matches:
                raise ValueError(
                    f"{s_id}/{filename} has no line for RUN {lr}"
                )
            combined.extend(matches)
        (root_dir / filename).write_text("\n".join(combined) + "\n", encoding="utf-8")


# ── main entry ───────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T8 multi-season DSSAT scheduler")
    parser.add_argument("--design", required=True)
    parser.add_argument("--param-csv", required=True)
    parser.add_argument("--harvest-var", default=_DEFAULT_HARVEST_VAR)
    parser.add_argument("--model", default=_DEFAULT_MODEL)
    parser.add_argument("--prefix", default="t8_joint")
    args = parser.parse_args(argv)

    design_path = Path(args.design).expanduser().resolve()
    design = MultiSeasonDesign.load(str(design_path))
    param_csv = Path(args.param_csv).resolve()
    if not param_csv.is_file():
        print(f"[run_multiseason] param-csv not found: {param_csv}", file=sys.stderr)
        return 1

    # PEST++ sets CWD to the agent directory (or the run directory for local runs).
    pest_run_dir = Path.cwd()

    status_path = pest_run_dir / "multiseason_run_status.json"

    # Remove any stale merged outputs from previous attempts so PEST++ cannot
    # read them if this realization fails.
    for fn in _TAGGED_OUTPUTS:
        p = pest_run_dir / fn
        if p.exists():
            p.unlink()
    if status_path.exists():
        status_path.unlink()

    # ── Phase 1: run each calibration season ────────────────────────────
    run_mapping_rows: list[dict[str, Any]] = []
    season_dirs: dict[str, Path] = {}
    global_run = 0
    t0_total = time.monotonic()

    for season in design.calibration_seasons:
        tid = time.monotonic()
        s_dir = pest_run_dir / "_seasons" / season.season_id
        if s_dir.exists():
            shutil.rmtree(s_dir, ignore_errors=True)
        s_dir.mkdir(parents=True, exist_ok=True)

        # Copy shared parameter CSV into season dir
        shutil.copy2(param_csv, s_dir / "pest_params.csv")

        selected_batch = s_dir / "DSSBatch.selected.v48"
        _write_selected_batch(
            season.bundle_absolute / "DSSBatch.v48",
            selected_batch,
            season.treatments,
        )

        # Build run-mapping entries for this season
        local_count = len(season.treatments)
        for local_run, treatment in enumerate(season.treatments, 1):
            global_run += 1
            run_mapping_rows.append({
                "global_run": global_run,
                "season_id": season.season_id,
                "experiment_code": season.experiment_code,
                "treatment": treatment,
                "local_run": local_run,
            })

        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT)

        # Use the proven calibration runner per season.  It handles all the
        # DSSAT isolation: CRD/TMD rewrite, genotype injection, FileX/batch
        # localization, ephemeral _iso_runs/, and atomic output copy-back.
        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "src" / "calibration" / "run_dssat.py"),
                "--param-csv", "pest_params.csv",
                "--batch", str(selected_batch),
                "--harvest-var", args.harvest_var,
                "--input-dir", str(season.bundle_absolute.resolve()),
            ],
            cwd=s_dir,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        elapsed = time.monotonic() - tid

        if result.returncode != 0:
            stderr_tail = (result.stderr or "(empty)").strip()[-600:]
            print(
                f"[{season.season_id}] DSSAT FAILED (rc={result.returncode}, "
                f"{elapsed:.1f}s): {stderr_tail}",
                file=sys.stderr,
            )
            return result.returncode

        # Validate tagged outputs exist
        for fn in _TAGGED_OUTPUTS:
            out = s_dir / fn
            if not out.is_file() or out.stat().st_size == 0:
                print(
                    f"[{season.season_id}] {fn} missing/empty after successful DSSAT (rc=0)",
                    file=sys.stderr,
                )
                return 3

        season_dirs[season.season_id] = s_dir
        print(
            f"[{season.season_id}] OK — {local_count} treatments, {elapsed:.1f}s",
            file=sys.stderr,
        )

    # ── Phase 2: merge tagged outputs for PEST++ ────────────────────────
    run_map_path = pest_run_dir / f"{args.prefix}_run_mapping.csv"
    if run_map_path.is_file():
        _merge_tagged_outputs(season_dirs, run_map_path, pest_run_dir, args.prefix)
    else:
        # Fallback: write run_mapping and merge using in-memory ordering
        import csv
        run_map_path.parent.mkdir(parents=True, exist_ok=True)
        with run_map_path.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=[
                "global_run", "season_id", "experiment_code", "treatment", "local_run"
            ])
            w.writeheader()
            w.writerows(run_mapping_rows)
        _merge_tagged_outputs(season_dirs, run_map_path, pest_run_dir, args.prefix)

    total_elapsed = time.monotonic() - t0_total
    status = {
        "design_id": design.design_id,
        "param_csv": str(param_csv),
        "global_runs": global_run,
        "total_elapsed_s": round(total_elapsed, 1),
        "seasons": [
            {"season_id": s_id, "role": design.season_by_id(s_id).role,
             "treatments": len(design.season_by_id(s_id).treatments)}
            for s_id in season_dirs
        ],
    }
    status_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(
        f"[run_multiseason] All {len(season_dirs)} seasons OK "
        f"({global_run} runs, {total_elapsed:.1f}s)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
