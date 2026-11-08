! Conservative organ N dispatch. Legacy organ totals remain the N inventory.
! Fast organic reserves are SUBSETS of those totals, in protein-equivalent
! units. Assimilation and resynthesis retain CROPGRO's existing C costs.
module N_BUFFER_MOD
  use iso_fortran_env, only: real64
  use, intrinsic :: ieee_arithmetic, only: ieee_is_finite
  implicit none
  private
  public :: NBUF_ACT, nb_read, nb_init, nb_targets, nb_plan, nb_allocate
  public :: nb_leftover, nb_commit, nb_leaf_loss, nb_stem_loss
  public :: nb_repair, nb_store, nb_mob, nb_reserve, nb_loss, nb_ncrit
  public :: nb_min_ratio, nb_smooth, nb_rate, nb_root_request
  public :: nb_kmob, nb_kfill, nb_protect, nb_target, nb_capacity, nb_delta
  public :: nb_transport_cost, nb_begin_reserve, nb_supply_residual
  public :: nb_carbon, nb_growth_supply, nb_withheld, nb_returned
  public :: nb_rejected,nb_settle_root,nb_seed_return
  public :: nb_function_ratio, nb_function_response
  public :: nb_photo_ready,nb_photo_factor,nb_photo_response
  public :: nb_bound_mob
  public :: nb_write_diagnostics
  public :: nb_root_capture,nb_root_write,nb_c_allocation
  public :: nb_soil_response,nb_uptake_mode,nb_soil_alpha,nb_stem_bmult,nb_stem_target
  public :: nb_limit_veg
  public :: nb_dm_audit
  public :: nb_root_partition
  public :: nb_sync_fruit
  public :: nb_cpool_delta,nb_cpool_audit
  public :: nb_feedback_response,nb_uptake_signal,nb_get_uptake_psi
  public :: nb_relative_state, nstate_mode, state_tau
  public :: nb_psi_star, nb_nni_func, nb_psi_pub, nb_relax_pub
  public :: floor_ratio, cap_density, nb_uptake_psi, nstate_pub_ready
  public :: nb_curve_conc
  public :: nb_psi_n, nb_dmax, nb_sigma_no3, nb_sigma_nh4
  public :: nb_beta_grow, nb_alpha_h, nb_alpha_l, nb_root_depth_max
  public :: nb_get_psi, nb_get_dmax, nb_set_dmax, nb_efflux_barrier, nb_calc_dmax
  public :: nb_get_beta_grow, nb_get_alpha_h, nb_get_alpha_l, nb_get_root_depth_max
  integer, parameter :: dp=real64
  real :: NBUF_ACT=0.0
  real(dp) :: nb_uptake_psi=0._dp
  real(dp) :: nb_psi_n=0._dp, nb_dmax=0._dp
  real(dp) :: nb_sigma_no3=0.70_dp, nb_sigma_nh4=0.30_dp
  real(dp) :: nb_beta_grow=1.80_dp, nb_alpha_h=3.00_dp, nb_alpha_l=1.50_dp, nb_root_depth_max=40.0_dp
  real(dp) :: nb_kmob=.35_dp, nb_kfill=.25_dp, nb_protect=.05_dp
  real(dp) :: nb_target=.20_dp, nb_capacity=.50_dp, nb_delta=.10_dp
  real(dp) :: nb_soil_alpha=.08_dp,nb_stem_bmult=1._dp,nb_stem_target=.20_dp
  integer :: nb_uptake_mode=0
  real(dp) :: organ_conc(5)=0,stem_ratio=0
  real(dp) :: nb_transport_cost=0._dp
  real(dp) :: nb_reserve(2)=0, nb_begin_reserve(2)=0, nb_ncrit(3)=0
  real(dp) :: cap_density(2)=0, cap(2)=0, repair_request(3)=0
  real(dp) :: plan(2)=0, refill_request(2)=0, budget(2)=0
  real(dp) :: nb_repair(3)=0, nb_store(2)=0, nb_mob(2)=0, nb_loss(2)=0
  real(dp) :: old_n(5)=0, old_seed=0, seed_supply=0, growth_demand=0
  real(dp) :: old_dm(5)=0
  real(dp) :: fruit_damage(2)=0
  real(dp) :: nb_root_request=0, nb_supply_residual=0, available=0
  real(dp) :: repaired_n=0, root_actual=0, extra_c=0
  real(dp) :: nb_growth_supply=0, assimilation_c=0, resynthesis_c=0, fruit_critical=0, nb_withheld=0
  real(dp) :: nb_rejected=0,root_provisional=0,nb_seed_return=0,seed_provisional=0
  real(dp) :: nb_fill_limit(2)=0
  real(dp) :: nb_returned=0
  real(dp) :: nb_function_ratio=1
  real(dp) :: nb_bound_mob(2)=0, floor_ratio(2)=0
  real(dp) :: curve_a=0,curve_b=0,curve_w0=1,curve_inf=0,photo_mean=0,photo_critical=0
  real(dp) :: photo_sum=0,photo_min=1,photo_max=0
  integer :: photo_calls=0
  logical :: nb_photo_ready=.false.
  logical :: nb_write_diagnostics=.true.
  real(dp),allocatable :: root_no3(:),root_nh4(:),root_length(:),root_water(:),root_kin(:),root_avail(:)
  integer :: run_key=0, trt_key=0, date_key=0, day_key=0
  logical :: pending=.false.
  ! v15_s4_nstate: fused plant-N state selection (NState.nml)
  !   nstate_mode=1  frozen S1 piecewise psi on total organ N (default;
  !                  byte-identical when the nml is absent)
  !   nstate_mode=2  fused psi*: functional-N basis + unified dilution
  !                  curve, two-sided anchored (-1 band floor, +1 capacity)
  !   state_tau>0    optional first-order relaxation of the PUBLISHED
  !                  growth-side state (nb_get_psi); the uptake feedback
  !                  (nb_get_uptake_psi) always reads the instantaneous psi.
  integer :: nstate_mode=1
  real(dp) :: state_tau=0._dp
  real(dp) :: nb_psi_pub=0._dp, nb_psi_star=0._dp, nb_nni_func=0._dp
  logical :: nstate_pub_ready=.false.
  logical :: nstate_exists=.false.
