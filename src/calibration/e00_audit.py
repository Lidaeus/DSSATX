"""E00: input, observation, and parameter-set freeze audit.

A read-only, no-side-effect audit run **before** any calibration (E01+).  It
does not modify any input file; it verifies that parameter ranges, FileX,
FileT, SOIL, harvest dates, and weights will not silently change between
experiments, and produces a frozen ``E00_audit_receipt.json`` plus a three-
season ``E00_harvest_alignment_audit.csv``.

The harvest-alignment *rule* (real event → model event one day earlier;
virtual terminal event one day after the last model event) is implemented once
in ``run_multiseason._prepare_t10_input_bundle``.  This audit only *reads and
reports* the alignment; it never rewrites the FileX.
"""
from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src.calibration.experiment_spec import ExperimentSpec
from src.calibration.run_multiseason import _read_direct_harvest_dates
from src.common.project import PROJECT_ROOT, sha256_file
from src.dssat.run_dssat import _yyddd_add_days


SOBOLO23_PROFILE = "configs/experiments/parameter_sets/sobol23_dryonly_v1.json"
FULL55_PROFILE = "configs/experiments/parameter_sets/highdim55_dryonly_v1.json"


@dataclass
class AuditFinding:
    check: str
    status: str  # "pass" | "fail"
    detail: str = ""


# ---------------------------------------------------------------------------
# Operation 1: input-manifest verification (per season)
# ---------------------------------------------------------------------------

def audit_input_manifests(spec: ExperimentSpec) -> tuple[list[dict[str, Any]], list[AuditFinding]]:
    """Verify each season's input_manifest.json: existence, SHA-256 vs spec,
    and every file it lists (existence + SHA)."""
    rows: list[dict[str, Any]] = []
    findings: list[AuditFinding] = []
    for season in spec.season_inputs:
        manifest_path = season.input_manifest_path
        sid = season.season_id
        row: dict[str, Any] = {
            "season_id": sid,
            "manifest_path": str(manifest_path),
            "manifest_exists": manifest_path.is_file(),
            "declared_sha256": season.input_manifest_sha256,
            "actual_sha256": None,
            "files_listed": 0,
            "files_verified": 0,
            "files_missing": 0,
            "files_sha_mismatch": 0,
        }
        if not manifest_path.is_file():
            findings.append(AuditFinding("input_manifest", "fail", f"{sid}: manifest not found"))
            rows.append(row)
            continue
        actual = sha256_file(manifest_path)
        row["actual_sha256"] = actual
        if season.input_manifest_sha256 and actual != season.input_manifest_sha256:
            findings.append(AuditFinding(
                "input_manifest", "fail",
                f"{sid}: manifest SHA-256 mismatch (declared {season.input_manifest_sha256[:12]}… != actual {actual[:12]}…)",
            ))
        # verify every listed file
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            findings.append(AuditFinding("input_manifest", "fail", f"{sid}: manifest unreadable: {exc}"))
            rows.append(row)
            continue
        bundle_dir = manifest_path.parent
        for entry in manifest.get("files", []):
            fname = entry.get("name")
            decl_sha = str(entry.get("sha256", "")).strip().lower()
            row["files_listed"] += 1
            fpath = bundle_dir / fname
            if not fpath.is_file():
                row["files_missing"] += 1
                findings.append(AuditFinding("input_manifest", "fail", f"{sid}: listed file missing: {fname}"))
                continue
            if decl_sha:
                actual_fsha = sha256_file(fpath)
                if actual_fsha != decl_sha:
                    row["files_sha_mismatch"] += 1
                    findings.append(AuditFinding(
                        "input_manifest", "fail",
                        f"{sid}: file SHA mismatch: {fname}",
                    ))
                else:
                    row["files_verified"] += 1
            else:
                row["files_verified"] += 1
        ok = (row["files_missing"] == 0 and row["files_sha_mismatch"] == 0
              and (not season.input_manifest_sha256 or actual == season.input_manifest_sha256))
        if ok and not any(f.check == "input_manifest" and f.status == "fail" and sid in f.detail for f in findings):
            findings.append(AuditFinding("input_manifest", "pass", f"{sid}: {row['files_verified']}/{row['files_listed']} files verified"))
        rows.append(row)
    return rows, findings


# ---------------------------------------------------------------------------
# Operation 4: CHPDT harvest-alignment audit (per season, read-only)
# ---------------------------------------------------------------------------

def _season_filet(spec: ExperimentSpec, season_id: str) -> Path | None:
    """Locate the FileT (.TMT) for one season from its input bundle."""
    for season in spec.season_inputs:
        if season.season_id == season_id:
            bundle = season.input_manifest_path.parent
            tmts = sorted(bundle.glob("*.TMT"))
            return tmts[0] if tmts else None
    return None


