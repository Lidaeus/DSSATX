import csv
import os

def _workspace_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", ".."))

def load_catalog():
    catalog_path = os.path.join(_workspace_dir(), "Sensitivity_Analyze", "SA_Project_Config", "sa_bounds_catalog.csv")
    if not os.path.exists(catalog_path):
        return {}
    
    catalog = {}
    with open(catalog_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("name", "").strip().upper()
            if name:
                catalog[name] = row
    return catalog

_CATALOG_CACHE = None

def get_catalog():
    global _CATALOG_CACHE
    if _CATALOG_CACHE is None:
        _CATALOG_CACHE = load_catalog()
    return _CATALOG_CACHE

def get_report_group(name):
    cat = get_catalog()
    n = str(name).strip().upper()
    if n in cat:
        return cat[n].get("report_group", "Other")
    return "Other"

def get_location(name):
    cat = get_catalog()
    n = str(name).strip().upper()
    if n in cat:
        return cat[n].get("location", "Unknown")
    return "Unknown"

def get_paper_label(name):
    cat = get_catalog()
    n = str(name).strip().upper()
    if n in cat:
        return cat[n].get("paper_label") or name
    return name

def get_default_bounds(name, init):
    cat = get_catalog()
    n = str(name).strip().upper()
    
    if init is None:
        return None, None, "fixed"

    if n in cat:
        row = cat[n]
        lb_def = row.get("lower_default", "")
        ub_def = row.get("upper_default", "")
        if lb_def and ub_def:
            try:
                lb = float(lb_def)
                ub = float(ub_def)
                return lb, ub, "active"
            except Exception:
                pass
        
        # Apply constraint rules
        rule = row.get("constraint_rule", "")
        try:
            init_f = float(init)
        except Exception:
            return None, None, "fixed"

        if "rel_20" in rule:
            return init_f * 0.8, init_f * 1.2, "active"
        if "rel_30" in rule:
            return init_f * 0.7, init_f * 1.3, "active"
        if "rel_25" in rule:
            return init_f * 0.75, init_f * 1.25, "active"
        if "positive_rel_25" in rule:
            lb = max(0.01, init_f * 0.75)
            ub = init_f * 1.25
            return lb, ub, "active"
        if "positive_rel_20" in rule:
            lb = max(0.01, init_f * 0.80)
            ub = init_f * 1.20
            return lb, ub, "active"
        if "fixed" in rule:
            return init_f, init_f, "fixed"

    # Fallbacks if not in catalog or rule matched nothing
    try:
        init_f = float(init)
    except Exception:
        return None, None, "fixed"

    if abs(init_f) < 1e-12:
        return init_f, init_f, "fixed"

    if 0.0 < init_f <= 1.0:
        lb = max(0.0, init_f * 0.7)
        ub = min(1.0, init_f * 1.3)
        return lb, ub, "active"

    lb = init_f * 0.75
    ub = init_f * 1.25
    if lb > ub:
        lb, ub = ub, lb
    return lb, ub, "active"

def is_param_active(name):
    cat = get_catalog()
    n = str(name).strip().upper()
    return n in cat

def get_all_soil_multipliers():
    cat = get_catalog()
    return [k for k, v in cat.items() if v.get("location") == "SOIL"]

def get_soil_group_mapping():
    # Defines how M_SOIL_WRET_SURF expands to actual soil parameters and layer indices
    # Default tomato root depth is up to 100-150cm. Let's say SURF=1-2, ROOT=3-5, DEEP=6+
    return {
        "M_SOIL_SALB": {"params": ["SOIL_SALB"], "layers": None},
        "M_SOIL_SLDR": {"params": ["SOIL_SLDR"], "layers": None},
        "M_SOIL_SLRO": {"params": ["SOIL_SLRO"], "layers": None},
        "M_SOIL_WRET_SURF": {"params": ["SOIL_SLLL", "SOIL_SDUL", "SOIL_SSAT"], "layers": [1, 2]},
        "M_SOIL_WRET_ROOT": {"params": ["SOIL_SLLL", "SOIL_SDUL", "SOIL_SSAT"], "layers": [3, 4, 5]},
        "M_SOIL_WRET_DEEP": {"params": ["SOIL_SLLL", "SOIL_SDUL", "SOIL_SSAT"], "layers": [6, 7, 8, 9, 10, 11, 12, 13, 14, 15]},
        "M_SOIL_BD_SURF": {"params": ["SOIL_SBDM"], "layers": [1, 2]},
        "M_SOIL_BD_ROOT": {"params": ["SOIL_SBDM"], "layers": [3, 4, 5]},
        "M_SOIL_BD_DEEP": {"params": ["SOIL_SBDM"], "layers": [6, 7, 8, 9, 10, 11, 12, 13, 14, 15]},
        "M_SOIL_OC_SURF": {"params": ["SOIL_SLOC"], "layers": [1, 2]},
        "M_SOIL_OC_ROOT": {"params": ["SOIL_SLOC"], "layers": [3, 4, 5]},
        "M_SOIL_OC_DEEP": {"params": ["SOIL_SLOC"], "layers": [6, 7, 8, 9, 10, 11, 12, 13, 14, 15]},
    }
