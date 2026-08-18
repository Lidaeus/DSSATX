# 观测文件已退役

本目录原有的 `XXQL2502.TMA` 和 `XXQL2502.TMT` 生成于 25FA 生长测定数据补齐之前。
其中 FileT 仅 6,481 bytes，缺少后续补入的生长测定日期和处理观测；FileA 的终点
LAI、叶干重和茎干重也与补齐后的权威数据不一致。两文件已于 2026-07-30 删除，
不得作为率定或验证观测来源。

本目录的 `XXQL2502.TMX` 仅作为历史 PAGE=25、SPRL=-99 管理修订的中间证据保留。
当前 25FA FileA/FileT 唯一真值位于：

`data/user/experiments/xxql2502_special_defaultn_v1_20260730/`

其权威哈希见：

`configs/runs/eggplant_e02_joint62_three_season_defaultn_nresponse_v2_20260730.json`