def _season_treatments(spec: ExperimentSpec, season_id: str) -> tuple[int, ...]:
    """Read the treatment list for one season from the multiseason design JSON."""
    if spec.multiseason_design_path is None:
        return ()
    design = json.loads(spec.multiseason_design_path.read_text(encoding="utf-8"))
    for season in design.get("seasons", []):
        if season.get("season_id") == season_id:
            return tuple(int(t) for t in season.get("treatments", []))
    return ()


def audit_chpdt_harvest_alignment(spec: ExperimentSpec) -> tuple[list[dict[str, Any]], list[AuditFinding]]:
    """Read-only CHPDT harvest-alignment audit for every season.

    Reports, per treatment: the real observed dates, the model harvest dates
    (observed - 1 day), and the virtual terminal date (last model + 1 day).
    Verifies every calibration treatment has >= 1 CHPDT observation.
    """
    rows: list[dict[str, Any]] = []
    findings: list[AuditFinding] = []
    for season in spec.season_inputs:
        sid = season.season_id
        if season.role not in ("calibration", "development_calibration", "diagnostic"):
            continue  # frozen_validation seasons are not calibrated
        filet = _season_filet(spec, sid)
        if filet is None or not filet.is_file():
            findings.append(AuditFinding("harvest_alignment", "fail", f"{sid}: FileT not found"))
            continue
        treatments = _season_treatments(spec, sid)
        if not treatments:
            findings.append(AuditFinding("harvest_alignment", "fail", f"{sid}: no treatments in design"))
            continue
        dates_by_tn = _read_direct_harvest_dates(filet, treatments)
        for tn in treatments:
            observed = dates_by_tn.get(int(tn), [])
            if not observed:
                findings.append(AuditFinding(
                    "harvest_alignment", "fail",
                    f"{sid}: TN{tn} has no direct CHFPW/CHPDT observations",
                ))
                continue
            model_dates = [_yyddd_add_days(d, -1) for d in observed]
            virtual_date = _yyddd_add_days(model_dates[-1], 1)
            for idx, (observed_date, model_date) in enumerate(zip(observed, model_dates), start=1):
                rows.append({
                    "season_id": sid, "treatment": int(tn),
                    "event_number": idx, "event_role": "real",
                    "observed_date": observed_date,
                    "model_harvest_date": model_date,
                    "virtual_terminal_date": "",
                })
            rows.append({
                "season_id": sid, "treatment": int(tn),
                "event_number": len(observed) + 1, "event_role": "virtual_terminal",
                "observed_date": "",
                "model_harvest_date": virtual_date,
                "virtual_terminal_date": virtual_date,
            })
            findings.append(AuditFinding(
                "harvest_alignment", "pass",
                f"{sid}: TN{tn} {len(observed)} real + 1 virtual",
            ))
    return rows, findings


# ---------------------------------------------------------------------------
# Operation 2/3: parameter-profile verification
# ---------------------------------------------------------------------------

def _load_profile(path: str | Path) -> dict[str, Any]:
    p = (PROJECT_ROOT / path) if not Path(path).is_absolute() else Path(path)
    return json.loads(p.read_text(encoding="utf-8"))


