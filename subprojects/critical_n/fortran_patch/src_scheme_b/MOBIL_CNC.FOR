C=======================================================================
C  MOBIL, Subroutine, G. Hoogenboom, J.W. Jones, and K.J.Boote
C-----------------------------------------------------------------------
C  Calculating of the Mobilization of N
C  Phase R1: Decoupled safe buffer mobilization vs stress mobilization
C-----------------------------------------------------------------------
C  REVISION       HISTORY
C  01/09/1989 GH  Written
C  04/02/1996 KJB Mobilization modified
C  08/15/1998 CHP Modified for modular format
C  05/10/1990 GH  Incorporated in CROPGRO
C  10/13/2026 R1  Decoupled safe buffer N mining from defoliation stress
C-----------------------------------------------------------------------
!  Called by:  PLANT
!  Calls:      None
C=======================================================================
      SUBROUTINE MOBIL(DYNAMIC,                           !Control
     &    NDMNEW, NMINEP, NMOBR, PROLFG, RPRO, TRNU,      !Input
     &    WCRLF, WNRLF, WNRRT, WNRSH, WNRST,              !Input
     &    WTLF, WTNLF,                                    !Input
     &    NMINEA, NRUSLF, NRUSRT, NRUSSH, NRUSST,         !Output
     &    NRUSLF_SAFE, NRUSLF_STR)                        !Output

!-----------------------------------------------------------------------
      USE ModuleDefs     !Definitions of constructed variable types, 
                         ! which contain control information, soil
                         ! parameters, hourly weather data.
      IMPLICIT NONE
      SAVE

      INTEGER DYNAMIC

      REAL CNMINE, NDMNEW, NMINEA, NMINEP, NMINER, NMOBR
      REAL NRUSLF, NRUSRT, NRUSSH, NRUSST, RPRO
      REAL TRNU, WNRLF, WNRRT, WNRSH, WNRST
      REAL PROLFG, WCRLF, WTLF, WTNLF
      REAL NRUSLF_SAFE, NRUSLF_STR, NBUF_FREE

!***********************************************************************
!***********************************************************************
!     Seasonal initialization - run once per season
!***********************************************************************
      IF (DYNAMIC .EQ. SEASINIT) THEN
!-----------------------------------------------------------------------
      CNMINE = 0.0         !
      NMINEA = 0.0         !
      NRUSLF = 0.0         !moved from INPLNT
      NRUSST = 0.0         !
      NRUSRT = 0.0         !
      NRUSSH = 0.0         !
      NRUSLF_SAFE = 0.0
      NRUSLF_STR  = 0.0

!***********************************************************************
!***********************************************************************
!     DAILY RATE/INTEGRATION
!***********************************************************************
      ELSEIF (DYNAMIC .EQ. INTEGR) THEN
!-----------------------------------------------------------------------
      CNMINE = 0.0
      NMINEA = 0.0
      NRUSLF = 0.0
      NRUSST = 0.0
      NRUSRT = 0.0
      NRUSSH = 0.0
      NRUSLF_SAFE = 0.0
      NRUSLF_STR  = 0.0

C-----------------------------------------------------------------------
!    Leave MOBIL with N Mined from Leaf, Stem,Root, Shell, and
!    Total Plant Tissue, and CH2O used in the Re-synthesis of Protein
!-----------------------------------------------------------------------
!      IF (TRNU .LT. NDMNEW .AND. NMINEP .GT. 1.E-4) THEN
      IF (NDMNEW - TRNU > 1.E-5 .AND. NMINEP .GT. 1.E-4) THEN
         NMINEA = NDMNEW - TRNU
         IF (NMINEA .GT. NMINEP) NMINEA = NMINEP
         NMINER = NMINEA/NMINEP * NMOBR
         NRUSLF = NMINER * WNRLF
         NRUSST = NMINER * WNRST
         NRUSRT = NMINER * WNRRT
         NRUSSH = NMINER * WNRSH
         CNMINE = NMINEA / 0.16 * RPRO        !Not used

C        Phase R1: Decouple leaf N mobilization into safe vs stress
         IF (PROLFG .GT. 0.0) THEN
           NBUF_FREE = MAX(0.0,
     &       WTNLF - PROLFG * 0.16 * MAX(0.0, WTLF - WCRLF))
         ELSE
           NBUF_FREE = 0.0
         ENDIF
         NRUSLF_SAFE = MAX(0.0, MIN(NRUSLF, NBUF_FREE))
         NRUSLF_STR  = MAX(0.0, NRUSLF - NRUSLF_SAFE)
      ENDIF
!***********************************************************************
!***********************************************************************
!     END OF DYNAMIC IF CONSTRUCT
!***********************************************************************
      ENDIF
!***********************************************************************
      RETURN
      END ! SUBROUTINE MOBIL
