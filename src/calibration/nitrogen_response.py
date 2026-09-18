"""Derived water x nitrogen response observations for multi-season PEST cases.

The objective is expressed as a log cumulative-yield contrast within one
season, water level, and harvest event::

    CHPDT_Nk - CHPDT_N0, or its explicitly requested log-ratio equivalent.

This constrains the observed response shape without assuming that yield must
increase monotonically with nitrogen.  The N0 observations are shared
references, so these residuals are intentionally kept in their own finite
Phi-budget family.
"""

from __future__ import annotations

import csv
import math
import re
from pathlib import Path
from typing import Iterable, Mapping

import pandas as pd

from src.common.experiment_inputs import parse_filex
from src.sensitivity.treatment_factor_attribution import fertilizer_n_total_kg_ha


PEST_N_RESPONSE_FILE = "PestNResponse.OUT"
# Non-N0 nitrogen dose-gradient output.  This is deliberately separate from
# N_RESPONSE (Nk-N0): it constrains N2-N1, N3-N2 and the N1:N3 spread without
# duplicating the common N0 reference residuals.
PEST_N_DOSE_GRADIENT_FILE = "PestNDoseGradient.OUT"
# Water-response contrast output: same-nitrogen W3 vs W1 yield difference.
PEST_W_RESPONSE_FILE = "PestWResponse.OUT"
_HNO = re.compile(r"(?:@HNO@|HNO)\s+(?P<hno>\d+)")


def _response_source(source_variable: str) -> tuple[str, str, re.Pattern[str]]:
    """Resolve a cumulative harvest source to measured column and output token."""
    variable = str(source_variable).strip().upper()
    sources = {"CHPDT": ("CHPDTM", "CHPDTS"), "CHFPW": ("CHFPWM", "CHFPWS")}
    if variable not in sources:
        raise ValueError("source_variable must be CHPDT or CHFPW")
    measured, simulated = sources[variable]
    pattern = re.compile(
        r"^RUN\s+(?P<run>\d+)\s+TN\s+(?P<tn>\d+)\s+"
        r".*?(?:@HNO@|HNO)\s+(?P<hno>\d+)\s+"
        r"(?:@DATE@|DATE)\s+(?P<date>\d+)\s+"
        rf".*?@{simulated}@\s+(?P<value>[-+0-9.eE]+)"
    )
    return measured, simulated, pattern


def _filex_irrigation_profiles(filex: Path) -> dict[int, dict[str, float | str]]:
    """Read FileX irrigation factor names and seasonal applied totals."""
    profiles: dict[int, dict[str, float | str]] = {}
    in_section = False
    header_kind = ""
    for raw in filex.read_text(encoding="utf-8", errors="ignore").splitlines():
        upper = raw.strip().upper()
        if upper.startswith("*IRRIGATION AND WATER MANAGEMENT"):
            in_section = True
            continue
        if in_section and raw.startswith("*"):
            break
        if not in_section or not upper:
            continue
        if upper.startswith("@I"):
            header_kind = (
                "events" if "IDATE" in upper and "IRVAL" in upper else "profile"
            )
            continue
        tokens = raw.split()
        if not tokens:
            continue
        try:
            level = int(tokens[0])
        except ValueError:
            continue
        if header_kind == "profile":
            profiles[level] = {
                "name": str(tokens[-1]).strip().upper(),
                "total_mm": 0.0,
            }
        elif header_kind == "events" and len(tokens) >= 4:
            profile = profiles.setdefault(
                level, {"name": f"MI{level}", "total_mm": 0.0}
            )
            profile["total_mm"] = float(profile["total_mm"]) + float(tokens[3])
    return profiles


