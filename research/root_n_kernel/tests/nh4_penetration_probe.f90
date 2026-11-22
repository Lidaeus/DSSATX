! The first root density and Kd combination reproduces the original engineering probe.
! Other root densities and sorption strengths test transfer across layers.
program penetration
  use RootNUptake
  use HistoricalRootNUptake, only: old_params=>rnk_params,old_layer=>rnk_layer,old_diag=>rnk_diag,rnk_layer_B
  implicit none
  type(rnk_params) :: a
  type(rnk_layer) :: layer
  type(rnk_diag) :: da(2)
  real(rnk_dp) :: original_no3
  type(old_params) :: b
  type(old_layer) :: old
  type(old_diag) :: db(2)
  real(rnk_dp),parameter :: coefficients(*)=[0._rnk_dp,.25_rnk_dp,.5_rnk_dp,1._rnk_dp,1.5_rnk_dp,2._rnk_dp, &
                                             3._rnk_dp,4._rnk_dp,8._rnk_dp,16._rnk_dp]
  real(rnk_dp),parameter :: water(*)=[.255_rnk_dp,.09_rnk_dp,.025_rnk_dp,.30_rnk_dp]
  real(rnk_dp),parameter :: roots(*)=[1._rnk_dp,.15_rnk_dp,3._rnk_dp], kd(*)=[1._rnk_dp,3._rnk_dp,.5_rnk_dp]
  integer :: i,j,k,n,s
  a%km_high=[.28_rnk_dp,.5_rnk_dp]; a%km_low=[35._rnk_dp,50._rnk_dp]
  a%vmax_high=[.0003_rnk_dp,.0004_rnk_dp]; a%vmax_low=[.0015_rnk_dp,.002_rnk_dp]
  b%km_high=a%km_high; b%km_low=a%km_low; b%vmax_high=a%vmax_high; b%vmax_low=a%vmax_low
  layer%bd=1.3_rnk_dp; layer%dlayr=20; layer%kg2ppm=10/(layer%bd*layer%dlayr)
  layer%porosity=.45_rnk_dp
  old%bd=layer%bd; old%dlayr=layer%dlayr; old%kg2ppm=layer%kg2ppm; old%porosity=layer%porosity
  print '(a)', 'moisture,rlv_case,kd_case,species,coefficient,A,B'
  do j=1,size(roots)
    layer%rlv=roots(j); old%rlv=layer%rlv
    do k=1,size(kd)
      a%kd_sorption(2)=kd(k); b%kd_sorption=a%kd_sorption
      do i=1,size(water)
        layer%theta0=water(i); layer%rwu=0
        layer%p=10*layer%kg2ppm
        if(i==1.or.i==4) layer%rwu=.2_rnk_dp
        if(i==4) layer%p=layer%p - db%candidate*10*layer%kg2ppm
        old%p=layer%p; old%theta0=layer%theta0; old%rwu=layer%rwu
        call rnk_layer_B(b,old,db,n_cells=32,n_substeps=96)
        if(any(db%solver_flag/=0).or.any(abs(db%mass_error)>1.e-9_rnk_dp)) error stop 'B32x96 audit failed'
        do n=1,size(coefficients)
          a%penetration_coeff=coefficients(n)
          call rnk_layer_A(a,layer,da)
          if (n==1) original_no3=da(RNK_NO3)%candidate
          if (da(RNK_NO3)%candidate/=original_no3) error stop 'NH4 correction altered NO3 candidate'
          if (any(da%candidate<0).or.any(da%c_root>da%c_bulk).or.any(da%diffusive_flux<0)) &
            error stop 'Steady concentration or flux outside physical bounds'
          do s=1,2
            print '(4(i0,","),f6.2,2(",",es24.15))', i,j,k,s,coefficients(n),da(s)%candidate,db(s)%candidate
          end do
        end do
      end do
    end do
  end do
end program
