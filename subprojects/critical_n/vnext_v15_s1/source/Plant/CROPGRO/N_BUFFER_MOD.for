C=======================================================================
C  MODULE: N_BUFFER_MOD
C  PURPOSE: Fast Organ Nitrogen Reserves, Continuous Source Dispatch,
C           Photosynthetic Functional N Coupling, and N/C Conservation.
C  REFERENCE: Gastal & Lemaire (2002), Yao (2023), Li (2026)
C=======================================================================
      MODULE N_BUFFER_MOD
      IMPLICIT NONE
      SAVE

C     Configuration and control switches
      REAL NBUF_ACT       ! 0=Inactive (Legacy B0), 1=Active
      REAL KMOB           ! Fast reserve mobilization rate (1/d)
      REAL KFILL          ! Fast reserve refill rate (1/d)
      REAL RPROT          ! Protected reserve fraction of Ncrit
      REAL RTARG          ! Target reserve fraction of Ncrit
      REAL RCAP           ! Maximum reserve capacity fraction
      REAL DELTA_S        ! Sigmoid transition width for NNI
      REAL C_COST         ! Carbon cost per g N (g CH2O / g N)

C     State variables: Persistent Fast Organ Reserves (g[N] / m2)
      REAL R_LF           ! Fast soluble reserve N in leaves
      REAL R_ST           ! Fast soluble reserve N in stems
      REAL R_LF_PREV      ! Reserve at start of day
      REAL R_ST_PREV      ! Reserve at start of day

C     Diagnostic and flux variables (g[N] / m2)
      REAL NCRIT_LF       ! Leaf critical N mass
      REAL NCRIT_ST       ! Stem critical N mass
      REAL NNI_SHOOT      ! Shoot N nutrition index
      REAL NNI_LF         ! Leaf NNI
      REAL NNI_ST         ! Stem NNI
      REAL A_PLAN_LF      ! Planned reserve mobilization from leaf
      REAL A_PLAN_ST      ! Planned reserve mobilization from stem
      REAL D_REFILL_LF    ! Buffer refill demand for leaf
      REAL D_REFILL_ST    ! Buffer refill demand for stem
      REAL D_ROOT_NET     ! Net root uptake demand passed to NUPTAK
      REAL U_TO_SINK      ! Actual root uptake allocated to new growth
      REAL U_REFILL_LF    ! Actual root uptake allocated to leaf reserve
      REAL U_REFILL_ST    ! Actual root uptake allocated to stem reserve
      REAL A_BACKUP_LF    ! Shortfall backup mobilization from leaf
      REAL A_BACKUP_ST    ! Shortfall backup mobilization from stem
      REAL RNITP_FUNC     ! Functional leaf N % for photosynthesis
      REAL RNITP_TOTAL    ! Total leaf N %

C     Cumulative conservation trackers (g[N] / m2)
      REAL CUM_TRNU       ! Cumulative root uptake
      REAL CUM_MOB_LF     ! Cumulative reserve mobilization from leaf
      REAL CUM_MOB_ST     ! Cumulative reserve mobilization from stem
      REAL CUM_REFILL_LF  ! Cumulative refill into leaf reserve
      REAL CUM_REFILL_ST  ! Cumulative refill into stem reserve

      CONTAINS

C=======================================================================
C     SUBROUTINE N_BUFFER_READ
C     Reads organ buffer parameters from TMGRO048.SPE.
C     Card: !*ORGAN NITROGEN RESERVES AND BUFFER DILUTION
C=======================================================================
      SUBROUTINE N_BUFFER_READ(FILECC)
      USE, INTRINSIC :: IEEE_ARITHMETIC, ONLY: IEEE_IS_FINITE
      IMPLICIT NONE
      CHARACTER*(*) FILECC
      CHARACTER*80 C80
      CHARACTER*6 SECTION, ERRKEY
      INTEGER LUNCRP, LNUM, LINC, FOUND, ISECT, ERR, LUNOUT
      ERRKEY = 'NBUF_R'

