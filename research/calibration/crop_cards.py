"""Prepare and verify fixed-width CROPGRO crop-card edits in private cases."""

import csv
import hashlib
import math
from pathlib import Path
import re

VALUES = "crop_values.csv"
WIDTH = 6
CARD_NAME = re.compile(r"TMGRO048\.(CUL|ECO|SPE)")
PEST_NAME = re.compile(r"[a-z][a-z0-9_]{0,19}")
RECORD_FIELDS = {
    "CUL": (b"@VAR#", 36, "CSDL PPSEN EM-FL FL-SH FL-SD SD-PM FL-LF LFMAX SLAVR SIZLF XFRT WTPSD SFDUR SDPDV PODUR THRSH SDPRO SDLIP"),
    "ECO": (b"@ECO#", 30, "THVAR PL-EM EM-V1 V1-JU JU-R0 PM06 PM09 LNGSH R7-R8 FL-VS TRIFL RWDTH RHGHT R1PPO OPTBI SLOBI XMAGE XFPHT XFINT"),
}
SPECIES_ROWS = (
    ("PGEFF", "PGEFF SCV KDIF LFANGB"),
    ("SLWREF", "SLWREF SLWSLO NSLOPE LNREF PGREF"),
    ("FNPGN(4)", "FNPGN(1) FNPGN(2) FNPGN(3) FNPGN(4)"),
    ("RNO3C", "RNO3C RNH4C RPRO RFIXN"),
    ("PROLFI", "PROLFI PROLFG PROLFF PROSTI PROSTG PROSTF"),
    ("PRORTI", "PRORTI PRORTG PRORTF PROSHI PROSHG PROSHF"),
    ("CMOBMX", "CMOBMX CADSTF CADPR1 NMOBMX NVSMOB NRCVR"),
    ("XPODF", "_ NSTFAC NREXP NRMIN"),
    ("ALPHL", "ALPHL ALPHS ALPHR ALPHSH"),
    ("WTFSD", "WTFSD PORPT FRSTMF FRLFF ATOP FRCNOD"),
    ("FRLFMX", "FRLFMX"),
    ("FINREF", "FINREF SLAREF SIZREF VSSINK EVMODC"),
    ("SENRTE", "SENRTE SENRT2 SENDAY FREEZ1 FREEZ2"),
    ("RTDEPI", "RTDEPI RFAC1 RTSEN RLDSM RTSDF RWUEP1 RWUMX"),
    ("RTNO3", "RTNO3 RTNH4 PORMIN RTEXF"),
    ("DSWBAR", "DSWBAR XFRMAX SHLAG"),
    ("YLEAF VALUES", " ".join(f"YLEAF({i})" for i in range(1, 9))),
    ("YSTEM VALUES", " ".join(f"YSTEM({i})" for i in range(1, 9))),
    ("XSWBAR(1-5)", " ".join(f"XSWBAR({i})" for i in range(1, 6))),
    ("YSWBAR(1-5)", " ".join(f"YSWBAR({i})" for i in range(1, 6))),
)
TEMPERATURE_FIELDS = (("TB1", "TO11", "TO21", "TM1"), ("TB2", "TO12", "TO22", "TM2"))

# Constraints are checked on the values DSSAT actually reads, including fixed neighbours.
SPECIES_ORDER = (
    (("PROLFF", "PROLFG", "PROLFI"), True),
    (("PROSTF", "PROSTG", "PROSTI"), False),
    (("FNPGN(1)", "FNPGN(2)"), True),
    (tuple(f"XSWBAR({i})" for i in range(1, 6)), False),
    (tuple(f"YSWBAR({i})" for i in range(1, 6)), False),
    (tuple(f"SENPOR({i})" for i in range(1, 5)), False),
    *((fields, False) for fields in TEMPERATURE_FIELDS),
)
FRACTIONS = {"XFRT", "XFINT", "FRLFF", "FRLFMX", "ATOP", "NVSMOB", "NSTFAC", "ALPHL", "ALPHS",
             "PROLFI", "PROLFG", "PROLFF", "PROSTI", "PROSTG", "PROSTF", "PROSHI"}


