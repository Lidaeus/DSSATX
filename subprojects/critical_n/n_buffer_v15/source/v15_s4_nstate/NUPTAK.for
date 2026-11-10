C=======================================================================
C  NUPTAK, Subroutine  --  v15_s3_v4root variant
C  Determines N uptake (adapted from CERES)
C
C  Variant delta vs frozen v15_s1_interface (S1):
C    * Optional RootUptake.nml in the run directory selects the root
C      kernel: root_kernel=1 (default, file absent) reproduces the S1
C      dual-channel additive kinetics byte-for-byte; root_kernel=2
C      activates the v4-R2 simultaneous root uptake kernel ported from
C      dssat_csm_os_4864 Plant/CROPGRO/CG_Nitrogen.f90 NI_ROOT_KERNEL
C      (mode 2, lines 1769-1850): membrane Michaelis-Menten evaluated at
C      the root-surface concentration solved jointly with
C      (mass flow + effective diffusion) supply by 64 bisection steps.
C      Total uptake is the membrane flux at the depleted concentration,
C      NOT mass flow + active uptake added together.
C    * Whole-plant down-regulation in kernel 2 keys on the existing S1
C      signal: feedback = nb_feedback_response(psi, alpha_H) multiplies
C      root_v via poolfactor = feedback * sqrt(wet) (same topology as
C      v4 pool_beta / QH1 fQ pool-filling feedback). PHI_EFFLUX and the
C      dual-affinity split are not applied in kernel 2 (ablation delta).
C    * NH4 in kernel 2 uses the native rate/saturation form
C      0.1*Lroot*sqrt(wet)*(1-exp(-0.08*NH4))*RTNH4 without the shared
C      ANDEM scaling and the 0.04 low-concentration cutoff (v4 form).
C    * Kernel 2 writes RootKernelLedger.csv (per layer per day) with the
C      kernel internals (c, rwu, wet, poolfactor, mf, mem(cr), cr,
C      diffusion, uptake).
C  Stock caps (0.25 / 0.50 ug/g), the D_max accounting ceiling and the
C  nb_settle_root acceptance/refund chain are unchanged for both kernels.
C-----------------------------------------------------------------------
C  Revision history
C  09/01/1989 JWJ,GH Written
C  03/01/1993 WTB Modified.
C  01/20/1997 GH  Modified.
C  07/10/1998 CHP modified for modular format.
C  05/11/1998 GH  Incorporated in CROPGRO
C  2026-11-07     v15_s3_v4root variant (see header above)
C-----------------------------------------------------------------------
C  Called from:  PLANT
C  Calls:        ERROR, FIND, IGNORE
C=======================================================================

      SUBROUTINE NUPTAK(DYNAMIC,
     &  DLAYR, DUL, FILECC, KG2PPM, LL, NDMSDR, NDMTOT,   !Input
     &  NH4, NO3, NLAYR, RLV, SAT, SW,                    !Input
     &  TRNH4U, TRNO3U, TRNU, UNH4, UNO3)                 !Output

!-----------------------------------------------------------------------
      USE ModuleDefs
      USE ModuleData
      USE N_BUFFER_MOD, ONLY: NBUF_ACT,nb_root_capture,
     & nb_soil_response,nb_uptake_mode,nb_get_psi,
     & nb_get_dmax,nb_efflux_barrier,nb_sigma_no3,nb_sigma_nh4,
     & nb_get_alpha_h,nb_get_alpha_l,nb_feedback_response,
     & nb_get_uptake_psi
      IMPLICIT NONE
      EXTERNAL GETLUN, FIND, ERROR, IGNORE
      SAVE

      CHARACTER*6 ERRKEY
      PARAMETER (ERRKEY = 'NUPTAK')
      CHARACTER*6 SECTION
      CHARACTER*80 CHAR
      CHARACTER*92 FILECC

      INTEGER I, LUNCRP, ERR, LNUM, ISECT, FOUND
      INTEGER L, NLAYR, DYNAMIC

      REAL NUF, XMIN
      REAL DLAYR(NL), LL(NL), DUL(NL), SAT(NL), SW(NL), RLV(NL)
      REAL SNO3(NL), SNH4(NL), KG2PPM(NL), NO3(NL), NH4(NL)
      REAL RNO3U(NL), RNH4U(NL), UNO3(NL), UNH4(NL)
      REAL TRNO3U, TRNH4U, TRNU
      REAL NDMTOT, NDMSDR, ANDEM, FNH4, FNO3, SMDFR, RFAC
      REAL RTNO3, RTNH4, MXNH4U, MXNO3U
      REAL RWU(NL), EP_SPAM, SUM_RWU, SUM_RLV
      REAL C_NO3(NL), C_NH4(NL)
      REAL U_PASS_NO3(NL), U_PASS_NH4(NL)
      REAL U_ACT_NO3(NL), U_ACT_NH4(NL)
      REAL F_DIFF, F_T, F_FB_H, F_FB_L, PHI_EFFLUX, PSI_N
      REAL HATS_NO3, LATS_NO3, HATS_NH4, LATS_NH4
      REAL UPTAKE_CEILING, WREL
      REAL SCALE_NO3, SCALE_NH4
      REAL, PARAMETER :: V_MAX_H = 0.003
      REAL, PARAMETER :: K_M_H   = 0.28
      REAL, PARAMETER :: V_MAX_L = 0.015
      REAL, PARAMETER :: K_M_L   = 35.0
      REAL, PARAMETER :: ALPHA_H = 3.0
      REAL, PARAMETER :: ALPHA_L = 1.5

