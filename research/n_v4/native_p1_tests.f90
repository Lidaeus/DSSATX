program native_p1_tests
  use iso_fortran_env,only:real64
  use CG_Nitrogen
  implicit none
  integer::i,checks=0
  real(real64)::lo,cc,hi,l0,c0,h0,l1,c1,h1,f,previous,w
  call NI_CURVE_KERNEL(2._real64,.04_real64,.3_real64,.45_real64,1.1_real64,l0,c0,h0,.9_real64)
  call NI_V4_CURVE_KERNEL(2._real64,.04_real64,.3_real64,0._real64,.45_real64,1.1_real64,.9_real64,lo,cc,hi)
  call check(lo==l0.and.cc==c0.and.hi==h0,'zero asymptote exactly reproduces the old kernel')
  call NI_V4_CURVE_KERNEL(2._real64,.04_real64,.3_real64,0._real64,.6_real64,1.1_real64,.9_real64,l1,c1,h1)
  call check(c1==c0.and.h1==h0.and.l1>l0,'minimum-band change cannot move critical or upper reference')
  call NI_V4_CURVE_KERNEL(.9_real64-1.e-8_real64,.04_real64,.3_real64,.015_real64, &
    .6_real64,1.1_real64,.9_real64,l0,c0,h0)
  call NI_V4_CURVE_KERNEL(.9_real64+1.e-8_real64,.04_real64,.3_real64,.015_real64, &
    .6_real64,1.1_real64,.9_real64,l1,c1,h1)
  call check(abs(c1-c0)<1.e-9_real64,'plateau-to-dilution transition has no value jump')
  previous=huge(previous)
  do i=0,1000
    w=real(i,real64)/100
    call NI_V4_CURVE_KERNEL(w,.04_real64,.3_real64,.015_real64,.6_real64,1.1_real64,.9_real64,lo,cc,hi)
    call check(cc<=previous.and.lo<cc.and.cc<hi.and.cc>=.015_real64,'ordered, diluting references retain asymptote')
    previous=cc
  enddo
  call check(NI_NATIVE_MOB_FACTOR(0.,.true.)==1.,'protected donor receives no native N acceleration')
  call check(NI_NATIVE_MOB_FACTOR(0.,.false.)==1.3,'native late donor retains its acceleration')
  call check(NI_NATIVE_MOB_FACTOR(1.,.true.)==NI_NATIVE_MOB_FACTOR(1.,.false.),'N sufficiency joins both donor routes')
  call check(NI_LUX_KERNEL(-.5_real64,.25_real64,0._real64)==1,'luxury factor leaves deficiency unchanged')
  call check(NI_LUX_KERNEL(0._real64,.25_real64,0._real64)==1,'luxury factor joins at the critical point')
  call check(NI_LUX_KERNEL(.5_real64,.25_real64,0._real64)==.9375_real64,'luxury factor follows the squared surplus')
  call check(NI_LUX_KERNEL(1.2_real64,.25_real64,0._real64)==.75_real64,'luxury factor caps at the upper reference')
  call check(NI_LUX_KERNEL(1._real64,0._real64,0._real64)==1,'zero luxury amplitude is neutral')
  call check(NI_LUX_KERNEL(.20_real64,.25_real64,.25_real64)==1,'mild surplus is inside the dead zone')
  call check(NI_LUX_KERNEL(.25_real64,.25_real64,.25_real64)==1,'neutral at the onset threshold')
  call check(NI_LUX_KERNEL(.625_real64,.25_real64,.25_real64)==.9375_real64,'response rescales above the threshold')
  call check(NI_LUX_KERNEL(1._real64,.25_real64,.25_real64)==.75_real64,'onset threshold preserves maximum drop')
  call check(NI_V4_PHOTO_KERNEL(0._real64,1._real64,.05_real64,1._real64)==.05_real64,'zero function reaches floor')
  call check(NI_V4_PHOTO_KERNEL(20._real64,1._real64,.05_real64,1._real64)==1,'excess N cannot amplify capacity')
  call check(abs(NI_V4_PHOTO_KERNEL(.8_real64,1._real64,.05_real64,1._real64)-.81_real64)<1.e-14_real64, &
    'area-N uses an independent physiological reference')
  previous=0
  do i=0,200
    f=NI_V4_PHOTO_KERNEL(real(i,real64)/100,1._real64,.05_real64,1.2_real64)
    call check(f>=previous.and.f>=.05_real64.and.f<=1,'continuous positive response to restored functional N')
    previous=f
  enddo
  call check(abs(NI_V4_PHOTO_KERNEL(1._real64-1.e-9_real64,1._real64,.05_real64,1.2_real64)-1)<2.e-9_real64, &
    'no five-percent discontinuity at adequate N')
  write(*,'(A,I0)')'NATIVE_P1_CHECKS_PASSED=',checks
contains
  subroutine check(ok,label)
    logical,intent(in)::ok
    character(*),intent(in)::label
    if(.not.ok)then
      print *,'FAIL ',label
      error stop 1
    endif
    checks=checks+1
  end subroutine
end program