def audit_parameter_profiles() -> tuple[dict[str, Any], list[AuditFinding]]:
    """Verify sobol23 and full55 profiles: count consistency, source SHA,
    PM06 inclusion in sobol23, and that full55 is not an auto-superset."""
    findings: list[AuditFinding] = []
    result: dict[str, Any] = {}
    for label, rel in (("sobol23", SOBOLO23_PROFILE), ("full55", FULL55_PROFILE)):
        profile = _load_profile(rel)
        params = [str(p).strip().upper() for p in profile.get("parameters", [])]
        declared = int(profile.get("declared_count", len(params)))
        result[label] = {
            "set_id": profile.get("set_id"),
            "path": rel,
            "declared_count": declared,
            "actual_count": len(params),
            "source_file": profile.get("source_file"),
            "source_sha256": profile.get("source_sha256"),
        }
        if declared != len(params):
            findings.append(AuditFinding(
                "parameter_profile", "fail",
                f"{label}: declared_count={declared} != parameters list len={len(params)}",
            ))
        # source file SHA verification
        src = profile.get("source_file", "")
        if src and profile.get("source_sha256"):
            src_path = (PROJECT_ROOT / src) if not Path(src).is_absolute() else Path(src)
            if src_path.is_file():
                actual = sha256_file(src_path)
                result[label]["source_actual_sha256"] = actual
                if actual != profile["source_sha256"]:
                    findings.append(AuditFinding(
                        "parameter_profile", "fail",
                        f"{label}: source file SHA mismatch",
                    ))
        else:
            findings.append(AuditFinding(
                "parameter_profile", "fail",
                f"{label}: missing source_file or source_sha256",
            ))
    # PM06 inclusion check for sobol23
    sobol_params = set(result["sobol23"].get("parameters", [])) if "parameters" in result["sobol23"] else set(
        [str(p).strip().upper() for p in _load_profile(SOBOLO23_PROFILE).get("parameters", [])])
    if "PM06" not in sobol_params:
        findings.append(AuditFinding("parameter_profile", "fail", "sobol23 must include PM06 (approved)"))
    else:
        findings.append(AuditFinding("parameter_profile", "pass", "sobol23 includes PM06 (approved)"))
    # full55 is NOT an automatic superset of sobol23
    full_params = set(
        [str(p).strip().upper() for p in _load_profile(FULL55_PROFILE).get("parameters", [])]
    )
    only_in_full = sorted(full_params - sobol_params)
    result["full55"]["params_beyond_sobol23"] = only_in_full
    if not only_in_full:
        findings.append(AuditFinding(
            "parameter_profile", "fail",
            "full55 must not equal sobol23 (it adds parameters, not an auto-extension)",
        ))
    else:
        findings.append(AuditFinding(
            "parameter_profile", "pass",
            f"full55 adds {len(only_in_full)} params beyond sobol23 (not auto-superset)",
        ))
    # store the parameter lists for the receipt
    result["sobol23"]["parameters"] = sorted(sobol_params)
    result["full55"]["parameters"] = sorted(full_params)
    # dedupe pass/fail: collapse duplicate pass findings
    seen_fail = {f.detail for f in findings if f.status == "fail"}
    return result, findings


# ---------------------------------------------------------------------------
# Pass-gate: bounds profile vs declared counts
# ---------------------------------------------------------------------------

def audit_bounds_profile(spec: ExperimentSpec, profiles: dict[str, Any]) -> list[AuditFinding]:
    """Verify frozen bounds against the parameter set selected by ``spec``.

    The canonical sobol23/full55 profiles are audited separately by
    :func:`audit_parameter_profiles`.  A specific experiment may intentionally
    use another approved set (for example joint54 with FL-VS fixed), so this
    gate must not impose the legacy full55 count on every experiment.
    """
    findings: list[AuditFinding] = []
    bounds_path = spec.bounds_path
    active_names: set[str] = set()
    with bounds_path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            name = str(row.get("name", "")).strip().upper()
            if str(row.get("status", "")).strip().lower() == "active":
                active_names.add(name)

    set_id = spec.parameter_set.set_id
    declared = spec.parameter_set.declared_count
    params = set(spec.parameter_set.parameters)
    active_count = len(active_names)
    missing = params - active_names
    unexpected = active_names - params
    if active_count != declared:
        findings.append(AuditFinding(
            "bounds_profile", "fail",
            f"{set_id}: frozen active={active_count} != declared={declared}",
        ))
    elif missing:
        findings.append(AuditFinding(
            "bounds_profile", "fail",
            f"{set_id}: declared params not active in frozen bounds: {sorted(missing)}",
        ))
    elif unexpected:
        findings.append(AuditFinding(
            "bounds_profile", "fail",
            f"{set_id}: undeclared active params in frozen bounds: {sorted(unexpected)}",
        ))
    else:
        findings.append(AuditFinding(
            "bounds_profile", "pass",
            f"{set_id}: frozen active={active_count} == declared={declared}; active names match",
        ))
    return findings


# ---------------------------------------------------------------------------
# Observation contract audit (P0-6: CHTD counts, SOIL_WATER counts, deprecated)
# ---------------------------------------------------------------------------

DEPRECATED_INDICATORS = {"CNAM", "L#SD", "M#AD", "CWID", "L#PA", "RWAD", "PDMCD"}


