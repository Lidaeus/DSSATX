"""Audit actual P0b native transactions. No fitted or synthetic physiological targets.

Exports raw-derived ledgers and distinguishes native bookkeeping defects from
instrumentation failures. All arithmetic below is independent float64 analysis
of float32 values recorded by the executable.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import numpy as np
import pandas as pd
from prepare_readiness import digest

EPS32 = np.finfo(np.float32).eps
ORG = ['WTNLF','WTNST','WTNRT','WTNSH','WTNSD','WTNNOD']
OFF = ['WTNLO','WTNSO','WTNRO','WTNSHO','WTNSDO','WTNNO']


def tomorrow(code):
    return int((datetime.strptime(str(int(code)), '%Y%j') + timedelta(days=1)).strftime('%Y%j'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--analysis-name',default='analysis')
    args = parser.parse_args()
    root = args.run.resolve()
    out = root/args.analysis_name
    out.mkdir(exist_ok=False)
    trace = root/'trace_on/P0Trace.csv'
    d = pd.read_csv(trace,dtype={'event':'category','key':'category','text':'category'},float_precision='round_trip')
    if not np.isfinite(d.value).all():
        raise ValueError('Non-finite trace values')
    assert d.seq.is_unique and (np.diff(d.seq)==1).all()

    def layer(event, dynamic=None):
        q = d[(d.event==event)&(d.layer>0)]
        if dynamic is not None:
            q = q[q.dynamic==dynamic]
        result=q.pivot(index=['run','yrdoy','layer'],columns='key',values='value').dropna(axis=1,how='all')
        result.columns=[str(x) for x in result.columns]
        return result

    def scalar(event, dynamic=None):
        q=d[(d.event==event)&(d.layer==0)&(d.text.isna())]
        if dynamic is not None:
            q=q[q.dynamic==dynamic]
        result=q.pivot(index=['run','yrdoy'],columns='key',values='value').dropna(axis=1,how='all')
        result.columns=[str(x) for x in result.columns]
        return result

    cg_u=layer('cg_uptake')
    before=layer('soil_debit_before')
    after=layer('soil_debit_after')
    ui=cg_u[['UNO3','UNH4']].reset_index()
    ui['origin_day']=ui.yrdoy
    ui['yrdoy']=ui.yrdoy.map(tomorrow)
    ui=ui.set_index(['run','yrdoy','layer']).rename(columns={'UNO3':'expected_NO3','UNH4':'expected_NH4'})
    lag=before[['UNO3','UNH4','SNO3','SNH4']].join(ui,how='left')
    lag[['expected_NO3','expected_NH4']]=lag[['expected_NO3','expected_NH4']].fillna(0)
    lag['NO3_payload_error_kg_ha']=lag.UNO3-lag.expected_NO3
    lag['NH4_payload_error_kg_ha']=lag.UNH4-lag.expected_NH4
    # Exact reproduction of the native single precision subtraction.
    for stock,uptake in [('SNO3','UNO3'),('SNH4','UNH4')]:
        predicted=(before[stock].astype(np.float32)-before[uptake].astype(np.float32)).astype(np.float64)
        lag[f'{stock}_native_subtraction_error']=after[stock]-predicted
    lag.to_csv(out/'layer_debit_ledger.csv',index=True)

    spam=layer('spam_rate')
    cache=layer('cg_cache')
    rate=layer('cg_rate')
    water=spam[['RWU','SW','SWDELTX','DLAYR','RLV','SW_AVAIL','LL','SWDELTS','SWDELTU']].copy()
    water['cached_RWU']=cache.RWU
    water['cache_error']=water.RWU-water.cached_RWU
    water['cg_RATE_SW']=rate.SW
    water['cg_INTEGR_SW']=cg_u.SW
    water['SW_INTEGR_minus_RATE']=water.cg_INTEGR_SW-water.cg_RATE_SW
    water['root_extraction_cm_from_SWDELTX']=-water.SWDELTX*water.DLAYR
    water['extraction_error_cm']=water.RWU-water.root_extraction_cm_from_SWDELTX
    water.to_csv(out/'layer_water_snapshots.csv',index=True)
    sw=scalar('spam_rate')
    cache_s=scalar('cg_cache')
    sumrwu=water.RWU.groupby(['run','yrdoy']).sum()
    hydro=pd.DataFrame({'sum_RWU_cm':sumrwu,'TRWU_cm':sw.TRWU,'EP_mm':sw.EP,
                        'cached_EP_mm':cache_s.EP})
    hydro['sum_RWU_minus_TRWU_cm']=hydro.sum_RWU_cm-hydro.TRWU_cm
    hydro['sum_RWU_minus_EP_div10_cm']=hydro.sum_RWU_cm-hydro.EP_mm/10
    hydro.to_csv(out/'daily_water_checks.csv',index=True)

    b=scalar('cg_begin')
    e=scalar('cg_end')
    seed=scalar('cg_seed')
    u=scalar('cg_uptake')
    ncost=scalar('cg_N_cost')
    mob=scalar('cg_mobil')
    fix=scalar('cg_fix')
    repro=scalar('cg_repro')
    bv=scalar('cg_before_veg')
    veg=scalar('cg_veg')
    cash=scalar('cg_ledger_end')
    demand=scalar('cg_demand')
    source=scalar('cg_source_next')
    losses=scalar('grow_losses')
    raw_rates=scalar('grow_N_rates_raw')
    grow_before=scalar('grow_N_before')
    veg_potential=scalar('veg_potential')
    veg_after_N=scalar('veg_after_N')
    budget=pd.DataFrame(index=e.index)
    budget['plant_N_begin_g_m2']=b[ORG].sum(axis=1)+b.SDNPL
    budget['plant_N_end_g_m2']=e[ORG].sum(axis=1)+e.SDNPL
    budget['organ_N_out_g_m2']=e[OFF].sum(axis=1)-b[OFF].sum(axis=1)
    budget['TNLEAK_daily_g_m2']=e.TNLEAK-b.TNLEAK
    budget['uptake_g_m2']=u.TRNU
    budget['NFIX_g_m2']=fix.NFIXN
    budget['seed_release_g_m2']=seed.NAVL
    budget['seed_threshold_discard_g_m2']=b.SDNPL-seed.SDNPL-seed.NAVL
    budget['NGR_veg_g_m2']=veg[['NGRLF','NGRST','NGRRT']].sum(axis=1)
    budget['NGR_repro_g_m2']=repro[['NGRSD','NGRSH']].sum(axis=1)
    budget['NAD_nominal_g_m2']=veg[['NADLF','NADST','NADRT']].sum(axis=1)
    retained=0
    for rate_name,off,remobil,growth in [('NLDOT','NLOFF','NRUSLF','NGRLF'),
                                       ('NSDOT','NSOFF','NRUSST','NGRST'),
                                       ('NRDOT','NROFF','NRUSRT','NGRRT')]:
        retained=retained+raw_rates[rate_name]+losses[off]+mob[remobil]-veg[growth]
    budget['NAD_retained_from_GROW_g_m2']=retained
    budget['NAD_retention_gap_g_m2']=budget.NAD_nominal_g_m2-retained
    dot_names=['NLDOT','NSDOT','NRDOT','NSHDOT','NSDDOT']
    budget['organ_N_negative_rate_clamp_adjustment_g_m2']=(losses[dot_names].sum(axis=1)-raw_rates[dot_names].sum(axis=1))
    budget['NMINEA_g_m2']=mob.NMINEA
    budget['NRUS_sum_g_m2']=mob[['NRUSLF','NRUSST','NRUSRT','NRUSSH']].sum(axis=1)
    budget['NAVL_end_g_m2']=cash.NAVL
    budget['organic_allocation_pool_residual_g_m2']=(seed.NAVL+u.TRNU+fix.NFIXN+mob.NMINEA-
        budget.NGR_veg_g_m2-budget.NGR_repro_g_m2-budget.NAD_nominal_g_m2-cash.NAVL)
    budget['plant_raw_N_residual_g_m2']=(budget.plant_N_end_g_m2-budget.plant_N_begin_g_m2+
        budget.organ_N_out_g_m2+budget.TNLEAK_daily_g_m2-u.TRNU-fix.NFIXN)
    budget['plant_explained_N_residual_g_m2']=(budget.plant_raw_N_residual_g_m2+
        budget.NAD_retention_gap_g_m2+budget.seed_threshold_discard_g_m2-
        (mob.NMINEA-budget.NRUS_sum_g_m2)-(budget.TNLEAK_daily_g_m2-cash.NAVL)-
        budget.organ_N_negative_rate_clamp_adjustment_g_m2)

    # Costs recorded before and after each native assignment; no invented demand.
    budget['PG_g_CH2O_m2']=b.PG
    budget['CMINEP_virtual_g_CH2O_m2']=demand.CMINEP
    budget['CMINEA_actual_g_CH2O_m2']=veg.CMINEA
    available=b.PG+demand.CMINEP
    main_actual=np.minimum(available,demand.MAINR)
    damage_C=np.maximum(0,available-main_actual-demand.PGAVL)
    rsp_requested=ncost.RSPNO3+ncost.RSPNH4
    rsp_actual=u.PGAVL-ncost.PGAVL
    mobil_actual=ncost.PGAVL-mob.PGAVL
    fix_actual=mob.PGAVL-fix.PGAVL
    repro_actual=fix.PGAVL-repro.PGAVL
    growth_C=veg.AGRVG*veg[['WLDOTN','WSDOTN','WRDOTN']].sum(axis=1)
    storage_C=(veg.CADLF+veg.CADST)*veg.PCH2O
    budget['N_assim_cost_requested_g_CH2O_m2']=rsp_requested
    budget['N_assim_cost_debited_g_CH2O_m2']=rsp_actual
    budget['N_assim_cost_unpaid_g_CH2O_m2']=np.maximum(0,rsp_requested-u.PGAVL)
    budget['N_mobil_cost_requested_g_CH2O_m2']=mob.NMINEA/0.16*mob.RPRO
    budget['N_mobil_cost_debited_g_CH2O_m2']=mobil_actual
    budget['repro_growth_cost_g_CH2O_m2']=repro_actual
    budget['veg_growth_cost_g_CH2O_m2']=growth_C
    budget['veg_growth_cost_before_N_g_CH2O_m2']=veg_potential.AGRVG*veg_potential.VGRDEM
    budget['veg_growth_cost_overrun_after_N_g_CH2O_m2']=np.maximum(0,growth_C-bv.PGAVL)
    budget['veg_NRATIO']=veg_after_N.NRATIO
    budget['reserve_deposition_cost_g_CH2O_m2']=storage_C
    budget['CSAVEV_internal_g_CH2O_m2']=bv.CSAVEV
    budget['PGAVL_native_end_g_CH2O_m2']=cash.PGAVL
    budget['C_available_ledger_residual_g_CH2O_m2']=(demand.PGAVL-rsp_actual-mobil_actual-
        fix_actual-repro_actual-bv.CSAVEV-growth_C-storage_C-cash.PGAVL)
    budget['C_actual_allocation_residual_g_CH2O_m2']=(b.PG+veg.CMINEA-main_actual-damage_C-
        rsp_actual-mobil_actual-fix_actual-repro_actual-growth_C-storage_C)
    budget['C_after_growth_overrun_accounted_g_CH2O_m2']=(budget.C_actual_allocation_residual_g_CH2O_m2+
        budget.veg_growth_cost_overrun_after_N_g_CH2O_m2)
    budget['RPROAV']=source.RPROAV
    denominator=source.TRNU+source.NFIXN+source.NMINEA
    expected=((source.RSPNO3+source.RSPNH4)*0.16+source.NFIXN*source.RFIXN+
              source.NMINEA*source.RPRO)/denominator
    expected=expected.where(denominator>1.e-4,(u.RNO3C+u.RNH4C)/2)
    budget['RPROAV_formula_residual']=source.RPROAV-expected
    budget['RPROAV_denominator_g_m2']=denominator
    budget['RPROAV_demand_uses_previous'] = demand.RPROAV-source.RPROAV.groupby('run').shift()

    # Date-tagged pending ledger. Official soil WTNUP includes only already debited U.
    soilend=scalar('soil_integr_end',4)
    daily_u=u.TRNU.reindex(soilend.index,fill_value=0)
    plantcum=e.WTNUP.reindex(soilend.index).groupby('run').ffill().fillna(0)
    pending=pd.DataFrame({'soil_cumulative_uptake_g_m2':soilend.WTNUP,
                          'plant_cumulative_uptake_g_m2':plantcum,
                          'pending_uptake_g_m2':daily_u})
    pending['cumulative_gap_minus_pending_g_m2']=plantcum-soilend.WTNUP-daily_u
    pending.to_csv(out/'daily_pending_ledger.csv',index=True)
    soil_pre=layer('soil_integr_before',4)
    soil_post=layer('soil_integr_end',4)
    soil_inventory=soil_post[['SNO3','SNH4','UREA']].sum(axis=1).groupby(['run','yrdoy']).sum()/10
    soil_process=soil_pre[['DLTSNO3','DLTSNH4','DLTUREA']].sum(axis=1).groupby(['run','yrdoy']).sum()/10
    init_soil=layer('soil_integr_end',2)[['SNO3','SNH4','UREA']].sum(axis=1).groupby('run').sum()/10
    previous=soil_inventory.groupby('run').shift()
    for run in init_soil.index:
        first=soil_inventory.loc[run].index[0]
        previous.loc[(run,first)]=init_soil.loc[run]
    previous_pending=daily_u.groupby('run').shift().fillna(0)
    soil_change=soil_inventory-previous
    budget['soil_NO3_NH4_urea_end_g_m2']=soil_inventory
    budget['pending_uptake_g_m2']=daily_u
    budget['soil_native_process_increment_g_m2']=soil_process
    # Boundary: soil inorganic pools + live plant including remaining seed.
    # Organic soil is OUTSIDE this diagnostic boundary. DLTS is the native net
    # exchange/processing input, not an independent all-soil external N audit.
    budget['combined_N_residual_without_pending_g_m2']=(soil_change+
        budget.plant_N_end_g_m2-budget.plant_N_begin_g_m2+
        budget.organ_N_out_g_m2+budget.TNLEAK_daily_g_m2-fix.NFIXN-soil_process)
    budget['combined_pending_corrected_N_residual_g_m2']=(
        budget.combined_N_residual_without_pending_g_m2-daily_u+previous_pending)
    budget['combined_after_known_N_gaps_g_m2']=(budget.combined_pending_corrected_N_residual_g_m2+
        budget.NAD_retention_gap_g_m2+budget.seed_threshold_discard_g_m2-
        (mob.NMINEA-budget.NRUS_sum_g_m2)-(budget.TNLEAK_daily_g_m2-cash.NAVL)-
        budget.organ_N_negative_rate_clamp_adjustment_g_m2)
    budget['harvest_shell_N_g_m2']=losses.HSHELWT*grow_before.PCNSH/100
    budget['harvest_seed_N_actual_g_m2']=losses.HSDWT*grow_before.PCNSD/100
    budget['harvest_seed_N_report_increment_g_m2']=losses.NHSDWT-grow_before.NHSDWT
    budget['harvest_seed_N_reporting_error_g_m2']=(budget.harvest_seed_N_report_increment_g_m2-
                                                       budget.harvest_seed_N_actual_g_m2)
    budget.to_csv(out/'daily_N_C_budget.csv',index=True)

    crin=scalar('century_residue_input')
    crbefore=scalar('century_residue_before')
    crafter=scalar('century_residue_after')
    residue=pd.DataFrame({'surface_N_received_kg_ha':crin.surface_N,
                          'root_N_received_kg_ha':crin.root_N,
                          'DM_received_kg_ha':crin.residue_DM,
                          'SENESSUMN_increment_kg_ha':crafter.SENESSUMN-crbefore.SENESSUMN})
    residue['N_received_kg_ha']=residue.surface_N_received_kg_ha+residue.root_N_received_kg_ha
    residue['N_accepted_increment_error_kg_ha']=residue.SENESSUMN_increment_kg_ha-residue.N_received_kg_ha
    # Connect yesterday's harvested shell N to today's residue consumer.
    harvested=budget.harvest_shell_N_g_m2.mul(10).reset_index()
    harvested['yrdoy']=harvested.yrdoy.map(tomorrow)
    harvested=harvested.set_index(['run','yrdoy']).iloc[:,0]
    residue['previous_harvest_shell_N_kg_ha']=harvested
    produced_surface=scalar('grow_residue').surface_N.reset_index()
    produced_surface['yrdoy']=produced_surface.yrdoy.map(tomorrow)
    produced_surface=produced_surface.set_index(['run','yrdoy']).surface_N
    residue['previous_GROW_surface_N_kg_ha']=produced_surface
    residue['surface_payload_error_kg_ha']=(residue.surface_N_received_kg_ha-
                                           residue.previous_GROW_surface_N_kg_ha)
    residue.to_csv(out/'residue_consumer_ledger.csv',index=True)

    # Individual PGLFEQ calls, including both sunlit/shaded and hourly instances.
    leaf=d[d.event=='leaf_capacity'].copy()
    leaf['sample']=leaf.key.eq('RNITP').cumsum()
    lf=leaf.pivot(index=['run','yrdoy','sample'],columns='key',values='value').dropna(axis=1,how='all')
    lf.columns=[str(x) for x in lf.columns]
    lf.to_csv(out/'leaf_capacity_samples.csv',index=True)
    ep=scalar('etphot_rate')
    photo=ep.join(b[['RNITP']].rename(columns={'RNITP':'cg_begin_RNITP'}),how='left')
    photo['RNITP_cache_minus_cg_begin']=photo.RNITP-photo.cg_begin_RNITP
    photo.to_csv(out/'daily_L_photosynthesis_chain.csv',index=True)

    # Run labels read explicitly from frozen TMX; no water/N class inferred.
    tmx=(root/'trace_on/XXQL2601.TMX').read_text(errors='replace')
    section=tmx.split('*TREATMENTS',1)[1].split('*CULTIVARS',1)[0]
    labels={int(line.split()[0]):line.split()[4] for line in section.splitlines()
            if line.strip() and line.split()[0].isdigit()}
    per=[]
    for run,g in budget.groupby('run'):
        pend=pending.loc[run].iloc[-1]
        lfrun=lf.loc[run]
        per.append({'run':run,'treatment_label':labels[run],'growth_days':len(g),
            'uptake_total_kg_ha':float(g.uptake_g_m2.sum()*10),
            'pending_last_day_kg_ha':float(pend.pending_uptake_g_m2*10),
            'TNLEAK_total_kg_ha':float(g.TNLEAK_daily_g_m2.sum()*10),
            'plant_raw_residual_total_kg_ha':float(g.plant_raw_N_residual_g_m2.sum()*10),
            'NAD_retention_gap_total_kg_ha':float(g.NAD_retention_gap_g_m2.sum()*10),
            'organ_N_clamp_adjustment_total_kg_ha':float(g.organ_N_negative_rate_clamp_adjustment_g_m2.sum()*10),
            'seed_threshold_discard_total_kg_ha':float(g.seed_threshold_discard_g_m2.sum()*10),
            'explained_plant_residual_max_abs_g_m2':float(g.plant_explained_N_residual_g_m2.abs().max()),
            'harvest_shell_N_total_kg_ha':float(g.harvest_shell_N_g_m2.sum()*10),
            'harvest_shell_N_already_in_residue_consumer_kg_ha':float(residue.loc[run].previous_harvest_shell_N_kg_ha.sum()),
            'harvest_seed_N_reporting_error_total_kg_ha':float(g.harvest_seed_N_reporting_error_g_m2.sum()*10),
            'C_allocation_residual_max_abs_g_CH2O_m2':float(g.C_actual_allocation_residual_g_CH2O_m2.abs().max()),
            'C_growth_overrun_days':int((g.veg_growth_cost_overrun_after_N_g_CH2O_m2>1.e-5).sum()),
            'C_growth_overrun_total_g_CH2O_m2':float(g.veg_growth_cost_overrun_after_N_g_CH2O_m2.sum()),
            'leaf_AGEMXL_min':float(lfrun.AGEMXL.min()),'leaf_AGEMXL_max':float(lfrun.AGEMXL.max())})
    runs=pd.DataFrame(per)
    runs.to_csv(out/'per_treatment_summary.csv',index=False)

    reset=scalar('cg_reset')
    reset_layers=layer('cg_reset')
    checks={
        'finite_trace_values':True,
        'trace_sequence_unique_contiguous':True,
        'twelve_treatments':len(runs)==12,
        'cached_RWU_exact_when_plant_called':bool(water.cache_error.dropna().eq(0).all()),
        'cached_EP_exact_when_plant_called':bool(hydro.EP_mm.loc[hydro.cached_EP_mm.notna()].eq(hydro.cached_EP_mm.dropna()).all()),
        'no_plant_cache_only_zero_water_days':bool(hydro.loc[hydro.cached_EP_mm.isna(),['sum_RWU_cm','EP_mm']].eq(0).all().all()),
        'uptake_previous_day_payload_exact':bool(lag[['NO3_payload_error_kg_ha','NH4_payload_error_kg_ha']].eq(0).all().all()),
        'soil_native_float32_subtraction_exact':bool(lag[['SNO3_native_subtraction_error','SNH4_native_subtraction_error']].eq(0).all().all()),
        'RWU_EP_sum_float32_consistent':bool((hydro.sum_RWU_minus_EP_div10_cm.abs()<=32*EPS32*np.maximum(1,hydro.sum_RWU_cm.abs())).all()),
        'reset_WTNUP_TNLEAK_zero':bool(reset[['WTNUP','TNLEAK']].eq(0).all().all()),
        'reset_species_uptake_zero':bool(reset_layers[['UNO3','UNH4']].eq(0).all().all()),
        'pending_cumulative_gap_float32_consistent':bool((pending.cumulative_gap_minus_pending_g_m2.abs()<=
            64*EPS32*np.maximum(1,pending.plant_cumulative_uptake_g_m2.abs())).all()),
        'RPROAV_previous_day_input_exact':bool(budget.RPROAV_demand_uses_previous.dropna().eq(0).all()),
        'RPROAV_weighted_formula_float32_consistent':bool((budget.RPROAV_formula_residual.abs()<=
            32*EPS32*np.maximum(1,budget.RPROAV.abs())).all()),
        'leaf_RNITP_cache_matches_plant_begin':bool(photo.RNITP_cache_minus_cg_begin.dropna().eq(0).all()),
        'GROW_to_CENTURY_surface_residue_payload_exact':bool(residue.surface_payload_error_kg_ha.dropna().eq(0).all()),
        'C_native_cash_ledger_float32_consistent':bool((budget.C_available_ledger_residual_g_CH2O_m2.abs()<=
            64*EPS32*np.maximum(1,budget.PG_g_CH2O_m2.abs()+budget.CMINEA_actual_g_CH2O_m2.abs())).all()),
        'C_after_identified_growth_overrun_float32_consistent':bool((budget.C_after_growth_overrun_accounted_g_CH2O_m2.abs()<=
            64*EPS32*np.maximum(1,budget.PG_g_CH2O_m2.abs()+budget.CMINEA_actual_g_CH2O_m2.abs())).all()),
    }
    metrics={
        'trace_rows':len(d),'leaf_capacity_calls':len(lf),'growth_days':len(budget),
        'soil_layer_debit_records':len(lag),'daily_water_records':len(hydro),
        'SW_RATE_INTEGR_max_abs_cm3_cm3':float(water.SW_INTEGR_minus_RATE.abs().max()),
        'RWU_EP_div10_max_abs_cm':float(hydro.sum_RWU_minus_EP_div10_cm.abs().max()),
        'pending_cumulative_gap_max_abs_g_m2':float(pending.cumulative_gap_minus_pending_g_m2.abs().max()),
        'RPROAV_formula_max_abs':float(budget.RPROAV_formula_residual.abs().max()),
        'N_allocation_pool_residual_max_abs_g_m2':float(budget.organic_allocation_pool_residual_g_m2.abs().max()),
        'plant_raw_N_residual_max_abs_g_m2':float(budget.plant_raw_N_residual_g_m2.abs().max()),
        'plant_explained_N_residual_max_abs_g_m2':float(budget.plant_explained_N_residual_g_m2.abs().max()),
        'combined_after_known_N_gaps_max_abs_g_m2':float(budget.combined_after_known_N_gaps_g_m2.abs().max()),
        'C_actual_allocation_residual_max_abs_g_CH2O_m2':float(budget.C_actual_allocation_residual_g_CH2O_m2.abs().max()),
        'C_after_growth_overrun_accounted_max_abs_g_CH2O_m2':float(budget.C_after_growth_overrun_accounted_g_CH2O_m2.abs().max()),
        'C_growth_overrun_days':int((budget.veg_growth_cost_overrun_after_N_g_CH2O_m2>1.e-5).sum()),
        'C_growth_overrun_total_g_CH2O_m2':float(budget.veg_growth_cost_overrun_after_N_g_CH2O_m2.sum()),
        'N_negative_rate_clamp_days':int((budget.organ_N_negative_rate_clamp_adjustment_g_m2>1.e-6).sum()),
        'native_PGAVL_end_min_g_CH2O_m2':float(budget.PGAVL_native_end_g_CH2O_m2.min()),
        'N_assimilation_cost_unpaid_max_g_CH2O_m2':float(budget.N_assim_cost_unpaid_g_CH2O_m2.max()),
        'N_leak_positive_days':int((budget.TNLEAK_daily_g_m2>0).sum()),
        'residue_consumer_increment_max_abs_error_kg_ha':float(residue.N_accepted_increment_error_kg_ha.abs().max()),
        'plant_raw_N_budget_is_closed':bool((budget.plant_raw_N_residual_g_m2.abs()<=
            32*EPS32*np.maximum(1,budget.plant_N_begin_g_m2.abs()+budget.plant_N_end_g_m2.abs())).all()),
        'C_raw_actual_allocation_is_closed':bool((budget.C_actual_allocation_residual_g_CH2O_m2.abs()<=
            64*EPS32*np.maximum(1,budget.PG_g_CH2O_m2.abs()+budget.CMINEA_actual_g_CH2O_m2.abs())).all()),
    }
    result={'trace_implementation_checks':checks,'trace_implementation_passed':all(checks.values()),
        'budget_audit_status':'native_N_retention_C_growth_overrun_and_harvest_residue_issues_found_not_fixed',
        'v15_mechanisms_adopted':False,'metrics':metrics,'per_treatment':per,
        'scope_note':'Combined inventory includes inorganic soil and plant; soil organic matter outside boundary; native DLTS used as net exchange. Not an independent all-soil C/N proof.',
        'float_tolerance_note':'Only instrumentation roundoff checks use 32/64 float32 eps scaled by stock or flux magnitude. Raw native N defects are reported separately, not declared closed.',
        'source_trace_sha256':digest(trace)}
    (out/'audit_summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'checks':checks,'metrics':metrics},ensure_ascii=False,indent=2))
    if not result['trace_implementation_passed']:
        raise SystemExit('Some trace implementation checks failed; inspect audit_summary.json')


if __name__=='__main__':
    main()
