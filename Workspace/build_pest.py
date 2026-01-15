import os
import argparse
import pandas as pd
import pyemu
import re

WORKSPACE = r"C:\DSSAT48\Tomato_Cal\Workspace"
CUL_BASE_FILE = os.path.join(WORKSPACE, "TMGRO048.CUL.base")
ECO_FILE = os.path.join(WORKSPACE, "TMGRO048.ECO")
SPE_FILE = os.path.join(WORKSPACE, "TMGRO048.SPE")
OUT_FILE = os.path.join(WORKSPACE, "Evaluate.OUT")
PEST_EVAL_FILE = os.path.join(WORKSPACE, "PestEval.OUT")
PEST_GROW_FILE = os.path.join(WORKSPACE, "PestGrow.OUT")
PEST_JOINT_FILE = os.path.join(WORKSPACE, "PestJoint.OUT")
PEST_HARVEST_FILE = os.path.join(WORKSPACE, "PestHarvest.OUT")
PEST_TMTGROW_FILE = os.path.join(WORKSPACE, "PestTmtGrow.OUT")

ECO_BOUNDS_EGGPLANT = {
    "PL-EM": (3.0, 12.0),
    "EM-V1": (10.0, 40.0),
    "V1-JU": (0.0, 0.0),
    "JU-R0": (2.0, 20.0),
    "FL-VS": (100.0, 100.0),
    "TRIFL": (0.20, 0.80),
    "RWDTH": (0.70, 1.60),
    "RHGHT": (0.70, 2.00),
    "OPTBI": (0.0, 20.0),
    "SLOBI": (-0.50, 0.0),
    "XMAGE": (5.0, 30.0),
    "XFPHT": (5.0, 40.0),
    "XFINT": (0.10, 1.20),
}

SPE_TEMP_BOUNDS_EGGPLANT = {
    "TB": (8.0, 12.0),
    "TO1": (22.0, 28.0),
    "TO2": (27.0, 32.0),
    "TM": (33.0, 40.0),
    "TB1": (8.0, 12.0),
    "TO11": (22.0, 28.0),
    "TO21": (27.0, 32.0),
    "TM1": (33.0, 40.0),
    "TB2": (8.0, 12.0),
    "TO12": (22.0, 28.0),
    "TO22": (27.0, 32.0),
    "TM2": (33.0, 40.0),
    "TB3": (8.0, 12.0),
    "TO13": (22.0, 28.0),
    "TO23": (27.0, 32.0),
    "TM3": (33.0, 40.0),
}


def _param_location_from_group(pargp):
    g = (pargp or "").strip().lower()
    if g == "cultivar":
        return "CUL"
    if g == "ecotype":
        return "ECO"
    if g == "species":
        return "SPE"
    return ""


def _param_file_from_location(location):
    loc = (location or "").strip().upper()
    if loc == "CUL":
        return os.path.basename(CUL_BASE_FILE)
    if loc == "ECO":
        return os.path.basename(ECO_FILE)
    if loc == "SPE":
        return os.path.basename(SPE_FILE)
    return ""


def write_param_review_csv(params, csv_path, cultivar=None, ecotype=None, mode=None):
    rows = []
    for p in params:
        pargp = p.get("pargp", "")
        location = _param_location_from_group(pargp)
        rows.append(
            {
                "name": p.get("name"),
                "init": p.get("init"),
                "lower": p.get("lower"),
                "upper": p.get("upper"),
                "status": p.get("status"),
                "pargp": pargp,
                "location": location,
                "file": _param_file_from_location(location),
                "cultivar": cultivar or "",
                "ecotype": ecotype or "",
                "mode": mode or "",
            }
        )

    df = pd.DataFrame(rows)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")


