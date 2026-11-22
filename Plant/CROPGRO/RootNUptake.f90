!> RootNUptake.f90 — 公共根系吸氮核（执行计划 T1, 2026-11-12）
!!
!! 双形态（NO3-, NH4+）独立参数双亲和米氏跨膜动力学 + 等效根际运输 A 臂
!! （质流 + 浓度差扩散代数根表平衡, 64 步区间二分）。
!!
!! 设计约束（DSSAT_root_nitrogen_execution_plan.md §3）:
!!  * 纯计算模块: 不依赖 ModuleData / CROPGRO 全局状态 / 文件 IO。
!!  * 内部单位: g N m^-2 (ground) 与 d; 形态浓度 mg N L^-1 (孔隙水);
!!    土层几何 cm/ cm3 cm-3 / kg L-1, 适配层负责底座单位换算。
!!  * 形态顺序: 1=NO3-, 2=NH4+。
!!  * 无液相且零取水: 净吸收为零, 浓度诊断标记不可定义;
!!    含水率低但液相存在: 照常计算, 运输与根活性因子由适配层给出。
module RootNUptake
   use ieee_arithmetic, only: ieee_is_finite
   implicit none
   private

   integer, parameter, public :: rnk_dp = selected_real_kind(15, 307)
   integer, parameter, public :: RNK_NO3 = 1, RNK_NH4 = 2
   integer, parameter, public :: RNK_NSPECIES = 2

   !> 运输模式: 0=关闭(沿用底座冻结行为, 适配层不调用本核)
   integer, parameter, public :: RNK_MODE_OFF = 0
   !> A: 等效根际运输(质流+代数扩散补给, 根表准稳态)
   integer, parameter, public :: RNK_MODE_A = 1

   !> 求解分支标签
   integer, parameter, public :: RNK_BRANCH_UNDEFINED = -1 ! 无液相/浓度不可定义
   integer, parameter, public :: RNK_BRANCH_ZERO = 0        ! 零根/零浓度/零参数 → 净吸收 0
   integer, parameter, public :: RNK_BRANCH_MEMBRANE = 1    ! U(Cb)<=MF: Cr=Cb, 膜限速
   integer, parameter, public :: RNK_BRANCH_BISECT = 2      ! 64 步二分联立平衡

   type, public :: rnk_params
      !> 米氏半饱和浓度 mg N L^-1 (孔隙水), 按形态
      real(rnk_dp) :: km_high(RNK_NSPECIES) = 0._rnk_dp
      real(rnk_dp) :: km_low(RNK_NSPECIES) = 0._rnk_dp
      !> 最大吸收速率 g N m^-1 root d^-1, 按形态
      real(rnk_dp) :: vmax_high(RNK_NSPECIES) = 0._rnk_dp
      real(rnk_dp) :: vmax_low(RNK_NSPECIES) = 0._rnk_dp
      !> 吸附分配系数 L kg^-1 (干土), 按形态; NO3 首版为 0
      real(rnk_dp) :: kd_sorption(RNK_NSPECIES) = 0._rnk_dp
      !> 库存底数(残留阈值) mg N kg^-1 干土, 按形态
      real(rnk_dp) :: residual_ppm(RNK_NSPECIES) = [0.25_rnk_dp, 0.50_rnk_dp]
      !> 参数来源标识(合成/文献先验/本地实测), 供初始化检查与收据登记
      character(len=32) :: source_tag(RNK_NSPECIES) = 'unset'
      !> 有效吸收根半径 m (典型细根 0.1-0.2 mm, 记录测量条件)
      real(rnk_dp) :: root_radius_m = 1.0e-4_rnk_dp
      !> Optional NH4 penetration correction. Zero uses the full root cylinder.
      real(rnk_dp) :: penetration_coeff = 0._rnk_dp
      !> Species-specific free-water diffusion, m^2/day.
      real(rnk_dp) :: species_diffusion_m2d(RNK_NSPECIES) = [1.64e-4_rnk_dp, 1.50e-4_rnk_dp]
   end type rnk_params

   !> 单层输入(适配层换算后)
   type, public :: rnk_layer
      real(rnk_dp) :: p(RNK_NSPECIES) = 0._rnk_dp     ! mg N kg^-1 干土
      real(rnk_dp) :: bd = 0._rnk_dp                  ! 容重 kg dry soil L^-1 soil
      real(rnk_dp) :: kg2ppm = 0._rnk_dp              ! 底座换算因子 (ppm → kg N ha^-1 为 p*kg2ppm/1? 见 stock_cap)
      real(rnk_dp) :: dlayr = 0._rnk_dp               ! 土层厚度 cm
      real(rnk_dp) :: water_depth = 0._rnk_dp        ! extraction snapshot thickness cm, defaults to dlayr
      real(rnk_dp) :: rlv = 0._rnk_dp                 ! 根长密度 cm root cm^-3 soil
      real(rnk_dp) :: theta0 = 0._rnk_dp              ! 日初总容积含水率 L L^-1
      real(rnk_dp) :: porosity = 0._rnk_dp         ! DSSAT saturation water content, used for diffusion only
      real(rnk_dp) :: rwu = 0._rnk_dp                 ! 实际根系吸水 cm d^-1
      real(rnk_dp) :: f_root = 1._rnk_dp              ! 根活性/反馈因子(如 sqrt(wet)*psi 反馈)
      real(rnk_dp) :: frac_high(RNK_NSPECIES) = 1._rnk_dp ! 高亲和系统活跃分数 fH
      real(rnk_dp) :: frac_low(RNK_NSPECIES) = 1._rnk_dp  ! 低亲和系统活跃分数 fL
   end type rnk_layer

   !> 单层诊断输出
   real(rnk_dp), parameter :: RNK_NOT_APPLICABLE = -99._rnk_dp

   type, public :: rnk_diag
      real(rnk_dp) :: c_bulk = 0._rnk_dp       ! 体相孔隙水浓度 mg N L^-1 (无液相时为 0 且 status=UNDEFINED)
      real(rnk_dp) :: c_root = 0._rnk_dp       ! 根表平衡浓度 mg N L^-1
      real(rnk_dp) :: mf_potential = 0._rnk_dp ! 质流供给潜力 g N m^-2 d^-1 (膜限速时非实际输入)
      real(rnk_dp) :: diffusive_flux = 0._rnk_dp ! 求解点扩散补给 G*(Cb-Cr) g N m^-2 d^-1
      real(rnk_dp) :: stock_cap = 0._rnk_dp    ! 层可提取库存上限 g N m^-2
      real(rnk_dp) :: candidate = 0._rnk_dp    ! 候选吸收 g N m^-2 d^-1 (库存裁剪后)
      real(rnk_dp) :: root_length = 0._rnk_dp  ! Lr = 100*RLV*DLAYR, m root m^-2
      real(rnk_dp) :: theta_mid = 0._rnk_dp    ! 吸水修正中点含水率
      integer :: branch = RNK_BRANCH_ZERO      ! 求解分支(裁剪前)
      logical :: stock_capped = .false.        ! 候选被库存上限裁剪
      real(rnk_dp) :: bulk_diffusion = 0._rnk_dp ! common D_bulk, m^2/day
      real(rnk_dp) :: steady_residual = RNK_NOT_APPLICABLE
      real(rnk_dp) :: c_root_mean = RNK_NOT_APPLICABLE
      real(rnk_dp) :: c_bulk_mean = RNK_NOT_APPLICABLE
      real(rnk_dp) :: hats_candidate = 0._rnk_dp
      real(rnk_dp) :: lats_candidate = 0._rnk_dp
      logical :: zero_diffusion = .false.
   end type rnk_diag

   public :: rnk_validate, rnk_membrane, rnk_layer_A