contains
  subroutine require(ok,message)
    logical,intent(in) :: ok
    character(*),intent(in) :: message
    integer :: u
    if (.not.ok) then
      open(newunit=u,file='NBufferFailure.txt',status='replace')
      write(u,'(A)') message
      write(u,*) 'keys',run_key,trt_key,date_key,day_key
      write(u,*) 'old_n',old_n,'old_seed',old_seed,'seed_supply',seed_supply
      write(u,*) 'reserve',nb_reserve,'begin',nb_begin_reserve,'cap',cap
      write(u,*) 'critical',nb_ncrit,'repair_req',repair_request,'repair',nb_repair
      write(u,*) 'plan',plan,'mob',nb_mob,'store',nb_store
      write(u,*) 'uptake',root_actual,'available',available,'growth_demand',growth_demand
      close(u)
      write(*,'(A)') 'NBUFFER_V2: '//message
      error stop 86
    end if
  end subroutine

  pure real(dp) function nb_smooth(x,width) result(y)
    real(dp),intent(in) :: x,width
    if(x<=0) then
      y=0
    else if(x<width) then
      y=x*x/(2*width)
    else
      y=x-width/2
    end if
  end function

  pure real(dp) function nb_rate(k,dt) result(y)
    real(dp),intent(in) :: k,dt
    y=1-exp(-k*dt)
  end function

  pure real function nb_function_response(x) result(y)
    real(dp),intent(in) :: x
    y=real(1-(1-max(0._dp,min(1._dp,x)))**2)
  end function

  pure real function nb_photo_response(psi) result(f)
    real(dp),intent(in) :: psi
    real(dp) :: p
    if (psi >= 0._dp) then
      f = 1.0
    else
      p = max(-1._dp, psi)
      f = real(1._dp - (-p)**2.5_dp)
    end if
  end function

  pure real function nb_soil_response(concentration) result(f)
    real,intent(in) :: concentration
    ! An empirical soil dry-mass concentration response, not a transporter
    ! Michaelis constant. Existing stock floors remain in NUPTAK.
    real(dp) :: c,k
    c=max(0._dp,real(concentration,dp))
    if(nb_uptake_mode==2)then
      ! Matched half-saturation to mode 1; empirical DRY SOIL units.
      ! This is neither a solution Km nor a HATS/LATS decomposition.
      k=log(2._dp)/nb_soil_alpha
      f=real(c/(k+c))
    else
      f=real(1-exp(-nb_soil_alpha*c))
    endif
  end function

  pure subroutine nb_curve_conc(weff,conc)
    ! v15_s4_nstate: unified dilution-curve concentration basis (leaf,
    ! stem) shared by the plan-side and commit-side state computations,
    ! removing the former dual basis (FNIN targets at plan vs curve at
    ! commit). Identical formula to the nb_commit curve lines and to
    ! nb_targets (curve_w0 low-biomass platform included).
    real(dp),intent(in)::weff
    real(dp),intent(out)::conc(2)
    real(dp)::base
    base=max(1._dp,weff/(100*curve_w0))
    conc(1)=(curve_inf+(curve_a-curve_inf)*base**(-curve_b))/100
    conc(2)=(curve_inf+(curve_a-curve_inf)*base**(-curve_b*nb_stem_bmult))*stem_ratio/100
  end subroutine

  subroutine nb_relax_pub()
    ! Published growth-side state: instantaneous unless state_tau>0
    ! (v4 growth_tau first-order relaxation). Mode 1 / tau=0 assign
    ! nb_psi_n directly, bit-identical to the frozen S1 behavior.
    if(.not.nstate_pub_ready) then
      nb_psi_pub=nb_psi_n
      nstate_pub_ready=.true.
    else if(state_tau>0._dp) then
      nb_psi_pub=nb_psi_pub+(1._dp-exp(-1._dp/state_tau))*(nb_psi_n-nb_psi_pub)
    else
      nb_psi_pub=nb_psi_n
    end if
  end subroutine

  pure subroutine nb_relative_state(dm,n,c,rmin,qcap,nmin,ncrit,nmax,psi,nni,valid)
    real(dp),intent(in) :: dm(2),n(2),c(2),rmin(2),qcap(2)
    real(dp),intent(out) :: nmin,ncrit,nmax,psi,nni
    logical,intent(out) :: valid
    nmin=sum(dm*c*rmin);ncrit=sum(dm*c);nmax=sum(dm*(c+qcap))
    valid=sum(dm)>1.e-10_dp.and.ncrit>nmin.and.nmax>ncrit
    psi=0;nni=0
    if(.not.valid)return
    nni=sum(n)/ncrit
    if(sum(n)<=ncrit)then
      psi=(sum(n)-ncrit)/(ncrit-nmin)
    else
      psi=(sum(n)-ncrit)/(nmax-ncrit)
    endif
  end subroutine

  pure real function nb_min_ratio(pro_min,pro_max) result(y)
    real,intent(in) :: pro_min,pro_max
    y=max(0.05,min(1.0,pro_min/max(1.e-6,pro_max)))
  end function

  pure real function nb_root_partition(base_root,gain,stress) result(y)
    real,intent(in) :: base_root,gain,stress
    ! A bounded transfer of the existing shoot share toward roots.
    ! Preserves the small-stress slope; a gain above 1 cannot create
    ! negative shoot allocation as it does in the legacy linear formula.
    y=real(1-(1-max(0._dp,min(1._dp,real(base_root,dp))))* &
      exp(-max(0._dp,real(gain,dp))*(1-max(0._dp,min(1._dp,real(stress,dp))))))
  end function

  subroutine nb_limit_veg(carbon,base_cost,base_protein,partition,growth,n_growth,cost)
    real,intent(in) :: carbon,base_cost(3),base_protein(3),partition(3)
    real,intent(inout) :: growth(3),n_growth(3)
    real,intent(out) :: cost
    real(dp) :: protein(3),nonprotein(3),required,scale
    call require(all(growth>=0).and.all(n_growth>=0),'negative organ growth or new-tissue N')
    protein=0
    where(growth>1.e-12) protein=real(n_growth,dp)/max(1.e-12_dp,real(growth,dp))/.16_dp
    call require(all(protein>=0.and.protein<1),'invalid new tissue composition')
    nonprotein=(1-protein)/(1-real(base_protein,dp))
    cost=real(sum(real(base_cost*partition,dp)*nonprotein))
    required=sum(real(growth,dp))*real(cost,dp)
    scale=min(1._dp,max(0._dp,real(carbon,dp))/max(1.e-20_dp,required))
    growth=real(real(growth,dp)*scale);n_growth=real(real(n_growth,dp)*scale)
  end subroutine

  subroutine nb_read(filecc)
    character(*),intent(in) :: filecc
    character(512) :: line
    real(dp) :: x(16)
    integer :: u,ios,v
    NBUF_ACT=0
    nb_kmob=.35_dp; nb_kfill=.25_dp; nb_protect=.05_dp
    nb_target=.20_dp; nb_capacity=.50_dp; nb_delta=.10_dp
    nb_transport_cost=0;nb_soil_alpha=.08_dp;nb_uptake_mode=0
    nb_stem_bmult=1;nb_stem_target=nb_target
    nb_beta_grow=1.80_dp; nb_alpha_h=3.00_dp; nb_alpha_l=1.50_dp; nb_root_depth_max=40.0_dp
    open(newunit=u,file=filecc,status='old',action='read',iostat=ios)
    call require(ios==0,'cannot open species file')
    do
      read(u,'(A)',iostat=ios) line
      if(ios/=0) exit
      if(trim(line)/='!*ORGAN NITROGEN RESERVES AND BUFFER DILUTION') cycle
      do
        read(u,'(A)',iostat=ios) line
        call require(ios==0,'reserve card has no values')
        if(len_trim(line)==0) cycle
        if(line(1:1)=='!' .or. line(1:1)=='@') cycle
        exit
      end do
      x=[0._dp,.35_dp,.25_dp,.05_dp,.20_dp,.50_dp,.10_dp,0._dp, &
         .08_dp,0._dp,1._dp,.20_dp,1.80_dp,3.00_dp,1.50_dp,40.0_dp]
      read(line,'(8F6.0)',iostat=ios) x(1:8)
      call require(ios==0,'invalid fixed-width reserve card')
      x(12)=x(5)
      if(len_trim(line)>=54) then
        line(len_trim(line)+1:72)=' '
        read(line(49:72),'(4F6.0)',iostat=ios) x(9:12)
        call require(ios==0,'incomplete extended reserve card')
      end if
      if(len_trim(line)>=78) then
        line(len_trim(line)+1:96)=' '
        read(line(73:96),'(4F6.0)',iostat=ios) x(13:16)
        call require(ios==0,'incomplete extended dynamic card')
      end if
      call require(all(ieee_is_finite(x)),'nonfinite reserve card')
      call require(x(9)>=.001_dp.and.x(9)<=1,'invalid soil concentration coefficient')
      call require(x(10)==0.or.x(10)==1.or.x(10)==2,'uptake mode must be zero, one or two')
      call require(x(11)>=.25_dp.and.x(11)<=5,'invalid stem dilution multiplier')
      call require(x(12)>=x(4).and.x(12)<=x(6),'invalid stem reserve target')
      call require(x(1)==0 .or. x(1)==1,'enable must be zero or one')
      call require(x(2)>=0 .and. x(2)<=2 .and. x(3)>=0 .and. x(3)<=2,'invalid rates')
      call require(x(4)>=0 .and. x(4)<=x(5) .and. x(5)<=x(6) .and. x(6)<=1,'invalid reserve ordering')
      call require(x(7)>0 .and. x(7)<=1 .and. x(8)>=0 .and. x(8)<=10,'invalid feedback/cost')
      call require(x(13)>=0._dp .and. x(13)<=10._dp, 'invalid beta grow rate')
      call require(x(14)>=0._dp .and. x(14)<=20._dp, 'invalid alpha_h feedback')
      call require(x(15)>=0._dp .and. x(15)<=20._dp, 'invalid alpha_l feedback')
      call require(x(16)>=5._dp .and. x(16)<=300._dp, 'invalid max root depth')
      NBUF_ACT=real(x(1)); nb_kmob=x(2); nb_kfill=x(3)
      nb_protect=x(4); nb_target=x(5); nb_capacity=x(6)
      nb_delta=x(7); nb_transport_cost=x(8)
      nb_soil_alpha=x(9);nb_uptake_mode=int(x(10));nb_stem_bmult=x(11);nb_stem_target=x(12)
      nb_beta_grow=x(13);nb_alpha_h=x(14);nb_alpha_l=x(15);nb_root_depth_max=x(16)
      exit
    end do
    close(u)
    open(newunit=v,file='NBufferParam.OUT',status='replace')
    write(v,'(A)') '@ ENABLE KMOB KFILL PROTECT TARGET CAPACITY DELTA TRANSPORT_EXTRA_CH2O_PER_N SOIL_ALPHA UPTAKE_MODE STEM_BMULT STEM_TARGET BETA_GROW ALPHA_H ALPHA_L ROOT_DEPTH_MAX'
    write(v,'(16(ES24.15,1X))') real(NBUF_ACT,dp),nb_kmob,nb_kfill,nb_protect,nb_target, &
      nb_capacity,nb_delta,nb_transport_cost,nb_soil_alpha,real(nb_uptake_mode,dp),nb_stem_bmult,nb_stem_target, &
      nb_beta_grow,nb_alpha_h,nb_alpha_l,nb_root_depth_max
    close(v)
    call read_nstate_nml()
  end subroutine

  subroutine read_nstate_nml()
    ! v15_s4_nstate: locate NState.nml in the run directory, falling back
    ! to the DSSAT_NSTATE_NML environment path (calibration sandboxes).
    ! Absent file keeps nstate_mode=1, i.e. the frozen S1 behavior.
    use iso_fortran_env, only: error_unit
    character(512)::path,msg
    integer::u,ios
    namelist /NSTATE/ nstate_mode,state_tau
    path='NState.nml'
    inquire(file=path,exist=nstate_exists)
    if(.not.nstate_exists) then
      path=' '
      call get_environment_variable('DSSAT_NSTATE_NML',path)
      if(len_trim(path)>0) inquire(file=trim(path),exist=nstate_exists)
    end if
    if(.not.nstate_exists) then
      nstate_mode=1; state_tau=0._dp
      return
    end if
    open(newunit=u,file=trim(path),status='old',action='read',iostat=ios,iomsg=msg)
    if(ios/=0) then
      write(error_unit,'(A)') 'N_BUFFER_V2: cannot open '//trim(path)//' -- '//trim(msg)
      error stop 'N_BUFFER_V2: NState.nml open failure'
    end if
    read(u,nml=NSTATE,iostat=ios,iomsg=msg)
    close(u)
    if(ios/=0) then
      write(error_unit,'(A)') 'N_BUFFER_V2: bad NState.nml -- '//trim(msg)
      error stop 'N_BUFFER_V2: NState.nml read failure'
    end if
    if(nstate_mode<1.or.nstate_mode>2) error stop 'N_BUFFER_V2: nstate_mode must be 1 or 2'
    if(state_tau<0._dp) error stop 'N_BUFFER_V2: state_tau must be >= 0'
    write(*,'(A,I0,A,ES12.4,A)') ' N_BUFFER_V2: nstate_mode=',nstate_mode, &
      ' state_tau=',state_tau,' (v15_s4_nstate fused plant-N state)'
  end subroutine

  subroutine nb_init(run)
    integer,intent(in) :: run
    integer :: u
    nb_reserve=0; nb_begin_reserve=0; plan=0; budget=0
    nb_repair=0; nb_store=0; nb_mob=0; nb_loss=0; nb_ncrit=0
    nb_uptake_psi=0._dp
    nb_psi_n=0._dp; nb_dmax=0._dp
    nb_psi_pub=0._dp; nb_psi_star=0._dp; nb_nni_func=0._dp
    nstate_pub_ready=.false.
    nb_photo_ready=.false.;photo_calls=0;photo_sum=0;photo_min=1;photo_max=0
    pending=.false.;nb_seed_return=0;nb_rejected=0;root_provisional=0;nb_fill_limit=0
    if(NBUF_ACT<.5 .or. run/=1 .or. .not.nb_write_diagnostics) return
    open(newunit=u,file='NAcceptance.csv',status='replace')
    write(u,'(A)') 'run,trt,yrdoy,das,root_provisional,root_accepted,root_rejected,seed_provisional,seed_returned,'// &
      'leaf_fill_limit,stem_fill_limit,leaf_store,stem_store,leaf_cap,stem_cap,leaf_repair,stem_repair,root_repair,'// &
      'preferred_leaf_refill,preferred_stem_refill,prepaid_assim_ch2o,accepted_assim_ch2o,refunded_assim_ch2o,internal_n_cancelled'
    close(u)
    open(newunit=u,file='CH2OPools.csv',status='replace')
    write(u,'(A)') 'run,trt,yrdoy,das,organ,begin_ch2o,end_ch2o,organ_dm,new_tissue,alpha,draw,loss,store,old_fraction,residual'
    close(u)
    open(newunit=u,file='RootNSupply.csv',status='replace')
    write(u,'(A)') 'run,trt,yrdoy,das,layer,no3_mgN_kgdrysoil,nh4_mgN_kgdrysoil,root_length_cm_cm3,'// &
      'water_cm3_cm3,kinetic_potential_kgN_ha,stock_limited_potential_kgN_ha,actual_kgN_ha,root_request_kgN_ha,carbon_scale'
    close(u)
    open(newunit=u,file='CAllocation.csv',status='replace')
    write(u,'(A)') 'run,trt,yrdoy,das,actual_available_ch2o,assimilation_ch2o,resynthesis_ch2o,extra_transport_ch2o,'// &
      'fixation_ch2o,fruit_ch2o,vegetative_ch2o,carbohydrate_storage_ch2o,end_ch2o,residual_ch2o,'// &
      'potential_stored_c_credit,actual_stored_c_draw,prepaid_carbohydrate_storage,'// &
      'leaf_c_draw,stem_c_draw,root_c_draw,shell_c_draw'
    close(u)
    open(newunit=u,file='DMState.csv',status='replace')
    write(u,'(A)') 'run,trt,yrdoy,das,leaf_dm,stem_dm,root_dm,shell_dm,seed_dm,'// &
      'leaf_residual,stem_residual,root_residual,shell_residual,seed_residual,'// &
      'pod_sum_residual,shoot_sum_residual,plant_sum_residual,harvest_dm'
    close(u)
    open(newunit=u,file='CohortSync.csv',status='replace')
    write(u,'(A)')'run,trt,yrdoy,das,organ,cohort_before,physical_target,bookkeeping_correction,roundoff_bound,begin_dm,growth,loss,damage'
    close(u)
    open(newunit=u,file='OrganNState.csv',status='replace')
    write(u,'(A)') 'run,trt,yrdoy,das,leaf_dm,stem_dm,root_dm,leaf_n,stem_n,root_n,fruit_n,'// &
      'leaf_reserve,stem_reserve,leaf_critical,stem_critical,root_critical,shoot_nni,leaf_functional_pct,'// &
      'vegetative_dm_t_ha,vegetative_n_g_m2,minimum_n_g_m2,critical_n_g_m2,maximum_n_g_m2,'// &
      'psi_raw,vegetative_nni,state_valid'
    close(u)
    open(newunit=u,file='PhotoN.csv',status='replace')
    write(u,'(A)') 'run,trt,yrdoy,das,kernel_calls,unweighted_mean_n_factor,min_n_factor,max_n_factor,functional_pct,next_critical_pct'
    close(u)
    open(newunit=u,file='NFlux.csv',status='replace')
    write(u,'(A)') 'run,trt,yrdoy,das,growth_request,repair_request,refill_request,root_request,root_actual,'// &
      'seed_supply,leaf_mobilized,stem_mobilized,leaf_repaired,stem_repaired,root_repaired,leaf_stored,stem_stored,'// &
      'leaf_reserve_lost,stem_reserve_lost,source_residual,extra_transport_c,leaf_bound_mobilized,stem_bound_mobilized'
    close(u)
    open(newunit=u,file='NCBalance.csv',status='replace')
    write(u,'(A)') 'run,trt,yrdoy,das,begin_plant_and_seed_n,root_input,fixation_input,end_plant_and_seed_n,'// &
      'outside_loss,plant_residual,leaf_residual,stem_residual,root_residual,shell_residual,seed_residual,'// &
      'reserve_residual,harvest_n,assimilation_ch2o,resynthesis_ch2o,extra_transport_ch2o'
    close(u)
  end subroutine

  subroutine nb_targets(weff,a,b,w0,cinf,proli,prosi,prolf,prosf,leaf,stem)
    real,intent(in) :: weff,a,b,w0,cinf,proli,prosi,prolf,prosf
    real,intent(out) :: leaf,stem
    leaf=(cinf+(a-cinf)*max(1.,weff/w0)**(-b))/100.
    stem_ratio=real(prosi/max(1.e-6,proli),dp)
    stem=real((cinf+(a-cinf)*max(1._dp,real(weff/w0,dp))**(-b*nb_stem_bmult))*stem_ratio/100)
    curve_a=a;curve_b=b;curve_w0=w0;curve_inf=cinf
    cap_density=nb_capacity*real([a/100.,a/100.*prosi/max(1.e-6,proli)],dp)
    floor_ratio=real([nb_min_ratio(prolf,proli),nb_min_ratio(prosf,prosi)],dp)
  end subroutine

  real function nb_photo_factor(layer_n) result(f)
    real,intent(in) :: layer_n
    real(dp) :: critical_layer,ratio,denom,psi_n
    ! Same optimal layer gradient as the native sun/shade allocation.
    ! Continuous smooth photo-response f_N,photo(psi_N) = 1 - (-psi_N)**2.5 for psi_N < 0, 1.0 for psi_N >= 0.
    critical_layer=max(1.e-6_dp,photo_critical+real(layer_n,dp)-photo_mean)
    ratio=max(0._dp,real(layer_n,dp))/critical_layer
    if (ratio >= 1._dp) then
      psi_n = 0._dp
    else
      denom = max(1.e-6_dp, 1._dp - floor_ratio(1))
      psi_n = (ratio - 1._dp) / denom
    end if
    f = nb_photo_response(psi_n)
    photo_calls=photo_calls+1;photo_sum=photo_sum+real(f,dp)
    photo_min=min(photo_min,real(f,dp));photo_max=max(photo_max,real(f,dp))
  end function

  subroutine nb_plan(run,trt,date,day,demand,dm,n,seed_remaining,seed_released,c,root_out,damage)
    integer,intent(in) :: run,trt,date,day
    real,intent(in) :: demand,dm(5),n(5),seed_remaining,seed_released,c(5)
    real,intent(out) :: root_out
    real,intent(in),optional :: damage(2)
    real(dp) :: total(3),sig,excess(2),release(2),fill(2),net(2),suma
    real(dp) :: state_min,state_crit,state_max,psi_today,veg_nni
    real(dp)::signal_n(2),ready_n(2),gap_n(2),signal_psi,nn_signal,nmin_signal,ncrit_signal,nmax_signal
    real(dp)::curve_conc(2),curve_ncrit(2),func_n(2)
    integer::decision_unit
    logical::decision_exists
    logical :: state_valid
    call require(.not.pending,'previous step has not committed')
    run_key=run; trt_key=trt; date_key=date; day_key=day
    old_n=real(n,dp); old_seed=real(seed_remaining+seed_released,dp)
    old_dm=real(dm,dp)
    fruit_damage=0
    if(present(damage))fruit_damage=real(damage,dp)
    organ_conc=real(c,dp)
    growth_demand=max(0._dp,real(demand,dp))
    seed_supply=seed_released
    call require(all(old_n>=-1.e-7_dp),'negative starting organ N')
    call require(all(nb_reserve<=old_n(1:2)+1.e-6_dp),'reserve exceeds organ N')
    nb_begin_reserve=nb_reserve
    nb_ncrit=real(dm(1:3),dp)*real(c(1:3),dp)
    nb_function_ratio=max(0._dp,old_n(1)-nb_reserve(1))/max(1.e-12_dp,nb_ncrit(1))
    ! Capacity is per surviving dry mass, not a shrinking dilution-curve cap.
    cap=max(0._dp,real(dm(1:2),dp))*cap_density
    call require(all(nb_reserve<=cap+2.e-5_dp),'reserve exceeds nominal physical capacity')
    nb_fill_limit=max(0._dp,cap-nb_reserve)*nb_rate(nb_kfill,1._dp)

    ! Compute relative distance psi_N for active uptake down-regulation and efflux barrier
    if (nstate_mode == 2) then
      ! v15_s4_nstate fused state psi*: functional-N basis (reserves that
      ! cannot be mobilized today do not inflate the state) on the unified
      ! dilution curve. nb_relative_state's two-sided anchoring then gives
      !   deficiency: psi* = (NNI_f-1)/(1-r_min_eff), anchored -1 at the
      !                reference-band floor (floor_ratio)
      !   luxury:     psi* = (N_func-Ncrit)/(Nmax-Ncrit), anchored +1 at
      !                physical capacity (cap_density)
      call nb_curve_conc(sum(real(dm(1:2),dp)),curve_conc)
      curve_ncrit=real(dm(1:2),dp)*curve_conc
      func_n=nb_uptake_signal(real(old_n(1:2),dp),curve_ncrit,nb_reserve,nb_kmob,nb_protect)
      call nb_relative_state(real(dm(1:2),dp),func_n,curve_conc,floor_ratio,cap_density, &
        state_min,state_crit,state_max,psi_today,veg_nni,state_valid)
    else
      call nb_relative_state(real(dm(1:2),dp),real(old_n(1:2),dp),organ_conc(1:2),floor_ratio,cap_density, &
        state_min,state_crit,state_max,psi_today,veg_nni,state_valid)
    end if
    if (state_valid) then
      nb_psi_n = max(-1.0_dp, min(1.0_dp, psi_today))
    else
      nb_psi_n = 0.0_dp
    end if
    nb_psi_star=nb_psi_n
    nb_nni_func=veg_nni
    call nb_relax_pub()

    signal_n=old_n(1:2)
    ready_n=min(max(0._dp,nb_reserve)*nb_rate(nb_kmob,1._dp),max(0._dp,nb_reserve-nb_protect*nb_ncrit(1:2)))
    gap_n=max(0._dp,nb_ncrit(1:2)-max(0._dp,old_n(1:2)-nb_reserve))
    nb_uptake_psi=nb_psi_n
    total=old_n(1:3)
    repaired_n=0; nb_repair=0; nb_store=0; nb_mob=0; nb_loss=0; nb_bound_mob=0
    nb_returned=0;nb_rejected=0;root_provisional=0;nb_seed_return=0;seed_provisional=seed_supply
    repair_request=max(0._dp,nb_ncrit-[total(1)-nb_reserve(1),total(2)-nb_reserve(2),total(3)])*nb_rate(nb_kfill,1._dp)

    ! Physiological capacity demand D_max (kg N/ha)
    ! Upgrades root uptake ceiling to fill available luxury buffer headroom up to N_max(W_veg)
    if (state_valid .and. state_max > sum(old_n(1:2))) then
      nb_dmax = ((state_max - sum(old_n(1:2))) * nb_rate(nb_kfill, 1._dp) + growth_demand) * 10.0_dp
    else
      nb_dmax = growth_demand * 10.0_dp
    end if
    ! Headroom protection: bound by total absorbable capacity to guarantee exact ledger closure
    nb_dmax = min(nb_dmax, (growth_demand + sum(repair_request) + sum(max(0._dp, cap - nb_reserve)) * nb_rate(nb_kfill, 1._dp)) * 10.0_dp)
    nb_dmax = max(0._dp, nb_dmax)
    ! n(4:5), c(4:5) are fruit shell and seed; fruit is never a donor.
    fruit_critical=sum(real(dm(4:5),dp)*real(c(4:5),dp))
    ! Organ feedback uses the same vegetative biomass as the dilution curve.
    ! Fruit remains an independent growth sink, never a donor or a mask
    ! for leaf/stem deficiency. Do not multiply this into all root influx.
    sig=sum(old_n(1:2))/max(1.e-12_dp,sum(nb_ncrit(1:2)))
    sig=1/(1+exp(-max(-40._dp,min(40._dp,(sig-1)/nb_delta))))
    budget=nb_reserve*nb_rate(nb_kmob,1._dp)
    excess=[nb_smooth(old_n(1)-nb_ncrit(1),nb_delta*max(1.e-8_dp,nb_ncrit(1))), &
            nb_smooth(old_n(2)-nb_ncrit(2),nb_delta*max(1.e-8_dp,nb_ncrit(2)))]
    release=sig*min(budget,min(max(0._dp,nb_reserve-nb_protect*nb_ncrit(1:2)),excess))
    ! A nonexistent sink cannot veto reserve replenishment through a
    ! hypothetical release preference. Bound the intended export BEFORE
    ! coordinating the two directions, not only after the netting step.
    suma=sum(release)
    if(suma>0) release=release*min(1._dp,(growth_demand+sum(repair_request))/suma)
    fill=max(0._dp,min(cap,[nb_target,nb_stem_target]*nb_ncrit(1:2))-nb_reserve)*nb_rate(nb_kfill,1._dp)
    net=release-fill
    plan=max(0._dp,net)
    suma=sum(plan)
    if(suma>0) plan=plan*min(1._dp,(growth_demand+sum(repair_request))/suma)
    refill_request=max(0._dp,-net)
    nb_root_request=max(0._dp,growth_demand+sum(repair_request)-sum(plan)-seed_supply)+sum(refill_request)
    if(nb_write_diagnostics)then
      inquire(file='NDecision.csv',exist=decision_exists)
      open(newunit=decision_unit,file='NDecision.csv',status='unknown',position='append')
      if(.not.decision_exists)write(decision_unit,'(A)')'run,trt,yrdoy,das,total_psi,uptake_psi,'// &
        'leaf_total_n,stem_total_n,leaf_reserve,stem_reserve,leaf_ready_n,stem_ready_n,'// &
        'leaf_functional_gap,stem_functional_gap,leaf_signal_n,stem_signal_n,growth_request,repair_request,dmax_kgN_ha'
      write(decision_unit,'(4(I0,","),*(ES24.15,:,","))')run_key,trt_key,date_key,day_key, &
        nb_psi_n,nb_uptake_psi,old_n(1:2),nb_reserve,ready_n,gap_n,signal_n,growth_demand,sum(repair_request),nb_dmax
      close(decision_unit)
      if(nstate_mode==2) then
        ! Dedicated fused-state ledger keeps NDecision.csv byte-stable in
        ! every mode; mode-2 diagnostics live in NStatePsi.csv.
        inquire(file='NStatePsi.csv',exist=decision_exists)
        open(newunit=decision_unit,file='NStatePsi.csv',status='unknown',position='append')
        if(.not.decision_exists)write(decision_unit,'(A)') &
          'run,trt,yrdoy,das,nstate_mode,psi_total,psi_star,nni_func,psi_pub,uptake_psi'
        write(decision_unit,'(4(I0,","),*(ES24.15,:,","))')run_key,trt_key,date_key,day_key, &
          real(nstate_mode,dp),nb_psi_n,nb_psi_star,nb_nni_func,nb_psi_pub,nb_uptake_psi
        close(decision_unit)
      end if
    endif
    root_out=real(nb_root_request)
    pending=.true.
  end subroutine

  subroutine nb_sync_fruit(shell,seed,ngrow,loss)
    real,intent(inout) :: shell(:),seed(:)
    real,intent(in) :: ngrow(2),loss(2)
    real(dp) :: target(2),before(2),correction(2),tol(2),scale
    integer :: j,u
    ! Bulk organ inventories are authoritative. Reconcile only accumulated
    ! floating-point drift in the redundant nominal cohort representation;
    ! never change physical DM/N or relax their conservation checks.
    target=max(0._dp,old_dm(4:5)+real(ngrow,dp)-real(loss,dp)-fruit_damage)
    before=[sum(real(shell,dp)),sum(real(seed,dp))]
    correction=target-before
    tol=max(1.e-5_dp,4*real(max(1,day_key),dp)*real(epsilon(1.),dp)*max(1._dp,before,target))
    if(nb_write_diagnostics) then
      open(newunit=u,file='CohortSync.csv',status='old',position='append')
      do j=1,2
        write(u,'(5(I0,","),*(ES24.15,:,","))')run_key,trt_key,date_key,day_key,j, &
          before(j),target(j),correction(j),tol(j),old_dm(j+3),real(ngrow(j),dp),real(loss(j),dp),fruit_damage(j)
      end do
      close(u)
    end if
    call require(all(abs(correction)<=tol),'cohort/bulk discrepancy exceeds accumulated roundoff bound')
    if(before(1)>0)then
      scale=target(1)/before(1);shell=real(real(shell,dp)*scale)
    endif
    if(before(2)>0)then
      scale=target(2)/before(2);seed=real(real(seed,dp)*scale)
    endif
  end subroutine

  subroutine nb_allocate(uptake,seed,mob_cap,slow_rate,navl,nmine,lf,st)
    real,intent(in) :: uptake,seed,mob_cap,slow_rate
    real,intent(out) :: navl,nmine,lf,st
    real(dp) :: shortfall,remaining(2),suma,repair_ratio,fill_total,excess
    call require(pending,'allocation without demand plan')
    root_actual=uptake;root_provisional=uptake
    available=real(uptake+seed,dp)+sum(plan)
    shortfall=max(0._dp,growth_demand+sum(repair_request)-available)
    remaining=min(max(0._dp,budget-plan),max(0._dp,nb_reserve-plan))
    suma=sum(remaining)
    nb_mob=plan
    if(suma>0) nb_mob=nb_mob+remaining*min(1._dp,shortfall/suma)
    suma=sum(nb_mob)
    if(suma>0) nb_mob=nb_mob*min(1._dp,real(max(0.,mob_cap),dp)/suma)
    ! Reproductive/new-growth sinks may use slowly mobilizable bound N
    ! only after root + fast reserves are insufficient. Loss of function
    ! is explicit and feeds tomorrow's photosynthesis and senescence.
    remaining=max(0._dp,old_n(1:2)-nb_reserve-floor_ratio*nb_ncrit(1:2))* &
      max(0._dp,min(1._dp,real(slow_rate,dp)))
    shortfall=max(0._dp,growth_demand-real(uptake+seed,dp)-sum(nb_mob))
    shortfall=min(shortfall,max(0._dp,real(mob_cap,dp)-sum(nb_mob)))
    suma=sum(remaining)
    if(suma>0) nb_bound_mob=remaining*min(1._dp,shortfall/suma)
    available=real(uptake+seed,dp)+sum(nb_mob)+sum(nb_bound_mob)
    repair_ratio=min(1._dp,max(0._dp,available-growth_demand)/max(1.e-12_dp,sum(repair_request)))
    nb_repair=repair_request*repair_ratio
    excess=max(0._dp,available-growth_demand-sum(nb_repair))
    fill_total=sum(refill_request)
    if(fill_total>0) nb_store=refill_request*min(1._dp,excess/fill_total)
    navl=real(available-sum(nb_repair)-sum(nb_store))
    nb_withheld=sum(nb_repair)+sum(nb_store)
    nb_growth_supply=navl
    nmine=real(sum(nb_mob)+sum(nb_bound_mob))
    lf=real(nb_mob(1)+nb_bound_mob(1)); st=real(nb_mob(2)+nb_bound_mob(2))
  end subroutine

  subroutine nb_leftover(left,lf,st,rt)
    real,intent(in) :: left
    real,intent(out) :: lf,st,rt
    real(dp) :: deficit(3),take(3),room(2),x,suma,excess
    x=max(0._dp,real(left,dp))
    suma=sum(nb_bound_mob)
    nb_returned=min(x,suma)
    if(suma>0) nb_bound_mob=nb_bound_mob*(1-nb_returned/suma)
    x=x-nb_returned
    ! Release is a reservation until actual sinks are known. Cancel unused
    ! internal credit before allocating root surplus; no same-pool cycling.
    suma=sum(nb_mob)
    excess=min(x,suma)
    if(suma>0) nb_mob=nb_mob*(1-excess/suma)
    x=x-excess;nb_returned=nb_returned+excess
    ! Actual growth may use less N than predicted. Repair first, then store
    ! in bounded spare volume. No silent NLEAK or unbounded clipping.
    deficit=max(0._dp,repair_request-nb_repair)
    suma=sum(deficit); take=0
    if(suma>0) take=deficit*min(1._dp,x/suma)
    nb_repair=nb_repair+take; x=max(0._dp,x-sum(take))
    room=min(max(0._dp,cap-nb_reserve+nb_mob-nb_store),max(0._dp,nb_fill_limit-nb_store))
    where(nb_mob>1.e-12_dp) room=0
    suma=sum(room)
    if(suma>0) then
      nb_store=nb_store+room*min(1._dp,x/suma)
      x=max(0._dp,x-suma)
    end if
    ! Unaccepted root N is still a reservation: cancel before soil integration.
    nb_rejected=min(x,root_actual)
    root_actual=root_actual-nb_rejected
    x=max(0._dp,x-nb_rejected)
    ! Seed release is also provisional. Return unused seed N to SDNPL, never delete it.
    nb_seed_return=min(x,seed_supply)
    seed_supply=seed_supply-nb_seed_return
    x=max(0._dp,x-nb_seed_return)
    call require(x<2.e-5_dp,'unplaced N after root/seed reservation cancellation')
    lf=real(nb_repair(1)+nb_store(1)); st=real(nb_repair(2)+nb_store(2)); rt=real(nb_repair(3))
  end subroutine

  subroutine nb_settle_root(u3,u4,t3,t4,total,r3,r4,refund)
    real,intent(inout)::u3(:),u4(:),t3,t4,total
    real,intent(in)::r3,r4
    real,intent(out)::refund
    real(dp)::initial,final,scale,prepaid,accepted
    integer::u
    initial=real(t3,dp)+real(t4,dp)
    call require(abs(initial-root_provisional)<2.e-6_dp,'provisional root allocation differs')
    scale=max(0._dp,min(1._dp,(initial-nb_rejected)/max(1.e-20_dp,initial)))
    prepaid=(real(t3,dp)*real(r3,dp)+real(t4,dp)*real(r4,dp))/.16_dp
    refund=real(prepaid*(1-scale))
    u3=real(real(u3,dp)*scale);u4=real(real(u4,dp)*scale)
    t3=sum(u3)/10.;t4=sum(u4)/10.;total=t3+t4
    final=real(total,dp)
    call require(abs(final-root_actual)<2.e-6_dp,'settled layer/organ uptake mismatch')
    root_actual=final
    accepted=(real(t3,dp)*real(r3,dp)+real(t4,dp)*real(r4,dp))/.16_dp
    if(nb_write_diagnostics)then
      open(newunit=u,file='NAcceptance.csv',status='old',position='append')
      write(u,'(4(I0,","),*(ES24.15,:,","))')run_key,trt_key,date_key,day_key, &
        root_provisional,root_actual,nb_rejected,seed_provisional,nb_seed_return, &
        nb_fill_limit,nb_store,cap,nb_repair,refill_request,prepaid,accepted,real(refund,dp),nb_returned
      close(u)
    endif
  end subroutine

  real function nb_leaf_loss(dm,loss,nonmobil,pcn,minconc) result(nloss)
    real,intent(in) :: dm,loss,nonmobil,pcn,minconc
    real(dp) :: r,frac,nonr,conc
    r=max(0._dp,nb_begin_reserve(1)-nb_mob(1))
    frac=min(1._dp,max(0._dp,real(loss,dp)/max(1.e-8_dp,real(dm,dp))))
    nb_loss(1)=r*frac
    nonr=max(0._dp,old_n(1)-nb_begin_reserve(1)-nb_bound_mob(1))
    conc=nonr/max(1.e-8_dp,real(dm,dp))
    nloss=real(nb_loss(1)+min(nonr,real(nonmobil,dp)*conc+ &
      max(0._dp,real(loss-nonmobil,dp))*min(conc,real(minconc,dp))))
  end function

  real function nb_stem_loss(dm,loss,nonmobil,pcn,minconc) result(nloss)
    real,intent(in) :: dm,loss,nonmobil,pcn,minconc
    real(dp) :: r,frac,nonr,conc
    r=max(0._dp,nb_begin_reserve(2)-nb_mob(2))
    frac=min(1._dp,max(0._dp,real(loss,dp)/max(1.e-8_dp,real(dm,dp))))
    nb_loss(2)=r*frac
    nonr=max(0._dp,old_n(2)-nb_begin_reserve(2)-nb_bound_mob(2))
    conc=nonr/max(1.e-8_dp,real(dm,dp))
    nloss=real(nb_loss(2)+min(nonr,real(nonmobil,dp)*conc+ &
      max(0._dp,real(loss-nonmobil,dp))*min(conc,real(minconc,dp))))
  end function

  subroutine nb_carbon(assim,resyn)
    real,intent(in) :: assim,resyn
    assimilation_c=assim; resynthesis_c=resyn
  end subroutine

  subroutine nb_c_allocation(begin_c,pot_mob,act_mob,saved,fix_c,fruit_c,veg_c,store_c,end_c,draw)
    real,intent(in) :: begin_c,pot_mob,act_mob,saved,fix_c,fruit_c,veg_c,store_c,end_c,draw(4)
    real(dp) :: residual,tol,cavailable,cend
    integer :: u
    extra_c=(sum(nb_mob)+sum(nb_bound_mob))*nb_transport_cost
    ! Native PGAVL begins with potential stored-C credit and later debits
    ! CSAVEV twice in the unused working variable. Physical sources use
    ! only actual storage withdrawal; CADLF/ST already contain CSAVEV.
    cavailable=real(begin_c,dp)-real(pot_mob,dp)+real(act_mob,dp)
    cend=real(end_c,dp)+real(saved,dp)-real(pot_mob,dp)+real(act_mob,dp)
    residual=cavailable-assimilation_c-resynthesis_c-extra_c-real(fix_c+fruit_c+veg_c+store_c,dp)-cend
    if(nb_write_diagnostics) then
      open(newunit=u,file='CAllocation.csv',status='old',position='append')
      write(u,'(4(I0,","),*(ES24.15,:,","))') run_key,trt_key,date_key,day_key, &
        cavailable,assimilation_c,resynthesis_c,extra_c,real(fix_c,dp),real(fruit_c,dp), &
        real(veg_c,dp),real(store_c,dp),cend,residual,real(pot_mob,dp),real(act_mob,dp),real(saved,dp),real(draw,dp)
      close(u)
    end if
    tol=max(1.e-5_dp,100*real(epsilon(1.),dp)*max(1._dp,real(begin_c,dp)))
    call require(abs(residual)<tol,'CH2O allocation budget does not close')
    call require(cend>=-tol,'growth spent unavailable CH2O')
    call require(abs(sum(real(draw,dp))-real(act_mob,dp))<=tol,'stored C draw and credited source differ')
  end subroutine

  subroutine nb_root_capture(nl,no3,nh4,rlv,sw,kin_no3,kin_nh4,kg2ppm)
    integer,intent(in) :: nl
    real,intent(in) :: no3(:),nh4(:),rlv(:),sw(:),kin_no3(:),kin_nh4(:),kg2ppm(:)
    if(allocated(root_no3)) deallocate(root_no3,root_nh4,root_length,root_water,root_kin,root_avail)
    allocate(root_no3(nl),root_nh4(nl),root_length(nl),root_water(nl),root_kin(nl),root_avail(nl))
    root_no3=no3(:nl);root_nh4=nh4(:nl);root_length=rlv(:nl);root_water=sw(:nl)
    root_kin=real(kin_no3(:nl),dp)+real(kin_nh4(:nl),dp)
    root_avail=min(real(kin_no3(:nl),dp),max(0._dp,(root_no3-.25_dp)/real(kg2ppm(:nl),dp)))+ &
      min(real(kin_nh4(:nl),dp),max(0._dp,(root_nh4-.5_dp)/real(kg2ppm(:nl),dp)))
  end subroutine

  subroutine nb_root_write(nl,u3,u4,cscale)
    integer,intent(in) :: nl
    real,intent(in) :: u3(:),u4(:),cscale
    integer :: i,u
    if(.not.nb_write_diagnostics) return
    call require(allocated(root_no3),'missing root potential trace')
    open(newunit=u,file='RootNSupply.csv',status='old',position='append')
    do i=1,nl
      write(u,'(5(I0,","),*(ES24.15,:,","))') run_key,trt_key,date_key,day_key,i, &
        root_no3(i),root_nh4(i),root_length(i),root_water(i),root_kin(i),root_avail(i), &
        real(u3(i)+u4(i),dp),10*nb_root_request,real(cscale,dp)
    end do
    close(u)
  end subroutine

  subroutine nb_dm_audit(dm,aggregate,ngrow,loss,cmobil,store,nadd,harvest)
    real,intent(in) :: dm(5),aggregate(3),ngrow(5),loss(5),cmobil(5),store(5),nadd(3),harvest
    real(dp) :: residual(5),sums(3),tol
    integer :: u
    residual=old_dm+real(ngrow,dp)-real(loss,dp)-real(cmobil,dp)+real(store,dp)-real(dm,dp)
    residual(1:2)=residual(1:2)-(nb_mob+nb_bound_mob)/.16_dp
    residual(1:3)=residual(1:3)+real(nadd,dp)/.16_dp
    sums=[sum(real(dm(4:5),dp)),sum(real(dm([1,2,4,5]),dp)),sum(real(dm,dp))]-real(aggregate,dp)
    tol=max(2.e-5_dp,40*real(epsilon(1.),dp)*max(1._dp,sum(real(dm,dp))))
    if(nb_write_diagnostics) then
      open(newunit=u,file='DMState.csv',status='old',position='append')
      write(u,'(4(I0,","),*(ES24.15,:,","))') run_key,trt_key,date_key,day_key, &
        real(dm,dp),residual,sums,real(harvest,dp)
      close(u)
    end if
    call require(all(real(dm,dp)>=-tol),'negative organ dry matter')
    call require(maxval(abs(residual))<tol,'organ dry matter step imbalance')
    call require(maxval(abs(sums))<tol,'organ sums disagree with pod/shoot/plant dry matter')
  end subroutine

  subroutine nb_commit(dm,n,seed,ngrow,nloss,nadd,fixation,harvest,rnitp,wcrlf)
    real,intent(in) :: dm(5),n(5),seed,ngrow(5),nloss(5),nadd(3),fixation,harvest,wcrlf
    real,intent(out) :: rnitp
    real(dp) :: organ_res(5),plant_res,reserve_res,nend,nbeg,idx,func
    real(dp) :: state_min,state_crit,state_max,psi,veg_nni
    real(dp) :: func_n(2)
    logical :: state_valid
    integer :: u
    nb_reserve=nb_begin_reserve-nb_mob+nb_store-nb_loss
    reserve_res=sum(nb_begin_reserve-nb_mob+nb_store-nb_loss-nb_reserve)
    call require(all(nb_reserve>=-1.e-8_dp),'negative reserve')
    call require(all(nb_reserve<=real(n(1:2),dp)+1.e-6_dp),'reserve exceeds updated total')
    call require(all(nb_reserve<=max(0._dp,real(dm(1:2),dp))*cap_density+2.e-5_dp),'updated reserve exceeds nominal capacity')
    call require(all(nb_store<=nb_fill_limit+2.e-6_dp),'storage exceeds physical daily fill limit')
    call require(all(nb_repair<=repair_request+2.e-6_dp),'repair exceeds daily rate')
    organ_res=old_n+real(ngrow-nloss,dp)-real(n,dp)
    organ_res(1:2)=organ_res(1:2)-nb_mob-nb_bound_mob
    organ_res(1:3)=organ_res(1:3)+real(nadd,dp)
    nb_supply_residual=real(root_actual+seed_supply+sum(nb_mob)+sum(nb_bound_mob),dp)-sum(real(ngrow,dp))-sum(real(nadd,dp))
    nbeg=sum(old_n)+old_seed; nend=sum(real(n,dp))+real(seed,dp)
    plant_res=nbeg+root_actual+real(fixation,dp)-nend-sum(real(nloss,dp))
    func=max(0._dp,real(n(1),dp)-nb_reserve(1))
    rnitp=real(100*func/max(1.e-6_dp,real(dm(1)-wcrlf,dp)))
    photo_mean=rnitp
    photo_critical=(curve_inf+(curve_a-curve_inf)*max(1._dp, &
      real(dm(1)+dm(2),dp)/(100*curve_w0))**(-curve_b))*real(dm(1),dp)/ &
      max(1.e-6_dp,real(dm(1)-wcrlf,dp))
    nb_photo_ready=dm(1)>1.e-5
    organ_conc(1)=(curve_inf+(curve_a-curve_inf)*max(1._dp,real(dm(1)+dm(2),dp)/(100*curve_w0))**(-curve_b))/100
    organ_conc(2)=(curve_inf+(curve_a-curve_inf)*max(1._dp,real(dm(1)+dm(2),dp)/(100*curve_w0))**(-curve_b*nb_stem_bmult))*stem_ratio/100
    nb_ncrit=real(dm(1:3),dp)*organ_conc(1:3)
    fruit_critical=sum(real(dm(4:5),dp)*organ_conc(4:5))
    idx=(sum(real(n(1:2),dp))+sum(real(n(4:5),dp)))/max(1.e-12_dp,sum(nb_ncrit(1:2))+fruit_critical)
    if (nstate_mode == 2) then
      ! Fused psi* at day end: functional-N basis on the same curve
      ! concentrations computed just above (organ_conc is already the
      ! unified curve here).
      func_n=nb_uptake_signal(real(n(1:2),dp),real(dm(1:2),dp)*organ_conc(1:2),nb_reserve,nb_kmob,nb_protect)
      call nb_relative_state(real(dm(1:2),dp),func_n,organ_conc(1:2),floor_ratio,cap_density, &
        state_min,state_crit,state_max,psi,veg_nni,state_valid)
    else
      call nb_relative_state(real(dm(1:2),dp),real(n(1:2),dp),organ_conc(1:2),floor_ratio,cap_density, &
        state_min,state_crit,state_max,psi,veg_nni,state_valid)
    end if
    if (state_valid) then
      nb_psi_n = max(-1.0_dp, min(1.0_dp, psi))
    else
      nb_psi_n = 0.0_dp
    end if
    nb_psi_star=nb_psi_n
    nb_nni_func=veg_nni
    call nb_relax_pub()
    extra_c=(sum(nb_mob)+sum(nb_bound_mob))*nb_transport_cost
    if(nb_write_diagnostics) then
    open(newunit=u,file='OrganNState.csv',status='old',position='append')
    write(u,'(4(I0,","),*(ES24.15,:,","))') run_key,trt_key,date_key,day_key, &
      real(dm(1:3),dp),real(n(1:3),dp),real(sum(n(4:5)),dp),nb_reserve,nb_ncrit,idx,real(rnitp,dp), &
      sum(real(dm(1:2),dp))/100,sum(real(n(1:2),dp)),state_min,state_crit,state_max,psi,veg_nni, &
      real(merge(1,0,state_valid),dp)
    close(u)
    open(newunit=u,file='PhotoN.csv',status='old',position='append')
    write(u,'(5(I0,","),*(ES24.15,:,","))') run_key,trt_key,date_key,day_key,photo_calls, &
      photo_sum/max(1,photo_calls),photo_min,photo_max,photo_mean,photo_critical
    close(u)
    photo_calls=0;photo_sum=0;photo_min=1;photo_max=0
    open(newunit=u,file='NFlux.csv',status='old',position='append')
    write(u,'(4(I0,","),*(ES24.15,:,","))') run_key,trt_key,date_key,day_key, &
      growth_demand,sum(repair_request),sum(refill_request),nb_root_request,root_actual,seed_supply, &
      nb_mob,nb_repair,nb_store,nb_loss,nb_supply_residual,extra_c,nb_bound_mob
    close(u)
    open(newunit=u,file='NCBalance.csv',status='old',position='append')
    write(u,'(4(I0,","),*(ES24.15,:,","))') run_key,trt_key,date_key,day_key, &
      nbeg,root_actual,real(fixation,dp),nend,sum(real(nloss,dp)),plant_res,organ_res,reserve_res, &
      real(harvest,dp),assimilation_c,resynthesis_c,extra_c
    close(u)
    end if
    call require(abs(plant_res)<max(1.e-5_dp,20*real(epsilon(1.),dp)*max(1._dp,nbeg,nend)), &
      'plant step N imbalance (g/m2)')
    call require(maxval(abs(organ_res))<2.e-4_dp,'organ step N imbalance')
    call require(abs(nb_supply_residual)<2.e-4_dp,'N source/recipient imbalance')
    pending=.false.
  end subroutine

  pure real function nb_cpool_delta(growth,alpha,draw,fraction,loss,store) result(change)
    real,intent(in)::growth,alpha,draw,fraction,loss,store
    ! Protein-only repairs do not create a second, withdrawable CH2O pool.
    change=alpha*growth-draw-fraction*loss+store
  end function

  subroutine nb_cpool_audit(qbegin,qend,dm,growth,alpha,draw,loss,store,fraction)
    real,intent(in)::qbegin(3),qend(3),dm(3),growth(3),alpha(3),draw(3),loss(3),store(3),fraction(3)
    real(dp)::res(3),tol
    integer::i,u
    do i=1,3
      res(i)=real(qbegin(i),dp)+real(nb_cpool_delta(growth(i),alpha(i),draw(i),fraction(i),loss(i),store(i)),dp)-real(qend(i),dp)
    enddo
    tol=max(2.e-5_dp,40*real(epsilon(1.),dp)*max(1._dp,maxval(real(dm,dp))))
    call require(maxval(abs(res))<=tol,'CH2O pool composition imbalance')
    call require(all(real(qend,dp)>=-tol).and.all(real(qend,dp)<=real(dm,dp)+tol),'CH2O pool is not an organ DM subset')
    if(.not.nb_write_diagnostics)return
    open(newunit=u,file='CH2OPools.csv',status='old',position='append')
    do i=1,3
      write(u,'(5(I0,","),*(ES24.15,:,","))')run_key,trt_key,date_key,day_key,i, &
        real(qbegin(i),dp),real(qend(i),dp),real(dm(i),dp),real(growth(i),dp),real(alpha(i),dp), &
        real(draw(i),dp),real(loss(i),dp),real(store(i),dp),real(fraction(i),dp),res(i)
    enddo
    close(u)
  end subroutine

  pure function nb_uptake_signal(total,critical,reserve,kmob,protect) result(signal)
    real(dp),intent(in)::total(2),critical(2),reserve(2),kmob,protect
    real(dp)::signal(2),ready(2),gap(2),unavailable(2)
    ! Signalling only: never mutate N inventory or credit an internal source.
    ready=min(max(0._dp,reserve)*nb_rate(kmob,1._dp),max(0._dp,reserve-protect*critical))
    gap=max(0._dp,critical-max(0._dp,total-reserve))
    unavailable=max(0._dp,reserve-ready)
    signal=max(0._dp,total-min(unavailable,max(0._dp,gap-ready)))
  end function

  pure real function nb_get_uptake_psi() result(p)
    p=real(nb_uptake_psi)
  end function

  pure real function nb_feedback_response(psi,alpha) result(f)
    real,intent(in)::psi,alpha
    real(dp)::distance
    ! C1 at the critical boundary; alpha=0 means no down-regulation.
    ! An empirical regulation response, not measured transporter activity.
    distance=min(40._dp,max(0._dp,real(alpha,dp))*max(0._dp,real(psi,dp)))
    ! Local regularization of the legacy positive-side logistic. For
    ! alpha*psi >> delta it recovers that response, while psi=0 and
    ! alpha=0 both have factor 1 and a zero boundary derivative.
    f=real(1._dp/(1._dp+exp(distance)*tanh((distance/max(1.e-6_dp,nb_delta))**2)))
  end function

  pure real function nb_efflux_barrier(psi) result(phi)
    real,intent(in) :: psi
    real(dp) :: p
    p = max(0._dp, min(1._dp, real(psi, dp)))
    phi = real(1._dp - (p ** 6), 4)
  end function

  pure real function nb_calc_dmax(w_veg, delta_w, n_max_pct, current_n) result(dmax)
    real,intent(in) :: w_veg, delta_w, n_max_pct, current_n
    real(dp) :: pot_total_n
    pot_total_n = (real(w_veg, dp) + real(delta_w, dp)) * real(n_max_pct, dp) * 10.0_dp
    dmax = real(max(0._dp, pot_total_n - real(current_n, dp)), 4)
  end function

  pure real function nb_get_psi() result(p)
    ! Growth-side consumers (VEGGR XNSTRES / root partition / photo /
    ! PODS) read the published state: instantaneous unless state_tau>0
    ! (v4 growth_tau first-order relaxation, nstate_mode=2 only).
    ! nstate_mode=1 keeps nb_psi_pub == nb_psi_n bit-exactly.
    p = real(nb_psi_pub, 4)
  end function

  pure real function nb_get_dmax() result(d)
    d = real(nb_dmax, 4)
  end function

  subroutine nb_set_dmax(val)
    real,intent(in) :: val
    nb_dmax = real(val, dp)
  end subroutine

  pure real function nb_get_beta_grow() result(bg)
    bg = real(nb_beta_grow, 4)
  end function

  pure real function nb_get_alpha_h() result(ah)
    ah = real(nb_alpha_h, 4)
  end function

  pure real function nb_get_alpha_l() result(al)
    al = real(nb_alpha_l, 4)
  end function

  pure real function nb_get_root_depth_max() result(rd)
    rd = real(nb_root_depth_max, 4)
  end function
end module
