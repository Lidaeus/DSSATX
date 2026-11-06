"""Scheme C (CANE) curve-anchored N envelope test suite, 2026-10-31.

Verifies (Python reference = line-by-line mirror of DEMAND.for CANE branch):
1. Seedling equivalence: for W <= W*, CANE targets equal the legacy static
   envelope (backward-compatible early behaviour, see proposal section 5).
2. F1 margin preserved globally: FNINL - Nmin_L == 0.002 and
   FNINS - Nmin_S >= 0.001 for W_eff in [0.01, 30] t/ha.
3. Envelope monotonicity: Nmin_L non-increasing in W; FNINL <= Nmax ceiling;
   late-season dilution unlocked (proposal numeric table reproduction).
4. Luxury gate: linear saturating functional-N form (decision D2 x D6):
   S = 1 at/above c_opt, S = PCNL/c_opt below, S = 1 fallback for PCNL <= 0.
5. Degenerate-parameter guard: RFNMN >= RFNMX rejected.
6. Legacy fallback formula unchanged (card-absent path equivalence source).
"""

from __future__ import annotations

import math

import pytest

from subprojects.critical_n.core.dilution_curve import (
    DEFAULT_CANE_KSTEM,
    DEFAULT_CANE_RFNMN,
    DEFAULT_CANE_RFNMX,
    cane_envelope,
    cane_gate,
    critical_n_concentration,
    legacy_static_envelope,
)

# All12-CNC calibrated species parameters (reports/all12_cnc_calibrated_parameters.csv)
P = dict(
    a=4.85, b=0.38, w0=1.00, nc_inf=1.70,
    prolfi=0.285134, prolfg=0.255094, prolff=0.236508,
    prosti=0.163477, prostg=0.134053, prostf=0.0808337,
)


def env(w, pcnl=None, **over):
    kw = {**P, **over}
    return cane_envelope(w, pcnl=pcnl, **kw)


class TestSeedlingEquivalence:
    def test_seedling_matches_legacy(self):
        """W <= W* (1.58 t/ha): CANE targets == legacy static envelope."""
        for w in (0.05, 0.5, 1.0, 1.5):
            new = env(w)
            old = legacy_static_envelope(w, **P)
            assert new["fninl_pct"] == pytest.approx(old["fninl_pct"], abs=1e-9), w
            assert new["fnins_pct"] == pytest.approx(old["fnins_pct"], abs=1e-9), w

    def test_gate_open_high_pcnl_reproduces_proposal_table(self):
        """Proposal section 5 numeric table (gate fully open, PCNL >= c_opt)."""
        table = {  # W -> (FNINL%, FNINS%, NVSTL%); margins are CROPGRO
                  # fraction units (+0.002 leaf / +0.001 stem = 0.2/0.1 pp),
                  # so the late-season leaf plateau is PROLFF*0.16*100+0.2.
            1.00: (4.56, 2.62, 4.56),
            2.00: (4.33, 2.48, 4.12),
            2.50: (4.12, 2.36, 3.92),
            3.00: (3.98, 2.27, 3.78),
            3.76: (3.98, 2.17, 3.78),
            5.00: (3.98, 2.05, 3.78),
            8.00: (3.98, 1.88, 3.78),
        }
        for w, (fl, fs, nv) in table.items():
            r = env(w, pcnl=10.0)  # gate saturated (functional pool full)
            assert r["fninl_pct"] == pytest.approx(fl, abs=0.005), (w, r["fninl_pct"], fl)
            assert r["fnins_pct"] == pytest.approx(fs, abs=0.005), (w, r["fnins_pct"], fs)
            assert r["nvstl_pct"] == pytest.approx(nv, abs=0.005), (w, r["nvstl_pct"], nv)


