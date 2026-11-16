!> test_root_n_uptake_B.f90 — T3 径向运输 B 数值验收 (计划 §5)
program test_root_n_uptake_B
   use RootNUptake
   implicit none

   type(rnk_params) :: par
   type(rnk_layer) :: lay
   type(rnk_diag) :: dg(RNK_NSPECIES)
   real(rnk_dp) :: kg2ppm, c_base, c_fine, rel
   integer :: nfail

   nfail = 0
   par%km_high(RNK_NO3) = 0.28_rnk_dp;  par%km_low(RNK_NO3) = 35.0_rnk_dp
   par%vmax_high(RNK_NO3) = 0.0003_rnk_dp; par%vmax_low(RNK_NO3) = 0.0015_rnk_dp
   par%kd_sorption(RNK_NO3) = 0._rnk_dp
   par%residual_ppm(RNK_NO3) = 0.25_rnk_dp
   par%source_tag(RNK_NO3) = 'synthetic'
   par%km_high(RNK_NH4) = 0.5_rnk_dp;   par%km_low(RNK_NH4) = 50.0_rnk_dp
   par%vmax_high(RNK_NH4) = 0.0004_rnk_dp; par%vmax_low(RNK_NH4) = 0.0020_rnk_dp
   par%kd_sorption(RNK_NH4) = 1.0_rnk_dp
   par%residual_ppm(RNK_NH4) = 0.50_rnk_dp
   par%source_tag(RNK_NH4) = 'literature-prior'
   par%root_radius_m = 1.0e-4_rnk_dp

   kg2ppm = 1._rnk_dp/(1.3_rnk_dp*0.1_rnk_dp*20._rnk_dp)
   lay%bd = 1.3_rnk_dp; lay%kg2ppm = kg2ppm; lay%dlayr = 20._rnk_dp
   lay%p(RNK_NO3) = 10._rnk_dp*kg2ppm
   lay%p(RNK_NH4) = 10._rnk_dp*kg2ppm
   lay%theta0 = 0.255_rnk_dp; lay%rwu = 0.20_rnk_dp
   lay%rlv = 1.0_rnk_dp; lay%f_root = 1._rnk_dp; lay%porosity=0.45_rnk_dp

   ! ---- 1. 无氮 → ZERO ----
   block
      type(rnk_layer) :: l; type(rnk_diag) :: d(RNK_NSPECIES)
      l = lay; l%p(RNK_NO3) = 0._rnk_dp
      call rnk_layer_B(par, l, d)
      call check('B no-N branch ZERO & cand 0', d(RNK_NO3)%branch == RNK_BRANCH_ZERO .and. &
                 d(RNK_NO3)%candidate == 0._rnk_dp, d(RNK_NO3)%candidate, 0._rnk_dp, nfail)
   end block

   ! ---- 2. 无根 → ZERO ----
   block
      type(rnk_layer) :: l; type(rnk_diag) :: d(RNK_NSPECIES)
      l = lay; l%rlv = 0._rnk_dp
      call rnk_layer_B(par, l, d)
      call check('B no-root ZERO', d(RNK_NO3)%branch == RNK_BRANCH_ZERO, 0._rnk_dp, 0._rnk_dp, nfail)
   end block

   ! ---- 3. 膜全关 (f_root=0) → ZERO ----
   block
      type(rnk_layer) :: l; type(rnk_diag) :: d(RNK_NSPECIES)
      l = lay; l%f_root = 0._rnk_dp
      call rnk_layer_B(par, l, d)
      call check('B closed membrane ZERO', d(RNK_NO3)%branch == RNK_BRANCH_ZERO, 0._rnk_dp, 0._rnk_dp, nfail)
   end block

   ! ---- 4. 零水纯扩散: uptake>0, 质量闭合; 关扩散则仅耗内单元 ----
   block
      type(rnk_layer) :: l; type(rnk_diag) :: d(RNK_NSPECIES), d0(RNK_NSPECIES)
      type(rnk_params) :: p0
      l = lay; l%rwu = 0._rnk_dp
      call rnk_layer_B(par, l, d)
      call check('B pure-diffusion uptake > 0', d(RNK_NO3)%candidate > 0._rnk_dp, &
                 d(RNK_NO3)%candidate, 1._rnk_dp, nfail)
      call check('B pure-diffusion mass closure', abs(d(RNK_NO3)%mass_error) < 1.e-9_rnk_dp, &
                 d(RNK_NO3)%mass_error, 0._rnk_dp, nfail)
      call check('B pure-diffusion c_root < c_bulk (depletion)', d(RNK_NO3)%c_root < d(RNK_NO3)%c_bulk, &
                 d(RNK_NO3)%c_root, d(RNK_NO3)%c_bulk, nfail)
      p0 = par; p0%species_diffusion_m2d = 0._rnk_dp
      call rnk_layer_B(p0, l, d0)
      call check('B D=0 uptake < D>0 uptake (diffusion supplies)', &
                 d0(RNK_NO3)%candidate < d(RNK_NO3)%candidate, &
                 d0(RNK_NO3)%candidate, d(RNK_NO3)%candidate, nfail)
      call check('B D=0 mass closure', abs(d0(RNK_NO3)%mass_error) < 1.e-9_rnk_dp, &
                 d0(RNK_NO3)%mass_error, 0._rnk_dp, nfail)
   end block

   ! ---- 5. Weak membrane: integral is close to the rate at mean root concentration ----
   block
      type(rnk_layer) :: l; type(rnk_diag) :: d(RNK_NSPECIES)
      type(rnk_params) :: pw
      real(rnk_dp) :: mean_rate
      pw = par; pw%vmax_high(RNK_NO3) = 3.e-7_rnk_dp; pw%vmax_low(RNK_NO3) = 1.5e-6_rnk_dp
      l = lay
      call rnk_layer_B(pw, l, d)
      mean_rate = rnk_membrane(pw, RNK_NO3, d(RNK_NO3)%c_root_mean, d(RNK_NO3)%root_length, &
                         l%f_root, 1._rnk_dp, 1._rnk_dp)
      call check('B weak membrane: uptake agrees with mean root concentration', &
                 abs(d(RNK_NO3)%candidate - mean_rate) <= 0.01_rnk_dp*mean_rate, d(RNK_NO3)%candidate, mean_rate, nfail)
      call check('B weak membrane: mean root enrichment under actual water uptake', &
                 d(RNK_NO3)%c_root_mean > d(RNK_NO3)%c_bulk_mean, &
                 d(RNK_NO3)%c_root_mean, d(RNK_NO3)%c_bulk_mean, nfail)
      call check('B weak membrane mass closure', abs(d(RNK_NO3)%mass_error) < 1.e-9_rnk_dp, &
                 d(RNK_NO3)%mass_error, 0._rnk_dp, nfail)
   end block

   ! ---- 6. NH4 吸附缓冲: 同库存 Kd=1 吸收慢于 Kd=0 ----
   block
      type(rnk_layer) :: l; type(rnk_diag) :: d(RNK_NSPECIES)
      type(rnk_params) :: pk
      pk = par; pk%kd_sorption(RNK_NH4) = 0._rnk_dp
      l = lay; l%rwu = 0.02_rnk_dp          ! 弱质流, 扩散补给主导 → 吸附延迟可见
      call rnk_layer_B(par, l, d)           ! Kd=1
      call rnk_layer_B(pk, l, dg)           ! Kd=0 (dg 复用)
      call check('B NH4 sorption buffers uptake (Kd1 < Kd0)', &
                 d(RNK_NH4)%candidate < dg(RNK_NH4)%candidate, &
                 d(RNK_NH4)%candidate, dg(RNK_NH4)%candidate, nfail)
      call check('B NH4 mass closure both', &
                 abs(d(RNK_NH4)%mass_error) < 1.e-9_rnk_dp .and. abs(dg(RNK_NH4)%mass_error) < 1.e-9_rnk_dp, &
                 d(RNK_NH4)%mass_error + dg(RNK_NH4)%mass_error, 0._rnk_dp, nfail)
   end block

   ! ---- 7. The cap must affect the radial solution, not just the returned candidate. ----
   block
      type(rnk_layer) :: l
      type(rnk_diag) :: d(RNK_NSPECIES), uncapped(RNK_NSPECIES)
      type(rnk_params) :: no_floor
      integer :: species
      l = lay
      l%p = [0.30_rnk_dp, 0.51_rnk_dp]
      no_floor = par
      no_floor%residual_ppm = 0._rnk_dp
      call rnk_layer_B(par, l, d)
      call rnk_layer_B(no_floor, l, uncapped)
      do species = 1, RNK_NSPECIES
         call check('B small-stock capped', d(species)%stock_capped, 1._rnk_dp, 1._rnk_dp, nfail)
         call check('B small-stock candidate == cap', &
                    abs(d(species)%candidate - d(species)%stock_cap) < 1.e-12_rnk_dp, &
                    d(species)%candidate, d(species)%stock_cap, nfail)
         call check('B cap is inside the mass balance', abs(d(species)%mass_error) < 1.e-9_rnk_dp, &
                    d(species)%mass_error, 0._rnk_dp, nfail)
         call check('B cap affects the solved root concentration', d(species)%c_root > uncapped(species)%c_root, &
                    d(species)%c_root, uncapped(species)%c_root, nfail)
      end do
   end block

   ! ---- 8. 无液相 → UNDEFINED ----
   block
      type(rnk_layer) :: l; type(rnk_diag) :: d(RNK_NSPECIES)
      l = lay; l%theta0 = 0.002_rnk_dp; l%rwu = 0.10_rnk_dp
      call rnk_layer_B(par, l, d)
      call check('B no-liquid UNDEFINED', d(RNK_NO3)%branch == RNK_BRANCH_UNDEFINED, 0._rnk_dp, 0._rnk_dp, nfail)
   end block

   ! ---- 9. Fixed 16-cell time-step comparison ----
   call rnk_layer_B(par, lay, dg, n_cells=16, n_substeps=24)
   c_base = dg(RNK_NO3)%candidate
   call rnk_layer_B(par, lay, dg, n_cells=16, n_substeps=48)
   c_fine = dg(RNK_NO3)%candidate
   rel = abs(c_fine - c_base)/max(max(abs(c_fine), abs(c_base)), 1.e-30_rnk_dp)
   call check('B fixed-grid step refinement <= 1% or 0.001', &
              rel <= 0.01_rnk_dp .or. abs(c_fine - c_base) <= 1.0e-3_rnk_dp, &
              c_base, c_fine, nfail)
   write (*, '(a,2es16.6)') '     coarse/fine daily candidates: ', c_base, c_fine

   ! ---- 10. 求解器状态与质量闭合 (基准工况) ----
   call rnk_layer_B(par, lay, dg)
   call check('B starts from pre-extraction water', &
              abs(dg(RNK_NO3)%c_bulk - 1._rnk_dp/(0.2_rnk_dp*lay%theta0)) < 1.e-10_rnk_dp, &
              dg(RNK_NO3)%c_bulk, 1._rnk_dp/(0.2_rnk_dp*lay%theta0), nfail)
   call check('B reports the separate midpoint', abs(dg(RNK_NO3)%theta_mid - 0.25_rnk_dp) < 1.e-10_rnk_dp, &
              dg(RNK_NO3)%theta_mid, 0.25_rnk_dp, nfail)
   call check('B baseline converged (solver_flag=0)', dg(RNK_NO3)%solver_flag == 0, 0._rnk_dp, 0._rnk_dp, nfail)
   call check('B baseline mass closure', abs(dg(RNK_NO3)%mass_error) < 1.e-9_rnk_dp, &
              dg(RNK_NO3)%mass_error, 0._rnk_dp, nfail)
   call check('B baseline branch RADIAL', dg(RNK_NO3)%branch == RNK_BRANCH_RADIAL, 3._rnk_dp, 3._rnk_dp, nfail)
   call check('B baseline cand within stock_cap', dg(RNK_NO3)%candidate <= dg(RNK_NO3)%stock_cap + 1.e-12_rnk_dp, &
              dg(RNK_NO3)%candidate, dg(RNK_NO3)%stock_cap, nfail)
   write (*, '(a,3es16.6)') '     cand/mf/diff: ', dg(RNK_NO3)%candidate, dg(RNK_NO3)%mf_potential, &
      dg(RNK_NO3)%diffusive_flux

   ! The paired profile must pass identical soil concentrations, diffusion and
   ! stock ceilings to both transport formulations.
   block
      type(rnk_layer) :: l
      type(rnk_params) :: common
      type(rnk_diag) :: a(RNK_NSPECIES), b(RNK_NSPECIES)
      real(rnk_dp) :: db, cb, deficit
      integer :: species
      common = par
      l = lay
      l%porosity = 0.45_rnk_dp
      call rnk_layer_A(common, l, a)
      call rnk_layer_B(common, l, b)
      do species = 1, RNK_NSPECIES
         db = common%species_diffusion_m2d(species)*a(species)%theta_mid**(10._rnk_dp/3._rnk_dp)/l%porosity**2
         cb = l%p(species)*l%bd/(l%theta0 + l%bd*common%kd_sorption(species))
         call check('paired: same initial equilibrium concentration', a(species)%c_bulk == b(species)%c_bulk .and. &
                    abs(a(species)%c_bulk - cb) < 1.e-12_rnk_dp, a(species)%c_bulk, cb, nfail)
         call check('paired: same Millington-Quirk bulk diffusion', a(species)%bulk_diffusion == b(species)%bulk_diffusion .and. &
                    abs(b(species)%bulk_diffusion - db) < 1.e-15_rnk_dp, b(species)%bulk_diffusion, db, nfail)
         call check('paired: same stock ceiling', a(species)%stock_cap == b(species)%stock_cap, &
                    a(species)%stock_cap, b(species)%stock_cap, nfail)
         deficit = min(rnk_membrane(common, species, a(species)%c_root, a(species)%root_length, &
                   l%f_root, 1._rnk_dp, 1._rnk_dp), a(species)%stock_cap) - &
                   (a(species)%mf_potential + a(species)%diffusive_flux)
         call check('paired: steady root boundary closes', abs(deficit) < 1.e-10_rnk_dp, deficit, 0._rnk_dp, nfail)
         call check('paired: dynamic root boundary conserves stock', abs(b(species)%mass_error) < 1.e-9_rnk_dp .and. &
                    b(species)%solver_flag == 0 .and. b(species)%candidate > 0._rnk_dp, b(species)%mass_error, 0._rnk_dp, nfail)
      end do
      l%theta0 = 0.09_rnk_dp
      l%rwu = 0._rnk_dp
      call rnk_layer_A(common, l, a)
      call rnk_layer_B(common, l, b)
      call check('paired: liquid below LL permits pure diffusion', a(RNK_NO3)%candidate > 0._rnk_dp .and. &
                 b(RNK_NO3)%candidate > 0._rnk_dp, b(RNK_NO3)%candidate, 0._rnk_dp, nfail)
   end block

   if (nfail > 0) then
      write (*, '(a,i0,a)') 'FAIL: ', nfail, ' check(s) failed'
      error stop 1
   end if
   write (*, '(a)') 'ALL B TESTS PASSED'

contains

   subroutine check(name, ok, got, want, nfail)
      character(len=*), intent(in) :: name
      logical, intent(in) :: ok
      real(rnk_dp), intent(in) :: got, want
      integer, intent(inout) :: nfail
      if (.not. ok) then
         nfail = nfail + 1
         write (*, '(a,a,a,es16.8,a,es16.8)') 'FAIL: ', name, '  got=', got, ' want=', want
      else
         write (*, '(a,a)') 'ok  : ', name
      end if
   end subroutine check

end program test_root_n_uptake_B
