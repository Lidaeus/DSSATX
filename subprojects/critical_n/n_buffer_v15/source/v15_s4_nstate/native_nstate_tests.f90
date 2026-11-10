!=======================================================================
! native_nstate_tests.f90 -- property tests for the v15_s4_nstate fused
! plant-N state psi*. Links the REAL variant N_BUFFER_V2 module; the
! psi* math (nb_relative_state / nb_uptake_signal / nb_curve_conc) is
! exercised directly as pure functions, and the wiring (nb_read nml
! selection, getter split, relaxation) through the public module API.
!
! Compile/run: run_native_tests.sh in this directory.
!=======================================================================
program test_nstate
  use N_BUFFER_MOD
  implicit none
  integer, parameter :: dp = kind(1.0d0)
  integer :: nfail, u
  real(dp) :: conc(2), nmin, ncrit, nmax, psi, nni
  logical :: valid
  real(dp) :: dm(2), nfunc(2), crit2(2), sig(2)
  real :: psir

  nfail = 0
  call write_test_spe()

  ! --- 0. default selection: no NState.nml => mode 1 -------------------
  call execute_command_line('rm -f NState.nml')
  call nb_read('TEST.SPE')
  call check(nstate_mode == 1, 'Z1: absent nml keeps nstate_mode=1', nfail)
  call check(nb_get_psi() == real(nb_psi_n, 4), &
       'Z2: getter equivalence in mode 1 (pub == psi_n)', nfail)

  ! --- 1. unified curve helper matches the commit-side formula ---------
  ! nb_targets(weff,a,b,w0,cinf,proli,prosi,prolf,prosf,leaf,stem)
  call nb_targets(1.5, 4.2, 0.3, 1.5, 2.2, 1.0, 0.5, 0.75, 0.75, psir, psir)
  call nb_curve_conc(1.5_dp, conc)
  call check(abs(conc(1) - (2.2 + (4.2-2.2)*1.0_dp**(-0.3_dp))/100.0_dp) &
       < 1.0e-12_dp, 'C1: nb_curve_conc leaf matches curve formula', nfail)
  call check(abs(conc(2) - conc(1)*0.5_dp) < 1.0e-12_dp, &
       'C2: nb_curve_conc stem applies stem_ratio', nfail)

  ! --- 2. continuity and two-sided anchoring of psi* --------------------
  dm = (/100.0_dp, 50.0_dp/)
  crit2 = dm * conc
  ncrit = sum(crit2)
  nmin = sum(dm*conc*floor_ratio)
  nmax = sum(dm*(conc+cap_density))

  ! exactly at critical: psi = 0 from the deficiency expression
  nfunc = crit2
  call nb_relative_state(dm, nfunc, conc, floor_ratio, cap_density, &
       nmin, ncrit, nmax, psi, nni, valid)
  call check(valid .and. abs(psi) < 1.0e-12_dp, &
       'A1: psi* = 0 exactly at Ncrit (continuous value)', nfail)
  call check(abs(nni - 1.0_dp) < 1.0e-12_dp, 'A2: NNI_f = 1 at Ncrit', nfail)

  ! slightly below / above: sign flip, no jump
  nfunc = crit2 * 0.99_dp
  call nb_relative_state(dm, nfunc, conc, floor_ratio, cap_density, &
       nmin, ncrit, nmax, psi, nni, valid)
  call check(valid .and. psi < 0.0_dp, 'A3: below-crit psi* negative', nfail)
  nfunc = crit2 * 1.01_dp
  call nb_relative_state(dm, nfunc, conc, floor_ratio, cap_density, &
       nmin, ncrit, nmax, psi, nni, valid)
  call check(valid .and. psi > 0.0_dp, 'A4: above-crit psi* positive', nfail)

  ! anchors: band floor -> -1, capacity -> +1
  nfunc = dm*conc*floor_ratio
  call nb_relative_state(dm, nfunc, conc, floor_ratio, cap_density, &
       nmin, ncrit, nmax, psi, nni, valid)
  call check(abs(psi + 1.0_dp) < 1.0e-12_dp, &
       'A5: functional band floor anchors psi* = -1', nfail)
  nfunc = dm*(conc+cap_density)
  call nb_relative_state(dm, nfunc, conc, floor_ratio, cap_density, &
       nmin, ncrit, nmax, psi, nni, valid)
  call check(abs(psi - 1.0_dp) < 1.0e-12_dp, &
       'A6: physical capacity anchors psi* = +1', nfail)

  ! --- 3. deficiency side is the NNI deficit (linear in NNI_f) ---------
  ! psi* = (NNI_f-1)/(1-r_eff) with the organ-weighted effective floor
  ! r_eff = nmin/ncrit (organ-specific floor_ratio aggregated).
  nfunc = crit2*0.8_dp
  call nb_relative_state(dm, nfunc, conc, floor_ratio, cap_density, &
       nmin, ncrit, nmax, psi, nni, valid)
  call check(abs(psi - (0.8_dp-1.0_dp)/(1.0_dp-nmin/ncrit)) &
       < 1.0e-12_dp, 'D1: deficiency psi* is the NNI_f deficit (linear)', nfail)

  ! --- 4. functional-N basis semantics (nb_uptake_signal) --------------
  ! Deficient organ holding a reserve: the locked part is excluded from
  ! the state basis, the mobilizable part is not.
  ! total = crit-0.2 (below critical) with reserve = 0.5.
  ! gap = crit - (total - reserve) = 0.7.
  ! mobilizable (kmob huge): ready=0.5, unavailable=0 -> signal = total.
  sig = nb_uptake_signal((/crit2(1)-0.2_dp, crit2(2)/), crit2, &
       (/0.5_dp, 0.0_dp/), 1.0e6_dp, 0.0_dp)
  call check(abs(sig(1) - (crit2(1)-0.2_dp)) < 1.0e-12_dp, &
       'F1: fully mobilizable reserve stays in the signal', nfail)
  ! locked (kmob=0): ready=0, unavailable=0.5, gap-ready=0.7 -> deduct 0.5
  sig = nb_uptake_signal((/crit2(1)-0.2_dp, crit2(2)/), crit2, &
       (/0.5_dp, 0.0_dp/), 0.0_dp, 0.0_dp)
  call check(abs(sig(1) - (crit2(1)-0.7_dp)) < 1.0e-12_dp, &
       'F2: locked reserve is excluded from the signal', nfail)

  ! --- 5. nml selection + relaxation wiring -----------------------------
  open(newunit=u, file='NState.nml', status='replace')
  write(u,'(A)') '&NSTATE nstate_mode=2, state_tau=2.0 /'
  close(u)
  call nb_read('TEST.SPE')
  call check(nstate_mode == 2, 'W1: NState.nml selects mode 2', nfail)
  call check(state_tau > 1.9999_dp .and. state_tau < 2.0001_dp, &
       'W2: state_tau read from nml', nfail)

  ! relaxation math via nb_relax_pub: first publish follows instantly,
  ! subsequent steps approach the target with alpha = 1-exp(-1/tau)
  nb_psi_n = 0.0_dp
  nstate_pub_ready = .false.
  call nb_relax_pub()
  call check(abs(nb_psi_pub) < 1.0e-12_dp, &
       'R1: first publish initializes to the current state', nfail)
  nb_psi_n = 1.0_dp
  call nb_relax_pub()
  call check(abs(nb_psi_pub - (1.0_dp-exp(-0.5_dp))) < 1.0e-12_dp, &
       'R2: tau=2 gives alpha=1-exp(-1/2) toward the target', nfail)
  call check(nb_get_psi() /= real(nb_psi_n, 4), &
       'R3: growth getter reads relaxed pub while uptake reads instant', nfail)
  call check(nb_get_uptake_psi() == real(nb_uptake_psi, 4), &
       'R4: uptake getter reads the instantaneous uptake state', nfail)
  ! tau=0 disables relaxation
  state_tau = 0.0_dp
  nb_psi_n = -1.0_dp
  call nb_relax_pub()
  call check(abs(nb_psi_pub + 1.0_dp) < 1.0e-12_dp, &
       'R5: tau=0 keeps pub bit-equal to the instantaneous state', nfail)

  write(*,'(A,I0,A)') 'native_nstate_tests: ', nfail, ' failure(s)'
  if (nfail > 0) stop 1
  stop 0

contains
  subroutine check(cond, msg, counter)
    logical, intent(in) :: cond
    character(*), intent(in) :: msg
    integer, intent(inout) :: counter
    if (.not. cond) then
      counter = counter + 1
      write(*,'(A)') 'FAIL: ' // msg
    else
      write(*,'(A)') 'pass: ' // msg
    end if
  end subroutine check
end program test_nstate

!-----------------------------------------------------------------------
! Minimal SPE fixture writer invoked before nb_read (the program above
! writes TEST.SPE via a helper call in main; kept as a subroutine here).
!-----------------------------------------------------------------------
subroutine write_test_spe()
  implicit none
  integer :: u
  open(newunit=u, file='TEST.SPE', status='replace')
  write(u,'(A)') '*SPECIES DATA'
  write(u,'(A)') '!*ORGAN NITROGEN RESERVES AND BUFFER DILUTION'
  write(u,'(A)') ' 1.000 0.030 0.370 0.020 0.078 0.100 0.100 0.000' // &
       ' 0.028 1.000 0.500 0.091 1.770 4.524 2.400  40.0'
  close(u)
end subroutine write_test_spe