C     Set compatibility defaults (Disabled = Legacy B0)
      NBUF_ACT = 0.0
      KMOB     = 0.35
      KFILL    = 0.25
      RPROT    = 0.05
      RTARG    = 0.25
      RCAP     = 0.45
      DELTA_S  = 0.10
      C_COST   = 1.50

      CALL GETLUN('FILEC', LUNCRP)
      OPEN(LUNCRP, FILE=FILECC, STATUS='OLD', IOSTAT=ERR)
      IF (ERR .NE. 0) CALL ERROR(ERRKEY, ERR, FILECC, 0)
      LNUM = 0
      SECTION = '!*ORGA'
      CALL FIND(LUNCRP, SECTION, LINC, FOUND)
      IF (FOUND .NE. 0) THEN
        LNUM = LNUM + LINC
        CALL IGNORE(LUNCRP, LNUM, ISECT, C80)
        READ(C80,'(8F6.0)',IOSTAT=ERR) NBUF_ACT, KMOB, KFILL,
     &    RPROT, RTARG, RCAP, DELTA_S, C_COST
        IF (ERR .NE. 0) CALL ERROR(ERRKEY, ERR, FILECC, LNUM)
        IF (.NOT. IEEE_IS_FINITE(NBUF_ACT) .OR.
     &      .NOT. IEEE_IS_FINITE(KMOB)     .OR.
     &      .NOT. IEEE_IS_FINITE(KFILL)    .OR.
     &      .NOT. IEEE_IS_FINITE(RPROT)    .OR.
     &      .NOT. IEEE_IS_FINITE(RTARG)    .OR.
     &      .NOT. IEEE_IS_FINITE(RCAP)     .OR.
     &      .NOT. IEEE_IS_FINITE(DELTA_S)  .OR.
     &      .NOT. IEEE_IS_FINITE(C_COST)) THEN
          CALL ERROR(ERRKEY, 98, FILECC, LNUM)
        ENDIF
        IF (NBUF_ACT .GT. 0.5) THEN
          IF (KMOB .LT. 0.01 .OR. KMOB .GT. 2.0 .OR.
     &        KFILL .LT. 0.01 .OR. KFILL .GT. 2.0 .OR.
     &        RPROT .LT. 0.0 .OR. RPROT .GT. RTARG .OR.
     &        RTARG .GT. RCAP .OR. RCAP .GT. 1.0 .OR.
     &        DELTA_S .LT. 0.01 .OR. DELTA_S .GT. 1.0 .OR.
     &        C_COST .LT. 0.0 .OR. C_COST .GT. 10.0) THEN
            CALL ERROR(ERRKEY, 99, FILECC, LNUM)
          ENDIF
        ENDIF
      ENDIF
      CLOSE(LUNCRP)

      CALL GETLUN('NBUFO', LUNOUT)
      OPEN(LUNOUT, FILE='NBufferParam.OUT', STATUS='REPLACE')
      WRITE(LUNOUT,'(A)') 
     &  '@ NBUF_ACT  KMOB  KFILL  RPROT  RTARG   RCAP  DELTA C_COST'
      WRITE(LUNOUT,'(8(1X,ES14.6))') 
     &  NBUF_ACT, KMOB, KFILL, RPROT, RTARG, RCAP, DELTA_S, C_COST
      CLOSE(LUNOUT)
      RETURN
      END SUBROUTINE N_BUFFER_READ

C=======================================================================
C     SUBROUTINE N_BUFFER_INIT
C     Initializes reserves at seasonal start.
C=======================================================================
      SUBROUTINE N_BUFFER_INIT(RUN, YRDOY)
      IMPLICIT NONE
      INTEGER RUN, YRDOY
      INTEGER LUN
      R_LF          = 0.0
      R_ST          = 0.0
      R_LF_PREV     = 0.0
      R_ST_PREV     = 0.0
      NCRIT_LF      = 0.0
      NCRIT_ST      = 0.0
      NNI_SHOOT     = 1.0
      NNI_LF        = 1.0
      NNI_ST        = 1.0
      A_PLAN_LF     = 0.0
      A_PLAN_ST     = 0.0
      D_REFILL_LF   = 0.0
      D_REFILL_ST   = 0.0
      D_ROOT_NET    = 0.0
      U_TO_SINK     = 0.0
      U_REFILL_LF   = 0.0
      U_REFILL_ST   = 0.0
      A_BACKUP_LF   = 0.0
      A_BACKUP_ST   = 0.0
      RNITP_FUNC    = 0.0
      RNITP_TOTAL   = 0.0
      CUM_TRNU      = 0.0
      CUM_MOB_LF    = 0.0
      CUM_MOB_ST    = 0.0
      CUM_REFILL_LF = 0.0
      CUM_REFILL_ST = 0.0

      IF (NBUF_ACT .GT. 0.5) THEN
        IF (RUN .EQ. 1) THEN
          CALL GETLUN('NBOUT1', LUN)
          OPEN(LUN, FILE='OrganNState.OUT', STATUS='REPLACE')
          WRITE(LUN,'(A)') '@TRNO   YRDOY   DAS   WTLF    WTST    ' //
     &      'WTNLF   WTNST   R_LF    R_ST    NCRIT_LF NCRIT_ST ' //
     &      'NNI_LF  NNI_ST  NNI_SH  RNITP_F RNITP_T'
          CLOSE(LUN)

          CALL GETLUN('NBOUT2', LUN)
          OPEN(LUN, FILE='NFlux.OUT', STATUS='REPLACE')
          WRITE(LUN,'(A)') '@TRNO   YRDOY   DAS   D_SINK   A_PLAN_L' //
     &      ' A_PLAN_S D_REFILL_L D_REFILL_S D_ROOT_N  U_ACTUAL ' //
     &      'U_TO_SK  U_REF_L  U_REF_S  A_BAK_L  A_BAK_S  RESIDUAL'
          CLOSE(LUN)

          CALL GETLUN('NBOUT3', LUN)
          OPEN(LUN, FILE='NCBalance.OUT', STATUS='REPLACE')
          WRITE(LUN,'(A)') '@TRNO   YRDOY   DAS   N_BEG   U_IN     ' //
     &      'MOB_TOT REFILL_T N_END   RESIDUAL  C_COST_D'
          CLOSE(LUN)
        ENDIF
      ENDIF
      RETURN
      END SUBROUTINE N_BUFFER_INIT

