"""Minimal, deterministic stage representative-parameter generator."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pandas as pd


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_stage_representative(run_dir: str | Path, case: str) -> dict[str, str] | None:
    """Write the median of the final numeric ensemble as ``name,value`` rows."""
    directory = Path(run_dir).resolve()
    candidates: list[tuple[int, Path]] = []
    pattern = re.compile(rf"^{re.escape(case)}\.(\d+)\.par\.csv$")
    for path in directory.glob(f"{case}.*.par.csv"):
        match = pattern.match(path.name)
        if match:
            candidates.append((int(match.group(1)), path))
    if not candidates:
        return None
    iteration, source = max(candidates)
    frame = pd.read_csv(source)
    real_col = next((c for c in frame.columns if str(c).lower() in {"real_name", "realization"}), None)
    value_cols = [c for c in frame.columns if c != real_col]
    rows = []
    for name in value_cols:
        values = pd.to_numeric(frame[name], errors="coerce").dropna()
        if not values.empty:
            rows.append({"name": str(name), "value": float(values.median())})
    if not rows:
        return None
    out_dir = directory / "calibration_finalize"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "stage_representative_params.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    metadata = {
        "schema_version": 1,
        "rule": "median_of_final_parameter_ensemble",
        "case": case,
        "source": source.name,
        "source_sha256": _sha256(source),
        "iteration": iteration,
        "output": out.name,
        "output_sha256": _sha256(out),
    }
    (out_dir / "stage_representative_params.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "path": str(out),
        "sha256": metadata["output_sha256"],
        "rule": metadata["rule"],
        "source": source.name,
        "source_sha256": metadata["source_sha256"],
    }

