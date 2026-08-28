"""param_registry.py — 参数注册表核心模块。

提取自 sa_generate_param_review_csv.py 的边界推断逻辑和参数分组逻辑。
这是参数管理的唯一权威来源，SA 和率定代码都应调用此模块而非各自硬编码。

职责：
1. 定义参数的物理硬边界（physical bounds）
2. 推断默认建议边界（default bounds）
3. 参数分组（parameter group inference）
4. 加载/保存参数注册表 CSV
"""

from __future__ import annotations

import csv
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional


# ── 注册表字段 ─────────────────────────────────────────────────

REGISTRY_COLUMNS = [
    "parameter_name",
    "crop",
    "parameter_family",     # CUL / ECO / SPE / SOIL / INIT / MANAGEMENT
    "target_file",
    "section",
    "dtype",
    "format_width",
    "format_precision",
    "base_value",
    "physical_lower",
    "physical_upper",
    "default_step",
    "calibration_stage",
    "enabled_by_default",
    "description",
]


# ── 物理硬边界字典 ────────────────────────────────────────────
# 来源：DSSAT 数值稳定性约束、文件格式约束和已验证的模型基线。
# 这些只是数值安全包络，不是推荐率定范围；科研工作范围见
# DEFAULT_BOUNDS 或经人工审核的 bounds proposal。

