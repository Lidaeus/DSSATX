"""WP5: evaluate PEST-GLM follow-up candidates against the member-126 baseline.

Implements plan ``docs/PEST_GLM_IES后续率定开发方案_20260818.md`` sections 2.1,
6.1 and 6.2.  Three modes:

``--export-baseline``
    Freeze the member-126 baseline metrics (plan section 2.1 values plus the
    deterministic-candidate CSV) into a machine-readable JSON used by later
    evaluations.  Run once; the file is committed under ``configs/runs/``.

``--screen`` (default)
    Compute per-season DRY_CUM / N_RESPONSE / W_RESPONSE NSE and PBIAS from
    the PEST ``.rei`` files of a finished GLM run, apply the engineering
    gates that do not require a deterministic replay, and rank candidates by
    the science-preference rules.  Organ-family gates are marked
    ``not_assessed`` here (the PEST organ observations are signed differences,
    not the raw LAID/LWAD/SWAD series the baseline uses).

``--replay LABEL``
    Deterministically replay a candidate parameter set with the official
    DSSAT (via ``src/calibration/run_multiseason.py``; the GLM variant is the
    official exe, so no swap is needed) inside the GLM run directory and
    compute the full metric set — organ raw-series NSE included — fully
    comparable to the baseline.  ``LABEL=final`` replays ``<case>.par``;
    otherwise ``<LABEL>.par``/``<case>.<LABEL>.par`` is used.  This is plan
    section 7 stage 4.

Outputs live in ``<run_dir>/glm_evaluation/`` (candidate_metrics.csv,
promotion_decision.json) and ``<run_dir>/glm_quality/engineering_quality.json``.

Absolute Phi is never compared across objective arms (plan section 6.2).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

IES_CASE = "e02_fixedsoil_nse_official_25sp26sp_200x6_20260817"
IES_DIR = ROOT / "workspace/runs" / IES_CASE
BASELINE_CANDIDATE_DIR = IES_DIR / "deterministic_candidates/phi_q10_highest_nse_tmxfix_20260818"
BASELINE_JSON = ROOT / "configs/runs/glm_followup_baseline_member126_20260818.json"
SEASONS = ("25SP", "26SP")

# Plan section 2.1 — user-confirmed member-126 response NSEs (20260817 formal IES).
PLAN_BASELINE_RESPONSES = {
    "N_RESPONSE": {"25SP": -0.926381, "26SP": -3.518331},
    "W_RESPONSE": {"25SP": -1.660082, "26SP": -1.461583},
}

# Plan section 6.1 engineering gate thresholds.
GATES = {
    "dry_nse_max_drop": 0.05,
    "pbias_25sp_max_pct": 10.0,
    "pbias_26sp_max_pct": 18.0,
    "organ_nse_max_drop": 0.10,
    "response_nse_mean_max_drop": 0.15,
    "response_family_both_season_drop": 0.10,
}


def nse(observed: np.ndarray, simulated: np.ndarray) -> float:
    obs = np.asarray(observed, float)
    sim = np.asarray(simulated, float)
    sst = float(np.square(obs - obs.mean()).sum())
    if sst <= 0:
        return float("nan")
    return float(1.0 - np.square(sim - obs).sum() / sst)


def pbias_pct(observed: np.ndarray, simulated: np.ndarray) -> float:
    obs = np.asarray(observed, float)
    mean = float(np.abs(obs).mean())
    if mean == 0:
        return float("nan")
    return float(100.0 * (simulated - observed).sum() / observed.sum()) if observed.sum() != 0 else float("nan")


# ── baseline ────────────────────────────────────────────────────────

def export_baseline(out_path: Path = BASELINE_JSON) -> Path:
    csv = BASELINE_CANDIDATE_DIR / "metrics_by_season_variable.csv"
    frame = pd.read_csv(csv)
    dry = frame[(frame["kind"] == "harvest") & (frame["variable"] == "DRY_CUM")]
    organ = frame[(frame["kind"] == "process") & frame["variable"].isin(["LAID", "LWAD", "SWAD", "CHTD"])]

    def table(rows: pd.DataFrame, value: str) -> dict:
        return {str(r["season"]): float(r[value]) for _, r in rows.iterrows()}

    baseline = {
        "schema_version": 1,
        "member": "126",
        "member_rule": "phi_q10_highest_nse of formal IES 20260817",
        "source_deterministic_dir": str(BASELINE_CANDIDATE_DIR),
        "source_metrics_csv": str(csv),
        "DRY_CUM": {
            "nse": table(dry, "nse"),
            "bias": table(dry, "bias"),
            # mean(|obs|) = rmse / (rrmse_pct/100); PBIAS% = bias/mean * 100
            "pbias_pct": {str(r["season"]): 100.0 * float(r["bias"])
                          / (float(r["rmse"]) / (float(r["rrmse_pct"]) / 100.0))
                          for _, r in dry.iterrows()},
        },
        "N_RESPONSE": {"nse": dict(PLAN_BASELINE_RESPONSES["N_RESPONSE"])},
        "W_RESPONSE": {"nse": dict(PLAN_BASELINE_RESPONSES["W_RESPONSE"])},
        "ORGAN": {
            str(v): {"nse": table(organ[organ["variable"] == v], "nse")}
            for v in ("LAID", "LWAD", "SWAD", "CHTD")
        },
        "notes": [
            "DRY_CUM/ORGAN from deterministic replay of member 126 on the fixed TMX (20260818).",
            "N/W response NSE are the user-confirmed formal-IES values (plan section 2.1).",
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"baseline written: {out_path}")
    return out_path


def load_baseline(path: Path | None = None) -> dict:
    path = path or BASELINE_JSON
    if not path.is_file():
        raise FileNotFoundError(f"baseline json missing; run --export-baseline first: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# ── rei parsing and transform inversion ─────────────────────────────

def parse_rei(path: Path) -> pd.DataFrame:
    """Parse a PEST residual file into obsnme/measured/modelled/weight."""
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header_idx = next(i for i, l in enumerate(lines) if l.strip().startswith("Name")
                      and "Measured" in l and "Modelled" in l)
    rows = []
    for line in lines[header_idx + 1:]:
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            rows.append({"obsnme": parts[0].lower(), "group": parts[1],
                         "measured": float(parts[2]), "modelled": float(parts[3]),
                         "weight": float(parts[4])})
        except ValueError:
            continue
    if not rows:
        raise ValueError(f"no rows parsed from {path}")
    return pd.DataFrame(rows)


def invert_transform(value: float, transform: str, offset: float, reference: float) -> float:
    """PEST-obs transforms in this project are ln((y+offset)/reference)."""
    t = str(transform or "raw").lower()
    if t in ("raw", "none", ""):
        return value
    if t == "log":
        return math.exp(value) * (reference if reference > 0 else 1.0) - offset
    raise ValueError(f"unsupported transform: {transform}")


def family_metrics_from_rei(
    rei: pd.DataFrame, registry: pd.DataFrame, family: str
) -> dict[str, dict[str, float]]:
    """Per-season NSE/PBIAS for a family, on the raw observation scale."""
    if family == "DRY_CUM":
        mask = registry["sim_token"].astype(str).isin(["CHPDTS", "CHPDTS_T"])
    elif family == "N_RESPONSE":
        mask = registry["obgnme"].astype(str).str.upper().str.contains("NRESP", na=False)
    elif family == "W_RESPONSE":
        mask = registry["obgnme"].astype(str).str.upper().str.contains("WRESP", na=False)
    else:
        raise ValueError(family)
    out = {}
    for season in SEASONS:
        rows = registry[mask & registry["season_id"].astype(str).eq(season)].copy()
        if rows.empty:
            continue
        rows["obsnme"] = rows["obsnme"].astype(str).str.lower()
        rows = rows.sort_values("obsnme")
        names = rows["obsnme"].tolist()
        idx = rows.set_index("obsnme")
        sub = rei[rei["obsnme"].isin(names)].set_index("obsnme").loc[names]
        if len(sub) != len(names):
            raise ValueError(f"{family} {season}: rei covers {len(sub)}/{len(names)} observations")
        transforms = idx["transform"].astype(str).str.lower()
        offsets = pd.to_numeric(idx["transform_offset"], errors="coerce").fillna(0.0)
        references = pd.to_numeric(idx["transform_reference"], errors="coerce").fillna(1.0)
        obs = np.array([invert_transform(m, t, o, r) for m, t, o, r in
                        zip(sub["measured"], transforms, offsets, references)])
        sim = np.array([invert_transform(m, t, o, r) for m, t, o, r in
                        zip(sub["modelled"], transforms, offsets, references)])
        out[season] = {"n": len(names), "nse": nse(obs, sim), "pbias_pct": pbias_pct(obs, sim)}
    return out


# ── engineering gates and science ranking (plan section 6) ──────────

def engineering_gates(candidate: dict, baseline: dict, source: str) -> tuple[bool, list[dict]]:
    checks = []

    def add(name: str, ok: bool | None, detail: str) -> None:
        checks.append({"gate": name, "status": ("pass" if ok else "fail") if ok is not None else "not_assessed",
                       "detail": detail, "source": source})

    base_dry = baseline["DRY_CUM"]["nse"]
    cand_dry = candidate.get("DRY_CUM", {})
    for season in SEASONS:
        if season not in cand_dry or season not in base_dry:
            add(f"dry_nse_drop_{season}", None, "missing metric")
            continue
        drop = base_dry[season] - cand_dry[season]["nse"]
        add(f"dry_nse_drop_{season}", drop <= GATES["dry_nse_max_drop"],
            f"baseline {base_dry[season]:.4f} -> {cand_dry[season]['nse']:.4f} (drop {drop:.4f})")

    for season, limit in (("25SP", GATES["pbias_25sp_max_pct"]), ("26SP", GATES["pbias_26sp_max_pct"])):
        if season in cand_dry and not math.isnan(cand_dry[season].get("pbias_pct", float("nan"))):
            pb = cand_dry[season]["pbias_pct"]
            add(f"dry_pbias_{season}", abs(pb) <= limit, f"PBIAS {pb:.2f}% vs |{limit}|%")

    for variable in ("LAID", "LWAD", "SWAD"):
        cand = candidate.get("ORGAN", {}).get(variable)
        base = baseline.get("ORGAN", {}).get(variable, {}).get("nse", {})
        if cand is None:
            add(f"organ_nse_{variable}", None, "requires deterministic replay")
            continue
        for season in SEASONS:
            drop = base[season] - cand[season]
            add(f"organ_nse_{variable}_{season}", drop <= GATES["organ_nse_max_drop"],
                f"baseline {base[season]:.4f} -> {cand[season]:.4f}")

    resp_base, resp_cand = [], []
    for family in ("N_RESPONSE", "W_RESPONSE"):
        base = baseline[family]["nse"]
        cand = candidate.get(family, {})
        for season in SEASONS:
            if season not in cand:
                add(f"response_nse_{family}_{season}", None, "missing metric")
                continue
            resp_base.append(base[season])
            resp_cand.append(cand[season]["nse"])
    if len(resp_base) == 4:
        mean_drop = float(np.mean(resp_base) - np.mean(resp_cand))
        add("response_nse_mean_drop", mean_drop <= GATES["response_nse_mean_max_drop"],
            f"baseline mean {np.mean(resp_base):.4f} -> {np.mean(resp_cand):.4f}")
        for family in ("N_RESPONSE", "W_RESPONSE"):
            base = baseline[family]["nse"]
            cand = candidate[family]
            drops = [base[s] - cand[s]["nse"] for s in SEASONS]
            add(f"response_both_seasons_{family}",
                not (drops[0] > GATES["response_family_both_season_drop"]
                     and drops[1] > GATES["response_family_both_season_drop"]),
                f"per-season drops {drops[0]:.4f}, {drops[1]:.4f}")

    passed = all(c["status"] != "fail" for c in checks)
    return passed, checks


def science_promotion(candidate: dict, baseline: dict) -> dict:
    dry_base = baseline["DRY_CUM"]["nse"]
    dry_cand = {s: candidate["DRY_CUM"][s]["nse"] for s in SEASONS if s in candidate.get("DRY_CUM", {})}
    resp_base = [baseline[f]["nse"][s] for f in ("N_RESPONSE", "W_RESPONSE") for s in SEASONS]
    resp_cand = [candidate[f][s]["nse"] for f in ("N_RESPONSE", "W_RESPONSE") for s in SEASONS
                 if s in candidate.get(f, {})]
    dry_mean_improve = float(np.mean([dry_cand[s] for s in SEASONS]) - np.mean([dry_base[s] for s in SEASONS]))
    resp_mean_improve = float(np.mean(resp_cand) - np.mean(resp_base)) if len(resp_cand) == 4 else float("nan")

    criteria = {
        "criterion_1": {
            "rule": "两季 DRY NSE 均不低于基线-0.02 且至少一个响应族两季平均 NSE 改善>=0.10",
            "met": (all(dry_cand[s] >= dry_base[s] - 0.02 for s in SEASONS)
                    and any(np.mean([candidate[f][s]["nse"] - baseline[f]["nse"][s] for s in SEASONS]) >= 0.10
                            for f in ("N_RESPONSE", "W_RESPONSE"))),
        },
        "criterion_2": {
            "rule": "两季 DRY 平均 NSE 提高>=0.01 且四响应平均不恶化超过 0.05",
            "met": dry_mean_improve >= 0.01 and resp_mean_improve >= -0.05,
        },
        "criterion_3": {
            "rule": "四响应 NSE 平均改善>=0.25 且两季 DRY NSE 下降均不超过 0.03",
            "met": (resp_mean_improve >= 0.25
                    and all(dry_base[s] - dry_cand[s] <= 0.03 for s in SEASONS)),
        },
    }
    return {
        "dry_nse_mean_improvement": dry_mean_improve,
        "response_nse_mean_improvement": resp_mean_improve,
        "criteria": criteria,
        "recommend_promotion": any(c["met"] for c in criteria.values()),
    }


def screen_run(run_dir: Path, case: str, baseline: dict) -> dict:
    registry = pd.read_csv(run_dir / f"{case}_observation_registry.csv", encoding="utf-8-sig")
    candidates = {}
    rei_files = sorted(run_dir.glob(f"{case}.*.rei")) + [run_dir / f"{case}.rei"]
    rei_files = sorted({p for p in rei_files if p.is_file()})
    if not rei_files:
        raise SystemExit("no .rei files found; did the GLM run complete?")
    for rei_path in rei_files:
        label = rei_path.name.replace(f"{case}.", "").replace(".rei", "") or "final"
        if label == "base":
            label = "initial"
        rei = parse_rei(rei_path)
        candidate = {
            "DRY_CUM": family_metrics_from_rei(rei, registry, "DRY_CUM"),
            "N_RESPONSE": family_metrics_from_rei(rei, registry, "N_RESPONSE"),
            "W_RESPONSE": family_metrics_from_rei(rei, registry, "W_RESPONSE"),
        }
        passed, checks = engineering_gates(candidate, baseline, source=f"rei:{rei_path.name}")
        candidates[label] = {
            "rei_file": rei_path.name,
            "metrics": candidate,
            "engineering_pass": passed,
            "gates": checks,
            "promotion": science_promotion(candidate, baseline),
        }
    return candidates


def write_outputs(run_dir: Path, candidates: dict, baseline: dict) -> None:
    eval_dir = run_dir / "glm_evaluation"
    eval_dir.mkdir(exist_ok=True)
    quality_dir = run_dir / "glm_quality"
    quality_dir.mkdir(exist_ok=True)

    # Merge with any previously written candidates so screening (.rei) and
    # deterministic replay results coexist in one table instead of the latest
    # call overwriting the others.
    rows = []
    metrics_path = eval_dir / "candidate_metrics.csv"
    if metrics_path.is_file():
        existing = pd.read_csv(metrics_path)
        keep = existing[~existing["candidate"].isin(candidates.keys())]
        if not keep.empty:
            rows = keep.to_dict(orient="records")
    for label, cand in candidates.items():
        for family in ("DRY_CUM", "N_RESPONSE", "W_RESPONSE"):
            for season, m in cand["metrics"].get(family, {}).items():
                rows.append({"candidate": label, "family": family, "season": season,
                             **m, "engineering_pass": cand["engineering_pass"],
                             "recommend_promotion": cand["promotion"]["recommend_promotion"]})
    pd.DataFrame(rows).to_csv(metrics_path, index=False)

    decision_path = eval_dir / "promotion_decision.json"
    decision = {
        "schema_version": 1,
        "case": run_dir.name,
        "baseline_member": baseline.get("member"),
        "candidates": {},
        "note": "candidate organ gates require --replay deterministic evaluation",
    }
    if decision_path.is_file():
        try:
            previous = json.loads(decision_path.read_text(encoding="utf-8"))
            decision["candidates"].update(previous.get("candidates", {}))
        except (OSError, json.JSONDecodeError):
            pass
    decision["candidates"].update({
        label: {
            "engineering_pass": c["engineering_pass"],
            "promotion": c["promotion"],
            "failed_gates": [g for g in c["gates"] if g["status"] == "fail"],
        } for label, c in candidates.items()
    })
    decision_path.write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    quality_path = quality_dir / "engineering_quality.json"
    quality = {
        "schema_version": 1,
        "case": run_dir.name,
        "assessment": "glm_followup_engineering",
        "candidates": {},
    }
    if quality_path.is_file():
        try:
            previous = json.loads(quality_path.read_text(encoding="utf-8"))
            quality["candidates"].update(previous.get("candidates", {}))
        except (OSError, json.JSONDecodeError):
            pass
    quality["candidates"].update({label: {"engineering_pass": c["engineering_pass"],
                                           "gates": c["gates"]} for label, c in candidates.items()})
    quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"outputs: {eval_dir} and {quality_dir}")


# ── deterministic replay (plan section 7 stage 4) ───────────────────

def _parse_response_out(path: Path, token: str) -> dict[tuple[int, int], float]:
    """Parse ``RUN n TN t @HNO@ h DATE d @<TOKEN>@ v`` into {(run, hno): value}.

    Keyed by the global RUN number because treatment numbers repeat across
    seasons (e.g. TN 4 exists in both 25SP and 26SP); the observation
    registry carries the matching ``global_run`` for every response obs.
    """
    values: dict[tuple[int, int], float] = {}
    if not path.is_file():
        return values
    pattern = re.compile(
        rf"RUN\s+(\d+)\s+TN\s+(\d+)\s+@HNO@\s+(\d+).*?@{token}@\s+([-+0-9.eE]+)")
    for line in path.read_text(errors="ignore").splitlines():
        match = pattern.search(line)
        if match:
            values[(int(match.group(1)), int(match.group(3)))] = float(match.group(4))
    return values


def replay_candidate(run_dir: Path, case: str, label: str, par_source: Path,
                     baseline: dict) -> dict:
    """Deterministically replay one candidate and evaluate every family.

    Runs ``run_multiseason.py`` (official DSSAT — the GLM variant needs no
    exe/SPE swap) inside ``<run_dir>/deterministic_candidates/<label>/``,
    then computes DRY_CUM/organ metrics via the shared deterministic compare
    utilities and response NSE from Pest{N,W}Response.OUT against the
    observation registry.
    """
    from src.reporting.analyze_results import (
        deterministic_harvest_compare,
        deterministic_process_compare,
    )

    det_dir = run_dir / "deterministic_candidates" / label
    det_dir.mkdir(parents=True, exist_ok=True)
    params_csv = det_dir / f"{label}_params.csv"
    # Accept both CSV layouts (name,value) and classic PEST .par files
    # ("single point" header + whitespace name value scale offset).
    if par_source.suffix.lower() == ".par":
        lines = par_source.read_text(encoding="utf-8", errors="ignore").splitlines()
        member = pd.DataFrame(
            [{"name": p[0], "value": float(p[1])}
             for line in lines[1:] if len((p := line.split())) >= 2])
    else:
        member = pd.read_csv(par_source)
        member = member.loc[:, ~member.columns.str.lower().isin(("real_name", "realization"))]
        member.columns = [{"name": "name", "value": "value"}.get(str(c).lower(), str(c))
                          for c in member.columns]
    if "name" not in member.columns or "value" not in member.columns:
        raise ValueError(f"unrecognized parameter file layout: {par_source}")
    member["name"] = member["name"].astype(str).str.upper()
    member.to_csv(params_csv, index=False)

    design = json.loads((run_dir / "joint_design.json").read_text(encoding="utf-8"))
    # The GLM follow-up contract mandates the official DSSAT v4.8
    # (plan section 1).  The workspace exe may hold a collaborator's custom
    # variant, so swap to the official build for the replay and restore it in
    # finally — exactly like the launcher does for pilot/formal runs.
    official_exe = ROOT / "DSCSM048.EXE"
    workspace_exe = ROOT / "workspace/DSCSM048.EXE"
    exe_backup = det_dir / "_workspace_exe_replay_backup"
    shutil.copy2(workspace_exe, exe_backup)
    shutil.copy2(official_exe, workspace_exe)
    try:
        subprocess.run([
            sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
            "--design", str(run_dir / "joint_design.json"),
            "--param-csv", str(params_csv),
            "--prefix", label, "--harvest-var", "CHPDT",
            "--keep-nitrogen-outputs",
        ], cwd=det_dir, check=True)
    finally:
        exe_backup.replace(workspace_exe)

    registry = pd.read_csv(run_dir / f"{case}_observation_registry.csv", encoding="utf-8-sig")
    candidate: dict = {"DRY_CUM": {}, "N_RESPONSE": {}, "W_RESPONSE": {}, "ORGAN": {}}
    for season in design["seasons"]:
        sid = season["season_id"]
        sdir = det_dir / "_seasons" / sid
        filex = next(sdir.glob("*.TMX"))
        batch = sdir / "analysis_batch.v48"
        batch.write_text("\n".join(
            f"{filex.resolve()} {int(tn)} 1 0 0 0" for tn in season["treatments"]) + "\n",
            encoding="utf-8")
        deterministic_process_compare(sid, str(batch), var_names=["LAID", "LWAD", "SWAD", "CHTD"],
                                      run_dir=str(sdir))
        deterministic_harvest_compare(sid, str(batch), run_dir=str(sdir))
        proc = pd.read_csv(sdir / f"{sid}_deterministic_process_compare.csv")
        for variable in ("LAID", "LWAD", "SWAD", "CHTD"):
            obs_col, sim_col = f"OBS_{variable}", f"SIM_{variable}"
            if obs_col in proc and sim_col in proc:
                sub = proc[(proc[obs_col] != -99) & (proc[sim_col] != -99)]
                candidate["ORGAN"].setdefault(variable, {})[sid] = nse(
                    sub[obs_col].to_numpy(float), sub[sim_col].to_numpy(float))
        harv = pd.read_csv(sdir / f"{sid}_deterministic_harvest_compare.csv")
        sub = harv[(harv["OBS_DRY_CUM"] != -99) & (harv["SIM_DRY_CUM"] != -99)]
        candidate["DRY_CUM"][sid] = {
            "n": len(sub),
            "nse": nse(sub["OBS_DRY_CUM"].to_numpy(float), sub["SIM_DRY_CUM"].to_numpy(float)),
            "pbias_pct": pbias_pct(sub["OBS_DRY_CUM"].to_numpy(float), sub["SIM_DRY_CUM"].to_numpy(float)),
        }

        for family, out_name in (("N_RESPONSE", "PestNResponse.OUT"),
                                 ("W_RESPONSE", "PestWResponse.OUT")):
            token = "NRESPS" if family == "N_RESPONSE" else "WRESPS"
            rows = registry[registry["season_id"].astype(str).eq(sid)
                            & registry["obgnme"].astype(str).str.upper().str.contains(
                                "NRESP" if family == "N_RESPONSE" else "WRESP", na=False)].copy()
            if rows.empty:
                continue
            sim_values = (_parse_response_out(det_dir / "_seasons" / sid / out_name, token)
                          or _parse_response_out(det_dir / out_name, token))
            harvest = rows["obgnme"].astype(str).str.extract(r"_H(\d+)$", expand=False).astype(int)
            pairs = list(zip(rows["global_run"].astype(int), harvest))
            missing = [p for p in pairs if p not in sim_values]
            if missing:
                candidate[family][sid] = {"n": len(rows), "nse": float("nan"),
                                          "pbias_pct": float("nan"),
                                          "warning": f"response sim missing {len(missing)}/{len(rows)} (tn,hno) pairs"}
                continue
            obs = rows["raw_obsval"].to_numpy(float)
            sim = np.array([sim_values[p] for p in pairs], float)
            candidate[family][sid] = {"n": len(rows), "nse": nse(obs, sim),
                                      "pbias_pct": pbias_pct(obs, sim)}

    passed, checks = engineering_gates(candidate, baseline, source=f"deterministic:{label}")
    return {"metrics": candidate, "engineering_pass": passed, "gates": checks,
            "promotion": science_promotion(candidate, baseline)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--case", default=None)
    parser.add_argument("--export-baseline", action="store_true")
    parser.add_argument("--baseline-json", type=Path, default=BASELINE_JSON)
    parser.add_argument("--replay", default=None, metavar="LABEL",
                        help="deterministically replay '<case>.par' (LABEL=final) or a "
                             "'<LABEL>.par'/'<LABEL>.par.csv' file and evaluate all families")
    args = parser.parse_args()

    if args.export_baseline:
        export_baseline(args.baseline_json)
        return 0

    if args.run_dir is None:
        raise SystemExit("--run-dir required (or --export-baseline)")
    run_dir: Path = args.run_dir.resolve()
    case = args.case or next((p.stem for p in run_dir.glob("*.pst")), None)
    if case is None:
        raise SystemExit("no PST found; pass --case")

    baseline = load_baseline(args.baseline_json)

    if args.replay is not None:
        label = args.replay
        if label == "final":
            par_source = run_dir / f"{case}.par"
        else:
            par_source = next(p for p in (
                run_dir / f"{label}.par", run_dir / f"{label}.par.csv",
                run_dir / f"{case}.{label}.par", run_dir / f"{case}.{label}.par.csv",
            ) if p.is_file())
        replay_label = f"{label}_deterministic_20260818"
        candidate = replay_candidate(run_dir, case, replay_label, par_source, baseline)
        candidates = {replay_label: candidate}
        write_outputs(run_dir, candidates, baseline)
        print(f"{replay_label}: engineering={'PASS' if candidate['engineering_pass'] else 'FAIL'} "
              f"promotion={'RECOMMEND' if candidate['promotion']['recommend_promotion'] else 'hold'}")
        return 0

    candidates = screen_run(run_dir, case, baseline)
    write_outputs(run_dir, candidates, baseline)
    for label, cand in sorted(candidates.items()):
        promo = cand["promotion"]["recommend_promotion"]
        print(f"{label}: engineering={'PASS' if cand['engineering_pass'] else 'FAIL'} "
              f"promotion={'RECOMMEND' if promo else 'hold'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