C     --- v15_s3_v4root additions -------------------------------------
      INTEGER ROOT_KERNEL
      REAL ROOT_V, ROOT_K, DIFFUSION_K
      INTEGER LUNNML, LUNRK, IBI, LEDGER_DAY, LNM
      LOGICAL NML_EXISTS, LEDGER_OPENED
      REAL CBULK, MF_G, CAP_G, MEM_C, MEM_CR, DIFF_G, SUPPLY
      REAL LO_C, HI_C, MID_C
      REAL WET_F, POOLF, LENGTH_M, UPT_G, NH4_G
      REAL F_FB_ROOT
      CHARACTER*512 NMLPATH, NMLFILE
      NAMELIST /ROOTUPTAKE/ ROOT_KERNEL, ROOT_V, ROOT_K,
     &  DIFFUSION_K

!***********************************************************************
!***********************************************************************
!     Run Initialization - Called once per simulation
!***********************************************************************
      IF (DYNAMIC .EQ. RUNINIT) THEN
!-----------------------------------------------------------------------
!     ***** READ ROOT GROWTH PARAMETERS *****************
!-----------------------------------------------------------------------
!     Read in values from input file, which were previously input
!       in Subroutine IPCROP.
!-----------------------------------------------------------------------
      CALL GETLUN('FILEC', LUNCRP)
      OPEN (LUNCRP,FILE = FILECC, STATUS = 'OLD',IOSTAT=ERR)
      IF (ERR .NE. 0) CALL ERROR(ERRKEY,ERR,FILECC,0)

!-----------------------------------------------------------------------
!    Find and Read Photosynthesis Section
!-----------------------------------------------------------------------
!     Subroutine FIND finds appropriate SECTION in a file by
!       searching for the specified 6-character string at beginning
!       of each line.
!-----------------------------------------------------------------------
      SECTION = '!*ROOT'
      CALL FIND(LUNCRP, SECTION, LNUM, FOUND)
      IF (FOUND .EQ. 0) THEN
        CALL ERROR(SECTION, 42, FILECC, LNUM)
      ELSE
        DO I = 1, 3
          CALL IGNORE(LUNCRP,LNUM,ISECT,CHAR)
          IF (ISECT .EQ. 0) CALL ERROR(ERRKEY,ERR,FILECC,LNUM)
        ENDDO
        READ(CHAR,'(2F6.0)',IOSTAT=ERR) RTNO3, RTNH4
        IF (ERR .NE. 0) CALL ERROR(ERRKEY,ERR,FILECC,LNUM)
      ENDIF

      CLOSE (LUNCRP)

!-----------------------------------------------------------------------
!     v15_s3_v4root: optional RootUptake.nml selects the root kernel.
!     Absent file => root_kernel=1 (frozen S1 dual-channel behavior).
!     Engineering defaults follow 4864 research/n_integration_v2
!     stage5_engineering.nml (UNCALIBRATED, not part of PEST domain).
!-----------------------------------------------------------------------
      ROOT_KERNEL = 1
      ROOT_V    = 0.0002
      ROOT_K    = 10.0
      DIFFUSION_K = 0.005
      LEDGER_DAY   = 0
      LEDGER_OPENED = .FALSE.
