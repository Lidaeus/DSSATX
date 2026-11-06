"""Minimal, deterministic stage representative-parameter generator."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pandas as pd


STAGE_REPRESENTATIVE_MANIFEST_FIELDS = frozenset({
    "stage_representative_params",
    "stage_representative_params_sha256",
    "stage_representative_rule",
    "stage_representative_source",
    "stage_representative_source_sha256",
})


def clear_stage_representative_manifest_fields(manifest_path: str | Path) -> list[str]:
    """Remove inherited finalization fields from a cloned run manifest.

    Run directories used as build templates can already be finalized.  Their
    representative-parameter fields describe the source run and must never be
    carried into a newly named case before that case has completed.
    """
    path = Path(manifest_path)
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    kept: list[str] = []
    removed: list[str] = []
    for line in lines:
        key = line.split(":", 1)[0].strip() if ":" in line else ""
        if key in STAGE_REPRESENTATIVE_MANIFEST_FIELDS:
            removed.append(key)
        else:
            kept.append(line)
    path.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")
    return removed


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_final_iteration(run_dir: str | Path, case: str) -> tuple[int, Path]:
    """Resolve the final ensemble using the live PST/Phi contract.

    A cloned run directory can contain historical ``case.N.par.csv`` files.
    Selecting the numerically largest file silently promotes stale output when
    the new run has a smaller ``noptmax``.  Bound the selection by both the PST
    ``noptmax`` and the largest iteration persisted in ``phi.actual.csv``.
    """
    directory = Path(run_dir).resolve()
    pattern = re.compile(rf"^{re.escape(case)}\.(\d+)\.par\.csv$")
    candidates: dict[int, Path] = {}
    for path in directory.glob(f"{case}.*.par.csv"):
        match = pattern.match(path.name)
        if match:
            candidates[int(match.group(1))] = path
    if not candidates:
        raise FileNotFoundError(f"No parameter ensembles found for {case}")

    ceilings: list[int] = []
    pst_path = directory / f"{case}.pst"
    if pst_path.is_file():
        try:
            import pyemu
            noptmax = int(pyemu.Pst(str(pst_path)).control_data.noptmax)
            if noptmax >= 0:
                ceilings.append(noptmax)
        except Exception:
            pass
    phi_path = directory / f"{case}.phi.actual.csv"
    if phi_path.is_file():
        try:
            phi = pd.read_csv(phi_path)
            iterations = pd.to_numeric(phi.get("iteration"), errors="coerce").dropna()
            if not iterations.empty:
                ceilings.append(int(iterations.max()))
        except Exception:
            pass
    ceiling = min(ceilings) if ceilings else max(candidates)
    eligible = [iteration for iteration in candidates if iteration <= ceiling]
    if not eligible:
        raise RuntimeError(
            f"No parameter ensemble is compatible with final-iteration ceiling {ceiling}"
        )
    iteration = max(eligible)
    return iteration, candidates[iteration]


def write_stage_representative(run_dir: str | Path, case: str) -> dict[str, str] | None:
    """Write the median of the final numeric ensemble as ``name,value`` rows."""
    directory = Path(run_dir).resolve()
    try:
        iteration, source = resolve_final_iteration(directory, case)
    except FileNotFoundError:
        return None
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