def derive_filex_water_n_mapping(
    filex_path: str | Path,
    *,
    season_id: str,
    treatments: Iterable[int] | None = None,
) -> pd.DataFrame:
    """Derive treatment water/N identities from one season's actual FileX.

    Water labels come from each treatment's MI-linked ``IRNAME`` and applied
    irrigation total. Nitrogen labels come from the ascending *full-season*
    fertilizer-dose ladder, not from TRNO ordering. This matters because the
    three experiments use different TRNO-to-management mappings.
    """
    filex = Path(filex_path).expanduser().resolve()
    parsed = parse_filex(filex)
    treatment_factors = parsed.get("treatments", {})
    if not treatment_factors:
        raise ValueError(f"{season_id}: FileX has no readable treatments: {filex}")
    text = filex.read_text(encoding="utf-8", errors="ignore")
    irrigation = _filex_irrigation_profiles(filex)

    # Build the dose ladder from every FileX treatment before filtering. A
    # selected N0/N2 subset must remain N0/N2 rather than being relabelled N0/N1.
    dose_by_mf: dict[int, float] = {}
    for factors in treatment_factors.values():
        mf = int(factors["MF"])
        if mf not in dose_by_mf:
            dose_by_mf[mf] = fertilizer_n_total_kg_ha(text, mf)
    dose_ladder = sorted({round(float(value), 9) for value in dose_by_mf.values()})
    if len(dose_ladder) != 4:
        raise ValueError(
            f"{season_id}: expected four FileX nitrogen doses, found {dose_ladder}"
        )
    nitrogen_label = {dose: f"N{index}" for index, dose in enumerate(dose_ladder)}
    selected = (
        {int(value) for value in treatments}
        if treatments is not None
        else {int(value) for value in treatment_factors}
    )
    missing = selected - {int(value) for value in treatment_factors}
    if missing:
        raise ValueError(f"{season_id}: selected TRNO absent from FileX: {sorted(missing)}")

    rows: list[dict[str, object]] = []
    for treatment in sorted(selected):
        factors = treatment_factors[treatment]
        mi = int(factors["MI"])
        mf = int(factors["MF"])
        if mi not in irrigation:
            raise ValueError(f"{season_id} TRNO {treatment}: MI={mi} has no irrigation profile")
        dose = float(dose_by_mf[mf])
        water = str(irrigation[mi]["name"]).strip().upper()
        if water not in {"W1", "W2", "W3", "CK"}:
            raise ValueError(
                f"{season_id} TRNO {treatment}: unsupported FileX IRNAME={water!r}"
            )
        rows.append(
            {
                "season_id": str(season_id),
                "treatment": int(treatment),
                "mi": mi,
                "water_level": water,
                "irrigation_mm": float(irrigation[mi]["total_mm"]),
                "mf": mf,
                "nitrogen_kg_ha": dose,
                "nitrogen_level": nitrogen_label[round(dose, 9)],
                "filex_path": str(filex),
            }
        )
    return pd.DataFrame(rows).sort_values(["water_level", "nitrogen_level", "treatment"])


def validate_mapping_against_filex(
    mapping: pd.DataFrame,
    filex_path: str | Path,
    *,
    season_id: str,
    treatments: Iterable[int],
) -> pd.DataFrame:
    """Fail if a frozen response mapping disagrees with the actual FileX."""
    derived = derive_filex_water_n_mapping(
        filex_path, season_id=season_id, treatments=treatments
    )
    declared = mapping.loc[
        mapping["season_id"].astype(str).eq(str(season_id))
        & mapping["treatment"].astype(int).isin([int(value) for value in treatments])
    ].copy()
    if len(declared) != len(derived):
        raise ValueError(
            f"{season_id}: response mapping has {len(declared)} selected rows but "
            f"FileX has {len(derived)}"
        )
    merged = derived.merge(
        declared,
        on=["season_id", "treatment"],
        how="outer",
        suffixes=("_filex", "_declared"),
        indicator=True,
        validate="one_to_one",
    )
    mismatches: list[str] = []
    for _, row in merged.iterrows():
        treatment = int(row["treatment"])
        if row["_merge"] != "both":
            mismatches.append(f"TRNO {treatment}: missing row")
            continue
        for field in ("water_level", "nitrogen_level"):
            if str(row[f"{field}_filex"]).upper() != str(
                row[f"{field}_declared"]
            ).upper():
                mismatches.append(
                    f"TRNO {treatment}: {field} FileX={row[f'{field}_filex']} "
                    f"declared={row[f'{field}_declared']}"
                )
        for field in ("nitrogen_kg_ha", "irrigation_mm"):
            declared_name = f"{field}_declared"
            if declared_name in merged.columns and not math.isclose(
                float(row[f"{field}_filex"]),
                float(row[declared_name]),
                rel_tol=0.0,
                abs_tol=0.11,
            ):
                mismatches.append(
                    f"TRNO {treatment}: {field} FileX={row[f'{field}_filex']} "
                    f"declared={row[declared_name]}"
                )
    if mismatches:
        raise ValueError(f"{season_id}: FileX water/N mapping mismatch: " + "; ".join(mismatches))
    return derived


