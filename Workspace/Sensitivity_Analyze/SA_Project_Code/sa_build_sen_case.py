import argparse
import os
import shutil

import pandas as pd
import pyemu


def _workspace_dir_from_this_file():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", ".."))


def _write_params_csv_and_tpl(param_df, params_csv_path, tpl_path):
    df = param_df.copy()
    df = df[df["status"].astype(str).str.lower().isin(["active", "adjustable", "free", "log", "none", "both"]) | (df["status"].astype(str).str.lower() == "active")]
    rows = []
    for _, r in df.iterrows():
        name = str(r["name"]).strip().upper()
        init = float(r["init"]) if pd.notna(r["init"]) else 0.0
        rows.append({"name": name, "value": init})
    out_df = pd.DataFrame(rows)
    out_df.to_csv(params_csv_path, index=False)

    with open(tpl_path, "w", encoding="utf-8") as f:
        f.write("ptf ~\n")
        f.write("name,value\n")
        for _, r in out_df.iterrows():
            name = str(r["name"]).strip().upper()
            f.write(f"{name},~ {name} ~\n")

    return out_df


def _write_indicators_ins(observation_names, ins_path):
    with open(ins_path, "w", encoding="utf-8") as f:
        f.write("pif ~\n")
        for n in observation_names:
            f.write(f"l1 w !{n}!\n")


def _default_observation_names():
    tns = [2, 3]
    base = [
        "YIELD_HWAMS",
        "HIAMS",
        "LAIXM",
        "CWAMS",
        "ADAPS",
        "PDFPS",
        "MDAPS",
        "LAI_AUC",
        "LAI_PEAK",
        "LAI_TPEAK",
        "LAI_END",
        "FRUITD_AUC",
        "FRUITD_END",
        "LEAF_END_LWAD",
        "STEM_END_SWAD",
        "AGB_END_CWAD",
        "HI_END_HIAD",
    ]
    daps = [28, 42, 56, 70, 84, 98, 112]
    names = []
    for tn in tns:
        p = f"TN{tn}_"
        for b in base:
            names.append(p + b)
        for d in daps:
            names.append(f"{p}LAI_DAP{d:03d}")
            names.append(f"{p}FRUITD_DAP{d:03d}")
    for b in base:
        names.append("MEAN_" + b)
    for d in daps:
        names.append(f"MEAN_LAI_DAP{d:03d}")
        names.append(f"MEAN_FRUITD_DAP{d:03d}")
    return names


