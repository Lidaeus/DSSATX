"""Three-season DSSAT dynamics diagnostic plots (Python run-diagnostics track).

Outputs ``timeseries_*`` / ``scatter_*`` / ``residual_*`` / ``bar_*`` PNGs only.
These are **run diagnostics**, never ``Fig``/``FigS`` (the paper track lives in
``paper/R/``). See AGENTS.md "双轨制图规则".

Design decisions (per the 2026-08-01 figure review):
  * Treatment organization uses Water x Nitrogen x Season, never raw Trno, since
    the three seasons use different Trno encodings (handled via the season map
    CSV). 25SP TN9 (lone W2) and TN14 (lone CK) are dropped for a clean W3/W1
    x N0..N3 factorial.
  * Continuous states (LAI, LWAD, SWAD): the daily PlantGro.OUT trajectory is
    drawn as a raw solid line (NO PCHIP/smoothing overlay). Observed means are
    points; error bars (+/-1 SE) come from the PEST-IES observation registry's
    ``raw_sigma``.
  * Cumulative harvest: the renderer first validates PlantGro.OUT ``GWAD`` as a
    possible continuous cumulative dry-fruit trajectory.  It is accepted only
    when it is monotone and on a plausible scale relative to FreshWt.OUT
    ``CHPDT``.  Otherwise the renderer uses the auditable FreshWt reconstruction
    (harvested fruit + on-plant fruit) and labels it as a visual proxy.  Metrics
    always use the raw harvest-day cumulative nodes, never either visual curve.
  * Scatter stats box reports RMSE / RRMSE / d / R^2 / NSE / MAE; the
    systematic/unsystematic MSE decomposition (MSE_s, MSE_u, MSE_s/MSE) is
    written to a side CSV, not drawn.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re

import matplotlib as _mpl

# Editable text in any exported vector (defensive; diagnostics are PNG-only per
# the dual-track rule, but keep exports consistent with publication settings).
_mpl.rcParams.update({"svg.fonttype": "none", "pdf.fonttype": 42,
                      "font.family": "sans-serif",
                      "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"]})

import numpy as np
import pandas as pd


# Dry-matter content used only for the *visual* fruit-weight interpolation of
# the cumulative-harvest curve. Matches the calibration run name ``dmc5``.
_VISUAL_DMC = 0.05

# 25SP TN9 (lone W2 treatment) and TN14 (lone CK) are excluded to keep a clean
# W3/W1 x N0..N3 factorial across all three seasons.
_EXCLUDE_TN = {("25SP", 9), ("25SP", 14)}
_INCLUDE_ALL_TREATMENTS = False
_ALL_TREATMENT_IDS = {
    "25SP": {2, 3, 4, 5, 9, 10, 11, 12, 13, 14},
    "25FA": set(range(1, 13)),
    "26SP": set(range(1, 13)),
}

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAPPING_CSV = os.path.join(ROOT, "configs", "runs", "e02_from_scratch_water_n_mapping_20260826.csv")

# Canonical publication palette / shapes (water -> shape, nitrogen -> color).
WATER_MARKERS = {"W3": "o", "W2": "s", "W1": "^", "CK": "D"}
NITROGEN_COLORS = {"N3": "#c0392b", "N2": "#e67e22", "N1": "#2980b9", "N0": "#7f8c8d"}
WATER_ORDER = ["W3", "W2", "W1", "CK"]
NITROGEN_ORDER = ["N3", "N2", "N1", "N0"]
SEASON_COLORS = {"25SP": "#1f77b4", "25FA": "#2ca02c", "26SP": "#d62728"}
SEASON_ORDER = ["25SP", "25FA", "26SP"]
SEASON_LABELS = {"25SP": "2025 Spring", "25FA": "2025 Autumn", "26SP": "2026 Spring"}


# --------------------------------------------------------------------------- #
# Data loading helpers
# --------------------------------------------------------------------------- #
def _load_season_map(season_id):
    """Return {trno: (water, nitrogen)} for a season from the canonical CSV."""
    if not os.path.exists(MAPPING_CSV):
        return {}
    df = pd.read_csv(MAPPING_CSV, encoding="utf-8-sig")
    sub = df[df["season_id"].astype(str) == str(season_id)]
    return {int(r["treatment"]): (str(r["water_level"]), str(r["nitrogen_level"]))
            for _, r in sub.iterrows()}


def _wn_for(tn, season_id):
    m = _load_season_map(season_id)
    if int(tn) in m:
        return m[int(tn)]
    if _INCLUDE_ALL_TREATMENTS:
        return (f"TN{int(tn)}", "unmapped")
    return ("?", "?")


def _excluded(season_id, tn):
    return (not _INCLUDE_ALL_TREATMENTS) and (str(season_id), int(tn)) in _EXCLUDE_TN


def _as_num(s):
    try:
        return pd.to_numeric(s, errors="coerce")
    except Exception:
        return pd.Series([np.nan] * len(s))


def _var_unit(name):
    return {
        "LAID": r"m$^2$ m$^{-2}$", "LAIX": r"m$^2$ m$^{-2}$",
        "LWAD": r"g m$^{-2}$", "SWAD": r"g m$^{-2}$", "RWAD": r"g m$^{-2}$",
        "DRY_CUM": r"kg ha$^{-1}$", "FRESH_CUM": r"kg ha$^{-1}$",
        "DRY_INC": r"kg ha$^{-1}$", "FRESH_INC": r"kg ha$^{-1}$",
    }.get(str(name).upper().replace("OBS_", "").replace("SIM_", ""), "")


def _yyddd_to_date(yyddd):
    """DSSAT yyddd (e.g. 25140 or 26006) -> datetime.date (handles year-cross)."""
    try:
        v = int(float(yyddd))
    except Exception:
        return None
    yy, doy = v // 1000, v % 1000
    year = 2000 + yy if yy < 70 else 1900 + yy
    return _dt.date(year, 1, 1) + _dt.timedelta(days=doy - 1)


def _parse_outfile(path, want_cols):
    """Parse a DSSAT *RUN-blocked .OUT file -> DataFrame with TN + want_cols.

    Header ``@YEAR`` columns keep the leading ``@`` stripped. Data rows may be
    indented (leading whitespace) in some DSSAT builds.
    """
    rows, tn, hdr = [], None, None
    pending_run = False
    with open(path, "r") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s.startswith("*RUN"):
                # DSSAT 4.8 may wrap the experiment/treatment suffix onto the
                # following line.  Do not keep the previous TN while waiting
                # for the continuation, otherwise all later runs can be
                # silently assigned to the first treatment.
                m = re.search(r"XXQL\d+\s+(\d+)", s)
                if m:
                    tn = int(m.group(1))
                    pending_run = False
                else:
                    pending_run = True
                hdr = None
                continue
            if pending_run:
                m = re.search(r"XXQL\d+\s+(\d+)", s)
                if m:
                    tn = int(m.group(1))
                    pending_run = False
                continue
            if s.startswith("@YEAR"):
                hdr = [c.lstrip("@") for c in s.split()]
                continue
            if hdr is not None and s[:4].isdigit():
                parts = s.split()
                if len(parts) >= len(hdr):
                    rows.append(dict(zip(hdr, parts)) | {"TN": tn})
    if not rows:
        return None
    df = pd.DataFrame(rows)
    for c in want_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _read_plantgro(run_dir):
    return _parse_outfile(os.path.join(run_dir, "PlantGro.OUT"),
                          ["YEAR", "DOY", "DAS", "DAP", "LAID", "LWAD", "SWAD",
                           "GWAD", "GWGD", "CWAD"])


def _read_freshwt(run_dir):
    return _parse_outfile(os.path.join(run_dir, "FreshWt.OUT"),
                          ["YEAR", "DOY", "DAS", "DAP", "CHPDT", "CHFPW",
                           "TOFPW", "HPODW", "HFPOW"])


def _load_obs_sigma(registry_csv, season_id):
    """Load per-(treatment, variable, date) observation SE from the PEST-IES
    observation registry. Returns a DataFrame keyed for joins.

    ``obgnme`` encodes season + variable + date/harvest suffix, e.g.
    ``25SP_LAIDM_D25120`` or ``25SP_CHPDTM_H1``. We split the trailing token
    to recover a comparable DATE / harvest key.
    """
    if not registry_csv or not os.path.exists(registry_csv):
        return None
    df = pd.read_csv(registry_csv, encoding="utf-8-sig")
    df = df[df["season_id"].astype(str) == str(season_id)].copy()
    # Variable token: middle segment of obgnme, e.g. 25SP_LAIDM_D25120 -> LAIDM.
    # Strip the trailing M (mean) to recover the DSSAT var name (LAID). Some
    # obgnme values (phenology: 25SP_PDAPM) have only 2 parts and no date token;
    # those get variable=PDAP, DATE/HNO=None and are simply unused downstream.

    def _parse_obgnme(obg):
        parts = str(obg).split("_")
        var = parts[1] if len(parts) >= 2 else None
        var_clean = var[:-1] if (var and var.endswith("M")) else var
        date = hno = None
        if len(parts) >= 3:
            tail = parts[-1]
            if tail.startswith("D") and tail[1:].isdigit():
                date = int(tail[1:])
            elif tail.startswith("H") and tail[1:].isdigit():
                hno = int(tail[1:])
        return var_clean, date, hno

    parsed = df["obgnme"].apply(_parse_obgnme).tolist()
    df["variable"] = [p[0] for p in parsed]
    df["DATE"] = [p[1] for p in parsed]
    df["HNO"] = [p[2] for p in parsed]
    df["TN"] = pd.to_numeric(df.get("treatment"), errors="coerce").astype("Int64")
    return df[["TN", "variable", "DATE", "HNO", "raw_obsval", "raw_sigma"]]


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def _metrics(obs, sim):
    """RMSE, RRMSE(%), d-index, R^2, NSE, MAE for paired finite values.

    Accepts pandas Series or numpy arrays. RRMSE = 100 * RMSE / |mean(obs)|.
    d = 1 - sum((s-o)^2) / sum((|s-mean_o|+|o-mean_o|)^2).
    R^2 = squared Pearson correlation.
    """
    o = pd.to_numeric(pd.Series(obs), errors="coerce")
    s = pd.to_numeric(pd.Series(sim), errors="coerce")
    m = (~o.isna()) & (~s.isna()) & (o > -90.0) & (s > -90.0)
    n = int(m.sum())
    if n == 0:
        return {"n": 0}
    o, s = o[m].astype(float).to_numpy(), s[m].astype(float).to_numpy()
    diff = s - o
    rmse = float(np.sqrt(np.mean(diff ** 2)))
    mean_o = float(np.mean(o))
    rrmse = float(100.0 * rmse / abs(mean_o)) if mean_o != 0 else float("nan")
    denom = float(np.sum((np.abs(s - mean_o) + np.abs(o - mean_o)) ** 2))
    d = float(1.0 - np.sum(diff ** 2) / denom) if denom > 0 else float("nan")
    ss_res = float(np.sum(diff ** 2))
    ss_tot_o = float(np.sum((o - mean_o) ** 2))
    nse = float(1.0 - ss_res / ss_tot_o) if ss_tot_o > 0 else float("nan")
    if n > 1 and ss_tot_o > 1e-12:
        ss_tot_s = float(np.sum((s - np.mean(s)) ** 2))
        cov = float(np.sum((o - mean_o) * (s - np.mean(s))))
        dr = np.sqrt(ss_tot_o * ss_tot_s)
        r2 = float((cov / dr) ** 2) if dr > 0 else float("nan")
    else:
        r2 = float("nan")
    return {"n": n, "RMSE": rmse, "RRMSE": rrmse, "d": d, "R2": r2,
            "NSE": nse, "MAE": float(np.mean(np.abs(diff)))}


def _mse_decomposition(obs, sim):
    """Systematic / unsystematic MSE split via OLS fit S = a + b*O.

    MSE_s = mean((fit - O)^2), MSE_u = mean((S - fit)^2), MSE = MSE_s + MSE_u.
    Per the project spec this goes to a side CSV (error-source audit), not on
    the figure. Returns a dict; empty if too few points.
    """
    o = pd.to_numeric(pd.Series(obs), errors="coerce")
    s = pd.to_numeric(pd.Series(sim), errors="coerce")
    m = (~o.isna()) & (~s.isna()) & (o > -90.0) & (s > -90.0)
    if int(m.sum()) < 3:
        return {}
    o, s = o[m].astype(float).to_numpy(), s[m].astype(float).to_numpy()
    b, a = np.polyfit(o, s, 1)
    fit = a + b * o
    mse_s = float(np.mean((fit - o) ** 2))
    mse_u = float(np.mean((s - fit) ** 2))
    mse = mse_s + mse_u
    return {"MSE": mse, "MSE_s": mse_s, "MSE_u": mse_u,
            "MSE_s_ratio": float(mse_s / mse) if mse > 0 else float("nan"),
            "slope": float(b), "intercept": float(a), "n": int(m.sum())}


# --------------------------------------------------------------------------- #
# Cumulative-harvest visual interpolation (fruit-weight based)
# --------------------------------------------------------------------------- #
def _fruit_weight_curve(dap, on_plant_dry, harvested_cum, on_plant_fresh=None,
                        harvested_cum_fresh=None, kind="cum_dry"):
    """Smooth, monotone *visual* cumulative-harvest curve from daily DSSAT data.

    The raw ``harvested_cum + on_plant`` series is daily but sawtooths DOWN on
    harvest days (fruit removed). A plain cummax flattens between harvests (the
    plant needs days to re-grow past the last peak). Instead we keep only the
    running peaks (new highs) and PCHIP-interpolate across the daily DAP grid,
    producing a smooth monotone curve that follows the genuine daily re-growth
    between harvest events. Purely visual — never used in any metric.

    Returns the curve evaluated on ``dap``, or None if infeasible / non-monotone.
    """
    from scipy.interpolate import PchipInterpolator
    if kind == "cum_dry":
        harvested = np.asarray(harvested_cum, dtype=float)
        on_plant = np.asarray(on_plant_dry, dtype=float).copy()
    else:  # cum_fresh
        if on_plant_fresh is None or harvested_cum_fresh is None:
            return None
        harvested = np.asarray(harvested_cum_fresh, dtype=float)
        on_plant = np.asarray(on_plant_fresh, dtype=float).copy()

    # FreshWt.OUT writes the harvest increment and the pre-harvest on-plant
    # fruit on the same DAP.  Adding both values therefore double-counts the
    # fruit removed on that day and creates the large artificial jump seen at
    # the first harvest.  Use the next day's post-harvest on-plant state for a
    # harvest row; if the harvest is the final row, use zero because no
    # post-harvest state is available.  This correction affects the diagnostic
    # display only, never the raw harvest-event metrics.
    event = np.r_[False, np.diff(harvested) > 1e-9]
    for i in np.flatnonzero(event):
        if i + 1 < len(on_plant):
            on_plant[i] = on_plant[i + 1]
        else:
            on_plant[i] = 0.0

    raw = harvested + on_plant
    dap = np.asarray(dap, dtype=float)
    if len(dap) < 4:
        return None
    peak_mask = raw == np.maximum.accumulate(raw)
    peak_idx = np.where(peak_mask)[0]
    if len(peak_idx) < 2:
        return None
    xp, yp = dap[peak_idx], raw[peak_idx]
    if np.any(np.diff(yp) < -1e-9):  # monotone gate (peaks are by construction)
        return None
    try:
        pchip = PchipInterpolator(xp, yp)
    except Exception:
        return None
    # Evaluate on the full daily grid.  Do not extrapolate beyond the last
    # observed running peak: PCHIP extrapolation can create an artificial
    # terminal drop to the first value after the final harvest.  Holding the
    # last peak is the conservative visual representation when no later
    # regrowth peak exists.
    curve = pchip(dap, extrapolate=False)
    curve = np.asarray(curve, dtype=float)
    curve[dap < xp[0]] = yp[0]
    curve[dap > xp[-1]] = yp[-1]
    curve = np.clip(curve, yp.min(), yp.max())
    return curve


def _cumulative_fruit_curve(pg_tn, fw_tn, kind="cum_dry"):
    """Select a cumulative fruit trajectory and return an audit record.

    ``GWAD`` is not assumed to have the same semantics in every DSSAT crop
    module/build.  For a dry-mass curve it is used directly only when the
    observed output is finite, non-decreasing and plausibly comparable with
    the same-treatment ``CHPDT`` scale.  No undocumented unit conversion is
    applied.  If the gate fails, the function falls back to the existing
    FreshWt-based visual reconstruction, which explicitly combines harvested
    and on-plant fruit mass.

    Returns ``(dap, curve, source_label, audit)``.  The curve is diagnostic
    presentation only and must never be fed into model metrics.
    """
    audit = {
        "kind": kind,
        "source": "none",
        "reason": "no_valid_curve",
        "n_curve": 0,
        "gwad_min_delta": np.nan,
        "gwad_final": np.nan,
        "chpdt_final": np.nan,
        "gwad_to_chpdt_ratio": np.nan,
        "harvest_rows_adjusted": 0,
        "harvest_day_alignment": "not_applicable",
    }
    pg_tn = pg_tn.sort_values("DAP").copy() if pg_tn is not None else pd.DataFrame()
    fw_tn = fw_tn.sort_values("DAP").copy() if fw_tn is not None else pd.DataFrame()

    # Candidate A: direct PlantGro GWAD for dry fruit only.  The scale gate is
    # deliberately conservative: if GWAD is a different DSSAT state/unit, it
    # must not be silently rescaled into a yield curve.
    if kind == "cum_dry" and not pg_tn.empty and "GWAD" in pg_tn.columns:
        g = pg_tn[["DAP", "GWAD"]].copy()
        g["DAP"] = pd.to_numeric(g["DAP"], errors="coerce")
        g["GWAD"] = pd.to_numeric(g["GWAD"], errors="coerce")
        g = g.replace([np.inf, -np.inf], np.nan).dropna().drop_duplicates("DAP")
        if len(g) >= 4:
            gv = g["GWAD"].to_numpy(dtype=float)
            min_delta = float(np.diff(gv).min())
            audit["gwad_min_delta"] = min_delta
            audit["gwad_final"] = float(gv[-1])
            if not fw_tn.empty and "CHPDT" in fw_tn.columns:
                ch = pd.to_numeric(fw_tn["CHPDT"], errors="coerce").dropna()
                if len(ch) and float(ch.iloc[-1]) > 0:
                    audit["chpdt_final"] = float(ch.iloc[-1])
                    audit["gwad_to_chpdt_ratio"] = float(gv[-1] / ch.iloc[-1])
            reasons = []
            if min_delta < -1e-6:
                reasons.append("GWAD_nonmonotone")
            ratio = audit["gwad_to_chpdt_ratio"]
            if np.isfinite(ratio) and not (0.25 <= ratio <= 4.0):
                reasons.append("GWAD_scale_incompatible_with_CHPDT")
            if not reasons:
                audit.update({
                    "source": "plantgro_gwad",
                    "reason": "passed_monotonicity_and_scale_gate",
                    "n_curve": int(len(g)),
                })
                return (g["DAP"].to_numpy(dtype=float), gv,
                        "PlantGro GWAD (validated direct output)", audit)
            audit["reason"] = ";".join(reasons)
        else:
            audit["reason"] = "GWAD_too_few_finite_points"
    elif kind == "cum_dry":
        audit["reason"] = "GWAD_unavailable"

    # Candidate B: FreshWt reconstruction.  This is the explicit fallback and
    # is marked visual-only because it includes fruit still on the plant.
    if not fw_tn.empty and "TOFPW" in fw_tn.columns:
        ft = fw_tn.copy()
        ft["DAP"] = pd.to_numeric(ft["DAP"], errors="coerce")
        ft["TOFPW"] = pd.to_numeric(ft["TOFPW"], errors="coerce")
        ft = ft.replace([np.inf, -np.inf], np.nan).dropna(subset=["DAP", "TOFPW"])
        ft = ft[ft["TOFPW"] > 0].drop_duplicates("DAP").sort_values("DAP")
        if len(ft) >= 4:
            if kind == "cum_dry" and {"CHPDT", "TOFPW"}.issubset(ft.columns):
                hcum = pd.to_numeric(ft["CHPDT"], errors="coerce").to_numpy(dtype=float)
                audit["harvest_rows_adjusted"] = int(np.sum(np.diff(hcum) > 1e-9))
                audit["harvest_day_alignment"] = "next_day_postharvest_onplant"
                curve = _fruit_weight_curve(
                    ft["DAP"].to_numpy(dtype=float),
                    ft["TOFPW"].to_numpy(dtype=float) * _VISUAL_DMC,
                    hcum,
                    kind="cum_dry",
                )
                label = "FreshWt reconstruction: CHPDT + TOFPW×DMC (visual)"
            elif kind == "cum_fresh" and {"CHFPW", "TOFPW"}.issubset(ft.columns):
                hcum = pd.to_numeric(ft["CHFPW"], errors="coerce").to_numpy(dtype=float)
                audit["harvest_rows_adjusted"] = int(np.sum(np.diff(hcum) > 1e-9))
                audit["harvest_day_alignment"] = "next_day_postharvest_onplant"
                curve = _fruit_weight_curve(
                    ft["DAP"].to_numpy(dtype=float), None, None,
                    on_plant_fresh=ft["TOFPW"].to_numpy(dtype=float),
                    harvested_cum_fresh=hcum,
                    kind="cum_fresh",
                )
                label = "FreshWt reconstruction: CHFPW + TOFPW (visual)"
            else:
                curve = None
                label = ""
            if curve is not None:
                audit.update({
                    "source": "freshwt_reconstruction",
                    "reason": audit["reason"] if kind == "cum_dry" else "GWAF_unavailable_in_PlantGro",
                    "n_curve": int(len(curve)),
                })
                return (ft["DAP"].to_numpy(dtype=float), np.asarray(curve, dtype=float), label, audit)
            audit["reason"] += ";FreshWt_reconstruction_failed"
        else:
            audit["reason"] += ";FreshWt_too_few_points"
    else:
        audit["reason"] += ";FreshWt_unavailable"
    return None, None, "", audit


# --------------------------------------------------------------------------- #
# Plot helpers
# --------------------------------------------------------------------------- #
def _ensure_dir(p):
    os.makedirs(p, exist_ok=True)
    return p


def _wn_grid(season_id):
    """Ordered list of (water, nitrogen, [tn]) present in this season, W3..W1 x N3..N0."""
    m = _load_season_map(season_id)
    rows = []
    for w in WATER_ORDER:
        for n in NITROGEN_ORDER:
            tns = [tn for tn, (ww, nn) in m.items() if ww == w and nn == n and not _excluded(season_id, tn)]
            if tns:
                rows.append((w, n, tns))
    if _INCLUDE_ALL_TREATMENTS:
        mapped = _ALL_TREATMENT_IDS.get(str(season_id), set(m))
        present = set()
        for _, _, tns in rows:
            present.update(int(tn) for tn in tns)
        for tn in sorted(mapped - present):
            rows.append((f"TN{tn}", "unmapped", [tn]))
    return rows


def _style_for(wn_pair):
    return WATER_MARKERS.get(wn_pair[0], "x"), NITROGEN_COLORS.get(wn_pair[1], "#555")


def _wn_legend_handles(seasons_present=None):
    from matplotlib.lines import Line2D
    h = [Line2D([0], [0], marker=WATER_MARKERS[w], color="w",
                markerfacecolor="#555", markeredgecolor="k", markersize=7,
                linestyle="None", label=f"{w} water") for w in WATER_ORDER]
    h += [Line2D([0], [0], marker="o", color="w", markerfacecolor=NITROGEN_COLORS[n],
                 markeredgecolor="k", markersize=7, linestyle="None", label=f"{n} nitrogen")
          for n in NITROGEN_ORDER]
    return h


def _season_legend_handles(seasons_present):
    from matplotlib.lines import Line2D
    return [Line2D([0], [0], color=SEASON_COLORS[s], lw=1.6, label=SEASON_LABELS.get(s, s))
            for s in SEASON_ORDER if s in seasons_present]


def _filter_pairs(df, obs_col, sim_col):
    o, s = _as_num(df.get(obs_col)), _as_num(df.get(sim_col))
    ok = np.isfinite(o) & np.isfinite(s) & (o > -90.0) & (s > -90.0)
    return df.loc[ok].copy(), o.loc[ok].astype(float), s.loc[ok].astype(float)


# --------------------------------------------------------------------------- #
# Cross-season overlay time series (LAI / biomass / cumulative harvest)
# --------------------------------------------------------------------------- #
def _to_yyddd(year, doy):
    """Normalize a (year, doy) pair to DSSAT 2-digit yyddd (e.g. 25120, 26006)."""
    yy = int(year)
    yy = yy - 2000 if yy >= 2000 else (yy - 1900 if yy >= 100 else yy)
    return yy * 1000 + int(doy)


def _yyddd_to_dap_lookup(daily_df):
    """Map DSSAT yyddd (e.g. 25120, year-cross-safe) -> DAP for one treatment's
    daily frame. Handles both 4-digit (2025) and 2-digit (25) YEAR columns by
    normalizing to 2-digit yyddd, matching the compare CSV's DATE encoding.
    """
    if daily_df is None or daily_df.empty:
        return {}
    yy = daily_df.get("YEAR")
    if yy is None:
        return {}
    code = [_to_yyddd(y, d) for y, d in zip(yy.astype(int), daily_df["DOY"].astype(int))]
    return dict(zip(code, daily_df["DAP"].astype(int)))


def _plot_dynamics_single_season(season_data, season_id, variable, kind, out_png,
                                 registry_csv, y_label, title, curve_audit=None):
    """One panel per WxN cell for a SINGLE season: simulated line + obs points.

    X axis is **DAP (days after planting)**. All panels share the SAME x and y
    axis range (sharex/sharey=True) so treatment differences are not visually
    exaggerated by independent axis scaling — readers can compare panels directly.
    ``kind`` in {"process", "cum_dry", "cum_fresh"}.
    """
    import matplotlib.pyplot as plt

    cells = _wn_grid(season_id)
    cells = [(w, n, tns[0]) for (w, n, tns) in cells if tns]
    if not cells:
        return None
    sd = season_data
    reg = _load_obs_sigma(registry_csv, season_id) if registry_csv else None

    ncols = 5 if len(cells) == 10 else min(4, len(cells))
    nrows = int(np.ceil(len(cells) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(3.4 * ncols, 2.7 * nrows),
                             dpi=150, sharex=True, sharey=True)
    axes = np.array(axes).reshape(-1)

    for i, (w, n, tn) in enumerate(cells):
        ax = axes[i]
        mk, base_col = _style_for((w, n))

        if kind == "process":
            pg = sd["plantgro"]
            if pg is not None:
                d = pg[(pg["TN"] == tn) & pg[variable].notna() & (pg[variable] > 0)].sort_values("DAP")
                if not d.empty:
                    ax.plot(d["DAP"].to_numpy(), d[variable].to_numpy(),
                            color="#1f3a93", lw=1.3, alpha=0.9)
            cmp = sd["compare"]
            obs = cmp[cmp["TN"] == tn]
            o = _as_num(obs.get(f"OBS_{variable}"))
            ok = o.notna() & (o > -90.0)
            if ok.any() and pg is not None:
                lut = _yyddd_to_dap_lookup(pg[pg["TN"] == tn])
                dcode = obs.loc[ok, "DATE"].astype(int)
                dap = np.array([lut.get(int(c), np.nan) for c in dcode])
                fin = np.isfinite(dap)
                if fin.any():
                    yerr = None
                    if reg is not None:
                        r = reg[(reg["TN"] == tn) & (reg["variable"] == variable)].set_index("DATE")
                        yerr = r.reindex(dcode[fin])["raw_sigma"].to_numpy()
                    ax.errorbar(dap[fin], o.loc[ok].to_numpy()[fin], yerr=yerr,
                                fmt=mk, color=base_col, markerfacecolor=base_col,
                                markeredgecolor="k", markersize=5, ecolor="#303030",
                                elinewidth=0.5, capsize=0, zorder=5)

        else:  # cumulative dry/fresh — continuous model trajectory + event observations
            fw = sd["freshwt"]
            pg = sd["plantgro"]
            pg_tn = pg[pg["TN"] == tn] if pg is not None else None
            fw_tn = fw[fw["TN"] == tn] if fw is not None else None
            curve_dap, curve, curve_label, audit = _cumulative_fruit_curve(
                pg_tn, fw_tn, kind=kind)
            audit.update({"season_id": season_id, "TN": int(tn), "water": w, "nitrogen": n})
            if curve_audit is not None:
                curve_audit.append(audit)
            if curve_dap is not None:
                ax.plot(curve_dap, curve, color="#1f3a93", lw=1.35, alpha=0.95,
                        zorder=3)
            cmp = sd["compare"]
            obs_col = "OBS_DRY_CUM" if kind == "cum_dry" else "OBS_FRESH_CUM"
            o = _as_num(cmp[cmp["TN"] == tn].get(obs_col))
            ok = o.notna() & (o > -90.0)
            if ok.any() and fw is not None:
                lut = _yyddd_to_dap_lookup(fw[fw["TN"] == tn])
                sub = cmp[cmp["TN"] == tn].loc[ok].sort_values("DATE")
                dap = np.array([lut.get(int(c), np.nan) for c in sub["DATE"].astype(int)])
                fin = np.isfinite(dap)
                if fin.any():
                    obs_y = o.reindex(sub.index).to_numpy()[fin]
                    yerr = None
                    if reg is not None:
                        reg_var = "CHPDT" if kind == "cum_dry" else "CHFPW"
                        r = reg[(reg["TN"] == tn) & (reg["variable"] == reg_var)]
                        if not r.empty and "HNO" in sub.columns:
                            yerr = (r.set_index("HNO")
                                      .reindex(sub.loc[fin, "HNO"].astype(int))["raw_sigma"]
                                      .to_numpy(dtype=float))
                            if not np.isfinite(yerr).any():
                                yerr = None
                    # Observations are event samples, not a daily trajectory:
                    # show only points and audited +/-1 SE bars, never a line.
                    ax.errorbar(dap[fin], obs_y, yerr=yerr, fmt=mk,
                                color=base_col, markerfacecolor=base_col,
                                markeredgecolor="k", markersize=5,
                                ecolor="#303030", elinewidth=0.6,
                                capsize=2, linestyle="None", zorder=5)

        ax.set_title(f"{w} × {n}", fontsize=10)
        ax.tick_params(labelsize=8)
        ax.grid(True, alpha=0.25)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)

    for j in range(len(cells), len(axes)):
        axes[j].axis("off")
    # Shared axis labels (only outer, since sharex/sharey).
    for ax in axes[len(cells) - ncols:]:
        ax.set_xlabel("Days after planting", fontsize=9)
    for ax in axes[::ncols]:
        ax.set_ylabel(y_label, fontsize=9)

    from matplotlib.lines import Line2D
    if kind in {"cum_dry", "cum_fresh"}:
        labels_seen = []
        if curve_audit is not None:
            labels_seen = [r.get("source") for r in curve_audit
                           if r.get("season_id") == season_id and r.get("kind") == kind]
        if labels_seen and all(x == "plantgro_gwad" for x in labels_seen):
            model_label = "PlantGro GWAD (validated direct output)"
        elif labels_seen and all(x == "freshwt_reconstruction" for x in labels_seen):
            model_label = ("FreshWt reconstruction (visual): "
                           + ("CHPDT + TOFPW×DMC" if kind == "cum_dry" else "CHFPW + TOFPW"))
        else:
            model_label = "Model continuous fruit-mass trajectory (source varies)"
        handles = [
            Line2D([0], [0], color="#1f3a93", lw=1.6, label=model_label),
        ] + _wn_legend_handles()
        legend_title = "Observed: points ±1 SE; water = shape; nitrogen = color"
        ncol = 4
        subtitle = ("Line = continuous model fruit-mass trajectory; "
                    "points = harvest-event observations ±1 SE")
    else:
        handles = _wn_legend_handles()
        legend_title = "Simulated = blue line | Observed: marker = water, color = nitrogen"
        ncol = min(len(handles), 8)
        subtitle = ""
    fig.legend(handles, [h.get_label() for h in handles], loc="lower center",
               ncol=ncol, fontsize=7.5, frameon=True,
               title=legend_title, title_fontsize=8)
    fig.suptitle(f"{title} — {SEASON_LABELS.get(season_id, season_id)}", fontsize=12)
    if subtitle:
        fig.text(0.5, 0.925, subtitle, ha="center", va="top", fontsize=8,
                 color="#4d4d4d")
    fig.tight_layout(rect=[0, 0.16 if kind in {"cum_dry", "cum_fresh"} else 0.09,
                           1, 0.90 if subtitle else 0.96])
    _ensure_dir(os.path.dirname(out_png))
    fig.savefig(out_png, bbox_inches="tight", dpi=150)
    plt.close(fig)
    return out_png


# --------------------------------------------------------------------------- #
# Cross-season 1:1 scatter + residual
# --------------------------------------------------------------------------- #
def _scatter_cross_season(all_season_data, obs_col, sim_col, variable, out_png, metrics_csv):
    """3-panel 1:1 scatter (one per season), shared equal axes, per-panel metrics.

    Points use the W×N dual encoding (water→marker, nitrogen→color) so treatment
    identity is visible. All three panels share the same x/y range so seasons are
    directly comparable. The shared W×N legend sits to the right of the panels.
    """
    import matplotlib.pyplot as plt
    seasons_present = [s for s in SEASON_ORDER if s in all_season_data]
    if not seasons_present:
        return None

    # Gather per-season points + compute the shared axis range across ALL seasons.
    per_season = {}
    all_o, all_s = [], []
    for s in seasons_present:
        dff, o, s_ = _filter_pairs(all_season_data[s]["compare"], obs_col, sim_col)
        if dff.empty:
            continue
        per_season[s] = (dff, o.to_numpy(), s_.to_numpy())
        all_o.append(o.to_numpy()); all_s.append(s_.to_numpy())
    if not per_season:
        return None
    ao = np.concatenate(all_o); as_ = np.concatenate(all_s)
    vmin = float(min(ao.min(), as_.min())); vmax = float(max(ao.max(), as_.max()))
    pad = 0.05 * (vmax - vmin) if vmax > vmin else 1.0
    lims = [vmin - pad, vmax + pad]
    u = _var_unit(obs_col)

    n_panels = len(per_season)
    fig, axes = plt.subplots(1, n_panels, figsize=(4.2 * n_panels + 1.6, 4.6),
                             dpi=150, sharex=True, sharey=True)
    if n_panels == 1:
        axes = [axes]
    for ax, s in zip(axes, seasons_present):
        if s not in per_season:
            ax.axis("off"); continue
        dff, o, sv = per_season[s]
        # Reset index so positional array indexing aligns with group row positions.
        dff = dff.reset_index(drop=True)
        for tn, g in dff.groupby("TN"):
            w, n = _wn_for(tn, s)
            mk = WATER_MARKERS.get(w, "o")
            ax.scatter(o[g.index.to_numpy()], sv[g.index.to_numpy()], marker=mk,
                       c=NITROGEN_COLORS.get(n, "#555"), edgecolors="k", s=38,
                       alpha=0.8, linewidths=0.4)
        ax.plot(lims, lims, color="gray", ls="--", lw=1.1)  # 1:1
        ax.set_xlim(lims); ax.set_ylim(lims)
        ax.set_aspect("equal", "box")
        ax.set_title(SEASON_LABELS.get(s, s), fontsize=10)
        ax.grid(True, alpha=0.25)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        # per-season metrics box (lower-right of each panel)
        mm = _metrics(o, sv)
        txt = (f"n={mm['n']}\nRMSE={mm['RMSE']:.3g}\nRRMSE={mm['RRMSE']:.1f}%\n"
               f"R²={mm['R2']:.3g}\nNSE={mm['NSE']:.3g}\nd={mm['d']:.3g}\nMAE={mm['MAE']:.3g}")
        ax.text(0.97, 0.03, txt, transform=ax.transAxes, ha="right", va="bottom",
                fontsize=7, family="monospace",
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.85))
    axes[0].set_ylabel(f"Simulated ({u})", fontsize=10)
    # shared x label under the middle/bottom
    fig.text(0.5, 0.02, f"Observed ({u})", ha="center", fontsize=10)

    # Shared W×N legend to the right of the panels (outside the axes).
    from matplotlib.lines import Line2D
    wn_h = _wn_legend_handles()
    fig.legend(wn_h, [h.get_label() for h in wn_h],
               loc="center left", bbox_to_anchor=(0.995, 0.5),
               fontsize=8, frameon=True, title="Treatment\n(marker=water,\ncolor=nitrogen)",
               title_fontsize=8)
    fig.suptitle(f"{variable}: observed vs simulated", fontsize=12, y=0.98)
    fig.tight_layout(rect=[0, 0.05, 0.96, 0.95])
    _ensure_dir(os.path.dirname(out_png))
    fig.savefig(out_png, bbox_inches="tight", dpi=150)
    plt.close(fig)

    # MSE decomposition side CSV (error-source audit, per spec not on-figure).
    rows = []
    all_dec = _mse_decomposition(ao, as_)
    if all_dec:
        rows.append({"scope": "all_seasons", "variable": variable, **all_dec})
    for s in seasons_present:
        if s not in per_season:
            continue
        _, o, sv = per_season[s]
        dec = _mse_decomposition(o, sv)
        if dec:
            rows.append({"scope": s, "variable": variable, **dec})
    if rows:
        pd.DataFrame(rows).to_csv(metrics_csv, index=False)
    return out_png


def _residual_cross_season(all_season_data, obs_col, sim_col, variable, out_png):
    """3-panel residual plot (one per season), shared x/y axes, zero reference line.

    Residual = simulated − observed (positive = overestimate). Shared axes across
    panels so residual magnitude is directly comparable between seasons.
    """
    import matplotlib.pyplot as plt
    seasons_present = [s for s in SEASON_ORDER if s in all_season_data]
    if not seasons_present:
        return None
    per_season = {}
    o_all, res_all = [], []
    for s in seasons_present:
        dff, o, sv = _filter_pairs(all_season_data[s]["compare"], obs_col, sim_col)
        if dff.empty:
            continue
        per_season[s] = (dff, o.to_numpy(), (sv - o).to_numpy())
        o_all.append(o.to_numpy()); res_all.append((sv - o).to_numpy())
    if not per_season:
        return None
    ao = np.concatenate(o_all); ar = np.concatenate(res_all)
    # Symmetric residual y-range so over/underestimate are visually balanced.
    rmax = float(np.nanmax(np.abs(ar)))
    xpad = 0.05 * (ao.max() - ao.min()) if ao.max() > ao.min() else 1.0
    xlims = [float(ao.min()) - xpad, float(ao.max()) + xpad]
    ylims = [-rmax * 1.15, rmax * 1.15]
    u = _var_unit(obs_col)

    n_panels = len(per_season)
    fig, axes = plt.subplots(1, n_panels, figsize=(4.2 * n_panels + 1.6, 4.2),
                             dpi=150, sharex=True, sharey=True)
    if n_panels == 1:
        axes = [axes]
    for ax, s in zip(axes, seasons_present):
        if s not in per_season:
            ax.axis("off"); continue
        dff, o, res = per_season[s]
        dff = dff.reset_index(drop=True)
        for tn, g in dff.groupby("TN"):
            w, n = _wn_for(tn, s)
            mk = WATER_MARKERS.get(w, "o")
            ax.scatter(o[g.index.to_numpy()], res[g.index.to_numpy()], marker=mk,
                       c=NITROGEN_COLORS.get(n, "#555"), edgecolors="k", s=38,
                       alpha=0.75, linewidths=0.4)
        ax.axhline(0, color="gray", ls="--", lw=1.1)
        ax.set_xlim(xlims); ax.set_ylim(ylims)
        ax.set_title(SEASON_LABELS.get(s, s), fontsize=10)
        ax.grid(True, alpha=0.25)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        # per-season bias annotation
        mbe = float(np.mean(res))
        ax.text(0.03, 0.97, f"MBE={mbe:+.3g}\nn={len(res)}", transform=ax.transAxes,
                ha="left", va="top", fontsize=7.5, family="monospace",
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.85))
    axes[0].set_ylabel(f"Simulated − Observed ({u})", fontsize=10)
    fig.text(0.5, 0.02, f"Observed ({u})", ha="center", fontsize=10)

    from matplotlib.lines import Line2D
    wn_h = _wn_legend_handles()
    fig.legend(wn_h, [h.get_label() for h in wn_h],
               loc="center left", bbox_to_anchor=(0.995, 0.5),
               fontsize=8, frameon=True, title="Treatment\n(marker=water,\ncolor=nitrogen)",
               title_fontsize=8)
    fig.suptitle(f"{variable}: residuals (simulated − observed)", fontsize=12, y=0.98)
    fig.tight_layout(rect=[0, 0.05, 0.96, 0.95])
    _ensure_dir(os.path.dirname(out_png))
    fig.savefig(out_png, bbox_inches="tight", dpi=150)
    plt.close(fig)
    return out_png


def _final_response_table(all_season_data, obs_col, sim_col, response):
    """Build one final observation/simulation pair per treatment and season.

    This is an audit of treatment discrimination, not a replacement for the
    full time-series or event-level metrics. Process variables use the last
    available DATE; cumulative dry harvest uses the last HNO/DATE pair.
    """
    rows = []
    for season in SEASON_ORDER:
        if season not in all_season_data:
            continue
        dff, obs, sim = _filter_pairs(all_season_data[season]["compare"], obs_col, sim_col)
        if dff.empty or "TN" not in dff.columns:
            continue
        dff = dff.copy()
        dff["_obs"] = obs.to_numpy()
        dff["_sim"] = sim.to_numpy()
        if response == "DRY_CUM" and "HNO" in dff.columns:
            dff["_sort_hno"] = pd.to_numeric(dff["HNO"], errors="coerce")
            dff["_sort_date"] = pd.to_numeric(dff.get("DATE"), errors="coerce")
            dff = dff.sort_values(["TN", "_sort_hno", "_sort_date"])
        else:
            dff["_sort_date"] = pd.to_numeric(dff.get("DATE"), errors="coerce")
            dff = dff.sort_values(["TN", "_sort_date"])
        final = dff.groupby("TN", as_index=False, sort=False).tail(1)
        for _, row in final.iterrows():
            tn = int(row["TN"])
            water, nitrogen = _wn_for(tn, season)
            if water == "?" or nitrogen == "?":
                continue
            rows.append({
                "season": season,
                "TN": tn,
                "water": water,
                "nitrogen": nitrogen,
                "observed": float(row["_obs"]),
                "simulated": float(row["_sim"]),
            })
    return pd.DataFrame(rows)


def _response_structure_audit(all_proc, all_harv, out_png, metrics_csv):
    """Plot final W×N contrasts and their spread compression by season.

    Filled markers are observations and open markers are simulations; the
    connecting segment exposes the final bias for each treatment. The bottom
    panel reports SD(simulated treatments) / SD(observed treatments), where
    values below one mean that the simulated treatment response is flatter.
    """
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    specs = [
        ("LAID", "LAI", r"m$^2$ m$^{-2}$", all_proc, "OBS_LAID", "SIM_LAID"),
        ("DRY_CUM", "Final cumulative dry fruit", r"kg ha$^{-1}$", all_harv,
         "OBS_DRY_CUM", "SIM_DRY_CUM"),
    ]
    tables = {
        key: _final_response_table(data, obs_col, sim_col, key)
        for key, _, _, data, obs_col, sim_col in specs
    }
    if not any(not x.empty for x in tables.values()):
        return None

    # Lay out only seasons that are actually present in this deterministic
    # replay.  The previous fixed three-column grid left an empty 25FA column
    # in spring-only (22-treatment) diagnostics.
    seasons_present = [
        season for season in SEASON_ORDER
        if any(
            not table.empty and season in set(table["season"].astype(str))
            for table in tables.values()
        )
    ]
    seasons_present.extend(
        season
        for table in tables.values() if not table.empty
        for season in table["season"].astype(str).drop_duplicates()
        if season not in seasons_present
    )
    if not seasons_present:
        return None

    ylims = {}
    for key, _, _, _, _, _ in specs:
        tab = tables[key]
        vals = pd.concat([tab.get("observed", pd.Series(dtype=float)),
                          tab.get("simulated", pd.Series(dtype=float))], ignore_index=True)
        if vals.empty:
            ylims[key] = (0.0, 1.0)
            continue
        lo, hi = float(vals.min()), float(vals.max())
        pad = 0.08 * (hi - lo) if hi > lo else max(abs(hi) * 0.08, 1.0)
        ylims[key] = (lo - pad, hi + pad)

    n_seasons = len(seasons_present)
    fig = plt.figure(figsize=(5.0 * n_seasons, 9.0), dpi=150)
    gs = fig.add_gridspec(3, n_seasons, height_ratios=[1.35, 1.35, 0.9],
                          hspace=0.48, wspace=0.18)
    audit_rows = []
    for row_idx, (key, title, unit, _, _, _) in enumerate(specs):
        tab = tables[key]
        for col_idx, season in enumerate(seasons_present):
            ax = fig.add_subplot(gs[row_idx, col_idx])
            sub = tab[tab["season"] == season].copy()
            if sub.empty:
                ax.axis("off")
                continue
            order = {(w, n): i for i, (w, n, _) in enumerate(_wn_grid(season))}
            sub["_order"] = [order.get((w, n), 999)
                              for w, n in zip(sub["water"], sub["nitrogen"])]
            sub = sub.sort_values("_order").reset_index(drop=True)
            x = np.arange(len(sub), dtype=float)
            for i, r in sub.iterrows():
                color = NITROGEN_COLORS.get(r["nitrogen"], "#555555")
                marker = WATER_MARKERS.get(r["water"], "o")
                ax.plot([x[i], x[i]], [r["observed"], r["simulated"]],
                        color="#aab2bd", lw=1.0, zorder=1)
                ax.scatter(x[i], r["observed"], marker=marker, s=58,
                           facecolor=color, edgecolor="black", linewidth=0.45,
                           zorder=3)
                ax.scatter(x[i], r["simulated"], marker=marker, s=58,
                           facecolor="white", edgecolor=color, linewidth=1.25,
                           zorder=3)
            ax.set_ylim(ylims[key])
            ax.set_xticks(x)
            ax.set_xticklabels([f"{r['water']}×{r['nitrogen']}" for _, r in sub.iterrows()],
                               rotation=45, ha="right", fontsize=7)
            ax.set_title(SEASON_LABELS.get(season, season), fontsize=10)
            ax.grid(True, axis="y", alpha=0.25)
            for sp in ("top", "right"):
                ax.spines[sp].set_visible(False)
            if col_idx == 0:
                ax.set_ylabel(f"{title}\n({unit})", fontsize=9)
            else:
                ax.tick_params(labelleft=False)

            obs_sd = float(sub["observed"].std(ddof=1)) if len(sub) > 1 else np.nan
            sim_sd = float(sub["simulated"].std(ddof=1)) if len(sub) > 1 else np.nan
            ratio = sim_sd / obs_sd if np.isfinite(obs_sd) and obs_sd > 0 else np.nan
            audit_rows.append({
                "season": season, "response": key, "n_treatments": len(sub),
                "observed_sd": obs_sd, "simulated_sd": sim_sd,
                "spread_ratio_sim_over_obs": ratio,
                "observed_range": float(sub["observed"].max() - sub["observed"].min()),
                "simulated_range": float(sub["simulated"].max() - sub["simulated"].min()),
                "mean_bias_sim_minus_obs": float((sub["simulated"] - sub["observed"]).mean()),
            })

    axb = fig.add_subplot(gs[2, :])
    audit = pd.DataFrame(audit_rows)
    positions = np.arange(len(seasons_present), dtype=float)
    width = 0.34
    for j, (key, label, color) in enumerate([
        ("LAID", "LAI", "#3567a8"),
        ("DRY_CUM", "dry fruit", "#b35c3e"),
    ]):
        sub = audit[audit["response"] == key].set_index("season").reindex(seasons_present)
        vals = sub["spread_ratio_sim_over_obs"].to_numpy(dtype=float)
        bars = axb.bar(positions + (j - 0.5) * width, vals, width=width,
                       color=color, alpha=0.88, label=label)
        for bar, val in zip(bars, vals):
            if np.isfinite(val):
                axb.text(bar.get_x() + bar.get_width() / 2, val + 0.035,
                         f"{val:.2f}", ha="center", va="bottom", fontsize=8)
    axb.axhline(1.0, color="#555555", ls="--", lw=1.0)
    axb.set_xticks(positions)
    axb.set_xticklabels([SEASON_LABELS.get(s, s) for s in seasons_present], fontsize=9)
    axb.set_ylabel("Treatment spread ratio\nSD(simulated) / SD(observed)", fontsize=9)
    max_ratio = float(np.nanmax(audit["spread_ratio_sim_over_obs"]))
    axb.set_ylim(0, max(1.15, max_ratio * 1.25))
    axb.grid(True, axis="y", alpha=0.25)
    axb.legend(loc="upper right", frameon=True, fontsize=8, ncol=2)
    axb.text(0.01, 0.95, "<1 = simulated W×N response is compressed",
             transform=axb.transAxes, ha="left", va="top", fontsize=8,
             color="#444444")
    for sp in ("top", "right"):
        axb.spines[sp].set_visible(False)

    handles = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#777777",
               markeredgecolor="black", markersize=7, label="Observed (filled)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="white",
               markeredgecolor="#777777", markersize=7, label="Simulated (open)"),
    ] + _wn_legend_handles()
    fig.legend(handles, [h.get_label() for h in handles], loc="upper center",
               bbox_to_anchor=(0.5, 0.995), ncol=6, fontsize=8,
               frameon=True, title="Filled/open = data role; marker = water; color = nitrogen",
               title_fontsize=8)
    fig.suptitle("Treatment-response structure audit: final LAI and dry fruit",
                 fontsize=13, y=1.04)
    fig.text(0.5, 1.005,
             "Paired segments show final bias; bottom panel tests whether treatment contrasts are preserved.",
             ha="center", va="top", fontsize=9, color="#444444")
    _ensure_dir(os.path.dirname(out_png))
    fig.savefig(out_png, bbox_inches="tight", dpi=150)
    plt.close(fig)
    if not audit.empty:
        audit.to_csv(metrics_csv, index=False)
    return out_png


# --------------------------------------------------------------------------- #
# Incremental harvest bar (per season, WxN faceted) - lollipop-style pairs
# --------------------------------------------------------------------------- #
def _increment_plot(all_season_data, out_png):
    import matplotlib.pyplot as plt
    seasons_present = [s for s in SEASON_ORDER if s in all_season_data]
    nrows = len(seasons_present)
    fig, axes = plt.subplots(nrows, 1, figsize=(9.5, 2.6 * nrows), dpi=150,
                             sharex=False)
    if nrows == 1:
        axes = [axes]
    for ax, season in zip(axes, seasons_present):
        dfh = all_season_data[season]["compare"]
        cells = _wn_grid(season)
        # build a flat ordered treatment list (W3..W1 x N3..N0)
        ordered_tns = [tns[0] for (_, _, tns) in cells]
        ordered_tns = [t for t in ordered_tns if t is not None]
        x_pos, x_labels = [], []
        obs_vals, sim_vals, obs_cols, sim_cols = [], [], [], []
        for tn in ordered_tns:
            w, n = _wn_for(tn, season)
            d = dfh[dfh["TN"] == tn].sort_values("HNO")
            o = _as_num(d.get("OBS_DRY_INC")); si = _as_num(d.get("SIM_DRY_INC"))
            ok = o.notna() & si.notna() & (o > -90) & (si > -90)
            d = d[ok]; o = o[ok].astype(float); si = si[ok].astype(float)
            for k in range(len(d)):
                x_pos.append(len(x_labels))
                x_labels.append(f"{w}×{n}\nH{int(d['HNO'].iloc[k])}")
                obs_vals.append(o.iloc[k]); sim_vals.append(si.iloc[k])
                obs_cols.append(NITROGEN_COLORS.get(n, "#777777")); sim_cols.append("#1f3a93")
        width = 0.38
        ax.bar([x - width / 2 for x in x_pos], obs_vals, width, color=obs_cols,
               edgecolor="k", linewidth=0.4, alpha=0.85, label="OBS")
        ax.bar([x + width / 2 for x in x_pos], sim_vals, width, color=sim_cols,
               edgecolor="k", linewidth=0.4, alpha=0.85, label="SIM")
        ax.set_title(SEASON_LABELS[season], fontsize=10)
        ax.set_ylabel("Dry increment\n(kg ha$^{-1}$)", fontsize=9)
        ax.set_xticks(x_pos)
        ax.set_xticklabels(x_labels, fontsize=6.5, rotation=45, ha="right")
        ax.grid(True, alpha=0.25, axis="y")
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        if ax is axes[0]:
            ax.legend(loc="upper right", fontsize=8)
    fig.suptitle("Incremental dry harvest by event — observed vs simulated", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    _ensure_dir(os.path.dirname(out_png))
    fig.savefig(out_png, bbox_inches="tight", dpi=150)
    plt.close(fig)
    return out_png


# --------------------------------------------------------------------------- #
# Per-season driver
# --------------------------------------------------------------------------- #
def _load_season(season_dir, season_id):
    return {
        "compare_proc": pd.read_csv(os.path.join(season_dir, f"{season_id}_deterministic_process_compare.csv")),
        "compare_harv": pd.read_csv(os.path.join(season_dir, f"{season_id}_deterministic_harvest_compare.csv")),
        "plantgro": _read_plantgro(season_dir),
        "freshwt": _read_freshwt(season_dir),
    }


def main():
    global MAPPING_CSV
    p = argparse.ArgumentParser(
        description="Per-season W×N dynamics diagnostics + cross-season scatter (Python track)")
    p.add_argument("--det-root", required=True,
                   help="deterministic run root (contains _seasons/{25SP,25FA,26SP})")
    p.add_argument("--out-root", required=True, help="output root for PNGs/CSVs")
    p.add_argument("--seasons", default="25SP,25FA,26SP",
                   help="comma-separated seasons to render (default all three)")
    p.add_argument("--registry-csv", default=None,
                   help="PEST-IES observation registry CSV (for SE error bars). "
                        "Default: auto-detect under the run dir if present.")
    p.add_argument("--include-all-treatments", action="store_true",
                   help="Include treatments normally excluded from the clean W x N grid (e.g. 25SP TN9/TN14).")
    p.add_argument("--mapping-csv", default=MAPPING_CSV,
                   help="Explicit season/treatment water-nitrogen mapping CSV.")
    args = p.parse_args()

    global _INCLUDE_ALL_TREATMENTS
    _INCLUDE_ALL_TREATMENTS = bool(args.include_all_treatments)
    MAPPING_CSV = os.path.abspath(args.mapping_csv)

    det_root = os.path.abspath(args.det_root)
    out_root = os.path.abspath(args.out_root)
    _ensure_dir(out_root)
    seasons_req = [s.strip() for s in args.seasons.split(",") if s.strip()]

    registry_csv = args.registry_csv
    if registry_csv is None:
        cand = os.path.join(det_root, "observation_registry.csv")
        if os.path.exists(cand):
            registry_csv = cand

    ref_years = {"25SP": 2025, "25FA": 2025, "26SP": 2026}
    curve_audit_rows = []
    all_proc, all_harv = {}, {}
    for s in seasons_req:
        sdir = os.path.join(det_root, "_seasons", s)
        if not os.path.isdir(sdir):
            print(f"[skip] {s}: no _seasons/{s} dir")
            continue
        loaded = _load_season(sdir, s)
        all_proc[s] = {**loaded, "ref_year": ref_years[s], "compare": loaded["compare_proc"]}
        all_harv[s] = {**loaded, "ref_year": ref_years[s], "compare": loaded["compare_harv"]}
    if not all_proc and not all_harv:
        raise SystemExit("No season data found under _seasons/")

    # --- per-season dynamics -> <out_root>/<season>/ (shared axes within each) ---
    proc_vars = [("LAID", "LAI"), ("LWAD", "leaf dry weight"), ("SWAD", "stem dry weight")]
    for s in seasons_req:
        if s not in all_proc:
            continue
        sdir_out = os.path.join(out_root, s)
        for var, label in proc_vars:
            _plot_dynamics_single_season(
                all_proc[s], s, var, "process",
                os.path.join(sdir_out, f"timeseries_{var}_by_WxN.png"),
                registry_csv, f"{label} ({_var_unit(var)})",
                f"{label}: daily simulation vs observed")
        if s in all_harv:
            _plot_dynamics_single_season(
                all_harv[s], s, "DRY_CUM", "cum_dry",
                os.path.join(sdir_out, "timeseries_dry_cum_by_WxN.png"),
                registry_csv, f"Cumulative dry fruit ({_var_unit('DRY_CUM')})",
                "Cumulative dry fruit: continuous model trajectory vs harvest events",
                curve_audit=curve_audit_rows)
            _plot_dynamics_single_season(
                all_harv[s], s, "FRESH_CUM", "cum_fresh",
                os.path.join(sdir_out, "timeseries_fresh_cum_by_WxN.png"),
                registry_csv, f"Cumulative fresh fruit ({_var_unit('FRESH_CUM')})",
                "Cumulative fresh fruit: continuous model trajectory vs harvest events",
                curve_audit=curve_audit_rows)
            _increment_plot({s: all_harv[s]},
                            os.path.join(sdir_out, "bar_dry_yield_increment.png"))

    # --- cross-season scatter / residual / MSE-decomposition -> <out_root>/ ---
    for var, _label in proc_vars:
        if all_proc:
            _scatter_cross_season(all_proc, f"OBS_{var}", f"SIM_{var}", var,
                                  os.path.join(out_root, f"scatter_{var}.png"),
                                  os.path.join(out_root, f"mse_decomposition_{var}.csv"))
            _residual_cross_season(all_proc, f"OBS_{var}", f"SIM_{var}", var,
                                   os.path.join(out_root, f"residual_{var}.png"))
    if all_harv:
        _scatter_cross_season(all_harv, "OBS_DRY_CUM", "SIM_DRY_CUM", "DRY_CUM",
                              os.path.join(out_root, "scatter_dry_cum.png"),
                              os.path.join(out_root, "mse_decomposition_dry_cum.csv"))
        _scatter_cross_season(all_harv, "OBS_FRESH_CUM", "SIM_FRESH_CUM", "FRESH_CUM",
                              os.path.join(out_root, "scatter_fresh_cum.png"),
                              os.path.join(out_root, "mse_decomposition_fresh_cum.csv"))
        _residual_cross_season(all_harv, "OBS_DRY_CUM", "SIM_DRY_CUM", "DRY_CUM",
                               os.path.join(out_root, "residual_dry_cum.png"))
        _residual_cross_season(all_harv, "OBS_FRESH_CUM", "SIM_FRESH_CUM", "FRESH_CUM",
                               os.path.join(out_root, "residual_fresh_cum.png"))

    # --- response-structure audit: treatment contrasts, not aggregate accuracy ---
    _response_structure_audit(
        all_proc, all_harv,
        os.path.join(out_root, "response_structure_audit.png"),
        os.path.join(out_root, "response_structure_audit.csv"),
    )

    if curve_audit_rows:
        pd.DataFrame(curve_audit_rows).to_csv(
            os.path.join(out_root, "yield_curve_source_audit.csv"),
            index=False, encoding="utf-8-sig")

    print(f"\nDone. Per-season dynamics under <out_root>/<season>/; "
          f"cross-season scatter/residual, response-structure audit and "
          f"yield-curve source audit under <out_root>/.")


if __name__ == "__main__":
    main()
