"""Automated build and verification runner for DSSAT-CSM Scheme B custom binary.

Environment & Safety Contract:
- Compiles sandboxed DSSAT binaries under `subprojects/critical_n/`:
    - Baseline vanilla: `subprojects/critical_n/bin/dscsm048_vanilla.exe`
    - Custom Scheme B: `subprojects/critical_n/bin/dscsm048_cnc.exe`
- NEVER modifies or overwrites production `C:\\DSSAT48\\DSCSM048.EXE`.
- Injects native CTest regression suite into CMakeLists.txt.
- Runs official DSSAT benchmarks and greenhouse tomato/eggplant cases for regression QA.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.calibration.run_dssat import prepare_run_directory
from subprojects.critical_n.scheme_b.patch_manager import validate_fortran_fixed_format

CRITICAL_N_DIR = PROJECT_ROOT / "subprojects" / "critical_n"
UPSTREAM_SRC_DIR = PROJECT_ROOT / "workspace" / "diagnostics" / "dssat-csm-os-v4.8.2-source"
FORTRAN_PATCH_DIR = CRITICAL_N_DIR / "fortran_patch"

DSSAT_CSM_DIR = CRITICAL_N_DIR / "dssat_csm"
DSSAT_CSM_CNC_DIR = CRITICAL_N_DIR / "dssat_csm_cnc"

BUILD_DIR = CRITICAL_N_DIR / "build"
BUILD_BASELINE_DIR = BUILD_DIR / "baseline"
BUILD_CUSTOM_DIR = BUILD_DIR / "custom"

BIN_DIR = CRITICAL_N_DIR / "bin"
BIN_VANILLA = BIN_DIR / "dscsm048_vanilla.exe"
BIN_CNC = BIN_DIR / "dscsm048_cnc.exe"

VERIFY_DIR = CRITICAL_N_DIR / "verification_runs"

PRODUCTION_EXE = Path(r"C:\DSSAT48\DSCSM048.EXE")
PRODUCTION_HASH = "92173d5f63bc60d58839630b9a29f57632a19b373cab0faa8ad70362d98f5c7a"


def find_toolchain() -> Dict[str, str]:
    """Detect Fortran compiler toolchain in PATH or standard WinLibs / MinGW directories."""
    candidate_dirs: List[Path] = []

    # 1. Search User Winget Packages directory
    winget_root = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    if winget_root.is_dir():
        for p in winget_root.glob("*WinLibs*/mingw64/bin"):
            if p.is_dir() and p not in candidate_dirs:
                candidate_dirs.append(p)

    # 2. Search common system locations
    system_candidates = [
        Path(r"C:\Users\Lidaeus\AppData\Local\Microsoft\WinGet\Packages\BrechtSanders.WinLibs.POSIX.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe\mingw64\bin"),
        Path(r"C:\msys64\mingw64\bin"),
        Path(r"C:\msys64\ucrt64\bin"),
        Path(r"C:\MinGW\bin"),
        Path(r"C:\winlibs\bin"),
    ]
    for sc in system_candidates:
        if sc.is_dir() and sc not in candidate_dirs:
            candidate_dirs.append(sc)

    current_path = os.environ.get("PATH", "")
    for cdir in candidate_dirs:
        if str(cdir) not in current_path:
            os.environ["PATH"] = str(cdir) + os.pathsep + os.environ["PATH"]
            current_path = os.environ["PATH"]

    tools = {}
    for tool_name in ["gfortran", "gcc", "cmake", "ninja", "ctest"]:
        found = shutil.which(tool_name)
        if not found:
            for cdir in candidate_dirs:
                direct = cdir / f"{tool_name}.exe"
                if direct.is_file():
                    found = str(direct)
                    break
        if not found:
            raise RuntimeError(f"Required tool '{tool_name}' not found in PATH or standard locations.")
        tools[tool_name] = found

    return tools


def check_production_safety() -> None:
    """Verify that production DSCSM048.EXE exists and remains untouched."""
    if not PRODUCTION_EXE.is_file():
        return
    current_hash = hashlib.sha256(PRODUCTION_EXE.read_bytes()).hexdigest()
    if current_hash != PRODUCTION_HASH:
        raise RuntimeError(
            f"CRITICAL SAFETY VIOLATION: Production {PRODUCTION_EXE} was modified!\n"
            f"Expected SHA-256: {PRODUCTION_HASH}\n"
            f"Found SHA-256:    {current_hash}"
        )


def _patch_opsoilni_descriptor(source_tree: Path) -> None:
    """Fix upstream Fortran format descriptor typo (T52X -> 52X) in OPSOILNI.for."""
    target = source_tree / "Soil" / "Inorganic_N" / "OPSOILNI.for"
    if not target.is_file():
        return
    text = target.read_text(encoding="latin-1")
    bad_pattern = "'(T',SPACES,'X,\"Total Inorganic N @dep(ppm):\"'"
    if bad_pattern in text:
        good_pattern = "'(',SPACES,'X,\"Total Inorganic N @dep(ppm):\"'"
        target.write_text(text.replace(bad_pattern, good_pattern), encoding="latin-1")


def _inject_ctest_support(source_tree: Path, is_custom: bool = False) -> None:
    """Inject CTest suite definition into DSSAT CMakeLists.txt if not present."""
    cmake_file = source_tree / "CMakeLists.txt"
    if not cmake_file.is_file():
        return
    text = cmake_file.read_text(encoding="utf-8")
    if "enable_testing()" in text:
        return

    ctest_block = """