PHYSICAL_BOUNDS: dict[str, tuple[float, float]] = {
    # --- CUL ---
    "CSDL":   (0.0,   24.0),
    "PPSEN":  (0.0,    1.0),
    "EM-FL":  (10.0,  80.0),
    "FL-SH":  (1.0,   20.0),
    "FL-SD":  (1.0,   30.0),
    # The shipped TMGRO048 cultivar uses 400 for both SD-PM and FL-LF.
    # These are DSSAT safety envelopes, not recommended calibration ranges.
    "SD-PM":  (10.0, 600.0),
    "FL-LF":  (10.0, 600.0),
    "LFMAX":  (0.5,    3.0),
    "SLAVR":  (100.0, 500.0),
    "SIZLF":  (50.0, 1000.0),
    "XFRT":   (0.01,   1.0),
    "WTPSD":  (0.001,  2.0),
    "SFDUR":  (5.0,   50.0),
    "SDPDV":  (0.5,  500.0),
    "PODUR":  (5.0,   80.0),
    "THRSH":  (0.0,   99.0),
    # Structural timing probes.  They remain continuous DSSAT fields in the
    # CUL file; the SA proposal uses a narrow local domain around 400 d.
    "SDPRO":  (0.0,    1.0),
    "SDLIP":  (0.0,    1.0),
    # --- ECO ---
    "PL-EM":  (1.0,   12.0),
    "EM-V1":  (10.0,  60.0),
    "V1-JU":  (0.0,   30.0),
    "JU-R0":  (2.0,   20.0),
    "LNGSH":  (1.0,  200.0),
    "PM06":   (0.0,    1.0),
    "PM09":   (0.0,    1.0),
    # Photothermal time from first flower to the last main-stem leaf.
    # Indeterminate crops may legitimately use values above 100; whether the
    # coefficient is identifiable is a separate scientific decision.
    "FL-VS":  (0.0,  300.0),
    "TRIFL":  (0.10,   2.50),
    "RWDTH":  (0.50,   2.00),
    # RHGHT is a relative multiplier on the species-file standard canopy-height
    # curve (YVSHT), not an absolute height in metres.  Joint E02 runs first
    # justified relaxing the historical 0.50 floor to 0.35; later review
    # concluded there is no clear finite positive physical lower bound beyond
    # keeping the multiplier non-negative.  Calibration ranges may still choose
    # a stricter working floor for identifiability.
    "RHGHT":  (0.0,    3.00),
    "OPTBI":  (0.0,   20.0),
    "SLOBI":  (-0.50,  0.0),
    # Dynamic fruit-partitioning safety envelopes.  The shipped strawberry
    # ecotypes and this project's DFAULT ecotype use XFPHT around 60, so 40
    # cannot be treated as a physical upper limit.  XMAGE < XFPHT is enforced
    # separately for every candidate.
    "XMAGE":  (1.0,   60.0),
    "XFPHT":  (5.0,  120.0),
    "XFINT":  (0.0,    1.0),
    # --- SPE temperature ---
    "TB":     (4.0,   15.0),
    "TO1":    (18.0,  32.0),
    "TO2":    (24.0,  38.0),
    "TM":     (30.0,  48.0),
    "TB1":    (4.0,   15.0),
    "TO11":   (18.0,  32.0),
    "TO21":   (24.0,  38.0),
    "TM1":    (30.0,  48.0),
    "TB2":    (4.0,   15.0),
    "TO12":   (12.0,  32.0),
    "TO22":   (24.0,  38.0),
    "TM2":    (30.0,  48.0),
    "TB3":    (4.0,   15.0),
    "TO13":   (18.0,  32.0),
    "TO23":   (24.0,  38.0),
    "TM3":    (30.0,  48.0),
    # --- SPE photosynthesis / source-sink ---
    "PARMAX":  (5.0, 100.0),
    "PHTMAX":  (10.0, 100.0),
    "KCAN":    (0.20,  1.00),
    "KC_SLOPE": (0.0,  0.50),
    "FINREF":  (0.0, 1000.0),
    "SLAREF":  (100.0, 800.0),
    "SIZREF":  (50.0, 1000.0),
    "VSSINK":  (0.2,   50.0),
    "EVMODC":  (0.0,    3.0),
    # --- SPE composition / seed-shell growth ---
    "SDPROS":  (0.0,    1.0),
    "PCARSD":  (0.0,    1.0),
    "XMPAGE":  (1.0,  300.0),
    # --- SPE root-water ---
    "WTFSD":   (0.0,  1.0),
    "PORPT":   (0.0,  1.0),
    "FRSTMF":  (0.0,  1.0),
    "FRLFF":   (0.0,  1.0),
    "ATOP":    (0.0, 10.0),
    "SRGF":    (0.0,  1.0),
    "FRCNOD":  (0.0,  1.0),  # narrow SA probe despite non-legume status
    # --- SPE root-N / N-stress ---
    # DSSAT TMGRO048.SPE stores these as small root-length-normalized
    # nitrogen uptake-rate scalars (template value 0.012), not centimetres.
    # Keep the hard numerical domain aligned with the documented SPE scale;
    # calibration-specific bounds remain in frozen bounds CSVs.
    "RTNO3":   (0.0,  0.05),
    "RTNH4":   (0.0,  0.05),
    "RTEXF":   (0.0,  1.0),
    "NSTFAC":  (0.0,  1.0),
    "NMOBMX":  (0.0,  1.0),
    "NVSMOB":  (0.0,  1.0),
    "NRCVR":   (0.0,  1.0),
    # A4 effective-concentration N-uptake response parameters.
    # NUPCMN floor stays 0.0: the a3_20260805 build hard-rejects negative
    # values (STOP 99, "Error key: NUPTAK") even though the formula
    # C*=max(C-NUPCMN,0) is mathematically well-defined for negatives.
    "NUPK50":  (0.0, 1000.0),
    "NUPQ":    (0.1,  5.0),
    "NUPCMN":  (0.0, 1000.0),
    "NUPAV":   (0.0,    1.0),
    # --- SPE parameter extension modules (docs/reference/参数拓展方案参考.MD) ---
    # Leaf senescence
    "SENRTE":  (0.0, 10.0),
    "SENDAY":  (0.0,  1.0),
    # Fruit set
    "SETMAX":  (0.0,  1.0),
    "RFLWAB":  (0.0,  1.0),
    # Fruit growth
    "SHLAG":   (0.0,  1.0),
    "SRMAX":   (0.0,  1.0),
    # Leaf area SLA modifiers
    "SLAMAX":  (50.0, 2000.0),
    "SLAMIN":  (50.0, 1000.0),
    "TURSLA":  (0.0,  10.0),
    "NSLA":    (0.0,  10.0),
    # Vegetative partition
    "FRLFMX":  (0.0,  1.0),
    # Photosynthesis
    "PGEFF":   (0.001, 0.5),
    "KDIF":    (0.0,  3.0),
    "LFANGB":  (0.0, 10.0),
    # Nitrogen
    "LNREF":   (0.5, 15.0),
    "NSLOPE":  (-1.0, 5.0),
    # Water stress
    "DSWBAR":  (1.0, 100.0),
    "XFRMAX":  (0.0,  1.0),
    # Root uptake & transplant initial state
    "PORMIN":  (0.0,  0.5),
    "RTDEPI":  (1.0,  50.0),
    "RWUMX":   (0.001, 1.0),
    "PLWT":    (1.0,  20.0),
    "PLDP":    (1.0,  30.0),
    # Carbon reserve
    "CMOBMX":  (0.0,  1.0),
    "CADSTF":  (0.0,  1.0),
    "CADPR1":  (0.0,  1.0),
    # Organ protein
    "PROLFI":  (0.0,  1.0),
    "PROLFG":  (0.0,  1.0),
    "PROLFF":  (0.0,  1.0),
    "PROSTI":  (0.0,  1.0),
    "PROSTG":  (0.0,  1.0),
    "PROSTF":  (0.0,  1.0),
    "PRORTI":  (0.0,  1.0),
    "PRORTG":  (0.0,  1.0),
    "PRORTF":  (0.0,  1.0),
    "PROSHI":  (0.0,  1.0),
    "PROSHG":  (0.0,  1.0),
    "PROSHF":  (0.0,  1.0),
    # --- SOIL surface hydro ---
    "SOIL_SALB": (0.01, 0.50),
    "SOIL_SLDR": (0.05, 2.50),
    "SOIL_SLRO": (20.0, 99.0),
    # DSSAT SLPF is the soil-profile fertility/productivity multiplier.  It is
    # not a measured mineral-N concentration; it is calibrated here as the
    # explicit soil fertility index requested for the N-response subspace.
    "SOIL_SLPF": (0.0, 2.0),
    "SOIL_SLNF": (0.0, 10.0),
}


