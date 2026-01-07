import os
import subprocess
import sys
import shutil
import time
import pandas as pd
import argparse
import re

# Configuration
DSSAT_EXE = "DSCSM048.EXE"
BATCH_FILE = "DSSBatch.v48"
CUL_BASE_FILE = "TMGRO048.CUL.base"
CUL_FILE = "TMGRO048.CUL"
ECO_FILE = "TMGRO048.ECO"
SPE_FILE = "TMGRO048.SPE"
PARAM_CSV = "pest_params.csv"

OUTPUT_FILES = [
    "PlantGro.OUT",
    "Evaluate.OUT",
    "Summary.OUT",
    "OVERVIEW.OUT",
    "WARNING.OUT"
]

PEST_EVAL_FILE = "PestEval.OUT"
PEST_GROW_FILE = "PestGrow.OUT"
PEST_JOINT_FILE = "PestJoint.OUT"
PEST_HARVEST_FILE = "PestHarvest.OUT"
PEST_TMTGROW_FILE = "PestTmtGrow.OUT"


def _parse_batch_entries(batch_file):
    entries = []
    if not os.path.exists(batch_file):
        return entries
    with open(batch_file, "r") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s.startswith("$") or s.startswith("@"):  # header/comment
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
        pwad = _as_float(r.get("PWAD"), default=-99.0)

        if chpdt == -99.0 and pwad == -99.0:
            continue

        events_by_tn.setdefault(tn, []).append({"date": date, "chpdt": chpdt, "pwad": pwad})

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
                inc = 0.0 if e["pwad"] == -99.0 else e["pwad"]
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

        laid = _as_float(r.get("LAID"), default=-99.0)
        lwad = _as_float(r.get("LWAD"), default=-99.0)
        swad = _as_float(r.get("SWAD"), default=-99.0)

        if laid == -99.0 and lwad == -99.0 and swad == -99.0:
            continue

        points_by_tn.setdefault(tn, []).append(
            {"date": int(date), "laid": float(laid), "lwad": float(lwad), "swad": float(swad)}
        )

    out = {}
    for tn, pts in points_by_tn.items():
        out[tn] = sorted(pts, key=lambda x: x["date"])
    return out


def _read_plantgro_pwad_by_run(plantgro_path):
    if not plantgro_path or not os.path.exists(plantgro_path):
        return {}

    pwad_by_run = {}
    current_run = None
    header = None
    pwad_idx = None

    with open(plantgro_path, "r") as f:
        for line in f:
            s = line.rstrip("\n")
            if s.startswith("*RUN"):
                m = re.match(r"^\*RUN\s+(\d+)", s)
                current_run = int(m.group(1)) if m else None
                header = None
                pwad_idx = None
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
            pwad_by_run.setdefault(current_run, {})[date] = pwad

    return pwad_by_run


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


def _write_pest_harvest_from_tmt_and_plantgro(batch_file, plantgro_path, pest_harvest_path, tmt_path=None):
    entries = _parse_batch_entries(batch_file)
    if not entries:
        with open(pest_harvest_path, "w") as f:
            f.write("RUN 1 TN -99 HNO -99 DATE -99 @PWADS@ -99.000\n")
        return

    base_dir = os.path.dirname(os.path.abspath(__file__))
    filex_abs = _resolve_filex_from_batch(batch_file, base_dir)
    if not tmt_path:
        excode = _infer_excode_from_filex(filex_abs or entries[0]["filex"])
        filex_dir = os.path.dirname(os.path.abspath(filex_abs)) if filex_abs else base_dir
        tmt_path = os.path.join(filex_dir, f"{excode}.TMT") if excode else None

    events_by_tn = _read_tmt_harvest_events(tmt_path)
    pwad_by_run = _read_plantgro_pwad_by_run(plantgro_path)

    wrote_any = False
    with open(pest_harvest_path, "w") as f:
        for e in entries:
            run_no = int(e["run"])
            tn = int(e.get("tn", -99))
            events = events_by_tn.get(tn, [])
            for ev in events:
                hno = int(ev["hno"])
                date = int(ev["date"])
                sim_val = _nearest_on_or_before(pwad_by_run.get(run_no, {}), date)
                if sim_val is None:
                    sim_val = -99.0
                f.write(
                    f"RUN {run_no:d} TN {tn:d} HNO {hno:d} DATE {date:d} @PWADS@ {float(sim_val):0.3f}\n"
                )
                wrote_any = True

        if not wrote_any:
            for e in entries:
                run_no = int(e["run"])
                tn = int(e.get("tn", -99))
                f.write(f"RUN {run_no:d} TN {tn:d} HNO -99 DATE -99 @PWADS@ -99.000\n")


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
    vars_by_run = _read_plantgro_vars_by_run(plantgro_path, ["LAID", "LWAD", "SWAD"])

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

                laid_s = -99.0
                lwad_s = -99.0
                swad_s = -99.0
                if sim_day is not None:
                    laid_s = float(sim_day.get("LAID", -99.0))
                    lwad_s = float(sim_day.get("LWAD", -99.0))
                    swad_s = float(sim_day.get("SWAD", -99.0))

                f.write(
                    f"RUN {run_no:d} TN {tn:d} DATE {date:d} "
                    f"@LAIDS@ {laid_s:0.3f} @LWADS@ {lwad_s:0.3f} @SWADS@ {swad_s:0.3f}\n"
                )
                wrote_any = True

        if not wrote_any:
            for e in entries:
                run_no = int(e["run"])
                tn = int(e.get("tn", -99))
                f.write(
                    f"RUN {run_no:d} TN {tn:d} DATE -99 "
                    f"@LAIDS@ -99.000 @LWADS@ -99.000 @SWADS@ -99.000\n"
                )


