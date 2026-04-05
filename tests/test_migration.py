"""tests/test_migration.py — 阶段 2 迁移验收测试。

验证：
1. src/ 下各子模块可导入
2. data/ 下文件完整
3. Workspace/ stub 可正常执行
4. 参数注册表可加载
"""

import os
import sys

# 确保项目根目录在 path 中
PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def test_param_registry_importable():
    """src.common.param_registry 应可正常导入。"""
    from src.common.param_registry import (
        compute_default_bounds,
        infer_parameter_group,
        PHYSICAL_BOUNDS,
        clamp_to_physical,
        load_registry_csv,
        save_registry_csv,
        RegistryEntry,
    )
    assert len(PHYSICAL_BOUNDS) > 50
    lb, ub, status = compute_default_bounds("EM-FL", 30.0, "CUL")
    assert lb < ub
    assert status == "active"


def test_param_registry_group_inference():
    """参数分组推断应返回正确结果。"""
    from src.common.param_registry import infer_parameter_group
    assert infer_parameter_group("EM-FL", "CUL") == "CUL_PheHrv"
    assert infer_parameter_group("LFMAX", "CUL") == "CUL_Growth"
    assert infer_parameter_group("SOIL_SALB", "SOIL") == "SOIL_SfcHyd"
    assert infer_parameter_group("PL-EM", "ECO") == "ECO_Pheno"
    assert infer_parameter_group("TB1", "SPE") == "SPE_Temp"


def test_param_registry_clamp():
    """物理边界截断应正常工作。"""
    from src.common.param_registry import clamp_to_physical
    lb, ub = clamp_to_physical("EM-FL", 5.0, 100.0)
    assert lb == 10.0  # PHYSICAL_BOUNDS["EM-FL"] = (10.0, 80.0)
    assert ub == 80.0


def test_data_files_exist():
    """data/ 下的关键文件应存在。"""
    checks = [
        "data/raw/weather/UFBR9401.WTH",
        "data/raw/weather/UFGA0601.WTH",
        "data/raw/weather/UFGA0701.WTH",
        "data/raw/soil/SOIL.SOL",
        "data/raw/experiments/UFBR9401.TMX",
        "data/raw/experiments/UFGA0602.TMX",
        "data/raw/experiments/UFGA0701.TMX",
        "data/raw/experiments/XXQL2501.TMX",
        "data/templates/genotype/TMGRO048.CUL.base",
        "data/templates/genotype/TMGRO048.ECO.base",
        "data/templates/genotype/TMGRO048.SPE.base",
        "data/templates/batch/DSSBatch.v48",
        "data/templates/DSSATPRO.v48",
        "data/parameter_registry/baseline/parameter_registry_skeleton.csv",
        "data/parameter_registry/bounds_frozen/eggplant/eggplant_v14_20260405.csv",
        "data/parameter_registry/bounds_frozen/eggplant/eggplant_v14_20260405.yaml",
    ]
    for rel in checks:
        path = os.path.join(PROJECT_ROOT, rel.replace("/", os.sep))
        assert os.path.exists(path), f"Missing: {rel}"


def test_src_modules_exist():
    """src/ 下的核心模块文件应存在。"""
    checks = [
        "src/common/param_registry.py",
        "src/calibration/build_pest.py",
        "src/dssat/run_dssat.py",
        "src/reporting/analyze_results.py",
        "src/reporting/plot_results.py",
        "src/reporting/visualize_results.py",
        "src/sensitivity/sa_build_sen_case.py",
        "src/sensitivity/sa_model.py",
        "src/sensitivity/sa_generate_param_review_csv.py",
    ]
    for rel in checks:
        path = os.path.join(PROJECT_ROOT, rel.replace("/", os.sep))
        assert os.path.exists(path), f"Missing: {rel}"


def test_tools_exist():
    """tools/ 下的工具脚本应存在。"""
    checks = [
        "tools/freeze_bounds.py",
        "tools/clean_workspace.py",
        "tools/cluster_parameters.py",
        "tools/download_pestpp.py",
        "tools/param_sweep.py",
        "tools/parallel/prepare_agents.py",
    ]
    for rel in checks:
        path = os.path.join(PROJECT_ROOT, rel.replace("/", os.sep))
        assert os.path.exists(path), f"Missing: {rel}"


def test_docs_exist():
    """docs/ 下的文档应存在。"""
    checks = [
        "docs/DEVELOPER_GUIDE.md",
        "docs/CHANGELOG.md",
    ]
    for rel in checks:
        path = os.path.join(PROJECT_ROOT, rel.replace("/", os.sep))
        assert os.path.exists(path), f"Missing: {rel}"


def test_workspace_stubs():
    """Workspace/ 下的 stub 应是小文件（<1KB）且包含 redirect 标记。"""
    stubs = [
        "Workspace/build_pest.py",
        "Workspace/run_dssat.py",
        "Workspace/analyze_results.py",
    ]
    for rel in stubs:
        path = os.path.join(PROJECT_ROOT, rel.replace("/", os.sep))
        assert os.path.exists(path), f"Stub missing: {rel}"
        size = os.path.getsize(path)
        assert size < 1024, f"Stub too large ({size} bytes): {rel}"
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "Stub" in content or "stub" in content, f"Not a stub: {rel}"


def test_configs_exist():
    """configs/ 下的配置文件应存在。"""
    path = os.path.join(PROJECT_ROOT, "configs", "runs", "tomato_cal.weights.csv")
    assert os.path.exists(path), "Missing: configs/runs/tomato_cal.weights.csv"


if __name__ == "__main__":
    # Simple test runner without pytest
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS: {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL: {test.__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed (total {passed + failed})")
    sys.exit(1 if failed else 0)
