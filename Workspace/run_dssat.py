import argparse
import datetime
import glob
import math
import os
import re
import shutil
import subprocess
import tempfile
import time

import pandas as pd

# Configuration
DSSAT_EXE = "DSCSM048.EXE"
BATCH_FILE = "DSSBatch.v48"
CUL_BASE_FILE = "TMGRO048.CUL.base"
CUL_FILE = "TMGRO048.CUL"
ECO_FILE = "TMGRO048.ECO"
SPE_FILE = "TMGRO048.SPE"
SOIL_FILE = "SOIL.SOL"
SOIL_BASE_FILE = "SOIL.SOL.base"
PARAM_CSV = "pest_params.csv"

OUTPUT_FILES = [
    "PlantGro.OUT",
    "FreshWt.OUT",
    "Summary.OUT",
    "OVERVIEW.OUT",
    "WARNING.OUT"
]


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
    with open(tmt_path, "r") as f:
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


def _read_tmt_process_points(tmt_path):
    if not tmt_path or not os.path.exists(tmt_path):
        return {}

    header = None
    rows = []
    with open(tmt_path, "r") as f:
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

        if lnsd == -99.0 and laid == -99.0 and lwad == -99.0 and swad == -99.0:
            continue

        points_by_tn.setdefault(tn, []).append(
            {
                "date": int(date),
                "lnsd": float(lnsd),
                "laid": float(laid),
                "lwad": float(lwad),
                "swad": float(swad),
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


def _write_pest_harvest_from_tmt_and_freshwt(batch_file, freshwt_path, pest_harvest_path, tmt_path=None, harvest_var="CHPDT"):
    entries = _parse_batch_entries(batch_file)
    if not entries:
        with open(pest_harvest_path, "w") as f:
            f.write("RUN 1 TN -99 HNO -99 DATE -99 @PWADS@ -99.000 @PWAIS@ -99.000\n")
        return

    base_dir = os.path.dirname(os.path.abspath(__file__))
    filex_abs = _resolve_filex_from_batch(batch_file, base_dir)
    if not tmt_path:
        excode = _infer_excode_from_filex(filex_abs or entries[0]["filex"])
        filex_dir = os.path.dirname(os.path.abspath(filex_abs)) if filex_abs else base_dir
        tmt_path = os.path.join(filex_dir, f"{excode}.TMT") if excode else None

    events_by_tn = _read_tmt_harvest_events(tmt_path)
    harvest_var = str(harvest_var or "CHPDT").strip().upper()
    var_by_run = _read_freshwt_var_by_run(freshwt_path, harvest_var)

    wrote_any = False
    with open(pest_harvest_path, "w") as f:
        for e in entries:
            run_no = int(e["run"])
            tn = int(e.get("tn", -99))
            events = events_by_tn.get(tn, [])
            prev_cum = None
            for ev in events:
                hno = int(ev["hno"])
                date = int(ev["date"])
                sim_date = _yyddd_add_days(date, 1)
                sim_val = _nearest_on_or_before(var_by_run.get(run_no, {}), sim_date)
                if sim_val is None:
                    sim_val = -99.0
                sim_inc = -99.0
                if sim_val != -99.0:
                    if prev_cum is None:
                        sim_inc = float(sim_val)
                    else:
                        sim_inc = float(sim_val) - float(prev_cum)
                    prev_cum = float(sim_val)
                f.write(
                    f"RUN {run_no:d} TN {tn:d} HNO {hno:d} DATE {date:d} @PWADS@ {float(sim_val):0.3f} @PWAIS@ {float(sim_inc):0.3f}\n"
                )
                wrote_any = True

        if not wrote_any:
            for e in entries:
                run_no = int(e["run"])
                tn = int(e.get("tn", -99))
                f.write(f"RUN {run_no:d} TN {tn:d} HNO -99 DATE -99 @PWADS@ -99.000 @PWAIS@ -99.000\n")


def _write_pest_tmtgrow_from_tmt_and_plantgro(batch_file, plantgro_path, pest_tmtgrow_path, tmt_path=None):
    entries = _parse_batch_entries(batch_file)
    if not entries:
        with open(pest_tmtgrow_path, "w") as f:
            f.write("RUN 1 TN -99 DATE -99 @LAIDS@ -99.000 @LWADS@ -99.000 @SWADS@ -99.000\n")
        return

    base_dir = os.path.dirname(os.path.abspath(__file__))
    filex_abs = _resolve_filex_from_batch(batch_file, base_dir)
    if not tmt_path:
        excode = _infer_excode_from_filex(filex_abs or entries[0]["filex"])
        filex_dir = os.path.dirname(os.path.abspath(filex_abs)) if filex_abs else base_dir
        tmt_path = os.path.join(filex_dir, f"{excode}.TMT") if excode else None

    points_by_tn = _read_tmt_process_points(tmt_path)
    vars_by_run = _read_plantgro_vars_by_run(plantgro_path, ["L#SD", "LAID", "LWAD", "SWAD"])

    wrote_any = False
    with open(pest_tmtgrow_path, "w") as f:
        for e in entries:
            run_no = int(e["run"])
            tn = int(e.get("tn", -99))
            pts = points_by_tn.get(tn, [])
            for p in pts:
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
                if sim_day is not None:
                    lnsd_s = float(sim_day.get("L#SD", -99.0))
                    laid_s = float(sim_day.get("LAID", -99.0))
                    lwad_s = float(sim_day.get("LWAD", -99.0))
                    swad_s = float(sim_day.get("SWAD", -99.0))

                f.write(
                    f"RUN {run_no:d} TN {tn:d} DATE {date:d} "
                    f"@L#SDS@ {lnsd_s:0.3f} @LAIDS@ {laid_s:0.3f} @LWADS@ {lwad_s:0.3f} @SWADS@ {swad_s:0.3f}\n"
                )
                wrote_any = True

        if not wrote_any:
            for e in entries:
                run_no = int(e["run"])
                tn = int(e.get("tn", -99))
                f.write(
                    f"RUN {run_no:d} TN {tn:d} DATE -99 "
                    f"@L#SDS@ -99.000 @LAIDS@ -99.000 @LWADS@ -99.000 @SWADS@ -99.000\n"
                )


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

    return copied_filex


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
        with open(pest_eval_path, "w") as f:
            for i in range(1, n_runs + 1):
                f.write(
                    f"RUN {i:d} TN {-99:d} @ADAPS@ {-99.0:0.3f} @ADAPM@ {-99.0:0.3f} "
                    f"@MDAPS@ {-99.0:0.3f} @MDAPM@ {-99.0:0.3f}\n"
                )
        return

    expected_cols = ["@RUN", "TN", "ADAPS", "ADAPM", "MDAPS", "MDAPM"]
    for c in expected_cols:
        if c not in df.columns:
            df[c] = -99

    for c in expected_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(-99)

    out_df = df[expected_cols].copy().sort_values(by="@RUN", kind="mergesort")
    with open(pest_eval_path, "w") as f:
        for _, row in out_df.iterrows():
            run_no = _as_int(row["@RUN"], default=-99)
            tn = _as_int(row["TN"], default=-99)
            adaps = float(row["ADAPS"]) if not pd.isna(row["ADAPS"]) else -99.0
            adapm = float(row["ADAPM"]) if not pd.isna(row["ADAPM"]) else -99.0
            mdaps = float(row["MDAPS"]) if not pd.isna(row["MDAPS"]) else -99.0
            mdapm = float(row["MDAPM"]) if not pd.isna(row["MDAPM"]) else -99.0
            f.write(
                f"RUN {run_no:d} TN {tn:d} @ADAPS@ {adaps:0.3f} @ADAPM@ {adapm:0.3f} "
                f"@MDAPS@ {mdaps:0.3f} @MDAPM@ {mdapm:0.3f}\n"
            )


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
        with open(pest_grow_path, "w") as f:
            for i in range(1, n_runs + 1):
                f.write(
                    f"RUN {i:d} TN {-99:d} @HWAMS@ {-99.0:0.3f} @LAIXS@ {-99.0:0.3f} @CNAMS@ {-99.0:0.3f}\n"
                )
        return

    expected_cols = ["@RUN", "TN", "HWAMS", "LAIXS", "CNAMS"]
    for c in expected_cols:
        if c not in df.columns:
            df[c] = -99

    for c in expected_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(-99)

    out_df = df[expected_cols].copy().sort_values(by="@RUN", kind="mergesort")
    with open(pest_grow_path, "w") as f:
        for _, row in out_df.iterrows():
            run_no = _as_int(row["@RUN"], default=-99)
            tn = _as_int(row["TN"], default=-99)
            hwams = float(row["HWAMS"]) if not pd.isna(row["HWAMS"]) else -99.0
            laixs = float(row["LAIXS"]) if not pd.isna(row["LAIXS"]) else -99.0
            cnams = float(row["CNAMS"]) if not pd.isna(row["CNAMS"]) else -99.0
            f.write(
                f"RUN {run_no:d} TN {tn:d} @HWAMS@ {hwams:0.3f} @LAIXS@ {laixs:0.3f} @CNAMS@ {cnams:0.3f}\n"
            )


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
        with open(pest_joint_path, "w") as f:
            for i in range(1, n_runs + 1):
                f.write(
                    f"RUN {i:d} TN {-99:d} "
                    f"@HWAMS@ {-99.0:0.3f} @HIAMS@ {-99.0:0.3f} @LAIXS@ {-99.0:0.3f} @CNAMS@ {-99.0:0.3f} "
                    f"@CHTAS@ {-99.0:0.3f} @CNAAS@ {-99.0:0.3f} "
                    f"@PWAMS@ {-99.0:0.3f} @H#AMS@ {-99.0:0.3f}\n"
                )
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
    with open(pest_joint_path, "w") as f:
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
            f.write(
                f"RUN {run_no:d} TN {tn:d} "
                f"@HWAMS@ {hwams:0.3f} @HIAMS@ {hiams:0.3f} @LAIXS@ {laixs:0.3f} @CNAMS@ {cnams:0.3f} "
                f"@CHTAS@ {chtas:0.3f} @CNAAS@ {cnaas:0.3f} "
                f"@PWAMS@ {pwams:0.3f} @H#AMS@ {h_n_ams:0.3f}\n"
            )

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

def cleanup(target_dir=".", keep_dssat_outputs=False):
    if not keep_dssat_outputs:
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
        "Evaluate.OUT",
    }
    if keep_dssat_outputs:
        keep_out.update({"FreshWt.OUT", "PlantGro.OUT"})
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

    if not os.path.exists(PEST_EVAL_FILE):
        n_runs = _count_batch_runs(BATCH_FILE)
        if n_runs <= 0:
            n_runs = 1
        with open(PEST_EVAL_FILE, "w") as f:
            for i in range(1, n_runs + 1):
                f.write(
                    f"RUN {i:d} TN {-99:d} @ADAPS@ {-99.0:0.3f} @ADAPM@ {-99.0:0.3f} "
                    f"@MDAPS@ {-99.0:0.3f} @MDAPM@ {-99.0:0.3f}\n"
                )

    if not os.path.exists(PEST_GROW_FILE):
        n_runs = _count_batch_runs(BATCH_FILE)
        if n_runs <= 0:
            n_runs = 1
        with open(PEST_GROW_FILE, "w") as f:
            for i in range(1, n_runs + 1):
                f.write(
                    f"RUN {i:d} TN {-99:d} @HWAMS@ {-99.0:0.3f} @LAIXS@ {-99.0:0.3f} @CNAMS@ {-99.0:0.3f}\n"
                )

    if not os.path.exists(PEST_JOINT_FILE):
        n_runs = _count_batch_runs(BATCH_FILE)
        if n_runs <= 0:
            n_runs = 1
        with open(PEST_JOINT_FILE, "w") as f:
            for i in range(1, n_runs + 1):
                f.write(
                    f"RUN {i:d} TN {-99:d} "
                    f"@HWAMS@ {-99.0:0.3f} @LAIXS@ {-99.0:0.3f} @CNAMS@ {-99.0:0.3f} "
                    f"@CHTAS@ {-99.0:0.3f} @CNAAS@ {-99.0:0.3f} "
                    f"@PWAMS@ {-99.0:0.3f} @H#AMS@ {-99.0:0.3f} @HIAMS@ {-99.0:0.3f}\n"
                )

    if not os.path.exists(PEST_HARVEST_FILE):
        try:
            _write_pest_harvest_from_tmt_and_freshwt(BATCH_FILE, "FreshWt.OUT", PEST_HARVEST_FILE)
        except Exception:
            n_runs = _count_batch_runs(BATCH_FILE)
            if n_runs <= 0:
                n_runs = 1
            with open(PEST_HARVEST_FILE, "w") as f:
                for i in range(1, n_runs + 1):
                    f.write(f"RUN {i:d} TN {-99:d} HNO -99 DATE -99 @PWADS@ -99.000 @PWAIS@ -99.000\n")

    if not os.path.exists(PEST_TMTGROW_FILE):
        try:
            _write_pest_tmtgrow_from_tmt_and_plantgro(BATCH_FILE, "PlantGro.OUT", PEST_TMTGROW_FILE)
        except Exception:
            n_runs = _count_batch_runs(BATCH_FILE)
            if n_runs <= 0:
                n_runs = 1
            with open(PEST_TMTGROW_FILE, "w") as f:
                for i in range(1, n_runs + 1):
                    f.write(
                        f"RUN {i:d} TN {-99:d} DATE -99 "
                        f"@LAIDS@ -99.000 @LWADS@ -99.000 @SWADS@ -99.000\n"
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
        return s[-width:]
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
        print(f"Error reading parameter CSV: {e}")
        return

    if not cul_base_path or (not os.path.exists(cul_base_path)):
        print(f"Error: {CUL_BASE_FILE} not found.")
        return

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
        print("Error: Invalid CUL structure.")
        return

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
        return
    if not os.path.exists(param_csv_path):
        return

    script_dir = os.path.dirname(os.path.abspath(__file__))
    eco_base_path = None
    cand = os.path.join(script_dir, ECO_FILE + ".base")
    if os.path.exists(cand):
        eco_base_path = cand
    else:
        cand = os.path.normpath(os.path.join(script_dir, "..", "..", "Genotype", ECO_FILE))
        if os.path.exists(cand):
            eco_base_path = cand
        elif os.path.exists(ECO_FILE):
            eco_base_path = ECO_FILE

    if not eco_base_path:
        return

    try:
        param_dict = _read_param_dict(param_csv_path)
    except Exception as e:
        print(f"Error reading parameter CSV: {e}")
        return
    if not param_dict:
        return

    if "XFINT" in param_dict:
        try:
            xfint = float(param_dict.get("XFINT"))
            xfrt = float(param_dict.get("XFRT", xfint))
            upper = max(0.0, min(1.0, xfrt, 0.30))
            if xfint < 0.0:
                xfint = 0.0
            if xfint > upper:
                xfint = upper
            param_dict["XFINT"] = xfint
        except Exception:
            pass

    if "XMAGE" in param_dict and "XFPHT" in param_dict:
        try:
            xmage = float(param_dict.get("XMAGE"))
            xfpht = float(param_dict.get("XFPHT"))
            if xfpht <= xmage:
                param_dict["XFPHT"] = xmage + 1.0
        except Exception:
            pass

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
        return

    header_line = lines[header_idx].rstrip("\n")
    headers = header_line.split()
    if len(headers) < 3:
        return
    param_names = headers[2:]

    eco_line = lines[eco_idx]

    line_len = len(eco_line.rstrip("\n"))
    spans = _eco_param_spans_from_template_line(eco_line, len(param_names))
    if spans is None or len(spans) < len(param_names):
        line_len = max(len(header_line), len(eco_line.rstrip("\n")))
        spans = _field_spans_from_header(header_line, param_names, line_len)
    if spans is None or len(spans) < len(param_names):
        return

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

        if (not math.isfinite(xfint)) or (xfint < 0.0) or (xfint > 1.0):
            orig = eco_line[abs_s0:abs_s1]
            width = abs_s1 - abs_s0
            safe = 0.20
            formatted = _format_to_width_preserve_space(safe, width, orig_token=orig)
            new_chars[abs_s0:abs_s1] = list(formatted)

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
        return

    script_dir = os.path.dirname(os.path.abspath(__file__))
    spe_base_path = None
    cand = os.path.join(script_dir, SPE_FILE + ".base")
    if os.path.exists(cand):
        spe_base_path = cand
    else:
        cand = os.path.normpath(os.path.join(script_dir, "..", "..", "Genotype", SPE_FILE))
        if os.path.exists(cand):
            spe_base_path = cand
        elif os.path.exists(SPE_FILE):
            spe_base_path = SPE_FILE

    if not spe_base_path:
        return

    try:
        param_dict = _read_param_dict(param_csv_path)
    except Exception as e:
        print(f"Error reading parameter CSV: {e}")
        return
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
        "CMOBMX",
        "CADSTF",
        "CADPR1",
        "NMOBMX",
        "NVSMOB",
        "NRCVR",
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
    ]

    keys = [k for k in (base_names + stage_names + direct_keys) if k in param_dict]
    if not keys:
        return

    number_re = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[Ee][-+]?\d+)?")
    with open(spe_base_path, "r") as f:
        lines = f.readlines()

    def _update_named_line(contains_text, param_order):
        if not contains_text or not param_order:
            return
        if not any((str(p).strip().upper() in param_dict) for p in param_order):
            return
        idx = -1
        for j, s in enumerate(lines):
            if contains_text in s:
                idx = j
                break
        if idx == -1:
            return
        s = lines[idx]
        matches = list(number_re.finditer(s))
        if len(matches) < len(param_order):
            return
        new_chars = list(s.rstrip("\n"))
        for name, m in zip(param_order, matches[: len(param_order)]):
            key = str(name).strip().upper()
            if key not in param_dict:
                continue
            v = float(param_dict[key])
            orig = m.group(0)
            width = m.end() - m.start()
            formatted = _format_to_width(v, width, orig_token=orig)
            if len(formatted) != width:
                formatted = formatted[:width].rjust(width)
            new_chars[m.start() : m.end()] = list(formatted)
        lines[idx] = "".join(new_chars) + "\n"

    _update_named_line("PARMAX,PHTMAX", ["PARMAX", "PHTMAX", "KCAN", "KC_SLOPE"])
    _update_named_line("RNO3C,RNH4C", ["RNO3C", "RNH4C", "RPRO", "RFIXN"])
    _update_named_line("CMOBMX,CADSTF", ["CMOBMX", "CADSTF", "CADPR1", "NMOBMX", "NVSMOB", "NRCVR"])
    _update_named_line("FNPGN(4)", ["FNPGN1", "FNPGN2", "FNPGN3", "FNPGN4"])
    _update_named_line("SLWREF,SLWSLO", ["SLWREF", "SLWSLO", "NSLOPE", "LNREF", "PGREF"])
    _update_named_line("WTFSD,PORPT", ["WTFSD", "PORPT", "FRSTMF", "FRLFF", "ATOP", "FRCNOD"])
    _update_named_line("FINREF,SLAREF", ["FINREF", "SLAREF", "SIZREF", "VSSINK", "EVMODC"])
    _update_named_line("RTNO3,RTNH4", ["RTNO3", "RTNH4", "PORMIN", "RTEXF"])

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
    if not os.path.exists(param_csv_path):
        return

    try:
        param_dict = _read_param_dict(param_csv_path)
    except Exception as e:
        print(f"Error reading parameter CSV: {e}")
        return
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
        return

    script_dir = os.path.dirname(os.path.abspath(__file__))
    soil_base_path = None
    cand = os.path.join(script_dir, SOIL_BASE_FILE)
    if os.path.exists(cand):
        soil_base_path = cand
    else:
        cand2 = os.path.join(script_dir, SOIL_FILE)
        if os.path.exists(cand2):
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

    def _clamp(x, lo, hi):
        try:
            v = float(x)
        except Exception:
            return None
        if v < float(lo):
            v = float(lo)
        if v > float(hi):
            v = float(hi)
        return v

    def _safe_water_triplet(slll, sdul, ssat):
        a = _clamp(slll, 0.01, 0.80) if slll is not None else None
        b = _clamp(sdul, 0.01, 0.80) if sdul is not None else None
        c = _clamp(ssat, 0.01, 0.80) if ssat is not None else None
        if a is None or b is None or c is None:
            return a, b, c
        eps = 1e-3
        if not (a < b):
            b = min(max(a + 0.01, a + eps), 0.80)
        if not (b < c):
            c = min(max(b + 0.01, b + eps), 0.80)
        if c - a < 2 * eps:
            c = min(0.80, a + 0.02)
            b = min(max(a + 0.01, a + eps), c - eps)
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
        header_line = lines[scom_header_idx].rstrip("\n")
        want = ["SALB", "SLDR", "SLRO"]
        line_len = max(len(header_line), len(lines[scom_header_idx + 1].rstrip("\n")) if (scom_header_idx + 1) < sec_end else len(header_line))
        spans = _field_spans_from_header(header_line, want, line_len)
        if spans is not None and (scom_header_idx + 1) < sec_end:
            data_idx = None
            for j in range(scom_header_idx + 1, sec_end):
                if not lines[j].strip():
                    continue
                if lines[j].lstrip().startswith("@") or lines[j].startswith("*"):
                    break
                data_idx = j
                break
            if data_idx is not None:
                s = lines[data_idx].rstrip("\n").ljust(line_len)
                new_chars = list(s)
                for name, (abs_s0, abs_s1) in zip(want, spans):
                    key = f"SOIL_{name}"
                    if key not in param_dict:
                        continue
                    v = float(param_dict[key])
                    if name == "SALB":
                        v2 = _clamp(v, 0.05, 0.35)
                    elif name == "SLDR":
                        v2 = _clamp(v, 0.01, 5.00)
                    elif name == "SLRO":
                        v2 = _clamp(v, 1.0, 99.0)
                    else:
                        v2 = v
                    if v2 is None:
                        continue
                    orig = s[abs_s0:abs_s1]
                    width = abs_s1 - abs_s0
                    formatted = _format_to_width_preserve_space(v2, width, orig_token=orig)
                    new_chars[abs_s0:abs_s1] = list(formatted)
                lines[data_idx] = "".join(new_chars).rstrip() + "\n"

    if layer_header_idx is not None:
        header_cols = lines[layer_header_idx].split()
        if header_cols and header_cols[0] == "@":
            header_cols = header_cols[1:]
        want = ["SLLL", "SDUL", "SSAT", "SBDM", "SLOC"]
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

            s = lines[idx].rstrip("\n")
            matches = list(re.finditer(r"[-+]?\d*\.\d+|[-+]?\d+", s))

            for name in ["SLLL", "SDUL", "SSAT", "SBDM", "SLOC"]:
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
                    v2 = _clamp(v, 0.01, 0.80)
                    if v2 is None:
                        continue
                    new_tok = f"{v2:.3f}"
                elif name == "SBDM":
                    v2 = _clamp(v, 0.5, 2.2)
                    if v2 is None:
                        continue
                    new_tok = f"{v2:.2f}"
                elif name == "SLOC":
                    v2 = _clamp(v, 0.0, 10.0)
                    if v2 is None:
                        continue
                    new_tok = f"{v2:.2f}"
                else:
                    new_tok = str(v)

                if len(new_tok) <= len(orig_tok):
                    new_tok = new_tok.rjust(len(orig_tok))
                else:
                    new_tok = new_tok[-len(orig_tok) :]

                s = s[: m.start()] + new_tok + s[m.end() :]
                matches = list(re.finditer(r"[-+]?\d*\.\d+|[-+]?\d+", s))

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
        print(f"Error reading parameter CSV: {e}")
        return
    if not param_dict:
        return

    ic_keys = [k for k in param_dict.keys() if str(k).strip().upper().startswith("IC_SH2O_")]
    if not ic_keys:
        return

    cwd_script = os.path.dirname(os.path.abspath(__file__))
    if not filex_path:
        filex_path = _resolve_filex_from_batch(batch_file, os.getcwd()) or _resolve_filex_from_batch(batch_file, cwd_script)
    if not filex_path or not os.path.exists(filex_path):
        return

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
            pcr_cols = s.split()
            pcr_icdat_col = None
            try:
                pcr_icdat_col = pcr_cols.index("ICDAT")
            except ValueError:
                pcr_icdat_col = None
            pcr_in_table = pcr_icdat_col is not None
            continue

        if s.lstrip().startswith("@C") and ("ICBL" in u) and ("SH2O" in u):
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
        v = max(0.01, min(0.80, v))
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