C     Locate RootUptake.nml: run directory first, then the path given
C     by DSSAT_ROOT_UPTAKE_NML (calibration sandboxes rely on the env).
      NMLPATH = 'RootUptake.nml'
      INQUIRE(FILE=NMLPATH, EXIST=NML_EXISTS)
      IF (.NOT. NML_EXISTS) THEN
        NMLFILE = ' '
        CALL GET_ENVIRONMENT_VARIABLE('DSSAT_ROOT_UPTAKE_NML', NMLFILE)
        LNM = LEN_TRIM(NMLFILE)
        IF (LNM .GT. 0) THEN
          INQUIRE(FILE=NMLFILE(1:LNM), EXIST=NML_EXISTS)
          IF (NML_EXISTS) NMLPATH = NMLFILE(1:LNM)
        ENDIF
      ENDIF
      IF (NML_EXISTS) THEN
        CALL GETLUN('NMLRT', LUNNML)
        OPEN(LUNNML, FILE=NMLPATH, STATUS='OLD', IOSTAT=ERR)
        IF (ERR .NE. 0) CALL ERROR(ERRKEY,ERR,NMLPATH,0)
        READ(LUNNML, NML=ROOTUPTAKE, IOSTAT=ERR)
        IF (ERR .NE. 0) CALL ERROR(ERRKEY,ERR,NMLPATH,0)
        CLOSE(LUNNML)
        IF (ROOT_KERNEL .LT. 1 .OR. ROOT_KERNEL .GT. 2) THEN
          PRINT *, 'RootUptake.nml: root_kernel must be 1 or 2'
          STOP 'NUPTAK: invalid root_kernel'
        ENDIF
        IF (ROOT_KERNEL .EQ. 2) THEN
          IF (ROOT_V .LE. 0.0 .OR. ROOT_K .LE. 0.0 .OR.
     &        DIFFUSION_K .LE. 0.0) THEN
            PRINT *, 'RootUptake.nml: root_kernel=2 requires ',
     &               'root_v>0, root_k>0, diffusion_k>0'
            STOP 'NUPTAK: invalid v4-R2 kernel parameters'
          ENDIF
        ENDIF
      ENDIF
      IF (ROOT_KERNEL .EQ. 2 .AND. .NOT. LEDGER_OPENED) THEN
        CALL GETLUN('RKLG', LUNRK)
        OPEN(LUNRK, FILE='RootKernelLedger.csv', STATUS='REPLACE')
        WRITE(LUNRK,'(A)') 'day_index,layer,c_mgN_L,rwu_cm_d,'//
     &    'rootlength_m_m2,wet,poolfactor,mf_g_m2_d,'//
     &    'mem_at_cr_g_m2_d,cr_mgN_L,diffusion_g_m2_d,'//
     &    'uptake_g_m2_d,nh4_g_m2_d,mode'
        CLOSE(LUNRK)
        LEDGER_OPENED = .TRUE.
      ENDIF

!***********************************************************************
!***********************************************************************
!     Seasonal initialization - run once per season
!***********************************************************************
      ELSEIF (DYNAMIC .EQ. SEASINIT) THEN
!-----------------------------------------------------------------------
      TRNO3U = 0.0
      TRNH4U = 0.0
      TRNU   = 0.0
      UNH4   = 0.0
      UNO3   = 0.0
      LEDGER_DAY = 0

!***********************************************************************
!***********************************************************************
!     DAILY RATE/INTEGRATION
!***********************************************************************
      ELSEIF (DYNAMIC .EQ. INTEGR) THEN
!-----------------------------------------------------------------------
C   Initialize variables
C-----------------------------------------------------------------------
      TRNU   = 0.0
      TRNO3U = 0.0
      TRNH4U = 0.0
      NUF    = 0.0
      XMIN   = 0.0
      DO L=1,NLAYR
        RNO3U(L) = 0.0
        RNH4U(L) = 0.0
        UNH4(L)  = 0.0
        UNO3(L)  = 0.0
        !KG2PPM(L) = 10. / (BD(L) * DLAYR(L))
        SNO3(L) = NO3(L) / KG2PPM(L)
        SNH4(L) = NH4(L) / KG2PPM(L)
      ENDDO
