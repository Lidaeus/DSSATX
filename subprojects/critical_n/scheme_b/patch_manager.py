"""Fortran patch validation and sandbox manager for Scheme B.

Ensures strict compliance with DSSAT CSM Fortran standards:
- Fixed-form Fortran 77/90 column rules:
    - Col 1: Comment indicator ('C', 'c', '*', '!') or blank/label
    - Cols 1-5: Statement label (integer) or spaces
    - Col 6: Continuation character (non-blank, non-zero) or space
    - Cols 7-72: Statement body (MUST NOT exceed column 72)
    - Cols > 72: Ignored by compiler; lines exceeding 72 characters cause silent code truncation!
- Safe sandbox application and verification without ever touching C:\\DSSAT48\\ or production trees.
"""

from __future__ import annotations

import difflib
from pathlib import Path
import shutil
import tempfile
from typing import List, Optional, Tuple


MAX_FORTRAN_FIXED_COLUMN: int = 72


def validate_fortran_fixed_format(
    content_or_path: str | Path,
    filename_for_msg: str = "source.for",
) -> List[Tuple[int, str, str]]:
    """Validate that fixed-form Fortran code complies with 72-column limit.

    Parameters
    ----------
    content_or_path : str or Path
        Either file content string or Path to Fortran file.
    filename_for_msg : str
        Filename used in error reporting.

    Returns
    -------
    list of (line_num, line_str, issue_description)
        List of detected format violations. Empty if valid.
    """
    if isinstance(content_or_path, Path):
        try:
            text = content_or_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = content_or_path.read_text(encoding="latin-1")
        filename_for_msg = content_or_path.name
    else:
        text = str(content_or_path)

    violations = []
    lines = text.splitlines()

    for idx, line in enumerate(lines, start=1):
        # Ignore comments
        stripped_left = line.lstrip()
        if stripped_left.startswith("!"):
            continue
        if len(line) > 0 and line[0] in ("C", "c", "*"):
            continue

        # Check line length
        if len(line) > MAX_FORTRAN_FIXED_COLUMN:
            # Check if overflow portion is purely whitespace or an inline comment
            code_part = line[:MAX_FORTRAN_FIXED_COLUMN]
            overflow = line[MAX_FORTRAN_FIXED_COLUMN:]
            if overflow.strip() and not overflow.lstrip().startswith("!"):
                violations.append((
                    idx,
                    line,
                    f"Line exceeds column 72 (length {len(line)}): overflow '{overflow}' would be truncated",
                ))

        # Check column 6 continuation vs statement start
        if len(line) >= 6:
            col6 = line[5]
            if col6 not in (" ", "0"):
                # Continuation line: columns 1-5 must not contain statement code
                label_part = line[:5].strip()
                if label_part and not label_part.isdigit():
                    violations.append((
                        idx,
                        line,
                        f"Continuation line has non-numeric characters in columns 1-5: '{label_part}'",
                    ))
            else:
                # Normal line: statement should start in columns 7+
                if len(line) > 6 and line[:6].strip() and not line[:5].strip().isdigit():
                    violations.append((
                        idx,
                        line,
                        f"Non-label characters found in columns 1-5: '{line[:5]}'",
                    ))

    return violations


def generate_unified_patch(
    original_text: str,
    modified_text: str,
    from_file: str,
    to_file: str,
) -> str:
    """Generate clean unified diff patch between original and modified text."""
    diff_lines = list(
        difflib.unified_diff(
            original_text.splitlines(keepends=True),
            modified_text.splitlines(keepends=True),
            fromfile=from_file,
            tofile=to_file,
            n=3,
        )
    )
    return "".join(diff_lines)


def apply_patch_in_sandbox(
    original_file: Path,
    patch_file: Path,
    sandbox_dir: Optional[Path] = None,
) -> Path:
    """Apply unified diff patch to a copy of original_file in an isolated sandbox.

    Guarantees zero modification to original files or production DSSAT directories.

    Returns
    -------
    Path
        Path to the patched file inside the sandbox directory.
    """
    if sandbox_dir is None:
        temp_dir = tempfile.mkdtemp(prefix="dssat_patch_sandbox_")
        target_dir = Path(temp_dir)
    else:
        target_dir = sandbox_dir
        target_dir.mkdir(parents=True, exist_ok=True)

    sandbox_file = target_dir / original_file.name
    shutil.copy2(original_file, sandbox_file)

    enc = "utf-8"
    try:
        orig_lines = sandbox_file.read_text(encoding="utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        enc = "latin-1"
        orig_lines = sandbox_file.read_text(encoding="latin-1").splitlines(keepends=True)

    try:
        patch_text = patch_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        patch_text = patch_file.read_text(encoding="latin-1")

    # Simple pure-python unified diff applicator for sandboxed testing
    patched_lines = _apply_unified_diff_lines(orig_lines, patch_text)
    sandbox_file.write_text("".join(patched_lines), encoding=enc)

    return sandbox_file


def _apply_unified_diff_lines(orig_lines: List[str], patch_text: str) -> List[str]:
    """Pure-Python unified diff applicator for reliable cross-platform test execution."""
    patch_lines = patch_text.splitlines(keepends=True)
    result = list(orig_lines)
    
    # Parse hunks
    i = 0
    while i < len(patch_lines):
        line = patch_lines[i]
        if line.startswith("@@"):
            # Header: @@ -start,len +start,len @@
            header = line.split("@@")[1].strip()
            orig_spec = header.split()[0][1:]  # e.g. 190,15
            orig_start = int(orig_spec.split(",")[0])
            
            # Collect hunk lines
            hunk_orig = []
            hunk_new = []
            i += 1
            while i < len(patch_lines) and not patch_lines[i].startswith("@@"):
                h_line = patch_lines[i]
                if h_line.startswith("-"):
                    hunk_orig.append(h_line[1:])
                elif h_line.startswith("+"):
                    hunk_new.append(h_line[1:])
                elif h_line.startswith(" "):
                    hunk_orig.append(h_line[1:])
                    hunk_new.append(h_line[1:])
                i += 1
            
            # Find matching context in result around orig_start - 1
            search_start = max(0, orig_start - 5)
            search_end = min(len(result), orig_start + 15)
            match_idx = -1
            
            # Match hunk_orig block in result
            for pos in range(search_start, search_end):
                if result[pos:pos + len(hunk_orig)] == hunk_orig:
                    match_idx = pos
                    break
            
            if match_idx != -1:
                result[match_idx:match_idx + len(hunk_orig)] = hunk_new
            else:
                # Fallback: search globally if not found locally
                for pos in range(len(result) - len(hunk_orig) + 1):
                    if result[pos:pos + len(hunk_orig)] == hunk_orig:
                        match_idx = pos
                        break
                if match_idx != -1:
                    result[match_idx:match_idx + len(hunk_orig)] = hunk_new
                else:
                    raise RuntimeError(f"Failed to match hunk context starting at line {orig_start}")
        else:
            i += 1

    return result
