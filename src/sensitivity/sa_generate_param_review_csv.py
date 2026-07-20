import argparse
import os
import re
from dataclasses import dataclass

import pandas as pd

from src.common.param_registry import compute_default_bounds


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
    return compute_default_bounds(name, init, location)


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

    if loc == "IC":
        if n.startswith("IC_SH2O"):
            return "IC_InitialWater"
        return "IC_Other"

    if loc == "SPE":
        if n in {"PARMAX", "PHTMAX", "KCAN", "KC_SLOPE"}:
            return "SPE_Photosynthesis"
        if n == "FRCNOD":
            return "SPE_Nodule"
        if n in {"WTFSD", "PORPT", "FRSTMF", "FRLFF", "ATOP"}:
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


def _read_soil_params(soil_path, soil_id, max_depth_cm=100):
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
            try:
                slb_idx = header.index("SLB")
            except ValueError:
                slb_idx = None
            layer_idx = 0
            for data_idx in range(j + 1, sec_end):
                line = lines[data_idx]
                if not line.strip():
                    continue
                if line.lstrip().startswith("@") or line.startswith("*") or line.lstrip().startswith("!"):
                    break
                parts = line.split()
                if slb_idx is None or len(parts) <= slb_idx:
                    continue
                depth = _parse_float(parts[slb_idx])
                if depth is None:
                    continue
                if float(depth) > float(max_depth_cm):
                    break
                layer_idx += 1
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
                    out[f"SOIL_{name}_{layer_idx:02d}"] = v

    return out


def _read_initial_conditions_sh2o(filex_path, max_layers=20):
    if not filex_path or not os.path.exists(filex_path):
        return {}

    with open(filex_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    in_ic = False
    header = None
    sh2o_idx = None
    icbl_idx = None
    layer_idx = 0
    out = {}

    for line in lines:
        u = line.strip().upper()
        if u.startswith("*INITIAL CONDITIONS"):
            in_ic = True
            header = None
            sh2o_idx = None
            icbl_idx = None
            layer_idx = 0
            continue
        if in_ic and u.startswith("*") and not u.startswith("*INITIAL CONDITIONS"):
            break
        if not in_ic:
            continue

        if line.lstrip().startswith("@C") and ("ICBL" in u) and ("SH2O" in u):
            header = line.split()
            try:
                sh2o_idx = header.index("SH2O")
                icbl_idx = header.index("ICBL")
            except ValueError:
                header = None
                sh2o_idx = None
                icbl_idx = None
            layer_idx = 0
            continue

        if header is None:
            continue

        if not line.strip():
            continue
        if line.lstrip().startswith("@") or line.startswith("*"):
            break

        parts = line.split()
        if sh2o_idx is None or icbl_idx is None or len(parts) <= max(sh2o_idx, icbl_idx):
            continue

        layer_idx += 1
        if layer_idx > int(max_layers):
            break

        v = _parse_float(parts[sh2o_idx])
        if v is None:
            continue
        out[f"IC_SH2O_{layer_idx:02d}"] = v

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
    soil_keep = {k for k in soil_vals.keys() if str(k).strip().upper().startswith("SOIL_")}
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

    ic_vals = _read_initial_conditions_sh2o(paths.filex_path)
    ic_keep = {k for k in ic_vals.keys() if str(k).strip().upper().startswith("IC_SH2O")}
    for k in sorted(ic_keep):
        if k not in ic_vals:
            continue
        init = _parse_float(ic_vals.get(k))
        lb, ub, status = _default_bounds(k, init, "IC")
        rows.append(
            {
                "name": k,
                "init": init,
                "lower": lb,
                "upper": ub,
                "status": status,
                "pargp": _infer_pargp(k, "IC"),
                "location": "IC",
                "file": os.path.basename(paths.filex_path),
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
        else os.path.join(workspace_dir, "workspace", "runs", "sa_output", "sensitivity_param_review.csv")
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
