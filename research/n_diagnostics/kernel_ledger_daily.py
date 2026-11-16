"""Align a legacy V15 root ledger with the declared NDecision run and dates."""

import argparse
import csv
from pathlib import Path


def convert(ledger_path, decision_path, out_path, run):
    with decision_path.open(newline="") as stream:
        decision = sorted(
            (row for row in csv.DictReader(stream) if int(row["run"]) == run),
            key=lambda row: int(row["das"]),
        )
    if not decision or len({row["das"] for row in decision}) != len(decision):
        raise ValueError(f"NDecision has missing or duplicate days for run {run}")
    with ledger_path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"day_index", "layer"} <= set(reader.fieldnames):
            raise ValueError("Expected V15 RootKernelLedger columns")
        fields = [field for field in reader.fieldnames if field not in {"day_index", "layer"}]
        output = []
        previous = (0, 0)
        for row in reader:
            day, layer = int(row["day_index"]), int(row["layer"])
            if not 1 <= day <= len(decision) or (day, layer) <= previous:
                raise ValueError("Expected one run's ledger with ascending days and layers")
            date = decision[day - 1]
            output.append({"run": run, "trt": date["trt"], "yrdoy": date["yrdoy"],
                           "das": date["das"], "layer": layer, **{field: row[field] for field in fields}})
            previous = day, layer
    if not output:
        raise ValueError("Root ledger has no records")
    with out_path.open("x", newline="") as stream:
        writer = csv.DictWriter(stream, ["run", "trt", "yrdoy", "das", "layer", *fields])
        writer.writeheader()
        writer.writerows(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("ledger", "decision", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--run", type=int, required=True,
                        help="DSSAT run known to have produced this unkeyed ledger")
    args = parser.parse_args()
    convert(args.ledger, args.decision, args.out, args.run)


if __name__ == "__main__":
    main()
