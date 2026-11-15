import csv

base = r"D:\Tomato_Cal\subprojects\critical_n\root_n_kernel_20261112\runs"
for mode in ("n4864_rnkA_smoke", "n4864_rnkB_smoke"):
    rows = list(csv.DictReader(open(base + "\\" + mode + "\\LayerRootNUptake.csv")))
    n_bad_commit = sum(1 for r in rows if r["source_day"] != r["soil_commit_day"])
    n_bad_order = sum(1 for r in rows if not (float(r["candidate_gN_m2"]) >= float(r["accepted_gN_m2"]) - 1e-9 >= float(r["deducted_gN_m2"]) - 2e-9))
    n_bad_cap = sum(1 for r in rows if float(r["deducted_gN_m2"]) > float(r["stock_cap_gN_m2"]) + 1e-6)
    st = {}
    for r in rows:
        st[r["solver_status"]] = st.get(r["solver_status"], 0) + 1
    no3 = sum(float(r["deducted_gN_m2"]) for r in rows if r["species"] == "1")
    nh4 = sum(float(r["deducted_gN_m2"]) for r in rows if r["species"] == "2")
    print(f"{mode}: rows={len(rows)} bad_commit={n_bad_commit} bad_order={n_bad_order} bad_cap={n_bad_cap}")
    print(f"  solver_status dist: {dict(sorted(st.items()))}")
    print(f"  season deducted: NO3={no3:.2f} NH4={nh4:.2f} g/m2 (12 runs)")
