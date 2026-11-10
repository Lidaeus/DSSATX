!=======================================================================
! native_root_tests.f90 -- property tests for the v15_s3_v4root NUPTAK
!
! Links the REAL production objects (ModuleDefs.for + N_BUFFER_V2.f90 +
! the variant NUPTAK.for) and drives SUBROUTINE NUPTAK directly through
! ModuleData PUT/GET and the N_BUFFER state API (nb_read/nb_init/nb_plan),
! so the assertions exercise the actual code path used by the engine.
!
! Compile/run: see run_native_tests.sh in this directory.
!=======================================================================
program test_root_kernel
  use ModuleDefs
  use ModuleData
  use N_BUFFER_MOD, only: nb_read, nb_init, nb_plan, nb_allocate, &
       nb_commit, nb_get_uptake_psi, nb_targets
  implicit none

  integer, parameter :: NLX = 20
  real, parameter :: TOL = 1.0e-4

  character(92) :: filecc
  character(200) :: line
  integer :: dynamic, u, ios, i, nfail
  integer :: nlayr

  real :: dlayr(NLX), dul(NLX), kg2ppm(NLX), ll(NLX), sat(NLX), sw(NLX)
  real :: rlv(NLX), no3(NLX), nh4(NLX)
  real :: uno3(NLX), unh4(NLX), trno3u, trnh4u, trnu
  real :: ndmtot, ndmsdr
  real :: rwu(NLX), ep_spam
  real :: dm(5), orgn(5), fnin(5), root_out, demand

  ! mode-2 kernel reference quantities (bounds only, mirrored formulas)
  real :: c_l, mf_g, cap_g, mem_c, sup_max, length_m, wet_f, wrel
  real :: u1_sum, u2_sum, sat_cap
  real :: uno3_deficient, trnu_deficient
  real :: navl_dummy, nmine_dummy, lf_dummy, st_dummy, rnitp
  real :: leaf_target, stem_target
  real :: dm_f(5), dm3(3)
  logical :: luxmode

  nfail = 0
  filecc = 'TEST.SPE'
  nlayr = 4
  dlayr(1:4) = (/10.0, 20.0, 30.0, 40.0/)
  ll(1:4)    = (/0.12, 0.14, 0.15, 0.16/)
  dul(1:4)   = (/0.28, 0.30, 0.31, 0.32/)
  sat(1:4)   = (/0.42, 0.43, 0.44, 0.45/)
  sw(1:4)    = (/0.25, 0.28, 0.30, 0.32/)   ! mid-range moisture
  rlv(1:4)   = (/0.60, 0.35, 0.12, 0.02/)
  no3(1:4)   = (/25.0, 18.0, 10.0, 4.0/)    ! ug N/g soil
  nh4(1:4)   = (/3.0, 2.0, 1.5, 1.0/)
  do i = 1, 4
    kg2ppm(i) = 10.0 / (1.30 * dlayr(i))    ! BD = 1.30 g/cm3
  enddo
  ndmtot = 0.5
  ndmsdr = 0.0
  rwu(1:4) = (/0.30, 0.15, 0.05, 0.01/)     ! cm/d
  ep_spam = 0.0

  ! --- synthetic species file: !*ROOT section + 16-field NBUF card -----
  open(newunit=u, file='TEST.SPE', status='replace')
  write(u,'(A)') '*SPECIES DATA'
  write(u,'(A)') '!*ROOT'
  write(u,'(A)') '  1.00  1.00  1.00  1.00  1.00  1.00  1.00  1.00'
  write(u,'(A)') '  1.00  1.00  1.00  1.00  1.00  1.00  1.00  1.00'
  write(u,'(A)') ' 0.012 0.012'
  write(u,'(A)') '!*ORGAN NITROGEN RESERVES AND BUFFER DILUTION'
  write(u,'(A)') ' 1.000 0.030 0.370 0.020 0.078 0.100 0.100 0.000' // &
       ' 0.028 1.000 0.500 0.091 1.770 4.524 2.400  40.0'
  close(u)

  ! --- phase selection: "lux" runs the F scenario in a fresh process ---
  luxmode = .false.
  if (command_argument_count() > 0) then
    call get_command_argument(1, line)
    luxmode = (trim(line) == 'lux')
  end if

  ! --- N buffer state: read card, init, plan the canopy ---------------
  call nb_read(trim(filecc))
  call nb_init(1)
  ! nb_targets sets cap_density/floor_ratio (DEMAND.for does this in the
  ! engine); without it nb_relative_state is invalid and psi stays 0.
  call nb_targets(1.5, 4.2, 0.3, 1.5, 2.2, 1.0, 0.5, 0.75, 0.75, &
       leaf_target, stem_target)
  dm   = (/100.0, 50.0, 20.0, 10.0, 5.0/)
  orgn = (/2.0, 0.8, 0.3, 0.15, 0.10/)      ! well below critical -> psi < 0
  if (luxmode) then
    ! above-organ-critical N everywhere (crit = dm*fnin): leaf 5.0,
    ! stem 1.25, root 0.24, shell 0.45, seed 0.25 -> psi > 0
    orgn = (/6.0, 1.6, 0.50, 0.55, 0.30/)
  end if
  fnin = (/0.05, 0.025, 0.012, 0.045, 0.05/)
  demand = 0.4
  call nb_plan(1, 1, 26071, 1, demand, dm, orgn, 0.0, 0.0, fnin, root_out)

  call PUT('SPAM', 'UH2O', rwu)
  call PUT('SPAM', 'EP', ep_spam)

  if (luxmode) then
    ! F. Luxury psi > 0 down-regulates kernel-2 uptake vs the deficient
    !    baseline persisted by the main phase (same soil/water state).
    open(newunit=u, file='RootUptake.nml', status='replace')
    write(u,'(A)') '&ROOTUPTAKE root_kernel=2, root_v=0.0002, '// &
         'root_k=10.0, diffusion_k=0.005 /'
    close(u)
    dynamic = RUNINIT
    call NUPTAK(dynamic, dlayr, dul, filecc, kg2ppm, ll, ndmsdr, ndmtot, &
         nh4, no3, nlayr, rlv, sat, sw, trnh4u, trno3u, trnu, unh4, uno3)
    dynamic = SEASINIT
    call NUPTAK(dynamic, dlayr, dul, filecc, kg2ppm, ll, ndmsdr, ndmtot, &
         nh4, no3, nlayr, rlv, sat, sw, trnh4u, trno3u, trnu, unh4, uno3)
    dynamic = INTEGR
    call NUPTAK(dynamic, dlayr, dul, filecc, kg2ppm, ll, ndmsdr, ndmtot, &
         nh4, no3, nlayr, rlv, sat, sw, trnh4u, trno3u, trnu, unh4, uno3)
    open(newunit=u, file='baseline.dat', status='old', action='read')
    read(u, *, iostat=ios) u1_sum
    close(u)
    write(*,'(A,ES14.6,A,ES14.6)') ' [diag] psi=', nb_get_uptake_psi(), &
         ' lux_sum=', sum(uno3(1:nlayr))
    call check(ios == 0 .and. u1_sum > 0.0, 'F0: baseline.dat available', nfail)
    call check(sum(uno3(1:nlayr)) < u1_sum, &
         'F1: luxury psi down-regulates uptake vs deficient psi', nfail)
    write(*,'(A,I0,A)') 'native_root_tests(lux): ', nfail, ' failure(s)'
    if (nfail > 0) stop 1
    stop 0
  end if

  !=====================================================================
  ! A. Mode 1 (no RootUptake.nml): frozen S1 behavior sanity
  !=====================================================================
  call execute_command_line('rm -f RootUptake.nml')
  dynamic = RUNINIT
  call NUPTAK(dynamic, dlayr, dul, filecc, kg2ppm, ll, ndmsdr, ndmtot, &
       nh4, no3, nlayr, rlv, sat, sw, trnh4u, trno3u, trnu, unh4, uno3)
  dynamic = SEASINIT
  call NUPTAK(dynamic, dlayr, dul, filecc, kg2ppm, ll, ndmsdr, ndmtot, &
       nh4, no3, nlayr, rlv, sat, sw, trnh4u, trno3u, trnu, unh4, uno3)
  dynamic = INTEGR
  call NUPTAK(dynamic, dlayr, dul, filecc, kg2ppm, ll, ndmsdr, ndmtot, &
       nh4, no3, nlayr, rlv, sat, sw, trnh4u, trno3u, trnu, unh4, uno3)
  call check(trnu > 0.0, 'A1: mode-1 TRNU positive', nfail)
  trnu_deficient = trnu
  uno3_deficient = sum(uno3(1:nlayr))

  !=====================================================================
  ! B. Mode 2 (RootUptake.nml present): v4-R2 kernel properties
  !=====================================================================
  open(newunit=u, file='RootUptake.nml', status='replace')
  write(u,'(A)') '&ROOTUPTAKE root_kernel=2, root_v=0.0002, '// &
       'root_k=10.0, diffusion_k=0.005 /'
  close(u)
  dynamic = RUNINIT
  call NUPTAK(dynamic, dlayr, dul, filecc, kg2ppm, ll, ndmsdr, ndmtot, &
       nh4, no3, nlayr, rlv, sat, sw, trnh4u, trno3u, trnu, unh4, uno3)
  dynamic = SEASINIT
  call NUPTAK(dynamic, dlayr, dul, filecc, kg2ppm, ll, ndmsdr, ndmtot, &
       nh4, no3, nlayr, rlv, sat, sw, trnh4u, trno3u, trnu, unh4, uno3)
  dynamic = INTEGR
  call NUPTAK(dynamic, dlayr, dul, filecc, kg2ppm, ll, ndmsdr, ndmtot, &
       nh4, no3, nlayr, rlv, sat, sw, trnh4u, trno3u, trnu, unh4, uno3)
  call check(trnu > 0.0, 'B1: mode-2 TRNU positive', nfail)
  call check(abs(sum(uno3(1:nlayr)) + sum(unh4(1:nlayr)) - 10.0*trnu) &
       <= 1.0e-3*max(1.0, 10.0*trnu), 'B2: layer sums conserve TRNU', nfail)
  call check(trnu /= trnu_deficient, 'B3: kernel 2 differs from kernel 1', nfail)

  ! per-layer bounds: uptake <= min(membrane at bulk, max supply)
  do i = 1, nlayr
    if (rlv(i) <= 1.0e-6) cycle
    c_l = (10.0 * (no3(i)/kg2ppm(i))) / (dlayr(i) * sw(i))
    if (sw(i) <= ll(i)) then
      wet_f = 0.0
    else if (sw(i) <= dul(i)) then
      wrel = (sw(i)-ll(i)) / max(1.0e-12, dul(i)-ll(i))
      wet_f = wrel
    else
      wet_f = max(0.0, min(1.0, (sat(i)-sw(i)) / max(1.0e-12, sat(i)-dul(i))))
    endif
    length_m = 100.0 * rlv(i) * dlayr(i)
    mf_g = 0.01 * max(0.0, rwu(i)) * c_l
    cap_g = length_m * 0.0002 * sqrt(wet_f)      ! psi<0 -> feedback = 1
    mem_c = cap_g * c_l / (10.0 + c_l)
    sup_max = mf_g + 0.001 * 0.005 * wet_f * length_m * c_l
    call check(uno3(i) <= 10.0*min(mem_c, sup_max) * (1.0 + 1.0e-3) + TOL, &
         'B4: uptake within membrane/supply bounds (layer)', nfail)
    call check(uno3(i) <= 10.0*(no3(i)/kg2ppm(i) - 0.25/kg2ppm(i)) + TOL, &
         'B5: uptake within extractable stock (layer)', nfail)
  enddo

  !=====================================================================
  ! C. Membrane saturation at high concentration (no additive double
  !    counting): uptake ~ cap, independent of C when C >> root_k.
  !    Asserted on the KERNEL ledger (pre-D_max ceiling values).
  !=====================================================================
  no3(1:4) = (/400.0, 300.0, 150.0, 60.0/)
  dynamic = INTEGR
  call NUPTAK(dynamic, dlayr, dul, filecc, kg2ppm, ll, ndmsdr, ndmtot, &
       nh4, no3, nlayr, rlv, sat, sw, trnh4u, trno3u, trnu, unh4, uno3)
  i = 1
  c_l = (10.0 * (no3(i)/kg2ppm(i))) / (dlayr(i) * sw(i))
  length_m = 100.0 * rlv(i) * dlayr(i)
  wet_f = (sw(i)-ll(i)) / (dul(i)-ll(i))
  sat_cap = 10.0 * length_m * 0.0002 * sqrt(wet_f)
  call check(c_l > 100.0*10.0, 'C0: saturation scenario is in high-C regime', nfail)
  call read_ledger_uptake(2, 1, u1_sum)   ! day 2, layer 1 -> g N/m2/d
  call check(abs(10.0*u1_sum - sat_cap) <= 0.05*sat_cap + TOL, &
       'C1: high-C kernel uptake saturates at membrane capacity', nfail)
  no3(1:4) = (/25.0, 18.0, 10.0, 4.0/)

  !=====================================================================
  ! D. Dry layer: SW = LL -> wet = 0 -> no uptake from that layer
  !=====================================================================
  sw(4) = ll(4)
  dynamic = INTEGR
  call NUPTAK(dynamic, dlayr, dul, filecc, kg2ppm, ll, ndmsdr, ndmtot, &
       nh4, no3, nlayr, rlv, sat, sw, trnh4u, trno3u, trnu, unh4, uno3)
  call check(uno3(4) <= TOL .and. unh4(4) <= TOL, &
       'D1: dry layer (SW=LL) takes up nothing', nfail)
  sw(4) = 0.32

  !=====================================================================
  ! E. Zero transpiration: pure-diffusion uptake, still bounded
  !=====================================================================
  rwu(1:4) = 0.0
  call PUT('SPAM', 'UH2O', rwu)
  dynamic = INTEGR
  call NUPTAK(dynamic, dlayr, dul, filecc, kg2ppm, ll, ndmsdr, ndmtot, &
       nh4, no3, nlayr, rlv, sat, sw, trnh4u, trno3u, trnu, unh4, uno3)
  call check(sum(uno3(1:nlayr)) > 0.0, &
       'E1: diffusion alone sustains positive uptake', nfail)
  u1_sum = sum(uno3(1:nlayr))
  rwu(1:4) = (/0.30, 0.15, 0.05, 0.01/)
  call PUT('SPAM', 'UH2O', rwu)
  dynamic = INTEGR
  call NUPTAK(dynamic, dlayr, dul, filecc, kg2ppm, ll, ndmsdr, ndmtot, &
       nh4, no3, nlayr, rlv, sat, sw, trnh4u, trno3u, trnu, unh4, uno3)
  u2_sum = sum(uno3(1:nlayr))
  call check(u2_sum > u1_sum, 'E2: mass flow adds to diffusion solution', nfail)

  !=====================================================================
  write(*,'(A,I0,A)') 'native_root_tests: ', nfail, ' failure(s)'
  if (nfail > 0) then
    stop 1
  end if
  ! Persist the deficient-psi reference uptake for the lux phase (E2
  ! state: normal NO3, mass-flow RWU restored).
  open(newunit=u, file='baseline.dat', status='replace')
  write(u, '(ES24.16)') u2_sum
  close(u)
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

  ! Read uptake_g_m2_d for (day_index, layer) from RootKernelLedger.csv
  subroutine read_ledger_uptake(day_want, layer_want, uptake_g)
    integer, intent(in) :: day_want, layer_want
    real, intent(out) :: uptake_g
    character(512) :: line
    integer :: u, ios, d, lyr, mode
    real :: c_v, rwu_v, len_v, wet_v, pool_v, mf_v, mem_v, cr_v, df_v, up_v, nh4_v
    uptake_g = -1.0
    open(newunit=u, file='RootKernelLedger.csv', status='old', action='read')
    do
      read(u, '(A)', iostat=ios) line
      if (ios /= 0) exit
      if (index(line, 'day_index') == 1) cycle
      read(line, *, iostat=ios) d, lyr, c_v, rwu_v, len_v, wet_v, pool_v, &
           mf_v, mem_v, cr_v, df_v, up_v, nh4_v, mode
      if (ios /= 0) cycle
      if (d == day_want .and. lyr == layer_want) then
        uptake_g = up_v
        exit
      end if
    end do
    close(u)
  end subroutine read_ledger_uptake
