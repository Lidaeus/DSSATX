# Boundary shift audit — 2026-09-24

Derived from `eggplant_full_gen_corrected_13trt_sasc090_icns1_20260923.csv`. The four parameters were at or within 1% of the same-sided boundary in both iterations 4 and 5. Each interval was translated outward by 5% of its original width; width and init were kept unchanged. The translated ranges remain within DSSAT physical bounds and contain the init value.

| Parameter | Old range | Direction | Translation | New range |
|---|---:|---|---:|---:|
| cmobmx | [0.01, 0.2] | lower | -0.0095 | [0.0005, 0.1905] |
| fl-sd | [8, 25] | upper | +0.85 | [8.85, 25.85] |
| rwdth | [0.7, 2.2] | lower | -0.075 | [0.625, 2.125] |
| optstp_fs | [0.002, 0.0038] | upper | +9e-05 | [0.00209, 0.00389] |

Fixed calibration settings carried forward unchanged: `SASC_RATIO=0.90`, `ICNS_25SP=1.0`, `ICNS_26SP=1.0`. Input bundle carried forward from the corrected 13-treatment run.