C-----------------------------------------------------------------------
C   Branch by NBUF_ACT: Legacy DSSAT when <= 0.5, Kinetics when > 0.5
C-----------------------------------------------------------------------
      IF (NBUF_ACT .LE. 0.5) THEN
C-----------------------------------------------------------------------
C   Legacy DSSAT CROPGRO NUPTAK Logic (G00 Baseline Preservation)
C-----------------------------------------------------------------------
        ANDEM = (NDMTOT - NDMSDR) * 10.0
        IF (ANDEM .GT. 1.E-9) THEN
          DO L=1,NLAYR
            IF (RLV(L) .GT. 1.E-6) THEN
              FNH4 = 1.0 - EXP(-0.08 * NH4(L))
              FNO3 = 1.0 - EXP(-0.08 * NO3(L))
              IF (FNO3 .LT. 0.04) FNO3 = 0.0
              IF (FNO3 .GT. 1.0)  FNO3 = 1.0
              IF (FNH4 .LT. 0.04) FNH4 = 0.0
              IF (FNH4 .GT. 1.0)  FNH4 = 1.0

              SMDFR = (SW(L) - LL(L)) / (DUL(L) - LL(L))
              IF (SW(L) .GT. DUL(L)) THEN
                SMDFR = 1.0 - (SW(L) - DUL(L)) / (SAT(L) - DUL(L))
              ENDIF
              IF (SMDFR .LT. 0.1) THEN
                SMDFR = 0.1
              ENDIF
              RFAC = RLV(L) * SQRT(SMDFR) * DLAYR(L) * 100.0
              RNO3U(L) = RFAC * FNO3 * RTNO3
              RNH4U(L) = RFAC * FNH4 * RTNH4
              RNO3U(L) = MAX(0.0,RNO3U(L))
              RNH4U(L) = MAX(0.0,RNH4U(L))
              TRNU = TRNU + RNO3U(L) + RNH4U(L) !kg[N]/ha
            ENDIF
          ENDDO

          IF (ANDEM .GT. TRNU) THEN
            ANDEM = TRNU
          ENDIF
          IF (TRNU .GT. 0.0) THEN
            NUF = ANDEM / TRNU
            DO L=1,NLAYR
              IF (RLV(L) .GT. 0.0) THEN
                UNO3(L) = RNO3U(L) * NUF
                UNH4(L) = RNH4U(L) * NUF
                XMIN    = 0.25 / KG2PPM(L)
                MXNO3U  = MAX(0.0,(SNO3(L) - XMIN))
                IF (UNO3(L) .GT. MXNO3U) THEN
                  UNO3(L) = MXNO3U
                ENDIF
                XMIN = 0.5 / KG2PPM(L)
                MXNH4U  = MAX(0.0,(SNH4(L) - XMIN))
                IF (UNH4(L) .GT. MXNH4U) UNH4(L) = MXNH4U
                TRNO3U  = TRNO3U + UNO3(L)
                TRNH4U  = TRNH4U + UNH4(L)
              ENDIF
            ENDDO
            TRNO3U = TRNO3U / 10.0
            TRNH4U = TRNH4U / 10.0
            TRNU   = TRNO3U + TRNH4U
          ENDIF
        ENDIF
      ELSE
C-----------------------------------------------------------------------
C   Milestone 2: Root N Uptake Kinetics (U_pass + U_act + D_max Ceiling)
C-----------------------------------------------------------------------
        ANDEM = (NDMTOT - NDMSDR) * 10.0

C       1. Zero-Signature RWU retrieval from ModuleData with Ep fallback
        RWU = 0.0
        CALL GET('SPAM', 'UH2O', RWU)
        SUM_RWU = 0.0
        DO L = 1, NLAYR
          SUM_RWU = SUM_RWU + RWU(L)
        ENDDO
        IF (SUM_RWU .LE. 1.E-6) THEN
          EP_SPAM = 0.0
          CALL GET('SPAM', 'EP', EP_SPAM)
          IF (EP_SPAM .GT. 1.E-6) THEN
            SUM_RLV = 0.0
            DO L = 1, NLAYR
              SUM_RLV = SUM_RLV + RLV(L)
            ENDDO
            IF (SUM_RLV .GT. 1.E-6) THEN
              DO L = 1, NLAYR
                RWU(L) = (RLV(L) / SUM_RLV) * (EP_SPAM / 10.0)
              ENDDO
            ENDIF
          ENDIF
        ENDIF

