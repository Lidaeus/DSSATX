"""Generate DSSBatch.v48 with correct column alignment for 25FA and 26SP.

Column widths (derived from 25SP reference):
  FILEX: 94 chars (positions 0-93)
  TRTNO:  4 chars (positions 94-97), right-justified
  RP:     7 chars (positions 98-104), right-justified
  SQ:     7 chars (positions 105-111), right-justified
  OP:     7 chars (positions 112-118), right-justified
  CO:     7 chars (positions 119-125), right-justified
"""
from pathlib import Path

HEADER = (
    "@FILEX" + " " * 88 + "TRTNO" + " " * 5
    + "RP" + " " * 5 + "SQ" + " " * 5 + "OP" + " " * 5 + "CO"
)


def make_dssbatch(excode: str, trtnos: list[int]) -> str:
    lines = [
        "$BATCH(TOMATO)",
        "!",
        "! Directory    : D:\\Tomato_Cal\\workspace\\runs",
        "! Command Line : C:\\DSSAT48\\DSCSM048.EXE B DSSBatch.v48",
        "! Crop         : Tomato",
        f"! Experiment   : {excode}.TMX",
        "! ExpNo        : 1",
        "!",
        HEADER,
    ]
    for tn in trtnos:
        filex_field = f"{excode}.TMX".ljust(94)
        trno_field = f"{tn:>4}"
        rp_field = f"{1:>7}"
        sq_field = f"{0:>7}"
        op_field = f"{0:>7}"
        co_field = f"{0:>7}"
        lines.append(filex_field + trno_field + rp_field + sq_field + op_field + co_field)
    return "\n".join(lines) + "\n"


targets = [
    ("XXQL2502", list(range(1, 13)),
     Path(r"d:\Tomato_Cal\data\user\experiments\xxql2502_actual_trial_calibration_v2_20260726\DSSBatch.v48")),
    ("XXQL2601", list(range(1, 13)),
     Path(r"d:\Tomato_Cal\data\user\experiments\xxql2601_actual_trial_calibration_v2_20260726\DSSBatch.v48")),
]

for excode, trtnos, path in targets:
    content = make_dssbatch(excode, trtnos)
    path.write_text(content, encoding="utf-8", newline="\n")
    print(f"Wrote {path}")
    # Verify alignment
    data_line = content.split("\n")[9]
    trno_pos = 97
    print(f"  Data line length: {len(data_line)}")
    print(f"  TRTNO value at pos {trno_pos}: {repr(data_line[trno_pos])}")
    print(f"  First data line: {repr(data_line[:100])}")
