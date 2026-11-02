program native_A_tests
  use iso_fortran_env,only:real64
  use ModuleDefs,only:ControlType,SwitchType
  use CG_Nitrogen
  implicit none
  type(ControlType)::c
  type(SwitchType)::s
  real(real64)::lo,nc,hi,lo2,nc2,hi2
  real::dm(3),nn(3),cost,nad(3),unused,p1,p2,w(3),off(6)
  integer::checks=0
  c%CROP='TM';s%ISWNIT='Y';s%ISWSYM='N';s%ISWDIS='N'
  s%ISWWAT='Y';s%MEPHO='L';s%MEEVP='R'
  call NI_LOAD(c,s);call NI_RESET()
  call check(NI_REVISED(),'revision explicitly enabled')
  call NI_CURVE_KERNEL(.1_real64,.04_real64,.3_real64,.4_real64,1.25_real64,lo,nc,hi,.7_real64)
  call NI_CURVE_KERNEL(.7_real64,.04_real64,.3_real64,.4_real64,1.25_real64,lo2,nc2,hi2,.7_real64)
  call check(abs(nc-nc2)<1.e-14_real64,'breakpoint plateau continuous')
  call NI_CURVE_KERNEL(2._real64,.04_real64,.3_real64,.4_real64,1.25_real64,lo,nc,hi,.7_real64)
  call NI_CURVE_KERNEL(2._real64,.04_real64,.3_real64,.4_real64,1.25_real64,lo2,nc2,hi2,1._real64)
  call check(abs(nc-nc2)<1.e-14_real64,'above both breakpoints amplitudes equal')
  w=[50.,50.,20.];off=0
  call NI_BEGIN(w)
  call NI_ORG_BEGIN([2.,1.,.3,0.,0.,0.],off,0.,0.)
  call NI_DONORS([0.,0.,0.],[0.,0.,0.])
  call NI_TARGETS(w(1),w(2),p1,p2)
  dm=[2.,2.,2.];nn=[.06,.04,.04];cost=2
  call NI_VEG_RECONCILE(.1,cost,dm,nn,[1.,1.,1.],[.3,.15,.14])
  call check(sum(dm)*cost<=.100001,'composition cost limits actual growth')
  call check(all(dm>=0).and.all(nn>=0),'allocation nonnegative')
  call NI_REFILL(.1,[0.,0.,0.],[0.,0.,0.],[0.,0.,0.],[0.,0.,0.],.02,nad,unused)
  call check(nad(1)>0.and.nad(2)>0,'refill allowed with zero new leaf and stem growth')
  call check(abs(sum(nad)+unused-.1)<1.e-7,'refill plus rejected supply closes')
  call check(NI_RETAIN(.5)==1.,'new refill not debited a second time')
  call NI_ORG_BEGIN([2.2,1.,.3,0.,0.,0.],off,0.,0.)
  call check(NI_AREA_REFILL(.1)==0.,'luxury refill does not automatically create area')
  write(*,'(A,I0)')'NATIVE_A_CHECKS_PASSED=',checks
contains
  subroutine check(ok,label)
    logical,intent(in)::ok
    character(*),intent(in)::label
    if(.not.ok) then
      write(*,*)'FAIL ',label
      error stop 1
    end if
    checks=checks+1
  end subroutine
end program
