"""Audit DSSAT FileA/FileT observations before calibration or validation.

The audit is deliberately non-mutating.  It distinguishes invalid observation
records from design limitations and from input-bundle/FileX problems handled
by :mod:`src.common.experiment_inputs`.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.common.experiment_inputs import findings_as_dicts, parse_filex, validate_input_bundle


MISSING_VALUE = -99.0


def read_dssat_observation_table(path: str | Path) -> pd.DataFrame:
    """Read the first ``@TRNO`` table from a FileA or FileT file."""
    source = Path(path)
    header: list[str] | None = None
    rows: list[list[str]] = []
    for raw in source.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = raw.strip()
        if stripped.upper().startswith("@TRNO"):
            header = [token.lstrip("@").upper() for token in stripped.split()]
            continue
        if header is None or not stripped or stripped.startswith(("*", "!", "@")):
            continue
        parts = stripped.split()
        if len(parts) < len(header):
            parts.extend(["-99"] * (len(header) - len(parts)))
        rows.append(parts[: len(header)])
    if header is None:
        raise ValueError(f"{source.name} has no @TRNO observation table")
    frame = pd.DataFrame(rows, columns=header)
    for column in frame.columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def derive_cumulative_harvest_increments(filet: pd.DataFrame) -> pd.DataFrame:
    """Return positive harvest events with increments derived from cumulative data."""
    rows: list[dict[str, Any]] = []
    for treatment, group in filet.groupby("TRNO", sort=True):
        previous = {"CHPDT": 0.0, "CHFPW": 0.0}
        for _, row in group.sort_values("DATE", kind="stable").iterrows():
            event: dict[str, Any] = {
                "treatment": int(treatment),
                "date": int(row["DATE"]),
            }
            present = False
            for cumulative, incremental in (("CHPDT", "HPODW"), ("CHFPW", "HFPOW")):
                value = float(row.get(cumulative, MISSING_VALUE))
                if pd.isna(value) or value == MISSING_VALUE:
                    event[cumulative.lower()] = MISSING_VALUE
                    event[f"derived_{incremental.lower()}"] = MISSING_VALUE
                    continue
                event[cumulative.lower()] = value
                event[f"derived_{incremental.lower()}"] = value - previous[cumulative]
                previous[cumulative] = value
                present = True
            if present:
                rows.append(event)
    return pd.DataFrame(rows)


def _valid_values(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(dtype=float)
    values = pd.to_numeric(frame[column], errors="coerce")
    return values.loc[values.notna() & values.ne(MISSING_VALUE)]


def audit_observation_bundle(input_dir: str | Path) -> tuple[dict[str, Any], pd.DataFrame]:
    root = Path(input_dir).resolve()
    filex_files = sorted(root.glob("*.TMX"))
    if len(filex_files) != 1:
        raise ValueError(f"expected exactly one .TMX in {root}, found {len(filex_files)}")
    filex = filex_files[0]
    filea = root / f"{filex.stem}.TMA"
    filet = root / f"{filex.stem}.TMT"
    if not filea.is_file() or not filet.is_file():
        raise FileNotFoundError(f"{root} must contain {filex.stem}.TMA and {filex.stem}.TMT")

    bundle_summary, bundle_findings = validate_input_bundle(root, require_observations=True)
    a = read_dssat_observation_table(filea)
    t = read_dssat_observation_table(filet)
    findings: list[dict[str, str]] = findings_as_dicts(bundle_findings)

    def add(code: str, severity: str, message: str) -> None:
        findings.append({"code": code, "severity": severity, "message": message})

    for name, frame, keys in ((filea.name, a, ["TRNO"]), (filet.name, t, ["TRNO", "DATE"])):
        if frame[keys].isna().any().any():
            add("OBSERVATION_KEY_INVALID", "error", f"{name} has missing/non-numeric keys {keys}")
        duplicate = frame.duplicated(keys, keep=False)
        if duplicate.any():
            records = frame.loc[duplicate, keys].astype("Int64").to_dict("records")
            add("OBSERVATION_KEY_DUPLICATE", "error", f"{name} duplicates {keys}: {records}")

    t_treatments = set(t["TRNO"].dropna().astype(int))
    a_treatments = set(a["TRNO"].dropna().astype(int))
    if t_treatments != a_treatments:
        add(
            "FILEA_FILET_TREATMENT_MISMATCH",
            "error",
            f"FileA treatments {sorted(a_treatments)} differ from FileT {sorted(t_treatments)}",
        )

    harvest = derive_cumulative_harvest_increments(t)
    for column in ("derived_hpodw", "derived_hfpow"):
        if column in harvest and (harvest[column].loc[harvest[column].ne(MISSING_VALUE)] < -1e-9).any():
            bad = harvest.loc[harvest[column] < -1e-9, ["treatment", "date", column]].to_dict("records")
            add("CUMULATIVE_HARVEST_DECREASES", "error", f"negative {column} from cumulative series: {bad}")

    comparisons = (
        ("HWAH", "CHPDT", "last"),
        ("HWAHF", "CHFPW", "last"),
        ("LAIX", "LAID", "max"),
        ("LWAM", "LWAD", "last"),
        ("SNAM", "SNAM" if len(_valid_values(t, "SNAM")) else "SNAD", "last"),
    )
    duplicate_fields: list[str] = []
    for summary_column, time_column, operation in comparisons:
        if summary_column not in a or time_column not in t:
            continue
        mismatches: list[int] = []
        compared = 0
        for treatment in sorted(a_treatments & t_treatments):
            av = _valid_values(a.loc[a["TRNO"].eq(treatment)], summary_column)
            tv_frame = t.loc[t["TRNO"].eq(treatment)].sort_values("DATE", kind="stable")
            tv = _valid_values(tv_frame, time_column)
            if av.empty or tv.empty:
                continue
            expected = float(tv.max() if operation == "max" else tv.iloc[-1])
            compared += 1
            if abs(float(av.iloc[-1]) - expected) > max(1e-6, 1e-6 * abs(expected)):
                mismatches.append(treatment)
        if mismatches:
            add(
                "FILEA_FILET_VALUE_MISMATCH",
                "error",
                f"{summary_column} does not match {operation} {time_column} for treatments {mismatches}",
            )
        elif compared:
            duplicate_fields.append(f"{summary_column}={operation}({time_column})")
    if duplicate_fields:
        add(
            "FILEA_DERIVED_DUPLICATES",
            "info",
            "FileA fields duplicate FileT evidence and must remain diagnostic-only: "
            + ", ".join(duplicate_fields),
        )

    source_text = (filea.read_text(encoding="utf-8", errors="ignore") + filet.read_text(encoding="utf-8", errors="ignore")).upper()
    if "TRNO=PLOT NUMBER" in source_text or "TRNO = PLOT NUMBER" in source_text:
        add(
            "TRNO_DECLARED_AS_PLOT_NUMBER",
            "warning",
            "TRNO is declared as plot number; formally confirm one-to-one mapping to FileX treatment number before calibration.",
        )

    total_n = len(_valid_values(t, "CNAM"))
    # The current FileT process reader consumes SNAM/LNAM; historical tables
    # used SNAD/LNAD. Both are organ N, never a substitute for whole-plant CNAM.
    organ_n = sum(len(_valid_values(t, column)) for column in ("SNAM", "LNAM", "SNAD", "LNAD"))
    if total_n == 0 and organ_n > 0:
        add(
            "ORGAN_N_WITHOUT_TOTAL_PLANT_N",
            "warning",
            "Organ N (SNAM/LNAM or historical SNAD/LNAD) is available but CNAM is absent; use organ N only after matching simulated definitions, and do not infer total plant N by silent summation.",
        )
    elif total_n == 0:
        add(
            "PLANT_N_OBSERVATIONS_UNAVAILABLE",
            "warning",
            "No usable CNAM/SNAM/LNAM/SNAD/LNAD observations are available; N-process parameters need external priors and response-level validation.",
        )

    factors = parse_filex(filex)["treatments"]
    pairs: dict[tuple[int, int], list[int]] = {}
    for treatment, factor in factors.items():
        if "MI" in factor and "MF" in factor:
            pairs.setdefault((factor["MI"], factor["MF"]), []).append(treatment)
    duplicate_pairs = {pair: values for pair, values in pairs.items() if len(values) > 1}
    if duplicate_pairs:
        add(
            "WATER_NITROGEN_CELL_DUPLICATED",
            "warning",
            f"MI/MF cells map to multiple treatments: {duplicate_pairs}",
        )
    if pairs:
        water = sorted({pair[0] for pair in pairs})
        nitrogen = sorted({pair[1] for pair in pairs})
        missing_pairs = sorted(set((mi, mf) for mi in water for mf in nitrogen) - set(pairs))
        if missing_pairs:
            add(
                "WATER_NITROGEN_GRID_INCOMPLETE",
                "warning",
                f"MI/MF factorial cells are absent: {missing_pairs}; do not report a full W×N interaction for this season.",
            )

    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input_dir": str(root),
        "filex": filex.name,
        "filea": filea.name,
        "filet": filet.name,
        "observation_row_counts": {"FileA": len(a), "FileT": len(t), "harvest_events": len(harvest)},
        "available_counts": {
            column: len(_valid_values(t, column))
            for column in ("LAID", "SWAD", "LWAD", "CHFPW", "CHPDT", "CNAM", "SNAM", "LNAM", "SNAD", "LNAD")
        },
        "bundle_summary": bundle_summary,
        "findings": findings,
        "error_count": sum(item["severity"] == "error" for item in findings),
        "warning_count": sum(item["severity"] == "warning" for item in findings),
        "safe_for_direct_formal_use": not any(item["severity"] == "error" for item in findings),
    }
    return report, harvest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit FileA/FileT observations without changing them")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)
    report, harvest = audit_observation_bundle(args.input_dir)
    out = Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "observation_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    harvest.to_csv(out / "derived_harvest_increments.csv", index=False, encoding="utf-8")
    print(out / "observation_audit.json")
    return 1 if report["error_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
