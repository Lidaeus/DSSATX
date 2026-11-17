program native_n_tests
  use iso_fortran_env,only:real64
  use ModuleDefs,only:ControlType,SwitchType,NL
  use CG_Nitrogen
  implicit none
  integer,parameter::dp=real64
  type(ControlType)::c
  type(SwitchType)::s
  real(dp)::a3,a4,u,cr,low,nc,high,low2,nc2,high2
  real::un3(NL),un4(NL),s3(NL),s4(NL),rw(NL),tr3,tr4,trnu,pg,nass,rsp3,rsp4,refund
  real::w(3),loss(3),n(3),q_before,q_after,fp,unused,nold,actual_u
  real(dp)::psi
  logical::psi_valid
  integer::checks
  checks=0
  call check(NI_BUFFER_INFLOW(0._dp,1._dp,.8_dp)==0,'storage: zero supply gives zero uptake')
  call check(NI_BUFFER_INFLOW(10._dp,1._dp,1._dp)==0,'storage: full pool gives zero uptake')
  a3=NI_BUFFER_INFLOW(.5_dp,1._dp,.8_dp)
  a4=NI_BUFFER_INFLOW(1._dp,1._dp,.8_dp)
  call check(0<a3.and.a3<a4.and.a4<.2_dp,'storage: supply contrast survives hard-cap regime')
  call check(abs(NI_BUFFER_INFLOW(1.e-10_dp,1._dp,.8_dp)/1.e-10_dp-.2_dp)<1.e-10_dp, &
    'storage: low exposure approaches open fraction')
  call check(NI_BUFFER_INFLOW(.5_dp,1._dp,.9_dp)<a3,'storage: fullness reduces uptake at fixed supply')
  call check(abs(a4-(a3+NI_BUFFER_INFLOW(.5_dp,1._dp,.8_dp+a3)))<1.e-14_dp, &
    'storage: splitting supply without withdrawals preserves uptake')
  call NI_PSI_KERNEL(.7_dp,.4_dp,1._dp,1.25_dp,psi,psi_valid)
  call check(psi_valid.and.abs(psi+.5_dp)<1.e-14_dp,'psi: deficit uses minimum-critical span')
  call check(NI_ROOT_PSI_FACTOR(psi,psi_valid,1._dp)==1,'psi: full membrane capacity in deficit')
  call NI_PSI_KERNEL(1._dp,.4_dp,1._dp,1.25_dp,psi,psi_valid)
  call check(psi_valid.and.psi==0,'psi: critical inventory is zero')
  call check(NI_ROOT_PSI_FACTOR(psi,psi_valid,1._dp)==1,'psi: critical inventory is neutral')
  call NI_PSI_KERNEL(1.125_dp,.4_dp,1._dp,1.25_dp,psi,psi_valid)
  call check(psi_valid.and.psi==.5_dp,'psi: surplus uses critical-upper span')
  call check(abs(NI_ROOT_PSI_FACTOR(psi,psi_valid,1._dp)-exp(-.25_dp))<1.e-14_dp,'psi: smooth root downregulation')
  call NI_PSI_KERNEL(2._dp,.4_dp,1._dp,1.25_dp,psi,psi_valid)
  call check(psi_valid.and.psi==1,'psi: luxury state is bounded')
  call check(NI_ROOT_PSI_FACTOR(psi,psi_valid,1._dp)<exp(-.25_dp),'psi: stronger surplus lowers root capacity')
  call check(NI_ROOT_PSI_FACTOR(psi,psi_valid,0._dp)==1,'psi: zero beta means no downregulation')
  call NI_PSI_KERNEL(.1_dp,.4_dp,1._dp,1.25_dp,psi,psi_valid)
  call check(psi_valid.and.psi==-1,'psi: severe deficit is bounded')
  call NI_PSI_KERNEL(0._dp,0._dp,0._dp,0._dp,psi,psi_valid)
  call check(.not.psi_valid.and.psi==0,'psi: no standing shoot gives no state')
  call check(NI_ROOT_PSI_FACTOR(1._dp,psi_valid,1._dp)==1,'psi: unavailable state gives neutral capacity')
  call NI_ASSIM_KERNEL(1.1_dp,.1_dp,1._dp,1._dp,.14_dp,1.1_dp,.1_dp,1._dp,10._dp,2._dp,1._dp,1._dp,a3,a4)
  call check(abs(a3-.5_dp)<1.e-14_dp.and.abs(a4-.07_dp)<1.e-14_dp,'manual conversion fluxes')
  call check(abs(1.1_dp-a3-.6_dp)<1.e-14_dp.and.abs(.1_dp-a4-.03_dp)<1.e-14_dp,'manual species inventories')
  call NI_ASSIM_KERNEL(1._dp,1._dp,1._dp,1._dp,1._dp,1._dp,1._dp,1._dp,0._dp,2._dp,3._dp,1._dp,a3,a4)
  call check(a3==0.and.a4==0,'zero carbon blocks conversion')
  call NI_ASSIM_KERNEL(1._dp,1._dp,1._dp,1._dp,1._dp,1._dp,1._dp,1._dp,.2_dp,2._dp,3._dp,1._dp,a3,a4)
  call check(a3*3+a4<=.2_dp+1.e-14_dp,'shared carbon budget for both species')
  call NI_ROOT_KERNEL(72.8_dp,.3_dp,1000._dp,.01_dp,10._dp,0._dp,1._dp,1,u,cr)
  call check(abs(u-.2184_dp)<1.e-12_dp,'mass flow water and N units')
  call NI_ROOT_KERNEL(72.8_dp,0._dp,1000._dp,.01_dp,10._dp,.005_dp,1._dp,1,u,cr)
  call check(u==0,'R1 no transpiration no delivery')
  call NI_ROOT_KERNEL(72.8_dp,0._dp,1000._dp,.01_dp,10._dp,.005_dp,1._dp,2,u,cr)
  call check(u>0.and.cr>=0.and.cr<=72.8_dp,'R2 permits nontranspirational diffusion')
  call check(abs(u-.001_dp*.005_dp*1000*(72.8_dp-cr))<1.e-12_dp,'R2 supply equals membrane flux')
  call NI_ROOT_KERNEL(72.8_dp,0._dp,1000._dp,.01_dp,10._dp,0._dp,1._dp,2,u,cr)
  call check(u<1.e-14_dp,'no water and no diffusion gives no uptake')
  call NI_ROOT_KERNEL(72.8_dp,.3_dp,0._dp,.01_dp,10._dp,.005_dp,1._dp,2,u,cr)
  call check(u==0,'rootless layer')
  call NI_CURVE_KERNEL(.1_dp,.042_dp,.3_dp,.4_dp,1.25_dp,low,nc,high)
  call NI_CURVE_KERNEL(1._dp,.042_dp,.3_dp,.4_dp,1.25_dp,low2,nc2,high2)
  call check(nc==nc2.and.low==low2.and.high==high2,'sub-1-tonne plateau')
  call NI_CURVE_KERNEL(4._dp,.042_dp,.3_dp,.4_dp,1.25_dp,low2,nc2,high2)
  call check(low2<low.and.nc2<nc.and.high2<high,'all three references dilute')
  call check(low2<nc2.and.nc2<high2,'ordered soft references')
  c%CROP='TM';c%RUN=1;c%YRDOY=2026001
  s%ISWNIT='Y';s%ISWSYM='N';s%ISWWAT='Y';s%MEPHO='L';s%MEEVP='R'
  s%ISWDIS='N'
  call NI_LOAD(c,s);call NI_RESET()
  call check(NI_TOTAL_Q()==0,'seasonal initialization')
  w=[100.,100.,100.];n=[.01,.01,.01];loss=0;rw=1
  call NI_BEGIN(w)
  un3=0;un4=0;un3(1)=8.;un4(1)=.2
  call NI_ACCEPT_UPTAKE(un3,un4,1,tr3,tr4,trnu)
  q_before=NI_TOTAL_Q()
  call check(abs(q_before-.82)<1.e-6,'actual soil vectors enter Q once')
  pg=10
  call NI_ASSIMILATE(pg,.1,1.,.16,.16,nass,rsp3,rsp4)
  call check(nass>0.and.nass<=.1,'finite accepted provisional supply')
  unused=nass
  call NI_SETTLE(unused,rsp3,rsp4,nass,refund,un3,un4,1,tr3,tr4,actual_u)
  call check(abs(NI_TOTAL_Q()-q_before)<1.e-6.and.nass==0,'unused provisional substrate returned once')
  call NI_END(c,w,loss,rw,1,n,1.,0.)
  call check(all(n==.01),'actual organ N can be below soft minimum without projection')
  fp=NI_LEAF_FACTOR(0.,.005,.005)
  call check(fp>=0.and.fp<1,'deficient functional area-N reduces capacity')
  call check(NI_LEAF_FACTOR(100.,.005,.005)<=1.,'luxury functional N saturates')
  c%YRDOY=2026002;call NI_BEGIN(w)
  pg=0;call NI_ASSIMILATE(pg,1.,1.,.16,.16,nass,rsp3,rsp4)
  call check(nass==0.and.pg==0,'zero carbon with stored N remains bounded')
  w=[50.,100.,100.];loss=[50.,0.,0.]
  call NI_END(c,w,loss,rw,1,n,1.,0.)
  q_after=NI_TOTAL_Q()
  call check(abs(q_after-q_before*5/6)<1.e-6,'tissue loss removes proportional inorganic N')
  s3=0;s4=0;call NI_RETURN_LITTER(s3,s4,1)
  call check(abs(sum(s3+s4)-10*(q_before-q_after))<1.e-5,'species litter reaches soil in kg/ha')
  call NI_RETURN_LITTER(s3,s4,1)
  call check(abs(sum(s3+s4)-10*(q_before-q_after))<1.e-5,'pending litter cannot be returned twice')
  call NI_RESET();call check(NI_TOTAL_Q()==0.and.NI_SOIL_INPUT()==0,'second run reset')
  c%YRDOY=2026003;w=100.;loss=0.;call NI_BEGIN(w)
  un3=0;un4=0;un3(1)=8.;un4(1)=.2
  call NI_ACCEPT_UPTAKE(un3,un4,1,tr3,tr4,trnu)
  call NI_END(c,w,loss,rw,1,n,1.,0.)
  q_before=NI_TOTAL_Q();fp=NI_LEAF_FACTOR(3.,.005,.005)
  c%YRDOY=2026004;call NI_BEGIN(w);pg=10
  call NI_PREASSIM(pg,.5,1.,.16,.16,nold)
  un3=0;un4=0;un3(1)=100.;un4(1)=20.
  call NI_ACCEPT_UPTAKE(un3,un4,1,tr3,tr4,trnu)
  call NI_ASSIMILATE(pg,max(0.,.5-nold),1.,.16,.16,nass,rsp3,rsp4,.5)
  call NI_MERGE_OLD(nass,rsp3,rsp4)
  unused=nass
  call NI_SETTLE(unused,rsp3,rsp4,nass,refund,un3,un4,1,tr3,tr4,trnu)
  call check(trnu<=.1100001,'provisional old conversion cannot invent receiver room')
  call check(abs(NI_TOTAL_Q()-q_before-trnu)<1.e-6,'rolled-back uptake still closes mass')
  call check(nass==0,'rejected conversion never enters organic ledger')
  call NI_END(c,w,loss,rw,1,n,1.,0.)
  call check(abs(NI_LEAF_FACTOR(3.,.005,.005)-fp)<1.e-7,'inorganic luxury N alone cannot increase photosynthesis')
  write(*,'(A,I0)') 'NATIVE_N_CHECKS_PASSED=',checks
contains
  subroutine check(test,message)
    logical,intent(in)::test
    character(*),intent(in)::message
    if(.not.test) then
      write(*,'(A)') 'FAIL '//message
      error stop 1
    end if
    checks=checks+1
  end subroutine
end program
