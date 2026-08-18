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
import csv
import datetime as dt
import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

# Ensure project root is on sys.path so src.* imports work even when
# PEST++ invokes this script without PYTHONPATH.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.calibration.multiseason_design import MultiSeasonDesign
from src.calibration.seasonal_parameters import write_projected_parameter_csv
from src.calibration.nitrogen_response import (
    PEST_N_RESPONSE_FILE,
    PEST_W_RESPONSE_FILE,
    load_n_response_mapping,
    validate_mapping_against_filex,
    write_simulated_n_response,
    write_simulated_water_response,
)
from src.common.project import PROJECT_ROOT

# ── constants ────────────────────────────────────────────────────────────────
_TAGGED_OUTPUTS = ("PestEval.OUT", "PestJoint.OUT", "PestHarvest.OUT", "PestTmtGrow.OUT", "PestSoilWat.OUT")
_DSSAT_MAX_RETRIES = 3


def _keep_failed_dssat_artifacts() -> bool:
    """Whether a diagnostic replay should retain native-DSSAT failure evidence."""
    return os.environ.get("DSSAT_KEEP_FAILED_RUNS", "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _classify_dssat_failure(returncode: int, stdout: str | None, stderr: str | None) -> tuple[str, bool]:
    """Classify a failed DSSAT subprocess and decide whether it is retryable.

    Native Windows exits and file-lock/process-launch failures are commonly
    transient under high agent concurrency.  Input/format/parse errors are
    deterministic and should fail immediately instead of being masked by
    retries.  Unknown non-zero exits remain retryable, but are recorded as
    ``process_exit`` for later audit.
    """
    text = f"{stdout or ''}\n{stderr or ''}".lower()
    deterministic = (
        "traceback", "filenotfound", "file not found", "missing/empty",
        "parse error", "could not parse", "invalid parameter", "valueerror",
        "filex", "cul", "eco", "spe", "soil.sol", "observation",
    )
    if any(token in text for token in deterministic):
        return "deterministic_input_or_parse", False
    transient = (
        "getexitcodeprocess", "unknown", "0xc000", "sharing violation",
        "access is denied", "being used by another process", "lock",
    )
    if any(token in text for token in transient):
        return "transient_process_or_lock", True
    return "process_exit", int(returncode) != 0


def _retry_sleep_seconds(retry_number: int, base: float) -> float:
    """Bounded exponential backoff for retry number 1..N."""
    return max(0.0, float(base)) * (2 ** max(0, int(retry_number) - 1))


def _archive_failed_dssat_artifacts(
    pest_run_dir: Path, season_dir: Path, season_id: str
) -> Path | None:
    """Copy failed isolated DSSAT calls outside the disposable season folder."""
    source = season_dir / "_iso_runs"
    if not source.is_dir():
        return None
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S%f")
    target = pest_run_dir / "failed_dssat_artifacts" / f"{season_id}_{stamp}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    return target


def _runner_advisories(stderr: str | None) -> list[str]:
    """Return machine-readable runner advisories from a successful DSSAT call.

    ``run_dssat.py`` writes advisory-range events to stderr.  The scheduler
    captures child stderr so that normal DSSAT diagnostics do not flood the
    PEST++ log; without this narrow pass-through, advisory events would be
    silently discarded whenever DSSAT succeeds.
    """
    return [
        line.strip()
        for line in str(stderr or "").splitlines()
        if line.strip().startswith("RUNNER_ADVISORY ")
    ]


def _season_has_soil_phi(bundle: Path) -> bool:
    """Whether a season has non-initial soil observations entering Phi."""
    path = bundle / "soil_water_observations.csv"
    if not path.is_file():
        return False
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return any(
                str(row.get("phi_role", "")).strip().lower() == "soil_water_phi"
                for row in csv.DictReader(handle)
            )
    except (OSError, UnicodeError):
        return False
_RUN_TAG = re.compile(r"^RUN\s+(\d+)\s", re.IGNORECASE)
_DEFAULT_HARVEST_VAR = "CHPDT"
_DEFAULT_MODEL = "CRGRO048"


def _yyddd_add_days(value: int, days: int) -> int:
    """Calendar-safe addition for DSSAT's YYDDD date code."""
    yy, doy = divmod(int(value), 1000)
    year = 2000 + yy if yy < 70 else 1900 + yy
    date = dt.date(year, 1, 1) + dt.timedelta(days=doy - 1 + int(days))
    return (date.year % 100) * 1000 + int(date.strftime("%j"))


def _read_direct_harvest_dates(filet: Path, treatments: tuple[int, ...]) -> dict[int, list[int]]:
    """Read FileT dates with observed direct CHFPW or CHPDT cumulative values."""
    header: list[str] | None = None
    dates: dict[int, set[int]] = {int(tn): set() for tn in treatments}
    for raw in filet.read_text(encoding="utf-8", errors="strict").splitlines():
        line = raw.strip()
        if line.upper().startswith("@TRNO"):
            header = [item.lstrip("@").upper() for item in line.split()]
            continue
        if header is None or not line or line.startswith(("*", "@", "!")):
            continue
        fields = line.split()
        if len(fields) < len(header):
            continue
        record = dict(zip(header, fields))
        try:
            tn = int(float(record["TRNO"]))
            date = int(float(record["DATE"]))
        except (KeyError, ValueError):
            continue
        if tn not in dates:
            continue
        values = []
        for name in ("CHFPW", "CHPDT"):
            try:
                values.append(float(record.get(name, "-99")))
            except ValueError:
                pass
        if any(value != -99.0 for value in values):
            dates[tn].add(date)
    return {tn: sorted(values) for tn, values in dates.items()}


def _prepare_t10_input_bundle(source: Path, target: Path, treatments: tuple[int, ...], season_id: str) -> Path:
    """Copy the authoritative input bundle to a local working directory.

    The user-maintained FileX is the **sole authority** for harvest management
    dates.  This function copies the bundle verbatim — it does NOT rewrite the
    FileX *HARVEST DETAILS section.  FileT stores the original observation
    dates; DSSAT's FreshWt.OUT is matched to FileT via the d±1 bounded-nearest
    window in the observation reader.

    This function still verifies that FileT has CHPDT/CHFPW observations for
    every calibration treatment, and writes an audit CSV recording the FileT
    observation dates per treatment for traceability.
    """
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.is_file() and not item.name.startswith((".", "_")):
            shutil.copy2(item, target / item.name)
    filex_files = list(target.glob("*.TMX"))
    if len(filex_files) != 1:
        raise ValueError(f"{season_id}: expected one FileX in local bundle, found {len(filex_files)}")
    filex = filex_files[0]
    filet = target / f"{filex.stem}.TMT"
    if not filet.is_file():
        raise FileNotFoundError(f"{season_id}: missing FileT: {filet}")
    dates_by_tn = _read_direct_harvest_dates(filet, treatments)
    if any(not dates_by_tn[int(tn)] for tn in treatments):
        missing = [tn for tn in treatments if not dates_by_tn[int(tn)]]
        raise ValueError(f"{season_id}: direct CHFPW/CHPDT observations absent for treatments {missing}")

    # Write an audit CSV of the FileT observation dates (read-only — FileX
    # harvest events are NOT rewritten).
    audit_rows: list[dict[str, object]] = []
    for tn in treatments:
        observed_dates = dates_by_tn[int(tn)]
        for index, observed_date in enumerate(observed_dates, start=1):
            audit_rows.append({
                "season_id": season_id, "treatment": int(tn), "event_role": "real",
                "event_number": index, "observed_date": observed_date,
                "model_harvest_date": observed_date,  # FileX is authoritative; no shift
            })
    audit_path = target / "harvest_observation_audit.csv"
    with audit_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "season_id", "treatment", "event_role", "event_number", "observed_date", "model_harvest_date",
        ])
        writer.writeheader()
        writer.writerows(audit_rows)
    return target


