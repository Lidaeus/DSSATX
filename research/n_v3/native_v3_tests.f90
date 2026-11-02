program native_v3_tests
  use iso_fortran_env,only:real64
  use CG_Nitrogen
  implicit none
  integer::i,checks=0
  real(real64)::z,f,old
  real(real64)::n(4),w(4),cm(2),cc(2),legacy(4),safe(4),func(4),safe2(4),func2(4)
  call check(NI_POD_KERNEL(-2._real64)==0,'negative functional state bounded')
  call check(NI_POD_KERNEL(2._real64)==1,'surplus does not amplify set')
  call check(abs(NI_POD_KERNEL(.5_real64)-.75_real64)<1.e-14_real64,'response midpoint')
  old=0
  do i=0,100
    z=real(i,real64)/100;f=NI_POD_KERNEL(z)
    call check(f>=old.and.f>=0.and.f<=1,'continuous bounded monotonic response')
    old=f
  enddo
  w=[100._real64,100._real64,50._real64,10._real64]
  n=[5._real64,2.5_real64,.5_real64,.1_real64]
  cm=[.016_real64,.008_real64];cc=[.04_real64,.02_real64];legacy=0
  call budget(1._real64,10._real64,100._real64,2._real64,safe,func)
  call check(all(func==0),'adequate state protects functional N')
  call check(all(safe(1:2)>0),'normal supply can release surplus organic balance')
  call check(all(safe(1:2)<=n(1:2)-cc*w(1:2)),'safe pool inventory limit')
  call budget(0._real64,10._real64,0._real64,2._real64,safe,func)
  call check(sum(safe+func)==0,'zero C cannot pay remobilization')
  call budget(0._real64,.01_real64,100._real64,2._real64,safe,func)
  call check(abs(sum(safe)-.01_real64)<1.e-14_real64.and.sum(func)==0,'safe balance used before function')
  call budget(0._real64,10._real64,.02_real64,2._real64,safe,func)
  call check(sum(safe+func)*2<=.02_real64+1.e-14_real64,'source cost is affordable before issue')
  n(1:2)=cc*w(1:2)
  call budget(.9_real64,10._real64,100._real64,2._real64,safe,func)
  call budget(.2_real64,10._real64,100._real64,2._real64,safe2,func2)
  call check(sum(func2)>sum(func).and.sum(func)>0,'continuous severe deficit enhances extra functional export')
  call check(all(func2(1:2)<=n(1:2)-w(1:2)*(cm+.7_real64*(cc-cm))),'functional protection limits flux')
  n(1:2)=cm*w(1:2)*.5_real64
  call budget(0._real64,10._real64,100._real64,2._real64,safe,func)
  call check(sum(safe+func)==0,'below-reference N stays below without artificial repair or export')
  n(1:2)=0
  call budget(0._real64,10._real64,100._real64,2._real64,safe,func)
  call check(sum(safe+func)==0,'empty donor never creates N')
  legacy(3:4)=10
  call budget(0._real64,10._real64,100._real64,2._real64,safe,func)
  call check(all(safe(3:4)<=n(3:4)),'native root shell paths bounded by physical stock')
  write(*,'(A,I0)')'NATIVE_V3_CHECKS_PASSED=',checks
contains
  subroutine budget(z,gap,c,cost,safe,func)
    real(real64),intent(in)::z,gap,c,cost
    real(real64),intent(out)::safe(4),func(4)
    call NI_REMOB_KERNEL(n,w,cm,cc,legacy,.2_real64,10._real64,3._real64,.7_real64,z,gap,c,cost,safe,func)
  end subroutine
  subroutine check(ok,label)
    logical,intent(in)::ok
    character(*),intent(in)::label
    if(.not.ok) then
      write(*,*)'FAIL ',label
      error stop 1
    endif
    checks=checks+1
  end subroutine
end program
