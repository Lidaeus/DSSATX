! Pulse the persistent inorganic store through uptake, assimilation and settlement.
program rnk_buffer_pulse
  use iso_fortran_env, only: dp=>real64
  use ModuleDefs, only: ControlType, SwitchType
  use CG_Nitrogen, only: NI_LOAD, NI_RESET, NI_BEGIN, NI_ORG_BEGIN, NI_ORG_END, NI_CAPTURE_WATER, &
    NI_ROOT_UPTAKE, NI_ACCEPT_UPTAKE, NI_ASSIMILATE, NI_SETTLE, NI_TOTAL_Q, NI_END, NI_ROOT_SOIL_DEBIT, NI_ROOT_SOIL_END
  implicit none
  type(ControlType) :: control
  type(SwitchType) :: switches
  real :: no3(1), uno3(1), unh4(1), previous3(1), previous4(1)
  real :: tr3, tr4, trnu, pg, nassim, rsp3, rsp4, refund, before_refund, q_before, q_after
  real :: organ(6), accum(6)
  real,parameter :: weights(3)=[100.,100.,100.], depth(1)=[20.]
  real :: weak_assim, weak_q, weak_organic, sufficient_assim, sufficient_q
  integer :: case, day
  control%CROP='TM'
  switches%ISWNIT='Y'; switches%ISWSYM='N'; switches%ISWWAT='Y'
  switches%MEPHO='L'; switches%MEEVP='R'; switches%ISWDIS='N'
  call NI_LOAD(control,switches)
  print '(a)', 'run,day,TRNO3U,NASSIMD,Q_end,organic_N,PGAVL,refund'
  do case=1,2
    control%RUN=case
    call NI_RESET()
    organ=[4.0,2.5,1.5,0.,0.,0.]
    accum=0; previous3=0; previous4=0
    do day=1,3
      control%YRDOY=2026000+day
      call NI_ROOT_SOIL_DEBIT(control,1,previous3,previous4)
      call NI_BEGIN(weights)
      call NI_ORG_BEGIN(organ,accum,0.,0.)
      no3=merge(25.,0.,day==1)
      call NI_CAPTURE_WATER(control,1,[0.2],[0.25],[1.0],depth)
      call NI_ROOT_UPTAKE(control,1,[1.3],depth,[.1],[.30],[.45],no3,[0.],[1./2.6],uno3,unh4)
      q_before=NI_TOTAL_Q()
      call NI_ACCEPT_UPTAKE(uno3,unh4,1,tr3,tr4,trnu)
      if(day>1.and.trnu/=0.) error stop 'cutoff must supply no new nitrogen'
      pg=merge(.03,100.,case==1.and.day==1)
      before_refund=pg
      call NI_ASSIMILATE(pg,100.,1.,.16,.16,nassim,rsp3,rsp4)
      call NI_SETTLE(0.25*nassim,rsp3,rsp4,nassim,refund,uno3,unh4,1,tr3,tr4,trnu)
      pg=pg+refund
      if(pg<0.or.abs((before_refund-pg)-(rsp3+rsp4))>4*epsilon(pg)*max(1.,before_refund)) error stop 'carbon debit or refund did not close'
      if(abs(nassim-(rsp3+rsp4))>1.e-6) error stop 'paid carbon differs from assimilated N at unit cost'
      q_after=NI_TOTAL_Q()
      if(abs(q_after-q_before-trnu+nassim)>1.e-6) error stop 'pulse inorganic budget failed'
      organ(1)=organ(1)+nassim
      call NI_ORG_END(organ,accum,0.,0.,0.)
      call NI_END(control,weights,[0.,0.,0.],[1.],1,organ(1:3),1.,0.)
      previous3=uno3; previous4=unh4
      print '(i0,",",i0,6(",",es18.9))',case,day,tr3,nassim,NI_TOTAL_Q(),sum(organ),pg,refund
      if(case==1.and.day==1) then
        weak_q=NI_TOTAL_Q()
        weak_assim=nassim/trnu
        weak_organic=sum(organ)
      end if
      if(case==1.and.day==2) then
        if(NI_TOTAL_Q()>=weak_q.or.sum(organ)<weak_organic) error stop 'nitrogen cutoff did not draw down the buffer'
      end if
      if(case==2.and.day==1) then
        sufficient_q=NI_TOTAL_Q()
        sufficient_assim=nassim/trnu
      end if
    end do
    call NI_ROOT_SOIL_END(control,1)
  end do
  if(weak_q<=sufficient_q.or.weak_assim>=sufficient_assim) error stop 'weak light pulse failed'
end program
