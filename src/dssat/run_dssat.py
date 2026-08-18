import argparse
import csv
import datetime
import glob
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from src.common.param_registry import PHYSICAL_BOUNDS
from src.calibration.observation_policy import apply_transform_config
from src.dssat.array_expander import (
    expand_leaf_area,
    expand_leaf_partition,
    expand_senpor,
    expand_stem_partition,
    validate_partition_sum,
)

# Configuration
DSSAT_EXE = "DSCSM048.EXE"
# Optional explicit CSM model code passed to DSCSM048 (e.g. "CRGRO048"). When
# None, DSSAT infers the model from the $BATCH crop code / DSSATPRO default.
# Per the DSSAT parallel-run path guide (§4.2), explicitly passing the model is
# the most robust option and avoids depending on FileX CRMODEL or DSSATPRO
# defaults that can vary by CWD.
DSSAT_MODEL = None
BATCH_FILE = "DSSBatch.v48"
CUL_BASE_FILE = "TMGRO048.CUL.base"
CUL_FILE = "TMGRO048.CUL"
ECO_FILE = "TMGRO048.ECO"
SPE_FILE = "TMGRO048.SPE"
SOIL_FILE = "SOIL.SOL"
SOIL_BASE_FILE = "SOIL.SOL.base"
PARAM_CSV = "pest_params.csv"
OBSERVATION_TRANSFORM_CONFIG = None
KEEP_SOIL_WATER = False
KEEP_NITROGEN_OUTPUTS = False

OUTPUT_FILES = [
    "PlantGro.OUT",
    "FreshWt.OUT",
    "Summary.OUT",
    "OVERVIEW.OUT",
    "WARNING.OUT"
]


def _runner_advisory(message):
    """Emit a machine-readable warning without changing a candidate member."""
    print(f"RUNNER_ADVISORY {message}", file=sys.stderr, flush=True)


def validate_candidate_parameters(param_dict):
    """Normalize finite values and log, rather than enforce, safety heuristics.

    Frozen calibration bounds define the scientific parameter domain.  The
    runner must not freeze a PEST++ realization merely because it crosses a
    historical physical or relational safety threshold: DSSAT is allowed to
    evaluate the actual value and its exit status decides whether the member
    ran.  NaN/Inf remain unrecoverable because they cannot be written to a
    DSSAT input file.
    """
    normalized = {str(key).strip().upper(): float(value) for key, value in param_dict.items()}
    for name, value in normalized.items():
        if not math.isfinite(value):
            raise ValueError(f"Parameter {name} must be finite")
        if name in PHYSICAL_BOUNDS:
            lower, upper = PHYSICAL_BOUNDS[name]
            if not lower <= value <= upper:
                _runner_advisory(
                    f"parameter={name} value={value:g} safety_range=[{lower:g},{upper:g}] "
                    "action=continue_to_dssat"
                )
        if name.startswith(("SOIL_SLLL_", "SOIL_SDUL_", "SOIL_SSAT_", "IC_SH2O_")):
            if not 0.01 <= value <= 0.80:
                _runner_advisory(
                    f"parameter={name} value={value:g} safety_range=[0.01,0.80] action=continue_to_dssat"
                )
        if name.startswith("SOIL_SBDM_") and not 0.5 <= value <= 2.2:
            _runner_advisory(
                f"parameter={name} value={value:g} safety_range=[0.5,2.2] action=continue_to_dssat"
            )
        if name.startswith("SOIL_SLOC_") and not 0.0 <= value <= 10.0:
            _runner_advisory(
                f"parameter={name} value={value:g} safety_range=[0,10] action=continue_to_dssat"
            )
        if name == "SOIL_SLPF" and not 0.0 <= value <= 1.0:
            _runner_advisory(
                f"parameter={name} value={value:g} safety_range=[0,1] action=continue_to_dssat"
            )

    if "XMAGE" in normalized and "XFPHT" in normalized and normalized["XMAGE"] >= normalized["XFPHT"]:
        _runner_advisory("relation=XMAGE<XFPHT action=continue_to_dssat")

    temperature_groups = [
        ("TB", "TO1", "TO2", "TM"),
        ("TB1", "TO11", "TO21", "TM1"),
        ("TB2", "TO12", "TO22", "TM2"),
        ("TB3", "TO13", "TO23", "TM3"),
    ]
    for names in temperature_groups:
        if all(name in normalized for name in names):
            values = [normalized[name] for name in names]
            if not all(left < right for left, right in zip(values, values[1:])):
                _runner_advisory(f"relation={'<'.join(names)} action=continue_to_dssat")

    suffixes = {
        name.rsplit("_", 1)[-1]
        for name in normalized
        if name.startswith(("SOIL_SLLL_", "SOIL_SDUL_", "SOIL_SSAT_"))
    }
    for suffix in suffixes:
        names = [f"SOIL_{kind}_{suffix}" for kind in ("SLLL", "SDUL", "SSAT")]
        if all(name in normalized for name in names):
            values = [normalized[name] for name in names]
            if not values[0] < values[1] < values[2]:
                _runner_advisory(
                    f"relation={'<'.join(names)} safety_layer={suffix} action=continue_to_dssat"
                )
    return normalized


def _resolve_batch_path(batch_file, base_dir=None):
    if not batch_file:
        return None
    p = str(batch_file)
    if os.path.exists(p):
        return os.path.normpath(p)
    if os.path.isabs(p):
        return os.path.normpath(p)
    base_dir = base_dir or os.getcwd()
    cand = os.path.normpath(os.path.join(base_dir, p))
    if os.path.exists(cand):
        return cand
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cand2 = os.path.normpath(os.path.join(script_dir, p))
    if os.path.exists(cand2):
        return cand2
    return None

PEST_EVAL_FILE = "PestEval.OUT"
PEST_GROW_FILE = "PestGrow.OUT"
PEST_JOINT_FILE = "PestJoint.OUT"
PEST_HARVEST_FILE = "PestHarvest.OUT"
PEST_TMTGROW_FILE = "PestTmtGrow.OUT"
PEST_SOILWAT_FILE = "PestSoilWat.OUT"


def _get_pest_out_dir():
    """Get the directory for pest output files.

    If the PEST_OUT_DIR environment variable is set (by the PEST++ stub),
    use that directory. Otherwise use the current working directory.

    This allows the DSSAT model to run from the workspace directory
    (where DSSAT inputs are) while writing pest output files to the
    PEST++ run directory.
    """
    return os.environ.get("PEST_OUT_DIR") or os.getcwd()


def _pest_path(filename):
    """Return absolute path for a pest output file."""
    return os.path.join(_get_pest_out_dir(), filename)


def _eval_pest_file():
    return _pest_path(PEST_EVAL_FILE)
def _joint_pest_file():
    return _pest_path(PEST_JOINT_FILE)
def _harvest_pest_file():
    return _pest_path(PEST_HARVEST_FILE)
def _tmtgrow_pest_file():
    return _pest_path(PEST_TMTGROW_FILE)


def _parse_batch_entries(batch_file):
    entries = []
    batch_path = _resolve_batch_path(batch_file)
    if not batch_path:
        return entries
    with open(batch_path, "r") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s.startswith("$") or s.startswith("@") or s.startswith("!"):
                continue
            parts = s.split()
            if not parts:
                continue
            filex = parts[0]
            tn = -99
            if len(parts) >= 2:
                try:
                    tn = int(float(parts[1]))
                except Exception:
                    tn = -99
            entries.append({"filex": filex, "tn": tn})

    for i, e in enumerate(entries, start=1):
        e["run"] = i
    return entries


def _infer_excode_from_filex(filex_path):
    if not filex_path:
        return None
    base = os.path.basename(filex_path)
    if "." in base:
        base = base.rsplit(".", 1)[0]
    return base or None


