program native_lai_tests
  use iso_fortran_env,only:real64
  use CG_Nitrogen
  implicit none
  integer::checks=0,i,j,k
  real(real64)::n(4),w(4),cm(2),cc(2),legacy(4),reserve(2),s(4),f(4),old_s(4),old_f(4),protect(2),z
  real(real64)::dm(3),build(3),target(3),agr(3),proi(3),ad(3),an(3),cost(3),scale,factor,carbon,nitrogen,last
  n=[5._real64,3._real64,1._real64,.5_real64];w=[100._real64,100._real64,20._real64,10._real64]
  cm=[.01_real64,.005_real64];cc=[.04_real64,.02_real64];legacy=n;reserve=[.5_real64,.4_real64]
  protect=w(1:2)*(cm+.7_real64*(cc-cm))
  do i=0,100
    z=real(i,real64)/100
    call NI_REMOB_KERNEL(n,w,cm,cc,legacy,.2_real64,8.52294_real64,3._real64,.7_real64,z, &
      10._real64,100._real64,5._real64,old_s,old_f)
    call NI_REMOB_KERNEL(n,w,cm,cc,legacy,.2_real64,8.52294_real64,3._real64,.7_real64,z, &
      10._real64,100._real64,5._real64,s,f,.01_real64,.001_real64)
    call check(all(s<=old_s+1.e-14_real64).and.all(f<=old_f+1.e-14_real64),'limits do not increase export')
    call check(all(s(1:2)<=max(0._real64,n(1:2)-cc*w(1:2))*.01_real64+1.e-14_real64),'leaf/stem safe fraction cap')
    call check(all(s(3:4)<=n(3:4)*.01_real64+1.e-14_real64),'root/shell cannot bypass cap')
    call check(all(f(1:2)<=max(0._real64,min(n(1:2),cc*w(1:2))-protect)*.001_real64*(1-z)**2+1.e-14_real64), &
      'functional cap and severe-deficit gate')
    call NI_RESERVE_DONOR_KERNEL(n,w,reserve,cm,cc,legacy,.2_real64,8.52294_real64,3._real64,.7_real64,z, &
      .02_real64,10._real64,10._real64,100._real64,5._real64,s,f,.01_real64,.001_real64)
    call check(all(s(1:2)<=max(0._real64,reserve-.02_real64*cc*w(1:2))*.01_real64+1.e-14_real64), &
      'true R export cap uses eligible R, not whole organic N')
  enddo
  call check(sum(old_f)==0,'fully sufficient state does not mine function')
  dm=[3._real64,2._real64,1._real64];build=[.025_real64,.01_real64,.01_real64]
  target=[.04_real64,.02_real64,.02_real64];agr=[1.4_real64,1.3_real64,1.3_real64];proi=[.25_real64,.15_real64,.15_real64]
  do i=0,30
    carbon=real(i,real64)*.5_real64
    do j=0,30
      nitrogen=real(j,real64)*.01_real64;last=-1
      do k=0,10
        z=real(k,real64)/10
        call NI_LAI_CN_KERNEL(carbon,nitrogen,dm,build,target,agr,proi,z,2._real64,ad,an,cost,scale,factor)
        call check(sum(ad*cost)<=carbon+1.e-12_real64.and.sum(an)<=nitrogen+1.e-12_real64,'shared C/N payment')
        call check(ad(1)<=dm(1)*factor+1.e-14_real64.and.all(ad>=0),'state limits request once')
        call check(all(an>=ad*build-1.e-14_real64).and.all(an<=ad*target+1.e-14_real64),'new tissue N composition')
        call check(ad(1)+1.e-12_real64>=last,'leaf growth does not fall when current N status improves')
        call check(abs(factor-(2*z-z*z))<1.e-14_real64,'smooth stock response reference')
        last=ad(1)
      enddo
    enddo
  enddo
  call NI_LAI_CN_KERNEL(0._real64,1._real64,dm,build,target,agr,proi,1._real64,2._real64,ad,an,cost,scale,factor)
  call check(sum(ad)==0,'no usable carbon means no new leaf or other vegetative tissue')
  call NI_LAI_CN_KERNEL(20._real64,0._real64,dm,build,target,agr,proi,1._real64,2._real64,ad,an,cost,scale,factor)
  call check(sum(ad)==0,'high leaf concentration cannot bypass absent assembly N')
  write(*,'(A,I0)')'NATIVE_LAI_CHECKS_PASSED=',checks
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
