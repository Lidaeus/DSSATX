import argparse
import os

import pandas as pd
import pyemu


def _default_case_dir():
    workspace_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    return os.path.join(workspace_dir, "workspace", "runs", "sa_output", "sen_case")


def prepare_sobol_case(case_dir, topk_csv, out_pst_name="sa_sen_sobol.pst", n_samples=1000):
    case_dir = os.path.normpath(case_dir)
    topk = pd.read_csv(topk_csv)
    name_col = None
    for c in topk.columns:
        if str(c).strip().lower() in {"par", "parnme", "name", "parameter"}:
            name_col = c
            break
    if name_col is None:
        name_col = topk.columns[0]
    keep = set(topk[name_col].astype(str).str.strip().str.upper().tolist())

    base_pst = os.path.join(case_dir, "sa_sen_morris.pst")
    if not os.path.exists(base_pst):
        raise FileNotFoundError(base_pst)
    pst = pyemu.Pst(base_pst)
    for p in pst.parameter_data.parnme:
        if str(p).strip().upper() in keep:
            continue
        pst.parameter_data.loc[p, "partrans"] = "fixed"
        v = float(pst.parameter_data.loc[p, "parval1"])
        pst.parameter_data.loc[p, "parlbnd"] = v
        pst.parameter_data.loc[p, "parubnd"] = v

    pst.pestpp_options["gsa_method"] = "sobol"
    pst.pestpp_options["gsa_sobol_samples"] = int(n_samples)
    pst.write(os.path.join(case_dir, out_pst_name))
    return os.path.join(case_dir, out_pst_name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", default=None)
    parser.add_argument("--topk", default=None)
    parser.add_argument("--samples", type=int, default=1000)
    args = parser.parse_args()

    case_dir = os.path.normpath(args.case_dir) if args.case_dir else _default_case_dir()
    topk_csv = (
        os.path.normpath(args.topk)
        if args.topk
        else os.path.join(os.path.dirname(case_dir), "morris_results", "topk_params.csv")
    )
    out_pst = prepare_sobol_case(case_dir=case_dir, topk_csv=topk_csv, out_pst_name="sa_sen_sobol.pst", n_samples=args.samples)
    print(f"Wrote: {out_pst}")


if __name__ == "__main__":
    main()
