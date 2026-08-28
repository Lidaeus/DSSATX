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
import datetime as dt
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pyemu

from src.calibration.build_pest import (
    PEST_EVAL_FILE,
    PEST_HARVEST_FILE,
    PEST_JOINT_FILE,
    PEST_N_RESPONSE_FILE,
    PEST_TMTGROW_FILE,
    PEST_W_RESPONSE_FILE,
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
from src.calibration.design_config import load_design_config
from src.calibration.nitrogen_response import (
    build_observed_n_response_rows,
    build_observed_water_response_rows,
    load_n_response_mapping,
)
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


def _iso_to_yyddd(value):
    try:
        day = dt.date.fromisoformat(str(value).strip()[:10])
        return int(f"{day.year % 100:02d}{day.timetuple().tm_yday:03d}")
    except (TypeError, ValueError):
        return -99


def _soil_rows_for_season(bundle: Path, season_id: str, entries, local_to_global):
    """Build one tagged PEST row per audited non-initial soil observation."""
    path = bundle / "soil_water_observations.csv"
    if not path.is_file():
        return [], {}
    rows = pd.read_csv(path, encoding="utf-8-sig")
    if rows.empty or "phi_role" not in rows.columns:
        return [], {}
    rows = rows[rows["phi_role"].astype(str).str.lower().eq("soil_water_phi")].copy()
    if rows.empty:
        return [], {}
    rows["date_code"] = rows["date"].map(_iso_to_yyddd)
    rows["trno"] = pd.to_numeric(rows["trno"], errors="coerce").astype("Int64")
    rows = rows[rows["date_code"] > 0].sort_values(["trno", "date_code", "depth_label"], kind="stable")
    local_by_tn = {int(e.get("tn", -99)): int(e["run"]) for e in entries}
    # Assign tokens after treatment selection.  Numbering the full source
    # table first leaves gaps (and can create a token with no matching sigma)
    # when a design uses a subset of treatments, as E01/T10 do.
    selected_rows = []
    for _, row in rows.iterrows():
        if int(row["trno"]) in local_by_tn:
            selected_rows.append(row)
    token_names = [f"SW{i:04d}M" for i in range(1, len(selected_rows) + 1)]
    all_rows = []
    sigmas = {}
    for token, row in zip(token_names, selected_rows):
        tn = int(row["trno"])
        local_run = local_by_tn[tn]
        obs = {"@RUN": int(local_to_global[local_run]), "TN": tn,
               "DATE": int(row["date_code"]), "season": season_id}
        for name in token_names:
            obs[name] = -99.0
        obs[token] = float(row["vwc_mean"])
        all_rows.append(obs)
        replicate_sd = float(row["vwc_sd"])
        n_replicates = int(row.get("n_rep", 1))
        if not replicate_sd > 0 or n_replicates < 1:
            raise ValueError(f"{season_id}: soil-water observation {token} has non-positive sigma")
        sigma = replicate_sd / math.sqrt(n_replicates)
        obs[f"{token}_SIGMA"] = sigma
        obs[f"{token}_SIGMA_SOURCE"] = (
            f"{row.get('vwc_sd_method', 'replicate_sd')}:sd/sqrt(n)"
        )
        obs[f"{token}_REPLICATE_SD"] = replicate_sd
        obs[f"{token}_N_REPLICATES"] = n_replicates
        sigmas[f"{token}_D{int(row['date_code'])}"] = sigma
    return all_rows, sigmas


def _load_crop_uncertainty(bundle: Path, season_id: str) -> pd.DataFrame:
    """Load and validate the per-observation replicate uncertainty contract."""
    path = bundle / "observation_uncertainty.csv"
    if not path.is_file():
        raise FileNotFoundError(
            f"{season_id}: observation_uncertainty.csv is required for formal E02"
        )
    frame = pd.read_csv(path, encoding="utf-8-sig")
    required = {"trno", "date", "variable", "value", "raw_sd", "n_rep", "sd_method"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(
            f"{season_id}: observation uncertainty missing columns {sorted(missing)}"
        )
    frame = frame.copy()
    frame["trno"] = pd.to_numeric(frame["trno"], errors="raise").astype(int)
    frame["date"] = pd.to_numeric(frame["date"], errors="raise").astype(int)
    frame["variable"] = frame["variable"].astype(str).str.upper()
    frame["value"] = pd.to_numeric(frame["value"], errors="raise")
    frame["raw_sd"] = pd.to_numeric(frame["raw_sd"], errors="raise")
    frame["n_rep"] = pd.to_numeric(frame["n_rep"], errors="raise").astype(int)
    # The table also carries derived season-end LWAM/SWAM rows whose SD is
    # inherited from the final process observation and whose n_rep is recorded
    # as zero.  They are not E02 targets.  Enforce n_rep >= 1 when a row is
    # actually attached below, while still rejecting impossible negative
    # counts at load time.
    if (frame["raw_sd"] <= 0).any() or (frame["n_rep"] < 0).any():
        bad = frame.loc[
            (frame["raw_sd"] <= 0) | (frame["n_rep"] < 0),
            ["trno", "date", "variable", "raw_sd", "n_rep"],
        ]
        raise ValueError(
            f"{season_id}: invalid replicate uncertainty rows: "
            f"{bad.head(5).to_dict('records')}"
        )
    duplicate = frame.duplicated(["trno", "date", "variable"], keep=False)
    if duplicate.any():
        raise ValueError(
            f"{season_id}: duplicate uncertainty keys: "
            f"{frame.loc[duplicate, ['trno', 'date', 'variable']].head(5).to_dict('records')}"
        )
    return frame


def _policy_component(policies, group: str, field: str, default: float = 0.0) -> float:
    policy = policies.get(str(group).upper(), {}) if policies else {}
    value = policy.get(field)
    if value is None or str(value).strip() == "":
        return float(default)
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"{group}: {field} must be finite and non-negative")
    return parsed


def _attach_measured_sigma(
    record: dict,
    uncertainty: pd.DataFrame,
    *,
    tn: int,
    date: int | None,
    obs_col: str,
    source_variable: str,
    policies,
) -> None:
    """Attach SD/sqrt(n) plus static model/floor uncertainty to one observation."""
    variable = str(source_variable).upper()
    candidates = uncertainty[
        uncertainty["trno"].eq(int(tn))
        & uncertainty["variable"].eq(variable)
    ]
    if date is not None:
        candidates = candidates[candidates["date"].eq(int(date))]
    if len(candidates) != 1:
        raise ValueError(
            f"uncertainty lookup must resolve exactly once for "
            f"TN={tn}, DATE={date}, variable={variable}; found {len(candidates)}"
        )
    row = candidates.iloc[0]
    observed = float(record[obs_col])
    source_value = float(row["value"])
    # FileA/FileT stores dry masses and cumulative harvests as whole numbers;
    # allow only the documented half-unit serialization loss.  Continuous
    # canopy variables retain three decimals.
    integer_serialized = {
        "LWADM", "SWADM", "CHFPWM", "CHPDTM", "HPODWM",
    }
    tolerance = (
        0.501
        if obs_col in integer_serialized
        else max(0.002, abs(source_value) * 1.0e-4)
    )
    if not math.isclose(observed, source_value, rel_tol=0.0, abs_tol=tolerance):
        raise ValueError(
            f"{obs_col}: FileA/FileT value {observed} disagrees with uncertainty "
            f"value {source_value} for TN={tn}, DATE={date}"
        )
    replicate_sd = float(row["raw_sd"])
    n_replicates = int(row["n_rep"])
    if n_replicates < 1:
        raise ValueError(
            f"{obs_col}: measured target requires n_rep >= 1 for "
            f"TN={tn}, DATE={date}"
        )
    n_effective = _policy_component(
        policies, obs_col, "n_eff", default=float(n_replicates)
    )
    if n_effective <= 0:
        raise ValueError(f"{obs_col}: n_eff must be positive")
    model_sigma = _policy_component(policies, obs_col, "model_sigma")
    sigma_floor = _policy_component(policies, obs_col, "sigma_floor")
    sigma = math.sqrt(
        replicate_sd**2 / n_effective + model_sigma**2 + sigma_floor**2
    )
    record[f"{obs_col}_SIGMA"] = sigma
    record[f"{obs_col}_SIGMA_SOURCE"] = (
        f"{row['sd_method']}:sd/sqrt(n)+static_model+floor"
    )
    record[f"{obs_col}_REPLICATE_SD"] = replicate_sd
    record[f"{obs_col}_N_REPLICATES"] = n_replicates


def _mask_disabled_harvest_objective(df_harvest: pd.DataFrame) -> None:
    """Remove ordinary dry-harvest observations from a disabled stage.

    The shared observation policy cannot express stage-local activation, so
    disabled stages mark the corresponding measured tokens missing before the
    PST is written.  Fresh yield remains available as a zero-weight diagnostic.
    """
    for column in ("CHPDTM", "CHPDTM_T", "HPODWM"):
        if column in df_harvest.columns:
            df_harvest[column] = -99.0


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
    all_soil_rows = []
    soil_sigmas = {}

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
        crop_uncertainty = _load_crop_uncertainty(sctx.input_dir, sid)
        eval_df = _build_evaluate_observations_from_filea(entries, input_dir=str(sctx.input_dir))
        for _, row_ in eval_df.iterrows():
            lr = int(row_.get("@RUN", row_.get("RUN", 0)))
            gr = local_to_global.get(lr, lr)
            tn = int(row_.get("TN", -99))
            record = {"@RUN": gr, "TN": tn, "season": sid}
            for col in eval_df.columns:
                if col in ("@RUN", "RUN", "TN", "season"):
                    continue
                record[col] = row_[col]
            for obs_col, source_variable in {
                "PDAPM": "PDAT",
                "ADAPM": "ADAT",
                "MDAPM": "MDAT",
                "LAIXM": "LAIX",
                "CNAMM": "CNAM",
            }.items():
                if (
                    obs_col in record
                    and pd.notna(record[obs_col])
                    and float(record[obs_col]) != -99.0
                ):
                    _attach_measured_sigma(
                        record,
                        crop_uncertainty,
                        tn=tn,
                        date=None,
                        obs_col=obs_col,
                        source_variable=source_variable,
                        policies=observation_policies,
                    )
            all_eval_rows.append(record)

        events_by_run, points_by_run = _tmt_events_per_run(
            entries, input_dir=str(sctx.input_dir)
        )
        for e in entries:
            lr = int(e["run"])
            gr = local_to_global.get(lr, lr)
            tn = int(e.get("tn", -99))
            for ev in events_by_run.get(lr, []):
                # Formal E02 retains cumulative fresh/dry series and the
                # measured single-harvest dry series.  Policy activates CHPDT
                # + HPODW and keeps CHFPW diagnostic-only.
                chfpw_val = float(ev.get("chfpw", -99.0))
                chpdt_val = float(ev.get("chpdt", -99.0))
                hpodw_val = float(ev.get("hpodw", ev.get("dry_inc", -99.0)))
                record = {
                    "@RUN": gr, "TN": tn, "HNO": int(ev["hno"]),
                    "DATE": int(ev["date"]),
                    "CHFPWM": chfpw_val, "CHPDTM": chpdt_val, "HPODWM": hpodw_val,
                    "CHFPWS": -99.0, "CHPDTS": -99.0, "HPODWS": -99.0, "season": sid,
                }
                for obs_col, source_variable in {
                    "CHFPWM": "CHFPW",
                    "CHPDTM": "CHPDT",
                    "HPODWM": "HPODW",
                }.items():
                    if float(record[obs_col]) != -99.0:
                        _attach_measured_sigma(
                            record,
                            crop_uncertainty,
                            tn=tn,
                            date=int(ev["date"]),
                            obs_col=obs_col,
                            source_variable=source_variable,
                            policies=observation_policies,
                        )
                all_harvest_rows.append(record)
            for p in points_by_run.get(lr, []):
                record = {
                    "@RUN": gr, "TN": tn, "DATE": int(p["date"]),
                    "LAIDM": float(p["laid"]), "LWADM": float(p["lwad"]),
                    "SWADM": float(p["swad"]),
                    "CHTDM": float(p.get("chtd", -99.0)),
                    "LAIDS": -99.0, "LWADS": -99.0, "SWADS": -99.0, "season": sid,
                    "CHTDS": -99.0,
                }
                for obs_col, source_variable in {
                    "LAIDM": "LAID",
                    "LWADM": "LWAD",
                    "SWADM": "SWAD",
                    "CHTDM": "CHTD",
                }.items():
                    if float(record[obs_col]) != -99.0:
                        _attach_measured_sigma(
                            record,
                            crop_uncertainty,
                            tn=tn,
                            date=int(p["date"]),
                            obs_col=obs_col,
                            source_variable=source_variable,
                            policies=observation_policies,
                        )
                all_process_rows.append(record)
        soil_rows, local_soil_sigmas = _soil_rows_for_season(
            sctx.input_dir, sid, entries, local_to_global
        )
        all_soil_rows.extend(soil_rows)
        soil_sigmas.update(local_soil_sigmas)

    df_eval = pd.DataFrame(all_eval_rows)
    df_harvest = pd.DataFrame(all_harvest_rows)
    df_process = pd.DataFrame(all_process_rows)
    df_soil = pd.DataFrame(all_soil_rows)
    # N-response contrasts are built from the complete observed cumulative
    # harvest series even though the ordinary CHPDT calibration target below
    # is terminal-only.
    nresp_harvest_df = df_harvest.copy()

    # Calibrate continuous process states as signed inter-observation
    # increments plus one terminal state per treatment.  The runner emits the
    # matching LAIDDS/LAIETS, LWADDS/LWETS and SWADDS/SWETS tokens.
    process_objective = design.process_state_objective or {}
    if bool(process_objective.get("enabled", False)) and not df_process.empty:
        derived_rows = []
        for _, group in df_process.groupby("@RUN", sort=False):
            group = group.sort_values("DATE")
            # B2 fix: track previous valid value per variable independently.
            # When a row has LAI=-99 but LWAD/SWAD present, the last valid LAI
            # must be retained for the next LAI increment, not overwritten.
            previous_valid = {"LAIDM": -99.0, "LWADM": -99.0, "SWADM": -99.0}
            previous_valid_date = {"LAIDM": None, "LWADM": None, "SWADM": None}
            terminal_index = {}
            for variable in ("LAIDM", "LWADM", "SWADM"):
                valid = group.loc[group[variable].astype(float).ne(-99.0)]
                terminal_index[variable] = valid.index[-1] if not valid.empty else None
            for idx, row in group.iterrows():
                out = row.to_dict()
                for variable, diff_name, terminal_name in (
                    ("LAIDM", "LAIDDM", "LAIETM"),
                    ("LWADM", "LWADDM", "LWETM"),
                    ("SWADM", "SWADDM", "SWETM"),
                ):
                    value = float(row.get(variable, -99.0))
                    prev_value = previous_valid[variable]
                    out[diff_name] = (
                        value - prev_value
                        if value != -99.0 and prev_value != -99.0 else -99.0
                    )
                    out[f"{diff_name}_prev_date"] = (
                        previous_valid_date[variable]
                        if value != -99.0 and prev_value != -99.0 else None
                    )
                    out[terminal_name] = (
                        value if idx == terminal_index[variable] else -99.0
                    )
                    # Update per-variable previous only when current is valid
                    if value != -99.0:
                        previous_valid[variable] = value
                        previous_valid_date[variable] = int(row.get("DATE", -99))
                derived_rows.append(out)
        df_process = pd.DataFrame(derived_rows)

    # CHPDT is a cumulative yield anchor at the terminal harvest only.  Event
    # increments remain represented by HPODW.  Intermediate CHPDT rows are
    # moved to the separate CHPDTM_T column (HARVEST_DRY_TREND family, log
    # transformed in the observation policy) so the early-season cumulative
    # shape contributes to Phi at a relative-error scale; the terminal CHPDTM
    # stays the raw absolute-yield anchor.
    harvest_objective = design.harvest_dry_objective or {}
    harvest_enabled = bool(harvest_objective.get("enabled", False))
    if harvest_enabled and not df_harvest.empty:
        if "CHPDTM_T" not in df_harvest.columns:
            df_harvest["CHPDTM_T"] = -99.0
        for _, indices in df_harvest.groupby("@RUN", sort=False).groups.items():
            indices = list(indices)
            if indices:
                terminal_idx = df_harvest.loc[indices].sort_values("HNO").index[-1]
                nonterminal = [idx for idx in indices if idx != terminal_idx]
                if nonterminal:
                    # intermediate cumulative dry harvest -> trend family
                    df_harvest.loc[nonterminal, "CHPDTM_T"] = df_harvest.loc[nonterminal, "CHPDTM"]
                    df_harvest.loc[nonterminal, "CHPDTM"] = -99.0
    elif not df_harvest.empty:
        # The observation policy is shared by all stages and marks CHPDT/HPODW
        # as calibration observations.  A stage-level disabled objective must
        # therefore remove those measured tokens before PST construction;
        # otherwise the shared policy silently reactivates harvest Phi (as it
        # did in the S1 canopy pre-calibration).  ``nresp_harvest_df`` was
        # copied above, so N/W response contrasts can still be enabled without
        # also enabling the ordinary harvest objective.
        _mask_disabled_harvest_objective(df_harvest)

    adapm_sigma = float(getattr(args, "adapm_sigma", None) or 25.0)
    harvest_sigmas = {}
    if not df_harvest.empty:
        s0 = float(getattr(args, "pwadm_sigma0", 250.0))
        cv = float(getattr(args, "pwadm_cv", 0.08))
        sf = float(getattr(args, "pwadm_sigma_factor", 1.0))
        for hno, g in df_harvest.groupby("HNO"):
            # T10 direct harvest: CHFPW, CHPDT and the log-transformed trend
            # series get their own sigma keys.  CHPDTM_T expresses a relative
            # (log-domain ~20%) residual: raw_sigma = 0.2 * median value, so
            # the delta-method propagation yields a stable log-scale sigma.
            for var in ("CHFPWM", "CHPDTM", "HPODWM"):
                med = float(g[var].median()) if var in g.columns else 0.0
                harvest_sigmas[f"{var}_H{int(hno)}"] = float((s0**2 + (cv * abs(med))**2)**0.5 * sf)
            if "CHPDTM_T" in g.columns:
                # Terminal rows keep CHPDTM_T = -99 (invalid); including them in
                # the median pollutes raw_sigma for HNO groups where most runs
                # terminate at that harvest (e.g. 25SP H5: 9/10 runs terminal),
                # shrinking sigma ~20x and exploding the T8 weight to dominate
                # the whole Phi budget.  Only valid observations enter the
                # median.
                valid_t = g.loc[g["CHPDTM_T"] != -99.0, "CHPDTM_T"]
                med_t = float(valid_t.median()) if (not valid_t.empty and pd.notna(valid_t.median())) else 0.0
                harvest_sigmas[f"CHPDTM_T_H{int(hno)}"] = float(0.2 * abs(med_t))

    process_sigmas = {}
    if not df_process.empty:
        laidm_sf = float(getattr(args, "laidm_sigma_factor", 1.0))
        lwadm_sf = float(getattr(args, "lwadm_sigma_factor", 1.0))
        swadm_sf = float(getattr(args, "swadm_sigma_factor", 1.0))
        for var, s0, cv in [
            ("LAIDM", 1.6, 0.50), ("LWADM", 80.0, 0.25), ("SWADM", 100.0, 0.25),
            ("CHTDM", 2.0, 0.15),
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

        if bool((design.process_state_objective or {}).get("enabled", False)):
            # Derived differences/terminal states use explicit native-scale
            # sigma floors; T10 later allocates the declared family budget.
            for var, sigma in (
                ("LAIDDM", 0.5), ("LAIETM", 0.2),
                ("LWADDM", 20.0), ("LWETM", 20.0),
                ("SWADDM", 25.0), ("SWETM", 25.0),
            ):
                for date in sorted(df_process["DATE"].dropna().unique()):
                    process_sigmas[f"{var}_D{int(date)}"] = float(sigma)

    n_response = design.nitrogen_response_objective or {}
    nresp_df = None
    if bool(n_response.get("enabled", False)):
        mapping_path = Path(str(n_response["mapping_csv"]))
        if not mapping_path.is_absolute():
            mapping_path = (PROJECT_ROOT / mapping_path).resolve()
        mapping = load_n_response_mapping(
            mapping_path,
            run_mapping_rows,
            response_levels=n_response.get("levels", ["N1", "N2", "N3"]),
        )
        nresp_df = build_observed_n_response_rows(
            nresp_harvest_df,
            mapping,
            sigma_floor=float(n_response.get("sigma_floor", 0.10)),
            response_target=str(n_response.get("response_target", "observed_shape")),
            response_levels=n_response.get("levels", ["N1", "N2", "N3"]),
            contrast_scale=str(n_response.get("contrast_scale", "log_ratio")),
            harvest_scope=str(n_response.get("harvest_scope", "all")),
        )

    water_response = design.water_response_objective or {}
    wresp_df = None
    if bool(water_response.get("enabled", False)):
        mapping_path = Path(str(water_response["mapping_csv"]))
        if not mapping_path.is_absolute():
            mapping_path = (PROJECT_ROOT / mapping_path).resolve()
        mapping = load_n_response_mapping(
            mapping_path,
            run_mapping_rows,
            response_levels=water_response.get("levels", ["N1", "N2", "N3"]),
        )
        wresp_df = build_observed_water_response_rows(
            nresp_harvest_df,
            mapping,
            sigma_floor=float(water_response.get("sigma_floor", 0.10)),
            response_target=str(water_response.get("response_target", "observed_shape")),
            contrast_scale=str(water_response.get("contrast_scale", "raw_difference")),
            harvest_scope=str(water_response.get("harvest_scope", "all")),
            high_water=str(water_response.get("high_water", "W3")),
            low_water=str(water_response.get("low_water", "W1")),
            season_contrasts=water_response.get("season_contrasts"),
            nitrogen_levels=water_response.get(
                "nitrogen_levels", ["N0", "N1", "N2", "N3"]
            ),
        )

    stage2_outputs = [
        {
            "model_out_path": PEST_EVAL_FILE, "obs_bases": {"PDAP", "ADAP", "MDAP"},
            "critical_obs": {"ADAPM"},
            "group_sigmas": {"PDAPM": 1.0, "ADAPM": float(adapm_sigma), "MDAPM": float(adapm_sigma)}, "df": df_eval,
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
            "model_out_path": PEST_HARVEST_FILE, "obs_bases": {"CHPDT", "CHPDT_T", "HPODW", "CHFPW"},
            "critical_obs": set(), "group_sigmas": harvest_sigmas, "df": df_harvest,
        },
        {
            "model_out_path": PEST_TMTGROW_FILE, "obs_bases": None,
            "critical_obs": set(), "group_sigmas": process_sigmas, "df": df_process,
        },
    ]
    if not df_soil.empty:
        stage2_outputs.append({
            "model_out_path": "PestSoilWat.OUT", "obs_bases": None,
            "critical_obs": set(), "group_sigmas": soil_sigmas, "df": df_soil,
        })
    if nresp_df is not None and not nresp_df.empty:
        stage2_outputs.append({
            "model_out_path": PEST_N_RESPONSE_FILE,
            "obs_bases": {"NRESP"},
            "critical_obs": set(),
            "group_sigmas": {},
            "df": nresp_df,
        })
    if wresp_df is not None and not wresp_df.empty:
        stage2_outputs.append({
            "model_out_path": PEST_W_RESPONSE_FILE,
            "obs_bases": {"WRESP"},
            "critical_obs": set(),
            "group_sigmas": {},
            "df": wresp_df,
        })

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
    _apply_t8_weights(
        out_dir,
        prefix,
        design.group_policy,
        run_mapping_rows,
        nse_objectives={
            "N_RESPONSE": n_response,
            "W_RESPONSE": water_response,
            "HARVEST_DRY_TOTAL": harvest_objective,
        },
    )

    # ── Write observation_registry.csv ───────────────────────────────────
    _write_obs_registry(out_dir, prefix, run_mapping_rows)

    # ── Write group_weight_audit.csv ─────────────────────────────────────
    _write_group_weight_audit(
        out_dir,
        prefix,
        design.group_policy,
        run_mapping_rows,
        nse_objectives={
            "N_RESPONSE": n_response,
            "W_RESPONSE": water_response,
            "HARVEST_DRY_TOTAL": harvest_objective,
        },
    )

    ies_contract = _finalize_ies_contract(
        pst_path,
        out_dir=str(out_dir),
        prefix=prefix,
        ies_num_reals=int(args.ies_num_reals),
        random_seed=int(args.random_seed),
        bad_phi_sigma=float(getattr(args, "bad_phi_sigma", None) or 1.0e300),
        observation_noise=bool(observation_policies),
    )

    staged_fields = {}
    # ``build_pest`` validates the stage before entering this module, but the
    # multiseason writer historically dropped that provenance when it rewrote
    # run_manifest.yaml.  Preserve the design-stage contract so a downstream
    # S2/S3 --fixed-from gate can verify its immediate predecessor.
    if getattr(args, "design_config", None) and getattr(args, "stage", None):
        stage_spec = load_design_config(args.design_config, args.stage)
        staged_fields = {
            "design_table_id": stage_spec.design_table_id,
            "design_stage": stage_spec.stage,
            "active_params": list(stage_spec.active_params),
            "validation_split_id": stage_spec.validation_split_id,
            "calibration_treatments": sorted(stage_spec.calibration_treatments),
            "validation_treatments": sorted(stage_spec.validation_treatments),
            "diagnostic_treatments": sorted(stage_spec.diagnostic_treatments),
            "approval_scope": stage_spec.approval_scope,
        }
    _write_run_manifest(
        str(out_dir), run_id=prefix, run_type="multiseason_calibration",
        crop="eggplant", mode="eggplant_stage2_multiseason",
        design_config=str(design_path), design_id=design.design_id,
        bad_phi_sigma=ies_contract.get("bad_phi_sigma", ""),
        observation_ensemble=ies_contract.get("observation_ensemble", ""),
        **staged_fields,
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
        "PDAPM": "PHENO", "PDAPS": "PHENO",
        "ADAPM": "PHENO", "ADAPS": "PHENO",
        "MDAPM": "PHENO", "MDAPS": "PHENO",
        "LAIXM": "CANOPY", "LAIDM": "CANOPY", "LAIXS": "CANOPY",
        "LAIDDM": "CANOPY_INCREMENT", "LAIDDS": "CANOPY_INCREMENT",
        "LAIETM": "CANOPY_TERMINAL", "LAIETS": "CANOPY_TERMINAL",
        "CHTDM": "CANOPY", "CHTDS": "CANOPY",
        "LWADM": "BIOMASS", "SWADM": "BIOMASS",
        "LWADDM": "BIOMASS_INCREMENT", "SWADDM": "BIOMASS_INCREMENT",
        "LWETM": "BIOMASS_TERMINAL", "SWETM": "BIOMASS_TERMINAL",
        "CNAMM": "PLANT_N",
        "HIAMM": "BIOMASS", "CWAMS": "BIOMASS",
        "PWADM": "CUMULATIVE_HARVEST", "PWAIM": "INCREMENTAL_HARVEST",
        # T10 direct harvest variables.  Cumulative terminal dry harvest and
        # event dry-harvest increments have separate audited budgets; keeping
        # them in one family silently applied a missing/incorrect budget.
        "CHFPWM": "HARVEST_FRESH", "CHFPWS": "HARVEST_FRESH",
        "CHPDTM": "HARVEST_DRY_TOTAL", "CHPDTS": "HARVEST_DRY_TOTAL",
        "CHPDTM_T": "HARVEST_DRY_TREND", "CHPDTS_T": "HARVEST_DRY_TREND",
        "HPODWM": "HARVEST_DRY_INCREMENT", "HPODWS": "HARVEST_DRY_INCREMENT",
        "NRESPM": "N_RESPONSE", "NRESPS": "N_RESPONSE",
        "WRESPM": "W_RESPONSE", "WRESPS": "W_RESPONSE",
    }
    for key, family in family_map.items():
        if root.startswith(key):
            return family
    if root.startswith("SW") or root.startswith("SOILW"):
        return "SOIL_WATER"
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


def _objective_weight_spec(objectives, family):
    """Return the configured direct metric weighting for one objective family."""
    spec = (objectives or {}).get(str(family).upper()) or {}
    mode = str(
        spec.get("terminal_weighting", spec.get("weighting", spec.get("objective_scale", "static")))
    ).strip().lower()
    if mode not in {"static", "nse", "season_nse", "rrmse", "season_rrmse"}:
        raise ValueError(
            f"{family}: weighting must be static, nse, or rrmse, got {mode!r}"
        )
    if mode == "static":
        return mode, None, spec
    key = "rrmse_lambda" if "rrmse" in mode else "nse_lambda"
    value = spec.get(key, spec.get("lambda_per_season"))
    if value is None or float(value) <= 0:
        raise ValueError(f"{family}: {mode} weighting requires positive {key}")
    return mode, float(value), spec


def _response_nse_lambda(nse_objectives, family):
    """Backward-compatible NSE-lambda accessor used by audit callers."""
    mode, value, _ = _objective_weight_spec(nse_objectives, family)
    return value if "nse" in mode else None


def _objective_bucket(obsnme, family, run_rows, objective_specs):
    """Partition metric objectives by season and, when requested, response stratum."""
    run_seasons = {int(row["global_run"]): str(row["season_id"]) for row in run_rows}
    season = _season_for_obsnme(obsnme, run_seasons)
    _, _, spec = _objective_weight_spec(objective_specs, family)
    scope = str(spec.get("sst_scope", "season_x_family")).strip().lower()
    if family not in {"N_RESPONSE", "W_RESPONSE"} or scope in {"", "season_x_family"}:
        return season, family
    if scope not in {
        "season_x_response_stratum", "season_x_family_x_stratum",
        "season_x_water_stratum", "season_x_nitrogen_stratum",
    }:
        raise ValueError(f"{family}: unsupported SST scope {scope!r}")

    import re
    match = re.search(r"_R(\d+)(?:_|$)", str(obsnme), flags=re.IGNORECASE)
    if match is None:
        raise ValueError(f"cannot assign response stratum: {obsnme!r}")
    global_run = int(match.group(1))
    run = next((row for row in run_rows if int(row["global_run"]) == global_run), None)
    if run is None:
        raise ValueError(f"response run is absent from run mapping: {obsnme!r}")
    mapping_path = Path(str(spec.get("mapping_csv", "")))
    if not mapping_path.is_absolute():
        mapping_path = (PROJECT_ROOT / mapping_path).resolve()
    mapping = pd.read_csv(mapping_path)
    selected = mapping.loc[
        mapping["season_id"].astype(str).eq(str(run["season_id"]))
        & pd.to_numeric(mapping["treatment"], errors="coerce").eq(int(run["treatment"]))
    ]
    if len(selected) != 1:
        raise ValueError(f"cannot resolve unique response stratum for {obsnme!r}")
    field = "water_level" if family == "N_RESPONSE" else "nitrogen_level"
    return season, family, str(selected.iloc[0][field]).upper()


def _apply_t8_weights(out_dir, prefix, group_policy, run_mapping_rows, *, nse_objectives=None):
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
                family = _family_for_group(grp)
                bucket = _objective_bucket(obsnme, family, run_mapping_rows, nse_objectives)
                obs_bucket[obsnme] = bucket
                bucket_n[bucket] = bucket_n.get(bucket, 0) + 1

    bucket_mult = {}
    bucket_nse_weight = {}
    bucket_sst = {}
    bucket_lambda = {}
    bucket_rrmse_mean = {}
    bucket_mode = {}
    for bucket, n in bucket_n.items():
        season, family = bucket[:2]
        mode, metric_lambda, _ = _objective_weight_spec(nse_objectives, family)
        bucket_mode[bucket] = mode
        if "nse" in mode:
            raw_values = [
                float(row.get("raw_obsval", row.get("obsval", "nan")))
                for row in csv.DictReader(
                    weights_path.open("r", encoding="utf-8-sig", newline="")
                )
                if float(row.get("weight", 0)) > 0
                and obs_bucket.get((row.get("obsnme") or "").strip().lower()) == bucket
            ]
            values = [value for value in raw_values if math.isfinite(value)]
            if len(values) != n:
                raise ValueError(
                    f"{season}:{family}: expected {n} finite raw observations for NSE, got {len(values)}"
                )
            sst = float(sum((value - (sum(values) / len(values))) ** 2 for value in values))
            if not sst > 0:
                raise ValueError(f"{season}:{family}: NSE SST must be positive")
            bucket_sst[bucket] = sst
            bucket_lambda[bucket] = metric_lambda
            bucket_nse_weight[bucket] = math.sqrt(metric_lambda / sst)
            bucket_mult[bucket] = bucket_nse_weight[bucket]
        elif "rrmse" in mode:
            raw_values = [
                abs(float(row.get("raw_obsval", row.get("obsval", "nan"))))
                for row in csv.DictReader(
                    weights_path.open("r", encoding="utf-8-sig", newline="")
                )
                if float(row.get("weight", 0)) > 0
                and obs_bucket.get((row.get("obsnme") or "").strip().lower()) == bucket
            ]
            values = [value for value in raw_values if math.isfinite(value)]
            mean_abs = sum(values) / len(values) if values else 0.0
            if not mean_abs > 0:
                raise ValueError(f"{season}:{family}: RRMSE mean(|obs|) must be positive")
            bucket_lambda[bucket] = metric_lambda
            bucket_rrmse_mean[bucket] = mean_abs
            bucket_mult[bucket] = math.sqrt(metric_lambda / n) / mean_abs
        else:
            bucket_mult[bucket] = math.sqrt(budgets[family] / max(n, 1))

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
        bucket = obs_bucket.get(key)
        if not active.get(key, False) or sigma <= 0:
            new_weights.append(0.0)
        elif bucket in bucket_nse_weight:
            new_weights.append(bucket_nse_weight[bucket])
        elif bucket in bucket_rrmse_mean:
            new_weights.append(bucket_mult[bucket])
        else:
            mult = bucket_mult.get(bucket, 1.0)
            new_weights.append(mult / sigma)

    obs["weight"] = new_weights
    pst.write(str(pst_path))

    # Keep the audit contract synchronized with the PST it describes.
    audit = pd.read_csv(weights_path, encoding="utf-8-sig")
    audit_key = audit["obsnme"].astype(str).str.lower()
    pst_weights = dict(zip(obs["obsnme"].astype(str).str.lower(), obs["weight"].astype(float)))
    audit["weight"] = [pst_weights.get(key, value) for key, value in zip(audit_key, audit["weight"])]
    audit["group_multiplier"] = [
        (
            bucket_nse_weight[obs_bucket[key]] * sigmas[key]
            if obs_bucket.get(key) in bucket_nse_weight
            else bucket_mult.get(obs_bucket.get(key), 1.0)
        )
        for key in audit_key
    ]
    audit["weight_mode"] = [
        bucket_mode.get(obs_bucket.get(key), "static")
        for key in audit_key
    ]
    audit["nse_lambda"] = [
        bucket_lambda.get(obs_bucket.get(key), "")
        if "nse" in bucket_mode.get(obs_bucket.get(key), "") else ""
        for key in audit_key
    ]
    audit["nse_sst"] = [
        bucket_sst.get(obs_bucket.get(key), "") for key in audit_key
    ]
    audit["rrmse_lambda"] = [
        bucket_lambda.get(obs_bucket.get(key), "")
        if "rrmse" in bucket_mode.get(obs_bucket.get(key), "") else ""
        for key in audit_key
    ]
    audit["rrmse_mean_abs_obs"] = [
        bucket_rrmse_mean.get(obs_bucket.get(key), "") for key in audit_key
    ]
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


def _write_group_weight_audit(out_dir, prefix, group_policy, run_mapping_rows, *, nse_objectives=None):
    """Write group_weight_audit.csv with T8 phi budgets."""
    import csv, math

    weights_path = out_dir / f"{prefix}.weights.audit.csv"
    if not weights_path.is_file():
        return

    run_seasons = {int(row["global_run"]): str(row["season_id"]) for row in run_mapping_rows}
    # Compute the exact family-season partitions used by _apply_t8_weights.
    groups = {}
    obs_bucket = {}
    with weights_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            obsnme = (row.get("obsnme") or row.get("\ufeffobsnme") or "").strip()
            family = _family_for_group(row.get("obgnme", ""))
            bucket = _objective_bucket(obsnme, family, run_mapping_rows, nse_objectives)
            obs_bucket[obsnme.lower()] = bucket
            if bucket not in groups:
                groups[bucket] = {"n_obs": 0, "weights": [], "sigmas": [], "raw_values": []}
            w = float(row.get("weight", 0))
            s = float(row.get("sigma", 1))
            if w > 0:
                groups[bucket]["n_obs"] += 1
                groups[bucket]["weights"].append(w)
                groups[bucket]["sigmas"].append(s)
                raw = float(row.get("raw_obsval", row.get("obsval", "nan")))
                if math.isfinite(raw):
                    groups[bucket]["raw_values"].append(raw)

    budgets = _load_group_budgets(group_policy)

    audit_path = out_dir / f"{prefix}_group_weight_audit.csv"
    with audit_path.open("w", encoding="utf-8-sig", newline="") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=[
            "group", "season_id", "variable_family", "phi_budget", "n_obs",
            "mean_sigma_eff", "mean_weight", "weight_multiplier",
            "weight_mode", "nse_lambda", "nse_sst", "rrmse_lambda",
            "rrmse_mean_abs_obs", "sigma_source", "note"
        ])
        writer.writeheader()
        for bucket in sorted(groups):
            season, family = bucket[:2]
            stratum = bucket[2] if len(bucket) > 2 else ""
            g = groups[bucket]
            budget = budgets.get(family, 1.0)
            mean_s = sum(g["sigmas"]) / max(len(g["sigmas"]), 1)
            mean_w = sum(g["weights"]) / max(len(g["weights"]), 1)
            # T10 family-season allocation: weight = (1/sigma) * sqrt(budget / n_obs)
            expected_mult = (
                math.sqrt(budget / g["n_obs"]) if g["n_obs"] > 0 else 0.0
            )
            actual_mult = mean_w * mean_s  # since weight = mult / sigma
            mode, metric_lambda, _ = _objective_weight_spec(nse_objectives, family)
            nse_lambda = metric_lambda if "nse" in mode else None
            finite_values = g["raw_values"]
            sst = float(sum((value - (sum(finite_values) / len(finite_values))) ** 2 for value in finite_values)) if finite_values else 0.0
            nse_weight = math.sqrt(nse_lambda / sst) if nse_lambda is not None and sst > 0 else None
            rrmse_mean = (
                sum(abs(value) for value in finite_values) / len(finite_values)
                if "rrmse" in mode and finite_values else None
            )
            rrmse_weight = (
                math.sqrt(metric_lambda / g["n_obs"]) / rrmse_mean
                if rrmse_mean and g["n_obs"] > 0 else None
            )
            writer.writerow({
                "group": f"{season}:{family}" + (f":{stratum}" if stratum else ""),
                "season_id": season,
                "variable_family": family,
                "phi_budget": budget,
                "n_obs": g["n_obs"],
                "mean_sigma_eff": round(mean_s, 4),
                "mean_weight": round(mean_w, 6),
                "weight_multiplier": round(
                    nse_weight if nse_weight is not None
                    else (rrmse_weight if rrmse_weight is not None else expected_mult), 6
                ),
                "weight_mode": mode,
                "nse_lambda": nse_lambda if nse_lambda is not None else "",
                "nse_sst": sst if nse_weight is not None else "",
                "rrmse_lambda": metric_lambda if "rrmse" in mode else "",
                "rrmse_mean_abs_obs": rrmse_mean if rrmse_mean is not None else "",
                "sigma_source": "assumed",
                "note": (
                    f"T8 §7.2: sqrt({budget}/{g['n_obs']}) = {expected_mult:.4f}"
                    if g["n_obs"] > 0
                    else "inactive diagnostic family; no positive-weight observations"
                ),
            })
    print(f"group_weight_audit ({len(groups)} groups) -> {audit_path}")
