"""Build a Git snapshot with read-only SLN probes and an isolated N-input cut."""

import argparse
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[3]


def insert(path, anchor, replacement):
    source = path.read_text(encoding="latin-1")
    if source.count(anchor) != 1:
        raise ValueError(f"Probe anchor must occur once in {path}: {anchor.strip()}")
    path.write_text(source.replace(anchor, replacement, 1), encoding="latin-1")


def instrument(source):
    crop = source / "Plant/CROPGRO/CROPGRO.for"
    insert(crop, "      REAL NIV3FLUX(", "      CHARACTER*1 SLNCUT\n      REAL NIV3FLUX(")
    anchor = """        CALL NI_ACCEPT_UPTAKE(UNO3,UNH4,NLAYR,
     &    TRNO3U,TRNH4U,TRNU)"""
    insert(crop, anchor, """!       Research-only 26SP DAP 50-69 pulse. Keep the soil pools and
!       potential RNK fluxes intact, and accept no new N at the boundary.
        CALL GET_ENVIRONMENT_VARIABLE('DSSAT_SLN_PROBE_CUT',SLNCUT)
        IF (SLNCUT.EQ.'1'.AND.YRDOY.GE.2026123.AND.
     &      YRDOY.LT.2026143) THEN
          UNO3=0.
          UNH4=0.
        ENDIF
""" + anchor)
    anchor = "      CALL PODS(INTEGR, \n"
    insert(crop, anchor, """      IF (P0_ENABLED().AND.NI_ENABLED()) THEN
        CALL P0_V(CONTROL,'sln_before_pods',
     &    'PG,MAINR,RSPNO3,RSPNH4,PGAVL,NAVL,NIV3CORE,NDMTOT,'//
     &    'NDMNEW,NDMREP,NASSIMD,pod_score,XFRT',
     &    (/PG,MAINR,RSPNO3,RSPNH4,PGAVL,NAVL,NIV3CORE,NDMTOT,
     &      NDMNEW,NDMREP,NASSIMD,NI_POD_FACTOR(),XFRT/))
      ENDIF
""" + anchor)
    nitrogen = source / "Plant/CROPGRO/CG_Nitrogen.f90"
    insert(nitrogen, "only: P0_V, P0_ENABLED", "only: P0_V, P0_ENABLED, P0_LOCAL")
    anchor = """    if(NI_LEAF_COUPLED())NI_N_SEN_EXTRA=real(min(max(0._dp,real(weight-baseline,dp)), &
      max(0._dp,real(weight,dp))*(1-exp(-n_sen_rate*(1-day_growth)**2))))"""
    insert(nitrogen, anchor, anchor + """
    if(P0_ENABLED()) call P0_LOCAL('sln_n_senescence','extra_DM', [NI_N_SEN_EXTRA])""")
    anchor = "      NI_LEAF_FACTOR=real(NI_V4_PHOTO_KERNEL(10000._dp*functional,photo_sln_ref,photo_floor,photo_gamma))"
    insert(nitrogen, anchor, anchor + """
      if(P0_ENABLED()) call P0_LOCAL('sln_photo','functional_SLN,factor',[real(10000._dp*functional),NI_LEAF_FACTOR])
      if(P0_ENABLED().and.NI_C4_PHOTO())then
        call P0_LOCAL('sln_photo_basis','uncapped_SLN,critical_SLN,whole_LMA,cmin,ccrit', &
          real([10000._dp*whole_slw*max(0._dp,real(rnitp,dp)/100*structural_fraction-cmin(1)), &
                10000._dp*whole_slw*(ccrit(1)-cmin(1)),10000._dp*whole_slw,cmin(1),ccrit(1)]))
      endif""")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ref", default="HEAD")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    source = out / "source"
    source.mkdir()
    revision = subprocess.check_output(["git", "rev-parse", f"{args.ref}^{{commit}}"], cwd=ROOT, text=True).strip()
    (out / "source_revision.txt").write_text(revision + "\n", encoding="ascii")
    archive = out / "source.tar"
    subprocess.run(["git", "archive", "-o", str(archive), revision], cwd=ROOT, check=True)
    with tarfile.open(archive) as tree:
        tree.extractall(source, filter="data")
    archive.unlink()
    instrument(source)
    build = out / "engine"
    with (out / "build.log").open("w") as log:
        for command in (
            ["cmake", "-S", str(source), "-B", str(build), "-G", "Ninja",
             "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_Fortran_COMPILER=gfortran", "-DCMAKE_POLICY_VERSION_MINIMUM=3.5"],
            ["cmake", "--build", str(build), "--parallel", "8"],
        ):
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    print(build / "bin/dscsm048")


if __name__ == "__main__":
    main()
