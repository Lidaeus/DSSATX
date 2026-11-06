"""Read-only snapshot of the five FileX inputs examined in the P0 review."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/reports/evidence/p0_settings_review_20260914"
BUNDLES = {
    "25C": "data/user/experiments/XXQL2501",
    "25D": "data/user/experiments/xxql2501_scheme4_double_n_20260831",
    "26C": "data/user/experiments/XXQL2601",
    "26D": "workspace/reports/e02_v46_26sp_soil_n_scale_sweep_20260901/bundles_v2/s0p34",
    "FA": "data/user/experiments/XXQL2502",
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    extracts, manifest, matrix = [], [], {}
    for label, relative in BUNDLES.items():
        folder = ROOT / relative
        filex = next(folder.glob("*.TMX"))
        files = [filex, *folder.glob("*.WTH")]
        if (folder / "SOIL.SOL").exists():
            files.append(folder / "SOIL.SOL")
        matrix[label] = {}
        for path in files:
            content = path.read_bytes()
            manifest.append({"bundle": label, "path": path.relative_to(ROOT).as_posix(),
                             "sha256": hashlib.sha256(content).hexdigest()})
            extracts.append(f"\n## {label}: {path.relative_to(ROOT).as_posix()}")
            lines = content.decode("utf-8", errors="replace").splitlines()
            section = ""
            header = []
            for number, line in enumerate(lines, 1):
                if line.startswith("*"):
                    section = line
                if path.suffix.upper() == ".TMX":
                    extracts.append(f"{number}: {line}")
                    if line.startswith("@N METHODS"):
                        header = line.split()[2:]
                    elif len(line.split()) > 2 and line.split()[1] == "ME" and header:
                        matrix[label][line.split()[0]] = dict(zip(header, line.split()[2:]))
                elif path.suffix.upper() == ".WTH" and number <= 6:
                    extracts.append(f"{number}: {line}")
                elif path.name == "SOIL.SOL" and section.startswith("*IBTM910017"):
                    extracts.append(f"{number}: {line}")
    expected = dict(zip("WTHER INCON LIGHT EVAPO INFIL PHOTO HYDRO NSWIT MESOM MESEV MESOL".split(),
                        "M M E R S L R 1 P R 2".split()))
    for label, controls in matrix.items():
        assert controls, label
        assert all(values == expected for values in controls.values()), (label, controls)
    for name, text in {
        "local_input_extracts.txt": "\n".join(extracts),
        "local_input_manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2),
        "actual_methods.json": json.dumps(matrix, ensure_ascii=False, indent=2),
    }.items():
        target = OUT / name
        with target.open("x", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print("Five bundles audited; all METHODS records match. Source inputs unchanged.")


if __name__ == "__main__":
    main()
