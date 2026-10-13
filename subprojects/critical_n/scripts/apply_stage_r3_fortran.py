"""Script to apply Stage R3 modifications to CROPGRO, PODS, and FreshWt Fortran sources."""

from pathlib import Path
import re
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from subprojects.critical_n.scheme_b.patch_manager import (
    validate_fortran_fixed_format,
    generate_unified_patch,
)

SRC_SCHEME_B_DIR = PROJECT_ROOT / "subprojects" / "critical_n" / "fortran_patch" / "src_scheme_b"
PATCH_DIR = PROJECT_ROOT / "subprojects" / "critical_n" / "fortran_patch" / "patches"
UPSTREAM_CROPGRO_DIR = PROJECT_ROOT / "workspace" / "diagnostics" / "dssat-csm-os-v4.8.2-source" / "Plant" / "CROPGRO"


def update_cropgro():
    cg_path = SRC_SCHEME_B_DIR / "CROPGRO_CNC.FOR"
    text = cg_path.read_text(encoding="latin-1")

    # 1. Declarations
    decl_target = (
        "!     Phase R2: Cumulative harvest pod dry weight & effective biomass\n"
        "      REAL CUM_HPODWT, WEFF\n"
    )
    decl_repl = (
        "!     Phase R2: Cumulative harvest pod dry weight & effective biomass\n"
        "      REAL CUM_HPODWT, WEFF\n"
        "!     Phase R3: Cumulative harvested fruit total nitrogen & pod N\n"
        "      REAL CHPDTN, HPODN, FNINL0\n"
    )
    assert decl_target in text, "Could not find decl_target in CROPGRO_CNC.FOR"
    text = text.replace(decl_target, decl_repl, 1)

    # 2. RUNINIT setting FNINL0
    runinit_target = (
        "      IF (PROLFG .LE. 0.0) THEN\n"
        "        IF (PROLFI .GT. 0.0) THEN\n"
        "          PROLFG = PROLFI * 0.815\n"
        "        ELSE\n"
        "          PROLFG = 0.220\n"
        "        ENDIF\n"
        "      ENDIF\n"
    )
    runinit_repl = (
        "      IF (PROLFG .LE. 0.0) THEN\n"
        "        IF (PROLFI .GT. 0.0) THEN\n"
        "          PROLFG = PROLFI * 0.815\n"
        "        ELSE\n"
        "          PROLFG = 0.220\n"
        "        ENDIF\n"
        "      ENDIF\n"
        "      FNINL0 = PROLFI * 0.16\n"
    )
    assert runinit_target in text, "Could not find runinit_target in CROPGRO_CNC.FOR"
    text = text.replace(runinit_target, runinit_repl, 1)

    # 3. SEASINIT resetting CHPDTN
    seasinit_target = (
        "      CUM_HPODWT = 0.0\n"
        "      WEFF = 0.0\n"
    )
    seasinit_repl = (
        "      CUM_HPODWT = 0.0\n"
        "      CHPDTN = 0.0\n"
        "      HPODN = 0.0\n"
        "      WEFF = 0.0\n"
    )
    assert seasinit_target in text, "Could not find seasinit_target in CROPGRO_CNC.FOR"
    text = text.replace(seasinit_target, seasinit_repl, 1)

    # 4. In all 5 CALL PODS: change FNINL -> FNINL0, and add CHPDTN
    # Target pattern in PODS call:
    #      FILEGC,FILEIO, FNINL, FNINSD, FNINSH, GDMSD,    !Input
    # ...
    #      PStres2, YRPLT,                                 !Input
    old_input1 = "     &    FILEGC,FILEIO, FNINL, FNINSD, FNINSH, GDMSD,    !Input\n"
    new_input1 = "     &    FILEGC,FILEIO, FNINL0, FNINSD, FNINSH, GDMSD,   !Input\n"
    assert text.count(old_input1) == 5, f"Expected 5 occurrences of old_input1, found {text.count(old_input1)}"
    text = text.replace(old_input1, new_input1)

    old_input2 = "     &    PStres2, YRPLT,                                 !Input\n"
    new_input2 = "     &    PStres2, YRPLT, CHPDTN,                         !Input\n"
    assert text.count(old_input2) == 5, f"Expected 5 occurrences of old_input2, found {text.count(old_input2)}"
    text = text.replace(old_input2, new_input2)

    # 5. After CALL GROW: accumulate CHPDTN
    grow_target = (
        "C     Phase R2: Accumulate harvested pod weight\n"
        "      CUM_HPODWT = CUM_HPODWT + HPODWT\n"
    )
    grow_repl = (
        "C     Phase R2: Accumulate harvested pod weight\n"
        "      CUM_HPODWT = CUM_HPODWT + HPODWT\n"
        "C     Phase R3: Explicit tracking of cumulative harvested fruit total N\n"
        "      IF (HPODWT .GT. 0.0) THEN\n"
        "        HPODN = HSDWT * (PCNSD / 100.0) + HSHELWT * (PCNSH / 100.0)\n"
        "        CHPDTN = CHPDTN + HPODN * 10.0\n"
        "      ENDIF\n"
    )
    assert grow_target in text, "Could not find grow_target in CROPGRO_CNC.FOR"
    text = text.replace(grow_target, grow_repl, 1)

    cg_path.write_text(text, encoding="latin-1")
    v = validate_fortran_fixed_format(cg_path)
    if v:
        raise ValueError(f"Violations in CROPGRO_CNC.FOR: {v}")
    print("[+] CROPGRO_CNC.FOR updated successfully (0 violations).")

    # Generate patch
    orig_cg = (UPSTREAM_CROPGRO_DIR / "CROPGRO.for").read_text(encoding="latin-1")
    patch = generate_unified_patch(orig_cg, text, "Plant/CROPGRO/CROPGRO.for", "Plant/CROPGRO/CROPGRO.for")
    (PATCH_DIR / "CROPGRO.for.patch").write_text(patch, encoding="utf-8")
    print("[+] CROPGRO.for.patch regenerated successfully.")


