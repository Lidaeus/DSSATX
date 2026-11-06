"""Unit tests for frozen external invariant bounds protocol."""

import pandas as pd
import pytest

from subprojects.critical_n.calibration.bounds_protocol import (
    CNC_FROZEN_INVARIANTS,
    CNC_PHYSICAL_BOUNDS,
    InvariantViolationError,
    create_frozen_cnc_records,
    register_cnc_into_param_registry,
    validate_no_active_cnc_params,
)


def test_frozen_invariant_protocol_enforcement():
    """Verify that CNC parameters marked active are rejected with InvariantViolationError."""
    # Case 1: Valid fixed bounds
    valid_df = pd.DataFrame([
        {"name": "EM-FL", "status": "active"},
        {"name": "CNC_A", "status": "fixed"},
        {"name": "CNC_B", "status": "fixed"},
    ])
    invariants = validate_no_active_cnc_params(valid_df)
    assert set(invariants) == {"CNC_A", "CNC_B"}

    # Case 2: Illegal active CNC parameter
    illegal_df = pd.DataFrame([
        {"name": "EM-FL", "status": "active"},
        {"name": "CNC_A", "status": "active"},  # FORBIDDEN!
        {"name": "CNC_B", "status": "fixed"},
    ])
    with pytest.raises(InvariantViolationError, match="collinearity"):
        validate_no_active_cnc_params(illegal_df)

    # Case 3: Illegal active asymptotic CNC parameter CNC_NC_INF
    illegal_df3 = pd.DataFrame([
        {"name": "CNC_NC_INF", "status": "active"},  # FORBIDDEN!
    ])
    with pytest.raises(InvariantViolationError, match="collinearity"):
        validate_no_active_cnc_params(illegal_df3)

    # Case 4: Case-insensitive parameter check (lowercase name)
    illegal_df4 = pd.DataFrame([
        {"name": "cnc_nc_inf", "status": "active"},  # Lowercase FORBIDDEN!
    ])
    with pytest.raises(InvariantViolationError, match="collinearity"):
        validate_no_active_cnc_params(illegal_df4)


def test_create_frozen_cnc_records():
    """Verify generated frozen bounds records comply with standard frozen CSV format."""
    records = create_frozen_cnc_records()
    assert len(records) == len(CNC_FROZEN_INVARIANTS)
    for rec in records:
        assert rec["status"] == "fixed"
        assert rec["name"] in CNC_PHYSICAL_BOUNDS
        assert rec["lower"] <= rec["init"] <= rec["upper"]
        assert rec["file"] == "TMGRO048.SPE.base"


def test_runtime_registration_into_param_registry():
    from subprojects.critical_n.calibration.bounds_protocol import (
        unregister_cnc_from_param_registry,
    )
    try:
        success = register_cnc_into_param_registry()
        assert success is True
        from src.common.param_registry import PHYSICAL_BOUNDS
        assert "CNC_A" in PHYSICAL_BOUNDS
        assert PHYSICAL_BOUNDS["CNC_A"] == (2.0, 8.0)
        assert "CNC_B" in PHYSICAL_BOUNDS
        assert "CNC_W0" in PHYSICAL_BOUNDS
    finally:
        unreg_success = unregister_cnc_from_param_registry()
        assert unreg_success is True
        from src.common.param_registry import PHYSICAL_BOUNDS
        assert "CNC_A" not in PHYSICAL_BOUNDS
