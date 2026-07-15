"""Fail early when the active Python environment violates runtime requirements."""

from importlib import metadata
from pathlib import Path
import sys

from packaging.requirements import Requirement


ROOT = Path(__file__).resolve().parents[1]


def test_supported_python_version():
    assert sys.version_info >= (3, 13)


def test_installed_runtime_dependencies_satisfy_requirements_file():
    requirements = []
    for raw_line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            requirements.append(Requirement(line))
    assert requirements
    violations = []
    for requirement in requirements:
        try:
            installed = metadata.version(requirement.name)
        except metadata.PackageNotFoundError:
            violations.append(f"{requirement.name}: missing")
            continue
        if installed not in requirement.specifier:
            violations.append(f"{requirement.name}: {installed} not in {requirement.specifier}")
    assert not violations, "; ".join(violations)
