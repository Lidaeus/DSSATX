[ignoring loop detection]
# ECO 参数对比

以下是用户定制的茄子 ECO 文件与原始番茄 ECO 文件的 diff 结果（`-` 为原始，`+` 为修改后）：

```diff
45,54c45,48
< @ECO#  ECONAME.......... MG TM THVAR PL-EM EM-V1 V1-JU JU-R0  PM06  PM09 LNGSH R7-R8 FL-VS TRIFL RWDTH RHGHT R1PPO OPTBI SLOBI XMAGE
< !                                  1     2     3     4     5     6     7     8     9    10    11    12    13    14    15    16    17
< !Calibration              N  N     N     N     N     N     N     G     G     G     N     G     G     G     G     N     N     N     G
< ! 
< ! 999991 MINIMA             .  .   0.0   6.0  22.0   0.0  05.0  0.45  0.65  37.0   0.0 20.00  0.40   0.9   0.9  .000  00.0  .000  15.0
< ! 999992 MAXIMA             .  .   0.0   6.0  22.0   0.0  05.0  0.65  0.85  41.0   0.0 30.00  0.50   1.0   1.0  .000  00.0  .000  30.0
< ! 
< ! TM0001 SEMI-DETERMINATE  01 01   0.0   6.0  22.0   0.0  05.0   .55  0.75  39.0   0.0 24.50  0.45   1.0   1.0  .000  00.0  .000  10.0
< ! DFAULT DEFAULT TYPE      01 01   0.0   6.0  22.0   0.0  05.0   .55  0.75  39.0   0.0 24.50  0.45   1.0   1.0  .000  00.0  .000  10.0
---
> @ECO#  ECONAME.......... MG TM THVAR PL-EM EM-V1 V1-JU JU-R0  PM06  PM09 LNGSH R7-R8 FL-VS TRIFL RWDTH RHGHT R1PPO OPTBI SLOBI XMAGE XFPHT XFINT
> !                                  1     2     3     4     5     6     7     8     9    10    11    12    13    14    15    16    17    18    19
> !Coeffient #                             1     2     3     4     5     6     7     8     9    10    11    12    13    14    15    16    17    18    19
> !Calibration                             P     P     P     P     P     P     P     G     G     G     G     G     P     G     P     G     N     N     N
> 
> TM0001 SEMI-DETERMINATE  01 00   0.0   8.4  39.9   0.0   2.8   0.6  0.85  10.0   0.0 100.0  0.33   1.5   1.2  0.00  0.00  0.00   9.7  23.0  0.30
> DFAULT DEFAULT TYPE      01 01   0.0   6.0  22.0   0.0  05.0   .55  0.85  10.0   0.0 100.0  0.45   1.0   1.0  .000  00.0  .000  10.0  23.0  0.30
```