# ── 默认建议边界 ──────────────────────────────────────────────
# 比物理硬边界更窄的工作范围，来源是文献 + 历史率定经验。

DEFAULT_BOUNDS: dict[str, tuple[float, float]] = {
    # --- ECO ---
    "PL-EM":  (3.0,  12.0),
    "EM-V1":  (10.0, 40.0),
    "V1-JU":  (0.0,   0.0),
    "JU-R0":  (2.0,  20.0),
    # Structural sensitivity probe for indeterminate eggplant.  Calibration is
    # allowed only when last-leaf/terminal-growth observations identify it.
    "FL-VS":  (100.0, 140.0),
    "TRIFL":  (0.20,  0.80),
    "RWDTH":  (0.70,  1.60),
    "RHGHT":  (0.70,  2.00),
    "OPTBI":  (0.0,  20.0),
    "SLOBI":  (-0.50, 0.0),
    # Rectangular ranges deliberately guarantee upper(XMAGE) < lower(XFPHT).
    # They cover the modified tomato baseline (XFPHT=38.8), the project
    # DFAULT value (60), and the DSSAT strawberry reference (58--62).
    "XMAGE":  (8.0,  30.0),
    "XFPHT":  (35.0, 70.0),
    "XFINT":  (0.10,  0.35),
    # ECO phenology durations (T9 high-dim active set).
    "LNGSH":  (25.0, 50.0),
    "PM06":   (0.35, 0.75),
    "PM09":   (0.60, 1.00),
    # Fruit dry/fresh conversion and composition probes used by the fruit-water
    # SA branch. THRSH remains part of the CUL default domain via generic
    # fallback/frozen bounds, while these SPE-only additions need explicit
    # defaults so proposal generation stays aligned with reviewed templates.
    "SDPRO":  (0.20, 0.45),
    "SDLIP":  (0.02, 0.08),
    "SDPROS": (0.20, 0.45),
    "PCARSD": (0.40, 0.70),
    "XMPAGE": (60.0, 150.0),
    # --- SPE temperature ---
    "TB":     (8.0,  12.0),
    "TO1":    (20.0, 27.5),
    "TO2":    (28.0, 33.0),
    "TM":     (34.0, 45.0),
    "TB1":    (8.0,  12.0),
    "TO11":   (20.0, 27.5),
    "TO21":   (28.0, 33.0),
    "TM1":    (34.0, 45.0),
    "TB2":    (8.0,  12.0),
    "TO12":   (20.0, 27.5),
    "TO22":   (28.0, 33.0),
    "TM2":    (34.0, 45.0),
    "TB3":    (8.0,  12.0),
    "TO13":   (20.0, 27.5),
    "TO23":   (28.0, 33.0),
    "TM3":    (34.0, 45.0),
    # --- SOIL surface ---
    "SOIL_SALB": (0.05, 0.35),
    "SOIL_SLDR": (0.10, 2.00),
    "SOIL_SLRO": (40.0, 95.0),
    # --- SPE parameter extension defaults (docs/reference/参数拓展方案参考.MD) ---
    "SENRTE":  (0.5, 2.0),
    "SENDAY":  (0.01, 0.05),
    "SETMAX":  (0.1, 0.5),
    "RFLWAB":  (0.05, 0.5),
    "SHLAG":   (0.05, 0.3),
    "SRMAX":   (0.1, 0.5),
    "SLAMAX":  (400.0, 900.0),
    "SLAMIN":  (200.0, 500.0),
    "TURSLA":  (0.5, 2.0),
    "NSLA":    (0.5, 1.5),
    "FRLFMX":  (0.5, 0.9),
    "PGEFF":   (0.03, 0.07),
    "KDIF":    (0.5, 1.0),
    "LFANGB":  (1.0, 3.0),
    "LNREF":   (3.0, 6.0),
    "NSLOPE":  (0.1, 0.5),
    "DSWBAR":  (10.0, 30.0),
    "XFRMAX":  (0.0, 0.5),
    "PORMIN":  (0.02, 0.06),
    "RTDEPI":  (10.0, 20.0),
    "RWUMX":   (0.02, 0.06),
    "PLWT":    (4.0, 12.0),
    "PLDP":    (5.0, 15.0),
    "CMOBMX":  (0.01, 0.05),
    "CADSTF":  (0.3, 0.9),
    "CADPR1":  (0.1, 0.5),
    "PROLFI":  (0.2, 0.35),
    "PROLFG":  (0.15, 0.3),
    "PROLFF":  (0.05, 0.15),
    "PROSTI":  (0.145, 0.220),
    "PROSTG":  (0.090, 0.140),
    "PROSTF":  (0.040, 0.080),
    "PRORTI":  (0.1296, 0.1584),
    "PRORTG":  (0.1071, 0.1309),
    "PRORTF":  (0.0540, 0.0660),
    "PROSHI":  (0.189, 0.231),
    "PROSHG":  (0.135, 0.165),
    "PROSHF":  (0.099, 0.121),
    # A4 first-round working domain; NUPQ is intentionally fixed at 1.0 in
    # the initial calibration proposal per the A4 method note.
    "NUPK50":  (1.0, 40.0),
    "NUPQ":    (0.50, 1.50),
    "NUPCMN":  (0.0, 2.0),
    "NUPAV":   (0.50, 1.00),
}


