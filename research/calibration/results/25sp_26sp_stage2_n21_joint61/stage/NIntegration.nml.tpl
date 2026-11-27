ptf ~
! 26SP B4 research template for tomato/eggplant (TM, MEPHO=L).
! Persistent inorganic N, shared steady RNK, limited protected remobilization,
! fixed functional SLN, coupled senescence, and single C/N leaf acceptance.
! 26SP working SLN band: 0.95-1.25 g N/m2 leaf.
! Keep the 1.05 anchor fixed in cultivar IES. 0.18 is a historical control.
! Reassess the anchor with leaf photosynthesis data for a different species.
! Senescence rate is a provisional daily maximum before stress scaling.
! lux_veg_mode: 0 is off by default. Mode 1 uses lux_xfrt_drop for reproductive C.
! lux_psi_threshold optionally delays onset.
&NINTEGRATION
 org_reserve_cap=0.,0., refill_tau=0., refill_substrate_target=1,
 refill_substrate_km=           0.05068119707858373,
 ni_stage=5, root_mode=2,
 q_no3_max=             ~ q_no3_max                 ~, q_nh4_max=  ~ q_nh4_max                 ~,
 assim_no3_v=             ~ assim_no3_v               ~, assim_nh4_v=  ~ assim_nh4_v               ~, assim_no3_k=                         ~ assim_no3_k               ~, assim_nh4_k= ~ assim_nh4_k               ~,
 pool_beta=                              ~ pool_beta                 ~,
 leaf_a=              ~ leaf_a                    ~, leaf_b=                 ~ leaf_b                    ~, stem_a=    ~ stem_a                    ~, stem_b=    ~ stem_b                    ~,
 min_ratio=    ~ min_ratio                 ~, max_ratio=                 ~ max_ratio                 ~, photo_floor=.05, photo_gamma=1., growth_tau=     ~ growth_tau                ~,
 state_timing=1, pods_n_state=1, budget_revision=1, c4_budget=1, leaf_coupling=1, c4_photo=1,
 remob_mode=1, luxury_priority=0, remob_tau=8., protect_beta=     ~ protect_beta              ~, slow_ratio=3.,
 remob_rate_mode=1, remob_rate_max=   ~ remob_rate_max            ~, functional_rate_max=   ~ functional_rate_max       ~,
 photo_reference_mode=1, photo_sln_ref=1.05,
 n_sen_rate=   ~ n_sen_rate                ~, lai_cn_mode=1, lai_cn_shape=      ~ lai_cn_shape              ~,
 common_acceptance=0, reserve_mode=0
/
! Shared steady root transport parameters.
! rnk_mode: 0=off, 1=steady equivalent transport.
! Vmax units: g N/(m root day). Km: mg N/L. Kd: L/kg. Residual: mg N/kg dry soil.
! Optional sorbing NH4 penetration: positive coefficient enables it, 0 uses the full cylinder.
! Species order: NO3, NH4. Optional rnk_vmax_scale defaults to 1 for both species.
&rootnuptake
 rnk_vmax_scale=                               ~ rnk_vmax_scale            ~,
 rnk_mode=1,
 rnk_source_tag="v15-engineering","literature-prior",
 rnk_km_high=0.28,0.5, rnk_km_low=              88.6517925516109,115.,
 rnk_vmax_high=        0.00017083338811394908,0.00018, rnk_vmax_low=0.0015,0.002,
 rnk_kd=0.,1., rnk_residual=0.25,0.5,
 rnk_penetration_coeff=0.,
 rnk_radius=0.0001, rnk_species_diffusion=0.000164,0.000150
/
