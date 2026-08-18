"""Unified integrity and use-clause checks for versioned input bundles.

Every scientific entry point (calibration build, SA case build, deterministic
re-run) must consume a frozen user-input bundle whose bytes are traceable. The
bundle directory contains an ``input_manifest.json`` that records:

- ``bundle_id``  — must equal the directory's basename;
- ``files``      — list of ``{name, sha256, bytes}`` for every payload file;
- ``intended_use`` / ``prohibited_use`` (optional) — use clauses that gate which
  downstream workflows may consume the bundle.

This module is the single source of truth for verifying those three concerns.
It is deliberately dependency-light (stdlib + :func:`sha256_file`) so it can be
imported from CLI entry points before any heavy model code is loaded.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.common.project import sha256_file


# Recognised use-clause tokens. ``parameter_calibration`` is the only one
# currently gated (an SA counterfactual bundle prohibits it); the constant is
# centralised so callers and tests share one spelling.
USE_PARAMETER_CALIBRATION = "parameter_calibration"
USE_GENETIC_SENSITIVITY = "genetic_parameter_sensitivity_analysis_only"
USE_VALIDATION_AGAINST_OBSERVED_IC = "validation_against_observed_treatment_initial_conditions"


class InputManifestError(RuntimeError):
    """Raised when a bundle's manifest is missing, malformed, or tampered with."""


class InputUseProhibitedError(InputManifestError):
    """Raised when a bundle's ``prohibited_use`` clauses block the requested use."""


@dataclass(frozen=True)
class ManifestFileIssue:
    name: str
    code: str
    message: str


@dataclass(frozen=True)
class InputManifest:
    """Parsed and validated view of an ``input_manifest.json``."""

    bundle_id: str
    directory: Path
    intended_use: str | None
    prohibited_use: tuple[str, ...]
    files: tuple[dict[str, Any], ...]
    raw: dict[str, Any]

    @property
    def manifest_path(self) -> Path:
        return self.directory / "input_manifest.json"

    @property
    def manifest_sha256(self) -> str:
        return sha256_file(self.manifest_path)

    def prohibits(self, use: str) -> bool:
        return use in self.prohibited_use


def load_input_manifest(input_dir: str | Path) -> InputManifest:
    """Load and structurally validate an input bundle manifest.

    Structural validation covers the keys the integrity check and use gates
    depend on (``bundle_id`` and ``files``). Per-file SHA-256 verification is a
    separate, explicit step (:func:`verify_manifest_files`) so callers can load
    without re-hashing on every access.

    Raises :class:`InputManifestError` if the manifest is missing, not JSON, or
    structurally incomplete.
    """
    directory = Path(input_dir).resolve()
    manifest_path = directory / "input_manifest.json"
    if not manifest_path.is_file():
        raise InputManifestError(
            f"input_manifest.json not found in input bundle {directory}"
        )
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InputManifestError(
            f"input_manifest.json in {directory} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise InputManifestError(
            f"input_manifest.json in {directory} must be a JSON object"
        )

    bundle_id = raw.get("bundle_id")
    if not isinstance(bundle_id, str) or not bundle_id.strip():
        raise InputManifestError(
            f"input_manifest.json in {directory} is missing a string bundle_id"
        )

    files = raw.get("files")
    if not isinstance(files, list) or not files:
        raise InputManifestError(
            f"input_manifest.json in {directory} must list at least one file"
        )
    normalised_files: list[dict[str, Any]] = []
    for entry in files:
        if not isinstance(entry, dict):
            raise InputManifestError(
                f"input_manifest.json in {directory} has a non-object file entry"
            )
        name = entry.get("name")
        digest = entry.get("sha256")
        if not isinstance(name, str) or not name.strip():
            raise InputManifestError(
                f"input_manifest.json in {directory} has a file entry without a name"
            )
        if not isinstance(digest, str) or len(digest) != 64:
            raise InputManifestError(
                f"input_manifest.json entry {name!r} in {directory} lacks a 64-char sha256"
            )
        normalised_files.append(entry)

    intended_use = raw.get("intended_use")
    if intended_use is not None and (not isinstance(intended_use, str) or not intended_use.strip()):
        raise InputManifestError(
            f"input_manifest.json in {directory} has a non-string intended_use"
        )
    prohibited = raw.get("prohibited_use", [])
    if prohibited is None:
        prohibited = []
    if not isinstance(prohibited, list) or any(
        not isinstance(item, str) or not item.strip() for item in prohibited
    ):
        raise InputManifestError(
            f"input_manifest.json in {directory} has a malformed prohibited_use list"
        )

    return InputManifest(
        bundle_id=bundle_id.strip(),
        directory=directory,
        intended_use=intended_use,
        prohibited_use=tuple(prohibited),
        files=tuple(normalised_files),
        raw=raw,
    )