# ── 参数分组推断 ──────────────────────────────────────────────

def infer_parameter_group(name: str, location: str) -> str:
    """根据参数名和所属文件，推断参数组名。

    Args:
        name: 参数名（大写）
        location: 所属文件族，如 CUL / ECO / SPE / SOIL / IC

    Returns:
        参数组名字符串（最长 12 字符，兼容 PEST 限制）
    """
    n = str(name).strip().upper()
    loc = str(location).strip().upper()

    if loc == "SOIL":
        if "SLLL" in n or "SDUL" in n or "SSAT" in n:
            return "SOIL_WatRet"
        if "SBDM" in n:
            return "SOIL_Phys"
        if "SLOC" in n:
            return "SOIL_Chem"
        if n in {"SOIL_SALB", "SOIL_SLDR", "SOIL_SLRO"}:
            return "SOIL_SfcHyd"
        return "SOIL_Other"

    if loc == "IC":
        if n.startswith("IC_SH2O"):
            return "IC_InitWat"
        return "IC_Other"

    if loc == "SPE":
        if n in {"PARMAX", "PHTMAX", "KCAN", "KC_SLOPE"}:
            return "SPE_Photo"
        if n == "FRCNOD":
            return "SPE_Nodule"
        if n in {"SDPRO", "SDLIP", "SDPROS", "PCARSD"}:
            return "SPE_Compo"
        if n == "XMPAGE":
            return "SPE_SeedSh"
        if n in {"WTFSD", "PORPT", "FRSTMF", "FRLFF", "ATOP"}:
            return "SPE_RtWat"
        if n in {"FINREF", "SLAREF", "SIZREF", "VSSINK", "EVMODC"}:
            return "SPE_SrcSnk"
        if (n.startswith("TB") or n.startswith("TO1") or
                n.startswith("TO2") or n.startswith("TM")):
            return "SPE_Temp"
        return "SPE_Other"

    if loc == "ECO":
        if n in {"PL-EM", "EM-V1", "V1-JU", "JU-R0", "PM06", "PM09",
                 "LNGSH", "FL-VS", "XMAGE", "XFPHT", "XFINT"}:
            return "ECO_Pheno"
        if n in {"TRIFL", "RWDTH", "RHGHT"}:
            return "ECO_Arch"
        return "ECO_Other"

    if loc == "CUL":
        if n in {"EM-FL", "FL-SH", "FL-SD", "SD-PM", "FL-LF",
                 "SFDUR", "SDPDV", "PODUR"}:
            return "CUL_PheHrv"
        if n in {"LFMAX", "SLAVR", "SIZLF"}:
            return "CUL_Growth"
        if n in {"XFRT", "WTPSD", "THRSH"}:
            return "CUL_HrvPar"
        return "CUL_Other"

    return ""


