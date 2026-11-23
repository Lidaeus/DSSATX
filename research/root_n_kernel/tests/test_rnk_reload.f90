program test_rnk_reload
  use ModuleDefs, only: ControlType
  use RootNUptake, only: dp => rnk_dp
  use CG_RootNUptakeAdapter, only: RNK_LOAD, RNK_CAPTURE, RNK_CANDIDATES, NI_COMMON_ROOT_ENABLED
  implicit none
  integer :: unit
  real :: first, last
  real(dp) :: theta_mid(1), diffusion
  type(ControlType) :: control

  call write_config('default.nml', .false.)
  call write_config('blocked_diffusion.nml', .true.)
  open(newunit=unit,file='disabled.nml',status='replace')
  write(unit,'(a)') '&ROOTNUPTAKE rnk_mode=0 /'
  close(unit)
  open(newunit=unit,file='no_root_group.nml',status='replace')
  write(unit,'(a)') '&NINTEGRATION ni_stage=0 /'
  close(unit)

  control%RUN=1
  control%YRDOY=2026100
  call RNK_CAPTURE(1,[0.30],[0.0],[1.0],[15.0],theta_mid)
  call RNK_LOAD('default.nml')
  if(.not.NI_COMMON_ROOT_ENABLED())error stop 'Default root configuration did not activate'
  first=uptake(diffusion)
  if(first<=0.or.diffusion<=0)error stop 'Default diffusion must support uptake without water extraction'

  call RNK_LOAD('blocked_diffusion.nml')
  last=uptake(diffusion)
  if(diffusion/=0.or.last>=first)error stop 'Explicit zero diffusion must override the default'
  call RNK_LOAD('disabled.nml')
  if(NI_COMMON_ROOT_ENABLED())error stop 'Explicit off retained the prior root mode'

  call RNK_LOAD('default.nml')
  last=uptake(diffusion)
  if(first/=last)error stop 'Previously loaded diffusion leaked into the default'
  call RNK_LOAD('no_root_group.nml')
  if(NI_COMMON_ROOT_ENABLED())error stop 'A missing root group retained the prior root mode'
  print '(a)', 'RNK reload checks passed'

contains

  subroutine write_config(path,zero_diffusion)
    character(*),intent(in)::path
    logical,intent(in)::zero_diffusion
    integer::unit
    open(newunit=unit,file=path,status='replace')
    write(unit,'(a)') '&ROOTNUPTAKE rnk_mode=1, rnk_radius=.0001,', &
      ' rnk_km_high=.28,.5, rnk_km_low=35.,50.,', &
      ' rnk_vmax_high=.0003,.0004, rnk_vmax_low=.0015,.002,', &
      ' rnk_kd=0.,1., rnk_residual=.25,.5, rnk_source_tag="test","test",'
    if(zero_diffusion)write(unit,'(a)') ' rnk_species_diffusion=0.,0.,'
    write(unit,'(a)') '/'
    close(unit)
  end subroutine

  real function uptake(diffusive_supply)
    real(dp),intent(out)::diffusive_supply
    real :: uno3(1),unh4(1)
    real(dp) :: bulk(1),root(1),mf(1),diffusion(1),membrane(1)
    call RNK_CANDIDATES(control,1,[1.3],[15.0],[0.10],[0.45],[10.0],[10.0],[1.0],1._dp, &
      uno3,unh4,bulk,root,mf,diffusion,membrane)
    uptake=uno3(1)+unh4(1)
    diffusive_supply=diffusion(1)
  end function
end program
