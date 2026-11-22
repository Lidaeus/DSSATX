! Connect the steady root kernel to CROPGRO's layer arrays and soil settlement.
module CG_RootNUptakeAdapter
  use iso_fortran_env, only: iostat_end
  use ieee_arithmetic, only: ieee_is_finite, ieee_next_after
  use ModuleDefs, only: ControlType, NL
  use RootNUptake, only: dp => rnk_dp, rnk_params, rnk_layer, rnk_diag, rnk_validate, rnk_membrane, &
    rnk_layer_A, RNK_MODE_OFF, RNK_MODE_A, RNK_NO3, RNK_NH4
  implicit none
  private
  public :: RNK_LOAD, RNK_RESET, RNK_CAPTURE, RNK_ACCEPT, RNK_PUBLISH, RNK_CANDIDATES
  public :: NI_COMMON_ROOT_ENABLED, NI_ROOT_SOIL_DEBIT, NI_ROOT_SOIL_END

  type :: layer_water
    real(dp) :: theta0, rwu, rlv, depth
  end type
  type(layer_water), save :: snapshot(NL)

  type :: layer_ledger
    type(rnk_diag) :: transport(2)
    type(layer_water) :: water
    real(dp) :: stock(2), candidate(2), accepted(2), settled(2)
  end type
  type(layer_ledger), save :: ledger(NL)
  type(rnk_params), save :: parameters
  integer, save :: mode=RNK_MODE_OFF, source_day=-1, pending_run=-1, pending_layers=0
  integer, save :: ledger_unit=0
  logical, save :: ledger_opened=.false., ledger_started=.false.
  character(*), parameter :: ledger_file='LayerRootNUptake.csv'