# ── 默认边界推断 ──────────────────────────────────────────────

def compute_default_bounds(
    name: str,
    init_value: Optional[float],
    location: str,
) -> tuple[Optional[float], Optional[float], str]:
    """根据参数名、初始值和所属文件，推断默认建议边界。

    Returns:
        (lower_bound, upper_bound, status)
        status 为 "active" / "fixed"
    """
    n = str(name).strip().upper()
    if init_value is None:
        return None, None, "fixed"

    init = float(init_value)
    loc = str(location).strip().upper()

    # 1. 尝试查找固定边界表
    if n in DEFAULT_BOUNDS:
        lb, ub = DEFAULT_BOUNDS[n]
        status = "active" if lb != ub else "fixed"
        return lb, ub, status

    # 2. SOIL 按初值比例
    if loc == "SOIL":
        return _soil_bounds(n, init)

    # 3. IC 按初值比例
    if loc == "IC" or n.startswith("IC_SH2O"):
        lb = max(0.01, init * 0.7)
        ub = min(0.80, init * 1.3)
        return lb, ub, "active" if lb != ub else "fixed"

    # 4. 特殊参数
    if n == "VSSINK":
        lb = max(0.2, 0.5 * init)
        ub = max(lb + 0.2, 2.0 * init)
        return lb, ub, "active"

    if n == "KC_SLOPE":
        lb = max(0.0, init - 0.10)
        ub = init + 0.10
        return lb, ub, "active"

    # 5. 通用回退
    if abs(init) < 1e-12:
        return init, init, "fixed"

    if 0.0 < init <= 1.0:
        lb = max(0.0, init * 0.7)
        ub = min(1.0, init * 1.3)
        return lb, ub, "active" if lb != ub else "fixed"

    lb = init * 0.75
    ub = init * 1.25
    if lb > ub:
        lb, ub = ub, lb
    return lb, ub, "active"


def _soil_bounds(name: str, init: float) -> tuple[float, float, str]:
    """SOIL 参数按初值比例推断边界。"""
    n = name.upper()
    if n == "SOIL_SALB":
        return 0.05, 0.35, "active"
    if n == "SOIL_SLDR":
        return 0.10, 2.00, "active"
    if n == "SOIL_SLRO":
        return 40.0, 95.0, "active"
    if n.startswith("SOIL_SLLL"):
        lb = max(0.01, init * 0.8)
        ub = min(0.80, init * 1.2)
        return lb, ub, "active" if lb != ub else "fixed"
    if n.startswith("SOIL_SDUL"):
        lb = max(0.01, init * 0.8)
        ub = min(0.80, init * 1.2)
        return lb, ub, "active" if lb != ub else "fixed"
    if n.startswith("SOIL_SSAT"):
        lb = max(0.01, init * 0.85)
        ub = min(0.80, init * 1.15)
        return lb, ub, "active" if lb != ub else "fixed"
    if n.startswith("SOIL_SBDM"):
        lb = max(0.5, init * 0.9)
        ub = min(2.2, init * 1.1)
        return lb, ub, "active" if lb != ub else "fixed"
    if n.startswith("SOIL_SLOC"):
        lb = max(0.0, init * 0.7)
        ub = min(10.0, init * 1.3)
        return lb, ub, "active" if lb != ub else "fixed"
    if n == "SOIL_SLNF":
        lb = max(0.5, init * 0.8)
        ub = min(3.0, init * 1.3)
        return lb, ub, "active" if lb != ub else "fixed"
    # 通用
    lb = max(0.0, init * 0.8)
    ub = init * 1.2
    return lb, ub, "active" if lb != ub else "fixed"