def load_n_response_mapping(
    path: str | Path,
    run_mapping_rows: Iterable[Mapping[str, object]],
    response_levels: Iterable[str] = ("N1", "N2", "N3"),
) -> pd.DataFrame:
    """Load and validate an explicit season/treatment W x N mapping."""
    mapping = pd.read_csv(path, encoding="utf-8-sig")
    required = {"season_id", "treatment", "water_level", "nitrogen_level"}
    missing = required - set(mapping.columns)
    if missing:
        raise ValueError(f"N-response mapping missing columns: {sorted(missing)}")
    mapping = mapping.copy()
    mapping["season_id"] = mapping["season_id"].astype(str)
    mapping["treatment"] = pd.to_numeric(mapping["treatment"], errors="raise").astype(int)
    mapping["water_level"] = mapping["water_level"].astype(str).str.upper()
    mapping["nitrogen_level"] = mapping["nitrogen_level"].astype(str).str.upper()
    allowed_water = {"W1", "W2", "W3", "CK"}
    allowed_n = {"N0", "N1", "N2", "N3"}
    if not set(mapping["water_level"]) <= allowed_water:
        raise ValueError("N-response mapping water_level must be W1, W2, W3 or CK")
    if not set(mapping["nitrogen_level"]) <= allowed_n:
        raise ValueError("N-response mapping nitrogen_level must be N0..N3")
    if mapping.duplicated(["season_id", "treatment"]).any():
        raise ValueError("N-response mapping has duplicate season/treatment rows")
    if mapping.duplicated(["season_id", "water_level", "nitrogen_level"]).any():
        raise ValueError("N-response mapping has duplicate W x N cells")

    run_map = pd.DataFrame(run_mapping_rows).rename(columns={"season_id": "_season_id"})
    run_map["_season_id"] = run_map["_season_id"].astype(str)
    run_map["treatment"] = pd.to_numeric(run_map["treatment"], errors="raise").astype(int)
    selected = mapping.merge(
        run_map[["_season_id", "treatment", "global_run"]].rename(
            columns={"_season_id": "season_id"}
        ),
        on=["season_id", "treatment"],
        how="inner",
        validate="one_to_one",
    )
    levels = tuple(str(x).strip().upper() for x in response_levels)
    if not levels or any(x not in {"N1", "N2", "N3"} for x in levels):
        raise ValueError("response_levels must be a non-empty subset of N1..N3")
    for season, group in selected.groupby("season_id"):
        complete_waters = []
        for water, water_group in group.groupby("water_level"):
            available = set(water_group["nitrogen_level"])
            if {"N0", *levels} <= available:
                complete_waters.append(str(water))
        if not complete_waters:
            raise ValueError(
                f"{season}: N-response objective has no strictly paired water level "
                f"containing N0 and {list(levels)}"
            )
    return selected