def number(raw):
    """Match Fortran Fw.0 card fields, including D exponents and omitted E."""
    value = raw.decode("ascii").strip().replace("d", "E").replace("D", "E")
    value = re.sub(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+))([+-]\d+)$", r"\1E\2", value)
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?", value):
        raise ValueError(f"Invalid numeric crop-card field {raw!r}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"Non-finite crop-card field {raw!r}")
    return result


def card_number(value):
    """Choose the closest representable six-column field within the rounding budget."""
    if not math.isfinite(value):
        raise ValueError(f"Non-finite crop-card value {value}")
    candidates = set()
    for digits in range(WIDTH):
        for mode in ("f", "e"):
            token = format(value, f".{digits}{mode}")
            mantissa, _, exponent = token.partition("e")
            if "." in mantissa:
                mantissa = mantissa.rstrip("0").rstrip(".")
            mantissa = re.sub(r"^(-?)0\.", r"\1.", mantissa)
            token = mantissa + (f"E{int(exponent)}" if exponent and int(exponent) else "")
            if len(token) <= WIDTH:
                candidates.add(token.encode("ascii"))
    if candidates:
        best = min(candidates, key=lambda raw: (abs(number(raw) - value), b"E" in raw, len(raw), raw))
        if math.isclose(number(best), value, rel_tol=1e-3):
            return best.rjust(WIDTH)
    raise ValueError(f"Crop-card value {value} cannot fit in {WIDTH} columns within 0.1%")


def unique(indices, label):
    if len(indices) != 1:
        raise ValueError(f"Expected one {label}, found {len(indices)}")
    return indices[0]


def crop_location(lines, kind, record, field):
    header, start, fields = RECORD_FIELDS[kind]
    fields = fields.split()
    index = unique([i for i, line in enumerate(lines) if line.startswith(header)], f"{kind} header")
    # ECO's human-readable PM06/PM09/LNGSH labels can be offset by a character.
    # The encoded field order plus the model's six-column record defines the spans.
    tokens = lines[index].decode("ascii").split()
    if tokens[4:4 + len(fields)] != fields or field not in fields:
        raise ValueError(f"{kind}: unsupported field {field} or reordered header")
    selector = record.encode("ascii")
    row = unique([i for i, line in enumerate(lines[index + 1:], start=index + 1)
                  if line[:6].strip() == selector], f"{kind} record {record}")
    return row, start + WIDTH * fields.index(field)


def species_location(lines, field):
    for marker, names in SPECIES_ROWS:
        fields = names.split()
        if field in fields:
            pattern = rb"(?<![A-Z0-9_])" + re.escape(marker.encode("ascii")) + rb"(?![A-Z0-9_])"
            row = unique([i for i, line in enumerate(lines)
                          if re.match(rb"[ .+0-9-]", line) and re.search(pattern, line[len(fields) * WIDTH:])],
                         f"SPE {marker} row")
            return row, WIDTH * fields.index(field)
    if field in {f"SENPOR({i})" for i in range(1, 5)}:
        header = unique([i for i, line in enumerate(lines)
                         if line.startswith(b"!") and b"SENPOR" in line and b"SENMAX" in line],
                        "SPE SENPOR header")
        return header + 1, WIDTH * (int(field[-2]) - 1)
    for i, fields in enumerate(TEMPERATURE_FIELDS, start=1):
        if field in fields:
            label = b"VEGETATIVE DEVELOPMENT" if i == 1 else b"EARLY REPRODUCTIVE DEVELOPMENT"
            row = unique([n for n, line in enumerate(lines)
                          if line[24:].split() == [str(i).encode(), *label.split()]],
                         f"SPE temperature row {i}")
            return row, WIDTH * fields.index(field)
    raise ValueError(f"SPE: unsupported field {field}")


def locate(lines, kind, record, field):
    row, col = species_location(lines, field) if kind == "SPE" else crop_location(lines, kind, record, field)
    if row >= len(lines) or len(lines[row].rstrip(b"\r\n")) < col + WIDTH:
        raise ValueError(f"Truncated {kind} field {record} {field}")
    return row, col


def active_records(inputs):
    """Resolve the cultivar and ecotype actually used by the flat TM batch."""
    batch = (inputs / "DSSBatch.v48").read_text(encoding="ascii")
    selected = {}
    for line in batch.splitlines():
        stripped = line.strip()
        if not stripped or stripped[0] in "$!@*":
            continue
        name, *columns = stripped.split()
        if Path(name).name != name or Path(name).suffix.upper() != ".TMX" or not columns:
            raise ValueError("Crop-card calibration requires flat CROPGRO TM batch files")
        selected.setdefault(name, set()).add(int(columns[0]))
    cultivars = set()
    for filename, treatments in selected.items():
        sections = {"*TREATMENTS": {}, "*CULTIVARS": {}}
        section = ""
        cu_end = None
        for line in (inputs / filename).read_text(encoding="ascii").splitlines():
            if line.startswith("*"):
                section = line.split(maxsplit=1)[0]
            if section == "*TREATMENTS" and line.startswith("@N"):
                cu = re.search(r"(?<!\S)CU(?!\S)", line)
                if cu:
                    cu_end = cu.end()
            parts = line.split()
            if section not in sections or not parts or not parts[0].isdigit():
                continue
            level = int(parts[0])
            if level in sections[section]:
                raise ValueError(f"{filename}: duplicate {section} level {level}")
            if section == "*TREATMENTS":
                if cu_end is None:
                    raise ValueError(f"{filename}: treatment header has no cultivar factor")
                sections[section][level] = int(line[cu_end - 3:cu_end])
            else:
                sections[section][level] = tuple(parts[1:3])
        for treatment in treatments:
            try:
                crop, cultivar = sections["*CULTIVARS"][sections["*TREATMENTS"][treatment]]
            except (KeyError, ValueError) as error:
                raise ValueError(f"{filename}: unresolved cultivar for treatment {treatment}") from error
            if crop != "TM":
                raise ValueError(f"{filename}: crop-card calibration expects TM, found {crop}")
            cultivars.add(cultivar)
    if not cultivars:
        raise ValueError("Crop-card calibration requires a nonempty TM batch")
    lines = (inputs / "TMGRO048.CUL").read_bytes().splitlines()
    ecotypes = set()
    for cultivar in cultivars:
        row, _ = crop_location(lines, "CUL", cultivar, "LFMAX")
        ecotypes.add(lines[row][30:36].decode("ascii").strip())
    return {"CUL": cultivars, "ECO": ecotypes, "SPE": {""}}


def read_map(path, inputs, bounds):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not {"name", "file", "record", "field"}.issubset(reader.fieldnames or ()):
            raise ValueError("Crop map requires name,file,record,field")
        rows = list(reader)
    if not rows:
        raise ValueError("Crop map is empty")
    plan = {}
    active = active_records(inputs)
    fields_used, aliases = set(), set()
    columns = ("name", "file", "record", "field")
    for row in rows:
        if any(row[key] is None for key in columns):
            raise ValueError(f"Missing column value in crop map row {row}")
        name, filename, record, field = (row[key].strip() for key in columns)
        field, record = field.upper(), record.upper()
        match = CARD_NAME.fullmatch(filename)
        if not PEST_NAME.fullmatch(name) or name not in bounds.index or name in aliases:
            raise ValueError(f"Unknown or duplicate crop parameter alias {name!r}")
        if not match:
            raise ValueError(f"Invalid crop-card filename {filename!r}")
        kind = match[1].upper()
        key = (filename.casefold(), record, field)
        if key in fields_used or record not in active[kind]:
            raise ValueError(f"Duplicate field or inactive record selector for {key}")
        fields_used.add(key)
        aliases.add(name)
        source = (inputs / filename).read_bytes()
        lines = source.splitlines(keepends=True)
        row_index, col = locate(lines, kind, record, field)
        base = number(lines[row_index][col:col + WIDTH])
        lower, upper = map(float, bounds.loc[name, ["lower", "upper"]])
        for endpoint in (lower, upper):
            if number(card_number(endpoint)) != endpoint:
                raise ValueError(f"{name}: bounds must be representable exactly in six columns")
        if lower >= upper:
            raise ValueError(f"{name}: crop bounds collapse at card precision")
        file_plan = plan.setdefault(filename, {"sha256": hashlib.sha256(source).hexdigest(), "fields": []})
        if any((row_index, col) == (p["row"], p["col"]) for p in file_plan["fields"]):
            raise ValueError(f"{filename}: overlapping crop-card selectors")
        file_plan["fields"].append(dict(name=name, record=record, field=field, row=row_index, col=col,
                                        lower=lower, upper=upper, baseline=base))
    return plan


def read_values(path):
    with path.open(newline="", encoding="ascii") as stream:
        reader = csv.reader(stream)
        if next(reader, None) != ["name", "value"]:
            raise ValueError(f"{path}: expected name,value")
        pairs = list(reader)
    values = {name: number(raw.encode("ascii")) for name, raw in pairs}
    if len(values) != len(pairs):
        raise ValueError(f"{path}: duplicate crop parameter values")
    return values


def verify_constraints(kind, lines, fields, readback):
    for field, value in readback.items():
        if field in FRACTIONS or field.startswith(("XSWBAR(", "YSWBAR(", "SENPOR(", "YLEAF(", "YSTEM(")):
            if not 0 <= value <= 1:
                raise ValueError(f"{field}: expected a fraction in [0,1]")
        if field in {"PODUR", "SFDUR", "PGEFF", "VSSINK", "LFMAX", "SLAVR", "RWUMX", "RWUEP1", "DSWBAR"}:
            if value <= 0:
                raise ValueError(f"{field}: expected a positive value")
    if kind != "SPE":
        return

    def read(field):
        row, col = locate(lines, kind, "", field)
        return number(lines[row][col:col + WIDTH])

    for names, strict in SPECIES_ORDER:
        if fields.intersection(names):
            values = [read(name) for name in names]
            if any(a > b or (strict and a == b) for a, b in zip(values, values[1:])):
                raise ValueError(f"SPE fields {names} violate their required order")
    for field in fields:
        if field.startswith(("YLEAF(", "YSTEM(")):
            index = field[field.index("("):]
            leaf, stem = f"YLEAF{index}", f"YSTEM{index}"
            if read(leaf) + read(stem) > 1:
                raise ValueError(f"{leaf} and {stem} leave negative root partition")


def materialize(plan, inputs, values, destination):
    """Write new files and read their numeric bytes back before a model invocation."""
    expected = {p["name"] for entry in plan.values() for p in entry["fields"]}
    if set(values) != expected:
        raise ValueError(f"Crop values must match map aliases exactly: {sorted(expected)}")
    overrides, receipt = {}, {}
    for filename, entry in plan.items():
        source = (inputs / filename).read_bytes()
        if hashlib.sha256(source).hexdigest() != entry["sha256"]:
            raise ValueError(f"Frozen crop card changed: {filename}")
        lines = source.splitlines(keepends=True)
        tokens = {}
        for field in entry["fields"]:
            alias, row, col = field["name"], field["row"], field["col"]
            value = float(values[alias])
            if not field["lower"] <= value <= field["upper"]:
                raise ValueError(f"{alias}={value} is outside its crop bounds")
            token = lines[row][col:col + WIDTH] if value == field["baseline"] else card_number(value)
            if not field["lower"] <= number(token) <= field["upper"]:
                raise ValueError(f"{alias} rounds outside its crop bounds")
            lines[row] = lines[row][:col] + token + lines[row][col + WIDTH:]
            tokens[alias] = token
        output = destination / filename
        payload = b"".join(lines)
        output.write_bytes(payload)
        read = output.read_bytes()
        if read != payload:
            raise ValueError(f"Crop-card write/read mismatch: {filename}")
        lines = read.splitlines(keepends=True)
        actual_by_record = {}
        for field in entry["fields"]:
            alias, row, col = field["name"], field["row"], field["col"]
            raw = lines[row][col:col + WIDTH]
            if raw != tokens[alias]:
                raise ValueError(f"Crop-card field read-back mismatch: {alias}")
            value = number(raw)
            actual_by_record.setdefault(field["record"], {})[field["field"]] = value
            receipt[alias] = {"file": filename, "record": field["record"], "field": field["field"],
                              "row": row + 1, "columns": [col + 1, col + WIDTH],
                              "requested": float(values[alias]), "readback": value}
        for actual in actual_by_record.values():
            verify_constraints(Path(filename).suffix[1:], lines, set(actual), actual)
        overrides[output] = filename
    return overrides, receipt