# ── 物理边界检查 ──────────────────────────────────────────────

def clamp_to_physical(
    name: str,
    lower: Optional[float],
    upper: Optional[float],
) -> tuple[Optional[float], Optional[float]]:
    """将候选边界截断到物理硬边界范围内。"""
    n = name.strip().upper()
    if n not in PHYSICAL_BOUNDS:
        return lower, upper
    phys_lb, phys_ub = PHYSICAL_BOUNDS[n]
    if lower is not None:
        lower = max(lower, phys_lb)
    if upper is not None:
        upper = min(upper, phys_ub)
    return lower, upper


# ── 冻结边界校验 ──────────────────────────────────────────────

@dataclass(frozen=True)
class ValidationIssue:
    """Machine-readable parameter validation finding."""

    code: str
    message: str
    parameter: str = ""
    severity: str = "error"

    def __str__(self) -> str:
        subject = f" [{self.parameter}]" if self.parameter else ""
        return f"{self.severity.upper()} {self.code}{subject}: {self.message}"


def validate_frozen_bounds(path: str) -> list[ValidationIssue]:
    """Validate a frozen bounds CSV without changing it.

    Frozen inputs are immutable scientific decisions.  Invalid ranges are
    rejected rather than reordered, clipped, or expanded automatically.
    """
    required = {
        "name", "init", "lower", "upper", "status", "pargp",
        "location", "file", "cultivar", "ecotype", "mode",
    }
    issues: list[ValidationIssue] = []
    if not os.path.isfile(path):
        return [ValidationIssue("FILE_NOT_FOUND", f"Frozen bounds file not found: {path}")]

    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = sorted(required - columns)
        if missing:
            return [ValidationIssue("MISSING_COLUMNS", f"Missing required columns: {', '.join(missing)}")]
        rows = list(reader)

    if not rows:
        return [ValidationIssue("EMPTY_REGISTRY", "Frozen bounds file contains no parameters")]

    seen: set[str] = set()
    parsed: dict[str, dict[str, object]] = {}
    allowed_status = {"active", "fixed", "disabled"}
    for row_number, row in enumerate(rows, start=2):
        name = str(row.get("name", "")).strip().upper()
        status = str(row.get("status", "")).strip().lower()
        location = str(row.get("location", "")).strip().upper()
        target_file = str(row.get("file", "")).strip()
        parameter_group = str(row.get("pargp", "")).strip()
        if not name:
            issues.append(ValidationIssue("EMPTY_NAME", f"Row {row_number} has no parameter name"))
            continue
        if name in seen:
            issues.append(ValidationIssue("DUPLICATE_NAME", "Parameter name occurs more than once", name))
        seen.add(name)
        if status not in allowed_status:
            issues.append(ValidationIssue("INVALID_STATUS", f"Unsupported status {status!r}", name))
        if not parameter_group:
            issues.append(ValidationIssue("EMPTY_PARAMETER_GROUP", "pargp is required", name))
        # ``DERIVED`` is PEST-side only: it projects a seasonal parameter and
        # is never written directly into a DSSAT input file.
        allowed_locations = {"CUL", "ECO", "SPE", "SOIL", "IC", "INIT", "DERIVED"}
        if location not in allowed_locations:
            issues.append(ValidationIssue("INVALID_LOCATION", f"Unsupported location {location!r}", name))
        if not target_file:
            issues.append(ValidationIssue("EMPTY_TARGET_FILE", "Target file is required", name))
        elif location in {"CUL", "ECO", "SPE"} and f".{location}" not in target_file.upper():
            issues.append(ValidationIssue("FILE_LOCATION_MISMATCH", f"{location} parameter targets {target_file!r}", name))
        elif location == "SOIL" and not target_file.upper().endswith(".SOL"):
            issues.append(ValidationIssue("FILE_LOCATION_MISMATCH", f"SOIL parameter targets {target_file!r}", name))
        elif location in {"IC", "INIT"} and Path(target_file).suffix.upper() not in {".TMX", ".TMA", ".TMT"}:
            issues.append(ValidationIssue("FILE_LOCATION_MISMATCH", f"IC parameter targets {target_file!r}", name))
        elif location == "DERIVED" and target_file.lower() != "seasonal_offsets.json":
            issues.append(
                ValidationIssue(
                    "FILE_LOCATION_MISMATCH",
                    "DERIVED parameters must target 'seasonal_offsets.json'",
                    name,
                )
            )

        values: dict[str, float] = {}
        for key in ("init", "lower", "upper"):
            raw = row.get(key)
            try:
                value = float(raw)
            except (TypeError, ValueError):
                issues.append(ValidationIssue("NON_NUMERIC", f"{key}={raw!r} is not numeric", name))
                continue
            if not math.isfinite(value):
                issues.append(ValidationIssue("NON_FINITE", f"{key} must be finite", name))
                continue
            values[key] = value

        if len(values) == 3:
            init, lower, upper = values["init"], values["lower"], values["upper"]
            if lower > upper:
                issues.append(ValidationIssue("REVERSED_BOUNDS", f"lower {lower:g} exceeds upper {upper:g}", name))
            if not lower <= init <= upper:
                issues.append(ValidationIssue("INIT_OUTSIDE_BOUNDS", f"init {init:g} not in [{lower:g}, {upper:g}]", name))
            if status == "fixed" and not (lower == init == upper):
                issues.append(ValidationIssue("FIXED_NOT_CONSTANT", "fixed requires lower == init == upper", name))
            if status == "active" and lower == upper:
                issues.append(
                    ValidationIssue(
                        "ACTIVE_ZERO_WIDTH",
                        "active parameters require lower < upper",
                        name,
                    )
                )

            physical = PHYSICAL_BOUNDS.get(name)
            if physical:
                phys_lower, phys_upper = physical
                tolerance = 1e-12 * max(abs(phys_lower), abs(phys_upper), 1.0)
                if (
                    min(init, lower, upper) < phys_lower - tolerance
                    or max(init, lower, upper) > phys_upper + tolerance
                ):
                    issues.append(
                        ValidationIssue(
                            "OUTSIDE_PHYSICAL_BOUNDS",
                            f"values must stay within [{phys_lower:g}, {phys_upper:g}]",
                            name,
                        )
                    )
            parsed[name] = {**values, "status": status, "location": location}

        if status == "active" and location in {"SOIL", "IC", "INIT"}:
            issues.append(
                ValidationIssue(
                    "NUISANCE_PARAMETER_ACTIVE",
                    "SOIL/IC parameters are fixed by default and require explicit scientific approval",
                    name,
                    severity="warning",
                )
            )

    _validate_temperature_relationships(parsed, issues)
    _validate_stage_relationships(parsed, issues)
    _validate_soil_water_relationships(parsed, issues)
    return issues


