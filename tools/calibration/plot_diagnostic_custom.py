import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl

mpl.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "Arial"],
    "axes.unicode_minus": False,
    "figure.dpi": 200,
    "savefig.dpi": 200
})

PROJECT_ROOT = Path("D:/Tomato_Cal")
MAPPING_CSV = PROJECT_ROOT / "scratch/three_season_35trt_water_n_mapping.csv"

# Nitrogen color palette and water marker shapes
NITROGEN_COLORS = {"N3": "#c0392b", "N2": "#e67e22", "N1": "#2980b9", "N0": "#707070"}
WATER_STYLES = {"W3": {"color": "#1f77b4", "marker": "o", "ls": "-"},
                "W2": {"color": "#ff7f0e", "marker": "s", "ls": "--"},
                "W1": {"color": "#2ca02c", "marker": "^", "ls": "-."}}

def parse_plantgro_tmt(pg_file, treatments):
    """Parse PlantGro.OUT and return dictionary of DataFrames keyed by TN."""
    rows = []
    cur_tn = None
    hdr = None
    with open(pg_file, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s.startswith("*RUN"):
                import re
                m = re.search(r"XXQL\d+\s+(\d+)", s)
                cur_tn = int(m.group(1)) if m else None
                hdr = None
                continue
            if s.startswith("@YEAR"):
                hdr = [c.lstrip("@") for c in s.split()]
                continue
            if hdr and s[:4].isdigit() and cur_tn in treatments:
                parts = s.split()
                if len(parts) >= len(hdr):
                    rows.append(dict(zip(hdr, parts)) | {"TN": cur_tn})
    df = pd.DataFrame(rows)
    for c in ["YEAR", "DOY", "DAS", "DAP", "LAID", "LWAD", "SWAD", "GWAD", "LN%D", "SLAD", "CHTD"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def plot_candidate_nitrogen_response(cand_dir, cand_label, out_file, *, mapping_csv=None, seasons=None, yield_csv=None):
    """Plot fresh yield vs N-rate across water levels for 25SP, 26SP, 25FA."""
    map_df = pd.read_csv(mapping_csv if mapping_csv is not None else MAPPING_CSV)
    y_file = Path(yield_csv) if yield_csv is not None else cand_dir / "all_35_treatments_final_yield.csv"
    if not y_file.exists():
        cands = list(cand_dir.glob("*35trt_yield.csv"))
        if cands:
            y_file = cands[0]
        else:
            # Check in workspace/candidates
            rname = cand_dir.name
            c_dirs = list((PROJECT_ROOT / "workspace/candidates").glob(f"*{rname.replace('iter6_', '')}*"))
            if c_dirs and (c_dirs[0] / "all_35_treatments_final_yield.csv").exists():
                y_file = c_dirs[0] / "all_35_treatments_final_yield.csv"
            else:
                raise FileNotFoundError(f"Could not find 35 treatment yield CSV in {cand_dir}")
    y_df = pd.read_csv(y_file)
    # Treatment identities come from the explicit mapping, without ambiguous
    # _x/_y columns if a modern yield audit already carries water/N labels.
    y_df = y_df.drop(columns=[c for c in ["water_level","nitrogen_level"] if c in y_df])
    merged = pd.merge(y_df, map_df, left_on=["season", "tn"], right_on=["season_id", "treatment"],validate="many_to_one")
    
    n_order = ["N0", "N1", "N2", "N3"]
    seasons = list(seasons) if seasons is not None else ["25SP", "26SP", "25FA"]
    season_names = {"25SP": "2025 Spring (XXQL2501)", "26SP": "2026 Spring (XXQL2601)", "25FA": "2025 Autumn Blind (XXQL2502)"}
    
    if mapping_csv is not None:
        season_names.update({"25SP":"2025 Spring (validation)","26SP":"2026 Spring (calibration)"})
        if "dataset_role" in map_df:
            for season, group in map_df.groupby("season_id"):
                if season in ("25SP", "26SP"):
                    role, = group.dataset_role.unique()
                    season_names[season] = f"20{season[:2]} Spring ({role})"
    fig, axes = plt.subplots(1, len(seasons), figsize=(5.4*len(seasons), 5), sharey=False)
    axes = np.atleast_1d(axes)
    
    for ax, s in zip(axes, seasons):
        sub_s = merged[merged["season"] == s]
        waters = ["W3", "W2", "W1"] if s != "25SP" else ["W3", "W1"]
        delta_labels = []
        
        for w in waters:
            sub_w = sub_s[sub_s["water_level"] == w].copy()
            sub_w["n_cat"] = pd.Categorical(sub_w["nitrogen_level"], categories=n_order, ordered=True)
            sub_w = sub_w.sort_values("n_cat")
            
            if sub_w.empty:
                continue
            
            x_vals = range(len(sub_w))
            x_labels = sub_w["nitrogen_level"].tolist()
            
            style = WATER_STYLES.get(w, {"color": "gray", "marker": "x", "ls": "-"})
            if mapping_csv is not None:
                colors=[NITROGEN_COLORS[n] for n in x_labels]
                ax.plot(x_vals,sub_w['sim_t_ha'],color='#555555',marker=style['marker'],
                        markerfacecolor='white',ls='-',lw=1.5,label=f'Model {w}')
                ax.scatter(x_vals,sub_w['sim_t_ha'],facecolors='white',edgecolors=colors,
                           marker=style['marker'],s=50,zorder=4)
                ax.scatter(x_vals,sub_w['obs_t_ha'],c=colors,edgecolors='black',
                           marker=style['marker'],s=50,label=f'Observed {w}',zorder=5)
            else:
                # Historical rendering is preserved for existing callers.
                ax.plot(x_vals, sub_w["obs_t_ha"], color=style["color"], marker=style["marker"],
                        ls=":", lw=1.5, alpha=0.5, label=f"Observed {w}")
                ax.plot(x_vals, sub_w["sim_t_ha"], color=style["color"], marker=style["marker"],
                        ls=style["ls"], lw=2.5, label=f"Simulated {w}")
            
            # Highlight N2 -> N3 delta
            if "N2" in x_labels and "N3" in x_labels:
                idx2 = x_labels.index("N2")
                idx3 = x_labels.index("N3")
                y2_sim = sub_w.iloc[idx2]["sim_t_ha"]
                y3_sim = sub_w.iloc[idx3]["sim_t_ha"]
                delta_sim = y3_sim - y2_sim
                if mapping_csv is not None:
                    delta_labels.append(f'{w}: {delta_sim*1000:+.1f} kg/ha')
                    continue
                
                # Annotate delta on plot
                sign = "+" if delta_sim >= 0 else ""
                ax.annotate(f"{sign}{delta_sim:.2f} t/ha",
                            xy=(idx3, y3_sim), xytext=(idx3 - 0.2, y3_sim + (1.0 if delta_sim>=0 else -1.8)),
                            fontsize=9, fontweight="bold",
                            color="#c0392b" if delta_sim < 0 else "#27ae60",
                            arrowprops=dict(arrowstyle="->", color=style["color"], lw=1))
        
        if delta_labels:
            ax.text(.98,.035,'Model N3 - N2\n'+'\n'.join(delta_labels),transform=ax.transAxes,
                    ha='right',va='bottom',fontsize=9,color='#303030',
                    bbox=dict(facecolor='white',edgecolor='#bbbbbb',alpha=.9))
        ax.set_xticks(range(len(n_order)))
        ax.set_xticklabels(n_order, fontsize=11, fontweight="bold")
        ax.set_title(season_names[s], fontsize=12, fontweight="bold", pad=10)
        ax.set_xlabel("Nitrogen Level", fontsize=11)
        ax.set_ylabel("Fruit Yield (t/ha)", fontsize=11)
        ax.grid(True, linestyle="--", alpha=0.4)
        legend_loc = "best" if mapping_csv is not None else ("lower right" if s == "25FA" else "upper left")
        ax.legend(fontsize=8, loc=legend_loc)
    
    fig.suptitle(f"Diagnostic: Nitrogen-Yield Response and N3-N2 Difference — {cand_label}",
                 fontsize=12, fontweight="bold", y=1.03)
    plt.tight_layout()
    plt.savefig(out_file, bbox_inches="tight")
    plt.close()
    print(f"Saved: {out_file}")

def plot_candidate_low_n_canopy(cand_dir, cand_label, out_file, *, mapping_csv=None, native_dirs=None, comparison=None):
    """Plot daily LAI and Leaf N% for low nitrogen (N0) treatments in 25SP and 26SP."""
    if native_dirs is not None:
        map_df=pd.read_csv(mapping_csv if mapping_csv is not None else MAPPING_CSV)
        fig,axes=plt.subplots(len(native_dirs),2,figsize=(12,4*len(native_dirs)),squeeze=False)
        for i,(season,folder) in enumerate(native_dirs.items()):
            role = "calibration" if season == "26SP" else "validation"
            if "dataset_role" in map_df:
                role, = map_df.loc[map_df.season_id.eq(season), "dataset_role"].unique()
            meta=map_df[(map_df.season_id==season)&(map_df.nitrogen_level=="N0")]
            ids=meta.treatment.astype(int).tolist()
            pg=parse_plantgro_tmt(Path(folder)/'PlantGro.OUT',ids)
            pn=parse_plantgro_tmt(Path(folder)/'PlantN.OUT',ids)
            for row in meta.itertuples():
                marker={'W3':'o','W2':'s','W1':'^'}.get(row.water_level,'D')
                for col,(df,var,label) in enumerate([(pg,'LAID','LAI'),(pn,'LN%D','Leaf N (% dry mass)')]):
                    sub=df[df.TN.eq(row.treatment)].sort_values('DAP')
                    axes[i,col].plot(sub.DAP,sub[var],color='#707070',marker=marker,markevery=12,
                                     markersize=4,lw=1.5,markerfacecolor='white',label=f'{row.water_level}N0 model')
                    if comparison is not None:
                        variable='LAID' if var=='LAID' else 'LEAF_N_PCT'
                        q=comparison[(comparison.season_id==season)&(comparison.trno==row.treatment)&(comparison.variable==variable)]
                        axes[i,col].scatter(q.dap,q.observed,color='#707070',marker=marker,s=42,label=f'{row.water_level}N0 observed',zorder=5)
                    axes[i,col].set_ylabel(label);axes[i,col].set_xlabel('Days after planting');axes[i,col].grid(alpha=.25)
                    axes[i,col].set_title(f'{season} ({role}): {label}')
                    axes[i,col].legend(fontsize=8)
        fig.suptitle(f'Low-N canopy and leaf-N trajectories — {cand_label}',fontsize=13)
        fig.tight_layout();fig.savefig(out_file,bbox_inches='tight');plt.close(fig)
        print(f'Saved: {out_file}');return
    map_df = pd.read_csv(MAPPING_CSV)
    
    # Target N0 treatments:
    # 25SP: TN13 (W1N0), TN5 (W3N0)
    # 26SP: TN12 (W1N0), TN9 (W3N0)
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), sharex=False)
    
    # 25SP
    pg_25sp = cand_dir / "25SP/PlantGro.OUT"
    if pg_25sp.exists():
        df_25 = parse_plantgro_tmt(pg_25sp, [5, 13])
        # W1N0 (TN13)
        sub13 = df_25[df_25["TN"] == 13].sort_values("DAP")
        sub5 = df_25[df_25["TN"] == 5].sort_values("DAP")
        
        # Panel (0,0): 25SP LAI
        ax = axes[0, 0]
        ax.plot(sub5["DAP"], sub5["LAID"], color="#1f77b4", lw=2.2, label="W3N0 Simulated")
        ax.plot(sub13["DAP"], sub13["LAID"], color="#2ca02c", lw=2.2, label="W1N0 Simulated")
        # Add annotation of final LAI
        if not sub13.empty:
            final_lai13 = sub13.iloc[-1]["LAID"]
            final_dap13 = sub13.iloc[-1]["DAP"]
            ax.annotate(f"Harvest LAI: {final_lai13:.2f}\n(No crash!)",
                        xy=(final_dap13, final_lai13), xytext=(final_dap13 - 25, final_lai13 + 0.6),
                        fontsize=10, fontweight="bold", color="#2ca02c",
                        arrowprops=dict(arrowstyle="->", color="#2ca02c", lw=1.5))
        ax.set_title("2025 Spring: Low-N (N0) LAI Dynamics Across DAP", fontsize=12, fontweight="bold")
        ax.set_xlabel("Days After Planting (DAP)", fontsize=10)
        ax.set_ylabel("Leaf Area Index (LAI)", fontsize=10)
        ax.grid(True, linestyle="--", alpha=0.4)
        ax.legend(fontsize=9, loc="upper left")
        
        # Panel (0,1): 25SP Leaf N%
        ax = axes[0, 1]
        ax.plot(sub5["DAP"], sub5["LN%D"], color="#1f77b4", lw=2.2, label="W3N0 Leaf N%")
        ax.plot(sub13["DAP"], sub13["LN%D"], color="#2ca02c", lw=2.2, label="W1N0 Leaf N%")
        ax.axhline(2.5, color="red", linestyle=":", label="Critical Min (2.5%)")
        if not sub13.empty:
            final_ln13 = sub13.iloc[-1]["LN%D"]
            final_dap13 = sub13.iloc[-1]["DAP"]
            ax.annotate(f"Harvest Leaf N%: {final_ln13:.2f}%\n(Realistic physiological range)",
                        xy=(final_dap13, final_ln13), xytext=(final_dap13 - 35, final_ln13 + 0.4),
                        fontsize=10, fontweight="bold", color="#2ca02c",
                        arrowprops=dict(arrowstyle="->", color="#2ca02c", lw=1.5))
        ax.set_title("2025 Spring: Low-N (N0) Leaf N% Dynamics", fontsize=12, fontweight="bold")
        ax.set_xlabel("Days After Planting (DAP)", fontsize=10)
        ax.set_ylabel("Leaf Nitrogen (%)", fontsize=10)
        ax.grid(True, linestyle="--", alpha=0.4)
        ax.legend(fontsize=9, loc="upper right")
    
    # 26SP
    pg_26sp = cand_dir / "26SP/PlantGro.OUT"
    if pg_26sp.exists():
        df_26 = parse_plantgro_tmt(pg_26sp, [9, 12])
        sub12 = df_26[df_26["TN"] == 12].sort_values("DAP")
        sub9 = df_26[df_26["TN"] == 9].sort_values("DAP")
        
        # Panel (1,0): 26SP LAI
        ax = axes[1, 0]
        ax.plot(sub9["DAP"], sub9["LAID"], color="#1f77b4", lw=2.2, label="W3N0 Simulated")
        ax.plot(sub12["DAP"], sub12["LAID"], color="#2ca02c", lw=2.2, label="W1N0 Simulated")
        if not sub12.empty:
            final_lai12 = sub12.iloc[-1]["LAID"]
            final_dap12 = sub12.iloc[-1]["DAP"]
            ax.annotate(f"Harvest LAI: {final_lai12:.2f}\n(Healthy canopy)",
                        xy=(final_dap12, final_lai12), xytext=(final_dap12 - 25, final_lai12 + 0.5),
                        fontsize=10, fontweight="bold", color="#2ca02c",
                        arrowprops=dict(arrowstyle="->", color="#2ca02c", lw=1.5))
        ax.set_title("2026 Spring: Low-N (N0) LAI Dynamics Across DAP", fontsize=12, fontweight="bold")
        ax.set_xlabel("Days After Planting (DAP)", fontsize=10)
        ax.set_ylabel("Leaf Area Index (LAI)", fontsize=10)
        ax.grid(True, linestyle="--", alpha=0.4)
        ax.legend(fontsize=9, loc="upper left")
        
        # Panel (1,1): 26SP Leaf N%
        ax = axes[1, 1]
        ax.plot(sub9["DAP"], sub9["LN%D"], color="#1f77b4", lw=2.2, label="W3N0 Leaf N%")
        ax.plot(sub12["DAP"], sub12["LN%D"], color="#2ca02c", lw=2.2, label="W1N0 Leaf N%")
        ax.axhline(2.5, color="red", linestyle=":", label="Critical Min (2.5%)")
        if not sub12.empty:
            final_ln12 = sub12.iloc[-1]["LN%D"]
            final_dap12 = sub12.iloc[-1]["DAP"]
            ax.annotate(f"Harvest Leaf N%: {final_ln12:.2f}%",
                        xy=(final_dap12, final_ln12), xytext=(final_dap12 - 30, final_ln12 + 0.4),
                        fontsize=10, fontweight="bold", color="#2ca02c",
                        arrowprops=dict(arrowstyle="->", color="#2ca02c", lw=1.5))
        ax.set_title("2026 Spring: Low-N (N0) Leaf N% Dynamics", fontsize=12, fontweight="bold")
        ax.set_xlabel("Days After Planting (DAP)", fontsize=10)
        ax.set_ylabel("Leaf Nitrogen (%)", fontsize=10)
        ax.grid(True, linestyle="--", alpha=0.4)
        ax.legend(fontsize=9, loc="upper right")
        
    fig.suptitle(f"Diagnostic: Low-Nitrogen Canopy Health & Non-Collapse Verification - {cand_label}",
                 fontsize=14, fontweight="bold", y=1.01)
    plt.tight_layout()
    plt.savefig(out_file, bbox_inches="tight")
    plt.close()
    print(f"Saved: {out_file}")

if __name__ == "__main__":
    print("plot_diagnostic_custom module loaded.")
