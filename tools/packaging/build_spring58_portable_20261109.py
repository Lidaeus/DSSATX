"""Build a path-preserving portable package for the spring58 restored-bounds calibration.

The package keeps every absolute path referenced by the run's sealed design.json
(D:\\Tomato_Cal\\..., C:\\DSSAT48\\..., D:\\Tomato_Cal_Cold_Storage\\...) as relative
subtrees, so hash verification inside trial.forward() passes after the package is
unpacked at the same drive roots.
"""
from __future__ import annotations
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(r"D:\Tomato_Cal")
RUN_ID = "eggplant_final_springs_58_restored_bounds_40x3_8agents_20261107"
RUN = ROOT / "workspace/runs" / RUN_ID
PKG = ROOT / "workspace/dist/eggplant_spring58_calibration_portable_20261109"
COLD = Path(r"D:\Tomato_Cal_Cold_Storage\bundle_retirement_20261105\calibration\xxql2501_refreshed_20261027")
DSSAT_EXE = Path(r"C:\DSSAT48\DSCSM048.EXE")

EXCLUDE_DIRS = {"__pycache__", "_agents", ".git", ".pytest_cache", ".dbg"}
EXCLUDE_FILES = {"_pkg_inventory.py"}
EXCLUDE_SUFFIX = {".pyc", ".log"}


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_tree(src: Path, dst: Path) -> None:
    for p in src.rglob("*"):
        if any(part in EXCLUDE_DIRS for part in p.parts):
            continue
        if p.is_dir():
            continue
        if p.suffix.lower() in EXCLUDE_SUFFIX or p.name in EXCLUDE_FILES:
            continue
        target = dst / p.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def main() -> None:
    design = json.loads((RUN / "design.json").read_text(encoding="utf-8"))
    if PKG.exists():
        shutil.rmtree(PKG)
    PKG.mkdir(parents=True)

    repo = PKG / "Tomato_Cal"
    # 1) code + registry + templates-side data + pestpp + requirements
    for sub in ("src", "tools", "data/parameter_registry", "pestpp-5.2.16-win"):
        copy_tree(ROOT / sub, repo / sub)
    copy_tree(ROOT / "data/user/experiments/xxql2601_final_20261105",
              repo / "data/user/experiments/xxql2601_final_20261105")
    copy_file(ROOT / "requirements.txt", repo / "requirements.txt")

    # 2) this run, complete except agent sandboxes
    copy_tree(RUN, repo / "workspace/runs" / RUN_ID)

    # 3) every remaining sealed source-hash file at its repo-relative path
    prefix = "D:\\Tomato_Cal\\"
    sealed = [p for p in map(Path, design["source_hashes"]) if str(p).startswith(prefix)]
    for p in sorted(sealed):
        rel = Path(str(p)[len(prefix):].replace("\\", "/"))
        target = repo / rel
        if not target.exists():
            copy_file(p, target)

    # 4) cold-storage validation bundle + DSSAT executable
    copy_tree(COLD, PKG / "Tomato_Cal_Cold_Storage/bundle_retirement_20261105/calibration/xxql2501_refreshed_20261027")
    copy_file(DSSAT_EXE, PKG / "DSSAT48/DSCSM048.EXE")

    # 5) clean_restart case with a PATH-resolvable model command
    clean = repo / "workspace/runs" / RUN_ID / "clean_restart"
    clean.mkdir(parents=True, exist_ok=True)
    joint = RUN / "joint"
    for name in ("parameters.tpl", "objectives.ins", "initial_ensemble.csv", "parameters.csv",
                 "FormalObjectives.OUT", "run_manifest.yaml"):
        copy_file(joint / name, clean / name)
    copy_file(ROOT / "tools/packaging/spring58_docs/make_fresh_joint.py", clean / "make_fresh_joint.py")
    copy_file(ROOT / "tools/packaging/spring58_docs/README_运行指南.md", PKG / "README_运行指南.md")
    copy_file(ROOT / "tools/packaging/spring58_docs/目标函数设计说明.md", PKG / "目标函数设计说明.md")
    pst = (joint / "joint.pst").read_text(encoding="utf-8", errors="replace")
    marker = r'"C:\Users\Lidaeus\AppData\Local\Programs\Python\Python313\python.exe"'
    assert pst.count(marker) == 1, "unexpected model command line"
    (clean / "joint.pst").write_text(pst.replace(marker, '"python"'), encoding="utf-8")

    # 6) verify every sealed hash against the packaged copy
    mapping = [(Path(p), (PKG / "DSSAT48" / Path(p).name) if Path(p).drive == "C:"
                else PKG / "Tomato_Cal" / Path(str(p)[len(prefix):])) for p in design["source_hashes"]]
    bad = [f"{src} -> {dst}: missing or hash mismatch" for src, dst in mapping
           if not dst.exists() or sha(dst) != design["source_hashes"][str(src)]]
    assert not bad, "\n".join(bad)

    # 7) manifest of the whole package
    rows = []
    for p in sorted(PKG.rglob("*")):
        if p.is_file():
            rows.append((p.relative_to(PKG).as_posix(), p.stat().st_size, sha(p)))
    manifest = PKG / "MANIFEST.csv"
    manifest.write_text("path,bytes,sha256\n" + "".join(f"{r},{b},{h}\n" for r, b, h in rows), encoding="utf-8")

    # 8) zip
    archive = PKG.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(PKG.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(PKG.parent))
    print("package:", PKG)
    print("files:", len(rows), "| zip:", archive, f"({archive.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
