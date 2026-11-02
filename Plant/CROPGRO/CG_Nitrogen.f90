! Official 4.8.6.4 integration. No V15 code/parameter set is used.
! NI_STAGE: 0 official; 1 bounded pools; 2 finite assimilation;
!           3 root transport; 4 organ reference curves; 5 functional feedback.
module CG_Nitrogen
  use iso_fortran_env, only: real64
  use ieee_arithmetic, only: ieee_is_finite, ieee_next_after
  use ModuleDefs, only: ControlType, SwitchType, NL
  implicit none
  private
  integer, parameter :: dp=real64
  integer, parameter :: implemented_stage=5
  integer, save :: ni_stage=0, root_mode=0, output_unit=0
  logical, save :: loaded=.false., opened=.false., ready=.false., water_ready=.false.
  real(dp), save :: q_no3_max=-1, q_nh4_max=-1
  real(dp), save :: assim_no3_v=-1, assim_nh4_v=-1, assim_no3_k=-1, assim_nh4_k=-1
  real(dp), save :: root_v=-1, root_k=-1, diffusion_k=-1, pool_beta=-1
  real(dp), save :: leaf_a=-1, leaf_b=-1, stem_a=-1, stem_b=-1
  real(dp), save :: min_ratio=-1, max_ratio=-1, photo_floor=-1, photo_gamma=-1, growth_tau=-1
  real(dp), save :: q3(3)=0, q4(3)=0, carrier(3)=0, w_begin(3)=0
  real(dp), save :: litter3(NL)=0, litter4(NL)=0, returned_litter=0
  real(dp), save :: theta_snapshot(NL)=0, rwu_snapshot(NL)=0, rlv_snapshot(NL)=0
  integer, save :: water_day=-1, water_run=-1
  real(dp), save :: cmin(2)=0, ccrit(2)=0, cmax(2)=0, structural_fraction=1, growth_factor=1
  real(dp), save :: d_q_begin=0, d_u3=0, d_u4=0, d_a3=0, d_a4=0
  real(dp), save :: d_cost=0, d_refund=0, d_litter=0, d_residual=0
  real(dp), save :: legacy_nh4=-1, d_pending=0
  real(dp), save :: old_a3=0,old_a4=0,old_rsp3=0,old_rsp4=0
  real(dp), save :: org_begin=0,org_off_begin=0,leak_begin=0,legacy_n_res=0,legacy_c_overrun=0
  real(dp), save :: r_mf(NL)=0,r_diff(NL)=0,r_mem(NL)=0,r_cr(NL)=0,r_bulk(NL)=0
  real(dp), save :: r_candidate3(NL)=0,r_candidate4(NL)=0,r_final3(NL)=0,r_final4(NL)=0
  integer,save::root_output_unit=0
  logical,save::root_opened=.false.
  public :: NI_LOAD, NI_RESET, NI_ENABLED, NI_CURVES, NI_FEEDBACK
  public :: NI_BEGIN, NI_ACCEPT_UPTAKE, NI_ASSIMILATE, NI_SETTLE, NI_END
  public :: NI_RETURN_LITTER, NI_SOIL_INPUT, NI_SET_NH4
  public :: NI_CAPTURE_WATER, NI_ROOT_MODE, NI_ROOT_UPTAKE
  public :: NI_TARGETS, NI_REFERENCES, NI_GROWTH, NI_LEAF_FACTOR
  public :: NI_TOTAL_Q, NI_CURVE_KERNEL, NI_ROOT_KERNEL, NI_ASSIM_KERNEL
  public :: NI_PREASSIM, NI_MERGE_OLD
  public :: NI_ORG_BEGIN, NI_ORG_END
  public :: NI_SPLIT