def build_observed_n_response_rows(
    harvest: pd.DataFrame,
    mapping: pd.DataFrame,
    *,
    sigma_floor: float = 0.10,
    response_target: str = "observed_shape",
    response_levels: Iterable[str] = ("N1", "N2", "N3"),
    contrast_scale: str = "log_ratio",
    harvest_scope: str = "all",
    source_variable: str = "CHPDT",
) -> pd.DataFrame:
    """Construct strictly paired within-water nitrogen-yield contrasts."""
    response_target = str(response_target).strip().lower()
    if response_target not in {"observed_shape", "monotone_plateau"}:
        raise ValueError(
            "response_target must be observed_shape or monotone_plateau"
        )
    contrast_scale = str(contrast_scale).strip().lower()
    if contrast_scale not in {"log_ratio", "raw_difference"}:
        raise ValueError("contrast_scale must be log_ratio or raw_difference")
    harvest_scope = str(harvest_scope).strip().lower()
    if harvest_scope not in {"all", "terminal"}:
        raise ValueError("harvest_scope must be all or terminal")
    measured_col, _, _ = _response_source(source_variable)
    sigma_col = f"{measured_col}_SIGMA"
    required = {"@RUN", "TN", "HNO", "DATE", measured_col, sigma_col, "season"}
    missing = required - set(harvest.columns)
    if missing:
        raise ValueError(f"harvest table lacks N-response inputs: {sorted(missing)}")
    levels = tuple(str(x).strip().upper() for x in response_levels)
    if not levels or any(x not in {"N1", "N2", "N3"} for x in levels):
        raise ValueError("response_levels must be a non-empty subset of N1..N3")
    joined = harvest.merge(
        mapping[["season_id", "treatment", "water_level", "nitrogen_level"]],
        left_on=["season", "TN"],
        right_on=["season_id", "treatment"],
        how="inner",
        validate="many_to_one",
    )
    rows: list[dict[str, object]] = []
    keys = ["season", "HNO", "DATE", "water_level"]
    for (season, hno, date, water), group in joined.groupby(keys, sort=True):
        by_n = group.set_index("nitrogen_level")
        if not {"N0", *levels} <= set(by_n.index):
            continue
        n0_y = float(by_n.loc["N0", measured_col])
        n0_s = float(by_n.loc["N0", sigma_col])
        if n0_y < 0:
            continue
        target_source = {"N0": "N0"}
        target_y = {"N0": n0_y}
        target_sigma = {"N0": n0_s}
        running_level = "N0"
        for level in levels:
            candidate_y = float(by_n.loc[level, measured_col])
            if (
                response_target == "monotone_plateau"
                and candidate_y < target_y[running_level]
            ):
                target_y[level] = target_y[running_level]
                target_sigma[level] = target_sigma[running_level]
                target_source[level] = target_source[running_level]
            else:
                target_y[level] = candidate_y
                target_sigma[level] = float(
                    by_n.loc[level, sigma_col]
                )
                target_source[level] = level
                running_level = level
        for level in levels:
            y = target_y[level]
            s = target_sigma[level]
            if y < 0:
                continue
            if contrast_scale == "log_ratio":
                observed_contrast = math.log1p(y) - math.log1p(n0_y)
                propagated = math.sqrt(
                    (s / (y + 1.0)) ** 2
                    + (n0_s / (n0_y + 1.0)) ** 2
                    + float(sigma_floor) ** 2
                )
                sigma_source = "delta_method_ln1p_pair_plus_static_floor"
            else:
                observed_contrast = y - n0_y
                propagated = math.sqrt(
                    s**2 + n0_s**2 + float(sigma_floor) ** 2
                )
                sigma_source = "paired_raw_difference_plus_static_floor"
            rows.append(
                {
                    "@RUN": int(by_n.loc[level, "@RUN"]),
                    "TN": int(by_n.loc[level, "TN"]),
                    "HNO": int(hno),
                    "DATE": int(date),
                    "NRESPM": observed_contrast,
                    "NRESPS": -99.0,
                    "NRESPM_SIGMA": propagated,
                    "NRESPM_SIGMA_SOURCE": sigma_source,
                    "season": str(season),
                    "water_level": str(water),
                    "nitrogen_level": level,
                    "response_target": response_target,
                    "target_source_level": target_source[level],
                    "contrast_scale": contrast_scale,
                }
            )
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("N-response objective produced no complete contrasts")
    if harvest_scope == "terminal":
        terminal_hno = result.groupby(
            ["season", "water_level", "nitrogen_level"], sort=False
        )["HNO"].transform("max")
        result = result.loc[result["HNO"].eq(terminal_hno)].reset_index(drop=True)
    return result


def write_simulated_n_response(
    harvest_output: str | Path,
    output_path: str | Path,
    mapping: pd.DataFrame,
    response_levels: Iterable[str] = ("N1", "N2", "N3"),
    *,
    source_scale: str = "raw",
    contrast_scale: str = "log_ratio",
    harvest_scope: str = "all",
    source_variable: str = "CHPDT",
) -> Path:
    """Derive simulated contrasts with explicit source and target scales.

    Never infer the CHPDT source scale from an observation-policy side effect.
    The output ordering intentionally matches :func:`build_observed_n_response_rows`.
    """
    _, _, tagged = _response_source(source_variable)
    lookup = {
        int(row.global_run): (
            str(row.season_id), str(row.water_level), str(row.nitrogen_level),
            int(row.treatment),
        )
        for row in mapping.itertuples(index=False)
    }
    source_scale = str(source_scale).strip().lower()
    contrast_scale = str(contrast_scale).strip().lower()
    harvest_scope = str(harvest_scope).strip().lower()
    if source_scale not in {"raw", "log1p"}:
        raise ValueError("source_scale must be raw or log1p")
    if contrast_scale not in {"log_ratio", "raw_difference"}:
        raise ValueError("contrast_scale must be log_ratio or raw_difference")
    if harvest_scope not in {"all", "terminal"}:
        raise ValueError("harvest_scope must be all or terminal")
    if contrast_scale == "raw_difference" and source_scale != "raw":
        raise ValueError("raw_difference requires raw cumulative-harvest source values")

    values: dict[tuple[str, int, int, str, str], tuple[int, int, float]] = {}
    for line in Path(harvest_output).read_text(encoding="utf-8").splitlines():
        match = tagged.search(line)
        if match is None:
            continue
        run = int(match.group("run"))
        if run not in lookup:
            continue
        season, water, nitrogen, treatment = lookup[run]
        values[(season, int(match.group("hno")), int(match.group("date")), water, nitrogen)] = (
            run, treatment, float(match.group("value"))
        )

    levels = tuple(str(x).strip().upper() for x in response_levels)
    if not levels or any(x not in {"N1", "N2", "N3"} for x in levels):
        raise ValueError("response_levels must be a non-empty subset of N1..N3")
    lines: list[str] = []
    groups = sorted({key[:4] for key in values})
    if harvest_scope == "terminal":
        terminal: dict[tuple[str, str], tuple[int, int]] = {}
        for season, hno, date, water in groups:
            key = (season, water)
            if key not in terminal or (hno, date) > terminal[key]:
                terminal[key] = (hno, date)
        groups = [
            group for group in groups
            if (group[1], group[2]) == terminal[(group[0], group[3])]
        ]
    for season, hno, date, water in groups:
        n0 = values.get((season, hno, date, water, "N0"))
        if n0 is None:
            continue
        for level in levels:
            current = values.get((season, hno, date, water, level))
            if current is None:
                continue
            run, treatment, value = current
            if contrast_scale == "log_ratio":
                contrast = (
                    value - n0[2]
                    if source_scale == "log1p"
                    else math.log1p(value) - math.log1p(n0[2])
                )
            else:
                contrast = value - n0[2]
            lines.append(
                f"RUN {run} TN {treatment} @HNO@ {hno} DATE {date} "
                f"@NRESPS@ {contrast:.12g}"
            )
    if not lines:
        raise ValueError("could not derive simulated N-response contrasts")
    target = Path(output_path)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def _positive_cv(values: Iterable[float]) -> float:
    """Population coefficient of variation for non-negative yield levels."""
    data = [float(value) for value in values]
    mean = sum(data) / len(data)
    if mean <= 0:
        return 0.0
    variance = sum((value - mean) ** 2 for value in data) / len(data)
    return math.sqrt(variance) / mean