C=======================================================================
C     FUNCTION SMOOTH_POS
C     C1 conservative positive part approximation: 0 <= p(x) <= max(x,0)
C=======================================================================
      REAL FUNCTION SMOOTH_POS(X, W)
      IMPLICIT NONE
      REAL X, W
      IF (X .LE. 0.0) THEN
        SMOOTH_POS = 0.0
      ELSE IF (X .LT. W) THEN
        SMOOTH_POS = (X * X) / (2.0 * W)
      ELSE
        SMOOTH_POS = X - 0.5 * W
      ENDIF
      RETURN
      END FUNCTION SMOOTH_POS

C=======================================================================
C     SUBROUTINE N_BUFFER_DISPATCH
C     Computes planned internal mobilization, buffer refill demand,
C     and single net root uptake demand (g[N] / m2).
C=======================================================================
      SUBROUTINE N_BUFFER_DISPATCH(D_SINK, WEFF, WTLF, WTST,
     &  WTNLF, WTNST, CNC_A, CNC_B, CNC_W0, CNC_NC_INF,
     &  PROLFG, PROSTG, PROLFI, PROSTI, D_ROOT_OUT, A_PLAN_OUT)
      IMPLICIT NONE
      REAL D_SINK, WEFF, WTLF, WTST, WTNLF, WTNST
      REAL CNC_A, CNC_B, CNC_W0, CNC_NC_INF
      REAL PROLFG, PROSTG, PROLFI, PROSTI
      REAL D_ROOT_OUT, A_PLAN_OUT

      REAL NC_LEAF, NC_STEM, FR_DIL
      REAL R_CAP_LF, R_CAP_ST, R_PROT_LF, R_PROT_ST
      REAL R_TARG_LF, R_TARG_ST
      REAL B_LF, B_ST, E_LF, E_ST, SIG_EXP, S_VAL
      REAL L_LF, L_ST, F_LF, F_ST, J_LF, J_ST, POS_J_SUM
      REAL MIN_PROLFG, MIN_PROSTG

      IF (NBUF_ACT .LE. 0.5) THEN
        D_ROOT_OUT = D_SINK
        A_PLAN_OUT = 0.0
        RETURN
      ENDIF

C     Save prior day reserves
      R_LF_PREV = R_LF
      R_ST_PREV = R_ST

C     1. Compute organ critical targets
      IF (WEFF .LT. CNC_W0) THEN
        NC_LEAF = CNC_A / 100.0
      ELSE
        NC_LEAF = (CNC_NC_INF + (CNC_A - CNC_NC_INF) *
     &            ((WEFF / CNC_W0) ** (-CNC_B))) / 100.0
      ENDIF

C     Ensure leaf critical target obeys physiological boundaries
      MIN_PROLFG = MAX(0.015, PROLFG * 0.16)
      NC_LEAF    = MAX(MIN_PROLFG, MIN(PROLFI * 0.16, NC_LEAF))