contains

   !> 初始化检查: 形态顺序、0<K_H<K_L、正容量、非负吸附/底数、有限值、
   !! 参数来源标识。nlayr>0 由适配层保证, 此处检查 nlayr 参数本身。
   pure function rnk_validate(par, nlayr) result(msg)
      type(rnk_params), intent(in) :: par
      integer, intent(in) :: nlayr
      character(len=160) :: msg
      integer :: s
      msg = ''
      if (nlayr <= 0) then
         msg = 'RNK: nlayr must be positive'; return
      end if
      if (.not. ieee_is_finite(par%root_radius_m)) then
         msg = 'RNK: root radius must be finite'; return
      end if
      if (par%root_radius_m <= 0._rnk_dp) then
         msg = 'RNK: root radius must be positive'; return
      end if
      if (.not. ieee_is_finite(par%penetration_coeff)) then
         msg = 'RNK: penetration coefficient must be finite'; return
      end if
      if (par%penetration_coeff < 0._rnk_dp) then
         msg = 'RNK: penetration coefficient must be nonnegative (0 disables it)'; return
      end if
      do s = 1, RNK_NSPECIES
         if (.not. all(ieee_is_finite([par%km_high(s), par%km_low(s), par%vmax_high(s), par%vmax_low(s), &
                                      par%kd_sorption(s), par%residual_ppm(s), par%species_diffusion_m2d(s)]))) then
            write (msg, '(a,i0)') 'RNK: non-finite parameter for species ', s
            return
         end if
         if (par%species_diffusion_m2d(s) < 0._rnk_dp) then
            write (msg, '(a,i0)') 'RNK: negative species diffusivity for species ', s
            return
         end if
         if (.not. (par%km_high(s) > 0._rnk_dp .and. par%km_low(s) > par%km_high(s))) then
            write (msg, '(a,i0,a)') 'RNK: require 0 < km_high < km_low for species ', s, ''
            return
         end if
         if (.not. (par%vmax_high(s) > 0._rnk_dp .and. par%vmax_low(s) > 0._rnk_dp)) then
            write (msg, '(a,i0,a)') 'RNK: require vmax_high > 0 and vmax_low > 0 for species ', s, ''
            return
         end if
         if (par%kd_sorption(s) < 0._rnk_dp .or. par%residual_ppm(s) < 0._rnk_dp) then
            write (msg, '(a,i0,a)') 'RNK: kd_sorption and residual_ppm must be >= 0 for species ', s, ''
            return
         end if
         if (len_trim(par%source_tag(s)) == 0 .or. trim(par%source_tag(s)) == 'unset') then
            write (msg, '(a,i0,a)') 'RNK: source_tag must be set (synthetic/literature/local) for species ', s, ''
            return
         end if
      end do
   end function rnk_validate

   !> 膜 Michaelis-Menten 组合通量 U(Cr), g N m^-2 d^-1
   !! U = Lr * f_root * [fH*VH*Cr/(KH+Cr) + fL*VL*Cr/(KL+Cr)]
   pure function rnk_membrane(par, s, cr, root_length, f_root, frac_high, frac_low) result(u)
      type(rnk_params), intent(in) :: par
      integer, intent(in) :: s
      real(rnk_dp), intent(in) :: cr, root_length, f_root, frac_high, frac_low
      real(rnk_dp) :: u
      real(rnk_dp) :: terms(2)
      terms = membrane_terms(par, s, cr, frac_high, frac_low)
      u = root_length*f_root*(terms(1) + terms(2))
   end function rnk_membrane

   pure function membrane_terms(par, s, cr, frac_high, frac_low) result(terms)
      type(rnk_params), intent(in) :: par
      integer, intent(in) :: s
      real(rnk_dp), intent(in) :: cr, frac_high, frac_low
      real(rnk_dp) :: terms(2)
      terms(1) = frac_high*par%vmax_high(s)*cr/(par%km_high(s) + cr)
      terms(2) = frac_low*par%vmax_low(s)*cr/(par%km_low(s) + cr)
   end function membrane_terms

   pure subroutine split_candidate(par, layer, s, cr, uptake, diag)
      type(rnk_params), intent(in) :: par
      type(rnk_layer), intent(in) :: layer
      integer, intent(in) :: s
      real(rnk_dp), intent(in) :: cr, uptake
      type(rnk_diag), intent(inout) :: diag
      real(rnk_dp) :: terms(2), hats
      if (uptake <= 0._rnk_dp) return
      terms = membrane_terms(par, s, cr, layer%frac_high(s), layer%frac_low(s))
      hats = uptake*(terms(1)/(terms(1) + terms(2)))
      diag%hats_candidate = diag%hats_candidate + hats
      diag%lats_candidate = diag%lats_candidate + (uptake - hats)
   end subroutine split_candidate

   pure function concentration(par, layer, species, theta) result(cb)
      type(rnk_params), intent(in) :: par
      type(rnk_layer), intent(in) :: layer
      integer, intent(in) :: species
      real(rnk_dp), intent(in) :: theta
      real(rnk_dp) :: cb, capacity
      cb = 0._rnk_dp
      capacity = theta + layer%bd*par%kd_sorption(species)
      if (theta > 0._rnk_dp .and. capacity > 0._rnk_dp) then
         cb = (max(0._rnk_dp, layer%p(species))/layer%kg2ppm/10._rnk_dp) / &
              ((layer%dlayr/100._rnk_dp)*capacity)
      end if
   end function concentration

   pure function bulk_diffusion(par, layer, species, theta) result(db)
      type(rnk_params), intent(in) :: par
      type(rnk_layer), intent(in) :: layer
      integer, intent(in) :: species
      real(rnk_dp), intent(in) :: theta
      real(rnk_dp) :: db, water
      water = max(0._rnk_dp, min(theta, layer%porosity))
      db = par%species_diffusion_m2d(species)*water**(10._rnk_dp/3._rnk_dp)/layer%porosity**2
   end function bulk_diffusion

   !> A 臂单层求解。返回两形态候选吸收(g N m^-2 d^-1)与诊断。
   pure subroutine rnk_layer_A(par, layer, diag)
      type(rnk_params), intent(in) :: par
      type(rnk_layer), intent(in) :: layer
      type(rnk_diag), intent(out) :: diag(RNK_NSPECIES)
      real(rnk_dp) :: theta_mid, extraction_depth, lr, mf, cb, cr, lo, hi, mid, mem_cb, u, cap, g, annulus, geometry
      real(rnk_dp) :: app_diffusion, penetration, outer_offset
      integer :: s, it
      logical :: no_liquid

      ! 1. 含水率中点与液相判定 (§3.2-1)
      extraction_depth = merge(layer%water_depth,layer%dlayr,layer%water_depth>0._rnk_dp)
      theta_mid = layer%theta0 - 0.5_rnk_dp*layer%rwu/extraction_depth
      no_liquid = layer%theta0 - max(0._rnk_dp, layer%rwu)/extraction_depth <= 0._rnk_dp
      ! 3. 层有效根长 m root m^-2
      lr = 100._rnk_dp*layer%rlv*layer%dlayr

      do s = 1, RNK_NSPECIES
         diag(s)%theta_mid = theta_mid
         diag(s)%root_length = lr
         diag(s)%stock_cap = max(0._rnk_dp, (layer%p(s) - par%residual_ppm(s)))/ &
                             merge(layer%kg2ppm, 1._rnk_dp, layer%kg2ppm > 0._rnk_dp)/10._rnk_dp
         diag(s)%candidate = 0._rnk_dp

         if (no_liquid) then
            ! 无液相: 无溶液可吸, 净吸收为零, 浓度不可定义 (§3.2-1)。
            ! theta_mid<0 且 rwu>0 属适配层水账错误, 适配层须另行校验。
            diag(s)%branch = RNK_BRANCH_UNDEFINED
            cycle
         end if
         if (lr <= 0._rnk_dp .or. diag(s)%stock_cap <= 0._rnk_dp .or. layer%f_root <= 0._rnk_dp) then
            diag(s)%branch = RNK_BRANCH_ZERO
            cycle
         end if

         cb = concentration(par, layer, s, layer%theta0)
         diag(s)%bulk_diffusion = bulk_diffusion(par, layer, s, theta_mid)
         diag(s)%zero_diffusion = diag(s)%bulk_diffusion == 0._rnk_dp
         ! Steady radial diffusion conductance of the soil annulus.
         ! Advection remains the separate bulk-water supply term in this formulation.
         annulus = (layer%dlayr/100._rnk_dp)/(acos(-1._rnk_dp)*lr*par%root_radius_m**2)
         if (s == RNK_NH4 .and. par%kd_sorption(s) > 0 .and. par%penetration_coeff > 0 .and. &
             .not. diag(s)%zero_diffusion) then
            app_diffusion = diag(s)%bulk_diffusion/(theta_mid + layer%bd*par%kd_sorption(s))
            ! One day of diffusion. Use (r_eff-a)/a to keep thin shells resolvable.
            outer_offset = annulus/(1._rnk_dp + sqrt(1._rnk_dp + annulus))
            penetration = sqrt(app_diffusion)/par%root_radius_m
            if (penetration > 0._rnk_dp) then
               if (par%penetration_coeff < outer_offset/penetration) then
                  penetration = par%penetration_coeff*penetration
                  if (penetration > 0._rnk_dp) annulus = penetration*(2._rnk_dp + penetration)
               end if
            end if
         end if
         if (annulus < 1.e-4_rnk_dp) then
            geometry = annulus*(0.5_rnk_dp - annulus/6._rnk_dp)
         else
            geometry = (1._rnk_dp + annulus)*log(1._rnk_dp + annulus)/annulus - 1._rnk_dp
         end if
         g = lr*4._rnk_dp*acos(-1._rnk_dp)*diag(s)%bulk_diffusion/geometry
         diag(s)%c_bulk = cb

         ! 4. 质流供给潜力 (膜限速分支下不是实际输入, 仅记账)
         mf = 0.01_rnk_dp*max(0._rnk_dp, layer%rwu)*cb
         diag(s)%mf_potential = mf

         mem_cb = rnk_membrane(par, s, cb, lr, layer%f_root, &
                               layer%frac_high(s), layer%frac_low(s))
         cap = diag(s)%stock_cap
         if (mem_cb <= mf) then
            cr = cb
            u = mem_cb
            diag(s)%branch = RNK_BRANCH_MEMBRANE
         else
            ! Solve the potential membrane/supply balance before imposing the daily stock cap.
            lo = 0._rnk_dp
            hi = cb
            do it = 1, 64
               mid = lo + 0.5_rnk_dp*(hi - lo)
               u = rnk_membrane(par, s, mid, lr, layer%f_root, layer%frac_high(s), layer%frac_low(s))
               if (u > mf + g*(cb - mid)) then
                  hi = mid
               else
                  lo = mid
               end if
            end do
            cr = lo + 0.5_rnk_dp*(hi - lo)
            u = rnk_membrane(par, s, cr, lr, layer%f_root, layer%frac_high(s), layer%frac_low(s))
            diag(s)%branch = RNK_BRANCH_BISECT
            diag(s)%steady_residual = mf + g*(cb - cr) - u
         end if
         diag(s)%c_root = cr
         diag(s)%diffusive_flux = g*(cb - cr)

         if (u > cap) then
            u = cap
            diag(s)%stock_capped = .true.
         end if
         diag(s)%candidate = u
         diag(s)%c_root_mean = cr
         diag(s)%c_bulk_mean = cb
         call split_candidate(par, layer, s, cr, u, diag(s))
      end do
   end subroutine rnk_layer_A
end module RootNUptake