def _write_selected_batch(source: Path, target: Path, treatments: tuple[int, ...], filex_name: str | None = None) -> None:
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
        # The custom NRESP DSSAT build does not reliably resolve a bare FileX
        # token after run_dssat enters its isolated execution directory. Use
        # the localized season-sandbox path, preserving isolation and making
        # the batch contract deterministic.
        basename = filex_name or Path(parts[0].replace("\\", "/")).name
        batch_root = os.environ.get("DSSAT_BATCH_FILEX_ROOT", "").strip()
        if batch_root:
            filex = str(Path(batch_root) / basename).replace("/", "\\")
        else:
            local_filex = (target.parent / basename).resolve()
            filex = str(local_filex).replace("/", "\\")
        # DSSAT's fixed batch field is only 93 characters wide. Windows 8.3
        # short paths keep the absolute, sandbox-local token within that
        # field while avoiding unreliable relative-path resolution.
        if len(filex) > filex_width:
            try:
                import ctypes
                buf = ctypes.create_unicode_buffer(32768)
                n = ctypes.windll.kernel32.GetShortPathNameW(filex, buf, len(buf))
                if n:
                    filex = buf.value
            except (AttributeError, OSError):
                pass
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
    soil_override = os.environ.get("DSSAT_SOIL_BASE", "").strip()
    if soil_override:
        override = Path(soil_override).expanduser().resolve()
        if not override.is_file():
            raise FileNotFoundError(f"DSSAT_SOIL_BASE not found: {override}")
        shutil.copy2(override, dst / "SOIL.SOL")
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
        installed = Path(r"C:\DSSAT48\Tomato") / fn
        ctrl = installed if installed.is_file() else PROJECT_ROOT / "data" / "templates" / fn
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

    soil_output_required = any(
        any("@SW" in line for line in (path / "PestSoilWat.OUT").read_text(encoding="utf-8", errors="ignore").splitlines())
        for path in season_dirs.values() if (path / "PestSoilWat.OUT").is_file()
    )
    tagged_outputs = tuple(
        name for name in _TAGGED_OUTPUTS
        if name != "PestSoilWat.OUT" or soil_output_required
    )
    for filename in tagged_outputs:
        combined: list[str] = []
        for row in ordered_rows:
            s_id = row["season_id"]
            lr = int(row["local_run"])
            gr = run_map.get((s_id, lr), lr)
            s_dir = season_dirs.get(s_id)
            if s_dir is None:
                raise FileNotFoundError(f"season dir missing for {s_id}")
            src_file = s_dir / filename
            if filename == "PestSoilWat.OUT":
                if not src_file.is_file() or not any(
                    "@SW" in line
                    for line in src_file.read_text(encoding="utf-8", errors="ignore").splitlines()
                ):
                    # A season such as 25FA can have only an initial soil
                    # measurement.  It contributes no SOIL_WATER Phi and must
                    # not be forced to manufacture a tagged line.
                    continue
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


