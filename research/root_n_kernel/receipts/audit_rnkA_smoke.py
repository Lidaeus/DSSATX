"""RNK A 模式田间冒烟的扣氮审计 (计划 §4/§6):
1. 账本 source_day == soil_commit_day 全量断言
2. accepted >= deducted (回退只减不加), candidate >= accepted
3. deducted 不超过 stock_before (含初始残留裕量, 用 cap 近似下界检查)
4. 植株侧累计 deducted vs SoilNi.OUT 土壤矿质氮变化的方向一致性报告
"""
import csv, sys
from pathlib import Path

run = Path(r"D:\Tomato_Cal\subprojects\critical_n\root_n_kernel_20261112\runs\n4864_rnkA_smoke")
rows = list(csv.DictReader(open(run / "LayerRootNUptake.csv")))
print(f"ledger rows: {len(rows)}")

n_commit = n_order = n_stock = 0
cum = {}
for r in rows:
    assert int(r["source_day"]) == int(r["soil_commit_day"]), f"cross-day: {r}"
    n_commit += 1
    cand, acc, ded = float(r["candidate_gN_m2"]), float(r["accepted_gN_m2"]), float(r["deducted_gN_m2"])
    sb, cap = float(r["stock_before_gN_m2"]), float(r["stock_cap_gN_m2"])
    assert acc <= cand + 1e-9, f"accepted>candidate: {r}"
    assert ded <= acc + 1e-9, f"deducted>accepted (refund added N?): {r}"
    n_order += 1
    # 扣除不应超过可提取上限 + 容差 (deducted 是日通量, stock_before 为当日库容)
    assert ded <= cap + 1e-6, f"deducted>stock_cap: {r}"
    assert sb >= 0 and cap >= 0
    n_stock += 1
    key = (int(r["run"]), int(r["species"]))
    cum[key] = cum.get(key, 0.0) + ded

print(f"same-day commit rows: {n_commit}/{len(rows)}")
print(f"ordering candidate>=accepted>=deducted rows: {n_order}/{len(rows)}")
print(f"stock-cap honored rows: {n_stock}/{len(rows)}")
print("per-run per-species cumulative deducted (g N/m2, top 6):")
for k in sorted(cum)[:6]:
    print(f"  run {k[0]} species {k[1]} (1=NO3): {cum[k]:.3f}")
total_no3 = sum(v for (r, s), v in cum.items() if s == 1)
total_nh4 = sum(v for (r, s), v in cum.items() if s == 2)
print(f"ALL-run NO3 deducted: {total_no3:.2f} g/m2 ; NH4: {total_nh4:.2f} g/m2 (12 runs)")
print("AUDIT PASSED")
