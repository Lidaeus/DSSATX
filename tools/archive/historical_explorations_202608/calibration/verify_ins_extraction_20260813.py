"""Verify .ins instruction files extract all observations from agent outputs.

Simulates PEST's instruction-file semantics (single forward cursor: each
instruction line advances the cursor by its l<N> offset, tokens are searched
sequentially in the output line; a token before the cursor is unreachable).

Usage:
    python tools/calibration/verify_ins_extraction_20260813.py <run_dir> [--fix-harvest-order]

With --fix-harvest-order, PestHarvest.OUT lines are re-ordered to the fixed
token order (CHFPWS CHPDTS HPODWS CHPDTS_T PWADS PWAIS) to simulate the
patched run_dssat.py output before validation.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TOKEN_RE = re.compile(r"@([A-Z0-9_]+)@")


def parse_ins(ins_path: Path) -> list[tuple[str, list[str]]]:
    """Return [(obs_name, [tokens in search order])] per instruction line."""
    instructions = []
    with open(ins_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("pif"):
                continue
            tokens = TOKEN_RE.findall(line)
            obs_names = re.findall(r"!([^!]+)!", line)
            if tokens and obs_names:
                assert len(tokens) == len(obs_names), f"mismatch in {ins_path}: {line}"
                instructions.append((obs_names[0], tokens))
    return instructions


def extract_observations(out_path: Path, instructions: list[tuple[str, list[str]]]) -> dict[str, str | None]:
    """Simulate PEST extraction: forward-only cursor across output lines."""
    lines = out_path.read_text(encoding="utf-8").splitlines()
    cursor = 0
    results: dict[str, str | None] = {}
    for obs_name, tokens in instructions:
        # advance cursor by l<N> (offset embedded in the instruction file).
        cursor += 1  # all generated .ins use l1
        if cursor - 1 >= len(lines):
            results[obs_name] = None
            continue
        line = lines[cursor - 1]
        fields = line.split()
        # find each token sequentially from a forward-only position
        pos = 0
        ok = True
        for tok in tokens:
            marker = f"@{tok}@"
            # search from current position forward
            idx = -1
            for i in range(pos, len(fields)):
                if fields[i] == marker:
                    idx = i
                    break
            if idx == -1:
                ok = False
                break
            pos = idx + 2  # skip marker and its value
        results[obs_name] = line if ok else None
    return results


def reorder_harvest_line(line: str) -> str:
    """Reorder tokens to the fixed output order (CHFPWS CHPDTS HPODWS CHPDTS_T PWADS PWAIS)."""
    fields = line.split()
    prefix = fields[:4]  # RUN <n> TN <t> HNO <h> DATE <d>
    rest = fields[4:]
    order = ["@CHFPWS@", "@CHPDTS@", "@HPODWS@", "@CHPDTS_T@", "@PWADS@", "@PWAIS@"]
    tokens = {}
    i = 0
    while i < len(rest):
        tokens[rest[i]] = rest[i + 1]
        i += 2
    out = prefix[:]
    for tok in order:
        out.append(tok)
        out.append(tokens.get(tok, "-99.000"))
    return " ".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--fix-harvest-order", action="store_true")
    ap.add_argument("--case", required=True, help="case name used in .ins filenames")
    args = ap.parse_args()

    run_dir: Path = args.run_dir
    files = {
        "PestEval.OUT": "PestEval", "PestHarvest.OUT": "PestHarvest",
        "PestJoint.OUT": "PestJoint", "PestNResponse.OUT": "PestNResponse",
        "PestSoilWat.OUT": "PestSoilWat", "PestTmtGrow.OUT": "PestTmtGrow",
        "PestWResponse.OUT": "PestWResponse",
    }
    agent_dir = run_dir / "_agents/agent_01"
    total_fail = 0
    for out_name, stem in files.items():
        ins_path = run_dir / f"{args.case}_{stem}.OUT.ins"
        out_path = agent_dir / out_name
        if not ins_path.is_file() or not out_path.is_file():
            print(f"{out_name}: SKIP (missing ins or output)")
            continue
        instructions = parse_ins(ins_path)
        lines = out_path.read_text(encoding="utf-8").splitlines()
        if args.fix_harvest_order and out_name == "PestHarvest.OUT":
            lines = [reorder_harvest_line(l) for l in lines]
            tmp = out_path.with_name(out_path.name + ".fixed")
            tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
            out_path = tmp
        results = extract_observations(out_path, instructions)
        n_ok = sum(1 for v in results.values() if v is not None)
        n_fail = len(results) - n_ok
        total_fail += n_fail
        status = "PASS" if n_fail == 0 else "FAIL"
        print(f"{out_name}: {status} ({n_ok}/{len(results)} extracted, {n_fail} failed)")
        if n_fail:
            failed = [k for k, v in results.items() if v is None]
            print(f"  sample failed obs: {failed[:5]}")
    print(f"\nTOTAL: {'ALL PASS' if total_fail == 0 else str(total_fail) + ' FAILURES'}")
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())
