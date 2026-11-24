program test_f5_refill
  use iso_fortran_env, only: real64
  use ModuleDefs, only: ControlType, SwitchType
  use CG_Nitrogen, only: NI_LOAD, NI_REFILL_FRACTION, NI_LUX_HILL_KERNEL
  implicit none
  integer, parameter :: dp=real64
  real(dp), parameter :: km=.05_dp, critical=.04_dp, upper=.05_dp
  real(dp), parameter :: hill_k=.0625_dp, threshold=.75_dp, drop=.50_dp
  real(dp) :: f, theta, previous
  integer :: i
  type(ControlType) :: control
  type(SwitchType) :: switches

  if(command_argument_count()>0)then
    control%CROP='TM'; control%RUN=1; control%YRDOY=2026073
    switches%ISWNIT='Y'; switches%ISWSYM='N'; switches%ISWWAT='Y'; switches%ISWDIS='N'
    switches%MEPHO='L'; switches%MEEVP='R'
    call NI_LOAD(control,switches)
    stop
  endif

  if(critical+NI_REFILL_FRACTION(0._dp,km)*(upper-critical)/=critical) error stop 'F5: empty endpoint'
  if(critical+NI_REFILL_FRACTION(1._dp,km)*(upper-critical)/=upper) error stop 'F5: full endpoint'
  previous=0
  do i=1,100
    f=real(i,dp)/100
    theta=NI_REFILL_FRACTION(f,km)
    if(theta<=previous.or.theta>1) error stop 'F5: monotone bounded response'
    if(NI_REFILL_FRACTION(f,0._dp)/=f) error stop 'F5: linear response'
    previous=theta
  enddo
  print '(A)', 'F5 refill response checks passed'

  if(NI_LUX_HILL_KERNEL(0._dp,1._dp,drop,threshold,hill_k)/=1) error stop 'Hill: no luxury signal'
  if(NI_LUX_HILL_KERNEL(-.5_dp,1._dp,drop,threshold,hill_k)/=1) error stop 'Hill: deficiency affected'
  if(NI_LUX_HILL_KERNEL(.5_dp,threshold,drop,threshold,hill_k)/=1) error stop 'Hill: threshold affected'
  if(NI_LUX_HILL_KERNEL(.5_dp,.7_dp,drop,threshold,hill_k)/=1) error stop 'Hill: below threshold'
  if(NI_LUX_HILL_KERNEL(.5_dp,threshold+hill_k,drop,threshold,hill_k)/=1-drop/2) error stop 'Hill: half amplitude'
  previous=1
  do i=1,100
    f=threshold+(1-threshold)*real(i,dp)/100
    theta=NI_LUX_HILL_KERNEL(.5_dp,f,drop,threshold,hill_k)
    if(theta>=previous.or.theta<1-drop) error stop 'Hill: nonmonotone or unbounded response'
    previous=theta
  enddo
  print '(A)', 'Luxury Hill response checks passed'
end program
