!> RootNUptake.f90 — 公共根系吸氮核（执行计划 T1, 2026-11-12）
!!
!! 双形态（NO3-, NH4+）独立参数双亲和米氏跨膜动力学 + 等效根际运输 A 臂
!! （质流 + 浓度差扩散代数根表平衡, 64 步区间二分）。B 臂（径向有限体积
!! 平流-扩散）由 T3 在本模块扩展, 当前 transport_mode=B 返回未实现状态。
!!
!! 设计约束（DSSAT_root_nitrogen_execution_plan.md §3）:
!!  * 纯计算模块: 不依赖 ModuleData / CROPGRO 全局状态 / 文件 IO。
!!  * 内部单位: g N m^-2 (ground) 与 d; 形态浓度 mg N L^-1 (孔隙水);
!!    土层几何 cm/ cm3 cm-3 / kg L-1, 适配层负责底座单位换算。
!!  * 形态顺序: 1=NO3-, 2=NH4+。
!!  * 无液相且零取水: 净吸收为零, 浓度诊断标记不可定义;
!!    含水率低但液相存在: 照常计算, 运输与根活性因子由适配层给出。
module RootNUptake
   implicit none
   private

   integer, parameter, public :: rnk_dp = selected_real_kind(15, 307)
   integer, parameter, public :: RNK_NO3 = 1, RNK_NH4 = 2
   integer, parameter, public :: RNK_NSPECIES = 2

   !> 运输模式: 0=关闭(沿用底座冻结行为, 适配层不调用本核)
   integer, parameter, public :: RNK_MODE_OFF = 0
   !> A: 等效根际运输(质流+代数扩散补给, 根表准稳态)
   integer, parameter, public :: RNK_MODE_A = 1
   !> B: 径向平流-扩散有限体积解 (T3 交付)
   integer, parameter, public :: RNK_MODE_B = 2

   !> 求解分支标签
   integer, parameter, public :: RNK_BRANCH_UNDEFINED = -1 ! 无液相/浓度不可定义
   integer, parameter, public :: RNK_BRANCH_ZERO = 0        ! 零根/零浓度/零参数 → 净吸收 0
   integer, parameter, public :: RNK_BRANCH_MEMBRANE = 1    ! U(Cb)<=MF: Cr=Cb, 膜不限制
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
      !> ---- B 臂参数 (T3, 径向有限体积) ----
      !> 有效吸收根半径 m (典型细根 0.1-0.2 mm, 记录测量条件)
      real(rnk_dp) :: root_radius_m = 1.0e-4_rnk_dp
      !> 液相分子扩散系数 m^2 d^-1 (NO3- ~1.9e-9 m^2/s ≈ 1.64e-4; NH4+ 相近)
      real(rnk_dp) :: molecular_diffusion_m2d = 1.64e-4_rnk_dp
      !> 曲折度无量纲因子 (固定先验, 记录来源; 首版不随含水量变化)
      real(rnk_dp) :: tortuosity = 0.5_rnk_dp
   end type rnk_params

   !> 单层输入(适配层换算后)
   type, public :: rnk_layer
      real(rnk_dp) :: p(RNK_NSPECIES) = 0._rnk_dp     ! mg N kg^-1 干土
      real(rnk_dp) :: bd = 0._rnk_dp                  ! 容重 kg dry soil L^-1 soil
      real(rnk_dp) :: kg2ppm = 0._rnk_dp              ! 底座换算因子 (ppm → kg N ha^-1 为 p*kg2ppm/1? 见 stock_cap)
      real(rnk_dp) :: dlayr = 0._rnk_dp               ! 土层厚度 cm
      real(rnk_dp) :: rlv = 0._rnk_dp                 ! 根长密度 cm root cm^-3 soil
      real(rnk_dp) :: theta0 = 0._rnk_dp              ! 日初总容积含水率 L L^-1
      real(rnk_dp) :: rwu = 0._rnk_dp                 ! 实际根系吸水 cm d^-1
      real(rnk_dp) :: f_root = 1._rnk_dp              ! 根活性/反馈因子(如 sqrt(wet)*psi 反馈)
      real(rnk_dp) :: frac_high(RNK_NSPECIES) = 1._rnk_dp ! 高亲和系统活跃分数 fH
      real(rnk_dp) :: frac_low(RNK_NSPECIES) = 1._rnk_dp  ! 低亲和系统活跃分数 fL
      !> A 臂层导度 G (g N m^-2 d^-1)/(mg N L^-1), 已含水分因子与根长
      !! (建议 G = 0.001 * D_eq * f_water(theta) * Lr, D_eq 继承各底座 v4-R2)
      real(rnk_dp) :: g_transport(RNK_NSPECIES) = 0._rnk_dp
   end type rnk_layer

   !> 单层诊断输出
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
      !> ---- B 臂扩展诊断 (A 臂保持 0) ----
      real(rnk_dp) :: advective_flux = 0._rnk_dp  ! 指定控制面(面 1)日内累计内向平流 g N m^-2
      real(rnk_dp) :: mass_error = 0._rnk_dp     ! 日质量闭合残差 (M0 - Mend - candidate)
      integer :: n_retries = 0                   ! 子步减半重试次数
      integer :: solver_flag = 0                 ! 0=收敛; 1=重试耗尽(候选置零,土壤持有)
   end type rnk_diag

   public :: rnk_validate, rnk_membrane, rnk_layer_A, rnk_layer_B

   !> B 臂求解分支标签
   integer, parameter, public :: RNK_BRANCH_RADIAL = 3

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
      do s = 1, RNK_NSPECIES
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
         if (.not. (finite(par%km_high(s)) .and. finite(par%km_low(s)) .and. &
                    finite(par%vmax_high(s)) .and. finite(par%vmax_low(s)) .and. &
                    finite(par%kd_sorption(s)) .and. finite(par%residual_ppm(s)))) then
            write (msg, '(a,i0,a)') 'RNK: non-finite parameter for species ', s, ''
            return
         end if
         if (len_trim(par%source_tag(s)) == 0 .or. trim(par%source_tag(s)) == 'unset') then
            write (msg, '(a,i0,a)') 'RNK: source_tag must be set (synthetic/literature/local) for species ', s, ''
            return
         end if
      end do
   contains
      elemental logical function finite(x)
         real(rnk_dp), intent(in) :: x
         finite = (x == x) .and. (x <= huge(x))
      end function finite
   end function rnk_validate

   !> 膜 Michaelis-Menten 组合通量 U(Cr), g N m^-2 d^-1
   !! U = Lr * f_root * [fH*VH*Cr/(KH+Cr) + fL*VL*Cr/(KL+Cr)]
   pure function rnk_membrane(par, s, cr, root_length, f_root, frac_high, frac_low) result(u)
      type(rnk_params), intent(in) :: par
      integer, intent(in) :: s
      real(rnk_dp), intent(in) :: cr, root_length, f_root, frac_high, frac_low
      real(rnk_dp) :: u
      u = root_length*f_root*(frac_high*par%vmax_high(s)*cr/(par%km_high(s) + cr) + &
                              frac_low*par%vmax_low(s)*cr/(par%km_low(s) + cr))
   end function rnk_membrane

   !> A 臂单层求解。返回两形态候选吸收(g N m^-2 d^-1)与诊断。
   pure subroutine rnk_layer_A(par, layer, diag)
      type(rnk_params), intent(in) :: par
      type(rnk_layer), intent(in) :: layer
      type(rnk_diag), intent(out) :: diag(RNK_NSPECIES)
      real(rnk_dp) :: theta_mid, lr, mf, cb, cr, lo, hi, mid, mem_cb, u, cap
      integer :: s, it
      logical :: no_liquid

      ! 1. 含水率中点与液相判定 (§3.2-1)
      theta_mid = layer%theta0 - 0.5_rnk_dp*layer%rwu/layer%dlayr
      no_liquid = (theta_mid <= 0._rnk_dp)
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
         if (lr <= 0._rnk_dp .or. layer%p(s) <= 0._rnk_dp .or. layer%f_root <= 0._rnk_dp) then
            diag(s)%branch = RNK_BRANCH_ZERO
            cycle
         end if

         ! 2. 体相浓度 (§3.2-2): Cb = p*BD/(theta_mid + BD*Kd), mg N L^-1 孔隙水
         !    无液相(theta_mid<=0)时该层已在上方按 UNDEFINED/ZERO 短路或仅作诊断
         cb = layer%p(s)*layer%bd/max(theta_mid + layer%bd*par%kd_sorption(s), 1.e-12_rnk_dp)
         diag(s)%c_bulk = cb

         ! 4. 质流供给潜力 (膜限速分支下不是实际输入, 仅记账)
         mf = 0.01_rnk_dp*max(0._rnk_dp, layer%rwu)*cb
         diag(s)%mf_potential = mf

         mem_cb = rnk_membrane(par, s, cb, lr, layer%f_root, &
                               layer%frac_high(s), layer%frac_low(s))
         if (mem_cb <= mf) then
            ! 膜不限制: Cr = Cb, 候选 = U(Cb) (§3.2-4 第一支)
            cr = cb
            diag(s)%branch = RNK_BRANCH_MEMBRANE
         else
            ! 二分求 U(Cr) = MF + G*(Cb-Cr), Cr ∈ [0, Cb] (§3.2-4 第二支)
            lo = 0._rnk_dp
            hi = cb
            do it = 1, 64
               mid = 0.5_rnk_dp*(lo + hi)
               if (rnk_membrane(par, s, mid, lr, layer%f_root, layer%frac_high(s), layer%frac_low(s)) > &
                   mf + layer%g_transport(s)*(cb - mid)) then
                  hi = mid
               else
                  lo = mid
               end if
            end do
            cr = 0.5_rnk_dp*(lo + hi)
            diag(s)%branch = RNK_BRANCH_BISECT
         end if
         diag(s)%c_root = cr
         diag(s)%diffusive_flux = layer%g_transport(s)*max(0._rnk_dp, cb - cr)

         u = rnk_membrane(par, s, cr, lr, layer%f_root, layer%frac_high(s), layer%frac_low(s))
         cap = diag(s)%stock_cap
         if (u > cap) then
            u = cap
            diag(s)%stock_capped = .true.
         end if
         diag(s)%candidate = u
      end do
   end subroutine rnk_layer_A

   !> B 臂单层求解 (T3, 计划 §5): 每层根圆柱环带对数网格有限体积,
   !! 迎风平流 + 隐式扩散, 根表守恒吸收边界 (与 A 同一米氏组合式,
   !! 以最内单元浓度近似根表浓度)。状态为单元质量 M_i (g N m^-2 ground),
   !! 吸附容量因子 capfac = theta + rho_b*Kd 仅用于浓度换算; 水分收缩使
   !! 溶质自动浓缩。日内子步; 负浓度或不收敛时子步减半重试 (从原子步状态),
   !! 重试耗尽时候选置零并置 solver_flag=1 —— 禁止静默回退 A。
   !! 可选 n_cells/n_substeps 供网格与步长收敛测试覆盖。
   pure subroutine rnk_layer_B(par, layer, diag, n_cells, n_substeps)
      type(rnk_params), intent(in) :: par
      type(rnk_layer), intent(in) :: layer
      type(rnk_diag), intent(out) :: diag(RNK_NSPECIES)
      integer, intent(in), optional :: n_cells, n_substeps
      integer, parameter :: NMAX = 64, NRETRY_MAX = 12, NPICARD = 12
      real(rnk_dp), parameter :: THETA_FLOOR = 1.0e-6_rnk_dp, NEG_TOL = -1.0e-12_rnk_dp
      integer :: nc, ns0, s, k, itry, ipic
      real(rnk_dp) :: pi_, h, lr, a_root, b_root
      real(rnk_dp) :: rf(0:NMAX), rc(NMAX)
      real(rnk_dp) :: vol(NMAX), wadv0(NMAX - 1), rgrad(NMAX - 1)
      real(rnk_dp) :: theta0, theta_now, theta_new, wrate, fw, t, dt
      real(rnk_dp) :: capfn, capfc, m0tot, mendtot, c0
      real(rnk_dp) :: m(NMAX), c(NMAX), cstar, u0, du, uend
      real(rnk_dp) :: lo(NMAX), di(NMAX), up(NMAX), rhs(NMAX), cp(NMAX)
      real(rnk_dp) :: cand, advcum, difcum, dfacenow
      real(rnk_dp) :: dface_k, dum, piv
      integer :: nretry, sflag
      logical :: conv, ok

      pi_ = acos(-1._rnk_dp)
      nc = 8; if (present(n_cells)) nc = n_cells
      ns0 = 24; if (present(n_substeps)) ns0 = n_substeps
      nc = min(max(nc, 2), NMAX); ns0 = max(ns0, 1)

      ! ---- 几何 (§5): b = sqrt(a^2 + h/(pi*Lr)), 对数面网格 ----
      h = layer%dlayr/100._rnk_dp
      lr = 100._rnk_dp*layer%rlv*layer%dlayr
      theta0 = layer%theta0 - 0.5_rnk_dp*layer%rwu/layer%dlayr
      do s = 1, RNK_NSPECIES
         diag(s)%theta_mid = theta0
         diag(s)%root_length = lr
         diag(s)%stock_cap = max(0._rnk_dp, layer%p(s) - par%residual_ppm(s))/ &
                             merge(layer%kg2ppm, 1._rnk_dp, layer%kg2ppm > 0._rnk_dp)/10._rnk_dp
         diag(s)%candidate = 0._rnk_dp
      end do
      if (lr <= 0._rnk_dp .or. layer%f_root <= 0._rnk_dp .or. theta0 <= THETA_FLOOR .or. &
          par%root_radius_m <= 0._rnk_dp .or. par%molecular_diffusion_m2d < 0._rnk_dp .or. &
          par%tortuosity <= 0._rnk_dp) then
         do s = 1, RNK_NSPECIES
            if (theta0 <= THETA_FLOOR) then
               diag(s)%branch = RNK_BRANCH_UNDEFINED
            else
               diag(s)%branch = RNK_BRANCH_ZERO
            end if
         end do
         return
      end if
      a_root = par%root_radius_m
      b_root = sqrt(a_root*a_root + h/(pi_*lr))
      do k = 0, nc
         rf(k) = a_root*(b_root/a_root)**(real(k, rnk_dp)/real(nc, rnk_dp))
      end do
      do k = 1, nc
         rc(k) = sqrt(rf(k - 1)*rf(k))
         vol(k) = pi_*lr*(rf(k)**2 - rf(k - 1)**2)   ! Σ vol = h (单位地面积)
      end do
      do k = 1, nc - 1
         rgrad(k) = rc(k + 1) - rc(k)
         ! 内向体积通量 (面 k): Q_a*(b^2-r^2)/(b^2-a^2)*Lr = 0.01*RWU*(b^2-r^2)/(b^2-a^2)
         wadv0(k) = 0.01_rnk_dp*max(0._rnk_dp, layer%rwu)*(b_root*b_root - rf(k)**2)/ &
                    (b_root*b_root - a_root*a_root)
      end do
      wrate = 0.01_rnk_dp*max(0._rnk_dp, layer%rwu)/h        ! theta 日衰减率

      do s = 1, RNK_NSPECIES
         if (layer%p(s) <= 0._rnk_dp) then
            diag(s)%branch = RNK_BRANCH_ZERO
            cycle
         end if
         ! ---- 初始化: 均匀浓度, Σ M_i == DSSAT 输入库存 ----
         m0tot = layer%p(s)/merge(layer%kg2ppm, 1._rnk_dp, layer%kg2ppm > 0._rnk_dp)/10._rnk_dp
         capfc = theta0 + layer%bd*par%kd_sorption(s)
         c0 = m0tot/(h*capfc)
         diag(s)%c_bulk = c0
         diag(s)%mf_potential = 0.01_rnk_dp*max(0._rnk_dp, layer%rwu)*c0
         do k = 1, nc
            m(k) = vol(k)*capfc*c0
         end do
         cand = 0._rnk_dp; advcum = 0._rnk_dp; difcum = 0._rnk_dp
         nretry = 0; sflag = 0; t = 0._rnk_dp; dt = 1._rnk_dp/real(ns0, rnk_dp)
         do while (t < 1._rnk_dp - 1.0e-12_rnk_dp)
            dt = min(dt, 1._rnk_dp - t)
            ok = .false.
            do itry = 0, NRETRY_MAX
               theta_now = max(theta0 - wrate*t, THETA_FLOOR)
               theta_new = max(theta0 - wrate*(t + dt), THETA_FLOOR)
               fw = 1._rnk_dp
               if (wrate*dt > 0._rnk_dp) fw = (theta_now - theta_new)/(wrate*dt)
               capfc = theta_now + layer%bd*par%kd_sorption(s)
               capfn = theta_new + layer%bd*par%kd_sorption(s)
               do k = 1, nc
                  c(k) = m(k)/(vol(k)*capfc)
                  cp(k) = vol(k)*capfn
               end do
               cstar = c(1)
               conv = .false.
               do ipic = 1, NPICARD
                  ! 根表米氏线性化 (在 cstar 处)
                  u0 = rnk_membrane(par, s, cstar, lr, layer%f_root, layer%frac_high(s), layer%frac_low(s))
                  du = lr*layer%f_root*(layer%frac_high(s)*par%vmax_high(s)*par%km_high(s)/ &
                       (par%km_high(s) + cstar)**2 + layer%frac_low(s)*par%vmax_low(s)*par%km_low(s)/ &
                       (par%km_low(s) + cstar)**2)
                  ! 组装三对角 (未知 cn), 内面: 迎风平流 + 隐式扩散
                  dfacenow = lr*2._rnk_dp*pi_*rf(1)*par%tortuosity*theta_new* &
                             par%molecular_diffusion_m2d/max(rgrad(1), 1.0e-15_rnk_dp)
                  di(1) = cp(1) + dt*(dfacenow + du)
                  up(1) = -dt*(fw*wadv0(1) + dfacenow)
                  rhs(1) = m(1) - dt*u0 + dt*du*cstar
                  do k = 2, nc - 1
                     dfacenow = lr*2._rnk_dp*pi_*rf(k)*par%tortuosity*theta_new* &
                                par%molecular_diffusion_m2d/max(rgrad(k), 1.0e-15_rnk_dp)
                     dface_k = lr*2._rnk_dp*pi_*rf(k - 1)*par%tortuosity*theta_new* &
                               par%molecular_diffusion_m2d/max(rgrad(k - 1), 1.0e-15_rnk_dp)
                     lo(k) = -dt*dface_k
                     di(k) = cp(k) + dt*(dfacenow + fw*wadv0(k - 1) + dface_k)
                     up(k) = -dt*(fw*wadv0(k) + dfacenow)
                     rhs(k) = m(k)
                  end do
                  dface_k = lr*2._rnk_dp*pi_*rf(nc - 1)*par%tortuosity*theta_new* &
                            par%molecular_diffusion_m2d/max(rgrad(nc - 1), 1.0e-15_rnk_dp)
                  lo(nc) = -dt*dface_k
                  di(nc) = cp(nc) + dt*(fw*wadv0(nc - 1) + dface_k)
                  rhs(nc) = m(nc)
                  ! Thomas 求解 (原地)
                  do k = 2, nc
                     piv = lo(k)/di(k - 1)
                     di(k) = di(k) - piv*up(k - 1)
                     rhs(k) = rhs(k) - piv*rhs(k - 1)
                  end do
                  c(nc) = rhs(nc)/di(nc)
                  do k = nc - 1, 1, -1
                     c(k) = (rhs(k) - up(k)*c(k + 1))/di(k)
                  end do
                  dum = abs(c(1) - cstar)
                  cstar = c(1)
                  if (dum <= 1.0e-11_rnk_dp*(1._rnk_dp + abs(cstar))) then
                     conv = .true.; exit
                  end if
               end do
               if (conv .and. minval(c(1:nc)) >= NEG_TOL) then
                  ok = .true.; exit
               end if
               ! 子步减半重试 (从原子步状态 m 不变)
               dt = 0.5_rnk_dp*dt
               nretry = nretry + 1
            end do
            if (.not. ok) then
               ! 重试耗尽: 候选置零, 土壤继续持有, 禁止静默回退 A
               sflag = 1
               cand = 0._rnk_dp; advcum = 0._rnk_dp; difcum = 0._rnk_dp
               exit
            end if
            ! 收敛: 结算质量、吸收与控制面通量
            uend = rnk_membrane(par, s, c(1), lr, layer%f_root, layer%frac_high(s), layer%frac_low(s))
            cand = cand + dt*uend
            dfacenow = lr*2._rnk_dp*pi_*rf(1)*par%tortuosity*theta_new* &
                       par%molecular_diffusion_m2d/max(rgrad(1), 1.0e-15_rnk_dp)
            advcum = advcum + dt*fw*wadv0(1)*c(2)
            difcum = difcum + dt*dfacenow*(c(2) - c(1))
            do k = 1, nc
               m(k) = cp(k)*c(k)
            end do
            t = t + dt
         end do
         mendtot = sum(m(1:nc))
         diag(s)%mass_error = m0tot - mendtot - cand
         diag(s)%advective_flux = advcum
         diag(s)%diffusive_flux = difcum
         diag(s)%c_root = c(1)
         diag(s)%n_retries = nretry
         diag(s)%solver_flag = sflag
         diag(s)%branch = RNK_BRANCH_RADIAL
         if (sflag /= 0) then
            diag(s)%candidate = 0._rnk_dp
            diag(s)%mass_error = m0tot - mendtot
            cycle
         end if
         if (cand > diag(s)%stock_cap) then
            cand = diag(s)%stock_cap
            diag(s)%stock_capped = .true.
         end if
         diag(s)%candidate = cand
      end do
   end subroutine rnk_layer_B

end module RootNUptake
