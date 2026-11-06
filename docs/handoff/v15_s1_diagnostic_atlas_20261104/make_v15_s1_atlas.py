"""Render an auditable diagnostic atlas from a frozen V15 S1 replay."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator

KEY = ["run", "yrdoy"]
WATER = ["W1", "W2", "W3"]
NITROGEN = ["N0", "N1", "N2", "N3"]
MARKER = dict(zip(WATER, ["^", "s", "o"]))
BINARY = "107ec95f443af66eb30d53769496836414131d6befd6ab2f34cd00ef98b137fc"
INK = "#213444"
MUTED = "#566570"
NATIVE = {
    "LAID": ("LAI", "m²/m²"),
    "RDPD": ("根深", "m"),
    "IRRC": ("累计灌溉", "mm"),
    "EPAA": ("实际蒸腾", "mm/d"),
    "WSPD": ("光合水胁迫", "0–1"),
    "WSGD": ("扩展水胁迫", "0–1"),
    "PHAD": ("冠层总光合", "g CH2O/m²/d"),
    "LWAD": ("叶干重", "kg DM/ha"),
    "SWAD": ("茎干重", "kg DM/ha"),
}
FIELDS = {
    **NATIVE,
    "root_potential": ("库存裁剪后潜力", "kg N/ha/d"),
    "dmax_kgN_ha": ("根输入上限 Dmax", "kg N/ha/d"),
    "root_before_c": ("Dmax 后候选吸收", "kg N/ha/d"),
    "root_prepaid": ("碳限后预接受量", "kg N/ha/d"),
    "root_rejected_ha": ("终结算退回", "kg N/ha/d"),
    "root_final": ("最终净吸氮", "kg N/ha/d"),
    "root_cum": ("累计净吸氮", "kg N/ha"),
    "carbon_scale": ("同化碳限比例", "0–1"),
    "assim_paid": ("已结算同化碳", "kg CH2O/ha/d"),
    "assim_refund": ("退回同化碳", "kg CH2O/ha/d"),
    "growth_request_ha": ("新生长需氮", "kg N/ha/d"),
    "repair_request_ha": ("旧组织修复需求", "kg N/ha/d"),
    "refill_request_ha": ("储备补充需求", "kg N/ha/d"),
    "repair": ("实际组织修复", "kg N/ha/d"),
    "fill": ("实际入储", "kg N/ha/d"),
    "fast": ("快速储备动员", "kg N/ha/d"),
    "bound": ("慢速结合氮动员", "kg N/ha/d"),
    "leaf_R": ("叶储备 N", "kg N/ha"),
    "stem_R": ("茎储备 N", "kg N/ha"),
    "leaf_nonreserve": ("叶非储备 N", "kg N/ha"),
    "stem_nonreserve": ("茎非储备 N", "kg N/ha"),
    "root_pool": ("根 N 库存", "kg N/ha"),
    "fruit_pool": ("站存果 N", "kg N/ha"),
    "harvest_N_cum": ("累计采收带走 N", "kg N/ha"),
    "leaf_pct": ("叶总氮浓度", "% DM"),
    "stem_pct": ("茎总氮浓度", "% DM"),
    "canopy_pct": ("茎叶加权总氮浓度", "% DM"),
    "leaf_functional_pct": ("功能叶氮浓度代理", "% 非糖叶干重"),
    "vegetative_nni": ("茎叶 NNI", "比值"),
    "uptake_psi": ("决策态根信号 ψ", "带宽尺度"),
    "psi_raw": ("日终茎叶 ψ", "带宽尺度"),
    "fb_H": ("HATS 反馈重算", "0–1"),
    "fb_L": ("LATS 反馈重算", "0–1"),
    "barrier": ("高氮屏障重算", "0–1"),
    "nstres": ("生长氮因子", "0–1"),
    "photo_factor": ("光合氮因子均值", "0–1"),
    "yield": ("累计采收鲜果", "t/ha"),
    "root_length_area": ("单位地面总根长", "cm 根/cm²"),
    "root_weighted_SW": ("根长加权含水率", "cm³/cm³"),
    "root_weighted_NO3": ("根长加权硝态氮", "mg N/kg 干土"),
    "root_weighted_NH4": ("根长加权铵态氮", "mg N/kg 干土"),
}
OBS_MAP = {"LAID": "LAID", "LWAD": "LWAD", "SWAD": "SWAD", "LEAF_N_PCT": "leaf_pct",
           "STEM_N_PCT": "stem_pct", "CHFPW": "yield", "HFPOW": "yield_event"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf8")


def echo(path):
    header, values = path.read_text().splitlines()[:2]
    return dict(zip(header.removeprefix("@").split(), map(float, values.split()), strict=True))


def freeze(case, source, profile, shared):
    sys.path.insert(0, str(shared))
    from data import harvest_on_crop_grid, merge_daily, native_table

    files = {profile, shared / "data.py", case.parent / "comparison.csv", case.parent / "receipt.json"}
    binary = sha(case / "DSCSM048.EXE")
    if binary != BINARY:
        raise ValueError("Expected frozen V15 S1 executable hash")
    files.add(case / "DSCSM048.EXE")

    def read_csv(name):
        files.add(case / name)
        return pd.read_csv(case / name)

    def native(name):
        files.add(case / name)
        return native_table(case / name)

    d = native("PlantGro.OUT")[KEY + ["treatment", "treatment_label_native", "DAP", "DAS", "NSTD"] +
                               [f for f in NATIVE if f not in {"IRRC", "EPAA", "PHAD"}]]
    d = d.rename(columns={"DAP": "dap"})
    meta = read_csv("treatment_metadata.csv")
    if set(zip(meta.water_level, meta.nitrogen_level)) != {(w, n) for w in WATER for n in NITROGEN}:
        raise ValueError("Expected one explicit treatment for each water × nitrogen cell")
    d = d.merge(meta, on="treatment", validate="many_to_one")
    if len(meta) != 12 or not d.treatment_label.eq(d.treatment_label_native).all():
        raise ValueError("Treatment mapping differs from native labels")
    d["date"] = pd.to_datetime(d.yrdoy.astype(str), format="%Y%j").dt.strftime("%Y-%m-%d")

    for name, field in [("SoilWat.OUT", "IRRC"), ("ET.OUT", "EPAA"), ("PlantC.OUT", "PHAD")]:
        other = native(name)
        d = merge_daily(d, other, [field], name)
    fresh, early = harvest_on_crop_grid(d, native("FreshWt.OUT"))
    d = fresh

    def join(name, columns=None, rename=None):
        nonlocal d
        table = read_csv(name)
        identity = table[KEY + ["trt", "das"]].merge(d[KEY + ["treatment", "DAS"]], on=KEY, validate="one_to_one")
        if len(identity) != len(d) or not identity.trt.eq(identity.treatment).all() or not identity.das.eq(identity.DAS).all():
            raise ValueError(f"{name}: incompatible treatment or date keys")
        if columns is None:
            columns = [c for c in table if c not in KEY + ["trt", "das"]]
        cols = KEY + columns
        table = table[cols].rename(columns=rename or {})
        d = merge_daily(d, table, list(table.columns[2:]), name)

    join("OrganNState.csv")
    join("NFlux.csv")
    join("NDecision.csv", ["total_psi", "uptake_psi", "dmax_kgN_ha", "leaf_ready_n", "stem_ready_n",
                            "leaf_functional_gap", "stem_functional_gap", "leaf_signal_n", "stem_signal_n"])
    join("NAcceptance.csv", ["root_provisional", "root_accepted", "root_rejected", "leaf_cap", "stem_cap",
                             "leaf_fill_limit", "stem_fill_limit", "prepaid_assim_ch2o", "accepted_assim_ch2o",
                             "refunded_assim_ch2o", "internal_n_cancelled"])
    join("NCBalance.csv")
    join("PhotoN.csv")
    layer = read_csv("RootNSupply.csv").merge(d[KEY + ["treatment", "DAS", "dap", "water_level", "nitrogen_level"]],
                                               on=KEY, validate="many_to_one")
    if layer.duplicated(KEY + ["layer"]).any() or not layer.trt.eq(layer.treatment).all() or not layer.das.eq(layer.DAS).all():
        raise ValueError("Root-layer identity mismatch")
    layer_totals = layer.groupby(KEY).agg(
        root_potential=("kinetic_potential_kgN_ha", "sum"),
        root_stock_check=("stock_limited_potential_kgN_ha", "sum"),
        layer_actual=("actual_kgN_ha", "sum"), carbon_scale=("carbon_scale", "first")).reset_index()
    d = merge_daily(d, layer_totals, list(layer_totals.columns[2:]), "RootNSupply.csv")

    files.update(case / f for f in ("CNCParam.OUT", "NBufferParam.OUT", "TMGRO048.SPE", "TMGRO048.ECO",
                                    "TMGRO048.CUL", "SOIL.SOL", "XXQL2601.TMX", "parameters.csv",
                                    "native_precision_audit.json", "injected_inputs.json"))
    files.update([source / "freeze_manifest.json"])
    source_manifest = json.loads((source / "freeze_manifest.json").read_text(encoding="utf8"))
    code = ["NUPTAK.for", "N_BUFFER_V2.f90", "CROPGRO.for", "VEGGR.for", "DEMAND.for", "PODS.for", "PHOTO.for"]
    for key in [f"Plant\\CROPGRO\\{name}" for name in code] + ["SPAM\\ETPHR.for"]:
        path = source / "source" / key
        if sha(path) != source_manifest["source_hashes"][key]:
            raise ValueError(f"Source hash changed: {key}")
        files.add(path)
    if source_manifest["baseline_sha256"] != binary:
        raise ValueError("Archive and source freeze identify different binaries")
    batch = case.parents[3]
    audited_paths = [batch / "final_audit.json", batch / "run_manifest.json"]
    files.update(audited_paths)
    audit = json.loads(audited_paths[0].read_text(encoding="utf8"))
    if Path(audit["selected_replay_trial"]).resolve() != case.parent or audit["binary_sha256"] != binary:
        raise ValueError("Run audit identifies a different best replay")
    params = {**echo(case / "CNCParam.OUT"), **echo(case / "NBufferParam.OUT")}
    if params["ENABLE"] != 1 or params["UPTAKE_MODE"] != 1:
        raise ValueError("Unexpected V15 S1 parameter switches")

    for key, src in {"root_final": "root_actual", "root_prepaid": "root_provisional",
                     "root_rejected_ha": "root_rejected", "assim_paid": "accepted_assim_ch2o",
                     "assim_refund": "refunded_assim_ch2o", "leaf_R": "leaf_reserve", "stem_R": "stem_reserve",
                     "root_pool": "root_n", "fruit_pool": "fruit_n", "growth_request_ha": "growth_request",
                     "repair_request_ha": "repair_request", "refill_request_ha": "refill_request"}.items():
        d[key] = 10 * d[src]
    for key, cols in {"fast": ["leaf_mobilized", "stem_mobilized"], "bound": ["leaf_bound_mobilized", "stem_bound_mobilized"],
                      "repair": ["leaf_repaired", "stem_repaired", "root_repaired"],
                      "fill": ["leaf_stored", "stem_stored"]}.items():
        d[key] = 10 * d[cols].sum(axis=1)
    d["root_before_c"] = d[["root_potential", "dmax_kgN_ha"]].min(axis=1)
    for organ in ["leaf", "stem"]:
        d[f"{organ}_nonreserve"] = 10 * (d[f"{organ}_n"] - d[f"{organ}_reserve"])
        d[f"{organ}_pct"] = 100 * d[f"{organ}_n"] / d[f"{organ}_dm"].where(d[f"{organ}_dm"] > 0)
        d[f"{organ}_crit_pct"] = 100 * d[f"{organ}_critical"] / d[f"{organ}_dm"].where(d[f"{organ}_dm"] > 0)
    d["canopy_pct"] = 100 * d.vegetative_n_g_m2 / (d.leaf_dm + d.stem_dm)
    for state in ["minimum", "critical", "maximum"]:
        d[f"canopy_{state}"] = 100 * d[f"{state}_n_g_m2"] / (d.leaf_dm + d.stem_dm)
    d["nstres"] = 1 - d.NSTD
    d["photo_factor"] = d.unweighted_mean_n_factor.where(d.kernel_calls.gt(0))
    psi = d.uptake_psi.clip(0, 1)
    for transport in ["H", "L"]:
        x = (params[f"ALPHA_{transport}"] * psi).clip(0, 40)
        d[f"fb_{transport}"] = 1 / (1 + np.exp(x) * np.tanh((x / params["DELTA"]) ** 2))
    d["barrier"] = 1 - psi ** 6
    d["yield"], d["yield_event"] = d.CHFPW / 1000, d.HFPOW / 1000
    d = d.sort_values(["run", "dap"])
    d["root_cum"] = d.groupby("run").root_final.cumsum()
    d["harvest_N_cum"] = 10 * d.groupby("run").harvest_n.cumsum()

    obs = pd.read_csv(case.parent / "comparison.csv")
    obs = obs.loc[obs.season_id.eq("26SP") & obs.variable.isin(OBS_MAP),
                  ["trno", "date", "variable", "unit", "observed", "simulated"]].rename(columns={"trno": "treatment"})
    obs["field"] = obs.variable.map(OBS_MAP)
    obs["role"] = "历史目标实测"
    raw = read_csv("plant_npk_source_values.csv")
    organ_map = {"叶": "leaf_pct", "茎": "stem_pct"}
    raw = raw.loc[raw.organ.isin(organ_map) & raw.date.eq(d.date.max())].copy()
    raw["field"] = raw.organ.map(organ_map)
    extra = raw.groupby(["trno", "date", "field"], as_index=False).N.mean()
    extra = extra.rename(columns={"trno": "treatment", "N": "observed"})
    extra["observed"] /= 10
    extra["role"] = "诊断实测"
    extra["unit"] = "% dry mass"
    obs = pd.concat([obs, extra], ignore_index=True).merge(d[["treatment", "date", "dap", "water_level", "nitrogen_level"]],
                                                            on=["treatment", "date"], how="left", validate="many_to_one")
    if obs.dap.isna().any() or obs.duplicated(["treatment", "date", "field"]).any():
        raise ValueError("Missing crop date or duplicate observation")
    obs.loc[obs.field.isin(["yield", "yield_event"]), "observed"] /= 1000
    np.testing.assert_allclose(d.root_final, d.layer_actual, atol=1e-6, rtol=0)
    np.testing.assert_allclose(d.root_final, 10 * d.root_accepted, atol=1e-6, rtol=0)
    np.testing.assert_allclose(d.root_prepaid, d.root_before_c * d.carbon_scale, atol=2e-6, rtol=0)
    np.testing.assert_allclose(d.assim_paid, 10 * d.assimilation_ch2o, atol=1e-5, rtol=0)
    np.testing.assert_allclose(d.begin_plant_and_seed_n + d.root_input + d.fixation_input -
                               d.end_plant_and_seed_n - d.outside_loss, d.plant_residual, atol=1e-11, rtol=0)
    np.testing.assert_allclose(d.CHFPW, d.groupby("run").HFPOW.cumsum(), atol=.31, rtol=0)
    pairs = obs[obs.field.eq("yield")].merge(d[["treatment", "date", "CHFPW"]], on=["treatment", "date"])
    np.testing.assert_allclose(pairs.simulated, pairs.CHFPW, atol=.11, rtol=0)
    if not d.groupby("run").dap.apply(lambda x: np.array_equal(x, np.arange(126))).all() or len(d) != 1512:
        raise ValueError("Expected 126 crop days for each of 12 treatments")
    if len(extra) != 24:
        raise ValueError("Expected 24 diagnostic leaf/stem concentration observations")
    fertilization = read_csv("fertilizer_event_audit.csv")
    irrigation = read_csv("irrigation_event_audit.csv")
    overview = case / "OVERVIEW.OUT"
    files.add(overview)
    profiles = []
    for section in overview.read_text(errors="replace").split("SOIL LOWER UPPER")[1:]:
        depths = [(int(a), int(b)) for a, b in re.findall(r"^\s*(\d+)-\s*(\d+)\s+[.\d]+", section, re.M)]
        profiles.append(depths)
    if len(profiles) != len(meta) or not all(profile == profiles[0] for profile in profiles):
        raise ValueError("Runtime soil layers differ across treatments")
    depths = pd.DataFrame(profiles[0], columns=["upper_cm", "lower_cm"]).rename_axis("zero_layer").reset_index()
    depths["layer"] = depths.pop("zero_layer") + 1
    layer = layer.merge(depths, on="layer", how="left", validate="many_to_one")
    if layer.lower_cm.isna().any() or not layer.groupby(KEY).layer.nunique().eq(len(depths)).all():
        raise ValueError("Root-layer coverage does not match runtime soil profile")
    weight = layer.root_length_cm_cm3 * (layer.lower_cm - layer.upper_cm)
    root_zone = layer[KEY].assign(root_length_area=weight)
    signals = {"root_weighted_SW": "water_cm3_cm3", "root_weighted_NO3": "no3_mgN_kgdrysoil",
               "root_weighted_NH4": "nh4_mgN_kgdrysoil"}
    for field, original in signals.items():
        root_zone[field] = weight * layer[original]
    root_zone = root_zone.groupby(KEY).sum().reset_index()
    for field in signals:
        root_zone[field] /= root_zone.root_length_area.where(root_zone.root_length_area.gt(0))
    d = merge_daily(d, root_zone, ["root_length_area", *signals], "Root length weighted conditions")
    spe = (case / "TMGRO048.SPE").read_text(encoding="ascii", errors="replace").splitlines()
    composition = next(line for line in spe if "PROLFI,PROLFG,PROLFF,PROSTI,PROSTG,PROSTF" in line)
    proli, _, prolf, prosi, _, prosf = (float(composition[i:i + 6]) for i in range(0, 36, 6))
    for organ, rmin, ratio in [("leaf", prolf / proli, 1), ("stem", prosf / prosi, prosi / proli)]:
        exponent = params["CNC_B"] * (params["STEM_BMULT"] if organ == "stem" else 1)
        ref = ratio * (params["CNC_NC_INF"] + (params["CNC_A"] - params["CNC_NC_INF"]) *
                       np.maximum(1, d.vegetative_dm_t_ha / params["CNC_W0"]) ** -exponent)
        np.testing.assert_allclose(d[f"{organ}_crit_pct"], ref, atol=3e-6, rtol=0)
        d[f"{organ}_min_pct"] = ref * np.clip(rmin, .05, 1)
        d[f"{organ}_max_pct"] = ref + ratio * params["CAPACITY"] * params["CNC_A"]
    for state, name in [("minimum", "min"), ("maximum", "max")]:
        canopy = (d.leaf_dm * d[f"leaf_{name}_pct"] + d.stem_dm * d[f"stem_{name}_pct"]) / (d.leaf_dm + d.stem_dm)
        np.testing.assert_allclose(d[f"canopy_{state}"], canopy, atol=3e-6, rtol=0)
    receipt = dict(
        model="DSSAT 4.8.2.000 / frozen V15 S1 interface", archive=str(case), binary_sha256=binary,
        days=126, treatments=12, rows=len(d), pre_freshwt_zero_days=early, diagnostic_N_points=len(extra),
        layer_uptake_max_abs_error_kg_ha=float((d.root_final - d.layer_actual).abs().max()),
        plant_N_max_abs_residual_g_m2=float(d.plant_residual.abs().max()),
        clipped_potential_vs_stock_max_abs_kg_ha=float((layer.kinetic_potential_kgN_ha - layer.stock_limited_potential_kgN_ha).abs().max()),
        source_hashes={str(f): sha(f) for f in sorted(files)}, parameters_echo=params)
    return d, layer, obs, fertilization, irrigation, receipt


def get_contrasts(d):
    frames = []
    for field, (_, unit) in FIELDS.items():
        wide = d.pivot(index="dap", columns=["water_level", "nitrogen_level"], values=field)
        for water in WATER:
            q = wide[water]
            high = q[NITROGEN[1:]]
            frames.append(pd.DataFrame(dict(dap=q.index, axis="N", group=water, variable=field, unit=unit,
                                            full_contrast=(q.N3 - q.N0).to_numpy(),
                                            intermediate_contrast=(q.N3 - q.N2).to_numpy(),
                                            N123_range=(high.max(axis=1) - high.min(axis=1)).where(high.notna().all(axis=1)).to_numpy())))
        for n in NITROGEN:
            frames.append(pd.DataFrame(dict(dap=wide.index, axis="W", group=n, variable=field, unit=unit,
                                            full_contrast=(wide["W3", n] - wide["W1", n]).to_numpy(),
                                            intermediate_contrast=(wide["W2", n] - wide["W1", n]).to_numpy(),
                                            N123_range=np.nan)))
    return pd.concat(frames, ignore_index=True)


class Atlas:
    def __init__(self, d, layers, obs, delta, colors, out):
        self.d, self.layers, self.obs, self.delta = d, layers, obs, delta
        self.colors, self.out = colors, out
        self.pages = []

    def layout(self, title, subtitle, rows=3, columns=3, legend=True):
        height = 2.0 * rows + 1.65
        fig, axes = plt.subplots(rows, columns, figsize=(13.8, height), squeeze=False)
        fig.subplots_adjust(left=.09, right=.97, bottom=.78 / height, top=1 - 1.20 / height,
                            hspace=.34, wspace=.20)
        fig.text(.062, 1 - .14 / height, title, va="top", fontsize=19, fontweight="bold", color=INK)
        fig.text(.062, 1 - .51 / height, subtitle, va="top", fontsize=9.5, color=MUTED)
        if legend:
            handles = [Line2D([], [], lw=1.8, color=self.colors[n], label=n) for n in NITROGEN]
            fig.legend(handles=handles, ncols=4, frameon=False, loc="upper center",
                       bbox_to_anchor=(.5, 1 - .71 / height))
        return fig, axes

    def save(self, pdf, fig, name, title, note):
        page = len(self.pages) + 1
        fig.text(.062, .19 / fig.get_figheight(), note, fontsize=8.5, color=MUTED, va="bottom")
        fig.text(.972, .19 / fig.get_figheight(), f"{page:02d}", fontsize=8.5, color=MUTED, ha="right")
        pdf.savefig(fig)
        if name == "root_limits":
            fig.savefig(self.out / "diagnostic_root_limits.png", dpi=150)
        self.pages.append(dict(page=page, id=name, title=title))
        plt.close(fig)

    @staticmethod
    def time_axis(ax, title=None, bottom=False):
        ax.grid(axis="y", color="#E5E9ED", linewidth=.6)
        ax.set_axisbelow(True)
        ax.set_xticks([0, 30, 60, 90, 125])
        ax.set_xlim(-2, 128)
        if title:
            ax.set_title(title, fontweight="bold", pad=6)
        if bottom:
            ax.set_xlabel("移栽后天数 DAP")
        else:
            ax.tick_params(labelbottom=False)

    def lines(self, pdf, name, title, fields, note, overlay=None):
        fig, axes = self.layout(title, "V15 S1 冻结最佳组 · 26SP · 逐日机制诊断", rows=len(fields))
        for row, field in enumerate(fields):
            label, unit = FIELDS[field]
            points = self.obs[self.obs.field.eq(field)]
            values = np.r_[self.d[field], points.observed]
            if overlay and field == "canopy_pct":
                values = np.r_[values, self.d.canopy_minimum, self.d.canopy_maximum]
            if field == "photo_factor":
                values = np.r_[values, self.d.min_n_factor.where(self.d.kernel_calls.gt(0))]
            low = min(0, np.nanmin(values))
            high = max(1 if unit == "0–1" else low + 1e-9, np.nanmax(values))
            width = max(high - low, 1e-6)
            for col, water in enumerate(WATER):
                ax = axes[row, col]
                for n in NITROGEN:
                    g = self.d[self.d.water_level.eq(water) & self.d.nitrogen_level.eq(n)]
                    o = points[points.water_level.eq(water) & points.nitrogen_level.eq(n)]
                    if overlay and field == "canopy_pct" and n == "N3":
                        ax.fill_between(g.dap, g.canopy_minimum, g.canopy_maximum, color="#93AE9B", alpha=.28)
                        ax.plot(g.dap, g.canopy_critical, color="#547A62", ls="--", lw=1.15)
                    if field == "photo_factor":
                        use = g.kernel_calls.gt(0)
                        ax.fill_between(g.dap, g.min_n_factor.where(use), g.max_n_factor.where(use),
                                        color=self.colors[n], alpha=.075, lw=0)
                    ax.plot(g.dap, g[field], lw=1.35, color=self.colors[n])
                    for role, group in o.groupby("role"):
                        color = self.colors[n]
                        ax.scatter(group.dap, group.observed, marker=MARKER[water], s=23, zorder=5,
                                   facecolors="white" if role == "诊断实测" else color,
                                   edgecolors=color, linewidths=.85)
                if unit == "0–1" or field == "vegetative_nni":
                    ax.axhline(1, color="#A3ADB5", lw=.7, ls=":")
                if low < 0:
                    ax.axhline(0, color="#A3ADB5", lw=.7)
                ax.set_ylim(low - (.05 * width if low < 0 else 0), high + .08 * width)
                self.time_axis(ax, water if row == 0 else None, row == len(fields) - 1)
                if col == 0:
                    ax.set_ylabel(f"{label}\n({unit})")
                else:
                    ax.tick_params(labelleft=False)
        self.save(pdf, fig, name, title, note)

    def layer_profiles(self, pdf):
        title = "净吸氮来自哪些土层"
        fig, axes = self.layout(title, "累计根层吸氮 · 线标出 40 cm 回显值 · 土层中心为标记位置", rows=1)
        bottom = self.layers.lower_cm.max()
        total = self.layers.groupby(["water_level", "nitrogen_level", "upper_cm", "lower_cm"], as_index=False).actual_kgN_ha.sum()
        max_value = total.actual_kgN_ha.max()
        for col, water in enumerate(WATER):
            ax = axes[0, col]
            for n in NITROGEN:
                g = total[total.water_level.eq(water) & total.nitrogen_level.eq(n)]
                ax.plot(g.actual_kgN_ha, (g.upper_cm + g.lower_cm) / 2, "o-", color=self.colors[n], ms=4)
            ax.axhline(40, color="#69757D", linestyle="--", lw=.85)
            ax.set(xlim=(0, max_value * 1.07), ylim=(bottom, 0), title=water, xlabel="全季分层净吸氮 (kg N/ha)")
            ax.grid(axis="y", color="#E5E9ED")
            if col == 0:
                ax.set_ylabel("深度 (cm)")
        self.save(pdf, fig, "root_layers", title, "按土层逐日最终通量求和。V15 S1 源码读入 40 cm，但未在根深计算中调用该上限。")

    def dilution(self, pdf):
        title = "器官氮参照带与实际浓度轨迹"
        fig, axes = self.layout(title, "同一曲线参数用于 12 个处理 · 横坐标为叶＋茎站存干重", rows=2)
        curve = self.d.sort_values("vegetative_dm_t_ha")
        for row, organ in enumerate(["leaf", "stem"]):
            lo = min(curve[f"{organ}_min_pct"].min(), curve[f"{organ}_pct"].min())
            hi = max(curve[f"{organ}_max_pct"].max(), curve[f"{organ}_pct"].max())
            for col, water in enumerate(WATER):
                ax = axes[row, col]
                ax.fill_between(curve.vegetative_dm_t_ha, curve[f"{organ}_min_pct"], curve[f"{organ}_max_pct"],
                                color="#93AE9B", alpha=.28)
                ax.plot(curve.vegetative_dm_t_ha, curve[f"{organ}_crit_pct"], color="#547A62", ls="--", lw=1.1)
                for n in NITROGEN:
                    g = self.d[self.d.water_level.eq(water) & self.d.nitrogen_level.eq(n)]
                    ax.plot(g.vegetative_dm_t_ha, g[f"{organ}_pct"], color=self.colors[n], lw=1.3)
                ax.set_ylim(lo * .95, hi * 1.06)
                ax.set_xscale("log")
                ax.set_xlim(curve.vegetative_dm_t_ha.min() * .9, curve.vegetative_dm_t_ha.max() * 1.1)
                ax.grid(axis="y", color="#E5E9ED", lw=.6)
                if row == 0:
                    ax.set_title(water, fontweight="bold")
                else:
                    ax.set_xlabel("茎叶站存干重 (t DM/ha)")
                if col == 0:
                    ax.set_ylabel(("叶" if organ == "leaf" else "茎") + "总氮浓度 (% DM)")
                else:
                    ax.tick_params(labelleft=False)
        self.save(pdf, fig, "dilution", title, "绿带为源码公式的上下界，绿虚线为临界浓度。彩线依日序连接模拟点。")

    def yield_page(self, pdf, smooth=False):
        title = "鲜果产量与真实采收事件" + (" · 单调曲线预览" if smooth else "")
        fig, axes = self.layout(title, "实线或实心标记为模拟 · 空心标记为同日实测 · 鲜重", rows=3)
        last = self.d.groupby("treatment", as_index=False).tail(1)
        obs = self.obs[self.obs.field.eq("yield")]
        end = obs[obs.dap.eq(last.dap.max())]
        ev = self.obs[self.obs.field.eq("yield_event")]
        limit = max(last["yield"].max(), obs.observed.max()) * 1.10
        event_limit = max(self.d.yield_event.max(), ev.observed.max()) * 1.12
        for col, water in enumerate(WATER):
            ax, ae, af = axes[:, col]
            for i, n in enumerate(NITROGEN):
                color, marker = self.colors[n], MARKER[water]
                g = self.d[self.d.water_level.eq(water) & self.d.nitrogen_level.eq(n)]
                q = obs[obs.water_level.eq(water) & obs.nitrogen_level.eq(n)]
                events = g[g.yield_event.gt(0)]
                if smooth:
                    nodes = g[g.dap.eq(g.dap.min()) | g.dap.eq(g.dap.max()) | g.yield_event.gt(0)]
                    xx = np.linspace(nodes.dap.min(), nodes.dap.max(), 401)
                    yy = PchipInterpolator(nodes.dap, nodes["yield"])(xx)
                    if np.min(np.diff(yy)) < -1e-9:
                        raise ValueError("Interpolated cumulative yield decreases")
                    ax.plot(xx, yy, color=color, lw=1.4)
                else:
                    ax.step(g.dap, g["yield"], where="post", color=color, lw=1.4)
                ax.scatter(q.dap, q.observed, marker=marker, facecolor="white", edgecolor=color, s=26)
                ae.vlines(events.dap, 0, events.yield_event, color=color, lw=1)
                ae.scatter(events.dap, events.yield_event, marker=marker, color=color, s=24)
                e = ev[ev.water_level.eq(water) & ev.nitrogen_level.eq(n)]
                ae.scatter(e.dap, e.observed, marker=marker, facecolor="white", edgecolor=color, s=25)
                af.bar(i, g["yield"].iloc[-1], width=.65, color=color, alpha=.78)
                measured = end[end.water_level.eq(water) & end.nitrogen_level.eq(n)]
                af.scatter([i] * len(measured), measured.observed, marker=marker,
                           facecolor="white", edgecolor=INK, s=34, zorder=5)
            self.time_axis(ax, water, True)
            self.time_axis(ae, bottom=True)
            ae.set_xticks(sorted(ev.dap.unique()))
            af.set_xticks(range(4), NITROGEN)
            for axis, ymax, label in zip([ax, ae, af], [limit, event_limit, limit],
                                          ["累计鲜果 (t/ha)", "单次鲜果 (t/ha)", "最终鲜果 (t/ha)"]):
                axis.set_ylim(0, ymax)
                if col == 0:
                    axis.set_ylabel(label)
                else:
                    axis.tick_params(labelleft=False)
        note = "平滑累计仅供读图。单次事件、实测日期及产量计算沿用原始节点。" if smooth else "累计按原始事件作阶梯。每一采收日保留单次模拟与实测。"
        self.save(pdf, fig, "yield_smooth" if smooth else "yield_events", title, note)

    def contrasts(self, pdf, axis):
        fields = ["root_cum", "canopy_pct", "LAID", "yield"]
        by_n = axis == "N"
        groups = WATER if by_n else NITROGEN
        title = "同日氮响应差值" if by_n else "同日水响应差值"
        labels = ["N3−N0", "N3−N2"] if by_n else ["W3−W1", "W2−W1"]
        fig, axes = self.layout(title, "同一日期内做差 · 每行共享纵轴 · 零线是两处理数值相同",
                                rows=len(fields), columns=len(groups), legend=False)
        fig.legend([Line2D([], [], color=c, lw=1.6) for c in ["#344D62", "#B86E3C"]], labels,
                   ncols=2, frameon=False, loc="upper center", bbox_to_anchor=(.5, 1 - .71 / fig.get_figheight()))
        for row, field in enumerate(fields):
            label, unit = FIELDS[field]
            sub = self.delta[self.delta.axis.eq(axis) & self.delta.variable.eq(field)]
            vals = sub[["full_contrast", "intermediate_contrast"]].to_numpy()
            lo, hi = min(0, vals.min()), max(0, vals.max())
            margin = max(1e-6, (hi - lo) * .08)
            for col, group in enumerate(groups):
                ax = axes[row, col]
                g = sub[sub.group.eq(group)]
                ax.axhline(0, color="#A3ADB5", lw=.7)
                ax.plot(g.dap, g.full_contrast, color="#344D62", lw=1.45)
                ax.plot(g.dap, g.intermediate_contrast, color="#B86E3C", lw=1.45)
                ax.set_ylim(lo - margin, hi + margin)
                self.time_axis(ax, group if row == 0 else None, row == len(fields) - 1)
                if col == 0:
                    ax.set_ylabel(f"{label}差\n({unit})")
                else:
                    ax.tick_params(labelleft=False)
        self.save(pdf, fig, f"{axis}_contrasts", title, "差值保留符号，用于定位分离出现的时间和阶段。")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for key in ("case", "source", "profile", "shared", "out"):
        ap.add_argument(f"--{key}", type=Path, required=True)
    a = ap.parse_args()
    d, layer, obs, fert, irrig, receipt = freeze(a.case.resolve(), a.source.resolve(), a.profile.resolve(), a.shared.resolve())
    delta = get_contrasts(d)
    a.out.mkdir(parents=True, exist_ok=False)
    tables = {"daily": d, "root_layers": layer, "observations": obs, "contrasts": delta,
              "fertilization_events": fert, "irrigation_events": irrig}
    for name, table in tables.items():
        table.to_csv(a.out / f"diagnostic_{name}.csv", index=False, encoding="utf-8-sig")
    dump(a.out / "diagnostic_variable_catalogue.json", FIELDS)

    font = Path("C:/Windows/Fonts/msyh.ttc")
    font_manager.fontManager.addfont(font)
    plt.rcParams.update({"font.family": font_manager.FontProperties(fname=font).get_name(),
                         "pdf.fonttype": 42, "font.size": 9, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.unicode_minus": False})
    colors = json.loads(a.profile.read_text(encoding="utf8"))["nitrogen_colors"]
    atlas = Atlas(d, layer, obs, delta, colors, a.out)
    with PdfPages(a.out / "diagnostic_atlas.pdf") as pdf:
        atlas.lines(pdf, "water", "水分输入与植株水分限制", ["IRRC", "EPAA", "WSPD", "WSGD"],
                    "IRRC 从原生逐日水账读取。两项胁迫按 DSSAT 输出，数值越高表示限制越强。")
        atlas.layer_profiles(pdf)
        atlas.lines(pdf, "root_zone", "根长与根系实际接触的水氮环境", ["RDPD", "root_length_area",
                    "root_weighted_SW", "root_weighted_NO3", "root_weighted_NH4"],
                    "土层条件按 RLV×层厚加权。两种土壤无机氮采用干土浓度，保留原生单位。")
        atlas.lines(pdf, "root_limits", "潜力、需求上限与实际吸氮", ["root_potential", "dmax_kgN_ha",
                    "root_before_c", "root_final", "root_cum"],
                    "归档潜力已过土层库存裁剪。Dmax 后候选量由 min(库存裁剪后潜力, Dmax) 重算。")
        atlas.lines(pdf, "root_feedback", "根系氮反馈与富氮抑制", ["uptake_psi", "fb_H", "fb_L", "barrier"],
                    "信号取当天决策态。三个反馈因子按冻结公式重算。负 ψ 时 HATS 和 LATS 均取 1。")
        atlas.lines(pdf, "assimilation", "吸收结算与氮同化碳成本", ["carbon_scale", "root_prepaid", "root_rejected_ha",
                    "assim_paid", "assim_refund"],
                    "S1 同日对净吸收结算蛋白当量成本。此页用实际接受量和碳账展示该过程。")
        atlas.lines(pdf, "requests", "氮需求与旧组织回补", ["growth_request_ha", "repair_request_ha",
                    "refill_request_ha", "repair", "fill"], "需求是候选请求。实际修复和储备填充分别读取器官账。")
        atlas.lines(pdf, "reserves", "叶与茎的氮库组成", ["leaf_nonreserve", "leaf_R", "stem_nonreserve", "stem_R"],
                    "有机储备是器官总氮的子集。非储备氮由总量扣除该子库。")
        atlas.lines(pdf, "turnover", "快速与慢速动员及果根氮库", ["fast", "bound", "root_pool", "fruit_pool", "harvest_N_cum"],
                    "前两行为叶茎内部再转运，后三行为站存或采收账。站存果氮含果壳与籽。")
        atlas.lines(pdf, "concentration", "叶、茎与冠层氮浓度", ["leaf_pct", "stem_pct", "canopy_pct", "leaf_functional_pct"],
                    "实心点为历史目标实测，空心点为 7 月 17 日诊断实测。绿带与虚线分别为 N3 当日冠层上下界与临界参照。",
                    overlay=True)
        atlas.dilution(pdf)
        atlas.lines(pdf, "stress", "氮状态与实际生长、光合反馈", ["vegetative_nni", "psi_raw", "nstres", "photo_factor"],
                    "生长氮因子由 1−NSTD 还原。光合氮因子为调用算术均值，色带为调用范围，零调用日留空。")
        atlas.lines(pdf, "growth", "LAI、茎叶干重与冠层光合", ["LAID", "LWAD", "SWAD", "PHAD"],
                    "点为同日实测。PHAD 为模型冠层总光合，以每日每地面积的碳水化合物量表示。")
        atlas.yield_page(pdf)
        atlas.yield_page(pdf, smooth=True)
        atlas.contrasts(pdf, "N")
        atlas.contrasts(pdf, "W")

    receipt["pages"] = atlas.pages
    receipt["generator_sha256"] = sha(Path(__file__))
    receipt["artifacts"] = {f.name: sha(f) for f in sorted(a.out.iterdir())}
    dump(a.out / "diagnostic_manifest.json", receipt)
    print(f"{len(atlas.pages)} pages / {len(d)} crop rows / {len(layer)} layer rows")


if __name__ == "__main__":
    main()


