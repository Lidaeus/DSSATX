"""Summarize original soil measurements and compare with the selected DSSAT bundles."""

from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.common.input_manifest import verify_manifest_integrity
from tools.experiments.rebuild_current_bundles import bulk_density

RAW = Path("D:/三季节数据汇总")
FILES = [
    RAW / "2025春/2025春初始土壤基础养分.xlsx",
    RAW / "2026春/2026春土壤养分数据集.xlsx",
    RAW / "2026春/2026春土壤养分全氮-有机碳集.xlsx",
]
BUNDLES = {
    2025: ROOT / "data/user/experiments/xxql2501_refreshed_lwad_20261108",
    2026: ROOT / "data/user/experiments/xxql2601_final_20261105",
}
OUT = ROOT / "workspace/audits/spring_soil_table1_20261108"
LAYERS = ["0-20", "20-40", "40-60"]
KEY = ["plot", "depth"]
CHEM = {"SAOC": "SOC", "SANI": "TN", "SAPHW": "pH", "SAPX": "AP", "SAKE": "AK_cmol",
        "SNH4": "NH4_N", "SNO3": "NO3_N"}
TOL = {"SAOC": .05, "SANI": .005, "SAPHW": .005, "SAPX": .05, "SAKE": .05, "SNH4": .005, "SNO3": .005}


def read_sources():
    spring25 = pd.read_excel(FILES[0], sheet_name="末-基础养分").rename(columns={
        "小区": "plot", "重复": "rep", "深度": "depth", "碱解氮": "AN", "全钾": "TK",
        "速效钾": "AK", "速效钾Cmol": "AK_cmol", "全磷": "TP", "速效磷": "AP",
        "铵态氮纯氮": "NH4_N", "硝态氮纯氮": "NO3_N", "全氮TN g/kg": "TN", "土壤有机碳 g/kg": "SOC",
    })
    spring26 = pd.read_excel(FILES[1], sheet_name="Sheet1").rename(columns={
        "小区号": "plot", "土样深度": "depth", "碱解氮（mg/kg）": "AN", "全钾（mg/g)": "TK",
        "AK(mg/kg)": "AK", "速效钾 Cmol": "AK_cmol", "全磷（mg/kg)": "TP", "AP(mg/kg)": "AP",
    })
    cn26 = pd.read_excel(FILES[2], sheet_name="Sheet1").rename(columns={
        "小区号": "plot", "重复": "rep", "深度": "depth", "水处理": "water_level",
        "氮处理": "nitrogen_level", "全氮g/kg": "TN", "有机碳含量（g/kg）": "SOC",
    })
    for source, keys in ((spring25, KEY + ["rep"]), (spring26, KEY), (cn26, KEY + ["rep"])):
        assert not source[keys].isna().any().any() and not source.duplicated(keys).any()
    assert spring25.groupby(KEY).size().eq(3).all() and cn26.groupby(KEY).size().eq(3).all()
    cn_shallow = cn26[cn26.depth.isin(LAYERS)]
    assert set(map(tuple, spring26[KEY].values)) == set(map(tuple, cn_shallow[KEY].values))
    print("Source rows (2025, 2026 other chemistry, 2026 C/N):", len(spring25), len(spring26), len(cn26))
    for year, source in ((2025, spring25), (2026, spring26)):
        print(year, "AK unit conversion discrepancy", (source.AK - source.AK_cmol*391).abs().max())
    return spring25, spring26, cn26


def model_rows(bundle):
    filex = next(bundle.glob("*.TMX"))
    result = []
    mode = None
    for line in filex.read_text(encoding="ascii").splitlines():
        if line.startswith("*"):
            mode = None
        elif line.startswith(("@A  SABL", "@C  ICBL")):
            mode = line[2:].split()
        elif line.startswith("@"):
            mode = None
        elif mode and line.strip() and not line.startswith("!"):
            factor = int(line[:2])
            values = [float(line[2+6*i:2+6*(i+1)]) for i in range(len(mode))]
            row = dict(zip(mode, values))
            bottom = int(row.get("SABL", row.get("ICBL")))
            if bottom <= 60:
                for field in CHEM.keys() & row.keys():
                    value = row[field] * (10 if field in {"SAOC", "SANI"} else 1)
                    result.append(dict(plot=factor, model_bottom_cm=bottom, field=field, bundle_value=value))
    return pd.DataFrame(result)


def sol_rows(bundle):
    result = []
    columns = None
    for line in (bundle / "SOIL.SOL").read_text(encoding="ascii").splitlines():
        if line.startswith("@  SLB"):
            columns = line[1:].split()
        elif columns and line.strip() and not line.startswith(("*", "@", "!")):
            values = dict(zip(columns, map(float, line.split())))
            if values["SLB"] <= 60:
                result.append({"model_bottom_cm": int(values["SLB"]), "SAOC": values["SLOC"]*10,
                               "SANI": values["SLNI"]*10, "SAPHW": values["SLHW"]})
    return pd.DataFrame(result).set_index("model_bottom_cm")


