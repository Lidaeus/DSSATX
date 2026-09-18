"""Generate the T7 Sobol-based 17-parameter selection (CSV + manifest).

Reads the three N=128 Sobol STI files, classifies outputs into the two T7
domains (general_genetic, water_nitrogen_response), computes the cross-season
mean RMS STI per parameter per domain, applies the per-domain 90% cumulative
contribution rule, takes the union, excludes PM06 (T7 §5.4), and writes:

  configs/calibration/t7_sobol_17param_20260721/calibration_parameter_candidates.csv
  configs/calibration/t7_sobol_17param_20260721/selection_manifest.json

This is a screening artifact, not a frozen scientific conclusion.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEASONS = ["XXQL2501", "XXQL2502", "XXQL2601"]
SAMPLES_DIR_TEMPLATE = "workspace/runs/sobol_formal_v1/{season}/n0128_seed_20260729"
STI_FILENAME = "sa_sen_sobol.sobol.sti.csv"
EXCLUDED = {"pm06"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_response_groups() -> dict:
    profile = json.loads(
        (ROOT / "configs/sa/eggplant_formal_xxql2501_outputs_20260720.json").read_text(encoding="utf-8")
    )
    return profile["response_groups"]


def build_general_features(response_groups: dict) -> set[str]:
    feats: set[str] = set()
    for g in ["phenology", "canopy", "biomass", "yield_harvest"]:
        for f in response_groups[g]:
            if f == "LAI_DAP":
                feats.update(["lai_dap045", "lai_dap067", "lai_dap095", "lai_dap119"])
            else:
                feats.add(f.lower())
    return feats


def response_name(output: str) -> str:
    m = re.match(r"^tn\d+_(.+)$", output)
    if m:
        return m.group(1)
    m = re.match(r"^wn_(.+)$", output)
    if m:
        return m.group(1)
    return output


def classify_domain(output: str, general_features: set[str]) -> str | None:
    name = response_name(output).lower()
    if name.startswith("water_n") or name.startswith("nslope_") or name.startswith("interaction_"):
        return "water_nitrogen_response"
    if name in general_features:
        return "general_genetic"
    return None


def read_sti(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open("r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        return header[1:], list(reader)


def compute_domain_rms(params, seasons, general_features):
    """Return {domain: {season: {param: rms_sti}}}."""
    domain_rms = {
        dom: {s: {} for s in seasons}
        for dom in ("general_genetic", "water_nitrogen_response")
    }
    for season in seasons:
        sti_path = ROOT / SAMPLES_DIR_TEMPLATE.format(season=season) / STI_FILENAME
        _, rows = read_sti(sti_path)
        for dom in domain_rms:
            for p in params:
                domain_rms[dom][season][p] = 0.0
        cnt = {dom: 0 for dom in domain_rms}
        for row in rows:
            if len(row) < len(params) + 1:
                continue
            dom = classify_domain(row[0], general_features)
            if dom is None:
                continue
            cnt[dom] += 1
            for i, v in enumerate(row[1:]):
                try:
                    domain_rms[dom][season][params[i]] += float(v) ** 2
                except ValueError:
                    pass
        for dom in domain_rms:
            for p in params:
                domain_rms[dom][season][p] = (domain_rms[dom][season][p] / max(cnt[dom], 1)) ** 0.5
    return domain_rms


def per_domain_cutoff(params, domain_rms, seasons, threshold=0.9):
    """Return {domain: (cutoff_idx, ranked_list, total)}."""
    cutoffs = {}
    for dom in ("general_genetic", "water_nitrogen_response"):
        means = sorted(
            ((p, sum(domain_rms[dom][s][p] for s in seasons) / len(seasons)) for p in params),
            key=lambda x: -x[1],
        )
        total = sum(m for _, m in means)
        acc = 0.0
        cut = None
        for i, (_, m) in enumerate(means, 1):
            acc += m / total if total else 0.0
            if acc >= threshold and cut is None:
                cut = i
        cutoffs[dom] = (cut, means, total)
    return cutoffs


def main() -> int:
    response_groups = load_response_groups()
    general_features = build_general_features(response_groups)

    sti_path = ROOT / SAMPLES_DIR_TEMPLATE.format(season=SEASONS[0]) / STI_FILENAME
    params, _ = read_sti(sti_path)
    domain_rms = compute_domain_rms(params, SEASONS, general_features)
    cutoffs = per_domain_cutoff(params, domain_rms, SEASONS)

    selected: dict[str, set[str]] = {}
    for dom, (cut, means, _) in cutoffs.items():
        for p, _ in means[:cut]:
            if p in EXCLUDED:
                continue
            selected.setdefault(p, set()).add(dom)

    records = []
    for p in params:
        if p in EXCLUDED or p not in selected:
            continue
        gen_mean = sum(domain_rms["general_genetic"][s][p] for s in SEASONS) / len(SEASONS)
        wn_mean = sum(domain_rms["water_nitrogen_response"][s][p] for s in SEASONS) / len(SEASONS)
        gen_total = cutoffs["general_genetic"][2]
        wn_total = cutoffs["water_nitrogen_response"][2]
        gen_rank = next((i for i, (pp, _) in enumerate(cutoffs["general_genetic"][1]) if pp == p), None)
        wn_rank = next((i for i, (pp, _) in enumerate(cutoffs["water_nitrogen_response"][1]) if pp == p), None)
        records.append(
            {
                "parameter": p.upper(),
                "sobol_general_genetic_mean_rms_sti": round(gen_mean, 6),
                "sobol_general_genetic_frac": round(gen_mean / gen_total, 6) if gen_total else 0.0,
                "sobol_general_genetic_rank": gen_rank + 1 if gen_rank is not None else "",
                "sobol_general_genetic_selected": p in {pp for pp, _ in cutoffs["general_genetic"][1][: cutoffs["general_genetic"][0]]},
                "sobol_water_nitrogen_mean_rms_sti": round(wn_mean, 6),
                "sobol_water_nitrogen_frac": round(wn_mean / wn_total, 6) if wn_total else 0.0,
                "sobol_water_nitrogen_rank": wn_rank + 1 if wn_rank is not None else "",
                "sobol_water_nitrogen_selected": p in {pp for pp, _ in cutoffs["water_nitrogen_response"][1][: cutoffs["water_nitrogen_response"][0]]},
                "selected_domain_count": len(selected[p]),
                "selected_domains": ";".join(sorted(selected[p])),
                "evidence_status": "science_pending",
            }
        )

    def sort_key(r):
        gen = r["sobol_general_genetic_rank"] if isinstance(r["sobol_general_genetic_rank"], int) else 999
        wn = r["sobol_water_nitrogen_rank"] if isinstance(r["sobol_water_nitrogen_rank"], int) else 999
        return (-r["selected_domain_count"], gen, wn)

    records.sort(key=sort_key)
    for i, r in enumerate(records, 1):
        r["selection_order"] = i

    out_dir = ROOT / "configs/calibration/t7_sobol_17param_20260721"
    out_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "selection_order",
        "evidence_status",
        "parameter",
        "selected_domain_count",
        "selected_domains",
        "sobol_general_genetic_mean_rms_sti",
        "sobol_general_genetic_frac",
        "sobol_general_genetic_rank",
        "sobol_general_genetic_selected",
        "sobol_water_nitrogen_mean_rms_sti",
        "sobol_water_nitrogen_frac",
        "sobol_water_nitrogen_rank",
        "sobol_water_nitrogen_selected",
    ]
    csv_path = out_dir / "calibration_parameter_candidates.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            writer.writerow({k: r[k] for k in fieldnames})

    sources = []
    for season in SEASONS:
        p = ROOT / SAMPLES_DIR_TEMPLATE.format(season=season) / STI_FILENAME
        sources.append(
            {
                "season": season,
                "path": str(p.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256(p),
                "samples": 128,
                "seed": 20260729,
            }
        )

    conv_path = ROOT / "workspace/runs/sobol_formal_v1/XXQL2501/convergence_n0064_n0128_repaired_20260721/sobol_convergence.json"
    conv_data = json.loads(conv_path.read_text(encoding="utf-8")) if conv_path.exists() else {}

    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "proposal_only": True,
        "automatic_bounds_change": False,
        "threshold": 0.9,
        "selection_rule": "per_domain_minimum_cumulative_then_union using cross-season mean RMS STI; PM06 excluded per T7 §5.4",
        "aggregation": "RMS STI across all outputs within each domain, then mean across XXQL2501/XXQL2502/XXQL2601",
        "required_domains": ["general_genetic", "water_nitrogen_response"],
        "excluded_parameters": ["PM06"],
        "source_STI_files": sources,
        "source_data_status": ["science_pending"],
        "sobol_convergence_decision_xxql2501": conv_data.get("decision"),
        "sobol_unvalidated_note": (
            "XXQL2501 N=64->128 convergence failed thresholds "
            "(Spearman 0.85/0.89, Jaccard 0.45/0.60); "
            "XXQL2502/XXQL2601 have no cross-scale convergence report. "
            "Sobol is treated as screening evidence, not as science_validated; "
            "the parameter set is an engineering candidate, not a frozen scientific conclusion."
        ),
        "general_genetic_cutoff_count": cutoffs["general_genetic"][0],
        "general_genetic_total_mean_rms_sti": round(cutoffs["general_genetic"][2], 6),
        "water_nitrogen_cutoff_count": cutoffs["water_nitrogen_response"][0],
        "water_nitrogen_total_mean_rms_sti": round(cutoffs["water_nitrogen_response"][2], 6),
        "union_parameter_count": len(records),
        "artifacts": [
            {"path": "calibration_parameter_candidates.csv", "sha256": sha256(csv_path)}
        ],
        "limitations": (
            "A 90% Sobol RMS STI rule controls screening coverage of total-order effects; "
            "it does not establish parameter identifiability, equifinality absence, or observation support. "
            "Literature, observation coverage, bounds and equifinality diagnostics remain mandatory "
            "before bounds are frozen and before posterior claims are made."
        ),
    }

    (out_dir / "selection_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"Wrote {csv_path}")
    print(f"Wrote {out_dir / 'selection_manifest.json'}")
    print()
    print(f"{len(records)} selected parameters (Sobol dual-domain 90% union, PM06 excluded):")
    for r in records:
        gen_rank = r["sobol_general_genetic_rank"]
        wn_rank = r["sobol_water_nitrogen_rank"]
        print(
            f"  {r['selection_order']:2d}. {r['parameter']:8s} "
            f"domains=[{r['selected_domains']:45s}] "
            f"GEN #{gen_rank:>2} frac={r['sobol_general_genetic_frac']:.4f}  "
            f"WN #{wn_rank:>2} frac={r['sobol_water_nitrogen_frac']:.4f}"
        )
    print()
    print(f"GEN cutoff={cutoffs['general_genetic'][0]} params for 90% (total={cutoffs['general_genetic'][2]:.4f})")
    print(f"WN  cutoff={cutoffs['water_nitrogen_response'][0]} params for 90% (total={cutoffs['water_nitrogen_response'][2]:.4f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
