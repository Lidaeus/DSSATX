"""Versioned user-input bundles and DSSAT cross-file validation.

The project keeps user supplied FileX/FileA/FileT, soil, weather and batch
files together so every scientific run can be traced to immutable bytes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import math
import re


MODEL_SUFFIXES = {".TMX", ".TMA", ".TMT"}


@dataclass(frozen=True)
class InputFinding:
    code: str
    severity: str
    message: str


def batch_entries(batch_file: str | Path) -> list[tuple[str, int]]:
    entries: list[tuple[str, int]] = []
    for raw in Path(batch_file).read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith(("$", "!", "@", "*")):
            continue
        parts = line.split()
        if Path(parts[0]).suffix.upper() != ".TMX" or len(parts) < 2:
            continue
        try:
            entries.append((Path(parts[0]).name, int(float(parts[1]))))
        except ValueError:
            continue
    return entries


def _section_lines(path: Path, heading: str) -> list[str]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip().upper().startswith(heading)), None)
    if start is None:
        return []
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("*") and not lines[i].strip().upper().startswith(heading)),
        len(lines),
    )
    return lines[start:end]


def parse_filex(path: str | Path) -> dict[str, object]:
    filex = Path(path)
    treatment_lines = _section_lines(filex, "*TREATMENTS")
    treatments: dict[int, dict[str, int]] = {}
    header: list[str] = []
    for line in treatment_lines:
        stripped = line.strip()
        if stripped.startswith("@"):
            header = stripped.lstrip("@").split()
            continue
        if not stripped or stripped.startswith(("*", "!")) or not header:
            continue
        parts = stripped.split()
        try:
            tn = int(parts[0])
        except (ValueError, IndexError):
            continue
        # TNAME contains spaces. Factor levels are the last 13 fields.
        factors = parts[-13:]
        factor_names = header[-13:]
        try:
            treatments[tn] = {name: int(float(value)) for name, value in zip(factor_names, factors)}
        except ValueError:
            continue

    soil_id = None
    station = None
    soil_depth = None
    field_lines = _section_lines(filex, "*FIELDS")
    for line in field_lines:
        parts = line.split()
        if not parts or line.lstrip().startswith(("@", "*", "!")):
            continue
        if len(parts) >= 12:
            station = parts[2]
            try:
                soil_depth = int(float(parts[10]))
            except ValueError:
                soil_depth = None
            soil_id = parts[11]
            break

    initial: dict[int, list[dict[str, float]]] = {}
    current = None
    in_initial = False
    layer_header = False
    for raw in filex.read_text(encoding="utf-8", errors="ignore").splitlines():
        upper = raw.strip().upper()
        if upper.startswith("*INITIAL CONDITIONS"):
            in_initial = True
            continue
        if in_initial and raw.startswith("*"):
            break
        if not in_initial:
            continue
        if upper.startswith("@C") and "ICBL" in upper and "SH2O" in upper:
            layer_header = True
            continue
        if upper.startswith("@C"):
            layer_header = False
            continue
        if not layer_header or not upper:
            continue
        parts = raw.split()
        if len(parts) < 5:
            continue
        try:
            current = int(parts[0])
            initial.setdefault(current, []).append(
                {"depth": float(parts[1]), "sh2o": float(parts[2]), "snh4": float(parts[3]), "sno3": float(parts[4])}
            )
        except ValueError:
            continue
    return {
        "treatments": treatments,
        "soil_id": soil_id,
        "weather_station": station,
        "soil_depth": soil_depth,
        "initial_conditions": initial,
    }


def parse_soil_profile(path: str | Path, soil_id: str) -> dict[str, object] | None:
    lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.startswith("*") and line[1:].strip().split()[0].upper() == soil_id.upper()),
        None,
    )
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("*")), len(lines))
    site_lat = site_lon = None
    surface: dict[str, float] = {}
    layers: list[dict[str, float]] = []
    header: list[str] = []
    header_kind = ""
    expect_site = False
    for raw in lines[start:end]:
        stripped = raw.strip()
        upper = stripped.upper()
        if upper.startswith("@SITE"):
            expect_site = True
            continue
        if expect_site and stripped and not stripped.startswith("@"):
            parts = stripped.split()
            numbers = [value for value in parts if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", value)]
            if len(numbers) >= 2:
                site_lat, site_lon = float(numbers[0]), float(numbers[1])
            expect_site = False
            continue
        if upper.startswith("@ SCOM"):
            header = stripped.lstrip("@").split()
            header_kind = "surface"
            continue
        if header_kind == "surface" and header and not stripped.startswith("@"):
            parts = stripped.split()
            if len(parts) >= len(header):
                for name, value in zip(header, parts):
                    try:
                        surface[name] = float(value)
                    except ValueError:
                        pass
                header = []
                header_kind = ""
                continue
        if upper.startswith("@  SLB") or upper.startswith("@ SLB"):
            header = stripped.lstrip("@").split()
            header_kind = "layers"
            continue
        if header_kind == "layers" and header and "SLB" in header and stripped and not stripped.startswith("@"):
            parts = stripped.split()
            if len(parts) < len(header):
                continue
            row: dict[str, float] = {}
            for name, value in zip(header, parts):
                try:
                    row[name] = float(value)
                except ValueError:
                    pass
            if "SLB" in row:
                layers.append(row)
    return {"soil_id": soil_id, "latitude": site_lat, "longitude": site_lon, "surface": surface, "layers": layers}


def treatment_ids(path: str | Path) -> set[int]:
    ids: set[int] = set()
    for raw in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith(("*", "@", "!")):
            continue
        try:
            ids.add(int(float(line.split()[0])))
        except (ValueError, IndexError):
            continue
    return ids


def parse_weather_site(path: str | Path) -> tuple[float | None, float | None]:
    lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    for index, raw in enumerate(lines):
        if raw.strip().upper().startswith("@ INSI") and index + 1 < len(lines):
            parts = lines[index + 1].split()
            if len(parts) >= 3:
                try:
                    return float(parts[1]), float(parts[2])
                except ValueError:
                    pass
    return None, None


def validate_input_bundle(input_dir: str | Path) -> tuple[dict[str, object], list[InputFinding]]:
    root = Path(input_dir).resolve()
    findings: list[InputFinding] = []
    batch = root / "DSSBatch.v48"
    if not batch.is_file():
        return {}, [InputFinding("BATCH_MISSING", "error", f"Missing {batch}")]
    entries = batch_entries(batch)
    if not entries:
        return {}, [InputFinding("BATCH_EMPTY", "error", "Batch has no FileX treatment entries")]
    filex_name = entries[0][0]
    if any(name.upper() != filex_name.upper() for name, _ in entries):
        findings.append(InputFinding("MULTIPLE_FILEX", "error", "One bundle currently supports one FileX stem"))
    filex = root / filex_name
    if not filex.is_file():
        findings.append(InputFinding("FILEX_MISSING", "error", f"Batch references missing {filex.name}"))
        return {}, findings
    parsed = parse_filex(filex)
    batch_treatments = {tn for _, tn in entries}
    filex_treatments = set(parsed["treatments"])
    missing = sorted(batch_treatments - filex_treatments)
    if missing:
        findings.append(InputFinding("TREATMENT_MISSING", "error", f"Batch treatments absent from FileX: {missing}"))
    initial = parsed["initial_conditions"]
    missing_initial = sorted(tn for tn in batch_treatments if parsed["treatments"].get(tn, {}).get("IC") not in initial)
    if missing_initial:
        findings.append(InputFinding("INITIAL_CONDITION_MISSING", "error", f"Treatments lack referenced IC sections: {missing_initial}"))

    for suffix in (".TMA", ".TMT"):
        companion = root / f"{filex.stem}{suffix}"
        if not companion.is_file():
            findings.append(InputFinding("OBSERVATION_FILE_MISSING", "error", f"Missing {companion.name}"))
            continue
        absent = sorted(batch_treatments - treatment_ids(companion))
        if absent:
            findings.append(InputFinding("OBSERVATION_TREATMENT_MISSING", "error", f"{companion.name} lacks treatments {absent}"))

    soil_file = root / "SOIL.SOL"
    profile = parse_soil_profile(soil_file, str(parsed["soil_id"])) if soil_file.is_file() and parsed["soil_id"] else None
    if profile is None:
        findings.append(InputFinding("SOIL_PROFILE_MISSING", "error", f"SOIL.SOL lacks profile {parsed['soil_id']}"))
    else:
        layers = profile["layers"]
        depths = [row["SLB"] for row in layers]
        if parsed["soil_depth"] and (not depths or max(depths) < float(parsed["soil_depth"])):
            findings.append(InputFinding("SOIL_DEPTH_SHORT", "error", "Soil profile is shallower than FileX field depth"))
        for tn in sorted(batch_treatments):
            ic_id = parsed["treatments"][tn]["IC"]
            for row in initial.get(ic_id, []):
                layer = next((item for item in layers if item.get("SLB") == row["depth"]), None)
                if not layer:
                    findings.append(InputFinding("IC_LAYER_UNMATCHED", "error", f"TN{tn} IC depth {row['depth']:g} is not a SOIL layer boundary"))
                    continue
                if not layer["SLLL"] <= row["sh2o"] <= layer["SSAT"]:
                    findings.append(InputFinding("IC_WATER_OUTSIDE_SOIL", "error", f"TN{tn} depth {row['depth']:g}: SH2O={row['sh2o']:g} outside [{layer['SLLL']:g}, {layer['SSAT']:g}]"))
        missing_ks = [
            row.get("SLB") for row in layers
            if row.get("SSKS", -99.0) <= 0.0
        ]
        if missing_ks:
            findings.append(
                InputFinding(
                    "SOIL_HYDRAULIC_CONDUCTIVITY_MISSING",
                    "warning",
                    "SSKS is missing/non-positive at soil depths "
                    f"{[float(value) for value in missing_ks]}; DSSAT will treat conductivity as missing",
                )
            )
        missing_texture = [
            row.get("SLB") for row in layers
            if row.get("SLCL", -99.0) < 0.0 or row.get("SLSI", -99.0) < 0.0
        ]
        if missing_texture:
            findings.append(
                InputFinding(
                    "SOIL_TEXTURE_MISSING",
                    "warning",
                    "SLCL/SLSI is missing at soil depths "
                    f"{[float(value) for value in missing_texture]}; DSSAT may substitute default texture",
                )
            )

    station = str(parsed.get("weather_station") or "")
    weather_files = sorted(root.glob(f"{station}*.WTH")) if station else []
    if not weather_files:
        findings.append(InputFinding("WEATHER_MISSING", "error", f"No weather file for station {station}"))
    elif profile:
        weather_lat, weather_lon = parse_weather_site(weather_files[0])
        soil_lat, soil_lon = profile.get("latitude"), profile.get("longitude")
        if None not in (weather_lat, weather_lon, soil_lat, soil_lon):
            distance = math.hypot(float(weather_lat) - float(soil_lat), float(weather_lon) - float(soil_lon))
            if distance > 0.5:
                findings.append(InputFinding("SOIL_WEATHER_SPATIAL_GAP", "warning", f"Soil and weather coordinates differ by {distance:.3f} degrees; document representativeness"))
    return {
        "root": str(root),
        "filex": filex.name,
        "soil_id": parsed.get("soil_id"),
        "weather_station": station,
        "treatments": sorted(batch_treatments),
        "treatment_factors": parsed.get("treatments"),
        "soil_profile": profile,
        "initial_conditions": initial,
    }, findings


def findings_as_dicts(findings: list[InputFinding]) -> list[dict[str, str]]:
    return [asdict(item) for item in findings]


__all__ = [
    "InputFinding", "batch_entries", "findings_as_dicts", "parse_filex",
    "parse_soil_profile", "validate_input_bundle",
]
