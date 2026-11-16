"""Stage a versioned DSSAT runtime and its checksums for an external consumer."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True)
    parser.add_argument("--source", type=Path, required=True, help="Git checkout used to build the engine")
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--std-data", type=Path, required=True)
    parser.add_argument("--spe", type=Path)
    parser.add_argument("--config", action="append", type=Path, default=[])
    parser.add_argument("--notes", default="")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.resolve(strict=True)
    head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    status = subprocess.check_output(
        ["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"], text=True,
    ).strip()
    exe, standard = args.engine.resolve(strict=True), args.std_data.resolve(strict=True)
    if not exe.is_file() or not standard.is_dir():
        parser.error("Supply an executable file and a standard-data directory")
    if not list(standard.glob("*.CDE")):
        parser.error("Expected flat DSSAT standard data with .CDE files")
    for path in ([args.spe] if args.spe else []) + args.config:
        if not path.is_file():
            parser.error(f"Missing runtime input {path}")

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    engine_path = Path("bin") / exe.name
    (out / engine_path.parent).mkdir()
    shutil.copy2(exe, out / engine_path)
    shutil.copytree(standard, out / "std-data")
    spe = None
    if args.spe:
        spe = Path(args.spe.name)
        shutil.copy2(args.spe, out / spe)
    for config in args.config:
        destination = out / "config" / config.name
        destination.parent.mkdir(exist_ok=True)
        if destination.exists():
            raise ValueError(f"Duplicate config filename: {config.name}")
        shutil.copy2(config, destination)
    manifest = {
        "schema": "dssatx-engine-v1", "id": args.id, "source_commit": head,
        "source_tracked_changes": status, "notes": args.notes,
        "engine": engine_path.as_posix(), "standard_data": "std-data",
        "spe_base": spe.as_posix() if spe else None,
        "sha256": {path.relative_to(out).as_posix(): sha(path)
                   for path in sorted(out.rglob("*")) if path.is_file()},
    }
    (out / "engine.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
