"""T8 multi-season observation builder for ``build_pest.py``.

This module is imported lazily by ``build_pest.py`` when
``--multiseason-design`` is supplied.  It handles per-season FileA/FileT/TMT
reading, observation merging with global-run numbering, and PST generation
via the existing ``create_ins_and_pst_multi``.

P0-C refactor: the previous ``ctx`` dict injection (13 symbols) and
``USER_INPUT_DIR`` module-global mutation have been eliminated.  Functions
and constants are now imported directly from ``build_pest``, and per-season
state is carried by :class:`SeasonContext` instead of mutating the global.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pyemu

from src.calibration.build_pest import (
    PEST_EVAL_FILE,
    PEST_HARVEST_FILE,
    PEST_JOINT_FILE,
    PEST_TMTGROW_FILE,
    _build_evaluate_observations_from_filea,
    _finalize_ies_contract,
    _infer_excode_from_filex,
    _parse_batch_entries,
    _read_tmt_harvest_events,
    _read_tmt_process_points,
    _resolve_filex_path,
    _write_run_manifest,
    create_ins_and_pst_multi,
)
from src.calibration.multiseason_design import MultiSeasonDesign
from src.calibration.observation_policy import load_observation_policy
from src.calibration.seasonal_parameters import (
    seasonal_offset_params_from_frozen_bounds,
    validate_projected_physical_bounds,
)
from src.common.project import PROJECT_ROOT


@dataclass
class SeasonContext:
    """Per-season state that was previously carried by ``USER_INPUT_DIR``.

    Replacing the module-global mutation with an explicit dataclass makes the
    multiseason builder reentrant: each season's FileX/SOIL resolution is
    scoped to its own ``input_dir``, with no risk of a stale global leaking
    into the next season's lookups.
    """

    season_id: str
    input_dir: Path
    experiment_code: str
    treatments: list[int] = field(default_factory=list)


def _design_observation_policies(design, explicit_policies=None):
    """Use the design-declared policy unless the CLI supplied one explicitly."""
    if explicit_policies:
        return explicit_policies
    policy_path = Path(design.observation_policy)
    if not policy_path.is_absolute():
        policy_path = (PROJECT_ROOT / policy_path).resolve()
    return load_observation_policy(policy_path)


def _tmt_events_per_run(entries, input_dir=None):
    """Cross-FileX TMT resolver (mirrors build_pest._collect_tmt_events_per_run).

    *input_dir* is passed explicitly to ``_resolve_filex_path`` so per-season
    FileX resolution is scoped to the season bundle — no global mutation.
    """
    events_by_run: dict[int, list] = {}
    points_by_run: dict[int, list] = {}
    tmt_cache = {}

    for entry in entries:
        run_no = int(entry["run"])
        tn = int(entry.get("tn", -99))
        filex = entry.get("filex")
        filex_path = (
            _resolve_filex_path(filex, input_dir=input_dir)
            or (filex if filex and os.path.isabs(filex) else None)
        )
        if not filex_path:
            raise FileNotFoundError(f"cannot resolve FileX for run {run_no}: {filex!r}")
        if filex_path not in tmt_cache:
            excode = _infer_excode_from_filex(filex_path)
            tmt_path = os.path.join(
                os.path.dirname(os.path.abspath(filex_path)), f"{excode}.TMT"
            ) if excode else None
            tmt_cache[filex_path] = (_read_tmt_harvest_events(tmt_path), _read_tmt_process_points(tmt_path))
        ev_by_tn, pt_by_tn = tmt_cache[filex_path]
        events_by_run[run_no] = list(ev_by_tn.get(tn, []))
        points_by_run[run_no] = list(pt_by_tn.get(tn, []))
    return events_by_run, points_by_run


def build_multiseason_stage2(
    args, prefix, allowed, extra_allowed, params, model_cmd_extra,
    *,
    observation_policies=None,
):
    """Build stage2 observations for multi-season joint calibration (T8 §4-§7).

    P0-C: the previous ``ctx`` dict (13 injected symbols) has been replaced
    by direct imports from ``build_pest``.  Per-season state is carried by
    :class:`SeasonContext` — no ``USER_INPUT_DIR`` global mutation.
    """
    design_path = Path(args.multiseason_design).expanduser().resolve()
    if not design_path.is_file():
        raise FileNotFoundError(f"Multi-season design not found: {design_path}")
    design = MultiSeasonDesign.load(design_path)
    observation_policies = _design_observation_policies(design, observation_policies)
    seasons = design.calibration_seasons
    if len(seasons) < 2 and not design.diagnostic_single_season:
        raise ValueError("Multi-season calibration requires at least 2 calibration seasons")

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # PEST has no knowledge of a derived autumn value.  Declare the small
    # offset vector as first-class PEST parameters, but source its bounds only
    # from the approved frozen file.  The runner will remove these PEST-only
    # names and inject the projected physical values season by season.
    if design.seasonal_parameterization is not None:
        bounds_id = str(getattr(args, "bounds_id", "") or "").strip()
        bounds_crop = str(getattr(args, "bounds_crop", "eggplant") or "eggplant").strip()
        if not bounds_id:
            raise ValueError("seasonal offsets require an explicit frozen --bounds-id")
        bounds_path = (
            PROJECT_ROOT / "data" / "parameter_registry" / "bounds_frozen" / bounds_crop / f"{bounds_id}.csv"
        )
        if not bounds_path.is_file():
            raise FileNotFoundError(f"seasonal-offset frozen bounds not found: {bounds_path}")
        params = list(params) + seasonal_offset_params_from_frozen_bounds(
            design.seasonal_parameterization, bounds_path
        )
        validate_projected_physical_bounds(params, design.seasonal_parameterization)

    global_run = 0
    run_mapping_rows = []
    all_eval_rows = []
    all_harvest_rows = []
    all_process_rows = []

    for season in seasons:
        bundle = season.bundle_absolute
        # SeasonContext replaces USER_INPUT_DIR global mutation.  Per-season
        # FileX/SOIL resolution is scoped to the season bundle.
        sctx = SeasonContext(
            season_id=season.season_id,
            input_dir=bundle,
            experiment_code=season.experiment_code,
            treatments=list(season.treatments),
        )

        batch_file = sctx.input_dir / "DSSBatch.v48"
        if not batch_file.is_file():
            raise FileNotFoundError(f"Season {sctx.season_id}: DSSBatch.v48 missing")
        entries = _parse_batch_entries(str(batch_file))
        # Rewrite absolute FileX paths to bare names so _resolve_filex_path
        # looks them up in the season bundle (passed as input_dir).  The
        # XXQL2502 batch ships with C:\DSSAT48\TOMATO\... absolute paths.
        for e in entries:
            raw = e.get("filex", "")
            if raw and os.path.isabs(str(raw)):
                e["filex"] = os.path.basename(str(raw))

        by_tn = {int(e.get("tn", -99)): e for e in entries}
        missing_tns = [tn for tn in sctx.treatments if tn not in by_tn]
        if missing_tns:
            raise ValueError(
                f"Season {sctx.season_id}: treatments absent from batch: {missing_tns}"
            )
        # DSSAT RUN is batch-row order.  The runtime writes a selected batch in
        # the design order, so the builder must use the identical local RUN map.
        entries = []
        for local_run, tn in enumerate(sctx.treatments, 1):
            entry = dict(by_tn[tn])
            entry["run"] = local_run
            entries.append(entry)

        local_to_global = {}
        for e in entries:
            global_run += 1
            lr = int(e["run"])
            tn = int(e.get("tn", -99))
            local_to_global[lr] = global_run
            run_mapping_rows.append({
                "global_run": global_run, "season_id": sctx.season_id,
                "experiment_code": sctx.experiment_code,
                "treatment": tn, "local_run": lr,
            })

        sid = sctx.season_id
        eval_df = _build_evaluate_observations_from_filea(entries, input_dir=str(sctx.input_dir))
        for _, row_ in eval_df.iterrows():
            lr = int(row_.get("@RUN", row_.get("RUN", 0)))
            gr = local_to_global.get(lr, lr)
            record = {"@RUN": gr, "TN": int(row_.get("TN", -99)), "season": sid}
            for col in eval_df.columns:
                if col in ("@RUN", "RUN", "TN", "season"):
                    continue
                record[col] = row_[col]
            all_eval_rows.append(record)

        events_by_run, points_by_run = _tmt_events_per_run(
            entries, input_dir=str(sctx.input_dir)
        )
        for e in entries:
            lr = int(e["run"])
            gr = local_to_global.get(lr, lr)
            tn = int(e.get("tn", -99))
            for ev in events_by_run.get(lr, []):
                # T10 direct harvest contract: read CHFPW and CHPDT as direct
                # cumulative series from FileT — no differencing, no PWAD/PWAI.
                # Both fresh and dry cumulative enter Phi after the shared
                # observation-policy transform. PWAD/PWAI are not formal
                # observations in T10.
                chfpw_val = float(ev.get("chfpw", -99.0))
                chpdt_val = float(ev.get("chpdt", -99.0))
                all_harvest_rows.append({
                    "@RUN": gr, "TN": tn, "HNO": int(ev["hno"]),
                    "DATE": int(ev["date"]),
                    "CHFPWM": chfpw_val, "CHPDTM": chpdt_val,
                    "CHFPWS": -99.0, "CHPDTS": -99.0, "season": sid,
                })
            for p in points_by_run.get(lr, []):
                all_process_rows.append({
                    "@RUN": gr, "TN": tn, "DATE": int(p["date"]),
                    "LAIDM": float(p["laid"]), "LWADM": float(p["lwad"]),
                    "SWADM": float(p["swad"]),
                    "LAIDS": -99.0, "LWADS": -99.0, "SWADS": -99.0, "season": sid,
                })

    df_eval = pd.DataFrame(all_eval_rows)
    df_harvest = pd.DataFrame(all_harvest_rows)
    df_process = pd.DataFrame(all_process_rows)

    adapm_sigma = float(getattr(args, "adapm_sigma", None) or 25.0)
    harvest_sigmas = {}
    if not df_harvest.empty:
        s0 = float(getattr(args, "pwadm_sigma0", 250.0))
        cv = float(getattr(args, "pwadm_cv", 0.08))
        sf = float(getattr(args, "pwadm_sigma_factor", 1.0))
        for hno, g in df_harvest.groupby("HNO"):
            # T10 direct harvest: CHFPW and CHPDT get their own sigma keys.
            for var in ("CHFPWM", "CHPDTM"):
                med = float(g[var].median()) if var in g.columns else 0.0
                harvest_sigmas[f"{var}_H{int(hno)}"] = float((s0**2 + (cv * abs(med))**2)**0.5 * sf)

    process_sigmas = {}
    if not df_process.empty:
        laidm_sf = float(getattr(args, "laidm_sigma_factor", 1.0))
        lwadm_sf = float(getattr(args, "lwadm_sigma_factor", 1.0))
        swadm_sf = float(getattr(args, "swadm_sigma_factor", 1.0))
        for var, s0, cv in [
            ("LAIDM", 1.6, 0.50), ("LWADM", 80.0, 0.25), ("SWADM", 100.0, 0.25),
        ]:
            g = df_process[df_process[var] != -99.0]
            if g.empty:
                continue
            for date, gg in g.groupby("DATE"):
                med = float(gg[var].median())
                sigma = (s0**2 + (cv * abs(med))**2)**0.5
                if var == "LAIDM":
                    sigma *= laidm_sf
                elif var == "LWADM":
                    sigma *= lwadm_sf
                elif var == "SWADM":
                    sigma *= swadm_sf
                process_sigmas[f"{var}_D{int(date)}"] = float(sigma)

    stage2_outputs = [
        {
            "model_out_path": PEST_EVAL_FILE, "obs_bases": {"ADAP"},
            "critical_obs": {"ADAPM"},
            "group_sigmas": {"ADAPM": float(adapm_sigma)}, "df": df_eval,
        },
        {
            "model_out_path": PEST_JOINT_FILE,
            "obs_bases": {"LAIX", "CNAM", "CHTA", "CNAA", "PWAM", "H#AM", "HIAM"},
            "critical_obs": set(),
            "group_sigmas": {
                "PWAMM": float(getattr(args, "pwamm_sigma", 20.0)),
                "LAIXM": float(getattr(args, "laixm_sigma", 0.8)),
                "CNAMM": float(getattr(args, "cnamm_sigma", 25.0)),
                "CHTAM": 15.0, "CNAAM": 20.0, "H#AMM": 50.0,
                "HIAMM": float(getattr(args, "hiamm_sigma", 0.10)),
            },
            "df": df_eval,
        },
        {
            "model_out_path": PEST_HARVEST_FILE, "obs_bases": {"CHFPW", "CHPDT"},
            "critical_obs": set(), "group_sigmas": harvest_sigmas, "df": df_harvest,
        },
        {
            "model_out_path": PEST_TMTGROW_FILE, "obs_bases": {"LAID", "LWAD", "SWAD"},
            "critical_obs": set(), "group_sigmas": process_sigmas, "df": df_process,
        },
    ]

    run_map_path = out_dir / f"{prefix}_run_mapping.csv"
    pd.DataFrame(run_mapping_rows).to_csv(run_map_path, index=False, encoding="utf-8-sig")
    print(f"run_mapping ({len(run_mapping_rows)} runs) -> {run_map_path}")

    model_cmd_extra = f"--batch DSSBatch.v48 --harvest-var {getattr(args, 'harvest_var', 'CHPDT')}"
    create_ins_and_pst_multi(
        params, prefix,
        noptmax=int(args.noptmax), ies_num_reals=int(args.ies_num_reals),
        random_seed=int(args.random_seed),
        outputs=stage2_outputs, evaluate_out_path=PEST_EVAL_FILE,
        model_cmd_extra=model_cmd_extra, out_dir=str(out_dir),
        weight_scheme=str(getattr(args, "weight_scheme", "raw")),
        observation_policies=observation_policies,
    )

    pst_path = out_dir / f"{prefix}.pst"
    if pst_path.is_file():
        pst = pyemu.Pst(str(pst_path))
        sched = str(PROJECT_ROOT / "src" / "calibration" / "run_multiseason.py").replace("\\", "/")
        design_path_fwd = str(design_path).replace("\\", "/")
        transform_path = out_dir / f"{prefix}.observation_transforms.json"
        transform_arg = (
            f" --observation-transform-config {transform_path.name}"
            if transform_path.is_file() else ""
        )
        pst.model_command = [
            f'python "{sched}" --design "{design_path_fwd}" --param-csv {prefix}_params.csv'
            f' --harvest-var {getattr(args, "harvest_var", "CHPDT")}'
            f' --prefix {prefix}{transform_arg}'
        ]
        pst.write(str(pst_path))

    # ── Apply T8 weight formula (§7.2) ──────────────────────────────────
    _apply_t8_weights(out_dir, prefix, design.group_policy, run_mapping_rows)

    # ── Write observation_registry.csv ───────────────────────────────────
    _write_obs_registry(out_dir, prefix, run_mapping_rows)

    # ── Write group_weight_audit.csv ─────────────────────────────────────
    _write_group_weight_audit(out_dir, prefix, design.group_policy, run_mapping_rows)

    ies_contract = _finalize_ies_contract(
        pst_path,
        out_dir=str(out_dir),
        prefix=prefix,
        ies_num_reals=int(args.ies_num_reals),
        random_seed=int(args.random_seed),
        bad_phi_sigma=float(getattr(args, "bad_phi_sigma", 1.0e300)),
        observation_noise=bool(observation_policies),
    )

    _write_run_manifest(
        str(out_dir), run_id=prefix, run_type="multiseason_calibration",
        crop="eggplant", mode="eggplant_stage2_multiseason",
        design_config=str(design_path), design_id=design.design_id,
        bad_phi_sigma=ies_contract.get("bad_phi_sigma", ""),
        observation_ensemble=ies_contract.get("observation_ensemble", ""),
    )
    print(f"Multi-season PST: {pst_path}")
    print(f"  seasons: {[s.season_id for s in seasons]}")
    print(f"  global runs: {global_run}")
    n_adj = len([p for p in params if p.get("status") != "fixed"])
    print(f"  npar_adj: {n_adj}")


# ── Post-build artifact writers ─────────────────────────────────────────────

def _family_for_group(group):
    root = str(group).strip().upper()
    if "_" in root and root.split("_", 1)[0][-2:] in {"SP", "FA"}:
        root = root.split("_", 1)[1]
    for suffix in ("_H", "_D"):
        idx = root.find(suffix)
        if idx > 0:
            root = root[:idx]
            break
    family_map = {
        "ADAPM": "PHENO", "ADAPS": "PHENO",
        "LAIXM": "CANOPY", "LAIDM": "CANOPY", "LAIXS": "CANOPY",
        "LWADM": "BIOMASS", "SWADM": "BIOMASS",
        "CNAMM": "PLANT_N",
        "HIAMM": "BIOMASS", "CWAMS": "BIOMASS",
        "PWADM": "CUMULATIVE_HARVEST", "PWAIM": "INCREMENTAL_HARVEST",
        # T10 direct harvest variables (log-transformed cumulative series).
        "CHFPWM": "HARVEST_FRESH", "CHFPWS": "HARVEST_FRESH",
        "CHPDTM": "HARVEST_DRY", "CHPDTS": "HARVEST_DRY",
    }
    for key, family in family_map.items():
        if root.startswith(key):
            return family
    raise ValueError(f"no T8 variable family declared for observation group {group!r}")


def _load_group_budgets(policy_path):
    path = Path(policy_path)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"T8 group policy not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    budgets = {str(row["group"]).strip().upper(): float(row["phi_budget"]) for row in rows}
    if any(not value > 0 for value in budgets.values()):
        raise ValueError("all T8 phi budgets must be positive")
    return budgets


def _season_for_obsnme(obsnme, run_seasons):
    """Return the calibration season encoded by an ``*_R<global_run>`` name."""
    import re

    match = re.search(r"_R(\d+)(?:_|$)", str(obsnme), flags=re.IGNORECASE)
    if match is None:
        raise ValueError(f"cannot assign observation to a season: {obsnme!r}")
    season = run_seasons.get(int(match.group(1)))
    if season is None:
        raise ValueError(f"observation run is absent from run mapping: {obsnme!r}")
    return season


def _apply_t8_weights(out_dir, prefix, group_policy, run_mapping_rows):
    """Rewrite PST weights using T8 §7.2 formula: weight = (1/sigma) × sqrt(budget/n_g)."""
    import csv, math

    pst_path = out_dir / f"{prefix}.pst"
    weights_path = out_dir / f"{prefix}.weights.audit.csv"
    if not pst_path.is_file() or not weights_path.is_file():
        return

    budgets = _load_group_budgets(group_policy)

    run_seasons = {int(row["global_run"]): str(row["season_id"]) for row in run_mapping_rows}
    # One budget applies to a scientific family within a season. Harvest HNO
    # and process DATE groups must not each receive the full family budget.
    bucket_n = {}
    obs_bucket = {}
    with weights_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            obsnme = (row.get("obsnme") or row.get("\ufeffobsnme") or "").strip().lower()
            grp = (row.get("obgnme") or "").strip().lower()
            if float(row.get("weight", 0)) > 0:
                bucket = (_season_for_obsnme(obsnme, run_seasons), _family_for_group(grp))
                obs_bucket[obsnme] = bucket
                bucket_n[bucket] = bucket_n.get(bucket, 0) + 1

    bucket_mult = {}
    for bucket, n in bucket_n.items():
        _, family = bucket
        budget = budgets[family]
        bucket_mult[bucket] = math.sqrt(budget / max(n, 1))

    # Rewrite PST observation weights
    pst = pyemu.Pst(str(pst_path))
    obs = pst.observation_data
    # Read sigma from weights audit (case-insensitive obsnme match, BOM-safe)
    sigmas = {}
    active = {}
    with weights_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            obsnme = (row.get("obsnme") or row.get("\ufeffobsnme") or "").strip().lower()
            s = float(row.get("sigma", 1))
            sigmas[obsnme] = s
            active[obsnme] = float(row.get("weight", 0)) > 0

    new_weights = []
    for obsnme in obs.obsnme:
        sigma = sigmas.get(obsnme.strip().lower(), 1.0)
        key = obsnme.strip().lower()
        mult = bucket_mult.get(obs_bucket.get(key), 1.0)
        new_weights.append(mult / sigma if active.get(key, False) and sigma > 0 else 0.0)

    obs["weight"] = new_weights
    pst.write(str(pst_path))

    # Keep the audit contract synchronized with the PST it describes.
    audit = pd.read_csv(weights_path, encoding="utf-8-sig")
    audit_key = audit["obsnme"].astype(str).str.lower()
    pst_weights = dict(zip(obs["obsnme"].astype(str).str.lower(), obs["weight"].astype(float)))
    audit["weight"] = [pst_weights.get(key, value) for key, value in zip(audit_key, audit["weight"])]
    audit["group_multiplier"] = [bucket_mult.get(obs_bucket.get(key), 1.0) for key in audit_key]
    audit.to_csv(weights_path, index=False, encoding="utf-8-sig")
    print(f"T10 weights applied ({len(bucket_mult)} family-season budgets) -> {pst_path}")


def _write_obs_registry(out_dir, prefix, run_mapping_rows):
    """Write observation_registry.csv joining run_mapping with weights audit."""
    import csv

    weights_path = out_dir / f"{prefix}.weights.audit.csv"
    if not weights_path.is_file():
        return

    # Build run lookup: global_run -> {season_id, experiment_code, treatment}
    run_lookup = {}
    for row in run_mapping_rows:
        run_lookup[int(row["global_run"])] = row

    registry_path = out_dir / f"{prefix}_observation_registry.csv"
    with weights_path.open("r", encoding="utf-8-sig", newline="") as f_in:
        reader = csv.DictReader(f_in)
        fieldnames = list(reader.fieldnames or []) + [
            "season_id", "experiment_code", "treatment", "global_run"
        ]
        # Move key columns to front
        ordered = ["obsnme", "season_id", "experiment_code", "treatment",
                   "global_run", "obgnme", "obsval", "weight", "sigma",
                   "sigma_source", "dataset_role"]
        remaining = [c for c in fieldnames if c not in ordered]
        all_fields = ordered + remaining
        rows_out = []
        for row in reader:
            # Extract global_run from obsnme (e.g., "adaps_r1" -> 1)
            obsnme = row.get("obsnme", "")
            import re
            m = re.search(r"[_Rr](\d+)(?:_|$)", obsnme)
            gr = int(m.group(1)) if m else None
            info = run_lookup.get(gr, {}) if gr else {}
            row.update({
                "season_id": info.get("season_id", ""),
                "experiment_code": info.get("experiment_code", ""),
                "treatment": info.get("treatment", ""),
                "global_run": gr or "",
                "dataset_role": "calibration",
            })
            rows_out.append({k: row.get(k, "") for k in all_fields})

    with registry_path.open("w", encoding="utf-8-sig", newline="") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=all_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows_out)
    print(f"observation_registry ({len(rows_out)} obs) -> {registry_path}")


def _write_group_weight_audit(out_dir, prefix, group_policy, run_mapping_rows):
    """Write group_weight_audit.csv with T8 phi budgets."""
    import csv, math

    weights_path = out_dir / f"{prefix}.weights.audit.csv"
    if not weights_path.is_file():
        return

    run_seasons = {int(row["global_run"]): str(row["season_id"]) for row in run_mapping_rows}
    # Compute the exact family-season partitions used by _apply_t8_weights.
    groups = {}
    with weights_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            obsnme = (row.get("obsnme") or row.get("\ufeffobsnme") or "").strip()
            bucket = (_season_for_obsnme(obsnme, run_seasons), _family_for_group(row.get("obgnme", "")))
            if bucket not in groups:
                groups[bucket] = {"n_obs": 0, "weights": [], "sigmas": []}
            w = float(row.get("weight", 0))
            s = float(row.get("sigma", 1))
            if w > 0:
                groups[bucket]["n_obs"] += 1
                groups[bucket]["weights"].append(w)
                groups[bucket]["sigmas"].append(s)

    budgets = _load_group_budgets(group_policy)

    audit_path = out_dir / f"{prefix}_group_weight_audit.csv"
    with audit_path.open("w", encoding="utf-8-sig", newline="") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=[
            "group", "season_id", "variable_family", "phi_budget", "n_obs",
            "mean_sigma_eff", "mean_weight", "weight_multiplier",
            "sigma_source", "note"
        ])
        writer.writeheader()
        for season, family in sorted(groups):
            g = groups[(season, family)]
            budget = budgets[family]
            mean_s = sum(g["sigmas"]) / max(len(g["sigmas"]), 1)
            mean_w = sum(g["weights"]) / max(len(g["weights"]), 1)
            # T10 family-season allocation: weight = (1/sigma) * sqrt(budget / n_obs)
            expected_mult = math.sqrt(budget / max(g["n_obs"], 1))
            actual_mult = mean_w * mean_s  # since weight = mult / sigma
            writer.writerow({
                "group": f"{season}:{family}",
                "season_id": season,
                "variable_family": family,
                "phi_budget": budget,
                "n_obs": g["n_obs"],
                "mean_sigma_eff": round(mean_s, 4),
                "mean_weight": round(mean_w, 6),
                "weight_multiplier": round(expected_mult, 6),
                "sigma_source": "assumed",
                "note": f"T8 §7.2: sqrt({budget}/{g['n_obs']}) = {expected_mult:.4f}",
            })
    print(f"group_weight_audit ({len(groups)} groups) -> {audit_path}")
