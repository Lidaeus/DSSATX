!> test_root_n_uptake.f90 — T1 单层单元测试
!! 手算基准来自执行计划 §3.2-5:
!!   层厚20cm, theta_mid=0.25, NO3 10 kg N/ha, RWU=0.20 cm/d
!!   → Cb=20 mg/L, MF=0.40 kg N/ha/d (=0.04 g/m2/d)
!!   同库存 NH4, BD=1.30, Kd=1.0 → Cb≈3.226 mg/L
program test_root_n_uptake
   use ieee_arithmetic, only: ieee_value, ieee_positive_inf, ieee_quiet_nan
   use RootNUptake
   implicit none

   type(rnk_params) :: par
   type(rnk_layer) :: lay
   type(rnk_diag) :: dg(RNK_NSPECIES)
   real(rnk_dp) :: kg2ppm, tol, res
   integer :: nfail

   nfail = 0
   tol = 1.e-9_rnk_dp

   ! ---- 工程参数 (SYNTHETIC/先验, 供单测; 田间重放须替换为登记参数) ----
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

   ! ---- 基准层: BD=1.30, dz=20cm, 10 kg N/ha → p=10*KG2PPM ----
   kg2ppm = 1._rnk_dp/(1.3_rnk_dp*0.1_rnk_dp*20._rnk_dp)   ! = 1/2.6
   lay%bd = 1.3_rnk_dp; lay%kg2ppm = kg2ppm; lay%dlayr = 20._rnk_dp
   lay%p(RNK_NO3) = 10._rnk_dp*kg2ppm      ! 3.846154 mg/kg
   lay%p(RNK_NH4) = 10._rnk_dp*kg2ppm
   lay%theta0 = 0.25_rnk_dp; lay%rwu = 0.20_rnk_dp         ! theta_mid = 0.245
   lay%rlv = 1.0_rnk_dp                                     ! Lr = 2000 m/m2
   lay%f_root = 1._rnk_dp
   lay%porosity = 0.45_rnk_dp
   par%species_diffusion_m2d = 0._rnk_dp                   ! Pure mass flow with membrane uptake

   ! ---- 1. NO3 手算: Cb=20, MF=0.04 g/m2/d, 二分分支 ----
   call rnk_layer_A(par, lay, dg)
   call check('NO3 Cb==20', abs(dg(RNK_NO3)%c_bulk - 20._rnk_dp) < 1.e-9_rnk_dp, &
              dg(RNK_NO3)%c_bulk, 20._rnk_dp, nfail)
   call check('NO3 MF==0.04 g/m2/d (0.40 kg/ha/d)', &
              abs(dg(RNK_NO3)%mf_potential - 0.04_rnk_dp) < 1.e-12_rnk_dp, &
              dg(RNK_NO3)%mf_potential, 0.04_rnk_dp, nfail)
   call check('NO3 branch==BISECT', dg(RNK_NO3)%branch == RNK_BRANCH_BISECT, &
              real(dg(RNK_NO3)%branch, rnk_dp), 2._rnk_dp, nfail)
   call check('NO3 theta_mid==0.245', abs(dg(RNK_NO3)%theta_mid - 0.245_rnk_dp) < tol, &
              dg(RNK_NO3)%theta_mid, 0.245_rnk_dp, nfail)
   ! 联立平衡残差 |U(Cr) - MF| (G=0) 应接近 0
   res = abs(rnk_membrane(par, RNK_NO3, dg(RNK_NO3)%c_root, dg(RNK_NO3)%root_length, &
              lay%f_root, 1._rnk_dp, 1._rnk_dp) - dg(RNK_NO3)%mf_potential)
   call check('NO3 bisection residual ~ 0', res < 1.e-6_rnk_dp, res, 0._rnk_dp, nfail)

   ! ---- 2. NH4 手算: Cb≈3.2258 (Kd=1.0 吸附缓冲) ----
   call check('NH4 Cb==3.2258', abs(dg(RNK_NH4)%c_bulk - 3.225806451612903_rnk_dp) < 1.e-9_rnk_dp, &
              dg(RNK_NH4)%c_bulk, 3.225806451612903_rnk_dp, nfail)

   ! ---- 3. 库存上限: NO3 残留 0.25 ppm 之上的可提取量 ----
   ! cap = (p-0.25)/KG2PPM/10 = (3.846154-0.25)*2.6/10 = 0.935 g/m2 (= 10-0.65 kg/ha)
   call check('NO3 stock_cap==0.935 g/m2', &
              abs(dg(RNK_NO3)%stock_cap - 0.935_rnk_dp) < 1.e-9_rnk_dp, &
              dg(RNK_NO3)%stock_cap, 0.935_rnk_dp, nfail)

   ! ---- 4. 库存裁剪: 低氮层 + 大扩散导度使膜/供给超过库存 → 候选截断 ----
   block
      type(rnk_layer) :: l2
      type(rnk_diag) :: d2(RNK_NSPECIES), uncapped(RNK_NSPECIES)
      type(rnk_params) :: diffusive, no_floor
      l2 = lay; l2%p = par%residual_ppm + 0.0001_rnk_dp
      diffusive = par; diffusive%species_diffusion_m2d(RNK_NO3) = 1.64e-4_rnk_dp
      call rnk_layer_A(diffusive, l2, d2)
      call check('low-N capped flag', d2(RNK_NO3)%stock_capped, 1._rnk_dp, 1._rnk_dp, nfail)
      call check('low-N candidate==cap', &
                 abs(d2(RNK_NO3)%candidate - d2(RNK_NO3)%stock_cap) < 1.e-12_rnk_dp, &
                 d2(RNK_NO3)%candidate, d2(RNK_NO3)%stock_cap, nfail)
      no_floor = diffusive
      no_floor%residual_ppm = 0
      call rnk_layer_A(no_floor, l2, uncapped)
      call check('stock cap below mass flow for both ions', all(d2%stock_cap<d2%mf_potential), 0._rnk_dp, 0._rnk_dp, nfail)
      call check('low-N candidates equal cap', all(d2%candidate==d2%stock_cap), 0._rnk_dp, 0._rnk_dp, nfail)
      call check('stock cap preserves root concentration', all(d2%c_root==uncapped%c_root), 0._rnk_dp, 0._rnk_dp, nfail)
      call check('root concentration bounded and diffusion inward', all(d2%c_root<=d2%c_bulk).and.all(d2%diffusive_flux>=0), &
                 0._rnk_dp, 0._rnk_dp, nfail)
      call check('uncapped balance closes', maxval(abs(d2%steady_residual))<1.e-12_rnk_dp, 0._rnk_dp, 0._rnk_dp, nfail)
      l2%p = [par%residual_ppm(RNK_NO3), 0.9_rnk_dp*par%residual_ppm(RNK_NH4)]
      call rnk_layer_A(diffusive, l2, d2)
      call check('at or below residual: no solve and no uptake', &
                 all(d2%branch==RNK_BRANCH_ZERO).and.all(d2%candidate==0), 0._rnk_dp, 0._rnk_dp, nfail)
      l2 = lay
      l2%rlv = 1.e-4_rnk_dp
      call rnk_layer_A(diffusive, l2, d2)
      call check('positive diffusion permits membrane limitation', all(d2%branch==RNK_BRANCH_MEMBRANE), &
                 0._rnk_dp, 0._rnk_dp, nfail)
      call check('membrane limitation uses bulk concentration', all(d2%c_root==d2%c_bulk).and.all(d2%diffusive_flux==0), &
                 0._rnk_dp, 0._rnk_dp, nfail)
   end block

   block
      type(rnk_params) :: invalid
      call check('valid parameters', rnk_validate(par,1)=='', 0._rnk_dp, 0._rnk_dp, nfail)
      invalid=par
      invalid%root_radius_m=0
      call check('reject zero radius', rnk_validate(invalid,1)/='', 0._rnk_dp, 0._rnk_dp, nfail)
      invalid%root_radius_m=ieee_value(0._rnk_dp,ieee_quiet_nan)
      call check('reject NaN radius', rnk_validate(invalid,1)/='', 0._rnk_dp, 0._rnk_dp, nfail)
      invalid=par
      invalid%species_diffusion_m2d(1)=-1
      call check('reject negative diffusivity', rnk_validate(invalid,1)/='', 0._rnk_dp, 0._rnk_dp, nfail)
      invalid%species_diffusion_m2d(1)=ieee_value(0._rnk_dp,ieee_positive_inf)
      call check('reject infinite diffusivity', rnk_validate(invalid,1)/='', 0._rnk_dp, 0._rnk_dp, nfail)
      invalid=par
      invalid%penetration_coeff=-1
      call check('reject negative penetration coefficient', rnk_validate(invalid,1)/='', 0._rnk_dp, 0._rnk_dp, nfail)
      invalid%penetration_coeff=ieee_value(0._rnk_dp,ieee_quiet_nan)
      call check('reject NaN penetration coefficient', rnk_validate(invalid,1)/='', 0._rnk_dp, 0._rnk_dp, nfail)
   end block

   block
      type(rnk_params) :: corrected
      type(rnk_layer) :: l
      type(rnk_diag) :: result(RNK_NSPECIES)
      corrected=par
      corrected%penetration_coeff=1.5_rnk_dp
      l=lay
      call rnk_layer_A(corrected,l,result)
      call check('zero diffusion preserves the mass-flow result', all(result%candidate==dg%candidate), &
                 0._rnk_dp, 0._rnk_dp, nfail)
      corrected%species_diffusion_m2d=1.5e-4_rnk_dp
      l%rwu=0
      call rnk_layer_A(corrected,l,result)
      call check('zero water uptake permits bounded diffusion', all(result%candidate>=0).and.all(result%c_root<=result%c_bulk), &
                 0._rnk_dp, 0._rnk_dp, nfail)
      l%rlv=0
      call rnk_layer_A(corrected,l,result)
      call check('correction gives zero uptake without roots', all(result%candidate==0), 0._rnk_dp, 0._rnk_dp, nfail)
      l%rlv=lay%rlv; l%theta0=0
      call rnk_layer_A(corrected,l,result)
      call check('correction gives zero uptake without liquid', all(result%candidate==0), 0._rnk_dp, 0._rnk_dp, nfail)
   end block

   ! ---- 5. 膜不限制分支: 极小根长 U(Cb)<=MF → Cr=Cb ----
   block
      type(rnk_layer) :: l3
      type(rnk_diag) :: d3(RNK_NSPECIES)
      l3 = lay; l3%rlv = 1.e-4_rnk_dp       ! Lr=0.2 m/m2
      call rnk_layer_A(par, l3, d3)
      call check('small-root branch==MEMBRANE', d3(RNK_NO3)%branch == RNK_BRANCH_MEMBRANE, &
                 real(d3(RNK_NO3)%branch, rnk_dp), 1._rnk_dp, nfail)
      call check('small-root Cr==Cb', abs(d3(RNK_NO3)%c_root - d3(RNK_NO3)%c_bulk) < tol, &
                 d3(RNK_NO3)%c_root, d3(RNK_NO3)%c_bulk, nfail)
   end block

   ! ---- 6. 无液相: theta_mid<0 → 吸收0, UNDEFINED ----
   block
      type(rnk_layer) :: l4
      type(rnk_diag) :: d4(RNK_NSPECIES)
      l4 = lay; l4%theta0 = 0.002_rnk_dp; l4%rwu = 0.10_rnk_dp  ! theta_mid<0
      call rnk_layer_A(par, l4, d4)
      call check('no-liquid branch==UNDEFINED', d4(RNK_NO3)%branch == RNK_BRANCH_UNDEFINED, &
                 real(d4(RNK_NO3)%branch, rnk_dp), -1._rnk_dp, nfail)
      call check('no-liquid candidate==0', d4(RNK_NO3)%candidate == 0._rnk_dp, &
                 d4(RNK_NO3)%candidate, 0._rnk_dp, nfail)
   end block

   ! ---- 7. 零根/零氮 → ZERO 分支 ----
   block
      type(rnk_layer) :: l5
      type(rnk_diag) :: d5(RNK_NSPECIES)
      l5 = lay; l5%rlv = 0._rnk_dp
      call rnk_layer_A(par, l5, d5)
      call check('zero-root branch==ZERO', d5(RNK_NO3)%branch == RNK_BRANCH_ZERO, &
                 real(d5(RNK_NO3)%branch, rnk_dp), 0._rnk_dp, nfail)
      l5 = lay; l5%p(RNK_NO3) = 0._rnk_dp; l5%rlv = 1._rnk_dp
      call rnk_layer_A(par, l5, d5)
      call check('zero-N branch==ZERO', d5(RNK_NO3)%branch == RNK_BRANCH_ZERO, &
                 real(d5(RNK_NO3)%branch, rnk_dp), 0._rnk_dp, nfail)
   end block

   ! ---- 8. 饱和封顶: 高浓度下 candidate ≤ Lr*(fH*VH+fL*VL) ----
   block
      type(rnk_layer) :: l6
      type(rnk_diag) :: d6(RNK_NSPECIES)
      l6 = lay; l6%p(RNK_NO3) = 1.e6_rnk_dp  ! Cb 极大
      call rnk_layer_A(par, l6, d6)
      call check('saturation cap honored', &
                 d6(RNK_NO3)%candidate <= 2000._rnk_dp*(0.0003_rnk_dp + 0.0015_rnk_dp)*(1 + 1.e-9), &
                 d6(RNK_NO3)%candidate, 3.6_rnk_dp, nfail)
      call check('saturation >90% of cap', &
                 d6(RNK_NO3)%candidate > 0.9_rnk_dp*2000._rnk_dp*(0.0003_rnk_dp + 0.0015_rnk_dp), &
                 d6(RNK_NO3)%candidate, 3.24_rnk_dp, nfail)
   end block

   ! ---- 9. 浓度单调性 ----
   block
      type(rnk_layer) :: l7
      type(rnk_diag) :: d7(RNK_NSPECIES)
      real(rnk_dp) :: u_lo
      u_lo = dg(RNK_NO3)%candidate
      l7 = lay; l7%p(RNK_NO3) = 2._rnk_dp*lay%p(RNK_NO3)
      call rnk_layer_A(par, l7, d7)
      call check('monotone in stock (G=0: MF doubles)', d7(RNK_NO3)%candidate > u_lo, &
                 d7(RNK_NO3)%candidate, u_lo, nfail)
   end block

   ! ---- 10. 扩散补给分支: RWU=0, G>0 → U(Cr)=G*(Cb-Cr) ----
   block
      type(rnk_layer) :: l8
      type(rnk_diag) :: d8(RNK_NSPECIES)
      real(rnk_dp) :: resid
      type(rnk_params) :: diffusive, no_floor
      l8 = lay; l8%rwu = 0._rnk_dp
      diffusive = par; diffusive%species_diffusion_m2d(RNK_NO3) = 1.64e-4_rnk_dp
      call rnk_layer_A(diffusive, l8, d8)
      call check('pure-diffusion branch==BISECT', d8(RNK_NO3)%branch == RNK_BRANCH_BISECT, &
                 real(d8(RNK_NO3)%branch, rnk_dp), 2._rnk_dp, nfail)
      resid = abs(rnk_membrane(par, RNK_NO3, d8(RNK_NO3)%c_root, d8(RNK_NO3)%root_length, &
                 l8%f_root, 1._rnk_dp, 1._rnk_dp) - d8(RNK_NO3)%diffusive_flux)
      call check('pure-diffusion residual ~ 0', resid < 1.e-6_rnk_dp, resid, 0._rnk_dp, nfail)
      call check('pure-diffusion MF==0', d8(RNK_NO3)%mf_potential == 0._rnk_dp, &
                 d8(RNK_NO3)%mf_potential, 0._rnk_dp, nfail)
   end block

   ! ---- 11. 参数校验 ----
   block
      character(len=160) :: msg
      msg = rnk_validate(par, 1)
      call check('validate ok on good params', len_trim(msg) == 0, 0._rnk_dp, 0._rnk_dp, nfail)
      msg = rnk_validate(par, 0)
      call check('validate rejects nlayr<=0', len_trim(msg) > 0, 1._rnk_dp, 1._rnk_dp, nfail)
      block
         type(rnk_params) :: bad
         bad = par; bad%km_low(RNK_NO3) = 0.1_rnk_dp  ! 破坏 0<KH<KL
         msg = rnk_validate(bad, 1)
         call check('validate rejects km order', len_trim(msg) > 0, 1._rnk_dp, 1._rnk_dp, nfail)
         bad = par; bad%source_tag(RNK_NH4) = 'unset'
         msg = rnk_validate(bad, 1)
         call check('validate rejects unset source_tag', len_trim(msg) > 0, 1._rnk_dp, 1._rnk_dp, nfail)
      end block
   end block

   if (nfail > 0) then
      write (*, '(a,i0,a)') 'FAIL: ', nfail, ' check(s) failed'
      error stop 1
   end if
   write (*, '(a)') 'ALL TESTS PASSED'

contains

   subroutine check(name, ok, got, want, nfail)
      character(len=*), intent(in) :: name
      logical, intent(in) :: ok
      real(rnk_dp), intent(in) :: got, want
      integer, intent(inout) :: nfail
      if (.not. ok) then
         nfail = nfail + 1
         write (*, '(a,a,a,es16.8,a,es16.8)') 'FAIL: ', name, '  got=', got, '  want=', want
      else
         write (*, '(a,a)') 'ok  : ', name
      end if
   end subroutine check

end program test_root_n_uptake