def run_model():
    """Runs the DSSAT model."""
    global BATCH_FILE
    print(f"Running {DSSAT_EXE} B {BATCH_FILE}...")
    
    try:
        cwd_script = os.path.dirname(os.path.abspath(__file__))
        run_dir = os.getcwd()
        filex_path = _resolve_filex_from_batch(BATCH_FILE, cwd_script) or _resolve_filex_from_batch(BATCH_FILE, run_dir)

        cleanup(run_dir, keep_dssat_outputs=False)

        exe_path = shutil.which(DSSAT_EXE)
        if not exe_path:
            candidate = os.path.normpath(os.path.join(cwd_script, "..", "..", DSSAT_EXE))
            exe_path = candidate if os.path.exists(candidate) else DSSAT_EXE

        dssat_root = os.path.normpath(os.path.join(cwd_script, "..", ".."))
        dssatpro_src = os.path.join(dssat_root, "DSSATPRO.v48")
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
        update_initial_conditions_file(param_csv_path=PARAM_CSV, batch_file=BATCH_FILE, filex_path=localized_filex or filex_path)

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
        # Note: DSCSM048.EXE requires the code (B) and batch file as arguments
        # It must be run in the directory containing the files
        result = subprocess.run(
            [exe_path, "B", batch_arg],
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
            print(f"Stdout: {result.stdout}")
            print(f"Stderr: {result.stderr}")
        else:
            orig_cwd = os.getcwd()
            try:
                os.chdir(run_dir)
                _sync_outputs_from_filex_dir(BATCH_FILE, run_dir, OUTPUT_FILES + ["Evaluate.OUT"], dest_dir=run_dir)

                if not os.path.exists("Evaluate.OUT") or os.path.getsize("Evaluate.OUT") == 0:
                    print("Evaluate.OUT missing or empty after sync.")
                    handle_failure(999)
                    return

                print("Evaluate.OUT generated successfully.")
                try:
                    _write_pest_eval_from_evaluate("Evaluate.OUT", PEST_EVAL_FILE)
                except Exception as e:
                    print(f"Warning: failed to write {PEST_EVAL_FILE}: {e}")
                try:
                    _write_pest_grow_from_evaluate("Evaluate.OUT", PEST_GROW_FILE)
                except Exception as e:
                    print(f"Warning: failed to write {PEST_GROW_FILE}: {e}")
                try:
                    _write_pest_joint_from_evaluate("Evaluate.OUT", PEST_JOINT_FILE)
                except Exception as e:
                    print(f"Warning: failed to write {PEST_JOINT_FILE}: {e}")
                try:
                    _write_pest_harvest_from_tmt_and_freshwt(
                        BATCH_FILE,
                        "FreshWt.OUT",
                        PEST_HARVEST_FILE,
                        harvest_var=HARVEST_VAR,
                    )
                except Exception as e:
                    print(f"Warning: failed to write {PEST_HARVEST_FILE}: {e}")
                try:
                    _write_pest_tmtgrow_from_tmt_and_plantgro(BATCH_FILE, "PlantGro.OUT", PEST_TMTGROW_FILE)
                except Exception as e:
                    print(f"Warning: failed to write {PEST_TMTGROW_FILE}: {e}")
            finally:
                try:
                    os.chdir(orig_cwd)
                except Exception:
                    pass

            cleanup(run_dir, keep_dssat_outputs=True)

    except Exception as e:
        print(f"Exception running model: {e}")
        handle_failure(998)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--param-csv", default=PARAM_CSV)
    parser.add_argument("--batch", default=BATCH_FILE)
    parser.add_argument("--cultivar", default=None)
    parser.add_argument("--harvest-var", default="CHPDT")
    args, _ = parser.parse_known_args()

    BATCH_FILE = args.batch
    PARAM_CSV = args.param_csv
    HARVEST_VAR = (args.harvest_var or "CHPDT").strip().upper()

    cwd_script = os.path.dirname(os.path.abspath(__file__))

    cultivar = args.cultivar
    if not cultivar:
        cwd_script = os.path.dirname(os.path.abspath(__file__))
        filex = _resolve_filex_from_batch(BATCH_FILE, cwd_script)
        cultivar = _infer_cultivar_from_filex(filex)
    if not cultivar:
        cultivar = "TM0001"

    cleanup(cwd_script, keep_dssat_outputs=False)
    update_cul_file(param_csv_path=args.param_csv, target_cultivar=cultivar)
    ecotype = _infer_ecotype_from_cul(CUL_FILE, cultivar) or "TM0001"
    update_eco_file(param_csv_path=args.param_csv, target_ecotype=ecotype)
    update_spe_file(param_csv_path=args.param_csv)
    update_soil_file(param_csv_path=args.param_csv, batch_file=BATCH_FILE)
    run_model()