end program test_root_kernel

!=======================================================================
! Simplified DSSAT utility stubs so the test links without the full
! engine. The production build links the real Utilities routines; these
! cover only the semantics needed by the harness (simple file scan and
! unit allocation). The engine-level regression is the authority for
! the real I/O behavior.
!=======================================================================
subroutine GETLUN(FILEXT, LUN)
  implicit none
  character(*), intent(in) :: FILEXT
  integer, intent(out) :: LUN
  integer, save :: next_unit = 70
  integer, parameter :: NMAX = 16
  character(16), save :: names(NMAX) = ''
  integer, save :: units(NMAX) = 0
  integer, save :: n_used = 0
  integer :: i
  do i = 1, n_used
    if (names(i) == FILEXT) then
      LUN = units(i)
      return
    end if
  end do
  if (n_used < NMAX) then
    n_used = n_used + 1
    names(n_used) = FILEXT
    units(n_used) = next_unit
    next_unit = next_unit + 1
    LUN = units(n_used)
  else
    LUN = next_unit
    next_unit = next_unit + 1
  end if
end subroutine GETLUN

subroutine FIND(LUN, SECTION, LNUM, FOUND)
  implicit none
  integer, intent(in) :: LUN
  character(*), intent(in) :: SECTION
  integer, intent(out) :: LNUM, FOUND
  character(512) :: line
  integer :: ios
  rewind(LUN)
  LNUM = 0
  FOUND = 0
  do
    read(LUN, '(A)', iostat=ios) line
    if (ios /= 0) exit
    LNUM = LNUM + 1
    if (index(line, trim(SECTION)) == 1) then
      FOUND = 1
      return
    end if
  end do