def build_observed_n_dose_gradient_rows(
    harvest: pd.DataFrame,
    mapping: pd.DataFrame,
    *,
    seasons: Iterable[str] = ("26SP",),
    sigma_floor: float = 0.05,
    response_target: str = "monotone_plateau",
    harvest_scope: str = "all",
    source_variable: str = "CHFPW",
) -> pd.DataFrame:
    """Build non-N0 nitrogen-gradient targets within water and harvest strata.

    Three dimensionless targets are emitted for each complete N1/N2/N3 group:
    log(N2+1)-log(N1+1), log(N3+1)-log(N2+1), and the population CV of
    N1:N3.  ``monotone_plateau`` clamps only the *observed target* upward;
    simulated values are never clamped, so a simulated yield inversion keeps
    its negative adjacent-gradient residual and is penalized by PEST.
    """
    target_mode = str(response_target).strip().lower()
    if target_mode not in {"observed_shape", "monotone_plateau"}:
        raise ValueError("response_target must be observed_shape or monotone_plateau")
    scope = str(harvest_scope).strip().lower()
    if scope not in {"all", "terminal"}:
        raise ValueError("harvest_scope must be all or terminal")
    selected_seasons = {str(value).strip() for value in seasons}
    if not selected_seasons:
        raise ValueError("n-dose-gradient seasons must not be empty")
    measured_col, _, _ = _response_source(source_variable)
    required = {"@RUN", "TN", "HNO", "DATE", measured_col, "season"}
    missing = required - set(harvest.columns)
    if missing:
        raise ValueError(f"harvest table lacks N-dose-gradient inputs: {sorted(missing)}")
    joined = harvest.merge(
        mapping[["season_id", "treatment", "water_level", "nitrogen_level"]],
        left_on=["season", "TN"], right_on=["season_id", "treatment"],
        how="inner", validate="many_to_one",
    )
    joined = joined.loc[joined["season"].astype(str).isin(selected_seasons)].copy()
    rows: list[dict[str, object]] = []
    for (season, hno, date, water), group in joined.groupby(
        ["season", "HNO", "DATE", "water_level"], sort=True
    ):
        by_n = group.set_index("nitrogen_level")
        if not {"N1", "N2", "N3"} <= set(by_n.index):
            continue
        raw = [float(by_n.loc[level, measured_col]) for level in ("N1", "N2", "N3")]
        if any(value < 0 for value in raw):
            continue
        target = list(raw)
        if target_mode == "monotone_plateau":
            target[1] = max(target[1], target[0])
            target[2] = max(target[2], target[1])
        common = {
            "@RUN": int(by_n.loc["N3", "@RUN"]),
            "TN": int(by_n.loc["N3", "TN"]),
            "HNO": int(hno),
            "DATE": int(date),
            "season": str(season),
            "water_level": str(water),
            "nitrogen_level": "N1_N2_N3",
            "response_target": target_mode,
        }
        metric_values = {
            "NG12": math.log1p(target[1]) - math.log1p(target[0]),
            "NG23": math.log1p(target[2]) - math.log1p(target[1]),
            "NGCV": _positive_cv(target),
        }
        # The generic PEST instruction builder has a strict row contract: one
        # measured/simulated observation pair per physical output line.  Do not
        # combine the three gradient metrics in one dataframe row; doing so
        # makes the generated word offsets point at the following @TAG@ token.
        for metric, value in metric_values.items():
            row = dict(common)
            row.update({
                "NG12M": -99.0, "NG12S": -99.0,
                "NG23M": -99.0, "NG23S": -99.0,
                "NGCVM": -99.0, "NGCVS": -99.0,
                "gradient_metric": metric,
                f"{metric}M": value,
                f"{metric}M_SIGMA": float(sigma_floor),
                f"{metric}M_SIGMA_SOURCE": "dimensionless_static_floor",
            })
            rows.append(row)
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("N-dose-gradient objective produced no complete N1/N2/N3 groups")
    if scope == "terminal":
        terminal = result.groupby(["season", "water_level"], sort=False)["HNO"].transform("max")
        result = result.loc[result["HNO"].eq(terminal)].reset_index(drop=True)
    return result