def _validate_stage_relationships(
    parsed: dict[str, dict[str, object]], issues: list[ValidationIssue]
) -> None:
    """Validate strict stage relations across every independent sample."""
    if not all(name in parsed for name in ("XMAGE", "XFPHT")):
        return
    if float(parsed["XMAGE"]["init"]) >= float(parsed["XFPHT"]["init"]):
        issues.append(ValidationIssue("STAGE_INIT_ORDER", "Expected XMAGE < XFPHT", "XMAGE/XFPHT"))
    if float(parsed["XMAGE"]["upper"]) >= float(parsed["XFPHT"]["lower"]):
        issues.append(
            ValidationIssue(
                "STAGE_RANGE_ORDER",
                "Independent ranges do not guarantee XMAGE < XFPHT",
                "XMAGE/XFPHT",
                severity="warning",
            )
        )


def _validate_temperature_relationships(
    parsed: dict[str, dict[str, object]], issues: list[ValidationIssue]
) -> None:
    groups = [
        ("TB", "TO1", "TO2", "TM"),
        ("TB1", "TO11", "TO21", "TM1"),
        ("TB2", "TO12", "TO22", "TM2"),
        ("TB3", "TO13", "TO23", "TM3"),
    ]
    for names in groups:
        if not all(name in parsed for name in names):
            continue
        init_values = [float(parsed[name]["init"]) for name in names]
        if not all(a < b for a, b in zip(init_values, init_values[1:])):
            issues.append(
                ValidationIssue("TEMP_INIT_ORDER", f"Expected {' < '.join(names)} at initial values", "/".join(names))
            )
        for left, right in zip(names, names[1:]):
            if float(parsed[left]["upper"]) >= float(parsed[right]["lower"]):
                issues.append(
                    ValidationIssue(
                        "TEMP_RANGE_ORDER",
                        f"Independent ranges do not guarantee {left} < {right}",
                        f"{left}/{right}",
                    )
                )