C       2. Soil pore solution concentrations (mg N / L)
        DO L = 1, NLAYR
          IF (SW(L) .GT. 1.E-6 .AND. DLAYR(L) .GT. 1.E-6) THEN
            C_NO3(L) = (10.0 * SNO3(L)) / (DLAYR(L) * SW(L))
            C_NH4(L) = (10.0 * SNH4(L)) / (DLAYR(L) * SW(L))
          ELSE
            C_NO3(L) = 0.0
            C_NH4(L) = 0.0
          ENDIF
          C_NO3(L) = MAX(0.0, C_NO3(L))
          C_NH4(L) = MAX(0.0, C_NH4(L))
        ENDDO

C       3. Whole-plant feedback down-regulation and high-N efflux barrier
        PSI_N = nb_get_uptake_psi()
        PSI_N = MAX(-1.0, MIN(1.0, PSI_N))
        PHI_EFFLUX = nb_efflux_barrier(PSI_N)
        PHI_EFFLUX = MAX(0.0, MIN(1.0, PHI_EFFLUX))

        IF (PSI_N .LE. 0.0) THEN
          F_FB_H = 1.0
          F_FB_L = 1.0
        ELSE
          F_FB_H = nb_feedback_response(PSI_N, nb_get_alpha_h())
          F_FB_L = nb_feedback_response(PSI_N, nb_get_alpha_l())
        ENDIF

        IF (ROOT_KERNEL .EQ. 2) THEN
C-----------------------------------------------------------------------
C   v4-R2 kernel (v15_s3_v4root): membrane MM at the root-surface
C   concentration solved jointly with (mass flow + diffusion) supply.
C   Ported from CG_Nitrogen.f90 NI_ROOT_KERNEL mode 2 (1769-1798) and
C   NI_ROOT_UPTAKE (1799-1850); feedback keys on the S1 psi signal and
C   multiplies root_v through poolfactor = feedback*sqrt(wet).
C-----------------------------------------------------------------------
          LEDGER_DAY = LEDGER_DAY + 1
          F_FB_ROOT = 1.0
          IF (PSI_N .GT. 0.0) THEN
            F_FB_ROOT = nb_feedback_response(PSI_N, nb_get_alpha_h())
          ENDIF
          DO L = 1, NLAYR
            RNO3U(L) = 0.0
            RNH4U(L) = 0.0
            MF_G  = 0.0
            CAP_G = 0.0
            MEM_CR = 0.0
            UPT_G  = 0.0
            DIFF_G = 0.0
            NH4_G  = 0.0
            IF (RLV(L) .GT. 1.E-6) THEN
              WET_F = 0.0
              IF (SW(L) .GT. LL(L) .AND. SW(L) .LE. DUL(L)) THEN
                WET_F = (SW(L) - LL(L)) / MAX(1.E-12, DUL(L)-LL(L))
              ELSEIF (SW(L) .GT. DUL(L)) THEN
                WET_F = (SAT(L) - SW(L)) / MAX(1.E-12, SAT(L)-DUL(L))
              ENDIF
              WET_F = MAX(0.0, MIN(1.0, WET_F))
              LENGTH_M = 100.0 * RLV(L) * DLAYR(L)
              POOLF = F_FB_ROOT * SQRT(WET_F)
              CBULK = C_NO3(L)
              MF_G = 0.01 * MAX(0.0, RWU(L)) * CBULK
              IF (CBULK .GT. 0.0 .AND. POOLF .GT. 0.0) THEN
                CAP_G = LENGTH_M * ROOT_V * POOLF
                MEM_C = CAP_G * CBULK / (ROOT_K + CBULK)
                IF (MEM_C .LE. MF_G) THEN
                  UPT_G  = MEM_C
                  MEM_CR = CBULK
                ELSE
                  LO_C = 0.0
                  HI_C = CBULK
                  DO IBI = 1, 64
                    MID_C = (LO_C + HI_C) * 0.5
                    MEM_CR = CAP_G * MID_C / (ROOT_K + MID_C)
                    SUPPLY = MF_G + 0.001 * DIFFUSION_K * WET_F *
     &                       LENGTH_M * (CBULK - MID_C)
                    IF (MEM_CR .GT. SUPPLY) THEN
                      HI_C = MID_C
                    ELSE
                      LO_C = MID_C
                    ENDIF
                  ENDDO
                  MEM_CR = (LO_C + HI_C) * 0.5
                  UPT_G  = CAP_G * MEM_CR / (ROOT_K + MEM_CR)
                ENDIF
                DIFF_G = 0.001 * DIFFUSION_K * WET_F * LENGTH_M *
     &                   MAX(0.0, CBULK - MEM_CR)
              ENDIF
