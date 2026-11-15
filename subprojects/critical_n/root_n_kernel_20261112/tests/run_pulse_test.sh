#!/bin/bash
# run_pulse_test.sh — 编译并执行两日单脉冲审计 (需先完成引擎 build 以获得 .mod)
set -e
REPO=/d/Tomato_Cal_worktrees/dssat4864-rootn-T2-20261112
T=/d/Tomato_Cal/subprojects/critical_n/root_n_kernel_20261112
OUT=$T/runs/rnk_pulse_test
FC=$(grep '^CMAKE_Fortran_COMPILER:' $REPO/build/CMakeCache.txt | cut -d= -f2)
rm -rf $OUT && mkdir -p $OUT/mod $OUT/run
FLAGS='-ffree-line-length-none -fcheck=all -finit-real=snan -ffpe-trap=invalid,zero,overflow'
"$FC" $FLAGS -J$OUT/mod -I$REPO/build/mod -c $REPO/Plant/CROPGRO/RootNUptake.f90 -o $OUT/mod/RootNUptake.o
"$FC" $FLAGS -J$OUT/mod -I$REPO/build/mod -I$OUT/mod -c $REPO/Plant/CROPGRO/CG_Nitrogen.f90 -o $OUT/mod/CG_Nitrogen.o
"$FC" $FLAGS -I$REPO/build/mod -I$OUT/mod $T/tests/rnk_pulse_test.f90 $OUT/mod/CG_Nitrogen.o $OUT/mod/RootNUptake.o \
  -o $OUT/mod/rnk_pulse_test.exe -static -static-libgcc -static-libgfortran
cd $OUT/run
cat > NIntegration.nml <<'EOF'
&NINTEGRATION
 ni_stage=5, root_mode=2,
 q_no3_max=.003, q_nh4_max=.0001,
 assim_no3_v=.003, assim_nh4_v=.006, assim_no3_k=.001, assim_nh4_k=.00005,
 root_v=.0002, root_k=10., diffusion_k=.005, pool_beta=1.,
 leaf_a=.042, leaf_b=.30, stem_a=.025, stem_b=.35,
 min_ratio=.40, max_ratio=1.25, photo_floor=.05, photo_gamma=1., growth_tau=2.,
 state_timing=1, pods_n_state=1, budget_revision=1, c4_budget=1, leaf_coupling=1, c4_photo=1,
 remob_mode=1, luxury_priority=1, remob_tau=8., protect_beta=0.5, slow_ratio=3.
/
&ROOTNUPTAKE
 rnk_mode=1,
 rnk_km_high=0.28, 0.5,
 rnk_km_low=35.0, 50.0,
 rnk_vmax_high=0.0003, 0.0004,
 rnk_vmax_low=0.0015, 0.0020,
 rnk_kd=0.0, 1.0,
 rnk_residual=0.25, 0.50,
 rnk_nh4_diff=0.005
/
EOF
$OUT/mod/rnk_pulse_test.exe