end subroutine FIND

subroutine IGNORE(LUN, LNUM, ISECT, CHAR)
  implicit none
  integer, intent(in) :: LUN
  integer, intent(inout) :: LNUM
  integer, intent(out) :: ISECT
  character(*), intent(out) :: CHAR
  character(512) :: line
  integer :: ios
  CHAR = ' '
  read(LUN, '(A)', iostat=ios) line
  if (ios == 0) then
    ISECT = 1
    CHAR = trim(line)
    LNUM = LNUM + 1
  else
    ISECT = 0
  end if
end subroutine IGNORE

subroutine ERROR(ERRKEY, ERRNUM, FILEX, LNUM)
  implicit none
  character(*), intent(in) :: ERRKEY
  integer, intent(in) :: ERRNUM
  character(*), intent(in) :: FILEX
  integer, intent(in) :: LNUM
  write(*,'(A,I0,A,A,A,I0)') 'ERROR stub: ', ERRNUM, ' in ', trim(ERRKEY), &
       ' file/line ', LNUM
  write(*,'(A)') 'file: ' // trim(FILEX)
  stop 9
end subroutine ERROR

subroutine WARNING(NUMMSG, KEY, MSG)
  implicit none
  integer, intent(in) :: NUMMSG
  character(*), intent(in) :: KEY
  character(*), intent(in) :: MSG(*)
  integer :: i
  write(*,'(A)') 'WARNING stub (' // trim(KEY) // '):'
  do i = 1, NUMMSG
    write(*,'(A)') '  ' // trim(MSG(i))
  end do
end subroutine WARNING