def create_pods():
    orig_path = UPSTREAM_CROPGRO_DIR / "PODS.for"
    text = orig_path.read_text(encoding="latin-1")

    # 1. Update SUBROUTINE signature to accept CHPDTN
    sig_old = "     &    PStres2, YRPLT,                                 !Input\n"
    sig_new = "     &    PStres2, YRPLT, CHPDTN,                         !Input\n"
    assert sig_old in text, "Could not find sig_old in PODS.for"
    text = text.replace(sig_old, sig_new, 1)

    # 2. Add REAL CHPDTN declaration
    decl_old = "      REAL HPODWT,HSDWT,HSHELWT\n"
    decl_new = "      REAL HPODWT,HSDWT,HSHELWT,CHPDTN\n"
    assert decl_old in text, "Could not find decl_old in PODS.for"
    text = text.replace(decl_old, decl_new, 1)

    # 3. Add CHPDTN to 4 CALL FRESHWT invocations
    fwt_old = "     &        HPODWT,HSDWT,HSHELWT)                             !Output\n"
    fwt_new = "     &        HPODWT,HSDWT,HSHELWT,CHPDTN)                      !Output\n"
    assert text.count(fwt_old) == 4, f"Expected 4 occurrences of fwt_old in PODS.for, found {text.count(fwt_old)}"
    text = text.replace(fwt_old, fwt_new)

    # 4. Protect line 747 with singularity guard & non-negative denominator
    padd_old = "          RNITPD = (RNITP*0.01-PROLFF*0.16)/(FNINL-PROLFF*0.16)\n"
    padd_new = (
        "C       Phase R3: Singularity guard & protected pod addition scaling\n"
        "          IF (FNINL - PROLFF * 0.16 .GT. 0.001) THEN\n"
        "            RNITPD = (RNITP*0.01-PROLFF*0.16)/(FNINL-PROLFF*0.16)\n"
        "          ELSE\n"
        "            RNITPD = 1.0\n"
        "          ENDIF\n"
    )
    assert padd_old in text, "Could not find padd_old in PODS.for"
    text = text.replace(padd_old, padd_new, 1)

    pods_out = SRC_SCHEME_B_DIR / "PODS_CNC.FOR"
    pods_out.write_text(text, encoding="latin-1")
    v = validate_fortran_fixed_format(pods_out)
    if v:
        raise ValueError(f"Violations in PODS_CNC.FOR: {v}")
    print("[+] PODS_CNC.FOR created successfully (0 violations).")

    # Generate patch
    patch = generate_unified_patch(orig_path.read_text(encoding="latin-1"), text, "Plant/CROPGRO/PODS.for", "Plant/CROPGRO/PODS.for")
    (PATCH_DIR / "PODS.for.patch").write_text(patch, encoding="utf-8")
    print("[+] PODS.for.patch generated successfully.")


