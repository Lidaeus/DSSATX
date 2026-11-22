! Read-only P0b tracing. No physiological state, parameter, or flux is modified.
! Explicit opt-in: DSSAT_P0_TRACE=1. Output is private to the current run cwd.
module CG_P0Trace
  use iso_fortran_env, only: real64, int64
  use ModuleDefs, only: ControlType
  implicit none
  private
  public :: P0_ENABLED, P0_CONTEXT, P0_V, P0_L, P0_TEXT, P0_LEAF, P0_LOCAL
  logical, save :: checked = .false., enabled = .false., opened = .false.
  integer, save :: log_unit
  integer(int64), save :: sequence = 0_int64
  type(ControlType), save :: context
  logical, save :: has_context = .false.
contains
  logical function P0_ENABLED()
    character(32) :: flag
    integer :: status, length
    if (.not. checked) then
      call get_environment_variable('DSSAT_P0_TRACE', flag, length, status)
      if (status == 1 .or. length == 0) then
        enabled = .false.
      else if (status /= 0) then
        error stop 'P0 trace: cannot read DSSAT_P0_TRACE'
      else
        select case (trim(flag))
        case ('0')
          enabled = .false.
        case ('1')
          enabled = .true.
        case default
          error stop 'P0 trace: DSSAT_P0_TRACE must be 0 or 1'
        end select
      end if
      checked = .true.
    end if
    P0_ENABLED = enabled
  end function

  subroutine P0_CONTEXT(control)
    type(ControlType), intent(in) :: control
    if (.not. P0_ENABLED()) return
    context = control
    has_context = .true.
  end subroutine

  subroutine emit(control, event, key, value, layer, text)
    type(ControlType), intent(in) :: control
    character(*), intent(in) :: event, key, text
    real(real64), intent(in) :: value
    integer, intent(in) :: layer
    integer :: ios
    if (.not. P0_ENABLED()) return
    if (.not. opened) then
      open(newunit=log_unit, file='P0Trace.csv', status='replace', &
           action='write', iostat=ios)
      if (ios /= 0) error stop 'P0 trace: cannot open trace output'
      write(log_unit,'(A)') &
        'seq,run,yrdoy,das,dynamic,event,layer,key,value,text'
      opened = .true.
    end if
    sequence = sequence + 1_int64
    write(log_unit,'(I0,4(",",I0),",",A,",",I0,",",A,",",ES25.16E3,",",A)') &
      sequence, control%RUN, control%YRDOY, control%DAS, &
      control%DYNAMIC, trim(event), layer, trim(key), value, trim(text)
  end subroutine

  subroutine P0_V(control, event, names, values)
    type(ControlType), intent(in) :: control
    character(*), intent(in) :: event, names
    real, intent(in) :: values(:)
    integer :: i, start, comma, finish
    if (.not. P0_ENABLED()) return
    start = 1
    do i = 1, size(values)
      comma = index(names(start:), ',')
      if (comma == 0) then
        finish = len_trim(names)
      else
        finish = start + comma - 2
      end if
      if (finish < start) error stop 'P0 trace: empty variable name'
      call emit(control, event, names(start:finish), &
                real(values(i),real64), 0, '')
      if (comma == 0) exit
      start = finish + 2
    end do
    if (i /= size(values) .or. comma /= 0) &
      error stop 'P0 trace: variable name/value count mismatch'
  end subroutine

  subroutine P0_L(control, event, key, values, nlayr)
    type(ControlType), intent(in) :: control
    character(*), intent(in) :: event, key
    real, intent(in) :: values(:)
    integer, intent(in) :: nlayr
    integer :: layer
    if (.not. P0_ENABLED()) return
    do layer = 1, nlayr
      call emit(control, event, key, real(values(layer),real64), layer, '')
    end do
  end subroutine

  subroutine P0_TEXT(control, event, key, text)
    type(ControlType), intent(in) :: control
    character(*), intent(in) :: event, key, text
    call emit(control, event, key, 0.0_real64, 0, text)
  end subroutine

  subroutine P0_LEAF(rnitp, slw, slwref, lnref, agemxl, ageqe, &
                     lfmax, qeff)
    real, intent(in) :: rnitp, slw, slwref, lnref, agemxl, ageqe, lfmax, qeff
    if (.not. P0_ENABLED()) return
    if (.not. has_context) error stop 'P0 trace: no SPAM call context'
    call P0_V(context, 'leaf_capacity', &
      'RNITP,SLW,SLWREF,LNREF,AGEMXL,AGEQE,LFMAX,QEFF', &
      [rnitp,slw,slwref,lnref,agemxl,ageqe,lfmax,qeff])
  end subroutine

  subroutine P0_LOCAL(event, names, values)
    character(*), intent(in) :: event, names
    real, intent(in) :: values(:)
    if (.not. P0_ENABLED()) return
    if (.not. has_context) error stop 'P0 trace: no call context'
    call P0_V(context,event,names,values)
  end subroutine
end module CG_P0Trace
