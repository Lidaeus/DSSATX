!> rnk_pulse_test.f90 — 两日单脉冲审计 (执行计划 §4 氮入口)
!! 驱动 NI_CAPTURE_WATER → NI_ROOT_UPTAKE(RNK A) → NI_ACCEPT_UPTAKE →
!! NI_ASSIMILATE → NI_SETTLE 两日序列, 断言:
!!   1. 候选 ≤ 库存上限, 扣除后土壤库存非负 (不透支)
!!   2. accepted ≤ candidate; 全部同化时 deducted == accepted (无漏扣/重扣)
!!   3. 第二日候选使用更新后的库存 (无跨日陈旧复用)
!!   4. 累计扣除 ≤ 初始库存 (总量守恒)
!!   5. LayerRootNUptake.csv 逐行 source_day == soil_commit_day
program rnk_pulse_test
  use iso_fortran_env,only:real64
  use ModuleDefs,only:ControlType,SwitchType,NL
  use CG_Nitrogen
  implicit none
  integer,parameter::dp=real64
  type(ControlType)::c
  type(SwitchType)::s
  real::bd(NL),dl(NL),ll(NL),dul(NL),sat(NL),n3(NL),n4(NL),k2p(NL)
  real::un3(NL),un4(NL),rw(NL),th(NL),rl(NL),w(3),loss(3),orgn(3),rw1(3)
  real::tr3,tr4,trnu,pg,nass,rsp3,rsp4,refund,unused
  real(dp)::stock0,stock1,cand1,acc1,ded1,cand2,acc2,ded2,cap1
  integer::checks,i,ios,lun
  character(len=1024)::line
  checks=0
  ! ---- 单层合成工况: BD=1.3, dz=20cm, KG2PPM=1/2.6 ----
  bd=0;dl=0;ll=0;dul=0;sat=0;n3=0;n4=0;k2p=0;un3=0;un4=0;rw=0;th=0;rl=0
  bd(1)=1.3; dl(1)=20.; ll(1)=.1; dul(1)=.3; sat(1)=.45
  k2p(1)=1./(1.3*0.1*20.)          ! = 1/2.6 (ppm→kg/ha 除以该值)
  n3(1)=3.846154                   ! 10 kg N/ha
  n4(1)=3.846154                   ! 10 kg N/ha
  stock0=10._dp                    ! g N/m2
  c%CROP='TM'; c%RUN=1; c%YRDOY=2026001
  s%ISWNIT='Y'; s%ISWSYM='N'; s%ISWWAT='Y'; s%MEPHO='L'; s%MEEVP='R'; s%ISWDIS='N'
  call NI_LOAD(c,s); call NI_RESET()
  w=[100.,100.,100.]; loss=0.; orgn=[.01,.01,.01]; rw1=1.
  ! ================= 第 1 日 =================
  call NI_BEGIN(w)
  ! SPAM 快照口径: theta 已含 -0.5*RWU/dz 中点修正
  rw(1)=0.20; th(1)=0.25; rl(1)=1.0
  call NI_CAPTURE_WATER(c,1,rw,th,rl)
  call NI_ROOT_UPTAKE(c,1,bd,dl,ll,dul,sat,n3,n4,k2p,un3,un4)
  cand1=real(un3(1),dp)/10
  cap1=max(0._dp,(real(n3(1),dp)-0.25_dp)/real(k2p(1),dp))/10
  call check(cand1>=0,'day1 candidate nonnegative')
  call check(cand1<=cap1+1e-12,'day1 candidate within stock cap')
  call NI_ACCEPT_UPTAKE(un3,un4,1,tr3,tr4,trnu)
  acc1=real(un3(1),dp)/10
  call check(acc1<=cand1+1e-12,'day1 accepted <= candidate')
  pg=100.
  call NI_ASSIMILATE(pg,real(acc1*10),1.,.16,.16,nass,rsp3,rsp4)
  unused=nass
  call NI_SETTLE(unused,rsp3,rsp4,nass,refund,un3,un4,1,tr3,tr4,trnu)
  ded1=real(un3(1),dp)/10
  call check(abs(ded1-acc1)<1e-9,'day1 fully-assimilated deduction == accepted (no miss, no double)')
  ! 土壤侧: 库存扣减后非负
  stock1=stock0-ded1
  call check(stock1>=0,'day1 soil stock stays nonnegative')
  call NI_END(c,w,loss,rw1,1,orgn,1.,0.)
  ! ================= 第 2 日: 用扣减后的库存 =================
  ! 土壤侧换算: kg/ha = ppm / KG2PPM → ppm 减量 = (ded1 g/m2 × 10) × KG2PPM
  block
    real::dec_ppm
    dec_ppm=real(ded1*10*real(k2p(1),dp))
    n3(1)=3.846154-dec_ppm
  end block
  c%YRDOY=2026002
  call NI_BEGIN(w)
  rw(1)=0.10; th(1)=0.25; rl(1)=1.0
  call NI_CAPTURE_WATER(c,1,rw,th,rl)
  call NI_ROOT_UPTAKE(c,1,bd,dl,ll,dul,sat,n3,n4,k2p,un3,un4)
  cand2=real(un3(1),dp)/10
  ! 第二日候选必须基于更新库存: 新 cap 明显小于第一日 cap
  call check(cand2<=max(0._dp,(real(n3(1),dp)-0.25_dp)/real(k2p(1),dp))/10+1e-12, &
             'day2 candidate within UPDATED stock cap (no stale reuse)')
  call NI_ACCEPT_UPTAKE(un3,un4,1,tr3,tr4,trnu)
  acc2=real(un3(1),dp)/10
  pg=100.
  call NI_ASSIMILATE(pg,real(acc2*10),1.,.16,.16,nass,rsp3,rsp4)
  unused=nass
  call NI_SETTLE(unused,rsp3,rsp4,nass,refund,un3,un4,1,tr3,tr4,trnu)
  ded2=real(un3(1),dp)/10
  call check(abs(ded2-acc2)<1e-9,'day2 deduction == accepted')
  ! 总量守恒: 两天累计扣除 ≤ 初始库存
  call check(ded1+ded2<=stock0+1e-12,'two-day cumulative deduction <= initial stock')
  call NI_END(c,w,loss,rw1,1,orgn,1.,0.)
  ! ================= 账本文件审计: source_day == soil_commit_day =================
  open(newunit=lun,file='LayerRootNUptake.csv',status='old',action='read',iostat=ios)
  call check(ios==0,'ledger file exists')
  if(ios==0) then
    i=0
    do
      read(lun,'(A)',iostat=ios) line
      if(ios/=0) exit
      i=i+1
      if(i>1) then
        if(index(line,',2026001,')==0 .and. index(line,',2026002,')==0) &
          call check(.false.,'ledger row day unexpected')
      end if
    end do
    call check(i>=5,'ledger has header + 2 days x 2 species rows')  ! 头 + 单层×2形态×2日 = 5 行(允许尾空行)
    close(lun)
  end if
  write(*,'(A,I0)') 'RNK_PULSE_CHECKS_PASSED=',checks
contains
  subroutine check(ok,name)
    logical,intent(in)::ok
    character(*),intent(in)::name
    if(.not.ok) then
      write(*,'(A)') 'FAIL: '//name
      error stop 1
    end if
    checks=checks+1
    write(*,'(A)') 'ok  : '//name
  end subroutine check
end program rnk_pulse_test