def verify_bundle_id_matches_directory(manifest: InputManifest) -> None:
    """Require the manifest ``bundle_id`` to equal the directory basename.

    A mismatch means the bytes on disk are not the bytes the manifest was
    written for — the directory was renamed or partially copied.
    """
    if manifest.bundle_id != manifest.directory.name:
        raise InputManifestError(
            f"Bundle directory {manifest.directory.name!r} does not match "
            f"manifest bundle_id {manifest.bundle_id!r}"
        )


def verify_manifest_files(manifest: InputManifest) -> list[ManifestFileIssue]:
    """Verify every manifest-listed file exists and its SHA-256 matches.

    Returns the list of issues found (empty when the bundle is intact). This is
    the per-file integrity check the plan requires: hashing the manifest file
    alone is insufficient because it does not detect payload tampering.

    Extra files in the directory that are not in the manifest are reported as
    issues too, so a bundle cannot silently gain un-tracked inputs.
    """
    issues: list[ManifestFileIssue] = []
    seen_names: set[str] = set()
    for entry in manifest.files:
        name = entry["name"]
        seen_names.add(name)
        path = manifest.directory / name
        if not path.is_file():
            issues.append(
                ManifestFileIssue(name, "FILE_MISSING", f"Manifest lists {name!r} but it is absent")
            )
            continue
        actual = sha256_file(path)
        expected = entry["sha256"]
        if actual.lower() != str(expected).lower():
            issues.append(
                ManifestFileIssue(
                    name,
                    "HASH_MISMATCH",
                    f"{name}: manifest sha256 {expected} != on-disk {actual}",
                )
            )

    for path in sorted(manifest.directory.iterdir()):
        if not path.is_file():
            continue
        if path.name in seen_names or path.name == "input_manifest.json":
            continue
        issues.append(
            ManifestFileIssue(
                path.name,
                "UNTRACKED_FILE",
                f"Directory contains {path.name!r} which is not recorded in the manifest",
            )
        )
    return issues


def verify_manifest_integrity(input_dir: str | Path) -> InputManifest:
    """Full integrity gate: load, match directory, verify every file hash.

    Raises :class:`InputManifestError` on the first structural or integrity
    failure. Use this at every scientific entry point (calibration, SA,
    deterministic re-run) so the checks cannot drift between callers.
    """
    manifest = load_input_manifest(input_dir)
    verify_bundle_id_matches_directory(manifest)
    issues = verify_manifest_files(manifest)
    if issues:
        rendered = "; ".join(f"{issue.name}[{issue.code}]: {issue.message}" for issue in issues)
        raise InputManifestError(f"Input bundle {manifest.bundle_id} failed integrity: {rendered}")
    return manifest


def assert_use_allowed(
    manifest: InputManifest,
    *,
    use: str,
) -> None:
    """Hard-fail when the bundle's ``prohibited_use`` clauses block ``use``.

    Calibration must pass ``USE_PARAMETER_CALIBRATION``; an SA counterfactual
    bundle declares that token as prohibited. Bundles without a
    ``prohibited_use`` clause (ordinary trial bundles) are always allowed.
    """
    if use in manifest.prohibited_use:
        intended = manifest.intended_use or "(not declared)"
        raise InputUseProhibitedError(
            f"Bundle {manifest.bundle_id!r} prohibits use {use!r}; "
            f"its intended_use is {intended}. This input must not be consumed "
            f"for {use}."
        )


def verify_calibrated_input_bundle(input_dir: str | Path) -> InputManifest:
    """Convenience for calibration entry points: integrity + use gate.

    Runs the full integrity check and then enforces that the bundle does not
    prohibit parameter calibration. Returns the validated manifest so the
    caller can stamp its hash into the run record.
    """
    manifest = verify_manifest_integrity(input_dir)
    assert_use_allowed(manifest, use=USE_PARAMETER_CALIBRATION)
    return manifest


def manifest_summary(manifest: InputManifest) -> dict[str, Any]:
    """A compact, JSON-serialisable provenance summary for run records."""
    return {
        "bundle_id": manifest.bundle_id,
        "directory": str(manifest.directory),
        "intended_use": manifest.intended_use,
        "prohibited_use": list(manifest.prohibited_use),
        "file_count": len(manifest.files),
        "manifest_sha256": manifest.manifest_sha256,
    }


def issues_as_dicts(issues: list[ManifestFileIssue]) -> list[dict[str, str]]:
    return [asdict(issue) for issue in issues]


__all__ = [
    "InputManifest",
    "InputManifestError",
    "InputUseProhibitedError",
    "ManifestFileIssue",
    "USE_PARAMETER_CALIBRATION",
    "USE_GENETIC_SENSITIVITY",
    "USE_VALIDATION_AGAINST_OBSERVED_IC",
    "assert_use_allowed",
    "issues_as_dicts",
    "load_input_manifest",
    "manifest_summary",
    "verify_bundle_id_matches_directory",
    "verify_calibrated_input_bundle",
    "verify_manifest_files",
    "verify_manifest_integrity",
]