contains
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
    integer::ios,unit,status,length
    logical::exists
    namelist /NINTEGRATION/ ni_stage,root_mode,q_no3_max,q_nh4_max, &
      assim_no3_v,assim_nh4_v,assim_no3_k,assim_nh4_k, &
      root_v,root_k,diffusion_k,pool_beta,leaf_a,leaf_b,stem_a,stem_b, &
      min_ratio,max_ratio,photo_floor,photo_gamma,growth_tau
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
    if(.not.NI_ENABLED()) return
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
    end if
    if(ni_stage>=5) then
      if(switch%MEPHO/='L'.or.switch%MEEVP=='Z') &
        error stop 'NI: new functional feedback currently supports verified non-Z L route only'
      if(photo_floor<0.or.photo_floor>=1.or.photo_gamma<=0.or.growth_tau<=0) &
        error stop 'NI: explicit bounded functional response parameters required'
    end if
  end subroutine
  subroutine NI_RESET()
    q3=0; q4=0; carrier=0; w_begin=0; litter3=0; litter4=0
    returned_litter=0; water_ready=.false.; ready=.false.; growth_factor=1
    cmin=0; ccrit=0; cmax=0; d_pending=0
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
  end subroutine
  subroutine NI_ORG_BEGIN(stocks,off,seed,leak)
    real,intent(in)::stocks(6),off(6),seed,leak
    org_begin=sum(real(stocks,dp))+real(seed,dp)
    org_off_begin=sum(real(off,dp));leak_begin=real(leak,dp)
  end subroutine
  subroutine NI_ORG_END(stocks,off,seed,leak,c_overrun)
    real,intent(in)::stocks(6),off(6),seed,leak,c_overrun
    legacy_n_res=sum(real(stocks,dp))+real(seed,dp)-org_begin+sum(real(off,dp))-org_off_begin &
      +real(leak,dp)-leak_begin-d_a3-d_a4
    legacy_c_overrun=real(c_overrun,dp)
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
    real(dp)::a3,a4,cost3,cost4,factor,capacity,wref,dt
    cost3=real(rno3,dp)/.16_dp; cost4=real(rnh4,dp)/.16_dp
    capacity=max(0._dp,real(accept,dp)); wref=sum(carrier)
    dt=1
    if(present(time_fraction)) dt=real(time_fraction,dp)
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
    integer::l,ios
    if(.not.NI_ENABLED()) return
    growth=max(0._dp,real(weights,dp)+max(0._dp,real(losses,dp))-w_begin)
    fraction=min(1._dp,max(0._dp,real(losses,dp))/max(w_begin+growth,1.e-12_dp))
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
      nraw=(real(org_n(1),dp)/max(real(weights(1),dp),1.e-12_dp)-cmin(1))/(ccrit(1)-cmin(1))
      target=min(1._dp,max(0._dp,nraw))
      if(.not.ready) then
        growth_factor=target
      else if(ni_stage>=5) then
        alpha=1-exp(-1/growth_tau); growth_factor=growth_factor+alpha*(target-growth_factor)
      end if
      structural_fraction=max(0._dp,real(weights(1)-wcrlf,dp))/max(real(weights(1),dp),1.e-12_dp)
    end if
    ready=.true.
    nniraw=0;nnifun=0;deficit=0;surplus=0
    if(NI_CURVES()) then
      nniraw=real(org_n(1:2),dp)/max(real(weights(1:2),dp)*ccrit,1.e-12_dp)
      nnifun=(real(org_n(1:2),dp)/max(real(weights(1:2),dp),1.e-12_dp)-cmin)/(ccrit-cmin)
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
      max(0._dp,real(org_n(1),dp)-cmin(1)*real(weights(1),dp))/max(real(lai,dp),1.e-12_dp), &
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
  subroutine NI_CAPTURE_WATER(control,nlayr,rwu,theta,rlv)
    type(ControlType),intent(in)::control
    integer,intent(in)::nlayr
    real,intent(in)::rwu(:),theta(:),rlv(:)
    if(.not.NI_ENABLED()) return
    water_day=control%YRDOY; water_run=control%RUN; water_ready=.true.
    rwu_snapshot(1:nlayr)=real(rwu(1:nlayr),dp)
    theta_snapshot(1:nlayr)=real(theta(1:nlayr),dp)
    rlv_snapshot(1:nlayr)=real(rlv(1:nlayr),dp)
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
    if(.not.water_ready.or.water_run/=control%RUN.or.water_day/=control%YRDOY) &
      error stop 'NI: missing or stale actual root water snapshot'
    if(legacy_nh4<0) error stop 'NI: native NH4 species capacity was not initialized'
    feedback=exp(-pool_beta*sum(q3)/max(q_no3_max*sum(carrier),1.e-12_dp))
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
  pure subroutine NI_CURVE_KERNEL(w,a,b,rmin,rmax,lower,critical,upper)
    real(dp),intent(in)::w,a,b,rmin,rmax
    real(dp),intent(out)::lower,critical,upper
    critical=a*max(1._dp,w)**(-b); lower=rmin*critical; upper=rmax*critical
  end subroutine
  subroutine references(weights)
    real(dp),intent(in)::weights(3)
    real(dp)::w
    w=max(0._dp,weights(1)+weights(2))/100 ! g DM/m2 -> t DM/ha; standing vegetative shoot
    call NI_CURVE_KERNEL(w,leaf_a,leaf_b,min_ratio,max_ratio,cmin(1),ccrit(1),cmax(1))
    call NI_CURVE_KERNEL(w,stem_a,stem_b,min_ratio,max_ratio,cmin(2),ccrit(2),cmax(2))
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
  end function
  real function NI_LEAF_FACTOR(rnitp,slw,slwref)
    real,intent(in)::rnitp,slw,slwref
    real(dp)::functional,reference,ratio
    functional=max(0._dp,(real(rnitp,dp)/100*structural_fraction-cmin(1))*real(slw,dp))
    reference=(ccrit(1)-cmin(1))*real(slwref,dp)
    ratio=max(0._dp,min(1._dp,functional/max(reference,1.e-15_dp)))
    NI_LEAF_FACTOR=real(photo_floor+(1-photo_floor)*ratio**photo_gamma)
  end function
end module CG_Nitrogen