def _validate_soil_water_relationships(
    parsed: dict[str, dict[str, object]], issues: list[ValidationIssue]
) -> None:
    suffixes: set[str] = set()
    for name in parsed:
        for marker in ("SOIL_SLLL_", "SOIL_SDUL_", "SOIL_SSAT_"):
            if name.startswith(marker):
                suffixes.add(name[len(marker):])
    for suffix in sorted(suffixes):
        names = tuple(f"SOIL_{kind}_{suffix}" for kind in ("SLLL", "SDUL", "SSAT"))
        if not all(name in parsed for name in names):
            continue
        init_values = [float(parsed[name]["init"]) for name in names]
        if not all(a < b for a, b in zip(init_values, init_values[1:])):
            issues.append(
                ValidationIssue("SOIL_WATER_INIT_ORDER", "Expected SLLL < SDUL < SSAT", "/".join(names))
            )
        for left, right in zip(names, names[1:]):
            if float(parsed[left]["upper"]) >= float(parsed[right]["lower"]):
                issues.append(
                    ValidationIssue(
                        "SOIL_WATER_RANGE_ORDER",
                        f"Independent ranges do not guarantee {left} < {right}",
                        f"{left}/{right}",
                    )
                )


def assert_valid_frozen_bounds(path: str | Path) -> list[ValidationIssue]:
    """Raise ValueError when a frozen file has any error-level finding."""
    issues = validate_frozen_bounds(path)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        preview = "\n".join(str(issue) for issue in errors[:30])
        raise ValueError(f"Frozen bounds validation failed ({len(errors)} errors):\n{preview}")
    return issues


# ── 注册表 I/O ────────────────────────────────────────────────

@dataclass
class RegistryEntry:
    """一条参数注册表记录。"""
    parameter_name: str
    crop: str = ""
    parameter_family: str = ""   # CUL / ECO / SPE / SOIL / INIT
    target_file: str = ""
    section: str = ""
    dtype: str = "float"
    format_width: int = 6
    format_precision: int = 3
    base_value: Optional[float] = None
    physical_lower: Optional[float] = None
    physical_upper: Optional[float] = None
    default_step: Optional[float] = None
    calibration_stage: str = ""
    enabled_by_default: bool = True
    description: str = ""


def load_registry_csv(path: str) -> list[RegistryEntry]:
    """从 CSV 加载参数注册表。"""
    entries: list[RegistryEntry] = []
    if not os.path.exists(path):
        return entries
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entry = RegistryEntry(
                parameter_name=row.get("parameter_name", ""),
                crop=row.get("crop", ""),
                parameter_family=row.get("parameter_family", ""),
                target_file=row.get("target_file", ""),
                section=row.get("section", ""),
                dtype=row.get("dtype", "float"),
                format_width=int(row.get("format_width", 6) or 6),
                format_precision=int(row.get("format_precision", 3) or 3),
                base_value=_safe_float(row.get("base_value")),
                physical_lower=_safe_float(row.get("physical_lower")),
                physical_upper=_safe_float(row.get("physical_upper")),
                default_step=_safe_float(row.get("default_step")),
                calibration_stage=row.get("calibration_stage", ""),
                enabled_by_default=row.get("enabled_by_default", "true").lower() in ("true", "1", "yes"),
                description=row.get("description", ""),
            )
            entries.append(entry)
    return entries


def save_registry_csv(entries: list[RegistryEntry], path: str) -> None:
    """保存参数注册表到 CSV。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=REGISTRY_COLUMNS)
        writer.writeheader()
        for e in entries:
            writer.writerow({
                "parameter_name": e.parameter_name,
                "crop": e.crop,
                "parameter_family": e.parameter_family,
                "target_file": e.target_file,
                "section": e.section,
                "dtype": e.dtype,
                "format_width": e.format_width,
                "format_precision": e.format_precision,
                "base_value": _fmt_float(e.base_value),
                "physical_lower": _fmt_float(e.physical_lower),
                "physical_upper": _fmt_float(e.physical_upper),
                "default_step": _fmt_float(e.default_step),
                "calibration_stage": e.calibration_stage,
                "enabled_by_default": str(e.enabled_by_default).lower(),
                "description": e.description,
            })


def _safe_float(val) -> Optional[float]:
    if val is None or str(val).strip() == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _fmt_float(val: Optional[float]) -> str:
    if val is None:
        return ""
    if val == int(val):
        return str(int(val))
    return f"{val:.6g}"