C     Stem target linked via dilution factor
      IF (PROLFI .GT. PROLFG) THEN
        FR_DIL = (NC_LEAF - MIN_PROLFG) / ((PROLFI - PROLFG) * 0.16)
        FR_DIL = MAX(0.0, MIN(1.0, FR_DIL))
      ELSE
        FR_DIL = 1.0
      ENDIF
      MIN_PROSTG = MAX(0.010, PROSTG * 0.16)
      NC_STEM = MIN_PROSTG + (PROSTI - PROSTG) * 0.16 * FR_DIL
      NC_STEM = MAX(MIN_PROSTG, MIN(PROSTI * 0.16, NC_STEM))

      NCRIT_LF = MAX(0.001, WTLF * NC_LEAF)
      NCRIT_ST = MAX(0.001, WTST * NC_STEM)

C     2. Compute nutrition indices
      NNI_LF    = WTNLF / NCRIT_LF
      NNI_ST    = WTNST / NCRIT_ST
      NNI_SHOOT = (WTNLF + WTNST) / (NCRIT_LF + NCRIT_ST)

C     3. Organ capacity, target, and protection thresholds
      R_CAP_LF  = RCAP * NCRIT_LF
      R_CAP_ST  = RCAP * NCRIT_ST
      R_PROT_LF = MIN(R_CAP_LF, RPROT * NCRIT_LF)
      R_PROT_ST = MIN(R_CAP_ST, RPROT * NCRIT_ST)
      R_TARG_LF = MIN(R_CAP_LF, RTARG * NCRIT_LF)
      R_TARG_ST = MIN(R_CAP_ST, RTARG * NCRIT_ST)

C     Bound current reserves within capacity
      R_LF = MAX(0.0, MIN(R_CAP_LF, R_LF))
      R_ST = MAX(0.0, MIN(R_CAP_ST, R_ST))

C     4. Rate budgets (dt = 1.0 day)
      B_LF = R_LF * (1.0 - EXP(-KMOB))
      B_ST = R_ST * (1.0 - EXP(-KMOB))

C     5. Eligible surplus reserve
      E_LF = MIN(MAX(0.0, R_LF - R_PROT_LF),
     &       NCRIT_LF * SMOOTH_POS(NNI_LF - 1.0, DELTA_S))
      E_ST = MIN(MAX(0.0, R_ST - R_PROT_ST),
     &       NCRIT_ST * SMOOTH_POS(NNI_ST - 1.0, DELTA_S))

C     6. Sigmoid dispatch signal based on shoot NNI
      SIG_EXP = MAX(-40.0, MIN(40.0, (NNI_SHOOT - 1.0) / DELTA_S))
      S_VAL   = 1.0 / (1.0 + EXP(-SIG_EXP))

C     7. Preferences and coordinated net flows
      L_LF = S_VAL * MIN(E_LF, B_LF)
      L_ST = S_VAL * MIN(E_ST, B_ST)

      F_LF = (1.0 - S_VAL) * MAX(0.0, R_TARG_LF - R_LF) *
     &       (1.0 - EXP(-KFILL))
      F_ST = (1.0 - S_VAL) * MAX(0.0, R_TARG_ST - R_ST) *
     &       (1.0 - EXP(-KFILL))

      J_LF = L_LF - F_LF
      J_ST = L_ST - F_ST

      POS_J_SUM = MAX(0.0, J_LF) + MAX(0.0, J_ST)
      IF (POS_J_SUM .GT. 1.0E-9 .AND. D_SINK .GT. 0.0) THEN
        A_PLAN_LF = MAX(0.0, J_LF) * MIN(1.0, D_SINK / POS_J_SUM)
        A_PLAN_ST = MAX(0.0, J_ST) * MIN(1.0, D_SINK / POS_J_SUM)
      ELSE
        A_PLAN_LF = 0.0
        A_PLAN_ST = 0.0
      ENDIF

      D_REFILL_LF = MAX(0.0, -J_LF)
      D_REFILL_ST = MAX(0.0, -J_ST)

C     8. Unique net root demand
      D_ROOT_NET = MAX(0.0, D_SINK - (A_PLAN_LF + A_PLAN_ST)) +
     &             (D_REFILL_LF + D_REFILL_ST)

      D_ROOT_OUT = D_ROOT_NET
      A_PLAN_OUT = A_PLAN_LF + A_PLAN_ST
      RETURN
      END SUBROUTINE N_BUFFER_DISPATCH

