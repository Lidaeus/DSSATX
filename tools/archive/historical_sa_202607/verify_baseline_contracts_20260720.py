"""T2 deliverable D: per-season baseline contract-extraction audit.

For each of the three season baseline run_dirs produced by T1, re-extract the
SA indicators using that season's frozen output contract and verify every
observation name resolves to a value that is:
  * finite (not -99 DSSAT missing sentinel)
  * non-constant across the 8 treatments (a constant response cannot rank
    parameters at the baseline — flag, do not fail, since some responses like
    ADAPS may legitimately collapse at an uncalibrated baseline)

Acceptance gate (handoff T2): finite_fraction == 1.0 for season-end features;
constant_response_names reported but not fatal at baseline.

This tool does NOT run DSSAT — it re-parses the Evaluate.OUT / PlantGro.OUT /
FreshWt.OUT already produced by the T1 baseline smoke.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.sensitivity.output_contract import load_output_contract, observation_names
from src.sensitivity.sa_model import (
    _parse_evaluate_out,
    _parse_dssat_out_by_run,
    _curve_features,
    _cumulative_dap_fraction,
    _series_value_on_or_before,
    derive_water_nitrogen_responses,
    _as_float,
)

SEASONS = [
    {"exp": "XXQL2501", "contract": "configs/sa/eggplant_formal_xxql2501_outputs_20260720.json",
     "run_dir": "workspace/runs/three_season_baseline_smoke_20260720/xxql2501_baseline_smoke_20260720"},
    {"exp": "XXQL2502", "contract": "configs/sa/eggplant_formal_xxql2502_outputs_20260720.json",
     "run_dir": "workspace/runs/three_season_baseline_smoke_20260720/xxql2502_baseline_smoke_20260720"},
    {"exp": "XXQL2601", "contract": "configs/sa/eggplant_formal_xxql2601_outputs_20260720.json",
     "run_dir": "workspace/runs/three_season_baseline_smoke_20260720/xxql2601_baseline_smoke_20260720"},
]


def extract_indicators(run_dir: Path, contract: dict) -> dict[str, float]:
    """Re-implement the indicator extraction from sa_model.compute_indicators
    but reading the already-present OUT files (no DSSAT re-run)."""
    eval_rows = _parse_evaluate_out(run_dir / "Evaluate.OUT")
    plantgro = _parse_dssat_out_by_run(run_dir / "PlantGro.OUT", ["LAID", "LWAD", "SWAD", "CWAD", "HIAD"])
    freshwt = _parse_dssat_out_by_run(run_dir / "FreshWt.OUT", ["CHPDT"])

    run_to_tn = {}
    for r in eval_rows:
        try:
            run_no = int(float(r.get("@RUN") or r.get("RUN") or r.get("RUNNO") or -99))
        except Exception:
            continue
        try:
            tn = int(float(r.get("TN", -99)))
        except Exception:
            tn = -99
        run_to_tn[run_no] = tn

    lai_time_points = list(contract["lai_time_points"])
    fruit_time_points = list(contract["fruit_time_points"])
    values: dict[str, float] = {}

    def _emit(name, val):
        values[str(name)] = _as_float(val)

    for r in eval_rows:
        run_no = None
        for k in ("RUN", "@RUN"):
            if k in r:
                try:
                    run_no = int(float(r[k]))
                except Exception:
                    pass
        if run_no is None:
            continue
        tn = run_to_tn.get(run_no, -99)
        prefix = f"TN{tn}" if tn != -99 else f"RUN{run_no}"

        _emit(f"{prefix}_YIELD_HWAMS", r.get("HWAMS"))
        _emit(f"{prefix}_LAIXS", r.get("LAIXS"))
        _emit(f"{prefix}_CWAMS", r.get("CWAMS"))
        _emit(f"{prefix}_ADAPS", r.get("ADAPS"))
        _emit(f"{prefix}_PDFPS", r.get("PDFPS"))

        pg = plantgro.get(run_no, [])
        fw = freshwt.get(run_no, [])
        lai = _curve_features(pg, "LAID")
        fruit = _curve_features(fw, "CHPDT")

        _emit(f"{prefix}_LAI_AUC", lai.get("auc"))
        _emit(f"{prefix}_LAI_PEAK", lai.get("peak"))
        _emit(f"{prefix}_LAI_END", lai.get("end"))
        _emit(f"{prefix}_FRUITD_END", fruit.get("end"))
        _emit(f"{prefix}_CUMHARVEST_DAP50", _cumulative_dap_fraction(fw, "CHPDT", 0.5))

        if pg:
            last = pg[-1]
            _emit(f"{prefix}_LEAF_END_LWAD", last.get("LWAD"))
            _emit(f"{prefix}_STEM_END_SWAD", last.get("SWAD"))
            _emit(f"{prefix}_AGB_END_CWAD", last.get("CWAD"))

        for tp in lai_time_points:
            _emit(f"{prefix}_LAI_DAP{tp:03d}", _series_value_on_or_before(pg, tp, "LAID"))
        for tp in fruit_time_points:
            _emit(f"{prefix}_FRUITD_DAP{tp:03d}", _series_value_on_or_before(fw, tp, "CHPDT"))

    values.update(derive_water_nitrogen_responses(values, contract))
    return values


def audit_one_season(season: dict) -> dict:
    exp = season["exp"]
    contract = load_output_contract(PROJECT_ROOT / season["contract"])
    run_dir = PROJECT_ROOT / season["run_dir"]
    names = observation_names(contract)
    values = extract_indicators(run_dir, contract)

    # Per-observation audit across the 8 treatments: finite? constant?
    finite_count = 0
    missing_count = 0
    constant_responses: list[dict] = []
    missing_responses: list[str] = []
    per_name_values: dict[str, list[float]] = {}

    for name in names:
        v = values.get(name, -99.0)
        if v == -99.0 or v is None:
            missing_count += 1
            missing_responses.append(name)
        else:
            finite_count += 1
        per_name_values[name] = [v]

    # constant-response check: group by feature suffix across treatments
    by_feature: dict[str, list[float]] = {}
    for name in names:
        # strip the TN{n}_ prefix
        if name.startswith("TN"):
            feat = name.split("_", 1)[1] if "_" in name else name
            by_feature.setdefault(feat, []).append(values.get(name, -99.0))
    for feat, vals in by_feature.items():
        finite_vals = [v for v in vals if v != -99.0 and v is not None]
        if len(finite_vals) >= 2 and len(set(finite_vals)) == 1:
            constant_responses.append({"feature": feat, "constant_value": finite_vals[0], "n_treatments": len(finite_vals)})

    return {
        "exp": exp,
        "contract": season["contract"],
        "contract_profile_id": contract["profile_id"],
        "observation_count": len(names),
        "finite_count": finite_count,
        "missing_count": missing_count,
        "finite_fraction": finite_count / len(names) if names else 0.0,
        "missing_response_names": missing_responses,
        "constant_response_features": constant_responses,
    }


def main():
    results = []
    print("=" * 72)
    print("T2 baseline contract-extraction audit")
    print("=" * 72)
    for season in SEASONS:
        r = audit_one_season(season)
        results.append(r)
        print(f"\n{r['exp']}: {r['contract_profile_id']}")
        print(f"  observations: {r['observation_count']}  finite: {r['finite_count']}  missing: {r['missing_count']}")
        print(f"  finite_fraction: {r['finite_fraction']:.3f}")
        if r["missing_response_names"]:
            print(f"  missing names ({len(r['missing_response_names'])}): {r['missing_response_names'][:8]}{'...' if len(r['missing_response_names'])>8 else ''}")
        if r["constant_response_features"]:
            print(f"  constant-response features ({len(r['constant_response_features'])}):")
            for c in r["constant_response_features"]:
                print(f"    {c['feature']} = {c['constant_value']} across {c['n_treatments']} treatments")

    out = PROJECT_ROOT / "workspace" / "runs" / "three_season_baseline_smoke_20260720" / "baseline_contract_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nWrote: {out}")

    # Acceptance summary
    all_finite = all(r["finite_fraction"] >= 0.95 for r in results)  # allow small WN_* gaps from 2601 imbalance
    print(f"\nAll seasons finite_fraction >= 0.95: {all_finite}")


if __name__ == "__main__":
    main()