C             NO3: membrane flux at cr, capped by extractable stock
              RNO3U(L) = MIN(10.0 * UPT_G,
     &             MAX(0.0, SNO3(L) - 0.25/KG2PPM(L)))
C             NH4: native rate/saturation form (v4), no ANDEM scaling
              NH4_G = 0.1 * LENGTH_M * SQRT(WET_F) *
     &                (1.0 - EXP(-0.08 * NH4(L))) * RTNH4
              RNH4U(L) = MIN(10.0 * NH4_G,
     &             MAX(0.0, SNH4(L) - 0.50/KG2PPM(L)))
              TRNU = TRNU + RNO3U(L) + RNH4U(L)
C             kernel internals ledger
              IF (LEDGER_OPENED) THEN
                CALL GETLUN('RKLG', LUNRK)
                OPEN(LUNRK, FILE='RootKernelLedger.csv',
     &               STATUS='UNKNOWN', POSITION='APPEND')
                WRITE(LUNRK,
     &            '(I0,",",I0,11(",",ES14.6),",",I1)')
     &            LEDGER_DAY, L, CBULK, MAX(0.0,RWU(L)), LENGTH_M,
     &            WET_F, POOLF, MF_G, UPT_G, MEM_CR, DIFF_G, UPT_G,
     &            NH4_G, 2
                CLOSE(LUNRK)
              ENDIF
            ENDIF
          ENDDO
        ELSE
C-----------------------------------------------------------------------
C   S1 dual-channel kernel (frozen v15_s1_interface behavior)
C-----------------------------------------------------------------------
          DO L = 1, NLAYR
            IF (RLV(L) .GT. 1.E-6) THEN
              IF (SW(L) .LE. LL(L)) THEN
                F_DIFF = 0.0
              ELSEIF (SW(L) .LE. DUL(L)) THEN
                WREL = (SW(L) - LL(L)) / MAX(1.E-6, DUL(L) - LL(L))
                F_DIFF = WREL ** 1.8
              ELSE
                F_DIFF = MAX(0.0, 1.0 - (SW(L) - DUL(L)) /
     &                 MAX(1.E-6, SAT(L) - DUL(L)))
              ENDIF
              F_DIFF = MAX(0.0, MIN(1.0, F_DIFF))
              F_T = 1.0

              ! Passive mass flow U_pass (kg N/ha/d)
              U_PASS_NO3(L) = 0.1 * RWU(L) * real(nb_sigma_no3) *
     &                      C_NO3(L) * PHI_EFFLUX
              U_PASS_NH4(L) = 0.1 * RWU(L) * real(nb_sigma_nh4) *
     &                      C_NH4(L) * PHI_EFFLUX

              ! Dual-affinity active kinetics U_act (kg N/ha/d)
              SCALE_NO3 = 1.0
              IF (RTNO3 .GT. 1.E-6) SCALE_NO3 = RTNO3 / 0.00721
              SCALE_NH4 = 1.0
              IF (RTNH4 .GT. 1.E-6) SCALE_NH4 = RTNH4 / 0.01212

              HATS_NO3 = F_FB_H * (V_MAX_H * SCALE_NO3 * C_NO3(L)) /
     &                 (K_M_H + C_NO3(L))
              LATS_NO3 = F_FB_L * (V_MAX_L * SCALE_NO3 * C_NO3(L)) /
     &                 (K_M_L + C_NO3(L))
              U_ACT_NO3(L) = 100.0 * RLV(L) * DLAYR(L) * F_T * F_DIFF *
     &                     (HATS_NO3 + LATS_NO3) * PHI_EFFLUX

              HATS_NH4 = F_FB_H * (V_MAX_H * SCALE_NH4 * C_NH4(L)) /
     &                 (K_M_H + C_NH4(L))
              LATS_NH4 = F_FB_L * (V_MAX_L * SCALE_NH4 * C_NH4(L)) /
     &                 (K_M_L + C_NH4(L))
              U_ACT_NH4(L) = 100.0 * RLV(L) * DLAYR(L) * F_T * F_DIFF *
     &                     (HATS_NH4 + LATS_NH4) * PHI_EFFLUX

              ! Total potential uptake in layer L
              RNO3U(L) = MAX(0.0, U_PASS_NO3(L) + U_ACT_NO3(L))
              RNH4U(L) = MAX(0.0, U_PASS_NH4(L) + U_ACT_NH4(L))

              ! Strictly bound by extractable mineral N stock in layer L
              RNO3U(L) = MIN(RNO3U(L),
     &             MAX(0.0, SNO3(L)-0.25/KG2PPM(L)))
              RNH4U(L) = MIN(RNH4U(L),
     &             MAX(0.0, SNH4(L)-0.50/KG2PPM(L)))

              TRNU = TRNU + RNO3U(L) + RNH4U(L)
            ELSE
              RNO3U(L) = 0.0
              RNH4U(L) = 0.0
            ENDIF
          ENDDO
        ENDIF

        CALL nb_root_capture(NLAYR, NO3, NH4, RLV, SW, RNO3U, RNH4U,
     &                       KG2PPM)