def _merge_t10_harvest_audits(season_dirs: dict[str, Path], root_dir: Path) -> None:
    """Freeze local virtual-event and bounded-read audits beside the case."""
    for filename in ("t10_virtual_harvest_schedule.csv", "harvest_observation_audit.csv", "PestHarvest.audit.csv"):
        rows: list[dict[str, str]] = []
        fields: list[str] = []
        for season_id, season_dir in season_dirs.items():
            source = season_dir / ("_t10_input" if filename.startswith("t10_") else "") / filename
            if not source.is_file():
                continue
            with source.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    row.setdefault("season_id", season_id)
                    if "season_id" not in fields:
                        fields.append("season_id")
                    for key in row:
                        if key not in fields:
                            fields.append(key)
                    rows.append(row)
        if rows:
            with (root_dir / filename).open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)


# ── main entry ───────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T8 multi-season DSSAT scheduler")
    parser.add_argument("--design", required=True)
    parser.add_argument("--param-csv", required=True)
    parser.add_argument("--harvest-var", default=_DEFAULT_HARVEST_VAR)
    parser.add_argument("--model", default=_DEFAULT_MODEL)
    parser.add_argument("--prefix", default="t8_joint")
    parser.add_argument("--observation-transform-config", default=None)
    parser.add_argument("--dssat-max-retries", type=int, default=_DSSAT_MAX_RETRIES,
                        help="maximum retries after the initial DSSAT attempt")
    parser.add_argument("--dssat-retry-backoff", type=float, default=1.0,
                        help="base seconds for exponential DSSAT retry backoff")
    parser.add_argument("--keep-nitrogen-outputs", action="store_true",
                        help="retain PlantN.OUT/SoilNi.OUT in each season sandbox")
    args = parser.parse_args(argv)
    if args.dssat_max_retries < 0 or args.dssat_max_retries > 10:
        parser.error("--dssat-max-retries must be between 0 and 10")
    if args.dssat_retry_backoff < 0:
        parser.error("--dssat-retry-backoff must be non-negative")

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
    derived_response = pest_run_dir / PEST_N_RESPONSE_FILE
    if derived_response.exists():
        derived_response.unlink()
    if status_path.exists():
        status_path.unlink()

    # ── Phase 1: run each calibration season ────────────────────────────
    run_mapping_rows: list[dict[str, Any]] = []
    season_dirs: dict[str, Path] = {}
    runner_advisories: list[dict[str, str]] = []
    dssat_retries: list[dict[str, Any]] = []
    seasonal_projection_rows: list[dict[str, object]] = []
    global_run = 0
    t0_total = time.monotonic()

    for season in design.calibration_seasons:
        tid = time.monotonic()
        s_dir = pest_run_dir / "_seasons" / season.season_id
        if s_dir.exists():
            shutil.rmtree(s_dir, ignore_errors=True)
        s_dir.mkdir(parents=True, exist_ok=True)

        # Project the shared PEST vector for this season.  In the default M0
        # contract this is a byte-for-byte copy; in M1 only declared autumn
        # offsets are transformed before DSSAT sees the vector.
        projection = write_projected_parameter_csv(
            param_csv,
            s_dir / "pest_params.csv",
            design.seasonal_parameterization,
            season.season_id,
        )
        seasonal_projection_rows.extend(projection)

        input_bundle = season.bundle_absolute
        if design.design_id.startswith("eggplant_t10"):
            input_bundle = _prepare_t10_input_bundle(
                season.bundle_absolute,
                s_dir / "_t10_input",
                season.treatments,
                season.season_id,
            )

        selected_batch = s_dir / "DSSBatch.selected.v48"
        # Materialise the authoritative season bundle in the season sandbox.
        # The inner DSSAT runner resolves a bare FileX token relative to its
        # current working directory; passing --input-dir alone is not enough
        # because the legacy runner historically ignored that extra argument.
        # Without this copy DSSAT can silently fall back to a stale
        # C:\\DSSAT48\\TOMATO\\*.TMX.  Keeping the bundle-local files beside
        # the selected batch makes the runtime path explicit and auditable.
        _copy_bundle(input_bundle, s_dir)
        source_filex = next(input_bundle.glob("*.TMX"), None)
        if source_filex is None:
            raise FileNotFoundError(f"{season.season_id}: bundle has no FileX")
        local_filex = s_dir / source_filex.name
        if not local_filex.is_file() or not filecmp.cmp(source_filex, local_filex, shallow=False):
            raise RuntimeError(
                f"{season.season_id}: localized FileX does not match bundle source "
                f"({source_filex} -> {local_filex})"
            )
        (s_dir / "dssat_input_resolution_audit.json").write_text(
            json.dumps({
                "season_id": season.season_id,
                "source_bundle": str(input_bundle.resolve()),
                "source_filex": str(source_filex.resolve()),
                "localized_filex": str(local_filex.resolve()),
                "filex_match_before_injection": True,
                "batch_filex_token": source_filex.name,
                "soil_override": os.environ.get("DSSAT_SOIL_BASE", ""),
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        # Keep the DSSAT experiment stem from the authoritative FileX.  The
        # custom executable uses this stem to resolve the corresponding soil
        # and output contract; synthetic names such as NRESP25SP.TMX trigger
        # its IPSOIL parser failure even when the file bytes are valid.
        batch_filex_name = source_filex.name
        if os.environ.get("DSSAT_BATCH_FILEX_ROOT", "").strip():
            override_filex = os.environ.get("DSSAT_FILEX_BASE", "").strip()
            override_map = {}
            raw_map = os.environ.get("DSSAT_FILEX_MAP", "").strip()
            if raw_map:
                try:
                    override_map = json.loads(raw_map)
                except json.JSONDecodeError:
                    override_map = {}
            mapped = override_map.get(source_filex.name, "") if isinstance(override_map, dict) else ""
            source_filex = Path(mapped or override_filex).expanduser().resolve() if (mapped or override_filex) else input_bundle / source_filex.name
            batch_target = Path(os.environ["DSSAT_BATCH_FILEX_ROOT"]) / batch_filex_name
            shutil.copy2(source_filex, batch_target)
        _write_selected_batch(
            season.bundle_absolute / "DSSBatch.v48",
            selected_batch,
            season.treatments,
            filex_name=batch_filex_name,
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
        result_args = [
            sys.executable,
            str(PROJECT_ROOT / "src" / "calibration" / "run_dssat.py"),
            "--param-csv", str((s_dir / "pest_params.csv").resolve()),
            "--batch", str(selected_batch),
            "--harvest-var", args.harvest_var,
            "--input-dir", str(s_dir.resolve()),
        ]
        if getattr(args, "keep_nitrogen_outputs", False):
            result_args.append("--keep-nitrogen-outputs")
        if args.observation_transform_config:
            result_args.extend([
                "--observation-transform-config",
                str((pest_run_dir / args.observation_transform_config).resolve()),
            ])
        failures: list[dict[str, Any]] = []
        max_attempts = args.dssat_max_retries + 1
        for attempt in range(1, max_attempts + 1):
            result = subprocess.run(
                result_args, cwd=s_dir, env=env, capture_output=True, text=True, check=False,
            )
            if result.returncode == 0:
                break
            stderr_tail = (result.stderr or "(empty)").strip()[-600:]
            failure_class, retryable = _classify_dssat_failure(
                int(result.returncode), result.stdout, result.stderr
            )
            failures.append({
                "attempt": attempt,
                "returncode": int(result.returncode),
                "classification": failure_class,
                "retryable": retryable,
                "stderr_tail": stderr_tail,
            })
            if attempt < max_attempts and retryable:
                delay = _retry_sleep_seconds(attempt, args.dssat_retry_backoff)
                print(
                    f"[{season.season_id}] DSSAT retry {attempt}/{args.dssat_max_retries} "
                    f"class={failure_class} after rc={result.returncode}; "
                    f"sleep={delay:.1f}s; retrying identical candidate",
                    file=sys.stderr,
                )
                if delay:
                    time.sleep(delay)
            else:
                break
        elapsed = time.monotonic() - tid

        if result.returncode != 0:
            stderr_tail = failures[-1]["stderr_tail"] if failures else "(empty)"
            retained = None
            if _keep_failed_dssat_artifacts():
                retained = _archive_failed_dssat_artifacts(
                    pest_run_dir, s_dir, season.season_id
                )
            print(
                f"[{season.season_id}] DSSAT FAILED (rc={result.returncode}, "
                f"{elapsed:.1f}s): {stderr_tail}",
                file=sys.stderr,
            )
            if retained is not None:
                print(
                    f"[{season.season_id}] retained failed DSSAT artifacts: {retained}",
                    file=sys.stderr,
                )
            return result.returncode

        if failures:
            dssat_retries.append({
                "season_id": season.season_id,
                "attempts": len(failures) + 1,
                "max_retries": args.dssat_max_retries,
                "failures": failures,
            })

        for advisory in _runner_advisories(result.stderr):
            runner_advisories.append({"season_id": season.season_id, "message": advisory})
            print(f"[{season.season_id}] {advisory}", file=sys.stderr)

        # Validate tagged outputs exist
        soil_active = _season_has_soil_phi(season.bundle_absolute)
        for fn in _TAGGED_OUTPUTS:
            if fn == "PestSoilWat.OUT" and not soil_active:
                continue
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

    n_response = design.nitrogen_response_objective or {}
    if bool(n_response.get("enabled", False)):
        mapping_path = Path(str(n_response["mapping_csv"]))
        if not mapping_path.is_absolute():
            mapping_path = (PROJECT_ROOT / mapping_path).resolve()
        declared_mapping = pd.read_csv(mapping_path, encoding="utf-8-sig")
        runtime_mapping_audits = []
        for season in design.calibration_seasons:
            filex = next(season.bundle_absolute.glob("*.TMX"), None)
            if filex is None:
                raise FileNotFoundError(f"{season.season_id}: bundle has no FileX")
            runtime_mapping_audits.append(
                validate_mapping_against_filex(
                    declared_mapping,
                    filex,
                    season_id=season.season_id,
                    treatments=season.treatments,
                )
            )
        pd.concat(runtime_mapping_audits, ignore_index=True).to_csv(
            pest_run_dir / "filex_water_n_mapping_runtime_audit.csv", index=False
        )
        mapping = load_n_response_mapping(
            mapping_path,
            run_mapping_rows,
            response_levels=n_response.get("levels", ["N1", "N2", "N3"]),
        )
        write_simulated_n_response(
            pest_run_dir / "PestHarvest.OUT",
            pest_run_dir / PEST_N_RESPONSE_FILE,
            mapping,
            response_levels=n_response.get("levels", ["N1", "N2", "N3"]),
            source_scale=str(n_response.get("source_scale", "raw")),
            contrast_scale=str(n_response.get("contrast_scale", "log_ratio")),
            harvest_scope=str(n_response.get("harvest_scope", "all")),
        )

    water_response = design.water_response_objective or {}
    if bool(water_response.get("enabled", False)):
        mapping_path = Path(str(water_response["mapping_csv"]))
        if not mapping_path.is_absolute():
            mapping_path = (PROJECT_ROOT / mapping_path).resolve()
        mapping = load_n_response_mapping(
            mapping_path,
            run_mapping_rows,
            response_levels=("N1", "N2", "N3"),
        )
        write_simulated_water_response(
            pest_run_dir / "PestHarvest.OUT",
            pest_run_dir / PEST_W_RESPONSE_FILE,
            mapping,
            source_scale=str(water_response.get("source_scale", "raw")),
            contrast_scale=str(water_response.get("contrast_scale", "raw_difference")),
            harvest_scope=str(water_response.get("harvest_scope", "all")),
            high_water=str(water_response.get("high_water", "W3")),
            low_water=str(water_response.get("low_water", "W1")),
        )

    if design.design_id.startswith("eggplant_t10"):
        _merge_t10_harvest_audits(season_dirs, pest_run_dir)

    if seasonal_projection_rows:
        import csv

        projection_path = pest_run_dir / "seasonal_parameter_projection.csv"
        fieldnames = [
            "season_id", "parameter", "shared_value", "offset_name", "offset_value",
            "offset_applied", "transform", "season_value", "rationale",
        ]
        with projection_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(seasonal_projection_rows)

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
        "runner_advisories": runner_advisories,
        "dssat_retries": dssat_retries,
        "dssat_retry_policy": {
            "max_retries": args.dssat_max_retries,
            "backoff_base_seconds": args.dssat_retry_backoff,
        },
        "seasonal_parameterization": {
            "reference_season_id": design.seasonal_parameterization.reference_season_id,
            "offset_names": sorted(design.seasonal_parameterization.offset_names),
            "projection_file": "seasonal_parameter_projection.csv",
        } if design.seasonal_parameterization else None,
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