def write_simulated_n_dose_gradient(
    harvest_output: str | Path,
    output_path: str | Path,
    mapping: pd.DataFrame,
    *,
    seasons: Iterable[str] = ("26SP",),
    harvest_scope: str = "all",
    source_variable: str = "CHFPW",
) -> Path:
    """Write un-clamped simulated N2-N1, N3-N2 and N1:N3 CV values."""
    _, _, tagged = _response_source(source_variable)
    selected_seasons = {str(value).strip() for value in seasons}
    scope = str(harvest_scope).strip().lower()
    if scope not in {"all", "terminal"}:
        raise ValueError("harvest_scope must be all or terminal")
    lookup = {
        int(row.global_run): (
            str(row.season_id), str(row.water_level), str(row.nitrogen_level), int(row.treatment)
        )
        for row in mapping.itertuples(index=False)
    }
    values: dict[tuple[str, int, int, str, str], tuple[int, int, float]] = {}
    for line in Path(harvest_output).read_text(encoding="utf-8").splitlines():
        match = tagged.search(line)
        if match is None or int(match.group("run")) not in lookup:
            continue
        run = int(match.group("run"))
        season, water, nitrogen, treatment = lookup[run]
        if season not in selected_seasons:
            continue
        values[(season, int(match.group("hno")), int(match.group("date")), water, nitrogen)] = (
            run, treatment, float(match.group("value"))
        )
    groups = sorted({key[:4] for key in values})
    if scope == "terminal":
        terminal: dict[tuple[str, str], tuple[int, int]] = {}
        for season, hno, date, water in groups:
            terminal[(season, water)] = max(terminal.get((season, water), (-1, -1)), (hno, date))
        groups = [g for g in groups if (g[1], g[2]) == terminal[(g[0], g[3])]]
    lines: list[str] = []
    for season, hno, date, water in groups:
        cells = [values.get((season, hno, date, water, level)) for level in ("N1", "N2", "N3")]
        if any(cell is None for cell in cells):
            continue
        n1, n2, n3 = (float(cell[2]) for cell in cells if cell is not None)
        run, treatment, _ = cells[2]  # type: ignore[misc]
        common = f"RUN {run} TN {treatment} @HNO@ {hno} DATE {date}"
        lines.extend([
            f"{common} @NG12S@ {math.log1p(n2) - math.log1p(n1):.12g}",
            f"{common} @NG23S@ {math.log1p(n3) - math.log1p(n2):.12g}",
            f"{common} @NGCVS@ {_positive_cv((n1, n2, n3)):.12g}",
        ])
    if not lines:
        raise ValueError("could not derive simulated N-dose-gradient targets")
    target = Path(output_path)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def build_observed_water_response_rows(
    harvest: pd.DataFrame,
    mapping: pd.DataFrame,
    *,
    sigma_floor: float = 0.10,
    response_target: str = "observed_shape",
    contrast_scale: str = "raw_difference",
    harvest_scope: str = "all",
    high_water: str = "W3",
    low_water: str = "W1",
    season_contrasts: Mapping[str, Mapping[str, str]] | None = None,
    nitrogen_levels: Iterable[str] = ("N0", "N1", "N2", "N3"),
    source_variable: str = "CHPDT",
) -> pd.DataFrame:
    """Construct strictly paired within-nitrogen water-yield contrasts.

    For every (season, HNO, DATE, nitrogen_level) the high-water treatment
    yield minus the low-water reference yield (W3 - W1 by default).  Mirrors
    :func:`build_observed_n_response_rows` with the contrast axis swapped.
    """
    response_target = str(response_target).strip().lower()
    if response_target not in {"observed_shape", "monotone_plateau"}:
        raise ValueError(
            "response_target must be observed_shape or monotone_plateau"
        )
    contrast_scale = str(contrast_scale).strip().lower()
    if contrast_scale not in {"log_ratio", "raw_difference"}:
        raise ValueError("contrast_scale must be log_ratio or raw_difference")
    harvest_scope = str(harvest_scope).strip().lower()
    if harvest_scope not in {"all", "terminal"}:
        raise ValueError("harvest_scope must be all or terminal")
    levels = tuple(str(value).strip().upper() for value in nitrogen_levels)
    if not levels or any(value not in {"N0", "N1", "N2", "N3"} for value in levels):
        raise ValueError("nitrogen_levels must be a non-empty subset of N0..N3")
    measured_col, _, _ = _response_source(source_variable)
    sigma_col = f"{measured_col}_SIGMA"
    required = {"@RUN", "TN", "HNO", "DATE", measured_col, sigma_col, "season"}
    missing = required - set(harvest.columns)
    if missing:
        raise ValueError(f"harvest table lacks water-response inputs: {sorted(missing)}")

    high_water = str(high_water).strip().upper()
    low_water = str(low_water).strip().upper()
    contrast_by_season = {
        str(season): (
            str(spec["high_water"]).strip().upper(),
            str(spec["low_water"]).strip().upper(),
        )
        for season, spec in (season_contrasts or {}).items()
    }
    joined = harvest.merge(
        mapping[["season_id", "treatment", "water_level", "nitrogen_level"]],
        left_on=["season", "TN"],
        right_on=["season_id", "treatment"],
        how="inner",
        validate="many_to_one",
    )
    joined = joined.loc[joined["nitrogen_level"].isin(levels)].copy()
    rows: list[dict[str, object]] = []
    keys = ["season", "HNO", "DATE", "nitrogen_level"]
    for (season, hno, date, nitrogen), group in joined.groupby(keys, sort=True):
        season_high, season_low = contrast_by_season.get(
            str(season), (high_water, low_water)
        )
        by_w = group.set_index("water_level")
        if season_low not in by_w.index or season_high not in by_w.index:
            continue
        ref = by_w.loc[season_low]
        cur = by_w.loc[season_high]
        ref_y = float(ref[measured_col])
        cur_y = float(cur[measured_col])
        if ref_y < 0 or cur_y < 0:
            continue
        if response_target == "monotone_plateau" and cur_y < ref_y:
            target_y = ref_y
            target_sigma = float(ref[sigma_col])
            target_source = season_low
        else:
            target_y = cur_y
            target_sigma = float(cur[sigma_col])
            target_source = season_high
        if contrast_scale == "log_ratio":
            observed_contrast = math.log1p(target_y) - math.log1p(ref_y)
            propagated = math.sqrt(
                (target_sigma / (target_y + 1.0)) ** 2
                + (float(ref[sigma_col]) / (ref_y + 1.0)) ** 2
                + float(sigma_floor) ** 2
            )
            sigma_source = "delta_method_ln1p_pair_plus_static_floor"
        else:
            observed_contrast = target_y - ref_y
            propagated = math.sqrt(
                target_sigma**2
                + float(ref[sigma_col]) ** 2
                + float(sigma_floor) ** 2
            )
            sigma_source = "paired_raw_difference_plus_static_floor"
        rows.append(
            {
                "@RUN": int(cur["@RUN"]),
                "TN": int(cur["TN"]),
                "HNO": int(hno),
                "DATE": int(date),
                "WRESPM": observed_contrast,
                "WRESPS": -99.0,
                "WRESPM_SIGMA": propagated,
                "WRESPM_SIGMA_SOURCE": sigma_source,
                "season": str(season),
                "water_level": season_high,
                "nitrogen_level": str(nitrogen),
                "response_target": response_target,
                "target_source_level": target_source,
                "contrast_scale": contrast_scale,
            }
        )
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("water-response objective produced no complete contrasts")
    if harvest_scope == "terminal":
        terminal_hno = result.groupby(
            ["season", "water_level", "nitrogen_level"], sort=False
        )["HNO"].transform("max")
        result = result.loc[result["HNO"].eq(terminal_hno)].reset_index(drop=True)
    return result


