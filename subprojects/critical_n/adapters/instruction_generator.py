"""PEST++ instruction file generator for PestCNC.OUT.

Generates rigid instruction files (PestCNC.ins) matching PestCNC.OUT.
Supports:
1. Phenological subsampling (e.g. 3~5 key stages per treatment) to avoid
   collinear redundancy while preserving well-conditioned TSVD inversion.
2. Rigid line advances (l1 / l<skip>) and column-range extraction [obs_name]55:64.
3. Clean observation naming: cnc_t{trt}_dap{das} or cnc_r{run}_d{das}.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple, Union

from subprojects.critical_n.adapters.pest_cnc_exporter import (
    HEADER_COLUMNS,
    HEADER_TITLE,
    PEST_CNC_FILENAME,
)
from subprojects.critical_n.adapters.stream_parser import (
    DailyMergedRecord,
    load_merged_nitrogen_series,
)


# Column slice definitions (1-indexed PEST character positions)
COLUMN_SLICES = {
    "CWAD_T": (25, 34),
    "N_ACT": (35, 44),
    "NC_CRIT": (45, 54),
    "NNI": (55, 64),
}


@dataclass(frozen=True)
class CNCObservationTarget:
    """Target observation definition for PEST++."""

    obs_name: str
    run_id: int
    treatment_id: int
    das: int
    variable: str = "NNI"
    target_value: float = 1.05
    weight: float = 0.25
    group: str = "cnc_nni"


def make_obs_name(treatment_id: int, das: int, var_prefix: str = "cnc") -> str:
    """Generate standardized PEST observation name (<= 20 chars for PEST compatibility).

    Example: cnc_t2_d55
    """
    return f"{var_prefix}_t{treatment_id}_d{das}"


def generate_pest_cnc_instructions(
    run_dir: Union[str, Path],
    selected_targets: Sequence[CNCObservationTarget],
    ins_file_path: Optional[Union[str, Path]] = None,
    use_line_skips: bool = True,
) -> Path:
    """Generate a rigid PestCNC.ins instruction file for the selected observation targets.

    Parameters
    ----------
    run_dir : Path or str
        DSSAT run directory containing outputs (used to discover row sequence).
    selected_targets : Sequence[CNCObservationTarget]
        List of targets to extract.
    ins_file_path : Path or str, optional
        Destination .ins file path. Default is `run_dir / "PestCNC.OUT.ins"`.
    use_line_skips : bool, optional
        If True, compress consecutive non-observed lines into `l<n>`. Default True.

    Returns
    -------
    Path
        Path to the generated instruction file.
    """
    dir_path = Path(run_dir)
    target_ins = Path(ins_file_path) if ins_file_path else dir_path / f"{PEST_CNC_FILENAME}.ins"

    # Index targets by (run_id, das)
    target_map: dict[tuple[int, int], CNCObservationTarget] = {
        (t.run_id, t.das): t for t in selected_targets
    }

    runs_data = load_merged_nitrogen_series(dir_path)

    header_marker = HEADER_COLUMNS.strip().lstrip("@")
    ins_lines = ["pif @\n", "l1\n", f"@{header_marker}@\n"]

    pending_skips = 0

    for run_id in sorted(runs_data.keys()):
        records = runs_data[run_id]
        for rec in records:
            key = (rec.run_id, rec.das)
            if key in target_map:
                target = target_map[key]
                col_start, col_end = COLUMN_SLICES.get(str(target.variable).upper(), (55, 64))

                if pending_skips > 0:
                    if use_line_skips:
                        ins_lines.append(f"l{pending_skips}\n")
                    else:
                        ins_lines.extend(["l1\n"] * pending_skips)
                    pending_skips = 0

                ins_lines.append(f"l1 [{target.obs_name}]{col_start}:{col_end}\n")
            else:
                pending_skips += 1

    # In PEST instruction files, no trailing skips are required after the final observation.
    target_ins.write_text("".join(ins_lines), encoding="utf-8")
    return target_ins
