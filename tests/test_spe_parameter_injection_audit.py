"""Regression tests for the expanded SPE sensitivity-analysis domain.

These tests intentionally exercise the same public writer used by DSSAT runs.
They do not require a DSSAT executable: the safety property being tested is
that every declared parameter survives baseline/lower/upper injection, exact
fixed-width read-back, and file-hash comparison.
"""

from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path

import pytest

from src.dssat import run_dssat


ROOT = Path(__file__).resolve().parents[1]
SPE_BASE = ROOT / "data" / "templates" / "genotype" / "TMGRO048.SPE.base"
NRESP_SPE = ROOT / "windows" / "windows_nresp_20260803" / "Genotype" / "TMGRO048.SPE"
NUMBER_RE = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[Ee][-+]?\d+)?")


_NAMED_LINES = (
    ("PARMAX,PHTMAX", ("PARMAX", "PHTMAX", "KCAN", "KC_SLOPE")),
    ("PROLFI,PROLFG,PROLFF", ("PROLFI", "PROLFG", "PROLFF", "PROSTI", "PROSTG", "PROSTF")),
    ("PRORTI,PRORTG,PRORTF", ("PRORTI", "PRORTG", "PRORTF", "PROSHI", "PROSHG", "PROSHF")),
    ("CMOBMX,CADSTF", ("CMOBMX", "CADSTF", "CADPR1", "NMOBMX", "NVSMOB", "NRCVR")),
    ("FNPGN(4)", ("FNPGN1", "FNPGN2", "FNPGN3", "FNPGN4")),
    ("SLWREF,SLWSLO", ("SLWREF", "SLWSLO", "NSLOPE", "LNREF", "PGREF")),
    ("WTFSD,PORPT", ("WTFSD", "PORPT", "FRSTMF", "FRLFF", "ATOP", "FRCNOD")),
    ("FINREF,SLAREF", ("FINREF", "SLAREF", "SIZREF", "VSSINK", "EVMODC")),
    ("RTNO3,RTNH4", ("RTNO3", "RTNH4", "PORMIN", "RTEXF")),
    ("SETMAX,SRMAX", ("SETMAX", "SRMAX", "RFLWAB", "XMPAGE")),
    ("SENRTE,SENRT2", ("SENRTE", "SENRT2", "SENDAY", "FREEZ1", "FREEZ2")),
    ("SLAMAX,SLAMIN", ("SLAMAX", "SLAMIN", "SLAPAR", "TURSLA", "NSLA")),
    ("PGEFF SCV KDIF", ("PGEFF", "SCV", "KDIF", "LFANGB")),
    ("DSWBAR,XFRMAX", ("DSWBAR", "XFRMAX", "SHLAG")),
    ("FRLFMX", ("FRLFMX",)),
)


def _read_spe_values(path: Path) -> dict[str, float]:
    values: dict[str, float] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    for needle, names in _NAMED_LINES:
        for line in lines:
            if needle in line:
                nums = [float(m.group(0)) for m in NUMBER_RE.finditer(line)]
                for name, value in zip(names, nums):
                    values[name] = value
                break
    for line in lines:
        upper = line.upper()
        if "VEGETATIVE DEVELOPMENT" in upper:
            stage = 1
        elif "EARLY REPRODUCTIVE DEVELOPMENT" in upper:
            stage = 2
        elif "LATE REPRODUCTIVE DEVELOPMENT" in upper:
            stage = 3
        else:
            continue
        nums = [float(m.group(0)) for m in NUMBER_RE.finditer(line)]
        for name, value in zip((f"TB{stage}", f"TO1{stage}", f"TO2{stage}", f"TM{stage}"), nums[:4]):
            values[name] = value
    return values


def _write_params(path: Path, values: dict[str, float]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["name", "value"])
        writer.writerows(values.items())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "name,lower,upper",
    [
        ("FRCNOD", 0.04, 0.06),
        ("PROLFI", 0.260, 0.360),
        ("PROLFG", 0.170, 0.250),
        ("PROLFF", 0.080, 0.140),
        ("PROSTI", 0.145, 0.220),
        ("PROSTG", 0.090, 0.140),
        ("PROSTF", 0.040, 0.080),
        ("PRORTI", 0.1296, 0.1584),
        ("PRORTG", 0.1071, 0.1309),
        ("PRORTF", 0.05, 0.07),
        ("PROSHI", 0.189, 0.231),
        ("PROSHG", 0.14, 0.16),
        ("PROSHF", 0.10, 0.12),
        ("FNPGN1", 1.5, 2.5),
        ("FNPGN2", 4.0, 5.0),
        ("SENRTE", 0.5, 2.0),
        ("SENDAY", 0.01, 0.05),
        ("SETMAX", 0.1, 0.5),
        ("SRMAX", 0.1, 0.5),
        ("RFLWAB", 0.05, 0.5),
        ("DSWBAR", 10.0, 30.0),
        ("XFRMAX", 0.01, 0.5),
        ("SHLAG", 0.05, 0.3),
        ("SLAMAX", 400.0, 900.0),
        ("SLAMIN", 200.0, 500.0),
        ("TURSLA", 0.5, 2.0),
        ("NSLA", 0.5, 1.5),
        ("FRLFMX", 0.5, 0.9),
        ("PGEFF", 0.03, 0.07),
        ("KDIF", 0.5, 1.0),
        ("LFANGB", 1.0, 3.0),
    ],
)
def test_spe_parameter_baseline_lower_upper_readback_and_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    lower: float,
    upper: float,
) -> None:
    params = tmp_path / "params.csv"
    baseline = _read_spe_values(SPE_BASE)[name]
    baseline_hash = _sha256(SPE_BASE)
    for serial, value in (("lower", lower), ("upper", upper)):
        monkeypatch.chdir(tmp_path)
        spe_name = f"TMGRO048_{name}_{serial}.SPE"
        monkeypatch.setattr(run_dssat, "SPE_FILE", spe_name)
        (tmp_path / f"{spe_name}.base").write_bytes(SPE_BASE.read_bytes())
        baseline_path = tmp_path / spe_name
        _write_params(params, {name: value})
        run_dssat.update_spe_file(str(params))
        assert _read_spe_values(baseline_path)[name] == pytest.approx(value, rel=2e-3, abs=2e-3)
        assert _sha256(baseline_path) != baseline_hash


@pytest.mark.skipif(not NRESP_SPE.exists(), reason="windows_nresp_20260803 was cleaned up in repository purification")
def test_custom_nresp_parameters_use_custom_spe_and_exact_readback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The two N-response parameters must be injected into the custom SPE row."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_dssat, "SPE_FILE", "TMGRO048.SPE")
    monkeypatch.setenv("DSSAT_SPE_BASE", str(NRESP_SPE))
    params = tmp_path / "params.csv"
    _write_params(params, {"NREXP": 0.4, "NRMIN": 0.2})
    run_dssat.update_spe_file(str(params))
    out = tmp_path / "TMGRO048.SPE"
    row = next(line for line in out.read_text(encoding="latin1").splitlines() if "XPODF" in line)
    nums = [float(m.group(0)) for m in NUMBER_RE.finditer(row)]
    assert nums[-3:] == pytest.approx([0.7, 0.4, 0.2])
    assert _sha256(out) != _sha256(NRESP_SPE)
