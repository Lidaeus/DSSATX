C=======================================================================
C  NUPTAK, Subroutine
C  Determines N uptake (adapted from CERES)
C-----------------------------------------------------------------------
C  Revision history
C  09/01/1989 JWJ,GH Written
C  03/01/1993 WTB Modified.
C  01/20/1997 GH  Modified.
C  07/10/1998 CHP modified for modular format.
C  05/11/1998 GH  Incorporated in CROPGRO
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
!     searching for the specified 6-character string at beginning
!     of each line.
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

C       4. Layer-by-layer dual-channel uptake (U_pass + U_act)
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
            RNO3U(L) = MIN(RNO3U(L), MAX(0.0, SNO3(L)-0.25/KG2PPM(L)))
            RNH4U(L) = MIN(RNH4U(L), MAX(0.0, SNH4(L)-0.50/KG2PPM(L)))

            TRNU = TRNU + RNO3U(L) + RNH4U(L)
          ELSE
            RNO3U(L) = 0.0
            RNH4U(L) = 0.0
          ENDIF
        ENDDO

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
!       Variable definitions
!-----------------------------------------------------------------------
! ANDEM    Total crop N demand (kg[N]/ha)
! CHAR     Contains the contents of last record read 
! DLAYR(L) Soil thickness in layer L (cm)
! DUL(L)   Volumetric soil water content at Drained Upper Limit in soil 
!            layer L (cm3 [H2O] /cm3 [soil])
! ERR      Error code for file operation 
! ERRKEY   Subroutine name for error file 
! FILECC   Path plus filename for species file (*.spe) 
! FNH4     Potential NH4 availability factor 
! FNO3     Potential NO3 availability factor 
! KG2PPM(L) Conversion factor to switch from kg [N] / ha to ug [N] / g 
!            [soil] for soil layer L 
! LL(L)    Volumetric soil water content in soil layer L at lower limit
!            ( cm3/cm3)
! LUNCRP   Logical unit number for FILEC (*.spe file) 
! MXNH4U   Maximum NH4 uptake from soil (kg N/ha)
! MXNO3U   Maximum NO3 uptake from soil (kg N/ha)
! NDMSDR   Amount of Mobilized N which can be used for seed growth
!            (g[N] / m2 / d)
! NDMTOT   Total N demand (g[N] / m2 / d)
! NH4(L)   Ammonium N in soil layer L (µg[N] / g[soil])
! NL       maximum number of soil layers = 20 
! NLAYR    Number of soil layers 
! NO3(L)   Nitrate in soil layer L (µg[N] / g[soil])
! NUF      N uptake fraction (ratio of demand to N uptake), <= 1.0 
! RFAC     Nitrogen uptake conversion factor ((kg N/ha) / (mg N / cm root))
! RLV(L)   Root length density for soil layer L ((cm root / cm3 soil))
! RNH4U(L) Ammonium uptake (kg N/ha)
! RNO3U(L) Nitrate uptake (kg N/ha)
! RTNH4    Ammonium uptake per unit root length (mg N / cm)
! RTNO3    Nitrate uptake per unit root length (mg N / cm)
! SAT(L)   Volumetric soil water content in layer L at saturation
!            (cm3 [water] / cm3 [soil])
! SMDFR    Relative drought factor 
! SNH4(L)  Total extractable ammonium N in soil layer L (kg [N] / ha)
! SNO3(L)  Total extractable nitrate N in soil layer L (kg [N] / ha)
! SW(L)    Volumetric soil water content in layer L
!            (cm3 [water] / cm3 [soil])
! TRNH4U   Total N uptake in ammonium form in a day (g[N] / m2 / d)
! TRNO3U   Total N uptake in nitrate form in a day (g[N] / m2 / d)
! TRNU     Total N uptake in a day (kg[N] / ha / d)
! UNH4     Uptake of NH4 from soil (interim value) (kg N/ha)
! UNO3     Uptake of NO3 from soil (interim value) (kg N/ha)
! XMIN     Amount of NH4 that cannot be immobilized but stays behind in 
!            soil as NH4; Also, Amount of NO3 that cannot denitrify but 
!            stays behind in the soil as NO3 (kg [N] / ha)
!-----------------------------------------------------------------------
!       END SUBROUTINE NUPTAK
!=======================================================================
