"""Fail-closed source checks for IES diagnostic parameter plots (not science approval)."""
from pathlib import Path
import hashlib
import numpy as np
import pandas as pd


def load_ies_plot_sources(run_dir, case, iteration, *, prior=None):
    root = Path(run_dir).resolve()
    if Path(case).name != case or iteration < 1:
        raise ValueError("Explicit case basename and positive posterior iteration required")
    post_path = root / f"{case}.{iteration}.par.csv"
    prior_path = Path(prior).resolve() if prior else root / f"{case}.0.par.csv"
    expected_prior = root / f"{case}.0.par.csv"
    if prior_path != expected_prior or not prior_path.is_file():
        raise ValueError("Missing/mismatched same-run IES prior; posterior cannot replace prior")
    pst_path = root / f"{case}.pst"
    phi_path = root / f"{case}.phi.actual.csv"
    paths = [prior_path, post_path, pst_path, phi_path]
    for path in paths:
        if not path.is_file():
            raise ValueError(f"Missing IES source: {path}")
    bounds = {}
    in_parameters = False
    for line in pst_path.read_text(encoding="utf-8-sig").splitlines():
        if line.lstrip().startswith("*"):
            in_parameters = line.strip().lower() == "* parameter data"
        elif in_parameters and line.strip():
            cells = line.split()
            if len(cells) >= 7:
                bounds[cells[0].lower()] = (float(cells[4]), float(cells[5]))
    if not bounds:
        raise ValueError("PST parameter bounds are absent/unsupported")
    phi = pd.read_csv(phi_path)
    if not {"iteration", "total_runs", "mean"}.issubset(phi.columns):
        raise ValueError("Expected original IES member-wise phi.actual.csv, not a summary/grid score")
    frames = []
    for path, it in [(prior_path, 0), (post_path, iteration)]:
        frame = pd.read_csv(path, dtype={"real_name": str})
        frame.columns = frame.columns.str.lower()
        if "real_name" not in frame or frame.real_name.duplicated().any() or len(frame) < 2:
            raise ValueError(f"Invalid realization identities: {path}")
        frame = frame.set_index("real_name")
        if set(frame.columns) != set(bounds):
            raise ValueError(f"Parameter columns do not match this batch's PST: {path}")
        frame = frame.apply(pd.to_numeric, errors="raise")
        if not np.isfinite(frame.to_numpy()).all():
            raise ValueError(f"Non-finite parameter value: {path}")
        for name, (lo, hi) in bounds.items():
            tol = max(1.0, abs(lo), abs(hi)) * 1e-6
            if ((frame[name] < lo - tol) | (frame[name] > hi + tol)).any():
                raise ValueError(f"{path.name}: {name} outside this batch's PST bounds")
        rows = phi[pd.to_numeric(phi.iteration, errors="coerce") == it]
        if len(rows) != 1 or not set(frame.index).issubset(phi.columns):
            raise ValueError(f"Iteration/member IDs not supported by actual Phi: {path}")
        scores = pd.to_numeric(rows.iloc[0][list(frame.index)], errors="coerce")
        if not np.isfinite(scores).all():
            raise ValueError(f"Missing finite member Phi at iteration {it}")
        frames.append(frame)
    if not set(frames[1].index).issubset(frames[0].index):
        raise ValueError("Posterior member identities do not match prior")
    evidence = {
        "run_dir": str(root), "case": case, "iteration": iteration,
        "status": "source_consistency_checked_not_science_approval",
        "parameter_bounds": bounds,
        "files": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
    }
    return frames[0], frames[1], evidence
