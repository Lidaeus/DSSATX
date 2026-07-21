"""T8 multi-season observation builder for ``build_pest.py``.

This module is imported by ``build_pest.py`` when ``--multiseason-design``
is supplied.  It handles per-season FileA/FileT/TMT reading, observation
merging with global-run numbering, and PST generation via the existing
``create_ins_and_pst_multi``.

It is deliberately kept separate so that single-season ``build_pest.py``
changes do not risk cascading merge conflicts or indentation drift in a
file that is already ~4000 lines.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import pandas as pd
import pyemu

from src.calibration.multiseason_design import MultiSeasonDesign
from src.common.project import PROJECT_ROOT

# Re-export from parent module so the multi-season branch can reach them.
# These are set by build_pest before calling _build_multiseason_stage2.
_PARENT_NAMESPACE: dict = {}


def _tmt_events_per_run(entries, _resolve_filex_path, _infer_excode, _read_harvest, _read_process):
    """Cross-FileX TMT resolver (mirrors build_pest._collect_tmt_events_per_run)."""
    events_by_run: dict[int, list] = {}
    points_by_run: dict[int, list] = {}
    tmt_cache = {}

    for entry in entries:
        run_no = int(entry["run"])
        tn = int(entry.get("tn", -99))
        filex = entry.get("filex")
        filex_path = (
            _resolve_filex_path(filex)
            or (filex if filex and os.path.isabs(filex) else None)
        )
        if not filex_path:
            raise FileNotFoundError(f"cannot resolve FileX for run {run_no}: {filex!r}")
        if filex_path not in tmt_cache:
            excode = _infer_excode(filex_path)
            tmt_path = os.path.join(
                os.path.dirname(os.path.abspath(filex_path)), f"{excode}.TMT"
            ) if excode else None
            tmt_cache[filex_path] = (_read_harvest(tmt_path), _read_process(tmt_path))
        ev_by_tn, pt_by_tn = tmt_cache[filex_path]
        events_by_run[run_no] = list(ev_by_tn.get(tn, []))
        points_by_run[run_no] = list(pt_by_tn.get(tn, []))
    return events_by_run, points_by_run


def build_multiseason_stage2(args, prefix, allowed, extra_allowed, params, model_cmd_extra, ctx: dict):
    """Build stage2 observations for multi-season joint calibration (T8 §4-§7).

    Parameters
    ----------
    ctx : dict
        Namespace providing functions from the parent ``build_pest`` module:
        ``_parse_batch_entries``, ``_build_evaluate_observations_from_filea``,
        ``_read_tmt_harvest_events``, ``_read_tmt_process_points``,
        ``_resolve_filex_path``, ``_infer_excode_from_filex``,
        ``PEST_EVAL_FILE``, ``PEST_JOINT_FILE``, ``PEST_HARVEST_FILE``,
        ``PEST_TMTGROW_FILE``, ``create_ins_and_pst_multi``,
        ``_write_run_manifest``, ``observation_policies``.
    """
    _parse_batch = ctx["_parse_batch_entries"]
    _build_eval = ctx["_build_evaluate_observations_from_filea"]
    _read_harvest = ctx["_read_tmt_harvest_events"]
    _read_process = ctx["_read_tmt_process_points"]
    _resolve_fx = ctx["_resolve_filex_path"]
    _infer_excode = ctx["_infer_excode_from_filex"]
    PEST_EVAL = ctx["PEST_EVAL_FILE"]
    PEST_JOINT = ctx["PEST_JOINT_FILE"]
    PEST_HARVEST = ctx["PEST_HARVEST_FILE"]
    PEST_TMTGROW = ctx["PEST_TMTGROW_FILE"]
    create_pst = ctx["create_ins_and_pst_multi"]
    write_manifest = ctx["_write_run_manifest"]
    observation_policies = ctx.get("observation_policies")

    design_path = Path(args.multiseason_design).expanduser().resolve()
    if not design_path.is_file():
        raise FileNotFoundError(f"Multi-season design not found: {design_path}")
    design = MultiSeasonDesign.load(design_path)
    seasons = design.calibration_seasons
    if len(seasons) < 2:
        raise ValueError("Multi-season calibration requires at least 2 calibration seasons")

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    global_run = 0
    run_mapping_rows = []
    all_eval_rows = []
    all_harvest_rows = []
    all_process_rows = []

    for season in seasons:
        bundle = season.bundle_absolute
        # Point USER_INPUT_DIR to this season's bundle.  Since build_pest.py
        # runs as __main__, its module-level functions (like _resolve_filex_path)
        # resolve USER_INPUT_DIR from __main__'s namespace, NOT from the
        # imported ``src.calibration.build_pest`` module.  We set both so
        # that both single-season (imported) and __main__-based lookups work.
        import sys
        main_mod = sys.modules.get("__main__")
        if main_mod is not None and hasattr(main_mod, "USER_INPUT_DIR"):
            main_mod.USER_INPUT_DIR = str(bundle)
        bp_mod = ctx.get("_bp_module")
        if bp_mod is not None:
            bp_mod.USER_INPUT_DIR = str(bundle)
        
        batch_file = bundle / "DSSBatch.v48"
        if not batch_file.is_file():
            raise FileNotFoundError(f"Season {season.season_id}: DSSBatch.v48 missing")
        entries = _parse_batch(str(batch_file))
        # Rewrite absolute FileX paths to bare names so _resolve_filex_path
        # looks them up in USER_INPUT_DIR (the season bundle).  The XXQL2502
        # batch ships with C:\DSSAT48\TOMATO\... absolute paths.
        for e in entries:
            raw = e.get("filex", "")
            if raw and os.path.isabs(str(raw)):
                e["filex"] = os.path.basename(str(raw))
        
        by_tn = {int(e.get("tn", -99)): e for e in entries}
        missing_tns = [tn for tn in season.treatments if tn not in by_tn]
        if missing_tns:
            raise ValueError(
                f"Season {season.season_id}: treatments absent from batch: {missing_tns}"
            )
        # DSSAT RUN is batch-row order.  The runtime writes a selected batch in
        # the design order, so the builder must use the identical local RUN map.
        entries = []
        for local_run, tn in enumerate(season.treatments, 1):
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
                "global_run": global_run, "season_id": season.season_id,
                "experiment_code": season.experiment_code,
                "treatment": tn, "local_run": lr,
            })

        sid = season.season_id
        eval_df = _build_eval(entries)
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
            entries, _resolve_fx, _infer_excode, _read_harvest, _read_process
        )
        for e in entries:
            lr = int(e["run"])
            gr = local_to_global.get(lr, lr)
            tn = int(e.get("tn", -99))
            for ev in events_by_run.get(lr, []):
                hv = getattr(args, "harvest_var", "CHPDT")
                obs_cum = ev.get("dry_cum", -99.0) if hv == "CHPDT" else ev.get("fresh_cum", -99.0)
                obs_inc = ev.get("dry_inc", -99.0) if hv == "CHPDT" else ev.get("fresh_inc", -99.0)
                all_harvest_rows.append({
                    "@RUN": gr, "TN": tn, "HNO": int(ev["hno"]),
                    "DATE": int(ev["date"]),
                    "PWADM": float(obs_cum), "PWAIM": float(obs_inc),
                    "PWADS": -99.0, "PWAIS": -99.0, "season": sid,
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
            med_cum = float(g["PWADM"].median())
            med_inc = float(g["PWAIM"].median())
            harvest_sigmas[f"PWADM_H{int(hno)}"] = float((s0**2 + (cv * abs(med_cum))**2)**0.5 * sf)
            harvest_sigmas[f"PWAIM_H{int(hno)}"] = float((s0**2 + (cv * abs(med_inc))**2)**0.5 * sf)

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
            "model_out_path": PEST_EVAL, "obs_bases": {"ADAP"},
            "critical_obs": {"ADAPM"},
            "group_sigmas": {"ADAPM": float(adapm_sigma)}, "df": df_eval,
        },
        {
            "model_out_path": PEST_JOINT,
            "obs_bases": {"HWAM", "LAIX", "CNAM", "CHTA", "CNAA", "PWAM", "H#AM", "HIAM"},
            "critical_obs": set(),
            "group_sigmas": {
                "HWAMM": float(getattr(args, "hwamm_sigma", 50.0)),
                "PWAMM": float(getattr(args, "pwamm_sigma", 20.0)),
                "LAIXM": float(getattr(args, "laixm_sigma", 0.8)),
                "CNAMM": float(getattr(args, "cnamm_sigma", 25.0)),
                "CHTAM": 15.0, "CNAAM": 20.0, "H#AMM": 50.0,
                "HIAMM": float(getattr(args, "hiamm_sigma", 0.10)),
            },
            "df": df_eval,
        },
        {
            "model_out_path": PEST_HARVEST, "obs_bases": {"PWAD", "PWAI"},
            "critical_obs": set(), "group_sigmas": harvest_sigmas, "df": df_harvest,
        },
        {
            "model_out_path": PEST_TMTGROW, "obs_bases": {"LAID", "LWAD", "SWAD"},
            "critical_obs": set(), "group_sigmas": process_sigmas, "df": df_process,
        },
    ]

    run_map_path = out_dir / f"{prefix}_run_mapping.csv"
    pd.DataFrame(run_mapping_rows).to_csv(run_map_path, index=False, encoding="utf-8-sig")
    print(f"run_mapping ({len(run_mapping_rows)} runs) -> {run_map_path}")

    model_cmd_extra = f"--batch DSSBatch.v48 --harvest-var {getattr(args, 'harvest_var', 'CHPDT')}"
    create_pst(
        params, prefix,
        noptmax=int(args.noptmax), ies_num_reals=int(args.ies_num_reals),
        random_seed=int(args.random_seed),
        outputs=stage2_outputs, evaluate_out_path=PEST_EVAL,
        model_cmd_extra=model_cmd_extra, out_dir=str(out_dir),
        weight_scheme=str(getattr(args, "weight_scheme", "raw")),
        observation_policies=observation_policies,
    )

    pst_path = out_dir / f"{prefix}.pst"
    if pst_path.is_file():
        pst = pyemu.Pst(str(pst_path))
        sched = str(PROJECT_ROOT / "src" / "calibration" / "run_multiseason.py").replace("\\", "/")
        design_path_fwd = str(design_path).replace("\\", "/")
        pst.model_command = [
            f'python "{sched}" --design "{design_path_fwd}" --param-csv {prefix}_params.csv'
            f' --harvest-var {getattr(args, "harvest_var", "CHPDT")}'
            f' --prefix {prefix}'
        ]
        pst.write(str(pst_path))

    # ── Apply T8 weight formula (§7.2) ──────────────────────────────────
    _apply_t8_weights(out_dir, prefix, design.group_policy)

    # ── Write observation_registry.csv ───────────────────────────────────
    _write_obs_registry(out_dir, prefix, run_mapping_rows)

    # ── Write group_weight_audit.csv ─────────────────────────────────────
    _write_group_weight_audit(out_dir, prefix, design.group_policy)

    finalize_ies = ctx.get("_finalize_ies_contract")
    ies_contract = {}
    if finalize_ies is not None:
        ies_contract = finalize_ies(
            pst_path,
            out_dir=str(out_dir),
            prefix=prefix,
            ies_num_reals=int(args.ies_num_reals),
            random_seed=int(args.random_seed),
            bad_phi_sigma=float(ctx.get("bad_phi_sigma", 1.0e300)),
            observation_noise=bool(observation_policies),
        )

    write_manifest(
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
        "LWADM": "BIOMASS", "SWADM": "BIOMASS", "CNAMM": "BIOMASS",
        "HWAMM": "BIOMASS", "HIAMM": "BIOMASS", "CWAMS": "BIOMASS",
        "PWADM": "CUMULATIVE_HARVEST", "PWAIM": "INCREMENTAL_HARVEST",
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


def _apply_t8_weights(out_dir, prefix, group_policy):
    """Rewrite PST weights using T8 §7.2 formula: weight = (1/sigma) × sqrt(budget/n_g)."""
    import csv, math

    pst_path = out_dir / f"{prefix}.pst"
    weights_path = out_dir / f"{prefix}.weights.audit.csv"
    if not pst_path.is_file() or not weights_path.is_file():
        return

    budgets = _load_group_budgets(group_policy)

    # Count non-zero-weight observations per group
    group_n = {}
    with weights_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            grp = (row.get("obgnme") or "").strip().lower()
            if float(row.get("weight", 0)) > 0:
                group_n[grp] = group_n.get(grp, 0) + 1

    # Compute per-group multipliers
    group_mult = {}
    for grp, n in group_n.items():
        family = _family_for_group(grp)
        budget = budgets[family]
        group_mult[grp] = math.sqrt(budget / max(n, 1))

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
        grp = str(obs.loc[obs.obsnme == obsnme, "obgnme"].iloc[0]).strip().lower() if obsnme in obs.obsnme.values else ""
        mult = group_mult.get(grp, 1.0)
        key = obsnme.strip().lower()
        new_weights.append(mult / sigma if active.get(key, False) and sigma > 0 else 0.0)

    obs["weight"] = new_weights
    pst.write(str(pst_path))

    # Keep the audit contract synchronized with the PST it describes.
    audit = pd.read_csv(weights_path, encoding="utf-8-sig")
    audit_key = audit["obsnme"].astype(str).str.lower()
    pst_weights = dict(zip(obs["obsnme"].astype(str).str.lower(), obs["weight"].astype(float)))
    audit["weight"] = [pst_weights.get(key, value) for key, value in zip(audit_key, audit["weight"])]
    audit["group_multiplier"] = [
        group_mult.get(str(group).strip().lower(), 1.0) for group in audit["obgnme"]
    ]
    audit.to_csv(weights_path, index=False, encoding="utf-8-sig")
    print(f"T8 weights applied ({len(group_mult)} groups × budget) -> {pst_path}")


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


def _write_group_weight_audit(out_dir, prefix, group_policy):
    """Write group_weight_audit.csv with T8 phi budgets."""
    import csv, math

    weights_path = out_dir / f"{prefix}.weights.audit.csv"
    if not weights_path.is_file():
        return

    # Compute per-group stats from weights audit
    groups = {}
    with weights_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            grp = row.get("obgnme", "")
            if grp not in groups:
                groups[grp] = {"n_obs": 0, "weights": [], "sigmas": []}
            w = float(row.get("weight", 0))
            s = float(row.get("sigma", 1))
            if w > 0:
                groups[grp]["n_obs"] += 1
                groups[grp]["weights"].append(w)
                groups[grp]["sigmas"].append(s)

    budgets = _load_group_budgets(group_policy)

    audit_path = out_dir / f"{prefix}_group_weight_audit.csv"
    with audit_path.open("w", encoding="utf-8-sig", newline="") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=[
            "group", "variable_family", "phi_budget", "n_obs",
            "mean_sigma_eff", "mean_weight", "weight_multiplier",
            "sigma_source", "note"
        ])
        writer.writeheader()
        for grp in sorted(groups):
            g = groups[grp]
            # Determine family from group name root (strip _H{N} and _D{DATE} suffixes)
            family = _family_for_group(grp)
            budget = budgets[family]
            mean_s = sum(g["sigmas"]) / max(len(g["sigmas"]), 1)
            mean_w = sum(g["weights"]) / max(len(g["weights"]), 1)
            # T8 weight formula: weight = (1/sigma) * sqrt(budget / n_obs)
            expected_mult = math.sqrt(budget / max(g["n_obs"], 1))
            actual_mult = mean_w * mean_s  # since weight = mult / sigma
            writer.writerow({
                "group": grp,
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
