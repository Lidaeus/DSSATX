program native_p2_tests
  use iso_fortran_env,only:real64
  use CG_Nitrogen
  implicit none
  integer::i,j,checks=0
  real(real64)::dm(3),build(3),target(3),agr(3),proi(3),fruit(2),repair(3),ad(3),an(3),ar(3),af(2),cost(3),scale
  real(real64)::carbon,nitrogen,begin(2),sen(2),fast(2),recovery(2),fill(2),ending(2),rec(2),litter(2),res(2)
  real(real64)::n(4),w(4),legacy(4),safe(4),func(4)
  dm=[3._real64,2._real64,1._real64]
  build=[.02_real64,.01_real64,.01_real64];target=[.04_real64,.02_real64,.02_real64]
  agr=[1.4_real64,1.3_real64,1.3_real64];proi=[.25_real64,.15_real64,.15_real64]
  fruit=[4._real64,.04_real64];repair=[.02_real64,.01_real64,0._real64]
  do i=0,40
    carbon=real(i,real64)*.5_real64
    do j=0,40
      nitrogen=real(j,real64)*.01_real64
      call NI_JOINT_KERNEL(carbon,nitrogen,dm,build,target,agr,proi,fruit,repair,ad,an,ar,af,cost,scale)
      call check(sum(ad*cost)+af(1)<=carbon+1.e-12_real64,'one common C envelope')
      call check(sum(an)+sum(ar)+af(2)<=nitrogen+1.e-12_real64,'one common N envelope')
      call check(all(ad>=0).and.all(ad<=dm).and.scale>=0.and.scale<=1,'growth bounded by source and potential')
      call check(all(an>=ad*build-1.e-14_real64).and.all(an<=ad*target+1.e-14_real64),'new tissue respects composition interval')
      call check(abs(af(1)-scale*fruit(1))<1.e-14_real64,'fruit shares N scarcity, not first use of all N')
      call NI_JOINT_KERNEL(carbon,nitrogen,dm,build,target,agr,proi,fruit,repair,ad,an,ar,af,cost,scale, &
        15._real64,.03_real64)
      call check(sum(ad*cost)+af(1)+max(0._real64,sum(an)+sum(ar)+af(2)-.03_real64)*15 &
        <=carbon+1.e-12_real64,'C envelope includes accepted assimilation, not a late refund')
      call check(sum(an)+sum(ar)+af(2)<=nitrogen+1.e-12_real64,'priced assimilation cannot create extra N')
    enddo
  enddo
  call NI_JOINT_KERNEL(0._real64,1._real64,dm,build,target,agr,proi,fruit,repair,ad,an,ar,af,cost,scale)
  call check(sum(ad)==0.and.sum(af)==0,'no C means no new structural tissue or fruit growth')
  call NI_JOINT_KERNEL(20._real64,0._real64,dm,build,target,agr,proi,fruit,repair,ad,an,ar,af,cost,scale)
  call check(sum(ad)==0.and.sum(an)==0,'no N cannot create new tissue')
  begin=[.5_real64,.2_real64];sen=[.2_real64,.5_real64]
  fast=[.1_real64,.02_real64];recovery=[.04_real64,.03_real64];fill=[.03_real64,.01_real64]
  call NI_RESERVE_COMMIT_KERNEL(begin,sen,fast,recovery,fill,ending,rec,litter,res)
  call check(maxval(abs(res))<1.e-14_real64,'reserve stock-flow closure')
  call check(maxval(abs(ending-[.33_real64,.09_real64]))<1.e-14_real64,'old reserve death removed once; new fill survives')
  call check(maxval(abs(rec+litter-begin*sen))<1.e-14_real64,'senescing reserve split between recovery and litter')
  call NI_RESERVE_COMMIT_KERNEL(begin,sen,[0._real64,0._real64],[0._real64,0._real64],[0._real64,0._real64],ending,rec,litter,res)
  call check(maxval(abs(ending-begin*(1-sen)))<1.e-14_real64,'unused reservation does not leave the stock')
  n=[4._real64,2._real64,1._real64,.1_real64];w=[100._real64,100._real64,20._real64,5._real64];legacy=0
  call NI_RESERVE_DONOR_KERNEL(n,w,begin,[.01_real64,.005_real64],[.04_real64,.02_real64],legacy, &
    1._real64,10._real64,3._real64,.7_real64,1._real64,0._real64, &
    1._real64,1._real64,10._real64,5._real64,safe,func)
  call check(all(safe(1:2)>0).and.sum(func)==0,'fast reserve can supply growth without destroying healthy function')
  call NI_RESERVE_DONOR_KERNEL(n,w,begin,[.01_real64,.005_real64],[.04_real64,.02_real64],legacy, &
    1._real64,10._real64,3._real64,.7_real64,0._real64,0._real64, &
    1._real64,1._real64,0._real64,5._real64,safe,func)
  call check(sum(safe+func)==0,'no C cannot pay remobilization')
  call NI_RESERVE_DONOR_KERNEL(n,w,begin,[.01_real64,.005_real64],[.04_real64,.02_real64],legacy, &
    1._real64,10._real64,3._real64,.7_real64,0._real64,0._real64, &
    0._real64,1._real64,10._real64,5._real64,safe,func)
  call check(sum(func)==0,'repair-only demand cannot mine healthy functional protein')
  write(*,'(A,I0)')'NATIVE_P2_CHECKS_PASSED=',checks
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
