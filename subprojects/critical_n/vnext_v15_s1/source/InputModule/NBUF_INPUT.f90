! Opt-in preservation of fractional N application through both gray files.
! No dependence on yesterday's NBUF_ACT: input runs before crop initialization.
module NBUF_INPUT
  use, intrinsic :: ieee_arithmetic,only:ieee_is_finite
  implicit none
  private
  public :: nb_precision_enabled,nb_fertilizer_field
contains
  logical function nb_precision_enabled(crop) result(enabled)
    character(*),intent(in) :: crop
    character(512) :: line
    integer :: u,ios
    real :: enable
    logical :: exists
    enabled=.false.
    if(crop/='TM')return
    inquire(file='TMGRO048.SPE',exist=exists)
    if(.not.exists)return
    open(newunit=u,file='TMGRO048.SPE',status='old',action='read',iostat=ios)
    if(ios/=0)return
    do
      read(u,'(A)',iostat=ios)line
      if(ios/=0)exit
      if(trim(line)/='!*ORGAN NITROGEN RESERVES AND BUFFER DILUTION')cycle
      do
        read(u,'(A)',iostat=ios)line
        if(ios/=0)exit
        if(len_trim(line)==0)cycle
        if(line(1:1)=='!'.or.line(1:1)=='@')cycle
        read(line,'(F6.0)',iostat=ios)enable
        if(ios==0)enabled=ieee_is_finite(enable).and.enable==1.
        exit
      enddo
      exit
    enddo
    close(u)
  end function

  function nb_fertilizer_field(amount) result(field)
    real,intent(in) :: amount
    character(5) :: field
    if(abs(amount)<10.)then
      write(field,'(F5.3)')amount
    else if(abs(amount)<100.)then
      write(field,'(F5.2)')amount
    else if(abs(amount)<1000.)then
      write(field,'(F5.1)')amount
    else
      write(field,'(F5.0)')amount
    endif
  end function
end module