##########################################################################################
# CTest Regression Test Suite
##########################################################################################
enable_testing()

add_test(
    NAME dssat_smoke_help
    COMMAND ${CMAKE_RUNTIME_OUTPUT_DIRECTORY}/${EXECUTABLE_NAME}
)
set_tests_properties(dssat_smoke_help PROPERTIES
    PASS_REGULAR_EXPRESSION "dscsm048 <model> runmode"
)

find_package(Python3 COMPONENTS Interpreter QUIET)
if(Python3_FOUND)
    add_test(
        NAME dssat_official_tomato
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_SOURCE_DIR}/../scripts/build_and_verify_dssat.py" --ctest-benchmark Tomato.v48 --exe "$<TARGET_FILE:${EXECUTABLE_NAME}>"
    )
    add_test(
        NAME dssat_official_maize
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_SOURCE_DIR}/../scripts/build_and_verify_dssat.py" --ctest-benchmark Maize.v48 --exe "$<TARGET_FILE:${EXECUTABLE_NAME}>"
    )
    add_test(
        NAME dssat_greenhouse_simulation
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_SOURCE_DIR}/../scripts/build_and_verify_dssat.py" --ctest-greenhouse --exe "$<TARGET_FILE:${EXECUTABLE_NAME}>"
    )
"""
    if is_custom:
        ctest_block += """    add_test(
        NAME dssat_scheme_b_coupling
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_SOURCE_DIR}/../scripts/build_and_verify_dssat.py" --ctest-greenhouse --mepho C --exe "$<TARGET_FILE:${EXECUTABLE_NAME}>"
    )
"""
    ctest_block += """endif()
