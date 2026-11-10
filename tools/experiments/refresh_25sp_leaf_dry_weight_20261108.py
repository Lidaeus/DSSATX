"""Refresh the cold-storage validation bundle with corrected leaf dry weights."""

from pathlib import Path
import json
import shutil
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.calibration.audit_observations import audit_observation_bundle, read_dssat_observation_table
from src.common.input_manifest import verify_manifest_integrity
from tools.experiments import rebuild_current_bundles as legacy
from tools.experiments.refresh_spring_inputs_20261027 import compare_observations

OLD = Path("D:/Tomato_Cal_Cold_Storage/bundle_retirement_20261105/calibration/xxql2501_refreshed_20261027")
SOURCE = Path("D:/三季节数据汇总/2025春/2025春作物生长指标集.xlsx")
NEW = ROOT / "data/user/experiments/xxql2501_refreshed_lwad_20261108"
KEYS = ["trno", "rep", "date"]


def read_csv(path):
    return pd.read_csv(path, float_precision="round_trip")


def update_file(path, keys, values):
    """Replace only the requested six-character fields and reread FileA/FileT."""
    rows = path.read_text(encoding="ascii").splitlines()
    header = next(i for i, line in enumerate(rows) if line.startswith("@TRNO"))
    cols = rows[header][1:].split()
    pending = {(k, c): v for c, series in values.items() for k, v in series.items()}
    for i, line in enumerate(rows[header + 1:], header + 1):
        if not line.strip() or line.startswith("!"):
            continue
        key = tuple(int(line[6 * cols.index(c):6 * (cols.index(c) + 1)]) for c in keys)
        key = key[0] if len(key) == 1 else key
        for col in values:
            if (key, col) in pending:
                start = 6 * cols.index(col)
                line = line[:start] + legacy.numeric_field(col, pending.pop((key, col))) + line[start + 6:]
        rows[i] = line
    assert not pending, pending
    path.write_text("\n".join(rows) + "\n", encoding="ascii")
    return read_dssat_observation_table(path)