C=======================================================================
C     SUBROUTINE N_BUFFER_ALLOCATE
C     Allocates actual root uptake (TRNU), updates reserve pools,
C     evaluates backup mobilization, and outputs functional leaf N.
C=======================================================================
      SUBROUTINE N_BUFFER_ALLOCATE(TRNU, D_SINK, WTLF, WCRLF,
     &  WTNLF, NAVL_OUT, NMINEA_OUT, RNITP_OUT)
      IMPLICIT NONE
      REAL TRNU, D_SINK, WTLF, WCRLF, WTNLF
      REAL NAVL_OUT, NMINEA_OUT, RNITP_OUT

      REAL D_GROWTH_ROOT, REFILL_TOT, SHORTFALL
      REAL B_REM_LF, B_REM_ST, B_REM_SUM
      REAL N_SUPPLIED, N_FUNC_LF

      IF (NBUF_ACT .LE. 0.5) THEN
        NAVL_OUT   = TRNU
        NMINEA_OUT = 0.0
        RNITP_OUT  = 100.0 * WTNLF / MAX(0.001, WTLF - WCRLF)
        RETURN
      ENDIF

C     1. Allocate root uptake between new growth and refill
      D_GROWTH_ROOT = MAX(0.0, D_SINK - (A_PLAN_LF + A_PLAN_ST))
      U_TO_SINK     = MIN(TRNU, D_GROWTH_ROOT)

      REFILL_TOT    = D_REFILL_LF + D_REFILL_ST
      IF (REFILL_TOT .GT. 1.0E-9) THEN
        U_REFILL_LF = MIN(TRNU - U_TO_SINK, REFILL_TOT) *
     &                (D_REFILL_LF / REFILL_TOT)
        U_REFILL_ST = MIN(TRNU - U_TO_SINK, REFILL_TOT) *
     &                (D_REFILL_ST / REFILL_TOT)
      ELSE
        U_REFILL_LF = 0.0
        U_REFILL_ST = 0.0
      ENDIF

C     2. Check for sink shortfall and engage backup mobilization
      SHORTFALL = MAX(0.0, D_SINK - (A_PLAN_LF + A_PLAN_ST) - U_TO_SINK)
      IF (SHORTFALL .GT. 1.0E-9) THEN
        B_REM_LF  = MAX(0.0, MIN(R_LF * (1.0 - EXP(-KMOB)) - A_PLAN_LF,
     &                           R_LF - A_PLAN_LF))
        B_REM_ST  = MAX(0.0, MIN(R_ST * (1.0 - EXP(-KMOB)) - A_PLAN_ST,
     &                           R_ST - A_PLAN_ST))
        B_REM_SUM = B_REM_LF + B_REM_ST
        IF (B_REM_SUM .GT. 1.0E-9) THEN
          A_BACKUP_LF = B_REM_LF * MIN(1.0, SHORTFALL / B_REM_SUM)
          A_BACKUP_ST = B_REM_ST * MIN(1.0, SHORTFALL / B_REM_SUM)
        ELSE
          A_BACKUP_LF = 0.0
          A_BACKUP_ST = 0.0
        ENDIF
      ELSE
        A_BACKUP_LF = 0.0
        A_BACKUP_ST = 0.0
      ENDIF

C     3. Update state of fast reserves
      R_LF = MAX(0.0, R_LF - (A_PLAN_LF + A_BACKUP_LF) + U_REFILL_LF)
      R_ST = MAX(0.0, R_ST - (A_PLAN_ST + A_BACKUP_ST) + U_REFILL_ST)

C     4. Total internal supply and total available for new growth
      NMINEA_OUT = (A_PLAN_LF + A_BACKUP_LF) +
     &             (A_PLAN_ST + A_BACKUP_ST)
      NAVL_OUT   = U_TO_SINK + NMINEA_OUT

C     5. Photosynthetic functional N calculation
C        Reserves do NOT artificially inflate leaf photosynthesis.
      N_FUNC_LF   = MAX(0.0, WTNLF - R_LF)
      RNITP_FUNC  = 100.0 * N_FUNC_LF / MAX(0.001, WTLF - WCRLF)
      RNITP_TOTAL = 100.0 * WTNLF / MAX(0.001, WTLF - WCRLF)
      RNITP_OUT   = RNITP_FUNC