def _resolve_filex_from_batch(batch_file, base_dir):
    filex = _first_batch_filex_path(batch_file)
    if not filex:
        return None
    if os.path.isabs(filex):
        return os.path.normpath(filex)
    return os.path.normpath(os.path.join(base_dir, filex))


def _sync_outputs_from_filex_dir(batch_file, base_dir, output_files):
    filex_path = _resolve_filex_from_batch(batch_file, base_dir)
    if not filex_path:
        return
    src_dir = os.path.dirname(os.path.abspath(filex_path))
    for fn in output_files:
        if os.path.exists(fn) and os.path.getsize(fn) > 0:
            continue
        src = os.path.join(src_dir, fn)
        if os.path.exists(src) and os.path.getsize(src) > 0:
            try:
                shutil.copy(src, fn)
            except Exception:
                pass

def _count_batch_runs(batch_file):
    if not os.path.exists(batch_file):
        return 0
    n = 0
    with open(batch_file, "r") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s.startswith("$") or s.startswith("@"):
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
                    f"@HWAMS@ {-99.0:0.3f} @LAIXS@ {-99.0:0.3f} @CNAMS@ {-99.0:0.3f} "
                    f"@CHTAS@ {-99.0:0.3f} @CNAAS@ {-99.0:0.3f} "
                    f"@PWAMS@ {-99.0:0.3f} @H#AMS@ {-99.0:0.3f} @HIAMS@ {-99.0:0.3f}\n"
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
                f"@HWAMS@ {hwams:0.3f} @LAIXS@ {laixs:0.3f} @CNAMS@ {cnams:0.3f} "
                f"@CHTAS@ {chtas:0.3f} @CNAAS@ {cnaas:0.3f} "
                f"@PWAMS@ {pwams:0.3f} @H#AMS@ {h_n_ams:0.3f} @HIAMS@ {hiams:0.3f}\n"
            )

def _first_batch_filex_path(batch_file):
    if not os.path.exists(batch_file):
        return None
    with open(batch_file, "r") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s.startswith("$") or s.startswith("@"):
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

