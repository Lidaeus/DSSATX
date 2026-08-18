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
    PEST_N_RESPONSE_FILE,
    PEST_JOINT_FILE,
    PEST_TMTGROW_FILE,
    _build_evaluate_observations_from_filea,
    _finalize_ies_contract,
    _infer_excode_from_filex,
    _parse_batch_entries,
    _read_tmt_harvest_events,
    _read_tmt_process_points,
    _load_init_overrides,
    _resolve_filex_path,
    _write_run_manifest,
    create_ins_and_pst_multi,
)
from src.calibration.nitrogen_response import (
    build_observed_n_response_rows,
    load_n_response_mapping,
    validate_mapping_against_filex,
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


def _initial_n_parameter(
    *, name: str, value: float, season_id: str, experiment_code: str,
    treatment: int, field: str, layer: int, depth_cm: float | None,
) -> dict:
    """Build one treatment/layer-specific initial soil-N parameter.

    The requested working range is interpreted literally for SNH4/SNO3: the
    lower bound is 50% below the FileX value and the upper bound is 30 units
    above it.  SANI is a soil-analysis concentration-like field in DSSAT,
    not a kg/ha mineral-N pool; a literal ``+30`` upper bound produces
    ``IPSLAN`` invalid-input failures.  It therefore retains the requested
    range as an audit field but applies the conservative DSSAT-safe cap of
    1.0 to the effective upper bound.
    """
    init = float(value)
    lower = max(0.0, init * 0.5)
    requested_upper = init + 30.0
    upper = min(requested_upper, 1.0) if field.upper() == "SANI" else requested_upper
    upper = max(lower + 1.0e-9, upper)
    return {
        "name": name,
        "init": min(max(init, lower), upper),
        "lower": lower,
        "upper": upper,
        "idx": None,
        "status": "none",
        "pargp": "initial_conditions",
        "season_id": season_id,
        "experiment_code": experiment_code,
        "treatment": int(treatment),
        "field": field,
        "layer": int(layer),
        "depth_cm": depth_cm,
        "bound_rule": (
            "init*0.5_to_min(init+30,1.0)" if field.upper() == "SANI"
            else "init*0.5_to_init+30"
        ),
        "requested_upper": requested_upper,
    }


def _read_initial_soil_n_parameters(
    filex: Path, *, season_id: str, experiment_code: str, treatments: tuple[int, ...]
) -> list[dict]:
    """Read SANI/SNH4/SNO3 and create explicit season-treatment-layer params.

    ``SANI`` is the FileX ``*SOIL ANALYSIS`` mineral/total-N reference field;
    ``SNH4`` and ``SNO3`` are the corresponding ``*INITIAL CONDITIONS`` pools.
    Parameters are keyed by experiment code and treatment so equal treatment
    numbers in different seasons are never silently shared.
    """
    lines = filex.read_text(encoding="utf-8-sig", errors="strict").splitlines()
    treatment_set = {int(t) for t in treatments}
    out: list[dict] = []
    seen: set[str] = set()

    def add(field: str, treatment: int, layer: int, value: str, depth: str | None):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        if treatment not in treatment_set or v == -99.0:
            return
        depth_v = None
        try:
            depth_v = float(depth) if depth is not None else None
        except (TypeError, ValueError):
            pass
        prefix = "SA_SANI" if field == "SANI" else f"IC_{field}"
        name = f"{prefix}_{experiment_code.upper()}_TN{treatment:02d}_L{layer:02d}"
        if name in seen:
            return
        seen.add(name)
        out.append(
            _initial_n_parameter(
                name=name, value=v, season_id=season_id,
                experiment_code=experiment_code.upper(), treatment=treatment,
                field=field, layer=layer, depth_cm=depth_v,
            )
        )

    # *SOIL ANALYSIS: the treatment number is the first token of the metadata
    # row; the following layer rows carry SABL and SANI.
    in_sa = False
    sa_mode = None
    sa_tn = None
    sa_layer = 0
    sa_sani_idx = None
    for raw in lines:
        s = raw.strip()
        u = s.upper()
        if u.startswith("*SOIL ANALYSIS"):
            in_sa, sa_mode, sa_tn, sa_layer, sa_sani_idx = True, None, None, 0, None
            continue
        if in_sa and u.startswith("*") and not u.startswith("*SOIL ANALYSIS"):
            in_sa = False
            continue
        if not in_sa or not s:
            continue
        if s.startswith("@A") and "SADAT" in u:
            sa_mode = "meta"
            continue
        if s.startswith("@A") and "SABL" in u and "SANI" in u:
            header = s.split()[1:]
            sa_sani_idx = header.index("SANI")
            sa_mode = "layer"
            continue
        if s.startswith("@"):
            sa_mode = None
            continue
        parts = s.split()
        if sa_mode == "meta" and parts:
            try:
                sa_tn = int(float(parts[0]))
            except ValueError:
                sa_tn = None
            sa_layer = 0
            sa_mode = None
        elif sa_mode == "layer" and sa_sani_idx is not None:
            if sa_tn is None or len(parts) <= sa_sani_idx + 1:
                continue
            sa_layer += 1
            add("SANI", sa_tn, sa_layer, parts[sa_sani_idx + 1], parts[1])

    # *INITIAL CONDITIONS: the PCR row defines the treatment/ICNAME; each
    # following ICBL row contributes one layer of SNH4 and SNO3.
    in_ic = False
    ic_mode = None
    ic_tn = None
    ic_layer = 0
    snh4_idx = None
    sno3_idx = None
    for raw in lines:
        s = raw.strip()
        u = s.upper()
        if u.startswith("*INITIAL CONDITIONS"):
            in_ic, ic_mode, ic_tn, ic_layer = True, None, None, 0
            continue
        if in_ic and u.startswith("*") and not u.startswith("*INITIAL CONDITIONS"):
            in_ic = False
            continue
        if not in_ic or not s:
            continue
        if s.startswith("@C") and "PCR" in u and "ICDAT" in u:
            ic_mode = "meta"
            continue
        if s.startswith("@C") and "ICBL" in u and "SNH4" in u and "SNO3" in u:
            header = s.split()[1:]
            snh4_idx = header.index("SNH4")
            sno3_idx = header.index("SNO3")
            ic_mode = "layer"
            continue
        if s.startswith("@"):
            ic_mode = None
            continue
        parts = s.split()
        if ic_mode == "meta" and parts:
            try:
                ic_tn = int(float(parts[0]))
            except ValueError:
                ic_tn = None
            ic_layer = 0
            ic_mode = None
        elif ic_mode == "layer" and ic_tn is not None and snh4_idx is not None and sno3_idx is not None:
            if len(parts) <= max(snh4_idx, sno3_idx) + 1:
                continue
            ic_layer += 1
            add("SNH4", ic_tn, ic_layer, parts[snh4_idx + 1], parts[1])
            add("SNO3", ic_tn, ic_layer, parts[sno3_idx + 1], parts[1])

    return out


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
        "LWADM", "SWADM", "SNAMM", "LNAMM", "CHFPWM", "CHPDTM", "HPODWM",
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

    if bool(getattr(args, "include_initial_soil_n", False)):
        n_params = []
        for season in seasons:
            filex = season.initial_soil_n_reference_filex or next(season.bundle_absolute.glob("*.TMX"), None)
            if filex is None:
                raise FileNotFoundError(
                    f"{season.season_id}: bundle has no FileX for initial soil-N parameterization"
                )
            n_params.extend(
                _read_initial_soil_n_parameters(
                    filex,
                    season_id=season.season_id,
                    experiment_code=season.experiment_code,
                    treatments=season.treatments,
                )
            )
        existing = {str(p.get("name", "")).upper() for p in params}
        duplicate = [p["name"] for p in n_params if p["name"].upper() in existing]
        if duplicate:
            raise ValueError(f"duplicate initial soil-N parameter names: {duplicate[:5]}")
        params.extend(n_params)
        print(
            f"Initial soil-N parameters: {len(n_params)} "
            f"(SANI/SNH4/SNO3; treatment- and layer-specific)"
        )

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Soil-profile terms are not present in CUL/ECO/SPE templates and thus
    # cannot be discovered by parse_cul_params/parse_extra_params.  Promote
    # any explicitly declared frozen SOIL_* term (currently SOIL_SLPF) into
    # the PEST vector so the runner can inject it into SOIL.SOL.
    bounds_id = str(getattr(args, "bounds_id", "") or "").strip()
    if bounds_id:
        bounds_path = PROJECT_ROOT / "data" / "parameter_registry" / "bounds_frozen" / str(getattr(args, "bounds_crop", "eggplant")) / f"{bounds_id}.csv"
        if bounds_path.is_file():
            frozen = pd.read_csv(bounds_path, encoding="utf-8-sig")
            init_override = {}
            for init_path in getattr(args, "init_from", None) or []:
                init_override.update(_load_init_overrides(init_path))
            freeze_existing_soil = bool(
                getattr(args, "freeze_existing_soil_params", False)
            )
            present = {str(p.get("name", "")).strip().upper() for p in params}
            for _, row in frozen.iterrows():
                name = str(row.get("name", "")).strip().upper()
                if not name.startswith("SOIL_") or name in present:
                    continue
                value = float(init_override.get(name.lower(), row["init"]))
                status = str(row.get("status", "fixed")).strip().lower()
                if freeze_existing_soil:
                    status = "fixed"
                params.append({
                    "name": name,
                    "init": value,
                    "lower": value if freeze_existing_soil else float(row["lower"]),
                    "upper": value if freeze_existing_soil else float(row["upper"]),
                    "idx": None,
                    "status": "none" if status == "active" else "fixed",
                    "pargp": "soil",
                })
                present.add(name)
            if freeze_existing_soil:
                print(
                    "Existing SOIL_* profile parameters frozen at --init-from "
                    "values; only initial soil-N parameters remain released."
                )

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
        harvest_objective = design.harvest_dry_objective or {}
        increment_source = str(
            harvest_objective.get("increment_source", "measured_hpodw")
        ).strip().lower()
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
                if increment_source == "cumulative_difference":
                    hpodw_val = float(ev.get("dry_inc", -99.0))
                else:
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
            process_points = points_by_run.get(lr, [])
            process_objective = design.process_state_objective or {}
            mixed_process = bool(process_objective.get("enabled", False)) and str(
                process_objective.get("mode", "")
            ).strip().lower() == "signed_difference_plus_terminal"
            previous_process = None
            for point_index, p in enumerate(process_points):
                terminal_point = point_index == len(process_points) - 1
                record = {
                    "@RUN": gr, "TN": tn, "DATE": int(p["date"]),
                    "LAIDM": float(p["laid"]), "LWADM": float(p["lwad"]),
                    "SWADM": float(p["swad"]),
                    "CHTDM": float(p.get("chtd", -99.0)),
                    "SNAMM": float(p.get("snam", -99.0)),
                    "LNAMM": float(p.get("lnam", -99.0)),
                    "LAIDS": -99.0, "LWADS": -99.0, "SWADS": -99.0,
                    "SNAMS": -99.0, "LNAMS": -99.0, "season": sid,
                    "CHTDS": -99.0,
                }
                for obs_col, source_variable in {
                    "LAIDM": "LAID",
                    "LWADM": "LWAD",
                    "SWADM": "SWAD",
                    "CHTDM": "CHTD",
                    "SNAMM": "SNAM",
                    "LNAMM": "LNAM",
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
                if mixed_process:
                    for source, delta_obs, terminal_obs in (
                        ("LAIDM", "LAIDDM", "LAIETM"),
                        ("LWADM", "LWADDM", "LWETM"),
                        ("SWADM", "SWADDM", "SWETM"),
                    ):
                        value = float(record[source])
                        previous_value = (
                            float(previous_process[source])
                            if previous_process is not None
                            else -99.0
                        )
                        record[delta_obs] = (
                            value - previous_value
                            if value != -99.0 and previous_value != -99.0
                            else -99.0
                        )
                        record[terminal_obs] = (
                            value if terminal_point and value != -99.0 else -99.0
                        )
                        record[delta_obs[:-1] + "S"] = -99.0
                        record[terminal_obs[:-1] + "S"] = -99.0
                        current_sigma = record.get(f"{source}_SIGMA")
                        previous_sigma = (
                            previous_process.get(f"{source}_SIGMA")
                            if previous_process is not None
                            else None
                        )
                        if record[delta_obs] != -99.0:
                            if current_sigma is None or previous_sigma is None:
                                raise ValueError(
                                    f"{sid} TN={tn} {delta_obs}: missing source sigma"
                                )
                            record[f"{delta_obs}_SIGMA"] = math.sqrt(
                                float(current_sigma) ** 2 + float(previous_sigma) ** 2
                            )
                            record[f"{delta_obs}_SIGMA_SOURCE"] = (
                                "difference_independent:"
                                "sqrt(current_mean_sigma^2+previous_mean_sigma^2)"
                            )
                        if record[terminal_obs] != -99.0:
                            record[f"{terminal_obs}_SIGMA"] = float(current_sigma)
                            record[f"{terminal_obs}_SIGMA_SOURCE"] = (
                                "terminal_state:source_mean_sigma"
                            )
                all_process_rows.append(record)
                previous_process = record
        soil_rows, local_soil_sigmas = _soil_rows_for_season(
            sctx.input_dir, sid, entries, local_to_global
        )
        all_soil_rows.extend(soil_rows)
        soil_sigmas.update(local_soil_sigmas)

    df_eval = pd.DataFrame(all_eval_rows)
    df_harvest = pd.DataFrame(all_harvest_rows)
    df_process = pd.DataFrame(all_process_rows)
    df_soil = pd.DataFrame(all_soil_rows)

    adapm_sigma = float(getattr(args, "adapm_sigma", None) or 25.0)
    harvest_sigmas = {}
    if not df_harvest.empty:
        s0 = float(getattr(args, "pwadm_sigma0", 250.0))
        cv = float(getattr(args, "pwadm_cv", 0.08))
        sf = float(getattr(args, "pwadm_sigma_factor", 1.0))
        for hno, g in df_harvest.groupby("HNO"):
            # T10 direct harvest: CHFPW and CHPDT get their own sigma keys.
            for var in ("CHFPWM", "CHPDTM", "HPODWM"):
                med = float(g[var].median()) if var in g.columns else 0.0
                harvest_sigmas[f"{var}_H{int(hno)}"] = float((s0**2 + (cv * abs(med))**2)**0.5 * sf)

    process_sigmas = {}
    if not df_process.empty:
        laidm_sf = float(getattr(args, "laidm_sigma_factor", 1.0))
        lwadm_sf = float(getattr(args, "lwadm_sigma_factor", 1.0))
        swadm_sf = float(getattr(args, "swadm_sigma_factor", 1.0))
        for var, s0, cv in [
            ("LAIDM", 1.6, 0.50), ("LWADM", 80.0, 0.25), ("SWADM", 100.0, 0.25),
            ("CHTDM", 2.0, 0.15),
            ("SNAMM", 5.0, 0.25), ("LNAMM", 5.0, 0.25),
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
            "model_out_path": PEST_HARVEST_FILE, "obs_bases": {"CHFPW", "CHPDT", "HPODW"},
            "critical_obs": set(), "group_sigmas": harvest_sigmas, "df": df_harvest,
        },
        {
            "model_out_path": PEST_TMTGROW_FILE,
            "obs_bases": {
                "LAID", "LWAD", "SWAD", "CHTD", "SNAM", "LNAM",
                "LAIDD", "LWADD", "SWADD", "LAIET", "LWET", "SWET",
            },
            "critical_obs": set(), "group_sigmas": process_sigmas, "df": df_process,
        },
    ]
    n_response = design.nitrogen_response_objective or {}
    if bool(n_response.get("enabled", False)):
        mapping_path = Path(str(n_response["mapping_csv"]))
        if not mapping_path.is_absolute():
            mapping_path = (PROJECT_ROOT / mapping_path).resolve()
        response_levels = n_response.get("levels", ["N1", "N2", "N3"])
        declared_mapping = pd.read_csv(mapping_path, encoding="utf-8-sig")
        filex_mapping_audits = []
        for season in design.calibration_seasons:
            filex = next(season.bundle_absolute.glob("*.TMX"), None)
            if filex is None:
                raise FileNotFoundError(f"{season.season_id}: bundle has no FileX")
            filex_mapping_audits.append(
                validate_mapping_against_filex(
                    declared_mapping,
                    filex,
                    season_id=season.season_id,
                    treatments=season.treatments,
                )
            )
        pd.concat(filex_mapping_audits, ignore_index=True).to_csv(
            out_dir / f"{prefix}_filex_water_n_mapping_audit.csv", index=False
        )
        response_mapping = load_n_response_mapping(
            mapping_path, run_mapping_rows, response_levels=response_levels
        )
        df_n_response = build_observed_n_response_rows(
            df_harvest,
            response_mapping,
            sigma_floor=float(n_response.get("sigma_floor", 0.10)),
            response_target=str(
                n_response.get("response_target", "observed_shape")
            ),
            response_levels=response_levels,
            contrast_scale=str(n_response.get("contrast_scale", "log_ratio")),
            harvest_scope=str(n_response.get("harvest_scope", "all")),
        )
        stage2_outputs.append({
            "model_out_path": PEST_N_RESPONSE_FILE,
            "obs_bases": {"NRESP"},
            "critical_obs": set(),
            "group_sigmas": {"NRESPM": 1.0},
            "df": df_n_response,
        })
    if not df_soil.empty:
        stage2_outputs.append({
            "model_out_path": "PestSoilWat.OUT", "obs_bases": None,
            "critical_obs": set(), "group_sigmas": soil_sigmas, "df": df_soil,
        })

    run_map_path = out_dir / f"{prefix}_run_mapping.csv"
    pd.DataFrame(run_mapping_rows).to_csv(run_map_path, index=False, encoding="utf-8-sig")
    print(f"run_mapping ({len(run_mapping_rows)} runs) -> {run_map_path}")

    model_cmd_extra = (
        f"--batch DSSBatch.v48 --harvest-var {getattr(args, 'harvest_var', 'CHPDT')} "
        "--keep-nitrogen-outputs"
    )
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
            f' --harvest-var {getattr(args, "harvest_var", "CHPDT")} --keep-nitrogen-outputs'
            f' --prefix {prefix}{transform_arg}'
        ]
        pst.write(str(pst_path))

    # ── Apply T8 weight formula (§7.2) ──────────────────────────────────
    _apply_harvest_dry_objective_mask(
        out_dir, prefix, design.harvest_dry_objective
    )
    _apply_t8_weights(
        out_dir, prefix, design.group_policy, run_mapping_rows,
        harvest_dry_objective=design.harvest_dry_objective,
        process_state_objective=design.process_state_objective,
    )

    # ── Write observation_registry.csv ───────────────────────────────────
    _write_obs_registry(out_dir, prefix, run_mapping_rows)

    # ── Write group_weight_audit.csv ─────────────────────────────────────
    _write_group_weight_audit(
        out_dir, prefix, design.group_policy, run_mapping_rows,
        harvest_dry_objective=design.harvest_dry_objective,
        process_state_objective=design.process_state_objective,
    )

    ies_contract = _finalize_ies_contract(
        pst_path,
        out_dir=str(out_dir),
        prefix=prefix,
        ies_num_reals=int(args.ies_num_reals),
        random_seed=int(args.random_seed),
        bad_phi_sigma=float(
            getattr(args, "bad_phi_sigma", None)
            if getattr(args, "bad_phi_sigma", None) is not None
            else 1.0e300
        ),
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

def _family_for_group(
    group, harvest_dry_objective=None, process_state_objective=None
):
    root = str(group).strip().upper()
    if "_" in root and root.split("_", 1)[0][-2:] in {"SP", "FA"}:
        root = root.split("_", 1)[1]
    for suffix in ("_H", "_D"):
        idx = root.find(suffix)
        if idx > 0:
            root = root[:idx]
            break
    harvest_mode = str(
        (harvest_dry_objective or {}).get("mode", "")
    ).strip().lower()
    if bool((harvest_dry_objective or {}).get("enabled", False)) and \
            harvest_mode == "increment_plus_terminal":
        if root.startswith("CHPDTM") or root.startswith("CHPDTS"):
            return "HARVEST_DRY_TOTAL"
        if root.startswith("HPODWM") or root.startswith("HPODWS"):
            return "HARVEST_DRY_INCREMENT"
    process_mode = str(
        (process_state_objective or {}).get("mode", "")
    ).strip().lower()
    if bool((process_state_objective or {}).get("enabled", False)) and \
            process_mode == "signed_difference_plus_terminal":
        if root.startswith("LAIDDM") or root.startswith("LAIDDS"):
            return "CANOPY_INCREMENT"
        if root.startswith("LAIETM") or root.startswith("LAIETS"):
            return "CANOPY_TERMINAL"
        if root.startswith(("LWADDM", "LWADDS", "SWADDM", "SWADDS")):
            return "BIOMASS_INCREMENT"
        if root.startswith(("LWETM", "LWETS", "SWETM", "SWETS")):
            return "BIOMASS_TERMINAL"
    family_map = {
        "PDAPM": "PHENO", "PDAPS": "PHENO",
        "ADAPM": "PHENO", "ADAPS": "PHENO",
        "MDAPM": "PHENO", "MDAPS": "PHENO",
        "LAIXM": "CANOPY", "LAIDM": "CANOPY", "LAIXS": "CANOPY",
        "CHTDM": "CANOPY", "CHTDS": "CANOPY",
        "LWADM": "BIOMASS", "SWADM": "BIOMASS",
        "CNAMM": "PLANT_N",
        "SNAMM": "PLANT_N", "LNAMM": "PLANT_N",
        "HIAMM": "BIOMASS", "CWAMS": "BIOMASS",
        "PWADM": "CUMULATIVE_HARVEST", "PWAIM": "INCREMENTAL_HARVEST",
        # T10 direct harvest variables (log-transformed cumulative series).
        "CHFPWM": "HARVEST_FRESH", "CHFPWS": "HARVEST_FRESH",
        "CHPDTM": "HARVEST_DRY", "CHPDTS": "HARVEST_DRY",
        "HPODWM": "HARVEST_DRY", "HPODWS": "HARVEST_DRY",
        "NRESPM": "N_RESPONSE", "NRESPS": "N_RESPONSE",
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


def _apply_harvest_dry_objective_mask(out_dir, prefix, objective):
    """Keep only terminal CHPDT points active for the mixed dry-yield target.

    All HPODW event increments stay active.  Intermediate cumulative points
    remain in the PEST interface and registry for diagnostics, but receive
    zero weight before family-budget normalization.
    """
    import re

    cfg = objective or {}
    if not bool(cfg.get("enabled", False)) or str(cfg.get("mode", "")).strip().lower() != "increment_plus_terminal":
        return
    weights_path = out_dir / f"{prefix}.weights.audit.csv"
    if not weights_path.is_file():
        raise FileNotFoundError(weights_path)
    audit = pd.read_csv(weights_path, encoding="utf-8-sig")
    names = audit["obsnme"].astype(str)
    groups = audit["obgnme"].astype(str).str.upper()
    is_chpdt = groups.str.contains("CHPDTM", regex=False)
    parsed = names.str.extract(r"_R(?P<run>\d+)_H(?P<hno>\d+)$", flags=re.IGNORECASE)
    if parsed.loc[is_chpdt].isna().any().any():
        bad = names[is_chpdt & parsed.isna().any(axis=1)].tolist()
        raise ValueError(f"cannot parse CHPDT run/harvest identity: {bad[:5]}")
    parsed["run"] = pd.to_numeric(parsed["run"], errors="coerce")
    parsed["hno"] = pd.to_numeric(parsed["hno"], errors="coerce")
    terminal_hno = parsed.loc[is_chpdt].groupby("run")["hno"].transform("max")
    terminal = is_chpdt.copy()
    terminal.loc[is_chpdt] = (
        parsed.loc[is_chpdt, "hno"].to_numpy() == terminal_hno.to_numpy()
    )
    diagnostic = is_chpdt & ~terminal
    audit.loc[diagnostic, "weight"] = 0.0
    if "phi_role" in audit.columns:
        audit.loc[diagnostic, "phi_role"] = "diagnostic_only"
    audit.loc[diagnostic, "note"] = (
        "Intermediate cumulative CHPDT retained for diagnostics; mixed objective uses terminal total only"
    )
    audit.loc[terminal, "note"] = (
        "Terminal cumulative CHPDT anchors final harvested dry mass"
    )
    audit.to_csv(weights_path, index=False, encoding="utf-8-sig")
    print(
        f"Mixed harvest objective: {int(diagnostic.sum())} intermediate CHPDT diagnostic-only; "
        f"{int(terminal.sum())} terminal CHPDT active"
    )


def _apply_t8_weights(
    out_dir, prefix, group_policy, run_mapping_rows,
    harvest_dry_objective=None,
    process_state_objective=None,
):
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
                bucket = (
                    _season_for_obsnme(obsnme, run_seasons),
                    _family_for_group(
                        grp, harvest_dry_objective, process_state_objective
                    ),
                )
                obs_bucket[obsnme] = bucket
                bucket_n[bucket] = bucket_n.get(bucket, 0) + 1

    bucket_mult = {}
    for bucket, n in bucket_n.items():
        _, family = bucket
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


def _write_group_weight_audit(
    out_dir, prefix, group_policy, run_mapping_rows,
    harvest_dry_objective=None,
    process_state_objective=None,
):
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
            bucket = (
                _season_for_obsnme(obsnme, run_seasons),
                _family_for_group(
                    row.get("obgnme", ""), harvest_dry_objective
                    , process_state_objective
                ),
            )
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
            budget = budgets.get(family, 1.0)
            mean_s = sum(g["sigmas"]) / max(len(g["sigmas"]), 1)
            mean_w = sum(g["weights"]) / max(len(g["weights"]), 1)
            # T10 family-season allocation: weight = (1/sigma) * sqrt(budget / n_obs)
            expected_mult = (
                math.sqrt(budget / g["n_obs"]) if g["n_obs"] > 0 else 0.0
            )
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
                "note": (
                    f"T8 §7.2: sqrt({budget}/{g['n_obs']}) = {expected_mult:.4f}"
                    if g["n_obs"] > 0
                    else "inactive diagnostic family; no positive-weight observations"
                ),
            })
    print(f"group_weight_audit ({len(groups)} groups) -> {audit_path}")