def audit_observation_contract(spec: ExperimentSpec) -> tuple[dict[str, Any], list[AuditFinding]]:
    """Verify CHTD counts, SOIL_WATER counts, and absence of deprecated indicators
    across FileT, uncertainty CSV, and observation profile."""
    findings: list[AuditFinding] = []
    summary: dict[str, Any] = {"seasons": {}}

    for season in spec.season_inputs:
        sid = season.season_id
        bundle = season.input_manifest_path.parent
        ft_path = bundle / "FileT_values.csv"
        unc_path = bundle / "observation_uncertainty.csv"
        sw_path = bundle / "soil_water_observations.csv"
        season_info: dict[str, Any] = {}

        # CHTD counts
        chtd_ft = 0
        chtd_unc = 0
        if ft_path.is_file():
            import pandas as _pd
            ft = _pd.read_csv(ft_path)
            if "CHTD" in ft.columns:
                chtd_ft = int((ft["CHTD"].notna() & (ft["CHTD"] != -99)).sum())
        if unc_path.is_file():
            unc = _pd.read_csv(unc_path)
            if "variable" in unc.columns:
                chtd_unc = int((unc["variable"].astype(str).str.upper() == "CHTD").sum())
        season_info["chtd_filet"] = chtd_ft
        season_info["chtd_uncertainty"] = chtd_unc
        if chtd_ft != chtd_unc:
            findings.append(AuditFinding(
                "observation_contract", "fail",
                f"{sid}: CHTD count mismatch FileT={chtd_ft} vs uncertainty={chtd_unc}",
            ))
        else:
            findings.append(AuditFinding(
                "observation_contract", "pass",
                f"{sid}: CHTD consistent ({chtd_ft})",
            ))

        # SOIL_WATER counts
        sw_phi = 0
        if sw_path.is_file():
            sw = _pd.read_csv(sw_path)
            if "phi_role" in sw.columns:
                sw_phi = int((sw["phi_role"].astype(str).str.lower() == "soil_water_phi").sum())
        season_info["soil_water_phi"] = sw_phi
        findings.append(AuditFinding(
            "observation_contract", "pass",
            f"{sid}: SOIL_WATER phi_role count={sw_phi}",
        ))

        # Deprecated indicators in uncertainty
        deprecated_present = set()
        if unc_path.is_file():
            if "variable" in unc.columns:
                vars_present = set(unc["variable"].astype(str).str.upper())
                deprecated_present = DEPRECATED_INDICATORS & vars_present
        season_info["deprecated_in_uncertainty"] = sorted(deprecated_present)
        if deprecated_present:
            findings.append(AuditFinding(
                "observation_contract", "fail",
                f"{sid}: deprecated indicators in uncertainty: {sorted(deprecated_present)}",
            ))

        summary["seasons"][sid] = season_info

    # Check observation profile
    active = set(spec.observation_profile.active_phi_targets)
    diagnostic = set(spec.observation_profile.diagnostic_targets)
    forbidden_in_diag = DEPRECATED_INDICATORS & diagnostic
    if forbidden_in_diag:
        findings.append(AuditFinding(
            "observation_contract", "fail",
            f"deprecated indicators in diagnostic_targets: {sorted(forbidden_in_diag)}",
        ))
    else:
        findings.append(AuditFinding(
            "observation_contract", "pass",
            "no deprecated indicators in diagnostic_targets",
        ))

    return summary, findings


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------

def run_e00_audit(spec_path: str | Path, out_dir: str | Path) -> dict[str, Any]:
    """Run the full E00 audit and write receipt + harvest-alignment CSV."""
    spec = ExperimentSpec.load(spec_path)  # validates contract (pass-gate)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    manifest_rows, manifest_findings = audit_input_manifests(spec)
    harvest_rows, harvest_findings = audit_chpdt_harvest_alignment(spec)
    profiles, profile_findings = audit_parameter_profiles()
    bounds_findings = audit_bounds_profile(spec, profiles)
    obs_summary, obs_findings = audit_observation_contract(spec)

    all_findings = manifest_findings + harvest_findings + profile_findings + bounds_findings + obs_findings
    failed = [f for f in all_findings if f.status == "fail"]
    status = "fail" if failed else "pass"

    # write harvest-alignment CSV
    harvest_path = out / "E00_harvest_alignment_audit.csv"
    if harvest_rows:
        with harvest_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(harvest_rows[0].keys()))
            writer.writeheader()
            writer.writerows(harvest_rows)

    receipt = {
        "audit_id": "E00_input_audit",
        "status": status,
        "spec_path": str(spec.path),
        "spec_sha256": spec.sha256,
        "bounds_id": spec.bounds_id,
        "bounds_sha256": spec.bounds_sha256,
        "observation_profile": spec.observation_profile.profile_id,
        "seasons": [s.season_id for s in spec.season_inputs],
        "manifest_audit": manifest_rows,
        "observation_contract": obs_summary,
        "parameter_profiles": profiles,
        "findings": [asdict(f) for f in all_findings],
        "n_findings_total": len(all_findings),
        "n_findings_failed": len(failed),
        "harvest_alignment_csv": str(harvest_path) if harvest_rows else None,
        "harvest_alignment_rows": len(harvest_rows),
    }
    receipt_path = out / "E00_audit_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return receipt


__all__ = [
    "AuditFinding",
    "audit_input_manifests",
    "audit_chpdt_harvest_alignment",
    "audit_parameter_profiles",
    "audit_bounds_profile",
    "run_e00_audit",
]
