! Controlled module lifecycle, not a whole-crop or measured-data experiment.
program native_reserve_lifecycle
  use iso_fortran_env,only:real64
  use ModuleDefs,only:ControlType,SwitchType,NL
  use CG_Nitrogen
  implicit none
  type(ControlType)::c
  type(SwitchType)::s
  real::w(3),n(3),off(6),rw(NL),un3(NL),un4(NL),tr3,tr4,trnu,pg,na,rsp3,rsp4,refund
  real::dm(3),nn(3),cr(3),nad(3),cad(2),pcl,pcs,flux(4),nmine,returned,mobrefund,loss(3),f_before,f_after,available,planned
  integer::day,checks=0
  c%CROP='TM';c%RUN=1;c%YRDOY=2026001
  s%ISWNIT='Y';s%ISWSYM='N';s%ISWDIS='N';s%ISWWAT='Y';s%MEPHO='L';s%MEEVP='R'
  call NI_LOAD(c,s);call NI_RESET()
  call check(NI_RESERVES().and..not.NI_COMMON(),'isolated reserve lifecycle mode')
  w=[100.,100.,50.];n=[4.8,2.6,1.];off=0;rw=0;rw(1)=1
  dm=0;nn=0;cr=0
  do day=1,11
    c%YRDOY=2026000+day
    call NI_BEGIN(w)
    call NI_ORG_BEGIN([n,0.,0.,0.],off,0.,0.)
    call NI_DONORS([0.,0.,0.],[0.,0.,0.])
    call NI_TARGETS(w(1),w(2),pcl,pcs)
    loss=0
    if(day==10)loss=[.2*w(1),.1*w(2),0.]
    call NI_C4_SEN_PLAN(loss(1:2),1.)
    un3=0;un4=0
    if(day<=8)un3(1)=2.
    call NI_ACCEPT_UPTAKE(un3,un4,1,tr3,tr4,trnu)
    pg=100
    ! Force external organic supply to zero here to test buffer use, while
    ! retaining the actual finite late-assimilation interface for filling.
    call NI_ASSIMILATE(pg,0.,1.,2.,.6,na,rsp3,rsp4)
    nad=0;nmine=0;flux=0;available=0
    if(day<=8)then
      cad=10
      call NI_LUXURY(pg,dm,nn,cr,1.2,0.,cad,nad,available,na,rsp3,rsp4)
      n=n+nad;w=w+nad/.16
    elseif(day==9.or.day==11)then
      f_before=NI_P2_RNITP(n(1),w(1),100*n(1)/w(1))*w(1)/100
      call NI_REMOB_PLAN(.3,0.,pg,100.,[n,0.],[w,0.],[0.,0.,0.,0.],1.,1.,nmine,flux)
      call check(nmine>0,'stored organic reserve can actually enter a donor reservation')
      planned=nmine
      if(day==9)then
        call NI_REMOB_SETTLE(0.,planned,1.,nmine,flux,returned,mobrefund)
        n=n-flux(1:3);w=w-flux(1:3)/.16
        n(3)=n(3)+nmine;w(3)=w(3)+nmine/.16
      else
        call NI_REMOB_SETTLE(planned,0.,1.,nmine,flux,returned,mobrefund)
        call check(nmine==0.and.returned>0,'unaccepted release is cancelled before stock commit')
      endif
    endif
    if(day==10)then
      n(1:2)=n(1:2)*(1-[.2,.1]);w(1:2)=w(1:2)*(1-[.2,.1])
    endif
    call NI_SETTLE(0.,rsp3,rsp4,na,refund,un3,un4,1,tr3,tr4,trnu)
    call NI_P2_COMMIT_RESERVES(n(1:2),w(1:2))
    if(day==9)then
      f_after=NI_P2_RNITP(n(1),w(1),100*n(1)/w(1))*w(1)/100
      call check(abs(f_after-f_before)<1.e-6,'fast reserve release leaves nonreserve leaf N intact')
    endif
    call NI_END(c,w,loss,rw,1,n,1.,0.)
  enddo
  call NI_RESET()
  call check(abs(NI_P2_RNITP(4.8,100.,4.8)-4.8)<1.e-6,'new treatment resets reserve stock')
  write(*,'(A,I0)')'NATIVE_RESERVE_LIFECYCLE_CHECKS_PASSED=',checks
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