def _coerce_float(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        if pd.isna(v):
            return None
        return float(v)
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return None
    try:
        return float(s)
    except Exception:
        return None


def _coerce_str(v):
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s if s else None
    if pd.isna(v):
        return None
    s = str(v).strip()
    return s if s else None


def apply_param_review_csv(params, csv_path):
    if not csv_path or not os.path.exists(csv_path):
        return params

    df = pd.read_csv(csv_path)
    if df.empty:
        return params

    cols_lower = {str(c).strip().lower(): c for c in df.columns}

    def _col(*names):
        for n in names:
            key = str(n).strip().lower()
            if key in cols_lower:
                return cols_lower[key]
        return None

    name_col = _col("name", "parnme", "parameter")
    if name_col is None:
        return params

    init_col = _col("init", "initial", "value", "parval1")
    lb_col = _col("lower", "lb", "parlbnd")
    ub_col = _col("upper", "ub", "parubnd")
    status_col = _col("status", "partrans")
    pargp_col = _col("pargp", "group")

    by_name = {}
    for _, r in df.iterrows():
        k = _coerce_str(r.get(name_col))
        if not k:
            continue
        by_name[k.strip().lower()] = r

    for p in params:
        k = str(p.get("name", "")).strip().lower()
        if not k or k not in by_name:
            continue
        r = by_name[k]

        init_v = _coerce_float(r.get(init_col)) if init_col else None
        lb_v = _coerce_float(r.get(lb_col)) if lb_col else None
        ub_v = _coerce_float(r.get(ub_col)) if ub_col else None
        status_v = _coerce_str(r.get(status_col)) if status_col else None
        pargp_v = _coerce_str(r.get(pargp_col)) if pargp_col else None

        if lb_v is not None:
            p["lower"] = float(lb_v)
        if ub_v is not None:
            p["upper"] = float(ub_v)
        if init_v is not None:
            p["init"] = float(init_v)
        if status_v is not None:
            p["status"] = str(status_v)
        if pargp_v is not None:
            p["pargp"] = str(pargp_v)

        try:
            lb = float(p.get("lower"))
            ub = float(p.get("upper"))
            if lb > ub:
                p["lower"], p["upper"] = ub, lb
                lb, ub = ub, lb
            init = float(p.get("init"))
            if init < lb:
                p["init"] = lb
            elif init > ub:
                p["init"] = ub
        except Exception:
            pass

        if float(p.get("lower", 0.0)) == float(p.get("upper", 0.0)):
            p["status"] = "fixed"

    return params


def _parse_batch_entries(batch_file):
    entries = []
    if not batch_file or not os.path.exists(batch_file):
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


def _infer_ecotype_from_cul_base(target_cultivar):
    if not target_cultivar or not os.path.exists(CUL_BASE_FILE):
        return None
    number_re = re.compile(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?")
    with open(CUL_BASE_FILE, "r") as f:
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


def _read_eco_init_values(target_ecotype):
    if not target_ecotype or not os.path.exists(ECO_FILE):
        return {}

    header_idx = -1
    eco_idx = -1
    with open(ECO_FILE, "r") as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        if line.startswith("@ECO#"):
            header_idx = i
        elif line.startswith(target_ecotype):
            eco_idx = i

    if header_idx == -1 or eco_idx == -1:
        return {}

    headers = lines[header_idx].split()
    if len(headers) < 3:
        return {}
    param_names = headers[2:]

    eco_line = lines[eco_idx]
    number_re = re.compile(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?")
    matches = [m.group(0) for m in number_re.finditer(eco_line)]
    if len(matches) < len(param_names):
        return {}

    vals = matches[-len(param_names) :]
    out = {}
    for name, v in zip(param_names, vals):
        try:
            out[str(name).strip().upper()] = float(v)
        except Exception:
            continue
    return out


def _read_spe_temp_init_values():
    if not os.path.exists(SPE_FILE):
        return {}

    number_re = re.compile(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?")
    with open(SPE_FILE, "r") as f:
        lines = f.readlines()

    pheno_idx = -1
    for i, line in enumerate(lines):
        if line.strip().upper().startswith("!*PHENOLOGY PARAMETERS") or line.strip().upper().startswith("*PHENOLOGY PARAMETERS"):
            pheno_idx = i
            break
    if pheno_idx == -1:
        return {}

    def _stage_for_line(line):
        u = (line or "").upper()
        if "VEGETATIVE DEVELOPMENT" in u:
            return 1
        if "EARLY REPRODUCTIVE DEVELOPMENT" in u:
            return 2
        if "LATE REPRODUCTIVE DEVELOPMENT" in u:
            return 3
        return None

    out = {}
    for i in range(pheno_idx + 1, min(pheno_idx + 60, len(lines))):
        s = lines[i]
        if "DEVELOPMENT" not in s.upper():
            continue
        stage = _stage_for_line(s)
        if stage is None:
            continue
        matches = [m.group(0) for m in number_re.finditer(s)]
        if len(matches) < 4:
            continue
        try:
            tb, to1, to2, tm = (float(matches[0]), float(matches[1]), float(matches[2]), float(matches[3]))
        except Exception:
            continue

        out[f"TB{stage}"] = tb
        out[f"TO1{stage}"] = to1
        out[f"TO2{stage}"] = to2
        out[f"TM{stage}"] = tm

        if stage == 1:
            out["TB"] = tb
            out["TO1"] = to1
            out["TO2"] = to2
            out["TM"] = tm

    return out


def parse_extra_params(init_map, bounds_map, allowed_params=None, pargp="ecotype"):
    params = []
    for name_raw, (lb, ub) in (bounds_map or {}).items():
        name = str(name_raw).strip().upper()
        if allowed_params is not None and name not in {str(a).strip().upper() for a in allowed_params}:
            continue
        init = init_map.get(name)
        if init is None:
            init = (float(lb) + float(ub)) / 2.0
        status = "none" if float(lb) != float(ub) else "fixed"
        params.append(
            {
                "name": name_raw,
                "init": float(init),
                "lower": float(lb),
                "upper": float(ub),
                "idx": None,
                "status": status,
                "pargp": str(pargp),
            }
        )
    return params


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
        chfpw = _as_float(r.get("CHFPW"), default=-99.0)
        hfpow = _as_float(r.get("HFPOW"), default=-99.0)
        if all(v == -99.0 for v in [chpdt, hpodw, pwad, chfpw, hfpow]):
            continue

        events_by_tn.setdefault(tn, []).append(
            {
                "date": date,
                "chpdt": chpdt,
                "hpodw": hpodw,
                "pwad": pwad,
                "chfpw": chfpw,
                "hfpow": hfpow,
            }
        )

    out = {}
    for tn, evs in events_by_tn.items():
        evs_sorted = sorted(evs, key=lambda x: x["date"])
        dry_cum = 0.0
        fresh_cum = 0.0
        out_list = []
        for idx, e in enumerate(evs_sorted, start=1):
            if e["chpdt"] != -99.0:
                dry_cum = float(e["chpdt"])
            else:
                if e.get("hpodw", -99.0) != -99.0:
                    inc = float(e["hpodw"])
                elif e.get("pwad", -99.0) != -99.0:
                    inc = float(e["pwad"])
                else:
                    inc = 0.0
                dry_cum += inc

            if e["chfpw"] != -99.0:
                fresh_cum = float(e["chfpw"])
            else:
                inc = 0.0 if e["hfpow"] == -99.0 else float(e["hfpow"])
                fresh_cum += inc

            out_list.append(
                {
                    "hno": idx,
                    "date": int(e["date"]),
                    "dry_cum": float(dry_cum)
                    if e["chpdt"] != -99.0 or e.get("hpodw", -99.0) != -99.0 or e.get("pwad", -99.0) != -99.0
                    else -99.0,
                    "fresh_cum": float(fresh_cum) if e["chfpw"] != -99.0 or e["hfpow"] != -99.0 else -99.0,
                }
            )
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
            if not stripped[:1].isdigit():
                continue

            parts = stripped.split()
            if len(parts) < len(header):
                parts += ["-99"] * (len(header) - len(parts))
            rows.append(dict(zip(header, parts[: len(header)])))

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    for c in df.columns:
        if c in {"EXCODE", "CR"}:
            continue
        as_num = pd.to_numeric(df[c], errors="coerce")
        if as_num.notna().sum() >= max(1, int(0.8 * len(df))):
            df[c] = as_num.fillna(-99)

    return df

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


def _evaluate_out_path_from_batch(batch_file, fallback=OUT_FILE):
    filex = _first_batch_filex_path(batch_file)
    if not filex:
        return fallback
    filex_path = filex if os.path.isabs(filex) else os.path.join(WORKSPACE, filex)
    eval_path = os.path.join(os.path.dirname(os.path.abspath(filex_path)), "Evaluate.OUT")
    if os.path.exists(eval_path):
        return eval_path
    return fallback

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

def parse_cul_params(target_cultivar, allowed_params=None):
    with open(CUL_BASE_FILE, 'r') as f:
        lines = f.readlines()

    header_idx = -1
    calib_idx = -1
    min_idx = -1
    max_idx = -1
    cultivar_idx = -1

    for i, line in enumerate(lines):
        if line.startswith("@VAR#"):
            header_idx = i
        elif line.startswith("!Calibration"):
            calib_idx = i
        elif "MINIMA" in line:
            min_idx = i
        elif "MAXIMA" in line:
            max_idx = i
        elif target_cultivar and line.startswith(target_cultivar):
            cultivar_idx = i

    if any(idx == -1 for idx in [header_idx, calib_idx, min_idx, max_idx, cultivar_idx]):
        raise ValueError("Could not find all required sections in TMGRO048.CUL.base")

    headers = lines[header_idx].split()
    param_names = headers[4:]

    calib_flags = lines[calib_idx].split()[1:]

    number_re = re.compile(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?")

    def _last_n_numbers(line, n):
        matches = [m.group(0) for m in number_re.finditer(line)]
        if len(matches) < n:
            raise ValueError(f"Not enough numeric tokens in line for {n} params")
        return matches[-n:]

    n_params = len(param_names)
    min_vals = _last_n_numbers(lines[min_idx], n_params)
    max_vals = _last_n_numbers(lines[max_idx], n_params)
    init_vals = _last_n_numbers(lines[cultivar_idx], n_params)

    params = []
    for i, name in enumerate(param_names):
        if i >= len(calib_flags):
            continue
        if allowed_params is not None and name not in allowed_params:
            continue
        flag = calib_flags[i]
        if flag not in ['P', 'G']:
            continue
        p_min = float(min_vals[i])
        p_max = float(max_vals[i])
        p_init = float(init_vals[i])
        status = "none"
        if p_min == p_max:
            status = "fixed"
        params.append({
            "name": name,
            "init": p_init,
            "lower": p_min,
            "upper": p_max,
            "idx": i,
            "status": status,
            "pargp": "cultivar",
        })

    return params

def create_param_csv_tpl(params, param_csv_tpl_path):
    with open(param_csv_tpl_path, 'w') as f:
        f.write("ptf ~\n")
        f.write("name,value\n")
        for p in params:
            f.write(f"{p['name']},~ {p['name']} ~\n")

def create_param_csv(params, param_csv_path):
    with open(param_csv_path, "w") as f:
        f.write("name,value\n")
        for p in params:
            f.write(f"{p['name']},{p['init']}\n")

def create_ins_and_pst(
    params,
    prefix,
    noptmax,
    ies_num_reals,
    obs_bases=None,
    critical_obs=None,
    model_out_path=OUT_FILE,
    group_sigmas=None,
    evaluate_out_path=OUT_FILE,
    df_override=None,
    model_cmd_extra=None,
):
    if df_override is not None:
        df = df_override.copy()
    else:
        try:
            df = _read_evaluate_out(evaluate_out_path)
        except Exception as e:
            print(f"Warning: Could not read model output file: {e}.")
            return

    param_csv_tpl_path = os.path.join(WORKSPACE, f"{prefix}_params.csv.tpl")
    param_csv_path = os.path.join(WORKSPACE, f"{prefix}_params.csv")
    ins_path = os.path.join(WORKSPACE, f"{prefix}_{os.path.basename(model_out_path)}.ins")
    pst_path = os.path.join(WORKSPACE, f"{prefix}.pst")

    obs_cols = [c for c in df.columns if isinstance(c, str) and c.endswith('M')]
    sim_cols = [c[:-1] + 'S' for c in obs_cols]

    if obs_bases is not None:
        filtered = []
        for o, s in zip(obs_cols, sim_cols):
            if o[:-1] in obs_bases:
                filtered.append((o, s))
        obs_cols = [o for o, _ in filtered]
        sim_cols = [s for _, s in filtered]

    critical_obs = set(critical_obs or [])

    def get_pest_offset(col_idx):
        return 0

    obs_data = []
    model_out_norm = os.path.normcase(os.path.abspath(model_out_path))
    is_tagged_output = model_out_norm in {
        os.path.normcase(os.path.abspath(PEST_EVAL_FILE)),
        os.path.normcase(os.path.abspath(PEST_GROW_FILE)),
        os.path.normcase(os.path.abspath(PEST_JOINT_FILE)),
        os.path.normcase(os.path.abspath(PEST_HARVEST_FILE)),
        os.path.normcase(os.path.abspath(PEST_TMTGROW_FILE)),
    }
    if is_tagged_output:
        ins_lines = ["pif @"]
    else:
        ins_lines = ["pif @", "l3"]

    col_names = df.columns.tolist()
    for _, row in df.iterrows():
        if "@RUN" in row.index:
            run_no = int(row['@RUN'])
        else:
            run_no = int(row["RUN"])

        suffix = ""
        if "HNO" in row.index:
            try:
                suffix = f"_H{int(row['HNO'])}"
            except Exception:
                suffix = ""
        elif "DATE" in row.index:
            try:
                suffix = f"_D{int(row['DATE'])}"
            except Exception:
                suffix = ""

        current_ins_line = "l1 "

        valid_obs = []
        for obs_col, sim_col in zip(obs_cols, sim_cols):
            val = row[obs_col]
            if val != -99 or obs_col in critical_obs:
                valid_obs.append((obs_col, sim_col, val))

        if not valid_obs:
            ins_lines.append(current_ins_line)
            continue

        if not is_tagged_output:
            valid_obs.sort(key=lambda x: col_names.index(x[1]))

        last_idx = -1
        for obs_col, sim_col, val in valid_obs:
            obs_name = f"{sim_col}_R{run_no}{suffix}"
            if is_tagged_output:
                current_ins_line += f"@{sim_col}@ w !{obs_name}! "
            else:
                col_idx = col_names.index(sim_col)
                target_idx = col_idx + get_pest_offset(col_idx)
                skips = target_idx - last_idx - 1
                if skips < 0:
                    skips = 0
                current_ins_line += "w " * skips
                current_ins_line += f"!{obs_name}! "

            if val == -99:
                weight = 0.0
            else:
                if group_sigmas is None:
                    weight = 1.0
                else:
                    obgnme = f"{obs_col}{suffix}" if suffix else obs_col
                    sigma = float(group_sigmas.get(obgnme, group_sigmas.get(obs_col, 1.0)))
                    if sigma <= 0:
                        sigma = 1.0
                    weight = 1.0 / (sigma ** 2)

            obs_data.append({
                "obsnme": obs_name,
                "obsval": val if val != -99 else 0,
                "weight": weight,
                "obgnme": f"{obs_col}{suffix}" if suffix else obs_col
            })
            if not is_tagged_output:
                last_idx = target_idx

        ins_lines.append(current_ins_line)

    with open(ins_path, 'w') as f:
        f.write("\n".join(ins_lines))

    create_param_csv_tpl(params, param_csv_tpl_path)
    create_param_csv(params, param_csv_path)

    par_df = pd.DataFrame([{
        "parnme": p['name'],
        "parval1": p['init'],
        "parlbnd": p['lower'],
        "parubnd": p['upper'],
        "pargp": p.get('pargp', 'cultivar'),
        "scale": 1.0,
        "offset": 0.0,
        "partrans": p['status']
    } for p in params])

    obs_df = pd.DataFrame(obs_data)

    pst = pyemu.Pst.from_par_obs_names(par_df.parnme, obs_df.obsnme if not obs_df.empty else [])

    par_df_indexed = par_df.set_index('parnme')
    for col in ['parval1', 'parlbnd', 'parubnd', 'pargp', 'partrans']:
        pst.parameter_data.loc[par_df.parnme, col] = par_df_indexed[col].values

    fixed_pars = par_df[par_df['parlbnd'] == par_df['parubnd']]['parnme']
    if not fixed_pars.empty:
        pst.parameter_data.loc[fixed_pars, 'partrans'] = 'fixed'

    zero_pars = par_df[(par_df['parval1'] == 0) & (par_df['parlbnd'] != par_df['parubnd'])]['parnme']
    if not zero_pars.empty:
        pst.parameter_data.loc[zero_pars, 'partrans'] = 'none'

    if not obs_df.empty:
        pst.observation_data.loc[obs_df.obsnme, 'obsval'] = obs_df.set_index('obsnme')['obsval']
        pst.observation_data.loc[obs_df.obsnme, 'obgnme'] = obs_df.set_index('obsnme')['obgnme']
        pst.observation_data.loc[obs_df.obsnme, 'weight'] = obs_df.set_index('obsnme')['weight']

    pst.control_data.noptmax = noptmax
    pst.pestpp_options["ies_num_reals"] = ies_num_reals
    pst.pestpp_options["ies_bad_phi_sigma"] = 2.0
    pst.pestpp_options["overdue_giveup_fac"] = 4.0

    cmd = f"python run_dssat.py --param-csv {os.path.basename(param_csv_path)}"
    if model_cmd_extra:
        cmd = f"{cmd} {str(model_cmd_extra).strip()}"
    pst.model_command = [cmd]
    pst.model_input_data = pd.DataFrame({"pest_file": [os.path.basename(param_csv_tpl_path)], "model_file": [os.path.basename(param_csv_path)]})
    pst.model_output_data = pd.DataFrame({"pest_file": [os.path.basename(ins_path)], "model_file": [os.path.basename(model_out_path)]})

    pst.write(pst_path)
    print(f"PST file written to {pst_path}")


def _is_tagged_output(model_out_path):
    model_out_norm = os.path.normcase(os.path.abspath(model_out_path))
    return model_out_norm in {
        os.path.normcase(os.path.abspath(PEST_EVAL_FILE)),
        os.path.normcase(os.path.abspath(PEST_GROW_FILE)),
        os.path.normcase(os.path.abspath(PEST_JOINT_FILE)),
        os.path.normcase(os.path.abspath(PEST_HARVEST_FILE)),
        os.path.normcase(os.path.abspath(PEST_TMTGROW_FILE)),
    }


def _build_ins_and_obs(df, obs_bases, critical_obs, model_out_path, group_sigmas):
    obs_cols = [c for c in df.columns if isinstance(c, str) and c.endswith('M')]
    sim_cols = [c[:-1] + 'S' for c in obs_cols]

    if obs_bases is not None:
        filtered = []
        for o, s in zip(obs_cols, sim_cols):
            if o[:-1] in obs_bases:
                filtered.append((o, s))
        obs_cols = [o for o, _ in filtered]
        sim_cols = [s for _, s in filtered]

    critical_obs = set(critical_obs or [])

    def get_pest_offset(col_idx):
        return 0

    obs_data = []
    is_tagged_output = _is_tagged_output(model_out_path)
    ins_lines = ["pif @"] if is_tagged_output else ["pif @", "l3"]

    col_names = df.columns.tolist()
    for _, row in df.iterrows():
        if "@RUN" in row.index:
            run_no = int(row['@RUN'])
        else:
            run_no = int(row["RUN"])

        suffix = ""
        if "HNO" in row.index:
            try:
                suffix = f"_H{int(row['HNO'])}"
            except Exception:
                suffix = ""
        elif "DATE" in row.index:
            try:
                suffix = f"_D{int(row['DATE'])}"
            except Exception:
                suffix = ""

        current_ins_line = "l1 "

        valid_obs = []
        for obs_col, sim_col in zip(obs_cols, sim_cols):
            val = row[obs_col]
            if val != -99 or obs_col in critical_obs:
                valid_obs.append((obs_col, sim_col, val))

        if not valid_obs:
            ins_lines.append(current_ins_line)
            continue

        if not is_tagged_output:
            valid_obs.sort(key=lambda x: col_names.index(x[1]))

        last_idx = -1
        for obs_col, sim_col, val in valid_obs:
            obs_name = f"{sim_col}_R{run_no}{suffix}"
            if is_tagged_output:
                current_ins_line += f"@{sim_col}@ w !{obs_name}! "
            else:
                col_idx = col_names.index(sim_col)
                target_idx = col_idx + get_pest_offset(col_idx)
                skips = target_idx - last_idx - 1
                if skips < 0:
                    skips = 0
                current_ins_line += "w " * skips
                current_ins_line += f"!{obs_name}! "

            if val == -99:
                weight = 0.0
            else:
                if group_sigmas is None:
                    weight = 1.0
                else:
                    obgnme = f"{obs_col}{suffix}" if suffix else obs_col
                    sigma = float(group_sigmas.get(obgnme, group_sigmas.get(obs_col, 1.0)))
                    if sigma <= 0:
                        sigma = 1.0
                    weight = 1.0 / (sigma ** 2)

            obs_data.append(
                {
                    "obsnme": obs_name,
                    "obsval": val if val != -99 else 0,
                    "weight": weight,
                    "obgnme": f"{obs_col}{suffix}" if suffix else obs_col,
                }
            )
            if not is_tagged_output:
                last_idx = target_idx

        ins_lines.append(current_ins_line)

    return obs_data, ins_lines


def _populate_pst_from_par_obs(pst, par_df, obs_df):
    par_df_indexed = par_df.set_index('parnme')
    for col in ['parval1', 'parlbnd', 'parubnd', 'pargp', 'partrans']:
        pst.parameter_data.loc[par_df.parnme, col] = par_df_indexed[col].values

    fixed_pars = par_df[par_df['parlbnd'] == par_df['parubnd']]['parnme']
    if not fixed_pars.empty:
        pst.parameter_data.loc[fixed_pars, 'partrans'] = 'fixed'

    zero_pars = par_df[(par_df['parval1'] == 0) & (par_df['parlbnd'] != par_df['parubnd'])]['parnme']
    if not zero_pars.empty:
        pst.parameter_data.loc[zero_pars, 'partrans'] = 'none'

    if not obs_df.empty:
        pst.observation_data.loc[obs_df.obsnme, 'obsval'] = obs_df.set_index('obsnme')['obsval']
        pst.observation_data.loc[obs_df.obsnme, 'obgnme'] = obs_df.set_index('obsnme')['obgnme']
        pst.observation_data.loc[obs_df.obsnme, 'weight'] = obs_df.set_index('obsnme')['weight']


def create_ins_and_pst_multi(
    params,
    prefix,
    noptmax,
    ies_num_reals,
    outputs,
    evaluate_out_path=OUT_FILE,
    model_cmd_extra=None,
):
    try:
        eval_df = _read_evaluate_out(evaluate_out_path)
    except Exception as e:
        print(f"Warning: Could not read model output file: {e}.")
        return

    param_csv_tpl_path = os.path.join(WORKSPACE, f"{prefix}_params.csv.tpl")
    param_csv_path = os.path.join(WORKSPACE, f"{prefix}_params.csv")
    pst_path = os.path.join(WORKSPACE, f"{prefix}.pst")

    create_param_csv_tpl(params, param_csv_tpl_path)
    create_param_csv(params, param_csv_path)

    par_df = pd.DataFrame([
        {
            "parnme": p['name'],
            "parval1": p['init'],
            "parlbnd": p['lower'],
            "parubnd": p['upper'],
            "pargp": p.get('pargp', 'cultivar'),
            "scale": 1.0,
            "offset": 0.0,
            "partrans": p['status'],
        }
        for p in params
    ])

    obs_data_all = []
    model_output_rows = []

    for out in outputs:
        model_out_path = out["model_out_path"]
        df = out.get("df")
        if df is None:
            df = eval_df

        obs_data, ins_lines = _build_ins_and_obs(
            df=df,
            obs_bases=out.get("obs_bases"),
            critical_obs=out.get("critical_obs"),
            model_out_path=model_out_path,
            group_sigmas=out.get("group_sigmas"),
        )
        obs_data_all.extend(obs_data)

        ins_path = os.path.join(WORKSPACE, f"{prefix}_{os.path.basename(model_out_path)}.ins")
        with open(ins_path, 'w') as f:
            f.write("\n".join(ins_lines))

        model_output_rows.append(
            {"pest_file": os.path.basename(ins_path), "model_file": os.path.basename(model_out_path)}
        )

    obs_df = pd.DataFrame(obs_data_all)
    pst = pyemu.Pst.from_par_obs_names(par_df.parnme, obs_df.obsnme if not obs_df.empty else [])
    _populate_pst_from_par_obs(pst, par_df, obs_df)

    pst.control_data.noptmax = noptmax
    pst.pestpp_options["ies_num_reals"] = ies_num_reals
    pst.pestpp_options["ies_bad_phi_sigma"] = 2.0
    pst.pestpp_options["overdue_giveup_fac"] = 4.0

    cmd = f"python run_dssat.py --param-csv {os.path.basename(param_csv_path)}"
    if model_cmd_extra:
        cmd = f"{cmd} {str(model_cmd_extra).strip()}"
    pst.model_command = [cmd]
    pst.model_input_data = pd.DataFrame(
        {"pest_file": [os.path.basename(param_csv_tpl_path)], "model_file": [os.path.basename(param_csv_path)]}
    )
    pst.model_output_data = pd.DataFrame(model_output_rows)

    pst.write(pst_path)
    print(f"PST file written to {pst_path}")


def _load_init_overrides(csv_path):
    if not csv_path or not os.path.exists(csv_path):
        return {}
    df = pd.read_csv(csv_path)
    cols = [str(c) for c in df.columns]

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
        else:
            return {}

    out = {}
    for _, r in df.iterrows():
        k = str(r.get(name_col, "")).strip()
        if not k or k.lower() == "nan":
            continue
        try:
            v = float(r.get(value_col))
        except Exception:
            continue
        out[k.lower()] = v
    return out

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="tomato_full")
    parser.add_argument("--prefix", default=None)
    parser.add_argument("--noptmax", type=int, default=5)
    parser.add_argument("--ies-num-reals", type=int, default=50)
    parser.add_argument("--batch", default=os.path.join(WORKSPACE, "DSSBatch.v48"))
    parser.add_argument("--init-from", action="append", default=None)
    parser.add_argument(
        "--param-review-mode",
        choices=["auto", "export", "import", "off"],
        default="auto",
    )
    parser.add_argument("--param-review-csv", default=None)
    parser.add_argument("--pwadm-sigma0", type=float, default=250.0)
    parser.add_argument("--pwadm-cv", type=float, default=0.08)
    parser.add_argument("--pwadm-sigma-factor", type=float, default=1.0)
    parser.add_argument("--harvest-var", default="CHPDT")
    args = parser.parse_args()

    mode = (args.mode or "").strip().lower()
    filex = _first_batch_filex_path(args.batch)
    cultivar = _infer_cultivar_from_filex(filex) or "TM0001"
    ecotype = _infer_ecotype_from_cul_base(cultivar) or "TM0001"
    evaluate_out_path = _evaluate_out_path_from_batch(args.batch)

    df_override = None
    stage2_outputs = None

    harvest_var = (args.harvest_var or "CHPDT").strip().upper()
    model_cmd_extra = f"--batch {os.path.basename(args.batch)} --harvest-var {harvest_var}"

    if mode == "eggplant_pheno":
        prefix = args.prefix or "eggplant_pheno"
        allowed = {"CSDL", "PPSEN", "EM-FL", "FL-SH", "FL-SD", "SD-PM", "FL-LF"}
        obs_bases = {'ADAP'}
        critical = {'ADAPM'}
        model_out_path = PEST_EVAL_FILE
        group_sigmas = {
            "ADAPM": 3.0,
        }
        extra_allowed = None
    elif mode == "eggplant_growth":
        prefix = args.prefix or "eggplant_growth"
        allowed = {"SLAVR", "SIZLF", "LFMAX", "XFRT", "WTPSD", "SFDUR", "SDPDV", "PODUR"}
        obs_bases = {"HWAM", "LAIX", "CNAM"}
        critical = set()
        model_out_path = PEST_GROW_FILE
        group_sigmas = {
            "HWAMM": 500.0,
            "LAIXM": 0.8,
            "CNAMM": 25.0,
        }
        extra_allowed = None
    elif mode == "eggplant_joint":
        prefix = args.prefix or "eggplant_joint"
        allowed = {"SLAVR", "SIZLF", "LFMAX", "XFRT", "WTPSD", "SFDUR", "SDPDV", "PODUR"}
        obs_bases = {"HWAM", "LAIX", "CNAM", "CHTA", "CNAA", "PWAM", "H#AM", "HIAM"}
        critical = set()
        model_out_path = PEST_JOINT_FILE
        group_sigmas = {
            "HWAMM": 500.0,
            "PWAMM": 200.0,
            "LAIXM": 0.8,
            "CNAMM": 25.0,
            "CHTAM": 15.0,
            "CNAAM": 20.0,
            "H#AMM": 50.0,
            "HIAMM": 0.10,
        }
        extra_allowed = {"XMAGE", "FL-VS", "TRIFL", "RWDTH", "RHGHT"}
    elif mode == "eggplant_stage2":
        prefix = args.prefix or "eggplant_stage2"
        allowed = {
            "CSDL",
            "PPSEN",
            "EM-FL",
            "FL-SH",
            "FL-SD",
            "SD-PM",
            "FL-LF",
            "SLAVR",
            "SIZLF",
            "LFMAX",
            "XFRT",
            "WTPSD",
            "SFDUR",
            "SDPDV",
            "PODUR",
            "THRSH",
        }
        extra_allowed = {
            "XMAGE",
            "FL-VS",
            "TRIFL",
            "RWDTH",
            "RHGHT",
            "XFPHT",
            "XFINT",
            "PL-EM",
            "EM-V1",
            "V1-JU",
            "JU-R0",
            "TB",
            "TO1",
            "TO2",
            "TM",
        }

        entries = _parse_batch_entries(args.batch)

        if not entries:
            df_harvest = pd.DataFrame(columns=["@RUN", "TN", "HNO", "DATE", "PWADM", "PWADS"])
            harvest_sigmas = {"PWADM": 1.0}
            df_process = pd.DataFrame(
                columns=["@RUN", "TN", "DATE", "LAIDM", "LWADM", "SWADM", "LAIDS", "LWADS", "SWADS"]
            )
            process_sigmas = {"LAIDM": 2.0, "LWADM": 150.0, "SWADM": 200.0}
        else:
            filex = entries[0]["filex"]
            filex_path = filex if os.path.isabs(filex) else os.path.join(WORKSPACE, filex)
            excode = _infer_excode_from_filex(filex_path)
            tmt_path = os.path.join(os.path.dirname(os.path.abspath(filex_path)), f"{excode}.TMT") if excode else None

            events_by_tn = _read_tmt_harvest_events(tmt_path)
            points_by_tn = _read_tmt_process_points(tmt_path)

            harvest_rows = []
            process_rows = []

            for e in entries:
                run_no = int(e["run"])
                tn = int(e.get("tn", -99))

                for ev in events_by_tn.get(tn, []):
                    obs_cum = ev.get("dry_cum", -99.0) if harvest_var == "CHPDT" else ev.get("fresh_cum", -99.0)
                    harvest_rows.append(
                        {
                            "@RUN": run_no,
                            "TN": tn,
                            "HNO": int(ev["hno"]),
                            "DATE": int(ev["date"]),
                            "PWADM": float(obs_cum),
                            "PWADS": -99.0,
                        }
                    )

                for p in points_by_tn.get(tn, []):
                    process_rows.append(
                        {
                            "@RUN": run_no,
                            "TN": tn,
                            "DATE": int(p["date"]),
                            "LAIDM": float(p["laid"]),
                            "LWADM": float(p["lwad"]),
                            "SWADM": float(p["swad"]),
                            "LAIDS": -99.0,
                            "LWADS": -99.0,
                            "SWADS": -99.0,
                        }
                    )

            df_harvest = pd.DataFrame(harvest_rows)
            df_process = pd.DataFrame(process_rows)

            harvest_sigmas = {"PWADM": 1.0}
            if not df_harvest.empty:
                for hno, g in df_harvest.groupby("HNO"):
                    med = float(g["PWADM"].median())
                    sigma0 = float(args.pwadm_sigma0)
                    cv = float(args.pwadm_cv)
                    sigma_factor = float(args.pwadm_sigma_factor)
                    sigma = (sigma0**2 + (cv * abs(med)) ** 2) ** 0.5
                    sigma = sigma * sigma_factor
                    harvest_sigmas[f"PWADM_H{int(hno)}"] = float(sigma)

            process_sigmas = {"LAIDM": 2.0, "LWADM": 150.0, "SWADM": 200.0}
            if not df_process.empty:
                for var, sigma0, cv in [
                    ("LAIDM", 1.6, 0.50),
                    ("LWADM", 80.0, 0.25),
                    ("SWADM", 100.0, 0.25),
                ]:
                    g = df_process[df_process[var] != -99.0]
                    if g.empty:
                        continue
                    for date, gg in g.groupby("DATE"):
                        med = float(gg[var].median())
                        sigma = (sigma0**2 + (cv * abs(med)) ** 2) ** 0.5
                        process_sigmas[f"{var}_D{int(date)}"] = float(sigma)

        stage2_outputs = [
            {
                "model_out_path": PEST_EVAL_FILE,
                "obs_bases": {"ADAP"},
                "critical_obs": {"ADAPM"},
                "group_sigmas": {"ADAPM": 20.0},
            },
            {
                "model_out_path": PEST_JOINT_FILE,
                "obs_bases": {"HWAM", "LAIX", "CNAM", "CHTA", "CNAA", "PWAM", "H#AM", "HIAM"},
                "critical_obs": set(),
                "group_sigmas": {
                    "HWAMM": 500.0,
                    "PWAMM": 200.0,
                    "LAIXM": 0.8,
                    "CNAMM": 25.0,
                    "CHTAM": 15.0,
                    "CNAAM": 20.0,
                    "H#AMM": 50.0,
                    "HIAMM": 0.10,
                },
            },
            {
                "model_out_path": PEST_HARVEST_FILE,
                "obs_bases": {"PWAD"},
                "critical_obs": set(),
                "group_sigmas": harvest_sigmas,
                "df": df_harvest,
            },
            {
                "model_out_path": PEST_TMTGROW_FILE,
                "obs_bases": {"LAID", "LWAD", "SWAD"},
                "critical_obs": set(),
                "group_sigmas": process_sigmas,
                "df": df_process,
            },
        ]
    elif mode == "eggplant_harvest":
        prefix = args.prefix or "eggplant_harvest"
        allowed = {"SLAVR", "SIZLF", "LFMAX", "XFRT", "WTPSD", "SFDUR", "SDPDV", "PODUR"}
        obs_bases = {"PWAD"}
        critical = set()
        model_out_path = PEST_HARVEST_FILE

        entries = _parse_batch_entries(args.batch)
        if not entries:
            print("Warning: batch file is empty; no harvest observations will be created.")
            df_override = pd.DataFrame(columns=["@RUN", "TN", "HNO", "DATE", "PWADM", "PWADS"])
            group_sigmas = {"PWADM": 1.0}
        else:
            filex = entries[0]["filex"]
            filex_path = filex if os.path.isabs(filex) else os.path.join(WORKSPACE, filex)
            excode = _infer_excode_from_filex(filex_path)
            tmt_path = os.path.join(os.path.dirname(os.path.abspath(filex_path)), f"{excode}.TMT") if excode else None

            events_by_tn = _read_tmt_harvest_events(tmt_path)

            rows = []
            for e in entries:
                run_no = int(e["run"])
                tn = int(e.get("tn", -99))
                for ev in events_by_tn.get(tn, []):
                    obs_cum = ev.get("dry_cum", -99.0) if harvest_var == "CHPDT" else ev.get("fresh_cum", -99.0)
                    rows.append({
                        "@RUN": run_no,
                        "TN": tn,
                        "HNO": int(ev["hno"]),
                        "DATE": int(ev["date"]),
                        "PWADM": float(obs_cum),
                        "PWADS": -99.0,
                    })

            df_override = pd.DataFrame(rows)
            if df_override.empty:
                group_sigmas = {"PWADM": 1.0}
            else:
                group_sigmas = {"PWADM": 1.0}
                for hno, g in df_override.groupby("HNO"):
                    med = float(g["PWADM"].median())
                    sigma0 = float(args.pwadm_sigma0)
                    cv = float(args.pwadm_cv)
                    sigma_factor = float(args.pwadm_sigma_factor)
                    sigma = (sigma0 ** 2 + (cv * abs(med)) ** 2) ** 0.5
                    sigma = sigma * sigma_factor
                    group_sigmas[f"PWADM_H{int(hno)}"] = float(sigma)
        extra_allowed = {"XMAGE", "FL-VS", "TRIFL"}
    elif mode == "eggplant_v13":
        prefix = args.prefix or "eggplant_v13"
        allowed = {
            "CSDL",
            "PPSEN",
            "EM-FL",
            "FL-SH",
            "FL-SD",
            "SD-PM",
            "FL-LF",
            "SLAVR",
            "SIZLF",
            "LFMAX",
            "XFRT",
            "WTPSD",
            "SFDUR",
            "SDPDV",
            "PODUR",
            "THRSH",
        }

        entries = _parse_batch_entries(args.batch)

        if not entries:
            df_harvest = pd.DataFrame(columns=["@RUN", "TN", "HNO", "DATE", "PWADM", "PWADS"])
            harvest_sigmas = {"PWADM": 1.0}
            df_process = pd.DataFrame(
                columns=[
                    "@RUN",
                    "TN",
                    "DATE",
                    "L#SDM",
                    "LAIDM",
                    "LWADM",
                    "SWADM",
                    "L#SDS",
                    "LAIDS",
                    "LWADS",
                    "SWADS",
                ]
            )
            process_sigmas = {"L#SDM": 0.6, "LAIDM": 2.0, "LWADM": 150.0, "SWADM": 200.0}
        else:
            filex = entries[0]["filex"]
            filex_path = filex if os.path.isabs(filex) else os.path.join(WORKSPACE, filex)
            excode = _infer_excode_from_filex(filex_path)
            tmt_path = os.path.join(os.path.dirname(os.path.abspath(filex_path)), f"{excode}.TMT") if excode else None

            events_by_tn = _read_tmt_harvest_events(tmt_path)
            points_by_tn = _read_tmt_process_points(tmt_path)

            harvest_rows = []
            process_rows = []

            for e in entries:
                run_no = int(e["run"])
                tn = int(e.get("tn", -99))

                for ev in events_by_tn.get(tn, []):
                    obs_cum = ev.get("dry_cum", -99.0) if harvest_var == "CHPDT" else ev.get("fresh_cum", -99.0)
                    harvest_rows.append(
                        {
                            "@RUN": run_no,
                            "TN": tn,
                            "HNO": int(ev["hno"]),
                            "DATE": int(ev["date"]),
                            "PWADM": float(obs_cum),
                            "PWADS": -99.0,
                        }
                    )

                for p in points_by_tn.get(tn, []):
                    process_rows.append(
                        {
                            "@RUN": run_no,
                            "TN": tn,
                            "DATE": int(p["date"]),
                            "L#SDM": float(p.get("lnsd", -99.0)),
                            "LAIDM": float(p["laid"]),
                            "LWADM": float(p["lwad"]),
                            "SWADM": float(p["swad"]),
                            "L#SDS": -99.0,
                            "LAIDS": -99.0,
                            "LWADS": -99.0,
                            "SWADS": -99.0,
                        }
                    )

            df_harvest = pd.DataFrame(harvest_rows)
            if df_harvest.empty:
                harvest_sigmas = {"PWADM": 1.0}
            else:
                harvest_sigmas = {"PWADM": 1.0}
                for hno, g in df_harvest.groupby("HNO"):
                    med = float(g["PWADM"].median())
                    sigma0 = float(args.pwadm_sigma0)
                    cv = float(args.pwadm_cv)
                    sigma_factor = float(args.pwadm_sigma_factor)
                    sigma = (sigma0**2 + (cv * abs(med)) ** 2) ** 0.5
                    sigma = sigma * sigma_factor
                    harvest_sigmas[f"PWADM_H{int(hno)}"] = float(sigma)

            df_process = pd.DataFrame(process_rows)
            process_sigmas = {"L#SDM": 0.6, "LAIDM": 2.0, "LWADM": 150.0, "SWADM": 200.0}
            if not df_process.empty:
                for var, sigma0, cv in [
                    ("L#SDM", 0.5, 0.15),
                    ("LAIDM", 1.6, 0.50),
                    ("LWADM", 80.0, 0.25),
                    ("SWADM", 100.0, 0.25),
                ]:
                    g = df_process[df_process[var] != -99.0]
                    if g.empty:
                        continue
                    for date, gg in g.groupby("DATE"):
                        med = float(gg[var].median())
                        sigma = (sigma0**2 + (cv * abs(med)) ** 2) ** 0.5
                        process_sigmas[f"{var}_D{int(date)}"] = float(sigma)

        stage2_outputs = [
            {
                "model_out_path": PEST_HARVEST_FILE,
                "obs_bases": {"PWAD"},
                "critical_obs": set(),
                "group_sigmas": harvest_sigmas,
                "df": df_harvest,
            },
            {
                "model_out_path": PEST_TMTGROW_FILE,
                "obs_bases": {"L#SD", "LAID", "LWAD", "SWAD"},
                "critical_obs": set(),
                "group_sigmas": process_sigmas,
                "df": df_process,
            },
        ]
        extra_allowed = {
            "PL-EM",
            "EM-V1",
            "V1-JU",
            "JU-R0",
            "FL-VS",
            "TRIFL",
            "RWDTH",
            "RHGHT",
            "OPTBI",
            "SLOBI",
            "XMAGE",
            "XFPHT",
            "XFINT",
            "TB1",
            "TO11",
            "TO21",
            "TM1",
            "TB2",
            "TO12",
            "TO22",
            "TM2",
            "TB3",
            "TO13",
            "TO23",
            "TM3",
        }
    elif mode == "eggplant_process":
        prefix = args.prefix or "eggplant_process"
        allowed = {"SLAVR", "SIZLF", "LFMAX", "XFRT", "WTPSD", "SFDUR", "SDPDV", "PODUR"}
        obs_bases = {"LAID", "LWAD", "SWAD"}
        critical = set()
        model_out_path = PEST_TMTGROW_FILE

        entries = _parse_batch_entries(args.batch)
        if not entries:
            print("Warning: batch file is empty; no process observations will be created.")
            df_override = pd.DataFrame(columns=["@RUN", "TN", "DATE", "LAIDM", "LWADM", "SWADM", "LAIDS", "LWADS", "SWADS"])
            group_sigmas = {"LAIDM": 2.0, "LWADM": 150.0, "SWADM": 200.0}
        else:
            filex = entries[0]["filex"]
            filex_path = filex if os.path.isabs(filex) else os.path.join(WORKSPACE, filex)
            excode = _infer_excode_from_filex(filex_path)
            tmt_path = os.path.join(os.path.dirname(os.path.abspath(filex_path)), f"{excode}.TMT") if excode else None

            points_by_tn = _read_tmt_process_points(tmt_path)
            rows = []
            for e in entries:
                run_no = int(e["run"])
                tn = int(e.get("tn", -99))
                for p in points_by_tn.get(tn, []):
                    rows.append(
                        {
                            "@RUN": run_no,
                            "TN": tn,
                            "DATE": int(p["date"]),
                            "LAIDM": float(p["laid"]),
                            "LWADM": float(p["lwad"]),
                            "SWADM": float(p["swad"]),
                            "LAIDS": -99.0,
                            "LWADS": -99.0,
                            "SWADS": -99.0,
                        }
                    )

            df_override = pd.DataFrame(rows)
            group_sigmas = {"LAIDM": 2.0, "LWADM": 150.0, "SWADM": 200.0}
            if not df_override.empty:
                for var, sigma0, cv in [
                    ("LAIDM", 1.6, 0.50),
                    ("LWADM", 80.0, 0.25),
                    ("SWADM", 100.0, 0.25),
                ]:
                    g = df_override[df_override[var] != -99.0]
                    if g.empty:
                        continue
                    for date, gg in g.groupby("DATE"):
                        med = float(gg[var].median())
                        sigma = (sigma0 ** 2 + (cv * abs(med)) ** 2) ** 0.5
                        group_sigmas[f"{var}_D{int(date)}"] = float(sigma)
        extra_allowed = None
    elif mode == "eggplant_spe_temp":
        prefix = args.prefix or "eggplant_spe_temp"
        allowed = set()
        obs_bases = {"ADAP"}
        critical = {"ADAPM"}
        model_out_path = PEST_EVAL_FILE
        group_sigmas = {
            "ADAPM": 15.0,
        }
        extra_allowed = {
            "TB1",
            "TO11",
            "TO21",
            "TM1",
            "TB2",
            "TO12",
            "TO22",
            "TM2",
            "TB3",
            "TO13",
            "TO23",
            "TM3",
        }
    else:
        prefix = args.prefix or "tomato_cal"
        allowed = None
        obs_bases = None
        critical = {'ADAPM', 'MDAPM', 'PD1PM'}
        model_out_path = OUT_FILE
        group_sigmas = None
        extra_allowed = None

    params = parse_cul_params(cultivar, allowed_params=allowed)

    if extra_allowed is not None:
        eco_init = _read_eco_init_values(ecotype)
        spe_init = _read_spe_temp_init_values()
        params.extend(
            parse_extra_params(
                init_map=eco_init,
                bounds_map=ECO_BOUNDS_EGGPLANT,
                allowed_params=extra_allowed,
                pargp="ecotype",
            )
        )
        params.extend(
            parse_extra_params(
                init_map=spe_init,
                bounds_map=SPE_TEMP_BOUNDS_EGGPLANT,
                allowed_params=extra_allowed,
                pargp="species",
            )
        )
    print(f"Found {len(params)} adjustable parameters.")

    override = {}
    for p in args.init_from or []:
        override.update(_load_init_overrides(p))
    if override:
        for p in params:
            k = str(p.get("name", "")).strip().lower()
            if k and k in override:
                p["init"] = float(override[k])

    param_review_csv = args.param_review_csv
    if not param_review_csv:
        param_review_csv = os.path.join(WORKSPACE, f"{prefix}_param_review.csv")

    prm_mode = (args.param_review_mode or "auto").strip().lower()
    if prm_mode != "off":
        exists = os.path.exists(param_review_csv)
        if prm_mode in {"auto", "export"} and not exists:
            write_param_review_csv(params, param_review_csv, cultivar=cultivar, ecotype=ecotype, mode=mode)
            print(f"Parameter review CSV written to {param_review_csv}")
            if prm_mode != "export":
                print("Edit this file and re-run with --param-review-mode import")
            raise SystemExit(0)
        if prm_mode == "export":
            write_param_review_csv(params, param_review_csv, cultivar=cultivar, ecotype=ecotype, mode=mode)
            print(f"Parameter review CSV written to {param_review_csv}")
            raise SystemExit(0)
        if exists and prm_mode in {"auto", "import"}:
            params = apply_param_review_csv(params, param_review_csv)

    if stage2_outputs is not None:
        create_ins_and_pst_multi(
            params,
            prefix=prefix,
            noptmax=args.noptmax,
            ies_num_reals=args.ies_num_reals,
            outputs=stage2_outputs,
            evaluate_out_path=evaluate_out_path,
            model_cmd_extra=model_cmd_extra,
        )
    else:
        create_ins_and_pst(
            params,
            prefix=prefix,
            noptmax=args.noptmax,
            ies_num_reals=args.ies_num_reals,
            obs_bases=obs_bases,
            critical_obs=critical,
            model_out_path=model_out_path,
            group_sigmas=group_sigmas,
            evaluate_out_path=evaluate_out_path,
            df_override=df_override,
            model_cmd_extra=model_cmd_extra,
        )