def main():
    old_manifest = verify_manifest_integrity(OLD)
    source_hash = legacy.sha(SOURCE)
    original = read_csv(OLD / "growth_replicates.csv").set_index(KEYS)
    source = pd.read_excel(SOURCE, sheet_name="Sheet1").rename(
        columns={"小区号": "trno", "重复": "rep", "日期": "date"})
    source["date"] = source.date.map(lambda day: legacy.date_of(day).date().isoformat())
    source = source.set_index(KEYS, verify_integrity=True)
    assert set(source.index) == set(original.index)
    source = source.reindex(original.index)
    pd.testing.assert_frame_equal(source.drop(columns="叶干重"), original[source.columns].drop(columns="叶干重"),
                                  check_dtype=False)
    leaf = pd.to_numeric(source["叶干重"], errors="raise")
    assert leaf.notna().equals(original.LWAD.notna()) and np.isfinite(leaf.dropna()).all() and (leaf.dropna() >= 0).all()
    growth = original.copy()
    growth["叶干重"], growth["LWAD"] = leaf, leaf * 27
    changed_reps = int((~np.isclose(original.LWAD, growth.LWAD, rtol=0, atol=1e-10, equal_nan=True)).sum())
    l_summary = growth.reset_index().groupby(["trno", "date"]).LWAD.agg(["mean", "std", "count"])
    l_summary = l_summary[l_summary["count"].gt(0)]
    last_mass = l_summary["mean"].groupby(level="trno").last()

    npk = read_csv(OLD / "plant_npk_source_values.csv").query("organ == '叶'").set_index(KEYS)
    mass = growth.LWAD.reindex(npk.index)
    assert npk.index.is_unique and mass.notna().all()
    amounts = npk[["N", "P", "K"]].mul(mass, axis=0) / 1000
    n_summary = amounts.N.groupby(["trno", "date"]).agg(["mean", "std", "count"])
    n_audit = read_csv(OLD / "standing_npk_calculation_audit.csv")
    leaf_mask = n_audit.organ.eq("叶")
    lookup = amounts.stack()
    keys = pd.MultiIndex.from_frame(n_audit.loc[leaf_mask, ["trno", "rep", "growth_date", "nutrient"]])
    assert len(keys) == len(lookup) and keys.is_unique and lookup.reindex(keys).notna().all()
    n_audit.loc[leaf_mask, "amount_kg_ha"] = lookup.reindex(keys).to_numpy()

    shutil.copytree(OLD, NEW)
    growth.reset_index().loc[:, read_csv(OLD / "growth_replicates.csv").columns].to_csv(
        NEW / "growth_replicates.csv", index=False)
    n_audit.to_csv(NEW / "standing_npk_calculation_audit.csv", index=False)
    def dated(series):
        return pd.Series(series.to_numpy(), index=[(tn, legacy.code(day)) for tn, day in series.index])

    t = update_file(NEW / "XXQL2501.TMT", ["TRNO", "DATE"],
                    {"LWAD": dated(l_summary["mean"]), "LNAM": dated(n_summary["mean"])})
    a = update_file(NEW / "XXQL2501.TMA", ["TRNO"], {"LWAM": last_mass})
    t.to_csv(NEW / "FileT_values.csv", index=False)
    a.to_csv(NEW / "FileA_values.csv", index=False)
    printed = t.set_index(["TRNO", "DATE"])
    u = read_csv(OLD / "observation_uncertainty.csv")
    for variable, summary in (("LWAD", l_summary), ("LNAM", n_summary)):
        mask = u.variable.eq(variable)
        k = pd.MultiIndex.from_frame(u.loc[mask, ["trno", "date"]])
        assert len(k) == len(summary) and set(k) == set(summary.index)
        table = summary.reindex(k)
        u.loc[mask, ["unrounded_source_mean", "raw_sd", "n_rep", "n_samples"]] = table[
            ["mean", "std", "count", "count"]].to_numpy()
        u.loc[mask, "value"] = [printed.loc[(tn, legacy.code(day)), variable] for tn, day in k]
    u.to_csv(NEW / "observation_uncertainty.csv", index=False)

    changes = pd.DataFrame(compare_observations(OLD, NEW, "XXQL2501"))
    assert changes.variable.value_counts().to_dict() == {"LWAD": 32, "LWAM": 8, "LNAM": 8}
    changes.to_csv(NEW / "observation_value_changes.csv", index=False)
    audit, reconcile = audit_observation_bundle(NEW)
    assert audit["error_count"] == 0, audit["findings"]
    legacy.write_json(NEW / "input_quality_audit.json", audit)
    reconcile.to_csv(NEW / "harvest_increment_reconciliation.csv", index=False)
    acceptance = json.loads((OLD / "calibration_reader_acceptance.json").read_text(encoding="utf8"))
    acceptance.update(leaf_dry_weight_refresh=dict(replicates_changed=changed_reps,
                      FileA_FileT_changed_fields=changes.variable.value_counts().to_dict(), input_audit_errors=0))
    legacy.write_json(NEW / "calibration_reader_acceptance.json", acceptance)
    decision = json.loads((OLD / "decision_record.json").read_text(encoding="utf8"))
    decision.update(date="2026-11-08", refresh_scope="25SP leaf dry weight and derived standing leaf nutrient amounts")
    legacy.write_json(NEW / "decision_record.json", decision)
    assert source_hash == legacy.sha(SOURCE)
    provenance = dict(baseline_bundle=str(OLD), baseline_manifest_sha256=old_manifest.manifest_sha256,
                      sources=[dict(path=str(SOURCE), sha256=source_hash, sheet="Sheet1", field="叶干重")],
                      generator=str(Path(__file__).relative_to(ROOT)), generator_sha256=legacy.sha(__file__))
    legacy.write_json(NEW / "source_provenance.json", provenance)
    manifest = json.loads((OLD / "input_manifest.json").read_text(encoding="utf8"))
    manifest.update(bundle_id=NEW.name, created="2026-11-08", decision_record=decision,
                    source_provenance_sha256=legacy.sha(NEW / "source_provenance.json"),
                    generator_sha256=legacy.sha(__file__),
                    engineering_checks="updated FileA/FileT audit passed; baseline native simulation inputs preserved",
                    files=[dict(name=p.name, sha256=legacy.sha(p), size_bytes=p.stat().st_size)
                           for p in sorted(NEW.iterdir()) if p.is_file() and p.name != "input_manifest.json"])
    legacy.write_json(NEW / "input_manifest.json", manifest)
    print(verify_manifest_integrity(NEW).manifest_sha256, changed_reps, changes.variable.value_counts().to_dict())


if __name__ == "__main__":
    main()
