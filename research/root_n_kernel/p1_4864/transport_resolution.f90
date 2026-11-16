! Fixed-parameter engineering probes for the two transport formulations.
program transport_resolution
   use, intrinsic :: ieee_arithmetic, only: ieee_is_finite
   use RootNUptake
   implicit none

   integer, parameter :: grids(*) = [8, 16, 32], steps(*) = [24, 48, 96]
   type(rnk_params) :: params, zero_diffusion
   type(rnk_layer) :: layer, dry, rewet, normal
   type(rnk_diag) :: result(2)
   integer :: grid, step, output, method

   params%km_high = [0.28_rnk_dp, 0.5_rnk_dp]
   params%km_low = [35._rnk_dp, 50._rnk_dp]
   params%vmax_high = [0.0003_rnk_dp, 0.0004_rnk_dp]
   params%vmax_low = [0.0015_rnk_dp, 0.0020_rnk_dp]
   params%kd_sorption = [0._rnk_dp, 1._rnk_dp]

   normal%bd = 1.3_rnk_dp
   normal%dlayr = 20._rnk_dp
   normal%kg2ppm = 10._rnk_dp/(normal%bd*normal%dlayr)
   normal%p = 10._rnk_dp*normal%kg2ppm
   normal%porosity = 0.45_rnk_dp
   normal%rlv = 1._rnk_dp
   normal%theta0 = 0.255_rnk_dp
   normal%rwu = 0.20_rnk_dp

   open(newunit=output, file='transport_resolution.csv', status='new')
   write(output,'(a)') 'scenario,cells,nominal_substeps,species,candidate_gN_m2,mass_error_gN_m2,retries'
   do grid = 1, size(grids)
      do step = 1, size(steps)
         call run_case('normal', normal)
         dry = normal
         dry%theta0 = 0.09_rnk_dp
         dry%rwu = 0._rnk_dp
         call run_case('dry', dry)
         dry%theta0 = 0.025_rnk_dp
         call run_case('extreme_dry', dry)
         ! Match the engine's daily homogenization. Rewetting adds only water.
         rewet = normal
         rewet%p = dry%p - result%candidate*10._rnk_dp*dry%kg2ppm
         rewet%theta0 = 0.30_rnk_dp
         call run_case('rewet', rewet)
      end do
   end do
   close(output)

   ! One soil layer contrast. Approximate the 26SP 80–100 cm layer's
   ! density and SAT, and hold the other synthetic inputs fixed.
   layer = normal
   layer%bd = 1.47_rnk_dp
   layer%kg2ppm = 10._rnk_dp/(layer%bd*layer%dlayr)
   layer%p = 10._rnk_dp*layer%kg2ppm
   layer%theta0 = 0.29_rnk_dp
   open(newunit=output, file='transport_porosity.csv', status='new')
   write(output,'(a)') 'porosity_basis,method,species,porosity,d_bulk_m2_d,candidate_gN_m2'
   do method = 1, 2
      layer%porosity = 0.498_rnk_dp
      call compare_porosity('SAT')
      layer%porosity = 1._rnk_dp - layer%bd/2.65_rnk_dp
      call compare_porosity('POROS')
   end do
   close(output)

   zero_diffusion = params
   zero_diffusion%species_diffusion_m2d = 0._rnk_dp
   call rnk_layer_A(zero_diffusion, normal, result)
   if (.not. all(result%zero_diffusion) .or. any(result%steady_residual /= -99._rnk_dp)) &
      error stop 'Steady zero-diffusion diagnostics failed'
   call rnk_layer_B(zero_diffusion, normal, result)
   if (.not. all(result%zero_diffusion)) error stop 'Transient zero-diffusion diagnostics failed'

contains

   subroutine run_case(name, inputs)
      character(len=*), intent(in) :: name
      type(rnk_layer), intent(in) :: inputs
      integer :: species
      real(rnk_dp) :: capacity, remaining, expected_end

      call rnk_layer_B(params, inputs, result, n_cells=grids(grid), n_substeps=steps(step))
      do species = 1, 2
         associate(d => result(species))
            if (d%solver_flag /= 0 .or. .not. ieee_is_finite(d%candidate) .or. &
                abs(d%mass_error) > 1.e-9_rnk_dp .or. min(d%candidate, d%stock_cap - d%candidate) < -1.e-12_rnk_dp) &
               error stop 'Transient solution failed the resolution audit'
            capacity = inputs%theta0 - inputs%rwu/inputs%dlayr + inputs%bd*params%kd_sorption(species)
            remaining = inputs%p(species)/(10._rnk_dp*inputs%kg2ppm) - d%candidate
            expected_end = remaining/((inputs%dlayr/100._rnk_dp)*capacity)
            if (min(d%c_bulk_end, d%c_bulk_mean, d%c_root_mean) < -1.e-12_rnk_dp .or. &
                abs(d%c_bulk_end - expected_end) > 1.e-8_rnk_dp .or. &
                abs(d%hats_candidate + d%lats_candidate - d%candidate) > 1.e-12_rnk_dp) &
               error stop 'Transient concentration or membrane diagnostics failed'
            write(output,'(a,3(",",i0),2(",",es24.15e3),",",i0)') &
               name, grids(grid), steps(step), species, d%candidate, d%mass_error, d%n_retries
         end associate
      end do
   end subroutine run_case

   subroutine compare_porosity(label)
      character(len=*), intent(in) :: label
      integer :: species

      if (method == 1) then
         call rnk_layer_A(params, layer, result)
         if (maxval(abs(result%steady_residual)) > 1.e-8_rnk_dp) error stop 'Steady transport residual failed'
      else
         call rnk_layer_B(params, layer, result, n_cells=32, n_substeps=96)
         if (any(result%solver_flag /= 0)) error stop 'Transient porosity probe failed'
      end if
      do species = 1, 2
         write(output,'(a,2(",",i0),3(",",es24.15e3))') label, method, species, &
            layer%porosity, result(species)%bulk_diffusion, result(species)%candidate
      end do
   end subroutine compare_porosity

end program transport_resolution
