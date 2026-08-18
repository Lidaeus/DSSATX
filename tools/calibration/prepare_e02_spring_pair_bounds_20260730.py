"""Create the approved spring-pair bounds proposal from the historical v6 bounds."""

from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_joint62_m1_offsets_v5_plantn_slpf_20260729.csv"
PROPOSAL = ROOT / "data/parameter_registry/bounds_proposals/eggplant_e02_spring_pair_histbest_rtn_relax_20260730.csv"

def main() -> int:
    b = pd.read_csv(SOURCE, encoding="utf-8-sig")
    b.loc[b["name"].isin(["DLFMAX_AUT", "DSLAVR_AUT", "DXFRT_AUT", "DSFDUR_AUT", "DTB1_AUT", "DTB2_AUT", "DTB3_AUT"]), "status"] = "disabled"
    b.loc[b["name"].eq("RTNH4"), "lower"] = 0.001
    b.loc[b["name"].eq("RTNO3"), "lower"] = 0.003
    b.loc[b["name"].eq("RTNH4"), "review_note"] = "Historical v6 spring-pair baseline; user-approved lower-bound relaxation to 0.001"
    b.loc[b["name"].eq("RTNO3"), "review_note"] = "Historical v6 spring-pair baseline; user-approved lower-bound relaxation to 0.003"
    PROPOSAL.parent.mkdir(parents=True, exist_ok=True)
    b.to_csv(PROPOSAL, index=False, encoding="utf-8-sig")
    print(PROPOSAL)
    print(b.loc[b["name"].isin(["RTNH4", "RTNO3"]), ["name", "init", "lower", "upper", "status"]].to_string(index=False))
    print(f"active={int(b['status'].astype(str).str.lower().eq('active').sum())}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
