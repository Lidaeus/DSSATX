! Official 4.8.6.4 + A budgets; opt-in v3 adaptations approved 2026-11-03.
! NI_STAGE: 0 official; 1 bounded pools; 2 finite assimilation;
!           3 root transport; 4 organ reference curves; 5 functional feedback.
module CG_Nitrogen
  use iso_fortran_env, only: real64
  use ieee_arithmetic, only: ieee_is_finite, ieee_next_after
  use ModuleDefs, only: ControlType, SwitchType, NL
  use RootNUptake, only: rnk_dp, rnk_params, rnk_layer, rnk_diag, &
    rnk_NO3, rnk_NH4, rnk_layer_A, rnk_layer_B, rnk_membrane, rnk_validate, &
    RNK_MODE_A, RNK_MODE_B
  implicit none
  private
  integer, parameter :: dp=real64
  integer, parameter :: implemented_stage=5
  integer, save :: ni_stage=0, root_mode=0, output_unit=0, budget_revision=0
  integer, save :: state_timing=0, pods_n_state=0
  integer, save :: end_run=-1,end_day=-1,day_run=-1,day_date=-1,day_source=-1
  integer, save :: v3_unit=0
  logical,save :: day_valid=.false.,v3_opened=.false.
  real(dp),save :: z_end(2)=0,day_z(2)=0,day_growth=1
  integer,save :: remob_mode=0,remob_severity=1
  real(dp),save :: remob_tau=-1,protect_beta=-1,slow_ratio=-1
  integer,save :: remob_rate_mode=0
  real(dp),save :: remob_rate_max=-1,functional_rate_max=-1
  real(dp),save :: mob_rate_cap(4)=0,mob_function_cap(4)=0
  integer,save :: lai_cn_mode=0,lai_unit=0,lai_accept_calls=0,lai_area_calls=0
  logical,save :: lai_opened=.false.
  real(dp),save :: lai_cn_shape=-1,lai_state=1,lai_signal=1,lai_dm_raw=0,lai_dm_request=0
  real(dp),save :: lai_c_available=0,lai_n_available=0,lai_dm_actual=0,lai_n_actual=0
  real(dp),save :: lai_c_actual=0,lai_veg_c=0,lai_veg_n=0,lai_build=0,lai_sla=0,lai_area=0
  real(dp),save :: lai_min_begin=0,lai_crit_begin=0
  real(dp),save :: veg_z_end=1,day_veg_z=1
  real(dp),save :: mob_safe(4)=0,mob_func(4)=0,mob_plan(4)=0,mob_returned(4)=0
  real(dp),save :: mob_gap=0,mob_accept=0,mob_new_used=0,mob_c_paid=0
  integer,save :: mob_unit=0
  logical,save :: mob_opened=.false.
  integer,save :: luxury_priority=0,lux_unit=0
  logical,save :: lux_opened=.false.
  integer,save :: c4_budget=0,leaf_coupling=0,c4_photo=0,cash_unit=0,leaf_unit=0
  logical,save :: cash_opened=.false.,leaf_opened=.false.
  real(dp),save :: n_sen_rate=0,sen_frac(3)=0,sen_plan_dm(2)=0,sen_available(4)=0,mob_sen(4)=0
  real(dp),save :: c4_nloss(3)=0,c4_area_dead=0
  real(dp),save :: kinetic_cap(2)=0,late_a(2)=0,late_cost=0,late_c_budget=0,late_func=0,late_lux=0
  real(dp),save :: late_unit_cost(2)=0,late_c_before=0,late_c_after=0,late_c_reserved=0,late_nad(2)=0
  real(dp), save :: curve_w0=1, photo_slw_ref=.0028_dp
  ! V4 P1: independent, opt-in mechanism comparisons; defaults reproduce C4.
  real(dp),save :: leaf_min_ratio=-1,stem_min_ratio=-1,leaf_inf=0,stem_inf=0
  real(dp),save :: photo_sln_ref=-1,veg_before(3)=0,veg_after(3)=0,storage_shift=0
  integer,save :: photo_reference_mode=0,leaf_expansion_mode=0,v4_diagnostics=0,v4_unit=0
  logical,save :: v4_opened=.false.
  integer,save :: common_acceptance=0,reserve_mode=0,p2_unit=0,p2_plan_calls=0,p2_veg_calls=0
  real(dp),save :: reserve_capacity=-1,reserve_fill_tau=-1,reserve_protect=-1
  real(dp),save :: build_min_leaf=-1,build_min_stem=-1
  logical,save :: p2_opened=.false.,reserve_pending=.false.
  real(dp),save :: reserve_n(2)=0,reserve_begin(2)=0,reserve_fill(2)=0,reserve_release(2)=0
  real(dp),save :: reserve_sen_recovery(2)=0,reserve_litter(2)=0,reserve_residual(2)=0
  real(dp),save :: joint_dm_req(3)=0,joint_build(3)=0,joint_target(3)=0,joint_agr(3)=0,joint_proi(3)=0
  real(dp),save :: joint_dm(3)=0,joint_nn(3)=0,joint_repair(3)=0,joint_repair_used(3)=0
  real(dp),save :: joint_unitcost(3)=0,joint_carbon=0,joint_nitrogen=0,joint_fruit_req(2)=0
  real(dp),save :: joint_fruit_cap(2)=0,joint_fruit_used(2)=0,joint_scale=1,mob_repair_used=0
  real(dp),save :: joint_assim_n=0,joint_assim_c=0,joint_assim_unused=0
  real(dp), save :: org_start(3)=0, donor_n(3)=0, donor_c(3)=0
  real(dp), save :: org_end_stock=0,org_end_off=0,seed_end=0,leak_end=0
  real(dp), save :: veg_available=0,veg_cost=0,leaf_gate=1,refill_n(3)=0
  integer,save::audit_unit=0
  logical,save::audit_opened=.false.
  logical, save :: loaded=.false., opened=.false., ready=.false., water_ready=.false.
  real(dp), save :: q_no3_max=-1, q_nh4_max=-1
  real(dp), save :: assim_no3_v=-1, assim_nh4_v=-1, assim_no3_k=-1, assim_nh4_k=-1
  real(dp), save :: root_v=-1, root_k=-1, diffusion_k=-1, pool_beta=-1
  real(dp), save :: leaf_a=-1, leaf_b=-1, stem_a=-1, stem_b=-1
  real(dp), save :: min_ratio=-1, max_ratio=-1, photo_floor=-1, photo_gamma=-1, growth_tau=-1
  real(dp), save :: q3(3)=0, q4(3)=0, carrier(3)=0, w_begin(3)=0
  real(dp), save :: litter3(NL)=0, litter4(NL)=0, returned_litter=0
  real(dp), save :: theta_snapshot(NL)=0, rwu_snapshot(NL)=0, rlv_snapshot(NL)=0
  integer, save :: water_day=-1, water_run=-1, water_nlayr=0
  real(dp), save :: theta0_snapshot(NL)=0
  real(dp), save :: cmin(2)=0, ccrit(2)=0, cmax(2)=0, structural_fraction=1, growth_factor=1
  real(dp), save :: d_q_begin=0, d_u3=0, d_u4=0, d_a3=0, d_a4=0
  real(dp), save :: d_cost=0, d_refund=0, d_litter=0, d_residual=0
  real(dp), save :: legacy_nh4=-1, d_pending=0
  real(dp), save :: old_a3=0,old_a4=0,old_rsp3=0,old_rsp4=0
  real(dp), save :: org_begin=0,org_off_begin=0,leak_begin=0,legacy_n_res=0,legacy_c_overrun=0
  real(dp), save :: r_mf(NL)=0,r_diff(NL)=0,r_mem(NL)=0,r_cr(NL)=0,r_bulk(NL)=0
  real(dp), save :: r_candidate3(NL)=0,r_candidate4(NL)=0,r_final3(NL)=0,r_final4(NL)=0
  ! --- RootNUptake 公共核 (T2 2026-11-12): 0=off(冻结行为), 1=A(等效根际运输) ---
  integer, save :: rnk_mode=0, rnk_radial_cells=8
  real(dp), save :: rnk_species_diffusion(2)=[1.64e-4_dp,1.50e-4_dp]
  type(rnk_diag), save :: r_rnk_transport(2,NL)
  real(dp), save :: rnk_km_high(2)=0, rnk_km_low(2)=0
  real(dp), save :: rnk_vmax_high(2)=0, rnk_vmax_low(2)=0
  real(dp), save :: rnk_kd(2)=0, rnk_residual(2)=0
  real(dp), save :: rnk_radius=0
  type(rnk_params), save :: rnk_par
  integer, save :: r_rnk_branch(2,NL)=0
  integer, save :: r_rnk_flag(2,NL)=0
  real(dp), save :: r_rnk_cap(2,NL)=0, r_rnk_mf4(NL)=0, r_rnk_bulk4(NL)=0, r_rnk_cr4(NL)=0
  logical, save :: r_rnk_capped(2,NL)=.false.
  real(dp), save :: r_rnk_stock_before(2,NL)=0, r_rnk_theta0(NL)=0, r_rnk_diff(2,NL)=0
  real(dp), save :: r_rnk_accept3(NL)=0, r_rnk_accept4(NL)=0
  real(dp), save :: r_rnk_adv(2,NL)=0, r_rnk_mass_error(2,NL)=0
  integer, save :: r_rnk_source_day=-1, r_rnk_pending_run=-1, r_rnk_pending_nlayr=0
  integer, save :: rnk_ledger_unit=0
  logical, save :: rnk_ledger_opened=.false.
  integer,save::root_output_unit=0
  logical,save::root_opened=.false.
  public :: NI_LOAD, NI_RESET, NI_ENABLED, NI_CURVES, NI_FEEDBACK
  public :: NI_BEGIN, NI_ACCEPT_UPTAKE, NI_ASSIMILATE, NI_SETTLE, NI_END
  public :: NI_RETURN_LITTER, NI_SOIL_INPUT, NI_SET_NH4
  public :: NI_CAPTURE_WATER, NI_ROOT_MODE, NI_ROOT_UPTAKE, NI_COMMON_ROOT_ENABLED
  public :: NI_ROOT_SOIL_DEBIT, NI_ROOT_SOIL_END
  public :: NI_TARGETS, NI_REFERENCES, NI_GROWTH, NI_LEAF_FACTOR
  public :: NI_TOTAL_Q, NI_CURVE_KERNEL, NI_ROOT_KERNEL, NI_ASSIM_KERNEL
  public :: NI_PREASSIM, NI_MERGE_OLD
  public :: NI_ORG_BEGIN, NI_ORG_END
  public :: NI_SPLIT
  public :: NI_REVISED, NI_VEG_RECONCILE, NI_REFILL, NI_DONORS, NI_RETAIN
  public :: NI_EXPANSION, NI_AREA_REFILL, NI_MINIMUM
  public :: NI_OPEN_DAY, NI_SYNC_STATE, NI_PODS, NI_POD_FACTOR, NI_POD_KERNEL
  public :: NI_REMOB_ON, NI_REMOB_KERNEL, NI_REMOB_PLAN, NI_REMOB_SETTLE, NI_REMOB_REPRO
  public :: NI_CORE_DEMAND, NI_LUXURY, NI_LATE_KERNEL, NI_REDUCTION_RESP
  public :: NI_LUX_ON
  public :: NI_C4_ON, NI_LEAF_COUPLED, NI_C4_CASH, NI_CARB_KERNEL, NI_SHELL_CARB_KERNEL
  public :: NI_C4_SEN_PLAN, NI_C4_FATE, NI_C4_NLOSS, NI_C4_AREA, NI_N_SEN_EXTRA
  public :: NI_C4_FRACTIONS
  public :: NI_C4_PHOTO, NI_CANOPY_N, NI_CANOPY_N_KERNEL
  public :: NI_V4_CURVE_KERNEL, NI_V4_PHOTO_KERNEL, NI_V4_STORAGE_SHIFT
  public :: NI_COMMON,NI_RESERVES,NI_P2_POTENTIAL,NI_P2_PLAN,NI_P2_POD_BUDGET,NI_P2_FRUIT_USED
  public :: NI_P2_VEG_ACCEPT,NI_P2_CSAVE,NI_P2_COMMIT_RESERVES,NI_P2_RNITP
  public :: NI_JOINT_KERNEL,NI_RESERVE_DONOR_KERNEL,NI_RESERVE_COMMIT_KERNEL
  public :: NI_P2_CARBON,NI_P2_UNUSED_ASSIM
  public :: NI_LAI_ON,NI_LAI_REQUEST,NI_LAI_BUILD,NI_LAI_ACCEPT,NI_LAI_RECORD,NI_LAI_AREA,NI_LAI_CN_KERNEL
