import argparse
import os
import re
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Paths:
    workspace_dir: str
    cul_path: str
    cul_base_path: str
    eco_path: str
    spe_path: str
    filex_path: str
    soil_path: str
    out_csv_path: str


def _workspace_dir_from_this_file():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", ".."))


def _read_table_row_by_key(file_path, key, key_col_name):
    if not os.path.exists(file_path):
        raise FileNotFoundError(file_path)

    header = None
    header_line = None
    values_line = None

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith(key_col_name):
                header_line = line.rstrip("\n")
                header = header_line.split()
                continue
            if header and line.startswith(key):
                values_line = line.rstrip("\n")
                break

    if not header or values_line is None:
        raise ValueError(f"Failed to read {key} from {file_path}")

    parts = values_line.split()
    if len(parts) < len(header):
        parts += [""] * (len(header) - len(parts))

    row = dict(zip(header, parts[: len(header)]))
    if key_col_name in row and row[key_col_name] != key:
        row[key_col_name] = key
    return header_line, values_line, row


def _parse_float(s):
    try:
        return float(str(s).strip())
    except Exception:
        return None


def _default_bounds(name, init, location):
    n = str(name).strip().upper()
    if init is None:
        return None, None, "fixed"

    loc = str(location).strip().upper()
    if loc == "SOIL":
        if n == "SOIL_SALB":
            return 0.05, 0.35, "active"
        if n == "SOIL_SLDR":
            return 0.10, 2.00, "active"
        if n == "SOIL_SLRO":
            return 40.0, 95.0, "active"
        if n.startswith("SOIL_SLLL"):
            lb = max(0.01, float(init) * 0.8)
            ub = min(0.80, float(init) * 1.2)
            return lb, ub, "active" if lb != ub else "fixed"
        if n.startswith("SOIL_SDUL"):
            lb = max(0.01, float(init) * 0.8)
            ub = min(0.80, float(init) * 1.2)
            return lb, ub, "active" if lb != ub else "fixed"
        if n.startswith("SOIL_SSAT"):
            lb = max(0.01, float(init) * 0.85)
            ub = min(0.80, float(init) * 1.15)
            return lb, ub, "active" if lb != ub else "fixed"
        if n.startswith("SOIL_SBDM"):
            lb = max(0.5, float(init) * 0.9)
            ub = min(2.2, float(init) * 1.1)
            return lb, ub, "active" if lb != ub else "fixed"
        if n.startswith("SOIL_SLOC"):
            lb = max(0.0, float(init) * 0.7)
            ub = min(10.0, float(init) * 1.3)
            return lb, ub, "active" if lb != ub else "fixed"

    eco_bounds = {
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
    if n in eco_bounds:
        lb, ub = eco_bounds[n]
        status = "active" if lb != ub else "fixed"
        return lb, ub, status

    temp_bounds = {
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
    if n in temp_bounds:
        return temp_bounds[n][0], temp_bounds[n][1], "active"

    if n == "VSSINK":
        lb = max(0.2, 0.5 * float(init))
        ub = max(lb + 0.2, 2.0 * float(init))
        return lb, ub, "active"

    if n == "KC_SLOPE":
        lb = max(0.0, float(init) - 0.10)
        ub = float(init) + 0.10
        return lb, ub, "active"

    if abs(float(init)) < 1e-12:
        return float(init), float(init), "fixed"

    if 0.0 < float(init) <= 1.0:
        lb = max(0.0, float(init) * 0.7)
        ub = min(1.0, float(init) * 1.3)
        status = "active" if lb != ub else "fixed"
        return lb, ub, status

    lb = float(init) * 0.75
    ub = float(init) * 1.25
    if lb > ub:
        lb, ub = ub, lb
    return lb, ub, "active"


def _infer_pargp(name, location):
    n = str(name).strip().upper()
    loc = str(location).strip().upper()

    if loc == "SOIL":
        if "SLLL" in n or "SDUL" in n or "SSAT" in n:
            return "SOIL_WaterRetention"
        if "SBDM" in n:
            return "SOIL_Physical"
        if "SLOC" in n:
            return "SOIL_Chemical"
        if n in {"SOIL_SALB", "SOIL_SLDR", "SOIL_SLRO"}:
            return "SOIL_SurfaceHydro"
        return "SOIL_Other"

    if loc == "SPE":
        if n in {"PARMAX", "PHTMAX", "KCAN", "KC_SLOPE"}:
            return "SPE_Photosynthesis"
        if n in {"WTFSD", "PORPT", "FRSTMF", "FRLFF", "ATOP", "FRCNOD"}:
            return "SPE_RootWater"
        if n in {"FINREF", "SLAREF", "SIZREF", "VSSINK", "EVMODC"}:
            return "SPE_SourceSink"
        if n.startswith("TB") or n.startswith("TO1") or n.startswith("TO2") or n.startswith("TM"):
            return "SPE_TempStages"
        return "SPE_Other"

    if loc == "ECO":
        if n in {"PL-EM", "EM-V1", "V1-JU", "JU-R0", "PM06", "PM09", "LNGSH", "FL-VS", "XMAGE", "XFPHT", "XFINT"}:
            return "ECO_Phenology"
        if n in {"TRIFL", "RWDTH", "RHGHT"}:
            return "ECO_Architecture"
        return "ECO_Other"

    if loc == "CUL":
        if n in {"EM-FL", "FL-SH", "FL-SD", "SD-PM", "FL-LF", "SFDUR", "SDPDV", "PODUR"}:
            return "CUL_PhenologyHarvest"
        if n in {"LFMAX", "SLAVR", "SIZLF"}:
            return "CUL_Growth"
        if n in {"XFRT", "WTPSD", "THRSH"}:
            return "CUL_HarvestPartition"
        return "CUL_Other"

    return ""


def _read_spe_params(spe_path):
    if not os.path.exists(spe_path):
        raise FileNotFoundError(spe_path)

    number_re = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[Ee][-+]?\d+)?")
    values = {}

    def _values_from_named_line(needle, names_in_order):
        with open(spe_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if needle in line:
                    matches = list(number_re.finditer(line))
                    if len(matches) < len(names_in_order):
                        return
                    for name, m in zip(names_in_order, matches[: len(names_in_order)]):
                        values[str(name).strip().upper()] = float(m.group(0))
                    return

    _values_from_named_line("PARMAX,PHTMAX", ["PARMAX", "PHTMAX", "KCAN", "KC_SLOPE"])
    _values_from_named_line("WTFSD,PORPT", ["WTFSD", "PORPT", "FRSTMF", "FRLFF", "ATOP", "FRCNOD"])
    _values_from_named_line("FINREF,SLAREF", ["FINREF", "SLAREF", "SIZREF", "VSSINK", "EVMODC"])

    pheno_section = False
    with open(spe_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            u = line.strip().upper()
            if u.startswith("!*PHENOLOGY PARAMETERS") or u.startswith("*PHENOLOGY PARAMETERS"):
                pheno_section = True
                continue
            if pheno_section and "DEVELOPMENT" in u:
                matches = list(number_re.finditer(line))
                if len(matches) < 4:
                    continue
                if "VEGETATIVE DEVELOPMENT" in u:
                    stage = 1
                elif "EARLY REPRODUCTIVE DEVELOPMENT" in u:
                    stage = 2
                elif "LATE REPRODUCTIVE DEVELOPMENT" in u:
                    stage = 3
                else:
                    continue
                keys = [f"TB{stage}", f"TO1{stage}", f"TO2{stage}", f"TM{stage}"]
                for k, m in zip(keys, matches[:4]):
                    values[k] = float(m.group(0))
                continue
            if pheno_section and line.startswith("*") and ("PHENOLOGY" not in u):
                break

    return values


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


def _read_soil_params(soil_path, soil_id):
    if not soil_path or not os.path.exists(soil_path) or not soil_id:
        return {}

    lines = []
    with open(soil_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    sec_start = None
    for i, s in enumerate(lines):
        if not s.startswith("*"):
            continue
        sid = s[1:].strip().split()[0] if s[1:].strip() else ""
        if sid.upper() == str(soil_id).strip().upper():
            sec_start = i
            break
    if sec_start is None:
        return {}

    sec_end = len(lines)
    for j in range(sec_start + 1, len(lines)):
        if lines[j].startswith("*"):
            sec_end = j
            break

    out = {}

    def _next_data_line(idx):
        for j in range(idx + 1, sec_end):
            if not lines[j].strip():
                continue
            if lines[j].lstrip().startswith("@") or lines[j].startswith("*") or lines[j].lstrip().startswith("!"):
                continue
            return j
        return None

    for j in range(sec_start, sec_end):
        u = lines[j].strip().upper()
        if u.startswith("@") and ("SCOM" in u) and ("SALB" in u):
            header = lines[j].split()
            if header and str(header[0]).strip().startswith("@"):
                header = header[1:]
            data_idx = _next_data_line(j)
            if data_idx is None:
                continue
            parts = lines[data_idx].split()
            for name in ["SALB", "SLDR", "SLRO"]:
                try:
                    k = header.index(name)
                except ValueError:
                    continue
                if len(parts) <= k:
                    continue
                v = _parse_float(parts[k])
                if v is None:
                    continue
                out[f"SOIL_{name}"] = v

        if u.startswith("@") and ("SLLL" in u) and ("SDUL" in u) and ("SSAT" in u):
            header = lines[j].split()
            if header and str(header[0]).strip().startswith("@"):
                header = header[1:]
            data_idx = _next_data_line(j)
            if data_idx is None:
                continue
            parts = lines[data_idx].split()
            for name in ["SLLL", "SDUL", "SSAT", "SBDM", "SLOC"]:
                try:
                    k = header.index(name)
                except ValueError:
                    continue
                if len(parts) <= k:
                    continue
                v = _parse_float(parts[k])
                if v is None:
                    continue
                out[f"SOIL_{name}_01"] = v

    return out


def generate_review_csv(paths: Paths, cultivar: str, ecotype: str):
    cul_header, _, cul_row = _read_table_row_by_key(paths.cul_base_path, cultivar, "@VAR#")
    cul_min_row = None
    cul_max_row = None
    try:
        _, _, cul_min_row = _read_table_row_by_key(paths.cul_base_path, "999991", "@VAR#")
        _, _, cul_max_row = _read_table_row_by_key(paths.cul_base_path, "999992", "@VAR#")
    except Exception:
        cul_min_row = None
        cul_max_row = None
    cul_cols = cul_header.split()
    cul_param_cols = cul_cols[4:]

    eco_header, _, eco_row = _read_table_row_by_key(paths.eco_path, ecotype, "@ECO#")
    eco_min_row = None
    eco_max_row = None
    try:
        _, _, eco_min_row = _read_table_row_by_key(paths.eco_path, "999991", "@ECO#")
        _, _, eco_max_row = _read_table_row_by_key(paths.eco_path, "999992", "@ECO#")
    except Exception:
        eco_min_row = None
        eco_max_row = None
    eco_cols = eco_header.split()
    eco_param_cols = eco_cols[2:]

    spe_vals = _read_spe_params(paths.spe_path)

    cul_keep = {
        "EM-FL",
        "FL-SH",
        "FL-SD",
        "SD-PM",
        "FL-LF",
        "LFMAX",
        "SLAVR",
        "SIZLF",
        "XFRT",
        "WTPSD",
        "SFDUR",
        "SDPDV",
        "PODUR",
        "THRSH",
    }
    eco_keep = {
        "PL-EM",
        "EM-V1",
        "V1-JU",
        "JU-R0",
        "PM06",
        "PM09",
        "LNGSH",
        "FL-VS",
        "TRIFL",
        "RWDTH",
        "RHGHT",
        "XMAGE",
        "XFPHT",
        "XFINT",
    }
    spe_keep = {
        "PARMAX",
        "PHTMAX",
        "KCAN",
        "KC_SLOPE",
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

    rows = []

    for p in cul_param_cols:
        k = str(p).strip().upper()
        if k not in cul_keep:
            continue
        init = _parse_float(cul_row.get(p))

        lb = None
        ub = None
        status = None
        if cul_min_row is not None and cul_max_row is not None:
            lb = _parse_float(cul_min_row.get(p))
            ub = _parse_float(cul_max_row.get(p))
            if lb is not None and ub is not None:
                status = "fixed" if float(lb) == float(ub) else "active"
        if lb is None or ub is None:
            lb, ub, status = _default_bounds(k, init, "CUL")

        rows.append(
            {
                "name": k,
                "init": init,
                "lower": lb,
                "upper": ub,
                "status": status,
                "pargp": _infer_pargp(k, "CUL"),
                "location": "CUL",
                "file": os.path.basename(paths.cul_base_path),
                "cultivar": cultivar,
                "ecotype": ecotype,
                "mode": "both",
            }
        )

    for p in eco_param_cols:
        k = str(p).strip().upper()
        if k == "TM":
            continue
        if k not in eco_keep:
            continue
        init = _parse_float(eco_row.get(p))

        lb = None
        ub = None
        status = None
        if eco_min_row is not None and eco_max_row is not None:
            lb = _parse_float(eco_min_row.get(p))
            ub = _parse_float(eco_max_row.get(p))
            if lb is not None and ub is not None:
                status = "fixed" if float(lb) == float(ub) else "active"
        if lb is None or ub is None:
            lb, ub, status = _default_bounds(k, init, "ECO")

        rows.append(
            {
                "name": k,
                "init": init,
                "lower": lb,
                "upper": ub,
                "status": status,
                "pargp": _infer_pargp(k, "ECO"),
                "location": "ECO",
                "file": os.path.basename(paths.eco_path),
                "cultivar": cultivar,
                "ecotype": ecotype,
                "mode": "both",
            }
        )

    for k in sorted(spe_keep):
        if k not in spe_vals:
            continue
        init = _parse_float(spe_vals.get(k))
        lb, ub, status = _default_bounds(k, init, "SPE")
        rows.append(
            {
                "name": k,
                "init": init,
                "lower": lb,
                "upper": ub,
                "status": status,
                "pargp": _infer_pargp(k, "SPE"),
                "location": "SPE",
                "file": os.path.basename(paths.spe_path),
                "cultivar": cultivar,
                "ecotype": ecotype,
                "mode": "both",
            }
        )

    soil_id = _infer_soil_id_from_filex(paths.filex_path)
    soil_vals = _read_soil_params(paths.soil_path, soil_id)
    soil_keep = {
        "SOIL_SALB",
        "SOIL_SLDR",
        "SOIL_SLRO",
        "SOIL_SLLL_01",
        "SOIL_SDUL_01",
        "SOIL_SSAT_01",
        "SOIL_SBDM_01",
        "SOIL_SLOC_01",
    }
    for k in sorted(soil_keep):
        if k not in soil_vals:
            continue
        init = _parse_float(soil_vals.get(k))
        lb, ub, status = _default_bounds(k, init, "SOIL")
        rows.append(
            {
                "name": k,
                "init": init,
                "lower": lb,
                "upper": ub,
                "status": status,
                "pargp": _infer_pargp(k, "SOIL"),
                "location": "SOIL",
                "file": os.path.basename(paths.soil_path),
                "cultivar": cultivar,
                "ecotype": ecotype,
                "mode": "both",
            }
        )

    df = pd.DataFrame(rows)
    df = df.sort_values(["location", "pargp", "name"], kind="stable").reset_index(drop=True)
    os.makedirs(os.path.dirname(paths.out_csv_path), exist_ok=True)
    df.to_csv(paths.out_csv_path, index=False, encoding="utf-8-sig")
    return df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cultivar", default="TM0008")
    parser.add_argument("--ecotype", default="TM0001")
    parser.add_argument("--filex", default=None)
    parser.add_argument("--soil", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    workspace_dir = _workspace_dir_from_this_file()
    out_csv = (
        args.out
        if args.out
        else os.path.join(workspace_dir, "Sensitivity_Analyze", "SA_Project_Output", "sensitivity_param_review.csv")
    )

    paths = Paths(
        workspace_dir=workspace_dir,
        cul_path=os.path.join(workspace_dir, "TMGRO048.CUL"),
        cul_base_path=os.path.join(workspace_dir, "TMGRO048.CUL.base"),
        eco_path=os.path.join(workspace_dir, "TMGRO048.ECO"),
        spe_path=os.path.join(workspace_dir, "TMGRO048.SPE"),
        filex_path=os.path.normpath(args.filex) if args.filex else os.path.join(workspace_dir, "XXQL2501.TMX"),
        soil_path=os.path.normpath(args.soil) if args.soil else os.path.join(workspace_dir, "SOIL.SOL"),
        out_csv_path=os.path.normpath(out_csv),
    )

    df = generate_review_csv(paths, cultivar=args.cultivar, ecotype=args.ecotype)
    print(f"Wrote {len(df)} rows: {paths.out_csv_path}")


if __name__ == "__main__":
    main()