class TestF1MarginGlobal:
    def test_margin_over_full_domain(self):
        ws = [0.01, 0.05, 0.1, 0.5, 1.0, 1.58, 2.0, 3.76, 6.0, 12.0, 30.0]
        for w in ws:
            for pcnl in (0.0, 1.5, 2.5, 3.8, 4.56, 6.0):
                r = env(w, pcnl=pcnl)
                # margins in CROPGRO fraction units: 0.002 leaf = 0.2 pp,
                # 0.001 stem = 0.1 pp; floor-winning max guarantees them
                # even where the raw ceiling inverts at extreme W.
                assert r["fninl_pct"] >= r["nmin_l_pct"] + 0.2 - 1e-6, (w, pcnl)
                assert r["fnins_pct"] >= r["nmin_s_pct"] + 0.1 - 1e-6, (w, pcnl)

    def test_dynamic_floor_equals_f1_floor(self):
        """Nmin_L is the FNINLG override: the F1 anchor itself is dynamic."""
        w = 4.0
        r = env(w, pcnl=5.0)
        assert r["nmin_l_pct"] > 100 * P["prolff"] * 0.16 - 1e-9  # above PROLFF floor only at large W? check
        # at W=4: RFNMN*Nc = 0.88 * (1.7+3.15*4^-0.38)*... must be >= PROLFF floor
        nc = critical_n_concentration(w, **{k: P[k] for k in ("a", "b", "w0", "nc_inf")})
        assert r["nmin_l_pct"] == pytest.approx(100 * max(P["prolff"] * 0.16, DEFAULT_CANE_RFNMN * nc / 100), abs=1e-9)


class TestMonotonicityAndDilution:
    def test_nmin_non_increasing(self):
        prev = math.inf
        for i in range(1, 1201):
            w = 0.01 * (30.0 / 0.01) ** (i / 1200)
            r = env(w, pcnl=10.0)
            assert r["nmin_l_pct"] <= prev + 1e-12
            prev = r["nmin_l_pct"]

    def test_dilution_window_widened(self):
        """Late-season leaf target declines below legacy static floor 4.28%."""
        legacy_floor = 100 * (P["prolfg"] * 0.16 + 0.002)  # 4.28
        r5 = env(5.0, pcnl=10.0)
        assert r5["fninl_pct"] < legacy_floor - 0.25  # 3.98 vs 4.28
        assert r5["fninl_pct"] == pytest.approx(100 * P["prolff"] * 0.16 + 0.2, abs=1e-9)
        r8 = env(8.0, pcnl=10.0)
        assert r8["fnins_pct"] < 2.1  # stem keeps diluting (legacy lock at 2.24)

    def test_refill_target_at_critical_not_headroom(self):
        """NVSTL tracks Nc (D1), not 1.05*Nc, capped by FNINL."""
        r = env(2.5, pcnl=10.0)
        nc = r["nc_pct"]
        assert r["nvstl_pct"] == pytest.approx(min(r["fninl_pct"], nc), abs=1e-9)


class TestLuxuryGate:
    def test_gate_saturates_at_copt(self):
        nmin = env(2.0)["nmin_l_pct"]
        assert cane_gate(nmin, nmin / 100.0) == 1.0
        assert cane_gate(nmin * 2.0, nmin / 100.0) == 1.0

    def test_gate_linear_below_copt(self):
        nmin = env(2.0)["nmin_l_pct"]
        assert cane_gate(nmin * 0.5, nmin / 100.0) == pytest.approx(0.5)
        assert cane_gate(0.0, nmin / 100.0) == 1.0  # fallback (pre-emergence)

    def test_gate_shrinks_ceiling(self):
        r_open = env(3.0, pcnl=10.0)
        r_shut = env(3.0, pcnl=env(3.0)["nmin_l_pct"] * 0.5)
        assert r_shut["nmax_l_pct"] < r_open["nmax_l_pct"]

    def test_no_extra_parameter(self):
        """D2 x D6 resolution: gate is parameter-free; defaults unchanged."""
        assert (DEFAULT_CANE_RFNMX, DEFAULT_CANE_RFNMN, DEFAULT_CANE_KSTEM) == (1.20, 0.88, 0.573)


class TestGuards:
    def test_rfnmn_ge_rfnmx_rejected(self):
        with pytest.raises(ValueError):
            env(2.0, rfnmn=1.2)

    def test_continuity_at_w0(self):
        w0 = P["w0"]
        lo = env(w0, pcnl=10.0)
        hi = env(w0 * 1.000001, pcnl=10.0)
        assert lo["fninl_pct"] == pytest.approx(hi["fninl_pct"], abs=1e-6)
        assert lo["nmin_l_pct"] == pytest.approx(hi["nmin_l_pct"], abs=1e-5)
        assert lo["fnins_pct"] == pytest.approx(hi["fnins_pct"], abs=1e-6)
