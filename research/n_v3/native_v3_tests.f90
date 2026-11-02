program native_v3_tests
  use iso_fortran_env,only:real64
  use CG_Nitrogen
  implicit none
  integer::i,checks=0
  real(real64)::z,f,old
  call check(NI_POD_KERNEL(-2._real64)==0,'negative functional state bounded')
  call check(NI_POD_KERNEL(2._real64)==1,'surplus does not amplify set')
  call check(abs(NI_POD_KERNEL(.5_real64)-.75_real64)<1.e-14_real64,'response midpoint')
  old=0
  do i=0,100
    z=real(i,real64)/100;f=NI_POD_KERNEL(z)
    call check(f>=old.and.f>=0.and.f<=1,'continuous bounded monotonic response')
    old=f
  enddo
  write(*,'(A,I0)')'NATIVE_V3_CHECKS_PASSED=',checks
contains
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