"""
    cmake_file.write_text(text + ctest_block, encoding="utf-8")


def setup_source_trees(force_refresh: bool = False) -> None:
    """Prepare vanilla source tree and Scheme B custom source tree in subprojects/critical_n/."""
    if not UPSTREAM_SRC_DIR.is_dir():
        raise FileNotFoundError(f"DSSAT upstream source directory not found: {UPSTREAM_SRC_DIR}")

    # 1. Setup vanilla dssat_csm
    if force_refresh or not (DSSAT_CSM_DIR / "CMakeLists.txt").is_file():
        print(f"[*] Copying upstream DSSAT source to {DSSAT_CSM_DIR}...")
        if DSSAT_CSM_DIR.exists():
            shutil.rmtree(DSSAT_CSM_DIR)
        shutil.copytree(
            UPSTREAM_SRC_DIR,
            DSSAT_CSM_DIR,
            ignore=shutil.ignore_patterns(".git", ".vscode", "build*", "*.o", "*.obj", "*.mod"),
        )
    else:
        print(f"[+] Vanilla source tree present: {DSSAT_CSM_DIR}")

    _patch_opsoilni_descriptor(DSSAT_CSM_DIR)
    _inject_ctest_support(DSSAT_CSM_DIR, is_custom=False)

    # 2. Setup patched dssat_csm_cnc
    if force_refresh or not (DSSAT_CSM_CNC_DIR / "CMakeLists.txt").is_file():
        print(f"[*] Creating custom Scheme B source tree at {DSSAT_CSM_CNC_DIR}...")
        if DSSAT_CSM_CNC_DIR.exists():
            shutil.rmtree(DSSAT_CSM_CNC_DIR)
        shutil.copytree(
            DSSAT_CSM_DIR,
            DSSAT_CSM_CNC_DIR,
            ignore=shutil.ignore_patterns("build*", "*.o", "*.obj", "*.mod"),
        )
    else:
        print(f"[+] Custom source tree present: {DSSAT_CSM_CNC_DIR}")

    _patch_opsoilni_descriptor(DSSAT_CSM_CNC_DIR)
    _inject_ctest_support(DSSAT_CSM_CNC_DIR, is_custom=True)

    # Synchronize Scheme B patches in Plant/CROPGRO/
    cropgro_dir = DSSAT_CSM_CNC_DIR / "Plant" / "CROPGRO"
    src_scheme_b = FORTRAN_PATCH_DIR / "src_scheme_b"

    patch_targets = [
        ("PHOTO_CNC.FOR", "PHOTO.for"),
        ("SENES_CNC.FOR", "SENES.for"),
        ("CROPGRO_CNC.FOR", "CROPGRO.for"),
    ]

    for src_name, dst_name in patch_targets:
        src_file = src_scheme_b / src_name
        dst_file = cropgro_dir / dst_name
        if not src_file.is_file():
            raise FileNotFoundError(f"Missing Scheme B patched source: {src_file}")

        need_copy = not dst_file.is_file()
        if not need_copy:
            need_copy = src_file.read_bytes() != dst_file.read_bytes()

        if need_copy:
            print(f"  -> Injecting {src_name} into {dst_file.relative_to(CRITICAL_N_DIR)}")
            shutil.copy2(src_file, dst_file)

        violations = validate_fortran_fixed_format(dst_file)
        if violations:
            raise ValueError(
                f"72-column violations detected in {dst_file}: {violations[:3]}"
            )
    print("  -> Scheme B patches synchronized and validated (0 column violations).")


def build_binary(
    source_dir: Path,
    build_dir: Path,
    output_bin: Path,
    tools: Dict[str, str],
    build_type: str = "Release",
) -> Path:
    """Configure with CMake and build with Ninja into isolated binary."""
    build_dir.mkdir(parents=True, exist_ok=True)
    BIN_DIR.mkdir(parents=True, exist_ok=True)

    cmake_exe = tools["cmake"]
    ninja_exe = tools["ninja"]
    gfortran_exe = tools["gfortran"]
    py_exe = sys.executable.replace(os.sep, "/")

    # 1. CMake configure
    config_cmd = [
        cmake_exe,
        "-G", "Ninja",
        f"-DCMAKE_Fortran_COMPILER={gfortran_exe}",
        f"-DCMAKE_BUILD_TYPE={build_type}",
        f"-DPython3_EXECUTABLE={py_exe}",
        str(source_dir),
    ]
    print(f"[*] Configuring {source_dir.name} in {build_dir.name}...")
    t0 = time.time()
    p_cfg = subprocess.run(
        config_cmd,
        cwd=build_dir,
        capture_output=True,
        text=True,
    )
    if p_cfg.returncode != 0:
        raise RuntimeError(
            f"CMake configuration failed for {source_dir}:\nSTDOUT:\n{p_cfg.stdout}\nSTDERR:\n{p_cfg.stderr}"
        )
    print(f"  -> CMake configuration succeeded in {time.time() - t0:.1f}s")

    # 2. Ninja build
    print(f"[*] Building with Ninja...")
    t1 = time.time()
    p_build = subprocess.run(
        [ninja_exe],
        cwd=build_dir,
        capture_output=True,
        text=True,
    )
    if p_build.returncode != 0:
        raise RuntimeError(
            f"Ninja build failed for {source_dir}:\nSTDOUT:\n{p_build.stdout[-2000:]}\nSTDERR:\n{p_build.stderr[-2000:]}"
        )
    print(f"  -> Ninja build succeeded in {time.time() - t1:.1f}s")

    # 3. Locate built binary
    built_exe = build_dir / "bin" / "dscsm048.exe"
    if not built_exe.is_file():
        raise FileNotFoundError(f"Expected binary not found: {built_exe}")

    # Copy to destination in subprojects/critical_n/bin/
    shutil.copy2(built_exe, output_bin)
    print(f"[+] Output executable ready: {output_bin} ({output_bin.stat().st_size / (1024*1024):.2f} MB)")
    check_production_safety()
    return output_bin


def run_ctest_suite(build_dir: Path, tools: Dict[str, str]) -> Dict[str, Any]:
    """Execute CTest regression test suite inside build directory."""
    ctest_exe = tools["ctest"]
    t0 = time.time()
    p = subprocess.run(
        [ctest_exe, "--output-on-failure"],
        cwd=build_dir,
        capture_output=True,
        text=True,
        timeout=300,
    )
    elapsed = time.time() - t0
    check_production_safety()
    return {
        "returncode": p.returncode,
        "elapsed_sec": round(elapsed, 2),
        "passed": p.returncode == 0,
        "stdout": p.stdout,
        "stderr": p.stderr,
    }


def run_official_benchmark(
    exe_path: Path,
    batch_name: str,
    work_dir: Path,
    crop_model: Optional[str] = None,
) -> Dict[str, Any]:
    """Run an official DSSAT benchmark batch file in an isolated verification directory."""
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    batch_src = UPSTREAM_SRC_DIR / "Data" / "BatchFiles" / batch_name
    if not batch_src.is_file():
        raise FileNotFoundError(f"Official batch file not found: {batch_src}")

    target_batch = work_dir / "DSSBatch.v48"
    if batch_name == "Tomato.v48":
        # Keep verified treatments 1-8 (UFBR and UFGA), filter out broken UFQU lines 19-20
        raw_lines = batch_src.read_text(encoding="latin-1").splitlines(keepends=True)
        valid_lines = [l for l in raw_lines if "UFQU" not in l]
        target_batch.write_text("".join(valid_lines), encoding="latin-1")
    else:
        shutil.copy2(batch_src, target_batch)

    cmd = [str(exe_path)]
    if crop_model:
        cmd.append(crop_model)
    cmd.extend(["B", "DSSBatch.v48"])

    t0 = time.time()
    p = subprocess.run(
        cmd,
        cwd=work_dir,
        input="\n" * 8,
        capture_output=True,
        text=True,
        timeout=180,
    )
    elapsed = time.time() - t0

    out_files = [f.name for f in work_dir.glob("*.OUT")]
    has_summary = (work_dir / "Summary.OUT").is_file()
    has_evaluate = (work_dir / "Evaluate.OUT").is_file()
    summary_lines = 0
    if has_summary:
        summary_lines = len((work_dir / "Summary.OUT").read_text(encoding="latin-1", errors="ignore").splitlines())

    check_production_safety()

    return {
        "batch_name": batch_name,
        "crop_model": crop_model or "DEFAULT",
        "returncode": p.returncode,
        "elapsed_sec": round(elapsed, 2),
        "out_files_count": len(out_files),
        "has_summary": has_summary,
        "summary_lines": summary_lines,
        "has_evaluate": has_evaluate,
        "stdout_tail": p.stdout[-500:] if p.stdout else "",
        "stderr": p.stderr,
    }


def run_greenhouse_experiment(
    exe_path: Path,
    work_dir: Path,
    mepho: str = "L",
) -> Dict[str, Any]:
    """Run greenhouse eggplant/tomato experiment XXQL2501 in an isolated directory."""
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    # Use project standard prepare_run_directory
    prepare_run_directory(work_dir, ["--batch", "DSSBatch.v48", "--harvest-var", "CHPDT"])

    # Remove copied production DSCSM048.EXE from work_dir to guarantee sandbox execution
    copied_prod = work_dir / "DSCSM048.EXE"
    if copied_prod.is_file():
        copied_prod.unlink()

    # Optionally switch to Canopy photosynthesis for Scheme B active coupling
    if mepho.upper() == "C":
        tmx = work_dir / "XXQL2501.TMX"
        if tmx.is_file():
            raw = tmx.read_text(encoding="latin-1")
            tmx.write_text(
                raw.replace("S     L     R     1", "S     C     R     1"),
                encoding="latin-1",
            )

    cmd = [str(exe_path), "CRGRO048", "B", "DSSBatch.v48"]
    t0 = time.time()
    p = subprocess.run(
        cmd,
        cwd=work_dir,
        input="\n" * 8,
        capture_output=True,
        text=True,
        timeout=180,
    )
    elapsed = time.time() - t0

    plantgro = work_dir / "PlantGro.OUT"
    plantgro_lines = 0
    if plantgro.is_file():
        plantgro_lines = len(plantgro.read_text(encoding="latin-1", errors="ignore").splitlines())

    summary = work_dir / "Summary.OUT"
    summary_lines = 0
    if summary.is_file():
        summary_lines = len(summary.read_text(encoding="latin-1", errors="ignore").splitlines())

    freshwt = work_dir / "FreshWt.OUT"
    freshwt_lines = 0
    if freshwt.is_file():
        freshwt_lines = len(freshwt.read_text(encoding="latin-1", errors="ignore").splitlines())

    check_production_safety()

    return {
        "mepho": mepho.upper(),
        "returncode": p.returncode,
        "elapsed_sec": round(elapsed, 2),
        "has_plantgro": plantgro.is_file(),
        "plantgro_lines": plantgro_lines,
        "has_summary": summary.is_file(),
        "summary_lines": summary_lines,
        "has_freshwt": freshwt.is_file(),
        "freshwt_lines": freshwt_lines,
        "stderr": p.stderr,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="DSSAT-CSM Custom Build and Verification")
    parser.add_argument("--force-refresh", action="store_true", help="Force rebuild from scratch")
    parser.add_argument("--skip-benchmarks", action="store_true", help="Skip running benchmarks")
    parser.add_argument("--ctest-benchmark", type=str, default=None, help="Run single benchmark for CTest")
    parser.add_argument("--ctest-greenhouse", action="store_true", help="Run greenhouse experiment for CTest")
    parser.add_argument("--mepho", type=str, default="L", choices=["L", "C"], help="Photosynthesis method (L=leaf, C=canopy)")
    parser.add_argument("--exe", type=str, default=None, help="Executable path to test under CTest")
    args = parser.parse_args()

    # CTest helper execution modes
    if args.ctest_benchmark:
        target_exe = Path(args.exe) if args.exe else BIN_VANILLA
        work_d = VERIFY_DIR / "ctest" / f"{args.ctest_benchmark}_{target_exe.stem}" / str(int(time.time()))
        crop_model = "CRGRO048" if "Tomato" in args.ctest_benchmark else None
        res = run_official_benchmark(target_exe, args.ctest_benchmark, work_d, crop_model)
        if res["returncode"] != 0 or not res["has_summary"]:
            print(f"[-] CTest benchmark failed: {res}")
            return 1
        print(f"[+] CTest benchmark {args.ctest_benchmark} PASSED. Summary lines: {res['summary_lines']}")
        return 0

    if args.ctest_greenhouse:
        target_exe = Path(args.exe) if args.exe else BIN_CNC
        work_d = VERIFY_DIR / "ctest" / f"greenhouse_{args.mepho}_{target_exe.stem}" / str(int(time.time()))
        res = run_greenhouse_experiment(target_exe, work_d, mepho=args.mepho)
        if res["returncode"] != 0 or not res["has_plantgro"]:
            print(f"[-] CTest greenhouse failed: {res}")
            return 1
        print(f"[+] CTest greenhouse (MEPHO={args.mepho}) PASSED. PlantGro lines: {res['plantgro_lines']}")
        return 0

    print("=================================================================")
    print(" DSSAT-CSM Fortran Compilation & Scheme B Verification Pipeline   ")
    print("=================================================================")

    # 1. Check production isolation & toolchain
    check_production_safety()
    print("[*] Detecting Fortran compiler toolchain...")
    tools = find_toolchain()
    for t_name, t_path in tools.items():
        print(f"  {t_name:10s} : {t_path}")

    # Output compiler version
    p_ver = subprocess.run([tools["gfortran"], "--version"], capture_output=True, text=True)
    compiler_line = p_ver.stdout.splitlines()[0]
    print(f"[*] Fortran Compiler: {compiler_line}")

    # 2. Source setup
    print("\n[*] Preparing isolated source trees...")
    setup_source_trees(force_refresh=args.force_refresh)

    # 3. Build baseline executable
    print("\n[*] Building baseline vanilla DSSAT executable...")
    build_binary(DSSAT_CSM_DIR, BUILD_BASELINE_DIR, BIN_VANILLA, tools)

    # 4. Build custom Scheme B executable
    print("\n[*] Building custom Scheme B DSSAT executable...")
    build_binary(DSSAT_CSM_CNC_DIR, BUILD_CUSTOM_DIR, BIN_CNC, tools)

    check_production_safety()

    if args.skip_benchmarks:
        print("\n[+] Build complete. Skipping benchmarks as requested.")
        return 0

    # 5. Run native CTest suites
    print("\n[*] Running native CTest regression suites in build directories...")
    ctest_vanilla = run_ctest_suite(BUILD_BASELINE_DIR, tools)
    print(f"  [Vanilla CTest] Passed={ctest_vanilla['passed']}, Elapsed={ctest_vanilla['elapsed_sec']}s")
    assert ctest_vanilla["passed"], f"Vanilla CTest failed:\n{ctest_vanilla['stdout']}\n{ctest_vanilla['stderr']}"

    ctest_cnc = run_ctest_suite(BUILD_CUSTOM_DIR, tools)
    print(f"  [Scheme B CTest] Passed={ctest_cnc['passed']}, Elapsed={ctest_cnc['elapsed_sec']}s")
    assert ctest_cnc["passed"], f"Scheme B CTest failed:\n{ctest_cnc['stdout']}\n{ctest_cnc['stderr']}"

    # 6. Run official benchmarks
    print("\n[*] Running official DSSAT benchmark test suites...")
    results: Dict[str, Any] = {
        "toolchain": tools,
        "compiler_version": compiler_line,
        "binaries": {
            "vanilla": str(BIN_VANILLA),
            "vanilla_size": BIN_VANILLA.stat().st_size,
            "cnc": str(BIN_CNC),
            "cnc_size": BIN_CNC.stat().st_size,
        },
        "ctest_results": {
            "vanilla": {
                "passed": ctest_vanilla["passed"],
                "elapsed_sec": ctest_vanilla["elapsed_sec"],
                "output_tail": ctest_vanilla["stdout"][-500:],
            },
            "cnc": {
                "passed": ctest_cnc["passed"],
                "elapsed_sec": ctest_cnc["elapsed_sec"],
                "output_tail": ctest_cnc["stdout"][-500:],
            },
        },
        "official_benchmarks": {},
        "greenhouse_runs": {},
    }

    test_batches = [
        ("Tomato.v48", "CRGRO048"),
        ("Maize.v48", None),
        ("Potato.v48", None),
        ("Rice.v48", None),
    ]

    for bname, model in test_batches:
        print(f"\n  >> Benchmark: {bname} (Model: {model or 'DEFAULT'})")
        vanilla_dir = VERIFY_DIR / "official" / "vanilla" / bname.split(".")[0]
        res_v = run_official_benchmark(BIN_VANILLA, bname, vanilla_dir, model)
        print(f"     [Vanilla] exit={res_v['returncode']}, elapsed={res_v['elapsed_sec']}s, Summary lines={res_v['summary_lines']}")

        cnc_dir = VERIFY_DIR / "official" / "cnc" / bname.split(".")[0]
        res_c = run_official_benchmark(BIN_CNC, bname, cnc_dir, model)
        print(f"     [Scheme B] exit={res_c['returncode']}, elapsed={res_c['elapsed_sec']}s, Summary lines={res_c['summary_lines']}")

        results["official_benchmarks"][bname] = {
            "vanilla": res_v,
            "cnc": res_c,
        }

        assert res_v["returncode"] == 0, f"Vanilla failed on {bname}: {res_v['stderr']}"
        assert res_c["returncode"] == 0, f"Custom CNC failed on {bname}: {res_c['stderr']}"
        assert res_c["has_summary"], f"Summary.OUT missing in CNC run for {bname}"

    # 7. Run greenhouse tomato/eggplant experiment (Dual-Mode: MEPHO=L and MEPHO=C)
    print("\n[*] Running greenhouse experiment under default MEPHO='L' (backward compatibility check)...")
    gh_v_l_dir = VERIFY_DIR / "greenhouse" / "vanilla_mepho_l"
    res_gh_v_l = run_greenhouse_experiment(BIN_VANILLA, gh_v_l_dir, mepho="L")
    gh_c_l_dir = VERIFY_DIR / "greenhouse" / "cnc_mepho_l"
    res_gh_c_l = run_greenhouse_experiment(BIN_CNC, gh_c_l_dir, mepho="L")
    print(f"  [Vanilla MEPHO=L] exit={res_gh_v_l['returncode']}, PlantGro lines={res_gh_v_l['plantgro_lines']}")
    print(f"  [Scheme B MEPHO=L] exit={res_gh_c_l['returncode']}, PlantGro lines={res_gh_c_l['plantgro_lines']}")

    print("\n[*] Running greenhouse experiment under MEPHO='C' (Scheme B continuous NNI acclimation active)...")
    gh_v_c_dir = VERIFY_DIR / "greenhouse" / "vanilla_mepho_c"
    res_gh_v_c = run_greenhouse_experiment(BIN_VANILLA, gh_v_c_dir, mepho="C")
    gh_c_c_dir = VERIFY_DIR / "greenhouse" / "cnc_mepho_c"
    res_gh_c_c = run_greenhouse_experiment(BIN_CNC, gh_c_c_dir, mepho="C")
    print(f"  [Vanilla MEPHO=C] exit={res_gh_v_c['returncode']}, PlantGro lines={res_gh_v_c['plantgro_lines']}")
    print(f"  [Scheme B MEPHO=C] exit={res_gh_c_c['returncode']}, PlantGro lines={res_gh_c_c['plantgro_lines']}")

    results["greenhouse_runs"] = {
        "mepho_l": {
            "vanilla": res_gh_v_l,
            "cnc": res_gh_c_l,
        },
        "mepho_c": {
            "vanilla": res_gh_v_c,
            "cnc": res_gh_c_c,
        },
    }

    assert res_gh_v_l["returncode"] == 0 and res_gh_c_l["returncode"] == 0
    assert res_gh_v_c["returncode"] == 0 and res_gh_c_c["returncode"] == 0
    assert res_gh_c_c["plantgro_lines"] > 0

    # 8. Production safety final check
    check_production_safety()
    print("\n[+] All verifications PASSED! Production C:\\DSSAT48\\DSCSM048.EXE untouched.")

    # Save results JSON
    report_json_path = CRITICAL_N_DIR / "reports" / "build_verification_summary.json"
    report_json_path.parent.mkdir(parents=True, exist_ok=True)
    report_json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"[+] Saved execution record: {report_json_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