def _read_tmt_harvest_events(tmt_path):
    if not tmt_path or not os.path.exists(tmt_path):
        return {}

    header = None
    rows = []
    with open(tmt_path, "r", encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            s = line.rstrip("\n")
            if not s.strip():
                continue
            if s.lstrip().startswith("@TRNO"):
                header = s.split()
                continue
            if header is None:
                continue
            if s.startswith("*") or s.lstrip().startswith("@"):  
                continue
            parts = s.split()
            if len(parts) < 2:
                continue
            if len(parts) < len(header):
                parts += ["-99"] * (len(header) - len(parts))
            row = dict(zip(header, parts[: len(header)]))
            rows.append(row)

    def _as_int(v, default=-99):
        try:
            return int(float(v))
        except Exception:
            return default

    def _as_float(v, default=-99.0):
        try:
            return float(v)
        except Exception:
            return default

    events_by_tn = {}
    for r in rows:
        tn = _as_int(r.get("@TRNO"), default=-99)
        date = _as_int(r.get("DATE"), default=-99)
        if tn <= 0 or date <= 0:
            continue

        chpdt = _as_float(r.get("CHPDT"), default=-99.0)
        hpodw = _as_float(r.get("HPODW"), default=-99.0)
        pwad = _as_float(r.get("PWAD"), default=-99.0)

        if chpdt == -99.0 and hpodw == -99.0 and pwad == -99.0:
            continue

        events_by_tn.setdefault(tn, []).append({"date": date, "chpdt": chpdt, "hpodw": hpodw, "pwad": pwad})

    out = {}
    for tn, evs in events_by_tn.items():
        evs_sorted = sorted(evs, key=lambda x: x["date"])
        cum = 0.0
        out_list = []
        for idx, e in enumerate(evs_sorted, start=1):
            if e["chpdt"] != -99.0:
                cum_val = e["chpdt"]
                cum = cum_val
            else:
                if e.get("hpodw", -99.0) != -99.0:
                    inc = float(e["hpodw"])
                elif e.get("pwad", -99.0) != -99.0:
                    inc = float(e["pwad"])
                else:
                    inc = 0.0
                cum += inc
                cum_val = cum
            out_list.append({"hno": idx, "date": int(e["date"]), "obs_cum": float(cum_val)})
        out[tn] = out_list

    return out


def _run_base_dir():
    """Directory used to resolve the FileX/TMT for pest-output writers.

    DSSAT runs from the current working directory, into which the calibration
    stub (``src/calibration/run_dssat.py``) has copied the localized FileX and
    ``{excode}.TMT``.  Resolving the FileX relative to the cwd (rather than the
    script directory, where those inputs never live) is what lets the
    TMT-derived ``PestTmtGrow.OUT`` / ``PestHarvest.OUT`` pick up the measured
    process and harvest observations.  Falls back to the script directory when
    the batch file cannot be found in the cwd (e.g. unit tests run in place).
    """
    cwd = os.getcwd()
    if _resolve_filex_from_batch("DSSBatch.v48", cwd):
        return cwd
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if _resolve_filex_from_batch("DSSBatch.v48", script_dir):
        return script_dir
    return cwd


def _read_tmt_process_points(tmt_path):
    if not tmt_path or not os.path.exists(tmt_path):
        return {}

    header = None
    rows = []
    with open(tmt_path, "r", encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            s = line.rstrip("\n")
            if not s.strip():
                continue
            if s.lstrip().startswith("@TRNO"):
                header = s.split()
                continue
            if header is None:
                continue
            if s.startswith("*") or s.lstrip().startswith("@"):  
                continue
            parts = s.split()
            if len(parts) < 2:
                continue
            if len(parts) < len(header):
                parts += ["-99"] * (len(header) - len(parts))
            row = dict(zip(header, parts[: len(header)]))
            rows.append(row)

    def _as_int(v, default=-99):
        try:
            return int(float(v))
        except Exception:
            return default

    def _as_float(v, default=-99.0):
        try:
            return float(v)
        except Exception:
            return default

    points_by_tn = {}
    for r in rows:
        tn = _as_int(r.get("@TRNO"), default=-99)
        date = _as_int(r.get("DATE"), default=-99)
        if tn <= 0 or date <= 0:
            continue

        lnsd = _as_float(r.get("L#SD"), default=-99.0)
        laid = _as_float(r.get("LAID"), default=-99.0)
        lwad = _as_float(r.get("LWAD"), default=-99.0)
        swad = _as_float(r.get("SWAD"), default=-99.0)
        chtd = _as_float(r.get("CHTD"), default=-99.0)
        snam = _as_float(r.get("SNAM"), default=-99.0)
        lnam = _as_float(r.get("LNAM"), default=-99.0)

        if lnsd == -99.0 and laid == -99.0 and lwad == -99.0 and swad == -99.0 and chtd == -99.0 and snam == -99.0 and lnam == -99.0:
            continue

        points_by_tn.setdefault(tn, []).append(
            {
                "date": int(date),
                "lnsd": float(lnsd),
                "laid": float(laid),
                "lwad": float(lwad),
                "swad": float(swad),
                "chtd": float(chtd),
                "snam": float(snam),
                "lnam": float(lnam),
            }
        )

    out = {}
    for tn, pts in points_by_tn.items():
        out[tn] = sorted(pts, key=lambda x: x["date"])
    return out


def _read_plantgro_pwad_by_run(plantgro_path):
    if not plantgro_path or not os.path.exists(plantgro_path):
        return {}

    pwad_cum_by_run = {}
    current_run = None
    header = None
    pwad_idx = None
    cum = 0.0

    with open(plantgro_path, "r") as f:
        for line in f:
            s = line.rstrip("\n")
            if s.startswith("*RUN"):
                m = re.match(r"^\*RUN\s+(\d+)", s)
                current_run = int(m.group(1)) if m else None
                header = None
                pwad_idx = None
                cum = 0.0
                continue

            if current_run is None:
                continue

            if s.lstrip().startswith("@YEAR"):
                header = s.split()
                try:
                    pwad_idx = header.index("PWAD")
                except ValueError:
                    pwad_idx = None
                continue

            if header is None or pwad_idx is None:
                continue

            if not s.strip() or s.startswith("*") or s.startswith("!"):
                continue

            parts = s.split()
            if len(parts) <= pwad_idx:
                continue
            try:
                year = int(float(parts[0]))
                doy = int(float(parts[1]))
                pwad = float(parts[pwad_idx])
            except Exception:
                continue

            date = (year % 100) * 1000 + doy
            cum += pwad
            pwad_cum_by_run.setdefault(current_run, {})[date] = cum

    return pwad_cum_by_run


def _read_freshwt_chpdt_by_run(freshwt_path):
    return _read_freshwt_var_by_run(freshwt_path, "CHPDT")


def _read_freshwt_var_by_run(freshwt_path, var_name):
    if not freshwt_path or not os.path.exists(freshwt_path):
        return {}

    var_name = str(var_name).strip().upper()
    by_run = {}
    current_run = None
    header = None
    idx = None

    with open(freshwt_path, "r") as f:
        for line in f:
            s = line.rstrip("\n")
            if s.startswith("*RUN"):
                m = re.match(r"^\*RUN\s+(\d+)", s)
                current_run = int(m.group(1)) if m else None
                header = None
                idx = None
                continue

            if current_run is None:
                continue

            if s.lstrip().startswith("@YEAR"):
                header = s.split()
                try:
                    idx = header.index(var_name)
                except ValueError:
                    idx = None
                continue

            if header is None or idx is None:
                continue

            if not s.strip() or s.startswith("*") or s.startswith("!"):
                continue

            parts = s.split()
            if len(parts) <= idx:
                continue
            try:
                year = int(float(parts[0]))
                doy = int(float(parts[1]))
                val = float(parts[idx])
            except Exception:
                continue

            date = (year % 100) * 1000 + doy
            by_run.setdefault(current_run, {})[date] = val

    return by_run


def _read_plantgro_vars_by_run(plantgro_path, var_names):
    if not plantgro_path or not os.path.exists(plantgro_path):
        return {}

    var_names = [v for v in (var_names or []) if v]
    if not var_names:
        return {}

    by_run = {}
    current_run = None
    header = None
    idx_map = None

    with open(plantgro_path, "r") as f:
        for line in f:
            s = line.rstrip("\n")
            if s.startswith("*RUN"):
                m = re.match(r"^\*RUN\s+(\d+)", s)
                current_run = int(m.group(1)) if m else None
                header = None
                idx_map = None
                continue

            if current_run is None:
                continue

            if s.lstrip().startswith("@YEAR"):
                header = s.split()
                idx_map = {}
                for v in var_names:
                    try:
                        idx_map[v] = header.index(v)
                    except ValueError:
                        idx_map[v] = None
                continue

            if header is None or idx_map is None:
                continue

            if not s.strip() or s.startswith("*") or s.startswith("!"):
                continue

            parts = s.split()
            try:
                year = int(float(parts[0]))
                doy = int(float(parts[1]))
            except Exception:
                continue

            date = (year % 100) * 1000 + doy
            run_day = by_run.setdefault(current_run, {}).setdefault(date, {})
            for v, idx in idx_map.items():
                if idx is None or len(parts) <= idx:
                    continue
                try:
                    run_day[v] = float(parts[idx])
                except Exception:
                    continue

    return by_run


def _nearest_on_or_before(date_to_value, date):
    if not date_to_value:
        return None
    if date in date_to_value:
        return date_to_value[date]
    candidates = [d for d in date_to_value.keys() if d <= date]
    if not candidates:
        return None
    return date_to_value[max(candidates)]


def _yyddd_add_days(yyddd, days):
    yy = int(yyddd) // 1000
    doy = int(yyddd) % 1000
    year = 2000 + yy if yy < 70 else 1900 + yy
    d0 = datetime.date(year, 1, 1) + datetime.timedelta(days=doy - 1)
    d1 = d0 + datetime.timedelta(days=int(days))
    return (d1.year % 100) * 1000 + int(d1.strftime("%j"))


def _bounded_nearest_within_window(date_to_value: dict, target_date: int, window: int = 1):
    """T10 bounded-nearest read: select the value at the date with minimum
    absolute distance from ``target_date`` within ``[target_date - window,
    target_date + window]``. Ties resolve to the later date (matching DSSAT's
    "day-update-then-write" semantics). Returns ``(value, selected_date)`` or
    ``(None, None)`` if no finite value exists in the window.
    """
    best_date = None
    best_dist = None
    # YYDDD is not an ordinal integer across a year boundary (e.g. 25365 is
    # followed by 26001, not 25366).  Build the small search window with the
    # same calendar helper used by the DSSAT-output readers.
    for delta in range(-window, window + 1):
        d = _yyddd_add_days(target_date, delta)
        v = date_to_value.get(d)
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv == -99.0 or fv != fv:  # skip -99 sentinel and NaN
            continue
        dist = abs(delta)
        if best_dist is None or dist < best_dist or (dist == best_dist and d > best_date):
            best_date = d
            best_dist = dist
    if best_date is None:
        return None, None
    return float(date_to_value[best_date]), best_date


def _write_pest_harvest_from_tmt_and_freshwt(batch_file, freshwt_path, pest_harvest_path, tmt_path=None, harvest_var="CHPDT"):
    """Write PestHarvest.OUT with T10 direct cumulative harvest tokens.

    T10 reads CHFPW and CHPDT as **direct cumulative series** from FreshWt.OUT
    (no differencing) on the exact FileT observation date.  The audited FileX
    schedules the corresponding management event on the preceding day. Both
    are written on their raw kg ha-1 scale as
    ``@CHFPWS@`` and ``@CHPDTS@`` tokens.  The shared observation-policy
    transform is responsible for applying log exactly once to observations and
    simulations after this file is written.
    Legacy ``@PWADS@``/``@PWAIS@`` tokens are retained for backward-compatible
    diagnostics but use the old differenced path. No neighbouring-date
    fallback is permitted for the formal direct-harvest targets.
    """
    entries = _parse_batch_entries(batch_file)
    if not entries:
        _append_pest_file(
            ["RUN 1 TN -99 HNO -99 DATE -99 @CHFPWS@ -99.000 @CHPDTS@ -99.000 @HPODWS@ -99.000 @CHPDTS_T@ -99.000 @PWADS@ -99.000 @PWAIS@ -99.000"],
            pest_harvest_path,
        )
        return

    base_dir = _run_base_dir()
    filex_abs = _resolve_filex_from_batch(batch_file, base_dir)
    if not tmt_path:
        excode = _infer_excode_from_filex(filex_abs or entries[0]["filex"])
        filex_dir = os.path.dirname(os.path.abspath(filex_abs)) if filex_abs else base_dir
        tmt_path = os.path.join(filex_dir, f"{excode}.TMT") if excode else None

    events_by_tn = _read_tmt_harvest_events(tmt_path)
    harvest_var = str(harvest_var or "CHPDT").strip().upper()

    # T10: read both CHFPW and CHPDT from FreshWt.OUT.
    chfpw_by_run = _read_freshwt_var_by_run(freshwt_path, "CHFPW")
    chpdt_by_run = _read_freshwt_var_by_run(freshwt_path, "CHPDT")
    # Legacy: keep the old harvest_var for PWADS/PWAIS diagnostics.
    legacy_by_run = _read_freshwt_var_by_run(freshwt_path, harvest_var)

    wrote_any = False
    new_lines = []
    audit_rows = []
    for e in entries:
        run_no = int(e["run"])
        tn = int(e.get("tn", -99))
        events = events_by_tn.get(tn, [])
        prev_cum = None
        prev_dry_cum = None
        for ev in events:
            hno = int(ev["hno"])
            date = int(ev["date"])
            # T10 exact observation-date read.
            # Read the FileT observation date exactly; FileX/FileT alignment
            # is audited separately and no neighbouring date is admissible.
            # FileT stores the post-harvest observation date.  The audited
            # FileX schedules its matching harvest on the preceding day, so
            # formal targets must read this exact date.  Nearest-day fallback
            # can silently bind a neighbouring event to the wrong target.
            read_reference_date = date
            chfpw_date = date if date in chfpw_by_run.get(run_no, {}) else None
            chpdt_date = date if date in chpdt_by_run.get(run_no, {}) else None
            chfpw_raw = chfpw_by_run.get(run_no, {}).get(date)
            chpdt_raw = chpdt_by_run.get(run_no, {}).get(date)
            if chfpw_raw is None:
                chfpw_raw = -99.0
            if chpdt_raw is None:
                chpdt_raw = -99.0
            hpodw_raw = -99.0
            if chpdt_raw != -99.0:
                hpodw_raw = float(chpdt_raw) if prev_dry_cum is None else float(chpdt_raw) - float(prev_dry_cum)
                prev_dry_cum = float(chpdt_raw)
            # Legacy differenced path for PWADS/PWAIS.
            sim_date = _yyddd_add_days(date, 1)
            sim_val = _nearest_on_or_before(legacy_by_run.get(run_no, {}), sim_date)
            if sim_val is None:
                sim_val = -99.0
            sim_inc = -99.0
            if sim_val != -99.0:
                if prev_cum is None:
                    sim_inc = float(sim_val)
                else:
                    sim_inc = float(sim_val) - float(prev_cum)
                prev_cum = float(sim_val)
            new_lines.append(
                f"RUN {run_no:d} TN {tn:d} HNO {hno:d} DATE {date:d}"
                f" @CHFPWS@ {float(chfpw_raw):0.3f} @CHPDTS@ {float(chpdt_raw):0.3f}"
                # Token order must match the .ins search order (CHFPWS ->
                # HPODWS -> CHPDTS_T for intermediate harvests).  PEST
                # instruction parsing advances a single forward cursor, so a
                # token placed before an earlier-searched token is unreachable
                # and the whole run is flagged failed.
                f" @HPODWS@ {float(hpodw_raw):0.3f}"
                f" @CHPDTS_T@ {float(chpdt_raw):0.3f}"
                f" @PWADS@ {float(sim_val):0.3f} @PWAIS@ {float(sim_inc):0.3f}"
            )
            audit_rows.append({
                "run": run_no, "treatment": tn, "harvest_number": hno,
                "target_date": date, "read_reference_date": read_reference_date,
                "chfpw_selected_date": chfpw_date or "",
                "chpdt_selected_date": chpdt_date or "",
                "chfpw_raw": chfpw_raw, "chpdt_raw": chpdt_raw, "hpodw_raw": hpodw_raw,
                "selection_window_days": 0,
            })
            wrote_any = True

    if not wrote_any:
        for e in entries:
            run_no = int(e["run"])
            tn = int(e.get("tn", -99))
            new_lines.append(
                f"RUN {run_no:d} TN {tn:d} HNO -99 DATE -99"
                f" @CHFPWS@ -99.000 @CHPDTS@ -99.000"
                f" @HPODWS@ -99.000 @CHPDTS_T@ -99.000"
                f" @PWADS@ -99.000 @PWAIS@ -99.000"
            )

    with open(pest_harvest_path, "w") as f:
        for line in new_lines:
            f.write(line + "\n")
    # This audit is deliberately separate from the PEST interface. It records
    # the bounded date match while leaving FileT/FreshWt and formal metrics on
    # their native scale.
    try:
        import csv
        audit_path = os.path.splitext(pest_harvest_path)[0] + ".audit.csv"
        with open(audit_path, "w", newline="", encoding="utf-8") as handle:
            fields = [
                "run", "treatment", "harvest_number", "target_date",
                "read_reference_date",
                "chfpw_selected_date", "chpdt_selected_date", "chfpw_raw",
                "chpdt_raw", "hpodw_raw", "selection_window_days",
            ]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(audit_rows)
    except Exception as exc:
        print(f"Warning: failed to write PestHarvest audit: {exc}")


def _write_pest_tmtgrow_from_tmt_and_plantgro(batch_file, plantgro_path, pest_tmtgrow_path, tmt_path=None, plantn_path=None):
    entries = _parse_batch_entries(batch_file)
    if not entries:
        with open(pest_tmtgrow_path, "w") as f:
            f.write(
                "RUN 1 TN -99 DATE -99 @LAIDS@ -99.000 @LWADS@ -99.000 "
                "@SWADS@ -99.000 @CHTDS@ -99.000 @LAIDDS@ -99.000 "
                "@LWADDS@ -99.000 @SWADDS@ -99.000 @LAIETS@ -99.000 "
                "@LWETS@ -99.000 @SWETS@ -99.000\n"
            )
        return

    base_dir = _run_base_dir()
    filex_abs = _resolve_filex_from_batch(batch_file, base_dir)
    if not tmt_path:
        excode = _infer_excode_from_filex(filex_abs or entries[0]["filex"])
        filex_dir = os.path.dirname(os.path.abspath(filex_abs)) if filex_abs else base_dir
        tmt_path = os.path.join(filex_dir, f"{excode}.TMT") if excode else None

    points_by_tn = _read_tmt_process_points(tmt_path)
    vars_by_run = _read_plantgro_vars_by_run(plantgro_path, ["L#SD", "LAID", "LWAD", "SWAD", "CHTD"])
    n_by_run = _read_plantgro_vars_by_run(plantn_path, ["SNAD", "LNAD"]) if plantn_path else {}

    wrote_any = False
    with open(pest_tmtgrow_path, "w") as f:
        for e in entries:
            run_no = int(e["run"])
            tn = int(e.get("tn", -99))
            pts = points_by_tn.get(tn, [])
            previous_state = None
            terminal_index = {}
            for variable, field in (
                ("LAID", "laid"), ("LWAD", "lwad"), ("SWAD", "swad")
            ):
                valid = [
                    idx for idx, item in enumerate(pts)
                    if float(item.get(field, -99.0)) != -99.0
                ]
                terminal_index[variable] = valid[-1] if valid else None
            for point_index, p in enumerate(pts):
                date = int(p["date"])

                sim_day = None
                candidates = vars_by_run.get(run_no, {})
                if date in candidates:
                    sim_day = candidates[date]
                else:
                    prev_dates = [d for d in candidates.keys() if d <= date]
                    if prev_dates:
                        sim_day = candidates[max(prev_dates)]

                lnsd_s = -99.0
                laid_s = -99.0
                lwad_s = -99.0
                swad_s = -99.0
                chtd_s = -99.0
                if sim_day is not None:
                    lnsd_s = float(sim_day.get("L#SD", -99.0))
                    laid_s = float(sim_day.get("LAID", -99.0))
                    lwad_s = float(sim_day.get("LWAD", -99.0))
                    swad_s = float(sim_day.get("SWAD", -99.0))
                    chtd_s = float(sim_day.get("CHTD", -99.0))
                # CANOPY_TERMINAL is an exact-date contract: the terminal
                # observed LAI must be paired with DSSAT LAID on that same
                # observation date.  Never inherit the general process-state
                # on-or-before fallback for this token.
                if point_index == terminal_index["LAID"] and date not in candidates:
                    laid_s = -99.0
                current_state = {
                    "LAID": laid_s, "LWAD": lwad_s, "SWAD": swad_s
                }
                delta_state = {}
                for variable, value in current_state.items():
                    previous_value = (
                        previous_state.get(variable, -99.0)
                        if previous_state is not None
                        else -99.0
                    )
                    delta_state[variable] = (
                        float(value) - float(previous_value)
                        if value != -99.0 and previous_value != -99.0
                        else -99.0
                    )
                snam_s = -99.0
                lnam_s = -99.0
                n_candidates = n_by_run.get(run_no, {})
                n_dates = [d for d in n_candidates if abs(int(d) - int(date)) <= 1]
                if n_dates:
                    selected_n = n_candidates[sorted(n_dates, key=lambda d: (abs(int(d) - int(date)), -int(d)))[0]]
                    snam_s = float(selected_n.get("SNAD", -99.0))
                    lnam_s = float(selected_n.get("LNAD", -99.0))

                f.write(
                    f"RUN {run_no:d} TN {tn:d} DATE {date:d} "
                    f"@L#SDS@ {lnsd_s:0.3f} @LAIDS@ {laid_s:0.3f} @LWADS@ {lwad_s:0.3f} @SWADS@ {swad_s:0.3f} @CHTDS@ {chtd_s:0.3f} "
                    f"@SNAMS@ {snam_s:0.3f} @LNAMS@ {lnam_s:0.3f} "
                    f"@LAIDDS@ {delta_state['LAID']:0.3f} @LAIETS@ {(laid_s if point_index == terminal_index['LAID'] else -99.0):0.3f} "
                    f"@LWADDS@ {delta_state['LWAD']:0.3f} @LWETS@ {(lwad_s if point_index == terminal_index['LWAD'] else -99.0):0.3f} "
                    f"@SWADDS@ {delta_state['SWAD']:0.3f} @SWETS@ {(swad_s if point_index == terminal_index['SWAD'] else -99.0):0.3f}\n"
                )
                previous_state = current_state
                wrote_any = True

        if not wrote_any:
            for e in entries:
                run_no = int(e["run"])
                tn = int(e.get("tn", -99))
                f.write(
                    f"RUN {run_no:d} TN {tn:d} DATE -99 "
                    f"@L#SDS@ -99.000 @LAIDS@ -99.000 @LWADS@ -99.000 "
                    f"@SWADS@ -99.000 @CHTDS@ -99.000 @LAIDDS@ -99.000 "
                    f"@LWADDS@ -99.000 @SWADDS@ -99.000 @LAIETS@ -99.000 "
                    f"@LWETS@ -99.000 @SWETS@ -99.000 @SNAMS@ -99.000 "
                    f"@LNAMS@ -99.000\n"
                )


def _yyddd_from_iso(value):
    try:
        d = datetime.date.fromisoformat(str(value).strip()[:10])
        return int(f"{d.year % 100:02d}{d.timetuple().tm_yday:03d}")
    except (TypeError, ValueError):
        return -99


def _soil_observation_records(path):
    """Return non-initial soil observations in the same deterministic order as the builder."""
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("phi_role", "")).strip().lower() != "soil_water_phi":
                continue
            try:
                row["trno"] = int(float(row.get("trno", -99)))
                row["date_code"] = _yyddd_from_iso(row.get("date"))
                row["vwc_mean"] = float(row.get("vwc_mean"))
            except (TypeError, ValueError):
                continue
            if row["trno"] > 0 and row["date_code"] > 0:
                rows.append(row)
    rows.sort(key=lambda r: (int(r["trno"]), int(r["date_code"]), str(r.get("depth_label", ""))))
    for idx, row in enumerate(rows, 1):
        row["token"] = f"SW{idx:04d}S"
    return rows


def _read_soilwat_by_run(path):
    """Parse SoilWat.OUT into run -> date-code -> SW column values."""
    result = {}
    if not os.path.isfile(path):
        return result
    run_no = None
    header = None
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            if line.startswith("*RUN"):
                match = re.match(r"^\*RUN\s+(\d+)", line)
                run_no = int(match.group(1)) if match else None
                header = None
                continue
            if run_no is None:
                continue
            if line.lstrip().startswith("@YEAR"):
                header = line.split()
                continue
            if header is None or not line.strip() or line.lstrip().startswith(("!", "*", "@")):
                continue
            parts = line.split()
            if len(parts) < len(header):
                continue
            try:
                date_code = int(parts[0]) % 100 * 1000 + int(parts[1])
            except (ValueError, IndexError):
                continue
            values = {}
            for name, value in zip(header, parts):
                if name.startswith("SW") and name.endswith("D"):
                    try:
                        values[name] = float(value)
                    except ValueError:
                        pass
            result.setdefault(run_no, {})[date_code] = values
    return result


def _write_pest_soilwat_from_soilwat(batch_file, soilwat_path, pest_path, observations_path=None):
    """Create tagged soil-water observations using audited layer weights.

    The first field measurement is excluded upstream by ``phi_role``.  For
    each remaining observation the nearest available DSSAT date is selected;
    no additional date shift or fabricated observation is introduced.
    """
    observations_path = observations_path or "soil_water_observations.csv"
    observations = _soil_observation_records(observations_path)
    entries = _parse_batch_entries(batch_file)
    # The bundle may contain audited soil observations for all treatments,
    # while a diagnostic E01/T10 batch intentionally runs a subset.  Compact
    # token numbering must follow the actual batch treatments; otherwise the
    # generated PestSoilWat.OUT tokens (e.g. SW0009S) no longer match the
    # .ins file (SW0001S), producing an EOF/initial-evaluation failure.
    run_order = {int(e.get("tn", -99)): i for i, e in enumerate(entries)}
    allowed_treatments = set(run_order)
    observations = [r for r in observations if int(r["trno"]) in allowed_treatments]
    observations.sort(key=lambda r: (run_order[int(r["trno"])], int(r["date_code"]), str(r.get("depth_label", ""))))
    for idx, row in enumerate(observations, 1):
        row["token"] = f"SW{idx:04d}S"
    by_run = _read_soilwat_by_run(soilwat_path)
    with open(pest_path, "w", encoding="utf-8") as handle:
        for entry in entries:
            run_no = int(entry.get("run", -99))
            tn = int(entry.get("tn", -99))
            run_rows = [r for r in observations if int(r["trno"]) == tn]
            for row in run_rows:
                candidates = by_run.get(run_no, {})
                if not candidates:
                    value = -99.0
                else:
                    selected = min(candidates, key=lambda date: (abs(int(date) - int(row["date_code"])), int(date)))
                    raw = candidates[selected]
                    value = 0.0
                    total = 0.0
                    for item in str(row.get("dssat_layer_weights", "")).split(";"):
                        if not item.strip() or ":" not in item:
                            continue
                        idx, weight = item.split(":", 1)
                        try:
                            w = float(weight)
                            v = float(raw.get(f"SW{int(idx) + 1}D", float("nan")))
                        except (ValueError, TypeError):
                            continue
                        if math.isfinite(v):
                            value += w * v
                            total += w
                    if total <= 0:
                        value = -99.0
                handle.write(f"RUN {run_no:d} TN {tn:d} DATE {int(row['date_code']):d} @{row['token']}@ {value:.6f}\n")


def _resolve_filex_from_batch(batch_file, base_dir):
    filex = _first_batch_filex_path(batch_file)
    if not filex:
        return None
    if os.path.isabs(filex):
        return os.path.normpath(filex)
    return os.path.normpath(os.path.join(base_dir, filex))


def _norm_abs_case(p):
    return os.path.normcase(os.path.abspath(str(p)))


def _is_same_path(src, dst):
    if not (src and dst):
        return False
    try:
        if os.path.exists(src) and os.path.exists(dst):
            return os.path.samefile(src, dst)
    except Exception:
        pass
    return _norm_abs_case(src) == _norm_abs_case(dst)


def _copy_with_retries(src, dst, n_tries=5, sleep_s=0.2):
    if _is_same_path(src, dst):
        return None
    last_err = None
    for _ in range(int(n_tries)):
        try:
            shutil.copy(src, dst)
            return None
        except Exception as e:
            last_err = e
            if sleep_s:
                time.sleep(float(sleep_s))
    return last_err


def _acquire_file_lock(lock_path, timeout_s=120.0, poll_s=0.10, stale_s=900.0):
    lock_path = os.path.normpath(str(lock_path))
    parent = os.path.dirname(os.path.abspath(lock_path))
    if parent and (not os.path.exists(parent)):
        os.makedirs(parent, exist_ok=True)

    start = time.time()
    last_err = None
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            with os.fdopen(fd, "w", encoding="utf-8", errors="ignore", newline="") as f:
                f.write(f"pid={os.getpid()}\n")
                f.write(f"time={time.time():0.6f}\n")
            return None
        except FileExistsError as e:
            last_err = e
            if stale_s:
                try:
                    age_s = time.time() - os.path.getmtime(lock_path)
                    if age_s > float(stale_s):
                        try:
                            os.remove(lock_path)
                            continue
                        except Exception:
                            pass
                except Exception:
                    pass

            if (time.time() - start) >= float(timeout_s):
                return TimeoutError(f"Timeout acquiring lock: {lock_path} ({last_err})")
            time.sleep(float(poll_s))
        except Exception as e:
            return e


def _release_file_lock(lock_path):
    try:
        os.remove(os.path.normpath(str(lock_path)))
    except FileNotFoundError:
        return
    except Exception:
        return


def _atomic_write_lines(path, lines, n_tries=8, sleep_s=0.15):
    path = os.path.normpath(path)
    parent = os.path.dirname(os.path.abspath(path))
    if parent and (not os.path.exists(parent)):
        os.makedirs(parent, exist_ok=True)
    last_err = None
    for _ in range(int(n_tries)):
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(prefix=os.path.basename(path) + ".tmp.", dir=parent, text=True)
            with os.fdopen(fd, "w", encoding="utf-8", errors="ignore", newline="") as f:
                f.writelines(lines)
                try:
                    f.flush()
                    os.fsync(f.fileno())
                except Exception:
                    pass
            os.replace(tmp_path, path)
            return None
        except Exception as e:
            last_err = e
            try:
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            if sleep_s:
                time.sleep(float(sleep_s))
    return last_err


def _sync_outputs_from_filex_dir(batch_file, base_dir, output_files, dest_dir=None):
    filex_path = _resolve_filex_from_batch(batch_file, base_dir)
    if not filex_path:
        return
    src_dir = os.path.dirname(os.path.abspath(filex_path))
    dest_dir = dest_dir or base_dir

    for fn in output_files:
        src = os.path.join(src_dir, fn)
        if not (os.path.exists(src) and os.path.getsize(src) > 0):
            continue

        dest = os.path.join(dest_dir, fn)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            try:
                if os.path.getmtime(dest) >= os.path.getmtime(src):
                    continue
            except Exception:
                pass

        last_err = _copy_with_retries(src, dest, n_tries=5, sleep_s=0.2)
        if last_err is not None:
            print(f"Warning: could not sync {fn}: {last_err}")


def _sync_genotype_files_to_run_dir(src_dir, run_dir):
    if not src_dir or not run_dir:
        return
    for fn in [CUL_FILE, ECO_FILE, SPE_FILE]:
        src = os.path.join(src_dir, fn)
        if not (os.path.exists(src) and os.path.getsize(src) > 0):
            continue
        dst = os.path.join(run_dir, fn)
        last_err = _copy_with_retries(src, dst, n_tries=5, sleep_s=0.2)
        if last_err is not None:
            print(f"Warning: could not sync {fn}: {last_err}")


def _localize_experiment_files(filex_path, run_dir):
    if not filex_path or not run_dir:
        return None
    if not os.path.exists(filex_path):
        return None

    src_dir = os.path.dirname(os.path.abspath(filex_path))
    base = os.path.basename(filex_path)
    stem = base.rsplit(".", 1)[0] if "." in base else base

    copied_filex = None
    for ext in ["TMX", "TMA", "TMT"]:
        src = os.path.join(src_dir, f"{stem}.{ext}")
        if not (os.path.exists(src) and os.path.getsize(src) > 0):
            continue
        dst = os.path.join(run_dir, os.path.basename(src))
        last_err = _copy_with_retries(src, dst, n_tries=5, sleep_s=0.2)
        if last_err is not None:
            print(f"Warning: could not localize {os.path.basename(src)}: {last_err}")
            continue
        if ext == "TMX":
            copied_filex = dst

    if not copied_filex:
        # The calibration wrapper may already have staged the FileX into the
        # run directory.  In that case copying the file onto itself fails and
        # the loop above intentionally leaves ``copied_filex`` unset; still
        # normalize the staged copy and return it to the caller.
        staged = os.path.join(run_dir, base)
        if os.path.exists(staged):
            copied_filex = staged
    if copied_filex:
        _normalize_filex_initial_conditions_boundary(copied_filex)

    return copied_filex


def _normalize_filex_initial_conditions_boundary(filex_path):
    """Remove a DSSAT-incompatible blank line at the end of INITIAL CONDITIONS.

    Some user FileX files contain one empty line between the last initial
    condition row and the next section header.  DSSAT's FileX reader can
    interpret that line as an invalid initial-condition record (IPSLIN).  The
    source file remains untouched; only the per-run localized copy is
    normalized.
    """
    try:
        with open(filex_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception:
        return

    out_lines = []
    section = None
    changed = False
    for index, line in enumerate(lines):
        stripped = line.strip().upper()
        if stripped.startswith("*"):
            section = stripped
        if not stripped:
            next_section = ""
            for candidate in lines[index + 1 :]:
                if candidate.strip():
                    next_section = candidate.strip().upper()
                    break
            if section == "*INITIAL CONDITIONS" or next_section.startswith("*PLANTING DETAILS"):
                changed = True
                continue
        out_lines.append(line)

    if not changed:
        return
    last_err = _atomic_write_lines(filex_path, out_lines, n_tries=20, sleep_s=0.05)
    if last_err is not None:
        raise last_err


def _write_local_batch(batch_src_path, batch_dst_path, filex_basename):
    if not (batch_src_path and os.path.exists(batch_src_path)):
        return False
    try:
        with open(batch_src_path, "r") as f:
            lines = f.readlines()
    except Exception:
        return False

    out_lines = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("$") or s.startswith("@") or s.startswith("!"):
            out_lines.append(line)
            continue

        m = re.match(r"^(\s*)(\S+)(.*)$", line.rstrip("\n"))
        if not m:
            out_lines.append(line)
            continue
        prefix = m.group(1)
        old_tok = m.group(2)
        rest = m.group(3)

        new_tok = str(filex_basename)
        if len(new_tok) < len(old_tok):
            new_tok = new_tok + (" " * (len(old_tok) - len(new_tok)))

        out_lines.append(prefix + new_tok + rest + "\n")

    try:
        with open(batch_dst_path, "w") as f:
            f.writelines(out_lines)
        return True
    except Exception:
        return False

def _count_batch_runs(batch_file):
    batch_path = _resolve_batch_path(batch_file)
    if not batch_path:
        return 0
    n = 0
    with open(batch_path, "r") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s.startswith("$") or s.startswith("@") or s.startswith("!"):
                continue
            n += 1
    return n

def _append_pest_file(new_lines, pest_path):
    existing_lines = []
    if os.path.exists(pest_path):
        with open(pest_path, "r") as f:
            existing_lines = [line.rstrip("\n") for line in f if line.strip()]
    with open(pest_path, "w") as f:
        for line in existing_lines:
            f.write(line + "\n")
        for line in new_lines:
            f.write(line + "\n")


def _write_pest_eval_from_evaluate(evaluate_out_path, pest_eval_path):
    def _read_evaluate_out(path):
        rows = []
        header = None
        with open(path, "r") as f:
            for line in f:
                s = line.rstrip("\n")
                if not s.strip():
                    continue

                stripped = s.lstrip()
                if stripped.startswith("@RUN"):
                    header = stripped.split()
                    continue

                if header is None:
                    continue
                if stripped.startswith("*") or stripped.startswith("@"):
                    continue
                if not re.match(r"^\s*\d+\s+", s):
                    continue

                parts = stripped.split()
                if len(parts) < len(header):
                    parts += ["-99"] * (len(header) - len(parts))
                rows.append(dict(zip(header, parts[: len(header)])))

        return pd.DataFrame(rows)

    def _as_int(v, default=-99):
        try:
            if pd.isna(v):
                return default
            return int(float(v))
        except Exception:
            return default

    df = _read_evaluate_out(evaluate_out_path)
    if df.empty:
        n_runs = _count_batch_runs(BATCH_FILE)
        if n_runs <= 0:
            n_runs = 1
        new_lines = [
            f"RUN {i:d} TN {-99:d} @PDAPS@ {0.0:0.3f} @PDAPM@ {0.0:0.3f} "
            f"@ADAPS@ {-99.0:0.3f} @ADAPM@ {-99.0:0.3f} "
            f"@MDAPS@ {-99.0:0.3f} @MDAPM@ {-99.0:0.3f}"
            for i in range(1, n_runs + 1)
        ]
        _append_pest_file(new_lines, pest_eval_path)
        return

    expected_cols = ["@RUN", "TN", "PDAPS", "PDAPM", "ADAPS", "ADAPM", "MDAPS", "MDAPM"]
    for c in expected_cols:
        if c not in df.columns:
            df[c] = 0 if c in {"PDAPS", "PDAPM"} else -99

    for c in expected_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(-99)

    out_df = df[expected_cols].copy().sort_values(by="@RUN", kind="mergesort")
    new_lines = []
    for _, row in out_df.iterrows():
        run_no = _as_int(row["@RUN"], default=-99)
        tn = _as_int(row["TN"], default=-99)
        pdaps = float(row["PDAPS"]) if not pd.isna(row["PDAPS"]) else 0.0
        pdapm = float(row["PDAPM"]) if not pd.isna(row["PDAPM"]) else 0.0
        adaps = float(row["ADAPS"]) if not pd.isna(row["ADAPS"]) else -99.0
        adapm = float(row["ADAPM"]) if not pd.isna(row["ADAPM"]) else -99.0
        mdaps = float(row["MDAPS"]) if not pd.isna(row["MDAPS"]) else -99.0
        mdapm = float(row["MDAPM"]) if not pd.isna(row["MDAPM"]) else -99.0
        new_lines.append(
            f"RUN {run_no:d} TN {tn:d} @PDAPS@ {pdaps:0.3f} @PDAPM@ {pdapm:0.3f} "
            f"@ADAPS@ {adaps:0.3f} @ADAPM@ {adapm:0.3f} "
            f"@MDAPS@ {mdaps:0.3f} @MDAPM@ {mdapm:0.3f}"
        )
    _append_pest_file(new_lines, pest_eval_path)


def _write_pest_grow_from_evaluate(evaluate_out_path, pest_grow_path):
    def _read_evaluate_out(path):
        rows = []
        header = None
        with open(path, "r") as f:
            for line in f:
                s = line.rstrip("\n")
                if not s.strip():
                    continue

                stripped = s.lstrip()
                if stripped.startswith("@RUN"):
                    header = stripped.split()
                    continue

                if header is None:
                    continue
                if stripped.startswith("*") or stripped.startswith("@"): 
                    continue
                if not re.match(r"^\s*\d+\s+", s):
                    continue

                parts = stripped.split()
                if len(parts) < len(header):
                    parts += ["-99"] * (len(header) - len(parts))
                rows.append(dict(zip(header, parts[: len(header)])))

        return pd.DataFrame(rows)

    def _as_int(v, default=-99):
        try:
            if pd.isna(v):
                return default
            return int(float(v))
        except Exception:
            return default

    df = _read_evaluate_out(evaluate_out_path)
    if df.empty:
        n_runs = _count_batch_runs(BATCH_FILE)
        if n_runs <= 0:
            n_runs = 1
        new_lines = [
            f"RUN {i:d} TN {-99:d} @HWAMS@ {-99.0:0.3f} @LAIXS@ {-99.0:0.3f} @CNAMS@ {-99.0:0.3f}"
            for i in range(1, n_runs + 1)
        ]
        _append_pest_file(new_lines, pest_grow_path)
        return

    expected_cols = ["@RUN", "TN", "HWAMS", "LAIXS", "CNAMS"]
    for c in expected_cols:
        if c not in df.columns:
            df[c] = -99

    for c in expected_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(-99)

    out_df = df[expected_cols].copy().sort_values(by="@RUN", kind="mergesort")
    new_lines = []
    for _, row in out_df.iterrows():
        run_no = _as_int(row["@RUN"], default=-99)
        tn = _as_int(row["TN"], default=-99)
        hwams = float(row["HWAMS"]) if not pd.isna(row["HWAMS"]) else -99.0
        laixs = float(row["LAIXS"]) if not pd.isna(row["LAIXS"]) else -99.0
        cnams = float(row["CNAMS"]) if not pd.isna(row["CNAMS"]) else -99.0
        new_lines.append(
            f"RUN {run_no:d} TN {tn:d} @HWAMS@ {hwams:0.3f} @LAIXS@ {laixs:0.3f} @CNAMS@ {cnams:0.3f}"
        )
    _append_pest_file(new_lines, pest_grow_path)


def _write_pest_joint_from_evaluate(evaluate_out_path, pest_joint_path):
    def _read_evaluate_out(path):
        rows = []
        header = None
        with open(path, "r") as f:
            for line in f:
                s = line.rstrip("\n")
                if not s.strip():
                    continue

                stripped = s.lstrip()
                if stripped.startswith("@RUN"):
                    header = stripped.split()
                    continue

                if header is None:
                    continue
                if stripped.startswith("*") or stripped.startswith("@"): 
                    continue
                if not re.match(r"^\s*\d+\s+", s):
                    continue

                parts = stripped.split()
                if len(parts) < len(header):
                    parts += ["-99"] * (len(header) - len(parts))
                rows.append(dict(zip(header, parts[: len(header)])))

        return pd.DataFrame(rows)

    def _as_int(v, default=-99):
        try:
            if pd.isna(v):
                return default
            return int(float(v))
        except Exception:
            return default

    df = _read_evaluate_out(evaluate_out_path)
    if df.empty:
        n_runs = _count_batch_runs(BATCH_FILE)
        if n_runs <= 0:
            n_runs = 1
        new_lines = [
            f"RUN {i:d} TN {-99:d} "
            f"@HWAMS@ {-99.0:0.3f} @HIAMS@ {-99.0:0.3f} @LAIXS@ {-99.0:0.3f} @CNAMS@ {-99.0:0.3f} "
            f"@CHTAS@ {-99.0:0.3f} @CNAAS@ {-99.0:0.3f} "
            f"@PWAMS@ {-99.0:0.3f} @H#AMS@ {-99.0:0.3f}"
            for i in range(1, n_runs + 1)
        ]
        _append_pest_file(new_lines, pest_joint_path)
        return

    expected_cols = [
        "@RUN",
        "TN",
        "HWAMS",
        "LAIXS",
        "CNAMS",
        "CHTAS",
        "CNAAS",
        "PWAMS",
        "H#AMS",
        "HIAMS",
    ]
    for c in expected_cols:
        if c not in df.columns:
            df[c] = -99

    for c in expected_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(-99)

    out_df = df[expected_cols].copy().sort_values(by="@RUN", kind="mergesort")
    new_lines = []
    for _, row in out_df.iterrows():
        run_no = _as_int(row["@RUN"], default=-99)
        tn = _as_int(row["TN"], default=-99)
        hwams = float(row["HWAMS"]) if not pd.isna(row["HWAMS"]) else -99.0
        laixs = float(row["LAIXS"]) if not pd.isna(row["LAIXS"]) else -99.0
        cnams = float(row["CNAMS"]) if not pd.isna(row["CNAMS"]) else -99.0
        chtas = float(row["CHTAS"]) if not pd.isna(row["CHTAS"]) else -99.0
        cnaas = float(row["CNAAS"]) if not pd.isna(row["CNAAS"]) else -99.0
        pwams = float(row["PWAMS"]) if not pd.isna(row["PWAMS"]) else -99.0
        h_n_ams = float(row["H#AMS"]) if not pd.isna(row["H#AMS"]) else -99.0
        hiams = float(row["HIAMS"]) if not pd.isna(row["HIAMS"]) else -99.0
        new_lines.append(
            f"RUN {run_no:d} TN {tn:d} "
            f"@HWAMS@ {hwams:0.3f} @HIAMS@ {hiams:0.3f} @LAIXS@ {laixs:0.3f} @CNAMS@ {cnams:0.3f} "
            f"@CHTAS@ {chtas:0.3f} @CNAAS@ {cnaas:0.3f} "
            f"@PWAMS@ {pwams:0.3f} @H#AMS@ {h_n_ams:0.3f}"
        )
    _append_pest_file(new_lines, pest_joint_path)

def _first_batch_filex_path(batch_file):
    batch_path = _resolve_batch_path(batch_file)
    if not batch_path:
        return None
    with open(batch_path, "r") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s.startswith("$") or s.startswith("@") or s.startswith("!"):
                continue
            return s.split()[0]
    return None

def _infer_cultivar_from_filex(filex_path):
    if not filex_path or not os.path.exists(filex_path):
        return None
    with open(filex_path, "r") as f:
        lines = f.readlines()

    def _section_idx(tag):
        for i, line in enumerate(lines):
            if line.strip().upper().startswith(tag):
                return i
        return -1

    trt_idx = _section_idx("*TREATMENTS")
    cul_idx = _section_idx("*CULTIVARS")
    if trt_idx == -1 or cul_idx == -1:
        return None

    cu_level = None
    for i in range(trt_idx + 1, len(lines)):
        s = lines[i].rstrip("\n")
        if not s.strip():
            continue
        if s.startswith("*"):
            break
        if s.startswith("@"):
            continue

        parts = s.split()
        if len(parts) < 4 + 13:
            continue

        factor_tokens = parts[-13:]
        try:
            factors = [int(t) for t in factor_tokens]
        except Exception:
            continue

        cu_level = factors[0]
        break

    if cu_level is None:
        return None

    for i in range(cul_idx + 1, len(lines)):
        s = lines[i].strip("\n")
        if not s.strip():
            continue
        if s.startswith("*"):
            break
        if s.startswith("@"):
            continue
        parts = s.split()
        if len(parts) < 4:
            continue
        try:
            c = int(parts[0])
        except Exception:
            continue
        if c == cu_level:
            return parts[2]

    return None


def _infer_soil_id_from_filex(filex_path):
    if not filex_path or not os.path.exists(filex_path):
        return None
    header = None
    soil_idx = None
    in_fields = False
    with open(filex_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.rstrip("\n")
            u = s.strip().upper()
            if not u:
                continue
            if u.startswith("*FIELDS"):
                in_fields = True
                header = None
                soil_idx = None
                continue
            if in_fields and u.startswith("*") and (not u.startswith("*FIELDS")):
                break
            if not in_fields:
                continue
            if s.lstrip().startswith("@"):
                header = s.split()
                try:
                    soil_idx = header.index("ID_SOIL")
                except ValueError:
                    soil_idx = None
                continue
            if s.lstrip().startswith("!"):
                continue
            if header is None or soil_idx is None:
                continue
            parts = s.split()
            if len(parts) <= soil_idx:
                continue
            sid = str(parts[soil_idx]).strip()
            return sid or None
    return None

def cleanup(target_dir=".", keep_dssat_outputs=False, keep_soil_water=False, keep_nitrogen_outputs=False):
    """Clean up DSSAT transient output files.

    Parameters
    ----------
    target_dir : str
        Directory containing DSSAT output files.
    keep_dssat_outputs : bool
        If True, keep FreshWt.OUT and PlantGro.OUT (process-level diagnostics).
    keep_soil_water : bool
        If True, keep SoilWat.OUT (needed for the SOIL_WATER observation group
        in calibration mode; the file is large and should be off otherwise).
    """
    if not keep_dssat_outputs and not keep_soil_water:
        for file in (OUTPUT_FILES + ["Evaluate.OUT", "SoilWat.OUT"]):
            p = os.path.join(target_dir, file)
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
    elif not keep_dssat_outputs and keep_soil_water:
        # SoilWat.OUT is kept; still drop other OUTPUT_FILES + Evaluate.OUT.
        for file in (OUTPUT_FILES + ["Evaluate.OUT"]):
            p = os.path.join(target_dir, file)
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    for file in ["LUN.LST", "LUN.OUT", "LUN.REP", "DSSAT48.LST"]:
        p = os.path.join(target_dir, file)
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass

    keep_out = {
        PEST_EVAL_FILE,
        PEST_GROW_FILE,
        PEST_JOINT_FILE,
        PEST_HARVEST_FILE,
        PEST_TMTGROW_FILE,
        PEST_SOILWAT_FILE,
        "Evaluate.OUT",
    }
    if keep_dssat_outputs:
        keep_out.update({"FreshWt.OUT", "PlantGro.OUT"})
    if keep_soil_water:
        keep_out.update({"SoilWat.OUT"})
    if keep_nitrogen_outputs:
        keep_out.update({"PlantN.OUT", "SoilNi.OUT", "SoilN.OUT"})
    for p in glob.glob(os.path.join(target_dir, "*.OUT")):
        if os.path.basename(p) in keep_out:
            continue
        try:
            os.remove(p)
        except Exception:
            pass

    for p in glob.glob(os.path.join(target_dir, "*.LST")):
        try:
            os.remove(p)
        except Exception:
            pass

def handle_failure(exit_code):
    """
    Handle model failure by creating a dummy Evaluate.OUT with high penalty.
    """
    print(f"DSSAT execution failed with exit code {exit_code}.")
    
    # Write a dummy Evaluate.OUT if it doesn't exist
    if not os.path.exists("Evaluate.OUT"):
        try:
            with open("Evaluate.OUT", "w") as f:
                f.write("*DSSAT Model Failed - Penalty Applied\n")
                f.write("@TRNO   RE     CR    T    T(D)    P    P(D)    L    L(D)    G    G(D)    M    M(D)    H    H(D)\n")
                # Write dummy line
                f.write("     1     1     1    -99    -99    -99    -99    -99    -99    -99    -99    -99    -99    -99    -99\n")
            print("Created dummy Evaluate.OUT")
        except Exception as e:
            print(f"Error creating dummy output: {e}")

    if not os.path.exists(_eval_pest_file()):
        n_runs = _count_batch_runs(BATCH_FILE)
        if n_runs <= 0:
            n_runs = 1
        with open(_eval_pest_file(), "w") as f:
            for i in range(1, n_runs + 1):
                f.write(
                    f"RUN {i:d} TN {-99:d} @PDAPS@ {0.0:0.3f} @PDAPM@ {0.0:0.3f} "
                    f"@ADAPS@ {-99.0:0.3f} @ADAPM@ {-99.0:0.3f} "
                    f"@MDAPS@ {-99.0:0.3f} @MDAPM@ {-99.0:0.3f}\n"
                )

    if not os.path.exists(_pest_path(PEST_GROW_FILE)):
        n_runs = _count_batch_runs(BATCH_FILE)
        if n_runs <= 0:
            n_runs = 1
        with open(_pest_path(PEST_GROW_FILE), "w") as f:
            for i in range(1, n_runs + 1):
                f.write(
                    f"RUN {i:d} TN {-99:d} @HWAMS@ {-99.0:0.3f} @LAIXS@ {-99.0:0.3f} @CNAMS@ {-99.0:0.3f}\n"
                )

    if not os.path.exists(_joint_pest_file()):
        n_runs = _count_batch_runs(BATCH_FILE)
        if n_runs <= 0:
            n_runs = 1
        with open(_joint_pest_file(), "w") as f:
            for i in range(1, n_runs + 1):
                f.write(
                    f"RUN {i:d} TN {-99:d} "
                    f"@HWAMS@ {-99.0:0.3f} @LAIXS@ {-99.0:0.3f} @CNAMS@ {-99.0:0.3f} "
                    f"@CHTAS@ {-99.0:0.3f} @CNAAS@ {-99.0:0.3f} "
                    f"@PWAMS@ {-99.0:0.3f} @H#AMS@ {-99.0:0.3f} @HIAMS@ {-99.0:0.3f}\n"
                )

    if not os.path.exists(_harvest_pest_file()):
        try:
            _write_pest_harvest_from_tmt_and_freshwt(BATCH_FILE, "FreshWt.OUT", _harvest_pest_file())
        except Exception:
            n_runs = _count_batch_runs(BATCH_FILE)
            if n_runs <= 0:
                n_runs = 1
            with open(_harvest_pest_file(), "w") as f:
                for i in range(1, n_runs + 1):
                    f.write(f"RUN {i:d} TN {-99:d} HNO -99 DATE -99 @PWADS@ -99.000 @PWAIS@ -99.000\n")

    if not os.path.exists(_tmtgrow_pest_file()):
        try:
            _write_pest_tmtgrow_from_tmt_and_plantgro(
                BATCH_FILE, "PlantGro.OUT", _tmtgrow_pest_file(), plantn_path="PlantN.OUT"
            )
        except Exception:
            n_runs = _count_batch_runs(BATCH_FILE)
            if n_runs <= 0:
                n_runs = 1
            with open(_tmtgrow_pest_file(), "w") as f:
                for i in range(1, n_runs + 1):
                    f.write(
                        f"RUN {i:d} TN {-99:d} DATE -99 "
                        f"@LAIDS@ -99.000 @LWADS@ -99.000 @SWADS@ -99.000 @CHTDS@ -99.000\n"
                    )

def _format_to_width(val, width, orig_token=None):
    if width <= 0:
        return ""

    try:
        v = float(val)
    except Exception:
        v = val

    if isinstance(v, float):
        orig_strip = (orig_token or "").strip()
        orig_has_dot = "." in orig_strip
        orig_trailing_dot = orig_strip.endswith(".")

        # DSSAT SPE uses compact fractional tokens (e.g. ``.05``).  Do not
        # round a sensitivity candidate back to the template precision: that
        # would make lower/upper injections silently identical.  Prefer the
        # shortest representation that preserves the requested value.
        if abs(v) < 1 and (orig_strip.startswith((".", "-.")) or orig_has_dot):
            sign = "-" if v < 0 else ""
            av = abs(v)
            for dec in range(6, 0, -1):
                body = f"{av:.{dec}f}".split(".", 1)[1].rstrip("0")
                if body:
                    token = sign + "." + body
                    if len(token) <= width:
                        return token.rjust(width)

        if orig_token:
            tok = orig_token.strip()
            if tok.startswith(".") or tok.startswith("-."):
                try:
                    dec = len(tok.split(".", 1)[1]) if "." in tok else 0
                except Exception:
                    dec = 0
                if dec >= 0:
                    try:
                        s0 = f"{v:.{dec}f}"
                    except Exception:
                        s0 = None
                    if s0:
                        if s0.startswith("-0."):
                            s0 = "-." + s0[3:]
                        elif s0.startswith("0."):
                            s0 = "." + s0[2:]
                        if len(s0) <= width:
                            return s0.rjust(width)

        candidates = []

        if orig_has_dot:
            dec = len(orig_strip.split(".", 1)[1])
            if dec >= 0:
                candidates.append(("f", dec))

        for d in range(min(6, max(0, width - 2)), -1, -1):
            candidates.append(("f", d))

        if abs(v - round(v)) < 1e-9:
            candidates.append(("d", 0))

        for kind, d in candidates:
            if kind == "d":
                s = f"{int(round(v)):>{width}d}"
                if len(s) == width:
                    return s
                continue

            if d == 0 and orig_trailing_dot:
                try:
                    s_td = f"{v:.0f}."
                    if len(s_td) <= width:
                        return s_td.rjust(width)
                except Exception:
                    pass

            s = f"{v:>{width}.{d}f}" if d > 0 else f"{v:>{width}.0f}"
            if len(s) == width:
                if abs(v) < 1 and orig_token and orig_token.strip().startswith("."):
                    st = s.strip()
                    if st.startswith("-0."):
                        st = "-." + st[3:]
                    elif st.startswith("0."):
                        st = "." + st[2:]
                    s2 = st.rjust(width)
                    if len(s2) == width:
                        return s2
                return s

        for prec in range(max(1, width - 2), 0, -1):
            s = f"{v:>{width}.{prec}g}"
            if len(s) == width and ("*" not in s):
                return s

    s = str(v)
    if len(s) > width:
        raise ValueError(f"value {v!r} cannot be represented in SPE field width {width}")
    return s.rjust(width)


def _format_to_width_preserve_space(val, width, orig_token=None):
    orig = orig_token or ""
    if width >= 2 and orig.startswith(" "):
        inner = _format_to_width(val, width - 1, orig_token=orig[1:])
        if len(inner) != width - 1:
            inner = inner[: width - 1].rjust(width - 1)
        return " " + inner

    s = _format_to_width(val, width, orig_token=orig)
    if len(s) != width:
        s = s[:width].rjust(width)
    return s


def _field_spans_from_header(header_line, field_names, line_len):
    positions = []
    pos = 0
    for name in field_names:
        idx = header_line.find(str(name), pos)
        if idx < 0:
            return None
        positions.append(idx)
        pos = idx + len(str(name))

    spans = []
    for i, start in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else line_len
        spans.append((start, min(end, line_len)))
    return spans


def _to_dssatpro_path(p):
    p = os.path.abspath(str(p))
    drive, rest = os.path.splitdrive(p)
    rest = rest.replace("/", "\\")
    if not rest.startswith("\\"):
        rest = "\\" + rest
    return f"{drive} {rest}"


def _from_dssatpro_path(s):
    s = str(s or "").strip()
    if not s:
        return None
    m = re.match(r"^([A-Za-z]:)\s+(\\.+)$", s)
    if not m:
        return None
    return os.path.normpath(m.group(1) + m.group(2))


def _read_crd_dir_from_dssatpro(dssatpro_path):
    if not (dssatpro_path and os.path.exists(dssatpro_path)):
        return None
    try:
        with open(dssatpro_path, "r") as f:
            for line in f:
                if line.startswith("CRD "):
                    return _from_dssatpro_path(line[4:])
    except Exception:
        return None
    return None


def _write_dssatpro_with_crd(src_path, dst_path, crd_path):
    if not (src_path and os.path.exists(src_path)):
        return False
    with open(src_path, "r") as f:
        lines = f.readlines()

    crd_line = f"CRD {_to_dssatpro_path(crd_path)}\n"
    wrote = False
    for i, line in enumerate(lines):
        if line.startswith("CRD "):
            lines[i] = crd_line
            wrote = True
            break
    if not wrote:
        ins = 0
        for j, line in enumerate(lines):
            if line.strip() == "":
                ins = j + 1
                break
        lines.insert(ins, crd_line)

    with open(dst_path, "w") as f:
        f.writelines(lines)
    return True


def _cul_param_spans_from_template_line(cul_line, n_fields):
    line = (cul_line or "").rstrip("\n")
    if not line or n_fields <= 0:
        return None

    m = re.search(r"\s\.\s+", line)
    if not m:
        return None

    pos = m.end()
    while pos < len(line) and line[pos] == " ":
        pos += 1
    while pos < len(line) and line[pos] != " ":
        pos += 1

    field_re = re.compile(
        r"\s+[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[Ee][-+]?\d+)?"
    )
    matches = list(field_re.finditer(line[pos:]))
    if len(matches) < n_fields:
        return None

    spans = []
    for mm in matches[:n_fields]:
        spans.append((pos + mm.start(), pos + mm.end()))
    return spans


def _eco_param_spans_from_template_line(eco_line, n_fields):
    line = (eco_line or "").rstrip("\n")
    if not line or n_fields <= 0:
        return None

    pos = 0
    while pos < len(line) and line[pos] != " ":
        pos += 1

    field_re = re.compile(
        r"\s+[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[Ee][-+]?\d+)?"
    )
    matches = list(field_re.finditer(line[pos:]))
    if len(matches) < n_fields:
        return None

    spans = []
    for mm in matches[:n_fields]:
        spans.append((pos + mm.start(), pos + mm.end()))
    return spans


def _read_param_dict(param_csv_path):
    if not param_csv_path or not os.path.exists(param_csv_path):
        return {}
    params_df = pd.read_csv(param_csv_path)
    cols = [str(c) for c in params_df.columns]

    name_col = None
    value_col = None

    if "name" in cols and "value" in cols:
        name_col = "name"
        value_col = "value"
    elif "Value" in cols:
        value_col = "Value"
        unnamed = [c for c in cols if c.lower().startswith("unnamed")]
        if unnamed:
            name_col = unnamed[0]
    if name_col is None or value_col is None:
        if len(cols) >= 2:
            name_col, value_col = cols[0], cols[1]

    if name_col is None or value_col is None:
        raise ValueError(f"Unrecognized parameter CSV columns: {cols}")

    param_dict = {}
    for _, r in params_df.iterrows():
        k = str(r.get(name_col, "")).strip()
        if not k or k.lower() == "nan":
            continue
        try:
            v = float(r.get(value_col))
        except Exception:
            continue
        param_dict[k.strip().upper()] = v
    return param_dict


def _infer_ecotype_from_cul(cul_path, target_cultivar):
    if not cul_path or not target_cultivar or not os.path.exists(cul_path):
        return None

    number_re = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[Ee][-+]?\d+)?")
    with open(cul_path, "r") as f:
        for line in f:
            if not line.startswith(target_cultivar):
                continue
            m = number_re.search(line)
            if not m:
                return None
            prefix = line[: m.start()]
            parts = prefix.split()
            if not parts:
                return None
            return parts[-1].strip() or None
    return None

def update_cul_file(param_csv_path=PARAM_CSV, target_cultivar=None):
    """
    Reads pest_params.csv and TMGRO048.CUL.base, updates values, writes TMGRO048.CUL.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cul_base_path = None
    cand = os.path.join(script_dir, CUL_BASE_FILE)
    if os.path.exists(cand):
        cul_base_path = cand
    elif os.path.exists(CUL_BASE_FILE):
        cul_base_path = CUL_BASE_FILE
    else:
        cand = os.path.normpath(os.path.join(script_dir, "..", "..", "Genotype", CUL_FILE))
        if os.path.exists(cand):
            cul_base_path = cand

    if not os.path.exists(param_csv_path):
        print(f"No {param_csv_path} found. Using base CUL file.")
        if cul_base_path and os.path.exists(cul_base_path):
            lock_path = os.path.abspath(CUL_FILE) + ".lock"
            lock_err = _acquire_file_lock(lock_path, timeout_s=180.0, poll_s=0.10, stale_s=900.0)
            if lock_err is not None:
                raise lock_err
            try:
                _copy_with_retries(cul_base_path, CUL_FILE, n_tries=30, sleep_s=0.20)
            finally:
                _release_file_lock(lock_path)
        return

    try:
        param_dict = _read_param_dict(param_csv_path)
    except Exception as e:
        raise RuntimeError(f"Could not read parameter CSV {param_csv_path}: {e}") from e

    if not cul_base_path or (not os.path.exists(cul_base_path)):
        raise FileNotFoundError(f"Cultivar base file not found: {CUL_BASE_FILE}")

    with open(cul_base_path, "r") as f:
        lines = f.readlines()

    # Parse Base File to find column indices
    header_idx = -1
    cultivar_idx = -1
    
    for i, line in enumerate(lines):
        if line.startswith("@VAR#"):
            header_idx = i
        elif target_cultivar and line.startswith(target_cultivar):
            cultivar_idx = i

    if header_idx == -1 or cultivar_idx == -1:
        raise RuntimeError(
            f"Invalid CUL structure or cultivar {target_cultivar!r} is absent from {cul_base_path}"
        )

    header_line = lines[header_idx].rstrip("\n")
    headers = header_line.split()
    # Headers: @VAR# VRNAME EXPNO ECO# CSDL ...
    # Indices: 0     1      2     3    4    ...
    # Parameter names start at index 4
    param_names = headers[4:]
    
    tm_line = lines[cultivar_idx]

    line_len = max(len(header_line), len(tm_line.rstrip("\n")))
    spans = _cul_param_spans_from_template_line(tm_line, len(param_names))
    if spans is None or len(spans) < len(param_names):
        spans = _field_spans_from_header(header_line, param_names, line_len)
    if spans is None or len(spans) < len(param_names):
        print("Error: Could not derive fixed-width spans for CUL parameters.")
        return

    new_chars = list(tm_line.rstrip("\n"))
    for name, (abs_s0, abs_s1) in zip(param_names, spans[: len(param_names)]):
        key = str(name).strip().upper()
        if key not in param_dict:
            continue

        orig = tm_line[abs_s0:abs_s1]
        width = abs_s1 - abs_s0
        formatted = _format_to_width_preserve_space(float(param_dict[key]), width, orig_token=orig)
        new_chars[abs_s0:abs_s1] = list(formatted)

    lines[cultivar_idx] = "".join(new_chars) + "\n"

    lock_path = os.path.abspath(CUL_FILE) + ".lock"
    lock_err = _acquire_file_lock(lock_path, timeout_s=180.0, poll_s=0.10, stale_s=900.0)
    if lock_err is not None:
        raise lock_err
    try:
        last_err = _atomic_write_lines(CUL_FILE, lines, n_tries=60, sleep_s=0.20)
        if last_err is not None:
            raise last_err
    finally:
        _release_file_lock(lock_path)


def update_eco_file(param_csv_path=PARAM_CSV, target_ecotype=None):
    if not target_ecotype:
        raise ValueError("A target ecotype is required for ECO injection")
    if not os.path.exists(param_csv_path):
        raise FileNotFoundError(f"Parameter CSV not found: {param_csv_path}")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    eco_base_path = None
    cand = os.path.join(script_dir, ECO_FILE + ".base")
    if os.path.exists(cand):
        eco_base_path = cand
    else:
        local_base = ECO_FILE + ".base"
        if os.path.exists(local_base):
            eco_base_path = local_base
            cand = None
        else:
            cand = os.path.normpath(os.path.join(script_dir, "..", "..", "Genotype", ECO_FILE))
        if cand and os.path.exists(cand):
            eco_base_path = cand
        elif os.path.exists(ECO_FILE):
            eco_base_path = ECO_FILE

    if not eco_base_path:
        raise FileNotFoundError(f"Ecotype base file not found: {ECO_FILE}.base")

    try:
        param_dict = _read_param_dict(param_csv_path)
    except Exception as e:
        raise RuntimeError(f"Could not read parameter CSV {param_csv_path}: {e}") from e
    if not param_dict:
        return

    validate_candidate_parameters(param_dict)

    with open(eco_base_path, "r") as f:
        lines = f.readlines()

    header_idx = -1
    eco_idx = -1
    for i, line in enumerate(lines):
        if line.startswith("@ECO#"):
            header_idx = i
        elif line.startswith(target_ecotype):
            eco_idx = i

    if header_idx == -1 or eco_idx == -1:
        raise RuntimeError(f"Invalid ECO structure or ecotype {target_ecotype!r} is absent from {eco_base_path}")

    header_line = lines[header_idx].rstrip("\n")
    headers = header_line.split()
    if len(headers) < 3:
        raise RuntimeError(f"Invalid ECO header in {eco_base_path}")
    param_names = headers[2:]

    eco_line = lines[eco_idx]

    line_len = len(eco_line.rstrip("\n"))
    spans = _eco_param_spans_from_template_line(eco_line, len(param_names))
    if spans is None or len(spans) < len(param_names):
        line_len = max(len(header_line), len(eco_line.rstrip("\n")))
        spans = _field_spans_from_header(header_line, param_names, line_len)
    if spans is None or len(spans) < len(param_names):
        raise RuntimeError(f"Could not resolve fixed-width ECO fields in {eco_base_path}")

    new_chars = list(eco_line.rstrip("\n").ljust(line_len))
    for name, (abs_s0, abs_s1) in zip(param_names, spans[: len(param_names)]):
        key = str(name).strip().upper()
        if key == "TM":
            if "ECO_TM" not in param_dict:
                continue
            v = float(param_dict["ECO_TM"])
        else:
            if key not in param_dict:
                continue
            v = float(param_dict[key])

        orig = eco_line[abs_s0:abs_s1]
        width = abs_s1 - abs_s0
        formatted = _format_to_width_preserve_space(v, width, orig_token=orig)
        new_chars[abs_s0:abs_s1] = list(formatted)

    xfint_idx = None
    for i, n in enumerate(param_names):
        if str(n).strip().upper() == "XFINT":
            xfint_idx = i
            break

    if xfint_idx is not None and xfint_idx < len(spans):
        abs_s0, abs_s1 = spans[xfint_idx]
        field = "".join(new_chars[abs_s0:abs_s1]).strip()
        try:
            xfint = float(field)
        except Exception:
            xfint = float("nan")

        if not math.isfinite(xfint):
            raise ValueError(f"Injected XFINT cannot be parsed after formatting: {xfint!r}")

        # Historical T9/P2 runs treated 0.12--0.50 as a numerical-safety
        # interval.  T10 deliberately freezes the scientific domain at
        # 0.08--0.50.  A value outside the former interval is useful failure
        # context, not a reason for the runner to delete a realization before
        # DSSAT has had a chance to evaluate it.
        if xfint < 0.12 or xfint > 0.50:
            print(
                "RUNNER_ADVISORY parameter=XFINT "
                f"value={xfint:g} historical_advisory_range=[0.12,0.50] "
                "action=continue_to_dssat",
                file=sys.stderr,
                flush=True,
            )

    lines[eco_idx] = "".join(new_chars) + "\n"
    lock_path = os.path.abspath(ECO_FILE) + ".lock"
    lock_err = _acquire_file_lock(lock_path, timeout_s=180.0, poll_s=0.10, stale_s=900.0)
    if lock_err is not None:
        raise lock_err
    try:
        last_err = _atomic_write_lines(ECO_FILE, lines, n_tries=60, sleep_s=0.20)
        if last_err is not None:
            raise last_err
    finally:
        _release_file_lock(lock_path)


def update_spe_file(param_csv_path=PARAM_CSV):
    if not os.path.exists(param_csv_path):
        raise FileNotFoundError(f"Parameter CSV not found: {param_csv_path}")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    spe_base_path = None
    env_spe_base = os.environ.get("DSSAT_SPE_BASE", "").strip()
    if env_spe_base and os.path.exists(env_spe_base):
        spe_base_path = os.path.abspath(env_spe_base)
    cand = os.path.join(script_dir, SPE_FILE + ".base")
    if spe_base_path:
        cand = None
    elif os.path.exists(cand):
        spe_base_path = cand
    else:
        local_base = SPE_FILE + ".base"
        if os.path.exists(local_base):
            spe_base_path = local_base
            cand = None
        else:
            cand = os.path.normpath(os.path.join(script_dir, "..", "..", "Genotype", SPE_FILE))
        if cand and os.path.exists(cand):
            spe_base_path = cand
        elif os.path.exists(SPE_FILE):
            spe_base_path = SPE_FILE

    if not spe_base_path:
        raise FileNotFoundError(f"Species base file not found: {SPE_FILE}.base")

    try:
        param_dict = _read_param_dict(param_csv_path)
    except Exception as e:
        raise RuntimeError(f"Could not read parameter CSV {param_csv_path}: {e}") from e
    if not param_dict:
        return

    base_names = ["TB", "TO1", "TO2", "TM"]
    stage_names = []
    for stage in (1, 2, 3):
        stage_names.extend([f"TB{stage}", f"TO1{stage}", f"TO2{stage}", f"TM{stage}"])

    direct_keys = [
        "PARMAX",
        "PHTMAX",
        "KCAN",
        "KC_SLOPE",
        "RNO3C",
        "RNH4C",
        "RPRO",
        "RFIXN",
        # Plant composition/N concentration parameters.  These are not
        # merely metadata: VEGGR uses the G-class values as the minimum
        # tissue-N gate and the I-class values as potential N demand.
        "PROLFI",
        "PROLFG",
        "PROLFF",
        "PROSTI",
        "PROSTG",
        "PROSTF",
        "PRORTI",
        "PRORTG",
        "PRORTF",
        "PROSHI",
        "PROSHG",
        "PROSHF",
        # Organ-composition parameters are deliberately explicit here.  They
        # must not depend on the legacy high-dimensional whitelist in the
        # calibration builder.
        "CMOBMX",
        "CADSTF",
        "CADPR1",
        "NMOBMX",
        "NVSMOB",
        "NRCVR",
        "NSTFAC",
        "NREXP",
        "NRMIN",
        "NUPK50",
        "NUPQ",
        "NUPCMN",
        "NUPAV",
        "FNPGN1",
        "FNPGN2",
        "FNPGN3",
        "FNPGN4",
        "SLWREF",
        "SLWSLO",
        "NSLOPE",
        "LNREF",
        "PGREF",
        "WTFSD",
        "PORPT",
        "FRSTMF",
        "FRLFF",
        "ATOP",
        "FRCNOD",
        "FINREF",
        "SLAREF",
        "SIZREF",
        "VSSINK",
        "EVMODC",
        "RTNO3",
        "RTNH4",
        "PORMIN",
        "RTEXF",
        "RTDEPI",
        "RFAC1",
        "RTSEN",
        "RLDSM",
        "RTSDF",
        "RWUEP1",
        "RWUMX",
        "SDPROS",
        "PCARSD",
        "XMPAGE",
        # Additional SPE fields used by the expanded sensitivity domain.
        "SENRTE",
        "SENDAY",
        "SETMAX",
        "SRMAX",
        "RFLWAB",
        "DSWBAR",
        "XFRMAX",
        "SHLAG",
        "SLAMAX",
        "SLAMIN",
        "TURSLA",
        "NSLA",
        "FRLFMX",
        "PGEFF",
        "KDIF",
        "LFANGB",
        "FNPGN1",
        "FNPGN2",
        "FNPGN3",
        "FNPGN4",
    ]
    anchor_keys = [
        "LAREA_EARLY",
        "LAREA_MID",
        "LAREA_LATE",
        "LEAF_PART_EARLY",
        "LEAF_PART_FLORAL",
        "LEAF_PART_LATE",
        "STEM_PART_EARLY",
        "STEM_PART_LATE",
        "SENPOR_LATE",
        "FNSDT_OPT1",
        "FNSDT_OPT2",
    ]

    keys = [k for k in (base_names + stage_names + direct_keys) if k in param_dict]
    if not keys and not any(k in param_dict for k in anchor_keys):
        return

    number_re = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[Ee][-+]?\d+)?")
    with open(spe_base_path, "r") as f:
        lines = f.readlines()

    def _find_line_index(contains_text):
        for j, s in enumerate(lines):
            if contains_text in s:
                return j
        return -1

    def _read_prefix_values(idx, count):
        if idx < 0 or idx >= len(lines):
            return []
        return [float(m.group(0)) for m in list(number_re.finditer(lines[idx]))[:count]]

    def _write_prefix_values(idx, values, count=None):
        if idx < 0 or idx >= len(lines):
            raise ValueError(f"line index out of range for SPE update: {idx}")
        s = lines[idx]
        matches = list(number_re.finditer(s))
        n_values = len(values) if count is None else count
        if len(matches) < n_values:
            raise ValueError(
                f"SPE line {idx + 1} has only {len(matches)} numeric fields; "
                f"expected at least {n_values}"
            )
        new_chars = list(s.rstrip("\n"))
        for value, m in zip(values, matches[:n_values]):
            orig = m.group(0)
            width = m.end() - m.start()
            formatted = _format_to_width(float(value), width, orig_token=orig)
            if len(formatted) != width:
                formatted = formatted[:width].rjust(width)
            new_chars[m.start() : m.end()] = list(formatted)
        lines[idx] = "".join(new_chars) + "\n"

    def _apply_anchor_expansions():
        yvref_idx = _find_line_index("YVREF(1-6)")
        if yvref_idx != -1 and any(
            key in param_dict for key in ("LAREA_EARLY", "LAREA_MID", "LAREA_LATE")
        ):
            current_yvref = _read_prefix_values(yvref_idx, 6)
            if len(current_yvref) < 6:
                raise ValueError("Could not read the 6-node YVREF array from the SPE template")
            expanded = expand_leaf_area(
                float(param_dict.get("LAREA_EARLY", current_yvref[0])),
                float(param_dict.get("LAREA_MID", current_yvref[3])),
                float(param_dict.get("LAREA_LATE", current_yvref[5])),
            )
            _write_prefix_values(yvref_idx, expanded.y_values, count=6)

        yleaf_idx = _find_line_index("YLEAF VALUES")
        ystem_idx = _find_line_index("YSTEM VALUES")
        yleaf_values = tuple(_read_prefix_values(yleaf_idx, 10))
        ystem_values = tuple(_read_prefix_values(ystem_idx, 10))
        update_leaf = yleaf_idx != -1 and any(
            key in param_dict
            for key in ("LEAF_PART_EARLY", "LEAF_PART_FLORAL", "LEAF_PART_LATE")
        )
        update_stem = ystem_idx != -1 and any(
            key in param_dict for key in ("STEM_PART_EARLY", "STEM_PART_LATE")
        )
        if update_leaf:
            if len(yleaf_values) < 10:
                raise ValueError("Could not read the 10-node YLEAF array from the SPE template")
            yleaf_values = expand_leaf_partition(
                float(param_dict.get("LEAF_PART_EARLY", yleaf_values[0])),
                float(param_dict.get("LEAF_PART_FLORAL", yleaf_values[4])),
                float(param_dict.get("LEAF_PART_LATE", yleaf_values[9])),
            ).y_values
        if update_stem:
            if len(ystem_values) < 10:
                raise ValueError("Could not read the 10-node YSTEM array from the SPE template")
            ystem_values = expand_stem_partition(
                float(param_dict.get("STEM_PART_EARLY", ystem_values[0])),
                float(param_dict.get("STEM_PART_LATE", ystem_values[9])),
            ).y_values
        if update_leaf or update_stem:
            violations = validate_partition_sum(yleaf_values, ystem_values)
            if violations:
                raise ValueError(
                    "Expanded leaf/stem partition anchors violate YLEAF + YSTEM <= 1 "
                    f"at nodes {violations}"
                )
            if update_leaf:
                _write_prefix_values(yleaf_idx, yleaf_values, count=10)
            if update_stem:
                _write_prefix_values(ystem_idx, ystem_values, count=10)

        senpor_marker_idx = _find_line_index("SENPOR.........")
        if senpor_marker_idx != -1 and "SENPOR_LATE" in param_dict:
            senpor_values_idx = senpor_marker_idx + 1
            current_senpor_line = _read_prefix_values(senpor_values_idx, 8)
            if len(current_senpor_line) < 8:
                raise ValueError("Could not read the SENPOR/SENMAX values from the SPE template")
            expanded = expand_senpor(float(param_dict["SENPOR_LATE"]))
            _write_prefix_values(
                senpor_values_idx,
                (*expanded.y_values, *current_senpor_line[4:8]),
                count=8,
            )

        fnsdt_idx = _find_line_index("FNSDT(1-4)")
        if fnsdt_idx != -1 and any(key in param_dict for key in ("FNSDT_OPT1", "FNSDT_OPT2")):
            current_fnsdt = _read_prefix_values(fnsdt_idx, 4)
            if len(current_fnsdt) < 4:
                raise ValueError("Could not read the 4-node FNSDT array from the SPE template")
            if "FNSDT_OPT1" in param_dict:
                current_fnsdt[1] = float(param_dict["FNSDT_OPT1"])
            if "FNSDT_OPT2" in param_dict:
                current_fnsdt[2] = float(param_dict["FNSDT_OPT2"])
            _write_prefix_values(fnsdt_idx, current_fnsdt, count=4)

    def _update_named_line(contains_text, param_order):
        if not contains_text or not param_order:
            return
        if not any((str(p).strip().upper() in param_dict) for p in param_order):
            return
        idx = _find_line_index(contains_text)
        if idx == -1:
            return
        values = _read_prefix_values(idx, len(param_order))
        if len(values) < len(param_order):
            return
        for pos, name in enumerate(param_order):
            key = str(name).strip().upper()
            if key in param_dict:
                values[pos] = float(param_dict[key])
        _write_prefix_values(idx, values, count=len(param_order))

    _apply_anchor_expansions()

    _update_named_line("PARMAX,PHTMAX", ["PARMAX", "PHTMAX", "KCAN", "KC_SLOPE"])
    _update_named_line("RNO3C,RNH4C", ["RNO3C", "RNH4C", "RPRO", "RFIXN"])
    _update_named_line(
        "PROLFI,PROLFG,PROLFF",
        ["PROLFI", "PROLFG", "PROLFF", "PROSTI", "PROSTG", "PROSTF"],
    )
    _update_named_line(
        "PRORTI,PRORTG,PRORTF",
        ["PRORTI", "PRORTG", "PRORTF", "PROSHI", "PROSHG", "PROSHF"],
    )
    _update_named_line("CMOBMX,CADSTF", ["CMOBMX", "CADSTF", "CADPR1", "NMOBMX", "NVSMOB", "NRCVR"])
    _update_named_line("SDPROS,SDPROG", ["SDPROS"])
    _update_named_line("PCARLF,PCARST", ["PCARSD"])
    _update_named_line("FNPGN(4)", ["FNPGN1", "FNPGN2", "FNPGN3", "FNPGN4"])
    _update_named_line("SLWREF,SLWSLO", ["SLWREF", "SLWSLO", "NSLOPE", "LNREF", "PGREF"])
    _update_named_line("WTFSD,PORPT", ["WTFSD", "PORPT", "FRSTMF", "FRLFF", "ATOP", "FRCNOD"])
    _update_named_line("FINREF,SLAREF", ["FINREF", "SLAREF", "SIZREF", "VSSINK", "EVMODC"])
    _update_named_line("RTDEPI,RFAC1", ["RTDEPI", "RFAC1", "RTSEN", "RLDSM", "RTSDF", "RWUEP1", "RWUMX"])
    _update_named_line("RTNO3,RTNH4", ["RTNO3", "RTNH4", "PORMIN", "RTEXF"])
    _update_named_line("SETMAX,SRMAX", ["SETMAX", "SRMAX", "RFLWAB", "XMPAGE"])
    _update_named_line("SENRTE,SENRT2", ["SENRTE", "_SENRT2", "SENDAY", "_FREEZ1", "_FREEZ2"])
    _update_named_line("SLAMAX,SLAMIN", ["SLAMAX", "SLAMIN", "_SLAPAR", "TURSLA", "NSLA"])
    _update_named_line("PGEFF SCV KDIF", ["PGEFF", "_SCV", "KDIF", "LFANGB"])
    _update_named_line("DSWBAR,XFRMAX", ["DSWBAR", "XFRMAX", "SHLAG"])
    _update_named_line("FRLFMX", ["FRLFMX"])

    # Last-resort label-driven injection.  This closes the whitelist gap for
    # newly added SPE fields whose static grouping has not yet been extended:
    # the comma-separated labels at the end of every SPE row are themselves a
    # machine-readable contract, so update the matching numeric slot exactly.
    for _key, _value in param_dict.items():
        _u = str(_key).strip().upper()
        if not _u:
            continue
        for _idx, _line in enumerate(lines):
            if _u not in _line.upper() or "," not in _line:
                continue
            _label_text = _line.rsplit(" ", 1)[-1].strip().upper()
            _labels = [x.strip() for x in _label_text.split(",")]
            if _u not in _labels:
                continue
            _matches = list(number_re.finditer(_line))
            _pos = _labels.index(_u)
            if _pos >= len(_matches):
                continue
            _m = _matches[_pos]
            _formatted = _format_to_width(float(_value), _m.end() - _m.start(), orig_token=_m.group(0))
            _chars = list(_line.rstrip("\n"))
            _chars[_m.start() : _m.end()] = list(_formatted)
            lines[_idx] = "".join(_chars) + "\n"
            break
    # XPODF was historically a one-field row (only NSTFAC).  The modified
    # executable extends it to three fields: NSTFAC, NREXP and NRMIN.  Map
    # these by their labels so the legacy one-field template and the extended
    # template are both written correctly.  In particular, do not use the
    # last numeric token for NSTFAC: on the extended row that token is NRMIN.
    for idx, line in enumerate(lines):
        upper = line.upper()
        marker = upper.find("XPODF")
        if marker < 0:
            continue
        label_text = line[marker:].split("!", 1)[0]
        if "," not in label_text:
            continue
        labels = [part.strip().upper() for part in label_text.split(",")]
        if labels:
            # XPODF is the section marker, not a numeric field.
            labels = labels[1:]
        if not labels:
            continue
        matches = list(number_re.finditer(line[:marker]))
        if not matches:
            continue
        changed = False
        new_chars = list(line.rstrip("\n"))
        for pos, label in enumerate(labels):
            if pos >= len(matches) or label not in param_dict:
                continue
            match = matches[pos]
            orig = match.group(0)
            width = match.end() - match.start()
            formatted = _format_to_width(float(param_dict[label]), width, orig_token=orig)
            if len(formatted) != width:
                formatted = formatted[:width].rjust(width)
            new_chars[match.start() : match.end()] = list(formatted)
            changed = True
        if changed:
            lines[idx] = "".join(new_chars) + "\n"
        break

    pheno_idx = -1
    for i, line in enumerate(lines):
        if line.strip().upper().startswith("!*PHENOLOGY PARAMETERS") or line.strip().upper().startswith("*PHENOLOGY PARAMETERS"):
            pheno_idx = i
            break

    if pheno_idx == -1:
        return

    def _stage_for_line(line):
        u = (line or "").upper()
        if "VEGETATIVE DEVELOPMENT" in u:
            return 1
        if "EARLY REPRODUCTIVE DEVELOPMENT" in u:
            return 2
        if "LATE REPRODUCTIVE DEVELOPMENT" in u:
            return 3
        return None

    def _param_key(base, stage):
        if stage is None:
            return base
        if base == "TB":
            return f"TB{stage}"
        if base == "TM":
            return f"TM{stage}"
        if base == "TO1":
            return f"TO1{stage}"
        if base == "TO2":
            return f"TO2{stage}"
        return base

    use_stage = any(k in param_dict for k in stage_names)

    for i in range(pheno_idx + 1, min(pheno_idx + 60, len(lines))):
        s = lines[i]
        if "DEVELOPMENT" not in s.upper():
            continue
        matches = list(number_re.finditer(s))
        if len(matches) < 4:
            continue

        stage = _stage_for_line(s) if use_stage else None
        new_chars = list(s.rstrip("\n"))
        for base, m in zip(base_names, matches[:4]):
            key = _param_key(base, stage)
            if key in param_dict:
                v = float(param_dict[key])
            elif base in param_dict:
                v = float(param_dict[base])
            else:
                continue
            orig = m.group(0)
            width = m.end() - m.start()
            formatted = _format_to_width(v, width, orig_token=orig)
            if len(formatted) != width:
                formatted = formatted[:width].rjust(width)
            new_chars[m.start() : m.end()] = list(formatted)
        lines[i] = "".join(new_chars) + "\n"

    lock_path = os.path.abspath(SPE_FILE) + ".lock"
    lock_err = _acquire_file_lock(lock_path, timeout_s=180.0, poll_s=0.10, stale_s=900.0)
    if lock_err is not None:
        raise lock_err
    try:
        last_err = _atomic_write_lines(SPE_FILE, lines, n_tries=60, sleep_s=0.20)
        if last_err is not None:
            raise last_err
    finally:
        _release_file_lock(lock_path)


def update_soil_file(param_csv_path=PARAM_CSV, batch_file=BATCH_FILE, soil_id=None):
    if os.environ.get("DSSAT_DISABLE_SOIL_INJECTION", "").strip().lower() in {"1", "true", "yes", "on"}:
        return
    if not os.path.exists(param_csv_path):
        return

    try:
        param_dict = _read_param_dict(param_csv_path)
    except Exception as e:
        raise RuntimeError(f"Could not read parameter CSV {param_csv_path}: {e}") from e
    if not param_dict:
        return

    soil_keys = [k for k in param_dict.keys() if str(k).strip().upper().startswith("SOIL_")]
    if not soil_keys:
        return

    cwd_script = os.path.dirname(os.path.abspath(__file__))
    filex_path = _resolve_filex_from_batch(batch_file, os.getcwd()) or _resolve_filex_from_batch(batch_file, cwd_script)
    if soil_id is None:
        soil_id = _infer_soil_id_from_filex(filex_path)
    soil_id = str(soil_id).strip() if soil_id else None
    if not soil_id:
        raise RuntimeError("Could not infer a soil profile ID for SOIL parameter injection")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    soil_base_path = None
    cand = os.path.join(script_dir, SOIL_BASE_FILE)
    if os.path.exists(cand):
        soil_base_path = cand
    else:
        if os.path.exists(SOIL_BASE_FILE):
            soil_base_path = SOIL_BASE_FILE
            cand2 = None
        else:
            cand2 = os.path.join(script_dir, SOIL_FILE)
        if cand2 and os.path.exists(cand2):
            soil_base_path = cand2
        elif os.path.exists(SOIL_FILE):
            soil_base_path = SOIL_FILE
        else:
            cand3 = os.path.normpath(os.path.join(script_dir, "..", "SOIL.SOL"))
            if os.path.exists(cand3):
                soil_base_path = cand3

    if not soil_base_path or (not os.path.exists(soil_base_path)):
        return

    with open(soil_base_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    def _as_layer_key(base, layer_idx_1):
        return f"SOIL_{base}_{int(layer_idx_1):02d}"

    def _recommended(x, lo, hi, *, name):
        try:
            v = float(x)
        except Exception:
            return None
        if not float(lo) <= v <= float(hi):
            _runner_advisory(
                f"parameter={name} value={v:g} safety_range=[{float(lo):g},{float(hi):g}] "
                "action=continue_to_dssat"
            )
        return v

    def _safe_water_triplet(slll, sdul, ssat):
        a = float(slll) if slll is not None else None
        b = float(sdul) if sdul is not None else None
        c = float(ssat) if ssat is not None else None
        if a is None or b is None or c is None:
            return a, b, c
        if not all(0.01 <= value <= 0.80 for value in (a, b, c)):
            _runner_advisory(
                "relation=SOIL_SLLL<SOIL_SDUL<SOIL_SSAT safety_range=[0.01,0.80] "
                "action=continue_to_dssat"
            )
        if not a < b < c:
            _runner_advisory(
                "relation=SOIL_SLLL<SOIL_SDUL<SOIL_SSAT action=continue_to_dssat"
            )
        return a, b, c

    sec_start = None
    for i, s in enumerate(lines):
        if s.startswith("*"):
            sid = s[1:].strip().split()[0] if s[1:].strip() else ""
            if sid.upper() == soil_id.upper():
                sec_start = i
                break
    if sec_start is None:
        return

    sec_end = len(lines)
    for j in range(sec_start + 1, len(lines)):
        if lines[j].startswith("*"):
            sec_end = j
            break

    scom_header_idx = None
    layer_header_idx = None
    for j in range(sec_start, sec_end):
        u = lines[j].strip().upper()
        if u.startswith("@") and "SCOM" in u and "SALB" in u:
            scom_header_idx = j
        if u.startswith("@") and "SLLL" in u and "SDUL" in u and "SSAT" in u:
            layer_header_idx = j

    if scom_header_idx is not None:
        # SCOM headers are whitespace-delimited labels, not fixed-column
        # fields.  Character spans inferred from the header can swallow the
        # intervening labels (SLU1/SLNF) and blank the remainder of the data
        # row, which stricter custom DSSAT builds reject as IPSOIL.  Replace
        # the numeric slots by semantic position instead.
        want = [("SALB", 0), ("SLDR", 2), ("SLRO", 3), ("SLPF", 5)]
        if (scom_header_idx + 1) < sec_end:
            data_idx = None
            for j in range(scom_header_idx + 1, sec_end):
                if not lines[j].strip():
                    continue
                if lines[j].lstrip().startswith("@") or lines[j].startswith("*"):
                    break
                data_idx = j
                break
            if data_idx is not None:
                s = lines[data_idx].rstrip("\n")
                matches = list(re.finditer(r"[-+]?\d*\.\d+|[-+]?\d+", s))
                replacements = []
                for name, pos in want:
                    key = f"SOIL_{name}"
                    if key not in param_dict:
                        continue
                    if pos >= len(matches):
                        continue
                    v = float(param_dict[key])
                    ranges = {"SALB": (0.05, 0.35), "SLDR": (0.01, 5.00), "SLRO": (1.0, 99.0), "SLPF": (0.0, 1.0)}
                    v2 = _recommended(v, *ranges[name], name=key) if name in ranges else v
                    if v2 is None:
                        continue
                    match = matches[pos]
                    orig = s[match.start() : match.end()]
                    width = len(orig)
                    formatted = _format_to_width_preserve_space(v2, width, orig_token=orig)
                    replacements.append((match.start(), match.end(), formatted))
                for start, end, formatted in sorted(replacements, key=lambda x: x[0], reverse=True):
                    s = s[:start] + formatted + s[end:]
                lines[data_idx] = s.rstrip() + "\n"

    if layer_header_idx is not None:
        header_cols = lines[layer_header_idx].split()
        if header_cols and header_cols[0] == "@":
            header_cols = header_cols[1:]
        want = ["SLLL", "SDUL", "SSAT", "SBDM", "SLOC", "SSKS", "SLCL", "SLSI"]
        col_pos = {k: header_cols.index(k) for k in want if k in header_cols}
        layer_lines = []
        for j in range(layer_header_idx + 1, sec_end):
            if not lines[j].strip():
                continue
            if lines[j].lstrip().startswith("@") or lines[j].startswith("*"):
                break
            layer_lines.append(j)

        for li, idx in enumerate(layer_lines, start=1):
            slll_key = _as_layer_key("SLLL", li)
            sdul_key = _as_layer_key("SDUL", li)
            ssat_key = _as_layer_key("SSAT", li)
            slll_in = float(param_dict[slll_key]) if slll_key in param_dict else None
            sdul_in = float(param_dict[sdul_key]) if sdul_key in param_dict else None
            ssat_in = float(param_dict[ssat_key]) if ssat_key in param_dict else None
            slll_v, sdul_v, ssat_v = _safe_water_triplet(slll_in, sdul_in, ssat_in)
            if slll_v is not None:
                param_dict[slll_key] = slll_v
            if sdul_v is not None:
                param_dict[sdul_key] = sdul_v
            if ssat_v is not None:
                param_dict[ssat_key] = ssat_v

            # Locate all source tokens once, then apply replacements from
            # right to left.  Re-scanning after every replacement is unsafe:
            # values with different widths shift subsequent regex matches and
            # can make a later soil field overwrite SCEC/SLNI/SLHW with
            # overflow stars (DSSAT then reports SOILDYN).
            s = lines[idx].rstrip("\n")
            matches = list(re.finditer(r"[-+]?\d*\.\d+|[-+]?\d+", s))
            replacements = []

            for name in ["SLLL", "SDUL", "SSAT", "SBDM", "SLOC", "SSKS", "SLCL", "SLSI"]:
                key = _as_layer_key(name, li)
                if key not in param_dict:
                    continue
                if name not in col_pos:
                    continue
                pos = int(col_pos[name])
                if pos < 0 or pos >= len(matches):
                    continue
                m = matches[pos]
                orig_tok = s[m.start() : m.end()]
                v = float(param_dict[key])
                if name in {"SLLL", "SDUL", "SSAT"}:
                    v2 = _recommended(v, 0.01, 0.80, name=key)
                    if v2 is None:
                        continue
                    # Preserve the DSSAT token width/notation.  A fixed
                    # ``.3f`` string would be truncated into e.g. ``456``
                    # when the source token is ``.49`` (width 3), turning
                    # SAT/DUL into invalid values and making DSSAT abort.
                    new_tok = _format_to_width(v2, len(orig_tok), orig_token=orig_tok)
                elif name == "SBDM":
                    v2 = _recommended(v, 0.5, 2.2, name=key)
                    if v2 is None:
                        continue
                    new_tok = _format_to_width(v2, len(orig_tok), orig_token=orig_tok)
                elif name == "SLOC":
                    v2 = _recommended(v, 0.0, 10.0, name=key)
                    if v2 is None:
                        continue
                    new_tok = _format_to_width(v2, len(orig_tok), orig_token=orig_tok)
                elif name == "SSKS":
                    # Saturated hydraulic conductivity (cm/h); allow 0-100
                    v2 = _recommended(v, 0.0, 100.0, name=key)
                    if v2 is None:
                        continue
                    new_tok = _format_to_width(v2, len(orig_tok), orig_token=orig_tok)
                elif name in ("SLCL", "SLSI"):
                    # Clay/silt percentage (0-100); only inject if source is
                    # not -99 (missing) to avoid overwriting unmeasured layers
                    if orig_tok.strip() == "-99":
                        continue
                    v2 = _recommended(v, 0.0, 100.0, name=key)
                    if v2 is None:
                        continue
                    new_tok = _format_to_width(v2, len(orig_tok), orig_token=orig_tok)
                else:
                    new_tok = str(v)

                if len(new_tok) <= len(orig_tok):
                    new_tok = new_tok.rjust(len(orig_tok))
                else:
                    new_tok = new_tok[-len(orig_tok) :]

                replacements.append((m.start(), m.end(), new_tok))

            for start, end, new_tok in sorted(replacements, key=lambda x: x[0], reverse=True):
                s = s[:start] + new_tok + s[end:]

            lines[idx] = s + "\n"

    lock_path = os.path.abspath(SOIL_FILE) + ".lock"
    lock_err = _acquire_file_lock(lock_path, timeout_s=180.0, poll_s=0.10, stale_s=900.0)
    if lock_err is not None:
        raise lock_err
    try:
        last_err = _atomic_write_lines(SOIL_FILE, lines, n_tries=60, sleep_s=0.20)
        if last_err is not None:
            raise last_err
    finally:
        _release_file_lock(lock_path)


def update_initial_conditions_file(param_csv_path=PARAM_CSV, batch_file=BATCH_FILE, filex_path=None):
    if not os.path.exists(param_csv_path):
        return

    try:
        param_dict = _read_param_dict(param_csv_path)
    except Exception as e:
        raise RuntimeError(f"Could not read parameter CSV {param_csv_path}: {e}") from e
    if not param_dict:
        return

    ic_keys = [k for k in param_dict.keys() if str(k).strip().upper().startswith("IC_SH2O_")]
    if not ic_keys:
        return

    cwd_script = os.path.dirname(os.path.abspath(__file__))
    if not filex_path:
        filex_path = _resolve_filex_from_batch(batch_file, os.getcwd()) or _resolve_filex_from_batch(batch_file, cwd_script)
    if not filex_path or not os.path.exists(filex_path):
        raise FileNotFoundError("Experiment file for initial-condition injection was not found")

    with open(filex_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    ic_start = None
    ic_end = None
    for i, line in enumerate(lines):
        u = line.strip().upper()
        if u.startswith("*INITIAL CONDITIONS"):
            ic_start = i
            continue
        if ic_start is not None and u.startswith("*") and (not u.startswith("*INITIAL CONDITIONS")):
            ic_end = i
            break
    if ic_start is None:
        return
    if ic_end is None:
        ic_end = len(lines)

    header_idx = None
    for j in range(ic_start + 1, ic_end):
        u = lines[j].strip().upper()
        if lines[j].lstrip().startswith("@C") and ("ICBL" in u) and ("SH2O" in u):
            header_idx = j
            break
    if header_idx is None:
        return

    def _is_valid_yyddd(tok):
        try:
            v = int(float(tok))
        except Exception:
            return False
        return 10000 <= v <= 99999

    default_icdat = None
    pcr_in_table = False
    pcr_cols = None
    pcr_icdat_col = None

    layer_idx = 0
    in_sh2o_table = False
    sh2o_col = None
    header_cols = None

    for j in range(ic_start + 1, ic_end):
        s = lines[j].rstrip("\n")
        u = s.strip().upper()
        if not u:
            continue

        if u.startswith("*") and (not u.startswith("*INITIAL CONDITIONS")):
            break

        if s.lstrip().startswith("@C") and ("PCR" in u) and ("ICDAT" in u):
            in_sh2o_table = False
            sh2o_col = None
            header_cols = None
            layer_idx = 0
            pcr_cols = s.split()
            pcr_icdat_col = None
            try:
                pcr_icdat_col = pcr_cols.index("ICDAT")
            except ValueError:
                pcr_icdat_col = None
            pcr_in_table = pcr_icdat_col is not None
            continue

        if s.lstrip().startswith("@C") and ("ICBL" in u) and ("SH2O" in u):
            pcr_in_table = False
            pcr_cols = None
            pcr_icdat_col = None
            header_cols = s.split()
            sh2o_col = None
            try:
                sh2o_col = header_cols.index("SH2O")
            except ValueError:
                sh2o_col = None
            in_sh2o_table = sh2o_col is not None
            layer_idx = 0
            continue

        if s.lstrip().startswith("@"):
            pcr_in_table = False
            pcr_cols = None
            pcr_icdat_col = None
            in_sh2o_table = False
            sh2o_col = None
            header_cols = None
            layer_idx = 0
            continue

        if pcr_in_table and pcr_cols and (pcr_icdat_col is not None):
            parts = s.split()
            if len(parts) < 2:
                continue
            if len(parts) < len(pcr_cols):
                parts += ["-99"] * (len(pcr_cols) - len(parts))

            icdat_tok = parts[pcr_icdat_col]
            if default_icdat is None and _is_valid_yyddd(icdat_tok):
                default_icdat = icdat_tok
                continue

            if default_icdat is None:
                continue
            if _is_valid_yyddd(icdat_tok) or (icdat_tok == "-99"):
                continue

            data_offset = 1 if (pcr_cols and str(pcr_cols[0]).upper() == "@C") else 0
            icdat_pos = int(pcr_icdat_col) - data_offset
            matches = list(re.finditer(r"[-+]?\d*\.\d+|[-+]?\d+", s))
            if icdat_pos < 0 or icdat_pos >= len(matches):
                continue
            m = matches[icdat_pos]
            orig_tok = s[m.start() : m.end()]
            new_tok = str(default_icdat)
            if len(new_tok) <= len(orig_tok):
                new_tok = new_tok.rjust(len(orig_tok))
            else:
                new_tok = new_tok[-len(orig_tok) :]
            lines[j] = (s[: m.start()] + new_tok + s[m.end() :] + "\n")
            continue

        if not in_sh2o_table or sh2o_col is None or not header_cols:
            continue

        parts = s.split()
        if len(parts) < 2:
            continue
        if len(parts) < len(header_cols):
            parts += ["-99"] * (len(header_cols) - len(parts))

        layer_idx += 1
        key = f"IC_SH2O_{layer_idx:02d}"
        if key not in param_dict:
            continue
        try:
            v = float(param_dict[key])
        except Exception:
            continue
        if not 0.01 <= v <= 0.80:
            _runner_advisory(
                f"parameter={key} value={v:g} safety_range=[0.01,0.80] action=continue_to_dssat"
            )
        parts[sh2o_col] = f"{v:.3f}"
        lines[j] = " ".join(parts).rstrip() + "\n"

    lock_path = os.path.abspath(filex_path) + ".lock"
    lock_err = _acquire_file_lock(lock_path, timeout_s=180.0, poll_s=0.10, stale_s=900.0)
    if lock_err is not None:
        raise lock_err
    try:
        last_err = _atomic_write_lines(filex_path, lines, n_tries=60, sleep_s=0.20)
        if last_err is not None:
            raise last_err
    finally:
        _release_file_lock(lock_path)


def _initial_n_key(prefix, excode, treatment, layer):
    return f"{prefix}_{str(excode).strip().upper()}_TN{int(treatment):02d}_L{int(layer):02d}"


def update_initial_soil_n_file(param_csv_path=PARAM_CSV, filex_path=None):
    """Inject treatment/layer-specific SNH4 and SNO3 parameters into FileX."""
    if not os.path.exists(param_csv_path) or not filex_path or not os.path.exists(filex_path):
        return
    param_dict = _read_param_dict(param_csv_path)
    if not any(k.startswith("IC_SNH4_") or k.startswith("IC_SNO3_") for k in param_dict):
        return

    with open(filex_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    excode = os.path.splitext(os.path.basename(filex_path))[0].upper()
    ic_start = None
    ic_end = None
    for i, line in enumerate(lines):
        u = line.strip().upper()
        if u.startswith("*INITIAL CONDITIONS"):
            ic_start = i
            continue
        if ic_start is not None and u.startswith("*") and not u.startswith("*INITIAL CONDITIONS"):
            ic_end = i
            break
    if ic_start is None:
        return
    if ic_end is None:
        ic_end = len(lines)

    current_tn = None
    table_cols = None
    in_layer_table = False
    layer_by_tn = {}
    modified = False
    for i in range(ic_start + 1, ic_end):
        s = lines[i].rstrip("\n")
        u = s.strip().upper()
        if not u:
            continue
        if s.lstrip().startswith("@C") and "PCR" in u and "ICDAT" in u:
            table_cols = None
            in_layer_table = False
            continue
        if s.lstrip().startswith("@C") and "ICBL" in u and "SNH4" in u and "SNO3" in u:
            table_cols = s.split()[1:]
            in_layer_table = True
            continue
        if s.lstrip().startswith("@"):
            table_cols = None
            in_layer_table = False
            continue
        parts = s.split()
        if table_cols is None:
            # PCR data rows carry the treatment/ICNAME in the first column.
            if parts:
                try:
                    current_tn = int(float(parts[0]))
                    layer_by_tn[current_tn] = 0
                except ValueError:
                    current_tn = None
            continue
        if not in_layer_table or current_tn is None:
            continue
        layer_by_tn[current_tn] = layer_by_tn.get(current_tn, 0) + 1
        layer = layer_by_tn[current_tn]
        # Reconstruct the complete IC row before changing N.  The audited
        # layer-mean bundles contain several legacy layouts, including rows
        # where depth is attached to SH2O or SH2O/SNH4/SNO3 touch each other.
        # Indexing ``parts`` in those rows can silently join the N fields and
        # leaves DSSAT to report IPSLIN/SOILDYN.  The treatment and depth
        # prefix is stable; the remaining numeric tokens are the three
        # semantic fields.
        snh4_key = _initial_n_key("IC_SNH4", excode, current_tn, layer)
        sno3_key = _initial_n_key("IC_SNO3", excode, current_tn, layer)
        if snh4_key not in param_dict and sno3_key not in param_dict:
            continue
        try:
            prefix_match = re.match(r"^\s*(\d+)\s+(\d+)", s)
            if prefix_match:
                depth = int(prefix_match.group(2))
                tail = s[prefix_match.end() :]
                semantic = re.findall(r"[-+]?\d*\.?\d+", tail)
            else:
                depth = int(float(parts[1]))
                semantic = parts[2:]
            if len(semantic) < 3:
                raise ValueError("incomplete IC layer row")
            sh2o_token, snh4_token, sno3_token = semantic[:3]

            def _fit_ic_field(value):
                token = f"{float(value):.5g}"
                if len(token) > 6:
                    token = f"{float(value):.4g}"
                if len(token) > 6:
                    raise ValueError(f"initial-condition value does not fit FileX field: {value}")
                return token

            if snh4_key in param_dict:
                snh4_token = _fit_ic_field(param_dict[snh4_key])
            if sno3_key in param_dict:
                sno3_token = _fit_ic_field(param_dict[sno3_key])
            lines[i] = (
                f"{current_tn:3d}{depth:6d}"
                f"{_fit_ic_field(sh2o_token).rjust(6)}"
                f"{_fit_ic_field(snh4_token).rjust(6)}"
                f"{_fit_ic_field(sno3_token).rjust(6)}\n"
            )
            modified = True
        except (TypeError, ValueError, IndexError):
            continue
        continue

        try:
            snh4_idx = 1 + table_cols.index("SNH4")
            sno3_idx = 1 + table_cols.index("SNO3")
        except ValueError:
            continue
        if len(parts) < len(table_cols) + 1:
            # Audited layer-mean FileX rows use DSSAT fixed-width fields and
            # may contain no whitespace between SH2O and SNH4 (e.g.
            # ``.2121.7583``).  Rebuild the row in the same fixed-width layout
            # as the audited bundle generator.  Do not write a whitespace-
            # delimited row here: DSSAT's legacy FileX reader can interpret the
            # adjacent decimal fields as one number and report IPSLAN/IPSLIN.
            if len(parts) < 2 or len(s) < 20:
                continue
            # The first two fields are stable (treatment width 3, depth width
            # 6), but the three numeric values can overflow their nominal six-
            # character fields and become adjacent (e.g. ``.2121.7583``).
            # Parse the semantic numeric tokens after that stable prefix, then
            # render every field back into the canonical 3/6/6/6/6 layout.
            depth = 20 * layer
            sh2o_token = None
            snh4_token = None
            sno3_token = None
            if len(s) >= 9:
                try:
                    fixed_tn = int(s[0:3])
                    fixed_depth = int(s[3:9])
                    tail_values = re.findall(r"[-+]?\d*\.\d+|[-+]?\d+", s[9:])
                    if fixed_tn == current_tn and fixed_depth > 0 and tail_values:
                        depth = fixed_depth
                        # The legacy rows are sometimes whitespace-collapsed,
                        # so the nominal fixed spans can cut through a token
                        # (e.g. ``.2121.7583 35.15`` gives ``7583 3`` in a
                        # six-character slice).  When the stable TN/depth
                        # prefix is valid, the first three numeric tokens in
                        # the tail are the semantic SH2O/SNH4/SNO3 fields.
                        # This also avoids reducing a touching value such as
                        # ``3.232.025`` to the suffix ``.025``.
                        sh2o_token = tail_values[0]
                        snh4_token = tail_values[1] if len(tail_values) > 1 else "0"
                        sno3_token = tail_values[2] if len(tail_values) > 2 else "0"
                except (TypeError, ValueError):
                    pass
            if sh2o_token is None:
                raw_depth = parts[1]
                depth_text = str(depth)
                if raw_depth.startswith(depth_text) and raw_depth != depth_text:
                    remainder = raw_depth[len(depth_text):]
                    sh2o_token = remainder if remainder.startswith(".") else f".{remainder}"
                    n_source = parts[2:]
                else:
                    numeric = re.findall(r"[-+]?\d*\.\d+|[-+]?\d+", " ".join(parts[2:]))
                    sh2o_token = numeric[0] if numeric else ".190"
                    n_source = numeric[1:] if len(numeric) > 1 else []
                snh4_token = n_source[0] if n_source else "0"
                sno3_token = n_source[1] if len(n_source) > 1 else "0"

            def _fixed_n_token(value, fallback):
                token = fallback if value is None else f"{float(value):.5g}"
                if len(token) > 6:
                    token = f"{float(token):.4g}"
                if len(token) > 6:
                    raise ValueError(f"initial soil-N value does not fit FileX field: {value}")
                return token

            # Keep every fixed-width field within six characters.  A few
            # layer-mean SH2O anchors contain seven characters (for example
            # ``.296581``); retaining all digits would shift SNH4/SNO3 and
            # make DSSAT read the wrong columns.
            sh2o_token = _fixed_n_token(None, sh2o_token)
            snh4_token = _fixed_n_token(None, snh4_token)
            sno3_token = _fixed_n_token(None, sno3_token)

            changed_fixed = False
            for prefix, fallback, token in (
                ("IC_SNH4", snh4_token, "SNH4"),
                ("IC_SNO3", sno3_token, "SNO3"),
            ):
                key = _initial_n_key(prefix, excode, current_tn, layer)
                if key not in param_dict:
                    continue
                try:
                    new_value = float(param_dict[key])
                except (TypeError, ValueError):
                    continue
                if token == "SNH4":
                    snh4_token = _fixed_n_token(new_value, fallback)
                else:
                    sno3_token = _fixed_n_token(new_value, fallback)
                changed_fixed = True
            if changed_fixed:
                lines[i] = (
                    f"{current_tn:3d}{depth:6d}"
                    f"{str(sh2o_token).rjust(6)}"
                    f"{str(snh4_token).rjust(6)}"
                    f"{str(sno3_token).rjust(6)}\n"
                )
                modified = True
            continue
        for idx, prefix in ((snh4_idx, "IC_SNH4"), (sno3_idx, "IC_SNO3")):
            key = _initial_n_key(prefix, excode, current_tn, layer)
            if key not in param_dict:
                continue
            try:
                value = float(param_dict[key])
            except (TypeError, ValueError):
                continue
            parts[idx] = f"{value:.6g}"
            modified = True
        try:
            # The normal-looking user rows still need the same fixed-width
            # serialization as legacy layer-mean rows.  DSSAT may accept the
            # former when no injection occurs, but its IPSLIN reader is not
            # reliable after a whitespace-joined rewrite (notably at the
            # deepest 26SP layer).
            def _fit_normal_field(token):
                rendered = f"{float(token):.5g}"
                if rendered.startswith("0."):
                    rendered = rendered[1:]
                elif rendered.startswith("-0."):
                    rendered = "-." + rendered[3:]
                if len(rendered) > 6:
                    rendered = f"{float(token):.4g}"
                    if rendered.startswith("0."):
                        rendered = rendered[1:]
                    elif rendered.startswith("-0."):
                        rendered = "-." + rendered[3:]
                if len(rendered) > 6:
                    raise ValueError(f"initial soil-N value does not fit FileX field: {token}")
                return rendered.rjust(6)

            lines[i] = (
                f"{int(float(parts[0])):3d}{int(float(parts[1])):6d}"
                f"{_fit_normal_field(parts[2])}"
                f"{_fit_normal_field(parts[3])}"
                f"{_fit_normal_field(parts[4])}\n"
            )
        except (IndexError, TypeError, ValueError):
            lines[i] = " ".join(parts).rstrip() + "\n"

    if not modified:
        return
    lock_path = os.path.abspath(filex_path) + ".lock"
    lock_err = _acquire_file_lock(lock_path, timeout_s=180.0, poll_s=0.10, stale_s=900.0)
    if lock_err is not None:
        raise lock_err
    try:
        last_err = _atomic_write_lines(filex_path, lines, n_tries=60, sleep_s=0.20)
        if last_err is not None:
            raise last_err
    finally:
        _release_file_lock(lock_path)


def update_soil_analysis_n_file(param_csv_path=PARAM_CSV, filex_path=None):
    """Inject treatment/layer-specific SANI values into FileX soil analysis."""
    if not os.path.exists(param_csv_path) or not filex_path or not os.path.exists(filex_path):
        return
    param_dict = _read_param_dict(param_csv_path)
    if not any(k.startswith("SA_SANI_") for k in param_dict):
        return

    with open(filex_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    excode = os.path.splitext(os.path.basename(filex_path))[0].upper()
    section_start = None
    section_end = None
    for i, line in enumerate(lines):
        u = line.strip().upper()
        if u.startswith("*SOIL ANALYSIS"):
            section_start = i
            continue
        if section_start is not None and u.startswith("*") and not u.startswith("*SOIL ANALYSIS"):
            section_end = i
            break
    if section_start is None:
        return
    if section_end is None:
        section_end = len(lines)

    mode = None
    current_tn = None
    layer = 0
    table_cols = None
    modified = False
    for i in range(section_start + 1, section_end):
        s = lines[i].rstrip("\n")
        u = s.strip().upper()
        if not u:
            continue
        if s.lstrip().startswith("@A") and "SADAT" in u:
            mode = "meta"
            table_cols = None
            continue
        if s.lstrip().startswith("@A") and "SABL" in u and "SANI" in u:
            mode = "layer"
            table_cols = s.split()[1:]
            layer = 0
            continue
        if s.lstrip().startswith("@"):
            mode = None
            table_cols = None
            continue
        parts = s.split()
        if mode == "meta" and parts:
            try:
                current_tn = int(float(parts[0]))
            except ValueError:
                current_tn = None
            mode = None
            layer = 0
            continue
        if mode != "layer" or current_tn is None or not table_cols:
            continue
        sani_header_idx = next((j for j, name in enumerate(table_cols) if name == "SANI"), None)
        if sani_header_idx is None or len(parts) <= sani_header_idx + 1:
            continue
        layer += 1
        key = _initial_n_key("SA_SANI", excode, current_tn, layer)
        if key not in param_dict:
            continue
        try:
            value = float(param_dict[key])
        except (TypeError, ValueError):
            continue
        # SANI is embedded in a fixed-width soil-analysis row.  Six
        # significant digits can produce a seven-character token such as
        # ``.336723`` and shift SAPHW/SAPHB/SAPX, which DSSAT later reports as
        # a SOILDYN format error.  Keep the injected token within six chars.
        numeric = list(re.finditer(r"[-+]?\d*\.?\d+", s))
        numeric_idx = sani_header_idx + 1
        if numeric_idx >= len(numeric):
            continue
        match = numeric[numeric_idx]
        # Preserve the source field width as well as the <=6-character
        # maximum.  Replacing ``.11`` with ``.2271`` in-place shifts all
        # following SANI columns and causes DSSAT to report IPSLAN even though
        # the numeric value itself is valid.
        orig_token = s[match.start() : match.end()]
        sani_token = _format_to_width(value, len(orig_token), orig_token=orig_token)
        if len(sani_token) != len(orig_token) or "*" in sani_token:
            raise ValueError(f"SANI value does not fit source FileX field: {value}")
        lines[i] = s[: match.start()] + sani_token + s[match.end() :] + "\n"
        modified = True

    if not modified:
        return
    lock_path = os.path.abspath(filex_path) + ".lock"
    lock_err = _acquire_file_lock(lock_path, timeout_s=180.0, poll_s=0.10, stale_s=900.0)
    if lock_err is not None:
        raise lock_err
    try:
        last_err = _atomic_write_lines(filex_path, lines, n_tries=60, sleep_s=0.20)
        if last_err is not None:
            raise last_err
    finally:
        _release_file_lock(lock_path)

def _assert_fresh_nonempty(path, started_at, *, tolerance_seconds=2.0):
    """Reject missing, empty, or pre-existing outputs after a model run."""
    if not os.path.isfile(path):
        raise RuntimeError(f"Required DSSAT output was not produced: {path}")
    if os.path.getsize(path) <= 0:
        raise RuntimeError(f"Required DSSAT output is empty: {path}")
    modified = os.path.getmtime(path)
    if modified < float(started_at) - float(tolerance_seconds):
        raise RuntimeError(
            f"Required DSSAT output is stale: {path} "
            f"(mtime={modified:.3f}, run_started={started_at:.3f})"
        )


def run_model():
    """Runs the DSSAT model."""
    global BATCH_FILE
    print(f"Running {DSSAT_EXE} B {BATCH_FILE}...")
    
    try:
        cwd_script = os.path.dirname(os.path.abspath(__file__))
        run_dir = os.getcwd()
        filex_candidates = [
            _resolve_filex_from_batch(BATCH_FILE, run_dir),
            _resolve_filex_from_batch(BATCH_FILE, cwd_script),
        ]
        filex_path = next((path for path in filex_candidates if path and os.path.exists(path)), None)
        if filex_path is None:
            raise FileNotFoundError(f"Experiment file referenced by {BATCH_FILE} was not found")

        cleanup(run_dir, keep_dssat_outputs=False)

        exe_path = shutil.which(DSSAT_EXE)
        if not exe_path:
            candidate = os.path.normpath(os.path.join(cwd_script, "..", "..", DSSAT_EXE))
            if os.path.exists(candidate):
                exe_path = candidate
            else:
                workspace_candidate = os.path.join(run_dir, DSSAT_EXE)
                if os.path.exists(workspace_candidate):
                    exe_path = workspace_candidate
                else:
                    exe_path = DSSAT_EXE

        dssat_root = os.path.normpath(os.path.join(cwd_script, "..", ".."))
        local_dssatpro = os.path.join(run_dir, "DSSATPRO.v48")
        dssatpro_src = local_dssatpro if os.path.exists(local_dssatpro) else os.path.join(dssat_root, "DSSATPRO.v48")
        dssatpro_dst = os.path.join(run_dir, "DSSATPRO.v48")
        wrote_dssatpro = False
        try:
            if os.path.exists(dssatpro_src):
                wrote_dssatpro = _write_dssatpro_with_crd(dssatpro_src, dssatpro_dst, run_dir)
        except Exception:
            wrote_dssatpro = False

        if not wrote_dssatpro:
            try:
                if os.path.exists(dssatpro_src):
                    shutil.copy(dssatpro_src, dssatpro_dst)
            except Exception:
                pass

        localized_filex = _localize_experiment_files(filex_path, run_dir)
        active_filex = localized_filex or filex_path
        update_initial_conditions_file(param_csv_path=PARAM_CSV, batch_file=BATCH_FILE, filex_path=active_filex)
        update_initial_soil_n_file(
            param_csv_path=PARAM_CSV,
            filex_path=active_filex,
        )
        update_soil_analysis_n_file(
            param_csv_path=PARAM_CSV,
            filex_path=active_filex,
        )
        # update_* functions intentionally preserve source line layout.  Apply
        # the FileX boundary normalization once more after all injections so
        # a wrapper-staged file cannot reintroduce the IPSLIN blank-line case.
        _normalize_filex_initial_conditions_boundary(active_filex)

        batch_src = _resolve_batch_path(BATCH_FILE, base_dir=run_dir) or _resolve_batch_path(BATCH_FILE, base_dir=cwd_script)

        batch_dst_name = os.path.basename(BATCH_FILE) if BATCH_FILE else "DSSBatch.v48"
        if not batch_dst_name:
            batch_dst_name = "DSSBatch.v48"
        batch_dst = os.path.join(run_dir, batch_dst_name)
        try:
            if batch_src:
                if localized_filex:
                    wrote = _write_local_batch(batch_src, batch_dst, os.path.basename(localized_filex))
                    if not wrote:
                        shutil.copy(batch_src, batch_dst)
                else:
                    shutil.copy(batch_src, batch_dst)
        except Exception:
            pass

        BATCH_FILE = batch_dst

        batch_arg = batch_dst_name
        
        start_time = time.time()

        # Run DSSAT
        # Note: DSCSM048.EXE takes an optional model code (e.g. CRGRO048) before
        # the run-mode code (B) and batch file. It must be run in the directory
        # containing the files.
        dssat_args = [exe_path]
        if DSSAT_MODEL:
            dssat_args.append(DSSAT_MODEL)
        dssat_args.extend(["B", batch_arg])
        result = subprocess.run(
            dssat_args,
            cwd=run_dir,
            input="\n" * 8,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        
        end_time = time.time()
        print(f"Model run completed in {end_time - start_time:.2f} seconds.")
        
        if result.returncode != 0:
            handle_failure(result.returncode)
            raise RuntimeError(
                f"DSSAT exited with {result.returncode}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        else:
            orig_cwd = os.getcwd()
            try:
                os.chdir(run_dir)
                extra_outputs = ["Evaluate.OUT"]
                if KEEP_NITROGEN_OUTPUTS:
                    extra_outputs.extend(["PlantN.OUT", "SoilNi.OUT", "SoilN.OUT"])
                _sync_outputs_from_filex_dir(BATCH_FILE, run_dir, OUTPUT_FILES + extra_outputs, dest_dir=run_dir)

                _assert_fresh_nonempty("Evaluate.OUT", start_time)

                print("Evaluate.OUT generated successfully.")
                try:
                    _write_pest_eval_from_evaluate("Evaluate.OUT", _eval_pest_file())
                except Exception as e:
                    print(f"Warning: failed to write {_eval_pest_file()}: {e}")
                try:
                    _write_pest_grow_from_evaluate("Evaluate.OUT", _pest_path(PEST_GROW_FILE))
                except Exception as e:
                    print(f"Warning: failed to write {_pest_path(PEST_GROW_FILE)}: {e}")
                try:
                    _write_pest_joint_from_evaluate("Evaluate.OUT", _joint_pest_file())
                except Exception as e:
                    print(f"Warning: failed to write {_joint_pest_file()}: {e}")
                try:
                    _write_pest_harvest_from_tmt_and_freshwt(
                        BATCH_FILE,
                        "FreshWt.OUT",
                        _harvest_pest_file(),
                        harvest_var=HARVEST_VAR,
                    )
                except Exception as e:
                    print(f"Warning: failed to write {_harvest_pest_file()}: {e}")
                try:
                    _write_pest_tmtgrow_from_tmt_and_plantgro(
                        BATCH_FILE, "PlantGro.OUT", _tmtgrow_pest_file(), plantn_path="PlantN.OUT"
                    )
                except Exception as e:
                    print(f"Warning: failed to write {_tmtgrow_pest_file()}: {e}")
                if os.path.isfile("soil_water_observations.csv"):
                    try:
                        _write_pest_soilwat_from_soilwat(
                            BATCH_FILE, "SoilWat.OUT", _pest_path(PEST_SOILWAT_FILE),
                            "soil_water_observations.csv",
                        )
                    except Exception as e:
                        print(f"Warning: failed to write {_pest_path(PEST_SOILWAT_FILE)}: {e}")
                if OBSERVATION_TRANSFORM_CONFIG:
                    config_path = OBSERVATION_TRANSFORM_CONFIG
                    if not os.path.isabs(config_path):
                        config_path = os.path.join(run_dir, config_path)
                    apply_transform_config(config_path, _get_pest_out_dir())
                    print(f"Applied audited observation transforms from {config_path}.")
            finally:
                try:
                    os.chdir(orig_cwd)
                except Exception:
                    pass

            cleanup(
                run_dir, keep_dssat_outputs=True, keep_soil_water=KEEP_SOIL_WATER,
                keep_nitrogen_outputs=KEEP_NITROGEN_OUTPUTS,
            )

    except Exception as e:
        print(f"Exception running model: {e}")
        handle_failure(998)
        raise

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inject parameters and run DSSAT in the current directory")
    parser.add_argument("--param-csv", default=PARAM_CSV)
    parser.add_argument("--batch", default=BATCH_FILE)
    parser.add_argument("--cultivar", default=None)
    parser.add_argument("--harvest-var", default="CHPDT")
    parser.add_argument("--model", default=None,
                        help="Explicit CSM model code passed to DSCSM048 (e.g. CRGRO048). "
                             "When omitted, DSSAT infers the model from $BATCH / DSSATPRO.")
    parser.add_argument("--observation-transform-config", default=None)
    parser.add_argument("--keep-soil-water", action="store_true",
                        help="Keep SoilWat.OUT after run (needed for SOIL_WATER Phi).")
    parser.add_argument("--keep-nitrogen-outputs", action="store_true",
                        help="Keep PlantN.OUT/SoilNi.OUT for nitrogen engineering gates.")
    args, _ = parser.parse_known_args()

    BATCH_FILE = args.batch
    PARAM_CSV = args.param_csv
    HARVEST_VAR = (args.harvest_var or "CHPDT").strip().upper()
    DSSAT_MODEL = (args.model or None)
    OBSERVATION_TRANSFORM_CONFIG = args.observation_transform_config
    KEEP_SOIL_WATER = bool(args.keep_soil_water)
    KEEP_NITROGEN_OUTPUTS = bool(args.keep_nitrogen_outputs)

    candidate_parameters = _read_param_dict(PARAM_CSV)
    validate_candidate_parameters(candidate_parameters)

    cwd_script = os.path.dirname(os.path.abspath(__file__))

    cultivar = args.cultivar
    if not cultivar:
        filex = _resolve_filex_from_batch(BATCH_FILE, os.getcwd())
        if not (filex and os.path.exists(filex)):
            cwd_script = os.path.dirname(os.path.abspath(__file__))
            filex = _resolve_filex_from_batch(BATCH_FILE, cwd_script)
        cultivar = _infer_cultivar_from_filex(filex)
    if not cultivar:
        cultivar = "TM0001"

    run_dir = os.getcwd()
    if os.path.normcase(os.path.abspath(run_dir)) == os.path.normcase(os.path.abspath(cwd_script)):
        cleanup(cwd_script, keep_dssat_outputs=False)
    update_cul_file(param_csv_path=args.param_csv, target_cultivar=cultivar)
    ecotype = _infer_ecotype_from_cul(CUL_FILE, cultivar) or "TM0001"
    update_eco_file(param_csv_path=args.param_csv, target_ecotype=ecotype)
    update_spe_file(param_csv_path=args.param_csv)
    update_soil_file(param_csv_path=args.param_csv, batch_file=BATCH_FILE)
    run_model()