def build_case(
    param_review_csv,
    case_dir,
    workspace_dir,
    cultivar="TM0008",
    morris_r=100,
    morris_p=None,
    morris_delta=None,
):
    os.makedirs(case_dir, exist_ok=True)
    case_dir = os.path.abspath(case_dir)
    workspace_dir = os.path.abspath(workspace_dir)

    review_df = pd.read_csv(param_review_csv)
    review_df["name"] = review_df["name"].astype(str).str.strip().str.upper()
    review_df["status"] = review_df["status"].fillna("active")

    params_csv_name = "sa_params.csv"
    tpl_name = "sa_params.csv.tpl"
    params_csv = os.path.join(case_dir, params_csv_name)
    tpl_path = os.path.join(case_dir, tpl_name)
    _write_params_csv_and_tpl(review_df[review_df["status"].str.lower() == "active"], params_csv, tpl_path)

    out_name = "SA_Indicators.OUT"
    ins_name = "SA_Indicators.OUT.ins"
    ins_path = os.path.join(case_dir, ins_name)
    obs_names = _default_observation_names()
    _write_indicators_ins(obs_names, ins_path)
    obs_order_path = os.path.join(case_dir, "sa_obs_order.txt")
    with open(obs_order_path, "w", encoding="utf-8") as f:
        for n in obs_names:
            f.write(str(n) + "\n")

    pst_path = os.path.join(case_dir, "sa_sen_morris.pst")

    cwd0 = os.getcwd()
    try:
        os.chdir(case_dir)
        pst = pyemu.Pst.from_io_files(
            tpl_files=[tpl_name],
            in_files=[params_csv_name],
            ins_files=[ins_name],
            out_files=[out_name],
        )
    finally:
        os.chdir(cwd0)
    pst.control_data.noptmax = 0

    for p in pst.parameter_data.parnme:
        m = review_df[review_df["name"] == p.upper()]
        if m.empty:
            continue
        r = m.iloc[0]
        try:
            if pd.notna(r.get("init")):
                pst.parameter_data.loc[p, "parval1"] = float(r["init"])
        except Exception:
            pass
        try:
            pst.parameter_data.loc[p, "parlbnd"] = float(r["lower"]) if pd.notna(r["lower"]) else pst.parameter_data.loc[p, "parlbnd"]
            pst.parameter_data.loc[p, "parubnd"] = float(r["upper"]) if pd.notna(r["upper"]) else pst.parameter_data.loc[p, "parubnd"]
        except Exception:
            pass
        pst.parameter_data.loc[p, "pargp"] = str(r.get("pargp", ""))[:12] if pd.notna(r.get("pargp", "")) else ""

    pst.parameter_data.loc[:, "partrans"] = "none"

    pst.observation_data.loc[:, "weight"] = 1.0

    model_script = os.path.normpath(os.path.join(workspace_dir, "Sensitivity_Analyze", "SA_Project_Code", "sa_model.py"))
    batch_path = os.path.normpath(os.path.join(workspace_dir, "DSSBatch.v48"))
    model_cmd = (
        f"python \"{model_script}\" --workspace . --batch \"{batch_path}\" "
        f"--cultivar {cultivar} --param-csv {params_csv_name} --out {out_name} --obs-order sa_obs_order.txt"
    )
    pst.model_command = [model_cmd]

    pst.pestpp_options["gsa_morris_r"] = int(morris_r)
    if morris_p is not None:
        pst.pestpp_options["gsa_morris_p"] = int(morris_p)
    if morris_delta is not None:
        pst.pestpp_options["gsa_morris_delta"] = float(morris_delta)
    pst.pestpp_options["gsa_morris_obs_sen"] = True

    pst.write(pst_path)

    pst_sobol_path = os.path.join(case_dir, "sa_sen_sobol.pst")
    pst_sobol = pyemu.Pst(pst_path)
    pst_sobol.pestpp_options["gsa_method"] = "sobol"
    pst_sobol.pestpp_options["gsa_sobol_samples"] = 1000
    pst_sobol.write(pst_sobol_path)

    for fp in [model_script]:
        if os.path.exists(fp):
            shutil.copy(fp, os.path.join(case_dir, os.path.basename(fp)))

    return pst_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--param-review",
        default=None,
    )
    parser.add_argument("--case-dir", default=None)
    parser.add_argument("--cultivar", default="TM0008")
    parser.add_argument("--morris-r", type=int, default=100)
    parser.add_argument("--morris-p", type=int, default=None)
    parser.add_argument("--morris-delta", type=float, default=None)
    args = parser.parse_args()

    workspace_dir = _workspace_dir_from_this_file()
    param_review = (
        os.path.normpath(args.param_review)
        if args.param_review
        else os.path.join(workspace_dir, "Sensitivity_Analyze", "SA_Project_Output", "sensitivity_param_review.csv")
    )
    case_dir = (
        os.path.normpath(args.case_dir)
        if args.case_dir
        else os.path.join(workspace_dir, "Sensitivity_Analyze", "SA_Project_Output", "sen_case")
    )

    pst_path = build_case(
        param_review,
        case_dir=case_dir,
        workspace_dir=workspace_dir,
        cultivar=args.cultivar,
        morris_r=args.morris_r,
        morris_p=args.morris_p,
        morris_delta=args.morris_delta,
    )
    print(f"Wrote: {pst_path}")


if __name__ == "__main__":
    main()