def compare(year, plots, bundle):
    depth_lookup = plots.set_index(KEY)
    audit = pd.read_csv(bundle / "soil_depth_mapping_audit.csv")
    layer_rows = model_rows(bundle)
    assert not layer_rows.duplicated(["plot", "model_bottom_cm", "field"]).any()
    details = []
    for row in layer_rows.itertuples(index=False):
        field, metric, bottom = row.field, CHEM[row.field], row.model_bottom_cm
        if metric not in plots:
            continue
        top = {2: 0, 4: 2, 15: 4, 30: 15, 40: 30, 60: 40}[bottom]
        vals, weights = [], []
        for depth in LAYERS:
            lo, hi = map(int, depth.split("-"))
            overlap = min(hi, bottom) - max(lo, top)
            if overlap > 0:
                vals.append(depth_lookup.loc[(row.plot, depth), metric])
                weights.append(overlap * (1 if field == "SAPHW" else bulk_density(lo, hi)))
        expected = np.average(vals, weights=weights)
        lookup = {"SAOC": "organic_c_pct", "SANI": "total_n_gkg", "SAPHW": "ph",
                  "SAPX": "available_p", "SAKE": "available_k"}.get(field, field)
        historical = audit.loc[(audit.trno == row.plot) & (audit.column == lookup) &
                               (audit.target_bottom_cm == bottom), "mapped_value"].item()
        historical *= 10 if field == "SAOC" else 1
        details.append(dict(year=year, **row._asdict(), model_top_cm=top, metric=metric,
                            latest_source_mapped=expected, bundle_audit_mapped=historical,
                            difference=row.bundle_value-expected,
                            within_print_precision=abs(row.bundle_value-expected) <= TOL[field]+1e-10,
                            agrees_with_bundle_audit=abs(row.bundle_value-historical) <= TOL[field]+1e-10))
    tmx = pd.DataFrame(details)
    expected = tmx.groupby(["model_bottom_cm", "field"]).latest_source_mapped.mean()
    sol = sol_rows(bundle).stack().rename_axis(["model_bottom_cm", "field"]).rename("bundle_value").reset_index()
    sol["latest_source_mapped"] = expected.reindex(pd.MultiIndex.from_frame(sol[["model_bottom_cm", "field"]])).to_numpy()
    sol["difference"] = sol.bundle_value - sol.latest_source_mapped
    sol["within_print_precision"] = sol.difference.abs().le(sol.field.map(TOL)+1e-10)
    return tmx, sol.assign(year=year)


def main():
    s25, s26, cn26 = read_sources()
    metadata = {year: pd.read_csv(bundle / "treatment_metadata.csv").rename(columns={"treatment": "plot"})
                for year, bundle in BUNDLES.items()}
    sources = {2025: s25.groupby(KEY, as_index=False).mean(numeric_only=True).drop(columns="rep"),
               2026: s26.merge(cn26.groupby(KEY, as_index=False)[["SOC", "TN"]].mean(), on=KEY,
                              validate="one_to_one")}
    labels = cn26[["plot", "water_level", "nitrogen_level"]].drop_duplicates().merge(
        metadata[2026], on="plot", suffixes=("_source", "_bundle"), validate="one_to_one")
    print("2026 treatment label differences:", {
        kind: labels.loc[labels[f"{kind}_level_source"].ne(labels[f"{kind}_level_bundle"]), "plot"].tolist()
        for kind in ("water", "nitrogen")})
    cells, shared, used, provenance = [], [], [], {}
    for year, bundle in BUNDLES.items():
        manifest = verify_manifest_integrity(bundle)
        selected = metadata[year]["plot"]
        data = sources[year][sources[year]["plot"].isin(selected)]
        print(year, "source plots excluded", sorted(set(sources[year]["plot"])-set(selected)))
        assert set(data["plot"]) == set(selected) and len(data) == 3*len(selected)
        used.append(data.assign(year=year))
        tmx, sol = compare(year, data, bundle)
        cells.append(tmx)
        shared.append(sol)
        provenance[year] = dict(bundle=str(bundle), manifest_sha256=manifest.manifest_sha256, plots=selected.tolist())
    OUT.mkdir(parents=True, exist_ok=True)
    assert not any(OUT.iterdir())
    pd.concat(used).to_csv(OUT / "table1_plot_layer_means.csv", index=False)
    stat = pd.concat(used).groupby(["year", "depth"]).agg(
        {c: ["mean", "std", "count"] for c in ["SOC", "TN", "TP", "TK", "pH", "EC", "AK", "AP", "AN", "NH4_N", "NO3_N"]})
    stat.columns = ["_".join(c) for c in stat.columns]
    stat.to_csv(OUT / "table1_soil_summary.csv")
    print(stat.round(3).to_string())
    tmx = pd.concat(cells)
    tmx.to_csv(OUT / "tmx_source_comparison.csv", index=False)
    pd.concat(shared).to_csv(OUT / "shared_sol_source_comparison.csv", index=False)
    labels.to_csv(OUT / "2026_treatment_label_check.csv", index=False)
    print(tmx.groupby(["year", "field"]).agg(rows=("plot", "size"), matches=("within_print_precision", "sum"),
          audit_matches=("agrees_with_bundle_audit", "sum"), min_diff=("difference", "min"), max_diff=("difference", "max")).to_string())
    print(pd.concat(shared).round(4).to_string(index=False))
    (OUT / "provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2)+"\n",encoding="utf8")


if __name__ == "__main__":
    main()
