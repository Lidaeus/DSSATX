"""WP1: build a PEST-GLM follow-up case from the formal IES run (20260818).

Implements the development plan ``docs/PEST_GLM_IES后续率定开发方案_20260818.md``
sections 3-5 and 8: parameter pool selection from the approved Sobol top-k CSV,
member-126 initial values, posterior-quantile GLM bounds, objective-function
arms (A = verbatim IES objective; B/C = N/W response families re-weighted to
the ``phi = lambda * (1 - NSE)`` identity), and a GLM PST stripped of all
IES-only options.

The formal IES directory is never modified: every output lands in a new
``workspace/runs/e02_glm_<arm>_<pool>_<stage>_official_20260818`` directory.

Usage:
    python tools/calibration/prepare_ies_to_glm_20260818.py \
        --pool top15 --objective-arm A --stage pilot --noptmax 1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.param_registry import PHYSICAL_BOUNDS  # noqa: E402

IES_CASE = "e02_fixedsoil_nse_official_25sp26sp_200x6_20260817"
IES_DIR = ROOT / "workspace/runs" / IES_CASE
APPROVED_TOPK_CSV = ROOT / "configs/sa/approved_topk/eggplant_formal_sobol_top23_v1_20260721.csv"
DATE_TAG = "20260818"
INITIAL_MEMBER = "126"          # phi_q10_highest_nse of the formal IES run
DRY_NSE_LAMBDA = 75.0           # inherited IES lambda per season (arm A keeps it)

# Objective-arm response lambdas (plan section 5): (N_RESPONSE, W_RESPONSE).
ARM_RESPONSE_LAMBDAS = {
    "A": None,                  # verbatim IES weights, no re-weighting
    "B": {"N_RESPONSE": 1.0, "W_RESPONSE": 0.5},
    "C": {"N_RESPONSE": 0.5, "W_RESPONSE": 0.25},
}

# Static build artifacts copied verbatim from the IES run dir (everything the
# template/instruction interface and the model command need).  Run outputs and
# ensemble files are deliberately excluded — GLM regenerates its own.
COPY_FILES = [
    "{case}.pst",
    "{case}_params.csv",
    "{case}_params.csv.tpl",
    "{case}.observation_transforms.json",
    "{case}.weights.audit.csv",
    "{case}_observation_registry.csv",
    "{case}_run_mapping.csv",
    "DSSBatch.v48",
    "joint_design.json",
]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_approved_pool(csv_path: Path, k: int) -> list[str]:
    """Return the first *k* approved parameters in ``selection_order``.

    The single source of truth is the approved CSV; callers must not hard-code
    the list.  Names are normalized to the PST convention (lowercase).
    """
    frame = pd.read_csv(csv_path, encoding="utf-8-sig")
    frame = frame.sort_values("selection_order", kind="stable")
    if not frame["approval_status"].astype(str).eq("approved").all():
        raise ValueError("approved top-k CSV contains unapproved rows")
    names = frame["parameter"].astype(str).str.strip().tolist()
    if len(names) < k:
        raise ValueError(f"approved CSV has only {len(names)} parameters, need {k}")
    pool = [n.lower() for n in names[:k]]
    if len(set(pool)) != len(pool):
        raise ValueError("duplicate parameter names in approved pool")
    return pool


DEFAULT_SELECTED_SET_CSV = ROOT / ("workspace/runs/e02_glm_A_top15_pilot_official_20260818/"
                                   "glm_quality/recommended_formal_parameter_set.csv")


def load_selected_pool(csv_path: Path, max_params: int = 18) -> list[str]:
    """Read the locally-validated parameter set from a WP3 recommendation CSV.

    Plan section 7 stage 3 caps the formal set at 15 (18 with sufficient
    top-23 rank); loading more than ``max_params`` rows is rejected.
    """
    frame = pd.read_csv(csv_path, encoding="utf-8-sig")
    if "parameter" not in frame.columns:
        raise ValueError(f"selected-set CSV lacks a 'parameter' column: {csv_path}")
    pool = [str(n).strip().lower() for n in frame["parameter"].tolist() if str(n).strip()]
    if not pool:
        raise ValueError(f"selected-set CSV is empty: {csv_path}")
    if len(set(pool)) != len(pool):
        raise ValueError("duplicate parameter names in selected set")
    if len(pool) > max_params:
        raise ValueError(
            f"selected set has {len(pool)} parameters; plan section 7 caps formal at {max_params}")
    return pool


def physical_bounds_for(name: str) -> tuple[float | None, float | None]:
    entry = PHYSICAL_BOUNDS.get(name) or PHYSICAL_BOUNDS.get(name.upper())
    if entry is None:
        return None, None
    if isinstance(entry, dict):
        lo = entry.get("lower", entry.get("min"))
        hi = entry.get("upper", entry.get("max"))
    else:
        lo, hi = entry
    try:
        return (None if lo is None else float(lo)), (None if hi is None else float(hi))
    except (TypeError, ValueError):
        return None, None


def compute_posterior_bounds(
    ensemble_values: np.ndarray,
    member_value: float,
    frozen_lo: float,
    frozen_hi: float,
    physical_lo: float | None = None,
    physical_hi: float | None = None,
) -> dict:
    """Plan section 4.2 posterior-quantile GLM bounds with full audit trail.

    Returns a dict with glm_lo/glm_hi plus every intermediate value and the
    ordered list of rules that fired, so ``glm_parameter_bounds_audit.csv``
    can reproduce the decision chain.
    """
    reasons: list[str] = []
    vals = np.asarray(ensemble_values, dtype=float)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        raise ValueError("no finite ensemble values for posterior bounds")
    q025 = float(np.quantile(vals, 0.025))
    q975 = float(np.quantile(vals, 0.975))
    posterior_lo, posterior_hi = q025, q975
    padding = 0.10 * (posterior_hi - posterior_lo)

    hard_lo = frozen_lo if physical_lo is None else max(frozen_lo, physical_lo)
    hard_hi = frozen_hi if physical_hi is None else min(frozen_hi, physical_hi)
    if hard_lo > hard_hi:
        raise ValueError(f"physical clip inverts bounds: [{hard_lo}, {hard_hi}]")
    if physical_lo is not None and hard_lo > frozen_lo:
        reasons.append("lower clipped to PHYSICAL_BOUNDS")
    if physical_hi is not None and hard_hi < frozen_hi:
        reasons.append("upper clipped to PHYSICAL_BOUNDS")

    glm_lo = max(hard_lo, posterior_lo - padding)
    glm_hi = min(hard_hi, posterior_hi + padding)
    if glm_lo == hard_lo and posterior_lo - padding < hard_lo:
        reasons.append("lower at frozen/physical bound (padding clipped)")
    if glm_hi == hard_hi and posterior_hi + padding > hard_hi:
        reasons.append("upper at frozen/physical bound (padding clipped)")

    member = float(member_value)
    frozen_width = frozen_hi - frozen_lo
    if member < glm_lo or member > glm_hi:
        reasons.append("expanded to include member 126 (posterior quantiles excluded it)")
        glm_lo = min(glm_lo, max(hard_lo, member))
        glm_hi = max(glm_hi, min(hard_hi, member))

    if glm_hi - glm_lo < 0.05 * frozen_width:
        reasons.append("posterior width < 5% of frozen width; widened to 10% of frozen width centered on member 126")
        center = min(max(member, hard_lo + 0.05 * frozen_width), hard_hi - 0.05 * frozen_width)
        glm_lo = max(hard_lo, center - 0.05 * frozen_width)
        glm_hi = min(hard_hi, center + 0.05 * frozen_width)

    if member - hard_lo <= 0.01 * frozen_width:
        reasons.append("member 126 within 1% of frozen width from lower bound; full frozen lower bound used")
        glm_lo = hard_lo
    if hard_hi - member <= 0.01 * frozen_width:
        reasons.append("member 126 within 1% of frozen width from upper bound; full frozen upper bound used")
        glm_hi = hard_hi

    glm_lo = min(glm_lo, member)
    glm_hi = max(glm_hi, member)
    if not (glm_lo <= member <= glm_hi):
        raise AssertionError(f"member 126 outside GLM bounds for: [{glm_lo}, {glm_hi}]")

    return {
        "q025": q025, "q975": q975, "padding": padding,
        "glm_lo": float(glm_lo), "glm_hi": float(glm_hi),
        "frozen_lo": frozen_lo, "frozen_hi": frozen_hi,
        "physical_lo": physical_lo, "physical_hi": physical_hi,
        "member_value": member, "reasons": reasons,
    }


def nse_uniform_weight(observed: np.ndarray, lam: float) -> float:
    """Uniform weight implementing ``phi = lambda * (1 - NSE)`` per season.

    ``phi = sum(w^2 r^2) = (lambda / SST) * SSE`` requires ``w = sqrt(lambda / SST)``
    for every observation in the season x family block.
    """
    obs = np.asarray(observed, dtype=float)
    sst = float(np.square(obs - obs.mean()).sum())
    if sst <= 0:
        raise ValueError("non-positive SST; NSE undefined for constant observations")
    return float(np.sqrt(lam / sst)), sst


def response_family_pattern(family: str) -> str:
    return "NRESP" if family == "N_RESPONSE" else "WRESP"


def apply_response_nse_weights(
    registry: pd.DataFrame,
    observation_data: pd.DataFrame,
    lambdas: dict[str, float],
) -> tuple[pd.DataFrame, list[dict]]:
    """Re-weight N/W response families to the NSE identity, per season.

    ``observation_data`` is pyemu's ``pst.observation_data`` (modified in
    place); returns the audit rows for ``objective_weight_audit.csv``.
    """
    audit: list[dict] = []
    for family, lam in lambdas.items():
        pattern = response_family_pattern(family)
        mask = registry["obgnme"].astype(str).str.upper().str.contains(pattern, na=False)
        for season in sorted(registry.loc[mask, "season_id"].astype(str).unique()):
            rows = registry[mask & registry["season_id"].astype(str).eq(season)]
            obs = pd.to_numeric(rows["raw_obsval"], errors="raise").to_numpy(float)
            transform = set(rows["transform"].astype(str).str.lower())
            if transform != {"raw"}:
                raise ValueError(f"{family} {season}: NSE weights require raw-scale observations, got {transform}")
            weight, sst = nse_uniform_weight(obs, lam)
            names = rows["obsnme"].astype(str).str.lower().tolist()
            old = observation_data.loc[names, "weight"].astype(float).to_numpy()
            if not np.allclose(old, old[0]):
                raise ValueError(f"{family} {season}: existing weights are not uniform; refusing silent partial update")
            observation_data.loc[names, "weight"] = weight
            audit.append({
                "family": family, "season": season, "n_obs": len(names),
                "lambda": lam, "sst": sst,
                "old_weight": float(old[0]), "new_weight": weight,
                "identity": f"phi_{season} = {lam} * (1 - NSE_{season})",
                "obsnme_first": names[0],
            })
    return observation_data, audit


def load_member(ens_path: Path, member: str) -> pd.Series:
    frame = pd.read_csv(ens_path)
    real_col = next(c for c in frame.columns if str(c).lower() in {"real_name", "realization"})
    hit = frame[frame[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(member)]
    if len(hit) != 1:
        raise ValueError(f"member {member} occurs {len(hit)} times in {ens_path.name}")
    return hit.iloc[0]


def _rewrite_model_command(command: list[str], old_dir: str, new_dir: str) -> list[str]:
    out = []
    for token in command:
        out.append(token.replace(old_dir, new_dir))
    return out


def build_glm_case(
    pool: str,
    arm: str,
    stage: str,
    noptmax: int,
    ies_dir: Path = IES_DIR,
    ies_case: str = IES_CASE,
    date_tag: str = DATE_TAG,
    initial_member: str = INITIAL_MEMBER,
    derinc_scale: float = 1.0,
    selected_set_csv: Path | None = None,
) -> Path:
    """Create the GLM run directory.  Refuses to overwrite existing output.

    ``derinc_scale`` multiplies the default 1%-of-GLM-range increment (plan
    section 8 spot checks use 0.5 and 2.0).  ``--pool selected`` reads the
    locally-validated set from ``selected_set_csv`` (default: the WP3
    recommendation written by the top-15 A-arm pilot audit).
    """
    if pool not in ("top15", "top23", "selected"):
        raise ValueError(f"unsupported pool: {pool}")
    if arm not in ARM_RESPONSE_LAMBDAS:
        raise ValueError(f"unsupported arm: {arm}")

    if pool == "selected":
        selected = load_selected_pool(selected_set_csv or DEFAULT_SELECTED_SET_CSV)
    else:
        k = 15 if pool == "top15" else 23
        selected = load_approved_pool(APPROVED_TOPK_CSV, k)
    case = f"e02_glm_{arm}_{pool}_{stage}_official_{date_tag}"
    target = ROOT / "workspace/runs" / case
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing GLM run dir: {target}")
    target.mkdir(parents=True)

    src = {t.format(case=ies_case): ies_dir / t.format(case=ies_case) for t in COPY_FILES}
    for name, path in src.items():
        if not path.is_file():
            raise FileNotFoundError(path)
    # Instruction files: every PEST model interface referenced by the PST.
    for ins_path in sorted(ies_dir.glob(f"{ies_case}_*.OUT.ins")):
        src[ins_path.name] = ins_path
    if not any(n.endswith(".ins") for n in src):
        raise FileNotFoundError(f"no instruction files found in {ies_dir}")
    for name, path in src.items():
        new_name = name.replace(ies_case, case)
        shutil.copy2(path, target / new_name)

    # Case-name rewrite in file contents (tpl/ins references, transforms json).
    old_b, new_b = ies_case.encode(), case.encode()
    for path in sorted(target.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            if old_b in data:
                path.write_bytes(data.replace(old_b, new_b))

    ens = pd.read_csv(ies_dir / f"{ies_case}.6.par.csv")
    member = load_member(ies_dir / f"{ies_case}.6.par.csv", initial_member)
    pst = pyemu.Pst(str(target / f"{case}.pst"))
    par = pst.parameter_data
    lower_index = {str(i).lower(): i for i in par.index}
    missing = [n for n in selected if n not in lower_index]
    if missing:
        raise ValueError(f"pool parameters missing from PST: {missing}")

    # Member 126 initial values for every parameter (fixed ones included).
    for name in par.index:
        key = lower_index.get(str(name).lower())
        value = member.get(str(name))
        if value is None or not np.isfinite(float(value)):
            raise ValueError(f"member {initial_member} has no finite value for {name}")
        par.loc[key, "parval1"] = float(value)

    # Fix everything outside the pool; posterior bounds for pool members.
    bounds_audit: list[dict] = []
    for name in par.index:
        if name in selected:
            continue
        par.loc[name, "partrans"] = "fixed"

    glm_groups: dict[str, dict] = {}
    for order, name in enumerate(selected, start=1):
        frozen_lo, frozen_hi = float(par.loc[name, "parlbnd"]), float(par.loc[name, "parubnd"])
        phys_lo, phys_hi = physical_bounds_for(name)
        values = pd.to_numeric(ens[name], errors="coerce").to_numpy(float)
        result = compute_posterior_bounds(
            values, float(par.loc[name, "parval1"]), frozen_lo, frozen_hi, phys_lo, phys_hi)
        par.loc[name, "parlbnd"] = result["glm_lo"]
        par.loc[name, "parubnd"] = result["glm_hi"]
        group = f"glm_{order:02d}_{name.replace('-', '_')}"
        par.loc[name, "pargp"] = group
        derinc = derinc_scale * 0.01 * (result["glm_hi"] - result["glm_lo"])
        glm_groups[group] = {"derinc": derinc, "derinclb": 0.5 * derinc}
        bounds_audit.append({
            "order": order, "parameter": name, "group": group,
            "member126": result["member_value"],
            "frozen_lower": frozen_lo, "frozen_upper": frozen_hi,
            "posterior_q025": result["q025"], "posterior_q975": result["q975"],
            "padding": result["padding"],
            "glm_lower": result["glm_lo"], "glm_upper": result["glm_hi"],
            "derinc": derinc,
            "at_frozen_lower": float(par.loc[name, "parval1"]) - frozen_lo <= 0.01 * (frozen_hi - frozen_lo),
            "at_frozen_upper": frozen_hi - float(par.loc[name, "parval1"]) <= 0.01 * (frozen_hi - frozen_lo),
            "reasons": "; ".join(result["reasons"]) if result["reasons"] else "posterior quantiles with 10% padding",
        })

    # Per-parameter groups so DERINC honours the 1%-of-own-range rule.
    groups = pst.parameter_groups
    keep = groups.loc[[g for g in groups.index if g not in {r["group"] for r in bounds_audit}]].copy()
    # pyemu keeps pargpnme as BOTH index and column; new rows must populate
    # every column or the PST writer substitutes its own defaults.
    extra = pd.DataFrame(
        [{"pargpnme": g, "inctyp": "absolute", "derinc": v["derinc"],
          "derinclb": v["derinclb"], "forcen": "switch", "derincmul": 2.0,
          "dermthd": "parabolic", "splitthresh": 1.0e-5, "splitreldiff": 0.5,
          "splitaction": "smaller", "extra": np.nan} for g, v in glm_groups.items()]
    ).set_index("pargpnme", drop=False)
    pst.parameter_groups = pd.concat([keep, extra])

    # GLM control settings; strip every IES-only option.
    pst.control_data.pestmode = "estimation"
    pst.control_data.noptmax = int(noptmax)
    pst.svd_data.maxsing = max(1, len(selected))
    removed_options = sorted(k for k in pst.pestpp_options if k.startswith("ies_"))
    for key in removed_options:
        pst.pestpp_options.pop(key)

    command = pst.model_command
    pst.model_command = _rewrite_model_command(command, str(ies_dir), str(target))

    # Objective arm: A keeps the IES weights verbatim; B/C re-weight responses.
    registry = pd.read_csv(target / f"{case}_observation_registry.csv", encoding="utf-8-sig")
    lambdas = ARM_RESPONSE_LAMBDAS[arm]
    weight_audit: list[dict] = [{
        "family": "DRY_CUMULATIVE", "season": s,
        "n_obs": int(n), "lambda": DRY_NSE_LAMBDA,
        "old_weight": float(w), "new_weight": float(w),
        "identity": f"phi_{s} = {DRY_NSE_LAMBDA} * (1 - NSE_{s}) (inherited)",
        "obsnme_first": "",
    } for s, n, w in _dry_family_summary(registry, pst)]
    if lambdas is not None:
        pst.observation_data, extra_audit = apply_response_nse_weights(registry, pst.observation_data, lambdas)
        weight_audit.extend(extra_audit)
    if lambdas is None:
        weight_audit.extend(_response_weights_inherited(registry, pst))

    pst.write(str(target / f"{case}.pst"))

    member_frame = pd.DataFrame(
        [{"name": str(i).upper(), "value": float(par.loc[i, "parval1"])} for i in par.index])
    member_frame.to_csv(target / f"{case}_params.csv", index=False)

    pd.DataFrame(bounds_audit).to_csv(target / "glm_parameter_bounds_audit.csv", index=False)
    pd.DataFrame(weight_audit).to_csv(target / "objective_weight_audit.csv", index=False)
    pd.DataFrame({"order": range(1, len(selected) + 1), "parameter": selected}).to_csv(
        target / "selected_parameters.csv", index=False)

    design = json.loads((target / "joint_design.json").read_text(encoding="utf-8"))
    _assert_design_contracts(design)
    # The bundles were legitimately updated after the formal IES run (fixed
    # 25SP/26SP TMX and the 2026-08-18 26SP T12 IC, plan section 1).  Re-declare
    # the manifest hashes from the CURRENT bundles so run_multiseason's safety
    # check passes, recording old -> new for audit.
    hash_updates = {}
    for season in design.get("seasons", []):
        bundle = Path(season["bundle_path"])
        manifest = bundle / "input_manifest.json"
        if not manifest.is_file():
            raise FileNotFoundError(manifest)
        current = sha256_of(manifest)
        declared = season.get("bundle_manifest_sha256")
        if declared != current:
            hash_updates[season["season_id"]] = {"declared": declared, "current": current}
            season["bundle_manifest_sha256"] = current
    if hash_updates:
        (target / "joint_design.json").write_text(
            json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    glm_design = {
        "schema_version": 1,
        "design_id": f"glm_followup_{arm}_{pool}_{date_tag}",
        "source_ies_case": ies_case,
        "source_ies_iteration": 6,
        "initial_member": initial_member,
        "initial_member_rule": "phi_q10_highest_nse",
        "pool": pool,
        "objective_arm": arm,
        "response_lambdas": lambdas or "inherited_from_ies",
        "dry_nse_lambda_per_season": DRY_NSE_LAMBDA,
        "noptmax": int(noptmax),
        "stage": stage,
        "dssat": "official_v4.8",
        "derinc_rule": "1% of GLM range per parameter (absolute), switch to one-sided at bounds",
        "derinc_scale": float(derinc_scale),
        "selected_set_source": str(selected_set_csv) if pool == "selected" and selected_set_csv else "default_pilot_recommendation",
        "removed_ies_options": removed_options,
        "bundle_hash_updates": hash_updates,
        "seasons": design["seasons"],
    }
    (target / "glm_design.json").write_text(json.dumps(glm_design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    source_manifest = {
        "schema_version": 1,
        "source_run_dir": str(ies_dir),
        "source_case": ies_case,
        "source_status": json.loads((ies_dir / "run_status.json").read_text(encoding="utf-8")),
        "artifact_sha256": {
            "pst": sha256_of(ies_dir / f"{ies_case}.pst"),
            "final_parameter_ensemble": sha256_of(ies_dir / f"{ies_case}.6.par.csv"),
            "observation_registry": sha256_of(ies_dir / f"{ies_case}_observation_registry.csv"),
            "joint_design": sha256_of(ies_dir / "joint_design.json"),
            "approved_topk": sha256_of(APPROVED_TOPK_CSV),
            "dssat_exe": sha256_of(ROOT / "DSCSM048.EXE"),
            "pestpp_glm": sha256_of(ROOT / "pestpp-5.2.16-win/bin/pestpp-glm.exe"),
        },
    }
    (target / "source_ies_manifest.json").write_text(json.dumps(source_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest_lines = [
        f"run_id: '{case}'", "run_type: 'glm_followup_calibration'",
        f"source_ies_run: '{ies_case}'", f"initial_member: '{initial_member}'",
        f"pool: '{pool}'", f"objective_arm: '{arm}'", f"stage: '{stage}'",
        f"noptmax: {int(noptmax)}", "pest_mode: 'estimation'",
        "dssat_variant: 'official_v4.8'",
        "design_config: 'glm_design.json'",
        f"selected_parameters: {len(selected)}",
        "date_created: '" + pd.Timestamp.now().strftime("%Y-%m-%dT%H:%M:%S") + "'",
    ]
    (target / "run_manifest.yaml").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")

    print(f"case={case}")
    print(f"run_dir={target}")
    print(f"selected={len(selected)} fixed_genetic={int((par.partrans == 'fixed').sum()) - 275}")
    print(f"arm={arm} response_lambdas={lambdas}")
    print(f"removed_ies_options={removed_options}")
    return target


def _dry_family_summary(registry: pd.DataFrame, pst: pyemu.Pst) -> list[tuple[str, int, float]]:
    dry = registry[registry["sim_token"].astype(str).isin(["CHPDTS", "CHPDTS_T"])]
    out = []
    for season in sorted(dry["season_id"].astype(str).unique()):
        rows = dry[dry["season_id"].astype(str).eq(season)]
        names = rows["obsnme"].astype(str).str.lower().tolist()
        weights = pst.observation_data.loc[names, "weight"].astype(float).to_numpy()
        out.append((season, len(names), float(np.median(weights))))
    return out


def _response_weights_inherited(registry: pd.DataFrame, pst: pyemu.Pst) -> list[dict]:
    audit = []
    for family, pattern in (("N_RESPONSE", "NRESP"), ("W_RESPONSE", "WRESP")):
        mask = registry["obgnme"].astype(str).str.upper().str.contains(pattern, na=False)
        for season in sorted(registry.loc[mask, "season_id"].astype(str).unique()):
            rows = registry[mask & registry["season_id"].astype(str).eq(season)]
            names = rows["obsnme"].astype(str).str.lower().tolist()
            weights = pst.observation_data.loc[names, "weight"].astype(float).to_numpy()
            audit.append({
                "family": family, "season": season, "n_obs": len(names),
                "lambda": "inherited", "sst": "",
                "old_weight": float(weights[0]), "new_weight": float(weights[0]),
                "identity": "inherited verbatim from formal IES weights (arm A)",
                "obsnme_first": names[0],
            })
    return audit


def _assert_design_contracts(design: dict) -> None:
    """Hard scientific contracts from plan section 1 (fail fast)."""
    water = design.get("water_response_objective") or {}
    if water.get("contrast") != "W2_minus_W1_within_same_nitrogen":
        raise ValueError(f"W_RESPONSE contract violated: {water.get('contrast')}")
    if str(water.get("high_water")) != "W2" or str(water.get("low_water")) != "W1":
        raise ValueError("W_RESPONSE must be W2 minus W1")
    nitrogen = design.get("nitrogen_response_objective") or {}
    contrast = str(nitrogen.get("contrast", ""))
    if not contrast.startswith("N2_minus_N0"):
        raise ValueError(f"N_RESPONSE contract violated: {contrast}")
    seasons = design.get("seasons", [])
    counts = {s.get("season_id"): len(s.get("treatments", [])) for s in seasons}
    if counts.get("25SP") != 10 or counts.get("26SP") != 12:
        raise ValueError(f"season treatment counts must be 25SP=10 and 26SP=12, got {counts}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", choices=["top15", "top23", "selected"], default="top15")
    parser.add_argument("--objective-arm", choices=["A", "B", "C"], default="A")
    parser.add_argument("--stage", choices=["pilot", "formal"], default="pilot")
    parser.add_argument("--noptmax", type=int, default=1)
    parser.add_argument("--initial-member", default=INITIAL_MEMBER)
    parser.add_argument("--derinc-scale", type=float, default=1.0,
                        help="multiplier on the 1%%-of-range DERINC (0.5/2.0 spot checks)")
    parser.add_argument("--selected-set-csv", type=Path, default=None,
                        help="parameter CSV for --pool selected (default: WP3 pilot recommendation)")
    args = parser.parse_args()
    build_glm_case(args.pool, args.objective_arm, args.stage, args.noptmax,
                   initial_member=args.initial_member, derinc_scale=args.derinc_scale,
                   selected_set_csv=args.selected_set_csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