C     Accumulate cumulative fluxes
      CUM_TRNU      = CUM_TRNU + TRNU
      CUM_MOB_LF    = CUM_MOB_LF + (A_PLAN_LF + A_BACKUP_LF)
      CUM_MOB_ST    = CUM_MOB_ST + (A_PLAN_ST + A_BACKUP_ST)
      CUM_REFILL_LF = CUM_REFILL_LF + U_REFILL_LF
      CUM_REFILL_ST = CUM_REFILL_ST + U_REFILL_ST
      RETURN
      END SUBROUTINE N_BUFFER_ALLOCATE

C=======================================================================
C     SUBROUTINE N_BUFFER_SENESCENCE
C     Deducts proportional fast reserve when leaf/stem tissue senesces.
C=======================================================================
      SUBROUTINE N_BUFFER_SENESCENCE(LFLOSS_FRAC, STLOSS_FRAC)
      IMPLICIT NONE
      REAL LFLOSS_FRAC, STLOSS_FRAC
      IF (NBUF_ACT .GT. 0.5) THEN
        IF (LFLOSS_FRAC .GT. 0.0) THEN
          R_LF = MAX(0.0, R_LF * (1.0 - MIN(1.0, LFLOSS_FRAC)))
        ENDIF
        IF (STLOSS_FRAC .GT. 0.0) THEN
          R_ST = MAX(0.0, R_ST * (1.0 - MIN(1.0, STLOSS_FRAC)))
        ENDIF
      ENDIF
      RETURN
      END SUBROUTINE N_BUFFER_SENESCENCE

C=======================================================================
C     SUBROUTINE N_BUFFER_DIAGNOSTICS
C     Writes high-precision daily tracking records.
C=======================================================================
      SUBROUTINE N_BUFFER_DIAGNOSTICS(TRNO, YRDOY, DAS, WTLF, WTST,
     &  WTNLF, WTNST, D_SINK, TRNU)
      IMPLICIT NONE
      INTEGER TRNO, YRDOY, DAS
      REAL WTLF, WTST, WTNLF, WTNST, D_SINK, TRNU
      INTEGER LUN
      REAL RESIDUAL, N_BEG, N_END, MOB_TOT, REFILL_TOT, C_COST_DAY

      IF (NBUF_ACT .LE. 0.5) RETURN

      MOB_TOT    = (A_PLAN_LF + A_BACKUP_LF) + (A_PLAN_ST + A_BACKUP_ST)
      REFILL_TOT = U_REFILL_LF + U_REFILL_ST
      N_BEG      = R_LF_PREV + R_ST_PREV
      N_END      = R_LF + R_ST
      RESIDUAL   = (N_BEG + REFILL_TOT - MOB_TOT) - N_END
      C_COST_DAY = TRNU * C_COST

      CALL GETLUN('NBOUT1', LUN)
      OPEN(LUN, FILE='OrganNState.OUT', STATUS='UNKNOWN',
     &     POSITION='APPEND')
      WRITE(LUN,'(I5,1X,I7,1X,I5,13(1X,ES14.6))')
     &  TRNO, YRDOY, DAS, WTLF, WTST, WTNLF, WTNST, R_LF, R_ST,
     &  NCRIT_LF, NCRIT_ST, NNI_LF, NNI_ST, NNI_SHOOT,
     &  RNITP_FUNC, RNITP_TOTAL
      CLOSE(LUN)

      CALL GETLUN('NBOUT2', LUN)
      OPEN(LUN, FILE='NFlux.OUT', STATUS='UNKNOWN',
     &     POSITION='APPEND')
      WRITE(LUN,'(I5,1X,I7,1X,I5,12(1X,ES14.6))')
     &  TRNO, YRDOY, DAS, D_SINK, A_PLAN_LF, A_PLAN_ST,
     &  D_REFILL_LF, D_REFILL_ST, D_ROOT_NET, TRNU,
     &  U_TO_SINK, U_REFILL_LF, U_REFILL_ST,
     &  A_BACKUP_LF, A_BACKUP_ST, RESIDUAL
      CLOSE(LUN)

      CALL GETLUN('NBOUT3', LUN)
      OPEN(LUN, FILE='NCBalance.OUT', STATUS='UNKNOWN',
     &     POSITION='APPEND')
      WRITE(LUN,'(I5,1X,I7,1X,I5,6(1X,ES14.6))')
     &  TRNO, YRDOY, DAS, N_BEG, TRNU, MOB_TOT, REFILL_TOT,
     &  N_END, RESIDUAL, C_COST_DAY
      CLOSE(LUN)
      RETURN
      END SUBROUTINE N_BUFFER_DIAGNOSTICS

      END MODULE N_BUFFER_MOD
