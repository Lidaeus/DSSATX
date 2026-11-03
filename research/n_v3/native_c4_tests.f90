program native_c4_tests
  use iso_fortran_env,only:real64
  use CG_Nitrogen
  implicit none
  integer::checks=0
  real(real64)::q1,litter,locked
  real(real64)::mass(2),pcn(2),lai(2)
  call NI_CARB_KERNEL(10._real64,2._real64,.08_real64,1._real64,3._real64,.2_real64,q1,litter)
  call check(abs(litter-1.4_real64)<1.e-14_real64,'old C lost only once after real draw')
  call check(abs(q1-6.76_real64)<1.e-14_real64,'growth and explicit store determine CH2O increment')
  call NI_CARB_KERNEL(10._real64,0._real64,.08_real64,0._real64,0._real64,0._real64,q1,litter)
  call check(q1==10.and.litter==0,'no new growth means no incidental mobile C from N-only repair')
  call NI_CARB_KERNEL(10._real64,0._real64,.08_real64,0._real64,3._real64,1._real64,q1,litter)
  call check(q1==0.and.litter==7,'complete old cell death removes remaining C after draw')
  call NI_SHELL_CARB_KERNEL(4._real64,10._real64,.08_real64,0._real64,50._real64,20._real64, &
    0._real64,.1_real64,q1,litter,locked)
  call check(abs(litter-1.92_real64)<1.e-14_real64,'shell harvest exports actual carbohydrate share')
  call check(abs(q1-2.88_real64)<1.e-14_real64,'harvest CH2O removed once')
  call NI_SHELL_CARB_KERNEL(4._real64,0._real64,.08_real64,0._real64,50._real64,0._real64, &
    10._real64,.1_real64,q1,litter,locked)
  call check(q1==3.and.locked==1.and.litter==0,'maturation immobilizes C internally, not litter')
  call NI_SHELL_CARB_KERNEL(1._real64,0._real64,.08_real64,2._real64,50._real64,50._real64, &
    0._real64,.1_real64,q1,litter,locked)
  call check(q1<0,'overspent shell stock stays visible to host assertion')
  lai=[2._real64,1._real64]
  call NI_CANOPY_N_KERNEL(lai,300._real64,4._real64,[.0006_real64,.3_real64],mass,pcn)
  call check(abs(sum(mass*lai)-sum(lai)/300)<1.e-14_real64,'layer masses sum to actual noncarbohydrate leaf mass')
  call check(abs(sum(pcn/100*mass*lai)-.04_real64*sum(lai)/300)<1.e-14_real64,'layer N sums to actual leaf organic N')
  call check(all(mass>=0).and.all(pcn>=0),'layer pools nonnegative')
  call NI_CANOPY_N_KERNEL(lai,3000._real64,.05_real64,[.002_real64,2._real64],mass,pcn)
  call check(all(mass>=0).and.all(pcn>=0),'extreme thin shaded leaf has no negative mass/N')
  call check(abs(sum(pcn/100*mass*lai)-.0005_real64*sum(lai)/3000)<1.e-14_real64,'extreme gradient cannot create N')
  call NI_CANOPY_N_KERNEL(lai,3000._real64,.05_real64,[.002_real64,-2._real64],mass,pcn)
  call check(abs(sum(pcn/100*mass*lai)-.0005_real64*sum(lai)/3000)<1.e-14_real64,'opposed slopes cannot erase N')
  call NI_CANOPY_N_KERNEL(lai,300._real64,0._real64,[.0006_real64,.3_real64],mass,pcn)
  call check(sum(pcn)==0,'empty canopy N cannot create positive layer N')
  call NI_CANOPY_N_KERNEL([0._real64,0._real64],300._real64,4._real64,[.0006_real64,.3_real64],mass,pcn)
  call check(sum(mass)==0.and.sum(pcn)==0,'empty canopy safe geometry')
  write(*,'(A,I0)')'NATIVE_C4_CHECKS_PASSED=',checks
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
