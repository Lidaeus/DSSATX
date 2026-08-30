"""Run the standard best-member audit against the v15 boundary-fix run."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import tools.analysis.analyze_formal_measuredmoisture_best42_20260819 as audit

audit.CASE = "e02_v15_boundary_fix_official_200x6_20260819"
audit.RUN = ROOT / "workspace/runs" / audit.CASE
audit.DET = audit.RUN / "deterministic_candidates/best_phi_member38_two_season_20260819"
audit.OUT = ROOT / "figture/e02_v15_boundary_fix_best38_two_season_full_20260819"
audit.BEST = "38"


if __name__ == "__main__":
    raise SystemExit(audit.main())