def cleanup(target_dir="."):
    for file in OUTPUT_FILES:
        p = os.path.join(target_dir, file)
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception as e:
                print(f"Warning: Could not remove {p}: {e}")

    for file in ["LUN.LST", "LUN.OUT", "LUN.REP", "DSSAT48.LST"]:
        p = os.path.join(target_dir, file)
        if os.path.exists(p):
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
            _write_pest_harvest_from_tmt_and_plantgro(BATCH_FILE, "PlantGro.OUT", PEST_HARVEST_FILE)
        except Exception:
            n_runs = _count_batch_runs(BATCH_FILE)
            if n_runs <= 0:
                n_runs = 1
            with open(PEST_HARVEST_FILE, "w") as f:
                for i in range(1, n_runs + 1):
                    f.write(f"RUN {i:d} TN {-99:d} HNO -99 DATE -99 @PWADS@ -99.000\n")

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

    if isinstance(v, float) and v == 0:
        for d in range(min(4, max(0, width - 2)), -1, -1):
            s = f"{0:>{width}.{d}f}" if d > 0 else f"{0:>{width}d}"
            if len(s) == width:
                if orig_token and orig_token.strip().startswith(".") and s.strip().startswith("0."):
                    s2 = s.replace("0.", ".", 1)
                    if len(s2) == width:
                        return s2
                return s
        return f"{0:>{width}d}"

    if isinstance(v, float):
        candidates = []

        if orig_token and "." in orig_token.strip():
            dec = len(orig_token.strip().split(".", 1)[1])
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

            s = f"{v:>{width}.{d}f}" if d > 0 else f"{v:>{width}.0f}"
            if len(s) == width:
                if abs(v) < 1 and orig_token and orig_token.strip().startswith(".") and s.strip().startswith("0."):
                    s2 = s.replace("0.", ".", 1)
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

    number_re = re.compile(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?")
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
    if not os.path.exists(param_csv_path):
        print(f"No {param_csv_path} found. Using base CUL file.")
        if os.path.exists(CUL_BASE_FILE):
            shutil.copy(CUL_BASE_FILE, CUL_FILE)
        return

    try:
        param_dict = _read_param_dict(param_csv_path)
    except Exception as e:
        print(f"Error reading parameter CSV: {e}")
        return

    if not os.path.exists(CUL_BASE_FILE):
        print(f"Error: {CUL_BASE_FILE} not found.")
        return

    with open(CUL_BASE_FILE, 'r') as f:
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

    # Map headers
    headers = lines[header_idx].split()
    # Headers: @VAR# VRNAME EXPNO ECO# CSDL ...
    # Indices: 0     1      2     3    4    ...
    # Parameter names start at index 4
    param_names = headers[4:]
    
    tm_line = lines[cultivar_idx]
    number_re = re.compile(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?")
    matches = list(number_re.finditer(tm_line))
    if len(matches) < len(param_names):
        print("Error: Could not locate numeric cultivar parameters in cultivar line.")
        return

    param_matches = matches[-len(param_names):]
    new_chars = list(tm_line.rstrip("\n"))

    for name, m in zip(param_names, param_matches):
        orig = m.group(0)
        try:
            current_val = float(orig)
        except Exception:
            current_val = orig

        key = str(name).strip().upper()
        if key in param_dict:
            try:
                current_val = float(param_dict[key])
            except Exception:
                current_val = param_dict[key]

        width = m.end() - m.start()
        formatted = _format_to_width(current_val, width, orig_token=orig)
        if len(formatted) != width:
            formatted = formatted[:width].rjust(width)
        new_chars[m.start() : m.end()] = list(formatted)

    lines[cultivar_idx] = "".join(new_chars) + "\n"
    
    with open(CUL_FILE, 'w') as f:
        f.writelines(lines)


def update_eco_file(param_csv_path=PARAM_CSV, target_ecotype=None):
    if not target_ecotype:
        return
    if not os.path.exists(param_csv_path):
        return
    if not os.path.exists(ECO_FILE):
        return

    try:
        param_dict = _read_param_dict(param_csv_path)
    except Exception as e:
        print(f"Error reading parameter CSV: {e}")
        return
    if not param_dict:
        return

    with open(ECO_FILE, "r") as f:
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

    headers = lines[header_idx].split()
    if len(headers) < 3:
        return
    param_names = headers[2:]

    eco_line = lines[eco_idx]
    number_re = re.compile(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?")
    matches = list(number_re.finditer(eco_line))
    if len(matches) < len(param_names):
        return

    param_matches = matches[-len(param_names):]
    new_chars = list(eco_line.rstrip("\n"))

    for name, m in zip(param_names, param_matches):
        orig = m.group(0)
        try:
            current_val = float(orig)
        except Exception:
            current_val = orig

        key = str(name).strip().upper()
        if key == "TM":
            if "ECO_TM" in param_dict:
                current_val = param_dict["ECO_TM"]
        else:
            if key in param_dict:
                current_val = param_dict[key]

        width = m.end() - m.start()
        formatted = _format_to_width(current_val, width, orig_token=orig)
        if len(formatted) != width:
            formatted = formatted[:width].rjust(width)
        new_chars[m.start() : m.end()] = list(formatted)

    lines[eco_idx] = "".join(new_chars) + "\n"
    with open(ECO_FILE, "w") as f:
        f.writelines(lines)


def update_spe_file(param_csv_path=PARAM_CSV):
    if not os.path.exists(param_csv_path):
        return
    if not os.path.exists(SPE_FILE):
        return

    try:
        param_dict = _read_param_dict(param_csv_path)
    except Exception as e:
        print(f"Error reading parameter CSV: {e}")
        return
    if not param_dict:
        return

    keys = [k for k in ["TB", "TO1", "TO2", "TM"] if k in param_dict]
    if not keys:
        return

    number_re = re.compile(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?")
    with open(SPE_FILE, "r") as f:
        lines = f.readlines()

    pheno_idx = -1
    for i, line in enumerate(lines):
        if line.strip().upper().startswith("!*PHENOLOGY PARAMETERS") or line.strip().upper().startswith("*PHENOLOGY PARAMETERS"):
            pheno_idx = i
            break

    if pheno_idx == -1:
        return

    for i in range(pheno_idx + 1, min(pheno_idx + 30, len(lines))):
        s = lines[i]
        if "DEVELOPMENT" not in s.upper():
            continue
        matches = list(number_re.finditer(s))
        if len(matches) < 4:
            continue

        new_chars = list(s.rstrip("\n"))
        for name, m in zip(["TB", "TO1", "TO2", "TM"], matches[:4]):
            if name not in param_dict:
                continue
            orig = m.group(0)
            width = m.end() - m.start()
            formatted = _format_to_width(float(param_dict[name]), width, orig_token=orig)
            if len(formatted) != width:
                formatted = formatted[:width].rjust(width)
            new_chars[m.start() : m.end()] = list(formatted)
        lines[i] = "".join(new_chars) + "\n"

    with open(SPE_FILE, "w") as f:
        f.writelines(lines)

def run_model():
    """Runs the DSSAT model."""
    print(f"Running {DSSAT_EXE} B {BATCH_FILE}...")
    
    try:
        cwd_script = os.path.dirname(os.path.abspath(__file__))
        filex_path = _resolve_filex_from_batch(BATCH_FILE, cwd_script)
        run_dir = os.path.dirname(os.path.abspath(filex_path)) if filex_path else cwd_script

        cleanup(cwd_script)
        cleanup(run_dir)

        exe_path = shutil.which(DSSAT_EXE)
        if not exe_path:
            candidate = os.path.normpath(os.path.join(cwd_script, "..", "..", DSSAT_EXE))
            exe_path = candidate if os.path.exists(candidate) else DSSAT_EXE

        try:
            shutil.copy(os.path.join(cwd_script, "DSSATPRO.v48"), os.path.join(run_dir, "DSSATPRO.v48"))
        except Exception:
            pass

        batch_src = BATCH_FILE
        if not os.path.isabs(batch_src):
            batch_src = os.path.join(cwd_script, BATCH_FILE)

        batch_dst_name = os.path.basename(BATCH_FILE) if BATCH_FILE else "DSSBatch.v48"
        if not batch_dst_name:
            batch_dst_name = "DSSBatch.v48"
        batch_dst = os.path.join(run_dir, batch_dst_name)
        try:
            shutil.copy(batch_src, batch_dst)
        except Exception:
            pass

        batch_arg = batch_dst_name
        
        start_time = time.time()
        
        # Run DSSAT
        # Note: DSCSM048.EXE requires the code (B) and batch file as arguments
        # It must be run in the directory containing the files
        result = subprocess.run(
            [exe_path, "B", batch_arg],
            cwd=run_dir,
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
            _sync_outputs_from_filex_dir(BATCH_FILE, cwd_script, OUTPUT_FILES)

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
                _write_pest_harvest_from_tmt_and_plantgro(BATCH_FILE, "PlantGro.OUT", PEST_HARVEST_FILE)
            except Exception as e:
                print(f"Warning: failed to write {PEST_HARVEST_FILE}: {e}")
            try:
                _write_pest_tmtgrow_from_tmt_and_plantgro(BATCH_FILE, "PlantGro.OUT", PEST_TMTGROW_FILE)
            except Exception as e:
                print(f"Warning: failed to write {PEST_TMTGROW_FILE}: {e}")

    except Exception as e:
        print(f"Exception running model: {e}")
        handle_failure(998)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--param-csv", default=PARAM_CSV)
    parser.add_argument("--batch", default=BATCH_FILE)
    parser.add_argument("--cultivar", default=None)
    args, _ = parser.parse_known_args()

    BATCH_FILE = args.batch

    cultivar = args.cultivar
    if not cultivar:
        filex = _first_batch_filex_path(BATCH_FILE)
        cultivar = _infer_cultivar_from_filex(filex)
    if not cultivar:
        cultivar = "TM0001"

    cleanup(".")
    update_cul_file(param_csv_path=args.param_csv, target_cultivar=cultivar)
    ecotype = _infer_ecotype_from_cul(CUL_FILE, cultivar) or "TM0001"
    update_eco_file(param_csv_path=args.param_csv, target_ecotype=ecotype)
    update_spe_file(param_csv_path=args.param_csv)
    run_model()