def create_freshwt():
    orig_path = UPSTREAM_CROPGRO_DIR / "FreshWt.for"
    text = orig_path.read_text(encoding="latin-1")

    # 1. Update SUBROUTINE signature to accept CHPDTN
    sig_old = "     &        HPODWT,HSDWT,HSHELWT)                             !Output\n"
    sig_new = "     &        HPODWT,HSDWT,HSHELWT,CHPDTN)                      !Output\n"
    assert sig_old in text, "Could not find sig_old in FreshWt.for"
    text = text.replace(sig_old, sig_new, 1)

    # 2. Add CHPDTN to declarations
    decl_old = "      REAL :: RTFPW,HPODWT,HSDWT,HSHELWT,HFPOW\n"
    decl_new = "      REAL :: RTFPW,HPODWT,HSDWT,HSHELWT,HFPOW,CHPDTN\n"
    assert decl_old in text, "Could not find decl_old in FreshWt.for"
    text = text.replace(decl_old, decl_new, 1)

    # 3. Add CHPDTN description
    desc_old = "     &    '!CHNUM  Cum. harvest number (#)'\n"
    desc_new = (
        "     &    '!CHNUM  Cum. harvest number (#)',\n"
        "     &    '!CHPDTN Cum. har. pod total N of mat. fruits (kg[N]/ha)'\n"
    )
    assert desc_old in text, "Could not find desc_old in FreshWt.for"
    text = text.replace(desc_old, desc_new, 1)

    # 4. Formats 230 and 231
    fmt230_old = "     &    '   TOSDN   TOWSD   MTDSD   HSDWT')\n"
    fmt230_new = "     &    '   TOSDN   TOWSD   MTDSD   HSDWT  CHPDTN')\n"
    assert text.count(fmt230_old) == 2, f"Expected 2 occurrences of fmt230_old, found {text.count(fmt230_old)}"
    text = text.replace(fmt230_old, fmt230_new)

    # 5. WRITE statements in SELECT CASE (CROP)
    write_old = "     &      TOSDN,TOWSD*10.,MTDSD*10.,HSDWT*10.\n"
    write_new = "     &      TOSDN,TOWSD*10.,MTDSD*10.,HSDWT*10., CHPDTN\n"
    assert text.count(write_old) == 6, f"Expected 6 occurrences of write_old, found {text.count(write_old)}"
    text = text.replace(write_old, write_new)

    # 6. Output formats 1000 and 2000
    fmt_old = "     &    4(F8.1))\n"
    fmt_new = "     &    4(F8.1),F8.2)\n"
    assert text.count(fmt_old) == 2, f"Expected 2 occurrences of fmt_old, found {text.count(fmt_old)}"
    text = text.replace(fmt_old, fmt_new)

    fwt_out = SRC_SCHEME_B_DIR / "FreshWt_CNC.FOR"
    fwt_out.write_text(text, encoding="latin-1")
    v = validate_fortran_fixed_format(fwt_out)
    if v:
        raise ValueError(f"Violations in FreshWt_CNC.FOR: {v}")
    print("[+] FreshWt_CNC.FOR created successfully (0 violations).")

    # Generate patch
    patch = generate_unified_patch(orig_path.read_text(encoding="latin-1"), text, "Plant/CROPGRO/FreshWt.for", "Plant/CROPGRO/FreshWt.for")
    (PATCH_DIR / "FreshWt.for.patch").write_text(patch, encoding="utf-8")
    print("[+] FreshWt.for.patch generated successfully.")


if __name__ == "__main__":
    update_cropgro()
    create_pods()
    create_freshwt()
    print("[*] Stage R3 Fortran modifications and patches successfully generated!")