contains
  logical function NI_LAI_ON()
    NI_LAI_ON=lai_cn_mode==1
  end function
  pure real(dp) function lai_factor(z,shape)
    real(dp),intent(in)::z,shape
    lai_factor=1-(1-max(0._dp,min(1._dp,z)))**shape
  end function
  pure subroutine NI_LAI_CN_KERNEL(carbon,nitrogen,dm,build,target,agr,proi,z,shape,accepted_dm,accepted_n,unitcost,scale,factor)
    real(dp),intent(in)::carbon,nitrogen,dm(3),build(3),target(3),agr(3),proi(3),z,shape
    real(dp),intent(out)::accepted_dm(3),accepted_n(3),unitcost(3),scale,factor
    real(dp)::request(3),unused_repair(3),unused_fruit(2)
    factor=lai_factor(z,shape);request=max(0._dp,dm);request(1)=request(1)*factor
    call NI_JOINT_KERNEL(carbon,nitrogen,request,build,target,agr,proi,[0._dp,0._dp],[0._dp,0._dp,0._dp], &
      accepted_dm,accepted_n,unused_repair,unused_fruit,unitcost,scale)
  end subroutine
  subroutine NI_LAI_REQUEST(dm)
    real,intent(inout)::dm
    lai_dm_raw=real(dm,dp);lai_state=1; lai_min_begin=cmin(1);lai_crit_begin=ccrit(1)
    if(ready)lai_state=growth_factor
    if(state_timing==1.and.day_valid)lai_state=day_growth
    lai_signal=1
    if(NI_LAI_ON())then
      lai_signal=lai_factor(lai_state,lai_cn_shape)
      dm=flux32(max(0._dp,real(dm,dp))*lai_signal)
    endif
    lai_dm_request=real(dm,dp)
  end subroutine
  subroutine NI_LAI_BUILD(build_leaf,build_stem,target_leaf,target_stem)
    real,intent(inout)::build_leaf,build_stem
    real,intent(in)::target_leaf,target_stem
    if(.not.NI_LAI_ON())return
    if(build_min_leaf>0)build_leaf=real(build_min_leaf*real(target_leaf,dp))
    if(build_min_stem>0)build_stem=real(build_min_stem*real(target_stem,dp))
  end subroutine
  subroutine NI_LAI_ACCEPT(carbon,nitrogen,dm,nn,build,target,agr,proi,cost)
    real,intent(in)::carbon,nitrogen,build(3),target(3),agr(3),proi(3)
    real,intent(inout)::dm(3)
    real,intent(out)::nn(3),cost
    real(dp)::raw(3),accepted(3),nitrogen_used(3),unitcost(3),scale,factor,total,previous
    integer::i
    raw=real(dm,dp);raw(1)=lai_dm_raw
    call NI_LAI_CN_KERNEL(real(carbon,dp),real(nitrogen,dp),raw,real(build,dp),real(target,dp), &
      real(agr,dp),real(proi,dp),lai_state,lai_cn_shape,accepted,nitrogen_used,unitcost,scale,factor)
    do i=1,3
      previous=accepted(i);dm(i)=flux32(previous)
      if(previous>0)nitrogen_used(i)=nitrogen_used(i)*real(dm(i),dp)/previous
      nn(i)=flux32(nitrogen_used(i))
    enddo
    total=sum(real(dm,dp));cost=1
    if(total>0)cost=real(sum(real(dm,dp)*unitcost)/total)
  end subroutine
  subroutine NI_LAI_RECORD(carbon,nitrogen,dm,nn,build,agr,proi,cost)
    real,intent(in)::carbon,nitrogen,dm(3),nn(3),build,agr,proi,cost
    real(dp)::composition
    if(.not.NI_REVISED())return
    lai_accept_calls=lai_accept_calls+1
    if(lai_accept_calls/=1)error stop 'NI LAI: repeated vegetative acceptance'
    lai_c_available=real(carbon,dp);lai_n_available=real(nitrogen,dp)
    lai_dm_actual=real(dm(1),dp);lai_n_actual=real(nn(1),dp);lai_build=real(build,dp)
    composition=0
    if(dm(1)>0)composition=real(nn(1),dp)/(.16_dp*real(dm(1),dp))
    lai_c_actual=real(dm(1),dp)*real(agr,dp)*(1-(composition-real(proi,dp))/(1-real(proi,dp)))
    lai_veg_c=sum(real(dm,dp))*real(cost,dp);lai_veg_n=sum(real(nn,dp))
    if(NI_LAI_ON())then
      if(lai_dm_actual>lai_dm_request+2.e-6_dp)error stop 'NI LAI: accepted leaf exceeds state-limited request'
      if(lai_n_actual+1.e-7_dp<lai_build*lai_dm_actual)error stop 'NI LAI: leaf assembly N deficit'
    endif
  end subroutine
  real function NI_LAI_AREA(dm,sla)
    real,intent(in)::dm,sla
    NI_LAI_AREA=dm*sla
    if(.not.NI_REVISED())return
    lai_area_calls=lai_area_calls+1
    if(lai_area_calls/=1)error stop 'NI LAI: repeated new leaf area integration'
    lai_sla=real(sla,dp);lai_area=real(NI_LAI_AREA,dp)
    if(abs(real(dm,dp)-lai_dm_actual)>1.e-7_dp)error stop 'NI LAI: area uses an unaccepted leaf mass'
  end function
  subroutine write_lai(control,lai)
    type(ControlType),intent(in)::control
    real,intent(in)::lai
    real(dp)::nonreserve
    integer::ios
    if(max(lai_cn_mode,remob_rate_mode,v4_diagnostics)==0)return
    ! Standalone pool/remobilization drivers do not execute VEGGR/GROW.
    ! Full-crop replay separately requires all 1512 coupled ledger rows.
    if(lai_cn_mode==0.and.lai_accept_calls==0.and.lai_area_calls==0)return
    if(lai_accept_calls/=1.or.lai_area_calls/=1)error stop 'NI LAI: missing acceptance or area integration'
    nonreserve=org_start(1)
    if(NI_RESERVES())nonreserve=nonreserve-reserve_begin(1)
    if(.not.lai_opened)then
      open(newunit=lai_unit,file='PlantNLAI.csv',status='new',action='write',iostat=ios)
      if(ios/=0)error stop 'NI LAI: cannot create leaf growth ledger'
      write(lai_unit,'(A)')'run,yrdoy,lai_cn_mode,accept_calls,area_calls,shape,state_smoothed,state_raw_leaf,'// &
        'state_response,N_nonreserve_begin,W_leaf_begin,N_min_begin,N_crit_begin,dm_leaf_potential,dm_leaf_request,'// &
        'C_available_veg,N_available_veg,C_used_veg,N_used_veg,dm_leaf_actual,N_leaf_actual,C_leaf_actual,'// &
        'build_N_leaf,SLA_new,new_leaf_area,old_leaf_area_lost,LAI_end,N_uptake_day,N_assim_day'
      lai_opened=.true.
    endif
    write(lai_unit,'(5(I0,","),*(ES24.15E3,:,","))')control%RUN,control%YRDOY,lai_cn_mode,lai_accept_calls,lai_area_calls, &
      lai_cn_shape,lai_state,day_z(1),lai_signal,nonreserve,w_begin(1), &
      lai_min_begin,lai_crit_begin,lai_dm_raw,lai_dm_request,lai_c_available,lai_n_available,lai_veg_c,lai_veg_n, &
      lai_dm_actual,lai_n_actual,lai_c_actual,lai_build,lai_sla,lai_area,c4_area_dead,real(lai,dp),d_u3+d_u4,d_a3+d_a4
  end subroutine
  logical function NI_COMMON()
    NI_COMMON=common_acceptance==1
  end function
  logical function NI_RESERVES()
    NI_RESERVES=reserve_mode==1
  end function
  pure subroutine NI_JOINT_KERNEL(carbon,nitrogen,dm,build,target,agr,proi,fruit,repair, &
      accepted_dm,accepted_n,accepted_repair,fruit_cap,cost,scale,assim_price,free_n)
    real(dp),intent(in)::carbon,nitrogen,dm(3),build(3),target(3),agr(3),proi(3),fruit(2),repair(3)
    real(dp),intent(out)::accepted_dm(3),accepted_n(3),accepted_repair(3),fruit_cap(2),cost(3),scale
    real(dp),intent(in),optional::assim_price,free_n
    real(dp)::lower,total,gap,blend,composition(3),nreq,creq,price,free,lo,hi,mid,expense,veg_fraction,planned_dm(3)
    integer::i
    lower=sum(dm*build)+fruit(2)+sum(repair)
    total=sum(dm*target)+fruit(2)+sum(repair)
    gap=max(0._dp,total-lower)
    blend=max(0._dp,min(1._dp,(max(0._dp,nitrogen)-lower)/max(gap,1.e-30_dp)))
    composition=build+blend*(target-build)
    cost=agr*(1-(composition/.16_dp-proi)/(1-proi))
    planned_dm=dm
    if(present(assim_price).and.present(free_n))then
      price=max(0._dp,assim_price);free=max(0._dp,free_n)
      ! Keep the native reproductive C potential as a sink preference.
      ! Vegetative potential must first include its own N acquisition cost;
      ! otherwise ample-N plants spuriously lose fruit C to oversubscribed
      ! veg potential. Scarce N is still shared by ALL receivers below.
      expense=fruit(1)+max(0._dp,fruit(2)+sum(repair)-free)*price
      if(expense<=max(0._dp,carbon))then
        lo=0;hi=1
        do i=1,64
          mid=.5_dp*(lo+hi)
          expense=fruit(1)+mid*sum(dm*cost)+ &
            max(0._dp,fruit(2)+sum(repair)+mid*sum(dm*composition)-free)*price
          if(expense<=max(0._dp,carbon))then
            lo=mid
          else
            hi=mid
          endif
        enddo
        veg_fraction=lo;planned_dm=dm*veg_fraction
      endif
    endif
    creq=sum(planned_dm*cost)+fruit(1)
    nreq=sum(planned_dm*composition)+fruit(2)+sum(repair)
    scale=1
    if(creq>0)scale=min(scale,max(0._dp,carbon)/creq)
    if(nreq>0)scale=min(scale,max(0._dp,nitrogen)/nreq)
    if(present(assim_price).and.present(free_n))then
      price=max(0._dp,assim_price);free=max(0._dp,free_n)
      lo=0;hi=scale
      do i=1,64
        mid=.5_dp*(lo+hi)
        expense=mid*creq+max(0._dp,mid*nreq-free)*price
        if(expense<=max(0._dp,carbon))then
          lo=mid
        else
          hi=mid
        endif
      enddo
      scale=lo
    endif
    accepted_dm=planned_dm*scale;accepted_n=accepted_dm*composition
    accepted_repair=repair*scale;fruit_cap=fruit*scale
  end subroutine
  real function NI_P2_CARBON(pg)
    real,intent(in)::pg
    NI_P2_CARBON=pg
    if(NI_COMMON())NI_P2_CARBON=real(real(pg,dp)+d_cost)
  end function
  real function NI_P2_UNUSED_ASSIM()
    NI_P2_UNUSED_ASSIM=real(joint_assim_unused)
  end function
  subroutine NI_P2_POTENTIAL(dm,build,target,agr,proi)
    real,intent(in)::dm(3),build(3),target(3),agr(3),proi(3)
    joint_dm_req=max(0._dp,real(dm,dp));joint_build=real(build,dp);joint_target=real(target,dp)
    joint_agr=real(agr,dp);joint_proi=real(proi,dp)
    if(build_min_leaf>0)joint_build(1)=build_min_leaf*joint_target(1)
    if(build_min_stem>0)joint_build(2)=build_min_stem*joint_target(2)
    if(any(joint_build<0).or.any(joint_target<joint_build).or.any(joint_target>=.16_dp)) &
      error stop 'NI P2: new tissue composition order'
  end subroutine
  subroutine NI_P2_PLAN(carbon,nitrogen,fruit_c,fruit_n,root_target)
    real,intent(in)::carbon,nitrogen,fruit_c,fruit_n,root_target
    real(dp)::repair(3),nonreserve(3),target(3),amount,surviving_mass(3),price,free,accepted_n
    integer::i
    if(.not.NI_COMMON())return
    if(p2_plan_calls/=0)error stop 'NI P2: repeated common acceptance'
    p2_plan_calls=1
    joint_carbon=max(0._dp,real(carbon,dp)+d_cost);joint_nitrogen=max(0._dp,real(nitrogen,dp))
    price=d_cost/max(d_a3+d_a4,1.e-30_dp);free=max(0._dp,joint_nitrogen-d_a3-d_a4)
    joint_fruit_req=max(0._dp,real([fruit_c,fruit_n],dp))
    nonreserve=org_start-donor_n;surviving_mass=max(0._dp,w_begin-donor_n/.16_dp)
    nonreserve(1:2)=org_start(1:2)*(1-sen_frac(1:2))-mob_safe(1:2)-mob_func(1:2)
    surviving_mass(1:2)=max(0._dp,w_begin(1:2)*(1-sen_frac(1:2))-(mob_safe(1:2)+mob_func(1:2))/.16_dp)
    if(NI_RESERVES())nonreserve(1:2)=nonreserve(1:2)-max(0._dp,reserve_begin*(1-sen_frac(1:2))-mob_safe(1:2))
    target=[ccrit,real(root_target,dp)]
    repair=max(0._dp,(target*surviving_mass-nonreserve)/max(1.e-6_dp,1-target/.16_dp))*(1-exp(-1/growth_tau))
    where(surviving_mass<=1.e-4_dp)repair=0
    call NI_JOINT_KERNEL(joint_carbon,joint_nitrogen,joint_dm_req,joint_build,joint_target,joint_agr,joint_proi, &
      joint_fruit_req,repair,joint_dm,joint_nn,joint_repair,joint_fruit_cap,joint_unitcost,joint_scale,price,free)
    ! Only conservative rounding at the native float32 boundary, no new solve.
    do i=1,3
      amount=joint_dm(i);joint_dm(i)=real(flux32(amount),dp)
      if(amount>0)joint_nn(i)=joint_nn(i)*joint_dm(i)/amount
      joint_nn(i)=real(flux32(joint_nn(i)),dp)
      joint_repair(i)=real(flux32(joint_repair(i)),dp)
    enddo
    joint_fruit_cap=real([flux32(joint_fruit_cap(1)),flux32(joint_fruit_cap(2))],dp)
    accepted_n=sum(joint_nn)+sum(joint_repair)+joint_fruit_cap(2)
    joint_assim_n=max(0._dp,accepted_n-free);joint_assim_c=joint_assim_n*price
    joint_assim_unused=max(0._dp,d_a3+d_a4-joint_assim_n)
  end subroutine
  subroutine NI_P2_POD_BUDGET(carbon,nitrogen)
    real,intent(inout)::carbon,nitrogen
    if(.not.NI_COMMON())return
    if(p2_plan_calls/=1)error stop 'NI P2: fruit execution without common plan'
    carbon=min(carbon,real(joint_fruit_cap(1)));nitrogen=min(nitrogen,real(joint_fruit_cap(2)))
  end subroutine
  subroutine NI_P2_FRUIT_USED(carbon,nitrogen)
    real,intent(in)::carbon,nitrogen
    if(.not.NI_COMMON())return
    joint_fruit_used=real([carbon,nitrogen],dp)
    if(any(joint_fruit_used>joint_fruit_cap+2.e-5_dp))error stop 'NI P2: actual fruit exceeds accepted budget'
  end subroutine
  real function NI_P2_CSAVE(native,available)
    real,intent(in)::native,available
    NI_P2_CSAVE=native
    if(NI_COMMON())NI_P2_CSAVE=min(native,real(max(0._dp,real(available,dp)-sum(joint_dm*joint_unitcost))))
  end function
  subroutine NI_P2_VEG_ACCEPT(pg,available,cost,dm,nn)
    real,intent(in)::pg,available
    real,intent(out)::cost,dm(3),nn(3)
    real(dp)::unitcost(3),composition(3),total
    if(p2_plan_calls/=1.or.p2_veg_calls/=0)error stop 'NI P2: missing/repeated vegetative execution'
    p2_veg_calls=1
    dm=real(joint_dm);nn=real(joint_nn)
    composition=joint_nn/max(.16_dp*joint_dm,1.e-30_dp)
    unitcost=joint_agr*(1-(composition-joint_proi)/(1-joint_proi))
    total=sum(joint_dm)
    cost=1
    if(total>0)cost=real(sum(joint_dm*unitcost)/total)
    if(total*real(cost,dp)>real(pg,dp)+2.e-5_dp.or.sum(joint_nn)>real(available,dp)+1.e-6_dp) &
      error stop 'NI P2: accepted vegetative growth is not payable'
    veg_before=joint_dm_req;veg_after=joint_dm;leaf_gate=1
    veg_available=real(pg,dp);veg_cost=total*real(cost,dp)
  end subroutine
  pure subroutine NI_RESERVE_DONOR_KERNEL(n,w,reserve,cm,cc,legacy,rate,tau,slow,beta,z,protect_ratio, &
      growth_gap,total_gap,carbon,cost,safe,func,safe_max,func_max)
    real(dp),intent(in)::n(4),w(4),reserve(2),cm(2),cc(2),legacy(4),rate,tau,slow,beta,z,protect_ratio
    real(dp),intent(in)::growth_gap,total_gap,carbon,cost
    real(dp),intent(out)::safe(4),func(4)
    real(dp),intent(in),optional::safe_max,func_max
    real(dp)::nonreserve(4),s(4),f(4),room,scale,fraction
    nonreserve=n;nonreserve(1:2)=max(0._dp,n(1:2)-reserve)
    call NI_REMOB_KERNEL(nonreserve,w,cm,cc,legacy,rate,tau,slow,beta,z,1.e30_dp,1.e30_dp,cost,s,f,safe_max,func_max)
    fraction=1-exp(-1/tau)
    if(present(safe_max))fraction=min(fraction,max(0._dp,safe_max))
    safe=s;safe(1:2)=max(0._dp,reserve-protect_ratio*cc*w(1:2))*fraction
    room=max(0._dp,total_gap)
    if(cost>0)room=min(room,max(0._dp,carbon)/cost)
    scale=min(1._dp,room/max(sum(safe),1.e-30_dp));safe=safe*scale
    ! Healthy functional protein can support new growth, never an old-tissue
    ! repair-only request that would mine and rebuild the same function.
    room=min(max(0._dp,room-sum(safe)),max(0._dp,growth_gap-sum(safe)))
    scale=min(1._dp,room/max(sum(f),1.e-30_dp));func=f*scale
  end subroutine
  pure subroutine NI_RESERVE_COMMIT_KERNEL(begin,sen_fraction,fast,sen_recovered,fill,ending,recovered,litter,residual)
    real(dp),intent(in)::begin(2),sen_fraction(2),fast(2),sen_recovered(2),fill(2)
    real(dp),intent(out)::ending(2),recovered(2),litter(2),residual(2)
    recovered=min(begin*sen_fraction,max(0._dp,sen_recovered))
    litter=begin*sen_fraction-recovered
    ending=begin-fast-recovered-litter+fill
    residual=ending-begin+fast+recovered+litter-fill
  end subroutine
  subroutine NI_P2_COMMIT_RESERVES(n,w)
    real,intent(in)::n(2),w(2)
    if(.not.NI_RESERVES())return
    if(.not.reserve_pending)error stop 'NI P2: repeated reserve commit'
    reserve_release=mob_safe(1:2)
    call NI_RESERVE_COMMIT_KERNEL(reserve_begin,sen_frac(1:2),reserve_release,mob_sen(1:2),reserve_fill, &
      reserve_n,reserve_sen_recovery,reserve_litter,reserve_residual)
    if(minval(reserve_n)<-1.e-12_dp.or.any(reserve_n>real(n,dp)+1.e-7_dp)) &
      error stop 'NI P2: organic reserve is not a subset of organic N'
    if(any(reserve_n>reserve_capacity*max(real(w,dp),carrier(1:2)*(1-sen_frac(1:2)))+1.e-9_dp)) &
      error stop 'NI P2: organic reserve nominal capacity exceeded'
    if(maxval(abs(reserve_residual))>1.e-12_dp)error stop 'NI P2: organic reserve budget'
    reserve_pending=.false.
  end subroutine
  real function NI_P2_RNITP(n,mass,current)
    real,intent(in)::n,mass,current
    NI_P2_RNITP=current
    if(NI_RESERVES().and.mass>1.e-4)NI_P2_RNITP=real(100*max(0._dp,real(n,dp)-reserve_n(1))/real(mass,dp))
  end function
  subroutine write_p2(control,n)
    type(ControlType),intent(in)::control
    real,intent(in)::n(3)
    integer::ios
    if(.not.p2_opened)then
      open(newunit=p2_unit,file='PlantNP2.csv',status='new',action='write',iostat=ios)
      if(ios/=0)error stop 'NI P2: cannot create common/reserve ledger'
      write(p2_unit,'(A)')'run,yrdoy,common_acceptance,reserve_mode,plan_calls,veg_calls,C_available,N_available,'// &
        'fruit_C_request,fruit_N_request,fruit_C_cap,fruit_N_cap,fruit_C_used,fruit_N_used,common_scale,'// &
        'dm_request_leaf,dm_request_stem,dm_request_root,dm_accept_leaf,dm_accept_stem,dm_accept_root,'// &
        'N_accept_leaf,N_accept_stem,N_accept_root,unit_C_leaf,unit_C_stem,unit_C_root,'// &
        'repair_accept_leaf,repair_accept_stem,repair_accept_root,repair_used_leaf,repair_used_stem,repair_used_root,'// &
        'R_begin_leaf,R_begin_stem,R_end_leaf,R_end_stem,R_fill_leaf,R_fill_stem,R_fast_leaf,R_fast_stem,'// &
        'R_sen_recovery_leaf,R_sen_recovery_stem,R_litter_leaf,R_litter_stem,R_residual_leaf,R_residual_stem,'// &
        'R_capacity_leaf,R_capacity_stem,N_nonreserve_leaf,N_nonreserve_stem,C_assim_accepted,N_assim_accepted,'// &
        'build_N_leaf,build_N_stem,build_N_root,target_N_leaf,target_N_stem,target_N_root'
      p2_opened=.true.
    endif
    write(p2_unit,'(2(I0,","),*(ES24.15E3,:,","))')control%RUN,control%YRDOY, &
      real([common_acceptance,reserve_mode,p2_plan_calls,p2_veg_calls],dp),joint_carbon,joint_nitrogen, &
      joint_fruit_req,joint_fruit_cap,joint_fruit_used,joint_scale,joint_dm_req,joint_dm,joint_nn,joint_unitcost, &
      joint_repair,joint_repair_used,reserve_begin,reserve_n,reserve_fill,reserve_release, &
      reserve_sen_recovery,reserve_litter,reserve_residual,max(0._dp,reserve_capacity)*carrier(1:2),real(n(1:2),dp)-reserve_n, &
      joint_assim_c,joint_assim_n,joint_build,joint_target
  end subroutine
  logical function NI_C4_PHOTO()
    NI_C4_PHOTO=ni_stage==5.and.budget_revision==1.and.c4_photo==1.and.ready
  end function
  pure subroutine NI_CANOPY_N_KERNEL(lai,slaad,nitrogen,slopes,mass,npercent)
    real(dp),intent(in)::lai(2),slaad,nitrogen,slopes(2)
    real(dp),intent(out)::mass(2),npercent(2)
    real(dp)::mean_mass,total,target,actual
    mass=0;npercent=0;total=sum(max(0._dp,lai))
    if(slaad<=0.or.total<=1.e-12_dp) return
    mean_mass=1/slaad
    mass=max(0._dp,mean_mass+.5_dp*slopes(1)*[lai(2),-lai(1)])
    mass=mass*(mean_mass*total)/max(sum(mass*lai),1.e-30_dp)
    npercent=max(0._dp,nitrogen+.5_dp*slopes(2)*[lai(2),-lai(1)])
    target=max(0._dp,nitrogen)/100*mean_mass*total
    actual=sum(npercent/100*mass*lai)
    if(actual>1.e-30_dp)then
      npercent=npercent*target/actual
    else
      ! Disjoint, extreme slopes cannot erase the existing canopy N stock.
      npercent=max(0._dp,nitrogen)
    endif
  end subroutine
  subroutine NI_CANOPY_N(lsl,lsh,slaad,nitrogen,slwslo,nslope,slwsl,slwsh,pcnsl,pcnsh)
    real,intent(in)::lsl,lsh,slaad,nitrogen,slwslo,nslope
    real,intent(out)::slwsl,slwsh,pcnsl,pcnsh
    real(dp)::mass(2),pcn(2)
    call NI_CANOPY_N_KERNEL(real([lsl,lsh],dp),real(slaad,dp),real(nitrogen,dp), &
      real([slwslo,nslope],dp),mass,pcn)
    slwsl=real(mass(1));slwsh=real(mass(2));pcnsl=real(pcn(1));pcnsh=real(pcn(2))
  end subroutine
  subroutine NI_C4_FRACTIONS(fraction)
    real(dp),intent(out)::fraction(3)
    fraction=sen_frac
  end subroutine
  logical function NI_C4_ON()
    NI_C4_ON=ni_stage==5.and.budget_revision==1.and.c4_budget==1
  end function
  logical function NI_LEAF_COUPLED()
    NI_LEAF_COUPLED=NI_C4_ON().and.leaf_coupling==1
  end function
  pure subroutine NI_CARB_KERNEL(q0,growth,alpha,addition,draw,fraction,q1,litter)
    real(dp),intent(in)::q0,growth,alpha,addition,draw,fraction
    real(dp),intent(out)::q1,litter
    litter=max(0._dp,q0-draw)*max(0._dp,min(1._dp,fraction))
    q1=q0+alpha*growth+addition-draw-litter
  end subroutine
  pure subroutine NI_SHELL_CARB_KERNEL(q0,growth,alpha,draw,mass_before_loss,loss,mature,ratio,q1,out,locked)
    real(dp),intent(in)::q0,growth,alpha,draw,mass_before_loss,loss,mature,ratio
    real(dp),intent(out)::q1,out,locked
    real(dp)::q
    q=q0+alpha*growth-draw
    out=max(0._dp,q)*min(1._dp,max(0._dp,loss)/max(mass_before_loss,1.e-12_dp))
    locked=min(max(0._dp,q-out),max(0._dp,mature*ratio))
    q1=q-out-locked
  end subroutine
  subroutine NI_C4_CASH(control,pg,main,draw,assim,mob,veg,fruit,store,predicted_unused,main_potential)
    type(ControlType),intent(in)::control
    real,intent(in)::pg,main,draw(4),assim,mob,veg,fruit,store,predicted_unused,main_potential
    real(dp)::res,scale
    integer::ios
    if(.not.NI_C4_ON()) return
    res=real(pg,dp)+sum(real(draw,dp))-real(main,dp)-real(assim,dp)-real(mob,dp) &
      -real(veg,dp)-real(fruit,dp)-real(store,dp)
    scale=max(1._dp,abs(real(pg,dp)),sum(real(draw,dp)))
    if(abs(res)>32*epsilon(1.)*scale) then
      write(*,*)'NI C4 cash failure run/day/res:',control%RUN,control%YRDOY,res
      write(*,*)'PG,draw,maintenance,assim,mob,veg,fruit,store,unused,maintenance potential:', &
        pg,draw,main,assim,mob,veg,fruit,store,predicted_unused,main_potential
      error stop 'NI C4: actual carbohydrate expenditure imbalance'
    endif
    if(.not.cash_opened) then
      open(newunit=cash_unit,file='PlantCCash.csv',status='new',action='write',iostat=ios)
      if(ios/=0)error stop 'NI C4: cannot create carbohydrate expenditure ledger'
      write(cash_unit,'(A)')'run,yrdoy,PG,actual_C_mined,maintenance,N_assim,N_resynthesis,veg_growth,fruit_growth,'// &
        'storage_cost,CH2O_residual,C_equivalent_residual,predicted_unused_not_a_stock,'// &
        'maintenance_potential,maintenance_unpaid'
      cash_opened=.true.
    endif
    write(cash_unit,'(2(I0,","),12(ES24.15E3,","),ES24.15E3)')control%RUN,control%YRDOY,real(pg,dp), &
      sum(real(draw,dp)),real(main,dp),real(assim,dp),real(mob,dp),real(veg,dp),real(fruit,dp),real(store,dp), &
      res,.4_dp*res,real(predicted_unused,dp),real(main_potential,dp),real(main_potential,dp)-real(main,dp)
  end subroutine
  real function NI_N_SEN_EXTRA(weight,baseline)
    real,intent(in)::weight,baseline
    NI_N_SEN_EXTRA=0
    if(NI_LEAF_COUPLED())NI_N_SEN_EXTRA=real(min(max(0._dp,real(weight-baseline,dp)), &
      max(0._dp,real(weight,dp))*(1-exp(-n_sen_rate*(1-day_growth)**2))))
  end function
  subroutine NI_C4_SEN_PLAN(loss,area)
    real,intent(in)::loss(2),area
    sen_plan_dm=min(w_begin(1:2),max(0._dp,real(loss,dp)))
    sen_frac(1:2)=sen_plan_dm/max(w_begin(1:2),1.e-12_dp)
    sen_available=0
    sen_available(1:2)=max(0._dp,org_start(1:2)*sen_frac(1:2)-cmin*sen_plan_dm)
    c4_area_dead=real(area,dp)*sen_frac(1)
  end subroutine
  subroutine NI_C4_FATE(sl,ss,sln,ssn,sr,senrt,nlayers,draw,wlid,wlfd,wsid,wrid)
    integer,intent(in)::nlayers
    real,intent(inout)::sl,ss,sln,ssn,sr,senrt(:)
    real,intent(in)::draw(3),wlid,wlfd,wsid,wrid
    real(dp)::loss(2),root_mass_before,old_sr
    if(.not.NI_LEAF_COUPLED()) return
    ! Extra damage is not silently assimilated into the planned aging pool.
    if(max(wlid,wlfd,wsid,wrid)>1.e-7)error stop 'NI C4: unplanned pest/freeze loss needs explicit receiver settlement'
    loss=sen_plan_dm-mob_sen(1:2)/.16_dp-real(draw(1:2),dp)*sen_frac(1:2)
    if(minval(loss)<-1.e-6_dp)error stop 'NI C4: reclaimed material exceeds planned senescence'
    c4_nloss(1:2)=max(0._dp,org_start(1:2)*sen_frac(1:2)-mob_sen(1:2))
    if(sl>0)sln=real(real(sln,dp)*max(0._dp,loss(1))/real(sl,dp))
    if(ss>0)ssn=real(real(ssn,dp)*max(0._dp,loss(2))/real(ss,dp))
    sl=real(max(0._dp,loss(1)));ss=real(max(0._dp,loss(2)))
    old_sr=max(0._dp,real(sr,dp))
    sen_frac(3)=min(1._dp,old_sr/max(w_begin(3),1.e-12_dp))
    root_mass_before=max(0._dp,w_begin(3)-donor_n(3)/.16_dp-real(draw(3),dp))
    sr=real(root_mass_before*sen_frac(3))
    if(old_sr>0)senrt(1:nlayers)=real(real(senrt(1:nlayers),dp)*real(sr,dp)/old_sr)
    c4_nloss(3)=max(0._dp,org_start(3)-donor_n(3))*sen_frac(3)
  end subroutine
  subroutine NI_C4_NLOSS(nloss)
    real,intent(out)::nloss(3)
    nloss=real(c4_nloss)
  end subroutine
  real function NI_C4_AREA(newarea)
    real,intent(in)::newarea
    NI_C4_AREA=real(real(newarea,dp)-c4_area_dead)
  end function
  logical function NI_LUX_ON()
    NI_LUX_ON=ni_stage==5.and.budget_revision==1.and.luxury_priority==1
  end function
  real function NI_CORE_DEMAND(total,new_n,root_target)
    real,intent(in)::total,new_n,root_target
    real(dp)::target(3),room(3),functional(3)
    NI_CORE_DEMAND=total
    if(luxury_priority/=1) return
    target=[ccrit(1),ccrit(2),real(root_target,dp)]
    functional=org_start
    if(NI_RESERVES())functional(1:2)=functional(1:2)-reserve_begin
    room=max(0._dp,(target*w_begin-functional)/max(1.e-6_dp,1-target/.16_dp))
    where(w_begin<=1.e-4_dp)room=0
    NI_CORE_DEMAND=real(min(max(0._dp,real(total,dp)),max(0._dp,real(new_n,dp))+sum(room)))
  end function
  pure subroutine NI_LATE_KERNEL(q,remaining,carbon,cost,receiver,a)
    real(dp),intent(in)::q(2),remaining(2),carbon,cost(2),receiver
    real(dp),intent(out)::a(2)
    real(dp)::f
    a=min(max(0._dp,q),max(0._dp,remaining))
    f=min(1._dp,max(0._dp,receiver)/max(sum(a),1.e-30_dp));a=a*f
    f=min(1._dp,max(0._dp,carbon)/max(sum(a*cost),1.e-30_dp));a=a*f
  end subroutine
  subroutine NI_LUXURY(pg,dm,nn,cr,pch,csave,cad,nad,navl,nassim,rsp3,rsp4)
    real,intent(inout)::pg,cad(2),nad(3),navl,nassim,rsp3,rsp4
    real,intent(in)::dm(3),nn(3),cr(3),pch,csave
    real(dp)::mass(2),stock(2),room(2),repair(2),a(2),cost(2),spare,f,amount,take(2),extra(2),previous(2)
    real(dp)::r_surv(2),r_goal(2),r_room(2),r_cap(2),gapc(2)
    if(luxury_priority/=1) return
    ! Existing growth, core repairs and native reserved CSAVEV keep priority.
    spare=max(0._dp,sum(real(cad,dp))*real(pch,dp)-max(0._dp,real(csave,dp)))
    late_c_budget=spare
    late_c_before=sum(real(cad,dp))*real(pch,dp);late_c_reserved=max(0._dp,real(csave,dp))
    previous=real(cad,dp)
    f=min(1._dp,spare/max(sum(previous)*real(pch,dp),1.e-30_dp))
    ! A conservative receiver excludes ALL discretionary C storage before
    ! determining space; later actual spending can only increase that space.
    mass=max(0._dp,w_begin(1:2)+real(dm(1:2),dp)+previous*(1-f)- &
      donor_n(1:2)/.16_dp-real(cr(1:2),dp)+real(nad(1:2),dp)/.16_dp)
    stock=max(0._dp,org_start(1:2)+real(nn(1:2),dp)-donor_n(1:2)+real(nad(1:2),dp))
    if(NI_COMMON().or.NI_RESERVES())then
      ! Match C4's actual surviving receiver: reclaimed senescing protein
      ! was already debited as donor, and remaining cell loss occurs once.
      mass=max(0._dp,mass-sen_plan_dm+mob_sen(1:2)/.16_dp+real(cr(1:2),dp)*sen_frac(1:2))
      stock=max(0._dp,stock-org_start(1:2)*sen_frac(1:2)+mob_sen(1:2))
    endif
    room=max(0._dp,(cmax*mass-stock)/max(1.e-6_dp,1-cmax/.16_dp))
    repair=max(0._dp,(ccrit*mass-stock)/max(1.e-6_dp,1-ccrit/.16_dp))
    if(NI_RESERVES())then
      r_surv=max(0._dp,reserve_begin*(1-sen_frac(1:2))-mob_safe(1:2))
      repair=max(0._dp,(ccrit*mass-stock+r_surv)/max(1.e-6_dp,1-ccrit/.16_dp))
      gapc=cmax-ccrit
      r_cap=reserve_capacity*max(mass,carrier(1:2)*(1-sen_frac(1:2)))
      r_goal=max(0._dp,(gapc*mass-r_surv)/max(1.e-6_dp,1-gapc/.16_dp))
      r_room=min(max(0._dp,r_cap-r_surv),r_goal)*(1-exp(-1/reserve_fill_tau))
      where(mass<=1.e-4_dp.or.donor_n(1:2)>1.e-12_dp)r_room=0
      room=repair+r_room
    endif
    if(NI_COMMON())then
      ! Growth and functional repair were jointly accepted once. Remaining
      ! kinetic/C room can fill a true reserve, never rerun growth/repair.
      if(NI_RESERVES())then
        where(stock-r_surv<ccrit*mass)r_room=0
        room=r_room
      else
        where(stock<ccrit*mass)room=0
      endif
      repair=0
    endif
    where(mass<=1.e-4_dp.or.donor_n(1:2)>1.e-12_dp)room=0
    repair=min(repair,room)
    cost=late_unit_cost
    call NI_LATE_KERNEL([sum(q3),sum(q4)],kinetic_cap-[d_a3,d_a4],spare,cost,sum(room),a)
    amount=real(flux32(sum(a)),dp);a=a*amount/max(sum(a),1.e-30_dp)
    take=0;extra=0
    f=min(1._dp,amount/max(sum(repair),1.e-30_dp));take=repair*f
    amount=max(0._dp,amount-sum(take));room=max(0._dp,room-take)
    if(NI_RESERVES())room=r_room
    f=min(1._dp,amount/max(sum(room),1.e-30_dp));extra=room*f
    late_func=sum(take);late_lux=sum(extra);late_a=a;late_cost=sum(a*cost)
    if(late_cost>spare+1.e-8_dp)error stop 'NI v3: luxury assimilation exceeds residual C'
    call remove(q3,a(1));call remove(q4,a(2))
    d_a3=d_a3+a(1);d_a4=d_a4+a(2)
    rsp3=rsp3+real(a(1)*cost(1));rsp4=rsp4+real(a(2)*cost(2))
    d_cost=real(rsp3,dp)+real(rsp4,dp)
    pg=pg-real(late_cost)
    ! Pay once by replacing discretionary storage, not by taking C from
    ! already accepted new tissues or invoking VEGGR/PODS a second time.
    f=max(0._dp,1-late_cost/max(sum(previous)*real(pch,dp),1.e-30_dp))
    cad=real(previous*f)
    late_c_after=sum(real(cad,dp))*real(pch,dp);late_nad=take+extra
    if(NI_RESERVES())reserve_fill=reserve_fill+extra
    nad(1:2)=nad(1:2)+real(take+extra)
    refill_n=real(nad,dp)
    navl=navl+real(sum(a));nassim=real(d_a3+d_a4)
  end subroutine
  real function NI_REDUCTION_RESP(tr3,tr4,nfix)
    real,intent(in)::tr3,tr4,nfix
    real(dp)::a3,a4
    a3=real(tr3,dp);a4=real(tr4,dp)
    if(NI_ENABLED())then
      a3=d_a3;a4=d_a4
    endif
    NI_REDUCTION_RESP=real(30._dp/44*(a3/.16_dp*1.798_dp+a4/.16_dp*.462_dp+real(nfix,dp)/.16_dp*1.798_dp))
  end function
  logical function NI_REMOB_ON()
    NI_REMOB_ON=ni_stage==5.and.budget_revision==1.and.remob_mode==1
  end function
  pure subroutine NI_REMOB_KERNEL(n,w,cm,cc,legacy,rate,tau,slow,beta,z,gap,carbon,cost,safe,func,safe_max,func_max)
    real(dp),intent(in)::n(4),w(4),cm(2),cc(2),legacy(4),rate,tau,slow,beta,z,gap,carbon,cost
    real(dp),intent(out)::safe(4),func(4)
    real(dp),intent(in),optional::safe_max,func_max
    real(dp)::available(2),protect(2),remaining,total,factor,fast_fraction,slow_fraction
    protect=w(1:2)*(cm+beta*(cc-cm))
    available=max(0._dp,n(1:2)-cc*w(1:2))
    safe=0;func=0
    fast_fraction=1-exp(-1/tau);slow_fraction=1-exp(-1/(tau*slow))
    if(present(safe_max))fast_fraction=min(fast_fraction,max(0._dp,safe_max))
    if(present(func_max))slow_fraction=min(slow_fraction,max(0._dp,func_max))
    safe(1:2)=available*fast_fraction
    ! Keep the native root/shell donor paths, never increase their rate.
    safe(3:4)=min(max(0._dp,n(3:4)),max(0._dp,legacy(3:4)))*max(0._dp,min(1._dp,rate))
    if(present(safe_max))safe(3:4)=min(safe(3:4), &
      min(max(0._dp,n(3:4)),max(0._dp,legacy(3:4)))*max(0._dp,safe_max))
    available=max(0._dp,min(n(1:2),cc*w(1:2))-protect)
    func(1:2)=available*slow_fraction*(1-max(0._dp,min(1._dp,z)))**2
    remaining=max(0._dp,gap)
    if(cost>0) remaining=min(remaining,max(0._dp,carbon)/cost)
    total=sum(safe);factor=min(1._dp,remaining/max(total,1.e-30_dp));safe=safe*factor
    remaining=max(0._dp,remaining-sum(safe))
    total=sum(func);factor=min(1._dp,remaining/max(total,1.e-30_dp));func=func*factor
  end subroutine
  subroutine NI_REMOB_PLAN(demand,supply,pg,cdemand,n,w,legacy,rate,rpro,nmine,flux)
    real,intent(in)::demand,supply,pg,cdemand,n(4),w(4),legacy(4),rate,rpro
    real,intent(out)::nmine,flux(4)
    real(dp)::ratio,gap,paid,z,factor,total,healthy_n(4),healthy_w(4),remaining,remaining_c
    real(dp)::growth_gap,repair_gap,healthy_reserve(2)
    integer::i
    ! Conservative C/N acceptance predictor, not a replay of stateful PODS.
    ! The final accepted amount is reconciled against actual growth below.
    ratio=max(0._dp,real(demand,dp))/max(real(cdemand,dp),1.e-12_dp)
    paid=max(0._dp,real(rpro,dp))/.16_dp
    mob_accept=min(max(0._dp,real(demand,dp)),ratio*max(0._dp,real(pg,dp)))
    gap=min(max(0._dp,real(demand-supply,dp)), &
      max(0._dp,ratio*real(pg,dp)-real(supply,dp))/(1+ratio*paid))
    growth_gap=gap
    repair_gap=0
    if(NI_RESERVES())then
      repair_gap=sum(max(0._dp,ccrit*w_begin(1:2)-(org_start(1:2)-reserve_begin)))*(1-exp(-1/growth_tau))
      gap=growth_gap+repair_gap
      if(paid>0)gap=min(gap,max(0._dp,real(pg,dp))/paid)
    endif
    mob_gap=gap;z=day_growth ! shared smoothed C1 state; no second severity clock
    if(remob_severity==0) z=0
    healthy_n=real(n,dp);healthy_w=real(w,dp);mob_sen=0;healthy_reserve=0
    remaining=gap;remaining_c=max(0._dp,real(pg,dp))
    if(NI_LEAF_COUPLED())then
      ! Planned dying material is disjoint from healthy donor balances.
      healthy_n(1:2)=healthy_n(1:2)*(1-sen_frac(1:2))
      healthy_w(1:2)=healthy_w(1:2)*(1-sen_frac(1:2))
      total=sum(sen_available)
      if(paid>0)remaining=min(remaining,remaining_c/paid)
      mob_sen=sen_available*min(1._dp,remaining/max(total,1.e-30_dp))
      remaining=max(0._dp,gap-sum(mob_sen));remaining_c=max(0._dp,remaining_c-paid*sum(mob_sen))
    endif
    if(NI_RESERVES())then
      healthy_reserve=reserve_begin*(1-sen_frac(1:2))
      call NI_RESERVE_DONOR_KERNEL(healthy_n,healthy_w,healthy_reserve,cmin,ccrit,real(legacy,dp),real(rate,dp), &
        remob_tau,slow_ratio,protect_beta,z,reserve_protect,max(0._dp,growth_gap-sum(mob_sen)), &
        remaining,remaining_c,paid,mob_safe,mob_func,remob_fast_limit(),remob_slow_limit())
    else
      call NI_REMOB_KERNEL(healthy_n,healthy_w,cmin,ccrit,real(legacy,dp),real(rate,dp), &
        remob_tau,slow_ratio,protect_beta,z,remaining,remaining_c,paid,mob_safe,mob_func,remob_fast_limit(),remob_slow_limit())
    endif
    mob_rate_cap=0;mob_function_cap=0
    mob_rate_cap(1:2)=max(0._dp,healthy_n(1:2)-ccrit*healthy_w(1:2))* &
      min(1-exp(-1/remob_tau),remob_fast_limit())
    if(NI_RESERVES())mob_rate_cap(1:2)=max(0._dp,healthy_reserve-reserve_protect*ccrit*healthy_w(1:2))* &
      min(1-exp(-1/remob_tau),remob_fast_limit())
    mob_rate_cap(3:4)=min(max(0._dp,healthy_n(3:4)),max(0._dp,real(legacy(3:4),dp)))* &
      min(max(0._dp,min(1._dp,real(rate,dp))),remob_fast_limit())
    mob_function_cap(1:2)=max(0._dp,min(healthy_n(1:2)-healthy_reserve,ccrit*healthy_w(1:2))- &
      healthy_w(1:2)*(cmin+protect_beta*(ccrit-cmin)))* &
      min(1-exp(-1/(remob_tau*slow_ratio)),remob_slow_limit())*(1-max(0._dp,min(1._dp,z)))**2
    mob_plan=mob_safe+mob_func+mob_sen
    ! Round down once at the host boundary; retain source components.
    do i=1,4
      flux(i)=flux32(mob_plan(i))
    end do
    do i=1,4
      total=mob_plan(i);factor=real(flux(i),dp)/max(total,1.e-30_dp)
      mob_safe(i)=mob_safe(i)*factor;mob_func(i)=mob_func(i)*factor;mob_sen(i)=mob_sen(i)*factor
    end do
    mob_plan=real(flux,dp);mob_returned=0;mob_new_used=0
    nmine=sum(flux);mob_c_paid=real(nmine,dp)*paid
    if(mob_c_paid>real(pg,dp)+1.e-6_dp) error stop 'NI v3: unaffordable mobilization'
  end subroutine
  real(dp) function remob_fast_limit()
    remob_fast_limit=1
    if(remob_rate_mode==1)remob_fast_limit=remob_rate_max
  end function
  real(dp) function remob_slow_limit()
    remob_slow_limit=1
    if(remob_rate_mode==1)remob_slow_limit=functional_rate_max
  end function
  subroutine NI_REMOB_REPRO(used)
    real,intent(in)::used
    if(NI_REMOB_ON()) mob_new_used=max(0._dp,real(used,dp))
  end subroutine
  subroutine NI_REMOB_SETTLE(unused,veg_used,rpro,nmine,flux,returned,refund)
    real,intent(in)::unused,veg_used,rpro
    real,intent(inout)::nmine,flux(4)
    real,intent(out)::returned,refund
    real(dp)::left,total,take(4),part(4),amount,factor,old
    integer::j,k
    left=max(0._dp,real(unused,dp));mob_new_used=mob_new_used+max(0._dp,real(veg_used,dp))
    ! Shell mining is integrated into cohorts/harvest inside PODS. It stays
    ! on the native path and is never undone after those irreversible calls.
    if(mob_plan(4)>mob_new_used+1.e-6_dp) error stop 'NI v3: native shell export has no growth recipient'
    if((NI_COMMON().or.NI_RESERVES()).and.mob_new_used+mob_repair_used==0)then
      ! Float32 SUM(unused) can be slightly below the component-wise double
      ! total. A nonexistent recipient must cancel every provisional source,
      ! rather than leave a tiny irreversible reserve export.
      left=max(left,sum(mob_safe(1:3)+mob_func(1:3)+mob_sen(1:3)))
    endif
    old=real(nmine,dp);take=0
    do k=1,3
      if(k==1) then
        part=mob_func
      else if(k==2)then
        part=mob_safe
      else
        part=mob_sen
      endif
      part(4)=0
      total=sum(part);amount=min(left,total);factor=amount/max(total,1.e-30_dp)
      do j=1,3
        if(k==1) then
          mob_func(j)=mob_func(j)*(1-factor)
        else if(k==2)then
          mob_safe(j)=mob_safe(j)*(1-factor)
        else
          mob_sen(j)=mob_sen(j)*(1-factor)
        endif
        take(j)=take(j)+part(j)*factor
      enddo
      left=max(0._dp,left-amount)
    enddo
    do j=1,3
      total=mob_safe(j)+mob_func(j)+mob_sen(j)
      flux(j)=flux32(total)
      factor=real(flux(j),dp)/max(total,1.e-30_dp)
      mob_safe(j)=mob_safe(j)*factor;mob_func(j)=mob_func(j)*factor;mob_sen(j)=mob_sen(j)*factor
    enddo
    nmine=sum(flux)
    returned=real(max(0._dp,old-real(nmine,dp)))
    refund=returned/.16*max(0.,rpro)
    mob_returned=mob_plan-real(flux,dp)
    mob_c_paid=real(nmine,dp)*max(0._dp,real(rpro,dp))/.16_dp
    if(real(returned,dp)>real(unused,dp)+1.e-6_dp) error stop 'NI v3: cancellation exceeds unaccepted supply'
    if(real(nmine,dp)>mob_new_used+mob_repair_used+1.e-6_dp) error stop 'NI v3: internal export has no accepted recipient'
    if(NI_RESERVES().and.sum(mob_func)>mob_new_used+1.e-6_dp)error stop 'NI P2: healthy function exported for repair only'
    donor_n=real(flux(1:3),dp)
  end subroutine
  logical function NI_PODS()
    NI_PODS=pods_n_state==1.and.day_valid
  end function
  pure real(dp) function NI_POD_KERNEL(z) result(f)
    real(dp),intent(in)::z
    ! V15 functional-response shape; new daily Z, not its old state scale.
    f=1-(1-max(0._dp,min(1._dp,z)))**2
  end function
  real function NI_POD_FACTOR()
    NI_POD_FACTOR=real(NI_POD_KERNEL(day_z(1)))
  end function
  subroutine NI_OPEN_DAY(control)
    type(ControlType),intent(in)::control
    if(state_timing==0.and.pods_n_state==0) return
    if(day_run==control%RUN.and.day_date==control%YRDOY) return
    day_run=control%RUN;day_date=control%YRDOY
    day_valid=ready.and.end_run==control%RUN
    day_source=-1;day_z=0;day_growth=1;day_veg_z=1
    if(day_valid) then
      if(end_day>=control%YRDOY) error stop 'NI v3: current/future state in day snapshot'
      day_source=end_day;day_z=z_end;day_growth=growth_factor;day_veg_z=veg_z_end
    end if
  end subroutine
  subroutine NI_SYNC_STATE(control,nstres)
    type(ControlType),intent(in)::control
    real,intent(inout)::nstres
    call NI_OPEN_DAY(control)
    if(state_timing==1.and.day_valid) nstres=real(day_growth)
  end subroutine
  logical function NI_REVISED()
    NI_REVISED=ni_stage>=4.and.budget_revision==1
  end function
  subroutine NI_DONORS(nmobil,cmobil)
    real,intent(in)::nmobil(3),cmobil(3)
    donor_n=max(0._dp,real(nmobil,dp)); donor_c=max(0._dp,real(cmobil,dp))
  end subroutine
  real function NI_RETAIN(loss_fraction)
    real,intent(in)::loss_fraction
    NI_RETAIN=1-min(1.,max(0.,loss_fraction))
    ! A allocates refills to today's surviving receiver, after old tissue
    ! loss. They must not be debited a second time by a survival fraction.
    if(NI_REVISED()) NI_RETAIN=1.
  end function
  real function NI_EXPANSION(dm,nnew)
    real,intent(in)::dm,nnew
    real(dp)::concentration,x
    if(leaf_expansion_mode==1.or.NI_COMMON().or.NI_LAI_ON())then
      ! Ablation: native new-tissue C/N acceptance and shared allocation
      ! remain; omit the additional organ-concentration policy multiplier.
      NI_EXPANSION=1.
      return
    endif
    concentration=max(0._dp,org_start(1)-donor_n(1)+real(nnew,dp))/ &
      max(1.e-12_dp,w_begin(1)-donor_n(1)/.16_dp-donor_c(1)+real(dm,dp))
    x=max(0._dp,min(1._dp,(concentration-cmin(1))/(ccrit(1)-cmin(1))))
    ! Fast inhibition near the lower reference, slower recovery retained.
    NI_EXPANSION=real(min(growth_factor,x))
  end function
  real function NI_AREA_REFILL(nad)
    real,intent(in)::nad
    NI_AREA_REFILL=nad
    if(NI_REVISED()) NI_AREA_REFILL=real(min(real(nad,dp), &
      max(0._dp,ccrit(1)*w_begin(1)-org_start(1)+donor_n(1))))
  end function
  subroutine NI_MINIMUM(wl,ws,ml,ms)
    real,intent(in)::wl,ws
    real,intent(out)::ml,ms
    call references([real(wl,dp),real(ws,dp),0._dp])
    ml=real(cmin(1));ms=real(cmin(2))
  end subroutine
  subroutine NI_VEG_RECONCILE(pg,cost,dm,nn,agrs,proi)
    real,intent(in)::pg,agrs(3),proi(3)
    real,intent(inout)::cost,dm(3),nn(3)
    real(dp)::scale,total,oldtotal,unitcost(3),composition(3)
    if(.not.NI_REVISED()) return
    veg_available=real(pg,dp);veg_cost=0;leaf_gate=1
    veg_before=real(dm,dp);veg_after=veg_before
    oldtotal=sum(real(dm,dp))
    if(oldtotal<=0) return
    ! Preserve the actual N composition selected by VEGGR. Reduce potential
    ! leaf DM and its associated N together; unused N goes to independent
    ! existing-tissue refill, rather than being destroyed.
    composition=real(nn,dp)/max(.16_dp*real(dm,dp),1.e-30_dp)
    unitcost=real(agrs,dp)*(1-(composition-real(proi,dp))/(1-real(proi,dp)))
    scale=real(NI_EXPANSION(dm(1),nn(1)),dp)
    leaf_gate=scale
    dm(1)=real(real(dm(1),dp)*scale);nn(1)=real(real(nn(1),dp)*scale)
    total=sum(real(dm,dp))
    if(total>0) cost=real(sum(real(dm,dp)*unitcost)/total)
    scale=min(1._dp,max(0._dp,real(pg,dp))/max(total*real(cost,dp),1.e-30_dp))
    dm=real(real(dm,dp)*scale);nn=real(real(nn,dp)*scale)
    veg_available=real(pg,dp);veg_cost=sum(real(dm,dp))*real(cost,dp)
    veg_after=real(dm,dp)
  end subroutine
  subroutine NI_V4_STORAGE_SHIFT(amount)
    real,intent(in)::amount
    storage_shift=real(amount,dp)
  end subroutine
  subroutine NI_REFILL(available,dm,nn,cad,cr,root_target,nad,unused)
    real,intent(in)::available,dm(3),nn(3),cad(3),cr(3),root_target
    real,intent(out)::nad(3),unused
    real(dp)::mass(3),stock(3),target(3),room(3),total,amount
    mass=max(0._dp,w_begin+real(dm,dp)+real(cad,dp)-donor_n/.16_dp-real(cr,dp))
    stock=max(0._dp,org_start+real(nn,dp)-donor_n)
    if(NI_COMMON().or.NI_RESERVES())then
      mass(1:2)=max(0._dp,mass(1:2)-sen_plan_dm+mob_sen(1:2)/.16_dp+real(cr(1:2),dp)*sen_frac(1:2))
      stock(1:2)=max(0._dp,stock(1:2)-org_start(1:2)*sen_frac(1:2)+mob_sen(1:2))
    endif
    if(NI_RESERVES())stock(1:2)=max(0._dp,stock(1:2)- &
      max(0._dp,reserve_begin*(1-sen_frac(1:2))-mob_safe(1:2)))
    target=[cmax(1),cmax(2),real(root_target,dp)]
    if(luxury_priority==1) target(1:2)=ccrit
    ! Refill adds protein mass NAD/0.16 as well as N: solve receiver space
    ! with that mass explicitly, independently of new-growth fractions.
    room=max(0._dp,(target*mass-stock)/max(1.e-6_dp,1-target/.16_dp))
    where(mass<=1.e-4_dp) room=0
    total=sum(room);amount=min(max(0._dp,real(available,dp)),total)
    ! Internal growth credit must not be consumed by luxury or same-pool
    ! refill. Cancel its unused reservation before accepting external surplus.
    if(NI_REMOB_ON().and..not.NI_COMMON()) amount=min(max(0._dp,real(available,dp)-sum(mob_plan)),total)
    nad=0
    if(NI_COMMON())then
      room=min(room,joint_repair)
      total=sum(room);amount=min(max(0._dp,real(available,dp)),total)
    endif
    if(total>0) nad=real(amount*room/total)
    if(NI_COMMON())then
      joint_repair_used=real(nad,dp);mob_repair_used=sum(joint_repair_used)
    endif
    unused=max(0.,available-sum(nad))
    refill_n=real(nad,dp)
  end subroutine
  logical function NI_ENABLED()
    NI_ENABLED=ni_stage>0
  end function
  logical function NI_CURVES()
    NI_CURVES=ni_stage>=4
  end function
  logical function NI_SPLIT()
    NI_SPLIT=ni_stage>=2
  end function
  logical function NI_FEEDBACK()
    NI_FEEDBACK=ni_stage>=5.and.ready
  end function
  integer function NI_ROOT_MODE()
    NI_ROOT_MODE=0
    if(ni_stage>=3) NI_ROOT_MODE=root_mode
  end function
  real function NI_TOTAL_Q()
    NI_TOTAL_Q=real(sum(q3)+sum(q4))
  end function
  real function NI_SOIL_INPUT()
    NI_SOIL_INPUT=real(returned_litter)
  end function
  subroutine NI_SET_NH4(value)
    real,intent(in)::value
    legacy_nh4=real(value,dp)
  end subroutine
  subroutine NI_LOAD(control,switch)
    type(ControlType),intent(in)::control
    type(SwitchType),intent(in)::switch
    character(512)::path,message
    integer::ios,unit,status,length,i,k
    integer,parameter::group_len=len('&ROOTNUPTAKE')
    logical::exists
    namelist /NINTEGRATION/ ni_stage,root_mode,q_no3_max,q_nh4_max, &
      assim_no3_v,assim_nh4_v,assim_no3_k,assim_nh4_k, &
      root_v,root_k,diffusion_k,pool_beta,leaf_a,leaf_b,stem_a,stem_b, &
      min_ratio,max_ratio,photo_floor,photo_gamma,growth_tau,budget_revision,curve_w0,photo_slw_ref, &
      state_timing,pods_n_state,remob_mode,remob_severity,remob_tau,protect_beta,slow_ratio,luxury_priority, &
      c4_budget,leaf_coupling,n_sen_rate,c4_photo,leaf_min_ratio,stem_min_ratio,leaf_inf,stem_inf, &
      photo_reference_mode,photo_sln_ref,leaf_expansion_mode,v4_diagnostics,common_acceptance,reserve_mode, &
      reserve_capacity,reserve_fill_tau,reserve_protect,build_min_leaf,build_min_stem, &
      remob_rate_mode,remob_rate_max,functional_rate_max,lai_cn_mode,lai_cn_shape
    namelist /ROOTNUPTAKE/ rnk_mode,rnk_km_high,rnk_km_low,rnk_vmax_high,rnk_vmax_low, &
      rnk_kd,rnk_residual,rnk_radius,rnk_species_diffusion,rnk_radial_cells
    logical :: rnk_present
    if(loaded) then
      if(NI_ENABLED()) then
        if(control%CROP/='TM'.or.switch%ISWNIT/='Y'.or.switch%ISWSYM/='N'.or.switch%ISWDIS/='N') &
          error stop 'NI: mixed or unsupported crop/switch batch'
        if(NI_ROOT_MODE()>0.and.(switch%ISWWAT/='Y'.or.switch%MEEVP=='Z')) &
          error stop 'NI: unsupported water route in later treatment'
        if(ni_stage>=5.and.(switch%MEPHO/='L'.or.switch%MEEVP=='Z')) &
          error stop 'NI: replacement feedback requires the verified non-Z L route'
      end if
      return
    end if
    loaded=.true.
    path='NIntegration.nml'
    call get_environment_variable('DSSAT_N_CONFIG',message,length,status)
    if(status==0.and.length>0) path=trim(message)
    inquire(file=trim(path),exist=exists)
    if(.not.exists) then
      if(status==0.and.length>0) error stop 'NI: explicitly requested configuration is missing'
      return
    end if
    open(newunit=unit,file=trim(path),status='old',action='read',iostat=ios)
    if(ios/=0) error stop 'NI: cannot open configuration'
    read(unit,nml=NINTEGRATION,iostat=ios,iomsg=message)
    close(unit)
    if(ios/=0) then
      write(*,'(A)') trim(message)
      error stop 'NI: invalid namelist'
    end if
    if(ni_stage<0.or.ni_stage>5) error stop 'NI: stage must be 0..5'
    if(ni_stage>implemented_stage) error stop 'NI: requested integration stage is not connected in this build'
    if(lai_cn_mode<0.or.lai_cn_mode>1)error stop 'NI LAI: invalid leaf C/N mode'
    if(.not.ieee_is_finite(lai_cn_shape))error stop 'NI LAI: nonfinite leaf response'
    if(lai_cn_mode==1)then
      if(ni_stage/=5.or.budget_revision/=1.or.c4_budget/=1.or.leaf_coupling/=1.or.c4_photo/=1.or. &
        state_timing/=1.or.pods_n_state/=1.or.remob_mode/=1.or.luxury_priority/=1) &
        error stop 'NI LAI: leaf model requires complete revised C4 routes'
      if(leaf_expansion_mode/=0)error stop 'NI LAI: duplicate expansion policy'
      if(lai_cn_shape<1.or.lai_cn_shape>4)error stop 'NI LAI: explicit response shape in [1,4] required'
    else if(lai_cn_shape/=-1)then
      error stop 'NI LAI: unused leaf response requires lai_cn_mode=1'
    endif
    if(remob_rate_mode<0.or.remob_rate_mode>1)error stop 'NI LAI: invalid remobilization rate mode'
    if(.not.all(ieee_is_finite([remob_rate_max,functional_rate_max])))error stop 'NI LAI: nonfinite rate limits'
    if(remob_rate_mode==1)then
      if(ni_stage/=5.or.budget_revision/=1.or.remob_mode/=1)error stop 'NI LAI: rate limits require revised remobilization'
      if(remob_rate_max<=0.or.remob_rate_max>1.or.functional_rate_max<=0.or. &
        functional_rate_max>remob_rate_max)error stop 'NI LAI: explicit ordered daily rate limits required'
    else if(remob_rate_max/=-1.or.functional_rate_max/=-1)then
      error stop 'NI LAI: unused rate limits require remob_rate_mode=1'
    endif
    if(min(common_acceptance,reserve_mode)<0.or.max(common_acceptance,reserve_mode)>1)error stop 'NI P2: invalid mode'
    if(.not.all(ieee_is_finite([build_min_leaf,build_min_stem])))error stop 'NI P2: nonfinite new-tissue settings'
    if((build_min_leaf/=-1.and.(build_min_leaf<=0.or.build_min_leaf>1)).or. &
      (build_min_stem/=-1.and.(build_min_stem<=0.or.build_min_stem>1)))error stop 'NI P2: new-tissue fraction must be (0,1]'
    if(max(build_min_leaf,build_min_stem)>0.and.common_acceptance/=1.and.lai_cn_mode/=1) &
      error stop 'NI P2: separate new-tissue composition requires common acceptance or LAI C/N mode'
    if(max(common_acceptance,reserve_mode)>0)then
      if(ni_stage/=5.or.budget_revision/=1.or.c4_budget/=1.or.leaf_coupling/=1.or.c4_photo/=1.or. &
        remob_mode/=1.or.luxury_priority/=1)error stop 'NI P2: complete C4/C1-C3 routes required'
      if(leaf_expansion_mode/=0)error stop 'NI P2: common acceptance replaces the P1 expansion ablation'
    endif
    if(reserve_mode==1)then
      if(.not.all(ieee_is_finite([reserve_capacity,reserve_fill_tau,reserve_protect])))error stop 'NI P2: nonfinite reserve settings'
      if(reserve_capacity<=0.or.reserve_capacity>=.16_dp.or.reserve_fill_tau<=0.or. &
        reserve_protect<0.or.reserve_protect>=1)error stop 'NI P2: explicit reserve capacity, rate and protection required'
    endif
    if(min(photo_reference_mode,leaf_expansion_mode,v4_diagnostics)<0.or. &
      max(photo_reference_mode,leaf_expansion_mode,v4_diagnostics)>1)error stop 'NI V4: invalid mode'
    if(.not.all(ieee_is_finite([leaf_min_ratio,stem_min_ratio,leaf_inf,stem_inf,photo_sln_ref]))) &
      error stop 'NI V4: nonfinite configuration'
    if((leaf_min_ratio/=-1.and.(leaf_min_ratio<=0.or.leaf_min_ratio>=1)).or. &
      (stem_min_ratio/=-1.and.(stem_min_ratio<=0.or.stem_min_ratio>=1)))error stop 'NI V4: invalid minimum ratio'
    if(leaf_inf<0.or.stem_inf<0)error stop 'NI V4: negative asymptote'
    if(max(photo_reference_mode,leaf_expansion_mode,v4_diagnostics)>0.or.leaf_min_ratio/=-1.or. &
      stem_min_ratio/=-1.or.max(leaf_inf,stem_inf)>0)then
      if(ni_stage/=5.or.budget_revision/=1.or.c4_photo/=1.or.leaf_coupling/=1) &
        error stop 'NI V4: experiments require complete C4 stage5/A'
    endif
    if(photo_reference_mode==1.and.photo_sln_ref<=0)error stop 'NI V4: explicit area-N reference required'
    if(min(c4_budget,leaf_coupling,c4_photo)<0.or.max(c4_budget,leaf_coupling,c4_photo)>1)error stop 'NI C4: invalid mode'
    if(.not.ieee_is_finite(n_sen_rate).or.n_sen_rate<0.or.n_sen_rate>1)error stop 'NI C4: invalid senescence rate'
    if(c4_budget==1.and.(ni_stage/=5.or.budget_revision/=1.or.state_timing/=1.or.pods_n_state/=1)) &
      error stop 'NI C4: budget mode requires C1 stage5/A'
    if(leaf_coupling==1.and.(c4_budget/=1.or.remob_mode/=1))error stop 'NI C4: leaf coupling requires budget and remob modes'
    if(leaf_coupling==0.and.n_sen_rate/=0)error stop 'NI C4: N senescence requires leaf coupling'
    if(c4_photo==1.and.(ni_stage/=5.or.budget_revision/=1.or.state_timing/=1.or.pods_n_state/=1)) &
      error stop 'NI C4: area-N feedback requires C1 stage5/A'
    if(min(state_timing,pods_n_state,remob_mode,luxury_priority)<0.or. &
       max(state_timing,pods_n_state,remob_mode,luxury_priority)>1) error stop 'NI v3: switches must be 0 or 1'
    if(ni_stage/=5.and.max(state_timing,pods_n_state,remob_mode,luxury_priority)>0) &
      error stop 'NI v3: opt-in modes require stage5; stage0 cannot silently activate them'
    ! --- RootNUptake 公共核配置: &ROOTNUPTAKE 缺席即 mode=0(冻结行为) ---
    inquire(file=trim(path),exist=exists)
    if(exists) then
      open(newunit=unit,file=trim(path),status='old',action='read',iostat=ios)
      if(ios/=0) error stop 'RNK: cannot reopen configuration'
      rnk_present=.false.
      do
        read(unit,'(A)',iostat=ios) message
        if(ios/=0) exit
        do i=1,len_trim(message)
          k=iachar(message(i:i))
          if(k>=iachar('a').and.k<=iachar('z')) message(i:i)=achar(k-32)
        end do
        i=verify(message,' '//achar(9))
        if(i==0.or.i>len(message)-group_len) cycle
        if(message(i:i+group_len-1)=='&ROOTNUPTAKE'.and. &
           scan(message(i+group_len:i+group_len),' /!'//achar(9))/=0) then
          rnk_present=.true.
          exit
        end if
      end do
      if(rnk_present) then
        rewind(unit)
        read(unit,nml=ROOTNUPTAKE,iostat=ios,iomsg=message)
        close(unit)
        if(ios/=0) then
          write(*,'(A)') trim(message)
          error stop 'RNK: invalid ROOTNUPTAKE namelist'
        end if
        if(rnk_mode<0.or.rnk_mode>2) error stop 'RNK: transport mode must be 0(off),1(A),2(B)'
        if(rnk_mode==RNK_MODE_B.and.all(rnk_radial_cells/=[8,16])) &
          error stop 'RNK: radial grid must use 8 or 16 cells'
        if(rnk_mode>=1) then
          if(.not.NI_ENABLED()) error stop 'RNK: common kernel requires enabled NI integration'
          if(NI_ROOT_MODE()<=0) error stop 'RNK: common kernel requires actual-water root mode (root_mode>=1)'
          rnk_par%km_high=rnk_km_high; rnk_par%km_low=rnk_km_low
          rnk_par%vmax_high=rnk_vmax_high; rnk_par%vmax_low=rnk_vmax_low
          rnk_par%kd_sorption=rnk_kd; rnk_par%residual_ppm=rnk_residual
          rnk_par%source_tag(rnk_NO3)='v15-engineering'
          rnk_par%source_tag(rnk_NH4)='literature-prior'
          block
            character(160) :: rnk_msg
            rnk_msg=rnk_validate(rnk_par,NL)
            if(len_trim(rnk_msg)>0) then
              write(*,'(A)') trim(rnk_msg)
              error stop 'RNK: parameter validation failed'
            end if
          end block
          if(.not.all(ieee_is_finite([rnk_radius,rnk_species_diffusion]))) &
            error stop 'RNK: nonfinite transport parameters'
          if(rnk_radius<=0.or.any(rnk_species_diffusion<0)) &
            error stop 'RNK: require positive radius and nonnegative species diffusivities'
          rnk_par%species_diffusion_m2d=rnk_species_diffusion
          rnk_par%root_radius_m=rnk_radius
        end if
      else
        close(unit)
        rnk_mode=0
      end if
    end if
    if(.not.NI_ENABLED()) return
    if(budget_revision<0.or.budget_revision>1) error stop 'NI: budget_revision must be 0 or 1'
    if(min(state_timing,pods_n_state)<0.or.max(state_timing,pods_n_state)>1) &
      error stop 'NI v3: state switches must be 0 or 1'
    if(max(state_timing,pods_n_state)>0.and.(ni_stage/=5.or.budget_revision/=1)) &
      error stop 'NI v3: state changes require stage5 and A budget'
    if(remob_mode<0.or.remob_mode>1.or.remob_severity<0.or.remob_severity>1) &
      error stop 'NI v3: invalid remobilization switch'
    if(NI_REMOB_ON()) then
      if(state_timing/=1.or.pods_n_state/=1) error stop 'NI v3: remobilization requires C1 state modes'
      if(.not.all(ieee_is_finite([remob_tau,protect_beta,slow_ratio]))) error stop 'NI v3: nonfinite remob parameters'
      if(remob_tau<=0.or.slow_ratio<1.or.protect_beta<0.or.protect_beta>1) error stop 'NI v3: invalid remob parameters'
    endif
    if(luxury_priority<0.or.luxury_priority>1) error stop 'NI v3: invalid luxury priority mode'
    if(luxury_priority==1.and.(state_timing/=1.or.pods_n_state/=1)) &
      error stop 'NI v3: luxury priority requires C1 state modes'
    if(.not.ieee_is_finite(curve_w0).or.curve_w0<=0.or..not.ieee_is_finite(photo_slw_ref).or.photo_slw_ref<=0) &
      error stop 'NI: invalid curve breakpoint or functional leaf reference'
    if(.not.all(ieee_is_finite([q_no3_max,q_nh4_max,assim_no3_v,assim_nh4_v,assim_no3_k,assim_nh4_k, &
        root_v,root_k,diffusion_k,pool_beta,leaf_a,leaf_b,stem_a,stem_b,min_ratio,max_ratio, &
        photo_floor,photo_gamma,growth_tau]))) error stop 'NI: non-finite configuration value'
    if(control%CROP/='TM'.or.switch%ISWNIT/='Y'.or.switch%ISWSYM/='N') &
      error stop 'NI: first integration supports nonfixing TM nitrogen simulation only'
    if(switch%ISWDIS/='N') error stop 'NI: inorganic pest export is not implemented; pests must be off'
    if(q_no3_max<=0.or.q_nh4_max<=0.or.q_nh4_max>=q_no3_max) &
      error stop 'NI: explicit positive species capacities are required; NH4 capacity must be smaller'
    if(ni_stage>=2) then
      if(min(assim_no3_v,assim_nh4_v,assim_no3_k,assim_nh4_k)<=0) &
        error stop 'NI: explicit positive specific assimilation capacities and substrate constants required'
    end if
    if(ni_stage>=3) then
      if(root_mode<0.or.root_mode>2) error stop 'NI: invalid root mode'
      if(root_mode>0.and.(switch%ISWWAT/='Y'.or.switch%MEEVP=='Z')) &
        error stop 'NI: root mode requires actual non-Z water simulation'
      if(root_mode>0.and.(min(root_v,root_k)<=0.or.diffusion_k<0.or.pool_beta<0)) &
        error stop 'NI: explicit root kinetics, diffusion, and pool feedback required'
      if(root_mode==2.and.diffusion_k<=0) error stop 'NI: R2 requires positive effective diffusion'
    else if(root_mode/=0) then
      error stop 'NI: root_mode must be 0 before stage 3'
    end if
    if(NI_CURVES()) then
      if(min(leaf_a,leaf_b,stem_a,stem_b,min_ratio)<=0.or.min_ratio>=1.or.max_ratio<=1) &
        error stop 'NI: invalid organ soft-reference curves'
      if(max(leaf_a,stem_a)*max_ratio>=1) error stop 'NI: reference N fraction must remain below one'
      if(leaf_inf>=leaf_a.or.stem_inf>=stem_a)error stop 'NI V4: asymptote must be below unit-biomass coefficient'
    end if
    if(ni_stage>=5) then
      if(switch%MEPHO/='L'.or.switch%MEEVP=='Z') &
        error stop 'NI: new functional feedback currently supports verified non-Z L route only'
      if(photo_floor<0.or.photo_floor>=1.or.photo_gamma<=0.or.growth_tau<=0) &
        error stop 'NI: explicit bounded functional response parameters required'
    end if
  end subroutine
  subroutine NI_RESET()
    if(r_rnk_pending_run/=-1) error stop 'RNK: season reset before reporting pending uptake'
    q3=0; q4=0; carrier=0; w_begin=0; litter3=0; litter4=0
    returned_litter=0; water_ready=.false.; ready=.false.; growth_factor=1
    cmin=0; ccrit=0; cmax=0; d_pending=0
    end_run=-1;end_day=-1;day_run=-1;day_date=-1;day_source=-1
    day_valid=.false.;z_end=0;day_z=0;day_growth=1
    veg_z_end=1;day_veg_z=1;mob_safe=0;mob_func=0;mob_plan=0;mob_returned=0
    sen_frac=0;sen_plan_dm=0;sen_available=0;mob_sen=0;c4_nloss=0;c4_area_dead=0
    mob_rate_cap=0;mob_function_cap=0
    reserve_n=0;reserve_begin=0;reserve_fill=0;reserve_release=0;reserve_sen_recovery=0;reserve_litter=0
    reserve_pending=.false.;reserve_residual=0
    lai_accept_calls=0;lai_area_calls=0;lai_dm_raw=0;lai_dm_request=0;lai_area=0
    r_rnk_branch=0; r_rnk_flag=0; r_rnk_cap=0; r_rnk_mf4=0; r_rnk_bulk4=0; r_rnk_cr4=0; r_rnk_capped=.false.
    r_rnk_stock_before=0; r_rnk_theta0=0; r_rnk_diff=0; r_rnk_accept3=0; r_rnk_accept4=0
    r_rnk_source_day=-1
  end subroutine
  subroutine NI_BEGIN(weights)
    real,intent(in)::weights(3)
    if(.not.NI_ENABLED()) return
    w_begin=max(real(weights,dp),0._dp)
    ! Carrier follows live tissue loss but not internal carbohydrate/protein mining.
    ! It is an explicit storage-support proxy, not an observed dry-mass compartment.
    carrier=max(carrier,w_begin)
    d_q_begin=sum(q3)+sum(q4); d_u3=0; d_u4=0; d_a3=0; d_a4=0
    d_cost=0; d_refund=0; d_litter=0
    old_a3=0;old_a4=0;old_rsp3=0;old_rsp4=0
    r_mf=0;r_diff=0;r_mem=0;r_cr=0;r_bulk=0;r_candidate3=0;r_candidate4=0;r_final3=0;r_final4=0
    mob_safe=0;mob_func=0;mob_plan=0;mob_returned=0;mob_gap=0;mob_accept=0;mob_new_used=0;mob_c_paid=0
    mob_rate_cap=0;mob_function_cap=0
    kinetic_cap=0;late_a=0;late_cost=0;late_c_budget=0;late_func=0;late_lux=0
    late_unit_cost=0;late_c_before=0;late_c_after=0;late_c_reserved=0;late_nad=0
    veg_before=0;veg_after=0;storage_shift=0
    reserve_begin=reserve_n;reserve_fill=0;reserve_release=0;reserve_sen_recovery=0;reserve_litter=0
    reserve_pending=NI_RESERVES();reserve_residual=0
    p2_plan_calls=0;p2_veg_calls=0;mob_repair_used=0
    joint_dm_req=0;joint_dm=0;joint_nn=0;joint_repair=0;joint_repair_used=0;joint_fruit_req=0
    joint_build=0;joint_target=0;joint_agr=0;joint_proi=0;joint_unitcost=0
    joint_carbon=0;joint_nitrogen=0;joint_fruit_cap=0;joint_fruit_used=0;joint_scale=1
    joint_assim_n=0;joint_assim_c=0;joint_assim_unused=0
    lai_accept_calls=0;lai_area_calls=0;lai_dm_raw=0;lai_dm_request=0;lai_area=0
    lai_c_available=0;lai_n_available=0;lai_dm_actual=0;lai_n_actual=0;lai_veg_c=0;lai_veg_n=0
    lai_c_actual=0;lai_build=0;lai_sla=0;lai_min_begin=0;lai_crit_begin=0
    if(max(common_acceptance,reserve_mode)>0)then
      donor_n=0;donor_c=0
    endif
    sen_frac=0;sen_plan_dm=0;sen_available=0;mob_sen=0;c4_nloss=0;c4_area_dead=0
  end subroutine
  subroutine NI_ORG_BEGIN(stocks,off,seed,leak)
    real,intent(in)::stocks(6),off(6),seed,leak
    org_start=real(stocks(1:3),dp)
    org_begin=sum(real(stocks,dp))+real(seed,dp)
    org_off_begin=sum(real(off,dp));leak_begin=real(leak,dp)
  end subroutine
  subroutine NI_ORG_END(stocks,off,seed,leak,c_overrun)
    real,intent(in)::stocks(6),off(6),seed,leak,c_overrun
    legacy_n_res=sum(real(stocks,dp))+real(seed,dp)-org_begin+sum(real(off,dp))-org_off_begin &
      +real(leak,dp)-leak_begin-d_a3-d_a4
    legacy_c_overrun=real(c_overrun,dp)
    org_end_stock=sum(real(stocks,dp))+real(seed,dp)
    org_end_off=sum(real(off,dp));seed_end=real(seed,dp);leak_end=real(leak,dp)
    if(NI_REVISED()) then
      if(abs(legacy_n_res)>1.e-5_dp+2.e-6_dp*max(org_begin,sum(real(stocks,dp)))) &
        error stop 'NI A: committed organic nitrogen budget failure'
      if(legacy_c_overrun>2.e-5_dp) error stop 'NI A: vegetative carbon overrun'
    end if
  end subroutine
  real function flux32(value)
    real(dp),intent(in)::value
    flux32=real(max(0._dp,value))
    if(real(flux32,dp)>value.and.flux32>0) flux32=ieee_next_after(flux32,0.)
  end function
  subroutine spread(pool,amount,capacity)
    real(dp),intent(inout)::pool(3)
    real(dp),intent(in)::amount,capacity(3)
    real(dp)::room(3),total
    room=max(0._dp,capacity-pool); total=sum(room)
    if(amount>total+1.e-10_dp) error stop 'NI: uptake exceeded actual receiver capacity'
    if(total>0) pool=pool+amount*room/total
  end subroutine
  subroutine remove(pool,amount)
    real(dp),intent(inout)::pool(3)
    real(dp),intent(in)::amount
    real(dp)::total
    total=sum(pool)
    if(amount>total+1.e-10_dp) error stop 'NI: assimilation exceeds substrate'
    if(total>0) pool=pool*max(0._dp,1._dp-amount/total)
  end subroutine
  subroutine NI_ACCEPT_UPTAKE(uno3,unh4,nlayr,tr3,tr4,trnu)
    integer,intent(in)::nlayr
    real,intent(inout)::uno3(:),unh4(:)
    real,intent(out)::tr3,tr4,trnu
    real(dp)::p3,p4,h3,h4,scale
    integer::l
    p3=sum(real(uno3(1:nlayr),dp))/10; p4=sum(real(unh4(1:nlayr),dp))/10
    if(minval(uno3(1:nlayr))<0.or.minval(unh4(1:nlayr))<0) error stop 'NI: negative gross uptake candidate'
    h3=max(0._dp,q_no3_max*sum(carrier)-sum(q3))
    h4=max(0._dp,q_nh4_max*sum(carrier)-sum(q4))
    if(p3>0) then
      scale=min(1._dp,h3/p3)
      do l=1,nlayr
        uno3(l)=flux32(real(uno3(l),dp)*scale)
      end do
    end if
    if(p4>0) then
      scale=min(1._dp,h4/p4)
      do l=1,nlayr
        unh4(l)=flux32(real(unh4(l),dp)*scale)
      end do
    end if
    d_u3=sum(real(uno3(1:nlayr),dp))/10
    d_u4=sum(real(unh4(1:nlayr),dp))/10
    if(rnk_mode>=RNK_MODE_A) then
      ! 账本: 接受链缩放后的逐层接受量 (g N m^-2), 供 LayerRootNUptake.csv
      r_rnk_accept3(1:nlayr)=real(uno3(1:nlayr),dp)/10
      r_rnk_accept4(1:nlayr)=real(unh4(1:nlayr),dp)/10
    end if
    call spread(q3,d_u3,q_no3_max*carrier)
    call spread(q4,d_u4,q_nh4_max*carrier)
    tr3=real(d_u3); tr4=real(d_u4); trnu=tr3+tr4
    d_pending=d_u3+d_u4
  end subroutine
  subroutine NI_ASSIM_KERNEL(qno3,qnh4,wref,v3,v4,k3,k4,temperature,carbon,accept,cost3,cost4,a3,a4)
    real(dp),intent(in)::qno3,qnh4,wref,v3,v4,k3,k4,temperature,carbon,accept,cost3,cost4
    real(dp),intent(out)::a3,a4
    real(dp)::c3,c4,factor,cost
    c3=qno3/max(wref,1.e-12_dp); c4=qnh4/max(wref,1.e-12_dp)
    a3=min(qno3,v3*wref*temperature*c3/(k3+c3))
    a4=min(qnh4,v4*wref*temperature*c4/(k4+c4))
    factor=min(1._dp,max(0._dp,accept)/max(a3+a4,1.e-30_dp))
    a3=a3*factor; a4=a4*factor
    cost=a3*cost3+a4*cost4
    factor=min(1._dp,max(0._dp,carbon)/max(cost,1.e-30_dp))
    a3=a3*factor; a4=a4*factor
  end subroutine
  subroutine NI_ASSIMILATE(pg,accept,temperature,rno3,rnh4,nassim,rsp3,rsp4,time_fraction)
    real,intent(inout)::pg
    real,intent(in)::accept,temperature,rno3,rnh4
    real,intent(out)::nassim,rsp3,rsp4
    real,intent(in),optional::time_fraction
    real(dp)::a3,a4,cost3,cost4,factor,capacity,wref,dt,pot3,pot4
    cost3=real(rno3,dp)/.16_dp; cost4=real(rnh4,dp)/.16_dp
    capacity=max(0._dp,real(accept,dp)); wref=sum(carrier)
    dt=1
    if(present(time_fraction)) dt=real(time_fraction,dp)
    if(luxury_priority==1) then
      late_unit_cost=[cost3,cost4]
      call NI_ASSIM_KERNEL(sum(q3),sum(q4),wref,assim_no3_v*dt,assim_nh4_v*dt,assim_no3_k,assim_nh4_k, &
        max(0._dp,min(1._dp,real(temperature,dp))),1.e30_dp,1.e30_dp,cost3,cost4,pot3,pot4)
      kinetic_cap=kinetic_cap+[pot3,pot4]
    endif
    if(ni_stage==1) then
      a3=sum(q3); a4=sum(q4)
      factor=min(1._dp,capacity/max(a3+a4,1.e-30_dp)); a3=a3*factor; a4=a4*factor
      factor=min(1._dp,max(0._dp,real(pg,dp))/max(a3*cost3+a4*cost4,1.e-30_dp))
      a3=a3*factor; a4=a4*factor
    else
      call NI_ASSIM_KERNEL(sum(q3),sum(q4),wref,assim_no3_v*dt,assim_nh4_v*dt,assim_no3_k,assim_nh4_k, &
          max(0._dp,min(1._dp,real(temperature,dp))),real(pg,dp),capacity,cost3,cost4,a3,a4)
    end if
    ! Predicted demand is only a candidate bound. Actual host acceptance is
    ! settled after allocation, without replaying stateful SAVE routines.
    d_a3=real(flux32(a3),dp); d_a4=real(flux32(a4),dp)
    nassim=flux32(d_a3+d_a4)
    factor=real(nassim,dp)/max(d_a3+d_a4,1.e-30_dp)
    d_a3=d_a3*factor; d_a4=d_a4*factor
    call remove(q3,d_a3); call remove(q4,d_a4)
    rsp3=real(d_a3*cost3); rsp4=real(d_a4*cost4)
    d_cost=real(rsp3,dp)+real(rsp4,dp)
    if(d_cost>real(pg,dp)+1.e-6_dp) error stop 'NI: shared carbon budget exceeded'
    pg=max(0.,pg-rsp3-rsp4)
  end subroutine
  subroutine NI_PREASSIM(pg,accept,temperature,rno3,rnh4,n_old)
    real,intent(inout)::pg
    real,intent(in)::accept,temperature,rno3,rnh4
    real,intent(out)::n_old
    real::rsp3,rsp4
    call NI_ASSIMILATE(pg,accept,temperature,rno3,rnh4,n_old,rsp3,rsp4,.5)
    old_a3=d_a3;old_a4=d_a4;old_rsp3=real(rsp3,dp);old_rsp4=real(rsp4,dp)
    d_a3=0;d_a4=0;d_cost=0
  end subroutine
  subroutine NI_MERGE_OLD(nassim,rsp3,rsp4)
    real,intent(out)::nassim
    real,intent(inout)::rsp3,rsp4
    d_a3=d_a3+old_a3;d_a4=d_a4+old_a4
    rsp3=rsp3+real(old_rsp3);rsp4=rsp4+real(old_rsp4)
    d_cost=real(rsp3,dp)+real(rsp4,dp);nassim=real(d_a3+d_a4)
  end subroutine
  subroutine NI_SETTLE(unaccepted,rsp3,rsp4,nassim,refund_c,uno3,unh4,nlayr,tr3,tr4,trnu)
    real,intent(in)::unaccepted
    real,intent(inout)::rsp3,rsp4,nassim
    real,intent(out)::refund_c
    integer,intent(in)::nlayr
    real,intent(inout)::uno3(:),unh4(:),tr3,tr4,trnu
    real(dp)::fraction,ret3,ret4,cost_old,excess,scale,new_u,total
    integer::l
    fraction=min(1._dp,max(0._dp,real(unaccepted,dp))/max(d_a3+d_a4,1.e-30_dp))
    if(unaccepted>=real(d_a3+d_a4)) fraction=1
    ret3=d_a3*fraction; ret4=d_a4*fraction
    ! Return provisional, unassimilated substrate; no organic stock was committed.
    ! Old-stock conversion can free provisional room. If allocation rejects it,
    ! roll back the STILL UNPUBLISHED layer uptake, not soil already debited.
    excess=max(0._dp,sum(q3)+ret3-q_no3_max*sum(carrier))
    if(excess>d_u3+1.e-10_dp) error stop 'NI: NO3 receiver cannot reconcile candidate uptake'
    if(d_u3>0.and.excess>0) then
      scale=max(0._dp,1-excess/d_u3)
      do l=1,nlayr
        uno3(l)=flux32(real(uno3(l),dp)*scale)
      end do
    end if
    new_u=sum(real(uno3(1:nlayr),dp))/10
    total=sum(q3)+ret3-(d_u3-new_u)
    q3=max(0._dp,total)*carrier/max(sum(carrier),1.e-30_dp); d_u3=new_u
    excess=max(0._dp,sum(q4)+ret4-q_nh4_max*sum(carrier))
    if(excess>d_u4+1.e-10_dp) error stop 'NI: NH4 receiver cannot reconcile candidate uptake'
    if(d_u4>0.and.excess>0) then
      scale=max(0._dp,1-excess/d_u4)
      do l=1,nlayr
        unh4(l)=flux32(real(unh4(l),dp)*scale)
      end do
    end if
    new_u=sum(real(unh4(1:nlayr),dp))/10
    total=sum(q4)+ret4-(d_u4-new_u)
    q4=max(0._dp,total)*carrier/max(sum(carrier),1.e-30_dp);d_u4=new_u
    tr3=real(d_u3);tr4=real(d_u4);trnu=tr3+tr4;d_pending=d_u3+d_u4
    r_final3(1:nlayr)=real(uno3(1:nlayr),dp)/10
    r_final4(1:nlayr)=real(unh4(1:nlayr),dp)/10
    d_a3=d_a3-ret3; d_a4=d_a4-ret4
    cost_old=real(rsp3,dp)+real(rsp4,dp)
    rsp3=real(real(rsp3,dp)*(1-fraction)); rsp4=real(real(rsp4,dp)*(1-fraction))
    d_cost=real(rsp3,dp)+real(rsp4,dp)
    d_refund=cost_old-d_cost; refund_c=real(d_refund); nassim=real(d_a3+d_a4)
  end subroutine
  subroutine NI_END(control,weights,losses,root_weights,nlayr,org_n,lai,wcrlf)
    type(ControlType),intent(in)::control
    integer,intent(in)::nlayr
    real,intent(in)::weights(3),losses(3),root_weights(:),org_n(3),lai,wcrlf
    real(dp)::fraction(3),out3(3),out4(3),growth(3),denom,alpha,target,nraw,nniraw(2),nnifun(2),deficit(2),surplus(2)
    real(dp)::functional_n(2)
    integer::l,s,ios
    if(.not.NI_ENABLED()) return
    if(reserve_pending)error stop 'NI P2: reserve stock was not committed'
    growth=max(0._dp,real(weights,dp)+max(0._dp,real(losses,dp))-w_begin)
    fraction=min(1._dp,max(0._dp,real(losses,dp))/max(w_begin+growth,1.e-12_dp))
    if(NI_LEAF_COUPLED())fraction=sen_frac
    out3=q3*fraction; out4=q4*fraction
    q3=q3-out3; q4=q4-out4
    carrier=max(real(weights,dp),carrier*(1-fraction))
    litter3(1)=litter3(1)+sum(out3(1:2)); litter4(1)=litter4(1)+sum(out4(1:2))
    denom=sum(max(0._dp,real(root_weights(1:nlayr),dp)))
    do l=1,nlayr
      alpha=0
      if(denom>0) alpha=max(0._dp,real(root_weights(l),dp))/denom
      if(denom==0.and.l==1) alpha=1
      litter3(l)=litter3(l)+out3(3)*alpha; litter4(l)=litter4(l)+out4(3)*alpha
    end do
    d_litter=sum(out3)+sum(out4)
    d_residual=sum(q3)+sum(q4)-d_q_begin-d_u3-d_u4+d_a3+d_a4+d_litter
    if(abs(d_residual)>1.e-9_dp.or.minval(q3)<-1.e-12_dp.or.minval(q4)<-1.e-12_dp) &
      error stop 'NI: incremental inorganic N conservation failure'
    if(any(q3>q_no3_max*carrier+1.e-9_dp).or.any(q4>q_nh4_max*carrier+1.e-9_dp)) &
      error stop 'NI: storage capacity exceeded'
    if(NI_CURVES()) then
      call references(real(weights,dp))
      functional_n=real(org_n(1:2),dp)
      if(NI_RESERVES())functional_n=functional_n-reserve_n
      z_end=(functional_n/max(real(weights(1:2),dp),1.e-12_dp)-cmin)/(ccrit-cmin)
      veg_z_end=(sum(functional_n)-sum(real(weights(1:2),dp)*cmin))/ &
        max(sum(real(weights(1:2),dp)*(ccrit-cmin)),1.e-12_dp)
      nraw=(functional_n(1)/max(real(weights(1),dp),1.e-12_dp)-cmin(1))/(ccrit(1)-cmin(1))
      target=min(1._dp,max(0._dp,nraw))
      if(.not.ready) then
        growth_factor=target
      else if(ni_stage>=5) then
        alpha=1-exp(-1/growth_tau); growth_factor=growth_factor+alpha*(target-growth_factor)
      end if
      structural_fraction=max(0._dp,real(weights(1)-wcrlf,dp))/max(real(weights(1),dp),1.e-12_dp)
    end if
    ready=.true.
    if(NI_LEAF_COUPLED())then
      if(.not.leaf_opened)then
        open(newunit=leaf_unit,file='PlantNLeaf.csv',status='new',action='write',iostat=ios)
        if(ios/=0)error stop 'NI C4: cannot create leaf fate ledger'
        write(leaf_unit,'(A)')'run,yrdoy,sen_DM_leaf_planned,sen_DM_stem_planned,cell_loss_leaf,cell_loss_stem,cell_loss_root,'// &
          'sen_available_leaf,sen_available_stem,sen_N_leaf,sen_N_stem,sen_N_root,sen_N_shell,'// &
          'litter_N_leaf,litter_N_stem,litter_N_root,old_area_lost,n_sen_rate'
        leaf_opened=.true.
      endif
      write(leaf_unit,'(2(I0,","),15(ES24.15E3,","),ES24.15E3)')control%RUN,control%YRDOY,sen_plan_dm,sen_frac, &
        sen_available(1:2),mob_sen,c4_nloss,c4_area_dead,n_sen_rate
    endif
    if(max(state_timing,pods_n_state)>0) then
      if(.not.v3_opened) then
        open(newunit=v3_unit,file='PlantNV3.csv',status='new',action='write',iostat=ios)
        if(ios/=0) error stop 'NI v3: cannot create day-state ledger'
        write(v3_unit,'(A)')'run,yrdoy,state_timing,pods_n_state,source_yrdoy,valid,'// &
          'growth_day,z_leaf_day,z_stem_day,pod_n_factor,growth_end,z_leaf_end,z_stem_end'
        v3_opened=.true.
      end if
      write(v3_unit,'(6(I0,","),6(ES24.15E3,","),ES24.15E3)')control%RUN,control%YRDOY, &
        state_timing,pods_n_state,day_source,merge(1,0,day_valid),day_growth,day_z, &
        NI_POD_KERNEL(day_z(1)),growth_factor,z_end
    end if
    end_run=control%RUN;end_day=control%YRDOY
    if(max(common_acceptance,reserve_mode)>0)call write_p2(control,org_n)
    if(NI_REVISED())call write_lai(control,lai)
    if(v4_diagnostics==1)then
      if(.not.v4_opened)then
        open(newunit=v4_unit,file='PlantNV4.csv',status='new',action='write',iostat=ios)
        if(ios/=0)error stop 'NI V4: cannot create mechanism ledger'
        write(v4_unit,'(A)')'run,yrdoy,photo_reference_mode,leaf_expansion_mode,leaf_min_ratio,stem_min_ratio,'// &
          'leaf_inf,stem_inf,photo_sln_ref,leaf_gate,veg_before_leaf,veg_before_stem,veg_before_root,'// &
          'veg_after_leaf,veg_after_stem,veg_after_root,storage_shift_leaf_to_stem'
        v4_opened=.true.
      endif
      write(v4_unit,'(4(I0,","),12(ES24.15E3,","),ES24.15E3)') control%RUN,control%YRDOY, &
        photo_reference_mode,leaf_expansion_mode,merge(leaf_min_ratio,min_ratio,leaf_min_ratio>0), &
        merge(stem_min_ratio,min_ratio,stem_min_ratio>0),leaf_inf,stem_inf,photo_sln_ref,leaf_gate, &
        veg_before,veg_after,storage_shift
    endif
    if(luxury_priority==1) then
      if(.not.lux_opened)then
        open(newunit=lux_unit,file='PlantNLuxury.csv',status='new',action='write',iostat=ios)
        if(ios/=0)error stop 'NI v3: cannot create priority ledger'
        write(lux_unit,'(A)')'run,yrdoy,luxury_priority,cap_no3,cap_nh4,core_no3,core_nh4,late_no3,late_nh4,'// &
          'C_available,C_late,C_storage_before,C_storage_after,C_reserved,A_function_late,A_luxury,'// &
          'NAD_late_leaf,NAD_late_stem,cost_no3,cost_nh4'
        lux_opened=.true.
      endif
      write(lux_unit,'(3(I0,","),16(ES24.15E3,","),ES24.15E3)') control%RUN,control%YRDOY, &
        luxury_priority,kinetic_cap,[d_a3,d_a4]-late_a,late_a,late_c_budget,late_cost,late_c_before,late_c_after, &
        late_c_reserved,late_func,late_lux,late_nad,late_unit_cost
    endif
    if(NI_REMOB_ON()) then
      if(.not.mob_opened) then
        open(newunit=mob_unit,file='PlantNRemob.csv',status='new',action='write',iostat=ios)
        if(ios/=0) error stop 'NI v3: cannot create remobilization ledger'
        write(mob_unit,'(A)')'run,yrdoy,remob_mode,tau,protect_beta,slow_ratio,severity,veg_z_day,growth_severity_day,'// &
          'gap,acceptance_prediction,new_growth_N_actual,C_remob_actual,'// &
          'plan_leaf,plan_stem,plan_root,plan_shell,returned_leaf,returned_stem,returned_root,returned_shell,'// &
          'safe_leaf,safe_stem,safe_root,safe_shell,function_leaf,function_stem,function_root,function_shell,'// &
          'rate_mode,rate_max,functional_rate_max,capR_leaf,capR_stem,capR_root,capR_shell,'// &
          'capF_leaf,capF_stem,capF_root,capF_shell'
        mob_opened=.true.
      endif
      write(mob_unit,'(3(I0,","),*(ES24.15E3,:,","))') control%RUN,control%YRDOY, &
        remob_mode,remob_tau,protect_beta,slow_ratio,real(remob_severity,dp),day_veg_z,day_growth,mob_gap,mob_accept,mob_new_used, &
        mob_c_paid,mob_plan,mob_returned,mob_safe,mob_func,real(remob_rate_mode,dp), &
        remob_rate_max,functional_rate_max,mob_rate_cap,mob_function_cap
    endif
    if(NI_REVISED()) then
      if(.not.audit_opened) then
        open(newunit=audit_unit,file='PlantABudget.csv',status='new',action='write',iostat=ios)
        if(ios/=0) error stop 'NI A: cannot create actual acceptance ledger'
        write(audit_unit,'(A)') 'run,yrdoy,budget_revision,curve_w0,photo_slw_ref,'// &
          'organic_begin_including_seed,organic_end_including_seed,cumulative_loss_begin,cumulative_loss_end,'// &
          'leak_begin,leak_end,A_committed,organic_residual,veg_C_available,veg_C_actual,leaf_expansion_factor,'// &
          'refill_leaf,refill_stem,refill_root,mobilized_leaf,mobilized_stem,mobilized_root'
        audit_opened=.true.
      end if
      write(audit_unit,'(I0,2(",",I0),19(",",ES24.15E3))') control%RUN,control%YRDOY,budget_revision, &
        curve_w0,photo_slw_ref,org_begin,org_end_stock,org_off_begin,org_end_off,leak_begin,leak_end, &
        d_a3+d_a4,legacy_n_res,veg_available,veg_cost,leaf_gate,refill_n,donor_n
    end if
    nniraw=0;nnifun=0;deficit=0;surplus=0
    if(NI_CURVES()) then
      nniraw=real(org_n(1:2),dp)/max(real(weights(1:2),dp)*ccrit,1.e-12_dp)
      nnifun=(real(org_n(1:2),dp)/max(real(weights(1:2),dp),1.e-12_dp)-cmin)/(ccrit-cmin)
      if(NI_RESERVES())nnifun=(functional_n/max(real(weights(1:2),dp),1.e-12_dp)-cmin)/(ccrit-cmin)
      deficit=max(0._dp,ccrit*real(weights(1:2),dp)-real(org_n(1:2),dp))
      surplus=max(0._dp,real(org_n(1:2),dp)-ccrit*real(weights(1:2),dp))
    end if
    if(.not.opened) then
      open(newunit=output_unit,file='PlantNIntegration.csv',status='new',action='write',iostat=ios)
      if(ios/=0) error stop 'NI: output exists or cannot be created'
      write(output_unit,'(A)') 'run,yrdoy,stage,QNO3,QNH4,U_NO3,U_NH4,A_NO3,A_NH4,C_assim,C_refund,'// &
        'inorg_litter,pending_litter,Q_residual,carrier_leaf,carrier_stem,carrier_root,'// &
        'leaf_min,leaf_crit,leaf_max,stem_min,stem_crit,stem_max,growth_factor,pending_uptake,soil_litter_returned_kg_ha,'// &
        'legacy_organic_N_residual,legacy_growth_C_overrun,QNO3_leaf,QNO3_stem,QNO3_root,QNH4_leaf,QNH4_stem,QNH4_root,'// &
        'Norg_leaf,Norg_stem,Norg_root,Corg_leaf,Corg_stem,Corg_root,Ctotal_leaf,Ctotal_stem,Ctotal_root,'// &
        'W_leaf,W_stem,W_root,functional_leaf_N_per_area,NNI_raw_leaf,NNI_raw_stem,NNI_functional_leaf,NNI_functional_stem,'// &
        'Ndeficit_leaf,Ndeficit_stem,Nsurplus_leaf,Nsurplus_stem'
      opened=.true.
    end if
    write(output_unit,'(I0,2(",",I0),52(",",ES24.15E3))') control%RUN,control%YRDOY,ni_stage, &
      sum(q3),sum(q4),d_u3,d_u4,d_a3,d_a4,d_cost,d_refund,d_litter,sum(litter3)+sum(litter4), &
      d_residual,carrier,cmin(1),ccrit(1),cmax(1),cmin(2),ccrit(2),cmax(2),growth_factor,d_pending,returned_litter, &
      legacy_n_res,legacy_c_overrun,q3,q4,real(org_n,dp), &
      real(org_n,dp)/max(real(weights,dp),1.e-12_dp), &
      (real(org_n,dp)+q3+q4)/max(real(weights,dp),1.e-12_dp),real(weights,dp), &
      max(0._dp,real(org_n(1),dp)-reserve_n(1)-cmin(1)*real(weights(1),dp))/max(real(lai,dp),1.e-12_dp), &
      nniraw,nnifun,deficit,surplus
    if(NI_ROOT_MODE()>0) then
      if(.not.root_opened) then
        open(newunit=root_output_unit,file='LayerNIntegration.csv',status='new',action='write',iostat=ios)
        if(ios/=0) error stop 'NI: layer diagnostic already exists or cannot be opened'
        write(root_output_unit,'(A)') 'run,yrdoy,layer,theta_transport,RWU_cm,'// &
          'Cbulk_mgN_L,Cr_potential_mgN_L,MF_candidate_gN_m2,Diff_potential_gN_m2,'// &
          'membrane_potential_gN_m2,NO3_candidate_gN_m2,NH4_candidate_gN_m2,NO3_final_gN_m2,NH4_final_gN_m2'
        root_opened=.true.
      end if
      do l=1,nlayr
        write(root_output_unit,'(I0,2(",",I0),11(",",ES24.15E3))') control%RUN,control%YRDOY,l, &
          theta_snapshot(l),rwu_snapshot(l),r_bulk(l),r_cr(l),r_mf(l),r_diff(l),r_mem(l), &
          r_candidate3(l),r_candidate4(l),r_final3(l),r_final4(l)
      end do
    end if
    if(NI_COMMON_ROOT_ENABLED() .and. r_rnk_source_day==control%YRDOY) then
      if(r_rnk_pending_run/=-1) error stop 'RNK: previous uptake was not reported by soil'
      r_rnk_pending_run=control%RUN
      r_rnk_pending_nlayr=nlayr
    end if
  end subroutine

  logical function NI_COMMON_ROOT_ENABLED()
    NI_COMMON_ROOT_ENABLED=rnk_mode>=RNK_MODE_A
  end function

  subroutine NI_ROOT_SOIL_DEBIT(control,nlayr,uno3,unh4)
    type(ControlType),intent(in)::control
    integer,intent(in)::nlayr
    real,intent(in)::uno3(:),unh4(:)
    real(dp)::deducted(2,nlayr)
    if(.not.NI_COMMON_ROOT_ENABLED()) return
    if(r_rnk_pending_run==-1) then
      if(any(uno3(1:nlayr)/=0.) .or. any(unh4(1:nlayr)/=0.)) &
        error stop 'RNK: soil debit without pending plant uptake'
      return
    end if
    if(control%RUN/=r_rnk_pending_run.or.nlayr/=r_rnk_pending_nlayr.or.control%YRDOY<=r_rnk_source_day) &
      error stop 'RNK: soil debit does not follow the pending plant uptake'
    deducted(rnk_NO3,:)=real(uno3(1:nlayr),dp)/10
    deducted(rnk_NH4,:)=real(unh4(1:nlayr),dp)/10
    if(any(deducted(rnk_NO3,:)/=r_final3(1:nlayr)).or.any(deducted(rnk_NH4,:)/=r_final4(1:nlayr))) &
      error stop 'RNK: soil debit differs from the settled plant uptake'
    call NI_WRITE_ROOT_LEDGER(nlayr,control%YRDOY,deducted)
  end subroutine

  subroutine NI_ROOT_SOIL_END(control,nlayr)
    type(ControlType),intent(in)::control
    integer,intent(in)::nlayr
    real(dp)::deducted(2,nlayr)
    if(.not.NI_COMMON_ROOT_ENABLED().or.r_rnk_pending_run==-1) return
    if(control%RUN/=r_rnk_pending_run.or.nlayr/=r_rnk_pending_nlayr.or.control%YRDOY<r_rnk_source_day) &
      error stop 'RNK: season end does not match the pending plant uptake'
    ! Preserve the native season boundary. Report the pending flux without a soil mutation.
    deducted=0
    call NI_WRITE_ROOT_LEDGER(nlayr,0,deducted)
  end subroutine

  subroutine NI_WRITE_ROOT_LEDGER(nlayr,commit_day,deducted)
    integer,intent(in)::nlayr,commit_day
    real(dp),intent(in)::deducted(2,nlayr)
    integer::l,s,ios
    real(dp)::settled
    character(len=18)::soil_status
    type(rnk_diag)::diagnostic
    if(.not.rnk_ledger_opened) then
      open(newunit=rnk_ledger_unit,file='LayerRootNUptake.csv',status='new',action='write',iostat=ios)
      if(ios/=0) error stop 'RNK: layer ledger already exists or cannot be opened'
      write(rnk_ledger_unit,'(A)') 'run,yrdoy,layer,species,source_day,soil_commit_day,'// &
        'theta0,theta_mid,rwu_cm_d,rlv_cm_cm3,stock_before_gN_m2,c_bulk_mgN_L,c_root_mgN_L,'// &
        'mf_potential_gN_m2,diffusive_gN_m2,candidate_gN_m2,accepted_gN_m2,deducted_gN_m2,stock_cap_gN_m2,'// &
        'settled_gN_m2,pending_gN_m2,radial_advective_gN_m2,radial_mass_error_gN_m2,solver_status,soil_status,'// &
        'transport_mode,shared_transport,d_bulk_m2_d,zero_diffusion,steady_residual_gN_m2,'// &
        'c_bulk_end_mgN_L,c_root_mean_mgN_L,c_bulk_mean_mgN_L,hats_candidate_gN_m2,lats_candidate_gN_m2'
      rnk_ledger_opened=.true.
    end if
    soil_status=merge('committed         ','pending_season_end',commit_day/=0)
    do l=1,nlayr
      do s=1,2
        settled=rnk_fin(s,l)
        diagnostic=r_rnk_transport(s,l)
        write(rnk_ledger_unit,'(I0,5(",",I0),17(",",ES24.15E3),",",I0,",",A,2(",",I0),",",ES24.15E3, &
             & ",",I0,6(",",ES24.15E3))') &
          r_rnk_pending_run,r_rnk_source_day,l,s,r_rnk_source_day,commit_day, &
          r_rnk_theta0(l),theta_snapshot(l),rwu_snapshot(l),rlv_snapshot(l), &
          r_rnk_stock_before(s,l),rnk_cb(s,l),rnk_cr(s,l),rnk_mf(s,l), &
          r_rnk_diff(s,l),rnk_cand(s,l),rnk_acc(s,l),deducted(s,l),r_rnk_cap(s,l), &
          settled,settled-deducted(s,l),r_rnk_adv(s,l),r_rnk_mass_error(s,l),rnk_status(s,l),trim(soil_status), &
          rnk_mode,1,diagnostic%bulk_diffusion,merge(1,0,diagnostic%zero_diffusion), &
          diagnostic%steady_residual,diagnostic%c_bulk_end,diagnostic%c_root_mean,diagnostic%c_bulk_mean, &
          diagnostic%hats_candidate,diagnostic%lats_candidate
      end do
    end do
    flush(rnk_ledger_unit)
    r_rnk_pending_run=-1
    r_rnk_pending_nlayr=0
  end subroutine

  subroutine NI_RETURN_LITTER(sno3,snh4,nlayr)
    integer,intent(in)::nlayr
    real,intent(inout)::sno3(:),snh4(:)
    if(.not.NI_ENABLED()) return
    sno3(1:nlayr)=sno3(1:nlayr)+real(10*litter3(1:nlayr))
    snh4(1:nlayr)=snh4(1:nlayr)+real(10*litter4(1:nlayr))
    returned_litter=returned_litter+10*(sum(litter3)+sum(litter4))
    litter3=0; litter4=0
  end subroutine
  subroutine NI_CAPTURE_WATER(control,nlayr,rwu,theta,rlv,depth)
    type(ControlType),intent(in)::control
    integer,intent(in)::nlayr
    real,intent(in)::rwu(:),theta(:),rlv(:)
    real,intent(in),optional::depth(:)
    if(.not.NI_ENABLED()) return
    water_day=control%YRDOY; water_run=control%RUN; water_nlayr=nlayr; water_ready=.true.
    rwu_snapshot(1:nlayr)=real(rwu(1:nlayr),dp)
    theta_snapshot(1:nlayr)=real(theta(1:nlayr),dp)
    rlv_snapshot(1:nlayr)=real(rlv(1:nlayr),dp)
    if(NI_COMMON_ROOT_ENABLED()) then
      if(.not.present(depth)) error stop 'RNK: pre-extraction water snapshot requires layer depths'
      if(any(.not.ieee_is_finite(theta(1:nlayr))).or.any(.not.ieee_is_finite(rwu(1:nlayr))).or. &
         any(.not.ieee_is_finite(depth(1:nlayr))).or.any(.not.ieee_is_finite(rlv(1:nlayr)))) &
        error stop 'RNK: non-finite root water snapshot'
      if(any(depth(1:nlayr)<=0.).or.any(theta(1:nlayr)<0.).or.any(rwu(1:nlayr)<0.)) &
        error stop 'RNK: invalid root water snapshot'
      theta0_snapshot(1:nlayr)=real(theta(1:nlayr),dp)
      theta_snapshot(1:nlayr)=theta0_snapshot(1:nlayr)-0.5_dp*rwu_snapshot(1:nlayr)/real(depth(1:nlayr),dp)
    end if
  end subroutine
  subroutine NI_ROOT_KERNEL(cbulk,water,rootlength,vmax,km,kd,poolfactor,mode,uptake,cr)
    real(dp),intent(in)::cbulk,water,rootlength,vmax,km,kd,poolfactor
    integer,intent(in)::mode
    real(dp),intent(out)::uptake,cr
    real(dp)::mf,capacity,lo,hi,mid,mem,supply
    integer::i
    uptake=0; cr=0
    if(cbulk<=0.or.rootlength<=0.or.vmax<=0.or.poolfactor<=0) return
    mf=.01_dp*max(0._dp,water)*cbulk
    capacity=rootlength*vmax*poolfactor
    mem=capacity*cbulk/(km+cbulk)
    if(mode==1) then
      uptake=min(mf,mem); cr=cbulk; return
    end if
    if(mem<=mf) then
      uptake=mem; cr=cbulk; return
    end if
    lo=0; hi=cbulk
    do i=1,64
      mid=(lo+hi)/2
      mem=capacity*mid/(km+mid)
      supply=mf+.001_dp*kd*rootlength*(cbulk-mid)
      if(mem>supply) then
        hi=mid
      else
        lo=mid
      end if
    end do
    cr=(lo+hi)/2; uptake=capacity*cr/(km+cr)
  end subroutine
  subroutine NI_ROOT_UPTAKE(control,nlayr,bd,depth,ll,dul,sat,no3,nh4,kg2ppm,uno3,unh4)
    type(ControlType),intent(in)::control
    integer,intent(in)::nlayr
    real,intent(in)::bd(:),depth(:),ll(:),dul(:),sat(:),no3(:),nh4(:),kg2ppm(:)
    real,intent(out)::uno3(:),unh4(:)
    real(dp)::theta,wet,length,concentration,potential,cr,feedback
    integer::l
    if(.not.water_ready.or.water_run/=control%RUN.or.water_day/=control%YRDOY.or.water_nlayr/=nlayr) &
      error stop 'NI: missing or stale actual root water snapshot'
    if(legacy_nh4<0 .and. .not.NI_COMMON_ROOT_ENABLED()) error stop 'NI: native NH4 species capacity was not initialized'
    feedback=exp(-pool_beta*sum(q3)/max(q_no3_max*sum(carrier),1.e-12_dp))
    if(rnk_mode>=RNK_MODE_A) then
      ! 公共核: 1=A(等效根际运输, T2) 2=B(径向有限体积, T3)
      r_rnk_source_day=control%YRDOY
      call NI_ROOT_UPTAKE_RNK(nlayr,bd,depth,ll,sat,no3,nh4,kg2ppm,uno3,unh4,feedback)
      return
    end if
    uno3=0; unh4=0
    do l=1,nlayr
      theta=theta_snapshot(l)
      wet=max(0._dp,min(1._dp,(theta-real(ll(l),dp))/max(real(dul(l)-ll(l),dp),1.e-12_dp)))
      if(theta>dul(l)) wet=max(0._dp,min(1._dp,(real(sat(l),dp)-theta)/max(real(sat(l)-dul(l),dp),1.e-12_dp)))
      length=100*rlv_snapshot(l)*real(depth(l),dp)
      concentration=max(0._dp,real(no3(l)*bd(l),dp))/max(theta,1.e-12_dp)
      call NI_ROOT_KERNEL(concentration,rwu_snapshot(l),length,root_v,root_k,diffusion_k*wet, &
          feedback*sqrt(wet),root_mode,potential,cr)
      r_bulk(l)=concentration;r_cr(l)=cr;r_mf(l)=.01_dp*rwu_snapshot(l)*concentration
      r_mem(l)=potential
      if(root_mode==2) r_diff(l)=.001_dp*diffusion_k*wet*length*max(0._dp,concentration-cr)
      potential=min(potential,max(0._dp,real(no3(l)-.25,dp)/real(kg2ppm(l),dp)/10))
      uno3(l)=flux32(10*potential)
      ! Native NH4 rate and saturation form, without shared NO3/ANDEM scaling
      ! or the native arbitrary low-concentration cutoff.
      potential=.1_dp*length*sqrt(wet)*max(0._dp,1-exp(-.08_dp*real(nh4(l),dp)))*legacy_nh4
      potential=min(potential,max(0._dp,real(nh4(l)-.5,dp)/real(kg2ppm(l),dp)/10))
      unh4(l)=flux32(10*potential)
    end do
    r_candidate3(1:nlayr)=real(uno3(1:nlayr),dp)/10
    r_candidate4(1:nlayr)=real(unh4(1:nlayr),dp)/10
  end subroutine
  ! ---- RNK 账本辅助: 按形态选择既有/扩展诊断数组 ----
  elemental real(dp) function rnk_cb(s,l)
    integer,intent(in)::s,l
    rnk_cb=merge(r_bulk(l),r_rnk_bulk4(l),s==rnk_NO3)
  end function rnk_cb
  elemental real(dp) function rnk_cr(s,l)
    integer,intent(in)::s,l
    rnk_cr=merge(r_cr(l),r_rnk_cr4(l),s==rnk_NO3)
  end function rnk_cr
  elemental real(dp) function rnk_mf(s,l)
    integer,intent(in)::s,l
    rnk_mf=merge(r_mf(l),r_rnk_mf4(l),s==rnk_NO3)
  end function rnk_mf
  elemental real(dp) function rnk_cand(s,l)
    integer,intent(in)::s,l
    rnk_cand=merge(r_candidate3(l),r_candidate4(l),s==rnk_NO3)
  end function rnk_cand
  elemental real(dp) function rnk_acc(s,l)
    integer,intent(in)::s,l
    rnk_acc=merge(r_rnk_accept3(l),r_rnk_accept4(l),s==rnk_NO3)
  end function rnk_acc
  elemental real(dp) function rnk_fin(s,l)
    integer,intent(in)::s,l
    rnk_fin=merge(r_final3(l),r_final4(l),s==rnk_NO3)
  end function rnk_fin
  elemental integer function rnk_status(s,l)
    integer,intent(in)::s,l
    ! 编码: branch*10 + 裁剪位 + 100*solver_flag (B 臂重试耗尽=100+)
    rnk_status=r_rnk_branch(s,l)*10+merge(1,0,r_rnk_capped(s,l))+100*r_rnk_flag(s,l)
  end function rnk_status
  subroutine NI_ROOT_UPTAKE_RNK(nlayr,bd,depth,ll,sat,no3,nh4,kg2ppm,uno3,unh4,feedback)
    ! RootNUptake 公共核适配层: 底座数组(单精度 ppm/cm) → 双精度核输入(g N m^-2/d 内部),
    ! 返回 kg N ha^-1 d^-1 的 UNO3/UNH4 候选。诊断填充既有 r_* 账本与 rnk 扩展数组。
    integer,intent(in)::nlayr
    real,intent(in)::bd(:),depth(:),ll(:),sat(:),no3(:),nh4(:),kg2ppm(:)
    real,intent(out)::uno3(:),unh4(:)
    real(dp),intent(in)::feedback
    type(rnk_layer)::lay
    type(rnk_diag)::dg(2)
    real(dp)::theta0,extractable
    integer::l
    uno3=0; unh4=0
    do l=1,nlayr
      theta0=theta0_snapshot(l)
      extractable=max(0._dp,theta0-real(ll(l),dp))*real(depth(l),dp)
      if(rwu_snapshot(l)>extractable+1.e-6_dp.or. &
         (rwu_snapshot(l)>0._dp.and.theta0<=rwu_snapshot(l)/real(depth(l),dp))) then
        write(*,'(A,I0,A,I0,A,I0)') 'RNK: invalid water budget, run ',water_run,', day ',water_day,', layer ',l
        error stop 'RNK: actual extraction exceeds available water'
      end if
      lay%p(rnk_NO3)=real(no3(l),dp); lay%p(rnk_NH4)=real(nh4(l),dp)
      lay%bd=real(bd(l),dp); lay%kg2ppm=real(kg2ppm(l),dp); lay%dlayr=real(depth(l),dp)
      lay%rlv=real(rlv_snapshot(l),dp); lay%theta0=theta0; lay%rwu=rwu_snapshot(l)
      if(.not.all(ieee_is_finite([lay%bd,lay%kg2ppm,real(sat(l),dp)]))) &
        error stop 'RNK: nonfinite soil geometry'
      if(min(lay%bd,lay%kg2ppm,real(sat(l),dp))<=0.or.sat(l)>1.) &
        error stop 'RNK: invalid bulk density, conversion factor or saturation'
      lay%porosity=real(sat(l),dp)
      ! The shared membrane response depends on plant N status.
      lay%f_root=feedback
      lay%frac_high=1._dp; lay%frac_low=1._dp
      if(rnk_mode==RNK_MODE_B) then
         call rnk_layer_B(rnk_par,lay,dg,n_cells=rnk_radial_cells)
         if(any(dg%solver_flag/=0).or.any(abs(dg%mass_error)>1.e-9_dp)) then
           write(*,'(A,I0,A,I0,A,I0)') 'RNK: radial solve failed, run ',water_run,', day ',water_day,', layer ',l
           error stop 'RNK: radial convergence or mass closure failure'
         end if
      else
         call rnk_layer_A(rnk_par,lay,dg)
      end if
      uno3(l)=real(10*dg(rnk_NO3)%candidate)
      unh4(l)=real(10*dg(rnk_NH4)%candidate)
      r_bulk(l)=dg(rnk_NO3)%c_bulk; r_cr(l)=dg(rnk_NO3)%c_root
      r_mf(l)=dg(rnk_NO3)%mf_potential; r_diff(l)=dg(rnk_NO3)%diffusive_flux
      r_mem(l)=rnk_membrane(rnk_par,rnk_NO3,dg(rnk_NO3)%c_root,dg(rnk_NO3)%root_length, &
        lay%f_root,1._dp,1._dp)
      r_rnk_bulk4(l)=dg(rnk_NH4)%c_bulk; r_rnk_cr4(l)=dg(rnk_NH4)%c_root; r_rnk_mf4(l)=dg(rnk_NH4)%mf_potential
      r_rnk_branch(:,l)=(/dg(rnk_NO3)%branch,dg(rnk_NH4)%branch/)
      r_rnk_flag(:,l)=(/dg(rnk_NO3)%solver_flag,dg(rnk_NH4)%solver_flag/)
      r_rnk_cap(:,l)=(/dg(rnk_NO3)%stock_cap,dg(rnk_NH4)%stock_cap/)
      r_rnk_capped(:,l)=(/dg(rnk_NO3)%stock_capped,dg(rnk_NH4)%stock_capped/)
      r_rnk_stock_before(:,l)=(/real(no3(l),dp),real(nh4(l),dp)/)/ &
        merge(real(kg2ppm(l),dp),1._dp,real(kg2ppm(l),dp)>0._dp)/10._dp
      r_rnk_transport(:,l)=dg
      r_rnk_adv(:,l)=dg%advective_flux
      r_rnk_mass_error(:,l)=dg%mass_error
      r_rnk_theta0(l)=theta0
      r_rnk_diff(:,l)=(/dg(rnk_NO3)%diffusive_flux,dg(rnk_NH4)%diffusive_flux/)
    end do
    r_candidate3(1:nlayr)=real(uno3(1:nlayr),dp)/10
    r_candidate4(1:nlayr)=real(unh4(1:nlayr),dp)/10
  end subroutine
  pure subroutine NI_CURVE_KERNEL(w,a,b,rmin,rmax,lower,critical,upper,w0)
    real(dp),intent(in)::w,a,b,rmin,rmax
    real(dp),intent(out)::lower,critical,upper
    real(dp),intent(in),optional::w0
    real(dp)::breakpoint
    breakpoint=1
    if(present(w0)) breakpoint=w0
    critical=a*max(breakpoint,w)**(-b); lower=rmin*critical; upper=rmax*critical
  end subroutine
  pure subroutine NI_V4_CURVE_KERNEL(w,a,b,cinf,rmin,rmax,w0,lower,critical,upper)
    real(dp),intent(in)::w,a,b,cinf,rmin,rmax,w0
    real(dp),intent(out)::lower,critical,upper
    if(cinf==0)then
      call NI_CURVE_KERNEL(w,a,b,rmin,rmax,lower,critical,upper,w0)
    else
      critical=cinf+(a-cinf)*max(w0,w)**(-b)
      lower=rmin*critical;upper=rmax*critical
    endif
  end subroutine
  subroutine references(weights)
    real(dp),intent(in)::weights(3)
    real(dp)::w
    w=max(0._dp,weights(1)+weights(2))/100 ! g DM/m2 -> t DM/ha; standing vegetative shoot
    call NI_V4_CURVE_KERNEL(w,leaf_a,leaf_b,leaf_inf,merge(leaf_min_ratio,min_ratio,leaf_min_ratio>0), &
      max_ratio,curve_w0,cmin(1),ccrit(1),cmax(1))
    call NI_V4_CURVE_KERNEL(w,stem_a,stem_b,stem_inf,merge(stem_min_ratio,min_ratio,stem_min_ratio>0), &
      max_ratio,curve_w0,cmin(2),ccrit(2),cmax(2))
  end subroutine
  subroutine NI_TARGETS(wleaf,wstem,fnil,fnis)
    real,intent(in)::wleaf,wstem
    real,intent(inout)::fnil,fnis
    if(.not.NI_CURVES()) return
    call references([real(wleaf,dp),real(wstem,dp),0._dp])
    fnil=real(ccrit(1)); fnis=real(ccrit(2))
  end subroutine
  subroutine NI_REFERENCES(leafmax,stemmax)
    real,intent(out)::leafmax,stemmax
    leafmax=real(cmax(1)); stemmax=real(cmax(2))
  end subroutine
  real function NI_GROWTH()
    NI_GROWTH=real(growth_factor)
    if(state_timing==1.and.day_valid) NI_GROWTH=real(day_growth)
  end function
  real function NI_LEAF_FACTOR(rnitp,slw,slwref)
    real,intent(in)::rnitp,slw,slwref
    real(dp)::functional,reference,ratio,whole_slw
    functional=max(0._dp,(real(rnitp,dp)/100*structural_fraction-cmin(1))*real(slw,dp))
    reference=(ccrit(1)-cmin(1))*real(slwref,dp)
    if(NI_REVISED()) then
      ! Organic N above critical is reserve, not proportional Pmax gain.
      functional=min(functional,(ccrit(1)-cmin(1))*real(slw,dp))
      reference=(ccrit(1)-cmin(1))*photo_slw_ref
    end if
    if(NI_C4_PHOTO())then
      ! RNITP and native SLW both exclude carbohydrate. Convert both bases,
      ! not the concentration alone, to obtain actual organic N/leaf area.
      whole_slw=max(0._dp,real(slw,dp))/max(structural_fraction,1.e-12_dp)
      functional=max(0._dp,(real(rnitp,dp)/100*structural_fraction-cmin(1))*whole_slw)
      functional=min(functional,(ccrit(1)-cmin(1))*whole_slw)
    endif
    if(photo_reference_mode==1)then
      ! Fixed functional area-N reference in g N/m2 leaf; native SLW is
      ! g DM/cm2 leaf. No second NNI or legacy SLW multiplier is added.
      NI_LEAF_FACTOR=real(NI_V4_PHOTO_KERNEL(10000._dp*functional,photo_sln_ref,photo_floor,photo_gamma))
      return
    endif
    ratio=max(0._dp,min(1._dp,functional/max(reference,1.e-15_dp)))
    NI_LEAF_FACTOR=real(photo_floor+(1-photo_floor)*ratio**photo_gamma)
  end function
  pure real(dp) function NI_V4_PHOTO_KERNEL(functional_sln,reference,floor,gamma) result(f)
    real(dp),intent(in)::functional_sln,reference,floor,gamma
    f=floor+(1-floor)*max(0._dp,min(1._dp,functional_sln/max(reference,1.e-15_dp)))**gamma
  end function
end module CG_Nitrogen
