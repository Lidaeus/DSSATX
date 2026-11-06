"""Export ``morris_response_effects.csv`` — response-level Morris evidence (W2).

Implements W2 of ``docs/敏感性分析方案与图表优化_协作实施计划_20260729.md``
(§5.2, §10 W2).  Reads the raw PESTPP-SEN ``.mio`` files (which carry
``sen_mean``/``sen_mean_abs``/``sen_std_dev`` per observation×parameter×seed)
and emits one row per ``run_id × data_status × season × seed × observation_id
× parameter`` with the elementary-effects statistics, its canonical response
family, and response-internal normalisation.

Scientific rules enforced (plan §5.2):

1. Raw ``mu*``/``sigma`` are compared **only within a response** — never
   averaged across responses of different units.
2. Cross-response summaries use ``mu_star_relative_within_response`` and
   ``sigma_relative_within_response`` (response-internal share), not raw means.
3. The two ranking domains are kept strictly separate.
4. ``mu`` is a directional hint only — it is not a monotonic causal claim in
   the presence of nonlinearity/interactions.
5. Zero-effect and low-effect parameters are **retained** (no Top-K filtering).
6. The valid trajectory count (``n_samples``) and a per-(season,seed,response)
   failure rate are recorded.

The tool is read-only with respect to the source evidence: it never modifies
``.mio`` files or the existing ``paper_data`` bundles.  Output goes to a new
``workspace/sa/morris_response_effects/`` directory so the v4 evidence is not
overwritten (plan W0 rule 5).

Usage::

    python tools/sa/export_morris_response_effects.py \\
        --run-id formal_morris_response_effects_20260729 \\
        --case XXQL2501=workspace/runs/formal_morris_repro_v4/XXQL2501/r10/seed_20260729 \\
        --case XXQL2501=workspace/runs/formal_morris_repro_v4/XXQL2501/r10/seed_20260812 \\
        --case XXQL2502=workspace/runs/formal_morris_stability_rerun_v1/XXQL2502/r40/seed_20260729 \\
        --out-dir workspace/sa/morris_response_effects

Each ``--case`` is ``SEASON=DIR`` where DIR contains ``sa_sen_morris.mio``.
The seed is read from the parent ``seed_*`` directory name, so the caller
does not need to repeat it.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.project import PROJECT_ROOT, git_metadata, sha256_file
from src.sensitivity.sa_contract import (
    ALL_RESPONSES,
    MAIN_RESPONSE_IDS,
    RANKING_DOMAIN_GENERAL,
    RANKING_DOMAIN_WATER_NITROGEN,
    SAContractError,
)

MIO_FILENAME = "sa_sen_morris.mio"
OUTPUT_COLUMNS = [
    "run_id", "data_status", "season", "seed", "ranking_domain", "response_group",
    "response_id", "response_label", "unit", "observation_id", "treatment", "parameter",
    "mu", "mu_star", "sigma",
    "n_samples",
    "component_count", "aggregation_level", "aggregation_note",
    "mu_star_share_within_observation", "sigma_share_within_observation",
    "mu_star_share_within_family", "sigma_share_within_family",
    "trajectory_failure_rate_available",
]

# data_status for Morris evidence: the multiseason rerun is science_pending
# (bootstrap/convergence not all green), matching the existing paper_data.
DEFAULT_DATA_STATUS = "science_pending"

# observation-name → (treatment_number, response_feature_key) parser.
# .mio observation names look like "tn13_fruitd_end" (per-treatment) or
# "wn_water_n0_fruitd_end" / "wn_nslope_w3_fruitd_end" / "wn_interaction_fruitd_end"
# (water-nitrogen derived, carrying a level code that must be folded away to
# match the aggregated response contract).
_OBS_RE = re.compile(r"^tn(\d+)_([a-z0-9_]+)$", re.IGNORECASE)
# WN_WATER_<LEVEL>_<FEATURE>, WN_NSLOPE_<WLEVEL>_<FEATURE>, WN_INTERACTION_<FEATURE>
_WN_WATER_RE = re.compile(r"^wn_water_[a-z0-9]+_([a-z0-9_]+)$", re.IGNORECASE)
_WN_NSLOPE_RE = re.compile(r"^wn_nslope_[a-z0-9]+_([a-z0-9_]+)$", re.IGNORECASE)
_WN_INTERACTION_RE = re.compile(r"^wn_interaction_([a-z0-9_]+)$", re.IGNORECASE)


def _parse_observation(obs_name: str) -> tuple[int | None, str]:
    """Return (treatment_number, feature_key) for a .mio observation name.

    ``feature_key`` is the response-contract key, already aggregated:

    * per-treatment ``tn{N}_{feat}`` → ``(N, FEAT)`` — many treatments fold
      into one ``MEAN_FEAT`` response downstream;
    * ``wn_water_{level}_{feat}`` → ``(None, WN_WATER_FEAT)`` — all water
      levels fold into one ``WN_WATER_FEAT`` response;
    * ``wn_nslope_{w}_{feat}`` → ``(None, WN_NSLOPE_FEAT)``;
    * ``wn_interaction_{feat}`` → ``(None, WN_INTERACTION_FEAT)``.
    """
    s = str(obs_name).strip().lower()
    m = _OBS_RE.match(s)
    if m:
        return int(m.group(1)), m.group(2).upper()
    m = _WN_WATER_RE.match(s)
    if m:
        return None, f"WN_WATER_{m.group(1).upper()}"
    m = _WN_NSLOPE_RE.match(s)
    if m:
        return None, f"WN_NSLOPE_{m.group(1).upper()}"
    m = _WN_INTERACTION_RE.match(s)
    if m:
        return None, f"WN_INTERACTION_{m.group(1).upper()}"
    # Unrecognised: keep raw upper token so nothing is silently dropped.
    return None, s.upper()


# Map a feature key (the sa_model emit suffix) onto a response_group from the
# output contract.  Mirrors configs/sa/eggplant_formal_xxql*_outputs_*.json
# response_groups, but kept here so the exporter is self-contained and does
# not need to guess which season's contract to load.
_FEATURE_TO_GROUP: dict[str, str] = {}
for _grp, _feats in {
    "phenology": ["ADAPS", "PDFPS", "MDAPS"],
    "canopy": ["LAIXS", "LAI_AUC", "LAI_PEAK", "LAI_TPEAK", "LAI_END"],
    "biomass": ["CWAMS", "LEAF_END_LWAD", "STEM_END_SWAD", "AGB_END_CWAD", "HI_END_HIAD"],
    "yield_harvest": ["YIELD_HWAMS", "HIAMS", "FRUITD_AUC", "FRUITD_END", "CUMHARVEST_DAP50"],
    "water_response": [],   # WN_WATER_* — keyed by prefix below
    "nitrogen_response": [],  # WN_NSLOPE_*
    "water_nitrogen_interaction": [],  # WN_INTERACTION_*
}.items():
    for _f in _feats:
        _FEATURE_TO_GROUP[_f] = _grp


def _feature_to_group(feature_key: str) -> tuple[str, str]:
    """Return (response_group, ranking_domain) for a feature key."""
    key = feature_key.upper()
    if key.startswith("WN_WATER_"):
        return "water_response", RANKING_DOMAIN_WATER_NITROGEN
    if key.startswith("WN_NSLOPE_"):
        return "nitrogen_response", RANKING_DOMAIN_WATER_NITROGEN
    if key.startswith("WN_INTERACTION_"):
        return "water_nitrogen_interaction", RANKING_DOMAIN_WATER_NITROGEN
    group = _FEATURE_TO_GROUP.get(key, "other")
    return group, RANKING_DOMAIN_GENERAL


def _seed_from_dir(case_dir: Path) -> str:
    """Extract the seed from a ``seed_*`` parent directory name."""
    # Accept either the seed_XXXXXXXX dir itself or a dir containing the .mio
    # whose parent is seed_XXXXXXXX.
    for parent in [case_dir, case_dir.parent]:
        name = parent.name
        m = re.match(r"^seed_(\d+)$", name, re.IGNORECASE)
        if m:
            return m.group(1)
    # Fall back: use the directory name verbatim so provenance is not lost.
    return case_dir.name


def _load_mio(mio_path: Path) -> list[dict[str, str]]:
    """Read a .mio file into raw row dicts (BOM-tolerant)."""
    with mio_path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _feature_to_response_id(feature_key: str) -> str:
    """Map a feature key to its canonical response_id from the contract.

    ``WN_*`` derivatives are already canonical.  Per-treatment features fold to
    their ``MEAN_<KEY>`` family name *for grouping only* — the actual
    treatment-mean μ*/σ is NOT computed here (it requires per-run responses;
    see module docstring).  The returned id names the response family, not a
    claimed treatment-mean statistic.
    """
    key = feature_key.upper()
    if key.startswith("WN_"):
        return key
    return f"MEAN_{key}"


def export_morris_response_effects(
    run_id: str,
    cases: list[tuple[str, Path]],
    *,
    data_status: str = DEFAULT_DATA_STATUS,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    """Build response-effects rows from a list of (season, case_dir) cases.

    Each case_dir must contain ``sa_sen_morris.mio``.  Returns (rows, manifest).

    **Aggregation semantics (corrected for the P0 review finding).**

    The ``.mio`` file carries, for every (observation × parameter), the Morris
    summary statistics mu / mu_star / sigma and the realised trajectory count
    ``n_samples``.  These are *observation-level* statistics; they are computed
    by PESTPP-SEN directly on the per-observation model output and are exact at
    that level.

    A *treatment-mean response* (e.g. MEAN_FRUITD_END = mean over treatments of
    FRUITD_END) has its own mu / mu_star / sigma that are **not** the mean of
    the per-treatment mu / mu_star / sigma.  The correct treatment-mean
    elementary effect for trajectory r is::

        EE_mean_Y^(r) = (1/T) Σ_t EE_t^(r)

    and mu*/sigma are then computed over trajectories of *that* quantity.
    Computing mean_t(mu_star_t) instead loses sign cancellation and covariance
    across treatments.  Reconstructing the true treatment-mean statistics
    requires the per-run response matrix Y[run, observation], which PESTPP-SEN
    consumes as a disposable intermediate and does not persist in ``.mio``.

    Therefore this exporter **does not** claim to report treatment-mean mu/sigma.
    It reports:

    * one row per **observation** (e.g. ``tn13_fruitd_end``), carrying the
      exact observation-level mu / mu_star / sigma / n_samples from ``.mio``;
    * the within-observation share of mu_star (dimensionless, comparable across
      observations — this is the same normalisation the frozen ranking uses);
    * a within-response-family aggregate of the dimensionless shares only
      (``mu_star_share_within_family``), never a mean of raw mu_star.

    The ``MEAN_<KEY>`` response_id labels the response *family* (the set of
    treatments sharing a feature), not a computed treatment-mean statistic.
    ``aggregation_level`` and ``aggregation_note`` make this explicit per row.
    """
    if not cases:
        raise ValueError("at least one --case SEASON=DIR is required")

    source_artifacts: list[dict[str, str]] = []
    seen_cases: set[tuple[str, str]] = set()
    # One record per (season, seed, observation_name, parameter) — exact .mio row.
    records: list[dict[str, object]] = []

    for season, case_dir in cases:
        mio_path = case_dir / MIO_FILENAME
        if not mio_path.is_file():
            raise FileNotFoundError(f"{MIO_FILENAME} not found in case dir: {case_dir}")
        seed = _seed_from_dir(case_dir)
        case_key = (season, str(case_dir))
        if case_key in seen_cases:
            raise ValueError(f"duplicate case (same season+dir): {season}={case_dir}")
        seen_cases.add(case_key)
        source_artifacts.append({
            "season": season,
            "seed": seed,
            "case_dir": str(case_dir),
            "mio_sha256": sha256_file(mio_path),
        })
        for row in _load_mio(mio_path):
            obs_name = str(row.get("observation_name", "")).strip()
            tn, feature_key = _parse_observation(obs_name)
            if not feature_key:
                continue
            parameter = str(row.get("parameter_name", "")).strip().upper()
            if not parameter:
                continue
            try:
                mu = float(row["sen_mean"])
                mu_star = float(row["sen_mean_abs"])
                sigma = float(row["sen_std_dev"])
                n_samples = int(float(row.get("n_samples", 0)))
            except (KeyError, ValueError):
                continue
            response_family = _feature_to_response_id(feature_key)
            response_group, ranking_domain = _feature_to_group(feature_key)
            spec = ALL_RESPONSES.get(response_family)
            records.append({
                "season": season, "seed": seed,
                "observation_name": obs_name,
                "treatment": tn,
                "feature_key": feature_key,
                "response_family": response_family,
                "response_group": response_group,
                "ranking_domain": ranking_domain,
                "parameter": parameter,
                "mu": mu, "mu_star": mu_star, "sigma": sigma,
                "n_samples": n_samples,
                "response_label": spec.paper_label if spec else response_family,
                "unit": spec.unit if spec else "",
            })

    # Within-observation share of mu_star/sigma (dimensionless; matches the
    # frozen ranking's relative_effect = score / sum_over_parameters(score)).
    # Pre-aggregate totals once (O(n)) instead of an O(n^2) scan per record.
    obs_totals_mu: dict[tuple[str, str, str, str], float] = defaultdict(float)
    obs_totals_sigma: dict[tuple[str, str, str, str], float] = defaultdict(float)
    for r in records:
        key = (r["season"], r["seed"], r["observation_name"], r["ranking_domain"])
        obs_totals_mu[key] += r["mu_star"]
        obs_totals_sigma[key] += r["sigma"]
    for r in records:
        key = (r["season"], r["seed"], r["observation_name"], r["ranking_domain"])
        tot_mu = obs_totals_mu[key]
        tot_sigma = obs_totals_sigma[key]
        r["mu_star_share_within_observation"] = (r["mu_star"] / tot_mu) if tot_mu else float("nan")
        r["sigma_share_within_observation"] = (r["sigma"] / tot_sigma) if tot_sigma else float("nan")

    # Within-response-family aggregate of the dimensionless shares ONLY.
    # This is the legitimate cross-treatment summary: averaging shares (not raw
    # mu*) is valid because shares are dimensionless and already normalised.
    family_shares: dict[tuple[str, str, str, str, str], list[float]] = defaultdict(list)
    family_shares_sigma: dict[tuple[str, str, str, str, str], list[float]] = defaultdict(list)
    for r in records:
        fkey = (r["season"], r["seed"], r["response_family"], r["ranking_domain"], r["parameter"])
        family_shares[fkey].append(r["mu_star_share_within_observation"])
        family_shares_sigma[fkey].append(r["sigma_share_within_observation"])
    family_agg: dict[tuple[str, str, str, str, str], tuple[float, float, int]] = {}
    for fkey, shares in family_shares.items():
        finite = [s for s in shares if s == s]
        agg = sum(finite) / len(finite) if finite else float("nan")
        sig_shares = [s for s in family_shares_sigma[fkey] if s == s]
        agg_sig = sum(sig_shares) / len(sig_shares) if sig_shares else float("nan")
        family_agg[fkey] = (agg, agg_sig, len(finite))

    rows: list[dict[str, str]] = []
    for r in records:
        fkey = (r["season"], r["seed"], r["response_family"], r["ranking_domain"], r["parameter"])
        agg_share, agg_sig_share, component_count = family_agg.get(fkey, (float("nan"), float("nan"), 0))
        rows.append({
            "run_id": run_id,
            "data_status": data_status,
            "season": r["season"],
            "seed": r["seed"],
            "ranking_domain": r["ranking_domain"],
            "response_group": r["response_group"],
            "response_id": r["response_family"],
            "response_label": r["response_label"],
            "unit": r["unit"],
            "observation_id": r["observation_name"],
            "treatment": "" if r["treatment"] is None else str(r["treatment"]),
            "parameter": r["parameter"],
            "mu": f"{r['mu']:.10g}",
            "mu_star": f"{r['mu_star']:.10g}",
            "sigma": f"{r['sigma']:.10g}",
            "n_samples": str(r["n_samples"]),
            "component_count": str(component_count),
            "aggregation_level": "observation",
            "aggregation_note": (
                "Observation-level Morris statistics from .mio (exact). "
                "mu_star_share_within_family is the mean of dimensionless "
                "within-observation shares; raw mu/mu_star/sigma are NOT "
                "treatment-mean statistics (P0: requires per-run responses)."
            ),
            "mu_star_share_within_observation": (
                f"{r['mu_star_share_within_observation']:.10g}"
                if r["mu_star_share_within_observation"] == r["mu_star_share_within_observation"] else ""),
            "sigma_share_within_observation": (
                f"{r['sigma_share_within_observation']:.10g}"
                if r["sigma_share_within_observation"] == r["sigma_share_within_observation"] else ""),
            "mu_star_share_within_family": (
                f"{agg_share:.10g}" if agg_share == agg_share else ""),
            "sigma_share_within_family": (
                f"{agg_sig_share:.10g}" if agg_sig_share == agg_sig_share else ""),
            "trajectory_failure_rate_available": "no",
        })

    # Stable ordering: season, seed, ranking_domain, response_group, family, descending mu_star.
    rows.sort(key=lambda r: (
        r["season"], r["seed"], r["ranking_domain"], r["response_group"],
        r["response_id"], -(float(r["mu_star"]) if r["mu_star"] else 0.0),
        r["parameter"],
    ))

    manifest = {
        "run_id": run_id,
        "bundle_type": "morris_response_effects",
        "data_status": data_status,
        "schema_version": 2,
        "source_artifacts": source_artifacts,
        "git": git_metadata(),
        "row_count": len(rows),
        "seasons": sorted({r["season"] for r in rows}),
        "seeds": sorted({r["seed"] for r in rows}),
        "ranking_domains": sorted({r["ranking_domain"] for r in rows}),
        "response_count": len({r["response_id"] for r in rows}),
        "parameter_count": len({r["parameter"] for r in rows}),
        "main_response_ids_present": sorted(
            {r["response_id"] for r in rows} & set(MAIN_RESPONSE_IDS)
        ),
    }
    return rows, manifest


def _parse_case_arg(value: str) -> tuple[str, Path]:
    """Parse a ``SEASON=DIR`` argument."""
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            f"--case must be SEASON=DIR, got {value!r}"
        )
    season, _, dir_part = value.partition("=")
    season = season.strip()
    if not season:
        raise argparse.ArgumentTypeError(f"--case season is empty: {value!r}")
    p = Path(dir_part.strip())
    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve()
    return season, p


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export morris_response_effects.csv (W2, plan §5.2/§10)."
    )
    parser.add_argument("--run-id", required=True,
                        help="Bundle run id (e.g. formal_morris_response_effects_20260729).")
    parser.add_argument("--case", action="append", default=[], metavar="SEASON=DIR",
                        help="One Morris case dir containing sa_sen_morris.mio. Repeat per case.")
    parser.add_argument("--out-dir", required=True, help="Output directory.")
    parser.add_argument("--data-status", default=DEFAULT_DATA_STATUS,
                        help=f"data_status label (default: {DEFAULT_DATA_STATUS}).")
    args = parser.parse_args(argv)

    cases = [_parse_case_arg(c) for c in args.case]
    try:
        rows, manifest = export_morris_response_effects(
            args.run_id, cases, data_status=args.data_status,
        )
    except (ValueError, FileNotFoundError, SAContractError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "morris_response_effects.csv"
    # Write plain UTF-8 (no BOM): R's read.csv(check.names=FALSE) preserves a
    # BOM as part of the first column name, which would break the provenance
    # gate (run_id / data_status match).  The other SA tables are BOM-free.
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    manifest_path = out_dir / "morris_response_effects_manifest.json"
    manifest["artifacts"] = [
        {"role": "morris_response_effects", "path": csv_path.name,
         "sha256": sha256_file(csv_path), "rows": len(rows)},
    ]
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    print(f"morris_response_effects.csv written: {csv_path}")
    print(f"  rows: {len(rows)}")
    print(f"  seasons: {manifest['seasons']}")
    print(f"  seeds: {manifest['seeds']}")
    print(f"  ranking domains (kept separate): {manifest['ranking_domains']}")
    print(f"  responses: {manifest['response_count']} (main-text present: {len(manifest['main_response_ids_present'])})")
    print(f"  parameters: {manifest['parameter_count']}")
    print(f"  source cases: {len(cases)} (each .mio sha256-pinned in manifest)")
    print(f"  git: {manifest['git'].get('git_commit', '?')[:12]} dirty={manifest['git'].get('git_dirty', '?')}")
    print("  NOTE: read-only — .mio sources and v4 paper_data were not modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