C       5. Upgrade truncation ceiling from ANDEM to D_max
        UPTAKE_CEILING = MAX(0.0,nb_get_dmax())

        IF (UPTAKE_CEILING .GT. TRNU) THEN
          UPTAKE_CEILING = TRNU
        ENDIF
        IF (TRNU .GT. 0.0) THEN
          NUF = UPTAKE_CEILING / TRNU
          DO L = 1, NLAYR
            IF (RLV(L) .GT. 0.0) THEN
              UNO3(L) = RNO3U(L) * NUF
              UNH4(L) = RNH4U(L) * NUF
              XMIN    = 0.25 / KG2PPM(L)
              MXNO3U  = MAX(0.0, (SNO3(L) - XMIN))
              IF (UNO3(L) .GT. MXNO3U) UNO3(L) = MXNO3U
              XMIN    = 0.50 / KG2PPM(L)
              MXNH4U  = MAX(0.0, (SNH4(L) - XMIN))
              IF (UNH4(L) .GT. MXNH4U) UNH4(L) = MXNH4U
              TRNO3U  = TRNO3U + UNO3(L)
              TRNH4U  = TRNH4U + UNH4(L)
            ENDIF
          ENDDO
          TRNO3U = TRNO3U / 10.0
          TRNH4U = TRNH4U / 10.0
          TRNU   = TRNO3U + TRNH4U
        ENDIF
      ENDIF

!***********************************************************************
!***********************************************************************
!     END OF DYNAMIC IF CONSTRUCT
!***********************************************************************
      ENDIF
!***********************************************************************
      RETURN
      END ! SUBROUTINE NUPTAK
C=======================================================================

!-----------------------------------------------------------------------
!       Variable definitions (v15_s3_v4root additions)
!-----------------------------------------------------------------------
! ROOT_KERNEL  1 = S1 dual-channel additive (default), 2 = v4-R2
! ROOT_V    Membrane Vmax per unit root length (g N / m root / d)
! ROOT_K    Membrane half-saturation constant (mg N / L water)
! DIFFUSION_K  Effective diffusion conductance (L water / m root / d)
! CBULK     Pore-solution NO3 concentration in layer L (mg N / L)
! MF_G      Mass-flow supply, 0.01*RWU*CBULK (g N / m2 / d)
! CAP_G     Membrane capacity, Lroot*ROOT_V*poolfactor (g N / m2 / d)
! MEM_C     Membrane flux at bulk concentration (g N / m2 / d)
! MEM_CR    Root-surface (rhizosphere) concentration from bisection
! UPT_G     Membrane flux at MEM_CR = layer NO3 uptake (g N / m2 / d)
! DIFF_G    Diffusive replenishment at MEM_CR (g N / m2 / d)
! WET_F     Triangular water factor (LL->DUL rise, DUL->SAT decline)
! POOLF     Feedback*sqrt(WET_F), multiplies ROOT_V (v4 poolfactor)
! NH4_G     Native-form NH4 uptake (g N / m2 / d)
! LEDGER_DAY  Within-season day counter for RootKernelLedger.csv
!-----------------------------------------------------------------------
!       END SUBROUTINE NUPTAK
!=======================================================================