contains
  subroutine RNK_LOAD(path)
    character(*),intent(in)::path
    integer,parameter::group_len=len('&ROOTNUPTAKE')
    character(512)::line
    character(160)::validation
    integer::unit,ios,i,k,rnk_mode
    real(dp)::rnk_km_high(2),rnk_km_low(2),rnk_vmax_high(2),rnk_vmax_low(2)
    real(dp)::rnk_kd(2),rnk_residual(2),rnk_radius,rnk_species_diffusion(2),rnk_penetration_coeff
    character(32)::rnk_source_tag(2)
    namelist /ROOTNUPTAKE/ rnk_mode,rnk_km_high,rnk_km_low,rnk_vmax_high,rnk_vmax_low, &
      rnk_kd,rnk_residual,rnk_radius,rnk_species_diffusion,rnk_source_tag,rnk_penetration_coeff

    open(newunit=unit,file=trim(path),status='old',action='read',iostat=ios)
    if(ios/=0) error stop 'RNK: cannot reopen configuration'
    do
      read(unit,'(A)',iostat=ios) line
      if(ios==iostat_end) then
        close(unit)
        return
      end if
      if(ios/=0) error stop 'RNK: cannot read configuration'
      do i=1,len_trim(line)
        k=iachar(line(i:i))
        if(k>=iachar('a').and.k<=iachar('z')) line(i:i)=achar(k-32)
      end do
      i=verify(line,' '//achar(9))
      if(i==0.or.i>len(line)-group_len) cycle
      if(line(i:i+group_len-1)=='&ROOTNUPTAKE'.and.scan(line(i+group_len:i+group_len),' /!'//achar(9))/=0) exit
    end do
    rewind(unit)
    rnk_mode=RNK_MODE_OFF
    rnk_km_high=0; rnk_km_low=0; rnk_vmax_high=0; rnk_vmax_low=0
    rnk_kd=0; rnk_residual=0; rnk_radius=0
    rnk_species_diffusion=parameters%species_diffusion_m2d
    rnk_source_tag='unspecified'
    rnk_penetration_coeff=0
    read(unit,nml=ROOTNUPTAKE,iostat=ios,iomsg=line)
    close(unit)
    if(ios/=0) then
      write(*,'(A)') trim(line)
      error stop 'RNK: invalid ROOTNUPTAKE namelist'
    end if
    if(rnk_mode/=RNK_MODE_OFF.and.rnk_mode/=RNK_MODE_A) error stop 'RNK: rnk_mode must be 0 (off) or 1 (steady)'
    if(rnk_mode==RNK_MODE_OFF) return
    parameters%km_high=rnk_km_high; parameters%km_low=rnk_km_low
    parameters%vmax_high=rnk_vmax_high; parameters%vmax_low=rnk_vmax_low
    parameters%kd_sorption=rnk_kd; parameters%residual_ppm=rnk_residual
    parameters%source_tag=rnk_source_tag
    parameters%species_diffusion_m2d=rnk_species_diffusion
    parameters%root_radius_m=rnk_radius
    parameters%penetration_coeff=rnk_penetration_coeff
    validation=rnk_validate(parameters,NL)
    if(len_trim(validation)>0) then
      write(*,'(A)') trim(validation)
      error stop 'RNK: parameter validation failed'
    end if
    mode=rnk_mode
  end subroutine

  logical function NI_COMMON_ROOT_ENABLED()
    NI_COMMON_ROOT_ENABLED=mode==RNK_MODE_A
  end function

  subroutine RNK_RESET()
    if(pending_run/=-1) error stop 'RNK: season reset before reporting pending uptake'
    if(ledger_opened) error stop 'RNK: season reset before closing root ledger'
    source_day=-1
  end subroutine

  subroutine RNK_CAPTURE(nlayr,theta,rwu,rlv,depth,theta_mid)
    integer,intent(in)::nlayr
    real,intent(in)::theta(:),rwu(:),rlv(:)
    real,intent(in),optional::depth(:)
    real(dp),intent(out)::theta_mid(:)
    if(.not.present(depth)) error stop 'RNK: pre-extraction water snapshot requires layer depths'
    if(any(.not.ieee_is_finite(theta(1:nlayr))).or.any(.not.ieee_is_finite(rwu(1:nlayr))).or. &
       any(.not.ieee_is_finite(depth(1:nlayr))).or.any(.not.ieee_is_finite(rlv(1:nlayr)))) &
      error stop 'RNK: non-finite root water snapshot'
    if(any(depth(1:nlayr)<=0.).or.any(theta(1:nlayr)<0.).or.any(rwu(1:nlayr)<0.)) &
      error stop 'RNK: invalid root water snapshot'
    snapshot(1:nlayr)%theta0=real(theta(1:nlayr),dp)
    snapshot(1:nlayr)%rwu=real(rwu(1:nlayr),dp)
    snapshot(1:nlayr)%rlv=real(rlv(1:nlayr),dp)
    snapshot(1:nlayr)%depth=real(depth(1:nlayr),dp)
    theta_mid(1:nlayr)=snapshot(1:nlayr)%theta0-0.5_dp*snapshot(1:nlayr)%rwu/snapshot(1:nlayr)%depth
  end subroutine

  subroutine RNK_CANDIDATES(control,nlayr,bd,depth,ll,sat,no3,nh4,kg2ppm,feedback,uno3,unh4,bulk,cr,mf,diff,mem)
    type(ControlType),intent(in)::control
    integer,intent(in)::nlayr
    real,intent(in)::bd(:),depth(:),ll(:),sat(:),no3(:),nh4(:),kg2ppm(:)
    real(dp),intent(in)::feedback
    real,intent(out)::uno3(:),unh4(:)
    real(dp),intent(inout)::bulk(:),cr(:),mf(:),diff(:),mem(:)
    type(rnk_layer)::layer
    real(dp)::extractable
    real::candidate(2)
    integer::l,s
    if(pending_run/=-1) error stop 'RNK: previous uptake was not reported by soil'
    source_day=control%YRDOY
    uno3=0; unh4=0
    do l=1,nlayr
      layer%theta0=snapshot(l)%theta0
      layer%rwu=snapshot(l)%rwu
      layer%rlv=snapshot(l)%rlv
      layer%dlayr=real(depth(l),dp)
      layer%water_depth=snapshot(l)%depth
      extractable=max(0._dp,layer%theta0-real(ll(l),dp))*layer%water_depth
      if(layer%rwu>extractable+1.e-6_dp.or. &
         (layer%rwu>0._dp.and.layer%theta0<=layer%rwu/layer%water_depth)) then
        write(*,'(A,I0,A,I0,A,I0)') 'RNK: invalid water budget, run ',control%RUN,', day ',control%YRDOY,', layer ',l
        error stop 'RNK: actual extraction exceeds available water'
      end if
      layer%p=real([no3(l),nh4(l)],dp)
      layer%bd=real(bd(l),dp); layer%kg2ppm=real(kg2ppm(l),dp); layer%porosity=real(sat(l),dp)
      if(.not.all(ieee_is_finite([layer%bd,layer%kg2ppm,layer%porosity]))) error stop 'RNK: nonfinite soil geometry'
      if(min(layer%bd,layer%kg2ppm,layer%porosity)<=0.or.layer%porosity>1) &
        error stop 'RNK: invalid bulk density, conversion factor or saturation'
      layer%f_root=feedback

      associate(entry=>ledger(l))
        entry%water=snapshot(l)
        call rnk_layer_A(parameters,layer,entry%transport)
        candidate=real(10*entry%transport%candidate)
        do s=1,2
          if(real(candidate(s),dp)/10>entry%transport(s)%stock_cap) candidate(s)=ieee_next_after(candidate(s),0.)
        end do
        uno3(l)=candidate(RNK_NO3); unh4(l)=candidate(RNK_NH4)
        entry%candidate=real(candidate,dp)/10
        entry%stock=layer%p/layer%kg2ppm/10
        entry%accepted=0
        associate(diagnostic=>entry%transport(RNK_NO3))
          bulk(l)=diagnostic%c_bulk; cr(l)=diagnostic%c_root
          mf(l)=diagnostic%mf_potential; diff(l)=diagnostic%diffusive_flux
          mem(l)=rnk_membrane(parameters,RNK_NO3,diagnostic%c_root,diagnostic%root_length,feedback,1._dp,1._dp)
        end associate
      end associate
    end do
  end subroutine

  subroutine RNK_ACCEPT(nlayr,uno3,unh4)
    integer,intent(in)::nlayr
    real,intent(in)::uno3(:),unh4(:)
    integer::l
    do l=1,nlayr
      ledger(l)%accepted=real([uno3(l),unh4(l)],dp)/10
    end do
  end subroutine

  subroutine RNK_PUBLISH(control,nlayr,final3,final4)
    type(ControlType),intent(in)::control
    integer,intent(in)::nlayr
    real(dp),intent(in)::final3(:),final4(:)
    integer::l
    if(source_day/=control%YRDOY) return
    if(pending_run/=-1) error stop 'RNK: previous uptake was not reported by soil'
    pending_run=control%RUN
    pending_layers=nlayr
    do l=1,nlayr
      ledger(l)%settled=[final3(l),final4(l)]
    end do
  end subroutine

  subroutine NI_ROOT_SOIL_DEBIT(control,nlayr,uno3,unh4)
    type(ControlType),intent(in)::control
    integer,intent(in)::nlayr
    real,intent(in)::uno3(:),unh4(:)
    real(dp)::deducted(2,nlayr),expected(2)
    integer::l
    if(.not.NI_COMMON_ROOT_ENABLED()) return
    if(pending_run==-1) then
      if(any(uno3(1:nlayr)/=0.).or.any(unh4(1:nlayr)/=0.)) error stop 'RNK: soil debit without pending plant uptake'
      return
    end if
    if(control%RUN/=pending_run.or.nlayr/=pending_layers.or.control%YRDOY<=source_day) &
      error stop 'RNK: soil debit does not follow the pending plant uptake'
    deducted(RNK_NO3,:)=real(uno3(1:nlayr),dp)/10
    deducted(RNK_NH4,:)=real(unh4(1:nlayr),dp)/10
    if(.not.all(ieee_is_finite(deducted))) error stop 'RNK: nonfinite soil debit'
    do l=1,nlayr
      expected=ledger(l)%settled
      if(any(abs(deducted(:,l)-expected)>1.e-6_dp*max(1._dp,abs(expected)))) &
        error stop 'RNK: soil debit differs from the settled plant uptake'
    end do
    call write_ledger(nlayr,control%YRDOY,deducted)
  end subroutine

  subroutine NI_ROOT_SOIL_END(control,nlayr)
    type(ControlType),intent(in)::control
    integer,intent(in)::nlayr
    real(dp)::deducted(2,nlayr)
    if(.not.NI_COMMON_ROOT_ENABLED()) return
    if(pending_run/=-1) then
      if(control%RUN/=pending_run.or.nlayr/=pending_layers.or.control%YRDOY<source_day) &
        error stop 'RNK: season end does not match the pending plant uptake'
      ! The last plant flux is recorded as pending in the native season boundary.
      deducted=0
      call write_ledger(nlayr,0,deducted)
    end if
    if(ledger_opened) then
      close(ledger_unit)
      ledger_opened=.false.
    end if
  end subroutine

  subroutine write_ledger(nlayr,commit_day,deducted)
    integer,intent(in)::nlayr,commit_day
    real(dp),intent(in)::deducted(2,nlayr)
    integer::l,s,ios,status
    real(dp)::pending
    character(18)::soil_status
    if(.not.ledger_opened) then
      if(ledger_started) then
        open(newunit=ledger_unit,file=ledger_file,status='old',position='append',action='write',iostat=ios)
      else
        open(newunit=ledger_unit,file=ledger_file,status='replace',action='write',iostat=ios)
      end if
      if(ios/=0) error stop 'RNK: cannot open layer ledger'
      if(.not.ledger_started) then
        write(ledger_unit,'(A)') 'run,yrdoy,layer,species,source_day,soil_commit_day,'// &
          'theta0,theta_mid,rwu_cm_d,rlv_cm_cm3,stock_before_gN_m2,c_bulk_mgN_L,c_root_mgN_L,'// &
          'mf_potential_gN_m2,diffusive_gN_m2,candidate_gN_m2,accepted_gN_m2,deducted_gN_m2,stock_cap_gN_m2,'// &
          'settled_gN_m2,pending_gN_m2,radial_advective_gN_m2,radial_mass_error_gN_m2,solver_status,soil_status,'// &
          'transport_mode,shared_transport,d_bulk_m2_d,zero_diffusion,steady_residual_gN_m2,'// &
          'c_bulk_end_mgN_L,c_root_mean_mgN_L,c_bulk_mean_mgN_L,hats_candidate_gN_m2,lats_candidate_gN_m2'
        ledger_started=.true.
      end if
      ledger_opened=.true.
    end if

    soil_status=merge('committed         ','pending_season_end',commit_day/=0)
    do l=1,nlayr
      do s=1,2
        associate(entry=>ledger(l), diagnostic=>ledger(l)%transport(s))
          status=10*diagnostic%branch+merge(1,0,diagnostic%stock_capped)
          pending=merge(entry%settled(s),0._dp,commit_day==0)
          ! Keep historical CSV column positions. Radial fields are fixed placeholders.
          write(ledger_unit,'(I0,5(",",I0),17(",",ES24.15E3),",",I0,",",A,2(",",I0),",",ES24.15E3, &
               & ",",I0,6(",",ES24.15E3))') &
            pending_run,source_day,l,s,source_day,commit_day,entry%water%theta0,diagnostic%theta_mid,entry%water%rwu,entry%water%rlv, &
            entry%stock(s),diagnostic%c_bulk,diagnostic%c_root,diagnostic%mf_potential,diagnostic%diffusive_flux, &
            entry%candidate(s),entry%accepted(s),deducted(s,l),diagnostic%stock_cap,entry%settled(s),pending, &
            0._dp,0._dp,status,trim(soil_status),mode,1,diagnostic%bulk_diffusion,merge(1,0,diagnostic%zero_diffusion), &
            diagnostic%steady_residual,-99._dp,diagnostic%c_root_mean,diagnostic%c_bulk_mean, &
            diagnostic%hats_candidate,diagnostic%lats_candidate
        end associate
      end do
    end do
    flush(ledger_unit)
    pending_run=-1
    pending_layers=0
  end subroutine
end module CG_RootNUptakeAdapter