def write_simulated_water_response(
    harvest_output: str | Path,
    output_path: str | Path,
    mapping: pd.DataFrame,
    *,
    source_scale: str = "raw",
    contrast_scale: str = "raw_difference",
    harvest_scope: str = "all",
    high_water: str = "W3",
    low_water: str = "W1",
    season_contrasts: Mapping[str, Mapping[str, str]] | None = None,
    nitrogen_levels: Iterable[str] = ("N0", "N1", "N2", "N3"),
    source_variable: str = "CHPDT",
) -> Path:
    """Derive simulated W3-vs-W1 water-yield contrasts from PestHarvest.OUT.

    Output ordering matches :func:`build_observed_water_response_rows`.
    """
    _, _, tagged = _response_source(source_variable)
    source_scale = str(source_scale).strip().lower()
    contrast_scale = str(contrast_scale).strip().lower()
    harvest_scope = str(harvest_scope).strip().lower()
    if source_scale not in {"raw", "log1p"}:
        raise ValueError("source_scale must be raw or log1p")
    if contrast_scale not in {"log_ratio", "raw_difference"}:
        raise ValueError("contrast_scale must be log_ratio or raw_difference")
    if harvest_scope not in {"all", "terminal"}:
        raise ValueError("harvest_scope must be all or terminal")
    levels = tuple(str(value).strip().upper() for value in nitrogen_levels)
    if not levels or any(value not in {"N0", "N1", "N2", "N3"} for value in levels):
        raise ValueError("nitrogen_levels must be a non-empty subset of N0..N3")
    if contrast_scale == "raw_difference" and source_scale != "raw":
        raise ValueError("raw_difference requires raw cumulative-harvest source values")
    high_water = str(high_water).strip().upper()
    low_water = str(low_water).strip().upper()
    contrast_by_season = {
        str(season): (
            str(spec["high_water"]).strip().upper(),
            str(spec["low_water"]).strip().upper(),
        )
        for season, spec in (season_contrasts or {}).items()
    }

    lookup = {
        int(row.global_run): (
            str(row.season_id), str(row.water_level), str(row.nitrogen_level),
            int(row.treatment),
        )
        for row in mapping.itertuples(index=False)
    }
    values: dict[tuple[str, int, int, str, str], tuple[int, int, float]] = {}
    for line in Path(harvest_output).read_text(encoding="utf-8").splitlines():
        match = tagged.search(line)
        if match is None:
            continue
        run = int(match.group("run"))
        if run not in lookup:
            continue
        season, water, nitrogen, treatment = lookup[run]
        if nitrogen not in levels:
            continue
        values[(season, int(match.group("hno")), int(match.group("date")), water, nitrogen)] = (
            run, treatment, float(match.group("value"))
        )

    lines: list[str] = []
    # values keys are (season, hno, date, water, nitrogen); group by the
    # within-nitrogen axis (season, hno, date, nitrogen) so W3/W1 pair up.
    groups = sorted({(k[0], k[1], k[2], k[4]) for k in values})
    if harvest_scope == "terminal":
        terminal: dict[tuple[str, str], tuple[int, int]] = {}
        for season, hno, date, nitrogen in groups:
            key = (season, nitrogen)
            if key not in terminal or (hno, date) > terminal[key]:
                terminal[key] = (hno, date)
        groups = [
            group for group in groups
            if (group[1], group[2]) == terminal[(group[0], group[3])]
        ]
    for season, hno, date, nitrogen in groups:
        season_high, season_low = contrast_by_season.get(
            str(season), (high_water, low_water)
        )
        ref = values.get((season, hno, date, season_low, nitrogen))
        if ref is None:
            continue
        cur = values.get((season, hno, date, season_high, nitrogen))
        if cur is None:
            continue
        run, treatment, value = cur
        if contrast_scale == "log_ratio":
            contrast = (
                value - ref[2]
                if source_scale == "log1p"
                else math.log1p(value) - math.log1p(ref[2])
            )
        else:
            contrast = value - ref[2]
        lines.append(
            f"RUN {run} TN {treatment} @HNO@ {hno} DATE {date} "
            f"@WRESPS@ {contrast:.12g}"
        )
    if not lines:
        raise ValueError("could not derive simulated water-response contrasts")
    target = Path(output_path)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


__all__ = [
    "PEST_N_DOSE_GRADIENT_FILE",
    "PEST_N_RESPONSE_FILE",
    "PEST_W_RESPONSE_FILE",
    "build_observed_n_dose_gradient_rows",
    "build_observed_n_response_rows",
    "build_observed_water_response_rows",
    "derive_filex_water_n_mapping",
    "load_n_response_mapping",
    "validate_mapping_against_filex",
    "write_simulated_n_dose_gradient",
    "write_simulated_n_response",
    "write_simulated_water_response",
]
